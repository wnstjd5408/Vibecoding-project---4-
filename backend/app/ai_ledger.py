"""AI 한도 예약 → 호출 → 정산 (MEG-86, API spec v0.2 5.3·5.4·1.4.4).

E09(설명)·E11(퀴즈)·E13(꼬리 질문)은 run_ai_call 하나로 Bedrock을 부른다.

1. 설정·배포 환경을 먼저 검사한다. 실패하면 원장 행 없이 끝난다.
2. ai_reserve로 예약한다. 한도를 넘으면 행도 호출도 없이 AiLimitReached다.
3. Bedrock을 부른다(시간 초과 30초, botocore 재시도 없음).
4. ai_settle로 정산한다. 응답 usage가 있으면 usage, 요청이 닿지 않았거나 거절(인증 포함)이 확실하면 released, 그 밖은 reserved_fallback.
5. 다시 불러 볼 만한 실패면 attempt_no 2로 새로 예약해 한 번 더 부른다.

예산·단가 금액은 공개 저장소에 쓰지 않는다. 환경변수에서 읽는다(2026-11-02 사람 결정).
숫자(N=20, 한 사용자 몫 50%, 출력 토큰 600·3,000·400)는 API spec의 제안값이고 Q3에서 확정한다.
"""

import logging
import math
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Protocol

from app.bedrock import (
    SETTLE_FALLBACK,
    SETTLE_RELEASED,
    SETTLE_USAGE,
    AiCallError,
    AiConfigError,
    BedrockSettings,
    AGENT_MODEL_ENV,
    converse_text,
    ensure_ready,
    make_client,
    model_request_fields,
)
from app.errors import ApiError
from app.supabase import SupabaseClient

logger = logging.getLogger("app.ai")

KIND_EXPLAIN = "explain"
KIND_QUIZ = "quiz"
KIND_FOLLOWUP = "followup"
KIND_AGENT = "agent"
# CS Agent 2차 점검·보완 호출(MEG-282 설계 v0.2 4절 D2). 하루 턴 수 한도에 세지 않고 금액 한도와 agent 몫(70%)에는 넣는다.
KIND_AGENT_REVIEW = "agent_review"
# CS Agent 전용 모델·단가를 쓰는 kind(MEG-282). E09(explain)·퀴즈·후속 질문은 늘 기본 모델·단가다.
AGENT_KINDS = frozenset({KIND_AGENT, KIND_AGENT_REVIEW})


def model_id_for(settings: BedrockSettings, kind: str) -> str:
    """이 kind의 호출에 쓸 모델 ID. CS Agent kind는 BEDROCK_AGENT_MODEL_ID가 있으면 그 값, 아니면 기본 모델이다."""
    if kind in AGENT_KINDS and settings.agent_model_id:
        return settings.agent_model_id
    return settings.model_id


def validate_kind(settings: BedrockSettings, budget: "AiBudget", kind: str) -> None:
    """이 kind의 호출 설정이 맞는지 예약·선점 전에 본다(MEG-282 리뷰). 틀리면 AiConfigError(500)다.

    - CS Agent kind: 전용 모델·단가 짝(check_agent_config), 전용 단가 값(for_kind)
    - 모든 kind: 모델과 추론 강도의 짝(OpenAI가 아닌 모델에 effort를 주면 막음)
    """
    if kind in AGENT_KINDS:
        check_agent_config(settings, budget)
    budget.for_kind(kind)
    model_request_fields(model_id_for(settings, kind), CALL_SPECS[kind].effort)


def check_agent_config(settings: BedrockSettings, budget: "AiBudget") -> None:
    """CS Agent 전용 모델과 전용 단가는 함께 설정해야 한다(MEG-282 리뷰 H1).

    모델만 바꾸면 비싼 모델의 원가가 기본 단가로 기록되어 한도가 실제 금액보다 크게 느슨해진다. 단가만 바꾸면 반대로
    지나치게 일찍 막힌다. 어긋나면 AiConfigError(500)다. CS Agent 호출(예약 전)과 E29 사전 확인에서만 본다.
    """
    model_set = bool(settings.agent_model_id) and settings.agent_model_id != settings.model_id
    price_set = budget.agent_input_usd_per_mtok is not None
    if model_set != price_set:
        raise AiConfigError(
            f"{AGENT_MODEL_ENV}와 {' · '.join(AGENT_PRICE_ENV.values())}는 함께 설정해야 한다"
        )


