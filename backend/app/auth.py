"""세션·활성·역할 의존성 (API spec v0.2 1.2, 기술 검토 3절).

사용자 식별자는 세션에서만 꺼낸다. 권한 판단은 profiles 표가 원본이고, 쿠키나
user_metadata 같은 사용자가 고칠 수 있는 값은 쓰지 않는다.
"""

from dataclasses import dataclass

from fastapi import Depends, Request

from app.config import SESSION_COOKIE
from app.errors import ApiError
from app.supabase import SupabaseClient, get_supabase

OPERATOR_ROLE = "operator"


@dataclass(frozen=True)
class SessionUser:
    user_id: str
    role: str

    @property
    def is_operator(self) -> bool:
        return self.role == OPERATOR_ROLE


def get_session_user(request: Request, supabase: SupabaseClient = Depends(get_supabase)) -> SessionUser | None:
    """살아 있는 세션 + 활성 계정이면 사용자를, 아니면 None을 돌려준다.

    세션 없음·만료·무효, 비활성 계정, profiles 없음을 구분하지 않는다. 로그인이 필요 없는
    요청은 이 값이 None이면 비로그인으로 다룬다. 활성 여부는 요청마다 DB로 확인한다.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user_id = supabase.get_auth_user_id(token)
    if user_id is None:
        return None
    profile = supabase.get_profile(user_id)
    if profile is None or not profile.is_active:
        return None
    return SessionUser(user_id=user_id, role=profile.role)


def require_login(user: SessionUser | None = Depends(get_session_user)) -> SessionUser:
    if user is None:
        raise ApiError("login_required", stage="auth")
    return user


def require_operator(user: SessionUser = Depends(require_login)) -> SessionUser:
    # 방문자는 위에서 항상 401이고, 로그인한 일반 사용자가 운영자 API를 부르면 403이다.
    if not user.is_operator:
        raise ApiError("forbidden", stage="auth")
    return user
