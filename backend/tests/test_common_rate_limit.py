import json

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.errors import ApiError
from app.rate_limit import RateLimiter, RateResult, RateRule, SupabaseCounterStore, client_ip
from app.supabase import SupabaseClient
from support import LIMITED_RULE, FakeSupabase, build_app, cookie

@pytest.fixture(autouse=True)
def on_vercel(monkeypatch):
    # Vercel 위에서만 x-vercel-forwarded-for를 믿는다. 아래 시험은 Vercel 안에서 도는 것으로 본다.
    monkeypatch.setenv("VERCEL", "1")


USER_A = "00000000-0000-0000-0000-00000000000a"
USER_B = "00000000-0000-0000-0000-00000000000b"


def make_client(fake: FakeSupabase | None = None) -> tuple[TestClient, FakeSupabase]:
    fake = fake or FakeSupabase()
    fake.add_user("tok-a", USER_A)
    fake.add_user("tok-b", USER_B)
    return TestClient(build_app(fake)), fake


# AC-4: 한도를 넘은 요청은 429 rate_limited
def test_request_over_the_limit_is_429_with_retry_after():
    client, _ = make_client()

    statuses = [client.get("/api/limited", headers=cookie("tok-a")).status_code for _ in range(3)]
    over = client.get("/api/limited", headers=cookie("tok-a"))

    assert statuses == [200, 200, 429]
    assert over.status_code == 429
    error = over.json()["error"]
    assert error["code"] == "rate_limited"
    assert error["message"] == "Too many requests; retry later"
    assert error["retry_after_seconds"] >= 1
    assert over.headers["Retry-After"] == str(error["retry_after_seconds"])
    assert over.headers["Cache-Control"] == "private, no-store"


def test_limit_is_counted_per_user():
    client, _ = make_client()
    for _ in range(3):
        client.get("/api/limited", headers=cookie("tok-a"))

    assert client.get("/api/limited", headers=cookie("tok-a")).status_code == 429
    assert client.get("/api/limited", headers=cookie("tok-b")).status_code == 200


def test_visitors_are_counted_per_ip():
    client, _ = make_client()
    one = {"x-vercel-forwarded-for": "203.0.113.1"}
    two = {"x-vercel-forwarded-for": "203.0.113.2"}
    for _ in range(3):
        client.get("/api/limited", headers=one)

    assert client.get("/api/limited", headers=one).status_code == 429
    assert client.get("/api/limited", headers=two).status_code == 200


def test_client_supplied_x_forwarded_for_does_not_create_new_buckets():
    # XFF를 요청마다 바꿔도 제한을 피할 수 없다(Vercel 헤더가 없으면 소켓 주소 쪽으로 센다).
    client, _ = make_client()

    statuses = [
        client.get("/api/limited", headers={"x-forwarded-for": f"198.51.100.{n}"}).status_code
        for n in range(1, 5)
    ]

    assert statuses == [200, 200, 429, 429]


def test_stored_key_does_not_contain_raw_identifiers():
    client, fake = make_client()
    client.get("/api/limited", headers=cookie("tok-a"))
    client.get("/api/limited", headers={"x-vercel-forwarded-for": "203.0.113.1"})

    keys = [payload["p_key"] for _, payload in fake.rpc_calls]
    assert all(USER_A not in key and "203.0.113.1" not in key for key in keys)
    assert all(key.startswith(f"{LIMITED_RULE.name}:") for key in keys)


def test_counter_store_failure_is_503():
    client, fake = make_client()
    fake.down = True

    response = client.get("/api/limited")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


# client_ip: Vercel 헤더나 소켓 주소만 믿는다
def request_with(headers: dict[str, str], client=("203.0.113.50", 1234)) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": client,
        }
    )


def test_client_ip_prefers_vercel_header_and_normalizes():
    assert client_ip(request_with({"x-vercel-forwarded-for": "203.0.113.9, 10.0.0.1"})) == "203.0.113.9"
    assert client_ip(request_with({"x-vercel-forwarded-for": "2001:DB8:0:0:0:0:0:1"})) == "2001:db8::1"


def test_vercel_header_is_ignored_outside_vercel(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)

    assert client_ip(request_with({"x-vercel-forwarded-for": "198.51.100.7"})) == "203.0.113.50"


