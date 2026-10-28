from fastapi.testclient import TestClient

from support import FakeSupabase, build_app, cookie

MEMBER = "00000000-0000-0000-0000-00000000000a"
OPERATOR = "00000000-0000-0000-0000-00000000000b"
INACTIVE = "00000000-0000-0000-0000-00000000000c"
NO_PROFILE = "00000000-0000-0000-0000-00000000000d"


def make_client() -> TestClient:
    fake = FakeSupabase()
    fake.add_user("member-token", MEMBER)
    fake.add_user("operator-token", OPERATOR, role="operator")
    fake.add_user("inactive-token", INACTIVE, is_active=False)
    fake.add_user("inactive-op-token", "00000000-0000-0000-0000-00000000000e", role="operator", is_active=False)
    fake.sessions["no-profile-token"] = NO_PROFILE  # Auth 사용자는 있지만 profiles 행이 없다
    return TestClient(build_app(fake))


client = make_client()


def error_of(response):
    return response.json()["error"]


# AC-2: 로그인이 필요한 요청에서 비활성 계정은 401
def test_inactive_account_gets_401_on_login_required_endpoint():
    response = client.get("/api/me", headers=cookie("inactive-token"))

    assert response.status_code == 401
    assert error_of(response)["code"] == "login_required"


# AC-2: 공개 읽기에서는 비로그인으로 취급
def test_inactive_account_is_treated_as_anonymous_on_public_endpoint():
    response = client.get("/api/ping", headers=cookie("inactive-token"))

    assert response.status_code == 200
    assert response.json() == {"user_id": None}


def test_inactive_operator_is_treated_as_anonymous():
    assert client.get("/api/ping", headers=cookie("inactive-op-token")).json() == {"user_id": None}
    assert client.get("/api/operator", headers=cookie("inactive-op-token")).status_code == 401


def test_missing_profile_is_login_required_and_anonymous():
    assert client.get("/api/me", headers=cookie("no-profile-token")).status_code == 401
    assert client.get("/api/ping", headers=cookie("no-profile-token")).json() == {"user_id": None}


def test_no_cookie_unknown_and_inactive_responses_are_identical():
    # 세션 없음·무효·비활성·profiles 없음을 응답으로 구분할 수 없다.
    results = [
        client.get("/api/me"),
        client.get("/api/me", headers=cookie("unknown-token")),
        client.get("/api/me", headers=cookie("inactive-token")),
        client.get("/api/me", headers=cookie("no-profile-token")),
    ]
    normalized = [(r.status_code, {k: v for k, v in error_of(r).items() if k != "request_id"}) for r in results]

    assert all(item == normalized[0] for item in normalized)


def test_active_member_passes_login_required():
    response = client.get("/api/me", headers=cookie("member-token"))

    assert response.status_code == 200
    assert response.json() == {"user_id": MEMBER, "role": "member"}


def test_public_endpoint_sees_active_user():
    assert client.get("/api/ping", headers=cookie("member-token")).json() == {"user_id": MEMBER}


def test_visitor_gets_401_member_gets_403_on_operator_endpoint():
    visitor = client.get("/api/operator")
    member = client.get("/api/operator", headers=cookie("member-token"))
    operator = client.get("/api/operator", headers=cookie("operator-token"))

    assert (visitor.status_code, error_of(visitor)["code"]) == (401, "login_required")
    assert (member.status_code, error_of(member)["code"]) == (403, "forbidden")
    assert operator.status_code == 200


def test_activity_is_checked_on_every_request():
    fake = FakeSupabase()
    fake.add_user("tok", MEMBER)
    local = TestClient(build_app(fake))

    assert local.get("/api/me", headers=cookie("tok")).status_code == 200
    fake.profiles[MEMBER] = type(fake.profiles[MEMBER])(role="member", is_active=False)

    assert local.get("/api/me", headers=cookie("tok")).status_code == 401


def test_role_is_read_from_profiles_not_from_the_cookie():
    # 쿠키 값이 무엇이든 역할은 profiles 표에서 온다.
    response = client.get("/api/operator", headers=cookie("member-token"))

    assert response.status_code == 403


def test_revoked_session_is_rejected_immediately():
    fake = FakeSupabase()
    fake.add_user("tok", MEMBER)
    local = TestClient(build_app(fake))
    assert local.get("/api/me", headers=cookie("tok")).status_code == 200

    del fake.sessions["tok"]  # 로그아웃이나 회수로 Auth가 세션을 끊었다

    assert local.get("/api/me", headers=cookie("tok")).status_code == 401
