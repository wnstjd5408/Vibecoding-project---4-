"""Small, resumable Bedrock calibration. No CLI until a token bound is verified."""
import json
import os
import time
from dataclasses import asdict
from decimal import Decimal

from botocore.config import Config

from .dataset import _digest, freeze_dataset
from .runner import atomic, prepare, private_path, price
from .schema import DatasetError
from .live_output import OUTPUT_RULES, validate_output

MODEL = "global.openai.gpt-6-luna"
SDK_CONFIG = Config(retries={"total_max_attempts": 1, "mode": "standard"},
                    connect_timeout=10, read_timeout=60)


def input_bound(request):
    # CountTokens is unsupported for this model. Never substitute len/tiktoken guesses.
    raise DatasetError("live: verified_token_bound_unavailable")


class BedrockTransport:
    def __init__(self, client):
        if client.meta.config.retries.get("total_max_attempts") != 1:
            raise DatasetError("live: automatic_retries_forbidden")
        self.client = client

    def __call__(self, request):
        return self.client.converse(**request)


def request_for(case, config):
    data = prepare(case)
    return {"modelId": MODEL, "system": [{"text": OUTPUT_RULES}],
            "messages": [{"role": "user", "content": [{"text": json.dumps(
                data["messages"][0]["content"], ensure_ascii=False)}]}],
            "inferenceConfig": {"maxTokens": config.max_output},
            "additionalModelRequestFields": {"reasoning": {"effort": "none"}}}


def calibration(cases, manifest, config, directory, case_ids, transport):
    """One approval ledger directory must be reused; never retry uncertain attempts.

    Token bound is deliberately unavailable until a reviewed implementation exists.
    Tests replace it only with a synthetic counter and block network access.
    """
    config.validate()
    if (config.split != "dev" or config.repetitions != 1 or config.max_calls > 3
            or config.model_id != MODEL or not 1 <= len(case_ids) <= config.max_calls
            or len(set(case_ids)) != len(case_ids)):
        raise DatasetError("live: calibration_scope")
    fresh = freeze_dataset(cases, manifest.get("reviewer", ""))
    if any(fresh[k] != manifest.get(k) for k in ("dataset_version", "case_hashes")):
        raise DatasetError("live: manifest_mismatch")
    lookup = {c.case_id: c for c in cases if c.split == "dev"}
    if any(k not in lookup for k in case_ids):
        raise DatasetError("live: development_only")
    requests = {k: request_for(lookup[k], config) for k in case_ids}
    for request in requests.values():
        count = input_bound(request)
        if type(count) is not int or not 0 <= count <= config.max_input:
            raise DatasetError("live: input_limit")
    reserve = price(config, config.max_input, config.max_output)
    if reserve * len(requests) > Decimal(config.budget) or reserve <= 0:
        raise DatasetError("live: budget_exceeded")
    directory = private_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise DatasetError("live: locked_manual_recovery_required") from None
    try:
        path = directory / "state.json"
        identity = {"config": asdict(config), "dataset_version": fresh["dataset_version"],
                    "requests_hash": _digest(requests)}
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            if state["identity"] != identity or list(state["slots"]) != list(requests):
                raise DatasetError("live: resume_mismatch")
        else:
            state = {"identity": identity, "mode": "live", "provider_calls": 0,
                     "slots": {k: {"status": "pending"} for k in requests}}
        if any(r["status"] in ("started", "unknown", "over_limit") for r in state["slots"].values()):
            raise DatasetError("live: manual_recovery_required")
        for key, request in requests.items():
            if state["slots"][key]["status"] != "pending":
                continue
            if state["provider_calls"] >= config.max_calls:
                raise DatasetError("live: call_limit")
            row = {"status": "started", "reserved_cost": str(reserve),
                   "request_hash": _digest(request)}
            state["slots"][key] = row
            state["provider_calls"] += 1
            atomic(path, state)
            start = time.monotonic()
            try:
                response = transport(request)
            except Exception:
                # Do not log exception strings, headers or credentials. No automatic retry.
                response = {}
            row.update(status="unknown", elapsed_ms=round((time.monotonic() - start) * 1000))
            if not isinstance(response, dict):
                response = {}
            usage = response.get("usage")
            row["usage"] = usage  # Preserve even over-limit usage and truncated results.
            row["stop_reason"] = response.get("stopReason")
            row["output"] = response.get("output")
            if isinstance(usage, dict):
                fields = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheWriteInputTokens")
                values = [usage.get(k, 0 if k.startswith("cache") else None) for k in fields]
                if all(type(v) is int and v >= 0 for v in values):
                    inp, out, read, write = values
                    # Conservative charge: cache reads at full input rate; writes at 1.25x.
                    cost = price(config, inp + read, out) + Decimal(config.input_price) * write * Decimal("1.25") / 1000000
                    row.update(cost_upper_estimate=str(cost), input_tokens=inp, output_tokens=out)
                    output = response.get("output")
                    message = output.get("message") if isinstance(output, dict) else None
                    content = message.get("content", []) if isinstance(message, dict) else []
                    if not isinstance(content, list):
                        content = []
                    text = "".join(b.get("text", "") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
                    row.update(text=text, status="error")
                    if row["stop_reason"] == "end_turn":
                        try:
                            checked = validate_output(text, prepare(lookup[key])["messages"][0]["content"]["sources"])
                            row.update(text=checked["text"], structured_output=checked, status="ok")
                        except DatasetError as error:
                            row["error_code"] = str(error)
                    if inp + read + write > config.max_input or out > config.max_output or cost > reserve:
                        row["status"] = "over_limit"
            atomic(path, state)
            if row["status"] in ("unknown", "over_limit"):
                break
        return state
    finally:
        os.close(fd)
        lock.unlink()
