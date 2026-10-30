import copy
from dataclasses import replace

import pytest

from evals.dataset import _digest, freeze_dataset
from evals.scoring import score, templates
from evals.schema import DatasetError
from test_eval_dataset import full_set


def fixture():
    cases = full_set()
    state = {"mode": "fake", "identity": {"dataset_version": freeze_dataset(cases, "r")["dataset_version"]},
             "slots": {f"{c.case_id}:{r}": {"status": "ok", "text": "synthetic"} for c in cases if c.split == "final" for r in range(1, 4)}}
    reviews = templates(cases, state)
    for r in reviews:
        r.update(reviewer="primary", second_reviewer="independent", evidence="fixture",
                 claims=[{"id":"1", "text":"fact", "label":"correct", "evidence":"fixture"}],
                 concepts=[True], conditions=[], critical=0, completeness=True, expected=True,
                 adjudicated=True, rubric={k:"O" for k in r["rubric"]})
    return cases, state, reviews


def test_full_pass_is_not_product_pass():
    c, s, r = fixture()
    out = score(c, s, r)
    assert out["golden_status"] == "PASS" and out["score_mean"] == 5
    assert out["product_status"] == "INCOMPLETE"
    assert len(out["second_required"]) == 24 and out["expected_count"] == 120


@pytest.mark.parametrize("correct,status", [(19,"PASS"), (18,"FAIL")])
def test_95_percent_separate_from_four_points(correct, status):
    c, s, r = fixture()
    r[0]["claims"] = [{"id":str(i), "text":"fact", "label":"correct" if i < correct else "incorrect", "evidence":"fixture"} for i in range(20)]
    r[0]["rubric"]["facts"] = "X"
    out = score(c, s, r)
    assert out["rows"][r[0]["slot"]]["score"] == 4
    assert out["rows"][r[0]["slot"]]["accuracy"] == correct / 20
    assert out["golden_status"] == status


@pytest.mark.parametrize("kind", ["condition", "critical", "empty", "no_claim", "execution"])
def test_failure_cannot_hide_in_average(kind):
    c, s, r = fixture()
    slot = r[0]["slot"]
    if kind == "condition":
        c[20] = replace(c[20], required_conditions=["required"])
        for review in r:
            if review["slot"].startswith("C20:"):
                review["conditions"] = [True]
        r[0]["conditions"] = [False]
        r[0]["rubric"]["conditions"] = "X"
        s["identity"]["dataset_version"] = freeze_dataset(c, "r")["dataset_version"]
        for review in r:
            review["dataset_version"] = s["identity"]["dataset_version"]
    elif kind == "critical":
        r[0]["critical"] = 1
    elif kind == "empty":
        s["slots"][slot]["text"] = ""
        r[0]["output_hash"] = _digest(s["slots"][slot])
    elif kind == "no_claim":
        r[0]["claims"] = []
    else:
        s["slots"][slot]["status"] = "error"
        r[0]["output_hash"] = _digest(s["slots"][slot])
    assert score(c, s, r)["golden_status"] == "FAIL"


def test_exception_no_claim_is_na():
    c, s, r = fixture()
    for review in r:
        if int(review["slot"].split(":")[0][1:]) >= 52:
            review["claims"] = []
    out = score(c, s, r)
    assert out["golden_status"] == "PASS"
    assert out["groups"]["1:exception"]["claim_weighted"] is None


def test_unreviewed_and_missing_slots_do_not_pass():
    c, s, r = fixture()
    assert score(c, s, r[:-1])["golden_status"] == "INCOMPLETE"
    r[0]["rubric"]["clarity"] = None
    assert score(c, s, r)["rows"][r[0]["slot"]]["score"] is None
    r[0]["critical"] = 1
    assert score(c, s, r)["golden_status"] == "FAIL"


@pytest.mark.parametrize("kind", ["claim_id", "output", "version", "rubric"])
def test_invalid_review_rejected(kind):
    c, s, r = fixture()
    if kind == "claim_id":
        r[0]["claims"] *= 2
    elif kind == "output":
        r.append(copy.deepcopy(r[0]))
    elif kind == "version":
        r[0]["output_hash"] = "wrong"
    else:
        r[0]["rubric"]["facts"] = "X"
    with pytest.raises(DatasetError):
        score(c, s, r)


def test_independent_review_required_and_seed_reproducible():
    c, s, r = fixture()
    for review in r:
        review["second_reviewer"] = ""
    out = score(c, s, r, seed=17)
    assert out["golden_status"] == "INCOMPLETE"
    assert out["second_required"] == score(c, s, r, seed=17)["second_required"]


def test_blank_template_never_passes():
    c, s, r = fixture()
    assert score(c, s, templates(c, s))["golden_status"] == "INCOMPLETE"
