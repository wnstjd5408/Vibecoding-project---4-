"""운영자 신고 목록·처리(MEG-83) Supabase 래퍼의 HTTP 모양. 실제 요청 주소·필터·헤더·본문을 고정한다. 네트워크 없이 돈다.

실제 로컬 Supabase에서도 같은 호출을 확인한다(docs/backend-local-guide.md 8절). 여기서는 그 모양이 바뀌지 않게 지킨다.
"""

import json

import httpx
import pytest

from app.supabase import SupabaseClient, SupabaseConfigError, SupabaseUnavailable

SELECT = (
    "id,status,body,ai_explanation_id,quiz_item_id,"
    "ai_explanations(term_key_snapshot,body),quiz_items(question,answer)"
)


def recording_client(responses):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[len(seen) - 1]

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseClient("https://project.supabase.co/", "sb_secret_test", http), seen


AI_ROW = {
    "id": 9, "status": "open", "body": "합성", "ai_explanation_id": 3, "quiz_item_id": None,
    "ai_explanations": {"term_key_snapshot": "fixture alpha", "body": "합성 설명"}, "quiz_items": None,
}
ITEM_ROW = {
    "id": 8, "status": "open", "body": "", "ai_explanation_id": None, "quiz_item_id": 5,
    "ai_explanations": None, "quiz_items": {"question": "Q?", "answer": "A"},
}


def test_list_filters_by_status_orders_desc_and_embeds_the_target_without_the_reporter():
    client, seen = recording_client([httpx.Response(200, json=[AI_ROW, ITEM_ROW])])
    reports = client.list_admin_reports("open", 3, None)
    params = dict(seen[0].url.params)
    assert seen[0].url.path == "/rest/v1/reports"
    assert params == {"status": "eq.open", "select": SELECT, "order": "id.desc", "limit": "3"}
    assert "user_id" not in params["select"]
    assert reports == [
        {"id": 9, "status": "open", "body": "합성", "target": {
            "type": "ai_explanation", "id": 3, "term_key_snapshot": "fixture alpha", "body": "합성 설명"}},
        {"id": 8, "status": "open", "body": "", "target": {"type": "quiz_item", "id": 5, "question": "Q?", "answer": "A"}},
    ]


def test_list_with_cursor_adds_a_less_than_filter():
    client, seen = recording_client([httpx.Response(200, json=[])])
    assert client.list_admin_reports("resolved", 101, 12) == []
    params = dict(seen[0].url.params)
    assert params["id"] == "lt.12" and params["status"] == "eq.resolved" and params["limit"] == "101"


def test_list_rejects_an_unknown_status_before_calling():
    client, seen = recording_client([])
    with pytest.raises(ValueError):
        client.list_admin_reports("closed", 10, None)
    assert seen == []


@pytest.mark.parametrize("row", [
    {**AI_ROW, "ai_explanations": None},
    {**ITEM_ROW, "quiz_items": None},
])
def test_list_fails_loudly_when_a_target_row_is_missing_instead_of_dropping_it(row):
    client, _ = recording_client([httpx.Response(200, json=[row])])
    with pytest.raises(SupabaseConfigError):
        client.list_admin_reports("open", 10, None)


def test_list_failure_status_is_a_configuration_error():
    client, _ = recording_client([httpx.Response(401, json={"message": "secret-detail"})])
    with pytest.raises(SupabaseConfigError) as error:
        client.list_admin_reports("open", 10, None)
    assert "secret-detail" not in str(error.value)


def test_get_report_reads_status_and_explanation_id_only():
    client, seen = recording_client([httpx.Response(200, json=[{"id": 4, "status": "open", "ai_explanation_id": 2}])])
    assert client.get_admin_report(4) == {"id": 4, "status": "open", "ai_explanation_id": 2}
    assert dict(seen[0].url.params) == {"id": "eq.4", "select": "id,status,ai_explanation_id", "limit": "1"}


def test_get_report_returns_none_when_missing():
    client, _ = recording_client([httpx.Response(200, json=[])])
    assert client.get_admin_report(4) is None


def test_invalidate_calls_the_existing_function_with_only_the_explanation_id():
    client, seen = recording_client([httpx.Response(200, json=1), httpx.Response(200, json=0)])
    assert client.invalidate_ai_explanation(3) == 1
    assert client.invalidate_ai_explanation(3) == 0
    assert seen[0].url.path == "/rest/v1/rpc/ai_invalidate_explanations"
    assert json.loads(seen[0].content) == {"p_note_id": None, "p_term_id": None, "p_explanation_id": 3}


def test_invalidate_failure_is_a_configuration_error():
    client, _ = recording_client([httpx.Response(404, json={"message": "no function"})])
    with pytest.raises(SupabaseConfigError):
        client.invalidate_ai_explanation(3)


def test_mark_resolved_only_touches_open_reports_and_sets_the_time():
    client, seen = recording_client([httpx.Response(200, json=[{"id": 4}]), httpx.Response(200, json=[])])
    assert client.mark_report_resolved(4, "2026-11-02T00:00:00+00:00") is True
    assert client.mark_report_resolved(4, "2026-11-02T00:00:00+00:00") is False  # 이미 처리돼 바뀐 행이 없다
    request = seen[0]
    assert request.method == "PATCH" and request.url.path == "/rest/v1/reports"
    assert dict(request.url.params) == {"id": "eq.4", "status": "eq.open", "select": "id"}
    assert json.loads(request.content) == {"status": "resolved", "resolved_at": "2026-11-02T00:00:00+00:00"}
    assert request.headers["prefer"] == "return=representation"


def test_mark_resolved_failure_is_a_configuration_error():
    client, _ = recording_client([httpx.Response(401, json={"message": "secret-detail"})])
    with pytest.raises(SupabaseConfigError) as error:
        client.mark_report_resolved(4, "2026-11-02T00:00:00+00:00")
    assert "secret-detail" not in str(error.value)


def test_network_failure_surfaces_as_unavailable():
    def handler(request):
        raise httpx.ConnectError("down")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = SupabaseClient("https://project.supabase.co/", "sb_secret_test", http)
    with pytest.raises(SupabaseUnavailable):
        client.get_admin_report(4)
