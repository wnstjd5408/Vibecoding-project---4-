"""세션 쿠키 읽기·쓰기 (API spec v0.2 1.2, Q-N10 2026-10-29 결정).

쿠키는 두 개다.
- SESSION_COOKIE: Supabase 액세스 토큰. 요청마다 Auth로 확인한다.
- REFRESH_COOKIE: "{만료 시각}.{서명}.{리프레시 토큰}". 만료 시각은 로그인 시점 + 7일로 고정이고,
  secret key로 서명해 브라우저가 늘릴 수 없다. 갱신할 때도 같은 만료 시각을 이어 쓴다.

핸들러와 의존성은 쿠키를 직접 쓰지 않고 request.state에 바꿀 내용만 남긴다. 미들웨어가 오류 응답을
포함한 모든 /api 응답에 적용한다. 갱신된 리프레시 토큰이 브라우저에 저장되지 않으면 다음 요청이 옛 토큰을
다시 쓰게 되고, Auth는 이를 재사용으로 보고 세션을 끊을 수 있다.
"""

import hmac
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import Response

from app.config import REFRESH_COOKIE, SESSION_COOKIE, SESSION_MAX_AGE_SECONDS

# 리프레시 토큰 모양. 헤더에 실을 수 있는 글자만 받고, 쿠키 크기 한계(약 4KB) 안으로 자른다.
_REFRESH_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9._~+/=-]{1,2048}")
_DEADLINE_SHAPE = re.compile(r"[0-9]{1,12}")
_SIGNATURE_SHAPE = re.compile(r"[0-9a-f]{32}")


def now() -> float:
    """현재 시각(UTC 초). 시험에서 바꿔 끼운다."""
    return time.time()


def new_deadline() -> int:
    return int(now()) + SESSION_MAX_AGE_SECONDS


def _signature(sign: Callable[[str], str], deadline: int, refresh_token: str) -> str:
    # 다른 용도(속도 제한 키)의 해시와 섞이지 않게 접두어를 붙인다.
    return sign(f"session_deadline:{deadline}:{refresh_token}")


def encode_refresh_cookie(sign: Callable[[str], str], refresh_token: str, deadline: int) -> str:
    return f"{deadline}.{_signature(sign, deadline, refresh_token)}.{refresh_token}"


@dataclass(frozen=True)
class RefreshCookie:
    refresh_token: str
    deadline: int


def decode_refresh_cookie(sign: Callable[[str], str], value: str | None) -> RefreshCookie | None:
    """서명이 맞고 만료 전이면 리프레시 토큰과 만료 시각을, 아니면 None을 돌려준다."""
    if not value:
        return None
    parts = value.split(".", 2)
    if len(parts) != 3:
        return None
    deadline_text, signature, refresh_token = parts
    if not (
        _DEADLINE_SHAPE.fullmatch(deadline_text)
        and _SIGNATURE_SHAPE.fullmatch(signature)
        and _REFRESH_TOKEN_SHAPE.fullmatch(refresh_token)
    ):
        return None
    deadline = int(deadline_text)
    if not hmac.compare_digest(signature, _signature(sign, deadline, refresh_token)):
        return None
    if deadline <= now():
        return None
    return RefreshCookie(refresh_token=refresh_token, deadline=deadline)


@dataclass(frozen=True)
class _SetSession:
    access_token: str
    access_max_age: int
    refresh_value: str
    refresh_max_age: int


_CLEAR = "clear"


def stage_session(
    request: Request,
    sign: Callable[[str], str],
    access_token: str,
    refresh_token: str,
    expires_in: int,
    deadline: int,
) -> None:
    """응답에 새 세션 쿠키를 싣도록 남긴다. 두 쿠키 모두 만료 시각을 넘겨 살지 않는다."""
    remaining = max(deadline - int(now()), 0)
    request.state.session_cookies = _SetSession(
        access_token=access_token,
        # 액세스 쿠키는 토큰 수명만큼만 둔다. 만료된 토큰으로 Auth를 한 번 더 부르지 않고 바로 갱신한다.
        access_max_age=min(max(expires_in, 0), remaining),
        refresh_value=encode_refresh_cookie(sign, refresh_token, deadline),
        refresh_max_age=remaining,
    )


def stage_clear(request: Request) -> None:
    """응답에서 세션 쿠키를 지우도록 남긴다."""
    request.state.session_cookies = _CLEAR


def has_session_cookie(request: Request) -> bool:
    return bool(request.cookies.get(SESSION_COOKIE) or request.cookies.get(REFRESH_COOKIE))


_COOKIE_FLAGS = {"path": "/", "secure": True, "httponly": True, "samesite": "lax"}


def apply_session_cookies(request: Request, response: Response) -> None:
    """미들웨어가 부른다. 남긴 내용이 없으면 아무것도 하지 않는다."""
    staged = getattr(request.state, "session_cookies", None)
    if staged is None:
        return
    if staged == _CLEAR:
        response.delete_cookie(SESSION_COOKIE, **_COOKIE_FLAGS)
        response.delete_cookie(REFRESH_COOKIE, **_COOKIE_FLAGS)
        return
    response.set_cookie(SESSION_COOKIE, staged.access_token, max_age=staged.access_max_age, **_COOKIE_FLAGS)
    response.set_cookie(REFRESH_COOKIE, staged.refresh_value, max_age=staged.refresh_max_age, **_COOKIE_FLAGS)
