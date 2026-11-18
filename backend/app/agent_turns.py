"""CS Agent 질문 실행 E29 (MEG-236, API spec v0.2 4절 E29·5·6·9절, 기술 검토 v0.4 1~3절).

POST /api/ai/conversations/{conversation_id}/turns — 질문을 받아 근거를 찾고 모델을 한 번 불러 답을 저장한다.

처리 순서(기술 검토 3절):
1. 노출 중단 플래그(503) → 경로·Idempotency-Key(404·400) → AI 설정 확인(500, 원장 전) → 공통 권한 검사(404) →
   질문·선택 문맥·확인 선택·다시 묻기 검사(422·409).
2. agent_claim_turn으로 턴을 선점한다. 같은 키의 끝난 턴은 재생하고(모델 호출 없음, 가림 적용), 진행 중이면 409 in_progress,
   같은 대화에 다른 키의 턴이 진행 중이면 409 turn_in_progress다.
3. 속도 제한(429 rate_limited)과 AI 한도 사전 확인(ai_check_limit, 429 ai_limit_reached). 걸리면 선점한 턴을 지운다.
   409를 속도 제한보다 먼저 보는 것은 검사 순서의 예외다(spec E29 3단계): 같은 키 재전송이 한도를 쓰지 않게 한다.
4. 응답 수명 안의 스레드에서 run_turn을 돌린다(Q2 확정: 응답 뒤의 작업은 멈추므로 202 후 백그라운드 실행은 쓰지 않는다).
   질문 이해 → 검색 → (근거 없으면 no_evidence로 끝, 모델 호출 없음) → 취소 확인 → run_ai_call(예약·Bedrock·정산) →
   출력 검증 → 출처 확인 → agent_finish_turn(조건부 저장). 단계마다 턴 행의 step·lease_expires_at을 status = running 조건으로
   갱신하고, 0행이면(중단·만료) 실행을 멈춘다.
5. 응답은 SSE(text/event-stream)다. Accept가 application/json이면 끝날 때까지 기다려 E30과 같은 JSON을 준다.
   송신이 실패해도(연결 끊김) 남은 이벤트를 버리고 스레드가 끝날 때까지 요청을 끝내지 않는다. 결과는 E30으로 읽는다.

vercel.json에 supportsCancellation을 켜지 않는다(기술 검토 1절). 켜면 끊김이 앱으로 전달돼 실행이 멈출 수 있다.
로그에는 턴 id·단계·오류 코드만 남긴다. 질문·답변·노트 원문은 남기지 않는다(spec 8절).
"""

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from typing import Annotated, Any, Literal

import anyio
import anyio.from_thread
import anyio.to_thread
from fastapi import APIRouter, Depends, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app import session
from app.agent import agent_disabled, topic_label_of
from app.agent_access import (
    TURN_POLL_SECONDS,
    ConversationAccess,
    load_conversation,
    load_turn,
    path_uuid,
    read_turns,
    source_checker,
    visible_turns,
)
from app.agent_output import (
    MAX_QUESTION_CHARS,
    MAX_REPLY_TEXT_CHARS,
    MAX_SELECTION_TOTAL_CHARS,
    NO_EVIDENCE_RESULT,
    PRESET_TEXTS,
    PROMPT_VERSION,
    OutputInvalid,
    PromptInput,
    build_prompt,
    max_prompt_tokens,
    parse_output,
    source_rows,
    usable_paragraphs,
)
from app.agent_retrieval import RetrievalContext, Retriever, get_retriever
from app.ai_explain import OIDC_HEADER, AiRuntime, _field_error, get_ai_runtime, read_idempotency_key
from app.ai_ledger import (
    CALL_SPECS,
    KIND_AGENT,
    AiBudget,
    AiLimitReached,
    AiSettlementFailed,
    LedgerKeyExists,
    agent_request_key,
    api_error_for,
    run_ai_call,
)
from app.auth import SessionUser, require_login
from app.bedrock import AiCallError, AiConfigError, BedrockSettings, ensure_ready
from app.errors import ApiError, error_body, request_id_of
from app.rate_limit import AI_AGENT, RateLimiter, get_rate_limiter
from app.supabase import SupabaseClient, SupabaseConfigError, SupabaseUnavailable, get_supabase

router = APIRouter(prefix="/api")
logger = logging.getLogger("app.agent")

