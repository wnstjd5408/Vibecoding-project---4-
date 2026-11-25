"""CS Agent 대화·턴 스키마와 SQL 함수 시험 (MEG-232). 전용·네트워크 격리 일회용 PostgreSQL 컨테이너에서만 돈다.

원격 URL이나 자격증명은 받지 않는다. AI 원장 시험과 같은 컨테이너 변수(AI_LEDGER_TEST_CONTAINER)를 쓴다.
금액은 시험용 숫자다. 실제 예산·단가와 관계없다.
"""

import json
import os
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
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


def sql_error(database, query):
    result = _psql(database, query)
    assert result.returncode != 0, "expected failure"
    return result.stderr


def last(output):
    return output.splitlines()[-1] if output else ""


@pytest.fixture(scope="module")
def database():
    state = subprocess.run(["docker", "inspect", CONTAINER, "--format", "{{json .HostConfig.NetworkMode}}"],
                           capture_output=True, text=True, check=True)
    assert json.loads(state.stdout) == "none", "only network-isolated test containers are allowed"
    name = "meg232_" + uuid.uuid4().hex
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
def clean(database):
    sql(database, "delete from public.ai_conversations; delete from public.ai_usage_ledger; delete from public.notes;")
    return database


def new_user(database):
    user = str(uuid.uuid4())
    sql(database, f"insert into auth.users values ('{user}'); insert into public.profiles (user_id, role) values ('{user}', 'member');")
    return user


def new_note(database):
    return last(sql(database, "insert into public.notes (title, body_markdown, is_published) values ('n', 'body', true) returning id;"))


def new_conversation(database, user, note_id=None):
    if note_id is None:
        values = f"('{user}', 'none', null, null)"
    else:
        values = f"('{user}', 'note', {note_id}, 1)"
    return last(sql(database, "insert into public.ai_conversations (user_id, origin, note_id, note_revision) "
                              f"values {values} returning id;"))


def claim(database, user, conversation, key=None, *, lease=120, text="질문"):
    key = key or str(uuid.uuid4())
    row = last(sql(database, "set role service_role; select outcome || ',' || turn_id || ',' || seq || ',' || turn_status "
                             f"from public.agent_claim_turn('{user}', '{conversation}', '{key}', 'free', '{text}', {lease});"))
    outcome, turn_id, seq, status = row.split(",")
    return outcome, turn_id, int(seq), status


def finish(database, user, turn_id, status, *, failure="null", result="null", sources="null", ledger="null"):
    return last(sql(database, "set role service_role; select public.agent_finish_turn("
                              f"'{user}', '{turn_id}', '{status}', {failure}, {result}, {sources}, {ledger});"))


def turn(database, turn_id, columns="status, coalesce(failure, ''), coalesce(result::text, ''), finished_at is not null"):
    return sql(database, f"select {columns} from public.ai_turns where id = '{turn_id}';")


def reserve(database, user, key, amount, *, kind="agent", daily="1", share="1", kind_share="null", limit="null"):
    return last(sql(database, "set role service_role; select outcome from public.ai_reserve("
                              f"'{user}', '{kind}', '{key}', 1, {amount}, {daily}, 7, {share}, {limit}, {kind_share});"))


def check_limit(database, user, amount, *, kind="agent", daily="1", share="1", limit="null", kind_share="null"):
    return last(sql(database, "set role service_role; select public.ai_check_limit("
                              f"'{user}', '{kind}', {amount}, {daily}, 7, {share}, {limit}, {kind_share});"))


# --- AC-1: 테이블·제약·인덱스 ---


