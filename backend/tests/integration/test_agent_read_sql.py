"""CS Agent 읽기·중단 API(MEG-234)가 기대는 DB 규칙 시험. 전용·네트워크 격리 일회용 PostgreSQL 컨테이너에서만 돈다.

앱은 PostgREST로 아래 SQL과 같은 조건의 갱신·삭제를 한다(app/supabase.py의 expire_agent_turns·cancel_agent_turn). 여기서는
그 조건이 실제 스키마의 CHECK·외래키와 맞는지 본다. PostgREST·Auth는 없으므로 HTTP 모양은 test_supabase_agent_client.py가 맡는다.
원격 URL이나 자격증명은 받지 않는다. AI 원장·T1 시험과 같은 컨테이너 변수(AI_LEDGER_TEST_CONTAINER)를 쓴다.
"""

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

CONTAINER = os.environ.get("AI_LEDGER_TEST_CONTAINER")
pytestmark = pytest.mark.skipif(not CONTAINER, reason="dedicated local PostgreSQL container not selected")


def _psql(database, query):
    return subprocess.run(["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", database,
                           "-v", "ON_ERROR_STOP=1", "-qAt"], input=query, text=True, encoding="utf-8",
                          capture_output=True, timeout=60)


def sql(database, query):
    result = _psql(database, query)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def last(output):
    return output.splitlines()[-1] if output else ""


@pytest.fixture(scope="module")
def database():
    state = subprocess.run(["docker", "inspect", CONTAINER, "--format", "{{json .HostConfig.NetworkMode}}"],
                           capture_output=True, text=True, check=True)
    assert json.loads(state.stdout) == "none", "only network-isolated test containers are allowed"
    name = "meg234_" + uuid.uuid4().hex
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


@pytest.fixture
def db(database):
    sql(database, "delete from public.ai_conversations; delete from public.notes;")
    return database


def new_user(db):
    user = str(uuid.uuid4())
    sql(db, f"insert into auth.users values ('{user}'); insert into public.profiles (user_id, role) values ('{user}', 'member');")
    return user


def new_note(db, published=True):
    return last(sql(db, "insert into public.notes (title, body_markdown, is_published) "
                        f"values ('n', 'body', {str(published).lower()}) returning id;"))


def new_conversation(db, user, note_id, selection_note=None):
    cid = last(sql(db, "insert into public.ai_conversations (user_id, origin, note_id, note_revision) "
                       f"values ('{user}', 'note', {note_id}, 1) returning id;"))
    sql(db, "insert into public.ai_conversation_selections (conversation_id, note_id, note_revision, start, \"end\", text_snapshot) "
            f"values ('{cid}', {selection_note or note_id}, 1, 0, 3, 'abc');")
    return cid


def new_turn(db, cid, user, seq, status="running", lease="now() + interval '60 seconds'"):
    finished = "null" if status == "running" else "now()"
    result = "'{\"state\": \"answered\"}'::jsonb" if status == "completed" else "null"
    failure = "'error'" if status == "failed" else "null"
    return last(sql(db, "insert into public.ai_turns (conversation_id, user_id, seq, idempotency_key, question_kind, "
                        "question_text, status, failure, result, lease_expires_at, finished_at) values "
                        f"('{cid}', '{user}', {seq}, gen_random_uuid(), 'free', 'q', '{status}', {failure}, {result}, "
                        f"{lease}, {finished}) returning id;"))


def status_of(db, turn):
    return sql(db, f"select status || ':' || coalesce(failure, '-') from public.ai_turns where id = '{turn}';")


def expire(db, cid, user):
    """expire_agent_turns와 같은 조건(대화·사용자·running·만료 시각)의 갱신. 바꾼 행 수를 돌려준다."""
    return int(last(sql(db, f"""
      with changed as (
        update public.ai_turns set status = 'failed', failure = 'interrupted', finished_at = now()
         where conversation_id = '{cid}' and user_id = '{user}' and status = 'running' and lease_expires_at <= now()
        returning id)
      select count(*) from changed;""")))


def cancel(db, user, turn):
    return last(sql(db, f"select public.agent_finish_turn(p_user_id => '{user}', p_turn_id => '{turn}', p_status => 'cancelled');"))


# --- AC-4 ---