# 실행 만료(Q15 임시 120초). 단계마다 갱신한다. 한 단계의 최악(약 86초)보다 길고 함수 최대 실행 시간(300초)보다 짧다.
LEASE_SECONDS = 120
# 지연 안내 기준(Q6 임시 15초)과 SSE 주석 간격(10초). 모델 호출 중에는 이벤트가 없어 중간 장비가 끊지 않게 주석을 보낸다.
DELAYED_AFTER_SECONDS = 15.0
KEEPALIVE_SECONDS = 10.0
MAX_ADD_SELECTIONS = 5
MAX_EXCLUDE_SELECTIONS = 20

_MAX_BIGINT = 2**63 - 1
_MAX_INT = 2**31 - 1
_UUID_SHAPE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# 끝난 턴의 failure → 스트림 error 이벤트의 code(실행 중 원인을 모를 때). limit는 S12 화면, 나머지는 S8 화면이다.
_FAILURE_CODES = {"limit": "ai_limit_reached", "error": "ai_unavailable", "interrupted": "internal_error"}


# --- 요청 모양 (spec E29) ---


class QuestionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["free", "suggested", "preset"]
    text: StrictStr | None = None
    preset: Literal["detail", "simple", "example"] | None = None
    from_turn_id: StrictStr | None = None


class SelectionAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note_id: Annotated[StrictInt, Field(ge=1, le=_MAX_BIGINT)]
    note_revision: Annotated[StrictInt, Field(ge=1, le=_MAX_INT)]
    start: Annotated[StrictInt, Field(ge=0, le=_MAX_INT)]
    end: Annotated[StrictInt, Field(ge=0, le=_MAX_INT)]


class ReplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_id: StrictStr
    clarify_option_id: StrictStr | None = None
    text: StrictStr | None = None
    topic_choice: Literal["continue"] | None = None


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: QuestionBody
    add_selections: Annotated[list[SelectionAdd], Field(max_length=MAX_ADD_SELECTIONS)] = []
    exclude_selection_ids: Annotated[list[StrictStr], Field(max_length=MAX_EXCLUDE_SELECTIONS)] = []
    reply: ReplyBody | None = None
    retry_of_turn_id: StrictStr | None = None


# --- 사전 검사 결과 ---


@dataclass
class Checked:
    """1단계 검사를 통과한 질문. 선점과 실행에 쓴다."""

    kind: str
    text: str
    preset: str | None = None
    from_turn_id: str | None = None
    reply: dict[str, Any] | None = None
    retry_of_turn_id: str | None = None
    clarification: str | None = None
    allow_topic_check: bool = True
    new_selections: list[dict[str, Any]] = field(default_factory=list)
    exclude_ids: list[str] = field(default_factory=list)
    # 이번 턴에 쓰는 선택 문맥(제외 반영, 추가 포함): (note_id, 원문)
    selections: list[tuple[int, str]] = field(default_factory=list)
    # 이전 대화: 가리지 않은 끝난 턴의 (질문, 답 요약), 오래된 순
    recent: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class TurnJob:
    user: SessionUser
    access: ConversationAccess
    turn_id: str
    seq: int
    idempotency_key: str
    checked: Checked
    budget: AiBudget
    settings: BedrockSettings
    oidc_token: str | None
    request_id: str


@dataclass
class Final:
    """실행이 끝난 뒤 스트림의 마지막 이벤트. payload(turn 객체)가 있으면 result, 없거나 failed면 error다."""

    payload: dict[str, Any] | None
    error_code: str | None = None


def _uuid_or_422(value: str, name: str) -> str:
    if not _UUID_SHAPE.fullmatch(value):
        raise _field_error(name, "invalid_format")
    return value.lower()


def _answer_text(result: dict[str, Any]) -> str | None:
    """이전 대화 문맥에 넣을 답 요약. 설명 본문이 있는 결과와 의미 확인만 쓴다."""
    if result.get("state") == "clarify":
        return result["clarify"]["prompt"]
    sections = result.get("sections")
    if isinstance(sections, list) and sections:
        return "\n".join(section.get("body", "") for section in sections if isinstance(section, dict))
    return None


