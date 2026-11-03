"""E11 퀴즈 SQL 함수 시험 (MEG-91). 전용·네트워크 격리 일회용 PostgreSQL 컨테이너에서만 돈다.

원격 URL이나 자격증명은 받지 않는다. 컨테이너는 실행하는 사람이 만들고 지운다(test_ai_ledger_sql.py와 같은 방식).
AI_LEDGER_TEST_CONTAINER에 컨테이너 이름을 넣지 않으면 건너뛴다.

확인하는 것: quiz_store_items의 저장·조건부 갱신(stale)·한 트랜잭션 처리·권한, 그리고 AC-2의 DB 쪽 근거
(같은 사용자가 동시에 선점해도 세트는 하나이고 첫 예약도 하나다).
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


@pytest.fixture(scope="module")
def database():
    state = subprocess.run(["docker", "inspect", CONTAINER, "--format", "{{json .HostConfig.NetworkMode}}"],
                           capture_output=True, text=True, check=True)
    assert json.loads(state.stdout) == "none", "only network-isolated test containers are allowed"
    name = "meg91_" + uuid.uuid4().hex
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
    sql(database, "delete from public.ai_usage_ledger; delete from public.quiz_sets; delete from public.terms where key like 'meg91-%';")
    return database


def new_user(database):
    user = str(uuid.uuid4())
    sql(database, f"insert into auth.users values ('{user}'); insert into public.profiles (user_id, role) values ('{user}', 'member');")
    return user


def new_terms(database, count):
    values = ", ".join(f"('meg91-{uuid.uuid4().hex[:8]}', 'T{n}', 'ai')" for n in range(count))
    rows = sql(database, f"insert into public.terms (key, label, source) values {values} returning id;")
    return [int(row) for row in rows.splitlines()[:count]]


def item(term_id, n, reason="viewed", difficulty="중"):
    return {"term_id": term_id, "reason": reason, "question": f"문제 {n}", "answer": f"답 {n}",
            "explanation": f"해설 {n}", "difficulty": difficulty}


def literal(items):
    return "'" + json.dumps(items, ensure_ascii=False).replace("'", "''") + "'::jsonb"


def claim_sql(user, amount="0.1"):
    return ("select outcome || ',' || coalesce(set_id::text, '') || ',' || coalesce(attempt::text, '') "
            f"from public.ai_claim_quiz_set('{user}', date '2026-11-03', date '2026-11-02', {amount}, 1, 7, 0.5, 300, 2);")


def claimed_set(database, user):
    outcome, set_id, attempt = sql(database, "set role service_role; " + claim_sql(user)).splitlines()[-1].split(",")
    assert outcome == "claimed" and attempt == "1"
    return int(set_id)


def store(database, set_id, attempt, items):
    return sql(database, f"set role service_role; select public.quiz_store_items({set_id}, {attempt}, {literal(items)});").splitlines()[-1]


def set_row(database, set_id):
    return sql(database, f"select status || ':' || attempt || ':' || (lease_expires_at is null)::text from public.quiz_sets where id = {set_id};")


def test_store_saves_the_snapshot_and_items_in_order_and_marks_the_set_ready(clean):
    user = new_user(clean)
    terms = new_terms(clean, 3)
    set_id = claimed_set(clean, user)

    result = store(clean, set_id, 1, [item(terms[2], 1, "favorited", "상"), item(terms[0], 2), item(terms[1], 3, "viewed", "하")])

    assert result == "stored"
    assert set_row(clean, set_id) == "ready:1:true"
    assert sql(clean, f"select string_agg(term_id || ':' || question || ':' || difficulty, '|' order by id) from public.quiz_items where set_id = {set_id};") \
        == f"{terms[2]}:문제 1:상|{terms[0]}:문제 2:중|{terms[1]}:문제 3:하"
    assert sql(clean, f"select string_agg(term_id || ':' || reason, '|' order by term_id) from public.quiz_set_terms where set_id = {set_id};") \
        == "|".join(f"{t}:{'favorited' if t == terms[2] else 'viewed'}" for t in sorted(terms))


@pytest.mark.parametrize("case", ["other_attempt", "already_ready", "failed", "unknown_set"])
def test_store_is_stale_and_writes_nothing_unless_the_attempt_matches_a_generating_set(clean, case):
    user = new_user(clean)
    term = new_terms(clean, 1)[0]
    set_id = claimed_set(clean, user)
    attempt = 1
    if case == "other_attempt":
        sql(clean, f"update public.quiz_sets set attempt = 2 where id = {set_id};")
    elif case == "already_ready":
        sql(clean, f"update public.quiz_sets set status = 'ready', lease_expires_at = null where id = {set_id};")
    elif case == "failed":
        sql(clean, f"update public.quiz_sets set status = 'failed', lease_expires_at = null where id = {set_id};")
    else:
        set_id += 1000

    assert store(clean, set_id, attempt, [item(term, 1)]) == "stale"
    assert sql(clean, "select count(*) from public.quiz_items;") == "0"
    assert sql(clean, "select count(*) from public.quiz_set_terms;") == "0"


def test_store_after_the_lease_expired_but_before_anyone_re_claimed_still_saves(clean):
    user = new_user(clean)
    term = new_terms(clean, 1)[0]
    set_id = claimed_set(clean, user)
    sql(clean, f"update public.quiz_sets set lease_expires_at = now() - interval '1 minute' where id = {set_id};")

    assert store(clean, set_id, 1, [item(term, 1)]) == "stored"


def test_a_failure_in_the_middle_leaves_no_partial_rows(clean):
    user = new_user(clean)
    term = new_terms(clean, 1)[0]
    set_id = claimed_set(clean, user)

    # 같은 용어가 두 번 들어가면 quiz_set_terms의 기본 키에서 걸린다. 앞서 넣은 행도 함께 되돌아가야 한다.
    error = sql_error(clean, f"set role service_role; select public.quiz_store_items({set_id}, 1, {literal([item(term, 1), item(term, 2)])});")

    assert "duplicate key" in error
    assert sql(clean, "select count(*) from public.quiz_items;") == "0"
    assert sql(clean, "select count(*) from public.quiz_set_terms;") == "0"
    assert set_row(clean, set_id) == "generating:1:false"


def test_a_missing_field_or_a_bad_difficulty_rolls_everything_back(clean):
    user = new_user(clean)
    terms = new_terms(clean, 2)
    set_id = claimed_set(clean, user)

    for bad in ({**item(terms[1], 2), "question": None}, item(terms[1], 2, difficulty="최상")):
        assert sql_error(clean, f"set role service_role; select public.quiz_store_items({set_id}, 1, {literal([item(terms[0], 1), bad])});")
        assert sql(clean, "select count(*) from public.quiz_items;") == "0"
        assert set_row(clean, set_id) == "generating:1:false"


@pytest.mark.parametrize("items", ["'[]'::jsonb", "'{}'::jsonb", "'null'::jsonb", "null"])
def test_store_rejects_malformed_arguments(clean, items):
    user = new_user(clean)
    set_id = claimed_set(clean, user)

    assert "invalid quiz items arguments" in sql_error(clean, f"set role service_role; select public.quiz_store_items({set_id}, 1, {items});")


def test_store_rejects_more_than_ten_items(clean):
    user = new_user(clean)
    terms = new_terms(clean, 11)
    set_id = claimed_set(clean, user)

    assert "invalid quiz items arguments" in sql_error(
        clean, f"set role service_role; select public.quiz_store_items({set_id}, 1, {literal([item(t, n) for n, t in enumerate(terms)])});")
    assert store(clean, set_id, 1, [item(t, n) for n, t in enumerate(terms[:10])]) == "stored"


def test_store_is_not_executable_by_anon_or_authenticated_roles(clean):
    for role in ("anon", "authenticated"):
        error = sql_error(clean, f"set role {role}; select public.quiz_store_items(1, 1, '[]'::jsonb);")
        assert "permission denied" in error


def test_two_stores_of_the_same_attempt_save_once_and_the_other_is_stale(clean):
    user = new_user(clean)
    terms = new_terms(clean, 2)
    set_id = claimed_set(clean, user)

    def held_open():
        # 저장한 뒤 커밋 전에 2초 붙잡는다. 다른 저장은 세트 행 잠금에서 기다린다.
        return sql(clean, f"set role service_role; begin; select public.quiz_store_items({set_id}, 1, {literal([item(terms[0], 1)])}); "
                          "select pg_sleep(2); commit;").splitlines()

    def second():
        deadline = time.monotonic() + 10
        while sql(clean, f"select count(*) from pg_stat_activity where datname = '{clean}' and wait_event = 'PgSleep';") != "1":
            assert time.monotonic() < deadline, "first transaction never reached its hold"
            time.sleep(0.05)
        return store(clean, set_id, 1, [item(terms[1], 2)])

    with ThreadPoolExecutor(2) as pool:
        first, later = pool.submit(held_open), pool.submit(second)
        first_rows, second_result = first.result(), later.result()

    assert "stored" in first_rows and second_result == "stale"
    assert sql(clean, f"select string_agg(term_id::text, ',') from public.quiz_items where set_id = {set_id};") == str(terms[0])


def test_ac2_two_concurrent_claims_by_the_same_user_make_one_set_and_one_reservation(clean):
    user = new_user(clean)

    def held_open():
        # 선점하고 첫 예약까지 한 뒤 커밋 전에 2초 붙잡는다(AI를 부르는 중인 요청).
        return sql(clean, "set role service_role; begin; " + claim_sql(user) + " select pg_sleep(2); commit;").splitlines()

    def second():
        deadline = time.monotonic() + 10
        while sql(clean, f"select count(*) from pg_stat_activity where datname = '{clean}' and wait_event = 'PgSleep';") != "1":
            assert time.monotonic() < deadline, "first transaction never reached its hold"
            time.sleep(0.05)
        return sql(clean, "set role service_role; " + claim_sql(user)).splitlines()

    with ThreadPoolExecutor(2) as pool:
        first, later = pool.submit(held_open), pool.submit(second)
        rows = first.result() + later.result()

    outcomes = sorted(row.split(",")[0] for row in rows if row.startswith(("claimed,", "generating,", "ready,", "failed,")))
    assert outcomes == ["claimed", "generating"]
    assert sql(clean, "select count(*) from public.quiz_sets;") == "1"
    # 선점에 실패한 요청은 예약을 만들지 않으므로 AI 호출 근거(원장 행)도 하나뿐이다.
    assert sql(clean, "select count(*) from public.ai_usage_ledger where kind = 'quiz';") == "1"


def test_many_simultaneous_claims_make_exactly_one_set_and_one_reservation(clean):
    user = new_user(clean)

    def claim_once(_):
        return sql(clean, "set role service_role; " + claim_sql(user)).splitlines()[-1].split(",")[0]

    with ThreadPoolExecutor(8) as pool:
        outcomes = sorted(pool.map(claim_once, range(8)))

    assert outcomes.count("claimed") == 1
    assert set(outcomes) <= {"claimed", "generating"}
    assert sql(clean, "select count(*) from public.quiz_sets;") == "1"
    assert sql(clean, "select count(*) from public.ai_usage_ledger where kind = 'quiz';") == "1"
