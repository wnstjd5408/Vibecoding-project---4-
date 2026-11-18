"""CS Agent 대화·턴(MEG-234) Supabase 래퍼의 HTTP 모양. 요청 주소·필터·헤더·본문과 오류 판정을 고정한다. 네트워크 없이 돈다.

남의 행을 읽지 못하게 하는 user_id 필터와, 끝난 턴을 건드리지 않는 조건부 갱신 필터가 빠지지 않는지를 특히 본다.
"""

import json

import httpx
import pytest

from app.supabase import SupabaseClient, SupabaseConfigError, SupabaseUnavailable

USER_ID = "00000000-0000-4000-8000-00000000000a"
CONVERSATION = "11111111-1111-4111-8111-111111111111"
TURN = "22222222-2222-4222-8222-222222222222"


def recording_client(responses):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[len(seen) - 1]

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseClient("https://project.supabase.co/", "sb_secret_test", http), seen


def test_creating_a_conversation_posts_the_row_and_returns_it():
    row = {"id": CONVERSATION, "user_id": USER_ID, "origin": "none"}
    client, seen = recording_client([httpx.Response(201, json=[row])])
    assert client.create_agent_conversation({"user_id": USER_ID, "origin": "none", "topic_label": ""}) == row
    request = seen[0]
    assert request.method == "POST" and request.url.path == "/rest/v1/ai_conversations"
    assert request.headers["Prefer"] == "return=representation"
    assert json.loads(request.content) == {"user_id": USER_ID, "origin": "none", "topic_label": ""}
    assert "user_id" in dict(request.url.params)["select"]


def test_adding_a_selection_posts_the_snapshot():
    client, seen = recording_client([httpx.Response(201, json=[{"id": "s"}])])
    fields = {"conversation_id": CONVERSATION, "note_id": 1, "note_revision": 3, "start": 0, "end": 3,
              "text_snapshot": "abc"}
    assert client.add_agent_selection(fields) == {"id": "s"}
    assert seen[0].url.path == "/rest/v1/ai_conversation_selections"
    assert json.loads(seen[0].content) == fields
    assert '"end"' in dict(seen[0].url.params)["select"]


def test_a_note_deleted_before_the_insert_is_none():
    body = {"code": "23503", "message": "violates foreign key constraint"}
    client, _ = recording_client([httpx.Response(409, json=body)])
    assert client.create_agent_conversation({"note_id": 1}) is None


@pytest.mark.parametrize("method", ["create_agent_conversation", "add_agent_selection"])
def test_a_rejected_insert_is_a_config_error(method):
    client, _ = recording_client([httpx.Response(400, json={"code": "23514"})])
    with pytest.raises(SupabaseConfigError):
        getattr(client, method)({})


def test_deleting_a_conversation_filters_by_owner():
    client, seen = recording_client([httpx.Response(204)])
    client.delete_agent_conversation(USER_ID, CONVERSATION)
    params = dict(seen[0].url.params)
    assert seen[0].method == "DELETE" and seen[0].url.path == "/rest/v1/ai_conversations"
    assert params == {"id": f"eq.{CONVERSATION}", "user_id": f"eq.{USER_ID}"}


def test_reading_a_conversation_filters_by_owner_and_embeds_selections_in_order():
    row = {"id": CONVERSATION, "ai_conversation_selections": []}
    client, seen = recording_client([httpx.Response(200, json=[row])])
    assert client.get_agent_conversation(USER_ID, CONVERSATION) == row
    params = dict(seen[0].url.params)
    assert seen[0].method == "GET" and seen[0].url.path == "/rest/v1/ai_conversations"
    assert params["id"] == f"eq.{CONVERSATION}" and params["user_id"] == f"eq.{USER_ID}"
    assert "ai_conversation_selections(" in params["select"] and "excluded_at" in params["select"]
    assert params["ai_conversation_selections.order"] == "created_at.asc,id.asc" and params["limit"] == "1"


def test_another_users_conversation_or_turn_is_none():
    client, _ = recording_client([httpx.Response(200, json=[]), httpx.Response(200, json=[])])
    assert client.get_agent_conversation(USER_ID, CONVERSATION) is None
    assert client.get_agent_turn(USER_ID, TURN) is None


def test_ids_that_are_not_uuids_are_refused_before_any_request():
    client, seen = recording_client([])
    with pytest.raises(ValueError):
        client.get_agent_turn(USER_ID, "1 or 1=1")
    assert seen == []


