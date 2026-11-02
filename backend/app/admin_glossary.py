"""E19~E23 운영자 사전: 목록, 등록·갱신, 사전 설명·이미지 삭제, 이미지 올리기·삭제 (API spec v0.2 2.2~2.4, 권한 4절).

운영자만 부른다(방문자 401, 일반 사용자 403). 여러 문장을 묶어야 하는 쓰기는 SQL 함수가 한 트랜잭션으로 한다
(Q-N1, 마이그레이션 20261102160000). terms 행을 지우는 엔드포인트는 없다(Q-N4).
Storage 객체 삭제는 트랜잭션 뒤에 시도하고, 실패해도 204로 끝낸다. 삭제 작업은 pending으로 남는다(1.4.4).

속도 제한(그 밖의 쓰기, 사용자당 분당 30회)은 E24처럼 처리 맨 앞에서 센다. E21·E23은 대상 확인과 삭제가
한 SQL 함수라 1.2의 순서(대상 확인 뒤 제한)를 지킬 수 없다. E19(목록)는 1.8에 정한 제한이 없어 세지 않는다.
"""

import logging
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator
from pydantic_core import PydanticCustomError

from app.auth import SessionUser, require_operator
from app.errors import FIELD_MESSAGES, ApiError, request_id_of
from app.glossary_spans import normalize_key
from app.images import MAX_UPLOAD_BYTES, ImageRejected, reencode_upload
from app.rate_limit import WRITE, RateLimiter, get_rate_limiter
from app.supabase import SupabaseClient, SupabaseConfigError, SupabaseUnavailable, get_supabase

logger = logging.getLogger("app.admin_glossary")

router = APIRouter(prefix="/api")

_MAX_BIGINT = 2**63 - 1
_ID_SHAPE = re.compile(r"[1-9][0-9]{0,18}")
# terms.key·label 1~200자(스키마 check), glossary_entries.body_markdown 200,000자(스키마 gap v06 check)
_MAX_LABEL = 200
_MAX_BODY = 200_000
# glossary_images.alt에는 길이 제한이 없다. 화면 대체 문구로 충분한 상한을 둔다(AI 제안, spec에 숫자 없음).
_MAX_ALT = 1000


def _path_id(value: str) -> int:
    """경로의 id. 모양이 틀리면 없는 대상과 같은 404다(E06과 같은 규칙)."""
    if not _ID_SHAPE.fullmatch(value) or int(value) > _MAX_BIGINT:
        raise ApiError("not_found", stage="validate")
    return int(value)


def _field_error(name: str, reason: str) -> ApiError:
    return ApiError(
        "validation_failed",
        fields=[{"name": name, "reason": reason, "message": FIELD_MESSAGES[reason]}],
        stage="validate",
    )


def _remove_objects(request: Request, supabase: SupabaseClient, jobs: list[dict[str, Any]]) -> None:
    """트랜잭션 뒤 객체 삭제. 실패해도 응답은 성공이고 삭제 작업이 pending으로 남는다(1.4.4)."""
    try:
        supabase.remove_glossary_objects(jobs)
    except (SupabaseUnavailable, SupabaseConfigError) as exc:
        logger.warning(
            "request_id=%s stage=storage object_delete_failed jobs=%d kind=%s",
            request_id_of(request), len(jobs), type(exc).__name__,
        )