def test_tables_constraints_and_indexes_match_the_design(database):
    columns = sql(database, """
      select table_name || '.' || column_name from information_schema.columns
       where table_schema = 'public'
         and table_name in ('ai_conversations', 'ai_conversation_selections', 'ai_turns', 'ai_turn_sources')
       order by table_name, ordinal_position;""").splitlines()
    assert columns == [
        "ai_conversation_selections." + c for c in
        ("id", "conversation_id", "note_id", "note_revision", "start", "end", "text_snapshot", "excluded_at", "created_at")
    ] + [
        "ai_conversations." + c for c in
        ("id", "user_id", "origin", "note_id", "note_revision", "wiki_ref", "topic_label", "created_at", "last_active_at")
    ] + [
        "ai_turn_sources." + c for c in
        ("turn_id", "ref", "source_kind", "source_id", "cited_revision", "title", "section", "excerpt", "paragraph_snapshot")
    ] + [
        "ai_turns." + c for c in
        ("id", "conversation_id", "user_id", "seq", "idempotency_key", "question_kind", "question_text", "preset",
         "from_turn_id", "reply", "retry_of_turn_id", "status", "failure", "step", "paragraph_count", "result",
         "ledger_id", "model_id", "prompt_version", "retrieval_version", "lease_expires_at", "created_at", "finished_at",
         # 2차 점검·보완 기록(MEG-282 D2, 20261125120000)
         "review_status", "review_ledger_id", "review_prompt_version", "review_prompt_sha256")
    ]

    indexes = sql(database, """
      select indexname || ' ' || indexdef from pg_indexes
       where schemaname = 'public' and tablename in ('ai_conversations', 'ai_turns', 'ai_turn_sources')
       order by indexname;""")
    assert "ai_turns_user_id_idempotency_key_key CREATE UNIQUE INDEX" in indexes
    assert "ai_turns_conversation_id_seq_key CREATE UNIQUE INDEX" in indexes
    assert ("ai_turns_one_running_per_conversation_idx CREATE UNIQUE INDEX ai_turns_one_running_per_conversation_idx "
            "ON public.ai_turns USING btree (conversation_id) WHERE (status = 'running'::text)") in indexes
    assert "ai_turn_sources_pkey CREATE UNIQUE INDEX ai_turn_sources_pkey ON public.ai_turn_sources USING btree (turn_id, ref)" in indexes
    assert "ai_conversations_user_id_idx" in indexes and "ai_conversations_last_active_at_idx" in indexes

    foreign_keys = sql(database, """
      select conrelid::regclass || '.' || a.attname || '->' || confrelid::regclass || ':' || confdeltype::text
        from pg_constraint c join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
       where c.contype = 'f'
         and c.conrelid::regclass::text in ('ai_conversations', 'ai_conversation_selections', 'ai_turns', 'ai_turn_sources')
       order by 1;""").splitlines()
    # c = cascade, n = set null (2026-11-18 사용자 결정)
    assert foreign_keys == [
        "ai_conversation_selections.conversation_id->ai_conversations:c",
        "ai_conversation_selections.note_id->notes:c",
        "ai_conversations.note_id->notes:c",
        "ai_conversations.user_id->profiles:c",
        "ai_turn_sources.turn_id->ai_turns:c",
        "ai_turns.conversation_id->ai_conversations:c",
        "ai_turns.from_turn_id->ai_turns:n",
        "ai_turns.ledger_id->ai_usage_ledger:n",
        "ai_turns.retry_of_turn_id->ai_turns:n",
        "ai_turns.review_ledger_id->ai_usage_ledger:n",
        "ai_turns.user_id->profiles:c",
    ]

    # RLS는 켜고 정책은 없다.
    assert sql(database, """
      select string_agg(relname || ':' || relrowsecurity, ',' order by relname) from pg_class
       where relname in ('ai_conversations', 'ai_conversation_selections', 'ai_turns', 'ai_turn_sources');""") == (
        "ai_conversation_selections:true,ai_conversations:true,ai_turn_sources:true,ai_turns:true")
    assert sql(database, "select count(*) from pg_policies where tablename like 'ai_conversation%' or tablename like 'ai_turn%';") == "0"


def test_check_constraints_reject_inconsistent_rows(clean):
    a = new_user(clean)
    note = new_note(clean)
    assert "check" in sql_error(clean, f"insert into public.ai_conversations (user_id, origin) values ('{a}', 'note');")
    assert "check" in sql_error(clean, f"insert into public.ai_conversations (user_id, origin, wiki_ref) values ('{a}', 'none', 'w');")
    conversation = new_conversation(clean, a, note)
    too_long = "가" * 2001
    assert "check" in sql_error(clean, "insert into public.ai_conversation_selections "
                                       "(conversation_id, note_id, note_revision, start, \"end\", text_snapshot) "
                                       f"values ('{conversation}', {note}, 1, 0, 2001, '{too_long}');")
    assert "check" in sql_error(clean, "insert into public.ai_conversation_selections "
                                       "(conversation_id, note_id, note_revision, start, \"end\", text_snapshot) "
                                       f"values ('{conversation}', {note}, 1, 5, 5, 'x');")
    # preset 종류는 preset 값이 있어야 한다.
    assert "check" in sql_error(clean, "set role service_role; select * from public.agent_claim_turn("
                                       f"'{a}', '{conversation}', '{uuid.uuid4()}', 'preset', 'q', 120);")
    assert "check" in sql_error(clean, "set role service_role; select * from public.agent_claim_turn("
                                       f"'{a}', '{conversation}', '{uuid.uuid4()}', 'free', '{'q' * 1001}', 120);")


def test_ledger_accepts_agent_kind(clean):
    a = new_user(clean)
    assert reserve(clean, a, f"{a}:agent:{uuid.uuid4()}:1", "0.1") == "reserved"
    assert sql(clean, "select kind from public.ai_usage_ledger;") == "agent"
    assert "check" in sql_error(clean, f"insert into public.ai_usage_ledger (user_id, kind, idempotency_key, reserved_usd, kst_date) "
                                       f"values ('{a}', 'other', 'x', 0, current_date);")


# --- AC-3: agent_claim_turn 세 결과 ---


def test_claim_returns_claimed_existing_and_in_progress(clean):
    a = new_user(clean)
    conversation = new_conversation(clean, a)
    key = str(uuid.uuid4())

    outcome, first, seq, status = claim(clean, a, conversation, key)
    assert (outcome, seq, status) == ("claimed", 1, "running")

    # 같은 키: 진행 중인 같은 턴
    assert claim(clean, a, conversation, key) == ("existing", first, 1, "running")
    # 다른 키, 같은 대화: 진행 중인 다른 턴이 있다
    assert claim(clean, a, conversation) == ("in_progress", first, 1, "running")
    assert sql(clean, "select count(*) from public.ai_turns;") == "1"

    assert finish(clean, a, first, "completed", result="'{\"state\": \"answered\"}'") == "t"
    # 끝난 뒤 같은 키: 끝난 턴을 돌려준다. 새 키: 다음 순서로 선점
    assert claim(clean, a, conversation, key) == ("existing", first, 1, "completed")
    outcome, second, seq, status = claim(clean, a, conversation)
    assert (outcome, seq, status) == ("claimed", 2, "running")
    assert second != first


