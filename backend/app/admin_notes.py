"""E15~E18 운영자 노트. 출처·과목·상위 노트 쓰기는 MEG-79 범위에서 제외한다."""

import logging
import re
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator
from pydantic_core import PydanticCustomError

from app.auth import SessionUser, require_operator
from app.errors import ApiError, request_id_of
from app.notes import SIGNED_URL_SECONDS, _expires_at
from app.rate_limit import SIGNED_URL, WRITE, RateLimiter, get_rate_limiter
from app.supabase import SupabaseClient, SupabaseConfigError, SupabaseUnavailable, get_supabase

router = APIRouter(prefix="/api/admin/notes")
logger = logging.getLogger("app.admin_notes")


def _note_id(value: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > 2**63 - 1:
        raise ApiError("not_found", stage="validate")
    return int(value)


class NoteFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[StrictStr, Field(min_length=1, max_length=300)] = ""
    body_markdown: Annotated[StrictStr, Field(max_length=200_000)] = ""
    studied_on: date | None = None
    study_minutes: Annotated[StrictInt, Field(ge=0, le=2**31 - 1)] | None = None
    importance: Literal["상", "중", "하"] | None = None
    understanding: Annotated[StrictInt, Field(ge=1, le=5)] | None = None
    needs_review: StrictBool = False
    memo: StrictStr | None = None
    is_published: StrictBool = False

    @field_validator("title", "body_markdown", "memo")
    @classmethod
    def valid_text(cls, value: str | None) -> str | None:
        # PostgreSQL text는 NUL과 단독 surrogate를 저장할 수 없다.
        if value is not None and ("\x00" in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value)):
            raise PydanticCustomError("invalid_characters", "Invalid text")
        return value

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        if not value.strip():
            raise PydanticCustomError("missing", "Title is required")
        return value

    @field_validator("studied_on", mode="before")
    @classmethod
    def date_string(cls, value):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)):
            raise PydanticCustomError("date_format", "Expected YYYY-MM-DD")
        return value


class CreateNote(NoteFields):
    title: Annotated[StrictStr, Field(min_length=1, max_length=300)]


class UpdateNote(NoteFields):
    # 지정하지 않은 열은 보내지 않는다. 명시적인 null은 nullable 열만 허용한다.
    expected_revision: Annotated[StrictInt, Field(ge=1, le=2**31 - 1)] | None = None


@router.get("/{note_id}", summary="E15 operator note with image URLs")
def read_note(
    note_id: str,
    user: SessionUser = Depends(require_operator),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    note = supabase.get_admin_note(_note_id(note_id))
    if note is None:
        raise ApiError("not_found", stage="db")
    rows = note["note_images"]
    images = {}
    if rows:
        limiter.check(SIGNED_URL, f"user:{user.user_id}")
        expires_at = _expires_at(SIGNED_URL_SECONDS)
        try:
            signed = supabase.sign_note_images(sorted({r["storage_path"] for r in rows}), SIGNED_URL_SECONDS)
            if any(not signed.get(r["storage_path"]) for r in rows):
                raise SupabaseUnavailable("incomplete image signing")
        except (SupabaseConfigError, SupabaseUnavailable):
            # E05의 누락 이미지 제외 정책은 E15에 적용하지 않는다(API spec 1.4.4).
            raise ApiError("service_unavailable", stage="storage") from None
        images = {r["notion_block_id"]: {
            "url": signed[r["storage_path"]], "alt": r["alt"], "expires_at": expires_at,
        } for r in rows}
    fields = ("id", "revision", "title", "body_markdown", "studied_on", "study_minutes", "importance",
              "understanding", "needs_review", "memo", "is_published", "parent_note_id", "created_at", "updated_at")
    return {
        **{key: note[key] for key in fields},
        "subjects": sorted((link["subjects"] for link in note["note_subjects"]), key=lambda row: row["id"]),
        "sources": [{"url": r["url"], "label": r["label"]} for r in sorted(note["note_sources"], key=lambda r: r["id"])],
        "images": images,
    }


@router.post("", status_code=201, summary="E16 create a note")
def create_note(
    body: CreateNote,
    user: SessionUser = Depends(require_operator),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    limiter.check(WRITE, f"user:{user.user_id}")
    saved = supabase.create_note(body.model_dump(mode="json"))
    return {"id": saved["id"], "revision": saved["revision"]}


@router.patch("/{note_id}", summary="E17 update or publish a note")
def update_note(
    note_id: str,
    body: UpdateNote,
    user: SessionUser = Depends(require_operator),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    target = _note_id(note_id)
    # 대상 확인과 쓰기는 하나의 RPC다. 제한을 먼저 세어 DB 호출을 제한한다.
    limiter.check(WRITE, f"user:{user.user_id}")
    result = supabase.update_note(target, body.model_dump(mode="json", exclude_unset=True, exclude={"expected_revision"}), body.expected_revision)
    if result["status"] == "not_found":
        raise ApiError("not_found", stage="db")
    if result["status"] == "stale_revision":
        raise ApiError("conflict", "stale_revision", stage="db")
    return {key: result[key] for key in ("id", "revision", "is_published")}


@router.delete("/{note_id}", status_code=204, summary="E18 delete a note")
def delete_note(
    note_id: str,
    request: Request,
    user: SessionUser = Depends(require_operator),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    target = _note_id(note_id)
    limiter.check(WRITE, f"user:{user.user_id}")
    result = supabase.delete_note(target)
    if result["status"] == "not_found":
        raise ApiError("not_found", stage="db")
    try:
        supabase.retry_note_image_deletions()
    except (SupabaseConfigError, SupabaseUnavailable) as exc:
        logger.warning("request_id=%s stage=storage note_delete_retry_failed kind=%s", request_id_of(request), type(exc).__name__)
    return Response(status_code=204)
