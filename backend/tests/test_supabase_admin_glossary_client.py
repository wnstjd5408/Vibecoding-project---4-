"""운영자 사전(MEG-81) Supabase 래퍼의 HTTP 모양. 실제 요청 주소·필터·헤더·본문을 고정한다. 네트워크 없이 돈다.

같은 호출은 2026-11-02 로컬 Supabase(일회용 스택)에서 E2E로도 확인했다. 여기서는 그 모양이 바뀌지 않게 지킨다.
"""

import json

import httpx
import pytest

from app.supabase import SupabaseClient, SupabaseConfigError, SupabaseUnavailable

OPERATOR = "00000000-0000-0000-0000-0000000000a1"


def recording_client(responses):
    """요청을 순서대로 기록하고 responses의 응답을 차례로 돌려준다."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[len(seen) - 1]

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = SupabaseClient("https://project.supabase.co/", "sb_secret_test", http, glossary_image_bucket="glossary-images")
    return client, seen


def test_list_uses_inner_embed_desc_order_limit_and_lt_cursor():
    client, seen = recording_client([httpx.Response(200, json=[
        {"id": 9, "key": "k", "label": "K", "glossary_entries": {"term_id": 9}},
    ])])
    assert client.list_admin_glossary_terms(3, 12) == [{"id": 9, "key": "k", "label": "K"}]
    params = dict(seen[0].url.params)
    assert seen[0].url.path == "/rest/v1/terms"
    assert params == {"select": "id,key,label,glossary_entries!inner(term_id)", "order": "id.desc", "limit": "3", "id": "lt.12"}


def test_list_without_cursor_has_no_id_filter():
    client, seen = recording_client([httpx.Response(200, json=[])])
    client.list_admin_glossary_terms(101, None)
    assert "id" not in dict(seen[0].url.params)


def test_upsert_calls_the_rpc_with_named_arguments():
    result = {"id": 1, "key": "k", "label": "K", "created": True}
    client, seen = recording_client([httpx.Response(200, json=result)])
    assert client.upsert_glossary_entry("k", "K", "body", OPERATOR) == result
    assert seen[0].url.path == "/rest/v1/rpc/glossary_upsert_entry"
    assert json.loads(seen[0].content) == {"p_key": "k", "p_label": "K", "p_body_markdown": "body", "p_updated_by": OPERATOR}


def test_delete_entry_passes_the_bucket_and_maps_null_to_none():
    client, seen = recording_client([httpx.Response(200, content=b"null"), httpx.Response(200, json={"jobs": []})])
    assert client.delete_glossary_entry(7) is None
    assert client.delete_glossary_entry(7) == []
    assert json.loads(seen[0].content) == {"p_term_id": 7, "p_bucket": "glossary-images"}


def test_upload_job_insert_returns_the_new_id():
    client, seen = recording_client([httpx.Response(201, json=[{"id": 41}])])
    assert client.create_glossary_upload_job("terms/7/a.png") == 41
    assert seen[0].url.path == "/rest/v1/storage_delete_jobs"
    assert seen[0].headers["prefer"] == "return=representation"
    assert json.loads(seen[0].content) == {"bucket": "glossary-images", "object_path": "terms/7/a.png"}


def test_upload_posts_bytes_without_upsert_to_the_quoted_path():
    client, seen = recording_client([httpx.Response(200, json={"Key": "x"})])
    client.upload_glossary_image("terms/7/a b.png", b"PNGDATA", "image/png")
    request = seen[0]
    assert request.method == "POST"
    assert request.url.raw_path == b"/storage/v1/object/glossary-images/terms/7/a%20b.png"
    assert request.headers["content-type"] == "image/png"
    assert request.headers["x-upsert"] == "false"
    assert request.content == b"PNGDATA"


@pytest.mark.parametrize("status,error", [(400, SupabaseConfigError), (409, SupabaseConfigError),
                                          (503, SupabaseUnavailable), (429, SupabaseUnavailable)])
def test_upload_failures_map_to_config_or_unavailable(status, error):
    client, _ = recording_client([httpx.Response(status, json={})])
    with pytest.raises(error):
        client.upload_glossary_image("terms/7/a.png", b"x", "image/png")


def test_remove_objects_deletes_by_prefixes_then_marks_pending_jobs_done():
    client, seen = recording_client([httpx.Response(200, json=[]), httpx.Response(204)])
    client.remove_glossary_objects([{"job_id": 3, "object_path": "terms/7/a.png"},
                                    {"job_id": 4, "object_path": "terms/7/b.png"}])
    delete, patch = seen
    assert delete.method == "DELETE" and delete.url.path == "/storage/v1/object/glossary-images"
    assert json.loads(delete.content) == {"prefixes": ["terms/7/a.png", "terms/7/b.png"]}
    assert patch.method == "PATCH" and patch.url.path == "/rest/v1/storage_delete_jobs"
    assert dict(patch.url.params) == {"id": "in.(3,4)", "status": "eq.pending"}
    assert json.loads(patch.content)["status"] == "done"


def test_remove_objects_failure_does_not_mark_jobs_done():
    client, seen = recording_client([httpx.Response(500, json={})])
    with pytest.raises(SupabaseUnavailable):
        client.remove_glossary_objects([{"job_id": 3, "object_path": "terms/7/a.png"}])
    assert len(seen) == 1


def test_no_jobs_means_no_requests():
    client, seen = recording_client([])
    client.remove_glossary_objects([])
    assert seen == []


def test_add_image_returns_id_or_none():
    client, seen = recording_client([httpx.Response(200, json=55), httpx.Response(200, content=b"null")])
    assert client.add_glossary_image(7, "terms/7/a.png", None, 41) == 55
    assert client.add_glossary_image(7, "terms/7/a.png", None, 41) is None
    assert json.loads(seen[0].content) == {"p_term_id": 7, "p_storage_path": "terms/7/a.png", "p_alt": None, "p_job_id": 41}


def test_writes_without_bucket_are_config_errors():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    client = SupabaseClient("https://project.supabase.co", "sb_secret_test", http)
    for call in (lambda: client.delete_glossary_entry(1), lambda: client.delete_glossary_image(1, 2),
                 lambda: client.create_glossary_upload_job("p"), lambda: client.upload_glossary_image("p", b"", "image/png")):
        with pytest.raises(SupabaseConfigError):
            call()
