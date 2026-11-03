"""HTTP 계약과 삭제 재시도 경계를 확인한다. 합성 응답만 사용한다."""

import json

import httpx
import pytest

from app.supabase import SupabaseClient, SupabaseConfigError, SupabaseUnavailable


def client_for(responses, bucket="note-images"):
    seen = []
    def handler(request):
        seen.append(request)
        return responses[len(seen) - 1]
    client = SupabaseClient("https://project.supabase.co", "sb_secret_test",
                            httpx.Client(transport=httpx.MockTransport(handler)), note_image_bucket=bucket)
    return client, seen


def test_read_uses_explicit_operator_columns_and_no_published_filter():
    client, seen = client_for([httpx.Response(200, json=[{"id": 7}])])
    assert client.get_admin_note(7) == {"id": 7}
    params = dict(seen[0].url.params)
    assert params["id"] == "eq.7"
    assert "memo" in params["select"]
    assert "notion_page_id" not in params["select"]
    assert "imported_at" not in params["select"]
    assert "is_published" not in params


def test_create_is_one_insert_with_representation():
    client, seen = client_for([httpx.Response(201, json=[{"id": 7, "revision": 1}])])
    assert client.create_note({"title": "합성", "is_published": False}) == {"id": 7, "revision": 1}
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/rest/v1/notes"
    assert seen[0].url.params["select"] == "id,revision"
    assert seen[0].headers["prefer"] == "return=representation"
    assert json.loads(seen[0].content)["is_published"] is False


def test_update_uses_single_atomic_rpc_with_expected_revision():
    client, seen = client_for([httpx.Response(200, json={"status": "stale_revision"})])
    assert client.update_note(7, {"title": "new"}, 2) == {"status": "stale_revision"}
    assert seen[0].url.path == "/rest/v1/rpc/note_update"
    assert json.loads(seen[0].content) == {"p_note_id": 7, "p_fields": {"title": "new"}, "p_expected_revision": 2}
    assert len(seen) == 1


def test_delete_uses_configured_bucket_in_atomic_rpc():
    client, seen = client_for([httpx.Response(200, json={"status": "ok", "jobs": []})])
    assert client.delete_note(7)["status"] == "ok"
    assert seen[0].url.path == "/rest/v1/rpc/note_delete"
    assert json.loads(seen[0].content) == {"p_note_id": 7, "p_bucket": "note-images"}


def test_missing_bucket_prevents_delete():
    client, seen = client_for([], bucket=None)
    with pytest.raises(SupabaseConfigError):
        client.delete_note(7)
    assert not seen


def test_retry_reads_old_pending_note_jobs_only_and_marks_done_after_storage():
    client, seen = client_for([
        httpx.Response(200, json=[{"id": 4, "object_path": "old/a.png"}, {"id": 8, "object_path": "new/b.png"}]),
        httpx.Response(200, json=[]), httpx.Response(204),
    ])
    client.retry_note_image_deletions()
    assert dict(seen[0].url.params) == {"bucket": "eq.note-images", "status": "eq.pending",
                                        "select": "id,object_path", "order": "id.asc", "limit": "100"}
    assert seen[1].method == "DELETE"
    assert seen[1].url.path == "/storage/v1/object/note-images"
    assert sorted(json.loads(seen[1].content)["prefixes"]) == ["new/b.png", "old/a.png"]
    assert seen[2].url.params["id"] == "in.(4,8)"
    assert seen[2].url.params["bucket"] == "eq.note-images"
    assert json.loads(seen[2].content)["status"] == "done"


@pytest.mark.parametrize("status", [400, 403, 500, 503])
def test_failed_storage_delete_does_not_mark_done(status):
    client, seen = client_for([httpx.Response(200, json=[{"id": 4, "object_path": "a.png"}]),
                             httpx.Response(status, json={"message": "upstream private text"})])
    with pytest.raises((SupabaseConfigError, SupabaseUnavailable)):
        client.retry_note_image_deletions()
    assert len(seen) == 2


def test_empty_retry_does_not_call_storage():
    client, seen = client_for([httpx.Response(200, json=[])])
    client.retry_note_image_deletions()
    assert len(seen) == 1


@pytest.mark.parametrize("method", ["update", "delete"])
def test_unexpected_rpc_result_fails_closed(method):
    client, _ = client_for([httpx.Response(200, json={"status": "unknown"})])
    with pytest.raises(SupabaseConfigError):
        client.update_note(1, {}, None) if method == "update" else client.delete_note(1)
