"""노트 수정·삭제 SQL 함수 시험 (MEG-79, E17·E18). 전용·네트워크 격리 일회용 PostgreSQL 컨테이너에서만 돈다.

원격 URL이나 자격증명은 받지 않는다. 컨테이너는 실행하는 사람이 만들고 지운다(test_ai_ledger_sql.py와 같은 방식).
NOTE_WRITE_TEST_CONTAINER에 컨테이너 이름을 넣지 않으면 건너뛴다.
"""

import json
import os
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

CONTAINER = os.environ.get("NOTE_WRITE_TEST_CONTAINER")
pytestmark = pytest.mark.skipif(not CONTAINER, reason="dedicated local PostgreSQL container not selected")


def _psql(database, query):
    return subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", database, "-v", "ON_ERROR_STOP=1", "-qAt"],
        input=query, text=True, encoding="utf-8", capture_output=True, timeout=60,
    )


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
    name = "meg79_" + uuid.uuid4().hex
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
    sql(database, "delete from public.ai_explanations; delete from public.storage_delete_jobs; "
                  "delete from public.notes; delete from public.terms;")
    return database


def call(db, query):
    """service_role로 부르고 jsonb 결과를 파이썬 값으로 돌려준다."""
    return json.loads(sql(db, f"set role service_role; {query}").splitlines()[-1])


def new_note(db, title="note", body="body", published=True):
    return int(sql(db, f"insert into public.notes (title, body_markdown, is_published) "
                       f"values ('{title}', '{body}', {str(published).lower()}) returning id;").splitlines()[0])


def new_explanation(db, key, note_id):
    term = sql(db, f"insert into public.terms (key, label, source) values ('{key}', '{key}', 'ai') returning id;")
    sql(db, f"insert into public.ai_explanations (term_id, term_key_snapshot, note_id, note_revision, body, model, prompt_version) "
            f"values ({term.splitlines()[0]}, '{key}', {note_id}, 1, 'body', 'm', 'v1');")


def valid_explanations(db):
    return int(sql(db, "select count(*) from public.ai_explanations where invalidated_at is null;"))


def note_row(db, note_id):
    return json.loads(sql(db, f"select row_to_json(n) from public.notes n where id = {note_id};"))


# --- AC-3: 수정·비공개 전환·삭제가 AI 설명을 무효화한다 ---


def test_update_title_or_body_bumps_revision_and_invalidates_explanations(clean):
    note = new_note(clean)
    other = new_note(clean, title="other")
    new_explanation(clean, "t-a", note)
    new_explanation(clean, "t-b", other)

    result = call(clean, f"select public.note_update({note}, '{{\"title\": \"changed\"}}', 1);")

    assert result == {"status": "ok", "id": note, "revision": 2, "is_published": True}
    assert sql(clean, f"select count(*) from public.ai_explanations where note_id = {note} and invalidated_at is not null;") == "1"
    # 다른 노트의 설명은 그대로다.
    assert sql(clean, f"select count(*) from public.ai_explanations where note_id = {other} and invalidated_at is null;") == "1"


def test_update_body_only_also_invalidates(clean):
    note = new_note(clean)
    new_explanation(clean, "t-body", note)

    assert call(clean, f"select public.note_update({note}, '{{\"body_markdown\": \"new body\"}}', null);")["revision"] == 2
    assert valid_explanations(clean) == 0


def test_update_other_columns_keep_revision_and_explanations(clean):
    note = new_note(clean)
    new_explanation(clean, "t-memo", note)

    result = call(clean, f"select public.note_update({note}, '{{\"memo\": \"m\", \"needs_review\": true, \"importance\": \"상\"}}', 1);")

    assert result["revision"] == 1
    assert valid_explanations(clean) == 1
    assert note_row(clean, note)["memo"] == "m"


