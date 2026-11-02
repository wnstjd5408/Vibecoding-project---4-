"""운영자 사전 SQL 함수 시험 (MEG-81 E20~E23). 전용·네트워크 격리 일회용 PostgreSQL 컨테이너에서만 돈다.

원격 URL이나 자격증명은 받지 않는다. 컨테이너는 실행하는 사람이 만들고 지운다(test_ai_ledger_sql.py와 같은 방식).
GLOSSARY_SQL_TEST_CONTAINER에 컨테이너 이름을 넣지 않으면 건너뛴다. 예:
    docker run -d --name meg81-sql-test --network none -e POSTGRES_PASSWORD=<임의 값> postgres:17
"""

import json
import os
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

CONTAINER = os.environ.get("GLOSSARY_SQL_TEST_CONTAINER")
pytestmark = pytest.mark.skipif(not CONTAINER, reason="dedicated local PostgreSQL container not selected")
BUCKET = "glossary-images"


def run_sql(database, query, *, expect_ok=True):
    result = subprocess.run(["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", database,
                             "-v", "ON_ERROR_STOP=1", "-qAt"], input=query, text=True, encoding="utf-8",
                            capture_output=True, timeout=60)
    if expect_ok:
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()
    assert result.returncode != 0, "expected failure"
    return result.stderr


def sql(database, query):
    return run_sql(database, query)


def as_service(query):
    """FastAPI가 쓰는 service_role 권한으로 실행한다."""
    return f"set role service_role; {query}"


@pytest.fixture(scope="module")
def database():
    state = subprocess.run(["docker", "inspect", CONTAINER, "--format", "{{json .HostConfig.NetworkMode}}"],
                           capture_output=True, text=True, check=True)
    assert json.loads(state.stdout) == "none", "only network-isolated test containers are allowed"
    name = "meg81_" + uuid.uuid4().hex
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
    sql(database, """
      delete from public.ai_explanations; delete from public.quiz_sets; delete from public.storage_delete_jobs;
      delete from public.term_views; delete from public.favorites; delete from public.favorite_events;
      delete from public.terms; delete from public.profiles; delete from auth.users;
    """)
    return database


def new_user(database, role="operator"):
    user = str(uuid.uuid4())
    sql(database, f"insert into auth.users values ('{user}'); insert into public.profiles (user_id, role) values ('{user}', '{role}');")
    return user


def upsert(database, key, label, body, user):
    out = sql(database, as_service(
        f"select public.glossary_upsert_entry('{key}', '{label}', '{body}', '{user}')::text;"))
    return json.loads(out)


def add_ai_explanation(database, term_id, key):
    return int(sql(database, f"""
      insert into public.ai_explanations (term_id, term_key_snapshot, body, model, prompt_version)
      values ({term_id}, '{key}', 'synthetic ai body', 'test-model', 'v1') returning id;
    """))


def valid_ai_count(database, term_id):
    return int(sql(database, f"select count(*) from public.ai_explanations where term_id = {term_id} and invalidated_at is null;"))


# --- E20 / AC-2: 사전 등록이 AI 설명보다 우선한다 ---


def test_new_key_creates_glossary_term_and_entry(db):
    user = new_user(db)
    result = upsert(db, "exampleterm", "ExampleTerm", "synthetic body", user)
    assert result["created"] is True and result["key"] == "exampleterm" and result["label"] == "ExampleTerm"
    row = sql(db, f"select t.source || '|' || e.body_markdown || '|' || e.updated_by from public.terms t "
                  f"join public.glossary_entries e on e.term_id = t.id where t.id = {result['id']};")
    assert row == f"glossary|synthetic body|{user}"


