"""No-network tests for the independently approved wiki live calibration."""
import copy
import json
import socket

import pytest

from evals.schema import DatasetError
from evals.wiki_dev import manifest
from evals.wiki_live import initialize, make_plan, run


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in wiki tests")
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.fixture
def cases():
    return [{
        "id": f"WDEV{i:02}", "concept_id": f"C-{i}", "page_id": f"P-{i}",
        "term": f"Term{i}", "aliases": [f"Alias{i}"], "original": "Synthetic context",
        "reference": "DO_NOT_SEND_REFERENCE", "required_concepts": ["DO_NOT_SEND_RUBRIC"],
        "required_conditions": ["required condition"],
        "internal_evidence": [{"id": f"N{i}", "kind": "internal", "text": "Internal synthetic evidence",
                               "public": True, "revision": 1}],
        "evidence": [{"id": f"W{i}", "kind": "web", "text": "Public synthetic evidence",
                      "public": True, "revision": 1, "url": "https://example.org/source"}]
    } for i in range(1, 7)]


def response(*, stop="end_turn", body=None):
    if body is None:
        body = json.dumps({
            "summary": ["요약 1", "요약 2", "요약 3"],
            "explanation": "정의\n합성 정의 [1]\n작동 원리\n합성 원리\n활용 예시\n합성 예시\n주의사항\n합성 조건 [2]",
            "source_ids": ["1", "2"],
        }, ensure_ascii=False)
    return {"usage": {"inputTokens": 100, "outputTokens": 80}, "stopReason": stop,
            "output": {"message": {"role": "assistant", "content": [{"text": body}]}}}


class Scripted:
    def __init__(self, outputs=None):
        self.outputs = list(outputs or [])
        self.calls = []

    def __call__(self, request):
        self.calls.append(copy.deepcopy(request))
        result = self.outputs.pop(0) if self.outputs else response()
        if isinstance(result, BaseException):
            raise result
        return result


def prepared(cases, tmp_path, *, budget="2.00", mode="mock"):
    approval, ledger = tmp_path / "approval.json", tmp_path / "ledger.json"
    initialize(cases, manifest(cases), approval, ledger, approval_id="approved-fixture",
               run_id="test-wiki", budget=budget, mode=mode)
    return approval, ledger


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_plan_excludes_answers_and_maps_citations(cases):
    plan = make_plan(cases)
    assert len(plan["requests"]) == 6
    assert plan["per_call"] == "0.26475"
    for slot, request in plan["requests"].items():
        serialized = json.dumps(request, ensure_ascii=False)
        assert "DO_NOT_SEND_REFERENCE" not in serialized
        assert "DO_NOT_SEND_RUBRIC" not in serialized
        assert "required condition" not in serialized
        assert request["inferenceConfig"]["maxTokens"] == 3000
        assert request["modelId"] == "global.openai.gpt-6-luna"
        assert set(plan["sources"][slot]) == {"1", "2"}


def test_fewshot_examples_are_valid_and_current_payload_is_last(cases):
    from evals.wiki_examples import EXAMPLES, example_messages
    from evals.live_output import validate_output
    assert len(EXAMPLES) == 1
    for payload, answer in EXAMPLES:
        validate_output(json.dumps(answer, ensure_ascii=False), payload["sources"])
        for heading in ("정의", "작동 원리", "활용 예시", "주의사항"):
            assert f"**{heading}**\n" in answer["explanation"]
        assert payload["term"] not in [c["term"] for c in cases]
    messages = make_plan(cases)["requests"]["WDEV01:U"]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    current = json.loads(messages[-1]["content"][0]["text"])
    assert current["term"] == cases[0]["term"]
    assert current["sources"]["1"] == cases[0]["internal_evidence"][0]["text"]
    messages[0]["content"][0]["text"] = "mutated"
    assert example_messages()[0]["content"][0]["text"] != "mutated"


