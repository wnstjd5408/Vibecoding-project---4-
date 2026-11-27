"""MEG-282 AG09: CS Agent 권한 통합 시험(E27~E32). 실행 방법은 permission_matrix_README.md의 'CS Agent 권한(AG09)' 절.

PRD v0.5 AG09 "타 사용자 대화·미공개 근거·권한 회수 자료를 노출하지 않음"을 API spec v0.2 8절 규칙으로 확인한다.
MEG-69 권한 행렬과 같은 전용 로컬 스택(Auth·REST·Storage)과 실제 앱 라우터·세션·역할 검사를 쓴다. 비공개 전환과 삭제는
운영자의 실제 E17·E18로 한다. 대화·턴·출처 행은 SQL로 넣는다(모델 출력을 흉내 내지 않고 저장된 모양만 맞춘다).

모델과 검색은 부르지 않는다. 거부 경로가 모델·검색에 닿으면 시험이 실패한다. E29의 성공 경로(실제 답 생성)는 이 시험의
범위가 아니다. 이 파일은 명시적으로 실행할 때만 돈다(MEG69_LOCAL=1). 환경이 없으면 건너뜀이며 통과로 보고하지 않는다.
"""

import hashlib
import json
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from permission_local import NOTE, ORIGIN, PRIVATE, LocalMatrix, install, no_ai

from app import agent
from app.agent_note_search import NoteRetriever
from app.agent_retrieval import RetrievalContext, get_retriever
from app.ai_explain import AiRuntime, get_ai_runtime
from app.ai_ledger import AiBudget, SupabaseLedgerStore
from app.auth import SessionUser
from app.bedrock import BedrockSettings
from app.main import app

# 이 시험만 쓰는 합성 노트. MEG-69 예약 ID(69001~69007)와 겹치지 않는다.
CONTEXT, CITED, SELECTED = 69011, 69012, 69013
MISSING = 69019
OWN_NOTES = (CONTEXT, CITED, SELECTED)
CITED_TITLE = "MEG282 cited synthetic title"
CITED_TEXT = "MEG282 cited synthetic paragraph about idempotency keys."
CONTEXT_TEXT = "MEG282 context synthetic paragraph about retries."
AGENT_TABLES = ("ai_conversations", "ai_conversation_selections", "ai_turns", "ai_turn_sources", "ai_usage_ledger")
BUDGET = AiBudget(daily_usd=Decimal("0.9"), monthly_usd=Decimal(7),
                  input_usd_per_mtok=Decimal(2), output_usd_per_mtok=Decimal(8))


class NoRetriever:
    """거부 경로가 검색에 닿으면 실패시킨다."""

    version = "none"
    source_kind = "note"

    def retrieve(self, *args, **kwargs):
        raise AssertionError("A denied CS Agent request must not search notes")


@pytest.fixture(scope="module")
def local():
    if os.environ.get("MEG69_LOCAL") != "1":
        pytest.skip("MEG69_LOCAL=1 and this worktree's disposable Supabase stack required")
    matrix = LocalMatrix()
    with pytest.MonkeyPatch.context() as patch:
        install(matrix, patch)
        # 노출 중단·위키 플래그는 꺼진 상태(운영 베타와 같은 D1)로 본다. 예산·설정은 읽되 모델 클라이언트는 만들지 못한다.
        patch.delenv(agent.DISABLE_ENV, raising=False)
        patch.delenv("CS_AGENT_WIKI_ENABLED", raising=False)
        for name in ("VERCEL", "VERCEL_ENV"):
            patch.delenv(name, raising=False)
        runtime = AiRuntime(store=SupabaseLedgerStore(matrix.db), load_budget=lambda: BUDGET,
                            load_settings=lambda: BedrockSettings(auth_mode="api_key"), client_factory=no_ai)
        patch.setitem(app.dependency_overrides, get_ai_runtime, lambda: runtime)
        patch.setitem(app.dependency_overrides, get_retriever, lambda: NoRetriever())
        try:
            matrix.setup()
            ids = ",".join(str(n) for n in (*OWN_NOTES, MISSING))
            assert matrix.sql(f"select count(*) from notes where id in ({ids});") == "0"
            yield matrix
        finally:
            try:
                if matrix.seeded:
                    clear(matrix)
            finally:
                matrix.close()


def clear(matrix):
    users = ",".join(f"'{u['id']}'" for u in matrix.users.values())
    ids = ",".join(str(n) for n in OWN_NOTES)
    matrix.sql(f"""
      delete from ai_conversations where user_id in ({users});
      delete from ai_usage_ledger where user_id in ({users});
      delete from notes where id in ({ids});
    """)


