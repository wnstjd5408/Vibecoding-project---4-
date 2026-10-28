"""공통 계층을 앱에 붙인다: 오류 처리기, 요청 id·Origin·헤더 미들웨어, CORS."""

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


async def _handle_supabase_unavailable(request: Request, exc: SupabaseUnavailable):
    return await handle_api_error(request, ApiError("service_unavailable", stage="db"))


async def _handle_supabase_config_error(request: Request, exc: SupabaseConfigError):
    return internal_error_response(request, exc)


def install_common_layer(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(SupabaseUnavailable, _handle_supabase_unavailable)
    app.add_exception_handler(SupabaseConfigError, _handle_supabase_config_error)

    app.add_middleware(CommonMiddleware)
    # 허용 출처만 쿠키를 실어 부를 수 있다. 가장 바깥에 둬서 거부 응답에도 CORS 헤더가 붙는다.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed_origins()),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key"],
        expose_headers=["X-Request-Id", "Retry-After"],
    )