def test_cancel_changes_only_a_running_turn_of_the_same_user(db):
    user, other = new_user(db), new_user(db)
    cid = new_conversation(db, user, new_note(db))
    running = new_turn(db, cid, user, 1)
    assert cancel(db, other, running) == "f"
    assert status_of(db, running) == "running:-"
    assert cancel(db, user, running) == "t"
    assert status_of(db, running) == "cancelled:-"
    assert sql(db, f"select result is null and finished_at is not null from public.ai_turns where id = '{running}';") == "t"
    # 두 번째 중단은 바꾸지 않는다(이미 끝났다 → API는 409).
    assert cancel(db, user, running) == "f"


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_cancel_leaves_finished_turns_alone(db, status):
    user = new_user(db)
    cid = new_conversation(db, user, new_note(db))
    turn = new_turn(db, cid, user, 1, status=status)
    before = sql(db, f"select row_to_json(t)::text from public.ai_turns t where id = '{turn}';")
    assert cancel(db, user, turn) == "f"
    assert sql(db, f"select row_to_json(t)::text from public.ai_turns t where id = '{turn}';") == before


def test_expiry_marks_only_lapsed_running_turns_as_interrupted(db):
    user = new_user(db)
    note = new_note(db)
    lapsed_cid, live_cid = new_conversation(db, user, note), new_conversation(db, user, note)
    lapsed = new_turn(db, lapsed_cid, user, 1, lease="now() - interval '1 second'")
    done = new_turn(db, lapsed_cid, user, 2, status="completed", lease="now() - interval '1 hour'")
    live = new_turn(db, live_cid, user, 1)
    assert expire(db, lapsed_cid, user) == 1
    assert expire(db, live_cid, user) == 0
    assert status_of(db, lapsed) == "failed:interrupted"
    assert status_of(db, done) == "completed:-"
    assert status_of(db, live) == "running:-"
    # 만료로 끝난 턴은 중단되지 않고, 대화에 새 running 턴을 받을 자리가 생긴다(부분 유일 인덱스).
    assert cancel(db, user, lapsed) == "f"
    new_turn(db, lapsed_cid, user, 3)


def test_expiry_does_not_touch_another_users_turns(db):
    user, other = new_user(db), new_user(db)
    cid = new_conversation(db, other, new_note(db))
    turn = new_turn(db, cid, other, 1, lease="now() - interval '1 second'")
    assert expire(db, cid, user) == 0
    assert status_of(db, turn) == "running:-"


# --- AC-2: 노트를 지우면 대화가 닫힌다 ---


def test_deleting_the_conversation_note_removes_the_conversation_with_its_turns(db):
    user = new_user(db)
    note, other_note = new_note(db), new_note(db)
    by_note = new_conversation(db, user, note)
    untouched = new_conversation(db, user, other_note)
    turn = new_turn(db, by_note, user, 1, status="completed")
    sql(db, f"insert into public.ai_turn_sources (turn_id, ref, source_kind, source_id, cited_revision, title, paragraph_snapshot) "
            f"values ('{turn}', 1, 'note', '{other_note}', '1', 't', 'p');")
    sql(db, f"delete from public.notes where id = {note};")
    assert sql(db, "select id from public.ai_conversations;").splitlines() == [untouched]
    assert sql(db, "select count(*) from public.ai_turns;") == "0"
    assert sql(db, "select count(*) from public.ai_turn_sources;") == "0"


def test_deleting_a_selection_note_of_another_note_drops_only_the_selection(db):
    """T1 스키마의 실제 동작: 선택 문맥 행은 그 노트를 지우면 연쇄로 지워지고, 대화는 대화 노트를 따라 남는다.

    spec Q17(선택 문맥은 대화의 노트만)에서는 선택 노트가 늘 대화 노트라서 생기지 않는다. 다른 노트를 허용하게 바뀌면
    이 경우 대화가 닫히지 않고 문맥만 빠지므로, 그때 스키마나 권한 검사를 다시 정해야 한다(MEG-234 PR에 기록).
    """
    user = new_user(db)
    note, other_note = new_note(db), new_note(db)
    cid = new_conversation(db, user, other_note, selection_note=note)
    sql(db, f"delete from public.notes where id = {note};")
    assert sql(db, "select id from public.ai_conversations;") == cid
    assert sql(db, f"select count(*) from public.ai_conversation_selections where conversation_id = '{cid}';") == "0"


def test_a_deleted_source_note_keeps_the_source_row_for_the_hiding_function(db):
    user = new_user(db)
    note, source_note = new_note(db), new_note(db)
    cid = new_conversation(db, user, note)
    turn = new_turn(db, cid, user, 1, status="completed")
    sql(db, f"insert into public.ai_turn_sources (turn_id, ref, source_kind, source_id, cited_revision, title, paragraph_snapshot) "
            f"values ('{turn}', 1, 'note', '{source_note}', '1', 't', 'p');")
    sql(db, f"delete from public.notes where id = {source_note};")
    # 출처 행은 남고, 가림 함수가 노트가 없으므로 회수로 본다.
    assert sql(db, f"select source_id from public.ai_turn_sources where turn_id = '{turn}';") == source_note
    assert sql(db, f"select count(*) from public.notes where id = {source_note};") == "0"
