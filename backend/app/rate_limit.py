"""속도 제한 공통 의존성 (API spec v0.2 1.8, Q-N9).

저장소는 DB 카운터다(supabase/migrations의 rate_limit_hit 함수). 서버리스 인스턴스는
메모리를 공유하지 못하고, Vercel Hobby 방화벽은 규칙 1개·IP/JA4 키만 되어 이 제한들을 맡지 못한다.
엔드포인트는 한도 값(RateRule)과 대상만 넘긴다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from fastapi import Depends, Request

from app.auth import SessionUser, get_session_user
from app.errors import ApiError
from app.net import client_ip
from app.supabase import SupabaseClient, get_supabase


@dataclass(frozen=True)
class RateRule:
    name: str
    limit: int
    window_seconds: int
    # 성공했을 때 센 것을 되돌려도 되는 규칙. 계정 키로 세는 로그인 실패 제한만 true로 둔다.
    # IP 키 규칙을 되돌릴 수 있으면 자기 계정으로 로그인해 IP 제한을 초기화할 수 있다.
    releasable: bool = False


# API spec 1.8의 제안 숫자다. 시험 뒤 조정하며, 확정은 각 엔드포인트 티켓이 한다.
PUBLIC_READ = RateRule("public_read", 120, 60)
SIGNED_URL = RateRule("signed_url", 60, 60)
# 로그인 제한 두 개(MEG-63, 2026-10-29 사람 결정). 계정(이메일) 키는 성공하면 되돌린다.
# IP 키는 성공도 세고 되돌리지 않는다. 여러 계정을 돌아가며 시도하는 공격을 막는다.
LOGIN_FAILURE = RateRule("login_failure", 5, 15 * 60, releasable=True)
LOGIN_IP = RateRule("login_ip", 30, 15 * 60)
WRITE = RateRule("write", 30, 60)


@dataclass(frozen=True)
class RateResult:
    allowed: bool
    retry_after_seconds: int


class CounterStore(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int) -> RateResult: ...

    def release(self, key: str, window_seconds: int) -> None: ...


class SupabaseCounterStore:
    def __init__(self, supabase: SupabaseClient):
        self._supabase = supabase

    def hit(self, key: str, limit: int, window_seconds: int) -> RateResult:
        rows = self._supabase.rpc(
            "rate_limit_hit", {"p_key": key, "p_limit": limit, "p_window_seconds": window_seconds}
        )
        row = rows[0] if isinstance(rows, list) else rows
        return RateResult(allowed=bool(row["allowed"]), retry_after_seconds=max(int(row["retry_after_seconds"]), 1))

    def release(self, key: str, window_seconds: int) -> None:
        self._supabase.rpc("rate_limit_release", {"p_key": key, "p_window_seconds": window_seconds})


class RateLimiter:
    """키는 hasher로 해시해 저장한다. 이메일·IP·사용자 id 원문은 DB와 로그에 남기지 않는다.

    호출 쪽은 이메일을 소문자·공백 정리한 뒤 넘긴다(같은 계정이 다른 키로 세어지지 않게).
    """

    def __init__(self, store: CounterStore, hasher: Callable[[str], str]):
        self._store = store
        self._hasher = hasher

    def _key(self, rule: RateRule, subject: str) -> str:
        return f"{rule.name}:{self._hasher(subject)}"

    def _raise(self, result: RateResult) -> None:
        raise ApiError("rate_limited", retry_after_seconds=result.retry_after_seconds, stage="rate_limit")

    def check(self, rule: RateRule, subject: str) -> None:
        """요청 한 건을 세고, 한도를 넘으면 429 rate_limited를 낸다."""
        result = self._store.hit(self._key(rule, subject), rule.limit, rule.window_seconds)
        if not result.allowed:
            self._raise(result)

    def release(self, rule: RateRule, subject: str) -> None:
        """check로 센 한 건을 되돌린다.

        로그인 실패 제한: 비밀번호를 확인하기 전에 check로 먼저 세고(동시 요청이 한도를 넘어 검증까지
        가지 못한다), 로그인에 성공하면 release로 되돌린다. 확인만 하고 실패 뒤에 세는 방식은 동시 요청이
        모두 확인을 통과해 한도가 무력해지므로 쓰지 않는다. 되돌리는 것은 성공한 계정의 키뿐이다.
        IP 키까지 되돌리면 자기 계정으로 로그인해 IP 제한을 초기화할 수 있다.
        """
        if not rule.releasable:
            raise ValueError(f"rate rule {rule.name} cannot be released")
        self._store.release(self._key(rule, subject), rule.window_seconds)


def get_rate_limiter(supabase: SupabaseClient = Depends(get_supabase)) -> RateLimiter:
    return RateLimiter(SupabaseCounterStore(supabase), supabase.keyed_hash)


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