def test_same_key_in_another_conversation_returns_the_existing_turn(clean):
    a = new_user(clean)
    one, two = new_conversation(clean, a), new_conversation(clean, a)
    key = str(uuid.uuid4())
    _, first, _, _ = claim(clean, a, one, key)

    assert claim(clean, a, two, key) == ("existing", first, 1, "running")
    # 키는 사용자별이다. 다른 사용자는 같은 키로 선점할 수 있다.
    b = new_user(clean)
    assert claim(clean, b, new_conversation(clean, b), key)[0] == "claimed"


def test_expired_running_turn_becomes_interrupted_on_next_claim(clean):
    a = new_user(clean)
    conversation = new_conversation(clean, a)
    key = str(uuid.uuid4())
    _, first, _, _ = claim(clean, a, conversation, key)
    sql(clean, f"update public.ai_turns set lease_expires_at = now() - interval '1 second' where id = '{first}';")

    outcome, second, seq, _ = claim(clean, a, conversation)
    assert (outcome, seq) == ("claimed", 2)
    assert turn(clean, first) == "failed|interrupted||t"
    # 만료로 끝난 턴의 키를 다시 보내면 끝난 턴을 돌려준다.
    assert claim(clean, a, conversation, key) == ("existing", first, 1, "failed")


def test_expired_same_key_turn_in_another_conversation_is_closed(clean):
    a = new_user(clean)
    one, two = new_conversation(clean, a), new_conversation(clean, a)
    key = str(uuid.uuid4())
    _, first, _, _ = claim(clean, a, one, key)
    sql(clean, f"update public.ai_turns set lease_expires_at = now() - interval '1 second' where id = '{first}';")

    assert claim(clean, a, two, key) == ("existing", first, 1, "failed")
    assert turn(clean, first) == "failed|interrupted||t"


def test_claim_rejects_other_users_conversation(clean):
    a, b = new_user(clean), new_user(clean)
    conversation = new_conversation(clean, a)
    assert "conversation_not_found" in sql_error(clean, "set role service_role; select * from public.agent_claim_turn("
                                                        f"'{b}', '{conversation}', '{uuid.uuid4()}', 'free', 'q', 120);")
    assert "conversation_not_found" in sql_error(clean, "set role service_role; select * from public.agent_claim_turn("
                                                        f"'{a}', '{uuid.uuid4()}', '{uuid.uuid4()}', 'free', 'q', 120);")


def test_concurrent_claims_on_one_conversation_create_one_running_turn(clean):
    a = new_user(clean)
    conversation = new_conversation(clean, a)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: claim(clean, a, conversation), range(8)))

    outcomes = sorted(r[0] for r in results)
    assert outcomes == ["claimed"] + ["in_progress"] * 7
    assert sql(clean, "select count(*) from public.ai_turns;") == "1"


def test_concurrent_claims_with_the_same_key_in_different_conversations(clean):
    a = new_user(clean)
    conversations = [new_conversation(clean, a) for _ in range(6)]
    key = str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda c: claim(clean, a, c, key), conversations))

    assert sorted(r[0] for r in results) == ["claimed"] + ["existing"] * 5
    assert len({r[1] for r in results}) == 1
    assert sql(clean, "select count(*) from public.ai_turns;") == "1"


# --- AC-3: agent_finish_turn 조건부 전이 ---


def test_finish_only_changes_running_turns(clean):
    a = new_user(clean)
    conversation = new_conversation(clean, a)
    sql(clean, f"update public.ai_conversations set last_active_at = now() - interval '1 day' where id = '{conversation}';")
    _, first, _, _ = claim(clean, a, conversation)
    sources = ("'[{\"ref\": 1, \"source_kind\": \"note\", \"source_id\": \"12\", \"cited_revision\": \"3\", "
               "\"title\": \"t\", \"section\": \"s\", \"paragraph_snapshot\": \"원문\"}]'")

    assert finish(clean, a, first, "completed", result="'{\"state\": \"answered\"}'", sources=sources) == "t"
    assert turn(clean, first) == 'completed||{"state": "answered"}|t'
    assert sql(clean, f"select source_kind || ':' || source_id || ':' || paragraph_snapshot from public.ai_turn_sources "
                      f"where turn_id = '{first}';") == "note:12:원문"
    assert sql(clean, f"select last_active_at > now() - interval '1 minute' from public.ai_conversations where id = '{conversation}';") == "t"

    # 이미 끝난 턴은 바꾸지 않는다.
    assert finish(clean, a, first, "failed", failure="'error'") == "f"
    assert turn(clean, first, "status") == "completed"


