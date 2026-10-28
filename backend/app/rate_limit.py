"""속도 제한 공통 의존성 (API spec v0.2 1.8, Q-N9).

저장소는 DB 카운터다(supabase/migrations의 rate_limit_hit 함수). 서버리스 인스턴스는
메모리를 공유하지 못하고, Vercel Hobby 방화벽은 규칙 1개·IP/JA4 키만 되어 이 제한들을 맡지 못한다.
엔드포인트는 한도 값(RateRule)과 대상만 넘긴다.
"""

import hashlib
from dataclasses import dataclass
from typing import Protocol

from fastapi import Depends, Request

from app.auth import SessionUser, get_session_user
from app.errors import ApiError
from app.supabase import SupabaseClient, get_supabase


@dataclass(frozen=True)
class RateRule:
    name: str
    limit: int
    window_seconds: int


# API spec 1.8의 제안 숫자다. 시험 뒤 조정하며, 확정은 각 엔드포인트 티켓이 한다.
PUBLIC_READ = RateRule("public_read", 120, 60)
SIGNED_URL = RateRule("signed_url", 60, 60)
LOGIN_FAILURE = RateRule("login_failure", 5, 15 * 60)
WRITE = RateRule("write", 30, 60)


@dataclass(frozen=True)
class RateResult:
    allowed: bool
    retry_after_seconds: int


class CounterStore(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int) -> RateResult: ...


class SupabaseCounterStore:
    def __init__(self, supabase: SupabaseClient):
        self._supabase = supabase

    def hit(self, key: str, limit: int, window_seconds: int) -> RateResult:
        rows = self._supabase.rpc(
            "rate_limit_hit", {"p_key": key, "p_limit": limit, "p_window_seconds": window_seconds}
        )
        row = rows[0] if isinstance(rows, list) else rows
        return RateResult(allowed=bool(row["allowed"]), retry_after_seconds=max(int(row["retry_after_seconds"]), 1))


def counter_key(rule: RateRule, subject: str) -> str:
    """저장하는 키. 이메일·IP·사용자 id 원문은 DB와 로그에 남기지 않고 해시만 쓴다."""
    return f"{rule.name}:{hashlib.sha256(subject.encode()).hexdigest()[:32]}"


def client_ip(request: Request) -> str:
    # Vercel이 넣는 클라이언트 IP 헤더를 먼저 본다.
    for header in ("x-vercel-forwarded-for", "x-forwarded-for"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    def __init__(self, store: CounterStore):
        self._store = store

    def check(self, rule: RateRule, subject: str) -> None:
        """한도를 넘으면 429 rate_limited를 낸다. 카운터가 한 번 올라간다."""
        result = self._store.hit(counter_key(rule, subject), rule.limit, rule.window_seconds)
        if not result.allowed:
            raise ApiError("rate_limited", retry_after_seconds=result.retry_after_seconds, stage="rate_limit")


def get_rate_limiter(supabase: SupabaseClient = Depends(get_supabase)) -> RateLimiter:
    return RateLimiter(SupabaseCounterStore(supabase))


def rate_limited(rule: RateRule):
    """사용자(비로그인은 IP)별로 세는 의존성. 검사 순서 6번(대상 확인 뒤)이 필요한 엔드포인트는
    이 의존성 대신 RateLimiter.check를 핸들러 안의 그 자리에서 직접 부른다."""

    def dependency(
        request: Request,
        user: SessionUser | None = Depends(get_session_user),
        limiter: RateLimiter = Depends(get_rate_limiter),
    ) -> None:
        limiter.check(rule, f"user:{user.user_id}" if user else f"ip:{client_ip(request)}")

    return dependency
