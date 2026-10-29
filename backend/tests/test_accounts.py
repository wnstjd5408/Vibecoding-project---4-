"""E01~E03 로그인·로그아웃·내 상태 (MEG-63). 가짜 Supabase로 네트워크 없이 돈다."""

from http.cookies import SimpleCookie

import pytest
from fastapi.testclient import TestClient

from app.config import REFRESH_COOKIE, SESSION_COOKIE, SESSION_MAX_AGE_SECONDS
from support import FakeSupabase, build_accounts_app, origin

MEMBER = "00000000-0000-0000-0000-00000000000a"
OPERATOR = "00000000-0000-0000-0000-00000000000b"
INACTIVE = "00000000-0000-0000-0000-00000000000c"
NO_PROFILE = "00000000-0000-0000-0000-00000000000d"


@pytest.fixture
def fake(monkeypatch) -> FakeSupabase:
    fake = FakeSupabase()
    fake.add_account("member@example.test", "right-pw", MEMBER, display_name="Member")
    fake.add_account("ops@example.test", "ops-pw", OPERATOR, role="operator", display_name="Ops")
    fake.add_account("inactive@example.test", "inactive-pw", INACTIVE, is_active=False)
    fake.add_account("noprofile@example.test", "noprofile-pw", NO_PROFILE, profile=False)
    # 세션 만료 시각 계산도 가짜 시계를 따른다.
    monkeypatch.setattr("app.session.now", lambda: fake.now)
    monkeypatch.setenv("VERCEL", "1")
    return fake


@pytest.fixture
def client(fake) -> TestClient:
    return TestClient(build_accounts_app(fake))


def login(client, email="member@example.test", password="right-pw", ip="203.0.113.1"):
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers={**origin(), "x-vercel-forwarded-for": ip},
    )


def set_cookies(response) -> dict[str, dict]:
    """Set-Cookie 헤더를 {이름: {value, max-age, 속성...}}로 푼다."""
    result = {}
    for header in response.headers.get_list("set-cookie"):
        jar = SimpleCookie()
        jar.load(header)
        for name, morsel in jar.items():
            lowered = header.lower()
            result[name] = {
                "value": morsel.value,
                "max-age": morsel["max-age"],
                "path": morsel["path"],
                "samesite": morsel["samesite"].lower(),
                "httponly": "httponly" in lowered,
                "secure": "secure" in lowered,
            }
    return result


def cookie_header(cookies: dict[str, dict]) -> dict[str, str]:
    return {"Cookie": "; ".join(f'{name}="{c["value"]}"' for name, c in cookies.items())}


def me(client, cookies: dict[str, dict] | None = None):
    return client.get("/api/me", headers=cookie_header(cookies) if cookies else {})


def without_request_id(response) -> tuple[int, dict]:
    error = dict(response.json()["error"])
    error.pop("request_id")
    return response.status_code, error


# --- AC-1: 로그인하면 세션 쿠키가 생기고 E03이 로그인 상태와 역할을 준다 ---


def test_login_sets_both_session_cookies_and_returns_role_and_name(client):
    response = login(client)

    assert response.status_code == 200
    assert response.json() == {"user": {"role": "member", "display_name": "Member"}}
    cookies = set_cookies(response)
    assert set(cookies) == {SESSION_COOKIE, REFRESH_COOKIE}
    for c in cookies.values():
        assert (c["httponly"], c["secure"], c["samesite"], c["path"]) == (True, True, "lax", "/")
    assert cookies[SESSION_COOKIE]["max-age"] == "3600"
    assert cookies[REFRESH_COOKIE]["max-age"] == str(SESSION_MAX_AGE_SECONDS)
    assert response.headers["Cache-Control"] == "private, no-store"


def test_login_response_has_no_tokens_or_user_id(client):
    body = login(client).text

    assert "access." not in body
    assert "refresh" not in body
    assert MEMBER not in body


def test_me_after_login_is_authenticated_with_role(client):
    cookies = set_cookies(login(client))

    response = me(client, cookies)

    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "role": "member", "display_name": "Member"}


def test_operator_login_reports_operator_role(client):
    cookies = set_cookies(login(client, "ops@example.test", "ops-pw"))

    assert me(client, cookies).json() == {"authenticated": True, "role": "operator", "display_name": "Ops"}


def test_email_case_and_spaces_do_not_matter(client):
    assert login(client, "  Member@Example.TEST ").status_code == 200


# --- AC-2: 로그아웃 뒤 E03은 비로그인, 잘못된 비밀번호는 401 invalid_credentials ---


def test_logout_clears_cookies_and_me_becomes_visitor(client, fake):
    cookies = set_cookies(login(client))

    response = client.post("/api/auth/logout", headers={**origin(), **cookie_header(cookies)})

    assert response.status_code == 204
    cleared = set_cookies(response)
    assert set(cleared) == {SESSION_COOKIE, REFRESH_COOKIE}
    assert all(c["max-age"] == "0" for c in cleared.values())
    # Auth 쪽 세션도 끊겨서 옛 쿠키를 다시 보내도 비로그인이다.
    assert not fake.session_alive(cookies[SESSION_COOKIE]["value"])
    assert me(client, cookies).json() == {"authenticated": False}


