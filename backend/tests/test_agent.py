"""CS Agent 대화·턴 읽기와 중단 E27·E28·E30·E31 (MEG-234). 가짜 Supabase로 네트워크 없이 돈다. 데이터는 모두 합성이다.

실제 래퍼의 HTTP 모양은 test_supabase_agent_client.py가, 조건부 전이·외래키 연쇄 같은 DB 규칙은
tests/integration/test_agent_read_sql.py(일회용 PostgreSQL)가 확인한다. 여기서는 spec 4절의 요청·응답·오류(AC-1),
공통 권한 검사(AC-2), 가림 함수(AC-3), 중단의 조건부 전이(AC-4), 노출 중단 플래그(AC-5)를 본다.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import agent, session
from app.agent_access import Hidden, hidden_marks, source_checker
from app.common import install_common_layer
from app.rate_limit import AI_AGENT_READ, WRITE
from app.supabase import SupabaseUnavailable, get_supabase
from support import FakeSupabase, cookie, origin

A = "00000000-0000-4000-8000-00000000000a"
B = "00000000-0000-4000-8000-00000000000b"
OP = "00000000-0000-4000-8000-00000000000c"
# 2026-11-18T06:00:00Z
NOW = 1_794_981_600
BODY = "멱등성은 같은 요청을 여러 번 보내도 결과가 한 번 보낸 것과 같은 성질이다. 재시도와 함께 쓴다."
QUESTION = "합성 질문입니다"
PUBLIC, PRIVATE, OTHER_PUBLIC, SOURCE_NOTE, MISSING = 1, 2, 3, 4, 99


def iso(seconds_from_now: float) -> str:
    return datetime.fromtimestamp(NOW + seconds_from_now, UTC).isoformat()


@dataclass
class AgentFake(FakeSupabase):
    """노트·대화·선택 문맥·턴·출처 표 흉내. 실제 래퍼와 같은 규칙(사용자 필터, 조건부 전이, 외래키 연쇄)을 따른다."""

    note_rows: dict[int, dict] = field(default_factory=dict)
    conversations: dict[str, dict] = field(default_factory=dict)
    selections: list[dict] = field(default_factory=list)
    turns: dict[str, dict] = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    selection_down: bool = False

    # --- 시험 준비 ---

    def note(self, note_id, published=True, revision=3, title="합성 노트", body=BODY):
        self.note_rows[note_id] = {"id": note_id, "revision": revision, "title": title, "is_published": published,
                                   "body_markdown": body}

    def conversation(self, user, note_id=PUBLIC, revision=3, selection_note=None, excluded=False):
        cid = str(uuid.uuid4())
        self.conversations[cid] = {
            "id": cid, "user_id": user, "origin": "note" if note_id else "none", "note_id": note_id,
            "note_revision": revision if note_id else None, "wiki_ref": None, "topic_label": "멱등성",
            "created_at": iso(-600),
        }
        if note_id or selection_note:
            self.selections.append({
                "id": str(uuid.uuid4()), "conversation_id": cid, "note_id": selection_note or note_id,
                "note_revision": revision, "start": 0, "end": 3, "text_snapshot": "멱등성",
                "excluded_at": iso(-10) if excluded else None, "created_at": iso(-600),
            })
        return cid

    def turn(self, cid, seq, status="completed", sources=(), lease=60, failure=None, step=None):
        tid = str(uuid.uuid4())
        conversation = self.conversations[cid]
        self.turns[tid] = {
            "id": tid, "conversation_id": cid, "user_id": conversation["user_id"], "seq": seq,
            "question_kind": "free", "question_text": f"{QUESTION} {seq}", "preset": None, "from_turn_id": None,
            "status": status, "failure": failure if status == "failed" else None, "step": step,
            "paragraph_count": None,
            "result": {"state": "answered", "sections": [{"body": "합성 답변 [1]"}], "suggestions": ["다음 질문"]}
            if status == "completed" else None,
            "ledger_id": 77, "model_id": "model-secret", "prompt_version": "p1", "retrieval_version": "r1",
            "lease_expires_at": iso(lease), "created_at": iso(-300 + seq),
            "finished_at": None if status == "running" else iso(-200 + seq),
        }
        for ref, (kind, source_id) in enumerate(sources, start=1):
            self.sources.append({"turn_id": tid, "ref": ref, "source_kind": kind, "source_id": source_id,
                                 "cited_revision": "3", "title": f"출처 {ref}", "section": None, "excerpt": "발췌",
                                 "paragraph_snapshot": "인용 당시 원문"})
        return tid

    def delete_note(self, note_id):
        """notes 행 삭제와 외래키 연쇄(대화·선택 문맥 on delete cascade)를 흉내 낸다. 노트 출처 행은 남는다."""
        self.note_rows.pop(note_id)
        gone = {s["conversation_id"] for s in self.selections if s["note_id"] == note_id}
        gone |= {cid for cid, c in self.conversations.items() if c["note_id"] == note_id}
        for cid in gone:
            self.conversations.pop(cid, None)
            self.selections = [s for s in self.selections if s["conversation_id"] != cid]
            for tid in [t for t, row in self.turns.items() if row["conversation_id"] == cid]:
                self.turns.pop(tid)
                self.sources = [s for s in self.sources if s["turn_id"] != tid]

    def _db(self, name):
        self.calls.append(name)
        if self.down:
            raise SupabaseUnavailable("down")

    # --- 래퍼 흉내 ---

    def get_note_for_agent(self, note_id, include_unpublished):
        self._db("get_note_for_agent")
        row = self.note_rows.get(note_id)
        if row is None or not (row["is_published"] or include_unpublished):
            return None
        return dict(row)

    def create_agent_conversation(self, fields):
        self._db("create_agent_conversation")
        if fields.get("note_id") is not None and fields["note_id"] not in self.note_rows:
            return None
        cid = str(uuid.uuid4())
        row = {"id": cid, "note_id": None, "note_revision": None, "wiki_ref": None, "created_at": iso(0), **fields}
        self.conversations[cid] = row
        return {k: row[k] for k in ("id", "user_id", "origin", "note_id", "note_revision", "wiki_ref", "topic_label",
                                     "created_at")}

    def add_agent_selection(self, fields):
        self._db("add_agent_selection")
        if self.selection_down:
            raise SupabaseUnavailable("down")
        row = {"id": str(uuid.uuid4()), "excluded_at": None, "created_at": iso(0), **fields}
        self.selections.append(row)
        return {k: v for k, v in row.items() if k != "conversation_id"}

    def delete_agent_conversation(self, user_id, conversation_id):
        self._db("delete_agent_conversation")
        if self.conversations.get(conversation_id, {}).get("user_id") == user_id:
            self.conversations.pop(conversation_id)
            self.selections = [s for s in self.selections if s["conversation_id"] != conversation_id]

    def get_agent_conversation(self, user_id, conversation_id):
        self._db("get_agent_conversation")
        row = self.conversations.get(conversation_id)
        if row is None or row["user_id"] != user_id:
            return None
        selections = [{k: v for k, v in s.items() if k != "conversation_id"}
                      for s in self.selections if s["conversation_id"] == conversation_id]
        return {**row, "ai_conversation_selections": selections}

    def get_agent_turn(self, user_id, turn_id):
        self._db("get_agent_turn")
        row = self.turns.get(turn_id)
        if row is None or row["user_id"] != user_id:
            return None
        return {k: row[k] for k in ("id", "conversation_id", "seq", "status", "question_kind", "question_text",
                                     "preset", "from_turn_id", "created_at")}

    def list_agent_turns(self, user_id, conversation_id, max_seq=None):
        self._db("list_agent_turns")
        rows = []
        for row in sorted(self.turns.values(), key=lambda r: r["seq"]):
            if row["conversation_id"] != conversation_id or row["user_id"] != user_id:
                continue
            if max_seq is not None and row["seq"] > max_seq:
                continue
            sources = sorted((dict(s) for s in self.sources if s["turn_id"] == row["id"]), key=lambda s: s["ref"])
            rows.append({**row, "ai_turn_sources": [{k: s[k] for k in ("ref", "source_kind", "source_id",
                                                                         "cited_revision", "title", "section",
                                                                         "excerpt")} for s in sources]})
        return rows

    def expire_agent_turns(self, user_id, conversation_id, lapsed_before, now_iso):
        self._db("expire_agent_turns")
        now = datetime.fromisoformat(lapsed_before.replace("Z", "+00:00"))
        count = 0
        for row in self.turns.values():
            if (row["conversation_id"] == conversation_id and row["user_id"] == user_id and row["status"] == "running"
                    and datetime.fromisoformat(row["lease_expires_at"]) <= now):
                row.update(status="failed", failure="interrupted", finished_at=now_iso)
                count += 1
        return count

    def cancel_agent_turn(self, user_id, turn_id):
        self._db("cancel_agent_turn")
        row = self.turns.get(turn_id)
        if row is None or row["user_id"] != user_id or row["status"] != "running":
            return False
        row.update(status="cancelled", finished_at=iso(0))
        return True

    def get_note_states(self, note_ids):
        self._db("get_note_states")
        return {i: {k: self.note_rows[i][k] for k in ("id", "revision", "title", "is_published")}
                for i in note_ids if i in self.note_rows}


def build_app(fake):
    app = FastAPI()
    install_common_layer(app)
    app.dependency_overrides[get_supabase] = lambda: fake
    app.include_router(agent.router)
    return app


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.delenv(agent.DISABLE_ENV, raising=False)
    monkeypatch.setattr(session, "now", lambda: NOW + 0.5)
    fake = AgentFake(now=NOW + 0.5)
    fake.add_user("a-token", A)
    fake.add_user("b-token", B)
    fake.add_user("op-token", OP, role="operator")
    fake.add_user("inactive-token", "00000000-0000-4000-8000-00000000000d", is_active=False)
    fake.note(PUBLIC)
    fake.note(PRIVATE, published=False)
    fake.note(OTHER_PUBLIC)
    fake.note(SOURCE_NOTE)
    return fake


@pytest.fixture
def client(fake):
    return TestClient(build_app(fake))


def create(client, body, token="a-token", headers=None):
    sent = {**origin(), **(cookie(token) if token else {}), **(headers or {})}
    return client.post("/api/ai/conversations", json=body, headers=sent)


def note_body(**overrides):
    return {"origin": "note", "note_id": PUBLIC, "note_revision": 3, "selection": {"start": 0, "end": 3}, **overrides}


def get(client, path, token="a-token"):
    return client.get(path, headers=cookie(token) if token else {})


def cancel(client, turn_id, token="a-token", headers=None):
    sent = {**origin(), **(cookie(token) if token else {}), **(headers or {})}
    return client.post(f"/api/ai/turns/{turn_id}/cancel", headers=sent)


def assert_error(response, status, code, detail=None):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert error.get("detail") == detail


def assert_field(response, name, reason):
    assert_error(response, 422, "validation_failed")
    assert {"name": name, "reason": reason} in [
        {"name": f["name"], "reason": f["reason"]} for f in response.json()["error"]["fields"]
    ]


# --- AC-1: E27 대화 만들기 ---


def test_a_note_conversation_stores_the_selected_text_with_its_revision_and_returns_the_conversation(client, fake):
    response = create(client, note_body(selection={"start": 0, "end": 25}))
    assert response.status_code == 201, response.text
    data = response.json()
    assert set(data) == {"conversation_id", "topic_label", "origin", "note", "context_selections", "created_at"}
    assert data["origin"] == "note"
    assert data["note"] == {"note_id": PUBLIC, "note_revision": 3, "title": "합성 노트"}
    # 주제 이름은 선택 문장의 앞 20자(Q9), 공백은 하나로 줄인다.
    assert data["topic_label"] == BODY[:20]
    [selection] = data["context_selections"]
    assert selection["note_id"] == PUBLIC and selection["note_revision"] == 3
    assert (selection["start"], selection["end"]) == (0, 25)
    assert selection["text_preview"] == BODY[:25] and selection["revision_changed"] is False
    stored = fake.selections[-1]
    assert stored["text_snapshot"] == BODY[:25] and stored["conversation_id"] == data["conversation_id"]
    assert fake.conversations[data["conversation_id"]]["user_id"] == A
    uuid.UUID(data["conversation_id"])


def test_selection_positions_are_code_points(client, fake):
    fake.note(PUBLIC, body="가나다😀라마바")
    response = create(client, note_body(selection={"start": 3, "end": 5}))
    assert response.status_code == 201, response.text
    assert fake.selections[-1]["text_snapshot"] == "😀라"


def test_an_empty_conversation_has_no_note_and_an_empty_topic(client, fake):
    response = create(client, {"origin": "none"})
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["origin"] == "none" and data["topic_label"] == "" and data["context_selections"] == []
    assert "note" not in data
    assert fake.selections == []


def test_creating_a_conversation_reads_no_ai_and_writes_only_the_conversation(client, fake):
    create(client, note_body())
    assert [c for c in fake.calls if c != "get_note_for_agent"] == ["create_agent_conversation", "add_agent_selection"]


def test_wiki_origin_is_rejected_until_t4(client, fake):
    assert_field(create(client, {"origin": "wiki", "wiki_ref": "page-1"}), "origin", "invalid_value")
    assert fake.conversations == {}


@pytest.mark.parametrize(
    "body, name, reason",
    [
        ({"origin": "note", "note_revision": 3, "selection": {"start": 0, "end": 3}}, "note_id", "required"),
        ({"origin": "note", "note_id": PUBLIC, "selection": {"start": 0, "end": 3}}, "note_revision", "required"),
        ({"origin": "note", "note_id": PUBLIC, "note_revision": 3}, "selection", "required"),
        ({"origin": "none", "note_id": PUBLIC}, "note_id", "invalid_value"),
        ({"origin": "none", "selection": {"start": 0, "end": 3}}, "selection", "invalid_value"),
        (note_body(wiki_ref="page-1"), "wiki_ref", "invalid_value"),
        (note_body(selection={"start": 3, "end": 3}), "selection.end", "out_of_range"),
        (note_body(selection={"start": 0, "end": 2001}), "selection.end", "too_long"),
        (note_body(origin="chat"), "origin", "invalid_value"),
        (note_body(note_id="1"), "note_id", "invalid_format"),
        (note_body(extra=1), "body", "invalid_format"),
    ],
)
def test_malformed_requests_are_422_before_reading_the_note(client, fake, body, name, reason):
    assert_field(create(client, body), name, reason)
    assert "get_note_for_agent" not in fake.calls and fake.conversations == {}


def test_a_selection_past_the_body_or_of_only_spaces_is_422(client, fake):
    assert_field(create(client, note_body(selection={"start": 0, "end": len(BODY) + 1})), "selection.end", "out_of_range")
    fake.note(PUBLIC, body="   본문")
    assert_field(create(client, note_body(selection={"start": 0, "end": 3})), "selection", "invalid_value")
    assert fake.conversations == {}


def test_a_changed_note_revision_is_409_stale_revision(client, fake):
    assert_error(create(client, note_body(note_revision=2)), 409, "conflict", "stale_revision")
    assert fake.conversations == {}


@pytest.mark.parametrize("note_id", [PRIVATE, MISSING])
def test_a_note_the_member_cannot_read_is_404_and_creates_nothing(client, fake, note_id):
    assert_error(create(client, note_body(note_id=note_id)), 404, "not_found")
    assert fake.conversations == {}


def test_an_operator_can_start_from_an_unpublished_note(client, fake):
    response = create(client, note_body(note_id=PRIVATE), token="op-token")
    assert response.status_code == 201, response.text


def test_creating_needs_login_and_an_allowed_origin(client, fake):
    assert_error(create(client, note_body(), token=None), 401, "login_required")
    assert_error(create(client, note_body(), token="inactive-token"), 401, "login_required")
    assert_error(create(client, note_body(), headers={"Origin": "https://evil.example"}), 403, "origin_not_allowed")
    assert fake.conversations == {}


def test_creating_counts_the_write_limit_per_user(client, fake):
    for _ in range(WRITE.limit):
        assert create(client, {"origin": "none"}).status_code == 201
    response = create(client, {"origin": "none"})
    assert_error(response, 429, "rate_limited")
    assert response.headers["Retry-After"]
    # 다른 사용자는 따로 센다.
    assert create(client, {"origin": "none"}, token="b-token").status_code == 201


def test_a_failed_selection_write_removes_the_conversation(client, fake):
    fake.selection_down = True
    assert_error(create(client, note_body()), 503, "service_unavailable")
    assert fake.conversations == {}


# --- AC-1: E28 대화 읽기 ---


def test_reading_a_conversation_returns_it_with_turns_in_order(client, fake):
    cid = fake.conversation(A)
    t1 = fake.turn(cid, 1, sources=[("note", str(SOURCE_NOTE))])
    t2 = fake.turn(cid, 2, status="cancelled")
    t3 = fake.turn(cid, 3, status="failed", failure="error")
    t4 = fake.turn(cid, 4, status="running", step="retrieve")
    response = get(client, f"/api/ai/conversations/{cid}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["conversation_id"] == cid and data["note"]["note_id"] == PUBLIC
    assert [t["turn_id"] for t in data["turns"]] == [t1, t2, t3, t4]
    first, cancelled, failed, running = data["turns"]
    assert first["status"] == "completed" and first["question"] == {"kind": "free", "text": f"{QUESTION} 1"}
    assert first["result"]["state"] == "answered"
    assert first["result"]["sources"] == [{"ref": 1, "title": "출처 1", "cited_revision": "3", "excerpt": "발췌"}]
    assert "hidden" not in first and "finished_at" in first
    assert "result" not in cancelled and cancelled["status"] == "cancelled"
    assert failed["failure"] == "error" and "result" not in failed
    assert running["status"] == "running" and running["step"] == "retrieve" and "finished_at" not in running
    # 내부 열은 내보내지 않는다(spec 2절).
    text = response.text
    for secret in ("ledger_id", "model-secret", "prompt_version", "retrieval_version", "lease_expires_at",
                   "paragraph_snapshot", "인용 당시 원문", "source_kind", "user_id"):
        assert secret not in text


def test_excluded_selections_are_not_in_the_current_context(client, fake):
    cid = fake.conversation(A, excluded=True)
    assert get(client, f"/api/ai/conversations/{cid}").json()["context_selections"] == []


def test_a_selection_on_a_changed_note_revision_is_marked(client, fake):
    cid = fake.conversation(A)
    fake.note_rows[PUBLIC]["revision"] = 4
    data = get(client, f"/api/ai/conversations/{cid}").json()
    assert data["context_selections"][0]["revision_changed"] is True
    assert data["note"]["note_revision"] == 3


def test_an_expired_running_turn_is_read_as_interrupted(client, fake):
    cid = fake.conversation(A)
    expired = fake.turn(cid, 1, status="running", lease=-10)
    data = get(client, f"/api/ai/conversations/{cid}").json()
    assert data["turns"][0]["status"] == "failed" and data["turns"][0]["failure"] == "interrupted"
    assert fake.turns[expired]["status"] == "failed"


def test_a_lease_just_past_within_the_clock_grace_stays_running(client, fake):
    cid = fake.conversation(A)
    live = fake.turn(cid, 1, status="running", lease=-2)
    assert get(client, f"/api/ai/conversations/{cid}").json()["turns"][0]["status"] == "running"
    assert fake.turns[live]["status"] == "running" and "expire_agent_turns" not in fake.calls


def test_reads_do_not_write_when_nothing_has_expired(client, fake):
    cid = fake.conversation(A)
    tid = fake.turn(cid, 1)
    fake.turn(cid, 2, status="running", lease=30)
    get(client, f"/api/ai/conversations/{cid}")
    get(client, f"/api/ai/turns/{tid}")
    assert "expire_agent_turns" not in fake.calls


def test_sources_stored_inside_the_result_are_not_trusted(client, fake):
    cid = fake.conversation(A)
    tid = fake.turn(cid, 1)
    fake.turns[tid]["result"]["sources"] = [{"ref": 1, "title": "검증 안 된 출처"}]
    data = get(client, f"/api/ai/turns/{tid}").json()
    assert "sources" not in data["result"] and "검증 안 된 출처" not in str(data)


def test_a_malformed_stored_result_is_left_out_without_failing_the_conversation(client, fake):
    cid = fake.conversation(A)
    bad = fake.turn(cid, 1)
    fake.turn(cid, 2)
    fake.turns[bad]["result"] = ["not", "an", "object"]
    response = get(client, f"/api/ai/conversations/{cid}")
    assert response.status_code == 200
    first, second = response.json()["turns"]
    assert "result" not in first and second["result"]["state"] == "answered"


def test_a_running_turn_within_its_lease_stays_running(client, fake):
    cid = fake.conversation(A)
    live = fake.turn(cid, 1, status="running", lease=30)
    assert get(client, f"/api/ai/conversations/{cid}").json()["turns"][0]["status"] == "running"
    assert fake.turns[live]["status"] == "running"


# --- AC-2: 공통 권한 검사 ---


def test_another_users_missing_or_malformed_conversation_is_404(client, fake):
    cid = fake.conversation(A)
    assert_error(get(client, f"/api/ai/conversations/{cid}", token="b-token"), 404, "not_found")
    assert_error(get(client, f"/api/ai/conversations/{uuid.uuid4()}"), 404, "not_found")
    assert_error(get(client, "/api/ai/conversations/12"), 404, "not_found")
    # 모양이 틀린 id는 DB를 읽지 않는다.
    assert fake.calls.count("get_agent_conversation") == 2


def test_reading_needs_login(client, fake):
    cid = fake.conversation(A)
    assert_error(get(client, f"/api/ai/conversations/{cid}", token=None), 401, "login_required")


def test_a_conversation_whose_note_became_private_is_404_for_members_only(client, fake):
    cid = fake.conversation(A)
    tid = fake.turn(cid, 1, status="running")
    fake.note_rows[PUBLIC]["is_published"] = False
    assert_error(get(client, f"/api/ai/conversations/{cid}"), 404, "not_found")
    assert_error(get(client, f"/api/ai/turns/{tid}"), 404, "not_found")
    assert_error(cancel(client, tid), 404, "not_found")
    assert fake.turns[tid]["status"] == "running"
    # 운영자는 비공개 노트를 읽을 수 있으므로(E05와 같다) 자기 대화가 열린다.
    op_cid = fake.conversation(OP)
    assert get(client, f"/api/ai/conversations/{op_cid}", token="op-token").status_code == 200


def test_a_conversation_whose_selection_note_became_private_is_404(client, fake):
    cid = fake.conversation(A, selection_note=OTHER_PUBLIC)
    fake.note_rows[OTHER_PUBLIC]["is_published"] = False
    assert_error(get(client, f"/api/ai/conversations/{cid}"), 404, "not_found")


def test_an_excluded_selection_on_a_private_note_still_closes_the_conversation(client, fake):
    cid = fake.conversation(A, selection_note=OTHER_PUBLIC, excluded=True)
    fake.note_rows[OTHER_PUBLIC]["is_published"] = False
    assert_error(get(client, f"/api/ai/conversations/{cid}"), 404, "not_found")


def test_a_conversation_whose_note_was_deleted_is_404(client, fake):
    cid = fake.conversation(A)
    tid = fake.turn(cid, 1)
    fake.delete_note(PUBLIC)
    assert_error(get(client, f"/api/ai/conversations/{cid}"), 404, "not_found")
    assert_error(get(client, f"/api/ai/turns/{tid}"), 404, "not_found")


def test_a_missing_note_row_closes_the_conversation_even_without_the_cascade(client, fake):
    cid = fake.conversation(A)
    fake.note_rows.pop(PUBLIC)
    assert_error(get(client, f"/api/ai/conversations/{cid}"), 404, "not_found")


def test_a_wiki_conversation_is_closed_until_t4(client, fake):
    cid = fake.conversation(A, note_id=None)
    fake.conversations[cid].update(origin="wiki", wiki_ref="page-1")
    assert_error(get(client, f"/api/ai/conversations/{cid}"), 404, "not_found")


# --- AC-1: E30 턴 읽기 ---


def test_reading_a_turn_returns_the_same_shape_as_in_the_conversation(client, fake):
    cid = fake.conversation(A)
    tid = fake.turn(cid, 1, sources=[("note", str(SOURCE_NOTE))])
    single = get(client, f"/api/ai/turns/{tid}")
    assert single.status_code == 200, single.text
    listed = get(client, f"/api/ai/conversations/{cid}").json()["turns"][0]
    assert single.json() == listed
    assert "retry_after_seconds" not in single.json()


def test_a_running_turn_tells_when_to_poll_again(client, fake):
    cid = fake.conversation(A)
    tid = fake.turn(cid, 1, status="running")
    data = get(client, f"/api/ai/turns/{tid}").json()
    assert data["status"] == "running" and data["retry_after_seconds"] == 2


def test_an_expired_turn_is_interrupted_when_read_directly(client, fake):
    cid = fake.conversation(A)
    tid = fake.turn(cid, 1, status="running", lease=-10)
    data = get(client, f"/api/ai/turns/{tid}").json()
    assert data["status"] == "failed" and data["failure"] == "interrupted" and "retry_after_seconds" not in data


def test_another_users_or_missing_turn_is_404(client, fake):
    tid = fake.turn(fake.conversation(A), 1)
    assert_error(get(client, f"/api/ai/turns/{tid}", token="b-token"), 404, "not_found")
    assert_error(get(client, f"/api/ai/turns/{uuid.uuid4()}"), 404, "not_found")
    assert_error(get(client, "/api/ai/turns/not-a-uuid"), 404, "not_found")


def test_reads_count_the_read_limit_before_touching_the_conversation(client, fake):
    tid = fake.turn(fake.conversation(A), 1)
    for _ in range(AI_AGENT_READ.limit):
        assert get(client, f"/api/ai/turns/{tid}").status_code == 200
    reads = fake.calls.count("get_agent_turn")
    assert_error(get(client, f"/api/ai/turns/{tid}"), 429, "rate_limited")
    assert_error(get(client, f"/api/ai/turns/{uuid.uuid4()}"), 429, "rate_limited")
    assert fake.calls.count("get_agent_turn") == reads


# --- AC-3: 가림 ---


def three_turns(fake, user=A, revoked_kind="note"):
    cid = fake.conversation(user)
    t1 = fake.turn(cid, 1, sources=[("note", str(OTHER_PUBLIC))])
    t2 = fake.turn(cid, 2, sources=[("note", str(SOURCE_NOTE)), ("note", str(OTHER_PUBLIC))])
    t3 = fake.turn(cid, 3)
    return cid, t1, t2, t3


@pytest.mark.parametrize("revoke", ["private", "deleted"])
def test_turns_from_the_first_one_citing_a_revoked_note_are_hidden(client, fake, revoke):
    cid, t1, t2, t3 = three_turns(fake)
    if revoke == "private":
        fake.note_rows[SOURCE_NOTE]["is_published"] = False
    else:
        fake.note_rows.pop(SOURCE_NOTE)
    turns = get(client, f"/api/ai/conversations/{cid}").json()["turns"]
    assert "hidden" not in turns[0] and turns[0]["result"]["state"] == "answered"
    assert turns[1]["hidden"] == {"reason": "source_revoked", "retry_allowed": True}
    assert turns[2]["hidden"] == {"reason": "source_revoked", "retry_allowed": False}
    for turn in turns[1:]:
        # 결과(추천 질문 포함)는 빼고 질문은 남긴다.
        assert "result" not in turn and turn["question"]["text"]
    assert "다음 질문" not in str(turns[1:])
    # E30도 같은 가림 함수를 거친다.
    assert get(client, f"/api/ai/turns/{t1}").json() == turns[0]
    assert get(client, f"/api/ai/turns/{t2}").json() == turns[1]
    assert get(client, f"/api/ai/turns/{t3}").json() == turns[2]


def test_a_hidden_suggested_question_drops_its_model_written_text(client, fake):
    cid, t1, t2, t3 = three_turns(fake)
    fake.turns[t3].update(question_kind="suggested", from_turn_id=t2)
    fake.note_rows[SOURCE_NOTE]["is_published"] = False
    hidden = get(client, f"/api/ai/turns/{t3}").json()
    assert hidden["question"] == {"kind": "suggested", "from_turn_id": t2}
    # 가리지 않은 추천 질문은 문구를 그대로 준다.
    fake.note_rows[SOURCE_NOTE]["is_published"] = True
    assert get(client, f"/api/ai/turns/{t3}").json()["question"]["text"] == f"{QUESTION} 3"


def test_a_note_deleted_between_the_check_and_the_insert_is_404(client, fake):
    original = fake.get_note_for_agent

    def read_then_delete(note_id, include_unpublished):
        row = original(note_id, include_unpublished)
        fake.note_rows.pop(note_id)
        return row

    fake.get_note_for_agent = read_then_delete
    assert_error(create(client, note_body()), 404, "not_found")
    assert fake.conversations == {}


def test_a_private_source_note_is_hidden_even_for_an_operator(client, fake):
    cid, _, _, _ = three_turns(fake, user=OP)
    fake.note_rows[SOURCE_NOTE]["is_published"] = False
    turns = get(client, f"/api/ai/conversations/{cid}", token="op-token").json()["turns"]
    assert [("hidden" in t) for t in turns] == [False, True, True]


def test_a_republished_source_note_shows_the_turns_again(client, fake):
    cid, *_ = three_turns(fake)
    fake.note_rows[SOURCE_NOTE]["is_published"] = False
    assert "hidden" in get(client, f"/api/ai/conversations/{cid}").json()["turns"][1]
    fake.note_rows[SOURCE_NOTE]["is_published"] = True
    assert all("hidden" not in t for t in get(client, f"/api/ai/conversations/{cid}").json()["turns"])


def test_a_retry_turn_and_the_turns_after_it_are_shown_again(client, fake):
    """2026-11-18 결정: 첫 가림 턴의 다시 묻기 턴부터는 각자의 출처로 판정한다. 첫 가림 턴의 다시 묻기는 한 번만이다."""
    cid, t1, t2, t3 = three_turns(fake)
    retry = fake.turn(cid, 4, sources=[("note", str(OTHER_PUBLIC))])
    fake.turns[retry]["retry_of_turn_id"] = t2
    after = fake.turn(cid, 5)
    fake.note_rows[SOURCE_NOTE]["is_published"] = False
    turns = get(client, f"/api/ai/conversations/{cid}").json()["turns"]
    assert [t.get("hidden") for t in turns] == [
        None,
        {"reason": "source_revoked", "retry_allowed": False},
        {"reason": "source_revoked", "retry_allowed": False},
        None,
        None,
    ]
    assert turns[3]["result"]["state"] == "answered" and turns[4]["turn_id"] == after
    # E30도 같은 판정이다. 첫 가림 턴(t2)의 retry_allowed는 뒤의 다시 묻기 턴을 보고 정하므로 E30도 뒤 턴까지 읽어야 한다.
    assert get(client, f"/api/ai/turns/{retry}").json() == turns[3]
    assert get(client, f"/api/ai/turns/{t3}").json() == turns[2]
    assert get(client, f"/api/ai/turns/{t2}").json() == turns[1]


def test_hidden_marks_rules():
    visible = source_checker({5: {"is_published": True}, 6: {"is_published": False}})
    turns = [
        {"id": "a", "seq": 1, "ai_turn_sources": [{"source_kind": "note", "source_id": "5"}]},
        {"id": "b", "seq": 2, "ai_turn_sources": []},
        {"id": "c", "seq": 3, "ai_turn_sources": [{"source_kind": "wiki", "source_id": "w"}]},
        {"id": "d", "seq": 4, "ai_turn_sources": [{"source_kind": "note", "source_id": "5"}]},
    ]
    marks = hidden_marks(turns, visible)
    assert marks == {"a": None, "b": None, "c": Hidden("source_revoked", True), "d": Hidden("source_revoked", False)}
    # 모양이 틀린 노트 id, 없는 노트, 비공개 노트는 모두 볼 수 없는 출처다.
    for source_id in ("05", "x", "7", "6", "99999999999999999999"):
        assert visible({"source_kind": "note", "source_id": source_id}) is False


# --- AC-4: E31 중단 ---


def test_cancelling_a_running_turn_returns_the_question(client, fake):
    cid = fake.conversation(A)
    tid = fake.turn(cid, 1, status="running")
    response = cancel(client, tid)
    assert response.status_code == 200, response.text
    assert response.json() == {"turn_id": tid, "status": "cancelled", "question": {"kind": "free", "text": f"{QUESTION} 1"}}
    assert fake.turns[tid]["status"] == "cancelled" and fake.turns[tid]["result"] is None
    assert get(client, f"/api/ai/turns/{tid}").json()["status"] == "cancelled"


@pytest.mark.parametrize("status", ["completed", "cancelled", "failed"])
def test_a_finished_turn_is_not_cancelled(client, fake, status):
    tid = fake.turn(fake.conversation(A), 1, status=status, failure="error")
    before = dict(fake.turns[tid])
    assert_error(cancel(client, tid), 409, "conflict", "turn_not_cancellable")
    assert fake.turns[tid] == before


def test_an_expired_running_turn_becomes_interrupted_instead_of_cancelled(client, fake):
    tid = fake.turn(fake.conversation(A), 1, status="running", lease=-10)
    assert_error(cancel(client, tid), 409, "conflict", "turn_not_cancellable")
    assert fake.turns[tid]["status"] == "failed" and fake.turns[tid]["failure"] == "interrupted"


def test_cancelling_another_users_or_missing_turn_is_404(client, fake):
    tid = fake.turn(fake.conversation(A), 1, status="running")
    assert_error(cancel(client, tid, token="b-token"), 404, "not_found")
    assert_error(cancel(client, str(uuid.uuid4())), 404, "not_found")
    assert_error(cancel(client, "1"), 404, "not_found")
    assert fake.turns[tid]["status"] == "running"


def test_cancelling_needs_login_and_an_allowed_origin(client, fake):
    tid = fake.turn(fake.conversation(A), 1, status="running")
    assert_error(cancel(client, tid, token=None), 401, "login_required")
    assert_error(cancel(client, tid, headers={"Origin": "https://evil.example"}), 403, "origin_not_allowed")
    assert fake.turns[tid]["status"] == "running"


def test_a_turn_that_vanished_while_cancelling_is_404(client, fake):
    tid = fake.turn(fake.conversation(A), 1, status="running")
    original = fake.cancel_agent_turn

    def vanish(user_id, turn_id):
        fake.turns.pop(turn_id)
        return original(user_id, turn_id)

    fake.cancel_agent_turn = vanish
    assert_error(cancel(client, tid), 404, "not_found")


# --- AC-5: 노출 중단 플래그 ---


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "unexpected"])
def test_the_exposure_flag_stops_new_conversations_but_not_reads_or_cancel(client, fake, monkeypatch, value):
    cid = fake.conversation(A)
    done = fake.turn(cid, 1)
    running = fake.turn(cid, 2, status="running")
    monkeypatch.setenv(agent.DISABLE_ENV, value)
    assert_error(create(client, note_body()), 503, "service_unavailable")
    assert_error(create(client, {"origin": "none"}), 503, "service_unavailable")
    assert len(fake.conversations) == 1 and "get_note_for_agent" not in fake.calls
    assert get(client, f"/api/ai/conversations/{cid}").status_code == 200
    assert get(client, f"/api/ai/turns/{done}").status_code == 200
    assert cancel(client, running).status_code == 200


@pytest.mark.parametrize("value", ["", "0", "false", "No", " off "])
def test_off_values_keep_the_feature_open(client, fake, monkeypatch, value):
    monkeypatch.setenv(agent.DISABLE_ENV, value)
    assert create(client, {"origin": "none"}).status_code == 201


# --- 로그 ---


def test_logs_keep_ids_and_codes_but_no_question_answer_or_note_text(client, fake, caplog):
    cid = fake.conversation(A)
    tid = fake.turn(cid, 1, status="running")
    fake.turn(cid, 0, status="running", lease=-10)
    caplog.set_level(logging.INFO, logger="app")
    create(client, note_body(selection={"start": 0, "end": 25}))
    get(client, f"/api/ai/conversations/{cid}")
    cancel(client, tid)
    text = caplog.text
    assert "stage=cancel" in text and tid in text
    for secret in (QUESTION, "합성 답변", BODY[:10], "멱등성"):
        assert secret not in text
