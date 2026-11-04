"""Aggregate human judgments; never infer CS correctness from model text."""
import math
import random
from fractions import Fraction

from .dataset import _digest, freeze_dataset
from .schema import DatasetError

RUBRIC = ("facts", "concepts", "conditions", "clarity", "complete")


def templates(cases, state):
    by_id = {c.case_id: c for c in cases}
    reviews = []
    for slot, output in state["slots"].items():
        case = by_id[slot.rsplit(":", 1)[0]]
        reviews.append({
            "slot": slot, "output_hash": _digest(output),
            "dataset_version": state["identity"]["dataset_version"],
            "rubric_version": "human-v1", "reviewer": "", "evidence": "",
            "claims": [], "concepts": [None] * len(case.required_concepts),
            "conditions": [None] * len(case.required_conditions),
            "critical": None, "completeness": None, "expected": None,
            "rubric": {k: None for k in RUBRIC}, "adjudicated": None,
            "second_reviewer": "", "disputed": False,
        })
    return reviews


def verdict(case, output, review):
    base = {"score": None, "accuracy": None, "correct": 0, "claims": 0,
            "verdict": "pending", "critical": None}
    if output["status"] in ("error", "unknown", "started"):
        return {**base, "score": 0, "accuracy": 0 if case.expected_response == "answer" else None,
                "verdict": "X", "reason": "execution_failure"}
    if output["status"] != "ok" or review is None:
        return base
    if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip() or not review.get("evidence"):
        return base
    if review.get("rubric_version") != "human-v1":
        raise DatasetError("score: rubric_version")
    claims = review.get("claims")
    if not isinstance(claims, list):
        raise DatasetError("score: claims")
    ids = set()
    for claim in claims:
        if (not isinstance(claim, dict) or not isinstance(claim.get("id"), str) or not claim["id"]
                or claim["id"] in ids or not claim.get("text") or not claim.get("evidence")
                or claim.get("label") not in ("correct", "incorrect", "unsupported")):
            raise DatasetError("score: invalid_claim")
        ids.add(claim["id"])
    correct = sum(c["label"] == "correct" for c in claims)
    accuracy = Fraction(correct, len(claims)) if claims else (Fraction(0) if case.expected_response == "answer" else None)
    base.update(correct=correct, claims=len(claims), accuracy=float(accuracy) if accuracy is not None else None)
    checks = []
    for field, required in (("concepts", case.required_concepts), ("conditions", case.required_conditions)):
        values = review.get(field)
        if not isinstance(values, list) or len(values) != len(required) or any(v is not None and type(v) is not bool for v in values):
            raise DatasetError("score: required_items")
        checks.extend(values)
    for field in ("completeness", "expected", "adjudicated"):
        value = review.get(field)
        if value is not None and type(value) is not bool:
            raise DatasetError("score: boolean_required")
        checks.append(value)
    critical = review.get("critical")
    if critical is not None and (type(critical) is not int or critical < 0):
        raise DatasetError("score: critical_count")
    rubric = review.get("rubric")
    if not isinstance(rubric, dict) or set(rubric) != set(RUBRIC) or any(v not in ("O", "X", None) for v in rubric.values()):
        raise DatasetError("score: rubric")
    known_failure = (False in checks[:-1] or (critical is not None and critical > 0)
                     or (accuracy is not None and accuracy < Fraction(95, 100))
                     or not output.get("text", "").strip())
    pending = (None in checks or review["adjudicated"] is not True
               or critical is None or None in rubric.values())
    if not pending:
        # Reject contradictory human scores rather than silently fixing them.
        expected = {
            "facts": all(c["label"] == "correct" for c in claims),
            "concepts": all(review["concepts"]), "conditions": all(review["conditions"]),
            "complete": review["completeness"] and review["expected"],
        }
        if any((rubric[k] == "O") != v for k, v in expected.items()):
            raise DatasetError("score: contradictory_rubric")
    return {**base, "critical": critical,
            "score": None if pending else sum(v == "O" for v in rubric.values()),
            "verdict": "X" if known_failure else ("pending" if pending else "O")}


