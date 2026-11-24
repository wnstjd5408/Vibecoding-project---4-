"""CS Agent 노트 임시 검색을 E29에 붙인 흐름과 출처 보기 E32 (MEG-237 AC-1~AC-3, 기술 검토 v0.4 7절 T3b 시험).

검색은 앱 기본값(get_retriever → NoteRetriever)을 그대로 쓴다. Supabase·원장·Bedrock은 가짜라 네트워크 없이 돈다.
데이터는 모두 합성이다. 모델은 부르지 않는다(가짜 Bedrock이 정해 둔 답을 준다).

- AC-1: 비공개 노트는 검색되지 않는다. 운영자로 요청해도 같다.
- AC-2: 인용한 노트를 비공개로 바꾸거나 지우면 E28·E30에서 그 턴부터 hidden이고 E32는 404다.
- AC-3: 인용한 뒤 노트를 고치면 E32가 인용 당시 문단을 돌려주고 changed_since_cited가 참이다.
"""

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import agent, agent_sources, agent_turns
from app.agent_note_search import note_chunks
from app.ai_explain import AiRuntime, get_ai_runtime
from app.common import install_common_layer
from app.rate_limit import AI_AGENT_READ
from app.supabase import get_supabase
from support import cookie
from test_agent import A, B, OP, PRIVATE, PUBLIC, SOURCE_NOTE, assert_error
from test_agent_turns import (
    BUDGET,
    SETTINGS,
    AgentBedrock,
    AgentStore,
    TurnFake,
    answer_json,
    ask,
    bedrock_reply,
    events,
)

SOURCE_BODY = (
    "# 정의\n멱등성은 같은 요청을 여러 번 보내도 결과가 한 번 보낸 것과 같은 성질이다.\n\n"
    "# 재시도\n재시도는 멱등성이 있는 요청에만 안전하다."
)
DEFINITION = "멱등성은 같은 요청을 여러 번 보내도 결과가 한 번 보낸 것과 같은 성질이다."
# 비공개 노트에만 있는 글. 검색되면 프롬프트·출처에 나타난다.
PRIVATE_MARK = "비공개검토문단"
PRIVATE_BODY = f"# 비공개\n멱등성 {PRIVATE_MARK} 작성 중인 설명이다."
CONVERSATION_BODY = "# 대화 노트\n멱등성 선택 문장이 들어 있는 문단이다."


class SourceFake(TurnFake):
    """TurnFake에 노트 검색·E32 래퍼를 더한다. 실제 래퍼처럼 공개 노트만 읽는다."""

    def list_published_note_bodies(self):
        self._db("list_published_note_bodies")
        return [
            {k: row[k] for k in ("id", "revision", "title", "body_markdown")}
            for _, row in sorted(self.note_rows.items())
            if row["is_published"]
        ]

    def get_agent_turn_source(self, turn_id, ref):
        self._db("get_agent_turn_source")
        for source in self.sources:
            if source["turn_id"] == turn_id and source["ref"] == ref:
                return {k: source.get(k) for k in ("ref", "source_kind", "source_id", "cited_revision", "title",
                                                    "section", "paragraph_snapshot")}
        return None

    def edit_note(self, note_id, body=None, title=None):
        row = self.note_rows[note_id]
        if body is not None:
            row["body_markdown"] = body
        if title is not None:
            row["title"] = title
        row["revision"] += 1


