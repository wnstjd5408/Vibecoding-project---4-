"""E10 오류 신고 보내기 (API spec v0.2 2.2·2.4·3절 예시 7, 권한 4절).

신고 대상은 그 용어의 지금 유효한 공유 AI 설명이거나 자기 퀴즈 세트의 문항이다. 없는 대상, 남의 문항, 1회용 설명(id가
없다), 무효화된 설명은 모두 같은 404다. 같은 사용자·같은 대상의 열린 신고는 하나라서 다시 보내면 기존 신고를 200으로
돌려준다. 신고 목록·처리는 E25·E26이다.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from pydantic_core import PydanticCustomError

from app.auth import SessionUser, require_login
from app.errors import ApiError
from app.rate_limit import WRITE, RateLimiter, get_rate_limiter
from app.supabase import SupabaseClient, get_supabase

router = APIRouter(prefix="/api")

# ai_explanations.id·quiz_items.id는 bigint다.
_MAX_BIGINT = 2**63 - 1
# 신고 본문 상한. 파이썬 문자열 길이는 유니코드 코드포인트라 화면(frontend/src/reports/report.ts)과 같은 기준이다.
# DB에도 같은 check(reports_body_length_check)가 있다.
REPORT_BODY_LIMIT = 1000


class ReportTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ai_explanation", "quiz_item"]
    id: Annotated[StrictInt, Field(ge=1, le=_MAX_BIGINT)]


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: ReportTarget
    # 본문은 비어 있어도 된다(스키마 default '').
    body: Annotated[str, Field(max_length=REPORT_BODY_LIMIT)] = ""

    @field_validator("body")
    @classmethod
    def storable_text(cls, value: str) -> str:
        # Postgres text는 NUL(U+0000)을 담지 못하고, 짝 없는 서로게이트는 UTF-8로 인코딩되지 않는다. DB나 전송이
        # 거절하면 500이 되므로 형식 오류(422)로 먼저 막는다(admin_glossary와 같은 방식).
        if "\x00" in value:
            raise PydanticCustomError("invalid_characters", "Value contains a NUL character")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise PydanticCustomError("invalid_characters", "Value is not valid Unicode text") from None
        return value


@router.post("/reports", summary="E10 report a wrong AI explanation or quiz item")
def send_report(
    report: ReportRequest,
    response: Response,
    user: SessionUser = Depends(require_login),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """새로 저장하면 201, 같은 대상의 열린 신고가 이미 있으면 200으로 기존 신고를 준다. 응답은 id와 status뿐이다.

    방문자·비활성 계정은 401이다(의존성). 형식 검사는 본문 모델이 한다(422).
    """
    # 그 밖의 쓰기 제한(사용자당 분당 30회, 1.8)을 대상 확인보다 먼저 센다. 없는 id로 404만 받는 요청도 세어
    # DB 읽기·쓰기 시도를 무제한으로 만들지 못한다(E07과 같은 방식, 명세 1.2 순서의 예외).
    limiter.check(WRITE, f"user:{user.user_id}")
    target = report.target
    # 확인과 저장은 별도 요청이다. 확인 뒤 저장 전에 설명이 무효화되면 무효 설명에 대한 신고가 하나 저장될 수 있다
    # (운영자 목록에 남는 정도이고 사용자에게 보이지 않는다, MEG-88 리뷰에서 수용). 퀴즈 문항 삭제는 외래 키가 막는다.
    if not supabase.report_target_exists(target.type, target.id, user.user_id):
        raise ApiError("not_found", stage="db")
    created = supabase.create_report(user.user_id, target.type, target.id, report.body)
    if created is None:
        # 확인한 뒤 대상이 지워졌다.
        raise ApiError("not_found", stage="db")
    row, is_new = created
    response.status_code = 201 if is_new else 200
    return {"id": row["id"], "status": row["status"]}
