"""CS Agent 위키 검색 (MEG-251 T4b, 내부 위키 우선 RAG 설계 v0.3 3.2·3.4·3.5절, MEG-163 W1·W4·W7 결정).

위키는 사전 항목이다(W1). retrieve 인터페이스(agent_retrieval)의 구현이며, 앱 기본값은 아직 노트 검색이다. 바꿔 끼우는
것은 위키 플래그(T4c MEG-252)이고, 켜는 것은 측정 뒤 사람이 정한다(T4d MEG-253).

- 읽는 범위: 사전 항목만 읽는다. 항목이 있다는 판정은 `glossary_entries` 행이 있고 `terms.source = 'glossary'`인 것이다.
  사전 삭제(E21)는 `terms` 행을 남기고 source를 ai로 바꾸므로 terms 행만 남은 것은 없는 항목이다(설계 3.2, S1). DB 조회가
  먼저 거르고, 여기서 한 번 더 거른다. AI 설명(ai_explanations)과 노트는 읽지 않는다(S2). 사전은 모두 공개다(W5).
- 식별자: Paragraph.source_id와 wiki_ref는 `glossary:{term_id}`다(W7). revision은 `terms.glossary_revision`(T4a MEG-249)을
  문자열로 쓴다. 값이 0 이상 정수가 아니면 그 항목을 뺀다(개정을 모르는 문단을 인용하지 않는다).
- 문단 분할: 노트와 같은 note_chunks를 쓴다(설계 3.4). E32의 바뀜 판정과 검색 평가가 같은 규칙을 써야 하기 때문이다.
- 점수 [제안값]: T3b의 낱말 추출(keywords)과 키워드 점수를 그대로 쓴다. 여기에 개념 가산점을 더한다.
  - 후보는 노트 검색과 같다: 질문 낱말(질문에 낱말이 없으면 문맥 낱말)이 하나라도 들어 있는 문단이다. 가산점은
    순서만 바꾼다. 그래야 관계없는 질문이 '근거 없음'(P6)으로 끝날 수 있다.
  - wiki_ref 항목(위키에서 연 대화): WIKI_REF_BONUS. 예외로, 질문 자체에 낱말이 없을 때("더 쉽게 설명해 주세요")는
    낱말이 맞지 않아도 그 항목 문단이 후보다. 질문에 낱말이 있는데 맞지 않으면 그 항목도 후보가 아니다.
  - 질문·선택 문맥에 나오는 사전 용어의 항목(E05와 같은 찾기 규칙, find_spans): MENTION_BONUS. 한글 용어는 조사 때문에
    부분 문자열로 찾으므로("리포트" 속 "포트") 후보를 늘리는 데 쓰지 않는다.
- 중복과 상한 [제안값]: 같은 문단 원문(공백 정리 후)은 점수가 높은 하나만 남긴다. 한 항목에서 최대 MAX_PER_ENTRY문단,
  전체 MAX_RESULTS문단(근거 문단 상한과 같다).
- 선택 문맥 제외는 하지 않는다. 선택은 노트이고 근거는 위키라서 자기 인용 문제가 없다(설계 3.5).

로그에는 단계와 개수만 남긴다. 질문·사전 원문은 남기지 않는다(spec 8절, 설계 S10).
"""

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.agent_note_search import (
    CONTEXT_WEIGHT,
    MAX_CHUNK_CHARS,
    MAX_RESULTS,
    _score as keyword_score,
    keywords,
    note_chunks,
)
from app.agent_retrieval import Paragraph, RetrievalContext
from app.auth import SessionUser
from app.glossary_spans import find_spans

logger = logging.getLogger("app.agent")

SOURCE_KIND = "wiki"
RETRIEVAL_VERSION = "wiki-keyword-v1"
# 문단 분할 규칙의 이름. agent_note_search.note_chunks(제목 → 단락 → 줄 → 글자 수, 문단 상한 MAX_CHUNK_CHARS)를 가리킨다.
# 검색 평가 결과에 함께 기록한다. 분할 규칙이나 상한을 바꾸면 이 값을 올린다.
CHUNK_RULE_VERSION = "note-chunks-v1"
SOURCE_PREFIX = "glossary:"
# 한 항목에서 돌려주는 최대 문단 수. 제안값이며 측정 뒤 확정한다(설계 3.5).
MAX_PER_ENTRY = 3
# 개념 가산점. 질문 낱말 하나가 본문에 한 번 나오면 1점, 제목에 나오면 2점을 더 받는다(노트 검색 점수). 제안값이다.
WIKI_REF_BONUS = 5.0
MENTION_BONUS = 3.0