def test_unpublish_invalidates_but_publish_does_not(clean):
    note = new_note(clean, published=False)
    new_explanation(clean, "t-pub", note)

    # 비공개 노트를 공개로 바꿔도, 비공개를 다시 비공개로 둬도 개정 번호는 그대로이고 설명은 유효하다.
    assert call(clean, f"select public.note_update({note}, '{{\"is_published\": true}}', 1);")["is_published"] is True
    assert valid_explanations(clean) == 1
    assert call(clean, f"select public.note_update({note}, '{{\"is_published\": false}}', 1);") == {
        "status": "ok", "id": note, "revision": 1, "is_published": False}
    # 공개 → 비공개 전환은 개정 번호를 올리지 않아도 무효화한다(S14).
    assert valid_explanations(clean) == 0


def test_update_keeps_unmentioned_columns_and_null_clears(clean):
    note = new_note(clean)
    sql(clean, f"update public.notes set memo = 'keep', study_minutes = 30, studied_on = '2026-11-01' where id = {note};")

    call(clean, f"select public.note_update({note}, '{{\"study_minutes\": null, \"understanding\": 4}}', null);")

    row = note_row(clean, note)
    assert (row["memo"], row["study_minutes"], row["understanding"], row["studied_on"]) == ("keep", None, 4, "2026-11-01")


# --- AC-2: 오래된 expected_revision ---


def test_stale_revision_changes_nothing(clean):
    note = new_note(clean)
    new_explanation(clean, "t-stale", note)
    call(clean, f"select public.note_update({note}, '{{\"title\": \"second\"}}', 1);")
    sql(clean, "update public.ai_explanations set invalidated_at = null;")

    assert call(clean, f"select public.note_update({note}, '{{\"title\": \"third\"}}', 1);") == {"status": "stale_revision"}

    assert note_row(clean, note)["title"] == "second"
    assert valid_explanations(clean) == 1


def test_missing_note_is_not_found(clean):
    assert call(clean, "select public.note_update(999999, '{\"title\": \"x\"}', null);") == {"status": "not_found"}
    assert call(clean, "select public.note_delete(999999, 'bucket');") == {"status": "not_found"}
    assert sql(clean, "select count(*) from public.storage_delete_jobs;") == "0"


def test_concurrent_updates_with_same_expected_revision_only_one_wins(clean):
    note = new_note(clean)

    def update(title):
        return call(clean, f"select public.note_update({note}, '{{\"title\": \"{title}\"}}', 1);")["status"]

    with ThreadPoolExecutor(2) as pool:
        statuses = sorted(pool.map(update, ["a", "b"]))

    assert statuses == ["ok", "stale_revision"]
    assert note_row(clean, note)["revision"] == 2


# --- 삭제 ---


def test_delete_enqueues_jobs_invalidates_and_keeps_explanations(clean):
    note = new_note(clean)
    child = new_note(clean, title="child")
    other = new_note(clean, title="other")
    sql(clean, f"update public.notes set parent_note_id = {note} where id = {child};")
    sql(clean, f"insert into public.note_images (note_id, notion_block_id, storage_path) values "
               f"({note}, 'b1', 'n/{note}/one.png'), ({note}, 'b2', 'n/{note}/two.png'), ({other}, 'b3', 'n/{other}/keep.png');")
    sql(clean, f"insert into public.subjects (name) values ('s{note}'); "
               f"insert into public.note_subjects select {note}, id from public.subjects where name = 's{note}';")
    new_explanation(clean, "t-del", note)
    new_explanation(clean, "t-keep", other)

    result = call(clean, f"select public.note_delete({note}, 'note-images');")

    assert result["status"] == "ok"
    assert sorted(job["path"] for job in result["jobs"]) == [f"n/{note}/one.png", f"n/{note}/two.png"]
    jobs = sql(clean, "select bucket, status, object_path from public.storage_delete_jobs order by object_path;").splitlines()
    assert jobs == [f"note-images|pending|n/{note}/one.png", f"note-images|pending|n/{note}/two.png"]
    assert sql(clean, f"select count(*) from public.notes where id = {note};") == "0"
    assert sql(clean, f"select count(*) from public.note_images where note_id = {note};") == "0"
    assert sql(clean, f"select count(*) from public.note_subjects where note_id = {note};") == "0"
    assert note_row(clean, child)["parent_note_id"] is None
    # 지운 노트의 설명은 행이 남되 무효, 다른 노트의 설명과 이미지는 그대로다.
    assert sql(clean, "select count(*) from public.ai_explanations where note_id is null and invalidated_at is not null;") == "1"
    assert sql(clean, f"select count(*) from public.ai_explanations where note_id = {other} and invalidated_at is null;") == "1"
    assert sql(clean, f"select count(*) from public.note_images where note_id = {other};") == "1"


