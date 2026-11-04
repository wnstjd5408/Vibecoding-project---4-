"""E25·E26 운영자 신고 목록과 처리 (API spec v0.2 2.2·2.4, 권한 4절, 결정 D-062).

운영자만 부른다(방문자 401, 일반 사용자 403). 신고 저장은 E10(reports.py)이다. 신고자의 신원은 목록에 내지 않는다(1.9).
신고 처리와 AI 설명 무효화를 한 트랜잭션으로 묶는 SQL 함수는 만들지 않고, 기존 `ai_invalidate_explanations`와 신고 갱신을
차례로 부른다. 무효화를 먼저 하므로 중간에 실패해도 신고는 열린 채 남아 같은 요청을 다시 보내면 이어서 끝난다(멱등).

속도 제한(그 밖의 쓰기, 사용자당 분당 30회)은 E26 맨 앞에서 센다(E21·E24와 같은 방식). 목록(E25)은 1.8에 정한 제한이
없어 세지 않는다(E19와 같다).
"""

import re
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, StrictBool

from app import session
from app.auth import SessionUser, require_operator
from app.errors import FIELD_MESSAGES, ApiError
from app.rate_limit import WRITE, RateLimiter, get_rate_limiter
from app.supabase import SupabaseClient, get_supabase

router = APIRouter(prefix="/api")

_MAX_BIGINT = 2**63 - 1
_ID_SHAPE = re.compile(r"[1-9][0-9]{0,18}")


def _bigint(value: str) -> int | None:
    """양의 bigint 문자열이면 정수로, 아니면 None이다."""
    if not _ID_SHAPE.fullmatch(value) or int(value) > _MAX_BIGINT:
        return None
    return int(value)


@router.get("/admin/reports", summary="E25 reports for operators")
def list_reports(
    status: Literal["open", "resolved"] = "open",
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: str | None = None,
    user: SessionUser = Depends(require_operator),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """status가 같은 신고를 id 내림차순으로 준다. next_cursor를 다음 요청의 cursor로 보내면 이어서 받는다.

    각 신고는 id, status, body와 대상 요약(target)이다. target은 AI 설명이면 term_key_snapshot·body, 퀴즈 문항이면
    question·answer이고 둘 다 type과 id를 가진다. 신고자는 내지 않는다.
    """
    before_id = None
    if cursor is not None:
        before_id = _bigint(cursor)
        if before_id is None:
            raise ApiError(
                "validation_failed",
                fields=[{"name": "cursor", "reason": "invalid_format", "message": FIELD_MESSAGES["invalid_format"]}],
                stage="validate",
            )
    # 한 개 더 읽어 다음 쪽이 있는지 안다.
    rows = supabase.list_admin_reports(status, limit + 1, before_id)
    reports = rows[:limit]
    next_cursor = str(reports[-1]["id"]) if len(rows) > limit else None
    return {"reports": reports, "next_cursor": next_cursor}


class ResolveReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # 처리 상태는 resolved 하나뿐이다. 되돌리는 엔드포인트는 없다.
    status: Literal["resolved"]
    # 신고마다 운영자가 고른다(D-062). 주지 않으면 설명을 그대로 둔다. 문자열 "true" 같은 값은 형식 오류다.
    invalidate_explanation: StrictBool = False


@router.patch("/admin/reports/{report_id}", summary="E26 resolve a report")
def resolve_report(
    report_id: str,
    body: ResolveReportRequest,
    user: SessionUser = Depends(require_operator),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """신고를 처리됨으로 바꾼다. 응답은 id와 status뿐이다.

    invalidate_explanation이 true이고 대상이 AI 설명이면 그 설명 하나만 무효화한다. 대상이 퀴즈 문항이면 무시한다.
    이미 처리된 신고에 다시 보내도 200이고, true면 무효화를 다시 적용한다(이미 무효화됐으면 아무것도 바뀌지 않는다).
    무효화 뒤 신고 처리에 실패하면(503 등) 같은 요청을 다시 보내면 된다.
    """
    limiter.check(WRITE, f"user:{user.user_id}")
    # 경로의 id 모양이 틀리면 없는 신고와 같은 404다(E21과 같은 규칙).
    target_id = _bigint(report_id)
    if target_id is None:
        raise ApiError("not_found", stage="validate")
    report = supabase.get_admin_report(target_id)
    if report is None:
        raise ApiError("not_found", stage="db")
    if body.invalidate_explanation and report["ai_explanation_id"] is not None:
        supabase.invalidate_ai_explanation(report["ai_explanation_id"])
    resolved_at = datetime.fromtimestamp(session.now(), timezone.utc).isoformat()
    if not supabase.mark_report_resolved(target_id, resolved_at) and report["status"] == "open":
        # 열린 신고였는데 바뀐 행이 없다. 그 사이 다른 운영자가 처리했거나 신고가 지워졌다. 지워졌으면 404다.
        if supabase.get_admin_report(target_id) is None:
            raise ApiError("not_found", stage="db")
    return {"id": target_id, "status": "resolved"}
