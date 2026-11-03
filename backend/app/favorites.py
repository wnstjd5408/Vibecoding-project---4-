"""E08 즐겨찾기 추가·해제 (API spec v0.2 2.2·2.4·3절 예시 4, 권한 4절, 결정 D-043).

로그인한 사용자만 쓴다(방문자·비활성 계정 401). 사용자 id는 본문이 아니라 세션에서만 꺼낸다. 하나의 PUT이 추가와 해제를
모두 맡고, 응답은 바뀐 뒤의 상태다. 추가하면 그날(KST) favorite_events 한 건이 남고, 해제해도 그 이력은 지우지 않는다
(해제해도 그날 퀴즈 후보에 남는다). 둘을 한 트랜잭션으로 묶는 SQL 함수는 만들지 않는다. 두 쓰기 모두 충돌을 무시해서 같은
요청을 다시 보내면 이어서 끝난다.

속도 제한(그 밖의 쓰기, 사용자당 분당 30회)은 E07과 같은 이유로 용어 확인보다 먼저 센다. 없는 term_id를 계속 보내
DB 쓰기 시도를 무제한으로 만들지 못하게 한다.
"""

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StrictBool

from app.auth import SessionUser, require_login
from app.errors import ApiError
from app.glossary import study_date
from app.rate_limit import WRITE, RateLimiter, get_rate_limiter
from app.supabase import SupabaseClient, get_supabase

router = APIRouter(prefix="/api")

# terms.id는 bigint다. 경로 값이 틀리면 422가 아니라 없는 용어와 같은 404다(E06·E21과 같은 규칙).
_MAX_BIGINT = 2**63 - 1
_TERM_ID_SHAPE = re.compile(r"[1-9][0-9]{0,18}")


class FavoriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # 문자열 "true"·숫자 1·null은 받지 않는다(invalid_format). 빠지면 required다.
    favorited: StrictBool


@router.put("/favorites/{term_id}", summary="E08 add or remove a favorite term")
def set_favorite(
    term_id: str,
    body: FavoriteRequest,
    user: SessionUser = Depends(require_login),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """favorited가 true면 즐겨찾기에 넣고 오늘(KST) 이력을 남기고, false면 즐겨찾기만 지운다. 응답은 term_id와 is_favorite이다.

    이미 즐겨찾기한 용어에 true를, 즐겨찾기가 아닌 용어에 false를 다시 보내도 200이고 아무것도 바뀌지 않는다(멱등).
    terms에 없는 용어는 true·false 모두 404다. 방문자·비활성 계정은 401이다(의존성).
    """
    if not _TERM_ID_SHAPE.fullmatch(term_id) or int(term_id) > _MAX_BIGINT:
        raise ApiError("not_found", stage="validate")
    limiter.check(WRITE, f"user:{user.user_id}")
    target = int(term_id)
    if body.favorited:
        found = supabase.favorite_term(user.user_id, target, study_date())
    else:
        found = supabase.unfavorite_term(user.user_id, target)
    if not found:
        raise ApiError("not_found", stage="db")
    return {"term_id": target, "is_favorite": body.favorited}