@pytest.fixture
def fake(monkeypatch):
    from app import session
    from test_agent import NOW

    monkeypatch.delenv(agent.DISABLE_ENV, raising=False)
    for name in ("VERCEL", "VERCEL_ENV", "VERCEL_TARGET_ENV", "VERCEL_GIT_COMMIT_REF"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(session, "now", lambda: NOW + 0.5)
    fake = SourceFake(now=NOW + 0.5)
    fake.add_user("a-token", A)
    fake.add_user("b-token", B)
    fake.add_user("op-token", OP, role="operator")
    fake.note(PUBLIC, title="대화 노트", body=CONVERSATION_BODY)
    fake.note(PRIVATE, published=False, title="비공개 노트", body=PRIVATE_BODY)
    fake.note(SOURCE_NOTE, title="출처 노트", body=SOURCE_BODY)
    return fake


@pytest.fixture
def store():
    return AgentStore()


@pytest.fixture
def bedrock():
    return AgentBedrock()


@pytest.fixture
def client(fake, store, bedrock):
    app = FastAPI()
    install_common_layer(app)
    runtime = AiRuntime(
        store=store,
        load_budget=lambda: BUDGET,
        load_settings=lambda: SETTINGS,
        client_factory=lambda settings, token=None: bedrock,
        sleep=lambda seconds: None,
    )
    app.dependency_overrides[get_supabase] = lambda: fake
    app.dependency_overrides[get_ai_runtime] = lambda: runtime
    # get_retriever는 덮어쓰지 않는다. 앱 기본값(노트 임시 검색)을 시험한다.
    app.include_router(agent.router)
    app.include_router(agent_turns.router)
    app.include_router(agent_sources.router)
    return TestClient(app)


def get(client, path, token="a-token"):
    return client.get(path, headers=cookie(token))


def source_path(turn_id, ref=1):
    return f"/api/ai/turns/{turn_id}/sources/{ref}"


def asked_turn(client, fake, cid, token="a-token", question="멱등성이 뭐야?"):
    parsed = events(ask(client, cid, body={"question": {"kind": "free", "text": question}}, token=token))
    result = parsed[-1][1]
    assert parsed[-1][0] == "result" and result["status"] == "completed", parsed[-1]
    return result, parsed


def prompt_evidence(prompt: str) -> str:
    """프롬프트의 근거 문단 구역."""
    return prompt.split("<<<근거 문단 시작>>>")[1].split("<<<근거 문단 끝>>>")[0]


# --- 앱 기본값 ---


def test_the_app_default_retriever_is_the_note_search(fake):
    from app.agent_note_search import NoteRetriever
    from app.agent_retrieval import get_retriever

    retriever = get_retriever(fake)
    assert isinstance(retriever, NoteRetriever) and retriever.version == "note-keyword-v1"


def test_a_question_answered_from_notes_cites_note_paragraphs(client, fake, bedrock):
    cid = fake.conversation(A)
    result, parsed = asked_turn(client, fake, cid)
    steps = [data for name, data in parsed if name == "step"]
    # 단계 완료 이벤트에 근거 종류를 싣는다(spec 6절, 2026-11-18 결정).
    assert {"step": "retrieve", "state": "done", "paragraph_count": 2, "source_kind": "note"} in steps
    assert result["result"]["sources"] == [
        {"ref": 1, "source_kind": "note", "title": "출처 노트", "section": "정의", "excerpt": DEFINITION,
         "cited_revision": "3"}
    ]
    [finish] = fake.finishes
    assert finish["p_retrieval_version"] == "note-keyword-v1"
    assert finish["p_sources"][0]["source_id"] == str(SOURCE_NOTE)
    assert finish["p_sources"][0]["paragraph_snapshot"] == DEFINITION


# --- AC-1: 비공개 노트는 검색되지 않는다(운영자 포함) ---


@pytest.mark.parametrize("token,user", [("a-token", A), ("op-token", OP)])
def test_unpublished_notes_are_never_searched_for_members_or_operators(client, fake, bedrock, token, user):
    cid = fake.conversation(user)
    asked_turn(client, fake, cid, token=token)
    evidence = prompt_evidence(bedrock.prompts[-1])
    assert PRIVATE_MARK not in evidence and "비공개 노트" not in evidence
    assert all(source["source_id"] != str(PRIVATE) for source in fake.finishes[-1]["p_sources"])
    assert "list_published_note_bodies" in fake.calls


def test_an_operator_asking_from_an_unpublished_note_gets_no_evidence_from_that_note(client, fake, bedrock):
    # Q13: 운영자는 비공개 노트에서 대화를 열 수 있다. 선택 문장은 문맥으로만 쓰고, 그 노트의 다른 문단도 근거가 아니다.
    cid = fake.conversation(OP, note_id=PRIVATE)
    asked_turn(client, fake, cid, token="op-token")
    prompt = bedrock.prompts[-1]
    assert PRIVATE_MARK not in prompt_evidence(prompt)
    cited = {s["source_id"] for s in fake.finishes[-1]["p_sources"]}
    assert cited and cited <= {str(PUBLIC), str(SOURCE_NOTE)}


def test_when_only_unpublished_notes_match_the_turn_is_no_evidence_without_a_model_call(client, fake, bedrock):
    cid = fake.conversation(OP, note_id=PRIVATE)
    result, parsed = asked_turn(client, fake, cid, token="op-token", question=f"{PRIVATE_MARK} 설명")
    assert result["result"]["state"] == "no_evidence" and bedrock.calls == 0
    assert {"step": "retrieve", "state": "done", "paragraph_count": 0, "source_kind": "note"} in [
        data for name, data in parsed if name == "step"
    ]


def test_the_paragraph_holding_the_selection_is_not_evidence(client, fake, bedrock):
    # 대화의 선택 문장("멱등성", 대화 노트 0~3)이 든 대화 노트 문단은 검색에서 빠진다.
    cid = fake.conversation(A)
    asked_turn(client, fake, cid)
    assert "선택 문장이 들어 있는 문단" not in prompt_evidence(bedrock.prompts[-1])


# --- 노트 근거만 있을 때는 교정하지 않는다 ---


def test_with_note_evidence_only_the_prompt_has_no_correction_rule(client, fake, bedrock):
    cid = fake.conversation(A)
    asked_turn(client, fake, cid)
    prompt = bedrock.prompts[-1]
    assert "corrections" not in prompt and "state를 correction으로 하지 않습니다" in prompt


# --- AC-2: 인용한 노트를 비공개로 바꾸거나 지우면 그 턴부터 hidden, E32는 404 ---


@pytest.mark.parametrize("revoke", ["unpublish", "delete"])
def test_revoking_a_cited_note_hides_that_turn_and_later_turns_and_closes_e32(client, fake, bedrock, revoke):
    cid = fake.conversation(A)
    # 1번 턴은 대화 노트만 근거로 답한다(출처 노트를 인용하지 않는다). 2번 턴이 출처 노트를 인용한다.
    first, _ = asked_turn(client, fake, cid, question="선택 문장")
    assert first["result"]["state"] == "no_evidence"
    second, _ = asked_turn(client, fake, cid)
    third, _ = asked_turn(client, fake, cid, question="재시도는 언제 안전해?")
    assert get(client, source_path(second["turn_id"])).status_code == 200

    if revoke == "unpublish":
        fake.note_rows[SOURCE_NOTE]["is_published"] = False
    else:
        fake.delete_note(SOURCE_NOTE)

    turns = get(client, f"/api/ai/conversations/{cid}").json()["turns"]
    assert [t["turn_id"] for t in turns] == [first["turn_id"], second["turn_id"], third["turn_id"]]
    assert "hidden" not in turns[0] and turns[0]["result"]["state"] == "no_evidence"
    assert turns[1]["hidden"] == {"reason": "source_revoked", "retry_allowed": True} and "result" not in turns[1]
    assert turns[2]["hidden"] == {"reason": "source_revoked", "retry_allowed": False} and "result" not in turns[2]
    # E30도 같은 가림 함수를 쓴다.
    for turn in turns:
        assert get(client, f"/api/ai/turns/{turn['turn_id']}").json() == turn
    # E32는 404다. 운영자 역할이어도 같다(노트 출처는 역할 무관, 공개이고 존재해야 열린다).
    assert_error(get(client, source_path(second["turn_id"])), 404, "not_found")
    assert_error(get(client, source_path(third["turn_id"])), 404, "not_found")


def test_an_operator_cannot_open_a_source_from_an_unpublished_note(client, fake):
    cid = fake.conversation(OP)
    turn, _ = asked_turn(client, fake, cid, token="op-token")
    assert get(client, source_path(turn["turn_id"]), token="op-token").status_code == 200
    fake.note_rows[SOURCE_NOTE]["is_published"] = False
    assert_error(get(client, source_path(turn["turn_id"]), token="op-token"), 404, "not_found")


def test_e32_rechecks_the_note_after_the_hidden_check(client, fake, monkeypatch):
    # 가림 판정과 본문 읽기 사이에 노트가 비공개가 되어도 열지 않는다.
    cid = fake.conversation(A)
    turn, _ = asked_turn(client, fake, cid)
    original = fake.get_agent_turn_source

    def revoke_then_read(turn_id, ref):
        fake.note_rows[SOURCE_NOTE]["is_published"] = False
        return original(turn_id, ref)

    monkeypatch.setattr(fake, "get_agent_turn_source", revoke_then_read)
    assert_error(get(client, source_path(turn["turn_id"])), 404, "not_found")


# --- AC-3: 인용 뒤 노트를 고쳐도 E32는 인용 당시 문단을 준다 ---


def test_e32_returns_the_cited_paragraph_and_reports_no_change(client, fake):
    cid = fake.conversation(A)
    turn, _ = asked_turn(client, fake, cid)
    response = get(client, source_path(turn["turn_id"]))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "ref": 1, "source_kind": "note", "source_id": str(SOURCE_NOTE), "title": "출처 노트", "section": "정의",
        "cited_revision": "3",
        "paragraph_text": DEFINITION, "highlight": None, "changed_since_cited": False,
    }


