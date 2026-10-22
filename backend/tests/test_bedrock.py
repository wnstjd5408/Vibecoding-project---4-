import io
import json
from types import SimpleNamespace

import boto3
import pytest
from botocore.awsrequest import AWSResponse
from botocore.exceptions import ClientError, ConnectTimeoutError

from app import bedrock
from app.bedrock import (
    AiCallError,
    AiConfigError,
    BedrockSettings,
    call_bedrock,
    converse_text,
    make_client,
)

FAKE_KEY = "fake-api-key-for-tests"
FAKE_TOKEN = "fake.oidc.token"
FAKE_CREDENTIALS = {
    "AccessKeyId": "test-access-key-id",
    "SecretAccessKey": "fake-secret",
    "SessionToken": "fake-session",
}
GOOD_RESPONSE = {
    "output": {"message": {"role": "assistant", "content": [{"text": "pong"}]}},
    "stopReason": "end_turn",
    "usage": {"inputTokens": 5, "outputTokens": 2, "totalTokens": 7},
    "metrics": {"latencyMs": 1},
}


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "arn:aws:iam::1:role/x"}}, "Op")


class RawBody(io.BytesIO):
    def stream(self, *args, **kwargs):
        yield self.getvalue()


def sent_auth_scheme(client) -> str:
    """네트워크 없이 요청이 어떤 인증 헤더로 나가는지 읽는다."""
    seen = {}

    def before_send(request, **_):
        auth = request.headers.get("Authorization", b"")
        auth = auth.decode() if isinstance(auth, bytes) else auth
        seen["scheme"] = "bearer" if auth.startswith("Bearer") else "sigv4"
        body = json.dumps(GOOD_RESPONSE).encode()
        return AWSResponse(request.url, 200, {}, RawBody(body))

    client.meta.events.register("before-send.bedrock-runtime.Converse", before_send)
    client.converse(modelId="m", messages=[{"role": "user", "content": [{"text": "hi"}]}])
    return seen["scheme"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "AI_AUTH_MODE",
        "AWS_ROLE_ARN",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "BEDROCK_REGION",
        "BEDROCK_MODEL_ID",
    ):
        monkeypatch.delenv(name, raising=False)


# --- 설정 ---


def test_defaults_to_oidc_and_needs_role_arn():
    with pytest.raises(AiConfigError, match="AWS_ROLE_ARN"):
        BedrockSettings.from_env({})

    settings = BedrockSettings.from_env({"AWS_ROLE_ARN": "role"})

    assert settings.auth_mode == "oidc"
    assert settings.model_id == "global.openai.gpt-6-luna"
    assert settings.region == "ap-northeast-1"


def test_api_key_mode_needs_key_in_env():
    with pytest.raises(AiConfigError, match="AWS_BEARER_TOKEN_BEDROCK"):
        BedrockSettings.from_env({"AI_AUTH_MODE": "api_key"})

    settings = BedrockSettings.from_env(
        {"AI_AUTH_MODE": "api_key", "AWS_BEARER_TOKEN_BEDROCK": FAKE_KEY}
    )

    assert settings.auth_mode == "api_key"


def test_unknown_mode_is_rejected():
    with pytest.raises(AiConfigError, match="AI_AUTH_MODE"):
        BedrockSettings.from_env({"AI_AUTH_MODE": "iam_user", "AWS_ROLE_ARN": "role"})


def test_model_id_comes_from_settings():
    settings = BedrockSettings.from_env(
        {"AWS_ROLE_ARN": "role", "BEDROCK_MODEL_ID": "other.model"}
    )

    assert settings.model_id == "other.model"


def test_config_errors_and_settings_do_not_contain_secrets():
    env = {"AI_AUTH_MODE": "api_key", "AWS_BEARER_TOKEN_BEDROCK": FAKE_KEY}
    settings = BedrockSettings.from_env(env)

    assert FAKE_KEY not in repr(settings)
    with pytest.raises(AiConfigError) as error:
        BedrockSettings.from_env({**env, "AI_AUTH_MODE": "bad"})
    assert FAKE_KEY not in str(error.value)


# --- 클라이언트 생성 (두 모드) ---


def test_api_key_client_has_no_explicit_credentials(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        bedrock.boto3, "client", lambda name, **kwargs: captured.update(name=name, **kwargs)
    )

    make_client(BedrockSettings(auth_mode="api_key"))

    assert captured == {"name": "bedrock-runtime", "region_name": "ap-northeast-1"}


def test_oidc_client_uses_exchanged_credentials_and_pins_sigv4(monkeypatch):
    clients = []

    def fake_client(name, **kwargs):
        clients.append((name, kwargs))
        if name == "sts":
            return SimpleNamespace(
                assume_role_with_web_identity=lambda **_: {"Credentials": FAKE_CREDENTIALS}
            )
        return "bedrock-client"

    monkeypatch.setattr(bedrock.boto3, "client", fake_client)

    result = make_client(BedrockSettings(role_arn="role"), FAKE_TOKEN)

    assert result == "bedrock-client"
    name, kwargs = clients[-1]
    assert name == "bedrock-runtime"
    assert kwargs["aws_access_key_id"] == FAKE_CREDENTIALS["AccessKeyId"]
    assert kwargs["config"].signature_version == "v4"