def turn_sql(conversation, user, seq, *, status="completed", cites=None):
    """저장된 턴 한 개. completed면 결과를, cites가 있으면 그 노트를 인용한 출처 행(ref 1)을 함께 넣는다."""
    turn = str(uuid4())
    if status == "running":
        tail = "'running', null, null, now() + interval '1 hour', null"
    else:
        result = json.dumps({"state": "answered", "sections": [{"text": "Synthetic stored answer [1]"}]})
        tail = f"'completed', null, '{result}'::jsonb, now() - interval '1 minute', now()"
    statement = f"""
      insert into ai_turns(id,conversation_id,user_id,seq,idempotency_key,question_kind,question_text,
                           status,failure,result,lease_expires_at,finished_at)
        values ('{turn}','{conversation}','{user}',{seq},'{uuid4()}','free','Synthetic question {seq}',{tail});"""
    if cites is not None:
        title, text = (CITED_TITLE, CITED_TEXT) if cites == CITED else ("MEG282 context", CONTEXT_TEXT)
        statement += f"""
      insert into ai_turn_sources(turn_id,ref,source_kind,source_id,cited_revision,title,section,excerpt,paragraph_snapshot)
        values ('{turn}',1,'note','{cites}','1','{title}',null,'{text[:40]}','{text}');"""
    return turn, statement


def conversation_sql(user, *, note=None, selection=None):
    conversation = str(uuid4())
    if note is None:
        statement = f"""
      insert into ai_conversations(id,user_id,origin,topic_label) values ('{conversation}','{user}','none','Synthetic');"""
    else:
        statement = f"""
      insert into ai_conversations(id,user_id,origin,note_id,note_revision,topic_label)
        values ('{conversation}','{user}','note',{note},1,'Synthetic');"""
    for note_id in [n for n in (note, selection) if n is not None]:
        statement += f"""
      insert into ai_conversation_selections(conversation_id,note_id,note_revision,start,"end",text_snapshot)
        values ('{conversation}',{note_id},1,0,8,'MEG282 c');"""
    return conversation, statement


@pytest.fixture
def case(local):
    """케이스마다 MEG-69 데이터와 이 시험의 대화를 새로 넣는다. 반환값은 이름 → id다."""
    local.seed()
    clear(local)
    member, operator = local.users["member"]["id"], local.users["operator"]["id"]
    ids, sql = {}, [f"""
      insert into notes(id,title,body_markdown,is_published) overriding system value values
        ({CONTEXT},'MEG282 context','{CONTEXT_TEXT}',true),
        ({CITED},'{CITED_TITLE}','{CITED_TEXT}',true),
        ({SELECTED},'MEG282 selection','MEG282 selection synthetic paragraph.',true);"""]

    def add(name, statement_pair):
        ids[name], statement = statement_pair
        sql.append(statement)

    # 노트에서 연 대화: 완료 턴(노트 인용) + 실행 중 턴.
    add("note_conv", conversation_sql(member, note=CONTEXT))
    add("note_turn", turn_sql(ids["note_conv"], member, 1, cites=CONTEXT))
    add("note_run", turn_sql(ids["note_conv"], member, 2, status="running"))
    # 문맥 없이 연 대화: 1턴이 CITED를 인용하고 2턴은 출처가 없다(가림 연쇄 확인용).
    add("cited_conv", conversation_sql(member))
    add("cited_turn", turn_sql(ids["cited_conv"], member, 1, cites=CITED))
    add("after_turn", turn_sql(ids["cited_conv"], member, 2))
    # 다른 노트(SELECTED)의 문장을 선택 문맥으로 붙인 대화.
    add("sel_conv", conversation_sql(member, selection=SELECTED))
    add("sel_turn", turn_sql(ids["sel_conv"], member, 1, cites=CONTEXT))
    # 운영자 본인의 대화: CITED 인용 완료 턴 + 실행 중 턴.
    add("op_conv", conversation_sql(operator))
    add("op_turn", turn_sql(ids["op_conv"], operator, 1, cites=CITED))
    add("op_run", turn_sql(ids["op_conv"], operator, 2, status="running"))
    local.sql("\n".join(sql))
    return ids


def snapshot(matrix):
    """MEG-69 스냅숏(제품·Auth 사용자·Storage)에 CS Agent 테이블 전체 행 값을 더한 해시."""
    queries = [f"select '{t}',coalesce(jsonb_agg(j order by j::text),'[]') from "
               f"(select to_jsonb(r) j from public.{t} r) q;" for t in AGENT_TABLES]
    agent_rows = hashlib.sha256(matrix.sql("\n".join(queries)).encode()).hexdigest()
    return matrix.snapshot(), agent_rows