def test_cancelled_turn_cannot_be_completed_but_keeps_the_ledger_link(clean):
    a = new_user(clean)
    conversation = new_conversation(clean, a)
    _, first, _, _ = claim(clean, a, conversation)
    assert reserve(clean, a, f"{a}:agent:k:1", "0.1") == "reserved"
    ledger_id = sql(clean, "select id from public.ai_usage_ledger;")

    assert finish(clean, a, first, "cancelled") == "t"
    assert finish(clean, a, first, "completed", result="'{\"state\": \"answered\"}'", ledger=ledger_id) == "f"
    assert turn(clean, first, "status || ':' || coalesce(result::text, '') || ':' || ledger_id") == f"cancelled::{ledger_id}"
    assert sql(clean, "select count(*) from public.ai_turn_sources;") == "0"


def test_finish_requires_the_owner_and_consistent_arguments(clean):
    a, b = new_user(clean), new_user(clean)
    conversation = new_conversation(clean, a)
    _, first, _, _ = claim(clean, a, conversation)

    assert finish(clean, b, first, "cancelled") == "f"
    assert turn(clean, first, "status") == "running"
    for args in ("'completed'", "'failed'", "'cancelled', 'error'", "'running'",
                 "'cancelled', null, null, '[]'", "'completed', null, '{}', '{}'"):
        assert "invalid agent finish arguments" in sql_error(
            clean, f"set role service_role; select public.agent_finish_turn('{a}', '{first}', {args});")


def test_failed_turn_with_limit_failure(clean):
    a = new_user(clean)
    _, first, _, _ = claim(clean, a, new_conversation(clean, a))
    assert finish(clean, a, first, "failed", failure="'limit'") == "t"
    assert turn(clean, first) == "failed|limit||t"


# --- AC-3: ai_reserve agent 몫, ai_check_limit ---


def test_agent_share_of_the_daily_budget(clean):
    a, b = new_user(clean), new_user(clean)

    assert reserve(clean, a, "a1", "0.4") == "reserved"
    assert reserve(clean, b, "b1", "0.2") == "reserved"
    # agent 합계 0.6 + 0.2 > 하루 예산 1의 70%
    assert reserve(clean, b, "b2", "0.2") == "limit_reached"
    assert sql(clean, "select count(*) from public.ai_usage_ledger;") == "2"
    # 몫 안(0.7 이하)은 된다.
    assert reserve(clean, b, "b3", "0.1") == "reserved"
    # 다른 kind는 agent 몫과 관계없이 하루 예산 전체를 쓸 수 있다(기존 동작).
    assert reserve(clean, a, "a2", "0.3", kind="explain") == "reserved"
    assert reserve(clean, a, "a3", "0.01", kind="quiz") == "limit_reached"


def test_kind_share_argument_overrides_the_agent_default_and_applies_to_other_kinds(clean):
    a = new_user(clean)
    assert reserve(clean, a, "a1", "0.5", kind_share="0.5") == "reserved"
    assert reserve(clean, a, "a2", "0.1", kind_share="0.5") == "limit_reached"
    assert reserve(clean, a, "a3", "0.2", kind_share="0.8") == "reserved"

    assert reserve(clean, a, "e1", "0.1", kind="explain", kind_share="0.1") == "reserved"
    assert reserve(clean, a, "e2", "0.05", kind="explain", kind_share="0.1") == "limit_reached"
    assert "invalid ai reservation arguments" in sql_error(
        clean, "set role service_role; select * from public.ai_reserve("
               f"'{a}', 'agent', 'x', 1, 0.1, 1, 7, 1, null, 1.5);")


def test_check_limit_reads_without_reserving(clean):
    a = new_user(clean)
    assert check_limit(clean, a, "0.7") == "t"
    assert check_limit(clean, a, "0.71") == "f"
    assert sql(clean, "select count(*) from public.ai_usage_ledger;") == "0"

    assert reserve(clean, a, "a1", "0.3", limit="2") == "reserved"
    assert check_limit(clean, a, "0.5") == "f"
    assert check_limit(clean, a, "0.4") == "t"
    # 하루 횟수: 첫 시도 행 1개, 한도 1이면 막힌다.
    assert check_limit(clean, a, "0.01", limit="1") == "f"
    assert check_limit(clean, a, "0.01", limit="2") == "t"
    # 사용자 몫과 일 예산도 같은 규칙이다.
    assert check_limit(clean, a, "0.25", kind="explain", share="0.5") == "f"
    assert check_limit(clean, a, "0.2", kind="explain", share="0.5") == "t"
    assert sql(clean, "select count(*) from public.ai_usage_ledger;") == "1"


