"""Opt-in SQL tests against a dedicated, network-isolated disposable PostgreSQL container.

No remote URL or credentials are accepted. The caller creates/removes the container.
"""

import json
import os
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

CONTAINER = os.environ.get("NOTION_IMPORT_TEST_CONTAINER")
pytestmark = pytest.mark.skipif(not CONTAINER, reason="dedicated local PostgreSQL container not selected")


def sql(database, query):
    result = subprocess.run(["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", database,
                             "-v", "ON_ERROR_STOP=1", "-At"], input=query, text=True, encoding="utf-8",
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture(scope="module")
def database():
    state = subprocess.run(["docker", "inspect", CONTAINER, "--format", "{{json .HostConfig.NetworkMode}}"],
                           capture_output=True, text=True, check=True)
    assert json.loads(state.stdout) == "none", "only network-isolated test containers are allowed"
    name = "meg85_" + uuid4().hex
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


def call(page, subjects="array['Synthetic A','Synthetic B','Synthetic A']"):
    return f"select public.import_notion_note('{page}', 'Synthetic note', 'Synthetic body', '2026-10-30', {subjects});"


def test_atomic_subjects_and_repeated_import(database):
    page = str(uuid4())
    first = json.loads(sql(database, "set role service_role; " + call(page)).splitlines()[-1])
    assert first["created"] is True
    note_id = first["id"]
    assert sql(database, f"select count(*) from public.note_subjects where note_id={note_id};") == "2"
    assert sql(database, f"select is_published from public.notes where id={note_id};") == "f"
    sql(database, f"update public.notes set body_markdown='app edit', is_published=true where id={note_id};")
    second = json.loads(sql(database, "set role service_role; " + call(page, "array['Replacement']")).splitlines()[-1])
    assert second == {"id": note_id, "created": False}
    assert sql(database, f"select body_markdown || ':' || is_published from public.notes where id={note_id};") == "app edit:true"
    assert sql(database, "select count(*) from public.subjects where name='Replacement';") == "0"
    assert sql(database, f"select count(*) from public.note_subjects where note_id={note_id};") == "2"


def test_subject_insert_failure_rolls_back_note(database):
    page = str(uuid4())
    sql(database, """
      create function public.meg85_test_fail() returns trigger language plpgsql as $$
      begin if new.name='Synthetic failure' then raise exception 'synthetic'; end if; return new; end $$;
      create trigger meg85_test_fail before insert on public.subjects for each row execute function public.meg85_test_fail();
    """)
    try:
        sql(database, f"""do $$ begin
          begin perform public.import_notion_note('{page}', 'Synthetic', 'Body', '2026-10-30', array['Synthetic failure']);
            raise exception 'expected failure' using errcode='P0002';
          exception when sqlstate 'P0001' then null; end;
          if exists (select from public.notes where notion_page_id='{page}') then raise exception 'not rolled back'; end if;
        end $$;""")
    finally:
        sql(database, "drop trigger meg85_test_fail on public.subjects; drop function public.meg85_test_fail();")


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_unprivileged_roles_cannot_execute(database, role):
    assert sql(database, f"select has_function_privilege('{role}', 'public.import_notion_note(uuid,text,text,date,text[])', 'execute');") == "f"
    sql(database, f"""set role {role}; do $$ begin
      begin perform public.import_notion_note('{uuid4()}', 'Synthetic', 'Body', '2026-10-30', array[]::text[]);
        raise exception 'unexpected execution'; exception when insufficient_privilege then null; end;
    end $$;""")


def test_concurrent_same_page_one_note(database):
    page = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: json.loads(sql(database, call(page))), range(2)))
    assert sum(r["created"] for r in results) == 1
    assert len({r["id"] for r in results}) == 1


def test_invalid_subject_rejected_without_note(database):
    page = str(uuid4())
    sql(database, f"""do $$ begin
      begin perform public.import_notion_note('{page}', 'Synthetic', 'Body', '2026-10-30', array[null]::text[]);
        raise exception 'unexpected success'; exception when invalid_parameter_value then null; end;
      if exists (select from public.notes where notion_page_id='{page}') then raise exception 'unexpected note'; end if;
    end $$;""")