def test_forged_vercel_header_outside_vercel_cannot_make_new_buckets(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    client, _ = make_client()

    statuses = [
        client.get("/api/limited", headers={"x-vercel-forwarded-for": f"198.51.100.{n}"}).status_code
        for n in range(1, 5)
    ]

    assert statuses == [200, 200, 429, 429]


def test_client_ip_ignores_x_forwarded_for():
    assert client_ip(request_with({"x-forwarded-for": "198.51.100.7"})) == "203.0.113.50"


def test_client_ip_falls_back_to_socket_when_header_is_not_an_ip():
    assert client_ip(request_with({"x-vercel-forwarded-for": "not-an-ip"})) == "203.0.113.50"


def test_client_ip_unknown_when_nothing_usable():
    assert client_ip(request_with({}, client=None)) == "unknown"


# RateLimiter를 핸들러 안에서 직접 쓰는 경우
def make_limiter(fake: FakeSupabase | None = None) -> tuple[RateLimiter, FakeSupabase]:
    fake = fake or FakeSupabase()
    return RateLimiter(SupabaseCounterStore(fake), fake.keyed_hash), fake


def test_check_counts_each_call_and_raises_over_the_limit():
    limiter, _ = make_limiter()
    rule = RateRule("w", 2, 60)

    limiter.check(rule, "u1")
    limiter.check(rule, "u1")
    with pytest.raises(ApiError) as info:
        limiter.check(rule, "u1")

    assert info.value.code == "rate_limited"
    assert info.value.retry_after_seconds >= 1


def test_window_rolls_over_with_time():
    limiter, fake = make_limiter()
    rule = RateRule("w", 1, 60)
    limiter.check(rule, "u1")
    with pytest.raises(ApiError):
        limiter.check(rule, "u1")

    fake.advance(60)

    limiter.check(rule, "u1")


# 로그인 실패 제한: 비밀번호를 확인하기 전에 먼저 세고, 성공하면 되돌린다
def attempt_login(limiter: RateLimiter, rule: RateRule, subject: str, password_ok: bool) -> str:
    try:
        limiter.check(rule, subject)  # 확인 전에 센다
    except ApiError:
        return "blocked"
    if password_ok:
        limiter.release(rule, subject)
        return "ok"
    return "wrong"


def test_parallel_failures_cannot_all_reach_the_password_check():
    # 시도 100개가 모두 비밀번호 확인까지 가면 한도 5는 의미가 없다. 먼저 세므로 5개만 간다.
    limiter, _ = make_limiter()
    rule = RateRule("login_failure", 5, 900)

    results = [attempt_login(limiter, rule, "victim", password_ok=False) for _ in range(100)]

    assert results.count("wrong") == 5
    assert results.count("blocked") == 95


def test_successful_logins_are_released_and_never_lock_the_account():
    limiter, fake = make_limiter()
    rule = RateRule("login_failure", 3, 900)

    results = [attempt_login(limiter, rule, "alice", password_ok=True) for _ in range(20)]

    assert set(results) == {"ok"}
    assert fake.hits(f"login_failure:{fake.keyed_hash('alice')}", 900) == 0


def test_a_success_gives_back_only_its_own_count():
    limiter, fake = make_limiter()
    rule = RateRule("login_failure", 3, 900)
    key = f"login_failure:{fake.keyed_hash('alice')}"

    attempt_login(limiter, rule, "alice", password_ok=False)
    attempt_login(limiter, rule, "alice", password_ok=False)
    attempt_login(limiter, rule, "alice", password_ok=True)  # 세고 바로 되돌리므로 실패 2건은 남는다

    assert fake.hits(key, 900) == 2
    assert attempt_login(limiter, rule, "alice", password_ok=False) == "wrong"  # 3번째 실패
    assert attempt_login(limiter, rule, "alice", password_ok=False) == "blocked"


def test_release_without_a_counter_is_harmless():
    limiter, fake = make_limiter()

    limiter.release(RateRule("login_failure", 3, 900), "nobody")

    assert fake.hits(f"login_failure:{fake.keyed_hash('nobody')}", 900) == 0


def test_rule_name_and_subject_separate_counters():
    limiter, fake = make_limiter()

    limiter.check(RateRule("a", 1, 60), "same")
    limiter.check(RateRule("b", 1, 60), "same")
    limiter.check(RateRule("a", 1, 60), "other")

    assert len({payload["p_key"] for _, payload in fake.rpc_calls}) == 3


def test_limiter_passes_limit_and_window_to_the_store():
    seen = []

    class Store:
        def hit(self, key, limit, window_seconds):
            seen.append(("hit", limit, window_seconds))
            return RateResult(allowed=True, retry_after_seconds=7)

        def release(self, key, window_seconds):
            seen.append(("release", window_seconds))

    limiter = RateLimiter(Store(), lambda value: "h")
    rule = RateRule("login_failure", 5, 900)
    limiter.check(rule, "x")
    limiter.release(rule, "x")

    assert seen == [("hit", 5, 900), ("release", 900)]


# SupabaseClient / 카운터 저장소가 보내는 요청 모양
def supabase_with(handler) -> SupabaseClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseClient("https://project.supabase.co", "sb_secret_test", http)


def test_counter_store_calls_rate_limit_hit_rpc():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=[{"allowed": False, "retry_after_seconds": 12}])

    store = SupabaseCounterStore(supabase_with(handler))
    result = store.hit("k", 5, 900)

    assert seen["url"] == "https://project.supabase.co/rest/v1/rpc/rate_limit_hit"
    assert seen["body"] == {"p_key": "k", "p_limit": 5, "p_window_seconds": 900}
    assert seen["auth"] == "Bearer sb_secret_test"
    assert result == RateResult(allowed=False, retry_after_seconds=12)


def test_counter_store_calls_rate_limit_release_rpc():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=None)

    SupabaseCounterStore(supabase_with(handler)).release("k", 900)

    assert seen["url"] == "https://project.supabase.co/rest/v1/rpc/rate_limit_release"
    assert seen["body"] == {"p_key": "k", "p_window_seconds": 900}


@pytest.mark.parametrize("response", [httpx.Response(204), httpx.Response(200), httpx.Response(200, content=b"null")])
def test_void_function_responses_are_accepted(response):
    # 반환값이 없는 SQL 함수의 응답 모양: 204, 빈 200, null
    assert supabase_with(lambda request: response).rpc("rate_limit_release", {}) is None


def test_unexpected_status_for_rpc_is_a_config_error():
    from app.supabase import SupabaseConfigError

    with pytest.raises(SupabaseConfigError):
        supabase_with(lambda request: httpx.Response(404, json={})).rpc("rate_limit_release", {})