@dataclass(frozen=True)
class CallSpec:
    max_tokens: int
    effort: str
    # 사용자·KST 날짜별 새 호출 횟수(첫 시도만 센다). None이면 횟수 제한이 없다.
    daily_count_limit: int | None


# API spec 5.1·1.8의 제안값
CALL_SPECS: dict[str, CallSpec] = {
    KIND_EXPLAIN: CallSpec(max_tokens=600, effort="none", daily_count_limit=20),
    KIND_QUIZ: CallSpec(max_tokens=3000, effort="low", daily_count_limit=None),
    KIND_FOLLOWUP: CallSpec(max_tokens=400, effort="none", daily_count_limit=None),
    # CS Agent E29(MEG-236). 출력 1,500토큰은 Q4 임시값, 하루 20턴은 D4(사용자 결정 2026-11-18, 시작값)다.
    # agent 금액 몫 70%는 SQL 기본값을 쓴다(MEG-232 결정 1). 실측(MEG-236 AC-5) 뒤 다시 정한다.
    KIND_AGENT: CallSpec(max_tokens=1500, effort="none", daily_count_limit=20),
    # 2차 점검·보완(MEG-282 D2). 출력 상한은 1차와 같고 추론은 none으로 시작한다. 횟수 한도는 없다(9절 결정 5).
    KIND_AGENT_REVIEW: CallSpec(max_tokens=1500, effort="none", daily_count_limit=None),
}
# 한 사용자가 하루 전체 예산에서 쓸 수 있는 몫(5.3)
USER_DAILY_SHARE = Decimal("0.5")
# 퀴즈 세트 선점 만료와 선점 횟수(6.4)
QUIZ_LEASE_SECONDS = 300
QUIZ_MAX_ATTEMPTS = 2
# 입력 토큰 추정에 더하는 메시지 틀 몫
PROMPT_OVERHEAD_TOKENS = 64
# 호출 안 재시도 1회(5.2)
MAX_ATTEMPTS = 2
# 스로틀링 뒤 재시도 전에 쉬는 초. 시간 초과는 이미 30초를 기다렸으므로 쉬지 않는다.
THROTTLING_CODE = "ThrottlingException"
THROTTLE_BACKOFF_SECONDS = 1.0

# 프롬프트 캐시 토큰의 단가(MEG-275 4-A, 사용자 결정 2026-11-24: 보수적 고정 규칙).
# 캐시 읽기는 일반 입력 단가로 센다(실제로는 더 싸다). 캐시 쓰기는 일반 입력 단가의 1.25배다
# (AWS 문서의 Luna·Claude 5분 캐시 쓰기 단가). 비용을 실제보다 작게 잡지 않으려는 선택이다.
# 요청에 cachePoint(1시간 TTL 포함)를 넣지 않는다는 가정이다. 1시간 캐시를 쓰면 쓰기 단가가 더 높을 수 있으니 다시 정한다.
CACHE_WRITE_RATE_MULTIPLIER = Decimal("1.25")

_USD_STEP = Decimal("0.000001")
_MILLION = Decimal(1_000_000)

BUDGET_ENV = {
    "daily_usd": "AI_DAILY_BUDGET_USD",
    "monthly_usd": "AI_MONTHLY_BUDGET_USD",
    "input_usd_per_mtok": "AI_INPUT_USD_PER_MTOK",
    "output_usd_per_mtok": "AI_OUTPUT_USD_PER_MTOK",
}
# CS Agent(E29 1차·2차) 전용 모델의 단가(MEG-282). 둘 다 비어 있으면 위 단가를 쓴다(지금 동작). 하나만 있으면 설정 오류다.
AGENT_PRICE_ENV = {
    "agent_input_usd_per_mtok": "AI_AGENT_INPUT_USD_PER_MTOK",
    "agent_output_usd_per_mtok": "AI_AGENT_OUTPUT_USD_PER_MTOK",
}


class AiLimitReached(Exception):
    """한도 예약 실패. 원장 행도 AI 호출도 없다. 429 ai_limit_reached."""


class LedgerKeyExists(Exception):
    """같은 멱등 키의 원장 행이 이미 있다. status는 그 시도(:attempt_no) 행 하나의 상태다.

    E09의 9단계 판정은 이 값만 믿지 않는다. 첫 시도가 released여도 재시도(:2)가 아직 reserved일 수 있으므로
    {user_id}:{Idempotency-Key}: 접두사의 원장 행을 모두 읽어(REST 조회, MEG-87에서 만든다) 하나라도 reserved면
    in_progress로 답한다.
    """

    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


