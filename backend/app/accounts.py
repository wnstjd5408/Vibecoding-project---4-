"""E01~E03·E24 계정: 로그인, 로그아웃, 내 상태, 운영자 발급 (API spec v0.2 2.2·2.4, 1.2).

로그인은 FastAPI가 Supabase Auth를 대신 부른다. 브라우저는 세션 쿠키만 가진다(D-007, D-032).
"""

import logging

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic_core import PydanticCustomError

from app.auth import SessionUser, forwarded_ip, get_session_user, require_operator, revoke_quietly
from app.config import REFRESH_COOKIE, SESSION_COOKIE
from app.errors import FIELD_MESSAGES, ApiError, request_id_of
from app.net import client_ip, ip_bucket
from app.rate_limit import LOGIN_FAILURE, LOGIN_IP, WRITE, RateLimiter, get_rate_limiter
from app.session import decode_refresh_cookie, new_deadline, stage_clear, stage_session
from app.supabase import AccountInputRejected, EmailExists, SupabaseClient, get_supabase

logger = logging.getLogger("app.accounts")

router = APIRouter(prefix="/api")


class CreateAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(min_length=1, max_length=320)
    display_name: str = Field(min_length=1, max_length=100)
    initial_password: str = Field(min_length=1, max_length=1024, repr=False)

    @field_validator("initial_password")
    @classmethod
    def password_bytes(cls, value: str) -> str:
        # Auth의 bcrypt 한계는 문자 수가 아닌 UTF-8 바이트 수다. 조용한 잘림을 막는다.
        if len(value.encode("utf-8")) > 72:
            raise PydanticCustomError("string_too_long", "Password exceeds byte limit")
        return value


