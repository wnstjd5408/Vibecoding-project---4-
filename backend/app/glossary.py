"""E06 사전 용어 읽기, E07 열람 기록 (API spec v0.2 2.2·2.4·3절 예시 2, 권한 4절).

사전 이미지는 공개 읽기 버킷의 주소로 준다(기술 검토 Q7 결정 (a), 2026-11-02). 노트 이미지(E05)와 달리
서명 요청이 없다.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app import session
from app.auth import SessionUser, get_session_user
from app.errors import ApiError
from app.net import client_ip, ip_bucket
from app.rate_limit import PUBLIC_READ, WRITE, RateLimiter, get_rate_limiter
from app.supabase import SupabaseClient, get_supabase

router = APIRouter(prefix="/api")

# terms.id는 bigint다. E06은 경로 값이 틀려도 422가 아니라 404다(1.4.2 E06 행에 422가 없다).
_MAX_BIGINT = 2**63 - 1
_TERM_ID_SHAPE = re.compile(r"[1-9][0-9]{0,18}")
# 한국은 서머타임이 없어 UTC+9 고정이다(1.6).
_KST = timezone(timedelta(hours=9))


def study_date() -> str:
    """지금의 KST 날짜(YYYY-MM-DD). 시험은 session.now를 바꿔 고정한다."""
    return datetime.fromtimestamp(session.now(), _KST).date().isoformat()


def glossary_payload(row: dict, supabase: SupabaseClient) -> dict:
    """E06 응답의 term·body_markdown·images. E09의 사전 갈래(source: glossary)도 같은 모양을 쓴다."""
    return {
        "term": {"id": row["id"], "key": row["key"], "label": row["label"]},
        "body_markdown": row["glossary_entries"]["body_markdown"],
        "images": [
            # storage_path는 따로 내보내지 않는다. 공개 주소 안에 들어가는 것만 예외다(1.9, 2026-11-02 결정).
            # alt가 비어 있으면 빈 문자열이다(장식 이미지). 응답 형식은 문자열 하나로 유지한다.
            {"id": image["id"], "url": supabase.glossary_image_url(image["storage_path"]), "alt": image["alt"] or ""}
            for image in row["glossary_images"]
        ],
    }


@router.get("/glossary/{term_id}", summary="E06 glossary term with image URLs")
def read_glossary_term(
    term_id: str,
    request: Request,
    user: SessionUser | None = Depends(get_session_user),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """사전 용어(glossary_entries 행이 있는 terms)만 준다. AI로만 설명된 용어와 없는 용어는 같은 404다.

    is_favorite는 로그인했을 때만 넣는다. 방문자 응답에는 키가 없다(3절 예시 2).
    """
    if not _TERM_ID_SHAPE.fullmatch(term_id) or int(term_id) > _MAX_BIGINT:
        raise ApiError("not_found", stage="validate")
    # 공개 읽기 제한은 E04·E05와 같은 IP 키다. E05처럼 DB를 읽기 전에 센다. 없는 id를 무제한으로 두드려
    # DB를 읽게 하지 못한다(명세 1.2 순서의 예외, 2026-11-02 김준성 결정).
    limiter.check(PUBLIC_READ, f"ip:{ip_bucket(client_ip(request))}")
    row = supabase.get_glossary_entry(int(term_id), user.user_id if user is not None else None)
    if row is None:
        raise ApiError("not_found", stage="db")

    body = glossary_payload(row, supabase)
    if user is not None:
        # 세션 사용자의 즐겨찾기 행만 같은 조회로 읽었다. 다른 사용자의 행은 오지 않는다.
        body["is_favorite"] = bool(row["favorites"])
    return body


class TermViewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # 문자열 "7"·true·7.0은 받지 않는다(invalid_format).
    term_id: Annotated[StrictInt, Field(ge=1, le=_MAX_BIGINT)]


@router.post("/term-views", summary="E07 record a term view for today (KST)")
def record_term_view(
    body: TermViewRequest,
    user: SessionUser | None = Depends(get_session_user),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """로그인한 사용자의 오늘(KST) 열람을 한 건 남긴다. 같은 날 다시 불러도 한 건이고 응답은 같다.

    세션이 없거나 비활성이면 오류 없이 recorded: false다. 이때는 형식만 검사하고 DB 조회·속도 제한을
    하지 않는다(2026-11-02 김준성 결정). 사전 용어와 AI로 설명된 용어 모두 기록 대상이다(2.4).
    """
    if user is None:
        return {"recorded": False}
    # 그 밖의 쓰기 제한(사용자당 분당 30회, 1.8)을 용어 확인보다 먼저 센다. 없는 term_id로 404만 받는 요청도
    # 세어 DB 쓰기 시도를 무제한으로 만들지 못한다(명세 1.2 순서의 예외, 2026-11-02 김준성 결정, spec 10.5).
    limiter.check(WRITE, f"user:{user.user_id}")
    if not supabase.record_term_view(user.user_id, body.term_id, study_date()):
        # 용어가 없다. 따로 조회하지 않고 외래 키 결과로 판정한다.
        raise ApiError("not_found", stage="db")
    return {"recorded": True}
