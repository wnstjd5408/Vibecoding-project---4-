import json
import socket
from dataclasses import replace
from types import SimpleNamespace

import pytest

from evals import live
from evals.dataset import freeze_dataset
from evals.runner import RunConfig
from evals.schema import DatasetError
from test_eval_dataset import full_set


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*a, **k):
        pytest.fail("network attempted")
    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(socket, "create_connection", fail)


def setup(monkeypatch, counter=True):
    if counter:
        monkeypatch.setattr(live, "input_bound", lambda request: 100)
    cases = full_set()
    return cases, freeze_dataset(cases, "reviewer"), RunConfig(
        "calibration", split="dev", repetitions=1, max_calls=3, model_id=live.MODEL)


def response(**changes):
    return {"usage": {"inputTokens": 100, "outputTokens": 20},
            "stopReason": "end_turn", "output": {"message": {"content": [{"text": "fixture"}]}}, **changes}


def test_default_counter_blocks(monkeypatch, tmp_path):
    args = setup(monkeypatch, False)
    with pytest.raises(DatasetError, match="verified_token_bound"):
        live.calibration(*args, tmp_path, ["C0"], lambda _: pytest.fail("called"))


def test_three_and_resume(monkeypatch, tmp_path):
    args = setup(monkeypatch)
    calls = []
    def transport(request):
        calls.append(request)
        return response()
    for _ in range(2):
        state = live.calibration(*args, tmp_path, ["C0", "C1", "C2"], transport)
    assert len(calls) == state["provider_calls"] == 3
    assert all(r["status"] == "ok" for r in state["slots"].values())
    assert "grading_evidence" not in json.dumps(calls)
    assert calls[0]["additionalModelRequestFields"]["reasoning"]["effort"] == "none"


@pytest.mark.parametrize("change,ids", [({"budget": "0"}, ["C0"]),
    ({"max_calls": 4}, ["C0"]), ({}, ["C20"]), ({}, ["C0", "C0"]),
    ({"max_input": 99}, ["C0"]), ({"split": "final", "repetitions": 3}, ["C20"])])
def test_preflight_no_calls(monkeypatch, tmp_path, change, ids):
    cases, manifest, config = setup(monkeypatch)
    with pytest.raises(DatasetError):
        live.calibration(cases, manifest, replace(config, **change), tmp_path, ids,
                         lambda _: pytest.fail("called"))


@pytest.mark.parametrize("kind", ["unknown", "interrupt", "over_limit"])
def test_uncertain_never_retried(monkeypatch, tmp_path, kind):
    args = setup(monkeypatch)
    calls = []
    def transport(_):
        calls.append(1)
        if kind == "interrupt":
            raise KeyboardInterrupt()
        return response(usage=None if kind == "unknown" else {"inputTokens": 9999, "outputTokens": 20})
    if kind == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            live.calibration(*args, tmp_path, ["C0", "C1"], transport)
    else:
        live.calibration(*args, tmp_path, ["C0", "C1"], transport)
    with pytest.raises(DatasetError, match="manual_recovery"):
        live.calibration(*args, tmp_path, ["C0", "C1"], transport)
    assert len(calls) == 1
    state = json.loads((tmp_path / "state.json").read_text())
    if kind == "over_limit":
        assert state["slots"]["C0"]["usage"]["inputTokens"] == 9999


@pytest.mark.parametrize("change", [{"stopReason": "max_tokens"}, {"output": "malformed"}])
def test_output_failure_keeps_usage(monkeypatch, tmp_path, change):
    state = live.calibration(*setup(monkeypatch), tmp_path, ["C0"], lambda _: response(**change))
    row = state["slots"]["C0"]
    assert row["status"] == "error" and row["input_tokens"] == 100
    assert "cost_upper_estimate" in row


def test_sdk_retries_disabled():
    assert live.SDK_CONFIG.retries["total_max_attempts"] == 1
    with pytest.raises(DatasetError, match="automatic_retries"):
        live.BedrockTransport(SimpleNamespace(meta=SimpleNamespace(config=SimpleNamespace(retries={}))))