_WIKI_REF = re.compile(r"glossary:([1-9][0-9]{0,18})")
_MAX_BIGINT = 2**63 - 1
_SPACES = re.compile(r"\s+")


def wiki_source_id(term_id: int) -> str:
    """사전 항목의 source_id·wiki_ref 문자열(`glossary:{term_id}`, W7)."""
    return f"{SOURCE_PREFIX}{int(term_id)}"


def parse_wiki_ref(value: str | None) -> int | None:
    """`glossary:{term_id}`이면 term_id, 아니면 None. 앞자리 0·부호·공백·bigint 밖의 값은 받지 않는다."""
    if not isinstance(value, str):
        return None
    match = _WIKI_REF.fullmatch(value)
    if match is None:
        return None
    term_id = int(match.group(1))
    return term_id if term_id <= _MAX_BIGINT else None


@dataclass(frozen=True)
class WikiEntry:
    """검색에 쓰는 사전 항목 하나. body는 사전 본문(glossary_entries.body_markdown)이다."""

    term_id: int
    key: str
    label: str
    revision: int
    body: str


def entry_body(row: dict[str, Any]) -> str | None:
    """terms 행에 내장한 glossary_entries의 본문. 일대일 내장은 객체 하나다. 혹시 배열로 오면 한 행일 때만 받는다."""
    entry = row.get("glossary_entries")
    if isinstance(entry, list):
        entry = entry[0] if len(entry) == 1 else None
    body = entry.get("body_markdown") if isinstance(entry, dict) else None
    return body if isinstance(body, str) else None


def wiki_entries(rows: Iterable[dict[str, Any]]) -> tuple[list[WikiEntry], int]:
    """DB 행(terms + 내장 glossary_entries)에서 지금 있는 사전 항목만 고른다. (항목 목록, 뺀 행 수)를 준다.

    빼는 것: source가 glossary가 아닌 행(삭제 뒤 terms만 남은 행, AI로만 설명된 용어), glossary_entries 행이 없는 행,
    본문·제목·개정이 형식에 맞지 않는 행. 같은 term_id가 두 번 오면 처음 것만 쓴다.
    """
    entries: list[WikiEntry] = []
    seen: set[int] = set()
    skipped = 0
    for row in rows:
        term_id = row.get("id")
        body = entry_body(row)
        revision = row.get("glossary_revision")
        label = row.get("label")
        key = row.get("key")
        if (
            row.get("source") != "glossary"
            or not isinstance(term_id, int) or isinstance(term_id, bool) or not 0 < term_id <= _MAX_BIGINT
            or term_id in seen
            or not isinstance(body, str)
            or not isinstance(revision, int) or isinstance(revision, bool) or revision < 0
            or not isinstance(label, str) or not label.strip()
            or not isinstance(key, str) or not key.strip()
        ):
            skipped += 1
            continue
        seen.add(term_id)
        entries.append(WikiEntry(term_id, key, label, revision, body))
    return entries, skipped


def mentioned_term_ids(texts: Iterable[str], entries: Sequence[WikiEntry]) -> set[int]:
    """글들에 나오는 사전 용어의 term_id. 노트 강조(E05)와 같은 찾기 규칙(find_spans)을 쓴다. 별칭은 없다(W4)."""
    terms = [(entry.term_id, entry.key) for entry in entries]
    found: set[int] = set()
    for text in texts:
        if text:
            found.update(span.term_id for span in find_spans(text, terms))
    return found


def resolve_term(text: str, entries: Sequence[WikiEntry]) -> int | None:
    """표기 하나(노트에서 누른 글자)가 가리키는 대표 페이지(사전 항목)의 term_id. 표기 전체가 용어 하나와 맞을 때만이다.

    검색 평가 E2(표기 → 개념 → 대표 페이지 연결)에 쓴다. 별칭이 생기기 전(W4)에는 표기 = 용어 key다.
    """
    spans = find_spans(text, [(entry.term_id, entry.key) for entry in entries])
    stripped = text.strip()
    if len(spans) != 1 or not stripped:
        return None
    span = spans[0]
    lead = len(text) - len(text.lstrip())
    return span.term_id if span.start == lead and span.end == lead + len(stripped) else None


