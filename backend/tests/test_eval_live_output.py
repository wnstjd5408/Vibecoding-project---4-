import json
from types import SimpleNamespace

import pytest

from evals import live_auth
from evals.live_output import validate_output, development_report
from evals.schema import DatasetError
from test_eval_live import setup, response, no_network
from evals.live import calibration


def obj(**changes):
    return json.dumps({"summary": ["a", "b", "c"], "explanation": "definition [1]", "source_ids": ["1"], **changes})


@pytest.mark.parametrize("text", [obj(summary=["one"]), obj(summary=["a\nb", "b", "c"]),
    obj(source_ids=["2"]), obj(source_ids=[]), obj(explanation="https://invented.example [1]"),
    '{"summary":[],"summary":[]}', '```json\n{}\n```', obj(extra="x")])
def test_reject_bad_output(text):
    with pytest.raises(DatasetError):
        validate_output(text, {"1": "provided"})


def test_references_resolved_from_input():
    assert validate_output(obj(), {"1": "provided"})["references"] == [{"id": "1", "evidence": "provided"}]


def test_dev_t4_pending_and_failure(monkeypatch, tmp_path):
    args = setup(monkeypatch)
    state = calibration(*args, tmp_path, ["C0", "C1"], lambda _: response())
    reviews = development_report(args[0], state)
    assert reviews[0]["slot"] == "C0:1"
    report = development_report(args[0], state, reviews)
    assert report["verdict_counts"]["pending"] == 2
    assert report["golden_status"] == "NOT_EVALUATED"
    for review in reviews:
        review.update(reviewer="human", evidence="fixture review", claims=[{
            "id": "claim1", "text": "fixture", "evidence": "fixture", "label": "correct"}],
            concepts=[True], conditions=[], critical=0, completeness=True, expected=True,
            adjudicated=True, rubric={k: "O" for k in review["rubric"]})
    report = development_report(args[0], state, reviews)
    assert all(r["score"] == 5 and r["verdict"] == "O" for r in report["rows"].values())
    assert report["golden_status"] == "NOT_EVALUATED"
    state["slots"]["C0"]["status"] = "over_limit"
    with pytest.raises(DatasetError, match="version_mismatch"):
        development_report(args[0], state, reviews)
    report = development_report(args[0], state, [])
    assert report["rows"]["C0:1"]["verdict"] == "X"
    assert report["rows"]["C0:1"]["score"] == 0


def test_missing_auth_no_sdk(monkeypatch):
    monkeypatch.delenv("AWS_ROLE_ARN", raising=False)
    monkeypatch.delenv("VERCEL_OIDC_TOKEN", raising=False)
    monkeypatch.setattr(live_auth.boto3, "client", lambda *a, **k: pytest.fail("SDK called"))
    with pytest.raises(DatasetError, match="oidc_credentials_missing"):
        live_auth.oidc_transport()


def test_oidc_no_bearer_fallback_or_retries(monkeypatch):
    monkeypatch.setenv("AWS_ROLE_ARN", "fixture-role")
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "fixture-token")
    seen = []
    def client(service, **kwargs):
        seen.append((service, kwargs))
        if service == "sts":
            return SimpleNamespace(assume_role_with_web_identity=lambda **k: {"Credentials": {
                "AccessKeyId": "fixture", "SecretAccessKey": "fixture", "SessionToken": "fixture"}})
        return SimpleNamespace(meta=SimpleNamespace(config=kwargs["config"]))
    monkeypatch.setattr(live_auth.boto3, "client", client)
    live_auth.oidc_transport()
    assert all(k["config"].retries["total_max_attempts"] == 1 for _, k in seen)
    assert seen[1][1]["config"].signature_version == "v4"