def test_after_the_note_is_edited_e32_returns_the_paragraph_as_cited(client, fake):
    cid = fake.conversation(A)
    turn, _ = asked_turn(client, fake, cid)
    fake.edit_note(SOURCE_NOTE, body=SOURCE_BODY.replace("같은 성질이다", "같은 성질을 말한다"))
    data = get(client, source_path(turn["turn_id"])).json()
    assert data["paragraph_text"] == DEFINITION and data["cited_revision"] == "3"
    assert data["changed_since_cited"] is True
    # 턴은 가려지지 않는다(노트가 여전히 공개이고 존재한다).
    assert "hidden" not in get(client, f"/api/ai/turns/{turn['turn_id']}").json()


def test_edits_elsewhere_in_the_note_do_not_count_as_a_change(client, fake):
    # 노트 개정은 제목·다른 문단을 고쳐도 오른다. 인용한 문단이 그대로면 바뀌지 않은 것이다.
    cid = fake.conversation(A)
    turn, _ = asked_turn(client, fake, cid)
    fake.edit_note(SOURCE_NOTE, body=SOURCE_BODY + "\n\n# 덧붙임\n새 절을 더했다.", title="새 제목")
    data = get(client, source_path(turn["turn_id"])).json()
    assert data["changed_since_cited"] is False and data["title"] == "출처 노트"
    assert fake.note_rows[SOURCE_NOTE]["revision"] == 4


