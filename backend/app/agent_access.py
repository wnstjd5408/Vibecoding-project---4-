"""CS Agent 공통 권한 검사와 가림 함수 (MEG-234, API spec v0.2 8절, 기술 검토 v0.4 5.1·6절).

E28~E32와 E29 재생·스트림은 모두 이 모듈로 권한을 확인하고 턴을 내보낸다. 그래야 경로마다 규칙이 갈라지지 않는다.

- 공통 권한 검사(load_conversation): (1) 세션 사용자의 대화인가, (2) 대화에 연결된 노트와 선택 문맥의 노트(제외한 것 포함)를
  지금 읽을 수 있는가. 노트 읽기는 E05와 같다: 공개 노트는 누구나, 비공개 노트는 운영자만. 위키 문맥은 T4(MEG-163) 전에는
  확인할 방법이 없어 읽을 수 없는 것으로 본다. 하나라도 아니면 404다(없음·남의 것·회수를 구분하지 않는다).
- 가림 함수(hidden_marks): 지금 볼 수 없는 출처를 인용한 첫 턴부터 그 대화의 뒤쪽 턴을 모두 가린다. 첫 턴만 다시 묻기를
  허용한다(디자인 결정 7·11·15). 그 첫 턴을 대상으로 한 다시 묻기 턴에서 가림이 끝나고, 그 턴부터는 각자의 출처로 다시
  판정한다(2026-11-18 결정). 가림은 저장하지 않고 읽을 때마다 계산한다.
- 노트 출처(source_kind note, D1 임시 근거)는 역할과 상관없이 지금 공개이고 존재해야 보인다(기술 검토 5.1). 운영자도 비공개
  노트는 근거로 쓰지 않으므로 같은 기준이다. 위키 출처는 T4 전에는 확인할 수 없어 보이지 않는 것으로 본다.
- 실행 만료(spec 3.1): 읽을 때 lease_expires_at이 지난 running 턴을 failed(interrupted)로 바꾼다(expire_running_turns).

로그에는 턴 id·단계·오류 코드만 남긴다. 질문·답변·노트 원문은 남기지 않는다.
"""

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app import session
from app.auth import SessionUser
from app.errors import ApiError
from app.supabase import SupabaseClient

logger = logging.getLogger("app.agent")

# 경로의 대화·턴 id는 UUID다. 다른 모양은 DB에 묻지 않고 404다(없는 대상과 같다, spec 3절·8절 열거).
_UUID_SHAPE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_NOTE_ID_SHAPE = re.compile(r"[1-9][0-9]{0,18}")
_MAX_BIGINT = 2**63 - 1
# 선택 칩에 보여 줄 앞부분 길이(코드포인트). 저장한 원문 전체는 응답에 넣지 않는다.
SELECTION_PREVIEW_CHARS = 100
# running 턴을 다시 조회할 권장 간격(초, spec E30 retry_after_seconds). 제안값이다.
TURN_POLL_SECONDS = 2
# 실행 만료 판정의 여유(초). 만료 시각은 DB 시계로 쓰이고 비교는 앱 시계로 하므로 두 시계 차이를 흡수한다. 제안값이다.
EXPIRY_GRACE_SECONDS = 5


def path_uuid(value: str) -> str:
    """경로 id를 소문자 UUID로 맞춘다. UUID가 아니면 404다."""
    if not _UUID_SHAPE.fullmatch(value):
        raise ApiError("not_found", stage="validate")
    return value.lower()


