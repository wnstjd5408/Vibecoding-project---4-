"""E04 과목·노트 목록 (API spec v0.2 2.2·2.4·1.5, 권한 4절).

운영자가 아니면 공개 노트만 DB에서 읽는다. 비공개 노트의 존재·id·수가 응답에 새지 않게 한다(PRD v0.5 AC-2).
"""

from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.auth import SessionUser, get_session_user
from app.net import client_ip, ip_bucket
from app.rate_limit import PUBLIC_READ, RateLimiter, get_rate_limiter
from app.supabase import SupabaseClient, get_supabase

router = APIRouter(prefix="/api")

# subjects.id는 bigint다. 범위 밖 값은 DB에 묻기 전에 422로 끝낸다.
_MAX_BIGINT = 2**63 - 1


@router.get("/notes", summary="E04 subjects and notes")
def list_notes(
    request: Request,
    subject_id: Annotated[int | None, Query(ge=1, le=_MAX_BIGINT)] = None,
    user: SessionUser | None = Depends(get_session_user),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """subjects는 subject_id와 상관없이 전부 준다. 화면이 과목 목록을 그대로 그리고 노트만 거른다."""
    # 검사 순서 6번(형식 검사 뒤)이라 의존성이 아니라 여기서 센다. 422로 끝난 요청은 세지 않는다.
    # 공개 읽기 제한은 IP당이다(1.8). 로그인 여부와 상관없이 같은 키로 센다.
    limiter.check(PUBLIC_READ, f"ip:{ip_bucket(client_ip(request))}")
    operator = user is not None and user.is_operator
    notes = supabase.list_notes(include_unpublished=operator)
    names = {row["id"]: row["name"] for row in supabase.list_subjects()}

    def subject_ids(note: dict) -> list[int]:
        # 두 조회 사이에 연결이 바뀌어 subjects에 없는 과목 id는 뺀다.
        return sorted(link["subject_id"] for link in note["note_subjects"] if link["subject_id"] in names)

    counts = Counter(sid for note in notes for sid in subject_ids(note))
    visible = {note["id"] for note in notes}
    subjects = [
        {"id": sid, "name": name, "note_count": counts[sid]}
        for sid, name in names.items()
        # 공개 노트가 0개인 과목은 운영자가 아니면 뺀다(2.4).
        if operator or counts[sid] > 0
    ]

    items = []
    for note in notes:
        ids = subject_ids(note)
        if subject_id is not None and subject_id not in ids:
            continue
        parent = note["parent_note_id"]
        item = {
            "id": note["id"],
            "title": note["title"],
            "studied_on": note["studied_on"],
            "subjects": [{"id": sid, "name": names[sid]} for sid in ids],
            # 상위 노트가 이 사용자에게 안 보이면 null이다. 비공개 노트의 id를 숨긴다.
            "parent_note_id": parent if parent in visible else None,
        }
        if operator:
            item |= {
                "is_published": note["is_published"],
                "revision": note["revision"],
                "needs_review": note["needs_review"],
            }
        items.append(item)
    return {"subjects": subjects, "notes": items}