def check_request(
    body: TurnRequest,
    access: ConversationAccess,
    turns: list[dict[str, Any]],
    supabase: SupabaseClient,
    user: SessionUser,
) -> Checked:
    """spec E29 1단계의 질문·선택·확인 선택·다시 묻기 검사. turns는 가림을 적용한 turn 객체(오래된 순)다."""
    question = body.question
    by_id = {turn["turn_id"]: turn for turn in turns}

    if question.kind == "preset":
        if question.preset is None:
            raise _field_error("question.preset", "required")
        if question.text is not None or question.from_turn_id is not None:
            raise _field_error("question", "invalid_value")
        checked = Checked(kind="preset", text=PRESET_TEXTS[question.preset], preset=question.preset)
    else:
        if question.preset is not None:
            raise _field_error("question.preset", "invalid_value")
        if question.text is None or not question.text.strip():
            raise _field_error("question.text", "required")
        if len(question.text) > MAX_QUESTION_CHARS or "\x00" in question.text:
            raise _field_error("question.text", "too_long" if len(question.text) > MAX_QUESTION_CHARS else "invalid_format")
        checked = Checked(kind=question.kind, text=question.text)
        if question.kind == "free":
            if question.from_turn_id is not None:
                raise _field_error("question.from_turn_id", "invalid_value")
        else:
            # 추천 질문: 그 턴이 가려지지 않았고 문구가 그 턴의 추천 질문과 같아야 한다(spec E29, AG04).
            if question.from_turn_id is None:
                raise _field_error("question.from_turn_id", "required")
            from_id = _uuid_or_422(question.from_turn_id, "question.from_turn_id")
            source = by_id.get(from_id)
            suggestions = ((source or {}).get("result") or {}).get("suggestions") or []
            if source is None or source.get("hidden") is not None or question.text not in suggestions:
                raise _field_error("question.text", "invalid_value")
            checked.from_turn_id = from_id

    if body.reply is not None:
        _check_reply(body, checked, turns, by_id)

    if body.retry_of_turn_id is not None:
        retry_id = _uuid_or_422(body.retry_of_turn_id, "retry_of_turn_id")
        target = by_id.get(retry_id)
        if target is None:
            raise _field_error("retry_of_turn_id", "invalid_value")
        if not (target.get("hidden") or {}).get("retry_allowed"):
            raise ApiError("conflict", "turn_not_retryable", stage="validate")
        checked.retry_of_turn_id = retry_id

    _check_selections(body, checked, access, supabase, user)

    for turn in turns:
        if turn.get("hidden") is not None or turn["status"] != "completed" or "result" not in turn:
            continue
        answer = _answer_text(turn["result"])
        text = turn["question"].get("text")
        if answer and text:
            checked.recent.append((text, answer))
    return checked


def _check_reply(body: TurnRequest, checked: Checked, turns: list[dict[str, Any]], by_id: dict) -> None:
    """앞 턴의 의미 확인·주제 전환 확인에 대한 답(spec E29 reply). 대상 뒤에 턴이 생겼으면 409 choice_expired다."""
    reply = body.reply
    target_id = _uuid_or_422(reply.turn_id, "reply.turn_id")
    target = by_id.get(target_id)
    if target is None:
        raise _field_error("reply.turn_id", "invalid_value")
    if turns[-1]["turn_id"] != target_id:
        raise ApiError("conflict", "choice_expired", stage="validate")
    result = target.get("result") or {}
    chosen = [value for value in (reply.clarify_option_id, reply.text, reply.topic_choice) if value is not None]
    if len(chosen) != 1 or target.get("hidden") is not None or target["status"] != "completed":
        raise _field_error("reply", "invalid_value")
    stored: dict[str, Any] = {"turn_id": target_id}
    if reply.topic_choice is not None:
        # 주제 전환 확인에서 '이어서 질문': 같은 질문을 주제 판정 없이 다시 보낸다(결정 38).
        if result.get("state") != "topic_check":
            raise _field_error("reply.topic_choice", "invalid_value")
        if checked.kind != "free" or checked.text != target["question"].get("text"):
            raise _field_error("question.text", "invalid_value")
        stored["topic_choice"] = reply.topic_choice
        checked.allow_topic_check = False
    else:
        if result.get("state") != "clarify":
            raise _field_error("reply.turn_id", "invalid_value")
        if reply.clarify_option_id is not None:
            options = {option["option_id"]: option["label"] for option in result["clarify"]["options"]}
            if reply.clarify_option_id not in options:
                raise _field_error("reply.clarify_option_id", "invalid_value")
            stored["clarify_option_id"] = reply.clarify_option_id
            checked.clarification = options[reply.clarify_option_id]
        else:
            if not reply.text.strip() or len(reply.text) > MAX_REPLY_TEXT_CHARS or "\x00" in reply.text:
                raise _field_error("reply.text", "too_long" if len(reply.text) > MAX_REPLY_TEXT_CHARS else "invalid_value")
            stored["text"] = reply.text
            checked.clarification = reply.text
    checked.reply = stored


