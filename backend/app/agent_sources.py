"""CS Agent 출처 보기 E32 (MEG-237, API spec v0.2 4절 E32·0절 T4 전 임시 예외·8절, 기술 검토 v0.4 5.1절).

GET /api/ai/turns/{turn_id}/sources/{ref} — 그 턴이 인용한 문단을 인용 당시 원문으로 돌려준다. 모델을 부르지 않는다.

권한(열 때마다 다시 확인한다. 아니면 모두 404다. 없음·남의 것·회수를 구분하지 않는다):
1. 공통 권한 검사(load_turn): 세션 사용자의 턴이고, 대화에 연결된 노트·선택 문맥의 노트를 지금 읽을 수 있다.
2. 그 턴이 가려지지 않았다(visible_turns, E28·E30과 같은 가림 함수). 완료된 턴이고 그 번호의 출처가 있다.
3. 노트 출처(D1)는 역할과 관계없이 그 노트가 지금 공개이고 존재한다. 위키 출처(MEG-252)는 그 사전 항목이 지금 있다
   (설계 3.2: glossary_entries 행 + terms.source = 'glossary'). 사전은 모두 공개다(W5).

응답: {ref, source_kind, title, section, cited_revision, paragraph_text, highlight, changed_since_cited}. 노트와 위키가 같은 모양이다.
- paragraph_text는 인용 당시 문단 원문(paragraph_snapshot)이다. 노트와 사전은 이전 개정을 보관하지 않는다.
- changed_since_cited는 개정 번호가 아니라, 지금 본문을 같은 규칙(note_chunks)으로 나눈 문단 가운데 인용 당시 원문과 같은
  문단이 없는지로 정한다. 노트 개정은 제목·본문 어디가 바뀌어도 오르고, 사전 개정은 저장할 때마다 오르기 때문이다(기술 검토
  5.1, 설계 3.2).
- highlight는 null이다. 문단 전체가 인용 단위라 문단 안의 강조 범위가 없다(위키도 같다, 설계 3.2).

검사 순서(spec 2절): Origin(미들웨어) → 세션(의존성) → 경로 형식(404) → 속도 제한(E28·E30과 같은 사용자 키) → 대상·권한(404).
로그에는 턴 id·단계만 남긴다. 노트·문단 원문은 남기지 않는다(spec 8절).
"""

import logging
import re

from fastapi import APIRouter, Depends

from app.agent_access import load_turn, note_source_id, path_uuid, read_turns, visible_turns, wiki_source_term
from app.agent_note_search import note_chunks
from app.agent_wiki_search import entry_body
from app.auth import SessionUser, require_login
from app.errors import ApiError
from app.rate_limit import AI_AGENT_READ, RateLimiter, get_rate_limiter
from app.supabase import SupabaseClient, get_supabase

router = APIRouter(prefix="/api")
logger = logging.getLogger("app.agent")

# 인용 번호는 1부터다(근거 문단 최대 5개). 다른 모양은 DB에 묻지 않고 404다.
_REF_SHAPE = re.compile(r"[1-9][0-9]{0,2}")


def _not_found() -> ApiError:
    return ApiError("not_found", stage="db")


def _current_body(supabase: SupabaseClient, source: dict) -> str | None:
    """출처의 지금 본문. 지금 열 수 없는 출처면 None이다(가림 함수와 같은 기준을 본문을 읽으며 다시 본다).

    노트: 역할과 관계없이 공개 노트만 읽는다. 위키: 지금 있는 사전 항목만 읽는다(get_wiki_entry).
    """
    if source.get("source_kind") == "note":
        note_id = note_source_id(source)
        note = supabase.get_note_for_agent(note_id, include_unpublished=False) if note_id is not None else None
        return (note.get("body_markdown") or "") if note is not None else None
    term_id = wiki_source_term(source)
    if term_id is None:
        return None
    entry = supabase.get_wiki_entry(term_id)
    return entry_body(entry) if entry is not None else None


@router.get("/ai/turns/{turn_id}/sources/{ref}", summary="E32 read a source paragraph cited by a CS Agent turn")
def read_source(
    turn_id: str,
    ref: str,
    user: SessionUser = Depends(require_login),
    supabase: SupabaseClient = Depends(get_supabase),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    target = path_uuid(turn_id)
    if not _REF_SHAPE.fullmatch(ref):
        raise ApiError("not_found", stage="validate")
    number = int(ref)
    limiter.check(AI_AGENT_READ, f"user:{user.user_id}")

    turn, access = load_turn(supabase, user, target)
    # 가림은 앞 턴의 출처와 뒤의 다시 묻기 턴으로 정해지므로 대화의 턴을 모두 읽는다(E30과 같은 판정).
    turns = read_turns(supabase, user, access.conversation["id"])
    payload = next((p for p in visible_turns(supabase, access, turns) if p["turn_id"] == turn["id"]), None)
    if payload is None or payload.get("hidden") is not None or payload["status"] != "completed":
        raise _not_found()
    if not any(source["ref"] == number for source in (payload.get("result") or {}).get("sources") or []):
        raise _not_found()

    source = supabase.get_agent_turn_source(turn["id"], number)
    body = _current_body(supabase, source) if source is not None else None
    if body is None:
        # 가림 판정 뒤에 노트가 비공개가 되거나 지워졌거나, 사전 항목이 지워졌다. 모르는 종류도 열지 않는다.
        raise _not_found()

    snapshot = source["paragraph_snapshot"]
    current = {chunk.text for chunk in note_chunks(body)}
    changed = snapshot not in current
    logger.info("stage=source turn_id=%s changed=%s", turn["id"], changed)
    return {
        "ref": source["ref"],
        "source_kind": source["source_kind"],
        "title": source["title"],
        "section": source.get("section"),
        "cited_revision": source["cited_revision"],
        "paragraph_text": snapshot,
        "highlight": None,
        "changed_since_cited": changed,
    }