def test_the_current_paragraphs_are_split_by_the_same_rule_as_the_search():
    assert DEFINITION in {chunk.text for chunk in note_chunks(SOURCE_BODY)}


# --- E32 경로·권한·속도 제한 ---


def test_e32_refuses_bad_paths_uncited_refs_and_other_users(client, fake):
    cid = fake.conversation(A)
    turn, _ = asked_turn(client, fake, cid)
    tid = turn["turn_id"]
    for path in (source_path(tid, 2), source_path(tid, 0), source_path(tid, "01"), source_path(tid, "x"),
                 source_path(tid, 1000), source_path("not-a-uuid"), source_path(uuid.uuid4())):
        assert_error(get(client, path), 404, "not_found")
    assert_error(get(client, source_path(tid), token="b-token"), 404, "not_found")
    assert_error(client.get(source_path(tid)), 401, "login_required")


def test_e32_refuses_turns_without_a_result_and_wiki_sources(client, fake):
    cid = fake.conversation(A)
    running = fake.turn(cid, 1, status="running", sources=[("note", str(SOURCE_NOTE))])
    assert_error(get(client, source_path(running)), 404, "not_found")
    cid2 = fake.conversation(A)
    wiki = fake.turn(cid2, 1, sources=[("wiki", "w-1")])
    assert_error(get(client, source_path(wiki)), 404, "not_found")