def test_ai_term_becomes_glossary_and_its_explanations_are_invalidated(db):
    user = new_user(db)
    term_id = int(sql(db, "insert into public.terms (key, label, source) values ('aiterm', 'aiterm', 'ai') returning id;"))
    # 용어당 유효한 설명은 하나다(ai_explanations_active_term_idx). 이미 무효화된 설명 하나를 더 둔다.
    old = add_ai_explanation(db, term_id, "aiterm")
    sql(db, f"update public.ai_explanations set invalidated_at = now() - interval '1 day' where id = {old};")
    add_ai_explanation(db, term_id, "aiterm")
    other = int(sql(db, "insert into public.terms (key, label, source) values ('other', 'other', 'ai') returning id;"))
    add_ai_explanation(db, other, "other")

    result = upsert(db, "aiterm", "AiTerm", "dictionary body", user)

    assert result == {"id": term_id, "key": "aiterm", "label": "AiTerm", "created": True}
    assert sql(db, f"select source from public.terms where id = {term_id};") == "glossary"
    assert valid_ai_count(db, term_id) == 0
    # 무효화는 행을 지우지 않는다. 다른 용어의 설명은 그대로다.
    assert sql(db, f"select count(*) from public.ai_explanations where term_id = {term_id};") == "2"
    assert valid_ai_count(db, other) == 1


def test_second_upsert_updates_and_reports_not_created(db):
    user = new_user(db)
    first = upsert(db, "exampleterm", "ExampleTerm", "old", user)
    second = upsert(db, "exampleterm", "EXAMPLETERM", "new", user)
    assert second == {"id": first["id"], "key": "exampleterm", "label": "EXAMPLETERM", "created": False}
    assert sql(db, f"select body_markdown from public.glossary_entries where term_id = {first['id']};") == "new"
    assert sql(db, "select count(*) from public.terms;") == "1"


def test_unnormalized_key_is_rejected_by_the_schema(db):
    user = new_user(db)
    error = run_sql(db, as_service(f"select public.glossary_upsert_entry('Upper', 'Upper', '', '{user}');"),
                    expect_ok=False)
    assert "terms_key_normalized_check" in error


def test_concurrent_upserts_of_the_same_key_make_one_term(db):
    user = new_user(db)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda i: upsert(db, "race", f"Race{i}", f"b{i}", user), range(6)))
    assert len({r["id"] for r in results}) == 1
    assert sum(r["created"] for r in results) == 1
    assert sql(db, "select count(*) from public.glossary_entries;") == "1"


# --- E21 / AC-3: 사전 설명·이미지만 지우고 용어와 사용자 데이터는 남는다 ---


def seed_glossary_with_user_data(db):
    user = new_user(db, "member")
    operator = new_user(db)
    term_id = upsert(db, "keepme", "KeepMe", "body", operator)["id"]
    sql(db, f"""
      insert into public.glossary_images (term_id, storage_path, alt) values
        ({term_id}, 'terms/{term_id}/a.png', null), ({term_id}, 'terms/{term_id}/b.png', 'b');
      insert into public.favorites (user_id, term_id) values ('{user}', {term_id});
      insert into public.favorite_events (user_id, term_id, study_date) values ('{user}', {term_id}, '2026-10-30');
      insert into public.term_views (user_id, term_id, study_date) values ('{user}', {term_id}, '2026-10-30');
      insert into public.quiz_sets (user_id, quiz_date, source_date) values ('{user}', '2026-10-31', '2026-10-30');
      insert into public.quiz_set_terms (set_id, term_id, reason)
        select id, {term_id}, 'favorited' from public.quiz_sets where user_id = '{user}';
    """)
    return term_id


def test_delete_entry_keeps_term_and_user_data_and_sets_source_ai(db):
    term_id = seed_glossary_with_user_data(db)

    out = json.loads(sql(db, as_service(f"select public.glossary_delete_entry({term_id}, '{BUCKET}')::text;")))

    assert [job["object_path"] for job in out["jobs"]] == [f"terms/{term_id}/a.png", f"terms/{term_id}/b.png"]
    assert sql(db, f"select source from public.terms where id = {term_id};") == "ai"
    assert sql(db, f"select count(*) from public.glossary_entries where term_id = {term_id};") == "0"
    assert sql(db, f"select count(*) from public.glossary_images where term_id = {term_id};") == "0"
    counts = sql(db, f"""select (select count(*) from public.favorites where term_id = {term_id}) || ',' ||
                               (select count(*) from public.favorite_events where term_id = {term_id}) || ',' ||
                               (select count(*) from public.term_views where term_id = {term_id}) || ',' ||
                               (select count(*) from public.quiz_set_terms where term_id = {term_id});""")
    assert counts == "1,1,1,1"
    jobs = sql(db, "select bucket || ':' || object_path || ':' || status from public.storage_delete_jobs order by id;")
    assert jobs.splitlines() == [f"{BUCKET}:terms/{term_id}/a.png:pending", f"{BUCKET}:terms/{term_id}/b.png:pending"]


