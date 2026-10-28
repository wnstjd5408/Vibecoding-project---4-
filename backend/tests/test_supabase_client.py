import httpx
import pytest

from app.supabase import Profile, SupabaseClient, SupabaseConfigError, SupabaseUnavailable

USER_ID = "00000000-0000-0000-0000-00000000000a"
# 구조만 맞춘 가짜 값(base64url 세 구간). 실제 JWT처럼 보이는 값은 비밀 검사기가 오탐하므로 쓰지 않는다.
JWT = "header-part.payload-part.signature_part"


def client_with(handler) -> SupabaseClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseClient("https://project.supabase.co/", "sb_secret_test", http)


def test_auth_user_check_uses_the_session_token_not_the_secret_key_as_bearer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["authorization"]
        seen["apikey"] = request.headers["apikey"]
        return httpx.Response(200, json={"id": USER_ID})

    assert client_with(handler).get_auth_user_id(JWT) == USER_ID
    assert seen == {
        "url": "https://project.supabase.co/auth/v1/user",
        "authorization": f"Bearer {JWT}",
        "apikey": "sb_secret_test",
    }


@pytest.mark.parametrize("status", [400, 401, 403])
def test_rejected_token_is_no_user(status):
    assert client_with(lambda r: httpx.Response(status, json={})).get_auth_user_id(JWT) is None


def test_malformed_auth_body_is_no_user():
    assert client_with(lambda r: httpx.Response(200, json={"id": "not-a-uuid"})).get_auth_user_id(JWT) is None


def test_auth_server_error_is_unavailable():
    with pytest.raises(SupabaseUnavailable):
        client_with(lambda r: httpx.Response(503)).get_auth_user_id(JWT)


def test_network_failure_is_unavailable_without_cause_text():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect to secret-host timed out")

    with pytest.raises(SupabaseUnavailable) as info:
        client_with(handler).get_auth_user_id(JWT)

    assert "secret-host" not in str(info.value)


def test_profile_lookup_filters_by_user_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=[{"role": "operator", "is_active": True}])

    assert client_with(handler).get_profile(USER_ID) == Profile(role="operator", is_active=True)
    assert seen["params"] == {"user_id": f"eq.{USER_ID}", "select": "role,is_active", "limit": "1"}


def test_missing_profile_row_is_none():
    assert client_with(lambda r: httpx.Response(200, json=[])).get_profile(USER_ID) is None


def test_profile_lookup_rejects_non_uuid_ids():
    with pytest.raises(ValueError):
        client_with(lambda r: httpx.Response(200, json=[])).get_profile("1&select=*")


def test_denied_key_is_a_config_error():
    with pytest.raises(SupabaseConfigError):
        client_with(lambda r: httpx.Response(401, json={})).get_profile(USER_ID)


def test_from_env_requires_both_variables(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")

    with pytest.raises(SupabaseConfigError):
        SupabaseClient.from_env()


# 토큰 모양: 요청을 보내기 전에 걸러 낸다(비ASCII는 헤더를 만들 수 없어 예외가 된다)
@pytest.mark.parametrize(
    "token",
    ["abc", "a.b", "a.b.c.d", "..", "a..c", "éabc.b.c", "abc def", "abc\r\nX-Injected: 1", "", "a" * 4097, "토큰", "abc\x00", "abc;def", 'abc"'],
)
def test_malformed_token_is_no_user_and_sends_no_request(token):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": USER_ID})

    assert client_with(handler).get_auth_user_id(token) is None
    assert calls == []


def test_jwt_shaped_token_is_sent():
    token = JWT

    assert client_with(lambda r: httpx.Response(200, json={"id": USER_ID})).get_auth_user_id(token) == USER_ID


def test_non_ascii_cookie_through_the_real_client_is_anonymous_not_a_500():
    from starlette.requests import Request

    from app.auth import get_session_user

    calls = []
    real = client_with(lambda r: calls.append(r) or httpx.Response(401))
    request = Request(
        {"type": "http", "method": "GET", "path": "/api/ping", "query_string": b"",
         "headers": [(b"cookie", b"cs_session=\xe9abc")]}
    )

    assert get_session_user(request, real) is None
    assert calls == []


# 재시도하면 풀릴 수 있는 응답은 503, 설정 오류는 500
@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_transient_statuses_are_unavailable_for_every_call(status):
    handler = lambda r: httpx.Response(status, json={})  # noqa: E731

    with pytest.raises(SupabaseUnavailable):
        client_with(handler).get_profile(USER_ID)
    with pytest.raises(SupabaseUnavailable):
        client_with(handler).rpc("rate_limit_hit", {})
    with pytest.raises(SupabaseUnavailable):
        client_with(handler).get_auth_user_id(JWT)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_other_client_errors_on_data_calls_are_config_errors(status):
    handler = lambda r: httpx.Response(status, json={})  # noqa: E731

    with pytest.raises(SupabaseConfigError):
        client_with(handler).get_profile(USER_ID)
    with pytest.raises(SupabaseConfigError):
        client_with(handler).rpc("rate_limit_hit", {})


# 저장 키 해시: secret key로 서명한 HMAC
def test_keyed_hash_is_stable_and_hides_the_input():
    client = client_with(lambda r: httpx.Response(200, json=[]))

    one = client.keyed_hash("203.0.113.1")

    assert one == client.keyed_hash("203.0.113.1")
    assert one != client.keyed_hash("203.0.113.2")
    assert "203.0.113.1" not in one and len(one) == 32


def test_keyed_hash_depends_on_the_secret_key():
    other = SupabaseClient("https://project.supabase.co", "another-secret", httpx.Client())

    assert client_with(lambda r: httpx.Response(200)).keyed_hash("x") != other.keyed_hash("x")


def test_valid_shape_but_oversized_token_is_rejected_without_a_request():
    calls = []
    token = "a" * 2000 + "." + "b" * 2000 + "." + "c" * 200  # 각 구간은 상한 안이지만 전체가 4096자를 넘는다
    client = client_with(lambda r: calls.append(r) or httpx.Response(200, json={"id": USER_ID}))

    assert client.get_auth_user_id(token) is None
    assert calls == []


def test_realistic_large_payload_segment_is_accepted():
    # user_metadata가 큰 계정의 토큰: 가운데 구간이 2800자여도 전체가 4096자 이하면 받는다.
    token = "a" * 40 + "." + "b" * 2800 + "." + "c" * 86

    assert client_with(lambda r: httpx.Response(200, json={"id": USER_ID})).get_auth_user_id(token) == USER_ID