@router.post("/admin/users", status_code=201, summary="E24 create member account")
def create_account(
    body: CreateAccountRequest,
    request: Request,
    user: SessionUser = Depends(require_operator),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    limiter.check(WRITE, f"user:{user.user_id}")
    try:
        user_id = supabase.create_auth_user(_normalized(str(body.email)), body.initial_password)
    except EmailExists:
        raise ApiError("conflict", "email_exists", stage="auth") from None
    except AccountInputRejected as exc:
        raise ApiError("validation_failed", fields=[{
            "name": exc.field, "reason": "invalid_value", "message": FIELD_MESSAGES["invalid_value"],
        }], stage="validate") from None
    try:
        supabase.create_member_profile(user_id, body.display_name)
    except Exception:  # Auth 생성 이후의 DB 오류는 연결 장애도 500이다(S12).
        try:
            supabase.delete_auth_user(user_id)
        except Exception:
            # 운영자가 대시보드에서 정리할 id만 남긴다. 이메일·비밀번호·외부 오류는 기록하지 않는다.
            logger.error("request_id=%s stage=auth cleanup_failed auth_user_id=%s", request_id_of(request), user_id)
        raise ApiError("internal_error", stage="db") from None
    return {"id": user_id, "role": "member"}


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # 길이 상한만 둔다. 형식이 틀린 이메일도 계정 없음과 같은 401로 끝나야 계정 유무가 새지 않는다.
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


def _normalized(email: str) -> str:
    # Auth는 이메일을 소문자로 저장한다. 같은 계정이 대소문자·공백 차이로 다른 키로 세어지지 않게 한다.
    return email.strip().lower()


def _account_key(email: str) -> str:
    return f"email:{_normalized(email)}"


def _release_account(limiter: RateLimiter, email: str) -> None:
    """계정 키로 센 한 건을 되돌린다. 되돌리기 실패는 로그인 결과를 바꾸지 않는다."""
    try:
        limiter.release(LOGIN_FAILURE, _account_key(email))
    except Exception as exc:  # noqa: BLE001 — 실패해도 한도가 한 칸 덜 남을 뿐이다
        logger.warning("stage=rate_limit release failed: %s", type(exc).__name__)


def _end_browser_session(request: Request, supabase: SupabaseClient) -> None:
    """이 요청의 세션 쿠키가 가리키는 Auth 세션을 끊는다. Auth 오류는 그대로 올린다.

    액세스 토큰이 만료됐으면 리프레시 쿠키로 갱신해서 얻은 토큰으로 끊는다. 리프레시 토큰이 Auth에
    살아 남지 않게 한다.
    """
    access_token = request.cookies.get(SESSION_COOKIE)
    if access_token and supabase.sign_out(access_token):
        return
    refresh = decode_refresh_cookie(supabase.keyed_hash, request.cookies.get(REFRESH_COOKIE))
    if refresh is None:
        return
    session = supabase.refresh_session(refresh.refresh_token, forwarded_ip(request))
    if session is not None:
        supabase.sign_out(session.access_token)


@router.post("/auth/login", summary="E01 login")
def login(
    body: LoginRequest,
    request: Request,
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """계정 없음·비밀번호 오류·비활성·profiles 없음을 같은 401 invalid_credentials로 알린다."""
    # 비밀번호를 확인하기 전에 센다. 동시 요청이 한도를 넘어 검증까지 가지 못한다(MEG-62 결정).
    # IPv6는 /64로 묶어 센다. 한 회선이 주소를 바꿔 가며 제한을 피하지 못하게 한다.
    limiter.check(LOGIN_IP, f"ip:{ip_bucket(client_ip(request))}")
    limiter.check(LOGIN_FAILURE, _account_key(body.email))
    try:
        session = supabase.sign_in_with_password(_normalized(body.email), body.password, forwarded_ip(request))
    except Exception:
        # 판정 전에 실패했으니(Auth 장애) 이 시도는 실패로 세지 않는다.
        _release_account(limiter, body.email)
        raise
    if session is None:
        raise ApiError("invalid_credentials", stage="auth")
    try:
        profile = supabase.get_profile(session.user_id)
    except Exception:
        # 비밀번호는 맞았지만 앱 계정 확인 전에 DB가 실패했다. 실패로 세지 않고, 만든 세션은 끊는다.
        _release_account(limiter, body.email)
        revoke_quietly(supabase, session.access_token)
        raise
    if profile is None or not profile.is_active:
        # Auth에는 로그인됐지만 앱 계정이 아니다. 만든 세션을 끊고 실패로 센다.
        revoke_quietly(supabase, session.access_token)
        raise ApiError("invalid_credentials", stage="auth")
    _release_account(limiter, body.email)
    try:
        # 같은 브라우저에서 다시 로그인하면 쿠키에서 밀려나는 옛 세션을 Auth에서도 끊는다.
        _end_browser_session(request, supabase)
    except Exception as exc:  # noqa: BLE001 — 새 로그인은 이미 성공했다
        logger.warning("stage=auth previous session revoke failed: %s", type(exc).__name__)
    stage_session(
        request, supabase.keyed_hash, session.access_token, session.refresh_token, session.expires_in, new_deadline()
    )
    return {"user": {"role": profile.role, "display_name": profile.display_name}}


@router.post("/auth/logout", status_code=204, summary="E02 logout")
def logout(request: Request, supabase: SupabaseClient = Depends(get_supabase)) -> Response:
    """세션이 없어도 204다. Auth 쪽 세션도 끊는다(scope=local). Auth가 실패해도 쿠키는 지운다."""
    # 무엇이 실패하든 쿠키는 지운다. 사용자의 로그아웃 의도가 Auth 상태에 막히지 않게 한다.
    stage_clear(request)
    try:
        _end_browser_session(request, supabase)
    except Exception as exc:  # noqa: BLE001 — 장애·설정 오류 모두 로그만 남기고 204로 끝낸다
        logger.warning("stage=auth logout revoke failed: %s", type(exc).__name__)
    return Response(status_code=204)


@router.get("/me", summary="E03 current session")
def me(user: SessionUser | None = Depends(get_session_user)):
    """비로그인·비활성·profiles 없음도 200 authenticated: false다. 이메일·사용자 id는 주지 않는다."""
    if user is None:
        return {"authenticated": False}
    return {"authenticated": True, "role": user.role, "display_name": user.display_name}
