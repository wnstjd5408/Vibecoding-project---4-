"""임시 Bedrock 확인 API (MEG-120). 네트워크·AWS 없이 돈다."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import ai_probe
from app.bedrock import AiCallError, AiResult
from app.common import install_common_layer
from app.supabase import get_supabase
from support import FakeSupabase

FAKE_TOKEN = "fake.oidc.token-for-probe"
FAKE_ROLE = "arn:aws:iam::123456789012:role/fake-probe-role"
MODEL_TEXT = "pong and some model words"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "VERCEL",
        "VERCEL_ENV",
        "VERCEL_TARGET_ENV",
        "VERCEL_GIT_COMMIT_REF",
        "VERCEL_REGION",
        "AI_AUTH_MODE",
        "AWS_BEARER_TOKEN_BEDROCK",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ROLE_ARN", FAKE_ROLE)


@pytest.fixture
def staging(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_REF", "staging")


@pytest.fixture
def fake():
    return FakeSupabase()


@pytest.fixture
def client(fake):
    app = FastAPI()
    install_common_layer(app)
    app.dependency_overrides[get_supabase] = lambda: fake
    app.include_router(ai_probe.router)
    return TestClient(app)


@pytest.fixture
def aws(monkeypatch):
    """make_client·converse_text를 바꿔 끼운다. calls에 호출 순서가 남는다."""
    state = {"calls": [], "client_error": None, "converse_error": None}

    def fake_make_client(settings, oidc_token=None):
        state["calls"].append(("make_client", oidc_token))
        if state["client_error"]:
            raise state["client_error"]
        return "bedrock-client"

    def fake_converse(client, settings, prompt, *, max_tokens, effort="none"):
        state["calls"].append(("converse", max_tokens))
        if state["converse_error"]:
            raise state["converse_error"]
        return AiResult(text=MODEL_TEXT, stop_reason="end_turn", input_tokens=9, output_tokens=3)

    monkeypatch.setattr(ai_probe, "make_client", fake_make_client)
    monkeypatch.setattr(ai_probe, "converse_text", fake_converse)
    return state


def probe(client, token=FAKE_TOKEN):
    headers = {"x-vercel-oidc-token": token} if token else {}
    return client.get("/api/dev/ai-probe", headers=headers)


def assert_no_secrets(response, caplog):
    for text in (response.text, caplog.text):
        assert FAKE_TOKEN not in text
        assert FAKE_ROLE not in text
        assert "123456789012" not in text
        assert MODEL_TEXT not in text


# --- AC-2: staging에서만 동작 ---


@pytest.mark.parametrize(
    "vercel_env, ref",
    [
        (None, None),
        ("production", "main"),
        ("development", None),
        ("preview", "meg-9-feature"),
        ("preview", None),
        ("preview", "Staging"),
    ],
)
def test_probe_is_not_found_outside_staging(monkeypatch, client, aws, fake, vercel_env, ref):
    if vercel_env:
        monkeypatch.setenv("VERCEL_ENV", vercel_env)
    if ref:
        monkeypatch.setenv("VERCEL_GIT_COMMIT_REF", ref)

    response = probe(client)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert aws["calls"] == []
    # 환경 검사가 먼저라서 호출 횟수도 세지 않는다.
    assert fake.rpc_calls == []


def test_probe_on_staging_reports_steps_without_secrets(staging, client, aws, caplog, monkeypatch):
    monkeypatch.setenv("VERCEL_REGION", "hnd1")
    caplog.set_level(logging.DEBUG)

    response = probe(client)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["step"] == "done"
    assert body["reply_ok"] is True
    assert body["output_tokens"] == 3
    assert body["region"] == "hnd1"
    assert isinstance(body["credentials_ms"], int) and isinstance(body["bedrock_ms"], int)
    assert aws["calls"] == [("make_client", FAKE_TOKEN), ("converse", ai_probe.PROBE_MAX_TOKENS)]
    assert response.headers["cache-control"] == "private, no-store"
    assert_no_secrets(response, caplog)


def test_probe_reports_sts_failure_as_step_and_code(staging, client, aws, caplog):
    caplog.set_level(logging.DEBUG)
    aws["client_error"] = AiCallError("sts", "AccessDenied")

    response = probe(client)

    assert response.status_code == 200
    body = response.json()
    assert (body["ok"], body["step"], body["code"]) == (False, "sts", "AccessDenied")
    assert body["bedrock_ms"] is None
    assert [name for name, _ in aws["calls"]] == ["make_client"]
    assert_no_secrets(response, caplog)


def test_probe_reports_bedrock_failure(staging, client, aws, caplog):
    caplog.set_level(logging.DEBUG)
    aws["converse_error"] = AiCallError("response", "max_tokens")

    body = probe(client).json()

    assert (body["ok"], body["step"], body["code"]) == (False, "response", "max_tokens")
    assert isinstance(body["credentials_ms"], int)


def test_probe_without_token_does_not_call_aws(staging, client, aws):
    body = probe(client, token=None).json()

    assert (body["ok"], body["step"], body["code"]) == (False, "token", "MissingToken")
    assert aws["calls"] == []


def test_probe_reports_config_error_without_value(staging, client, aws, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.delenv("AWS_ROLE_ARN")

    response = probe(client)

    body = response.json()
    assert (body["ok"], body["step"], body["code"]) == (False, "config", "AiConfigError")
    assert aws["calls"] == []
    assert_no_secrets(response, caplog)


# --- AC-3: 호출 상한 ---


def test_probe_is_rate_limited_per_hour(staging, client, aws):
    statuses = [probe(client).status_code for _ in range(ai_probe.AI_PROBE.limit + 1)]

    assert statuses[:-1] == [200] * ai_probe.AI_PROBE.limit
    assert statuses[-1] == 429
    assert ai_probe.AI_PROBE.window_seconds == 3600
    assert len([name for name, _ in aws["calls"] if name == "make_client"]) == ai_probe.AI_PROBE.limit


def test_probe_is_not_in_openapi_schema(client):
    assert "/api/dev/ai-probe" not in client.get("/openapi.json").json()["paths"]


# --- 리뷰 반영: oidc 경로만 성공으로 본다, 토큰 모호성, 예상 밖 예외, 실제 경로의 비노출 ---


def test_probe_in_api_key_mode_fails_without_calling_aws(staging, client, aws, monkeypatch):
    monkeypatch.setenv("AI_AUTH_MODE", "api_key")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "fake-key-not-used")

    response = probe(client)

    body = response.json()
    assert (body["ok"], body["step"], body["code"]) == (False, "config", "NotOidcMode")
    assert aws["calls"] == []
    assert "fake-key-not-used" not in response.text


def test_probe_rejects_duplicate_token_headers(staging, client, aws):
    # 같은 이름의 헤더를 두 번 보낸다. 두 번째는 클라이언트가 직접 넣은 값이라고 가정한다.
    duplicated = [(ai_probe.OIDC_HEADER, value) for value in (FAKE_TOKEN, "second-value")]
    response = client.get("/api/dev/ai-probe", headers=duplicated)

    body = response.json()
    assert (body["ok"], body["step"], body["code"]) == (False, "token", "AmbiguousToken")
    assert aws["calls"] == []
    assert FAKE_TOKEN not in response.text


def assert_unexpected_error_reported(client, caplog, expected_step):
    response = probe(client)

    assert response.status_code == 200
    body = response.json()
    assert (body["ok"], body["step"], body["code"]) == (False, expected_step, "KeyError")
    assert_no_secrets(response, caplog)


def test_probe_reports_unexpected_exception_while_building_client(staging, client, aws, caplog):
    caplog.set_level(logging.DEBUG)
    aws["client_error"] = KeyError(f"detail with {FAKE_ROLE}")

    assert_unexpected_error_reported(client, caplog, "credentials")


def test_probe_reports_unexpected_exception_while_calling_model(staging, client, aws, caplog):
    caplog.set_level(logging.DEBUG)
    aws["converse_error"] = KeyError(f"detail with {FAKE_ROLE}")

    assert_unexpected_error_reported(client, caplog, "bedrock")


def test_probe_through_real_client_does_not_leak_arn(staging, client, caplog, monkeypatch):
    """실제 make_client를 지나게 하고 STS만 바꾼다. AWS 오류 메시지에 든 ARN이 밖으로 나가지 않는다."""
    from botocore.exceptions import ClientError

    from app import bedrock

    caplog.set_level(logging.DEBUG)
    seen = {}

    class FakeSts:
        def assume_role_with_web_identity(self, **kwargs):
            seen.update(kwargs)
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": f"not authorized: {FAKE_ROLE}"}}, "Op")

    monkeypatch.setattr(bedrock.boto3, "client", lambda name, **kwargs: FakeSts())

    response = probe(client)

    body = response.json()
    assert (body["ok"], body["step"], body["code"]) == (False, "sts", "AccessDenied")
    # 역할 ARN과 토큰은 STS 요청에만 쓰였다.
    assert seen["RoleArn"] == FAKE_ROLE and seen["WebIdentityToken"] == FAKE_TOKEN
    assert_no_secrets(response, caplog)


def test_probe_when_counter_db_is_down_returns_503_without_aws(staging, client, aws, fake):
    fake.down = True

    response = probe(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert aws["calls"] == []
