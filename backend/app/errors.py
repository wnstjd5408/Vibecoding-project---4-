"""오류 응답 형식과 영어 고정 문구 카탈로그 (API spec v0.2 1.4).

(code, detail) 하나에 문구 하나다. 카탈로그에 없는 조합은 응답에 나올 수 없다.
"""

import logging
import os
import re
import traceback
import uuid

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.error")

# (code, detail) -> (HTTP 상태, message). 1.4.6 표와 같아야 한다.
CATALOG: dict[tuple[str, str | None], tuple[int, str]] = {
    ("bad_request", "malformed_json"): (400, "Request body is not valid JSON"),
    ("bad_request", "idempotency_key_required"): (400, "Idempotency-Key header is required"),
    ("bad_request", "idempotency_key_invalid"): (400, "Idempotency-Key must be a UUID"),
    ("login_required", None): (401, "Login is required"),
    ("invalid_credentials", None): (401, "Invalid email or password"),
    ("forbidden", None): (403, "Operator permission is required"),
    ("origin_not_allowed", None): (403, "Request origin is not allowed"),
    ("not_found", None): (404, "Resource not found"),
    ("conflict", "already_answered"): (409, "This question has already been answered"),
    ("conflict", "answer_first"): (409, "Answer the question before requesting a follow-up"),
    ("conflict", "followup_limit_reached"): (409, "The follow-up limit for this question has been reached"),
    ("conflict", "in_progress"): (409, "The same request is already in progress"),
    ("conflict", "stale_revision"): (409, "The note has changed since it was loaded"),
    ("conflict", "result_unavailable"): (409, "The result is no longer available; send a new request"),
    ("conflict", "email_exists"): (409, "An account with this email already exists"),
    ("payload_too_large", None): (413, "Request is too large"),
    ("unsupported_media_type", None): (415, "Unsupported file type"),
    ("validation_failed", None): (422, "One or more fields are invalid"),
    ("rate_limited", None): (429, "Too many requests; retry later"),
    ("ai_limit_reached", None): (429, "AI usage limit reached; retry later"),
    ("internal_error", None): (500, "Internal server error"),
    ("ai_unavailable", None): (502, "AI service did not return a usable response"),
    ("service_unavailable", None): (503, "Service temporarily unavailable; retry later"),
}

# fields[].reason별 고정 문구 (1.4.3, 1.4.6)
FIELD_MESSAGES: dict[str, str] = {
    "required": "Value is required",
    "too_long": "Value is too long",
    "out_of_range": "Value is out of range",
    "invalid_format": "Value format is invalid",
    "invalid_value": "Value is not allowed or refers to a missing item",
}


class ApiError(Exception):
    """카탈로그의 (code, detail)로 응답을 만드는 예외."""

    def __init__(
        self,
        code: str,
        detail: str | None = None,
        *,
        fields: list[dict[str, str]] | None = None,
        retry_after_seconds: int | None = None,
        stage: str | None = None,
    ):
        if (code, detail) not in CATALOG:
            raise ValueError(f"unknown error: {code}/{detail}")
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.fields = fields
        self.retry_after_seconds = retry_after_seconds
        # 로그에만 남기는 단계(origin·auth·validate·db·ai·storage)
        self.stage = stage


def new_request_id() -> str:
    return f"r-{uuid.uuid4().hex[:12]}"


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", None) or new_request_id()


