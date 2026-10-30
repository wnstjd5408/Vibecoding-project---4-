"""E04 과목·노트 목록, E05 노트 읽기 (API spec v0.2 2.2·2.4·1.5, 권한 4절).

운영자가 아니면 공개 노트만 DB에서 읽는다. 비공개 노트의 존재·id·수가 응답에 새지 않게 한다(PRD v0.5 AC-2).
"""

import logging
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app import session
from app.auth import SessionUser, get_session_user
from app.errors import ApiError
from app.glossary_spans import find_spans
from app.net import client_ip, ip_bucket
from app.rate_limit import PUBLIC_READ, SIGNED_URL, RateLimiter, get_rate_limiter
from app.supabase import SupabaseClient, get_supabase

router = APIRouter(prefix="/api")
logger = logging.getLogger("app.notes")

# subjects.id는 bigint다. 범위 밖 값은 DB에 묻기 전에 422로 끝낸다.
_MAX_BIGINT = 2**63 - 1
# notes.id도 bigint다. E05는 경로 값이 틀려도 422가 아니라 404다(1.4.2 E05 행에 422가 없다).
_NOTE_ID_SHAPE = re.compile(r"[1-9][0-9]{0,18}")
# 서명 URL 유효 시간(제안값, 2026-10-30 수락). 읽을 때마다 새로 발급한다.
SIGNED_URL_SECONDS = 5 * 60


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


def _expires_at(seconds: int) -> str:
    # 발급 요청 전에 잰 시각이라 실제 만료보다 늦지 않다.
    return datetime.fromtimestamp(int(session.now()) + seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/notes/{note_id}", summary="E05 note with image URLs and glossary spans")
def read_note(
    note_id: str,
    request: Request,
    user: SessionUser | None = Depends(get_session_user),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """본문은 원문 그대로 준다. note-image: 토큰을 서명 URL로 바꾸지 않고 images 맵으로 따로 준다(2.4).

    운영자가 아니면 비공개 노트는 없는 노트와 같은 404다. 운영자도 응답 모양은 같다(비공개 열은 E15).
    """
    if not _NOTE_ID_SHAPE.fullmatch(note_id) or int(note_id) > _MAX_BIGINT:
        raise ApiError("not_found", stage="validate")
    # 공개 읽기 제한은 E04와 같은 IP 키다. DB를 읽기 전에 세어 없는 id로 DB를 두드리는 요청도 막는다.
    limiter.check(PUBLIC_READ, f"ip:{ip_bucket(client_ip(request))}")
    operator = user is not None and user.is_operator
    note = supabase.get_note(int(note_id), include_unpublished=operator)
    if note is None:
        raise ApiError("not_found", stage="db")

    body = note["body_markdown"]
    terms = {row["id"]: row for row in supabase.list_glossary_terms()}
    spans = find_spans(body, [(term_id, row["key"]) for term_id, row in terms.items()])
    used = sorted({span.term_id for span in spans})

    images = {}
    rows = note["note_images"]
    if rows:
        # 노트 한 번 열기는 이미지 장수와 상관없이 1회로 센다(1.8). 이미지가 없으면 발급하지 않으니 세지 않는다.
        limiter.check(SIGNED_URL, f"user:{user.user_id}" if user else f"ip:{ip_bucket(client_ip(request))}")
        expires_at = _expires_at(SIGNED_URL_SECONDS)
        signed = supabase.sign_note_images(sorted({row["storage_path"] for row in rows}), SIGNED_URL_SECONDS)
        for row in rows:
            url = signed.get(row["storage_path"])
            if url is not None:
                images[row["notion_block_id"]] = {"url": url, "alt": row["alt"], "expires_at": expires_at}
        missing = len(rows) - len(images)
        if missing:
            # DB 행은 있는데 Storage에 파일이 없다. 그 이미지만 빼고 노트는 준다(2026-10-30 결정).
            # Storage는 버킷 이름이 틀려도 200에 항목별 오류만 준다(2026-10-30 로컬 확인). 파일 누락과 구분할 수
            # 없으므로 하나도 발급되지 않으면 ERROR로 남겨 NOTE_IMAGE_BUCKET 설정을 확인하게 한다.
            level = logging.ERROR if not images else logging.WARNING
            logger.log(level, "stage=storage note_id=%s unsigned_images=%d of %d", note["id"], missing, len(rows))

    return {
        "id": note["id"],
        "revision": note["revision"],
        "title": note["title"],
        "studied_on": note["studied_on"],
        "subjects": sorted(
            ({"id": link["subjects"]["id"], "name": link["subjects"]["name"]} for link in note["note_subjects"]),
            key=lambda subject: subject["id"],
        ),
        "sources": [
            {"url": source["url"], "label": source["label"]}
            for source in sorted(note["note_sources"], key=lambda source: source["id"])
        ],
        "body_markdown": body,
        "images": images,
        "glossary_terms": [
            {"term_id": term_id, "key": terms[term_id]["key"], "label": terms[term_id]["label"]} for term_id in used
        ],
        "glossary_spans": [{"term_id": span.term_id, "start": span.start, "end": span.end} for span in spans],
    }