def test_example_change_invalidates_approval_before_call(cases, tmp_path, monkeypatch):
    import evals.wiki_live as wiki
    approval, _ = prepared(cases, tmp_path)
    original = wiki.example_messages
    def changed():
        messages = original()
        messages[0]["content"][0]["text"] += " "
        return messages
    monkeypatch.setattr(wiki, "example_messages", changed)
    transport = Scripted()
    with pytest.raises(DatasetError, match="approval_mismatch"):
        run(cases, manifest(cases), approval, transport, phase="canary", mode="mock")
    assert transport.calls == []


def test_fewshot_bytes_count_toward_request_limit(cases, monkeypatch):
    import evals.wiki_live as wiki
    monkeypatch.setattr(wiki, "example_messages", lambda: [
        {"role": "user", "content": [{"text": "x" * 16000}]}])
    with pytest.raises(DatasetError, match="request_byte_limit"):
        make_plan(cases)


def test_example_citations_do_not_expand_current_allowlist(cases):
    from evals.live_output import validate_output
    cases[0]["internal_evidence"] = []
    plan = make_plan(cases)
    assert set(plan["sources"]["WDEV01:U"]) == {"1"}
    with pytest.raises(DatasetError, match="unknown_source"):
        validate_output(response()["output"]["message"]["content"][0]["text"],
                        plan["sources"]["WDEV01:U"])


def test_canary_then_remaining_and_resume_are_idempotent(cases, tmp_path):
    approval, ledger = prepared(cases, tmp_path)
    transport = Scripted()
    state = run(cases, manifest(cases), approval, transport, phase="canary", mode="mock")
    assert len(transport.calls) == 1
    assert state["slots"]["WDEV01:U"]["status"] == "ok"
    assert sum(row["status"] == "pending" for row in state["slots"].values()) == 5
    run(cases, manifest(cases), approval, transport, phase="canary", mode="mock")
    assert len(transport.calls) == 1
    state = run(cases, manifest(cases), approval, transport, phase="remaining", mode="mock")
    assert len(transport.calls) == 6
    assert all(row["status"] == "ok" for row in state["slots"].values())
    run(cases, manifest(cases), approval, transport, phase="remaining", mode="mock")
    assert len(transport.calls) == 6
    assert read(ledger) == state


def test_remaining_cannot_skip_canary(cases, tmp_path):
    approval, _ = prepared(cases, tmp_path)
    transport = Scripted()
    with pytest.raises(DatasetError):
        run(cases, manifest(cases), approval, transport, phase="remaining", mode="mock")
    assert transport.calls == []


@pytest.mark.parametrize("budget", ["0", "-1", "NaN", "Infinity", "1.00", "nonsense"])
def test_budget_rejected_before_any_invocation(cases, tmp_path, budget):
    with pytest.raises(DatasetError):
        prepared(cases, tmp_path, budget=budget)


def test_approval_cannot_be_reinitialized(cases, tmp_path):
    approval, ledger = prepared(cases, tmp_path)
    original = approval.read_bytes(), ledger.read_bytes()
    with pytest.raises((DatasetError, FileExistsError)):
        prepared(cases, tmp_path)
    assert original == (approval.read_bytes(), ledger.read_bytes())


def test_missing_ledger_never_resets_allowance(cases, tmp_path):
    approval, ledger = prepared(cases, tmp_path)
    transport = Scripted()
    run(cases, manifest(cases), approval, transport, phase="canary", mode="mock")
    ledger.unlink()
    with pytest.raises(DatasetError):
        run(cases, manifest(cases), approval, transport, phase="canary", mode="mock")
    assert len(transport.calls) == 1


@pytest.mark.parametrize("change", ["manifest", "request"])
def test_changed_dataset_or_manifest_rejected(cases, tmp_path, change):
    frozen = manifest(cases)
    approval, _ = prepared(cases, tmp_path)
    if change == "manifest":
        frozen["dataset_version"] = "stale"
    else:
        cases[0]["original"] += " changed"
        frozen = manifest(cases)
    transport = Scripted()
    with pytest.raises(DatasetError):
        run(cases, frozen, approval, transport, phase="canary", mode="mock")
    assert transport.calls == []


