"""CS Agent 7일 보관 정리 예약 시험 (MEG-235), pg_cron이 있는 Supabase Postgres 이미지 쪽. 로컬 전용이다.

CI의 SQL 단계는 일반 PostgreSQL만 띄우므로 이 파일은 test_ 이름을 쓰지 않는다(skip이 있으면 CI 보고서 검사가 실패한다).
파일 경로를 직접 넘겨 실행한다:

    docker run -d --rm --name pgcron-test --network none -e POSTGRES_PASSWORD=<로컬 시험용 아무 값> public.ecr.aws/supabase/postgres:17.11.0.004
    $env:PG_CRON_TEST_CONTAINER = "pgcron-test"
    uv run pytest tests/integration/agent_purge_cron_local.py -v

Supabase 이미지는 pg_cron을 미리 읽어 두고(shared_preload_libraries) postgres 역할이 슈퍼유저가 아니라서
원격 Supabase의 마이그레이션 실행 조건과 가깝다. 예약이 등록되고, 실행하면 7일 지난 대화와 하위 행만 지우며
원장 행은 남는지 본다. 원격 URL이나 자격증명은 받지 않는다. 금액은 시험용 숫자다.
"""

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

CRON_CONTAINER = os.environ.get("PG_CRON_TEST_CONTAINER")
ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "supabase" / "migrations"
SCHEDULE_MIGRATION = MIGRATIONS / "20261118150000_cs_agent_purge_schedule.sql"
JOB = "agent-purge-expired"


