import pytest
from evals.dataset import _digest
from evals.schema import DatasetError
from evals.wiki_dev import manifest
from evals.wiki_live import make_plan
from evals.wiki_live_review import templates, aggregate
from test_eval_wiki_dev import cases


def fixture(cases):
    for c in cases:
        c["internal_evidence"] = []
    state = {"mode": "live", "identity": make_plan(cases)["identity"], "attempts": 6, "provider_calls": 6,
            "approval_hash": "approval", "slots": {
                c["id"] + ":U": {"status": "ok", "text": "response"} for c in cases}}
    state["integrity_hash"] = _digest(state)
    return state


def test_draft_not_human_approval(cases):
    s = fixture(cases)
    r = templates(cases, s)
    for row in r:
        row.update(reviewer="AI draft", evidence="fixture", claims=[
            {"id": "1", "text": "fact", "evidence": "source", "label": "correct"}],
            concepts=[True], conditions=[True], critical=0, completeness=True,
            expected=True, adjudicated=True, rubric={k: "O" for k in row["rubric"]})
    result = aggregate(cases, s, r)
    assert all(x["score"] == 5 for x in result["draft_rows"].values())
    assert result["counts"]["pending"] == 6
    for row in r:
        row["human_approved"] = True
    assert aggregate(cases, s, r)["counts"]["O"] == 6


def test_review_binding_and_mode(cases):
    s = fixture(cases)
    r = templates(cases, s)
    s["slots"]["WDEV01:U"]["text"] = "changed"
    s["integrity_hash"] = _digest({k: v for k, v in s.items() if k != "integrity_hash"})
    with pytest.raises(DatasetError, match="stale_review"):
        aggregate(cases, s, r)
    s["mode"] = "mock"
    s["integrity_hash"] = _digest({k: v for k, v in s.items() if k != "integrity_hash"})
    with pytest.raises(DatasetError, match="live_dataset"):
        templates(cases, s)


def test_abstention_is_not_quality_approval_or_removed_from_denominator(cases):
    import json
    from evals.wiki_live import INSUFFICIENT_EVIDENCE, _seal, _validate_wiki
    s = fixture(cases)
    checked = _validate_wiki(json.dumps(INSUFFICIENT_EVIDENCE), {"1": "unrelated"})
    s["slots"]["WDEV01:U"].update(text=checked["text"], structured_output=checked)
    s = _seal(s)
    pending = aggregate(cases, s, [])
    assert pending["counts"] == {"O": 0, "X": 0, "pending": 6}
    assert pending["metrics"]["responses"] == 6
    reviews = templates(cases, s)
    # Existing six-case contract expects an answer. An honest human review of a
    # refusal cannot turn format acceptance into an answered-concept quality pass.
    reviews[0].update(reviewer="Synthetic human fixture", evidence="No concept explained",
                      claims=[], concepts=[False], conditions=[False], critical=0,
                      completeness=False, expected=False, adjudicated=True,
                      human_approved=True,
                      rubric={"facts": "O", "concepts": "X", "conditions": "X",
                              "clarity": "O", "complete": "X"})
    reviewed = aggregate(cases, s, reviews)
    assert reviewed["counts"] == {"O": 0, "X": 1, "pending": 5}
    assert reviewed["metrics"]["responses"] == 6
