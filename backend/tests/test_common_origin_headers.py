import pytest
from fastapi.testclient import TestClient

from support import ALLOWED_ORIGIN, FakeSupabase, build_app, origin

client = TestClient(build_app(FakeSupabase()))

STATE_CHANGING = ["post", "put", "patch", "delete"]


def assert_origin_rejected(response):
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "origin_not_allowed"
    assert error["message"] == "Request origin is not allowed"


# AC-1
@pytest.mark.parametrize("method", STATE_CHANGING)
def test_state_changing_request_without_origin_is_rejected(method):
    assert_origin_rejected(getattr(client, method)("/api/write"))


@pytest.mark.parametrize("method", STATE_CHANGING)
@pytest.mark.parametrize(
    "value",
    ["https://evil.example", "null", "http://localhost:5174", "http://localhost:5173.evil.example", ""],
)
def test_state_changing_request_with_other_origin_is_rejected(method, value):
    assert_origin_rejected(getattr(client, method)("/api/write", headers=origin(value)))


@pytest.mark.parametrize("method", STATE_CHANGING)
def test_state_changing_request_with_allowed_origin_passes(method):
    response = getattr(client, method)("/api/write", headers=origin())

    assert response.status_code == 200


def test_origin_match_ignores_case_and_trailing_slash():
    response = client.post("/api/write", headers=origin("HTTP://LOCALHOST:5173/"))

    assert response.status_code == 200


def test_get_does_not_need_origin():
    assert client.get("/api/write").status_code == 200


def test_origin_is_checked_before_session_and_body_validation():
    # 검사 순서 1번(Origin)이 인증·형식 검사보다 앞선다.
    response = client.post("/api/items", json={})

    assert_origin_rejected(response)


def test_origin_check_does_not_apply_outside_api():
    # /api 밖에는 Origin 검사가 없다. 405가 not_found(404)로 바뀔 뿐 403이 아니다.
    assert client.post("/outside").status_code == 404


def test_allowed_origins_come_from_environment(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example.com, http://localhost:5173")
    app_client = TestClient(build_app(FakeSupabase()))

    assert app_client.post("/api/write", headers=origin("https://app.example.com")).status_code == 200
    assert_origin_rejected(app_client.post("/api/write", headers=origin("https://other.example.com")))


def test_origin_value_is_not_echoed_in_error_body():
    response = client.post("/api/write", headers=origin("https://evil.example"))

    assert "evil.example" not in response.text


# 1.3 응답 헤더
@pytest.mark.parametrize(
    "request_fn",
    [
        lambda: client.get("/api/ping"),
        lambda: client.get("/api/me"),  # 401
        lambda: client.get("/api/missing"),  # 404
        lambda: client.post("/api/write"),  # 403 origin
        lambda: client.post("/api/items", headers=origin(), json={}),  # 422
        lambda: client.get("/api/boom"),  # 500
    ],
)
def test_api_responses_have_no_store_and_request_id(request_fn):
    response = request_fn()

    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Request-Id"].startswith("r-")
    if response.status_code >= 400:
        assert response.json()["error"]["request_id"] == response.headers["X-Request-Id"]


def test_cache_control_is_not_added_outside_api():
    assert "Cache-Control" not in client.get("/outside").headers


def test_client_request_id_is_ignored():
    response = client.get("/api/ping", headers={"X-Request-Id": "r-attacker"})

    assert response.headers["X-Request-Id"] != "r-attacker"


def test_request_ids_differ_between_requests():
    ids = {client.get("/api/ping").headers["X-Request-Id"] for _ in range(5)}

    assert len(ids) == 5


def test_cors_allows_credentials_only_for_allowed_origin():
    allowed = client.options(
        "/api/write",
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    other = client.options(
        "/api/write",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert allowed.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in other.headers


def test_unusual_methods_without_origin_are_rejected_too():
    # 상태 변경 메서드를 목록으로 열거하지 않고 GET·HEAD·OPTIONS 밖은 전부 검사한다.
    for method in ("PROPFIND", "MKCOL", "TRACE"):
        assert_origin_rejected(client.request(method, "/api/write"))


def test_head_does_not_need_origin():
    assert client.head("/api/write").status_code != 403


def test_origin_list_is_fixed_when_the_app_is_built(monkeypatch):
    # CORS와 Origin 검사가 같은 목록을 쓴다. 뒤늦게 환경변수가 바뀌어도 둘이 어긋나지 않는다.
    app_client = TestClient(build_app(FakeSupabase()))
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://late.example.com")

    assert app_client.post("/api/write", headers=origin()).status_code == 200
    assert_origin_rejected(app_client.post("/api/write", headers=origin("https://late.example.com")))


def test_access_log_is_emitted_with_route_template(caplog):
    with caplog.at_level("INFO", logger="app.access"):
        response = client.get("/api/ping")

    lines = [r.getMessage() for r in caplog.records if r.name == "app.access"]
    assert len(lines) == 1
    assert f"request_id={response.headers['X-Request-Id']}" in lines[0]
    assert "path=/api/ping" in lines[0] and "status=200" in lines[0]


def test_access_log_has_codes_and_no_origin_value(caplog):
    with caplog.at_level("INFO", logger="app.access"):
        client.post("/api/write", headers=origin("https://evil.example"))

    line = next(r.getMessage() for r in caplog.records if r.name == "app.access")
    assert "code=origin_not_allowed" in line and "stage=origin" in line
    assert "evil.example" not in line


def test_info_logging_is_enabled_by_the_common_layer():
    import logging

    assert logging.getLogger("app.access").isEnabledFor(logging.INFO)


def test_client_disconnect_is_not_logged_as_a_server_error(caplog):
    with caplog.at_level("INFO", logger="app"):
        response = TestClient(build_app(FakeSupabase()), raise_server_exceptions=False).get("/api/disconnect")

    assert response.status_code == 499
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
    assert response.headers["X-Request-Id"].startswith("r-")


def test_other_runtime_errors_are_still_internal_errors():
    response = TestClient(build_app(FakeSupabase()), raise_server_exceptions=False).get("/api/runtime")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