def metrics(rows):
    eligible = [r for r in rows if r["accuracy"] is not None]
    correct, total = sum(r["correct"] for r in rows), sum(r["claims"] for r in rows)
    return {"responses": len(rows), "accuracy_responses": len(eligible),
            "response_mean": sum(r["accuracy"] for r in eligible) / len(eligible) if eligible else None,
            "correct": correct, "claims": total,
            "claim_weighted": correct / total if total else None}


def score(cases, state, reviews, *, seed=0):
    if freeze_dataset(cases, "verify")["dataset_version"] != state["identity"]["dataset_version"]:
        raise DatasetError("score: dataset_mismatch")
    by_id = {c.case_id: c for c in cases if c.split == "final"}
    expected_slots = {f"{c.case_id}:{r}" for c in by_id.values() for r in range(1, 4)}
    if any(k not in expected_slots for k in state["slots"]):
        raise DatasetError("score: unexpected_output")
    by_review = {}
    for review in reviews:
        slot = review.get("slot")
        if slot not in state["slots"] or slot in by_review:
            raise DatasetError("score: duplicate_or_missing_output")
        if (review.get("output_hash") != _digest(state["slots"][slot])
                or review.get("dataset_version") != state["identity"]["dataset_version"]):
            raise DatasetError("score: version_mismatch")
        by_review[slot] = review
    rows = {}
    for slot in sorted(expected_slots):
        case = by_id[slot.rsplit(":", 1)[0]]
        rows[slot] = verdict(case, state["slots"].get(slot, {"status": "pending"}), by_review.get(slot))
    # Independent review: all suspected critical/disputed, plus random 20% of remainder.
    mandatory = {k for k, r in rows.items() if r["critical"] or by_review.get(k, {}).get("disputed")}
    remainder = sorted(expected_slots - mandatory)
    sampled = set(random.Random(seed).sample(remainder, math.ceil(.2 * len(remainder))))
    second_required = mandatory | sampled
    second_missing = sorted(k for k in second_required
                            if not by_review.get(k, {}).get("second_reviewer")
                            or by_review[k]["second_reviewer"] == by_review[k].get("reviewer")
                            or by_review[k].get("adjudicated") is not True)
    groups = {}
    failed = any(r["verdict"] == "X" for r in rows.values())
    for repeat in range(1, 4):
        current = {k: v for k, v in rows.items() if k.endswith(f":{repeat}")}
        buckets = sorted({c.risk_bucket for c in by_id.values()})
        for bucket in ["answer", "exception", *buckets]:
            subset = [v for k, v in current.items() if
                      (("answer" if by_id[k.rsplit(":", 1)[0]].expected_response == "answer" else "exception") == bucket
                       or by_id[k.rsplit(":", 1)[0]].risk_bucket == bucket)]
            m = metrics(subset)
            groups[f"{repeat}:{bucket}"] = m
            if any(m[key] is not None and m[key] < .95 - 1e-12 for key in ("response_mean", "claim_weighted")):
                failed = True
    incomplete = (len(by_id) != 40 or any(r["verdict"] == "pending" for r in rows.values()) or bool(second_missing))
    status = "FAIL" if failed else ("INCOMPLETE" if incomplete else "PASS")
    scored = [r["score"] for r in rows.values() if r["score"] is not None]
    return {"golden_status": status, "product_status": "INCOMPLETE",
            "mode": state.get("mode", "unknown"), "quality_claim": "synthetic test only" if state.get("mode") == "fake" else "human-reviewed",
            "dataset_version": state["identity"]["dataset_version"], "rubric_version": "human-v1",
            "rows": rows, "groups": groups, "score_mean": sum(scored) / len(scored) if scored else None,
            "scored_count": len(scored), "expected_count": len(expected_slots),
            "verdict_counts": {v: sum(r["verdict"] == v for r in rows.values()) for v in ("O", "X", "pending")},
            "rubric_o_rates": {k: {
                "o": sum(by_review.get(slot, {}).get("rubric", {}).get(k) == "O"
                         for slot, row in rows.items() if row["score"] is not None
                         and row.get("reason") != "execution_failure"),
                "reviewed": len(scored)
            } for k in RUBRIC},
            "second_review_seed": seed, "second_required": sorted(second_required),
            "second_missing": second_missing, "incomplete": incomplete,
            "unverified": ["product_integration", "user_comprehension"]}