def test_delete_returns_only_this_calls_jobs(clean):
    note = new_note(clean)
    sql(clean, f"insert into public.note_images (note_id, notion_block_id, storage_path) values ({note}, 'b1', 'same/path.png');")
    # 이전에 실패해 남은 같은 경로의 작업은 이번 호출의 작업으로 돌려주지 않는다.
    sql(clean, "insert into public.storage_delete_jobs (bucket, object_path, created_at) "
               "values ('note-images', 'same/path.png', now() - interval '1 day');")

    result = call(clean, f"select public.note_delete({note}, 'note-images');")

    assert len(result["jobs"]) == 1
    assert sql(clean, "select count(*) from public.storage_delete_jobs;") == "2"


def test_delete_without_images_returns_empty_jobs(clean):
    note = new_note(clean)
    assert call(clean, f"select public.note_delete({note}, 'note-images');") == {"status": "ok", "jobs": []}


def test_only_service_role_can_execute(clean):
    note = new_note(clean)
    for role in ("anon", "authenticated"):
        assert "permission denied" in sql_error(clean, f"set role {role}; select public.note_update({note}, '{{}}', null);")
        assert "permission denied" in sql_error(clean, f"set role {role}; select public.note_delete({note}, 'b');")


def test_update_and_invalidation_roll_back_together(clean):
    note = new_note(clean)
    new_explanation(clean, "rollback-update", note)
    call(clean, f"begin; select public.note_update({note}, '{{\"title\": \"changed\"}}', 1); rollback;")
    assert note_row(clean, note)["revision"] == 1
    assert valid_explanations(clean) == 1


def test_delete_failure_rolls_back_jobs_and_invalidation(clean):
    note = new_note(clean)
    new_explanation(clean, "rollback-delete", note)
    sql(clean, f"insert into public.note_images (note_id, notion_block_id, storage_path) values ({note}, 'b', 'a.png');")
    # 노트 DELETE가 실패하도록 합성 제약을 추가한다. 선행한 job INSERT와 무효화도 취소돼야 한다.
    sql(clean, "create table public.test_delete_blocker (note_id bigint references public.notes(id));")
    try:
        sql(clean, f"insert into public.test_delete_blocker values ({note});")
        assert "foreign key" in sql_error(clean, f"set role service_role; select public.note_delete({note}, 'note-images');")
        assert note_row(clean, note)["id"] == note
        assert valid_explanations(clean) == 1
        assert sql(clean, "select count(*) from public.storage_delete_jobs;") == "0"
        assert sql(clean, f"select count(*) from public.note_images where note_id = {note};") == "1"
    finally:
        sql(clean, "drop table public.test_delete_blocker;")


def test_same_transaction_preexisting_job_is_not_returned(clean):
    note = new_note(clean)
    sql(clean, f"insert into public.note_images (note_id, notion_block_id, storage_path) values ({note}, 'b', 'same.png');")
    result = call(clean, "begin; insert into public.storage_delete_jobs (bucket, object_path) values ('note-images', 'same.png'); "
                  f"select public.note_delete({note}, 'note-images'); commit;")
    assert len(result["jobs"]) == 1
    assert sql(clean, "select count(*) from public.storage_delete_jobs;") == "2"