def test_delete_entry_of_ai_or_missing_term_changes_nothing(db):
    term_id = int(sql(db, "insert into public.terms (key, label, source) values ('aionly', 'aionly', 'ai') returning id;"))
    assert sql(db, as_service(f"select public.glossary_delete_entry({term_id}, '{BUCKET}') is null;")) == "t"
    assert sql(db, as_service(f"select public.glossary_delete_entry(987654, '{BUCKET}') is null;")) == "t"
    assert sql(db, "select count(*) from public.storage_delete_jobs;") == "0"


def test_entry_can_be_registered_again_after_delete(db):
    term_id = seed_glossary_with_user_data(db)
    sql(db, as_service(f"select public.glossary_delete_entry({term_id}, '{BUCKET}');"))
    again = upsert(db, "keepme", "KeepMe", "again", new_user(db))
    assert again["id"] == term_id and again["created"] is True


# --- E22·E23 ---


def test_add_image_inserts_row_and_removes_its_upload_job(db):
    term_id = upsert(db, "pic", "Pic", "", new_user(db))["id"]
    job = sql(db, f"insert into public.storage_delete_jobs (bucket, object_path) values ('{BUCKET}', 'terms/{term_id}/x.png') returning id;")
    image_id = sql(db, as_service(f"select public.glossary_add_image({term_id}, 'terms/{term_id}/x.png', 'alt', {job});"))
    assert sql(db, f"select term_id || ':' || storage_path || ':' || alt from public.glossary_images where id = {image_id};") \
        == f"{term_id}:terms/{term_id}/x.png:alt"
    assert sql(db, "select count(*) from public.storage_delete_jobs;") == "0"


def test_add_image_to_term_without_entry_returns_null_and_keeps_job(db):
    term_id = int(sql(db, "insert into public.terms (key, label, source) values ('noentry', 'noentry', 'ai') returning id;"))
    job = sql(db, f"insert into public.storage_delete_jobs (bucket, object_path) values ('{BUCKET}', 'terms/{term_id}/y.png') returning id;")
    assert sql(db, as_service(f"select public.glossary_add_image({term_id}, 'terms/{term_id}/y.png', null, {job}) is null;")) == "t"
    assert sql(db, "select count(*) from public.glossary_images;") == "0"
    assert sql(db, f"select status from public.storage_delete_jobs where id = {job};") == "pending"


def test_delete_image_checks_owner_term_and_records_a_job(db):
    operator = new_user(db)
    term_id = upsert(db, "one", "One", "", operator)["id"]
    other_id = upsert(db, "two", "Two", "", operator)["id"]
    image_id = sql(db, f"insert into public.glossary_images (term_id, storage_path) values ({term_id}, 'terms/{term_id}/z.png') returning id;")

    assert sql(db, as_service(f"select public.glossary_delete_image({other_id}, {image_id}, '{BUCKET}') is null;")) == "t"
    out = json.loads(sql(db, as_service(f"select public.glossary_delete_image({term_id}, {image_id}, '{BUCKET}')::text;")))

    assert out["object_path"] == f"terms/{term_id}/z.png"
    assert sql(db, "select count(*) from public.glossary_images;") == "0"
    assert sql(db, f"select status from public.storage_delete_jobs where id = {out['job_id']};") == "pending"


CALLS = [
    "select public.glossary_upsert_entry('k', 'k', '', '00000000-0000-0000-0000-000000000000')",
    f"select public.glossary_delete_entry(1, '{BUCKET}')",
    "select public.glossary_add_image(1, 'p', null, 1)",
    f"select public.glossary_delete_image(1, 1, '{BUCKET}')",
]


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize("call", CALLS, ids=["upsert", "delete_entry", "add_image", "delete_image"])
def test_only_service_role_can_execute(db, role, call):
    error = run_sql(db, f"set role {role}; {call};", expect_ok=False)
    assert "permission denied" in error


