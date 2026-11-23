"""CS Agent 위키 출처·권한과 위키 플래그 (MEG-252 AC-1~AC-6, 내부 위키 우선 RAG 설계 v0.3 4.1·7절 S1·S3~S6·S9~S11).

검색은 앱 기본값(get_retriever)을 그대로 쓴다. 플래그가 꺼져 있으면 노트 검색, 켜져 있으면 위키 검색이다. Supabase·원장·
Bedrock은 가짜라 네트워크 없이 돈다. 데이터는 모두 합성이다. 모델은 부르지 않는다(가짜 Bedrock이 정해 둔 답을 준다).

가짜 사전은 실제 래퍼와 같은 판정을 쓴다: 항목이 있다 = glossary_entries 행이 있고 terms.source = 'glossary'. 사전 삭제(E21)는
terms 행을 남기고 source를 ai로 바꾼다. 사전 저장(E20)은 개정 번호를 1 올린다(재등록 포함). 실제 SQL의 개정 번호 규칙은
tests/integration/test_glossary_admin_sql.py(T4a MEG-249)가 확인한다.
"""

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import agent, agent_sources, agent_turns
from app.agent_access import ConversationAccess, check_conversation, source_checker
from app.agent_note_search import NoteRetriever, note_chunks
from app.agent_retrieval import WIKI_ENV, get_retriever, wiki_enabled
from app.agent_wiki_search import WikiRetriever
from app.ai_explain import AiRuntime, get_ai_runtime
from app.auth import SessionUser
from app.common import install_common_layer
from app.errors import ApiError
from app.rate_limit import WRITE
from app.supabase import get_supabase
from support import cookie, origin
from test_agent import A, B, OP, PRIVATE, PUBLIC, SOURCE_NOTE, assert_error, assert_field, iso
from test_agent_sources import CONVERSATION_BODY, PRIVATE_BODY, SOURCE_BODY, SourceFake, prompt_evidence
from test_agent_turns import BUDGET, SETTINGS, AgentBedrock, AgentStore, answer_json, ask, bedrock_reply, events

IDEMPOTENCY, RETRY = 7, 8
IDEMPOTENCY_BODY = (
    "# 정의\n멱등성은 같은 요청을 여러 번 보내도 결과가 한 번 보낸 것과 같은 성질이다.\n\n"
    "# 예시\nHTTP PUT은 멱등성이 있는 메서드다."
)
IDEMPOTENCY_DEFINITION = "멱등성은 같은 요청을 여러 번 보내도 결과가 한 번 보낸 것과 같은 성질이다."
RETRY_BODY = "# 정의\n재시도는 실패한 요청을 다시 보내는 일이다. 멱등성이 있는 요청에만 안전하다."
# 운영자의 비공개 노트에만 있는 글(카나리). 선택 문장에 넣는다. 검색 후보·출처·로그 어디에도 나오면 안 된다(S6).
CANARY = "비공개카나리문장"