def build_error_response(
    request_id: str,
    code: str,
    detail: str | None = None,
    *,
    fields: list[dict[str, str]] | None = None,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    status, message = CATALOG[(code, detail)]
    error: dict = {"code": code, "message": message, "request_id": request_id}
    if detail is not None:
        error["detail"] = detail
    if fields:
        error["fields"] = fields
    headers = {}
    # 429와 409 in_progress에서만 재시도 시간을 준다.
    if retry_after_seconds is not None and (status == 429 or detail == "in_progress"):
        error["retry_after_seconds"] = retry_after_seconds
        headers["Retry-After"] = str(retry_after_seconds)
    return JSONResponse({"error": error}, status_code=status, headers=headers)


def _failure_site(exc: BaseException) -> str:
    """예외 메시지 원문 없이 종류와 마지막 프레임의 파일·줄 번호만 남긴다."""
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return type(exc).__name__
    last = frames[-1]
    return f"{type(exc).__name__} at {os.path.basename(last.filename)}:{last.lineno}"


def internal_error_response(
    request: Request, exc: BaseException, level: int = logging.ERROR
) -> JSONResponse:
    request_id = request_id_of(request)
    request.state.error_code = "internal_error"
    logger.log(level, "request_id=%s stage=internal %s", request_id, _failure_site(exc))
    return build_error_response(request_id, "internal_error")


def _reason_of(error: dict) -> str:
    kind = error.get("type", "")
    if kind == "missing" or kind == "string_too_short":
        return "required"
    if kind in ("string_too_long", "too_long"):
        return "too_long"
    if kind.startswith(("greater_than", "less_than")):
        return "out_of_range"
    if kind in ("enum", "literal_error"):
        return "invalid_value"
    return "invalid_format"


_LOCATIONS = ("body", "query", "path", "header", "cookie")
# 스키마에 있는 필드 이름 모양(점으로 중첩). 사용자가 보낸 임의 키가 응답에 되비치지 않게 한다.
_SAFE_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*")
_MAX_FIELD_NAME = 100


def _field_name(error: dict) -> str:
    loc = [str(part) for part in error.get("loc", ())]
    if loc and loc[0] in _LOCATIONS:
        loc = loc[1:]
    # 모델에 없는 키(extra_forbidden)의 이름은 사용자가 정한 값이라 쓰지 않는다.
    if error.get("type") == "extra_forbidden" and loc:
        loc = loc[:-1]
    name = ".".join(loc)
    if not name or len(name) > _MAX_FIELD_NAME or not _SAFE_FIELD_NAME.fullmatch(name):
        return "body"
    return name


async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    request.state.error_code = exc.code
    request.state.error_detail = exc.detail
    request.state.error_stage = exc.stage
    return build_error_response(
        request_id_of(request),
        exc.code,
        exc.detail,
        fields=exc.fields,
        retry_after_seconds=exc.retry_after_seconds,
    )


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    # 본문이 JSON으로 읽히지 않으면 필드 오류가 아니라 400이다.
    if any(e.get("type") == "json_invalid" for e in errors):
        return await handle_api_error(request, ApiError("bad_request", "malformed_json", stage="validate"))
    fields = []
    for error in errors:
        reason = _reason_of(error)
        # 입력 값은 되돌려 주지 않는다. 이름·사유·고정 문구만 낸다.
        fields.append({"name": _field_name(error), "reason": reason, "message": FIELD_MESSAGES[reason]})
    return await handle_api_error(request, ApiError("validation_failed", fields=fields, stage="validate"))


# 라우터·Starlette·엔드포인트가 던지는 HTTPException을 카탈로그의 응답으로 바꾼다.
# 405는 404 not_found로 맞춘다(카탈로그에 405가 없고 대상 유무를 구분해 알리지 않는다).
_HTTP_STATUS_TO_ERROR: dict[int, tuple[str, str | None]] = {
    400: ("bad_request", "malformed_json"),
    401: ("login_required", None),
    403: ("forbidden", None),
    404: ("not_found", None),
    405: ("not_found", None),
    413: ("payload_too_large", None),
    415: ("unsupported_media_type", None),
    422: ("validation_failed", None),
    429: ("rate_limited", None),
}


async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    mapped = _HTTP_STATUS_TO_ERROR.get(exc.status_code)
    if mapped is not None:
        return await handle_api_error(request, ApiError(*mapped))
    # 카탈로그에 대응이 없는 상태는 500으로 내되 서버 실패가 아니라 경고로 남긴다.
    level = logging.WARNING if 400 <= exc.status_code < 500 else logging.ERROR
    return internal_error_response(request, exc, level)
