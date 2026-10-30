"""임시 Bedrock 확인 API (MEG-120). MEG-118의 staging 검증이 끝나면 이 파일과 main.py의 연결을 지운다.

배포된 staging 런타임에서 요청의 실제 Vercel OIDC 토큰 → STS → Bedrock 경로가 되는지 한 번 확인한다.
로컬 자격증명이나 API 키 호출로는 이 경로를 증명할 수 없어서 따로 둔다. 그래서 oidc 모드가 아니면 실패로 답한다.

접근 제한(2026-10-29 사람 결정):
- staging 브랜치의 Preview 배포에서만 동작한다. 그 밖에서는 404다(운영·로컬·PR 미리보기 포함).
- staging URL은 Vercel 배포 보호(SSO)가 걸려 있어 팀원이나 보호 우회 토큰만 닿는다.
- 호출 상한은 시간당 5회다(DB 카운터). 로그인한 요청은 사용자별, 아니면 IP별로 센다.
  한 번에 합성 문장 하나, 짧은 응답만 요청한다.

응답에는 단계·지연·성공 여부·AWS 오류 코드(또는 예외 종류)만 담는다. 토큰·자격증명·역할 ARN·모델 응답 원문은
응답과 로그에 넣지 않는다. 오류도 200으로 돌려준다. 진단용이라 1.4 오류 형식(카탈로그)을 따르지 않는다.
"""

import logging
import os
import time

from fastapi import APIRouter, Depends, Request

from app.bedrock import (
    AUTH_OIDC,
    AiCallError,
    AiConfigError,
    BedrockSettings,
    converse_text,
    is_staging_preview,
    make_client,
)
from app.errors import ApiError
from app.rate_limit import RateRule, rate_limited

logger = logging.getLogger("app.ai_probe")

router = APIRouter(prefix="/api/dev")

OIDC_HEADER = "x-vercel-oidc-token"
AI_PROBE = RateRule("ai_probe", 5, 60 * 60)
PROBE_PROMPT = "Reply with exactly one word: pong"
PROBE_MAX_TOKENS = 64


def staging_only() -> None:
    """staging Preview가 아니면 경로가 없는 것처럼 404를 낸다. 호출 횟수를 세기 전에 검사한다."""
    if not is_staging_preview():
        raise ApiError("not_found")


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


@router.get(
    "/ai-probe",
    include_in_schema=False,
    dependencies=[Depends(staging_only), Depends(rate_limited(AI_PROBE))],
)
def ai_probe(request: Request) -> dict:
    result = {
        "ok": False,
        "step": None,
        "code": None,
        # STS 교환과 boto3 클라이언트 생성을 합친 시간이다. 콜드 스타트면 클라이언트 생성이 크다.
        "credentials_ms": None,
        "bedrock_ms": None,
        "reply_ok": None,
        "output_tokens": None,
        "region": os.environ.get("VERCEL_REGION"),
    }

    def failed(step: str, code: str) -> dict:
        logger.info("ai probe failed step=%s code=%s", step, code)
        return {**result, "step": step, "code": code}

    try:
        settings = BedrockSettings.from_env()
    except AiConfigError:
        return failed("config", "AiConfigError")
    if settings.auth_mode != AUTH_OIDC:
        return failed("config", "NotOidcMode")

    # 같은 이름의 헤더가 여럿이면 런타임이 넣은 토큰인지 알 수 없으므로 쓰지 않는다.
    tokens = request.headers.getlist(OIDC_HEADER)
    if not tokens:
        return failed("token", "MissingToken")
    if len(tokens) > 1:
        return failed("token", "AmbiguousToken")

    start = time.perf_counter()
    try:
        client = make_client(settings, tokens[0])
    except AiCallError as error:
        return failed(error.step, error.code)
    except Exception as error:  # 진단용이라 어떤 실패든 단계와 예외 종류로 돌려준다. 메시지는 쓰지 않는다.
        return failed("credentials", type(error).__name__)
    result["credentials_ms"] = _elapsed_ms(start)

    start = time.perf_counter()
    try:
        reply = converse_text(client, settings, PROBE_PROMPT, max_tokens=PROBE_MAX_TOKENS)
    except AiCallError as error:
        return failed(error.step, error.code)
    except Exception as error:
        return failed("bedrock", type(error).__name__)
    result["bedrock_ms"] = _elapsed_ms(start)

    logger.info("ai probe ok credentials_ms=%s bedrock_ms=%s", result["credentials_ms"], result["bedrock_ms"])
    return {
        **result,
        "ok": True,
        "step": "done",
        # 모델 응답은 돌려주지 않고 기대한 단어가 있었는지만 알린다.
        "reply_ok": "pong" in reply.text.lower(),
        "output_tokens": reply.output_tokens,
    }