@pytest.mark.parametrize("output", [response(stop="max_tokens"), response(body="not json"),
                                    response(body='{"summary":[],"explanation":"","source_ids":[]}')])
def test_invalid_or_truncated_output_is_saved_and_halts(cases, tmp_path, output):
    approval, ledger = prepared(cases, tmp_path)
    transport = Scripted([output])
    state = run(cases, manifest(cases), approval, transport, phase="canary", mode="mock")
    row = state["slots"]["WDEV01:U"]
    assert row["status"] == "error"
    assert row["usage"] == output["usage"]
    assert read(ledger)["slots"]["WDEV01:U"]["status"] == "error"
    with pytest.raises(DatasetError):
        run(cases, manifest(cases), approval, transport, phase="remaining", mode="mock")
    assert len(transport.calls) == 1


@pytest.mark.parametrize("failure", [RuntimeError("secret provider failure"), KeyboardInterrupt()])
def test_interruption_or_unknown_never_retries(cases, tmp_path, failure):
    approval, ledger = prepared(cases, tmp_path)
    transport = Scripted([failure])
    try:
        run(cases, manifest(cases), approval, transport, phase="canary", mode="mock")
    except KeyboardInterrupt:
        pass
    row = read(ledger)["slots"]["WDEV01:U"]
    assert row["status"] in ("started", "unknown")
    assert "secret provider failure" not in ledger.read_text(encoding="utf-8")
    with pytest.raises(DatasetError):
        run(cases, manifest(cases), approval, transport, phase="canary", mode="mock")
    assert len(transport.calls) == 1


def test_usage_exceeding_limit_halts(cases, tmp_path):
    approval, _ = prepared(cases, tmp_path)
    output = response()
    output["usage"]["outputTokens"] = 3001
    transport = Scripted([output])
    state = run(cases, manifest(cases), approval, transport, phase="canary", mode="mock")
    assert state["slots"]["WDEV01:U"]["status"] == "over_limit"
    with pytest.raises(DatasetError):
        run(cases, manifest(cases), approval, transport, phase="remaining", mode="mock")
    assert len(transport.calls) == 1


def test_mock_approval_cannot_be_run_as_live(cases, tmp_path):
    approval, _ = prepared(cases, tmp_path)
    transport = Scripted()
    with pytest.raises(DatasetError):
        run(cases, manifest(cases), approval, transport, phase="canary", mode="live")
    assert transport.calls == []


def test_live_approval_rejects_scripted_transport(cases, tmp_path):
    approval, _ = prepared(cases, tmp_path, mode="live")
    transport = Scripted()
    with pytest.raises(DatasetError):
        run(cases, manifest(cases), approval, transport, phase="canary", mode="live")
    assert transport.calls == []


def test_existing_execution_lock_prevents_call(cases, tmp_path):
    approval, _ = prepared(cases, tmp_path)
    lock = approval.parent / '.wiki-live.lock'
    lock.write_text('other process', encoding='utf-8')
    transport = Scripted()
    with pytest.raises(DatasetError):
        run(cases, manifest(cases), approval, transport, phase="canary", mode="mock")
    assert transport.calls == []
    assert lock.exists()


def test_unknown_usage_is_durable_and_not_retried(cases, tmp_path):
    approval, ledger = prepared(cases, tmp_path)
    output = response()
    del output['usage']
    transport = Scripted([output])
    state = run(cases, manifest(cases), approval, transport, phase="canary", mode="mock")
    assert state['slots']['WDEV01:U']['status'] == 'unknown'
    assert read(ledger)['slots']['WDEV01:U']['status'] == 'unknown'
    with pytest.raises(DatasetError):
        run(cases, manifest(cases), approval, transport, phase="remaining", mode="mock")
    assert len(transport.calls) == 1


