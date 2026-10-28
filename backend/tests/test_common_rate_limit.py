import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.rate_limit import RateLimiter, RateResult, RateRule, SupabaseCounterStore, counter_key
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


def test_ip_is_the_first_forwarded_entry():
    client, fake = make_client()
    client.get("/api/limited", headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"})
    client.get("/api/limited", headers={"x-forwarded-for": "203.0.113.9, 10.0.0.2"})

    assert len({payload["p_key"] for _, payload in fake.rpc_calls}) == 1


def test_stored_key_does_not_contain_raw_identifiers():
    client, fake = make_client()
    client.get("/api/limited", headers=cookie("tok-a"))
    client.get("/api/limited", headers={"x-vercel-forwarded-for": "203.0.113.1"})

    keys = [payload["p_key"] for _, payload in fake.rpc_calls]
    assert all(USER_A not in key and "203.0.113.1" not in key for key in keys)
    assert all(key.startswith(f"{LIMITED_RULE.name}:") for key in keys)


def test_rule_name_separates_counters():
    assert counter_key(RateRule("a", 1, 60), "user:1") != counter_key(RateRule("b", 1, 60), "user:1")


def test_counter_store_failure_is_503():
    client, fake = make_client()
    fake.down = True

    response = client.get("/api/limited")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_limiter_check_can_be_called_directly_after_other_checks():
    # 검사 순서 6번이 필요한 엔드포인트는 핸들러 안에서 직접 부른다.
    class Store:
        def __init__(self):
            self.calls = []

        def hit(self, key, limit, window_seconds):
            self.calls.append((limit, window_seconds))
            return RateResult(allowed=len(self.calls) <= limit, retry_after_seconds=7)

    store = Store()
    limiter = RateLimiter(store)
    rule = RateRule("login_failure", 1, 900)

    limiter.check(rule, "email-hash")
    with pytest.raises(Exception) as info:
        limiter.check(rule, "email-hash")

    assert info.value.code == "rate_limited"
    assert info.value.retry_after_seconds == 7
    assert store.calls == [(1, 900), (1, 900)]


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