class WikiFake(SourceFake):
    """SourceFake에 사전(terms + glossary_entries)과 위키 래퍼를 더한다."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.terms: dict[int, dict] = {}
        self.entries: dict[int, str] = {}

    # --- 시험 준비 (E20·E21 흉내) ---

    def save_entry(self, term_id, label, body):
        """E20: 처음 등록하면 개정 1, 이후 저장(재등록 포함)마다 1씩 오른다(T4a)."""
        row = self.terms.get(term_id)
        if row is None:
            self.terms[term_id] = {"id": term_id, "key": label.lower(), "label": label, "source": "glossary",
                                   "glossary_revision": 1}
        else:
            row.update(label=label, source="glossary", glossary_revision=row["glossary_revision"] + 1)
        self.entries[term_id] = body

    def delete_entry(self, term_id):
        """E21: glossary_entries 행을 지우고 terms 행은 남긴 채 source를 ai로 바꾼다."""
        self.entries.pop(term_id)
        self.terms[term_id]["source"] = "ai"

    def wiki_conversation(self, user, term_id):
        """플래그가 켜져 있던 동안 만든 위키 대화 행(DB 제약: note 필드 없음, wiki_ref 있음)."""
        cid = str(uuid.uuid4())
        self.conversations[cid] = {
            "id": cid, "user_id": user, "origin": "wiki", "note_id": None, "note_revision": None,
            "wiki_ref": f"glossary:{term_id}", "topic_label": self.terms[term_id]["label"], "created_at": iso(-600),
        }
        return cid

    def _current(self, term_id):
        row = self.terms.get(term_id)
        return row is not None and row["source"] == "glossary" and term_id in self.entries

    # --- 래퍼 흉내 ---

    def list_wiki_entries(self):
        self._db("list_wiki_entries")
        return [{**dict(row), "glossary_entries": {"body_markdown": self.entries[term_id]}}
                for term_id, row in sorted(self.terms.items()) if self._current(term_id)]

    def get_wiki_entry_states(self, term_ids):
        self._db("get_wiki_entry_states")
        return {term_id: {"id": term_id, "label": self.terms[term_id]["label"]}
                for term_id in term_ids if self._current(term_id)}

    def get_wiki_entry(self, term_id):
        self._db("get_wiki_entry")
        if not self._current(term_id):
            return None
        return {"id": term_id, "label": self.terms[term_id]["label"],
                "glossary_entries": {"body_markdown": self.entries[term_id]}}


@pytest.fixture
def fake(monkeypatch):
    from app import session
    from test_agent import NOW

    monkeypatch.delenv(agent.DISABLE_ENV, raising=False)
    for name in ("VERCEL", "VERCEL_ENV", "VERCEL_TARGET_ENV", "VERCEL_GIT_COMMIT_REF"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(session, "now", lambda: NOW + 0.5)
    fake = WikiFake(now=NOW + 0.5)
    fake.add_user("a-token", A)
    fake.add_user("b-token", B)
    fake.add_user("op-token", OP, role="operator")
    fake.note(PUBLIC, title="대화 노트", body=CONVERSATION_BODY)
    fake.note(PRIVATE, published=False, title="비공개 노트", body=PRIVATE_BODY + f"\n{CANARY}")
    fake.note(SOURCE_NOTE, title="출처 노트", body=SOURCE_BODY)
    fake.save_entry(IDEMPOTENCY, "멱등성", IDEMPOTENCY_BODY)
    fake.save_entry(RETRY, "재시도", RETRY_BODY)
    return fake


@pytest.fixture
def wiki_on(monkeypatch):
    monkeypatch.setenv(WIKI_ENV, "1")


@pytest.fixture
def bedrock():
    return AgentBedrock()


@pytest.fixture
def client(fake, bedrock):
    app = FastAPI()
    install_common_layer(app)
    runtime = AiRuntime(
        store=AgentStore(),
        load_budget=lambda: BUDGET,
        load_settings=lambda: SETTINGS,
        client_factory=lambda settings, token=None: bedrock,
        sleep=lambda seconds: None,
    )
    app.dependency_overrides[get_supabase] = lambda: fake
    app.dependency_overrides[get_ai_runtime] = lambda: runtime
    # get_retriever는 덮어쓰지 않는다. 플래그에 따른 앱 기본값을 시험한다.
    app.include_router(agent.router)
    app.include_router(agent_turns.router)
    app.include_router(agent_sources.router)
    return TestClient(app)


def get(client, path, token="a-token"):
    return client.get(path, headers=cookie(token))


def create(client, body, token="a-token"):
    return client.post("/api/ai/conversations", json=body, headers={**origin(), **cookie(token)})


def wiki_body(term_id=IDEMPOTENCY, **overrides):
    return {"origin": "wiki", "wiki_ref": f"glossary:{term_id}", **overrides}


def source_path(turn_id, ref=1):
    return f"/api/ai/turns/{turn_id}/sources/{ref}"


def asked(client, cid, token="a-token", question="멱등성이 뭐야?", body=None):
    parsed = events(ask(client, cid, body=body or {"question": {"kind": "free", "text": question}}, token=token))
    result = parsed[-1][1]
    assert parsed[-1][0] == "result" and result["status"] == "completed", parsed[-1]
    return result, parsed


def cited_terms(fake):
    return [source["source_id"] for source in fake.finishes[-1]["p_sources"] or []]


# --- 플래그 값 ---


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_the_wiki_flag_turns_on_only_with_an_on_value(monkeypatch, value):
    monkeypatch.setenv(WIKI_ENV, value)
    assert wiki_enabled()


@pytest.mark.parametrize("value", ["", "0", "false", "off", "no", "enabled", "2", "ture"])
def test_empty_off_or_misspelled_values_leave_the_wiki_flag_off(monkeypatch, value):
    # 꺼진 쪽이 지금 동작이다. 잘못 쓴 값이 위키 경로를 열지 않는다.
    monkeypatch.setenv(WIKI_ENV, value)
    assert not wiki_enabled()


def test_the_wiki_flag_is_off_by_default():
    assert not wiki_enabled()


# --- AC-1: 플래그가 꺼져 있으면 지금 동작 그대로 ---


def test_flag_off_e27_rejects_origin_wiki_before_any_db_read(client, fake):
    fake.calls.clear()
    assert_field(create(client, wiki_body()), "origin", "invalid_value")
    assert fake.calls == []


def test_flag_off_the_app_retriever_is_the_note_search(fake):
    assert isinstance(get_retriever(fake), NoteRetriever)


def test_flag_off_e29_answers_from_notes(client, fake):
    cid = fake.conversation(A)
    result, parsed = asked(client, cid)
    assert fake.finishes[-1]["p_retrieval_version"] == "note-keyword-v1"
    assert {s["source_kind"] for s in result["result"]["sources"]} == {"note"}
    assert "list_wiki_entries" not in fake.calls


def test_flag_off_a_wiki_conversation_made_while_it_was_on_is_closed(client, fake, bedrock):
    # 꺼진 동안 위키 대화에 질문하면 노트로 답하게 된다(설계 독립 리뷰 R1). 대화 전체를 404로 닫는다.
    cid = fake.wiki_conversation(A, IDEMPOTENCY)
    tid = fake.turn(cid, 1, sources=[("wiki", f"glossary:{IDEMPOTENCY}")])
    assert_error(get(client, f"/api/ai/conversations/{cid}"), 404, "not_found")
    assert_error(get(client, f"/api/ai/turns/{tid}"), 404, "not_found")
    assert_error(get(client, source_path(tid)), 404, "not_found")
    assert_error(ask(client, cid), 404, "not_found")
    assert bedrock.calls == 0 and "list_published_note_bodies" not in fake.calls
    # 사전을 읽지 않는다(꺼져 있으면 판정할 필요가 없다).
    assert "get_wiki_entry_states" not in fake.calls


# --- E27 origin wiki (플래그 켜짐) ---


def test_e27_opens_a_wiki_conversation_titled_by_the_entry(client, fake, wiki_on):
    response = create(client, wiki_body())
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["origin"] == "wiki" and data["wiki_ref"] == f"glossary:{IDEMPOTENCY}"
    assert data["topic_label"] == "멱등성" and data["context_selections"] == [] and "note" not in data
    row = fake.conversations[data["conversation_id"]]
    assert (row["origin"], row["note_id"], row["note_revision"], row["wiki_ref"]) == (
        "wiki", None, None, f"glossary:{IDEMPOTENCY}")
    # E28도 같은 모양이다.
    read = get(client, f"/api/ai/conversations/{data['conversation_id']}").json()
    assert read == {**data, "turns": []}


@pytest.mark.parametrize("ref", [
    "7", "glossary:", "glossary:07", "glossary:-1", "glossary:+7", "glossary: 7", "glossary:7 ", "GLOSSARY:7",
    "note:7", "glossary:7#정의", "glossary:9223372036854775808", "glossary:０", "",
])
def test_e27_rejects_a_malformed_wiki_ref_with_422(client, fake, wiki_on, ref):
    fake.calls.clear()
    assert_field(create(client, wiki_body(wiki_ref=ref)), "wiki_ref", "invalid_value")
    assert fake.calls == []


@pytest.mark.parametrize("body,name,reason", [
    ({"origin": "wiki"}, "wiki_ref", "required"),
    ({"origin": "wiki", "wiki_ref": None}, "wiki_ref", "required"),
    (wiki_body(note_id=PUBLIC), "note_id", "invalid_value"),
    (wiki_body(note_revision=3), "note_revision", "invalid_value"),
    (wiki_body(selection={"start": 0, "end": 3}), "selection", "invalid_value"),
    ({"origin": "none", "wiki_ref": "glossary:7"}, "wiki_ref", "invalid_value"),
    ({"origin": "note", "note_id": PUBLIC, "note_revision": 3, "selection": {"start": 0, "end": 3},
      "wiki_ref": "glossary:7"}, "wiki_ref", "invalid_value"),
])
def test_e27_rejects_field_combinations_that_do_not_match_origin_wiki(client, fake, wiki_on, body, name, reason):
    assert_field(create(client, body), name, reason)


def test_e27_rejects_a_non_string_wiki_ref(client, wiki_on):
    response = create(client, {"origin": "wiki", "wiki_ref": 7})
    assert_error(response, 422, "validation_failed")


@pytest.mark.parametrize("prepare", ["missing", "deleted", "ai_only"])
def test_e27_is_404_when_the_entry_does_not_exist_now(client, fake, wiki_on, prepare):
    term_id = 99
    if prepare == "deleted":
        fake.save_entry(term_id, "지운 항목", "# 정의\n지운 본문이다.")
        fake.delete_entry(term_id)
    elif prepare == "ai_only":
        # AI로만 설명된 용어(terms.source = 'ai', glossary_entries 없음)는 위키가 아니다(설계 3.2).
        fake.terms[term_id] = {"id": term_id, "key": "ai", "label": "AI 용어", "source": "ai", "glossary_revision": 0}
    count = len(fake.conversations)
    assert_error(create(client, wiki_body(term_id)), 404, "not_found")
    assert len(fake.conversations) == count


def test_e27_wiki_is_the_same_for_members_and_operators(client, fake, wiki_on):
    # 사전은 모두 공개다(W5). 역할에 따라 다르지 않다.
    assert create(client, wiki_body(), token="op-token").status_code == 201
    assert create(client, wiki_body(), token="b-token").status_code == 201


def test_e27_wiki_is_rate_limited_before_the_entry_is_read(client, fake, wiki_on):
    for _ in range(WRITE.limit):
        create(client, wiki_body())
    fake.calls.clear()
    assert_error(create(client, wiki_body(99)), 429, "rate_limited")
    assert fake.calls == []


def test_e27_wiki_still_obeys_the_exposure_kill_switch(client, fake, wiki_on, monkeypatch):
    monkeypatch.setenv(agent.DISABLE_ENV, "1")
    assert_error(create(client, wiki_body()), 503, "service_unavailable")


def test_another_users_wiki_conversation_is_404(client, fake, wiki_on):
    cid = create(client, wiki_body()).json()["conversation_id"]
    assert_error(get(client, f"/api/ai/conversations/{cid}", token="b-token"), 404, "not_found")
    assert_error(ask(client, cid, token="b-token"), 404, "not_found")


def test_a_wiki_conversation_does_not_take_note_selections(client, fake, wiki_on):
    # 위키 문단 선택은 v1 미지원이고(W7) 노트 선택도 위키 대화에 붙이지 않는다(같은 노트만, Q17).
    cid = create(client, wiki_body()).json()["conversation_id"]
    body = {"question": {"kind": "free", "text": "멱등성이 뭐야?"},
            "add_selections": [{"note_id": PUBLIC, "note_revision": 3, "start": 0, "end": 3}]}
    assert_field(ask(client, cid, body=body), "add_selections.note_id", "invalid_value")


# --- AC-2: 플래그가 켜져 있으면 E29 답의 출처가 모두 위키 ---


def test_flag_on_the_app_retriever_is_the_wiki_search(fake, wiki_on):
    assert isinstance(get_retriever(fake), WikiRetriever)


@pytest.mark.parametrize("origin_kind", ["wiki", "note", "none"])
def test_flag_on_every_cited_source_is_a_wiki_paragraph(client, fake, bedrock, wiki_on, origin_kind):
    if origin_kind == "wiki":
        cid = create(client, wiki_body()).json()["conversation_id"]
    elif origin_kind == "note":
        cid = fake.conversation(A)
    else:
        cid = fake.conversation(A, note_id=None)
    # 답이 근거 문단 둘을 모두 인용하게 한다.
    bedrock.replies = [bedrock_reply(answer_json(sections=[{"heading": "핵심", "body": "설명 [1] 그리고 [2]."}]))]
    result, parsed = asked(client, cid)
    sources = result["result"]["sources"]
    assert sources and {s["source_kind"] for s in sources} == {"wiki"}
    finish = fake.finishes[-1]
    assert finish["p_retrieval_version"] == "wiki-keyword-v1"
    assert all(s["source_id"].startswith("glossary:") for s in finish["p_sources"])
    assert {s["cited_revision"] for s in finish["p_sources"]} == {"1"}
    steps = [data for name, data in parsed if name == "step"]
    assert any(s.get("step") == "retrieve" and s.get("state") == "done" and s.get("source_kind") == "wiki"
               for s in steps)
    # 노트는 질문 문맥으로만 쓴다(W2). 노트 본문을 검색하지 않고, 근거 구역에 노트 문단이 없다.
    assert "list_published_note_bodies" not in fake.calls
    evidence = prompt_evidence(bedrock.prompts[-1])
    assert "재시도는 멱등성이 있는 요청에만 안전하다." not in evidence  # 출처 노트(SOURCE_BODY)의 문단
    assert "선택 문장이 들어 있는 문단" not in evidence  # 대화 노트(CONVERSATION_BODY)의 문단


def test_a_wiki_conversation_passes_its_entry_to_the_search(client, fake, bedrock, wiki_on, monkeypatch):
    # E29가 대화의 wiki_ref를 검색 문맥(RetrievalContext.wiki_ref)으로 넘긴다. 위키 검색은 그 항목 문단에 가산점을 준다.
    from app import agent_wiki_search

    seen = []
    original = agent_wiki_search.search_entries

    def spy(entries, question, context):
        seen.append(context.wiki_ref)
        return original(entries, question, context)

    monkeypatch.setattr(agent_wiki_search, "search_entries", spy)
    cid = create(client, wiki_body(RETRY)).json()["conversation_id"]
    asked(client, cid, body={"question": {"kind": "preset", "preset": "simple"}})
    assert seen == [f"glossary:{RETRY}"]
    assert cited_terms(fake) == [f"glossary:{RETRY}"]
    # 노트에서 연 대화는 wiki_ref가 없다.
    asked(client, fake.conversation(A))
    assert seen[-1] is None


def test_wiki_evidence_allows_a_correction(client, fake, bedrock, wiki_on):
    # 근거에 위키가 있으면 correction을 허용한다(지금 correction_allowed 동작, 설계 3.5).
    cid = fake.conversation(A)
    correction = json.dumps({
        "state": "correction",
        "sections": [{"body": "설명 [1]"}],
        "corrections": [{"note_excerpt": "멱등성", "corrected": "고친 내용 [1]", "source_refs": [1]}],
    }, ensure_ascii=False)
    bedrock.replies = [bedrock_reply(correction)]
    result, _ = asked(client, cid)
    assert "state를 correction으로 하지 않습니다" not in bedrock.prompts[-1]
    assert result["result"]["state"] == "correction" and result["result"]["corrections"]


def test_a_question_with_no_matching_entry_is_no_evidence_without_a_model_call(client, fake, bedrock, wiki_on):
    cid = fake.conversation(A)
    result, parsed = asked(client, cid, question="쿠버네티스 파드 스케줄링")
    assert result["result"]["state"] == "no_evidence" and bedrock.calls == 0
    assert {"step": "retrieve", "state": "done", "paragraph_count": 0, "source_kind": "wiki"} in [
        data for name, data in parsed if name == "step"
    ]


def test_an_entry_deleted_between_search_and_citing_fails_the_turn(client, fake, bedrock, wiki_on):
    # 인용 직전 확인(E29 9단계): 검색 뒤 항목이 지워지면 저장하지 않고 failed다.
    cid = fake.conversation(A)
    bedrock.during_call = lambda: fake.delete_entry(IDEMPOTENCY)
    parsed = events(ask(client, cid))
    assert parsed[-1][1]["error"]["code"] == "internal_error"
    assert fake.sources == []


# --- AC-3: 위키 항목을 지우면 그 턴부터 hidden, E32 404 ---


def test_deleting_a_cited_entry_hides_that_turn_and_later_turns_and_closes_e32(client, fake, wiki_on):
    # 노트에서 연 대화가 위키 항목을 인용한다. 대화 자체는 노트 문맥이라 열린 채 턴만 가린다.
    cid = fake.conversation(A)
    first, _ = asked(client, cid, question="쿠버네티스")
    assert first["result"]["state"] == "no_evidence"
    second, _ = asked(client, cid)
    cited = cited_terms(fake)
    third, _ = asked(client, cid, question="재시도는 언제 안전해?")
    assert get(client, source_path(second["turn_id"])).status_code == 200

    fake.delete_entry(int(cited[0].split(":")[1]))

    turns = get(client, f"/api/ai/conversations/{cid}").json()["turns"]
    assert "hidden" not in turns[0]
    assert turns[1]["hidden"] == {"reason": "source_revoked", "retry_allowed": True} and "result" not in turns[1]
    assert turns[2]["hidden"] == {"reason": "source_revoked", "retry_allowed": False} and "result" not in turns[2]
    for turn in turns:
        assert get(client, f"/api/ai/turns/{turn['turn_id']}").json() == turn
    assert_error(get(client, source_path(second["turn_id"])), 404, "not_found")
    assert_error(get(client, source_path(third["turn_id"])), 404, "not_found")


def test_deleting_the_entry_a_wiki_conversation_was_opened_from_closes_the_conversation(client, fake, wiki_on):
    # 공통 권한 검사: 대화에 연결된 위키를 지금 읽을 수 없으면 404다(spec 8절). 없음·회수를 구분하지 않는다.
    cid = create(client, wiki_body(RETRY)).json()["conversation_id"]
    turn, _ = asked(client, cid, question="재시도는 언제 안전해?")
    fake.delete_entry(RETRY)
    for path in (f"/api/ai/conversations/{cid}", f"/api/ai/turns/{turn['turn_id']}", source_path(turn["turn_id"])):
        assert_error(get(client, path), 404, "not_found")
    assert_error(ask(client, cid), 404, "not_found")


def test_e32_on_a_wiki_source_is_404_for_other_users_and_unknown_refs(client, fake, wiki_on):
    cid = fake.conversation(A)
    turn, _ = asked(client, cid)
    tid = turn["turn_id"]
    assert get(client, source_path(tid)).status_code == 200
    assert_error(get(client, source_path(tid), token="b-token"), 404, "not_found")
    assert_error(get(client, source_path(tid, 2)), 404, "not_found")
    assert_error(get(client, source_path(uuid.uuid4())), 404, "not_found")


def test_e32_rechecks_the_entry_after_the_hidden_check(client, fake, wiki_on, monkeypatch):
    cid = fake.conversation(A)
    turn, _ = asked(client, cid)
    term_id = int(cited_terms(fake)[0].split(":")[1])
    original = fake.get_agent_turn_source

    def delete_then_read(turn_id, ref):
        fake.delete_entry(term_id)
        return original(turn_id, ref)

    monkeypatch.setattr(fake, "get_agent_turn_source", delete_then_read)
    assert_error(get(client, source_path(turn["turn_id"])), 404, "not_found")


# --- AC-4: 인용 뒤 항목을 고치면 인용 당시 문단과 changed_since_cited: true ---


def test_e32_returns_the_cited_wiki_paragraph_unchanged(client, fake, wiki_on):
    cid = fake.conversation(A)
    turn, _ = asked(client, cid)
    assert cited_terms(fake) == [f"glossary:{IDEMPOTENCY}"]
    response = get(client, source_path(turn["turn_id"]))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "ref": 1, "source_kind": "wiki", "source_id": f"glossary:{IDEMPOTENCY}", "title": "멱등성", "section": "정의", "cited_revision": "1",
        "paragraph_text": IDEMPOTENCY_DEFINITION, "highlight": None, "changed_since_cited": False,
    }


def test_after_the_entry_is_edited_e32_returns_the_paragraph_as_cited(client, fake, wiki_on):
    cid = fake.conversation(A)
    turn, _ = asked(client, cid)
    fake.save_entry(IDEMPOTENCY, "멱등성", IDEMPOTENCY_BODY.replace("같은 성질이다", "같은 성질을 말한다"))
    data = get(client, source_path(turn["turn_id"])).json()
    assert data["paragraph_text"] == IDEMPOTENCY_DEFINITION and data["cited_revision"] == "1"
    assert data["changed_since_cited"] is True
    assert fake.terms[IDEMPOTENCY]["glossary_revision"] == 2
    assert "hidden" not in get(client, f"/api/ai/turns/{turn['turn_id']}").json()


def test_edits_elsewhere_in_the_entry_do_not_count_as_a_change(client, fake, wiki_on):
    # 사전 개정은 저장마다 오른다. 인용한 문단이 그대로면 바뀌지 않은 것이다.
    cid = fake.conversation(A)
    turn, _ = asked(client, cid)
    fake.save_entry(IDEMPOTENCY, "멱등성 (새 제목)", IDEMPOTENCY_BODY + "\n\n# 덧붙임\n새 절을 더했다.")
    data = get(client, source_path(turn["turn_id"])).json()
    assert data["changed_since_cited"] is False and data["title"] == "멱등성"


def test_the_current_entry_paragraphs_are_split_by_the_same_rule_as_the_search():
    assert IDEMPOTENCY_DEFINITION in {chunk.text for chunk in note_chunks(IDEMPOTENCY_BODY)}


# --- AC-5: 지운 항목을 다시 등록하면 개정 번호가 이어지고 가려졌던 턴이 다시 보인다 ---


def test_re_registering_a_deleted_entry_shows_the_hidden_turn_again_as_cited(client, fake, wiki_on):
    cid = fake.conversation(A)
    turn, _ = asked(client, cid)
    fake.delete_entry(IDEMPOTENCY)
    assert get(client, f"/api/ai/turns/{turn['turn_id']}").json()["hidden"]["reason"] == "source_revoked"

    fake.save_entry(IDEMPOTENCY, "멱등성", "# 정의\n다시 쓴 본문이다.")
    assert fake.terms[IDEMPOTENCY]["glossary_revision"] == 2
    read = get(client, f"/api/ai/turns/{turn['turn_id']}").json()
    assert "hidden" not in read and read["result"]["sources"][0]["cited_revision"] == "1"
    data = get(client, source_path(turn["turn_id"])).json()
    # 보이는 것은 인용 당시 원문이다. 본문이 바뀌었으므로 바뀜으로 알린다.
    assert data["paragraph_text"] == IDEMPOTENCY_DEFINITION and data["changed_since_cited"] is True

    # 새 질문은 이어서 오른 개정을 인용한다.
    asked(client, cid, question="다시 쓴 본문")
    assert {s["cited_revision"] for s in fake.finishes[-1]["p_sources"]} == {"2"}


# --- AC-6: 운영자의 비공개 노트 선택이 검색 후보·출처·로그에 나오지 않고, figures에 이미지가 없다 ---


def test_an_operators_private_note_selection_never_reaches_evidence_sources_or_logs(
    client, fake, bedrock, wiki_on, caplog
):
    cid = fake.conversation(OP, note_id=PRIVATE)
    fake.selections[-1]["text_snapshot"] = f"멱등성 {CANARY}"
    image = {"kind": "image", "image": {"url": "https://example.test/x.png"}, "caption": "c", "alt_text": "a",
             "source_refs": [1], "after_section": 1}
    diagram = {"mermaid": "flowchart LR\n  A[요청] --> B[응답]", "caption": "흐름", "alt_text": "요청에서 응답",
               "source_refs": [1], "after_section": 1}
    bedrock.replies = [bedrock_reply(answer_json(figures=[image, diagram]))]
    with caplog.at_level("DEBUG"):
        result, parsed = asked(client, cid, token="op-token")
        source = get(client, source_path(result["turn_id"]), token="op-token").json()

    prompt = bedrock.prompts[-1]
    # 선택 문장은 질문 문맥 구역에만 있다(PRD 4·11절). 근거 구역과 출처에는 없다.
    assert CANARY in prompt and CANARY not in prompt_evidence(prompt)
    assert "비공개검토문단" not in prompt
    sources = fake.finishes[-1]["p_sources"]
    assert sources and all(s["source_kind"] == "wiki" for s in sources)
    assert CANARY not in json.dumps(sources, ensure_ascii=False)
    assert CANARY not in json.dumps(result, ensure_ascii=False) and CANARY not in json.dumps(source, ensure_ascii=False)
    # 로그에는 단계와 개수만 남는다(S10). 선택·질문·위키 원문이 없다.
    assert "stage=retrieve source_kind=wiki" in caplog.text
    for text in (CANARY, "멱등성", IDEMPOTENCY_DEFINITION[:10]):
        assert text not in caplog.text
    # 그림은 다이어그램만이다(W6, S9).
    assert [f["kind"] for f in result["result"]["figures"]] == ["diagram"]
    # 비공개 노트 본문을 근거로 읽지 않는다.
    assert "list_published_note_bodies" not in fake.calls


# --- 판정 함수 ---


def _user(user_id=A, role="member"):
    return SessionUser(user_id=user_id, role=role)


def test_source_checker_sees_a_wiki_source_only_while_its_entry_exists():
    visible = source_checker({}, {7: {"id": 7, "label": "멱등성"}})
    assert visible({"source_kind": "wiki", "source_id": "glossary:7"})
    assert not visible({"source_kind": "wiki", "source_id": "glossary:8"})
    for odd in ("7", "glossary:07", "glossary:7 ", "page-1", "", None):
        assert not visible({"source_kind": "wiki", "source_id": odd})
    assert not visible({"source_kind": "web", "source_id": "glossary:7"})
    # 위키 상태가 없으면(T4 전 호출 방식) 위키 출처는 보이지 않는다.
    assert not source_checker({})({"source_kind": "wiki", "source_id": "glossary:7"})


def test_check_conversation_opens_a_wiki_conversation_only_with_the_flag_and_the_entry(monkeypatch):
    conversation = {"id": "c", "user_id": A, "origin": "wiki", "note_id": None, "wiki_ref": "glossary:7"}
    entry = {7: {"id": 7, "label": "멱등성"}}
    with pytest.raises(ApiError):
        check_conversation(_user(), conversation, {}, entry)  # 플래그 꺼짐
    monkeypatch.setenv(WIKI_ENV, "1")
    access = check_conversation(_user(), conversation, {}, entry)
    assert isinstance(access, ConversationAccess) and access.wiki == entry
    for bad_wiki, bad_conversation in (
        ({}, conversation),
        (entry, {**conversation, "wiki_ref": "glossary:07"}),
        (entry, {**conversation, "origin": "note", "note_id": 1}),
        (entry, {**conversation, "user_id": B}),
    ):
        with pytest.raises(ApiError):
            check_conversation(_user(), bad_conversation, {1: {"is_published": True}}, bad_wiki)


# --- 리뷰 뒤 보강 ---


def test_a_wiki_conversation_never_cites_note_paragraphs_even_from_another_retriever(client, fake, bedrock, wiki_on):
    # 위키 대화는 노트 문단을 근거로 쓰지 않는다(설계 독립 리뷰 R1, W2). 검색 구현이 무엇이든 E29가 걸러 낸다.
    from app.agent_retrieval import FixedRetriever, Paragraph

    note = Paragraph("note", str(SOURCE_NOTE), "3", "출처 노트", "재시도는 멱등성이 있는 요청에만 안전하다.", "재시도")
    wiki = Paragraph("wiki", f"glossary:{IDEMPOTENCY}", "1", "멱등성", IDEMPOTENCY_DEFINITION, "정의")
    cid = create(client, wiki_body()).json()["conversation_id"]
    client.app.dependency_overrides[get_retriever] = lambda: FixedRetriever([note, wiki])
    bedrock.replies = [bedrock_reply(answer_json(sections=[{"heading": "핵심", "body": "설명 [1]."}]))]
    asked(client, cid)
    assert [s["source_kind"] for s in fake.finishes[-1]["p_sources"]] == ["wiki"]
    assert "재시도는 멱등성이 있는 요청에만 안전하다." not in prompt_evidence(bedrock.prompts[-1])
    # 노트 문단만 나오면 근거 없음이다(모델을 부르지 않는다).
    client.app.dependency_overrides[get_retriever] = lambda: FixedRetriever([note])
    calls = bedrock.calls
    result, _ = asked(client, cid)
    assert result["result"]["state"] == "no_evidence" and bedrock.calls == calls


def test_flag_off_a_wiki_cited_turn_in_a_note_conversation_stays_visible_while_the_entry_exists(
    client, fake, monkeypatch
):
    # 위키 출처의 가림은 플래그와 관계없이 항목 존재로 정한다(배포 가이드 "끄면" 항목).
    monkeypatch.setenv(WIKI_ENV, "1")
    cid = fake.conversation(A)
    turn, _ = asked(client, cid)
    monkeypatch.delenv(WIKI_ENV)
    read = get(client, f"/api/ai/turns/{turn['turn_id']}").json()
    assert "hidden" not in read and read["result"]["sources"][0]["source_kind"] == "wiki"
    assert get(client, source_path(turn["turn_id"])).status_code == 200
    fake.delete_entry(IDEMPOTENCY)
    assert get(client, f"/api/ai/turns/{turn['turn_id']}").json()["hidden"]["reason"] == "source_revoked"
    assert_error(get(client, source_path(turn["turn_id"])), 404, "not_found")


def test_flag_off_a_resent_key_and_a_cancel_on_a_wiki_conversation_are_404(client, fake, monkeypatch):
    monkeypatch.setenv(WIKI_ENV, "1")
    cid = create(client, wiki_body()).json()["conversation_id"]
    key = str(uuid.uuid4())
    events(ask(client, cid, key=key))
    running = fake.turn(cid, 9, status="running")
    monkeypatch.delenv(WIKI_ENV)
    assert_error(ask(client, cid, key=key), 404, "not_found")
    response = client.post(f"/api/ai/turns/{running}/cancel", headers={**origin(), **cookie("a-token")})
    assert_error(response, 404, "not_found")
    assert fake.turns[running]["status"] == "running"


def test_flag_off_reading_a_note_conversation_does_not_read_the_dictionary(client, fake):
    cid = fake.conversation(A)
    asked(client, cid)
    fake.calls.clear()
    assert get(client, f"/api/ai/conversations/{cid}").status_code == 200
    assert not {"get_wiki_entry_states", "get_wiki_entry", "list_wiki_entries"} & set(fake.calls)
