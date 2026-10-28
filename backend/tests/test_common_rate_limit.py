import json

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.errors import ApiError
from app.rate_limit import RateLimiter, RateResult, RateRule, SupabaseCounterStore, client_ip
from app.supabase import SupabaseClient
from support import LIMITED_RULE, FakeSupabase, build_app, cookie

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


def test_failure_only_flow_peek_then_record():
    # 로그인 실패 제한: 확인 전에 ensure_not_limited, 실패했을 때만 record.
    limiter, _ = make_limiter()
    rule = RateRule("login_failure", 2, 900)

    for _ in range(5):  # 성공한 로그인은 세지 않으므로 몇 번을 해도 막히지 않는다
        limiter.ensure_not_limited(rule, "email-key")

    limiter.record(rule, "email-key")  # 실패 1
    limiter.ensure_not_limited(rule, "email-key")
    limiter.record(rule, "email-key")  # 실패 2 = 한도
    with pytest.raises(ApiError) as info:  # 다음 시도는 비밀번호를 확인하기 전에 막힌다
        limiter.ensure_not_limited(rule, "email-key")

    assert info.value.code == "rate_limited"


def test_record_never_raises_even_over_the_limit():
    limiter, _ = make_limiter()
    rule = RateRule("login_failure", 1, 900)

    for _ in range(3):
        limiter.record(rule, "email-key")


def test_rule_name_and_subject_separate_counters():
    limiter, fake = make_limiter()

    limiter.check(RateRule("a", 1, 60), "same")
    limiter.check(RateRule("b", 1, 60), "same")
    limiter.check(RateRule("a", 1, 60), "other")

    assert len({payload["p_key"] for _, payload in fake.rpc_calls}) == 3


def test_limiter_passes_limit_and_window_to_the_store():
    seen = []

    class Store:
        def hit(self, key, limit, window_seconds, increment=True):
            seen.append((limit, window_seconds, increment))
            return RateResult(allowed=True, retry_after_seconds=7)

    limiter = RateLimiter(Store(), lambda value: "h")
    rule = RateRule("login_failure", 5, 900)
    limiter.check(rule, "x")
    limiter.ensure_not_limited(rule, "x")
    limiter.record(rule, "x")

    assert seen == [(5, 900, True), (5, 900, False), (5, 900, True)]


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
    assert seen["body"] == {"p_key": "k", "p_limit": 5, "p_window_seconds": 900, "p_increment": True}
    assert seen["auth"] == "Bearer sb_secret_test"
    assert result == RateResult(allowed=False, retry_after_seconds=12)


def test_counter_store_sends_increment_false_for_peek():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=[{"allowed": True, "retry_after_seconds": 3}])

    SupabaseCounterStore(supabase_with(handler)).hit("k", 5, 900, increment=False)

    assert seen["body"]["p_increment"] is False
