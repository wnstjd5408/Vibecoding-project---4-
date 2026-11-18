"""CS Agent 대화·턴 읽기와 중단 (MEG-234, API spec v0.2 4절 E27·E28·E30·E31, 8절 권한).

- E27 POST /api/ai/conversations: 대화를 만든다. 모델을 부르지 않는다.
- E28 GET /api/ai/conversations/{conversation_id}: 대화와 턴 목록(가림 적용).
- E30 GET /api/ai/turns/{turn_id}: 턴 하나(가림 적용). running이면 다시 조회할 간격을 준다.
- E31 POST /api/ai/turns/{turn_id}/cancel: running인 턴만 cancelled로 바꾼다(조건부 전이).

권한·가림·만료 규칙은 agent_access에 있다. E29(T3)도 같은 함수를 쓴다.

검사 순서(spec 2절): Origin(미들웨어) → 세션(의존성) → 요청 형식 → 속도 제한 → 대상 존재·권한(404) → 상태 충돌(409) → 부작용.
속도 제한을 대상 확인 앞에 둔 것은 E05·E13과 같다. 없는 id·남의 id로도 DB 읽기를 무제한으로 부를 수 없게 하고, 세는 방식이 같아
대상이 있는지도 새지 않는다.

노출 중단(Q11): CS_AGENT_DISABLED를 켜면 E27(새 대화)과 E29(질문, agent_turns)가 503이 된다. E28·E30·E31은 그대로 동작한다.
끄고 켜는 절차는 docs/deployment-guide.md "CS Agent 노출 중단" 절에 있다.
T4(MEG-163) 전에는 위키 문맥이 없으므로 E27 origin wiki는 422다(기술 검토 4절).
로그에는 단계·오류 코드만 남기고 질문·답변·노트 원문은 남기지 않는다.
"""

import logging
import os
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from app.agent_access import (
    TURN_POLL_SECONDS,
    ConversationAccess,
    conversation_payload,
    expire_running_turns,
    read_turns,
    load_conversation,
    load_turn,
    path_uuid,
    turn_payload,
    visible_turns,
)
from app.auth import SessionUser, require_login
from app.ai_explain import SelectionBody, _field_error
from app.errors import ApiError
from app.rate_limit import AI_AGENT_READ, WRITE, RateLimiter, get_rate_limiter
from app.supabase import SupabaseClient, SupabaseConfigError, SupabaseUnavailable, get_supabase

router = APIRouter(prefix="/api")
logger = logging.getLogger("app.agent")

# 노출 중단 플래그(spec Q11, 기술 검토 6절). 끄는 값(0·false·no·off)이나 빈 값이 아니면 켠 것으로 본다(잘못 쓴 값도 막는 쪽).
DISABLE_ENV = "CS_AGENT_DISABLED"
_OFF_VALUES = frozenset({"", "0", "false", "no", "off"})
# 선택 문맥 상한(코드포인트). Q4 임시값 2,000자이며 ai_conversation_selections.text_snapshot 상한과 같다.
MAX_SELECTION_CHARS = 2000
# 주제 이름은 선택 문장의 앞 20자다(spec Q9 권장안). 공백은 하나로 줄인다.
TOPIC_LABEL_CHARS = 20

_MAX_BIGINT = 2**63 - 1
_MAX_INT = 2**31 - 1
_SPACES = re.compile(r"\s+")


def agent_disabled() -> bool:
    """노출 중단 플래그가 켜졌는가. E27과 E29(T3)가 새 대화·새 질문을 받기 전에 본다."""
    return os.environ.get(DISABLE_ENV, "").strip().lower() not in _OFF_VALUES


class ConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: Literal["note", "wiki", "none"]
    note_id: Annotated[StrictInt, Field(ge=1, le=_MAX_BIGINT)] | None = None
    note_revision: Annotated[StrictInt, Field(ge=1, le=_MAX_INT)] | None = None
    selection: SelectionBody | None = None
    wiki_ref: StrictStr | None = None


def _check_request_shape(body: ConversationRequest) -> None:
    """origin과 필드 조합(spec E27). 본문을 읽지 않고 판정한다. 맞지 않으면 422다."""
    if body.origin == "wiki":
        # T4 전에는 위키 문맥을 받지 않는다(기술 검토 4절 T4 전 동작).
        raise _field_error("origin", "invalid_value")
    note_fields = {"note_id": body.note_id, "note_revision": body.note_revision, "selection": body.selection}
    if body.wiki_ref is not None:
        raise _field_error("wiki_ref", "invalid_value")
    if body.origin == "none":
        for name, value in note_fields.items():
            if value is not None:
                raise _field_error(name, "invalid_value")
        return
    for name, value in note_fields.items():
        if value is None:
            raise _field_error(name, "required")
    start, end = body.selection.start, body.selection.end
    if end <= start:
        raise _field_error("selection.end", "out_of_range")
    if end - start > MAX_SELECTION_CHARS:
        raise _field_error("selection.end", "too_long")


def topic_label_of(text: str) -> str:
    return _SPACES.sub(" ", text).strip()[:TOPIC_LABEL_CHARS]


def _remove_conversation(supabase: SupabaseClient, user: SessionUser, conversation_id: str) -> None:
    """선택 문맥을 넣지 못한 대화를 지운다. 지우지 못해도 응답은 그대로이고 7일 보관 정리가 지운다."""
    try:
        supabase.delete_agent_conversation(user.user_id, conversation_id)
    except (SupabaseUnavailable, SupabaseConfigError) as error:
        logger.warning("stage=db conversation not removed: %s", type(error).__name__)