@pytest.mark.parametrize('explanation,source_ids', [
    ('정의\ntext [99]\n작동 원리\ntext\n활용 예시\ntext\n주의사항\ntext', ['99']),
    ('정의\ntext\n작동 원리\ntext\n활용 예시\ntext\n주의사항\ntext', []),
    ('정의 작동 원리 활용 예시 주의사항 [1]', ['1']),
    ('정의\n\n작동 원리\ntext\n활용 예시\ntext\n주의사항\ntext [1]', ['1']),
])
def test_citations_and_section_bodies_are_required(cases, tmp_path, explanation, source_ids):
    approval, _ = prepared(cases, tmp_path)
    body = json.dumps({'summary': ['a', 'b', 'c'], 'explanation': explanation,
                       'source_ids': source_ids}, ensure_ascii=False)
    transport = Scripted([response(body=body)])
    state = run(cases, manifest(cases), approval, transport, phase='canary', mode='mock')
    assert state['slots']['WDEV01:U']['status'] == 'error'
    assert len(transport.calls) == 1


def test_started_is_persisted_before_transport(cases, tmp_path):
    approval, ledger = prepared(cases, tmp_path)
    observed = []
    def transport(request):
        observed.append(read(ledger)['slots']['WDEV01:U']['status'])
        return response()
    run(cases, manifest(cases), approval, transport, phase='canary', mode='mock')
    assert observed == ['started']


def test_failure_in_remaining_batch_stops_later_slots(cases, tmp_path):
    approval, _ = prepared(cases, tmp_path)
    transport = Scripted([response(), response(stop='max_tokens'), response()])
    run(cases, manifest(cases), approval, transport, phase='canary', mode='mock')
    state = run(cases, manifest(cases), approval, transport, phase='remaining', mode='mock')
    assert len(transport.calls) == 2
    assert state['slots']['WDEV02:U']['status'] == 'error'
    assert all(state['slots'][f'WDEV{i:02}:U']['status'] == 'pending' for i in range(3, 7))


@pytest.mark.parametrize('record_name', ['approval', 'ledger'])
def test_mutated_records_fail_closed(cases, tmp_path, record_name):
    approval, ledger = prepared(cases, tmp_path)
    record_path = approval if record_name == 'approval' else ledger
    record = read(record_path)
    if record_name == 'approval':
        record['budget'] = '99'
    else:
        record['attempts'] = 6
    record_path.write_text(json.dumps(record), encoding='utf-8')
    transport = Scripted()
    with pytest.raises(DatasetError):
        run(cases, manifest(cases), approval, transport, phase='canary', mode='mock')
    assert transport.calls == []


def test_private_evidence_cannot_enter_live_request(cases):
    cases[0]['internal_evidence'][0]['public'] = False
    with pytest.raises(DatasetError):
        make_plan(cases)


def test_real_transport_wrapper_accounting_without_network(cases, tmp_path):
    from types import SimpleNamespace
    from evals.live import BedrockTransport
    class StubClient:
        meta = SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts': 1}))
        def __init__(self):
            self.calls = 0
        def converse(self, **request):
            self.calls += 1
            return response()
    approval, _ = prepared(cases, tmp_path, mode='live')
    client = StubClient()
    state = run(cases, manifest(cases), approval, BedrockTransport(client), phase='canary', mode='live')
    assert client.calls == state['provider_calls'] == state['attempts'] == 1
    assert state['slots']['WDEV01:U']['status'] == 'ok'


def test_directory_lock_also_blocks_alternate_approval_initialization(cases, tmp_path):
    approval, ledger = prepared(cases, tmp_path)
    lock = approval.parent / '.wiki-live.lock'
    lock.write_text('another approval is running', encoding='utf-8')
    alternate = approval.parent / 'alternate-approval.json'
    with pytest.raises(DatasetError):
        initialize(cases, manifest(cases), alternate, ledger,
                   approval_id='alternate', run_id='alternate', budget='2.00', mode='mock')
    assert not alternate.exists()
    assert lock.exists()
