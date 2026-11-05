import copy
import json
import socket
from dataclasses import asdict, replace
from decimal import Decimal
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import eval_staging
from evals import staging
from evals.dataset import _digest, freeze_dataset
from evals.live import BedrockTransport, SDK_CONFIG
from evals.live_output import development_report
from evals.schema import DatasetError
from evals.shared_ledger import SharedLedger
from support import FakeSupabase, build_app, cookie, ALLOWED_ORIGIN
from test_eval_live import response
from test_luna_budget import envelope


@pytest.fixture
def rig(monkeypatch):
    original_connect = socket.socket.connect
    def forbidden(sock, address):
        # Windows asyncio uses a loopback socketpair internally, not an HTTP service.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original_connect(sock, address)
        pytest.fail("external network attempted")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_REF", "staging")
    monkeypatch.setenv("EVAL_APPROVAL_ID", "fixture")
    monkeypatch.setenv("AI_AUTH_MODE", "oidc")
    cases, _, config = envelope(monkeypatch)
    cases[:3] = [replace(c, case_id=s) for c, s in zip(cases[:3], staging.SLOTS)]
    payload = {"cases": [asdict(c) for c in cases],
               "manifest": freeze_dataset(cases, "fixture"), "config": asdict(config)}
    bundle = staging.prepare_bundle(payload)
    approval = dict(run_id=config.run_id, identity_hash=_digest(bundle[3]),
        allowed_slots=staging.SLOTS, budget=config.budget, per_call=str(bundle[4]),
        attempts=0, reserved=0, halted=False)
    attempts, calls, exchanges = {}, [], []
    lock = Lock()
    def api(request):
        with lock:
            if request.method == "GET":
                rows = [approval] if request.url.path.endswith("eval_approvals") else list(attempts.values())
                return httpx.Response(200, json=copy.deepcopy(rows))
            data = json.loads(request.content)
            slot = data["p_slot"]
            if request.url.path.endswith("eval_reserve"):
                if (slot in attempts or approval["halted"] or approval["attempts"] >= 3
                        or data["p_identity"] != approval["identity_hash"]
                        or any(r["status"] in ("started", "unknown", "over_limit") for r in attempts.values())):
                    return httpx.Response(409, json={})
                attempts[slot] = {"slot": slot, "status": "started", "result": None}
                approval["attempts"] += 1
                approval["reserved"] += float(data["p_amount"])
            else:
                row = data["p_result"]
                attempts[slot].update(status=row["status"], result=row)
                approval["halted"] = row["status"] in ("unknown", "over_limit")
            return httpx.Response(200, json=True)
    def ledger():
        return SharedLedger("https://fixture.invalid", "fixture-secret", "fixture",
                            client=httpx.Client(transport=httpx.MockTransport(api)))
    monkeypatch.setattr(eval_staging.SharedLedger, "from_env", ledger)
    def converse(**request):
        calls.append(request)
        return response()
    client = SimpleNamespace(meta=SimpleNamespace(config=SDK_CONFIG), converse=converse, close=lambda: None)
    def transport(token=None):
        exchanges.append(token)
        return BedrockTransport(client)
    monkeypatch.setattr(eval_staging, "oidc_transport", transport)
    fake = FakeSupabase()
    fake.add_user("operator", "op", role="operator")
    fake.add_user("member", "member")
    fake.add_user("inactive", "inactive", role="operator", is_active=False)
    app = build_app(fake)
    app.include_router(eval_staging.router)
    http = TestClient(app)
    def post(path="preflight", token="operator", body=None):
        return http.post("/api/internal/evals/" + path, json=payload if body is None else body,
            headers={"Origin": ALLOWED_ORIGIN, **cookie(token)})
    return SimpleNamespace(post=post, http=http, payload=payload, approval=approval,
        attempts=attempts, calls=calls, exchanges=exchanges, ledger=ledger, client=client, bundle=bundle)


@pytest.mark.parametrize("token,status", [("missing",401),("member",403),("inactive",401)])
def test_auth_denies_without_provider_or_ledger_mutation(rig, token, status):
    assert rig.post("run/D01", token).status_code == status
    assert not rig.calls and not rig.exchanges and not rig.attempts


@pytest.mark.parametrize("key,value", [("VERCEL_ENV","production"),
    ("VERCEL_GIT_COMMIT_REF","meg-138-live-eval"),("EVAL_APPROVAL_ID",""),("AI_AUTH_MODE","api_key")])
def test_environment_closed(rig, monkeypatch, key, value):
    monkeypatch.setenv(key,value)
    assert rig.post().status_code == 404
    assert not rig.exchanges and not rig.attempts


def test_origin_and_get_do_not_execute(rig):
    assert rig.http.post("/api/internal/evals/run/D01", json=rig.payload).status_code == 403
    assert rig.http.get("/api/internal/evals/run/D01").status_code == 404
    assert not rig.calls