# --- 리뷰 지적 회귀 ---


def test_add_image_fails_and_rolls_back_when_the_upload_job_is_gone_or_mismatched(db):
    term_id = upsert(db, "guard", "Guard", "", new_user(db))["id"]
    done = sql(db, f"insert into public.storage_delete_jobs (bucket, object_path, status) values ('{BUCKET}', 'terms/{term_id}/d.png', 'done') returning id;")
    pending = sql(db, f"insert into public.storage_delete_jobs (bucket, object_path) values ('{BUCKET}', 'terms/{term_id}/other.png') returning id;")
    for job, path in ((done, f"terms/{term_id}/d.png"), (pending, f"terms/{term_id}/d.png"), (999999, f"terms/{term_id}/d.png")):
        error = run_sql(db, as_service(f"select public.glossary_add_image({term_id}, '{path}', null, {job});"), expect_ok=False)
        assert "missing or already processed" in error
    assert sql(db, "select count(*) from public.glossary_images;") == "0"
    assert sql(db, f"select status from public.storage_delete_jobs where id = {pending};") == "pending"


def test_delete_entry_takes_locks_in_the_same_order_as_upsert(db):
    """E20은 terms → glossary_entries 순서로 잠근다. E21이 반대로 잡으면 서로를 기다린다(교착).

    세션 1이 E20의 첫 단계(terms 행 잠금)를 흉내 내 쥐고 있는 동안 E21을 부르고, 세션 1이 E20의 둘째 단계
    (glossary_entries 갱신)로 넘어간다. E21이 terms를 먼저 잠그면 E21이 기다리기만 하고 둘 다 끝난다.
    """
    term_id = upsert(db, "ordering", "Ordering", "", new_user(db))["id"]

    def psql_process(query):
        return subprocess.Popen(["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", db,
                                 "-v", "ON_ERROR_STOP=1", "-qAt"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8")

    holder = psql_process(None)
    deleter = psql_process(None)
    holder.stdin.write(f"""begin;
      update public.terms set label = label where id = {term_id};
      select pg_sleep(2.5);
      update public.glossary_entries set body_markdown = 'x' where term_id = {term_id};
      commit;""")
    holder.stdin.close()
    time.sleep(1)
    deleter.stdin.write(as_service(f"select public.glossary_delete_entry({term_id}, '{BUCKET}');"))
    deleter.stdin.close()
    results = {name: (proc.wait(timeout=60), proc.stderr.read()) for name, proc in (("holder", holder), ("deleter", deleter))}
    assert results["holder"][0] == 0 and results["deleter"][0] == 0, results
    assert not any("deadlock" in err for _, err in results.values())


def test_concurrent_upsert_delete_and_add_image_keep_a_consistent_state(db):
    operator = new_user(db)
    term_id = upsert(db, "contend", "Contend", "", operator)["id"]

    def work(i):
        if i % 3 == 0:
            return sql(db, as_service(f"select public.glossary_upsert_entry('contend', 'Contend', 'b{i}', '{operator}');"))
        if i % 3 == 1:
            return sql(db, as_service(f"select public.glossary_delete_entry({term_id}, '{BUCKET}');"))
        job = sql(db, f"insert into public.storage_delete_jobs (bucket, object_path) values ('{BUCKET}', 'terms/{term_id}/{i}.png') returning id;")
        return sql(db, as_service(f"select public.glossary_add_image({term_id}, 'terms/{term_id}/{i}.png', null, {job});"))

    with ThreadPoolExecutor(max_workers=9) as pool:
        list(pool.map(work, range(18)))
    # 사전 설명이 없는데 이미지가 남는 일은 없다(E21과 E22의 잠금이 순서를 정한다).
    assert sql(db, f"""select exists (select 1 from public.glossary_images i
                                       where i.term_id = {term_id}
                                         and not exists (select 1 from public.glossary_entries e where e.term_id = i.term_id));""") == "f"
