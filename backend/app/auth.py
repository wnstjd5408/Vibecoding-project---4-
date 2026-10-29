"""세션·활성·역할 의존성 (API spec v0.2 1.2, 기술 검토 3절).

사용자 식별자는 세션에서만 꺼낸다. 권한 판단은 profiles 표가 원본이고, 쿠키나
user_metadata 같은 사용자가 고칠 수 있는 값은 쓰지 않는다.
"""

from dataclasses import dataclass

from fastapi import Depends, Request

from app.config import REFRESH_COOKIE, SESSION_COOKIE
from app.errors import ApiError
from app.session import decode_refresh_cookie, has_session_cookie, stage_clear, stage_session
from app.supabase import SupabaseClient, get_supabase

OPERATOR_ROLE = "operator"


@dataclass(frozen=True)
class SessionUser:
    user_id: str
    role: str
    display_name: str | None = None

    @property
    def is_operator(self) -> bool:
        return self.role == OPERATOR_ROLE


def _refreshed_user_id(request: Request, supabase: SupabaseClient) -> str | None:
    """액세스 토큰이 없거나 거절됐을 때 리프레시 쿠키로 세션을 이어 간다.

    리프레시 쿠키가 없거나 서명·만료가 틀리거나 Auth가 거절하면 None이다. 새 토큰은 같은 만료 시각으로
    쿠키에 다시 싣는다(로그인부터 7일 고정). Auth 장애(SupabaseUnavailable)는 그대로 올려 503이 되고,
    이때 쿠키는 지우지 않는다(다음 요청이 다시 시도한다).
    """
    cookie = decode_refresh_cookie(supabase.keyed_hash, request.cookies.get(REFRESH_COOKIE))
    if cookie is None:
        return None
    session = supabase.refresh_session(cookie.refresh_token)
    if session is None:
        return None
    stage_session(
        request, supabase.keyed_hash, session.access_token, session.refresh_token, session.expires_in, cookie.deadline
    )
    return session.user_id


def get_session_user(request: Request, supabase: SupabaseClient = Depends(get_supabase)) -> SessionUser | None:
    """살아 있는 세션 + 활성 계정이면 사용자를, 아니면 None을 돌려준다.

    세션 없음·만료·무효, 비활성 계정, profiles 없음을 구분하지 않는다. 로그인이 필요 없는
    요청은 이 값이 None이면 비로그인으로 다룬다. 활성 여부는 요청마다 DB로 확인한다.
    액세스 토큰이 만료됐으면 리프레시 쿠키로 한 번 갱신하고, 갱신도 안 되면 세션 쿠키를 지운다.
    FastAPI가 한 요청 안에서 이 의존성 결과를 재사용하므로 갱신은 요청당 최대 한 번이다.
    """
    token = request.cookies.get(SESSION_COOKIE)
    user_id = supabase.get_auth_user_id(token) if token else None
    if user_id is None:
        user_id = _refreshed_user_id(request, supabase)
    if user_id is None:
        if has_session_cookie(request):
            stage_clear(request)
        return None
    profile = supabase.get_profile(user_id)
    if profile is None or not profile.is_active:
        return None
    return SessionUser(user_id=user_id, role=profile.role, display_name=profile.display_name)


def require_login(user: SessionUser | None = Depends(get_session_user)) -> SessionUser:
    if user is None:
        raise ApiError("login_required", stage="auth")
    return user


def require_operator(user: SessionUser = Depends(require_login)) -> SessionUser:
    # 방문자는 위에서 항상 401이고, 로그인한 일반 사용자가 운영자 API를 부르면 403이다.
    if not user.is_operator:
        raise ApiError("forbidden", stage="auth")
    return user