def test_concurrent_agent_reservations_never_exceed_the_agent_share(clean):
    users = [new_user(clean) for _ in range(10)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        outcomes = list(pool.map(lambda u: reserve(clean, u, f"{u}:agent:k:1", "0.1"), users))

    assert outcomes.count("reserved") == 7
    assert sql(clean, "select sum(reserved_usd) from public.ai_usage_ledger;") == "0.700000"


# --- AC-3: 7일 보관 정리 ---


def test_purge_deletes_conversations_inactive_for_seven_days_with_children(clean):
    a = new_user(clean)
    note = new_note(clean)
    old, recent = new_conversation(clean, a, note), new_conversation(clean, a, note)
    for conversation in (old, recent):
        sql(clean, "insert into public.ai_conversation_selections "
                   "(conversation_id, note_id, note_revision, start, \"end\", text_snapshot) "
                   f"values ('{conversation}', {note}, 1, 0, 4, 'body');")
        _, turn_id, _, _ = claim(clean, a, conversation)
        assert reserve(clean, a, f"{a}:agent:{turn_id}:1", "0.01") == "reserved"
        finish(clean, a, turn_id, "completed", result="'{\"state\": \"answered\"}'",
               sources="'[{\"ref\": 1, \"source_kind\": \"note\", \"source_id\": \"1\", \"cited_revision\": \"1\", "
                       "\"title\": \"t\", \"paragraph_snapshot\": \"p\"}]'",
               ledger=f"(select id from public.ai_usage_ledger where idempotency_key = '{a}:agent:{turn_id}:1')")
    sql(clean, f"update public.ai_conversations set last_active_at = now() - interval '7 days 1 minute' where id = '{old}';")
    sql(clean, f"update public.ai_conversations set last_active_at = now() - interval '6 days 23 hours' where id = '{recent}';")

    assert last(sql(clean, "set role service_role; select public.agent_purge_expired();")) == "1"
    assert sql(clean, "select id from public.ai_conversations;") == recent
    assert sql(clean, "select count(*) from public.ai_conversation_selections;") == "1"
    assert sql(clean, "select count(*) from public.ai_turns;") == "1"
    assert sql(clean, "select count(*) from public.ai_turn_sources;") == "1"
    # 원장 행은 비용 기록이라 남는다.
    assert sql(clean, "select count(*) from public.ai_usage_ledger;") == "2"


def test_foreign_key_delete_rules(clean):
    a = new_user(clean)
    note = new_note(clean)
    by_note = new_conversation(clean, a, note)
    plain = new_conversation(clean, a)
    _, turn_id, _, _ = claim(clean, a, plain)
    assert reserve(clean, a, "l1", "0.01") == "reserved"
    sql(clean, f"update public.ai_turns set ledger_id = (select id from public.ai_usage_ledger) where id = '{turn_id}';")

    # 노트를 지우면 그 노트의 대화가 닫힌다.
    sql(clean, f"delete from public.notes where id = {note};")
    assert sql(clean, f"select count(*) from public.ai_conversations where id = '{by_note}';") == "0"
    # 원장 행이 지워지면 턴은 남고 연결만 빠진다.
    sql(clean, "delete from public.ai_usage_ledger;")
    assert turn(clean, turn_id, "status || ':' || coalesce(ledger_id::text, 'null')") == "running:null"
    # 사용자를 지우면 대화와 턴도 지운다.
    sql(clean, f"delete from public.profiles where user_id = '{a}';")
    assert sql(clean, "select count(*) from public.ai_conversations;") == "0"
    assert sql(clean, "select count(*) from public.ai_turns;") == "0"


# --- AC-2 보강: 바뀐 ai_reserve의 기존 호출 형태 ---


def test_existing_nine_argument_calls_keep_working(clean):
    a = new_user(clean)
    # 앱(ai_ledger.py)이 보내는 이름 인자 형태. p_kind_daily_share는 보내지 않는다.
    assert last(sql(clean, "set role service_role; select outcome from public.ai_reserve("
                           f"p_user_id => '{a}', p_kind => 'explain', p_idempotency_key => 'k1', p_attempt_no => 1, "
                           "p_reserved_usd => 0.9, p_user_daily_count_limit => null, p_daily_budget_usd => 1, "
                           "p_monthly_budget_usd => 7, p_user_daily_share => 1);")) == "reserved"
    assert sql(clean, "select count(*) from pg_proc where proname = 'ai_reserve';") == "1"


# --- 리뷰 반영: 교착, 다른 사용자 참조, 잘못된 출처, 결정적 동시성 ---


def hold(database, statements, seconds, end="commit"):
    """다른 세션에서 트랜잭션을 열고 statements를 실행한 뒤 seconds 동안 잡고 있다가 끝낸다."""
    return ThreadPoolExecutor(max_workers=1).submit(
        sql, database, f"begin; {statements}; select pg_sleep({seconds}); {end};")


def test_finish_and_claim_on_an_expired_turn_do_not_deadlock(clean):
    a = new_user(clean)
    conversation = new_conversation(clean, a)
    _, first, _, _ = claim(clean, a, conversation)
    sql(clean, f"update public.ai_turns set lease_expires_at = now() - interval '1 second' where id = '{first}';")

    # 세 번째 세션이 턴 행을 잠근 동안 끝내기와 선점이 차례로 들어온다. 잠금 순서가 서로 반대면(이전 구현)
    # 잠금이 풀린 뒤 끝내기는 턴→대화, 선점은 대화→턴을 기다려 교착(40P01)이 난다.
    blocker = hold(clean, f"select 1 from public.ai_turns where id = '{first}' for update", 1.5)
    time.sleep(0.3)
    pool = ThreadPoolExecutor(max_workers=2)
    finishing = pool.submit(finish, clean, a, first, "completed", result="'{\"state\": \"answered\"}'")
    time.sleep(0.3)
    claiming = pool.submit(claim, clean, a, conversation)
    blocker.result()
    assert finishing.result() == "t"
    outcome, _, seq, _ = claiming.result()

    # 끝내기가 먼저 대화를 잠갔으므로 completed가 되고, 선점은 그 뒤 새 턴을 만든다.
    assert turn(clean, first, "status") == "completed"
    assert (outcome, seq) == ("claimed", 2)


def test_claim_rejects_turn_references_outside_the_conversation(clean):
    a, b = new_user(clean), new_user(clean)
    mine, other = new_conversation(clean, a), new_conversation(clean, a)
    _, own_turn, _, _ = claim(clean, a, mine)
    finish(clean, a, own_turn, "completed", result="'{\"state\": \"answered\"}'")
    _, other_turn, _, _ = claim(clean, a, other)
    _, foreign_turn, _, _ = claim(clean, b, new_conversation(clean, b))

    for column in ("p_from_turn_id", "p_retry_of_turn_id"):
        for target in (other_turn, foreign_turn, str(uuid.uuid4())):
            assert "invalid agent claim arguments" in sql_error(
                clean, "set role service_role; select * from public.agent_claim_turn("
                       f"'{a}', '{mine}', '{uuid.uuid4()}', 'free', 'q', 120, {column} => '{target}');")
    row = last(sql(clean, "set role service_role; select outcome from public.agent_claim_turn("
                          f"'{a}', '{mine}', '{uuid.uuid4()}', 'suggested', 'q', 120, p_from_turn_id => '{own_turn}');"))
    assert row == "claimed"


def test_bad_sources_are_rejected_before_the_turn_changes(clean):
    a = new_user(clean)
    _, first, _, _ = claim(clean, a, new_conversation(clean, a))
    one = '{"ref": 1, "source_kind": "note", "source_id": "1", "cited_revision": "1", "title": "t", "paragraph_snapshot": "p"}'
    for sources in (f"[{one}, {one}]",
                    '[{"ref": 1, "source_kind": "note", "source_id": "1", "cited_revision": "1", "title": "t"}]',
                    one.replace('"note"', '"web"').join("[]")):
        assert "invalid agent finish arguments" in sql_error(
            clean, "set role service_role; select public.agent_finish_turn("
                   f"'{a}', '{first}', 'completed', null, '{{\"state\": \"answered\"}}', '{sources}');")
    assert turn(clean, first, "status") == "running"
    assert finish(clean, a, first, "completed", result="'{\"state\": \"answered\"}'", sources="'[]'") == "t"


def test_finish_rejects_a_ledger_row_of_another_user_or_kind(clean):
    a, b = new_user(clean), new_user(clean)
    _, first, _, _ = claim(clean, a, new_conversation(clean, a))
    assert reserve(clean, b, "b1", "0.1") == "reserved"
    assert reserve(clean, a, "a1", "0.1", kind="explain") == "reserved"
    for key in ("b1", "a1"):
        assert "invalid agent finish arguments" in sql_error(
            clean, "set role service_role; select public.agent_finish_turn("
                   f"'{a}', '{first}', 'cancelled', p_ledger_id => "
                   f"(select id from public.ai_usage_ledger where idempotency_key = '{key}'));")
    assert turn(clean, first, "status || ':' || coalesce(ledger_id::text, 'null')") == "running:null"


def test_turn_user_must_own_the_conversation(clean):
    a, b = new_user(clean), new_user(clean)
    conversation = new_conversation(clean, a)
    assert "foreign key" in sql_error(
        clean, "insert into public.ai_turns (conversation_id, user_id, seq, idempotency_key, question_kind, "
               f"question_text, lease_expires_at) values ('{conversation}', '{b}', 1, '{uuid.uuid4()}', 'free', 'q', now());")


def test_same_key_waits_for_the_first_claim_commit_or_rollback(clean):
    a = new_user(clean)
    one, two = new_conversation(clean, a), new_conversation(clean, a)
    for end, expected in (("commit", "existing"), ("rollback", "claimed")):
        key = str(uuid.uuid4())
        first = hold(clean, "set role service_role; select * from public.agent_claim_turn("
                            f"'{a}', '{one}', '{key}', 'free', 'q', 120);", 1.5, end)
        time.sleep(0.5)
        outcome, _, _, _ = claim(clean, a, two, key)
        first.result()
        assert outcome == expected, end
        sql(clean, "delete from public.ai_turns;")


def test_reservation_waits_for_a_concurrent_agent_reservation(clean):
    a, b = new_user(clean), new_user(clean)
    first = hold(clean, "set role service_role; select * from public.ai_reserve("
                        f"'{a}', 'agent', 'a1', 1, 0.6, 1, 7, 1, null);", 1.5)
    time.sleep(0.5)
    assert reserve(clean, b, "b1", "0.2") == "limit_reached"
    first.result()


def test_agent_retry_skips_the_count_limit_but_not_the_share(clean):
    a = new_user(clean)
    assert reserve(clean, a, "k:1", "0.3", limit="1") == "reserved"
    assert reserve(clean, a, "k2:1", "0.01", limit="1") == "limit_reached"
    retry = ("set role service_role; select outcome from public.ai_reserve("
             f"'{a}', 'agent', 'k:2', 2, {{}}, 1, 7, 1, 1, null);")
    assert last(sql(clean, retry.format("0.4"))) == "reserved"
    assert last(sql(clean, retry.replace("'k:2'", "'k:3'").replace(", 2,", ", 3,").format("0.01"))) == "limit_reached"
    # 사용자 몫도 agent에 적용된다.
    b = new_user(clean)
    sql(clean, "delete from public.ai_usage_ledger;")
    assert reserve(clean, b, "b1", "0.3", share="0.5") == "reserved"
    assert reserve(clean, b, "b2", "0.3", share="0.5") == "limit_reached"


def test_purge_handles_turns_that_reference_each_other(clean):
    a = new_user(clean)
    conversation = new_conversation(clean, a)
    _, first, _, _ = claim(clean, a, conversation)
    finish(clean, a, first, "completed", result="'{\"state\": \"answered\"}'")
    last(sql(clean, "set role service_role; select outcome from public.agent_claim_turn("
                    f"'{a}', '{conversation}', '{uuid.uuid4()}', 'suggested', 'q', 120, "
                    f"p_from_turn_id => '{first}', p_retry_of_turn_id => '{first}');"))
    sql(clean, f"update public.ai_conversations set last_active_at = now() - interval '8 days' where id = '{conversation}';")

    assert last(sql(clean, "set role service_role; select public.agent_purge_expired();")) == "1"
    assert sql(clean, "select count(*) from public.ai_turns;") == "0"


# --- AC-4: 권한 ---


def test_only_service_role_can_use_the_new_functions_and_tables(clean):
    a = new_user(clean)
    conversation = new_conversation(clean, a)
    calls = [
        f"select * from public.ai_reserve('{a}', 'agent', 'x', 1, 0.1, 1, 7, 1, null, null);",
        f"select * from public.ai_reserve('{a}', 'explain', 'x', 1, 0.1, 1, 7, 1, null);",
        f"select public.ai_check_limit('{a}', 'agent', 0.1, 1, 7, 1, null);",
        f"select * from public.agent_claim_turn('{a}', '{conversation}', '{uuid.uuid4()}', 'free', 'q', 120);",
        f"select public.agent_finish_turn('{a}', '{uuid.uuid4()}', 'cancelled');",
        "select public.agent_purge_expired();",
        f"select * from public.ai_claim_quiz_set('{a}', current_date + 1, current_date, 0.1, 1, 7, 0.5, 300, 2);",
        "select * from public.ai_conversations;",
        "select * from public.ai_conversation_selections;",
        "select * from public.ai_turns;",
        "select * from public.ai_turn_sources;",
    ]
    for role in ("anon", "authenticated"):
        for call in calls:
            assert "permission denied" in sql_error(clean, f"set role {role}; {call}"), (role, call)
    # 함수 실행 권한이 public에 남아 있지 않다.
    assert sql(clean, """
      select count(*) from pg_proc p
       where p.proname in ('ai_reserve', 'ai_check_limit', 'agent_claim_turn', 'agent_finish_turn', 'agent_purge_expired',
                           'ai_claim_quiz_set')
         and (has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('authenticated', p.oid, 'execute')
              or not has_function_privilege('service_role', p.oid, 'execute'));""") == "0"


# --- MEG-282 D2: 2차 점검·보완 원장 kind와 턴 기록 (20261125120000) ---


def test_agent_review_rows_share_the_agent_70_percent_but_not_the_turn_count(clean):
    a, b = new_user(clean), new_user(clean)
    # 횟수 한도 1: agent 첫 시도 1건 뒤 새 agent는 막히지만 agent_review(한도 null)는 횟수에 들지 않는다.
    assert reserve(clean, a, "a:agent:1", "0.1", limit="1") == "reserved"
    assert reserve(clean, a, "a:agent-review:1", "0.1", kind="agent_review") == "reserved"
    assert reserve(clean, a, "a:agent2:1", "0.01", limit="1") == "limit_reached"
    # agent_review 행은 agent의 횟수에 세지 않는다(같은 kind 첫 시도만 센다).
    sql(clean, "delete from public.ai_usage_ledger where kind = 'agent';")
    assert reserve(clean, a, "a:agent3:1", "0.1", limit="1") == "reserved"
    # agent 몫(하루 예산 1의 70%)은 agent + agent_review 합계로 본다. 지금 0.1 + 0.1.
    assert reserve(clean, b, "b:agent-review:1", "0.45", kind="agent_review") == "reserved"
    assert reserve(clean, b, "b:agent:1", "0.1") == "limit_reached"
    assert reserve(clean, b, "b:agent-review:2", "0.1", kind="agent_review") == "limit_reached"
    assert check_limit(clean, b, "0.05") == "t" and check_limit(clean, b, "0.06", kind="agent_review") == "f"
    # 다른 kind는 agent 묶음과 관계없다(하루 예산 전체를 쓸 수 있는 기존 동작).
    assert reserve(clean, b, "b:explain:1", "0.25", kind="explain") == "reserved"


def test_unknown_kinds_are_still_rejected(clean):
    a = new_user(clean)
    error = sql_error(clean, "set role service_role; select public.ai_check_limit("
                             f"'{a}', 'agent_other', 0.1, 1, 7, 1, null, null, 1);")
    assert "invalid ai limit arguments" in error
    error = sql_error(clean, "insert into public.ai_usage_ledger (user_id, kind, idempotency_key, reserved_usd, attempt_no, kst_date) "
                             f"values ('{a}', 'agent_other', 'x', 0.1, 1, current_date);")
    assert "ai_usage_ledger_kind_check" in error


def _ledger(database, user, kind, key):
    return last(sql(database, "insert into public.ai_usage_ledger (user_id, kind, idempotency_key, reserved_usd, attempt_no, kst_date) "
                              f"values ('{user}', '{kind}', '{key}', 0.1, 1, current_date) returning id;"))


def _finish_review(database, user, turn_id, status, *, result="null", ledger="null", review_status="null",
                   review_ledger="null", version="null", sha="null", failure="null"):
    return last(sql(database, "set role service_role; select public.agent_finish_turn("
                              f"p_user_id => '{user}', p_turn_id => '{turn_id}', p_status => '{status}', "
                              f"p_failure => {failure}, p_result => {result}, p_ledger_id => {ledger}, "
                              f"p_review_status => {review_status}, p_review_ledger_id => {review_ledger}, "
                              f"p_review_prompt_version => {version}, p_review_prompt_sha256 => {sha});"))


def test_finish_records_the_review_fields(clean):
    a = new_user(clean)
    conversation = new_conversation(clean, a)
    _, turn_id, _, _ = claim(clean, a, conversation)
    first, second = _ledger(clean, a, "agent", "a:agent:t:1"), _ledger(clean, a, "agent_review", "a:agent-review:t:1")
    sha = "a" * 64
    assert _finish_review(clean, a, turn_id, "completed", result="'{\"state\": \"answered\"}'", ledger=first,
                          review_status="'revised'", review_ledger=second, version="'agent-review-v1'",
                          sha=f"'{sha}'") == "t"
    assert turn(clean, turn_id, "ledger_id, review_status, review_ledger_id, review_prompt_version, review_prompt_sha256") \
        == f"{first}|revised|{second}|agent-review-v1|{sha}"


def test_finish_rejects_bad_review_arguments(clean):
    a, b = new_user(clean), new_user(clean)
    conversation = new_conversation(clean, a)
    _, turn_id, _, _ = claim(clean, a, conversation)
    agent_row = _ledger(clean, a, "agent", "a:agent:x:1")
    foreign_review = _ledger(clean, b, "agent_review", "b:agent-review:x:1")
    ok = "'{\"state\": \"answered\"}'"
    for kwargs in (
        {"review_status": "'maybe'"},
        {"sha": "'not-a-hash'"},
        # 2차 원장 칸은 같은 사용자의 agent_review 행만 받는다.
        {"review_ledger": agent_row},
        {"review_ledger": foreign_review},
    ):
        error = sql_error(clean, "set role service_role; select public.agent_finish_turn("
                                 f"p_user_id => '{a}', p_turn_id => '{turn_id}', p_status => 'completed', p_result => {ok}, "
                                 f"p_review_status => {kwargs.get('review_status', 'null')}, "
                                 f"p_review_ledger_id => {kwargs.get('review_ledger', 'null')}, "
                                 f"p_review_prompt_sha256 => {kwargs.get('sha', 'null')});")
        assert "invalid agent finish arguments" in error
    assert turn(clean, turn_id, "status") == "running"


def test_a_rejected_transition_still_links_the_review_ledger(clean):
    # 이미 취소된 턴에 completed를 쓰지 못해도 비용과 턴을 잇는다(1차 원장과 같은 규칙).
    a = new_user(clean)
    conversation = new_conversation(clean, a)
    _, turn_id, _, _ = claim(clean, a, conversation)
    assert _finish_review(clean, a, turn_id, "cancelled") == "t"
    second = _ledger(clean, a, "agent_review", "a:agent-review:c:1")
    assert _finish_review(clean, a, turn_id, "completed", result="'{\"state\": \"answered\"}'",
                          review_status="'unchanged'", review_ledger=second) == "f"
    assert turn(clean, turn_id, "status, review_ledger_id, coalesce(review_status, '-')") == f"cancelled|{second}|-"


def test_the_finish_function_keeps_service_role_only(clean):
    grants = sql(clean, """
      select grantee from information_schema.routine_privileges
       where routine_schema = 'public' and routine_name = 'agent_finish_turn' order by grantee;""")
    assert "service_role" in grants.splitlines()
    assert not {"anon", "authenticated", "PUBLIC"} & set(grants.splitlines())
    # 이름 인자 호출(E31 취소)은 새 인자 없이도 된다.
    a = new_user(clean)
    _, turn_id, _, _ = claim(clean, a, new_conversation(clean, a))
    assert last(sql(clean, f"set role service_role; select public.agent_finish_turn(p_user_id => '{a}', "
                           f"p_turn_id => '{turn_id}', p_status => 'cancelled');")) == "t"