def assert_404(response, label=""):
    assert response.status_code == 404, f"{label}: HTTP {response.status_code}"
    assert response.json().get("error", {}).get("code") == "not_found", label
    assert response.headers["Cache-Control"] == "private, no-store"


def call(client, endpoint, turn=None, conv=None):
    """E28~E32 한 번. E29는 Accept JSON으로 보낸다(거부는 스트림 전에 JSON 오류다)."""
    if endpoint == "E28":
        return client.get(f"/api/ai/conversations/{conv}")
    if endpoint == "E29":
        headers = {**ORIGIN, "Idempotency-Key": str(uuid4()), "Accept": "application/json"}
        return client.post(f"/api/ai/conversations/{conv}/turns", headers=headers,
                           json={"question": {"kind": "free", "text": "Synthetic denied question"}})
    if endpoint == "E30":
        return client.get(f"/api/ai/turns/{turn}")
    if endpoint == "E31":
        return client.post(f"/api/ai/turns/{turn}/cancel", headers=ORIGIN)
    if endpoint == "E32":
        return client.get(f"/api/ai/turns/{turn}/sources/1")
    raise AssertionError(endpoint)


def denied(matrix, role, checks):
    """checks: (endpoint, turn, conv) 목록. 모두 404이고 데이터·쓰기 시도가 없어야 한다."""
    before, offset = snapshot(matrix), len(matrix.calls)
    with matrix.client(role) as client:
        for endpoint, turn, conv in checks:
            assert_404(call(client, endpoint, turn=turn, conv=conv), endpoint)
    assert snapshot(matrix) == before, "Denied CS Agent request changed data"
    allowed = {"/rest/v1/rpc/rate_limit_hit", "/rest/v1/rpc/rate_limit_release"}
    writes = [(m, p) for m, p in matrix.calls[offset:] if m not in ("GET", "HEAD") and p not in allowed]
    assert not writes, f"Denied CS Agent request attempted a mutation: {writes}"


def all_paths(conv, done, running):
    return [("E28", None, conv), ("E29", None, conv), ("E30", done, None), ("E30", running, None),
            ("E31", running, None), ("E32", done, None)]


def operator_changes(matrix, note, change):
    """운영자의 실제 API로 노트를 비공개로 바꾸거나 지운다."""
    with matrix.client("operator") as client:
        if change == "private":
            response = client.patch(f"/api/admin/notes/{note}", headers=ORIGIN,
                                    json={"is_published": False, "expected_revision": 1})
            assert response.status_code == 200 and response.json()["is_published"] is False
        else:
            response = client.delete(f"/api/admin/notes/{note}", headers=ORIGIN)
            assert response.status_code == 204
            assert matrix.sql(f"select count(*) from notes where id={note};") == "0"


# --- 대조군: 주인은 자기 기록을 본다(거부 시험이 비어 있지 않음을 보인다) ---


def test_owner_sees_own_records_before_any_change(case, local):
    with local.client("member") as client:
        body = client.get(f"/api/ai/conversations/{case['note_conv']}").json()
        assert [t["status"] for t in body["turns"]] == ["completed", "running"]
        assert body["turns"][0]["result"]["sources"][0]["title"] == "MEG282 context"
        source = client.get(f"/api/ai/turns/{case['cited_turn']}/sources/1")
        assert source.status_code == 200 and source.json()["paragraph_text"] == CITED_TEXT
        assert client.get(f"/api/ai/turns/{case['note_run']}").json()["status"] == "running"
        assert client.get(f"/api/ai/conversations/{case['sel_conv']}").status_code == 200
    with local.client("operator") as client:
        assert client.get(f"/api/ai/turns/{case['op_turn']}/sources/1").json()["paragraph_text"] == CITED_TEXT


# --- 다른 사용자의 대화·턴·출처 ---


@pytest.mark.parametrize("requester,owner", [("operator", "member"), ("member", "operator")])
def test_another_users_conversation_turns_and_sources_are_404(case, local, requester, owner):
    """운영자도 남의 대화는 못 본다. 남의 실행 중 턴을 중단하지 못하고, 남의 대화에 질문하지 못한다."""
    conv, done, running = ((case["note_conv"], case["note_turn"], case["note_run"]) if owner == "member"
                           else (case["op_conv"], case["op_turn"], case["op_run"]))
    denied(local, requester, all_paths(conv, done, running))
    assert local.sql(f"select status from ai_turns where id='{running}';") == "running"


# --- 비공개·없는 노트로 대화를 열기(E27) ---


