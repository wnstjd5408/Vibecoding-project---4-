"""요청 id, Origin 검사, 응답 헤더, 접근 로그 (API spec v0.2 1.2·1.3).

검사 순서 1번(Origin)을 라우팅보다 앞에서 처리한다. 헤더는 오류 응답에도 붙는다.
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import allowed_origins
from app.errors import ApiError, build_error_response, internal_error_response, new_request_id

logger = logging.getLogger("app.access")

STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
API_PREFIX = "/api"


def is_api_path(path: str) -> bool:
    return path == API_PREFIX or path.startswith(API_PREFIX + "/")


def origin_allowed(request: Request) -> bool:
    # Origin 헤더가 없거나 허용 목록에 없으면 거부한다. 로그인·로그아웃도 같다.
    origin = request.headers.get("origin")
    if origin is None:
        return False
    return origin.strip().rstrip("/").lower() in allowed_origins()


class CommonMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        # 클라이언트가 보낸 X-Request-Id는 쓰지 않는다.
        request.state.request_id = new_request_id()
        api = is_api_path(request.url.path)

        if api and request.method in STATE_CHANGING_METHODS and not origin_allowed(request):
            # 허용 목록 밖이었다는 사실만 남기고 Origin 값 원문은 남기지 않는다.
            error = ApiError("origin_not_allowed", stage="origin")
            request.state.error_code, request.state.error_detail, request.state.error_stage = (
                error.code,
                error.detail,
                error.stage,
            )
            response = build_error_response(request.state.request_id, error.code)
        else:
            try:
                response = await call_next(request)
            except Exception as exc:  # 처리기에 닿기 전에 터진 예외도 같은 500 형식으로 낸다.
                response = internal_error_response(request, exc)

        response.headers["X-Request-Id"] = request.state.request_id
        if api:
            response.headers["Cache-Control"] = "private, no-store"
            self._log(request, response, started)
        return response

    @staticmethod
    def _log(request: Request, response: Response, started: float) -> None:
        route = request.scope.get("route")
        # 경로는 id가 들어간 실제 주소가 아니라 틀(/api/notes/{note_id})로 남긴다.
        path = getattr(route, "path", None) or "unmatched"
        state = request.state
        logger.info(
            "request_id=%s method=%s path=%s status=%s code=%s detail=%s stage=%s ms=%d",
            state.request_id,
            request.method,
            path,
            response.status_code,
            getattr(state, "error_code", "-"),
            getattr(state, "error_detail", None) or "-",
            getattr(state, "error_stage", None) or "-",
            (time.perf_counter() - started) * 1000,
        )
