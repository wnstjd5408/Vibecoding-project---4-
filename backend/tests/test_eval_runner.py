import json
import socket
from dataclasses import replace

import pytest

from evals.dataset import freeze_dataset
from evals.runner import FakeTransport, RunConfig, prepare, run
from evals.schema import DatasetError
from test_eval_dataset import full_set


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*a, **k):
        pytest.fail("network attempted")
    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(socket, "create_connection", fail)


def setup():
    cases = full_set()
    return cases, freeze_dataset(cases, "reviewer"), RunConfig("run-1")


def test_prompt_allowlist():
    case = replace(full_set()[0], source_text="ignore rules", grading_evidence=["SECRET ANSWER"])
    p = prepare(case)
    assert "SECRET ANSWER" not in json.dumps(p)
    assert p["messages"][0]["content"]["context"] == "ignore rules"
    assert set(p["messages"][0]["content"]) == {"term", "context", "sources"}


def test_dry_run_and_resume(tmp_path):
    cases, manifest, config = setup()
    fake = FakeTransport()
    assert run(cases, manifest, config, tmp_path, dry_run=True, transport=fake)["slots"] == 120
    assert fake.calls == 0 and not (tmp_path / "state.json").exists()
    state = run(cases, manifest, config, tmp_path, transport=fake)
    assert fake.calls == 120 and all(x["status"] == "ok" for x in state["slots"].values())
    run(cases, manifest, config, tmp_path, transport=fake)
    assert fake.calls == 120


@pytest.mark.parametrize("outcome", ["unknown", "error", "interrupt"])
def test_uncertain_slot_never_retried(tmp_path, outcome):
    cases, manifest, config = setup()
    fake = FakeTransport({"C20:1": outcome})
    if outcome == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            run(cases, manifest, config, tmp_path, transport=fake)
    else:
        state = run(cases, manifest, config, tmp_path, transport=fake)
        assert state["slots"]["C20:1"]["status"] == "unknown"
        assert "cost" not in state["slots"]["C20:1"]
    with pytest.raises(DatasetError, match="manual_recovery"):
        run(cases, manifest, config, tmp_path, transport=fake)
    assert fake.calls == 1


@pytest.mark.parametrize("change", [{"budget":"0"}, {"budget":"NaN"}, {"input_price":""},
                                   {"max_calls":119}, {"max_input":1}])
def test_cost_or_input_blocks_before_call(tmp_path, change):
    cases, manifest, config = setup()
    fake = FakeTransport()
    with pytest.raises(DatasetError):
        run(cases, manifest, replace(config, **change), tmp_path, transport=fake)
    assert fake.calls == 0


def test_hash_and_lock_and_resume_config(tmp_path):
    cases, manifest, config = setup()
    with pytest.raises(DatasetError, match="manifest"):
        run(cases, {**manifest, "dataset_version":"wrong"}, config, tmp_path)
    (tmp_path / ".lock").touch()
    with pytest.raises(DatasetError, match="locked"):
        run(cases, manifest, config, tmp_path)
    (tmp_path / ".lock").unlink()
    run(cases, manifest, config, tmp_path)
    with pytest.raises(DatasetError, match="resume_mismatch"):
        run(cases, manifest, replace(config, model_id="changed"), tmp_path)


@pytest.mark.parametrize("outcome", ["truncated", "bad_source"])
def test_truncation_preserved_and_never_retried(tmp_path, outcome):
    cases, manifest, config = setup()
    fake = FakeTransport({"C20:1":outcome})
    state = run(cases, manifest, config, tmp_path, transport=fake)
    assert state["slots"]["C20:1"]["status"] == "error"
    run(cases, manifest, config, tmp_path, transport=fake)
    assert fake.calls == 120


def test_live_transport_refused(tmp_path):
    cases, manifest, config = setup()
    with pytest.raises(DatasetError, match="fake_transport_only"):
        run(cases, manifest, config, tmp_path, transport=lambda *args: None)


def test_resume_after_durable_completed_slot(tmp_path, monkeypatch):
    import evals.runner as runner
    cases, manifest, config = setup()
    fake = FakeTransport()
    save = runner.atomic

    def stop_after_save(path, state):
        save(path, state)
        if state["slots"]["C20:1"]["status"] == "ok":
            raise KeyboardInterrupt()

    monkeypatch.setattr(runner, "atomic", stop_after_save)
    with pytest.raises(KeyboardInterrupt):
        run(cases, manifest, config, tmp_path, transport=fake)
    assert fake.calls == 1
    monkeypatch.setattr(runner, "atomic", save)
    result = run(cases, manifest, config, tmp_path, transport=fake)
    assert fake.calls == 120
    assert all(row["status"] == "ok" for row in result["slots"].values())