def test_preflight_no_reservation_or_model_call(rig):
    r = rig.post()
    assert r.status_code == 200 and r.json()["model_access"] == "unverified"
    assert r.json()["next_slot"] == "D01"
    assert r.headers["cache-control"] == "private, no-store"
    assert len(rig.exchanges) == 1 and not rig.calls and not rig.attempts


def test_auth_exchange_failure_no_reservation(rig, monkeypatch):
    def fail(token=None):
        raise DatasetError("private credential details")
    monkeypatch.setattr(eval_staging, "oidc_transport", fail)
    r = rig.post("run/D01")
    assert r.status_code == 503 and "credential" not in r.text
    assert not rig.calls and not rig.attempts


def test_approval_hash_and_dataset_tampering_blocked(rig):
    rig.payload["cases"][0]["required_concepts"] = ["tampered"]
    assert rig.post("run/D01").status_code == 422
    assert not rig.calls
    rig.approval["identity_hash"] = "other"
    assert rig.post("run/D01", body={"cases":[asdict(c) for c in rig.bundle[0]],
        "manifest":rig.bundle[1], "config":asdict(rig.bundle[2])}).status_code == 503
    assert not rig.exchanges


def test_three_calls_across_fresh_filesystems_and_export(rig):
    for slot in staging.SLOTS:
        assert rig.post("run/" + slot).status_code == 200
        assert rig.post("run/" + slot).status_code == 503
    assert len(rig.calls) == 3 and rig.approval["attempts"] == 3
    state = rig.post("status").json()
    assert state["provider_calls"] == 3
    assert all(row["status"] == "ok" and row["usage"] for row in state["slots"].values())
    report = development_report(rig.bundle[0], state, [])
    assert report["verdict_counts"]["pending"] == 3
    assert report["golden_status"] == "NOT_EVALUATED"
    assert all("grading_evidence" not in json.dumps(req) for req in rig.calls)
    assert rig.post().json()["ready"] is False


def test_wrong_slot_no_exchange(rig):
    for slot in ("D02", "F01", "D04"):
        assert rig.post("run/" + slot).status_code == 503
    assert not rig.calls and not rig.exchanges


@pytest.mark.parametrize("kind", ["unknown", "truncated", "over_limit"])
def test_failure_preserved_blocks_followup(rig, kind):
    rig.client.converse = lambda **kw: response(**(
        {"usage": None} if kind == "unknown" else
        {"stopReason":"max_tokens"} if kind == "truncated" else
        {"usage":{"inputTokens":1050001,"outputTokens":1}}))
    assert rig.post("run/D01").status_code == 200
    assert rig.post("run/D02").status_code == 503
    assert rig.approval["attempts"] == 1
    assert rig.post("status").json()["slots"]["D01"]["status"] != "ok"


def test_reservation_and_finish_failure_no_retry(rig, monkeypatch):
    def fail(*a):
        raise DatasetError("private remote failure")
    monkeypatch.setattr(SharedLedger, "reserve", fail)
    assert rig.post("run/D01").status_code == 503
    assert not rig.calls


def test_finish_failure_persists_started_and_blocks(rig, monkeypatch):
    def fail(*a):
        raise DatasetError("private remote failure")
    monkeypatch.setattr(SharedLedger, "finish", fail)
    assert rig.post("run/D01").status_code == 503
    assert rig.post("run/D01").status_code == 503
    assert rig.post("run/D02").status_code == 503
    assert len(rig.calls) == 1 and rig.attempts["D01"]["status"] == "started"


def test_concurrent_requests_one_provider_call(rig):
    def run():
        ledger = rig.ledger()
        try:
            staging.execute_slot(rig.bundle, ledger, "D01", BedrockTransport(rig.client))
        except DatasetError:
            pass
        finally:
            ledger.client.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: run(), range(2)))
    assert len(rig.calls) == 1 and rig.approval["attempts"] == 1


def test_snapshot_http_error_fails_closed(rig, monkeypatch):
    def ledger():
        return SharedLedger("https://fixture.invalid", "secret", "fixture", client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(503))))
    monkeypatch.setattr(SharedLedger, "from_env", ledger)
    assert rig.post("run/D01").status_code == 503
    assert not rig.exchanges and not rig.calls


def test_oversized_body_rejected_before_exchange(rig):
    r = rig.http.post("/api/internal/evals/preflight", content=" " * 2_000_001,
        headers={"Origin":ALLOWED_ORIGIN, **cookie("operator")})
    assert r.status_code == 413 and not rig.exchanges


def test_request_token_forwarded_without_cross_request_reuse(rig):
    for token in ("request-a", "request-b", None):
        headers = {"Origin": ALLOWED_ORIGIN, **cookie("operator")}
        if token:
            headers["x-vercel-oidc-token"] = token
        assert rig.http.post("/api/internal/evals/preflight", json=rig.payload, headers=headers).status_code == 200
    assert rig.exchanges == ["request-a", "request-b", None]
    assert not rig.calls and not rig.attempts