def test_reading_a_turn_filters_by_owner():
    client, seen = recording_client([httpx.Response(200, json=[{"id": TURN}])])
    assert client.get_agent_turn(USER_ID, TURN) == {"id": TURN}
    params = dict(seen[0].url.params)
    assert seen[0].url.path == "/rest/v1/ai_turns"
    assert params["id"] == f"eq.{TURN}" and params["user_id"] == f"eq.{USER_ID}"
    assert "question_text" in params["select"] and "ledger_id" not in params["select"]


def test_listing_turns_reads_sources_without_internal_columns():
    client, seen = recording_client([httpx.Response(200, json=[]), httpx.Response(200, json=[])])
    client.list_agent_turns(USER_ID, CONVERSATION)
    client.list_agent_turns(USER_ID, CONVERSATION, max_seq=4)
    first, second = (dict(r.url.params) for r in seen)
    assert first["conversation_id"] == f"eq.{CONVERSATION}" and first["user_id"] == f"eq.{USER_ID}"
    assert first["order"] == "seq.asc" and first["ai_turn_sources.order"] == "ref.asc"
    assert "seq" not in first and second["seq"] == "lte.4"
    select = first["select"]
    assert "ai_turn_sources(ref,source_kind,source_id,cited_revision,title,section,excerpt)" in select
    for internal in ("ledger_id", "model_id", "prompt_version", "retrieval_version", "paragraph_snapshot",
                     "idempotency_key", "reply"):
        assert internal not in select


def test_expiring_turns_is_a_conditional_update_on_running_and_lapsed_leases():
    client, seen = recording_client([httpx.Response(200, json=[{"id": TURN}])])
    cutoff, now = "2026-11-18T05:59:55.500000Z", "2026-11-18T06:00:00.500000Z"
    assert client.expire_agent_turns(USER_ID, CONVERSATION, cutoff, now) == 1
    request = seen[0]
    params = dict(request.url.params)
    assert request.method == "PATCH" and request.url.path == "/rest/v1/ai_turns"
    assert params["status"] == "eq.running" and params["lease_expires_at"] == f"lte.{cutoff}"
    assert params["conversation_id"] == f"eq.{CONVERSATION}" and params["user_id"] == f"eq.{USER_ID}"
    assert json.loads(request.content) == {"status": "failed", "failure": "interrupted", "finished_at": now}
    assert request.headers["Prefer"] == "return=representation"


def test_cancelling_calls_the_conditional_finish_function():
    client, seen = recording_client([httpx.Response(200, json=True), httpx.Response(200, json=False)])
    assert client.cancel_agent_turn(USER_ID, TURN) is True
    assert client.cancel_agent_turn(USER_ID, TURN) is False
    assert seen[0].url.path == "/rest/v1/rpc/agent_finish_turn"
    assert json.loads(seen[0].content) == {"p_user_id": USER_ID, "p_turn_id": TURN, "p_status": "cancelled"}


def test_note_states_are_read_in_one_query_including_unpublished_notes():
    rows = [{"id": 1, "revision": 2, "title": "t", "is_published": False}]
    client, seen = recording_client([httpx.Response(200, json=rows)])
    assert client.get_note_states([3, 1, 1]) == {1: rows[0]}
    params = dict(seen[0].url.params)
    assert params == {"id": "in.(1,3)", "select": "id,revision,title,is_published"}


def test_no_note_ids_means_no_request():
    client, seen = recording_client([])
    assert client.get_note_states([]) == {}
    assert seen == []


def test_reading_a_note_for_a_conversation_hides_unpublished_notes_from_members():
    client, seen = recording_client([httpx.Response(200, json=[]), httpx.Response(200, json=[{"id": 1}])])
    assert client.get_note_for_agent(1, include_unpublished=False) is None
    assert client.get_note_for_agent(1, include_unpublished=True) == {"id": 1}
    member, operator = (dict(r.url.params) for r in seen)
    assert member["is_published"] == "eq.true" and "is_published" not in operator
    assert "title" in member["select"] and "body_markdown" in member["select"]


def test_a_down_database_is_unavailable():
    client, _ = recording_client([httpx.Response(503)])
    with pytest.raises(SupabaseUnavailable):
        client.list_agent_turns(USER_ID, CONVERSATION)
