"""공통 계층을 앱에 붙인다: 오류 처리기, 요청 id·Origin·헤더 미들웨어, CORS."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import allowed_origins
from app.errors import (
    ApiError,
    handle_api_error,
    handle_http_exception,
    handle_validation_error,
    internal_error_response,
)
from app.middleware import CommonMiddleware
from app.supabase import SupabaseConfigError, SupabaseUnavailable


def _configure_logging() -> None:
    """app.* 로거의 INFO 접근 로그가 버려지지 않게 한다. 루트 로거 설정이 없을 때만 핸들러를 단다."""
    logger = logging.getLogger("app")
    logger.setLevel(logging.INFO)
    if not logging.getLogger().handlers and not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)


# 이 전역 처리기는 요청 처리 중 어디서든 난 Supabase 장애를 503으로 바꾼다.
# API spec 1.4.4: AI 호출이 끝난 뒤의 DB 실패는 503이 아니라 500이다. 그 구간을 가진 엔드포인트는
# 이 예외를 직접 잡아 internal_error로 바꿔야 한다(E09·E11·E13 구현 때).
async def _handle_supabase_unavailable(request: Request, exc: SupabaseUnavailable):
    return await handle_api_error(request, ApiError("service_unavailable", stage="db"))


async def _handle_supabase_config_error(request: Request, exc: SupabaseConfigError):
    return internal_error_response(request, exc)


def install_common_layer(app: FastAPI) -> None:
    _configure_logging()
    # 설정 오류는 여기서 터져 잘못된 허용 출처로 뜨지 않게 한다.
    app.state.allowed_origins = allowed_origins()
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(SupabaseUnavailable, _handle_supabase_unavailable)
    app.add_exception_handler(SupabaseConfigError, _handle_supabase_config_error)

    app.add_middleware(CommonMiddleware)
    # 허용 출처만 쿠키를 실어 부를 수 있다. 가장 바깥에 둬서 거부 응답에도 CORS 헤더가 붙는다.
    # CORS preflight(OPTIONS) 응답은 이 미들웨어가 직접 내므로 X-Request-Id·Cache-Control과 1.4 오류 형식이
    # 붙지 않는다. 브라우저 보조 요청이고 상태를 바꾸지 않아 규약의 예외로 둔다.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(app.state.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key"],
        expose_headers=["X-Request-Id", "Retry-After"],
    )