def now_iso() -> str:
    """앱 시계의 지금(UTC ISO, 마이크로초까지). 질의 값에 `+`가 들어가지 않게 Z로 쓴다."""
    return datetime.fromtimestamp(session.now(), UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class ConversationAccess:
    """공통 권한 검사를 통과한 대화. notes는 대화·선택 문맥 노트의 지금 상태(id → revision·title·is_published)다."""

    conversation: dict[str, Any]
    notes: dict[int, dict[str, Any]]


def conversation_note_ids(conversation: dict[str, Any]) -> set[int]:
    """대화에 연결된 노트 id: 대화의 노트와 선택 문맥의 노트(제외한 선택 포함, 앞 턴이 그 문맥을 썼다)."""
    ids = {selection["note_id"] for selection in conversation.get("ai_conversation_selections") or []}
    if conversation.get("note_id") is not None:
        ids.add(conversation["note_id"])
    return ids


def note_readable(state: dict[str, Any] | None, user: SessionUser) -> bool:
    """E05와 같은 노트 읽기 권한: 있고, 공개이거나 운영자다."""
    return state is not None and (state["is_published"] or user.is_operator)


def check_conversation(
    user: SessionUser, conversation: dict[str, Any] | None, notes: dict[int, dict[str, Any]]
) -> ConversationAccess:
    """공통 권한 검사의 판정 부분. DB를 읽지 않으므로 T3가 이미 읽은 행으로도 부를 수 있다. 아니면 404다."""
    if conversation is None or conversation.get("user_id") != user.user_id:
        raise ApiError("not_found", stage="db")
    if conversation.get("wiki_ref") is not None or conversation.get("origin") == "wiki":
        # 위키 권한 모델은 MEG-163(T4)에서 정한다. 그 전에는 확인할 수 없으므로 닫는다.
        raise ApiError("not_found", stage="db")
    if not all(note_readable(notes.get(note_id), user) for note_id in conversation_note_ids(conversation)):
        raise ApiError("not_found", stage="db")
    return ConversationAccess(conversation=conversation, notes=notes)


def load_conversation(supabase: SupabaseClient, user: SessionUser, conversation_id: str) -> ConversationAccess:
    """공통 권한 검사(spec 8절). 대화와 연결 노트를 읽고 check_conversation으로 판정한다. 아니면 404다."""
    conversation = supabase.get_agent_conversation(user.user_id, conversation_id)
    if conversation is None:
        raise ApiError("not_found", stage="db")
    notes = supabase.get_note_states(sorted(conversation_note_ids(conversation)))
    return check_conversation(user, conversation, notes)


def load_turn(supabase: SupabaseClient, user: SessionUser, turn_id: str) -> tuple[dict[str, Any], ConversationAccess]:
    """E30~E32: 그 사용자의 턴과, 그 턴이 속한 대화의 공통 권한 검사 결과. 아니면 404다."""
    turn = supabase.get_agent_turn(user.user_id, turn_id)
    if turn is None:
        raise ApiError("not_found", stage="db")
    return turn, load_conversation(supabase, user, turn["conversation_id"])


def lease_lapsed(turn: dict[str, Any]) -> bool:
    """running 턴의 만료 시각이 앱 시계로 EXPIRY_GRACE_SECONDS 넘게 지났는가. 시각을 읽지 못하면 지나지 않은 것으로 본다."""
    if turn.get("status") != "running":
        return False
    try:
        lease = datetime.fromisoformat(str(turn["lease_expires_at"]).replace("Z", "+00:00")).timestamp()
    except (KeyError, TypeError, ValueError):
        return False
    return lease + EXPIRY_GRACE_SECONDS <= session.now()


def expire_running_turns(supabase: SupabaseClient, user: SessionUser, conversation_id: str) -> int:
    """실행이 만료 시각까지 갱신하지 않은 running 턴을 failed(interrupted)로 바꾼다(spec 3.1). 조건부 갱신이다.

    만료 시각은 DB 시계(now())로 정해지고 비교는 앱 시계로 한다. 두 시계의 차이로 살아 있는 실행을 끊지 않도록
    EXPIRY_GRACE_SECONDS만큼 늦게 본다. 바꾼 턴 수를 돌려준다.
    """
    cutoff = datetime.fromtimestamp(session.now() - EXPIRY_GRACE_SECONDS, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    expired = supabase.expire_agent_turns(user.user_id, conversation_id, cutoff, now_iso())
    if expired:
        logger.info("stage=expire conversation turns_interrupted=%d", expired)
    return expired


def read_turns(
    supabase: SupabaseClient, user: SessionUser, conversation_id: str, max_seq: int | None = None
) -> list[dict[str, Any]]:
    """대화의 턴을 읽는다. 만료된 running 턴이 보일 때만 failed(interrupted)로 바꾸고 다시 읽는다(읽기마다 쓰지 않는다)."""
    turns = supabase.list_agent_turns(user.user_id, conversation_id, max_seq=max_seq)
    if any(lease_lapsed(turn) for turn in turns) and expire_running_turns(supabase, user, conversation_id):
        turns = supabase.list_agent_turns(user.user_id, conversation_id, max_seq=max_seq)
    return turns


# --- 가림 함수 ---


@dataclass(frozen=True)
class Hidden:
    reason: str
    retry_allowed: bool

    def payload(self) -> dict[str, Any]:
        return {"reason": self.reason, "retry_allowed": self.retry_allowed}


def note_source_id(source: dict[str, Any]) -> int | None:
    """노트 출처의 source_id(노트 id 문자열)를 정수로 바꾼다. 모양이 틀리면 None이다(볼 수 없는 출처로 본다)."""
    value = source.get("source_id")
    if not isinstance(value, str) or not _NOTE_ID_SHAPE.fullmatch(value) or int(value) > _MAX_BIGINT:
        return None
    return int(value)


def source_note_ids(turns: Iterable[dict[str, Any]]) -> set[int]:
    ids = set()
    for turn in turns:
        for source in turn.get("ai_turn_sources") or []:
            if source.get("source_kind") == "note":
                note_id = note_source_id(source)
                if note_id is not None:
                    ids.add(note_id)
    return ids


def source_checker(notes: dict[int, dict[str, Any]]) -> Callable[[dict[str, Any]], bool]:
    """출처 한 개가 지금 보이는지 판정하는 함수를 만든다. notes는 출처 노트의 지금 상태다(get_note_states).

    노트 출처는 공개이고 존재할 때만 보인다(역할 무관). 위키 출처와 모르는 종류는 T4 전에는 보이지 않는다.
    """

    def visible(source: dict[str, Any]) -> bool:
        if source.get("source_kind") != "note":
            return False
        note_id = note_source_id(source)
        state = notes.get(note_id) if note_id is not None else None
        return state is not None and bool(state["is_published"])

    return visible


def hidden_marks(
    turns: list[dict[str, Any]], source_visible: Callable[[dict[str, Any]], bool]
) -> dict[str, Hidden | None]:
    """턴 id → 가림 표시. turns는 같은 대화의 턴을 각 턴의 status·retry_of_turn_id·ai_turn_sources와 함께 받는다.

    seq 순서로 본다. 볼 수 없는 출처를 인용한 첫 턴(X)부터 뒤의 턴을 가린다(가림 연쇄). 다시 묻기(retry_allowed)는 X만
    true다. 2026-11-18 결정에 따라 다시 묻기 턴은 연쇄에서 빠진다.

    - X를 대상으로 한 첫 다시 묻기 턴(retry_of_turn_id = X)에서 연쇄가 끝난다. 그 턴과 뒤의 턴은 각자의 출처로 판정하고,
      볼 수 없는 출처를 인용한 턴이 또 나오면 그 턴이 새 X가 되어 같은 규칙을 다시 적용한다. 다시 묻기 턴 자신이 볼 수
      없는 출처를 인용하면 그 턴이 새 X다.
    - X와 그 다시 묻기 턴 사이의 턴은 가린다. X도 계속 가린다.
    - 다시 묻기는 한 번만이다. X를 대상으로 한 completed 다시 묻기 턴이 있으면 X의 retry_allowed는 false다.
    - 끝나지 않은 다시 묻기 턴(failed·cancelled·running)도 연쇄를 끝낸다(그 턴은 각자 판정해 보인다). 다만 다시 묻기를
      쓴 것으로 보지 않아 X의 retry_allowed는 true로 남는다. running 중의 겹친 다시 묻기는 E29가 turn_in_progress로 막는다.
    - X가 아닌 턴(연쇄 중간의 턴, 지금 보이는 턴)을 대상으로 한 다시 묻기 턴은 일반 턴과 같다. 연쇄를 끝내지 않는다.
    - retry_of_turn_id가 없는 행은 다시 묻기 턴이 아닌 것으로 본다.
    """
    ordered = sorted(turns, key=lambda row: row["seq"])
    retried = {
        turn["retry_of_turn_id"]
        for turn in ordered
        if turn.get("retry_of_turn_id") is not None and turn.get("status") == "completed"
    }
    marks: dict[str, Hidden | None] = {}
    first_hidden = None
    for turn in ordered:
        if first_hidden is not None and turn.get("retry_of_turn_id") == first_hidden:
            first_hidden = None
        if first_hidden is None and not all(source_visible(s) for s in turn.get("ai_turn_sources") or []):
            first_hidden = turn["id"]
            marks[turn["id"]] = Hidden("source_revoked", retry_allowed=turn["id"] not in retried)
        elif first_hidden is None:
            marks[turn["id"]] = None
        else:
            marks[turn["id"]] = Hidden("source_revoked", retry_allowed=False)
    return marks


def visible_turns(
    supabase: SupabaseClient, access: ConversationAccess, turns: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """턴 행 목록에 가림을 적용해 응답 모양(turn 객체)으로 바꾼다. 턴을 돌려주는 모든 경로가 이 함수를 쓴다.

    출처 노트 상태는 대화 권한 검사에서 이미 읽은 노트를 빼고 한 번만 더 읽는다.
    """
    needed = source_note_ids(turns)
    states = {note_id: access.notes[note_id] for note_id in needed if note_id in access.notes}
    missing = sorted(needed - states.keys())
    if missing:
        states |= supabase.get_note_states(missing)
    marks = hidden_marks(turns, source_checker(states))
    return [turn_payload(turn, marks.get(turn["id"])) for turn in sorted(turns, key=lambda row: row["seq"])]


def turn_payload(turn: dict[str, Any], hidden: Hidden | None) -> dict[str, Any]:
    """턴 행을 spec 3절 turn 객체로 바꾼다. 원장·실행 기록 열은 넣지 않는다(spec 2절).

    result는 completed이고 가리지 않았을 때만 넣는다. 저장한 result에 서버가 확인한 출처(ai_turn_sources)를 sources로 붙인다.
    가린 턴은 result(추천 질문 포함)를 빼고 hidden을 넣는다. 직접 입력·빠른 질문 문구는 사용자 입력이라 남기고, 추천 질문 문구는 뺀다.
    """
    question: dict[str, Any] = {"kind": turn["question_kind"]}
    if hidden is None or turn["question_kind"] != "suggested":
        # 추천 질문(suggested)의 문구는 앞 답변(모델 출력)에서 왔다. 가린 턴에서는 회수된 출처에서 나왔을 수 있어 뺀다.
        question["text"] = turn["question_text"]
    if turn.get("preset") is not None:
        question["preset"] = turn["preset"]
    if turn.get("from_turn_id") is not None:
        question["from_turn_id"] = turn["from_turn_id"]
    payload: dict[str, Any] = {
        "turn_id": turn["id"],
        "seq": turn["seq"],
        "question": question,
        "status": turn["status"],
        "created_at": turn["created_at"],
    }
    if turn["status"] == "failed" and turn.get("failure") is not None:
        payload["failure"] = turn["failure"]
    if turn["status"] == "running" and turn.get("step") is not None:
        payload["step"] = turn["step"]
    if turn.get("finished_at") is not None:
        payload["finished_at"] = turn["finished_at"]
    if hidden is not None:
        payload["hidden"] = hidden.payload()
    elif turn["status"] == "completed" and isinstance(turn.get("result"), dict):
        # 출처는 서버가 확인해 저장한 ai_turn_sources만 내보낸다. result 안에 남은 sources 키는 쓰지 않는다(spec 5.2).
        result = {key: value for key, value in turn["result"].items() if key != "sources"}
        sources = turn.get("ai_turn_sources") or []
        if sources:
            result["sources"] = [source_payload(source) for source in sorted(sources, key=lambda s: s["ref"])]
        payload["result"] = result
    elif turn["status"] == "completed":
        # 저장한 결과의 모양이 틀렸다. 대화 전체를 500으로 만들지 않고 그 턴의 결과만 뺀다.
        logger.error("stage=read turn_id=%s invalid_result", turn["id"])
    return payload


def source_payload(source: dict[str, Any]) -> dict[str, Any]:
    """spec 5.2 출처 객체. 내부 id·인용 원문은 넣지 않는다(E32가 다시 확인하고 연다).

    source_kind(note·wiki)는 화면이 출처 문구를 고르는 값이다(spec 0절 T4 전 임시 예외, 2026-11-18 결정, MEG-237).
    """
    payload = {
        "ref": source["ref"],
        "source_kind": source["source_kind"],
        "title": source["title"],
        "cited_revision": source["cited_revision"],
    }
    for key in ("section", "excerpt"):
        if source.get(key) is not None:
            payload[key] = source[key]
    return payload


def selection_payload(selection: dict[str, Any], notes: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """spec 3절 selection 객체. 노트 개정이 저장 때와 다르면 revision_changed가 true다."""
    state = notes.get(selection["note_id"])
    return {
        "selection_id": selection["id"],
        "note_id": selection["note_id"],
        "note_revision": selection["note_revision"],
        "start": selection["start"],
        "end": selection["end"],
        "text_preview": selection["text_snapshot"][:SELECTION_PREVIEW_CHARS],
        "revision_changed": state is None or state["revision"] != selection["note_revision"],
    }


def conversation_payload(access: ConversationAccess) -> dict[str, Any]:
    """spec 3절 conversation 객체. 제외한 선택 문맥은 지금 문맥이 아니므로 context_selections에 넣지 않는다."""
    conversation = access.conversation
    payload: dict[str, Any] = {
        "conversation_id": conversation["id"],
        "topic_label": conversation["topic_label"],
        "origin": conversation["origin"],
        "context_selections": [
            selection_payload(selection, access.notes)
            for selection in conversation.get("ai_conversation_selections") or []
            if selection.get("excluded_at") is None
        ],
        "created_at": conversation["created_at"],
    }
    if conversation.get("note_id") is not None:
        state = access.notes[conversation["note_id"]]
        payload["note"] = {
            "note_id": conversation["note_id"],
            "note_revision": conversation["note_revision"],
            "title": state["title"],
        }
    return payload
