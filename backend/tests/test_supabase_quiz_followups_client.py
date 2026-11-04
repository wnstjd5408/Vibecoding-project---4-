"""꼬리 질문 생성(MEG-93) Supabase 래퍼의 HTTP 모양. 실제 요청 주소·필터·헤더·본문과 오류 판정을 고정한다. 네트워크 없이 돈다.

같은 호출은 실제 로컬 Supabase에서도 확인한다(docs/backend-local-guide.md). 여기서는 그 모양이 바뀌지 않게 지킨다.
"""

import json

import httpx
import pytest

from app.supabase import SupabaseClient, SupabaseConfigError, SupabaseUnavailable

USER_ID = "00000000-0000-4000-8000-00000000000a"
PKEY = {"code": "23505", "message": 'duplicate key value violates unique constraint "quiz_followups_pkey"'}
ITEM_FK = {
    "code": "23503",
    "message": 'insert or update on table "quiz_followups" violates foreign key constraint "quiz_followups_item_id_fkey"',
}


def recording_client(responses):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[len(seen) - 1]

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseClient("https://project.supabase.co/", "sb_secret_test", http), seen


# --- get_quiz_item_for_followup ---


def test_the_item_is_read_with_its_material_answer_and_slots_including_the_reservation_time():
    row = {"id": 7, "question": "q", "answer": "a", "explanation": "e", "quiz_answers": {"user_answer": "u"}, "quiz_followups": []}
    client, seen = recording_client([httpx.Response(200, json=[row])])
    assert client.get_quiz_item_for_followup(USER_ID, 7) == row
    request = seen[0]
    assert request.method == "GET" and request.url.path == "/rest/v1/quiz_items"
    params = dict(request.url.params)
    assert params["id"] == "eq.7" and params["quiz_sets.user_id"] == f"eq.{USER_ID}"
    assert "quiz_sets!inner(user_id)" in params["select"]
    assert "question,answer,explanation" in params["select"]
    assert "quiz_followups(seq,question,user_answer,created_at)" in params["select"]
    assert params["quiz_followups.order"] == "seq.asc" and params["limit"] == "1"


def test_another_users_item_is_none():
    client, _ = recording_client([httpx.Response(200, json=[])])
    assert client.get_quiz_item_for_followup(USER_ID, 7) is None


# --- reserve_followup_slot ---


def test_reserving_a_slot_inserts_only_the_key_without_ignoring_duplicates():
    client, seen = recording_client([httpx.Response(201)])
    assert client.reserve_followup_slot(7, 1) is True
    request = seen[0]
    assert request.method == "POST" and request.url.path == "/rest/v1/quiz_followups"
    assert json.loads(request.content) == {"item_id": 7, "seq": 1}  # question·user_answer는 비워 둔다
    assert request.headers["prefer"] == "return=minimal"  # 충돌을 무시하면 누가 예약했는지 알 수 없다


def test_a_slot_already_reserved_by_another_request_is_false():
    client, _ = recording_client([httpx.Response(409, json=PKEY)])
    assert client.reserve_followup_slot(7, 1) is False


def test_a_missing_item_foreign_key_is_none():
    client, _ = recording_client([httpx.Response(409, json=ITEM_FK)])
    assert client.reserve_followup_slot(7, 1) is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(409, json={"code": "23505", "message": "duplicate key other_index"}),
        httpx.Response(409, json={"code": "23503", "message": "other foreign key"}),
        httpx.Response(400, json={"code": "23514", "message": "quiz_followups_seq_check"}),
        httpx.Response(401, json={"message": "secret-detail"}),
        httpx.Response(403),
    ],
)
def test_other_reservation_rejections_are_configuration_errors_without_the_server_message(response):
    client, _ = recording_client([response])
    with pytest.raises(SupabaseConfigError) as raised:
        client.reserve_followup_slot(7, 1)
    assert "secret-detail" not in str(raised.value)


def test_a_server_outage_while_reserving_is_unavailable():
    client, _ = recording_client([httpx.Response(503)])
    with pytest.raises(SupabaseUnavailable):
        client.reserve_followup_slot(7, 1)


# --- fill_followup_slot ---


def test_filling_updates_only_a_slot_whose_question_is_still_empty():
    client, seen = recording_client([httpx.Response(200, json=[{"seq": 1}])])
    assert client.fill_followup_slot(7, 1, "질문?") is True
    request = seen[0]
    assert request.method == "PATCH" and request.url.path == "/rest/v1/quiz_followups"
    assert dict(request.url.params) == {"item_id": "eq.7", "seq": "eq.1", "question": "is.null", "select": "seq"}
    assert json.loads(request.content) == {"question": "질문?"}
    assert request.headers["prefer"] == "return=representation"


def test_a_slot_that_is_gone_or_already_filled_is_false():
    client, _ = recording_client([httpx.Response(200, json=[])])
    assert client.fill_followup_slot(7, 1, "질문?") is False


@pytest.mark.parametrize("response", [httpx.Response(401, json={"message": "secret-detail"}), httpx.Response(403), httpx.Response(400)])
def test_fill_rejections_are_configuration_errors(response):
    client, _ = recording_client([response])
    with pytest.raises(SupabaseConfigError) as raised:
        client.fill_followup_slot(7, 1, "질문?")
    assert "secret-detail" not in str(raised.value)


# --- release_followup_slot ---


@pytest.mark.parametrize("status", [200, 204])
def test_releasing_deletes_only_a_slot_with_no_question_and_no_answer(status):
    client, seen = recording_client([httpx.Response(status)])
    client.release_followup_slot(7, 2)
    request = seen[0]
    assert request.method == "DELETE" and request.url.path == "/rest/v1/quiz_followups"
    assert dict(request.url.params) == {"item_id": "eq.7", "seq": "eq.2", "question": "is.null", "user_answer": "is.null"}


def test_a_release_rejection_is_a_configuration_error():
    client, _ = recording_client([httpx.Response(401)])
    with pytest.raises(SupabaseConfigError):
        client.release_followup_slot(7, 2)


# --- delete_stale_followup_slot ---


def test_stale_cleanup_deletes_only_an_empty_slot_reserved_before_the_cutoff():
    client, seen = recording_client([httpx.Response(200, json=[{"seq": 1}])])
    assert client.delete_stale_followup_slot(7, 1, "2026-11-03T00:25:00Z") is True
    request = seen[0]
    assert request.method == "DELETE"
    assert dict(request.url.params) == {
        "item_id": "eq.7", "seq": "eq.1", "question": "is.null", "user_answer": "is.null",
        "created_at": "lt.2026-11-03T00:25:00Z", "select": "seq",
    }
    assert request.headers["prefer"] == "return=representation"


def test_stale_cleanup_that_matches_nothing_is_false():
    client, _ = recording_client([httpx.Response(200, json=[])])
    assert client.delete_stale_followup_slot(7, 1, "2026-11-03T00:25:00Z") is False


def test_a_stale_cleanup_rejection_is_a_configuration_error():
    client, _ = recording_client([httpx.Response(403)])
    with pytest.raises(SupabaseConfigError):
        client.delete_stale_followup_slot(7, 1, "2026-11-03T00:25:00Z")
