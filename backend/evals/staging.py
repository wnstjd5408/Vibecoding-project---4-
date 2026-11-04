"""Private staging orchestration. Caller identity is checked by the HTTP layer."""
from dataclasses import asdict
from decimal import Decimal
from tempfile import TemporaryDirectory

from .dataset import _digest, freeze_dataset
from .live import calibration, request_for, MODEL
from .luna_budget import POLICY, reservation
from .runner import RunConfig
from .schema import Case, DatasetError

SLOTS = ["D01", "D02", "D03"]


def prepare_bundle(body):
    try:
        if set(body) != {"cases", "manifest", "config"}:
            raise ValueError()
        cases = [Case.from_dict(row) for row in body["cases"]]
        config = RunConfig(**body["config"])
        config.validate()
        manifest = body["manifest"]
        fresh = freeze_dataset(cases, manifest["reviewer"])
        if any(fresh[k] != manifest[k] for k in ("dataset_version", "case_hashes")):
            raise ValueError()
        if (config.model_id != MODEL or config.split != "dev" or config.repetitions != 1
                or config.max_calls != 3 or config.tokenizer_version != POLICY):
            raise ValueError()
        lookup = {c.case_id: c for c in cases if c.split == "dev"}
        requests = {slot: request_for(lookup[slot], config) for slot in SLOTS}
        amount = reservation(config, requests)
        if amount * 3 > Decimal(config.budget):
            raise ValueError()
        identity = {"config": asdict(config), "dataset_version": fresh["dataset_version"],
                    "requests_hash": _digest(requests)}
        return cases, manifest, config, identity, amount
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
        raise DatasetError("live: invalid_bundle") from None


def checked_state(bundle, ledger):
    _, _, config, identity, amount = bundle
    approval, attempts = ledger.snapshot()
    if (approval.get("identity_hash") != _digest(identity)
            or approval.get("run_id") != config.run_id
            or approval.get("allowed_slots") != SLOTS
            or Decimal(str(approval.get("per_call"))) != amount
            or Decimal(str(approval.get("budget"))) != Decimal(config.budget)):
        raise DatasetError("live: approval_mismatch")
    slots = {slot: {"status": "pending"} for slot in SLOTS}
    for row in attempts:
        slot = row.get("slot")
        if slot not in slots or slots[slot]["status"] != "pending":
            raise DatasetError("live: ledger_inconsistent")
        result = row.get("result")
        slots[slot] = result if isinstance(result, dict) else {"status": row.get("status")}
        if slots[slot].get("status") != row.get("status"):
            raise DatasetError("live: ledger_inconsistent")
    if approval.get("attempts") != len(attempts):
        raise DatasetError("live: ledger_inconsistent")
    return {"identity": identity, "mode": "live", "provider_calls": len(attempts),
            "slots": slots}, approval


def next_slot(state, approval):
    # Failed/truncated/uncertain results require inspection, never automatic continuation.
    if approval.get("halted") is not False or any(
            r["status"] not in ("ok", "pending") for r in state["slots"].values()):
        raise DatasetError("live: manual_recovery_required")
    return next((s for s in SLOTS if state["slots"][s]["status"] == "pending"), None)


def execute_slot(bundle, ledger, slot, transport):
    cases, manifest, config, _, _ = bundle
    state, approval = checked_state(bundle, ledger)
    if slot != next_slot(state, approval) or slot not in SLOTS:
        raise DatasetError("live: slot_not_pending")
    # A fresh serverless filesystem never grants a new budget: reserve RPC is authoritative.
    with TemporaryDirectory(prefix="cs-eval-") as directory:
        calibration(cases, manifest, config, directory, SLOTS, transport,
                    ledger=ledger, only_slot=slot)
    return checked_state(bundle, ledger)[0]


if __name__ == "__main__":
    # Offline request packaging only. Does not import authentication or construct a client.
    import argparse
    import json
    from pathlib import Path
    from .dataset import load_cases
    from .runner import private_path

    parser = argparse.ArgumentParser(description="Package a private staging request without network calls")
    for name in ("dataset", "manifest", "config", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    try:
        body = {"cases": [asdict(c) for c in load_cases(args.dataset)],
                "manifest": json.loads(args.manifest.read_text(encoding="utf-8-sig")),
                "config": json.loads(args.config.read_text(encoding="utf-8-sig"))}
        bundle = prepare_bundle(body)
        with private_path(args.output).open("x", encoding="utf-8") as stream:
            json.dump(body, stream, ensure_ascii=False, allow_nan=False)
        print("identity_hash=" + _digest(bundle[3]))
    except (OSError, ValueError, TypeError):
        parser.exit(1, "staging: invalid input or private output unavailable\n")
