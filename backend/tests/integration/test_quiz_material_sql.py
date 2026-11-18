"""노트 용어 질문의 퀴즈 자료가 다음 날 퀴즈 후보가 되는지 (MEG-243 AC-6). 전용·네트워크 격리 일회용 PostgreSQL에서만 돈다.

원격 URL이나 자격증명은 받지 않는다. 다른 SQL 시험과 같은 컨테이너 변수(AI_LEDGER_TEST_CONTAINER)를 쓰고, 없으면 건너뛴다.

흐름: E29의 퀴즈 자료 처리(make_quiz_material)를 실제 마이그레이션을 올린 DB에 붙여 돌린다. 노트·용어 읽기와 열람 기록은
REST 래퍼(SupabaseClient)와 같은 조회를 SQL로 하고, 설명 저장은 실제 SQL 함수 ai_store_explanation을 service_role로 부른다.
원장과 Bedrock은 가짜다(모델 호출 없음). 그다음 E11의 후보 선택(quiz.pick_candidates)이 다음 날 그 용어와 AI 설명을 고르는지 본다.
"""

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app import glossary, session
from app.agent_quiz_material import make_quiz_material
from app.ai_explain import AiRuntime
from app.ai_ledger import AiBudget, Reservation
from app.auth import SessionUser
from app.bedrock import BedrockSettings
from app.quiz import pick_candidates

CONTAINER = os.environ.get("AI_LEDGER_TEST_CONTAINER")
pytestmark = pytest.mark.skipif(not CONTAINER, reason="dedicated local PostgreSQL container not selected")

BODY = "첫 문장입니다. 멱등성은 같은 요청을 여러 번 보내도 결과가 같은 성질이다. 마지막 문장입니다."
TERM = "멱등성"
EXPLAIN_TEXT = "합성 공유 설명입니다. 같은 요청을 다시 보내도 결과가 같습니다."
# 2026-11-18T06:00:00Z = 2026-11-18 15:00 KST
NOW = 1_794_981_600
STUDY_DAY = date(2026, 11, 18)


def _psql(database, query):
    return subprocess.run(["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", database,
                           "-v", "ON_ERROR_STOP=1", "-qAt"], input=query, text=True, encoding="utf-8",
                          capture_output=True, timeout=60)


def sql(database, query):
    result = _psql(database, query)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def json_rows(database, query):
    out = sql(database, f"select coalesce(json_agg(t), '[]'::json) from ({query}) t;")
    return json.loads(out.splitlines()[-1])


@pytest.fixture(scope="module")
def database():
    state = subprocess.run(["docker", "inspect", CONTAINER, "--format", "{{json .HostConfig.NetworkMode}}"],
                           capture_output=True, text=True, check=True)
    assert json.loads(state.stdout) == "none", "only network-isolated test containers are allowed"
    name = "meg243_" + uuid.uuid4().hex
    sql("postgres", """
      do $$ begin
        if not exists (select from pg_roles where rolname = 'anon') then create role anon; end if;
        if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated; end if;
        if not exists (select from pg_roles where rolname = 'service_role') then create role service_role bypassrls; end if;
      end $$;
    """)
    sql("postgres", f"create database {name};")
    try:
        sql(name, "create schema auth; create table auth.users(id uuid primary key); grant usage on schema public to service_role;")
        root = Path(__file__).resolve().parents[3]
        for migration in sorted((root / "supabase" / "migrations").glob("*.sql")):
            sql(name, migration.read_text(encoding="utf-8"))
        yield name
    finally:
        sql("postgres", f"drop database {name} with (force);")


class SqlSupabase:
    """make_quiz_material과 pick_candidates가 부르는 래퍼 메서드만 SQL로 흉내 낸다. 조회 조건은 supabase.py와 같다."""

    def __init__(self, database):
        self.db = database

    def get_note_for_explain(self, note_id, include_unpublished):
        published = "" if include_unpublished else " and is_published"
        rows = json_rows(self.db, f"select id, revision, is_published, body_markdown from public.notes "
                                  f"where id = {int(note_id)}{published}")
        return rows[0] if rows else None

    def find_term_for_explain(self, key, user_id):
        literal = key.replace("'", "''")
        rows = json_rows(self.db, f"""
          select t.id, t.key, t.label, t.source,
                 (select json_build_object('body_markdown', g.body_markdown) from public.glossary_entries g
                   where g.term_id = t.id) as glossary_entries,
                 '[]'::json as glossary_images,
                 coalesce((select json_agg(json_build_object('id', e.id, 'body', e.body, 'review_status', e.review_status))
                             from public.ai_explanations e where e.term_id = t.id and e.invalidated_at is null), '[]'::json)
                   as ai_explanations,
                 coalesce((select json_agg(json_build_object('term_id', f.term_id)) from public.favorites f
                            where f.term_id = t.id and f.user_id = '{uuid.UUID(user_id)}'), '[]'::json) as favorites
            from public.terms t where t.key = '{literal}' limit 1""")
        return rows[0] if rows else None

    def store_ai_explanation(self, **a):
        def text(value):
            return "'" + str(value).replace("'", "''") + "'"

        out = sql(self.db, "set role service_role; select row_to_json(r) from public.ai_store_explanation("
                           f"{int(a['note_id'])}, {int(a['note_revision'])}, {text(a['term_key'])}, {text(a['term_label'])}, "
                           f"{text(a['sentence_hash'])}, {text(a['body'])}, {text(a['model'])}, {text(a['prompt_version'])}) r;")
        row = json.loads(out.splitlines()[-1])
        return {key.removeprefix("out_"): value for key, value in row.items()}

    def record_term_view(self, user_id, term_id, study_date):
        sql(self.db, f"insert into public.term_views (user_id, term_id, study_date) values "
                     f"('{uuid.UUID(user_id)}', {int(term_id)}, '{study_date}') on conflict do nothing;")
        return True

    def list_quiz_source_terms(self, user_id, source_date, previous_quiz_date):
        user = uuid.UUID(user_id)
        day = f"user_id = '{user}' and study_date = '{source_date}'"
        return {
            "viewed": [r["term_id"] for r in json_rows(self.db, f"select term_id from public.term_views where {day} order by 1")],
            "favorited": [r["term_id"] for r in
                          json_rows(self.db, f"select term_id from public.favorite_events where {day} order by 1")],
            "excluded": [r["term_id"] for r in json_rows(self.db, f"""
              select i.term_id from public.quiz_items i join public.quiz_sets s on s.id = i.set_id
               where s.user_id = '{user}' and s.quiz_date = '{previous_quiz_date}' and i.term_id is not null order by 1""")],
        }

    def list_quiz_terms(self, term_ids):
        if not term_ids:
            return []
        ids = ",".join(str(int(term_id)) for term_id in term_ids)
        return json_rows(self.db, f"""
          select t.id, t.key, t.label,
                 (select json_build_object('body_markdown', g.body_markdown) from public.glossary_entries g
                   where g.term_id = t.id) as glossary_entries,
                 coalesce((select json_agg(json_build_object('body', e.body)) from public.ai_explanations e
                            where e.term_id = t.id and e.invalidated_at is null), '[]'::json) as ai_explanations
            from public.terms t where t.id in ({ids})""")


