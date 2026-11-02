"""AI 한도 예약 → 호출 → 정산 (MEG-86). 네트워크·DB 없이 가짜 원장과 가짜 Bedrock으로 돈다.

SQL 함수 자체의 한도·동시성은 tests/integration/test_ai_ledger_sql.py가 실제 PostgreSQL로 확인한다.
"""

import io
import json
from dataclasses import dataclass, field
from decimal import Decimal

import pytest
from botocore.awsrequest import AWSResponse
from botocore.exceptions import ClientError, ReadTimeoutError

from app import ai_ledger
from app.ai_ledger import (
    AiBudget,
    AiLimitReached,
    AiSettlementFailed,
    LedgerKeyExists,
    Reservation,
    SupabaseLedgerStore,
    api_error_for,
    estimate_input_tokens,
    run_ai_call,
)
from app.bedrock import AiCallError, AiConfigError, BedrockSettings
from app.errors import CATALOG
from app.supabase import SupabaseUnavailable

USER = "00000000-0000-4000-8000-000000000001"
BUDGET = AiBudget(
    daily_usd=Decimal("0.9"),
    monthly_usd=Decimal("7"),
    input_usd_per_mtok=Decimal("2"),
    output_usd_per_mtok=Decimal("8"),
)
API_KEY = BedrockSettings(auth_mode="api_key")
OK = {
    "output": {"message": {"content": [{"text": "설명"}]}},
    "stopReason": "end_turn",
    "usage": {"inputTokens": 100, "outputTokens": 50},
}


@dataclass
class FakeStore:
    """예약 결과를 미리 정해 두는 가짜 원장. 호출 기록만 남긴다."""

    limit_from_attempt: int | None = None
    existing_status: str | None = None
    settle_fails: bool = False
    reserve_down: bool = False
    reserved: list[dict] = field(default_factory=list)
    settled: list[tuple] = field(default_factory=list)

    def reserve(self, **kwargs):
        if self.reserve_down:
            raise SupabaseUnavailable("status 503")
        if self.existing_status:
            raise LedgerKeyExists(self.existing_status)
        if self.limit_from_attempt is not None and kwargs["attempt_no"] >= self.limit_from_attempt:
            raise AiLimitReached()
        self.reserved.append(kwargs)
        return Reservation(ledger_id=100 + len(self.reserved), attempt_no=kwargs["attempt_no"])

    def settle(self, ledger_id, outcome, **values):
        if self.settle_fails:
            raise SupabaseUnavailable("status 503")
        self.settled.append((ledger_id, outcome, values))
        return True


