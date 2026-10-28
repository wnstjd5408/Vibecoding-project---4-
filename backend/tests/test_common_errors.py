import re

import pytest
from fastapi.testclient import TestClient

from app.errors import CATALOG, FIELD_MESSAGES, ApiError
from support import FakeSupabase, build_app, cookie, origin

client = TestClient(build_app(FakeSupabase()), raise_server_exceptions=False)

# API spec v0.2 1.4.6 표를 그대로 옮긴 것이다. 문서가 바뀌면 이 표와 app/errors.py를 함께 고친다.
SPEC_MESSAGES = [
    ("bad_request", "malformed_json", 400, "Request body is not valid JSON"),
    ("bad_request", "idempotency_key_required", 400, "Idempotency-Key header is required"),
    ("bad_request", "idempotency_key_invalid", 400, "Idempotency-Key must be a UUID"),
    ("login_required", None, 401, "Login is required"),
    ("invalid_credentials", None, 401, "Invalid email or password"),
    ("forbidden", None, 403, "Operator permission is required"),
    ("origin_not_allowed", None, 403, "Request origin is not allowed"),
    ("not_found", None, 404, "Resource not found"),
    ("conflict", "already_answered", 409, "This question has already been answered"),
    ("conflict", "answer_first", 409, "Answer the question before requesting a follow-up"),
    ("conflict", "followup_limit_reached", 409, "The follow-up limit for this question has been reached"),
    ("conflict", "in_progress", 409, "The same request is already in progress"),
    ("conflict", "stale_revision", 409, "The note has changed since it was loaded"),
    ("conflict", "result_unavailable", 409, "The result is no longer available; send a new request"),
    ("conflict", "email_exists", 409, "An account with this email already exists"),
    ("payload_too_large", None, 413, "Request is too large"),
    ("unsupported_media_type", None, 415, "Unsupported file type"),
    ("validation_failed", None, 422, "One or more fields are invalid"),
    ("rate_limited", None, 429, "Too many requests; retry later"),
    ("ai_limit_reached", None, 429, "AI usage limit reached; retry later"),
    ("internal_error", None, 500, "Internal server error"),
    ("ai_unavailable", None, 502, "AI service did not return a usable response"),
    ("service_unavailable", None, 503, "Service temporarily unavailable; retry later"),
]

SPEC_FIELD_MESSAGES = {
    "required": "Value is required",
    "too_long": "Value is too long",
    "out_of_range": "Value is out of range",
    "invalid_format": "Value format is invalid",
    "invalid_value": "Value is not allowed or refers to a missing item",
}


# AC-3
def test_catalog_matches_spec_table():
    assert {(c, d): (s, m) for c, d, s, m in SPEC_MESSAGES} == CATALOG
    assert SPEC_FIELD_MESSAGES == FIELD_MESSAGES


@pytest.mark.parametrize(("code", "detail", "status", "message"), SPEC_MESSAGES)
def test_error_response_matches_catalog(code, detail, status, message):
    params = {"code": code}
    if detail:
        params["detail"] = detail

    response = client.get("/api/raise", params=params)

    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert error["message"] == message
    assert error.get("detail") == detail
    assert set(error) <= {"code", "detail", "message", "request_id", "fields", "retry_after_seconds"}


@pytest.mark.parametrize(("code", "detail", "status", "message"), SPEC_MESSAGES)
def test_message_rules(code, detail, status, message):
    # 영어 한 문장, 첫 글자 대문자, 끝에 마침표 없음, 100자 이하 (1.4.6)
    assert message[0].isupper()
    assert not message.endswith(".")
    assert len(message) <= 100
    assert re.fullmatch(r"[\x20-\x7e]+", message)


def test_unlisted_code_detail_pair_cannot_be_raised():
    with pytest.raises(ValueError):
        ApiError("conflict")  # detail 없는 conflict는 카탈로그에 없다
    with pytest.raises(ValueError):
        ApiError("login_required", "expired")


def test_detail_is_only_in_400_and_409():
    for code, detail, status, _ in SPEC_MESSAGES:
        if detail is not None:
            assert status in (400, 409)


