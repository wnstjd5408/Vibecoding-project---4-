import httpx
import pytest

from app.supabase import Profile, SupabaseClient, SupabaseConfigError, SupabaseUnavailable

USER_ID = "00000000-0000-0000-0000-00000000000a"


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

    assert client_with(handler).get_auth_user_id("session-token") == USER_ID
    assert seen == {
        "url": "https://project.supabase.co/auth/v1/user",
        "authorization": "Bearer session-token",
        "apikey": "sb_secret_test",
    }


@pytest.mark.parametrize("status", [400, 401, 403])
def test_rejected_token_is_no_user(status):
    assert client_with(lambda r: httpx.Response(status, json={})).get_auth_user_id("t") is None


def test_malformed_auth_body_is_no_user():
    assert client_with(lambda r: httpx.Response(200, json={"id": "not-a-uuid"})).get_auth_user_id("t") is None


def test_auth_server_error_is_unavailable():
    with pytest.raises(SupabaseUnavailable):
        client_with(lambda r: httpx.Response(503)).get_auth_user_id("t")


def test_network_failure_is_unavailable_without_cause_text():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect to secret-host timed out")

    with pytest.raises(SupabaseUnavailable) as info:
        client_with(handler).get_auth_user_id("t")

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
