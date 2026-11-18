"""CS Agent 근거 검색 인터페이스 (MEG-236, 기술 검토 v0.4 4절, API spec v0.2 E29 6단계).

검색은 `retrieve(user, question, context) -> [Paragraph]` 하나로 둔다. 실행 파이프라인(agent_turns)은 이 인터페이스만 안다.

- 앱 기본값은 노트 임시 검색(D1, T3b MEG-237, agent_note_search.NoteRetriever)이다. 위키 검색은 T4(MEG-238)가 이
  인터페이스로 구현을 바꿔 끼운다. 그때 retrieve의 모양과 E32 응답 모양은 바꾸지 않는다(기술 검토 4절).
- NoEvidenceRetriever는 문단을 돌려주지 않는 구현이다(모든 질문이 모델 호출 없이 no_evidence로 끝난다). 시험용 고정 문단
  (FixedRetriever)을 운영에 쓰면 근거 없는 답이 근거 있는 것처럼 보이므로 기본값으로 두지 않는다.
- 검색은 사용자 권한 안에서만 한다(spec 8절 "위키 근거"). 권한 확인은 구현의 책임이다. 파이프라인은 인용 직전에
  노트 출처를 한 번 더 확인한다(spec E29 9단계).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from fastapi import Depends

from app.auth import SessionUser
from app.supabase import SupabaseClient, get_supabase

SOURCE_KINDS = ("note", "wiki")


@dataclass(frozen=True)
class Paragraph:
    """근거 문단 하나. source_id·revision은 문자열이다(노트 id·개정을 문자열로, 위키 형태는 Q1에서 정한다).

    text는 모델에 보내고 인용 당시 원문(paragraph_snapshot)으로 저장한다. section은 문단이 속한 제목이다.
    """

    source_kind: str
    source_id: str
    revision: str
    title: str
    text: str
    section: str | None = None


@dataclass(frozen=True)
class RetrievalContext:
    """검색에 넘기는 대화 문맥. 노트 문맥(selections)은 검증된 근거가 아니다(PRD 4·11절).

    selection_note_ids·selection_texts는 지금 쓰는 선택 문맥(제외하지 않은 것)이다. 노트 근거 기간에는 선택 문맥에 쓰인
    문단을 검색에서 빼는 데 쓸 수 있다(기술 검토 4절 [제안]).
    """

    conversation_id: str
    origin: str
    note_id: int | None
    topic_label: str
    selection_note_ids: tuple[int, ...] = ()
    selection_texts: tuple[str, ...] = ()
    recent_questions: tuple[str, ...] = field(default=())


class Retriever(Protocol):
    # 턴의 실행 기록(ai_turns.retrieval_version)에 남기는 검색 버전. 응답에는 넣지 않는다(spec 9절).
    version: str
    # 이 구현이 찾는 근거 종류(note·wiki). 문단이 0개여도 retrieve 완료 step 이벤트의 source_kind로 쓴다(spec 6절).
    # 정할 수 없으면 None이고, 그때는 이벤트에 싣지 않는다.
    source_kind: str | None

    def retrieve(self, user: SessionUser, question: str, context: RetrievalContext) -> Sequence[Paragraph]: ...


class NoEvidenceRetriever:
    """T3b 전 기본값. 근거를 찾지 않는다. E29는 모델을 부르지 않고 no_evidence로 끝난다(spec E29 6단계)."""

    version = "none-v0"
    source_kind = None

    def retrieve(self, user: SessionUser, question: str, context: RetrievalContext) -> Sequence[Paragraph]:
        return ()


class FixedRetriever:
    """시험용 가짜 검색. 질문과 관계없이 정해 둔 문단을 돌려준다. 호출 기록을 남긴다."""

    version = "fixed-test"

    def __init__(
        self,
        paragraphs: Sequence[Paragraph],
        on_retrieve: Callable[[], None] | None = None,
        source_kind: str | None = "note",
    ):
        self.paragraphs = list(paragraphs)
        self.source_kind = source_kind
        self.calls: list[tuple[str, str, RetrievalContext]] = []
        self._on_retrieve = on_retrieve

    def retrieve(self, user: SessionUser, question: str, context: RetrievalContext) -> Sequence[Paragraph]:
        self.calls.append((user.user_id, question, context))
        if self._on_retrieve is not None:
            self._on_retrieve()
        return list(self.paragraphs)


def get_retriever(supabase: SupabaseClient = Depends(get_supabase)) -> Retriever:
    """FastAPI 의존성. T4 전에는 공개 노트 임시 검색이다(D1). 시험은 dependency_overrides로 바꾼다."""
    # agent_note_search가 이 모듈의 Paragraph를 쓰므로 순환 import를 피해 여기서 가져온다.
    from app.agent_note_search import NoteRetriever

    return NoteRetriever(supabase)
