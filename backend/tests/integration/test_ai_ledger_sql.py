"""AI 원장 SQL 함수 시험 (MEG-86). 전용·네트워크 격리 일회용 PostgreSQL 컨테이너에서만 돈다.

원격 URL이나 자격증명은 받지 않는다. 컨테이너는 실행하는 사람이 만들고 지운다(docs/notion-import.md와 같은 방식).
AI_LEDGER_TEST_CONTAINER에 컨테이너 이름을 넣지 않으면 건너뛴다.
"""

import json
import os
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest
from botocore.exceptions import ClientError, ConnectionClosedError, ConnectTimeoutError, ReadTimeoutError

from app.ai_ledger import AiBudget, AiLimitReached, SupabaseLedgerStore, run_ai_call
from app.bedrock import AiCallError, BedrockSettings

CONTAINER = os.environ.get("AI_LEDGER_TEST_CONTAINER")
pytestmark = pytest.mark.skipif(not CONTAINER, reason="dedicated local PostgreSQL container not selected")


def sql(database, query):
    result = subprocess.run(["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", database,
                             "-v", "ON_ERROR_STOP=1", "-qAt"], input=query, text=True, encoding="utf-8",
                            capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def sql_error(database, query):
    result = subprocess.run(["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", database,
                             "-v", "ON_ERROR_STOP=1", "-qAt"], input=query, text=True, encoding="utf-8",
                            capture_output=True, timeout=60)
    assert result.returncode != 0, "expected failure"
    return result.stderr


@pytest.fixture(scope="module")
def database():
    state = subprocess.run(["docker", "inspect", CONTAINER, "--format", "{{json .HostConfig.NetworkMode}}"],
                           capture_output=True, text=True, check=True)
    assert json.loads(state.stdout) == "none", "only network-isolated test containers are allowed"
    name = "meg86_" + uuid.uuid4().hex
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


def new_user(database):
    user = str(uuid.uuid4())
    sql(database, f"insert into auth.users values ('{user}'); insert into public.profiles (user_id, role) values ('{user}', 'member');")
    return user


@pytest.fixture
def clean(database):
    """시험마다 원장·퀴즈를 비워 합계가 섞이지 않게 한다."""
    sql(database, "delete from public.ai_usage_ledger; delete from public.quiz_sets;")
    return database


def reserve_sql(user, key, amount, *, daily="1", monthly="7", share="1", limit="null", kind="explain", attempt=1):
    return (f"select outcome || ',' || coalesce(ledger_id::text, '') || ',' || coalesce(ledger_status, '') "
            f"from public.ai_reserve('{user}', '{kind}', '{key}', {attempt}, {amount}, {daily}, {monthly}, {share}, {limit});")


def reserve(database, user, key, amount, **kwargs):
    outcome, ledger_id, status = sql(database, "set role service_role; " + reserve_sql(user, key, amount, **kwargs)).splitlines()[-1].split(",")
    return outcome, ledger_id, status


def ledger(database, column="status"):
    return sql(database, f"select coalesce(string_agg({column}, '|' order by id), '') from public.ai_usage_ledger;")


# --- AC-1: 남은 예산이 예약액보다 적으면 예약 실패, 행 없음 ---


def test_daily_budget_shortfall_rejects_without_a_row(clean):
    a, b = new_user(clean), new_user(clean)

    assert reserve(clean, a, f"{a}:k1:1", "0.6")[0] == "reserved"
    # 남은 하루 예산 0.4 < 예약액 0.5. 다른 사용자도 하루 전체 예산에 같이 걸린다.
    assert reserve(clean, b, f"{b}:k1:1", "0.5") == ("limit_reached", "", "")
    assert ledger(clean, "idempotency_key") == f"{a}:k1:1"
    # 남은 예산 안의 예약은 된다.
    assert reserve(clean, b, f"{b}:k2:1", "0.4")[0] == "reserved"


def test_monthly_budget_counts_earlier_days_of_the_same_kst_month(clean):
    a = new_user(clean)
    sql(clean, f"""insert into public.ai_usage_ledger (user_id, kind, idempotency_key, reserved_usd, actual_usd,
        input_tokens, output_tokens, status, settle_basis, settled_at, kst_date)
      values ('{a}', 'explain', 'old:1', 5, 6.7, 1, 1, 'settled', 'usage', now(),
              date_trunc('month', (now() at time zone 'Asia/Seoul'))::date),
             ('{a}', 'explain', 'lastmonth:1', 50, 50, 1, 1, 'settled', 'usage', now(),
              (date_trunc('month', (now() at time zone 'Asia/Seoul')) - interval '1 day')::date);""")
    # 정산된 행은 실제 금액(6.7)으로 센다. 지난달 행은 세지 않는다. 이번 달 첫날이 오늘이어도 같다(일 예산 9로 넉넉히).
    assert reserve(clean, a, f"{a}:k:1", "0.4", daily="9")[0] == "limit_reached"
    assert reserve(clean, a, f"{a}:k:1", "0.3", daily="9")[0] == "reserved"


def test_user_share_of_daily_budget(clean):
    a, b = new_user(clean), new_user(clean)

    assert reserve(clean, a, f"{a}:k1:1", "0.4", share="0.5")[0] == "reserved"
    assert reserve(clean, a, f"{a}:k2:1", "0.2", share="0.5")[0] == "limit_reached"
    assert reserve(clean, b, f"{b}:k1:1", "0.4", share="0.5")[0] == "reserved"


def test_released_rows_do_not_count_and_settled_rows_use_actual_cost(clean):
    a = new_user(clean)
    _, first, _ = reserve(clean, a, f"{a}:k1:1", "0.9")
    sql(clean, f"set role service_role; select public.ai_settle({first}, 'released', null, null, null);")
    _, second, _ = reserve(clean, a, f"{a}:k2:1", "0.9")
    sql(clean, f"set role service_role; select public.ai_settle({second}, 'usage', 0.1, 10, 5);")

    assert reserve(clean, a, f"{a}:k3:1", "0.85")[0] == "reserved"


def test_daily_count_limit_counts_first_attempts_of_the_kind_only(clean):
    a = new_user(clean)
    assert reserve(clean, a, f"{a}:k1:1", "0.01", limit="2")[0] == "reserved"
    # 호출 안 재시도(attempt 2)와 다른 kind는 횟수에 들지 않는다.
    assert reserve(clean, a, f"{a}:k1:2", "0.01", limit="2", attempt=2)[0] == "reserved"
    assert reserve(clean, a, f"{a}:quiz:1:1:1", "0.01", kind="quiz")[0] == "reserved"
    assert reserve(clean, a, f"{a}:k2:1", "0.01", limit="2")[0] == "reserved"
    assert reserve(clean, a, f"{a}:k3:1", "0.01", limit="2")[0] == "limit_reached"
    # 재시도는 횟수가 찼어도 금액만 보면 된다.
    assert reserve(clean, a, f"{a}:k2:2", "0.01", limit="2", attempt=2)[0] == "reserved"


def test_same_key_returns_existing_row_without_a_new_reservation(clean):
    a = new_user(clean)
    _, first, _ = reserve(clean, a, f"{a}:k1:1", "0.1")

    assert reserve(clean, a, f"{a}:k1:1", "0.1") == ("exists", first, "reserved")
    sql(clean, f"set role service_role; select public.ai_settle({first}, 'reserved_fallback', null, null, null);")
    assert reserve(clean, a, f"{a}:k1:1", "0.1") == ("exists", first, "settled")
    assert sql(clean, "select count(*) from public.ai_usage_ledger;") == "1"


# --- AC-2: 서로 다른 키로 동시에 예약하면 한도 안에서만 성공 ---


def test_two_concurrent_reservations_with_different_keys_only_one_fits(clean):
    a, b = new_user(clean), new_user(clean)

    def held_open():
        # 예약한 뒤 커밋하지 않고 2초 붙잡아 둔다.
        return sql(clean, "set role service_role; begin; " + reserve_sql(a, f"{a}:k1:1", "0.6")
                   + " select pg_sleep(2); commit;").splitlines()

    def second():
        # A가 예약을 마치고 커밋 전 대기에 들어간 것을 확인한 뒤에 예약한다. 두 트랜잭션이 확실히 겹친다.
        deadline = time.monotonic() + 10
        while sql(clean, f"select count(*) from pg_stat_activity where datname = '{clean}' "
                         "and wait_event = 'PgSleep';") != "1":
            assert time.monotonic() < deadline, "first transaction never reached its hold"
            time.sleep(0.05)
        return sql(clean, "set role service_role; " + reserve_sql(b, f"{b}:k1:1", "0.6")).splitlines()

    with ThreadPoolExecutor(2) as pool:
        first, later = pool.submit(held_open), pool.submit(second)
        first_rows, second_rows = first.result(), later.result()

    # psql은 SET·BEGIN·COMMIT 같은 명령 태그도 줄로 내므로 예약 결과 줄만 고른다.
    results = [row for row in first_rows + second_rows if row.startswith(("reserved,", "limit_reached,"))]
    outcomes = sorted(row.split(",")[0] for row in results)
    assert outcomes == ["limit_reached", "reserved"]
    assert sql(clean, "select count(*) from public.ai_usage_ledger;") == "1"


def test_many_concurrent_reservations_never_exceed_the_budget(clean):
    users = [new_user(clean) for _ in range(8)]

    def one(user):
        return sql(clean, "set role service_role; " + reserve_sql(user, f"{user}:k:1", "0.3")).splitlines()[-1].split(",")[0]

    with ThreadPoolExecutor(8) as pool:
        outcomes = list(pool.map(one, users))

    assert outcomes.count("reserved") == 3
    assert sql(clean, "select sum(reserved_usd) from public.ai_usage_ledger;") == "0.900000"


# --- 오래된 예약과 정산 ---


def test_reserved_rows_older_than_ten_minutes_settle_as_fallback_on_next_reservation(clean):
    a = new_user(clean)
    _, old, _ = reserve(clean, a, f"{a}:old:1", "0.2")
    _, fresh, _ = reserve(clean, a, f"{a}:fresh:1", "0.2")
    sql(clean, f"update public.ai_usage_ledger set created_at = now() - interval '11 minutes' where id = {old};")

    reserve(clean, a, f"{a}:next:1", "0.1")

    assert sql(clean, f"select status || ':' || settle_basis || ':' || actual_usd from public.ai_usage_ledger where id = {old};") \
        == "settled:reserved_fallback:0.200000"
    assert sql(clean, f"select status from public.ai_usage_ledger where id = {fresh};") == "reserved"
    # 이미 끝난 행은 다시 정산하지 않는다(비용을 한 번만 센다).
    assert sql(clean, f"set role service_role; select public.ai_settle({old}, 'usage', 0.01, 1, 1);") == "f"


def test_settle_outcomes_and_arguments(clean):
    a = new_user(clean)
    ids = [reserve(clean, a, f"{a}:s{i}:1", "0.1")[1] for i in range(3)]

    assert sql(clean, f"set role service_role; select public.ai_settle({ids[0]}, 'usage', 0.004, 120, 30);") == "t"
    assert sql(clean, f"set role service_role; select public.ai_settle({ids[1]}, 'reserved_fallback', null, null, null);") == "t"
    assert sql(clean, f"set role service_role; select public.ai_settle({ids[2]}, 'released', null, null, null);") == "t"
    assert ledger(clean, "status || ':' || coalesce(settle_basis, '-') || ':' || coalesce(actual_usd::text, '-') || ':' || coalesce(input_tokens::text, '-')") \
        == "settled:usage:0.004000:120|settled:reserved_fallback:0.100000:-|released:-:-:-"
    assert "invalid ai settlement arguments" in sql_error(clean, f"select public.ai_settle({ids[0]}, 'usage', 0.1, null, 1);")
    assert "invalid ai settlement arguments" in sql_error(clean, f"select public.ai_settle({ids[0]}, 'other', null, null, null);")


def test_invalid_reservation_arguments_are_rejected(clean):
    a = new_user(clean)
    for kwargs in ({"kind": "other"}, {"attempt": 0}, {"daily": "0"}, {"share": "1.5"}, {"limit": "0"}):
        assert "invalid ai reservation arguments" in sql_error(clean, reserve_sql(a, f"{a}:x:1", "0.1", **kwargs))
    assert "invalid ai reservation arguments" in sql_error(clean, reserve_sql(a, f"{a}:x:1", "-1"))


def test_only_service_role_can_execute(clean):
    a = new_user(clean)
    for role in ("anon", "authenticated"):
        assert "permission denied" in sql_error(clean, f"set role {role}; " + reserve_sql(a, f"{a}:x:1", "0.1"))
        assert "permission denied" in sql_error(clean, f"set role {role}; select public.ai_settle(1, 'released', null, null, null);")
        assert "permission denied" in sql_error(clean, f"set role {role}; select public.ai_invalidate_explanations(1, null, null);")
        assert "permission denied" in sql_error(
            clean, f"set role {role}; select * from public.ai_claim_quiz_set('{a}', current_date + 1, current_date, 0.1, 1, 7, 0.5, 300, 2);")


# --- 퀴즈 세트 선점 ---


def claim(database, user, amount="0.1", *, daily="1"):
    row = sql(database, "set role service_role; select outcome || ',' || coalesce(set_id::text, '') || ',' || "
              "coalesce(attempt::text, '') || ',' || coalesce(ledger_id::text, '') from public.ai_claim_quiz_set("
              f"'{user}', date '2026-11-03', date '2026-11-02', {amount}, {daily}, 7, 0.5, 300, 2);").splitlines()[-1]
    return row.split(",")


def test_quiz_claim_lease_retry_and_failure(clean):
    a = new_user(clean)

    outcome, set_id, attempt, ledger_id = claim(clean, a)
    assert (outcome, attempt) == ("claimed", "1")
    assert sql(clean, f"select idempotency_key || ':' || kind || ':' || attempt_no from public.ai_usage_ledger where id = {ledger_id};") \
        == f"{a}:quiz:{set_id}:1:1:quiz:1"
    # 선점이 살아 있으면 AI 없이 generating
    assert claim(clean, a) == ["generating", set_id, "1", ""]

    sql(clean, f"update public.quiz_sets set lease_expires_at = now() - interval '1 second' where id = {set_id};")
    outcome, _, attempt, ledger_id = claim(clean, a)
    assert (outcome, attempt) == ("claimed", "2")
    assert sql(clean, f"select idempotency_key from public.ai_usage_ledger where id = {ledger_id};") == f"{a}:quiz:{set_id}:2:1"

    sql(clean, f"update public.quiz_sets set lease_expires_at = now() - interval '1 second' where id = {set_id};")
    assert claim(clean, a) == ["failed", set_id, "2", ""]
    assert sql(clean, f"select status from public.quiz_sets where id = {set_id};") == "failed"
    assert sql(clean, "select count(*) from public.ai_usage_ledger;") == "2"


def test_quiz_claim_returns_ready_sets(clean):
    a = new_user(clean)
    _, set_id, _, _ = claim(clean, a)
    sql(clean, f"update public.quiz_sets set status = 'ready', lease_expires_at = null where id = {set_id};")

    assert claim(clean, a) == ["ready", set_id, "1", ""]


def test_quiz_claim_limit_rolls_back_the_claim(clean):
    a = new_user(clean)

    assert claim(clean, a, "2") == ["limit_reached", "", "", ""]
    assert sql(clean, "select count(*) from public.quiz_sets;") == "0"
    assert sql(clean, "select count(*) from public.ai_usage_ledger;") == "0"

    # 이미 있는 세트의 재선점도 한도로 실패하면 attempt·상태가 그대로다.
    _, set_id, _, _ = claim(clean, a)
    sql(clean, f"update public.quiz_sets set status = 'failed', lease_expires_at = null where id = {set_id};")
    assert claim(clean, a, "2")[0] == "limit_reached"
    assert sql(clean, f"select status || ':' || attempt from public.quiz_sets where id = {set_id};") == "failed:1"


# --- AI 설명 무효화 ---


def test_invalidate_explanations_by_note_term_or_id(clean):
    sql(clean, """
      delete from public.ai_explanations; delete from public.terms where key like 'meg86-%';
      insert into public.notes (title, body_markdown) values ('meg86 note a', 'a'), ('meg86 note b', 'b');
      insert into public.terms (key, label, source) values ('meg86-a', 'A', 'ai'), ('meg86-b', 'B', 'ai'), ('meg86-c', 'C', 'ai');
      insert into public.ai_explanations (term_id, term_key_snapshot, note_id, body, model, prompt_version)
      select t.id, t.key, n.id, 'body', 'm', 'v1'
        from public.terms t join public.notes n
          on (t.key, n.title) in (('meg86-a', 'meg86 note a'), ('meg86-b', 'meg86 note a'), ('meg86-c', 'meg86 note b'));
    """)
    note_a = sql(clean, "select id from public.notes where title = 'meg86 note a';")
    term_c = sql(clean, "select id from public.terms where key = 'meg86-c';")

    assert sql(clean, f"set role service_role; select public.ai_invalidate_explanations({note_a}, null, null);") == "2"
    assert sql(clean, f"set role service_role; select public.ai_invalidate_explanations({note_a}, null, null);") == "0"
    assert sql(clean, f"set role service_role; select public.ai_invalidate_explanations(null, {term_c}, null);") == "1"
    assert sql(clean, "select count(*) from public.ai_explanations where invalidated_at is null;") == "0"
    # 무효화한 용어에 새 설명을 넣을 수 있고, 설명 id 하나만 무효화할 수 있다.
    new_id = sql(clean, f"""insert into public.ai_explanations (term_id, term_key_snapshot, body, model, prompt_version)
                            values ({term_c}, 'meg86-c', 'new', 'm', 'v2') returning id;""").splitlines()[0]
    assert sql(clean, f"set role service_role; select public.ai_invalidate_explanations(null, null, {new_id});") == "1"
    for args in ("null, null, null", f"{note_a}, {term_c}, null"):
        assert "exactly one invalidation target" in sql_error(clean, f"select public.ai_invalidate_explanations({args});")


# --- AC-3: 실패 주입 → 실제 원장 상태 (Python 원장 모듈 + 실제 SQL 함수) ---


class PsqlSupabase:
    """SupabaseClient.rpc를 흉내 내어 컨테이너의 SQL 함수를 service_role로 부른다. PostgREST 응답 모양을 따른다."""

    TYPES = {"p_user_id": "uuid", "p_reserved_usd": "numeric", "p_daily_budget_usd": "numeric",
             "p_monthly_budget_usd": "numeric", "p_user_daily_share": "numeric", "p_actual_usd": "numeric",
             "p_quiz_date": "date", "p_source_date": "date"}

    def __init__(self, database):
        self.database = database

    def _literal(self, name, value):
        if value is None:
            return "null"
        if isinstance(value, int):
            return str(value)
        text = str(value).replace("'", "''")
        return f"'{text}'::{self.TYPES.get(name, 'text')}"

    def rpc(self, name, payload):
        args = ", ".join(f"{key} => {self._literal(key, value)}" for key, value in payload.items())
        if name == "ai_settle":
            query = f"select to_json(public.{name}({args}));"
        else:
            query = f"select coalesce(json_agg(t), '[]'::json) from public.{name}({args}) t;"
        return json.loads(sql(self.database, "set role service_role; " + query).splitlines()[-1])


class SequenceBedrock:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    def converse(self, **_):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


BUDGET = AiBudget(daily_usd=Decimal("1"), monthly_usd=Decimal("7"),
                  input_usd_per_mtok=Decimal("2"), output_usd_per_mtok=Decimal("8"))


def call(database, user, bedrock, key):
    store = SupabaseLedgerStore(PsqlSupabase(database))
    return run_ai_call(store, BedrockSettings(auth_mode="api_key"), BUDGET, user_id=user, kind="explain",
                       request_key=f"{user}:{key}", prompt="자료: 문장", client_factory=lambda *a: bedrock)


@pytest.fixture
def local_env(monkeypatch):
    for name in ("VERCEL", "VERCEL_ENV", "VERCEL_TARGET_ENV", "VERCEL_GIT_COMMIT_REF"):
        monkeypatch.delenv(name, raising=False)


def test_injected_failures_leave_the_specified_ledger_states(clean, local_env):
    a = new_user(clean)
    timeout = ReadTimeoutError(endpoint_url="https://bedrock-runtime.example")

    # 시간 초과 두 번: 두 시도 모두 예약액 그대로 정산(reserved_fallback), 502
    bedrock = SequenceBedrock(timeout, timeout)
    with pytest.raises(AiCallError):
        call(clean, a, bedrock, "timeout")
    assert bedrock.calls == 2

    # usage 없는 성공: 결과는 정상, 원장은 reserved_fallback(토큰 수 비움)
    outcome = call(clean, a, SequenceBedrock({"output": {"message": {"content": [{"text": "ok"}]}}, "stopReason": "end_turn"}), "nousage")
    assert outcome.text == "ok"

    # content 없음(usage 있음): usage로 정산, 재시도 없음, 502
    bedrock = SequenceBedrock({"stopReason": "end_turn", "usage": {"inputTokens": 40, "outputTokens": 0}})
    with pytest.raises(AiCallError) as error:
        call(clean, a, bedrock, "nocontent")
    assert (error.value.code, bedrock.calls) == ("NoContent", 1)

    rows = sql(clean, """select string_agg(idempotency_key || '=' || status || ':' || coalesce(settle_basis, '-') || ':'
                          || coalesce(input_tokens::text, '-') || ':' || actual_usd, '|' order by id)
                         from public.ai_usage_ledger;""")
    reserved = BUDGET.reserve_amount("자료: 문장", 600)
    assert rows.split("|") == [
        f"{a}:timeout:1=settled:reserved_fallback:-:{reserved}",
        f"{a}:timeout:2=settled:reserved_fallback:-:{reserved}",
        f"{a}:nousage:1=settled:reserved_fallback:-:{reserved}",
        f"{a}:nocontent:1=settled:usage:40:{BUDGET.cost(40, 0)}",
    ]


def test_connection_and_auth_failures_release_and_leave_every_limit_untouched(clean, local_env):
    """MEG-145: 요청이 닿지 않은 연결 실패와 인증 실패는 예약을 풀어 일·월 합계·사용자 몫·횟수에 남지 않는다."""
    a = new_user(clean)
    never_sent = ConnectTimeoutError(endpoint_url="https://bedrock-runtime.example")
    denied = ClientError({"Error": {"Code": "ExpiredTokenException", "Message": "x"}}, "Converse")

    # 연결 실패 두 번(호출 안 재시도 포함), 인증 실패 한 번. 모두 502
    for key, failures in (("conn", [never_sent, never_sent]), ("auth", [denied])):
        bedrock = SequenceBedrock(*failures)
        with pytest.raises(AiCallError):
            call(clean, a, bedrock, key)
        assert bedrock.calls == len(failures)

    rows = sql(clean, """select string_agg(idempotency_key || '=' || status || ':' || coalesce(settle_basis, '-'), '|' order by id)
                         from public.ai_usage_ledger;""")
    assert rows.split("|") == [
        f"{a}:conn:1=released:-",
        f"{a}:conn:2=released:-",
        f"{a}:auth:1=released:-",
    ]
    # 합계에 남은 금액이 없고, 첫 시도 횟수를 1회로 제한해도 다음 예약이 통과한다
    assert sql(clean, "select count(*) from public.ai_usage_ledger where status in ('reserved', 'settled');") == "0"
    outcome = sql(clean, f"""select outcome from public.ai_reserve('{a}', 'explain', '{a}:next:1', 1, 0.001, 1, 7, 0.5, 1);""")
    assert outcome == "reserved"


def test_connection_closed_after_sending_still_counts_as_billed(clean, local_env):
    """요청이 나갔을 수 있는 실패는 이전처럼 예약액 그대로 정산한다(과금으로 센다)."""
    a = new_user(clean)
    closed = ConnectionClosedError(endpoint_url="https://bedrock-runtime.example")

    with pytest.raises(AiCallError):
        call(clean, a, SequenceBedrock(closed, closed), "closed")

    reserved = BUDGET.reserve_amount("자료: 문장", 600)
    rows = sql(clean, """select string_agg(idempotency_key || '=' || status || ':' || coalesce(settle_basis, '-') || ':' || actual_usd,
                         '|' order by id) from public.ai_usage_ledger;""")
    assert rows.split("|") == [
        f"{a}:closed:1=settled:reserved_fallback:{reserved}",
        f"{a}:closed:2=settled:reserved_fallback:{reserved}",
    ]


def test_budget_shortfall_through_the_python_layer_makes_no_ai_call(clean, local_env):
    a = new_user(clean)
    sql(clean, f"""insert into public.ai_usage_ledger (user_id, kind, idempotency_key, reserved_usd, kst_date)
                   values ('{a}', 'explain', 'busy:1', 0.999, (now() at time zone 'Asia/Seoul')::date);""")
    bedrock = SequenceBedrock()

    with pytest.raises(AiLimitReached):
        call(clean, a, bedrock, "over")

    assert bedrock.calls == 0
    assert sql(clean, "select count(*) from public.ai_usage_ledger;") == "1"