def test_e32_is_rate_limited_with_the_read_rule_before_reading_the_turn(client, fake):
    cid = fake.conversation(A)
    turn, _ = asked_turn(client, fake, cid)
    for _ in range(AI_AGENT_READ.limit):
        fake.calls.clear()
        get(client, source_path(turn["turn_id"]))
    fake.calls.clear()
    assert_error(get(client, source_path(turn["turn_id"])), 429, "rate_limited")
    assert_error(get(client, source_path(uuid.uuid4())), 429, "rate_limited")
    assert fake.calls == []


def test_e32_logs_no_paragraph_text(client, fake, caplog):
    cid = fake.conversation(A)
    turn, _ = asked_turn(client, fake, cid)
    caplog.clear()
    with caplog.at_level("INFO", logger="app.agent"):
        get(client, source_path(turn["turn_id"]))
    assert "stage=source" in caplog.text
    assert DEFINITION[:10] not in caplog.text and "멱등성" not in caplog.text


def test_answer_json_default_cites_the_first_paragraph():
    # 이 파일의 시험은 기본 답(answer_json)이 [1]만 인용한다는 전제를 쓴다.
    assert "[1]" in answer_json() and "[2]" not in answer_json()


def test_e32_stays_readable_while_the_agent_is_disabled(client, fake, monkeypatch):
    # 노출 중단(Q11)은 E27·E29만 막는다. E32는 읽기라 남긴다(기술 검토 6절).
    cid = fake.conversation(A)
    turn, _ = asked_turn(client, fake, cid)
    monkeypatch.setenv(agent.DISABLE_ENV, "1")
    assert get(client, source_path(turn["turn_id"])).status_code == 200


def test_a_correction_reply_on_note_evidence_is_kept_as_an_answer(client, fake, bedrock):
    # 리뷰 지적(2026-11-18): 근거가 노트뿐이면 correction을 answered로 받는다(결정 "answered나 partial로 답한다").
    cid = fake.conversation(A)
    correction = json.dumps({
        "state": "correction",
        "sections": [{"body": "설명 [1]"}],
        "corrections": [{"note_excerpt": "멱등성", "corrected": "고친 내용 [1]", "source_refs": [1]}],
        "unresolved": ["남은 점"],
    }, ensure_ascii=False)
    bedrock.replies = [bedrock_reply(correction)]
    result, _ = asked_turn(client, fake, cid)
    assert result["result"]["state"] == "answered"
    assert result["result"]["sections"] == [{"body": "설명 [1]"}]
    assert "corrections" not in result["result"] and "unresolved" not in result["result"]
    assert [s["ref"] for s in result["result"]["sources"]] == [1]


def test_an_operator_sees_the_turn_hidden_after_the_cited_note_is_deleted(client, fake):
    # 노트 출처는 역할과 관계없이 공개이고 존재해야 보인다(test-verifier 지적: 운영자 삭제 경우).
    cid = fake.conversation(OP)
    turn, _ = asked_turn(client, fake, cid, token="op-token")
    fake.delete_note(SOURCE_NOTE)
    [read] = get(client, f"/api/ai/conversations/{cid}", token="op-token").json()["turns"]
    assert read["hidden"] == {"reason": "source_revoked", "retry_allowed": True}
    assert get(client, f"/api/ai/turns/{turn['turn_id']}", token="op-token").json() == read
    assert_error(get(client, source_path(turn["turn_id"]), token="op-token"), 404, "not_found")


def test_image_figures_are_dropped_on_note_evidence(client, fake, bedrock):
    # 노트 근거 기간에는 figures에 kind image를 넣지 않는다(기술 검토 4절 T4 전 동작).
    cid = fake.conversation(A)
    image = {"kind": "image", "image": {"url": "https://example.test/x.png"}, "caption": "c", "alt_text": "a",
             "source_refs": [1], "after_section": 1}
    diagram = {"mermaid": "flowchart LR\n  A[요청] --> B[응답]", "caption": "흐름", "alt_text": "요청에서 응답",
               "source_refs": [1], "after_section": 1}
    bedrock.replies = [bedrock_reply(answer_json(figures=[image, diagram]))]
    result, _ = asked_turn(client, fake, cid)
    assert [f["kind"] for f in result["result"]["figures"]] == ["diagram"]