def test_wrong_password_is_401_invalid_credentials_without_cookies(client):
    response = login(client, password="wrong")

    assert response.status_code == 401
    error = response.json()["error"]
    assert (error["code"], error["message"]) == ("invalid_credentials", "Invalid email or password")
    assert "set-cookie" not in response.headers


def test_unknown_inactive_and_profileless_accounts_look_the_same_as_a_wrong_password(client):
    results = [
        login(client, password="wrong"),
        login(client, email="nobody@example.test", password="x"),
        login(client, email="inactive@example.test", password="inactive-pw"),
        login(client, email="noprofile@example.test", password="noprofile-pw"),
    ]

    assert all(without_request_id(r) == without_request_id(results[0]) for r in results)
    assert all("set-cookie" not in r.headers for r in results)


def test_inactive_or_profileless_login_revokes_the_auth_session_it_created(client, fake):
    login(client, email="inactive@example.test", password="inactive-pw")
    login(client, email="noprofile@example.test", password="noprofile-pw")

    assert fake.auth_calls.count("logout") == 2
    assert fake.sessions == {}


def test_visitor_me_is_200_unauthenticated_without_auth_calls(client, fake):
    response = me(client)

    assert response.status_code == 200
    assert response.json() == {"authenticated": False}
    assert "set-cookie" not in response.headers
    assert fake.auth_calls == []


def test_logout_without_a_session_is_204(client):
    assert client.post("/api/auth/logout", headers=origin()).status_code == 204


