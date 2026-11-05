"""Human review bindings for real wiki responses, separate from mock results."""
from types import SimpleNamespace

from .dataset import _digest
from .schema import DatasetError
from .scoring import RUBRIC, metrics, verdict
from .wiki_dev import manifest
from .wiki_live import make_plan


def _check(cases, state):
    if state.get("integrity_hash") != _digest({k: v for k, v in state.items() if k != "integrity_hash"}):
        raise DatasetError("wiki_review: state_integrity")
    if state.get("mode") != "live" or state["identity"]["manifest"] != manifest(cases):
        raise DatasetError("wiki_review: live_dataset_required")
    if state["identity"] != make_plan(cases)["identity"]:
        raise DatasetError("wiki_review: prompt_or_request_mismatch")
    expected = {c["id"] + ":U" for c in cases}
    if set(state["slots"]) != expected or not state.get("approval_hash"):
        raise DatasetError("wiki_review: run_identity")
    attempts = sum(r.get("status") != "pending" for r in state["slots"].values())
    if state.get("attempts") != attempts or state.get("provider_calls") != attempts:
        raise DatasetError("wiki_review: attempt_mismatch")
    if any(r.get("status") not in ("pending", "started", "unknown", "error", "over_limit", "ok")
           for r in state["slots"].values()):
        raise DatasetError("wiki_review: invalid_status")


def templates(cases, state):
    _check(cases, state)
    return [{
        "slot": c["id"] + ":U",
        "output_hash": _digest(state["slots"][c["id"] + ":U"]),
        "identity_hash": _digest(state["identity"]),
        "approval_hash": state["approval_hash"],
        "rubric_version": "human-v1", "reviewer": "", "evidence": "",
        "claims": [], "concepts": [None] * len(c["required_concepts"]),
        "conditions": [None] * len(c["required_conditions"]),
        "critical": None, "completeness": None, "expected": None,
        "adjudicated": None, "human_approved": False,
        "rubric": {k: None for k in RUBRIC},
    } for c in cases]


def aggregate(cases, state, reviews):
    _check(cases, state)
    indexed = {}
    for r in reviews:
        slot = r.get("slot")
        if slot not in state["slots"] or slot in indexed:
            raise DatasetError("wiki_review: duplicate_or_unknown_slot")
        if (r.get("output_hash") != _digest(state["slots"][slot])
                or r.get("identity_hash") != _digest(state["identity"])
                or r.get("approval_hash") != state["approval_hash"]):
            raise DatasetError("wiki_review: stale_review")
        if type(r.get("human_approved")) is not bool:
            raise DatasetError("wiki_review: approval_boolean")
        indexed[slot] = r
    draft, final = {}, {}
    for c in cases:
        slot = c["id"] + ":U"
        output = state["slots"][slot]
        contract = SimpleNamespace(required_concepts=c["required_concepts"],
                                   required_conditions=c["required_conditions"],
                                   expected_response="answer")
        review = indexed.get(slot)
        row = verdict(contract, output, review)
        if output["status"] == "over_limit":
            row.update(verdict="X", reason="execution_limit")
        if review and any(x["label"] == "unsupported" for x in review.get("claims", [])):
            if row["verdict"] == "O":
                row.update(verdict="pending", reason="unverified_claims")
        draft[slot] = row
        final[slot] = row if review and review["human_approved"] else {
            "score": None, "accuracy": None, "correct": 0, "claims": 0,
            "verdict": "pending", "reason": "awaiting_human_review"}
    return {"scope": "live_development", "golden_set": "NOT_EVALUATED",
            "real_quality": "PENDING_HUMAN_REVIEW" if any(r["verdict"] == "pending" for r in final.values()) else "DEVELOPMENT_REVIEWED",
            "draft_rows": draft, "rows": final,
            "metrics": metrics(list(final.values())),
            "counts": {v: sum(r["verdict"] == v for r in final.values()) for v in ("O", "X", "pending")}}