def test_oidc_mode_without_token_is_a_config_error():
    with pytest.raises(AiConfigError):
        make_client(BedrockSettings(role_arn="role"), None)


def test_oidc_exchange_failure_reports_step_and_code_only(monkeypatch):
    def deny(**_):
        raise client_error("AccessDenied")

    sts = SimpleNamespace(assume_role_with_web_identity=deny)
    monkeypatch.setattr(bedrock.boto3, "client", lambda *a, **k: sts)

    with pytest.raises(AiCallError) as error:
        make_client(BedrockSettings(role_arn="role"), FAKE_TOKEN)

    assert (error.value.step, error.value.code) == ("sts", "AccessDenied")
    assert "arn:" not in str(error.value)
    assert FAKE_TOKEN not in str(error.value)


# --- 인증 헤더 (실제 boto3, 네트워크 없음) ---


def test_api_key_mode_sends_bearer(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", FAKE_KEY)

    client = make_client(BedrockSettings(auth_mode="api_key"))

    assert sent_auth_scheme(client) == "bearer"


def test_oidc_mode_signs_with_sigv4_even_if_api_key_env_is_left_set(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", FAKE_KEY)
    monkeypatch.setattr(bedrock, "_assume_role", lambda *a: FAKE_CREDENTIALS)

    client = make_client(BedrockSettings(role_arn="role"), FAKE_TOKEN)

    assert sent_auth_scheme(client) == "sigv4"


def test_plain_boto3_would_pick_bearer_over_explicit_keys(monkeypatch):
    """코드로 서명 방식을 고정하지 않으면 키가 이긴다. 위 고정 코드가 필요한 이유."""
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", FAKE_KEY)
    client = boto3.client(
        "bedrock-runtime",
        region_name="ap-northeast-1",
        aws_access_key_id="test-access-key-id",
        aws_secret_access_key="fake-secret",
    )

    assert sent_auth_scheme(client) == "bearer"


# --- 호출 결과 (두 모드가 같은 코드·같은 형식) ---


def test_both_modes_return_the_same_result_shape(monkeypatch):
    fake_bedrock = SimpleNamespace(converse=lambda **_: GOOD_RESPONSE)
    monkeypatch.setattr(bedrock, "make_client", lambda *a, **k: fake_bedrock)

    oidc = call_bedrock(
        BedrockSettings(role_arn="role"), "ping", max_tokens=50, oidc_token=FAKE_TOKEN
    )
    api_key = call_bedrock(BedrockSettings(auth_mode="api_key"), "ping", max_tokens=50)

    assert oidc == api_key
    assert (oidc.text, oidc.stop_reason, oidc.input_tokens, oidc.output_tokens) == (
        "pong",
        "end_turn",
        5,
        2,
    )


def test_converse_passes_model_limits_and_reasoning_effort():
    seen = {}

    def converse(**kwargs):
        seen.update(kwargs)
        return GOOD_RESPONSE

    settings = BedrockSettings(auth_mode="api_key", model_id="other.model")
    converse_text(SimpleNamespace(converse=converse), settings, "ping", max_tokens=40, effort="low")

    assert seen["modelId"] == "other.model"
    assert seen["inferenceConfig"] == {"maxTokens": 40}
    assert seen["additionalModelRequestFields"] == {"reasoning": {"effort": "low"}}


# --- 실패 경로 (만료·무효 키 포함) ---


@pytest.mark.parametrize(
    "code", ["ExpiredTokenException", "UnrecognizedClientException", "AccessDeniedException"]
)
def test_bad_or_expired_key_fails_with_code_only(code):
    def deny(**_):
        raise client_error(code)

    with pytest.raises(AiCallError) as error:
        converse_text(
            SimpleNamespace(converse=deny),
            BedrockSettings(auth_mode="api_key"),
            "ping",
            max_tokens=50,
        )

    assert (error.value.step, error.value.code) == ("bedrock", code)
    assert "arn:" not in str(error.value)
    assert error.value.__cause__ is None


def test_network_errors_report_the_exception_type():
    def timeout(**_):
        raise ConnectTimeoutError(endpoint_url="https://bedrock-runtime.example")

    with pytest.raises(AiCallError) as error:
        converse_text(
            SimpleNamespace(converse=timeout),
            BedrockSettings(auth_mode="api_key"),
            "ping",
            max_tokens=50,
        )

    assert error.value.code == "ConnectTimeoutError"
    assert "example" not in str(error.value)


def test_truncated_or_empty_answers_are_not_used():
    truncated = {
        "output": {"message": {"role": "assistant", "content": [{"reasoningContent": {}}]}},
        "stopReason": "max_tokens",
    }

    with pytest.raises(AiCallError) as error:
        converse_text(
            SimpleNamespace(converse=lambda **_: truncated),
            BedrockSettings(auth_mode="api_key"),
            "ping",
            max_tokens=20,
        )

    assert (error.value.step, error.value.code) == ("response", "max_tokens")
