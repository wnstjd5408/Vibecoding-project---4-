"""노트 용어 질문의 퀴즈 자료 (MEG-243). E29 안에서 E09 저장 경로를 돌려 공유 설명과 열람 기록을 만든다.

가짜 Supabase·가짜 원장·가짜 Bedrock으로 네트워크 없이 돈다. 모델은 부르지 않고 데이터는 모두 합성이다.
SQL 함수(ai_store_explanation·term_views 기본 키)는 tests/integration이 실제 PostgreSQL로 확인한다.

AC-1 새 용어: explain 원장 1건과 설명·용어·열람 기록, 턴 응답에는 없음. AC-2 사전·캐시 용어: explain 0회, 열람만.
AC-3 용어가 아닌 선택·origin none: 아무것도 바뀌지 않음. AC-4 비공개 노트: 저장 없음. AC-5 실패와 한도: 턴 결과가 같음.
그 밖에 실행 순서(agent 정산 뒤 explain 예약), 같은 키 재생, 마지막 이벤트 뒤 delayed 없음, 시간 초과, 로그를 본다.
"""

import logging
import time
import uuid

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from test_agent import BODY, NOW, OP, PRIVATE, PUBLIC, SOURCE_NOTE, A
from test_agent_turns import (
    PARAGRAPHS,
    QUESTION,
    AgentStore,
    TurnFake,
    answer_json,
    ask,
    bedrock_reply,
    build_app,
    events,
    names,
)

from app import agent_quiz_material, agent_turns
from app.agent_retrieval import FixedRetriever
from app.ai_ledger import CALL_SPECS, KIND_AGENT, KIND_EXPLAIN, AiLimitReached, LedgerKeyExists
from app.glossary import study_date
from app.glossary_spans import normalize_key
from app.supabase import SupabaseUnavailable

TERM = "멱등성"
KEY = normalize_key(TERM)
EXPLAIN_TEXT = "합성 공유 설명입니다."


def _kst_today() -> str:
    return study_date()


