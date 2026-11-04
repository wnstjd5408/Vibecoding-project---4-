"""E15~E18 HTTP 권한·검증·계약 시험. SQL 동작은 별도 실제 DB 시험으로 검증한다."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import admin_notes
from app.common import install_common_layer
from app.rate_limit import WRITE
from app.supabase import SupabaseConfigError, SupabaseUnavailable, get_supabase
from support import FakeSupabase, cookie, origin


@pytest.fixture
def setup():
    fake = FakeSupabase()
    fake.add_user("operator", "00000000-0000-0000-0000-000000000001", role="operator")
    fake.add_user("member", "00000000-0000-0000-0000-000000000002")
    fake.add_user("inactive", "00000000-0000-0000-0000-000000000003", role="operator", is_active=False)
    note = {
        "id": 1, "revision": 1, "title": "합성 노트", "body_markdown": "body ![](note-image:b1)",
        "studied_on": None, "study_minutes": 10, "importance": "상", "understanding": 3,
        "needs_review": True, "memo": "private memo", "is_published": False, "parent_note_id": None,
        "created_at": "2026-11-03T00:00:00Z", "updated_at": "2026-11-03T00:00:00Z",
        "note_subjects": [{"subjects": {"id": 2, "name": "합성 과목"}}],
        "note_sources": [{"id": 1, "url": "https://example.com", "label": "출처"}],
        "note_images": [], "notion_page_id": "must-not-leak", "imported_at": "must-not-leak",
    }
    fake.get_admin_note = Mock(return_value=note)
    fake.create_note = Mock(return_value={"id": 1, "revision": 1})
    fake.update_note = Mock(return_value={"status": "ok", "id": 1, "revision": 2, "is_published": True})
    fake.delete_note = Mock(return_value={"status": "ok", "jobs": []})
    fake.retry_note_image_deletions = Mock()
    app = FastAPI()
    install_common_layer(app)
    app.include_router(admin_notes.router)
    app.dependency_overrides[get_supabase] = lambda: fake
    with TestClient(app) as client:
        yield client, fake, note


def request(client, method, token="operator", body=None, note_id="1", with_origin=True):
    headers = origin() if with_origin else {}
    if token:
        headers.update(cookie(token))
    path = "/api/admin/notes" + ("" if method == "POST" else f"/{note_id}")
    return client.request(method, path, headers=headers, json=body)


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
@pytest.mark.parametrize("token,status", [(None, 401), ("invalid", 401), ("inactive", 401), ("member", 403)])
def test_role_matrix_denies_before_note_access(setup, method, token, status):
    client, fake, _ = setup
    response = request(client, method, token, {"title": "valid"} if method in ("POST", "PATCH") else None)
    assert response.status_code == status
    assert response.headers["cache-control"] == "private, no-store"
    for call in (fake.get_admin_note, fake.create_note, fake.update_note, fake.delete_note, fake.retry_note_image_deletions):
        call.assert_not_called()


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_origin_is_required_before_mutation(setup, method):
    client, fake, _ = setup
    assert request(client, method, body={"title": "valid"}, with_origin=False).json()["error"]["code"] == "origin_not_allowed"
    fake.create_note.assert_not_called()
    fake.update_note.assert_not_called()
    fake.delete_note.assert_not_called()


def test_create_defaults_to_private_and_returns_only_id_revision(setup):
    client, fake, _ = setup
    response = request(client, "POST", body={"title": "합성"})
    assert response.status_code == 201
    assert response.json() == {"id": 1, "revision": 1}
    payload = fake.create_note.call_args.args[0]
    assert payload["is_published"] is False
    assert payload["body_markdown"] == ""
    assert payload["needs_review"] is False
    assert "revision" not in payload


def test_patch_preserves_omitted_fields_and_explicit_null(setup):
    client, fake, _ = setup
    response = request(client, "PATCH", body={"memo": None, "is_published": True, "expected_revision": 1})
    assert response.status_code == 200
    assert response.json() == {"id": 1, "revision": 2, "is_published": True}
    fake.update_note.assert_called_once_with(1, {"memo": None, "is_published": True}, 1)


def test_patch_empty_and_date_payload(setup):
    client, fake, _ = setup
    assert request(client, "PATCH", body={}).status_code == 200
    fake.update_note.assert_called_with(1, {}, None)
    assert request(client, "PATCH", body={"studied_on": "2026-11-03"}).status_code == 200
    fake.update_note.assert_called_with(1, {"studied_on": "2026-11-03"}, None)


@pytest.mark.parametrize("status,http,detail", [("stale_revision", 409, "stale_revision"), ("not_found", 404, None)])
def test_patch_maps_rpc_results(setup, status, http, detail):
    client, fake, _ = setup
    fake.update_note.return_value = {"status": status}
    response = request(client, "PATCH", body={"title": "changed", "expected_revision": 1})
    assert response.status_code == http
    assert response.json()["error"].get("detail") == detail


@pytest.mark.parametrize("body,name,reason", [
    ({}, "title", "required"), ({"title": ""}, "title", "required"),
    ({"title": "  "}, "title", "required"), ({"title": "x" * 301}, "title", "too_long"),
    ({"title": 1}, "title", "invalid_format"), ({"title": "x\x00"}, "title", "invalid_format"),
    ({"body_markdown": "x" * 200001}, "body_markdown", "too_long"),
    ({"study_minutes": -1}, "study_minutes", "out_of_range"),
    ({"study_minutes": 2**31}, "study_minutes", "out_of_range"),
    ({"study_minutes": True}, "study_minutes", "invalid_format"),
    ({"understanding": 0}, "understanding", "out_of_range"),
    ({"understanding": 6}, "understanding", "out_of_range"),
    ({"importance": "other"}, "importance", "invalid_value"),
    ({"is_published": "false"}, "is_published", "invalid_format"),
    ({"is_published": None}, "is_published", "invalid_format"),
    ({"needs_review": None}, "needs_review", "invalid_format"),
    ({"body_markdown": None}, "body_markdown", "invalid_format"),
    ({"studied_on": "2026-02-30"}, "studied_on", "invalid_format"),
    ({"studied_on": 0}, "studied_on", "invalid_format"),
    ({"memo": "x\x00"}, "memo", "invalid_format"),
])
def test_invalid_create_never_writes(setup, body, name, reason):
    client, fake, _ = setup
    payload = {"title": "valid", **body} if body else {}
    response = request(client, "POST", body=payload)
    assert response.status_code == 422
    assert any(f["name"] == name and f["reason"] == reason for f in response.json()["error"]["fields"])
    fake.create_note.assert_not_called()


@pytest.mark.parametrize("field", ["subject_ids", "sources", "parent_note_id", "notion_page_id", "imported_at", "revision", "user_id"])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_unsupported_fields_cannot_be_written(setup, field, method):
    client, fake, _ = setup
    assert request(client, method, body={"title": "valid", field: None}).status_code == 422
    fake.create_note.assert_not_called()
    fake.update_note.assert_not_called()


@pytest.mark.parametrize("revision", [0, -1, 2**31, True, "1", 1.2])
def test_invalid_revision(setup, revision):
    client, fake, _ = setup
    assert request(client, "PATCH", body={"expected_revision": revision}).status_code == 422
    fake.update_note.assert_not_called()


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
@pytest.mark.parametrize("note_id", ["0", "-1", "abc", str(2**63)])
def test_invalid_path_is_404(setup, method, note_id):
    client, fake, _ = setup
    assert request(client, method, note_id=note_id, body={} if method == "PATCH" else None).status_code == 404
    fake.get_admin_note.assert_not_called()
    fake.update_note.assert_not_called()
    fake.delete_note.assert_not_called()


def test_read_private_fields_and_images_without_internal_metadata(setup):
    client, fake, note = setup
    note["note_images"] = [{"notion_block_id": "b1", "storage_path": "notes/1.png", "alt": "합성"}]
    fake.stored_images.add("notes/1.png")
    response = request(client, "GET")
    assert response.status_code == 200
    data = response.json()
    assert data["memo"] == "private memo"
    assert data["is_published"] is False
    assert data["body_markdown"] == note["body_markdown"]
    assert data["images"]["b1"]["alt"] == "합성"
    assert fake.sign_calls == [(["notes/1.png"], 300)]
    assert not {"notion_page_id", "imported_at", "note_images", "storage_path", "bucket"} & data.keys()
    assert "must-not-leak" not in response.text


@pytest.mark.parametrize("failure", ["missing", "down", "config"])
def test_e15_image_failure_is_503_not_partial_success(setup, failure):
    client, fake, note = setup
    note["note_images"] = [{"notion_block_id": "b1", "storage_path": "notes/1.png", "alt": None}]
    fake.storage_down = failure == "down"
    fake.bucket_configured = failure != "config"
    response = request(client, "GET")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "notes/1.png" not in response.text


def test_missing_read_and_delete(setup):
    client, fake, _ = setup
    fake.get_admin_note.return_value = None
    fake.delete_note.return_value = {"status": "not_found"}
    assert request(client, "GET").status_code == 404
    assert request(client, "DELETE").status_code == 404
    fake.retry_note_image_deletions.assert_not_called()


@pytest.mark.parametrize("failure", [None, SupabaseUnavailable("private upstream detail"), SupabaseConfigError("private bucket")])
def test_delete_commits_before_storage_and_stays_204_on_failure(setup, failure):
    client, fake, _ = setup
    events = []
    fake.delete_note.side_effect = lambda _: events.append("commit") or {"status": "ok"}
    def retry():
        events.append("storage")
        if failure:
            raise failure
    fake.retry_note_image_deletions.side_effect = retry
    response = request(client, "DELETE")
    assert response.status_code == 204
    assert response.content == b""
    assert events == ["commit", "storage"]


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_writes_are_rate_limited(setup, method):
    client, fake, _ = setup
    body = {"title": "valid"} if method != "DELETE" else None
    for _ in range(WRITE.limit):
        assert request(client, method, body=body).status_code in (200, 201, 204)
    assert request(client, method, body=body).status_code == 429


def test_real_app_registers_all_four_routes():
    from app.main import app
    schema = app.openapi()["paths"]
    assert "post" in schema["/api/admin/notes"]
    assert {"get", "patch", "delete"} <= schema["/api/admin/notes/{note_id}"].keys()
