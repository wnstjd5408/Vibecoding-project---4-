"""E12 퀴즈 답 제출, E14 꼬리 질문 답 저장 (MEG-92, API spec v0.2 2.4·1.4.4·1.7·6.5·6.6, 권한 4절, 3절 예시 6).

로그인한 사용자가 자기 퀴즈 세트의 문항에만 답한다. 남의 문항·없는 문항은 같은 404다. 답을 받으면 정답과 해설을 준다.
꼬리 질문은 채점하지 않으므로 응답에 정오 필드가 없다(D-028). 두 엔드포인트 모두 AI를 부르지 않는다.

같은 내용을 다시 보내면 같은 응답(200)이고, 다른 내용이면 409 already_answered다(1.7). 처음 쓰는 요청과 동시에 들어온
요청도 같은 규칙을 따른다. 저장은 기본 키 충돌을 무시하는 삽입(E12)과 아직 답이 없는 슬롯에만 하는 조건부 갱신(E14)이라
먼저 저장된 답을 덮어쓰지 않고, 저장된 답을 내 답과 비교해 판정한다. E12·E14는 날짜를 검사하지 않는다(6.6): 자정을 넘겨도
이미 낸 문항의 답은 받는다.

검사 순서: 로그인(의존성) → 본문 형식(422) → 경로 형식(404) → 사용자별 쓰기 제한(429) → 대상 확인(404) → 이미 답했는지(409)
→ 저장. 쓰기 제한을 대상 확인보다 먼저 세는 것은 E08·E10과 같은 이유다(없는 id로 DB 읽기를 무제한으로 만들지 못하게 한다,
API spec 1.2 순서의 예외). 로그에는 답변 원문을 남기지 않는다(5.6).
"""

import re
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from app.auth import SessionUser, require_login
from app.errors import ApiError
from app.quiz import _one, followup_progress
from app.rate_limit import WRITE, RateLimiter, get_rate_limiter
from app.supabase import SupabaseClient, get_supabase

router = APIRouter(prefix="/api")

# 답변 길이 상한(스키마 check quiz_answers_user_answer_length_check, quiz_followups_user_answer_length_check).
# 파이썬 문자열 길이는 유니코드 코드포인트라 DB의 char_length와 같은 기준이다.
ANSWER_LIMIT = 1000
# quiz_items.id는 bigint다. 경로 값이 틀리면 422가 아니라 없는 문항과 같은 404다(E08과 같은 규칙).
_MAX_BIGINT = 2**63 - 1
_ITEM_ID_SHAPE = re.compile(r"[1-9][0-9]{0,18}")
_SEQ_SHAPE = re.compile(r"[12]")


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: Annotated[str, Field(min_length=1, max_length=ANSWER_LIMIT)]

    @field_validator("answer")
    @classmethod
    def storable_text(cls, value: str) -> str:
        # 공백뿐인 답은 빈 값과 같다(required). 사용자가 쓴 글자는 바꾸지 않고 그대로 저장한다.
        if not value.strip():
            raise PydanticCustomError("string_too_short", "Value is blank", {"min_length": 1})
        # Postgres text는 NUL(U+0000)을 담지 못하고, 짝 없는 서로게이트는 UTF-8로 인코딩되지 않는다. 저장이 거절되면
        # 500이 되므로 형식 오류(422)로 먼저 막는다(E10·admin_glossary와 같은 방식).
        if "\x00" in value:
            raise PydanticCustomError("invalid_characters", "Value contains a NUL character")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise PydanticCustomError("invalid_characters", "Value is not valid Unicode text") from None
        return value


def _item_id(raw: str) -> int:
    if not _ITEM_ID_SHAPE.fullmatch(raw) or int(raw) > _MAX_BIGINT:
        raise ApiError("not_found", stage="validate")
    return int(raw)


def _already_answered() -> ApiError:
    return ApiError("conflict", "already_answered", stage="validate")


@router.post("/quiz/items/{item_id}/answer", summary="E12 submit an answer to a quiz item")
def answer_item(
    item_id: str,
    body: AnswerRequest,
    user: SessionUser = Depends(require_login),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """답을 저장하고 정답·해설을 준다. 같은 답을 다시 보내면 같은 응답(200), 다른 답이면 409 already_answered다.

    응답에 정오 판정 필드는 없다. can_request_followup과 followups_remaining은 그 문항의 꼬리 질문 상태다(6.5).
    """
    target = _item_id(item_id)
    limiter.check(WRITE, f"user:{user.user_id}")
    item = supabase.get_quiz_item_for_answer(user.user_id, target)
    if item is None:
        raise ApiError("not_found", stage="db")

    existing = _one(item.get("quiz_answers"))
    if existing is not None:
        stored = existing["user_answer"]
    else:
        stored = supabase.save_quiz_answer(target, body.answer)
        if stored is None:
            # 확인한 뒤 문항이 지워졌다.
            raise ApiError("not_found", stage="db")
    if stored != body.answer:
        # 먼저 저장된 다른 답이 있다. 내 쓰기는 아무 행도 바꾸지 않았다.
        raise _already_answered()

    can_request, remaining = followup_progress(True, item.get("quiz_followups") or [])
    return {
        "item_id": item["id"],
        "your_answer": stored,
        "correct_answer": item["answer"],
        "explanation": item["explanation"],
        "difficulty": item["difficulty"],
        "can_request_followup": can_request,
        "followups_remaining": remaining,
    }


@router.put("/quiz/items/{item_id}/followups/{seq}/answer", summary="E14 save the answer to a follow-up question")
def answer_followup(
    item_id: str,
    seq: str,
    body: AnswerRequest,
    user: SessionUser = Depends(require_login),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """질문이 만들어진 꼬리 질문에 답을 저장한다. 같은 답이면 200, 다른 답이면 409 already_answered다.

    아직 만들어지지 않은 seq(슬롯이 없거나 질문이 비어 있음)와 1·2가 아닌 seq는 404다(2.4절, 제안). 채점하지 않는다.
    """
    target = _item_id(item_id)
    if not _SEQ_SHAPE.fullmatch(seq):
        raise ApiError("not_found", stage="validate")
    number = int(seq)
    limiter.check(WRITE, f"user:{user.user_id}")
    item = supabase.get_quiz_item_for_answer(user.user_id, target)
    if item is None:
        raise ApiError("not_found", stage="db")
    slots = item.get("quiz_followups") or []
    slot = next((f for f in slots if f["seq"] == number), None)
    if slot is None or not slot.get("question"):
        raise ApiError("not_found", stage="db")

    if slot.get("user_answer") is not None:
        stored = slot["user_answer"]
    else:
        stored = supabase.save_followup_answer(target, number, body.answer)
        if stored is None:
            raise ApiError("not_found", stage="db")
    if stored != body.answer:
        raise _already_answered()

    answered_slots = [{**f, "user_answer": stored} if f["seq"] == number else f for f in slots]
    # 꼬리 질문이 있는 문항은 이미 답한 문항이다(E13이 답한 문항에서만 만든다).
    can_request, _ = followup_progress(True, answered_slots)
    return {"seq": number, "answered": True, "can_request_followup": can_request}