def _check_selections(
    body: TurnRequest, checked: Checked, access: ConversationAccess, supabase: SupabaseClient, user: SessionUser
) -> None:
    """선택 문맥 추가·제외(spec E29 add_selections·exclude_selection_ids). 같은 노트만 붙인다(Q17)."""
    conversation = access.conversation
    selections = conversation.get("ai_conversation_selections") or []
    known = {selection["id"] for selection in selections}
    excludes = []
    for raw_id in body.exclude_selection_ids:
        selection_id = _uuid_or_422(raw_id, "exclude_selection_ids")
        if selection_id not in known:
            raise _field_error("exclude_selection_ids", "invalid_value")
        if selection_id not in excludes:
            excludes.append(selection_id)
    checked.exclude_ids = excludes
    active = [
        (selection["note_id"], selection["text_snapshot"])
        for selection in selections
        if selection.get("excluded_at") is None and selection["id"] not in excludes
    ]

    if body.add_selections:
        note_id = conversation.get("note_id")
        if note_id is None or any(add.note_id != note_id for add in body.add_selections):
            raise _field_error("add_selections.note_id", "invalid_value")
        note = supabase.get_note_for_agent(note_id, include_unpublished=user.is_operator)
        if note is None:
            raise ApiError("not_found", stage="db")
        text = note["body_markdown"]
        for add in body.add_selections:
            if add.note_revision != note["revision"]:
                raise ApiError("conflict", "stale_revision", stage="validate")
            if add.end <= add.start or add.end > len(text):
                raise _field_error("add_selections.end", "out_of_range")
            snapshot = text[add.start : add.end]
            if not snapshot.strip():
                raise _field_error("add_selections", "invalid_value")
            checked.new_selections.append(
                {
                    "conversation_id": conversation["id"],
                    "note_id": note_id,
                    "note_revision": note["revision"],
                    "start": add.start,
                    "end": add.end,
                    "text_snapshot": snapshot,
                }
            )
            active.append((note_id, snapshot))
    if sum(len(text) for _, text in active) > MAX_SELECTION_TOTAL_CHARS:
        raise _field_error("add_selections", "too_long")
    checked.selections = active


# --- 실행 (스레드) ---


