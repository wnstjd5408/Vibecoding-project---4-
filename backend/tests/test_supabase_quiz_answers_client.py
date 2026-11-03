"""퀴즈 답 저장(MEG-92) Supabase 래퍼의 HTTP 모양. 실제 요청 주소·필터·헤더·본문과 오류 판정을 고정한다. 네트워크 없이 돈다.

같은 호출은 실제 로컬 Supabase에서도 확인한다(docs/backend-local-guide.md). 여기서는 그 모양이 바뀌지 않게 지킨다.
"""

import json

import httpx
import pytest

from app.supabase import SupabaseClient, SupabaseConfigError, SupabaseUnavailable

USER_ID = "00000000-0000-4000-8000-00000000000a"
ITEM_FK = {
    "code": "23503",
    "message": 'insert or update on table "quiz_answers" violates foreign key constraint "quiz_answers_item_id_fkey"',
}


def recording_client(responses):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[len(seen) - 1]

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseClient("https://project.supabase.co/", "sb_secret_test", http), seen


# --- get_quiz_item_for_answer ---


def test_the_item_is_read_through_an_inner_join_on_the_users_own_set():
    row = {"id": 7, "difficulty": "중", "answer": "정답", "explanation": "해설", "quiz_answers": None, "quiz_followups": []}
    client, seen = recording_client([httpx.Response(200, json=[row])])
    assert client.get_quiz_item_for_answer(USER_ID, 7) == row
    request = seen[0]
    assert request.method == "GET" and request.url.path == "/rest/v1/quiz_items"
    params = dict(request.url.params)
    assert params["id"] == "eq.7"
    assert params["quiz_sets.user_id"] == f"eq.{USER_ID}"
    assert "quiz_sets!inner(user_id)" in params["select"]
    assert "quiz_answers(user_answer)" in params["select"]
    assert "quiz_followups(seq,question,user_answer)" in params["select"]
    assert params["quiz_followups.order"] == "seq.asc"
    assert params["limit"] == "1"


def test_another_users_or_missing_item_is_none():
    client, _ = recording_client([httpx.Response(200, json=[])])
    assert client.get_quiz_item_for_answer(USER_ID, 7) is None


def test_the_item_read_rejects_a_malformed_user_id_before_any_request():
    client, seen = recording_client([])
    with pytest.raises(ValueError):
        client.get_quiz_item_for_answer("not-a-uuid", 7)
    assert seen == []


# --- save_quiz_answer ---


def test_saving_an_answer_inserts_ignoring_a_duplicate_primary_key_and_returns_the_row():
    client, seen = recording_client([httpx.Response(201, json=[{"user_answer": "내 답"}])])
    assert client.save_quiz_answer(7, "내 답") == "내 답"
    request = seen[0]
    assert request.method == "POST" and request.url.path == "/rest/v1/quiz_answers"
    assert request.headers["prefer"] == "resolution=ignore-duplicates,return=representation"
    assert dict(request.url.params) == {"select": "user_answer"}
    assert json.loads(request.content) == {"item_id": 7, "user_answer": "내 답"}
    assert len(seen) == 1


def test_a_duplicate_is_ignored_and_the_stored_answer_is_read_back():
    client, seen = recording_client([httpx.Response(201, json=[]), httpx.Response(200, json=[{"user_answer": "먼저 낸 답"}])])
    assert client.save_quiz_answer(7, "내 답") == "먼저 낸 답"
    read = seen[1]
    assert read.method == "GET" and read.url.path == "/rest/v1/quiz_answers"
    assert dict(read.url.params) == {"item_id": "eq.7", "select": "user_answer", "limit": "1"}


def test_an_ignored_duplicate_whose_row_vanished_is_none():
    client, _ = recording_client([httpx.Response(201, json=[]), httpx.Response(200, json=[])])
    assert client.save_quiz_answer(7, "내 답") is None


def test_a_missing_item_foreign_key_is_none():
    client, seen = recording_client([httpx.Response(409, json=ITEM_FK)])
    assert client.save_quiz_answer(7, "내 답") is None
    assert len(seen) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(409, json={"code": "23503", "message": "other foreign key"}),
        httpx.Response(409, json={"code": "23505", "message": "duplicate key"}),
        httpx.Response(409, json={"code": "23514", "message": "quiz_answers_user_answer_length_check"}),
        httpx.Response(401, json={"message": "secret-detail"}),
        httpx.Response(403),
        httpx.Response(400, json={"message": "bad"}),
    ],
)
def test_other_save_rejections_are_configuration_errors_without_the_server_message(response):
    client, _ = recording_client([response])
    with pytest.raises(SupabaseConfigError) as raised:
        client.save_quiz_answer(7, "내 답")
    assert "secret-detail" not in str(raised.value)


def test_a_server_outage_while_saving_is_unavailable():
    client, _ = recording_client([httpx.Response(503)])
    with pytest.raises(SupabaseUnavailable):
        client.save_quiz_answer(7, "내 답")


# --- save_followup_answer ---


def test_a_followup_answer_updates_only_an_unanswered_slot_with_a_question():
    client, seen = recording_client([httpx.Response(200, json=[{"user_answer": "꼬리 답"}])])
    assert client.save_followup_answer(7, 1, "꼬리 답") == "꼬리 답"
    request = seen[0]
    assert request.method == "PATCH" and request.url.path == "/rest/v1/quiz_followups"
    params = dict(request.url.params)
    assert params == {
        "item_id": "eq.7", "seq": "eq.1", "question": "not.is.null", "user_answer": "is.null", "select": "user_answer",
    }
    assert request.headers["prefer"] == "return=representation"
    assert json.loads(request.content) == {"user_answer": "꼬리 답"}


def test_an_already_answered_slot_returns_the_stored_answer_without_overwriting():
    client, seen = recording_client(
        [httpx.Response(200, json=[]), httpx.Response(200, json=[{"question": "q", "user_answer": "먼저 낸 답"}])]
    )
    assert client.save_followup_answer(7, 1, "내 답") == "먼저 낸 답"
    assert [r.method for r in seen] == ["PATCH", "GET"]
    assert dict(seen[1].url.params) == {"item_id": "eq.7", "seq": "eq.1", "select": "question,user_answer", "limit": "1"}


@pytest.mark.parametrize("rows", [[], [{"question": None, "user_answer": None}], [{"question": "", "user_answer": None}]])
def test_a_missing_slot_or_one_without_a_question_is_none(rows):
    client, _ = recording_client([httpx.Response(200, json=[]), httpx.Response(200, json=rows)])
    assert client.save_followup_answer(7, 1, "내 답") is None


def test_an_unanswered_slot_that_the_update_missed_is_retryable_unavailable():
    client, _ = recording_client(
        [httpx.Response(200, json=[]), httpx.Response(200, json=[{"question": "q", "user_answer": None}])]
    )
    with pytest.raises(SupabaseUnavailable):
        client.save_followup_answer(7, 1, "내 답")


@pytest.mark.parametrize("response", [httpx.Response(401, json={"message": "secret-detail"}), httpx.Response(403), httpx.Response(409)])
def test_followup_update_rejections_are_configuration_errors(response):
    client, _ = recording_client([response])
    with pytest.raises(SupabaseConfigError) as raised:
        client.save_followup_answer(7, 1, "내 답")
    assert "secret-detail" not in str(raised.value)