class Bedrock:
    def __init__(self):
        self.calls = 0

    def converse(self, **kwargs):
        self.calls += 1
        assert kwargs["inferenceConfig"] == {"maxTokens": 600}
        return {"output": {"message": {"content": [{"text": EXPLAIN_TEXT}]}}, "stopReason": "end_turn",
                "usage": {"inputTokens": 100, "outputTokens": 50}}


class Ledger:
    def __init__(self):
        self.kinds: list[str] = []

    def reserve(self, *, kind, attempt_no, **_):
        self.kinds.append(kind)
        return Reservation(len(self.kinds), attempt_no)

    def settle(self, ledger_id, outcome, **values):
        return True


@dataclass
class Job:
    user: SessionUser
    access: object
    checked: object
    turn_id: str = "t-meg243"
    idempotency_key: str = str(uuid.uuid4())
    budget: AiBudget = AiBudget(Decimal("0.9"), Decimal("7"), Decimal("2"), Decimal("8"))
    settings: BedrockSettings = field(default_factory=lambda: BedrockSettings(auth_mode="api_key"))
    oidc_token: str | None = None


@dataclass
class _Access:
    conversation: dict


@dataclass
class _Checked:
    selection_spans: list


def test_a_note_term_question_makes_the_term_a_quiz_candidate_the_next_day(database, monkeypatch):
    for name in ("VERCEL", "VERCEL_ENV", "VERCEL_TARGET_ENV", "VERCEL_GIT_COMMIT_REF"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(session, "now", lambda: NOW)
    assert glossary.study_date() == STUDY_DAY.isoformat()

    user = str(uuid.uuid4())
    sql(database, f"insert into auth.users values ('{user}'); insert into public.profiles (user_id, role) values ('{user}', 'member');")
    body = BODY.replace("'", "''")
    note_id, revision = (int(v) for v in sql(database, f"""insert into public.notes (title, body_markdown, is_published)
        values ('meg243 note', '{body}', true) returning id || ',' || revision;""").splitlines()[0].split(","))
    start = BODY.index(TERM)
    job = Job(
        user=SessionUser(user_id=user, role="member", display_name=None),
        access=_Access({"origin": "note", "note_id": note_id}),
        checked=_Checked([(note_id, revision, start, start + len(TERM))]),
    )
    supabase = SqlSupabase(database)
    bedrock = Bedrock()
    ledger = Ledger()
    runtime = AiRuntime(store=ledger, load_budget=lambda: job.budget, load_settings=lambda: job.settings,
                        client_factory=lambda settings, token=None: bedrock, sleep=lambda _: None)

    assert make_quiz_material(job, supabase, runtime, started_at=time.monotonic()) == "stored"
    assert (bedrock.calls, ledger.kinds) == (1, ["explain"])

    # DB에 terms(source='ai') 한 건, 유효한 ai_explanations 한 건, 그날 term_views 한 건이 생겼다.
    [term] = json_rows(database, f"select id, source from public.terms where key = '{TERM}'")
    assert term["source"] == "ai"
    explanations = json_rows(database, f"select body, note_id, note_revision from public.ai_explanations "
                                       f"where term_id = {term['id']} and invalidated_at is null")
    assert explanations == [{"body": EXPLAIN_TEXT, "note_id": note_id, "note_revision": revision}]
    assert json_rows(database, f"select study_date from public.term_views where user_id = '{user}'") == [
        {"study_date": STUDY_DAY.isoformat()}]

    # 다음 날 퀴즈(E11): 전날 연 용어가 후보가 되고, 자료는 이 AI 설명이다(사전 설명이 없으므로, D-020·D-036).
    [candidate] = pick_candidates(supabase, user, STUDY_DAY, STUDY_DAY)
    assert (candidate.term_id, candidate.label, candidate.reason, candidate.material) == (
        term["id"], TERM, "viewed", EXPLAIN_TEXT)

    # 같은 용어로 다시 물으면 AI 없이 열람만 남는다(AC-2와 같은 규칙을 실제 DB로 확인).
    assert make_quiz_material(job, supabase, runtime, started_at=time.monotonic()) == "known"
    assert bedrock.calls == 1