def _lease_iso() -> str:
    return datetime.fromtimestamp(session.now() + LEASE_SECONDS, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()


class _Stopped(Exception):
    """턴이 더는 running이 아니다(중단·만료·삭제). 실행을 멈추고 DB의 마지막 상태를 보낸다."""


class _Failed(Exception):
    def __init__(self, failure: str, code: str, ledger_id: int | None = None):
        super().__init__(code)
        self.failure = failure
        self.code = code
        self.ledger_id = ledger_id


def run_turn(
    job: TurnJob,
    supabase: SupabaseClient,
    runtime: AiRuntime,
    retriever: Retriever,
    emit: Callable[[bytes], None],
) -> Final:
    """턴 하나를 끝까지 실행하고 마지막 이벤트를 보낸다. 스레드에서 돈다(run_ai_call이 동기 함수다).

    emit은 SSE 조각을 보낸다. 송신 실패는 응답 쪽이 삼키므로 이 함수는 끝까지 실행된다.
    """
    error_code: str | None = None
    try:
        _execute(job, supabase, runtime, retriever, emit)
    except _Stopped:
        logger.info("stage=run turn_id=%s stopped", job.turn_id)
    except _Failed as failed:
        error_code = failed.code
        _finish_failed(job, supabase, failed.failure, failed.ledger_id)
    except Exception as error:
        logger.error("stage=run turn_id=%s unexpected=%s", job.turn_id, type(error).__name__)
        error_code = "internal_error"
        _finish_failed(job, supabase, "error", None)
    final = _final(job, supabase, error_code)
    emit(_final_event(job, final))
    return final


def _finish_failed(job: TurnJob, supabase: SupabaseClient, failure: str, ledger_id: int | None) -> None:
    try:
        _finish(job, supabase, "failed", failure=failure, ledger_id=ledger_id)
    except Exception as error:
        # 끝내지 못한 턴은 실행 만료(120초) 뒤 읽을 때 failed(interrupted)가 된다.
        logger.error("stage=run turn_id=%s finish_failed=%s", job.turn_id, type(error).__name__)


def _touch(job: TurnJob, supabase: SupabaseClient, step: str, paragraph_count: int | None = None) -> None:
    if not supabase.touch_agent_turn(job.user.user_id, job.turn_id, step, _lease_iso(), paragraph_count):
        raise _Stopped()


def _finish(job: TurnJob, supabase: SupabaseClient, status: str, **values: Any) -> bool:
    payload = {
        "p_user_id": job.user.user_id,
        "p_turn_id": job.turn_id,
        "p_status": status,
        "p_failure": values.get("failure"),
        "p_result": values.get("result"),
        "p_sources": values.get("sources"),
        "p_ledger_id": values.get("ledger_id"),
        "p_paragraph_count": values.get("paragraph_count"),
        "p_model_id": values.get("model_id"),
        "p_prompt_version": values.get("prompt_version"),
        "p_retrieval_version": values.get("retrieval_version"),
    }
    changed = supabase.finish_agent_turn(payload)
    logger.info("stage=finish turn_id=%s status=%s saved=%s", job.turn_id, status, changed)
    return changed


def _execute(
    job: TurnJob, supabase: SupabaseClient, runtime: AiRuntime, retriever: Retriever, emit: Callable[[bytes], None]
) -> None:
    checked = job.checked
    conversation = job.access.conversation

    _touch(job, supabase, "understand")
    emit(sse("step", {"step": "understand", "state": "current"}))
    context = RetrievalContext(
        conversation_id=conversation["id"],
        origin=conversation["origin"],
        note_id=conversation.get("note_id"),
        topic_label=conversation.get("topic_label") or "",
        selection_note_ids=tuple(note_id for note_id, _ in checked.selections),
        selection_texts=tuple(text for _, text in checked.selections),
        recent_questions=tuple(question for question, _ in checked.recent),
    )
    emit(sse("step", {"step": "understand", "state": "done"}))

    _touch(job, supabase, "retrieve")
    emit(sse("step", {"step": "retrieve", "state": "current"}))
    paragraphs = usable_paragraphs(retriever.retrieve(job.user, checked.text, context))
    _touch(job, supabase, "retrieve", len(paragraphs))
    emit(sse("step", {"step": "retrieve", "state": "done", "paragraph_count": len(paragraphs)}))

    if not paragraphs:
        # 쓸 근거가 없으면 모델을 부르지 않는다. 서버 고정 안내만 저장한다(spec E29 6단계, 결정 4·16).
        if not _finish(
            job,
            supabase,
            "completed",
            result=dict(NO_EVIDENCE_RESULT),
            paragraph_count=0,
            retrieval_version=retriever.version,
        ):
            raise _Stopped()
        return

    # 예약 직전의 취소 확인(spec E29 7단계). 갱신이 status = running 조건이라 중단된 턴이면 여기서 멈춘다.
    _touch(job, supabase, "compose")
    emit(sse("step", {"step": "compose", "state": "current"}))
    topic = conversation.get("topic_label") or ""
    prompt = build_prompt(
        PromptInput(
            question=checked.text,
            topic_label=topic,
            selections=[text for _, text in checked.selections],
            recent=checked.recent,
            paragraphs=paragraphs,
            clarification=checked.clarification,
            allow_topic_check=checked.allow_topic_check,
        )
    )
    try:
        outcome = run_ai_call(
            runtime.store,
            job.settings,
            job.budget,
            user_id=job.user.user_id,
            kind=KIND_AGENT,
            request_key=agent_request_key(job.user.user_id, job.idempotency_key),
            prompt=prompt,
            oidc_token=job.oidc_token,
            client_factory=runtime.client_factory,
            sleep=runtime.sleep,
        )
    except AiLimitReached:
        # 사전 확인 뒤 실제 예약에서 한도에 걸렸다(동시 요청 등). 화면은 S12다.
        raise _Failed("limit", "ai_limit_reached") from None
    except LedgerKeyExists:
        # 턴 선점 때문에 정상 흐름에서는 생기지 않는다. 새 호출 없이 failed다(spec E29 8단계).
        raise _Failed("error", "internal_error") from None
    except (AiCallError, AiSettlementFailed, AiConfigError) as error:
        raise _Failed("error", api_error_for(error).code) from None

    try:
        parsed = parse_output(
            outcome.text, len(paragraphs), current_topic=topic, allow_topic_check=checked.allow_topic_check
        )
    except OutputInvalid as invalid:
        # 형식 실패는 재시도 없이 failed다(Q19 임시). 호출은 이미 정산됐다. 원문은 남기지 않는다.
        logger.warning("stage=validate turn_id=%s output_invalid=%s", job.turn_id, invalid.reason)
        raise _Failed("error", "ai_unavailable", outcome.ledger_id) from None

    sources = source_rows(paragraphs, parsed.refs)
    _check_sources(job, supabase, sources, outcome.ledger_id)
    emit(sse("step", {"step": "compose", "state": "done"}))
    if not _finish(
        job,
        supabase,
        "completed",
        result=parsed.result,
        sources=sources or None,
        ledger_id=outcome.ledger_id,
        paragraph_count=len(paragraphs),
        model_id=job.settings.model_id,
        prompt_version=PROMPT_VERSION,
        retrieval_version=retriever.version,
    ):
        # 실행 중 E31로 중단됐거나 만료됐다. 결과는 버리고 정산은 그대로 둔다(spec 3.1).
        raise _Stopped()


def _check_sources(job: TurnJob, supabase: SupabaseClient, sources: list[dict[str, Any]], ledger_id: int) -> None:
    """인용한 문단이 지금도 볼 수 있는 출처인지 다시 본다(spec E29 9단계). 가림 함수와 같은 판정이다."""
    if not sources:
        return
    note_ids = []
    for source in sources:
        if source["source_kind"] == "note" and source["source_id"].isdigit():
            note_ids.append(int(source["source_id"]))
    visible = source_checker(supabase.get_note_states(note_ids) if note_ids else {})
    if not all(visible(source) for source in sources):
        logger.warning("stage=sources turn_id=%s source_not_visible", job.turn_id)
        raise _Failed("error", "internal_error", ledger_id)


def _final(job: TurnJob, supabase: SupabaseClient, error_code: str | None) -> Final:
    """DB에 남은 턴의 마지막 상태를 가림을 적용해 읽는다. 대화 권한이 사라졌으면 404다."""
    try:
        access = load_conversation(supabase, job.user, job.access.conversation["id"])
        turns = read_turns(supabase, job.user, access.conversation["id"], max_seq=job.seq)
        payload = next((p for p in visible_turns(supabase, access, turns) if p["turn_id"] == job.turn_id), None)
    except ApiError as error:
        return Final(None, error.code)
    except Exception as error:
        logger.error("stage=final turn_id=%s read_failed=%s", job.turn_id, type(error).__name__)
        return Final(None, error_code or "internal_error")
    if payload is None:
        return Final(None, "not_found")
    if payload["status"] == "failed":
        return Final(payload, error_code or _FAILURE_CODES.get(payload.get("failure"), "internal_error"))
    if payload["status"] == "running":
        # 끝내지 못했다. 만료 뒤 E30이 interrupted로 바꾼다.
        return Final(payload, error_code or "internal_error")
    return Final(payload)


def _final_event(job: TurnJob, final: Final) -> bytes:
    return _end_event(job.request_id, final.payload, final.error_code)


def _end_event(request_id: str, payload: dict[str, Any] | None, error_code: str | None) -> bytes:
    """스트림의 마지막 이벤트. 실패면 error, 아니면 result다(spec 6절). 실행과 재생이 같이 쓴다."""
    if error_code is None and payload is not None:
        return sse("result", payload)
    _, body, _ = error_body(request_id, error_code or "internal_error")
    return sse("error", body)


def _replay_event(request_id: str, payload: dict[str, Any]) -> bytes:
    """같은 키 재생의 마지막 이벤트. failed 턴은 실행 때처럼 error로 끝낸다(2026-11-18 결정).

    재생에는 실행 중 원인이 없으므로 저장된 failure로 code를 정한다. _final이 원인을 모를 때와 같은 규칙이다.
    """
    error_code = None
    if payload["status"] == "failed":
        error_code = _FAILURE_CODES.get(payload.get("failure"), "internal_error")
    return _end_event(request_id, payload, error_code)


# --- SSE 응답 ---


class _SafeSend:
    """송신 실패(연결 끊김)를 삼키고 그 뒤의 송신을 버린다. 실행은 계속된다."""

    def __init__(self, send: Send):
        self._send = send
        self.connected = True

    async def __call__(self, message: dict[str, Any]) -> None:
        if not self.connected:
            return
        try:
            await self._send(message)
        except Exception as error:
            self.connected = False
            logger.info("stage=stream client_gone=%s", type(error).__name__)

    async def body(self, chunk: bytes, more: bool = True) -> None:
        await self({"type": "http.response.body", "body": chunk, "more_body": more})


async def _no_body():
    if False:  # pragma: no cover - 빈 비동기 반복자
        yield b""


class TurnEventStream(StreamingResponse):
    """E29 SSE 응답. 앞 이벤트(turn)를 보내고, 일이 있으면 스레드에서 돌리며 이벤트를 내보낸다.

    - 송신이 실패하면 남은 이벤트를 버리고 스레드가 끝날 때까지 기다린다(기술 검토 3절 6번).
    - 바깥에서 취소돼도(미들웨어의 연결 끊김 처리) 스레드는 abandon_on_cancel=False라 끝날 때까지 이 호출이 끝나지 않는다.
    - 10초마다 SSE 주석을, Q6 기준을 넘으면 delayed를 한 번 보낸다.
    """

    def __init__(self, preamble: list[bytes], work: Callable[[Callable[[bytes], None]], Any] | None):
        super().__init__(_no_body(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})
        self._preamble = preamble
        self._work = work

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        sender = _SafeSend(send)
        if self._work is None:
            await self._send_preamble(sender)
            await sender.body(b"", more=False)
            return
        send_stream, receive_stream = anyio.create_memory_object_stream[bytes](max_buffer_size=256)

        def emit(chunk: bytes) -> None:
            try:
                anyio.from_thread.run_sync(send_stream.send_nowait, chunk)
            except Exception:
                # 받는 쪽이 이미 끝났다(취소). 이벤트는 버리고 실행은 계속한다.
                pass

        async def run() -> None:
            # 첫 송신에서 끊겨 바로 취소돼도 스레드를 시작하고 끝날 때까지 기다린다.
            with anyio.CancelScope(shield=True):
                try:
                    await anyio.to_thread.run_sync(self._work, emit, abandon_on_cancel=False)
                finally:
                    send_stream.close()

        # 스레드를 송신보다 먼저 시작한다. 송신이 실패하거나 이 호출이 취소돼도 그룹은 스레드가 끝날 때까지 닫히지 않는다.
        async with anyio.create_task_group() as group:
            group.start_soon(run)
            await self._send_preamble(sender)
            await _pump(receive_stream, sender)
        await sender.body(b"", more=False)

    async def _send_preamble(self, sender: "_SafeSend") -> None:
        await sender({"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers})
        for chunk in self._preamble:
            await sender.body(chunk)


async def _pump(stream, sender: _SafeSend) -> None:
    started = last = time.monotonic()
    delayed_sent = False
    async with stream:
        while True:
            deadline = last + KEEPALIVE_SECONDS
            if not delayed_sent:
                deadline = min(deadline, started + DELAYED_AFTER_SECONDS)
            chunk = None
            with anyio.move_on_after(max(deadline - time.monotonic(), 0)):
                try:
                    chunk = await stream.receive()
                except anyio.EndOfStream:
                    return
            now = time.monotonic()
            if chunk is not None:
                await sender.body(chunk)
            elif not delayed_sent and now >= started + DELAYED_AFTER_SECONDS:
                await sender.body(sse("delayed", {}))
                delayed_sent = True
            else:
                await sender.body(b": keep-alive\n\n")
            last = now


# --- 엔드포인트 ---


@dataclass
class Replay:
    payload: dict[str, Any]


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/event-stream" not in accept


def _remove_claim(supabase: SupabaseClient, user: SessionUser, turn_id: str) -> None:
    """한도·속도 제한에 걸린 선점 턴을 지운다. 지우지 못하면 실행 만료(120초) 뒤 interrupted가 된다."""
    try:
        supabase.delete_running_agent_turn(user.user_id, turn_id)
    except (SupabaseUnavailable, SupabaseConfigError) as error:
        logger.warning("stage=db turn_id=%s claim_not_removed=%s", turn_id, type(error).__name__)


def _replay(supabase: SupabaseClient, user: SessionUser, turn_id: str) -> Replay:
    """같은 키의 끝난 턴을 가림을 적용해 돌려준다. 그 턴의 대화 권한을 다시 확인한다(모델 호출 없음)."""
    turn, access = load_turn(supabase, user, turn_id)
    turns = read_turns(supabase, user, access.conversation["id"], max_seq=turn["seq"])
    payload = next((p for p in visible_turns(supabase, access, turns) if p["turn_id"] == turn["id"]), None)
    if payload is None:
        raise ApiError("not_found", stage="db")
    return Replay(payload)


def prepare_turn(
    conversation_id: str,
    body: TurnRequest,
    idempotency_key: str | None,
    oidc_token: str | None,
    request_id: str,
    user: SessionUser,
    supabase: SupabaseClient,
    limiter: RateLimiter,
    runtime: AiRuntime,
) -> TurnJob | Replay:
    """spec E29 1~3단계. 실행할 턴(TurnJob)이나 재생할 턴(Replay)을 돌려준다. 동기 함수다(스레드 풀에서 돈다)."""
    if agent_disabled():
        raise ApiError("service_unavailable", stage="flag")
    target = path_uuid(conversation_id)
    key = read_idempotency_key(idempotency_key)

    # 설정·배포 환경 오류로 끝날 요청이 턴을 선점하지 않게 먼저 검사한다(spec v0.2 5.4).
    try:
        budget = runtime.load_budget()
        settings = runtime.load_settings()
        ensure_ready(settings, oidc_token)
    except (AiConfigError, AiCallError) as error:
        raise api_error_for(error) from None

    access = load_conversation(supabase, user, target)
    turns = visible_turns(supabase, access, read_turns(supabase, user, target))
    checked = check_request(body, access, turns, supabase, user)

    claim = supabase.claim_agent_turn(
        {
            "p_user_id": user.user_id,
            "p_conversation_id": target,
            "p_idempotency_key": key,
            "p_question_kind": checked.kind,
            "p_question_text": checked.text,
            "p_lease_seconds": LEASE_SECONDS,
            "p_preset": checked.preset,
            "p_from_turn_id": checked.from_turn_id,
            "p_reply": checked.reply,
            "p_retry_of_turn_id": checked.retry_of_turn_id,
        }
    )
    if claim is None:
        raise ApiError("not_found", stage="db")
    logger.info("stage=claim turn_id=%s outcome=%s", claim["turn_id"], claim["outcome"])
    if claim["outcome"] == "existing":
        if claim["turn_status"] == "running":
            raise ApiError(
                "conflict",
                "in_progress",
                retry_after_seconds=TURN_POLL_SECONDS,
                turn_id=claim["turn_id"],
                stage="validate",
            )
        return _replay(supabase, user, claim["turn_id"])
    if claim["outcome"] == "in_progress":
        raise ApiError("conflict", "turn_in_progress", stage="validate")

    turn_id = claim["turn_id"]
    try:
        limiter.check(AI_AGENT, f"user:{user.user_id}")
        # Q4 상한을 모두 채운 최대 예약액으로 남은 한도를 본다. 예약은 하지 않는다(spec E29 3단계).
        spec = CALL_SPECS[KIND_AGENT]
        reserved = budget.cost(max_prompt_tokens(), spec.max_tokens)
        if not runtime.store.check_limit(
            user_id=user.user_id,
            kind=KIND_AGENT,
            reserved_usd=reserved,
            budget=budget,
            daily_count_limit=spec.daily_count_limit,
        ):
            raise ApiError("ai_limit_reached", stage="ai")
        if checked.exclude_ids:
            supabase.exclude_agent_selections(target, checked.exclude_ids, _now_iso())
        for selection in checked.new_selections:
            supabase.add_agent_selection(selection)
        if not access.conversation.get("topic_label"):
            # origin none 대화는 첫 질문의 앞 20자를 주제 이름으로 쓴다(spec Q9).
            supabase.set_agent_topic_label(user.user_id, target, topic_label_of(checked.text))
    except BaseException:
        _remove_claim(supabase, user, turn_id)
        raise

    return TurnJob(
        user=user,
        access=access,
        turn_id=turn_id,
        seq=claim["seq"],
        idempotency_key=key,
        checked=checked,
        budget=budget,
        settings=settings,
        oidc_token=oidc_token,
        request_id=request_id,
    )


def _now_iso() -> str:
    return datetime.fromtimestamp(session.now(), UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@router.post("/ai/conversations/{conversation_id}/turns", summary="E29 ask a question in a CS Agent conversation")
async def ask(
    conversation_id: str,
    body: TurnRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: SessionUser = Depends(require_login),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
    runtime: AiRuntime = Depends(get_ai_runtime),
    retriever: Retriever = Depends(get_retriever),
):
    """질문을 받아 답을 만든다. 기본 응답은 SSE(spec 6절)이고, Accept: application/json이면 E30과 같은 JSON이다."""
    request_id = request_id_of(request)
    prepared = await run_in_threadpool(
        prepare_turn,
        conversation_id,
        body,
        idempotency_key,
        request.headers.get(OIDC_HEADER),
        request_id,
        user,
        supabase,
        limiter,
        runtime,
    )
    if isinstance(prepared, Replay):
        if _wants_json(request):
            # JSON 재생은 상태와 관계없이 E30 턴 객체다(failed도 200).
            return JSONResponse(prepared.payload)
        turn = {"turn_id": prepared.payload["turn_id"], "seq": prepared.payload["seq"]}
        return TurnEventStream([sse("turn", turn), _replay_event(request_id, prepared.payload)], None)

    work = partial(run_turn, prepared, supabase, runtime, retriever)
    if _wants_json(request):
        final = await anyio.to_thread.run_sync(work, lambda chunk: None, abandon_on_cancel=False)
        if final.payload is None:
            raise ApiError(final.error_code or "internal_error", stage="ai")
        return JSONResponse(final.payload)
    return TurnEventStream([sse("turn", {"turn_id": prepared.turn_id, "seq": prepared.seq})], work)