@pytest.mark.parametrize("path", ["/api/auth/login", "/api/auth/logout"])
def test_login_and_logout_require_an_allowed_origin(client, path):
    response = client.post(path, json={"email": "member@example.test", "password": "right-pw"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"


@pytest.mark.parametrize(
    "body, name, reason",
    [
        ({"email": "member@example.test"}, "password", "required"),
        ({"email": "", "password": "x"}, "email", "required"),
        ({"email": "a" * 321, "password": "x"}, "email", "too_long"),
    ],
)
def test_login_body_is_validated_before_any_counting(client, fake, body, name, reason):
    response = client.post("/api/auth/login", json=body, headers=origin())

    assert response.status_code == 422
    assert {"name": name, "reason": reason} == {k: response.json()["error"]["fields"][0][k] for k in ("name", "reason")}
    assert fake.rpc_calls == []


def test_unknown_login_fields_are_rejected(client):
    body = {"email": "member@example.test", "password": "right-pw", "role": "operator"}
    assert client.post("/api/auth/login", json=body, headers=origin()).status_code == 422


# --- 로그인 실패 제한: 계정 5회/15분(성공하면 되돌림), IP 30회/15분(되돌리지 않음) ---


def test_sixth_attempt_on_an_account_is_429_even_with_the_right_password(client):
    statuses = [login(client, password="wrong").status_code for _ in range(5)]

    blocked = login(client)

    assert statuses == [401] * 5
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1


def test_account_limit_ignores_case_and_spaces(client):
    for variant in ["member@example.test", "MEMBER@example.test", " member@example.test", "Member@Example.Test", "member@EXAMPLE.test"]:
        login(client, email=variant, password="wrong")

    assert login(client).status_code == 429


def test_successful_logins_never_lock_the_account(client):
    assert [login(client).status_code for _ in range(10)] == [200] * 10


def test_ip_limit_counts_every_attempt_across_accounts(client, fake):
    for i in range(30):
        # 계정 제한에 걸리지 않게 계정을 바꿔 가며 같은 IP에서 시도한다(성공도 센다).
        email = "member@example.test" if i % 2 else f"user{i}@example.test"
        login(client, email=email, password="right-pw" if i % 2 else "x")

    assert login(client).status_code == 429
    assert login(client, ip="203.0.113.99").status_code == 200


def test_auth_outage_is_503_and_does_not_count_as_a_failure(client, fake):
    fake.auth_down = True
    response = login(client)
    fake.auth_down = False

    assert response.status_code == 503
    assert fake.hits(f"login_failure:{fake.keyed_hash('email:member@example.test')}", 15 * 60) == 0


def test_profile_outage_after_a_right_password_releases_and_revokes(client, fake, monkeypatch):
    def broken(user_id):
        from app.supabase import SupabaseUnavailable

        raise SupabaseUnavailable("down")

    monkeypatch.setattr(fake, "get_profile", broken)
    response = login(client)

    assert response.status_code == 503
    assert fake.hits(f"login_failure:{fake.keyed_hash('email:member@example.test')}", 15 * 60) == 0
    assert fake.sessions == {}


# --- 세션 갱신: 로그인부터 7일 고정 ---


def test_expired_access_token_is_refreshed_with_the_same_deadline(client, fake):
    cookies = set_cookies(login(client))
    fake.expire_access(cookies[SESSION_COOKIE]["value"])
    fake.advance(2 * 24 * 3600)

    response = me(client, cookies)

    assert response.json()["authenticated"] is True
    renewed = set_cookies(response)
    assert renewed[SESSION_COOKIE]["value"] != cookies[SESSION_COOKIE]["value"]
    assert renewed[REFRESH_COOKIE]["max-age"] == str(SESSION_MAX_AGE_SECONDS - 2 * 24 * 3600)
    # 만료 시각(쿠키 앞부분)은 로그인 때 값 그대로다.
    deadline = lambda c: c[REFRESH_COOKIE]["value"].split(".", 1)[0]  # noqa: E731
    assert deadline(renewed) == deadline(cookies)
    assert me(client, renewed).json()["authenticated"] is True


def test_missing_access_cookie_is_refreshed_without_an_auth_user_call(client, fake):
    cookies = set_cookies(login(client))
    fake.auth_calls.clear()

    response = me(client, {REFRESH_COOKIE: cookies[REFRESH_COOKIE]})

    assert response.json()["authenticated"] is True
    assert fake.auth_calls == ["refresh"]


def test_session_ends_seven_days_after_login_even_if_used(client, fake):
    cookies = set_cookies(login(client))
    fake.expire_access(cookies[SESSION_COOKIE]["value"])
    fake.advance(SESSION_MAX_AGE_SECONDS + 1)
    fake.auth_calls.clear()

    response = me(client, cookies)

    assert response.json() == {"authenticated": False}
    assert all(c["max-age"] == "0" for c in set_cookies(response).values())
    assert "refresh" not in fake.auth_calls


def test_a_tampered_deadline_is_rejected_without_calling_auth(client, fake):
    cookies = set_cookies(login(client))
    fake.expire_access(cookies[SESSION_COOKIE]["value"])
    deadline, rest = cookies[REFRESH_COOKIE]["value"].split(".", 1)
    cookies[REFRESH_COOKIE]["value"] = f"{int(deadline) + 30 * 24 * 3600}.{rest}"
    fake.auth_calls.clear()

    response = me(client, cookies)

    assert response.json() == {"authenticated": False}
    assert "refresh" not in fake.auth_calls


def test_reusing_an_old_refresh_cookie_ends_the_session(client, fake):
    old = set_cookies(login(client))
    fake.expire_access(old[SESSION_COOKIE]["value"])
    renewed = set_cookies(me(client, old))

    # 저장하지 못한 옛 쿠키로 다시 갱신하면 Auth가 세션 전체를 끊는다.
    assert me(client, {REFRESH_COOKIE: old[REFRESH_COOKIE]}).json() == {"authenticated": False}
    assert me(client, renewed).json() == {"authenticated": False}


def test_refreshed_cookies_are_sent_even_on_an_error_response(client, fake):
    cookies = set_cookies(login(client))
    fake.expire_access(cookies[SESSION_COOKIE]["value"])

    response = client.get("/api/session-then-404", headers=cookie_header(cookies))

    assert response.status_code == 404
    assert set(set_cookies(response)) == {SESSION_COOKIE, REFRESH_COOKIE}


def test_auth_outage_during_refresh_is_503_and_keeps_the_cookies(client, fake):
    cookies = set_cookies(login(client))
    fake.expire_access(cookies[SESSION_COOKIE]["value"])
    fake.auth_down = True

    response = me(client, cookies)

    assert response.status_code == 503
    assert "set-cookie" not in response.headers


def test_garbage_cookies_are_visitor_and_cleared(client, fake):
    response = client.get("/api/me", headers={"Cookie": f"{SESSION_COOKIE}=junk; {REFRESH_COOKIE}=junk"})

    assert response.json() == {"authenticated": False}
    assert all(c["max-age"] == "0" for c in set_cookies(response).values())


# --- 로그아웃의 Auth 세션 끊기 ---


def test_logout_with_an_expired_access_token_still_revokes_via_refresh(client, fake):
    cookies = set_cookies(login(client))
    refresh_token = cookies[REFRESH_COOKIE]["value"].split(".", 2)[2]
    fake.expire_access(cookies[SESSION_COOKIE]["value"])

    response = client.post("/api/auth/logout", headers={**origin(), **cookie_header(cookies)})

    assert response.status_code == 204
    assert not fake.session_alive(refresh_token)


def test_logout_during_an_auth_outage_still_clears_cookies(client, fake):
    cookies = set_cookies(login(client))
    fake.auth_down = True

    response = client.post("/api/auth/logout", headers={**origin(), **cookie_header(cookies)})

    assert response.status_code == 204
    assert all(c["max-age"] == "0" for c in set_cookies(response).values())