@router.post("/ai/conversations", status_code=201, summary="E27 start a CS Agent conversation")
def create_conversation(
    body: ConversationRequest,
    user: SessionUser = Depends(require_login),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """대화를 만든다. 노트 문맥이면 선택한 문장을 그때의 개정과 함께 저장한다. 모델은 부르지 않는다(spec E27)."""
    if agent_disabled():
        raise ApiError("service_unavailable", stage="flag")
    _check_request_shape(body)
    limiter.check(WRITE, f"user:{user.user_id}")

    if body.origin == "none":
        row = supabase.create_agent_conversation({"user_id": user.user_id, "origin": "none", "topic_label": ""})
        return conversation_payload(ConversationAccess(conversation={**row, "ai_conversation_selections": []}, notes={}))

    # 노트 읽기 권한은 E05와 같다. 일반 사용자의 비공개 노트는 없는 노트와 같은 404다.
    note = supabase.get_note_for_agent(body.note_id, include_unpublished=user.is_operator)
    if note is None:
        raise ApiError("not_found", stage="db")
    # 위치가 달라진 본문에서 엉뚱한 문장을 자르지 않는다.
    if note["revision"] != body.note_revision:
        raise ApiError("conflict", "stale_revision", stage="validate")
    text = note["body_markdown"]
    start, end = body.selection.start, body.selection.end
    if end > len(text):
        raise _field_error("selection.end", "out_of_range")
    snapshot = text[start:end]
    if not snapshot.strip():
        # 공백만 고른 선택은 문맥이 되지 못한다.
        raise _field_error("selection", "invalid_value")

    row = supabase.create_agent_conversation(
        {
            "user_id": user.user_id,
            "origin": "note",
            "note_id": note["id"],
            "note_revision": note["revision"],
            "topic_label": topic_label_of(snapshot),
        }
    )
    if row is None:
        # 확인한 뒤 노트가 지워졌다.
        raise ApiError("not_found", stage="db")
    try:
        selection = supabase.add_agent_selection(
            {
                "conversation_id": row["id"],
                "note_id": note["id"],
                "note_revision": note["revision"],
                "start": start,
                "end": end,
                "text_snapshot": snapshot,
            }
        )
    except Exception:
        _remove_conversation(supabase, user, row["id"])
        raise
    states = {note["id"]: {key: note[key] for key in ("id", "revision", "title", "is_published")}}
    access = ConversationAccess(conversation={**row, "ai_conversation_selections": [selection]}, notes=states)
    return conversation_payload(access)


@router.get("/ai/conversations/{conversation_id}", summary="E28 read a CS Agent conversation and its turns")
def read_conversation(
    conversation_id: str,
    user: SessionUser = Depends(require_login),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """대화와 턴 목록(오래된 순)을 준다. 턴은 E30과 같은 모양이고 같은 가림 함수를 거친다(spec E28, 8절)."""
    target = path_uuid(conversation_id)
    limiter.check(AI_AGENT_READ, f"user:{user.user_id}")
    access = load_conversation(supabase, user, target)
    turns = read_turns(supabase, user, target)
    return {**conversation_payload(access), "turns": visible_turns(supabase, access, turns)}


@router.get("/ai/turns/{turn_id}", summary="E30 read a CS Agent turn")
def read_turn(
    turn_id: str,
    user: SessionUser = Depends(require_login),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """턴 하나를 가림을 적용해 준다. running이면 retry_after_seconds(조회 간격 권장값)를 함께 준다(spec E30)."""
    target = path_uuid(turn_id)
    limiter.check(AI_AGENT_READ, f"user:{user.user_id}")
    turn, access = load_turn(supabase, user, target)
    # 가림은 앞 턴의 출처로도 정해지므로 이 턴까지의 턴을 함께 읽는다.
    turns = read_turns(supabase, user, access.conversation["id"], max_seq=turn["seq"])
    payload = next((p for p in visible_turns(supabase, access, turns) if p["turn_id"] == turn["id"]), None)
    if payload is None:
        # 확인한 뒤 턴이 지워졌다(대화 삭제·보관 정리).
        raise ApiError("not_found", stage="db")
    if payload["status"] == "running":
        payload["retry_after_seconds"] = TURN_POLL_SECONDS
    return payload


@router.post("/ai/turns/{turn_id}/cancel", summary="E31 cancel a running CS Agent turn")
def cancel_turn(
    turn_id: str,
    user: SessionUser = Depends(require_login),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """running인 턴만 cancelled로 바꾼다. 이미 끝났으면 409 turn_not_cancellable이다(spec E31).

    받다 만 답변은 저장하지도 돌려주지도 않는다. 응답의 question으로 클라이언트가 '중단한 질문 다시 넣기'를 한다.
    실행이 만료된 running 턴은 먼저 failed(interrupted)로 바꾸므로 중단할 수 없다.
    """
    target = path_uuid(turn_id)
    limiter.check(WRITE, f"user:{user.user_id}")
    turn, access = load_turn(supabase, user, target)
    if turn["status"] == "running":
        # 만료된 실행은 먼저 failed(interrupted)로 바꾼다. 그 턴은 중단할 수 없다.
        expire_running_turns(supabase, user, access.conversation["id"])
    if not supabase.cancel_agent_turn(user.user_id, turn["id"]):
        if supabase.get_agent_turn(user.user_id, turn["id"]) is None:
            raise ApiError("not_found", stage="db")
        raise ApiError("conflict", "turn_not_cancellable", stage="validate")
    logger.info("stage=cancel turn_id=%s", turn["id"])
    return {"turn_id": turn["id"], "status": "cancelled", "question": turn_payload(turn, None)["question"]}