def _normal(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


@dataclass(frozen=True)
class _Candidate:
    total: float
    term_id: int
    index: int
    paragraph: Paragraph


def search_wiki(rows: Iterable[dict[str, Any]], question: str, context: RetrievalContext) -> list[Paragraph]:
    """사전 항목 행에서 질문에 맞는 문단을 점수 순으로 최대 MAX_RESULTS개 고른다. 같은 입력이면 같은 결과다."""
    return search_entries(wiki_entries(rows)[0], question, context)


def search_entries(entries: Sequence[WikiEntry], question: str, context: RetrievalContext) -> list[Paragraph]:
    asked = keywords(question)
    question_has_words = bool(asked)
    context_text = "\n".join([*context.selection_texts, context.topic_label, *context.recent_questions[-1:]])
    around = [word for word in keywords(context_text) if word not in asked]
    if not asked:
        # 빠른 질문 칩처럼 질문에 낱말이 없으면 문맥 낱말로 찾는다(노트 검색과 같다).
        asked, around = around, []

    referenced = parse_wiki_ref(context.wiki_ref)
    mentioned = mentioned_term_ids([question, *context.selection_texts], entries)

    candidates: list[_Candidate] = []
    for entry in entries:
        bonus = 0.0
        if entry.term_id == referenced:
            bonus += WIKI_REF_BONUS
        if entry.term_id in mentioned:
            bonus += MENTION_BONUS
        # 질문에 낱말이 없을 때만 wiki_ref 항목은 낱말이 맞지 않아도 후보다(모듈 설명).
        open_entry = entry.term_id == referenced and not question_has_words
        if not asked and not open_entry:
            continue
        for index, chunk in enumerate(note_chunks(entry.body)):
            body = chunk.text.lower()
            head = f"{entry.label}\n{chunk.section or ''}".lower()
            main = keyword_score(asked, body, head)
            if main <= 0 and not open_entry:
                continue
            total = main + CONTEXT_WEIGHT * keyword_score(around, body, head) + bonus
            paragraph = Paragraph(
                source_kind=SOURCE_KIND,
                source_id=wiki_source_id(entry.term_id),
                revision=str(entry.revision),
                title=entry.label,
                text=chunk.text,
                section=chunk.section,
            )
            candidates.append(_Candidate(total, entry.term_id, index, paragraph))

    # 점수가 같으면 term_id, 문단 순서로 정한다(같은 입력이면 같은 결과).
    candidates.sort(key=lambda c: (-c.total, c.term_id, c.index))
    chosen: list[Paragraph] = []
    texts: set[str] = set()
    per_entry: dict[int, int] = {}
    for candidate in candidates:
        if len(chosen) >= MAX_RESULTS:
            break
        text = _normal(candidate.paragraph.text)
        if text in texts or per_entry.get(candidate.term_id, 0) >= MAX_PER_ENTRY:
            continue
        texts.add(text)
        per_entry[candidate.term_id] = per_entry.get(candidate.term_id, 0) + 1
        chosen.append(candidate.paragraph)
    return chosen


class WikiSource(Protocol):
    def list_wiki_entries(self) -> list[dict[str, Any]]: ...


class WikiRetriever:
    """위키 검색(wiki-keyword-v1). 지금 있는 사전 항목만 읽는다. 앱 기본값이 아니다(전환은 T4c 위키 플래그)."""

    version = RETRIEVAL_VERSION
    source_kind = SOURCE_KIND

    def __init__(self, supabase: WikiSource):
        self._supabase = supabase

    def retrieve(self, user: SessionUser, question: str, context: RetrievalContext) -> Sequence[Paragraph]:
        rows = self._supabase.list_wiki_entries()
        entries, skipped = wiki_entries(rows)
        paragraphs = search_entries(entries, question, context)
        logger.info(
            "stage=retrieve source_kind=%s entries=%d skipped=%d paragraphs=%d",
            SOURCE_KIND, len(entries), skipped, len(paragraphs),
        )
        return paragraphs