class AiSettlementFailed(Exception):
    """AI를 부른 뒤 원장 처리(정산·재시도 예약)가 DB 문제로 실패했다. 503이 아니라 500이다(1.4.4).

    503이면 클라이언트 자동 재시도가 붙어 비용이 겹친다. 결과를 사용자에게 주지 않는다.
    """


def estimate_input_tokens(prompt: str) -> int:
    """보수적인 입력 토큰 추정. UTF-8 2바이트를 토큰 하나로 센다.

    한글 한 글자(3바이트)는 1.5토큰, 영문 한 글자는 0.5토큰으로 실제보다 크게 잡는다. 예약액이 실제보다 커야
    동시 요청이 한도를 넘지 않는다. 정산은 응답 usage로 하므로 비용 기록은 실제 값이 된다.
    """
    return math.ceil(len(prompt.encode("utf-8")) / 2) + PROMPT_OVERHEAD_TOKENS


def _usd(value: Decimal) -> Decimal:
    return value.quantize(_USD_STEP, rounding=ROUND_CEILING)


@dataclass(frozen=True)
class AiBudget:
    daily_usd: Decimal
    monthly_usd: Decimal
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    # CS Agent 전용 모델의 단가(MEG-282). None이면 위 단가를 쓴다.
    agent_input_usd_per_mtok: Decimal | None = None
    agent_output_usd_per_mtok: Decimal | None = None
    # CS Agent 단가 설정 오류(MEG-282 리뷰). 다른 kind(E09·퀴즈·꼬리 질문)는 막지 않고, CS Agent kind만 for_kind에서 막는다.
    agent_price_error: str | None = None

    def __post_init__(self):
        if (self.agent_input_usd_per_mtok is None) != (self.agent_output_usd_per_mtok is None):
            raise ValueError("agent prices must be set together")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AiBudget":
        """값이 없거나 양수가 아니면 AiConfigError다. 오류 문구에는 변수 이름만 넣는다."""
        env = os.environ if environ is None else environ
        values = {}
        for field, name in BUDGET_ENV.items():
            raw = (env.get(name) or "").strip()
            try:
                value = Decimal(raw)
            except InvalidOperation:
                raise AiConfigError(f"{name}가 필요하다(양의 숫자)") from None
            if not value.is_finite() or value <= 0:
                raise AiConfigError(f"{name}가 필요하다(양의 숫자)")
            values[field] = value
        agent: dict = {}
        error = None
        for field, name in AGENT_PRICE_ENV.items():
            raw = (env.get(name) or "").strip()
            if not raw:
                continue
            try:
                value = Decimal(raw)
            except InvalidOperation:
                value = None
            if value is None or not value.is_finite() or value <= 0:
                error = f"{name}는 양의 숫자여야 한다"
                continue
            agent[field] = value
        if error is None and len(agent) == 1:
            # 한쪽만 바꾸면 입력·출력 단가가 서로 다른 모델 기준이 된다.
            error = f"{' · '.join(AGENT_PRICE_ENV.values())}는 함께 설정해야 한다"
        if error is not None:
            # CS Agent 전용 설정 하나가 E09·퀴즈까지 멈추지 않게, 오류는 CS Agent kind를 부를 때만 낸다.
            return cls(**values, agent_price_error=error)
        return cls(**values, **agent)

    def for_kind(self, kind: str) -> "AiBudget":
        """이 kind의 호출에 쓸 예산(단가). CS Agent kind에 전용 단가가 있으면 그 단가, 아니면 그대로다(MEG-282).

        하루·월 예산은 모든 kind가 함께 쓴다. 바뀌는 것은 토큰 단가뿐이다.
        """
        if kind in AGENT_KINDS and self.agent_price_error is not None:
            raise AiConfigError(self.agent_price_error)
        if kind in AGENT_KINDS and self.agent_input_usd_per_mtok is not None:
            return replace(self, input_usd_per_mtok=self.agent_input_usd_per_mtok,
                           output_usd_per_mtok=self.agent_output_usd_per_mtok)
        return self

    def cost(self, input_tokens: int, output_tokens: int, cache_write_tokens: int = 0) -> Decimal:
        """input_tokens는 캐시 읽기·쓰기를 포함한 전체 입력이다. 그 가운데 cache_write_tokens에는 웃돈을 붙인다.

        cache_write_tokens는 input_tokens의 일부여야 한다(bedrock._usage가 보장한다).
        """
        cache_write_surcharge = Decimal(cache_write_tokens) * (CACHE_WRITE_RATE_MULTIPLIER - 1)
        return _usd(
            (
                (Decimal(input_tokens) + cache_write_surcharge) * self.input_usd_per_mtok
                + Decimal(output_tokens) * self.output_usd_per_mtok
            )
            / _MILLION
        )

    def reserve_amount(self, prompt: str, max_tokens: int) -> Decimal:
        """예약액 = (입력 토큰 추정 + 출력 상한) × 단가(5.3)."""
        return self.cost(estimate_input_tokens(prompt), max_tokens)


