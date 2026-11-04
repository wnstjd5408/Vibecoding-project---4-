"""Real migrations in an explicitly selected network-isolated disposable DB."""
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest
from scripts.emphasis_recovery import digest, sql_package, sql_text

CONTAINER = os.environ.get("EMPHASIS_TEST_CONTAINER")
pytestmark = pytest.mark.skipif(not CONTAINER, reason="isolated local PostgreSQL container not selected")


def sql(db, query, fails=False):
    result = subprocess.run(["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", db,
                             "-v", "ON_ERROR_STOP=1", "-qAt"], input=query, text=True, encoding="utf-8",
                            capture_output=True, timeout=60)
    assert (result.returncode != 0) if fails else (result.returncode == 0), result.stderr
    return result.stderr if fails else result.stdout.strip()


@pytest.fixture(scope="module")
def database():
    state = subprocess.run(["docker", "inspect", CONTAINER, "--format", "{{json .HostConfig.NetworkMode}}"], capture_output=True, text=True, check=True)
    assert json.loads(state.stdout) == "none"
    name = "meg197_" + uuid4().hex
    sql("postgres", """do $$ begin
      if not exists(select from pg_roles where rolname='anon') then create role anon; end if;
      if not exists(select from pg_roles where rolname='authenticated') then create role authenticated; end if;
      if not exists(select from pg_roles where rolname='service_role') then create role service_role bypassrls; end if;
    end $$;""")
    sql("postgres", f"create database {name};")
    try:
        sql(name, "create schema auth; create table auth.users(id uuid primary key); grant usage on schema public to service_role;")
        root = Path(__file__).resolve().parents[3]
        for path in sorted((root / "supabase/migrations").glob("*.sql")):
            sql(name, path.read_text(encoding="utf-8"))
        yield name
    finally:
        sql("postgres", f"drop database {name} with (force);")


def note(db):
    before, after = "😀 **용어 **\n\n```mermaid\ngraph LR; A-->B\n```", "😀 **용어** \n\n```mermaid\ngraph LR; A-->B\n```"
    note_id = int(sql(db, f"insert into public.notes(title,body_markdown) values ('Synthetic',{sql_text(before)}) returning id;"))
    return {"id": note_id, "revision": 1, "before": before, "after": after}


def state(db, c):
    return json.loads(sql(db, f"select json_build_array(revision,body_markdown) from public.notes where id={c['id']};"))


def execute(db, changes, rollback=False, fails=False):
    return sql(db, "set role service_role;\n" + sql_package(changes, digest("synthetic"), rollback), fails)


def test_apply_idempotence_backup_restore_and_cache(database):
    c = note(database)
    term = int(sql(database, "insert into public.terms(key,label,source) values ('synthetic','Synthetic','ai') returning id;"))
    sql(database, f"insert into public.ai_explanations(term_id,term_key_snapshot,note_id,note_revision,body,model,prompt_version) values ({term},'synthetic',{c['id']},1,'Synthetic','test','v1');")
    execute(database, [c])
    assert state(database, c) == [2, c["after"]]
    assert sql(database, f"select invalidated_at is not null from public.ai_explanations where term_id={term};") == "t"
    execute(database, [c])
    assert state(database, c)[0] == 2
    execute(database, [c], rollback=True)
    assert state(database, c) == [3, c["before"]]
    execute(database, [c], rollback=True)
    assert state(database, c)[0] == 3


def test_conflict_rolls_back_whole_batch_then_resume(database):
    a, b = note(database), note(database)
    sql(database, f"update public.notes set title='edited' where id={b['id']};")
    assert "conflict" in execute(database, [a, b], fails=True)
    assert state(database, a) == [1, a["before"]]
    # Refresh the second plan from current revision, then simulate interrupted
    # execution where the first independently reviewed group already committed.
    b["revision"] = 2
    execute(database, [a])
    execute(database, [a, b])
    assert state(database, a)[0] == 2
    assert state(database, b)[0] == 3


def test_rollback_does_not_clobber_later_edit_or_missing_note(database):
    c = note(database)
    execute(database, [c])
    sql(database, f"update public.notes set body_markdown='human edit' where id={c['id']};")
    assert "conflict" in execute(database, [c], rollback=True, fails=True)
    assert state(database, c) == [3, "human edit"]
    sql(database, f"delete from public.notes where id={c['id']};")
    assert "missing" in execute(database, [c], fails=True)


def test_invalidation_failure_is_atomic(database):
    c = note(database)
    sql(database, "revoke execute on function public.ai_invalidate_explanations(bigint,bigint,bigint) from service_role;")
    try:
        execute(database, [c], fails=True)
        assert state(database, c) == [1, c["before"]]
    finally:
        sql(database, "grant execute on function public.ai_invalidate_explanations(bigint,bigint,bigint) to service_role;")