@router.get("/admin/glossary", summary="E19 glossary terms for operators")
def list_glossary(
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: str | None = None,
    user: SessionUser = Depends(require_operator),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """사전 용어의 id·key·label을 id 내림차순으로 준다. next_cursor를 다음 요청의 cursor로 보내면 이어서 받는다."""
    before_id = None
    if cursor is not None:
        if not _ID_SHAPE.fullmatch(cursor) or int(cursor) > _MAX_BIGINT:
            raise _field_error("cursor", "invalid_format")
        before_id = int(cursor)
    # 한 개 더 읽어 다음 쪽이 있는지 안다.
    rows = supabase.list_admin_glossary_terms(limit + 1, before_id)
    terms = rows[:limit]
    next_cursor = str(terms[-1]["id"]) if len(rows) > limit else None
    return {"terms": terms, "next_cursor": next_cursor}


class GlossaryEntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: StrictStr = Field(min_length=1, max_length=_MAX_LABEL)
    body_markdown: StrictStr = Field(default="", max_length=_MAX_BODY)

    @field_validator("label", "body_markdown")
    @classmethod
    def no_nul(cls, value: str) -> str:
        # Postgres text는 NUL(U+0000)을 담지 못한다. DB가 거절하면 500이 되므로 형식 오류로 먼저 막는다.
        if "\x00" in value:
            raise PydanticCustomError("invalid_characters", "Value contains a NUL character")
        return value


@router.post("/admin/glossary", status_code=201, summary="E20 create or update a glossary entry by term key")
def save_glossary_entry(
    body: GlossaryEntryRequest,
    response: Response,
    user: SessionUser = Depends(require_operator),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """label에서 key를 만들어 사전 설명을 넣거나 고친다. 사전 설명이 새로 생기면 201, 이미 있었으면 200이다.

    같은 key의 용어가 AI로만 설명돼 있었으면 사전 용어로 바꾸고 그 AI 설명을 무효화한다(D-020, 같은 트랜잭션).
    key가 바뀌는 이름 변경은 없다. 다른 key면 다른 용어다.
    """
    limiter.check(WRITE, f"user:{user.user_id}")
    label = body.label.strip()
    key = normalize_key(label)
    if not key:
        # 공백뿐인 이름
        raise _field_error("label", "required")
    if len(key) > _MAX_LABEL:
        # NFC 정규화로 글자 수가 늘어난 드문 경우
        raise _field_error("label", "too_long")
    saved = supabase.upsert_glossary_entry(key, label, body.body_markdown, user.user_id)
    if not saved["created"]:
        response.status_code = 200
    return {"term": {"id": saved["id"], "key": saved["key"], "label": saved["label"]}}


@router.delete("/admin/glossary/{term_id}", status_code=204, summary="E21 delete a glossary entry and its images")
def delete_glossary_entry(
    term_id: str,
    request: Request,
    user: SessionUser = Depends(require_operator),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """사전 설명과 사전 이미지만 지운다. 용어(terms 행)와 즐겨찾기·열람 기록·퀴즈 후보는 남고 source는 'ai'가 된다."""
    limiter.check(WRITE, f"user:{user.user_id}")
    jobs = supabase.delete_glossary_entry(_path_id(term_id))
    if jobs is None:
        raise ApiError("not_found", stage="db")
    _remove_objects(request, supabase, jobs)
    return Response(status_code=204)


@router.post("/admin/glossary/{term_id}/images", status_code=201, summary="E22 upload a glossary image")
def upload_glossary_image(
    term_id: str,
    request: Request,
    file: UploadFile = File(),
    alt: str | None = Form(default=None, max_length=_MAX_ALT),
    user: SessionUser = Depends(require_operator),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """png·jpeg·webp, 4MB 이하. 내용으로 형식을 판정하고 메타데이터를 지워 다시 인코딩한 뒤 올린다.

    순서(1.4.4): 삭제 작업(pending) → Storage 업로드 → 이미지 행과 작업 삭제(한 트랜잭션).
    업로드 실패는 503, 그 뒤 DB 실패는 500이다. 도중에 멈추면 남은 작업이 객체를 지울 대상이 된다.
    """
    limiter.check(WRITE, f"user:{user.user_id}")
    target = _path_id(term_id)
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    try:
        image = reencode_upload(data)
    except ImageRejected as exc:
        if exc.kind == "too_large":
            raise ApiError("payload_too_large", stage="validate") from None
        if exc.kind == "unsupported":
            raise ApiError("unsupported_media_type", stage="validate") from None
        raise _field_error("file", "invalid_format") from None
    if not supabase.glossary_entry_exists(target):
        raise ApiError("not_found", stage="db")

    if alt is not None and "\x00" in alt:
        raise _field_error("alt", "invalid_format")
    alt_text = (alt or "").strip() or None
    object_path = f"terms/{target}/{uuid.uuid4().hex}.{image.extension}"
    job_id = supabase.create_glossary_upload_job(object_path)
    supabase.upload_glossary_image(object_path, image.data, image.content_type)
    try:
        image_id = supabase.add_glossary_image(target, object_path, alt_text, job_id)
    except SupabaseUnavailable:
        # 올린 뒤의 DB 실패는 503이 아니라 500이다(1.4.4). 자동 재시도로 같은 파일이 두 번 올라가지 않게 한다.
        raise ApiError("internal_error", stage="db") from None
    if image_id is None:
        # 그 사이 사전 설명이 지워졌다. 방금 올린 객체를 지워 본다(실패하면 작업이 남는다).
        _remove_objects(request, supabase, [{"job_id": job_id, "object_path": object_path}])
        raise ApiError("not_found", stage="db")
    return {"id": image_id}


@router.delete(
    "/admin/glossary/{term_id}/images/{image_id}", status_code=204, summary="E23 delete a glossary image"
)
def delete_glossary_image(
    term_id: str,
    image_id: str,
    request: Request,
    user: SessionUser = Depends(require_operator),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    limiter.check(WRITE, f"user:{user.user_id}")
    job = supabase.delete_glossary_image(_path_id(term_id), _path_id(image_id))
    if job is None:
        raise ApiError("not_found", stage="db")
    _remove_objects(request, supabase, [job])
    return Response(status_code=204)