def sql(query):
    # Supabase 이미지는 TCP(localhost)로 들어가야 postgres 역할로 접속된다. 연결은 컨테이너 안에서만 열린다.
    result = subprocess.run(["docker", "exec", "-i", CRON_CONTAINER, "psql", "-U", "postgres", "-h", "localhost",
                             "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-qAt"],
                            input=query, text=True, encoding="utf-8", capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _require_isolated(container):
    state = subprocess.run(["docker", "inspect", container, "--format", "{{json .HostConfig.NetworkMode}}"],
                           capture_output=True, text=True, check=True)
    assert json.loads(state.stdout) == "none", "only network-isolated test containers are allowed"


def last(output):
    return output.splitlines()[-1] if output else ""


@pytest.fixture(scope="module")
def cron_db():
    if not CRON_CONTAINER:
        pytest.skip("dedicated Supabase Postgres container not selected")
    _require_isolated(CRON_CONTAINER)
    # pg_cron은 cron.database_name(postgres) DB에만 설치된다. 그래서 이 시험은 컨테이너의 postgres DB를 쓴다.
    # 처음이면 저장소 마이그레이션을 모두 적용하고, 이미 적용된 컨테이너면 예약 파일만 다시 적용한다(재실행 확인).
    if sql("select to_regclass('public.ai_conversations') is null;") == "t":
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            sql(migration.read_text(encoding="utf-8"))
    else:
        sql(SCHEDULE_MIGRATION.read_text(encoding="utf-8"))
    return CRON_CONTAINER


@pytest.fixture
def clean(cron_db):
    sql("delete from public.ai_conversations; delete from public.ai_usage_ledger; delete from public.notes;")
    return cron_db


def new_user():
    user = str(uuid.uuid4())
    sql(f"insert into auth.users (id) values ('{user}'); insert into public.profiles (user_id, role) values ('{user}', 'member');")
    return user


def new_note():
    return last(sql("insert into public.notes (title, body_markdown, is_published) values ('n', 'body', true) returning id;"))


def new_conversation(user, note, idle):
    """note 문맥 대화 하나에 선택 문맥, 완료된 턴, 출처, 원장 행을 하나씩 만든 뒤 마지막 활동을 idle만큼 앞당긴다."""
    conversation = last(sql("insert into public.ai_conversations (user_id, origin, note_id, note_revision) "
                            f"values ('{user}', 'note', {note}, 1) returning id;"))
    sql("insert into public.ai_conversation_selections (conversation_id, note_id, note_revision, start, \"end\", text_snapshot) "
        f"values ('{conversation}', {note}, 1, 0, 4, 'body');")
    row = last(sql("set role service_role; select outcome || ',' || turn_id from public.agent_claim_turn("
                   f"'{user}', '{conversation}', '{uuid.uuid4()}', 'free', '질문', 120);"))
    outcome, turn_id = row.split(",")
    assert outcome == "claimed"
    key = f"{user}:agent:{turn_id}:1"
    assert last(sql("set role service_role; select outcome from public.ai_reserve("
                    f"'{user}', 'agent', '{key}', 1, 0.01, 1, 7, 1, null, null);")) == "reserved"
    assert last(sql("set role service_role; select public.agent_finish_turn("
                    f"'{user}', '{turn_id}', 'completed', null, '{{\"state\": \"answered\"}}', "
                    "'[{\"ref\": 1, \"source_kind\": \"note\", \"source_id\": \"1\", \"cited_revision\": \"1\", "
                    "\"title\": \"t\", \"paragraph_snapshot\": \"p\"}]', "
                    f"(select id from public.ai_usage_ledger where idempotency_key = '{key}'));")) == "t"
    sql(f"update public.ai_conversations set last_active_at = now() - interval '{idle}' where id = '{conversation}';")
    return conversation


def counts():
    return sql("""
      select (select count(*) from public.ai_conversations) || ',' ||
             (select count(*) from public.ai_conversation_selections) || ',' ||
             (select count(*) from public.ai_turns) || ',' ||
             (select count(*) from public.ai_turn_sources) || ',' ||
             (select count(*) from public.ai_usage_ledger);""")


def test_daily_job_is_registered_once(cron_db):
    assert sql(f"select count(*) from cron.job where jobname = '{JOB}';") == "1"
    assert sql(f"select schedule || '|' || command || '|' || username || '|' || database || '|' || active "
               f"from cron.job where jobname = '{JOB}';") == (
        "0 18 * * *|select from pg_catalog.generate_series(1, public.agent_purge_expired())|postgres|postgres|true")

    # 같은 마이그레이션을 다시 실행해도 예약은 하나이고 번호도 그대로다.
    jobid = sql(f"select jobid from cron.job where jobname = '{JOB}';")
    sql(SCHEDULE_MIGRATION.read_text(encoding="utf-8"))
    assert sql(f"select string_agg(jobid::text, ',') from cron.job where jobname = '{JOB}';") == jobid


def test_manual_run_deletes_only_expired_conversations_and_keeps_the_ledger(clean):
    user = new_user()
    note = new_note()
    expired = new_conversation(user, note, "7 days 1 minute")
    kept = new_conversation(user, note, "6 days 23 hours 59 minutes")
    assert counts() == "2,2,2,2,2"

    # 예약에 저장된 명령을 그대로 실행한다. 돌려준 행 수가 지운 대화 수다.
    command = sql(f"select command from cron.job where jobname = '{JOB}';")
    assert sql(f"select count(*) from ({command}) deleted;") == "1"

    assert sql("select id from public.ai_conversations;") == kept
    assert sql(f"select count(*) from public.ai_conversation_selections where conversation_id = '{expired}';") == "0"
    # 대화·선택·턴·출처는 1개씩 남고, 원장 행은 2개 모두 남는다.
    assert counts() == "1,1,1,1,2"
    # 지운 대화의 턴을 가리키던 원장 행은 남아 있다(턴 쪽 외래키만 사라진다).
    assert sql("select count(*) from public.ai_usage_ledger l "
               "where not exists (select from public.ai_turns t where t.ledger_id = l.id);") == "1"

    # 다시 실행하면 지울 것이 없다.
    assert sql(f"select count(*) from ({command}) deleted;") == "0"
    assert counts() == "1,1,1,1,2"


def test_scheduler_runs_the_job_and_records_only_the_deleted_count(clean):
    user = new_user()
    note = new_note()
    for idle in ("8 days", "30 days"):
        new_conversation(user, note, idle)
    kept = new_conversation(user, note, "1 hour")
    jobid = sql(f"select jobid from cron.job where jobname = '{JOB}';")
    started = sql("select clock_timestamp();")

    # 스케줄러가 실제로 이 예약을 돌리는지 보려고 잠시 1초 간격으로 바꿨다가 되돌린다.
    sql(f"select cron.alter_job({jobid}, schedule => '1 seconds');")
    try:
        row = ""
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            row = sql(f"select status || '|' || return_message || '|' || username from cron.job_run_details "
                      f"where jobid = {jobid} and start_time >= '{started}' and status in ('succeeded', 'failed') "
                      "order by start_time limit 1;")
            if row:
                break
            time.sleep(0.5)
    finally:
        sql(f"select cron.alter_job({jobid}, schedule => '0 18 * * *');")

    assert sql(f"select schedule from cron.job where jobid = {jobid};") == "0 18 * * *"
    # 첫 실행이 2개를 지웠고, 실행 기록에는 지운 수만 남는다.
    assert row == "succeeded|2 rows|postgres"
    assert sql("select id from public.ai_conversations;") == kept
    assert counts() == "1,1,1,1,3"