class FakeBedrock:
    """응답이나 예외를 차례로 돌려준다. 호출 수를 센다."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    def converse(self, **kwargs):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class RawBody(io.BytesIO):
    def stream(self, *args, **kwargs):
        yield self.getvalue()


def client_error(code):
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "Converse")


def timeout():
    return ReadTimeoutError(endpoint_url="https://bedrock-runtime.example")


def run(store, bedrock, *, settings=API_KEY, **kwargs):
    """가짜 Bedrock으로 run_ai_call을 부른다. 클라이언트를 만든 횟수는 run.factory_calls에 남긴다."""
    run.factory_calls = []

    def factory(settings, token):
        run.factory_calls.append(settings)
        return bedrock

    params = dict(kind="explain", request_key=f"{USER}:key-1", prompt="자료: 문장")
    params.update(kwargs)
    return run_ai_call(store, settings, BUDGET, user_id=USER, client_factory=factory, **params)


@pytest.fixture(autouse=True)
def local_environment(monkeypatch):
    for name in ("VERCEL", "VERCEL_ENV", "VERCEL_TARGET_ENV", "VERCEL_GIT_COMMIT_REF"):
        monkeypatch.delenv(name, raising=False)


# --- 예산 설정 ---


def test_budget_comes_from_env_and_needs_every_value():
    env = {
        "AI_DAILY_BUDGET_USD": "1.5",
        "AI_MONTHLY_BUDGET_USD": "20",
        "AI_INPUT_USD_PER_MTOK": "0.1",
        "AI_OUTPUT_USD_PER_MTOK": "0.4",
    }

    budget = AiBudget.from_env(env)

    assert budget.daily_usd == Decimal("1.5")
    for name in env:
        for bad in ("", "abc", "0", "-1", "NaN", "Infinity"):
            with pytest.raises(AiConfigError) as error:
                AiBudget.from_env({**env, name: bad})
            assert name in str(error.value)
            assert bad not in str(error.value) or bad == ""


def test_cost_rounds_up_to_micro_dollars():
    assert BUDGET.cost(100, 50) == Decimal("0.000600")
    assert BUDGET.cost(1, 0) == Decimal("0.000002")
    assert BUDGET.cost(0, 0) == Decimal("0")


def test_input_estimate_is_conservative_for_korean_and_english():
    assert estimate_input_tokens("") == 64
    # 한글 한 글자 3바이트 → 1.5토큰, 영문 한 글자 → 0.5토큰
    assert estimate_input_tokens("가" * 100) == 150 + 64
    assert estimate_input_tokens("a" * 100) == 50 + 64


def test_reserve_amount_uses_estimate_plus_output_cap():
    prompt = "가" * 100
    assert BUDGET.reserve_amount(prompt, 600) == BUDGET.cost(214, 600)


# --- AC-1: 한도 예약 실패면 AI 호출 0건 ---


def test_limit_reached_makes_no_ai_call_and_no_settlement():
    store = FakeStore(limit_from_attempt=1)
    bedrock = FakeBedrock(OK)

    with pytest.raises(AiLimitReached) as error:
        run(store, bedrock)

    assert bedrock.calls == 0
    assert run.factory_calls == []
    assert store.settled == []
    api_error = api_error_for(error.value)
    assert CATALOG[(api_error.code, api_error.detail)][0] == 429
    assert api_error.code == "ai_limit_reached"


def test_config_errors_stop_before_reservation(monkeypatch):
    store = FakeStore()
    bedrock = FakeBedrock(OK)

    with pytest.raises(AiConfigError) as error:
        run(store, bedrock, settings=BedrockSettings(role_arn="role"), oidc_token=None)

    assert store.reserved == [] and bedrock.calls == 0
    assert api_error_for(error.value).code == "internal_error"


def test_blocked_environment_stops_before_reservation(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", "preview")
    store = FakeStore()
    bedrock = FakeBedrock(OK)

    with pytest.raises(AiCallError) as error:
        run(store, bedrock)

    assert error.value.step == "environment"
    assert store.reserved == [] and bedrock.calls == 0


def test_reservation_db_outage_before_the_call_stays_a_db_outage():
    """AI 호출 전의 DB 장애는 공통 처리기가 503으로 바꾼다(1.4.4)."""
    store = FakeStore(reserve_down=True)
    bedrock = FakeBedrock(OK)

    with pytest.raises(SupabaseUnavailable):
        run(store, bedrock)

    assert bedrock.calls == 0


def test_existing_key_is_reported_to_the_endpoint():
    store = FakeStore(existing_status="reserved")
    bedrock = FakeBedrock(OK)

    with pytest.raises(LedgerKeyExists) as error:
        run(store, bedrock)

    assert error.value.status == "reserved"
    assert bedrock.calls == 0


# --- 성공 ---


def test_success_settles_with_usage_and_reserves_with_kind_limits():
    store = FakeStore()
    bedrock = FakeBedrock(OK)

    outcome = run(store, bedrock)

    assert (outcome.text, outcome.ledger_id, outcome.attempt_no) == ("설명", 101, 1)
    [reserve] = store.reserved
    assert reserve["key"] == f"{USER}:key-1:1"
    assert (reserve["kind"], reserve["attempt_no"], reserve["daily_count_limit"]) == ("explain", 1, 20)
    assert reserve["reserved_usd"] == BUDGET.reserve_amount("자료: 문장", 600)
    assert store.settled == [
        (101, "usage", {"actual_usd": Decimal("0.000600"), "input_tokens": 100, "output_tokens": 50})
    ]


def test_success_without_usage_settles_with_reserved_fallback():
    store = FakeStore()
    no_usage = {k: v for k, v in OK.items() if k != "usage"}

    outcome = run(store, FakeBedrock(no_usage))

    assert outcome.text == "설명"
    assert store.settled == [(101, "reserved_fallback", {})]


@pytest.mark.parametrize(("kind", "max_tokens", "effort", "limit"), [("quiz", 3000, "low", None), ("followup", 400, "none", None)])
def test_kind_sets_tokens_effort_and_count_limit(kind, max_tokens, effort, limit):
    seen = {}
    store = FakeStore()

    class Recording(FakeBedrock):
        def converse(self, **kwargs):
            seen.update(kwargs)
            return super().converse(**kwargs)

    run(store, Recording(OK), kind=kind)

    assert seen["inferenceConfig"] == {"maxTokens": max_tokens}
    assert seen["additionalModelRequestFields"] == {"reasoning": {"effort": effort}}
    assert store.reserved[0]["daily_count_limit"] is limit


# --- AC-3: 실패 주입 → 원장 상태와 응답 ---


def test_timeout_retries_once_with_a_new_reservation_and_both_settle_as_fallback():
    store = FakeStore()
    bedrock = FakeBedrock(timeout(), timeout())

    with pytest.raises(AiCallError) as error:
        run(store, bedrock)

    assert bedrock.calls == 2
    assert [r["key"] for r in store.reserved] == [f"{USER}:key-1:1", f"{USER}:key-1:2"]
    assert [r["attempt_no"] for r in store.reserved] == [1, 2]
    assert store.settled == [(101, "reserved_fallback", {}), (102, "reserved_fallback", {})]
    api_error = api_error_for(error.value)
    assert (api_error.code, CATALOG[(api_error.code, None)][0]) == ("ai_unavailable", 502)


def test_retry_success_returns_second_attempt():
    store = FakeStore()

    outcome = run(store, FakeBedrock(client_error("ThrottlingException"), OK))

    assert outcome.attempt_no == 2 and outcome.ledger_id == 102
    assert [s[1] for s in store.settled] == ["released", "usage"]


def test_missing_content_settles_usage_and_does_not_retry():
    store = FakeStore()
    bedrock = FakeBedrock({"stopReason": "end_turn", "usage": {"inputTokens": 30, "outputTokens": 0}})

    with pytest.raises(AiCallError) as error:
        run(store, bedrock)

    assert (error.value.code, bedrock.calls) == ("NoContent", 1)
    assert store.settled == [(101, "usage", {"actual_usd": BUDGET.cost(30, 0), "input_tokens": 30, "output_tokens": 0})]
    assert api_error_for(error.value).code == "ai_unavailable"


def test_missing_content_without_usage_settles_with_fallback():
    store = FakeStore()

    with pytest.raises(AiCallError):
        run(store, FakeBedrock({"stopReason": "end_turn"}))

    assert store.settled == [(101, "reserved_fallback", {})]


def test_known_rejection_releases_and_does_not_retry():
    store = FakeStore()
    bedrock = FakeBedrock(client_error("AccessDeniedException"))

    with pytest.raises(AiCallError):
        run(store, bedrock)

    assert bedrock.calls == 1
    assert store.settled == [(101, "released", {})]


def test_sts_failure_releases_without_retry():
    store = FakeStore()

    def factory(settings, token):
        raise AiCallError("sts", "AccessDenied")

    with pytest.raises(AiCallError) as error:
        run_ai_call(
            store, API_KEY, BUDGET, user_id=USER, kind="explain", request_key="k", prompt="p", client_factory=factory
        )

    assert error.value.step == "sts"
    assert len(store.reserved) == 1
    assert store.settled == [(101, "released", {})]


def test_retry_blocked_by_limit_reports_the_first_failure():
    store = FakeStore(limit_from_attempt=2)
    bedrock = FakeBedrock(timeout(), OK)

    with pytest.raises(AiCallError) as error:
        run(store, bedrock)

    assert error.value.code == "ReadTimeoutError"
    assert bedrock.calls == 1
    assert store.settled == [(101, "reserved_fallback", {})]


def test_settlement_failure_after_the_call_is_a_500_not_a_503():
    store = FakeStore(settle_fails=True)

    with pytest.raises(AiSettlementFailed) as error:
        run(store, FakeBedrock(OK))

    api_error = api_error_for(error.value)
    assert (api_error.code, CATALOG[(api_error.code, None)][0]) == ("internal_error", 500)


def test_first_reservation_from_quiz_claim_is_used_for_attempt_one():
    store = FakeStore()
    bedrock = FakeBedrock(timeout(), OK)

    outcome = run(
        store, bedrock, kind="quiz", request_key=f"{USER}:quiz:7:1", first_reservation=Reservation(55, 1)
    )

    assert [r["key"] for r in store.reserved] == [f"{USER}:quiz:7:1:2"]
    assert [s[:2] for s in store.settled] == [(55, "reserved_fallback"), (101, "usage")]
    assert outcome.attempt_no == 2


def test_quiz_first_reservation_is_released_when_the_pre_check_fails(monkeypatch):
    """선점 함수가 넣은 첫 예약은 호출 전 검사가 실패하면 풀린다. 남기면 10분 뒤 과금으로 정산된다."""
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", "preview")
    store = FakeStore()
    bedrock = FakeBedrock(OK)

    with pytest.raises(AiCallError):
        run(store, bedrock, kind="quiz", request_key="q", first_reservation=Reservation(55, 1))
    monkeypatch.delenv("VERCEL")
    monkeypatch.delenv("VERCEL_ENV")
    with pytest.raises(AiConfigError):
        run(store, bedrock, kind="quiz", request_key="q", first_reservation=Reservation(56, 1),
            settings=BedrockSettings(role_arn="role"), oidc_token=None)

    assert store.settled == [(55, "released", {}), (56, "released", {})]
    assert store.reserved == [] and bedrock.calls == 0


def test_unexpected_exception_still_settles_the_reservation():
    store = FakeStore()

    class Boom(FakeBedrock):
        def converse(self, **kwargs):
            self.calls += 1
            raise RuntimeError("unexpected")

    with pytest.raises(RuntimeError):
        run(store, Boom())

    assert store.settled == [(101, "reserved_fallback", {})]
    assert len(store.reserved) == 1


def test_unexpected_exception_from_client_creation_still_settles():
    store = FakeStore()

    def factory(settings, token):
        raise KeyError("Credentials")

    with pytest.raises(KeyError):
        run_ai_call(
            store, API_KEY, BUDGET, user_id=USER, kind="explain", request_key="k", prompt="p", client_factory=factory
        )

    assert store.settled == [(101, "reserved_fallback", {})]


def test_retry_reservation_db_failure_after_a_call_is_a_500():
    class DownOnRetry(FakeStore):
        def reserve(self, **kwargs):
            if kwargs["attempt_no"] == 2:
                raise SupabaseUnavailable("status 503")
            return super().reserve(**kwargs)

    store = DownOnRetry()

    with pytest.raises(AiSettlementFailed) as error:
        run(store, FakeBedrock(timeout(), OK))

    assert api_error_for(error.value).code == "internal_error"
    assert store.settled == [(101, "reserved_fallback", {})]


def test_throttling_waits_before_the_retry_but_timeouts_do_not():
    waits = []

    run(FakeStore(), FakeBedrock(client_error("ThrottlingException"), OK), sleep=waits.append)
    run(FakeStore(), FakeBedrock(timeout(), OK), sleep=waits.append)

    assert waits == [1.0]


def test_already_settled_row_is_logged_not_failed(caplog):
    class Swept(FakeStore):
        def settle(self, ledger_id, outcome, **values):
            super().settle(ledger_id, outcome, **values)
            return False

    outcome = run(Swept(), FakeBedrock(OK))

    assert outcome.text == "설명"
    assert "already settled" in caplog.text


def test_failure_log_has_codes_only(caplog):
    store = FakeStore()

    with pytest.raises(AiCallError):
        run(store, FakeBedrock(client_error("AccessDeniedException")), prompt="비밀 노트 문장")

    text = caplog.text
    assert "AccessDeniedException" in text
    assert "비밀 노트 문장" not in text


def test_real_boto3_client_makes_at_most_two_bedrock_requests(monkeypatch):
    """botocore 자동 재시도를 끈 실제 클라이언트로, 스로틀링이 이어져도 Bedrock 요청은 첫 호출 + 앱 재시도 1회다."""
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "fake-api-key-for-tests")
    sent = []

    def factory(settings, token):
        client = ai_ledger.make_client(settings, token)

        def throttled(request, **_):
            sent.append(1)
            body = json.dumps({"message": "slow down"}).encode()
            return AWSResponse(request.url, 429, {"x-amzn-ErrorType": "ThrottlingException"}, RawBody(body))

        client.meta.events.register("before-send.bedrock-runtime.Converse", throttled)
        return client

    store = FakeStore()
    with pytest.raises(AiCallError):
        run_ai_call(
            store, API_KEY, BUDGET, user_id=USER, kind="explain", request_key="k", prompt="p", client_factory=factory
        )

    assert len(sent) == 2
    assert [s[1] for s in store.settled] == ["released", "released"]


# --- RPC 인자 모양 ---


@dataclass
class RecordingSupabase:
    rows: dict
    calls: list = field(default_factory=list)

    def rpc(self, name, payload):
        self.calls.append((name, payload))
        return self.rows[name]


def test_supabase_store_sends_amounts_as_strings_and_maps_outcomes():
    supabase = RecordingSupabase({"ai_reserve": [{"outcome": "reserved", "ledger_id": 9, "ledger_status": "reserved"}]})
    store = SupabaseLedgerStore(supabase)

    reservation = store.reserve(
        user_id=USER,
        kind="explain",
        key="k:1",
        attempt_no=1,
        reserved_usd=Decimal("0.004952"),
        budget=BUDGET,
        daily_count_limit=20,
    )

    assert reservation == Reservation(9, 1)
    name, payload = supabase.calls[0]
    assert name == "ai_reserve"
    assert payload == {
        "p_user_id": USER,
        "p_kind": "explain",
        "p_idempotency_key": "k:1",
        "p_attempt_no": 1,
        "p_reserved_usd": "0.004952",
        "p_user_daily_count_limit": 20,
        "p_daily_budget_usd": "0.9",
        "p_monthly_budget_usd": "7",
        "p_user_daily_share": "0.5",
    }

    supabase.rows["ai_reserve"] = [{"outcome": "limit_reached", "ledger_id": None, "ledger_status": None}]
    with pytest.raises(AiLimitReached):
        store.reserve(user_id=USER, kind="explain", key="k:2", attempt_no=1, reserved_usd=Decimal(0), budget=BUDGET, daily_count_limit=20)

    supabase.rows["ai_reserve"] = [{"outcome": "exists", "ledger_id": 3, "ledger_status": "settled"}]
    with pytest.raises(LedgerKeyExists) as error:
        store.reserve(user_id=USER, kind="explain", key="k:1", attempt_no=1, reserved_usd=Decimal(0), budget=BUDGET, daily_count_limit=20)
    assert error.value.status == "settled"


def test_supabase_store_settle_and_quiz_claim():
    supabase = RecordingSupabase(
        {
            "ai_settle": True,
            "ai_claim_quiz_set": [{"outcome": "claimed", "set_id": 4, "attempt": 1, "ledger_id": 12}],
        }
    )
    store = SupabaseLedgerStore(supabase)

    assert store.settle(12, "usage", actual_usd=Decimal("0.0006"), input_tokens=100, output_tokens=50) is True
    assert supabase.calls[-1] == (
        "ai_settle",
        {"p_ledger_id": 12, "p_outcome": "usage", "p_actual_usd": "0.0006", "p_input_tokens": 100, "p_output_tokens": 50},
    )

    claim = store.claim_quiz_set(
        user_id=USER, quiz_date="2026-11-03", source_date="2026-11-02", reserved_usd=Decimal("0.03"), budget=BUDGET
    )
    assert (claim.outcome, claim.set_id, claim.attempt, claim.reservation) == ("claimed", 4, 1, Reservation(12, 1))
    assert supabase.calls[-1][1]["p_lease_seconds"] == 300
    assert supabase.calls[-1][1]["p_max_attempts"] == 2

    supabase.rows["ai_claim_quiz_set"] = [{"outcome": "generating", "set_id": 4, "attempt": 1, "ledger_id": None}]
    claim = store.claim_quiz_set(
        user_id=USER, quiz_date="2026-11-03", source_date="2026-11-02", reserved_usd=Decimal("0.03"), budget=BUDGET
    )
    assert (claim.outcome, claim.reservation) == ("generating", None)

    supabase.rows["ai_claim_quiz_set"] = [{"outcome": "limit_reached", "set_id": None, "attempt": None, "ledger_id": None}]
    with pytest.raises(AiLimitReached):
        store.claim_quiz_set(
            user_id=USER, quiz_date="2026-11-03", source_date="2026-11-02", reserved_usd=Decimal("0.03"), budget=BUDGET
        )


def test_api_error_for_rejects_other_exceptions():
    with pytest.raises(TypeError):
        api_error_for(ValueError("x"))