@pytest.mark.parametrize("note", [PRIVATE, MISSING], ids=["private", "missing"])
def test_member_cannot_open_a_conversation_on_a_private_or_missing_note(case, local, note):
    before, offset = snapshot(local), len(local.calls)
    with local.client("member") as client:
        response = client.post("/api/ai/conversations", headers=ORIGIN, json={
            "origin": "note", "note_id": note, "note_revision": 1, "selection": {"start": 0, "end": 8}})
    assert_404(response)
    assert snapshot(local) == before
    writes = [(m, p) for m, p in local.calls[offset:] if m not in ("GET", "HEAD") and "rate_limit" not in p]
    assert not writes


def test_member_can_open_a_conversation_on_a_public_note(case, local):
    """대조군. 같은 요청이 공개 노트에서는 201이다."""
    with local.client("member") as client:
        response = client.post("/api/ai/conversations", headers=ORIGIN, json={
            "origin": "note", "note_id": NOTE, "note_revision": 1, "selection": {"start": 0, "end": 8}})
    assert response.status_code == 201 and response.json()["note"]["note_id"] == NOTE


# --- 대화·선택 문맥의 노트를 회수(비공개·삭제) ---


@pytest.mark.parametrize("change", ["private", "deleted"])
def test_conversation_closes_when_its_note_is_revoked(case, local, change):
    operator_changes(local, CONTEXT, change)
    if change == "deleted":
        # 노트를 지우면 대화와 턴이 외래키 연쇄로 함께 지워진다(디자인 결정 3).
        assert local.sql(f"select count(*) from ai_conversations where id='{case['note_conv']}';") == "0"
    denied(local, "member", all_paths(case["note_conv"], case["note_turn"], case["note_run"]))


def test_conversation_closes_when_a_selection_note_becomes_private(case, local):
    operator_changes(local, SELECTED, "private")
    denied(local, "member", [("E28", None, case["sel_conv"]), ("E29", None, case["sel_conv"]),
                             ("E30", case["sel_turn"], None), ("E32", case["sel_turn"], None)])


# --- 인용한 출처의 권한 회수(가림) ---


@pytest.mark.parametrize("change", ["private", "deleted"])
@pytest.mark.parametrize("role", ["member", "operator"])
def test_turns_citing_a_revoked_note_are_hidden_for_every_role(case, local, role, change):
    """운영자도 비공개가 된 노트를 근거로 보지 못한다(D1, 역할 무관). 가린 턴은 결과·출처 제목·문단을 내보내지 않는다."""
    operator_changes(local, CITED, change)
    conv, turn = (case["cited_conv"], case["cited_turn"]) if role == "member" else (case["op_conv"], case["op_turn"])
    with local.client(role) as client:
        conversation = client.get(f"/api/ai/conversations/{conv}")
        single = client.get(f"/api/ai/turns/{turn}")
        source = client.get(f"/api/ai/turns/{turn}/sources/1")
    assert conversation.status_code == 200 and single.status_code == 200
    first = conversation.json()["turns"][0]
    assert first["hidden"] == {"reason": "source_revoked", "retry_allowed": True} and "result" not in first
    assert single.json()["hidden"] == first["hidden"] and "result" not in single.json()
    if role == "member":
        # 가림 연쇄: 뒤의 턴도 가리고, 다시 묻기는 첫 가림 턴에만 있다.
        assert conversation.json()["turns"][1]["hidden"] == {"reason": "source_revoked", "retry_allowed": False}
    for response in (conversation, single):
        assert CITED_TEXT not in response.text and CITED_TITLE not in response.text
    assert_404(source)


# --- 지운 대화 ---


def test_deleted_conversation_is_404_on_every_path(case, local):
    """대화를 지우면(사용자 삭제·7일 보관 정리와 같은 행 삭제) 턴과 출처 행도 사라지고 모든 경로가 404다."""
    local.sql(f"delete from ai_conversations where id='{case['note_conv']}';")
    assert local.sql(f"select count(*) from ai_turns where id='{case['note_turn']}';") == "0"
    denied(local, "member", all_paths(case["note_conv"], case["note_turn"], case["note_run"]))


# --- 검색 범위 ---


@pytest.mark.parametrize("role", ["member", "operator"])
def test_note_search_reads_only_published_notes_for_every_role(case, local, role):
    """E29가 쓰는 검색(NoteRetriever)은 실제 DB에서 공개 노트만 읽는다. 같은 문장이 든 비공개 노트는 근거가 되지 않는다."""
    user = SessionUser(user_id=local.users[role]["id"], role=role)
    paragraphs = NoteRetriever(local.db).retrieve(user, "MatrixTerm synthetic", RetrievalContext(
        conversation_id=str(uuid4()), origin="none", note_id=None, topic_label=""))
    sources = {p.source_id for p in paragraphs}
    assert str(NOTE) in sources and str(PRIVATE) not in sources
