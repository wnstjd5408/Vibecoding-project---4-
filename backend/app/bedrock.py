"""Bedrock Converse 호출 모듈 (MEG-44).

인증 방식은 설정으로 고른다. 호출 코드와 결과 형식은 두 방식이 같다.
- oidc: 요청의 Vercel OIDC 토큰을 STS 임시 자격증명으로 바꿔 SigV4로 서명한다(기본).
- api_key: 환경변수 AWS_BEARER_TOKEN_BEDROCK의 Bedrock 장기 API 키를 Bearer로 보낸다.

키·토큰·자격증명·역할 ARN은 예외 메시지와 로그에 쓰지 않는다. 실패는 단계와 오류 코드만 남긴다.

호출 한 번은 시간 초과 30초이고 botocore 자동 재시도를 끈다(MEG-86, API spec v0.2 5.2). 재시도는 앱이
ai_ledger에서 한 번만 하고 따로 예약·정산한다. botocore가 몰래 다시 부르면 예약 없는 호출이 생긴다.

Vercel의 PR 미리보기 배포는 AI를 부르지 않는다(MEG-120). Vercel OIDC 토큰의 sub에는 브랜치가 없어
Preview 역할을 staging과 PR 미리보기가 함께 맡을 수 있기 때문이다. 이 검사는 앱 안의 장치이고,
PR 코드가 STS를 직접 부르는 경우는 막지 못한다(infra/README.md "Vercel OIDC 역할" 절).
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

AUTH_OIDC = "oidc"
AUTH_API_KEY = "api_key"
AUTH_MODES = (AUTH_OIDC, AUTH_API_KEY)

API_KEY_ENV = "AWS_BEARER_TOKEN_BEDROCK"

# AI를 부를 수 있는 Preview 배포의 브랜치. 다른 브랜치의 Preview(PR 미리보기)는 막는다.
STAGING_BRANCH = "staging"

# 호출당 시간 초과(API spec 5.2, 제안값). 연결은 따로 짧게 둔다.
CALL_TIMEOUT_SECONDS = 30
CONNECT_TIMEOUT_SECONDS = 5
STS_TIMEOUT_SECONDS = 10


def _no_retry() -> dict:
    """total_max_attempts 1 = 첫 요청만 보내고 botocore는 다시 보내지 않는다.

    botocore가 넘긴 dict에 mode를 써 넣으므로 클라이언트마다 새 dict를 준다.
    """
    return {"total_max_attempts": 1}


# Bedrock이 요청을 거절한 것이 확실한 오류. 과금되지 않은 것으로 보고 예약을 푼다(1.4.4, 과금 여부는 미확인).
REJECTED_CODES = frozenset(
    {"AccessDeniedException", "ThrottlingException", "ValidationException", "ResourceNotFoundException"}
)
# 한 번 더 불러 볼 만한 실패. 앱의 호출 안 재시도 1회만 쓴다(5.2).
RETRYABLE_CODES = frozenset(
    {
        "ThrottlingException",
        "ModelTimeoutException",
        "ModelNotReadyException",
        "InternalServerException",
        "ServiceUnavailableException",
        "ReadTimeoutError",
        "ConnectTimeoutError",
        "EndpointConnectionError",
        "ConnectionClosedError",
    }
)

# 원장 정산 방식(ai_usage_ledger.settle_basis와 released)
SETTLE_USAGE = "usage"
SETTLE_FALLBACK = "reserved_fallback"
SETTLE_RELEASED = "released"


class AiConfigError(ValueError):
    """설정이 잘못됐다. 값은 담지 않고 어떤 설정이 문제인지만 말한다."""


class AiCallError(Exception):
    """AI 호출 실패. step은 environment·sts·bedrock·response, code는 AWS 오류 코드나 중단 사유.

    불완전 응답에 usage가 있었으면 토큰 수를 담아 정산에 쓴다(5.4).
    """

    def __init__(
        self, step: str, code: str, *, input_tokens: int | None = None, output_tokens: int | None = None
    ) -> None:
        super().__init__(f"{step}: {code}")
        self.step = step
        self.code = code
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    @property
    def settlement(self) -> str:
        """원장을 어떻게 끝낼지(API spec 1.4.4). Bedrock에 닿지 않았거나 거절이 확실하면 예약을 푼다."""
        if self.step in ("environment", "sts") or (self.step == "bedrock" and self.code in REJECTED_CODES):
            return SETTLE_RELEASED
        if self.input_tokens is not None and self.output_tokens is not None:
            return SETTLE_USAGE
        # 과금 여부를 모르면 과금으로 센다.
        return SETTLE_FALLBACK

    @property
    def retryable(self) -> bool:
        return self.step == "bedrock" and self.code in RETRYABLE_CODES


@dataclass(frozen=True)
class BedrockSettings:
    auth_mode: str = AUTH_OIDC
    region: str = "ap-northeast-1"
    model_id: str = "global.openai.gpt-6-luna"
    role_arn: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "BedrockSettings":
        env = os.environ if environ is None else environ
        # .env.example처럼 값이 빈 줄은 설정하지 않은 것으로 본다.
        mode = env.get("AI_AUTH_MODE") or AUTH_OIDC
        if mode not in AUTH_MODES:
            raise AiConfigError(f"AI_AUTH_MODE는 {' 또는 '.join(AUTH_MODES)}여야 한다")

        role_arn = env.get("AWS_ROLE_ARN") or None
        if mode == AUTH_OIDC and not role_arn:
            raise AiConfigError("oidc 모드에는 AWS_ROLE_ARN이 필요하다")
        if mode == AUTH_API_KEY and not env.get(API_KEY_ENV):
            raise AiConfigError(f"api_key 모드에는 {API_KEY_ENV}가 필요하다")

        defaults = cls()
        return cls(
            auth_mode=mode,
            region=env.get("BEDROCK_REGION") or defaults.region,
            model_id=env.get("BEDROCK_MODEL_ID") or defaults.model_id,
            role_arn=role_arn,
        )


@dataclass(frozen=True)
class AiResult:
    text: str
    stop_reason: str
    input_tokens: int | None
    output_tokens: int | None


def _error_code(error: ClientError | BotoCoreError) -> str:
    """메시지에는 ARN이 들어갈 수 있어 코드(또는 예외 종류)만 쓴다."""
    if isinstance(error, ClientError):
        return error.response["Error"]["Code"]
    return type(error).__name__


def _assume_role(settings: BedrockSettings, oidc_token: str) -> dict[str, str]:
    try:
        sts = boto3.client(
            "sts",
            region_name=settings.region,
            config=Config(
                signature_version=UNSIGNED,
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                read_timeout=STS_TIMEOUT_SECONDS,
                retries=_no_retry(),
            ),
        )
        return sts.assume_role_with_web_identity(
            RoleArn=settings.role_arn,
            RoleSessionName="cs-learning-ai",
            WebIdentityToken=oidc_token,
            DurationSeconds=900,
        )["Credentials"]
    except (ClientError, BotoCoreError) as error:
        raise AiCallError("sts", _error_code(error)) from None


def is_staging_preview(environ: Mapping[str, str] | None = None) -> bool:
    """staging 브랜치의 Preview 배포인지. Vercel 시스템 환경변수로 판단한다.

    사용자 지정 환경도 VERCEL_ENV가 preview이고 이름은 VERCEL_TARGET_ENV에 들어가므로, 그것도 확인한다.
    """
    env = os.environ if environ is None else environ
    return (
        env.get("VERCEL_ENV") == "preview"
        and (env.get("VERCEL_TARGET_ENV") or "preview") == "preview"
        and env.get("VERCEL_GIT_COMMIT_REF") == STAGING_BRANCH
    )


def ai_allowed_in_environment(environ: Mapping[str, str] | None = None) -> bool:
    """이 배포에서 AI를 불러도 되는지. VERCEL·VERCEL_ENV·VERCEL_GIT_COMMIT_REF는 Vercel이 런타임에 넣는다.

    운영·vercel dev·로컬(Vercel 밖)은 허용하고, Preview는 staging 브랜치만 허용한다.
    Vercel 위(VERCEL 있음)인데 VERCEL_ENV가 없거나 모르는 값이면 막는다.
    """
    env = os.environ if environ is None else environ
    vercel_env = env.get("VERCEL_ENV") or ""
    if not vercel_env:
        return not env.get("VERCEL")
    if vercel_env in ("production", "development"):
        return True
    return is_staging_preview(env)


def ensure_ready(settings: BedrockSettings, oidc_token: str | None = None) -> None:
    """AWS에 요청하기 전에 알 수 있는 실패를 낸다. 원장 예약 전에 불러 행 없이 끝나게 한다(1.4.4)."""
    if not ai_allowed_in_environment():
        raise AiCallError("environment", "BlockedEnvironment")
    if settings.auth_mode == AUTH_OIDC and not oidc_token:
        raise AiConfigError("oidc 모드에는 요청의 OIDC 토큰이 필요하다")


def _runtime_config(**kwargs) -> Config:
    return Config(
        connect_timeout=CONNECT_TIMEOUT_SECONDS, read_timeout=CALL_TIMEOUT_SECONDS, retries=_no_retry(), **kwargs
    )


def make_client(settings: BedrockSettings, oidc_token: str | None = None):
    """설정에 맞는 bedrock-runtime 클라이언트를 만든다."""
    # 두 인증 방식 모두 AWS에 요청하기 전에 막는다.
    ensure_ready(settings, oidc_token)
    if settings.auth_mode == AUTH_API_KEY:
        # boto3가 환경변수의 키를 읽어 Bearer 인증을 고른다.
        return boto3.client("bedrock-runtime", region_name=settings.region, config=_runtime_config())

    credentials = _assume_role(settings, oidc_token)
    return boto3.client(
        "bedrock-runtime",
        region_name=settings.region,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
        # AWS_BEARER_TOKEN_BEDROCK이 환경에 남아 있으면 boto3가 Bearer를 우선한다.
        # 서명 방식을 코드로 고정해 oidc 모드가 키에 끌려가지 않게 한다.
        config=_runtime_config(signature_version="v4"),
    )


def _usage(response: Mapping) -> tuple[int | None, int | None]:
    """응답의 토큰 수. 없거나 음수·정수 아님이면 None이다(원장 check가 0 이상 정수만 받는다)."""
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        return None, None
    tokens = [usage.get("inputTokens"), usage.get("outputTokens")]
    if all(isinstance(t, int) and not isinstance(t, bool) and t >= 0 for t in tokens):
        return tokens[0], tokens[1]
    return None, None


def converse_text(
    client,
    settings: BedrockSettings,
    prompt: str,
    *,
    max_tokens: int,
    effort: str = "none",
) -> AiResult:
    """텍스트 한 번 묻고 답을 받는다. 추론 강도와 maxTokens는 호출마다 명시한다."""
    try:
        response = client.converse(
            modelId=settings.model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": max_tokens},
            additionalModelRequestFields={"reasoning": {"effort": effort}},
        )
    except (ClientError, BotoCoreError) as error:
        raise AiCallError("bedrock", _error_code(error)) from None

    stop_reason = response.get("stopReason") or ""
    input_tokens, output_tokens = _usage(response)
    message = (response.get("output") or {}).get("message") or {}
    blocks = message.get("content")
    # content 자체가 없는 응답도 불완전 응답과 같게 502로 끝낸다(1.4.4). usage가 있으면 정산에 쓴다.
    if not isinstance(blocks, list):
        raise AiCallError("response", "NoContent", input_tokens=input_tokens, output_tokens=output_tokens)
    # text가 문자열이 아닌 블록(null 등)은 버린다. 이런 응답을 예외(500)가 아니라 불완전 응답(502)으로 다룬다.
    text = "".join(
        block["text"] for block in blocks if isinstance(block, Mapping) and isinstance(block.get("text"), str)
    )
    # 응답은 end_turn이고 text가 있을 때만 쓴다. 추론이 예산을 다 쓰면 text 없이 끝난다.
    if stop_reason != "end_turn" or not text:
        raise AiCallError(
            "response", stop_reason or "NoText", input_tokens=input_tokens, output_tokens=output_tokens
        )

    # usage가 없으면 토큰 수가 None이다. 원장은 reserved_fallback으로 정산한다(1.4.4).
    return AiResult(
        text=text,
        stop_reason=stop_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