def test_internal_error_hides_cause():
    response = client.get("/api/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret internal detail" not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text


def test_unknown_api_path_is_not_found():
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_malformed_json_is_400():
    response = client.post(
        "/api/items", headers={**origin(), "Content-Type": "application/json"}, content="{not json"
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert (error["code"], error["detail"]) == ("bad_request", "malformed_json")


def test_validation_failed_lists_fields_without_values():
    response = client.post("/api/items", headers=origin(), json={"title": "x" * 6, "understanding": 9})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["fields"] == [
        {"name": "title", "reason": "too_long", "message": "Value is too long"},
        {"name": "understanding", "reason": "out_of_range", "message": "Value is out of range"},
    ]
    assert "xxxxxx" not in response.text


def test_missing_and_empty_fields_are_required():
    response = client.post("/api/items", headers=origin(), json={"title": ""})

    fields = {f["name"]: f["reason"] for f in response.json()["error"]["fields"]}
    assert fields == {"title": "required", "understanding": "required"}


def test_wrong_type_is_invalid_format():
    response = client.post("/api/items", headers=origin(), json={"title": "ok", "understanding": "many"})

    assert response.json()["error"]["fields"][0]["reason"] == "invalid_format"


def test_field_reasons_and_messages_are_in_the_allowed_set():
    response = client.post("/api/items", headers=origin(), json={"title": 1, "understanding": []})

    for field in response.json()["error"]["fields"]:
        assert FIELD_MESSAGES[field["reason"]] == field["message"]


def test_supabase_outage_is_503():
    fake = FakeSupabase(down=True)
    fake.add_user("tok", "00000000-0000-0000-0000-000000000001")
    down_client = TestClient(build_app(fake), raise_server_exceptions=False)

    response = down_client.get("/api/me", headers=cookie("tok"))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


# 라우터·엔드포인트가 던진 HTTPException은 카탈로그 응답으로 바뀐다
@pytest.mark.parametrize(
    ("status", "code", "detail", "expected_status"),
    [
        (400, "bad_request", "malformed_json", 400),
        (401, "login_required", None, 401),
        (403, "forbidden", None, 403),
        (404, "not_found", None, 404),
        (405, "not_found", None, 404),
        (413, "payload_too_large", None, 413),
        (415, "unsupported_media_type", None, 415),
        (422, "validation_failed", None, 422),
        (429, "rate_limited", None, 429),
    ],
)
def test_http_exceptions_map_to_catalog_errors(status, code, detail, expected_status):
    response = client.get(f"/api/http/{status}")

    assert response.status_code == expected_status
    error = response.json()["error"]
    assert (error["code"], error.get("detail")) == (code, detail)
    assert error["message"] == CATALOG[(code, detail)][1]
    assert "internal wording" not in response.text


def test_unmapped_client_error_is_500_logged_as_warning(caplog):
    with caplog.at_level("WARNING", logger="app.error"):
        response = client.get("/api/http/418")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert [r.levelname for r in caplog.records if r.name == "app.error"] == ["WARNING"]


def test_server_side_http_exception_is_logged_as_error(caplog):
    with caplog.at_level("WARNING", logger="app.error"):
        response = client.get("/api/http/501")

    assert response.status_code == 500
    assert [r.levelname for r in caplog.records if r.name == "app.error"] == ["ERROR"]


# 422 필드 이름: 스키마의 이름만 쓰고 사용자가 보낸 키는 되돌려 주지 않는다
def post(path, body):
    return client.post(path, headers=origin(), json=body)


def test_unknown_key_name_is_not_echoed():
    response = post("/api/strict", {"title": "a", "<script>secretkey": 1})

    assert response.status_code == 422
    assert response.json()["error"]["fields"] == [
        {"name": "body", "reason": "invalid_format", "message": "Value format is invalid"}
    ]
    assert "secretkey" not in response.text


def test_field_named_like_a_location_keeps_its_name():
    response = post("/api/pathitem", {"path": 1})

    assert [f["name"] for f in response.json()["error"]["fields"]] == ["path"]


def test_nested_field_name_keeps_the_whole_path():
    response = post("/api/parent", {"items": [{"path": 1}]})

    assert [f["name"] for f in response.json()["error"]["fields"]] == ["items.0.path"]


def test_overlong_or_odd_field_names_become_body():
    response = post("/api/strict", {"title": "a", "x" * 200: 1})

    assert [f["name"] for f in response.json()["error"]["fields"]] == ["body"]