class QuizFake(TurnFake):
    """TurnFake에 E09 저장 경로의 래퍼(노트 읽기, 용어 읽기, 설명 저장)를 더한다. SQL 함수와 같은 결과 모양이다."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # key -> {id, key, label, source, glossary_entries, explanations}
        self.terms: dict[str, dict] = {}
        self.next_term_id = 100
        self.next_explanation_id = 500
        self.store_calls: list[dict] = []
        self.store_outcome: str | None = None
        self.store_down = False
        self.find_error: Exception | None = None

    def add_term(self, label, *, glossary=False, explanation=None):
        key = normalize_key(label)
        term = {"id": self.next_term_id, "key": key, "label": label, "source": "glossary" if glossary else "ai",
                "glossary_entries": {"body_markdown": "사전 설명"} if glossary else None, "explanations": []}
        self.next_term_id += 1
        if explanation:
            term["explanations"].append({"id": self.next_explanation_id, "body": explanation,
                                         "review_status": "approved"})
            self.next_explanation_id += 1
        self.terms[key] = term
        if glossary:
            self.glossary.append({"id": term["id"], "key": key, "label": label})
        else:
            self.ai_terms.add(term["id"])
        return term

    def get_note_for_explain(self, note_id, include_unpublished):
        self._db("get_note_for_explain")
        row = self.note_rows.get(note_id)
        if row is None or not (row["is_published"] or include_unpublished):
            return None
        return {k: row[k] for k in ("id", "revision", "is_published", "body_markdown")}

    def find_term_for_explain(self, key, user_id):
        self._db("find_term_for_explain")
        if self.find_error is not None:
            raise self.find_error
        term = self.terms.get(key)
        if term is None:
            return None
        return {"id": term["id"], "key": term["key"], "label": term["label"], "source": term["source"],
                "glossary_entries": term["glossary_entries"], "glossary_images": [],
                "ai_explanations": list(term["explanations"]), "favorites": []}

    def store_ai_explanation(self, **arguments):
        self._db("store_ai_explanation")
        self.store_calls.append(arguments)
        if self.store_down:
            raise SupabaseUnavailable("status 503")
        note = self.note_rows.get(arguments["note_id"])
        if (self.store_outcome == "one_off" or note is None or not note["is_published"]
                or note["revision"] != arguments["note_revision"]):
            return {"outcome": "one_off", "term_id": None, "explanation_id": None, "body": None, "review_status": None}
        term = self.terms.get(arguments["term_key"])
        if term is not None and term["glossary_entries"] is not None:
            return {"outcome": "glossary", "term_id": term["id"], "explanation_id": None, "body": None,
                    "review_status": None}
        if term is None:
            term = self.add_term(arguments["term_label"])
        if term["explanations"]:
            existing = term["explanations"][0]
            return {"outcome": "existing", "term_id": term["id"], "explanation_id": existing["id"],
                    "body": existing["body"], "review_status": existing["review_status"]}
        explanation = {"id": self.next_explanation_id, "body": arguments["body"], "review_status": "pending"}
        self.next_explanation_id += 1
        term["explanations"].append(explanation)
        return {"outcome": "stored", "term_id": term["id"], "explanation_id": explanation["id"],
                "body": explanation["body"], "review_status": "pending"}


class MixedBedrock:
    """agent 호출(출력 1,500토큰)과 explain 호출(600토큰)을 구분해 기록하고 각각 정해 둔 답을 준다."""

    def __init__(self):
        self.log: list[tuple[str, str]] = []
        self.explain_steps: list = []
        self.agent_steps: list = []
        self.explain_delay = 0.0

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.log]

    def converse(self, **kwargs):
        prompt = kwargs["messages"][0]["content"][0]["text"]
        # 호출 설정(출력 상한)으로 agent와 explain을 가른다. 값은 CALL_SPECS를 따른다(MEG-282에서 agent 상한이 바뀜).
        kind = {CALL_SPECS[KIND_AGENT].max_tokens: "agent", CALL_SPECS[KIND_EXPLAIN].max_tokens: "explain"}[
            kwargs["inferenceConfig"]["maxTokens"]
        ]
        self.log.append((kind, prompt))
        if kind == "agent":
            step = self.agent_steps.pop(0) if self.agent_steps else bedrock_reply(answer_json())
            if isinstance(step, Exception):
                raise step
            return step
        if self.explain_delay:
            time.sleep(self.explain_delay)
        step = self.explain_steps.pop(0) if self.explain_steps else bedrock_reply(EXPLAIN_TEXT)
        if isinstance(step, Exception):
            raise step
        return step


class OrderedStore(AgentStore):
    """예약·정산 순서를 한 목록에 남긴다. limit_kinds에 든 kind는 예약에서 한도에 걸린다."""

    def __init__(self):
        super().__init__()
        self.log: list[tuple] = []
        self.limit_kinds: set[str] = set()
        self.exists_kinds: set[str] = set()

    def reserve(self, **kwargs):
        if kwargs["kind"] in self.limit_kinds:
            raise AiLimitReached()
        if kwargs["kind"] in self.exists_kinds:
            raise LedgerKeyExists("reserved")
        reservation = super().reserve(**kwargs)
        self.log.append(("reserve", kwargs["kind"]))
        return reservation

    def settle(self, ledger_id, outcome, **values):
        self.log.append(("settle", ledger_id))
        return super().settle(ledger_id, outcome, **values)


@pytest.fixture
def fake(monkeypatch):
    from app import agent, session

    monkeypatch.delenv(agent.DISABLE_ENV, raising=False)
    for name in ("VERCEL", "VERCEL_ENV", "VERCEL_TARGET_ENV", "VERCEL_GIT_COMMIT_REF"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(session, "now", lambda: NOW + 0.5)
    fake = QuizFake(now=NOW + 0.5)
    fake.add_user("a-token", A)
    fake.add_user("op-token", OP, role="operator")
    fake.note(PUBLIC)
    fake.note(PRIVATE, published=False)
    fake.note(SOURCE_NOTE)
    return fake


@pytest.fixture
def store():
    return OrderedStore()


@pytest.fixture
def bedrock():
    return MixedBedrock()


@pytest.fixture
def client(fake, store, bedrock):
    return TestClient(build_app(fake, store, bedrock, FixedRetriever(PARAGRAPHS)))


def untouched(fake, store, bedrock):
    """퀴즈 자료 쪽에서 아무것도 바뀌지 않았다: explain 호출·예약 0, 저장 0, 열람 0."""
    assert "explain" not in bedrock.kinds()
    assert [r for r in store.reserves if r["kind"] == "explain"] == []
    assert fake.store_calls == [] and fake.term_views == set()


# --- AC-1: 새 용어면 공유 설명·용어·열람 기록이 한 건씩 생긴다 ---


def test_a_new_term_creates_one_shared_explanation_and_a_view_without_touching_the_turn(client, fake, store, bedrock):
    cid = fake.conversation(A)
    key = str(uuid.uuid4())
    response = ask(client, cid, key=key)
    parsed = events(response)

    # 턴 이벤트는 퀴즈 자료가 없을 때와 같다. 설명 본문은 응답 어디에도 없다.
    assert names(parsed) == ["turn", "step", "step", "step", "step", "step", "step", "result"]
    assert parsed[-1][1]["status"] == "completed"
    assert EXPLAIN_TEXT not in response.text
    assert all(EXPLAIN_TEXT not in str(finish) for finish in fake.finishes)

    # 원장: agent 예약·정산이 끝난 뒤 explain을 예약한다(같은 턴의 agent 호출이 한도에 걸리지 않게).
    assert store.reserves == [
        {"kind": "agent", "key": f"{A}:agent:{key}:1", "daily_count_limit": 20},
        {"kind": "explain", "key": f"{A}:agent-explain:{key}:1", "daily_count_limit": 20},
    ]
    assert store.log == [("reserve", "agent"), ("settle", 101), ("reserve", "explain"), ("settle", 102)]
    assert bedrock.kinds() == ["agent", "explain"]

    # 저장: 공개 노트, 저장한 개정, 서버가 자른 용어. terms(source='ai')와 ai_explanations가 한 건씩 생긴다.
    [stored] = fake.store_calls
    assert (stored["note_id"], stored["note_revision"], stored["term_key"], stored["term_label"]) == (
        PUBLIC, 3, KEY, TERM)
    assert stored["body"] == EXPLAIN_TEXT and stored["prompt_version"] == "explain-v1"
    term = fake.terms[KEY]
    assert term["source"] == "ai" and [e["body"] for e in term["explanations"]] == [EXPLAIN_TEXT]
    assert fake.term_views == {(A, term["id"], _kst_today())}


def test_the_explain_prompt_has_only_the_term_and_the_note_sentence(client, fake, bedrock):
    cid = fake.conversation(A)
    events(ask(client, cid, body={"question": {"kind": "free", "text": "비밀 질문 문구입니다"}}))
    [(_, prompt)] = [entry for entry in bedrock.log if entry[0] == "explain"]
    assert f"용어: {TERM}" in prompt
    assert "노트 문장: 멱등성은 같은 요청을 여러 번 보내도 결과가 한 번 보낸 것과 같은 성질이다." in prompt
    # 질문, 근거 문단, 사용자 식별 정보는 넣지 않는다.
    assert "비밀 질문 문구입니다" not in prompt and PARAGRAPHS[1].text not in prompt and A not in prompt


def test_json_mode_also_creates_material_and_the_json_has_no_explanation(client, fake, bedrock):
    cid = fake.conversation(A)
    response = ask(client, cid, accept="application/json")
    assert response.status_code == 200 and response.json()["status"] == "completed"
    assert EXPLAIN_TEXT not in response.text
    assert bedrock.kinds() == ["agent", "explain"] and fake.terms[KEY]["explanations"]


# --- AC-2: 사전 용어·캐시 용어는 AI 없이 열람만 ---


@pytest.mark.parametrize("glossary", [True, False], ids=["glossary", "cached_ai"])
def test_a_known_term_records_only_a_view(client, fake, store, bedrock, glossary):
    term = fake.add_term(TERM, glossary=glossary, explanation=None if glossary else "이미 있는 설명")
    cid = fake.conversation(A)
    events(ask(client, cid))
    assert bedrock.kinds() == ["agent"]
    assert [r["kind"] for r in store.reserves] == ["agent"]
    assert fake.store_calls == []
    assert fake.term_views == {(A, term["id"], _kst_today())}


def test_asking_the_same_term_again_reuses_the_shared_explanation(client, fake, store, bedrock):
    cid = fake.conversation(A)
    events(ask(client, cid))
    events(ask(client, cid, body={"question": {"kind": "preset", "preset": "simple"}}))
    assert bedrock.kinds() == ["agent", "explain", "agent"]
    assert [r["kind"] for r in store.reserves] == ["agent", "explain", "agent"]
    assert len(fake.store_calls) == 1
    # 같은 날 열람 기록은 기본 키 때문에 한 건이다.
    assert fake.term_views == {(A, fake.terms[KEY]["id"], _kst_today())}


def test_a_failed_first_turn_still_creates_material_on_the_next_turn(client, fake, store, bedrock):
    cid = fake.conversation(A)
    store.limit_kinds = {"explain"}
    events(ask(client, cid))
    assert fake.store_calls == []
    store.limit_kinds = set()
    events(ask(client, cid))
    assert fake.terms[KEY]["explanations"] and len(fake.term_views) == 1


# --- AC-3: 용어 하나가 아니면 아무것도 바꾸지 않는다 ---


def _sentence(fake, cid):
    # 80자를 넘는 선택은 문장이다(E09 규칙). 노트를 길게 바꾸고 전체를 고른다. 개정은 그대로 둔다.
    long_body = f"{BODY} {BODY}"
    assert len(long_body) > 80
    fake.note_rows[PUBLIC]["body_markdown"] = long_body
    fake.selections[-1].update(start=0, end=len(long_body), text_snapshot=long_body)


def _punctuation(fake, cid):
    # 글자·숫자가 없는 선택(마침표 하나)은 용어가 아니다.
    start = BODY.index(".")
    fake.selections[-1].update(start=start, end=start + 1, text_snapshot=".")


def _stale(fake, cid):
    # 대화를 연 뒤 노트가 바뀌었다. 저장한 위치가 다른 글자를 가리킬 수 있다.
    fake.note_rows[PUBLIC]["revision"] = 4


@pytest.mark.parametrize("change", [_sentence, _punctuation, _stale], ids=["sentence", "punctuation", "stale_revision"])
def test_a_selection_that_is_not_one_term_changes_nothing(client, fake, store, bedrock, change):
    cid = fake.conversation(A)
    change(fake, cid)
    parsed = events(ask(client, cid))
    assert parsed[-1][1]["status"] == "completed"
    untouched(fake, store, bedrock)


def test_two_selections_change_nothing(client, fake, store, bedrock):
    cid = fake.conversation(A)
    body = {"question": {"kind": "free", "text": QUESTION},
            "add_selections": [{"note_id": PUBLIC, "note_revision": 3, "start": 5, "end": 7}]}
    events(ask(client, cid, body=body))
    untouched(fake, store, bedrock)


def test_an_excluded_selection_changes_nothing(client, fake, store, bedrock):
    cid = fake.conversation(A)
    body = {"question": {"kind": "free", "text": QUESTION}, "exclude_selection_ids": [fake.selections[-1]["id"]]}
    events(ask(client, cid, body=body))
    untouched(fake, store, bedrock)


def test_an_added_single_term_counts_when_the_first_selection_is_excluded(client, fake, store, bedrock):
    cid = fake.conversation(A)
    start = BODY.index("재시도")
    body = {"question": {"kind": "free", "text": QUESTION}, "exclude_selection_ids": [fake.selections[-1]["id"]],
            "add_selections": [{"note_id": PUBLIC, "note_revision": 3, "start": start, "end": start + 3}]}
    events(ask(client, cid, body=body))
    assert [call["term_label"] for call in fake.store_calls] == ["재시도"]


def test_an_origin_none_conversation_changes_nothing(client, fake, store, bedrock):
    cid = fake.conversation(A, note_id=None)
    events(ask(client, cid))
    untouched(fake, store, bedrock)


# --- AC-4: 비공개 노트의 사전 밖 용어는 AI를 부르지 않는다 ---


def test_a_private_note_unknown_term_does_not_call_ai_or_store(client, fake, store, bedrock):
    cid = fake.conversation(OP, note_id=PRIVATE)
    parsed = events(ask(client, cid, token="op-token"))
    assert parsed[-1][1]["status"] == "completed"
    untouched(fake, store, bedrock)


def test_a_private_note_glossary_term_records_a_view(client, fake, store, bedrock):
    term = fake.add_term(TERM, glossary=True)
    cid = fake.conversation(OP, note_id=PRIVATE)
    events(ask(client, cid, token="op-token"))
    assert bedrock.kinds() == ["agent"] and fake.store_calls == []
    assert fake.term_views == {(OP, term["id"], _kst_today())}


# --- AC-5: 실패와 한도 초과가 턴 결과를 바꾸지 않는다 ---


def _turn_result(client, fake):
    """퀴즈 자료가 돌지 않는 선택(문장)으로 같은 질문을 했을 때의 결과. 비교 기준이다."""
    cid = fake.conversation(A)
    _sentence(fake, cid)
    parsed = events(ask(client, cid))
    return names(parsed), parsed[-1][1]["status"], parsed[-1][1]["result"]


def _limit(fake, store, bedrock):
    store.limit_kinds = {"explain"}


def _bedrock_error(fake, store, bedrock):
    denied = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "합성"}}, "Converse")
    bedrock.explain_steps = [denied, denied]


def _store_down(fake, store, bedrock):
    fake.store_down = True


def _unexpected(fake, store, bedrock):
    fake.find_error = RuntimeError("합성 오류")


def _key_exists(fake, store, bedrock):
    # 같은 턴 키의 explain 예약이 이미 있다(정상 흐름에서는 선점 때문에 생기지 않는다).
    store.exists_kinds = {"explain"}


@pytest.mark.parametrize(
    ("failure", "outcome"),
    [(_limit, "limit"), (_bedrock_error, "ai_error"), (_store_down, "error"), (_unexpected, "error"),
     (_key_exists, "exists")],
    ids=["explain_limit", "bedrock_error", "store_down", "unexpected", "key_exists"],
)
def test_material_failures_leave_the_turn_result_unchanged(client, fake, store, bedrock, caplog, failure, outcome):
    expected = _turn_result(client, fake)
    failure(fake, store, bedrock)
    caplog.set_level(logging.INFO, logger="app.agent")
    caplog.clear()
    cid = fake.conversation(A)
    parsed = events(ask(client, cid))
    assert (names(parsed), parsed[-1][1]["status"], parsed[-1][1]["result"]) == expected
    assert last_finish_status(fake) == "completed"
    assert fake.term_views == set()
    # 실패 분기까지 갔는지 결과 종류로 확인한다(용어가 아니라서 건너뛴 것이 아니다).
    assert f"outcome={outcome}" in caplog.text


def last_finish_status(fake):
    return fake.finishes[-1]["p_status"]


def test_a_failed_turn_still_ends_with_its_error_and_material_runs_after_it(client, fake, store, bedrock):
    # agent 호출 자체가 한도에 걸린 턴: 턴은 failed(limit)이고 explain은 그 뒤에 따로 예약된다.
    store.limit_kinds = {"agent"}
    cid = fake.conversation(A)
    parsed = events(ask(client, cid))
    assert parsed[-1][0] == "error" and parsed[-1][1]["error"]["code"] == "ai_limit_reached"
    assert fake.terms[KEY]["explanations"] and store.log[0] == ("reserve", "explain")


def test_one_off_storage_records_no_view(client, fake, bedrock):
    fake.store_outcome = "one_off"
    cid = fake.conversation(A)
    events(ask(client, cid))
    assert bedrock.kinds() == ["agent", "explain"] and len(fake.store_calls) == 1
    assert KEY not in fake.terms and fake.term_views == set()


# --- 재생·스트림·시간·로그 ---


def test_a_same_key_replay_does_not_run_material_again(client, fake, store, bedrock):
    cid = fake.conversation(A)
    key = str(uuid.uuid4())
    events(ask(client, cid, key=key))
    reads = fake.calls.count("find_term_for_explain")
    replay = events(ask(client, cid, key=key))
    assert names(replay) == ["turn", "result"]
    assert fake.calls.count("find_term_for_explain") == reads
    assert bedrock.kinds() == ["agent", "explain"]


def test_after_the_last_event_the_stream_sends_only_keep_alive_comments(fake, store, bedrock, monkeypatch):
    # 턴 자체는 가짜라 수 밀리초에 끝난다. 기준을 1초로 넉넉히 두어 느린 실행기에서도 delayed가 result보다 먼저 나가지 않게 한다.
    monkeypatch.setattr(agent_turns, "DELAYED_AFTER_SECONDS", 1.0)
    monkeypatch.setattr(agent_turns, "KEEPALIVE_SECONDS", 0.3)
    bedrock.explain_delay = 1.6
    client = TestClient(build_app(fake, store, bedrock, FixedRetriever(PARAGRAPHS)))
    cid = fake.conversation(A)
    parsed = events(ask(client, cid))
    end = names(parsed).index("result")
    after = names(parsed)[end + 1:]
    assert after and set(after) == {"comment"}
    assert "delayed" not in names(parsed)
    assert fake.terms[KEY]["explanations"]


def test_a_late_turn_skips_the_ai_call_but_known_terms_still_get_a_view(client, fake, store, bedrock, monkeypatch):
    monkeypatch.setattr(agent_quiz_material, "AI_CUTOFF_SECONDS", -1.0)
    cid = fake.conversation(A)
    events(ask(client, cid))
    untouched(fake, store, bedrock)
    term = fake.add_term(TERM, glossary=True)
    events(ask(client, cid))
    assert fake.term_views == {(A, term["id"], _kst_today())}


def test_logs_have_no_term_sentence_or_question(client, fake, caplog):
    caplog.set_level(logging.INFO, logger="app")
    cid = fake.conversation(A)
    events(ask(client, cid, body={"question": {"kind": "free", "text": "로그에 남으면 안 되는 질문"}}))
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "stage=quiz_material" in text and "outcome=stored" in text
    for secret in (TERM, "로그에 남으면 안 되는 질문", EXPLAIN_TEXT, BODY[:20]):
        assert secret not in text


def test_the_ai_cutoff_counts_from_when_the_request_arrived(client, fake, store, bedrock, monkeypatch):
    # 선점 전 준비(DB 읽기 등)가 오래 걸리면 그 시간도 함수 최대 실행 시간에 들어간다. 요청을 받은 때부터 잰다.
    monkeypatch.setattr(agent_quiz_material, "AI_CUTOFF_SECONDS", 0.2)
    claim = fake.claim_agent_turn

    def slow_claim(fields):
        time.sleep(0.3)
        return claim(fields)

    fake.claim_agent_turn = slow_claim
    cid = fake.conversation(A)
    events(ask(client, cid))
    untouched(fake, store, bedrock)


def test_a_cancelled_turn_still_creates_material(client, fake, store, bedrock):
    # 설계 결정: 실행까지 간 턴이면 결과(completed·failed·cancelled)와 관계없이 돈다. 사용자가 그 용어를 물었기 때문이다.
    touch = fake.touch_agent_turn

    def cancel_before_compose(user_id, turn_id, step, lease_expires_at, paragraph_count=None):
        if step == "compose":
            fake.turns[turn_id]["status"] = "cancelled"
        return touch(user_id, turn_id, step, lease_expires_at, paragraph_count)

    fake.touch_agent_turn = cancel_before_compose
    cid = fake.conversation(A)
    parsed = events(ask(client, cid))
    assert parsed[-1][0] == "result" and parsed[-1][1]["status"] == "cancelled"
    assert bedrock.kinds() == ["explain"] and fake.terms[KEY]["explanations"]


def test_a_selection_on_a_hidden_image_token_changes_nothing(client, fake, store, bedrock):
    body = "그림 ![구조](note-image:abc123) 을 본다."
    fake.note_rows[PUBLIC]["body_markdown"] = body
    start = body.index("note-image:abc123")
    cid = fake.conversation(A)
    fake.selections[-1].update(start=start, end=start + len("note-image:abc123"), text_snapshot="note-image:abc123")
    events(ask(client, cid))
    untouched(fake, store, bedrock)


def test_a_private_note_cached_ai_term_records_a_view(client, fake, store, bedrock):
    term = fake.add_term(TERM, explanation="이미 있는 설명")
    cid = fake.conversation(OP, note_id=PRIVATE)
    events(ask(client, cid, token="op-token"))
    assert bedrock.kinds() == ["agent"] and fake.store_calls == []
    assert fake.term_views == {(OP, term["id"], _kst_today())}


# --- 2026-11-19 결정: agent 호출이 Bedrock 오류로 실패한 턴은 explain을 부르지 않는다 ---


def _denied():
    return ClientError({"Error": {"Code": "AccessDeniedException", "Message": "합성"}}, "Converse")


def test_a_turn_whose_agent_call_failed_at_bedrock_does_not_call_explain(client, fake, store, bedrock):
    bedrock.agent_steps = [_denied(), _denied()]
    cid = fake.conversation(A)
    parsed = events(ask(client, cid))
    assert parsed[-1][0] == "error" and parsed[-1][1]["error"]["code"] == "ai_unavailable"
    assert "explain" not in bedrock.kinds()
    assert [r["kind"] for r in store.reserves if r["kind"] == "explain"] == []
    assert fake.store_calls == [] and fake.term_views == set()


def test_a_bedrock_failed_turn_still_records_a_view_for_a_known_term(client, fake, bedrock):
    term = fake.add_term(TERM, glossary=True)
    bedrock.agent_steps = [_denied(), _denied()]
    cid = fake.conversation(A)
    events(ask(client, cid))
    assert fake.term_views == {(A, term["id"], _kst_today())}


def test_an_output_format_failure_is_not_a_provider_failure_and_still_calls_explain(client, fake, bedrock):
    # 형식 실패도 ai_unavailable로 끝나지만 공급자는 응답했다. explain은 그대로 부른다.
    bedrock.agent_steps = [bedrock_reply("JSON이 아닌 답")]
    cid = fake.conversation(A)
    parsed = events(ask(client, cid))
    assert parsed[-1][0] == "error" and parsed[-1][1]["error"]["code"] == "ai_unavailable"
    assert bedrock.kinds() == ["agent", "explain"] and fake.terms[KEY]["explanations"]


# --- MEG-272: 두 번 눌러 고른 어절의 서식 문자와 조사는 E09와 같은 규칙이다 ---
# 합성 본문. 일반 글, 인라인 코드(``` ` 하이퍼바이저 `는 ```), 굵게 쓴 낱말을 두 번 누른 범위(조사와 뒤 공백 포함)다.

HYPER = "하이퍼바이저는 VM에 자원을 나눈다. ` 하이퍼바이저 `는 이 문제를 해결한다. **하이퍼바이저**는 굵게 쓴다."


def _select_hyper(fake, nth):
    fake.note_rows[PUBLIC]["body_markdown"] = HYPER
    start = -1
    for _ in range(nth + 1):
        start = HYPER.index("하이퍼바이저", start + 1)
    end = HYPER.index("는 ", start) + 2
    fake.selections[-1].update(start=start, end=end, text_snapshot=HYPER[start:end])


@pytest.mark.parametrize("nth", [0, 1, 2], ids=["plain", "inline_code", "bold"])
def test_a_selection_with_a_particle_joins_the_existing_term_like_e09(client, fake, store, bedrock, nth):
    term = fake.add_term("하이퍼바이저", explanation="이미 있는 설명")
    cid = fake.conversation(A)
    _select_hyper(fake, nth)

    events(ask(client, cid))

    assert bedrock.kinds() == ["agent"] and fake.store_calls == []
    assert fake.term_views == {(A, term["id"], _kst_today())}


@pytest.mark.parametrize("nth", [0, 1, 2], ids=["plain", "inline_code", "bold"])
def test_an_unseen_word_is_stored_under_one_key_for_all_three_selections(client, fake, store, bedrock, nth):
    cid = fake.conversation(A)
    _select_hyper(fake, nth)

    events(ask(client, cid))

    [stored] = fake.store_calls
    assert (stored["term_key"], stored["term_label"]) == ("하이퍼바이저는", "하이퍼바이저는")
    [(_, prompt)] = [entry for entry in bedrock.log if entry[0] == "explain"]
    assert "용어: 하이퍼바이저는\n" in prompt


def test_the_stripped_existing_term_without_an_explanation_gets_one_under_its_own_key(client, fake, store, bedrock):
    term = fake.add_term("하이퍼바이저")
    cid = fake.conversation(A)
    _select_hyper(fake, 1)

    events(ask(client, cid))

    [stored] = fake.store_calls
    assert (stored["term_key"], stored["term_label"]) == ("하이퍼바이저", "하이퍼바이저")
    assert fake.term_views == {(A, term["id"], _kst_today())}
