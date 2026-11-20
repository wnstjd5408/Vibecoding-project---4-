"""CS Agent 7일 보관 정리 예약 시험 (MEG-235), pg_cron이 없는 일반 PostgreSQL 17 쪽.

전용·네트워크 격리 일회용 컨테이너(AI_LEDGER_TEST_CONTAINER)에서만 돈다. pg_cron이 없으면 예약 마이그레이션이
오류 없이 건너뛰는지 본다. pg_cron이 있는 Supabase 이미지 시험은 CI가 모으지 않는 agent_purge_cron_local.py에 있다.
"""

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

PLAIN_CONTAINER = os.environ.get("AI_LEDGER_TEST_CONTAINER")
ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "supabase" / "migrations"
SCHEDULE_MIGRATION = MIGRATIONS / "20261118150000_cs_agent_purge_schedule.sql"


def _psql(container, database, query):
    command = ["docker", "exec", "-i", container, "psql", "-U", "postgres", "-d", database, "-v", "ON_ERROR_STOP=1", "-qAt"]
    return subprocess.run(command, input=query, text=True, encoding="utf-8", capture_output=True, timeout=60)


def _require_isolated(container):
    state = subprocess.run(["docker", "inspect", container, "--format", "{{json .HostConfig.NetworkMode}}"],
                           capture_output=True, text=True, check=True)
    assert json.loads(state.stdout) == "none", "only network-isolated test containers are allowed"


# --- pg_cron이 없는 일반 PostgreSQL: 예약을 건너뛴다 ---


@pytest.mark.skipif(not PLAIN_CONTAINER, reason="dedicated local PostgreSQL container not selected")
def test_schedule_migration_is_skipped_without_pg_cron():
    _require_isolated(PLAIN_CONTAINER)

    def run(database, query):
        result = _psql(PLAIN_CONTAINER, database, query)
        assert result.returncode == 0, result.stderr
        return result

    assert run("postgres", "select count(*) from pg_available_extensions where name = 'pg_cron';").stdout.strip() == "0"
    run("postgres", """
      do $$ begin
        if not exists (select from pg_roles where rolname = 'anon') then create role anon; end if;
        if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated; end if;
        if not exists (select from pg_roles where rolname = 'service_role') then create role service_role bypassrls; end if;
      end $$;
    """)
    name = "meg235_" + uuid.uuid4().hex
    run("postgres", f"create database {name};")
    try:
        run(name, "create schema auth; create table auth.users(id uuid primary key); grant usage on schema public to service_role;")
        notices = {}
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            notices[migration.name] = run(name, migration.read_text(encoding="utf-8")).stderr
        # 예약 파일은 오류 없이 끝나고, 건너뛴다는 알림을 남긴다.
        assert "skipping the agent-purge-expired schedule" in notices[SCHEDULE_MIGRATION.name]
        assert run(name, "select count(*) from pg_namespace where nspname = 'cron';").stdout.strip() == "0"
    finally:
        run("postgres", f"drop database {name} with (force);")