@dataclass(frozen=True)
class Reservation:
    ledger_id: int
    attempt_no: int


@dataclass(frozen=True)
class QuizClaim:
    """outcome: claimed·ready·generating·failed. claimed일 때만 첫 예약이 있다. 한도는 AiLimitReached로 낸다."""

    outcome: str
    set_id: int | None
    attempt: int | None
    reservation: Reservation | None


class LedgerStore(Protocol):
    def reserve(
        self,
        *,
        user_id: str,
        kind: str,
        key: str,
        attempt_no: int,
        reserved_usd: Decimal,
        budget: AiBudget,
        daily_count_limit: int | None,
    ) -> Reservation: ...

    def check_limit(
        self, *, user_id: str, kind: str, reserved_usd: Decimal, budget: AiBudget, daily_count_limit: int | None
    ) -> bool: ...

    def settle(
        self,
        ledger_id: int,
        outcome: str,
        *,
        actual_usd: Decimal | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> bool: ...


def _first_row(rows):
    return rows[0] if isinstance(rows, list) else rows


class SupabaseLedgerStore:
    """SQL 함수(supabase/migrations의 ai_reserve·ai_settle·ai_claim_quiz_set)를 RPC로 부른다.

    금액은 문자열로 보내 numeric으로 정확히 들어가게 한다.
    """

    def __init__(self, supabase: SupabaseClient):
        self._supabase = supabase

    @staticmethod
    def _budget_args(budget: AiBudget) -> dict[str, str]:
        return {
            "p_daily_budget_usd": str(budget.daily_usd),
            "p_monthly_budget_usd": str(budget.monthly_usd),
            "p_user_daily_share": str(USER_DAILY_SHARE),
        }

    def reserve(self, *, user_id, kind, key, attempt_no, reserved_usd, budget, daily_count_limit) -> Reservation:
        row = _first_row(
            self._supabase.rpc(
                "ai_reserve",
                {
                    "p_user_id": user_id,
                    "p_kind": kind,
                    "p_idempotency_key": key,
                    "p_attempt_no": attempt_no,
                    "p_reserved_usd": str(reserved_usd),
                    "p_user_daily_count_limit": daily_count_limit,
                    **self._budget_args(budget),
                },
            )
        )
        if row["outcome"] == "limit_reached":
            raise AiLimitReached()
        if row["outcome"] == "exists":
            raise LedgerKeyExists(row["ledger_status"])
        return Reservation(ledger_id=int(row["ledger_id"]), attempt_no=attempt_no)

    def check_limit(self, *, user_id, kind, reserved_usd, budget, daily_count_limit) -> bool:
        """예약하지 않고 이 금액을 지금 예약하면 한도 안인지만 본다(ai_check_limit, 읽기 전용). 첫 시도로 센다."""
        return (
            self._supabase.rpc(
                "ai_check_limit",
                {
                    "p_user_id": user_id,
                    "p_kind": kind,
                    "p_reserved_usd": str(reserved_usd),
                    "p_user_daily_count_limit": daily_count_limit,
                    "p_attempt_no": 1,
                    **self._budget_args(budget),
                },
            )
            is True
        )

    def settle(self, ledger_id, outcome, *, actual_usd=None, input_tokens=None, output_tokens=None) -> bool:
        return bool(
            self._supabase.rpc(
                "ai_settle",
                {
                    "p_ledger_id": ledger_id,
                    "p_outcome": outcome,
                    "p_actual_usd": None if actual_usd is None else str(actual_usd),
                    "p_input_tokens": input_tokens,
                    "p_output_tokens": output_tokens,
                },
            )
        )

    def claim_quiz_set(
        self, *, user_id: str, quiz_date: str, source_date: str, reserved_usd: Decimal, budget: AiBudget
    ) -> QuizClaim:
        """퀴즈 세트 선점과 첫 예약(6.4절 2~5번). 날짜는 KST ISO 문자열이다.

        한도면 AiLimitReached다. E11은 이것을 429가 아니라 200 status: ai_limit_reached로 답한다(6.3).
        claimed면 reservation을 run_ai_call(first_reservation=...)에 넘긴다.
        E11은 이 함수보다 먼저 bedrock.ensure_ready를 부른다. 설정·배포 환경 오류로 끝날 요청이 선점 시도를 쓰지 않게 한다.
        """
        row = _first_row(
            self._supabase.rpc(
                "ai_claim_quiz_set",
                {
                    "p_user_id": user_id,
                    "p_quiz_date": quiz_date,
                    "p_source_date": source_date,
                    "p_reserved_usd": str(reserved_usd),
                    "p_lease_seconds": QUIZ_LEASE_SECONDS,
                    "p_max_attempts": QUIZ_MAX_ATTEMPTS,
                    **self._budget_args(budget),
                },
            )
        )
        if row["outcome"] == "limit_reached":
            raise AiLimitReached()
        reservation = None
        if row["outcome"] == "claimed":
            reservation = Reservation(ledger_id=int(row["ledger_id"]), attempt_no=1)
        return QuizClaim(
            outcome=row["outcome"], set_id=row["set_id"], attempt=row["attempt"], reservation=reservation
        )


@dataclass(frozen=True)
class AiOutcome:
    text: str
    ledger_id: int
    attempt_no: int


def explain_request_key(user_id: str, idempotency_key: str) -> str:
    """E09 원장 키의 앞부분. 원장 키는 {user_id}:{Idempotency-Key}:{attempt_no}다(v06 주석, S2)."""
    return f"{user_id}:{idempotency_key}"


def quiz_request_key(user_id: str, set_id: int, attempt: int) -> str:
    return f"{user_id}:quiz:{set_id}:{attempt}"


def followup_request_key(user_id: str, request_id: str) -> str:
    return f"{user_id}:followup:{request_id}"


def agent_request_key(user_id: str, idempotency_key: str) -> str:
    """E29 원장 키의 앞부분. 원장 키는 {user_id}:agent:{Idempotency-Key}:{attempt_no}다(CS Agent spec 9절)."""
    return f"{user_id}:agent:{idempotency_key}"


def agent_review_request_key(user_id: str, idempotency_key: str) -> str:
    """E29 2차 점검·보완 원장 키의 앞부분(MEG-282 D2). {user_id}:agent-review:{Idempotency-Key}:{attempt_no}다.

    1차 키와 겹치지 않는다(같은 키면 중복 키 오류). 2차는 앱 안 재시도가 없어 시도 번호는 늘 1이다.
    """
    return f"{user_id}:agent-review:{idempotency_key}"


def agent_explain_request_key(user_id: str, idempotency_key: str) -> str:
    """E29 노트 용어 질문의 explain 원장 키 앞부분(MEG-243, spec 9절). {user_id}:agent-explain:{Idempotency-Key}:{attempt_no}다.

    턴의 Idempotency-Key를 쓴다. E09 키({user_id}:{Idempotency-Key})·agent 키와 겹치지 않고, 턴마다 첫 시도는 최대 1건이다.
    """
    return f"{user_id}:agent-explain:{idempotency_key}"


# run_ai_call이 예약한 뒤에 낸 예외에 붙이는 속성 이름. 값은 마지막 예약의 원장 id다.
_LEDGER_ID_ATTR = "ledger_id"


def ledger_id_of(error: BaseException) -> int | None:
    """run_ai_call이 낸 예외의 마지막 원장 id. 예약 전에 끝났으면(한도·같은 키·첫 예약 DB 실패) None이다.

    E29는 실패한 턴에도 이 값을 저장해 쓴 비용과 턴을 잇는다(CS Agent spec 9절). E09·퀴즈는 쓰지 않는다.
    """
    value = getattr(error, _LEDGER_ID_ATTR, None)
    return value if isinstance(value, int) else None


def _settle(store: LedgerStore, reservation: Reservation, outcome: str, **values) -> None:
    """AI를 부른 뒤의 정산. 어떤 실패든 AiSettlementFailed(500)로 바꾼다. 503이면 자동 재시도로 비용이 겹친다."""
    try:
        changed = store.settle(reservation.ledger_id, outcome, **values)
    except Exception as error:
        raise AiSettlementFailed(type(error).__name__) from None
    if not changed:
        # 다음 예약이 10분 넘었다고 먼저 정산한 행이다. 비용은 그쪽에서 한 번 셌다.
        logger.warning("ai ledger row was already settled ledger_id=%s outcome=%s", reservation.ledger_id, outcome)


def _settle_failure(store: LedgerStore, budget: AiBudget, reservation: Reservation, error: AiCallError) -> None:
    outcome = error.settlement
    if outcome == SETTLE_USAGE:
        _settle(
            store,
            reservation,
            SETTLE_USAGE,
            actual_usd=budget.cost(error.input_tokens, error.output_tokens, error.cache_write_tokens),
            input_tokens=error.input_tokens,
            output_tokens=error.output_tokens,
        )
    else:
        _settle(store, reservation, outcome)


def run_ai_call(
    store: LedgerStore,
    settings: BedrockSettings,
    budget: AiBudget,
    *,
    user_id: str,
    kind: str,
    request_key: str,
    prompt: str,
    oidc_token: str | None = None,
    first_reservation: Reservation | None = None,
    client_factory: Callable = make_client,
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = MAX_ATTEMPTS,
) -> AiOutcome:
    """예약 → 호출 → 정산. 원장 키는 {request_key}:{attempt_no}다.

    max_attempts: 호출 안 시도 횟수(기본 2 = 재시도 1회). 1이면 재시도하지 않는다(CS Agent 2차, MEG-282 D2).

    동기 함수다. Bedrock 호출과 스로틀링 대기가 스레드를 막으므로 async 엔드포인트에서 직접 부르지 않는다
    (FastAPI의 일반 def 엔드포인트는 스레드 풀에서 돈다).
    first_reservation: 퀴즈처럼 선점 함수가 첫 예약을 이미 한 경우 넘긴다. 호출하지 못하고 끝나면 이 함수가 푼다.
    낼 수 있는 예외: AiConfigError(500), AiCallError(502), AiLimitReached(429), LedgerKeyExists(E09가 판단),
    AiSettlementFailed(500), 첫 예약 단계의 SupabaseUnavailable(503, AI 호출 전이므로).
    예약한 뒤에 낸 예외에는 마지막 예약의 원장 id를 붙인다(ledger_id_of로 읽는다).
    """
    spec = CALL_SPECS[kind]
    # CS Agent kind는 전용 모델·단가를 쓸 수 있다(MEG-282). 그 밖의 kind는 그대로다.
    try:
        validate_kind(settings, budget, kind)
        budget = budget.for_kind(kind)
        model_id = model_id_for(settings, kind)
    except AiConfigError:
        if first_reservation is not None:
            _settle(store, first_reservation, SETTLE_RELEASED)
        raise
    try:
        ensure_ready(settings, oidc_token)
    except (AiConfigError, AiCallError) as error:
        # 선점 함수가 미리 넣은 예약은 호출 없이 끝나므로 푼다. 없으면 10분 뒤 과금으로 정산된다.
        # 푸는 중 DB가 실패하면 503이 아니라 500(AiSettlementFailed)이다. 클라이언트 자동 재시도를 붙이지 않으려는 선택이다.
        if first_reservation is not None:
            logger.warning("ai pre-check failed with a claimed reservation type=%s", type(error).__name__)
            _settle(store, first_reservation, SETTLE_RELEASED)
        raise
    # 이번 호출에서 예약한 원장 id(시도 순). 예약한 뒤에 난 예외에 마지막 값을 붙인다.
    spent: list[int] = []
    try:
        return _call_attempts(
            store,
            settings,
            budget,
            spec=spec,
            user_id=user_id,
            kind=kind,
            request_key=request_key,
            prompt=prompt,
            oidc_token=oidc_token,
            first_reservation=first_reservation,
            client_factory=client_factory,
            sleep=sleep,
            spent=spent,
            max_attempts=max_attempts,
            model_id=model_id,
        )
    except Exception as error:
        if spent:
            setattr(error, _LEDGER_ID_ATTR, spent[-1])
        raise


def _call_attempts(
    store: LedgerStore,
    settings: BedrockSettings,
    budget: AiBudget,
    *,
    spec: CallSpec,
    user_id: str,
    kind: str,
    request_key: str,
    prompt: str,
    oidc_token: str | None,
    first_reservation: Reservation | None,
    client_factory: Callable,
    sleep: Callable[[float], None],
    spent: list[int],
    max_attempts: int = MAX_ATTEMPTS,
    model_id: str | None = None,
) -> AiOutcome:
    """run_ai_call의 예약 → 호출 → 정산 반복. 예약할 때마다 원장 id를 spent에 더한다."""
    reserved_usd = budget.reserve_amount(prompt, spec.max_tokens)
    client = None
    last_error: AiCallError | None = None

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    for attempt_no in range(1, max_attempts + 1):
        if attempt_no == 1 and first_reservation is not None:
            reservation = first_reservation
        else:
            try:
                reservation = store.reserve(
                    user_id=user_id,
                    kind=kind,
                    key=f"{request_key}:{attempt_no}",
                    attempt_no=attempt_no,
                    reserved_usd=reserved_usd,
                    budget=budget,
                    daily_count_limit=spec.daily_count_limit,
                )
            except Exception as error:
                if last_error is None:
                    raise
                # 재시도 예약이 한도·키로 막히면 첫 실패(502)를 그대로 낸다. 첫 호출 비용은 이미 정산됐다.
                if isinstance(error, (AiLimitReached, LedgerKeyExists)):
                    raise last_error from None
                # AI를 한 번 부른 뒤의 DB 실패는 500이다(1.4.4).
                raise AiSettlementFailed(type(error).__name__) from None
        spent.append(reservation.ledger_id)

        calling = False
        try:
            if client is None:
                client = client_factory(settings, oidc_token)
            calling = True
            result = converse_text(
                client, settings, prompt, max_tokens=spec.max_tokens, effort=spec.effort, model_id=model_id
            )
        except AiConfigError:
            # 예약 전 검사를 지나 호출 직전에 드러난 설정 오류. Bedrock에 닿지 않았다.
            _settle(store, reservation, SETTLE_RELEASED)
            raise
        except AiCallError as error:
            logger.warning(
                "ai call failed kind=%s attempt=%s step=%s code=%s settle=%s",
                kind,
                attempt_no,
                error.step,
                error.code,
                error.settlement,
            )
            _settle_failure(store, budget, reservation, error)
            last_error = error
            if error.retryable and attempt_no < max_attempts:
                if error.code == THROTTLING_CODE:
                    # 스로틀링은 바로 다시 부르면 또 걸리므로 잠깐 쉰다.
                    sleep(THROTTLE_BACKOFF_SECONDS)
                continue
            raise
        except Exception as error:
            # 예상하지 못한 예외도 예약을 남기지 않고 500으로 둔다. 클라이언트를 만들다 난 것은 Bedrock에 닿지 않았으므로
            # 풀고, 호출 중에 난 것은 과금 여부를 모르므로 예약액 그대로 정산한다.
            outcome = SETTLE_FALLBACK if calling else SETTLE_RELEASED
            logger.warning(
                "ai call raised unexpected kind=%s attempt=%s type=%s settle=%s",
                kind,
                attempt_no,
                type(error).__name__,
                outcome,
            )
            _settle(store, reservation, outcome)
            raise

        if result.input_tokens is not None and result.output_tokens is not None:
            _settle(
                store,
                reservation,
                SETTLE_USAGE,
                actual_usd=budget.cost(result.input_tokens, result.output_tokens, result.cache_write_tokens),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
        else:
            _settle(store, reservation, SETTLE_FALLBACK)
        return AiOutcome(text=result.text, ledger_id=reservation.ledger_id, attempt_no=attempt_no)

    raise AssertionError("unreachable")  # pragma: no cover


def api_error_for(error: Exception) -> ApiError:
    """공통 계층 예외를 응답 오류로 바꾼다(1.4.4). LedgerKeyExists는 엔드포인트마다 달라 여기서 다루지 않는다."""
    if isinstance(error, AiLimitReached):
        return ApiError("ai_limit_reached", stage="ai")
    if isinstance(error, AiCallError):
        return ApiError("ai_unavailable", stage="ai")
    if isinstance(error, AiSettlementFailed):
        return ApiError("internal_error", stage="db")
    if isinstance(error, AiConfigError):
        return ApiError("internal_error", stage="ai")
    raise TypeError(f"not an AI layer error: {type(error).__name__}")
