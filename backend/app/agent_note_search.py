"""CS Agent 노트 임시 검색 (MEG-237, D1 T4 전 임시 예외, 기술 검토 v0.4 4절, API spec v0.2 0절·8절).

위키 검색(T4, MEG-238)이 붙기 전에는 공개 CS 노트 문단을 근거로 쓴다. retrieve 인터페이스(agent_retrieval)의 구현이다.

- 검색 범위(사용자 결정 2026-11-18): 역할과 관계없이 공개 노트(is_published = true)만 DB에서 읽는다. 운영자도 비공개
  노트는 근거로 쓰지 않는다. 운영자가 비공개 노트에서 질문해도(Q13) 그 선택 문장은 질문 문맥일 뿐이다.
- 문단 분할 [제안, 기술 검토 4절]: 제목(# ~ ######) 단위로 나눈다. 절이 1,500자를 넘으면 단락(빈 줄) 경계에서 다시 나눈다.
  자르지 않는다. 단락 하나가 1,500자를 넘을 때만 줄 경계로, 줄 하나가 넘을 때만 1,500자씩 나눈다(드문 경우의 대비).
  코드 블록 안의 # 줄과 빈 줄은 경계로 보지 않는다.
- 전처리 [제안]: 모델에 보내기 전에 note-image: 이미지 문법은 대체 글([그림: 대체 글])로 바꾼다. 코드·Mermaid 블록은 남긴다.
  이렇게 만든 문단 원문이 모델이 보는 글이고 인용 당시 원문(paragraph_snapshot)으로 저장된다.
- 선택 문맥 제외(사용자 결정 2026-11-18): 대화의 선택 문장이 든 문단은 검색 결과에서 뺀다. 같은 노트의 다른 문단은
  근거로 쓴다. 판정은 "문단 안에 선택 원문이 들어 있는가"다 [제안]. 여러 문단에 걸친 선택은 줄마다 본다.
- 검색 [제안]: 백엔드가 공개 노트를 모두 읽어 Python에서 키워드로 점수를 매긴다. 새 SQL 함수는 없다. 노트가 늘면 T4에서
  다시 정한다. 질문의 낱말이 하나라도 들어 있는 문단만 후보다. 선택 문맥·주제·직전 질문의 낱말은 순서를 정하는 데만
  쓴다. 질문에 낱말이 없으면(빠른 질문 칩 등) 문맥 낱말로 찾는다.

로그에는 단계와 개수만 남긴다. 질문·노트 원문은 남기지 않는다(spec 8절).
"""

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.agent_output import MAX_PARAGRAPH_CHARS, MAX_PARAGRAPHS
from app.agent_retrieval import Paragraph, RetrievalContext
from app.auth import SessionUser
from app.glossary_spans import code_mask
from app.supabase import SupabaseClient

logger = logging.getLogger("app.agent")

SOURCE_KIND = "note"
RETRIEVAL_VERSION = "note-keyword-v1"
# 문단 상한(코드포인트, Q4 임시값). 저장 전 거르기(usable_paragraphs)와 같은 값이어야 문단이 잘리지 않고, E32가 지금
# 문단과 인용 당시 원문을 비교할 수 있다. 그래서 agent_output의 값을 그대로 쓴다.
MAX_CHUNK_CHARS = MAX_PARAGRAPH_CHARS
# 한 번에 돌려주는 문단 수(프롬프트에 넣는 근거 문단 상한과 같다).
MAX_RESULTS = MAX_PARAGRAPHS
# 여러 줄 선택을 줄마다 볼 때, 이보다 짧은 줄은 보지 않는다(목록 표시 같은 짧은 줄이 다른 문단에 우연히 들어 있을 수 있다).
MIN_SELECTION_LINE_CHARS = 10
# 문맥(선택 문장·주제·직전 질문) 낱말의 가중치. 질문 낱말은 1이다. 제안값이다.
CONTEXT_WEIGHT = 0.3
# 제목·절 이름에 낱말이 있을 때 더하는 점수, 본문에서 셀 최대 횟수. 제안값이다.
TITLE_BONUS = 2
MAX_COUNT = 3

_HEADING = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+$")
# ![대체 글](note-image:키 "제목"). 대체 글 안의 \] 이스케이프와 따옴표 제목도 받는다.
_NOTE_IMAGE = re.compile(r'!\[((?:[^\]\\]|\\.)*)\]\(\s*note-image:[^)\s]*(?:\s+"[^"]*")?\s*\)')
_BARE_NOTE_IMAGE = re.compile(r"note-image:[^\s)]*")
_SPACES = re.compile(r"\s+")
_WORDS = re.compile(r"[a-z0-9][a-z0-9+#]*|[가-힣]+")
_LATIN = re.compile(r"[a-z0-9+#]+")

# 질문에 흔히 붙는 말. 낱말로 세지 않는다. 제안값이다.
_STOPWORDS = frozenset(
    {
        "방금", "설명", "자세히", "쉽게", "예시", "예를", "들어", "주세요", "알려", "알려줘", "뭐야", "뭐예요", "무엇",
        "무엇인가요", "무엇인지", "어떻게", "어떤", "언제", "어디", "누가", "이것", "그것", "저것", "이거", "그거", "저거",
        "대해", "대해서", "관련", "관해", "정리", "질문", "답변", "내용", "있나요", "있어", "있어요", "없어", "하나요",
        "되나요", "인가요", "경우", "그럼", "그러면", "그리고", "또는", "그래서", "다시", "한번", "조금", "이유", "뜻",
        "의미", "뭔가요", "뭘까", "뭐지", "the", "is", "are", "what", "how", "why", "of", "to", "in", "and", "or",
        "for",
    }
)
# 낱말 끝의 조사·어미. 긴 것부터 뗀다. 떼고 남은 말이 2글자 이상일 때만 뗀다. 제안값이다.
_SUFFIXES = tuple(
    sorted(
        {
            "이란", "란", "이라는", "라는", "이라고", "라고", "에서는", "에서", "에게", "으로는", "으로", "로는", "로",
            "은", "는", "이", "가", "을", "를", "의", "와", "과", "도", "만", "까지", "부터", "보다", "처럼", "이야",
            "야", "이에요", "예요", "인가요", "인가", "일까요", "일까", "이고", "하고", "하는", "하면", "해서", "해줘",
            "해주세요", "해요", "해", "하나요", "한다", "이다", "에는", "에", "께서", "이나", "나", "랑", "이랑",
        },
        key=len,
        reverse=True,
    )
)


# --- 문단 분할과 전처리 ---


def replace_images(text: str) -> str:
    """코드 밖의 note-image: 이미지 문법을 대체 글로 바꾼다. 남은 note-image: 토큰은 지운다. 코드 안은 그대로 둔다."""
    mask = code_mask(text)
    out: list[str] = []
    last = 0
    for match in _NOTE_IMAGE.finditer(text):
        if mask[match.start()]:
            continue
        alt = _SPACES.sub(" ", match.group(1)).strip()
        out.append(text[last : match.start()])
        out.append(f"[그림: {alt}]" if alt else "[그림]")
        last = match.end()
    out.append(text[last:])
    replaced = "".join(out)
    mask = code_mask(replaced)
    return _BARE_NOTE_IMAGE.sub(lambda m: m.group(0) if mask[m.start()] else "", replaced)


@dataclass(frozen=True)
class NoteChunk:
    """노트 본문을 나눈 문단 하나. section은 속한 제목(첫 제목 앞이면 None), text는 전처리한 원문이다."""

    section: str | None
    text: str


def _lines(text: str) -> list[tuple[int, str]]:
    """(줄 시작 위치, 줄 내용). 줄바꿈은 뺀다."""
    out, start = [], 0
    for line in text.split("\n"):
        out.append((start, line))
        start += len(line) + 1
    return out


def _heading_text(line: str) -> str | None:
    match = _HEADING.fullmatch(line)
    if match is None:
        return None
    return _CLOSING_HASHES.sub("", match.group(2) or "").strip()


def _sections(body: str) -> list[tuple[str | None, list[list[str]]]]:
    """본문을 (제목, 단락 목록)으로 나눈다. 단락은 줄 목록이다. 코드 블록 안의 # 줄과 빈 줄은 경계가 아니다."""
    mask = code_mask(body)
    sections: list[tuple[str | None, list[list[str]]]] = [(None, [])]
    block: list[str] = []

    def close() -> None:
        if block:
            sections[-1][1].append(list(block))
            block.clear()

    for start, line in _lines(body):
        in_code = start < len(mask) and mask[start]
        if not in_code:
            heading = _heading_text(line)
            if heading is not None:
                close()
                sections.append((heading or None, []))
                continue
            if not line.strip():
                close()
                continue
        block.append(line)
    close()
    return [section for section in sections if section[1]]


def _split_long(text: str) -> list[str]:
    """MAX_CHUNK_CHARS를 넘는 단락 하나를 줄 경계에서, 줄 하나가 넘으면 글자 수로 나눈다(드문 경우)."""
    pieces: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > MAX_CHUNK_CHARS:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:MAX_CHUNK_CHARS])
            line = line[MAX_CHUNK_CHARS:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > MAX_CHUNK_CHARS:
            pieces.append(current)
            current = line
        else:
            current = candidate
    if current:
        pieces.append(current)
    return [piece for piece in pieces if piece.strip()]


def note_chunks(body: str) -> list[NoteChunk]:
    """노트 본문을 근거 문단으로 나눈다. 같은 본문이면 언제나 같은 결과다(E32가 현재 문단과 인용 당시 문단을 비교한다)."""
    chunks: list[NoteChunk] = []
    for section, blocks in _sections(body.replace("\r\n", "\n").replace("\r", "\n")):
        current = ""
        for lines in blocks:
            paragraph = replace_images("\n".join(lines)).strip("\n")
            if not paragraph.strip():
                continue
            for piece in [paragraph] if len(paragraph) <= MAX_CHUNK_CHARS else _split_long(paragraph):
                candidate = f"{current}\n\n{piece}" if current else piece
                if len(candidate) > MAX_CHUNK_CHARS:
                    chunks.append(NoteChunk(section, current))
                    current = piece
                else:
                    current = candidate
        if current:
            chunks.append(NoteChunk(section, current))
    return chunks


# --- 선택 문맥 제외 ---


def _normal(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def selection_pieces(selection: str) -> list[str]:
    """선택 원문에서 문단 안에 들어 있는지 볼 조각. 선택 전체와, 여러 줄이면 제목이 아닌 긴 줄 각각이다."""
    processed = replace_images(selection)
    pieces = []
    whole = _normal(processed)
    if whole:
        pieces.append(whole)
    lines = [line for line in processed.split("\n") if line.strip()]
    if len(lines) > 1:
        for line in lines:
            piece = _normal(line)
            if _heading_text(line) is None and len(piece) >= MIN_SELECTION_LINE_CHARS and piece not in pieces:
                pieces.append(piece)
    return pieces


def holds_selection(chunk_text: str, pieces: Sequence[str]) -> bool:
    """문단에 선택 원문(조각)이 들어 있거나, 문단 전체가 선택 안에 들어 있는가."""
    text = _normal(chunk_text)
    if not text:
        return False
    return any(piece in text for piece in pieces) or (bool(pieces) and text in pieces[0])


# --- 키워드 점수 ---


def _strip_suffix(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            return word[: -len(suffix)]
    return word


def keywords(text: str) -> list[str]:
    """검색 낱말(소문자, 중복 없음, 나온 순서). 한글 낱말은 끝의 조사·어미를 하나 뗀다. 2글자 미만과 흔한 말은 뺀다."""
    out: list[str] = []
    for word in _WORDS.findall(text.lower()):
        if word in _STOPWORDS:
            continue
        if "가" <= word[0] <= "힣":
            word = _strip_suffix(word)
        if len(word) < 2 or word in _STOPWORDS or word in out:
            continue
        out.append(word)
    return out


def _count(word: str, text: str) -> int:
    """text에 word가 나온 횟수. 영문·숫자 낱말은 낱말 단위로 센다(put이 output 안에서 세지지 않게). 한글은 조사가 붙으므로
    부분 문자열로 센다."""
    if _LATIN.fullmatch(word):
        return len(re.findall(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text))
    return text.count(word)


def _score(words: Iterable[str], body: str, head: str) -> float:
    total = 0.0
    for word in words:
        count = min(_count(word, body), MAX_COUNT)
        bonus = TITLE_BONUS if _count(word, head) else 0
        total += count + bonus
    return total


@dataclass(frozen=True)
class _Candidate:
    note_id: int
    index: int
    paragraph: Paragraph
    body: str
    head: str


def _candidates(notes: Iterable[dict[str, Any]], excluded: dict[int, list[list[str]]]) -> list[_Candidate]:
    out = []
    for note in notes:
        note_id = note["id"]
        title = note.get("title") or ""
        if not title.strip() or not isinstance(note.get("body_markdown"), str):
            continue
        selections = excluded.get(note_id, [])
        for index, chunk in enumerate(note_chunks(note["body_markdown"])):
            if any(holds_selection(chunk.text, pieces) for pieces in selections):
                continue
            paragraph = Paragraph(
                source_kind=SOURCE_KIND,
                source_id=str(note_id),
                revision=str(note["revision"]),
                title=title,
                text=chunk.text,
                section=chunk.section,
            )
            head = f"{title}\n{chunk.section or ''}".lower()
            out.append(_Candidate(note_id, index, paragraph, chunk.text.lower(), head))
    return out


def search_notes(notes: Iterable[dict[str, Any]], question: str, context: RetrievalContext) -> list[Paragraph]:
    """공개 노트 행(id·revision·title·body_markdown)에서 질문에 맞는 문단을 점수 순으로 최대 MAX_RESULTS개 고른다."""
    excluded: dict[int, list[list[str]]] = {}
    for note_id, text in zip(context.selection_note_ids, context.selection_texts, strict=False):
        pieces = selection_pieces(text)
        if pieces:
            excluded.setdefault(note_id, []).append(pieces)

    asked = keywords(question)
    context_text = "\n".join([*context.selection_texts, context.topic_label, *context.recent_questions[-1:]])
    around = [word for word in keywords(context_text) if word not in asked]
    if not asked:
        # 빠른 질문 칩처럼 질문에 낱말이 없으면 문맥 낱말로 찾는다.
        asked, around = around, []
    if not asked:
        return []

    scored = []
    for candidate in _candidates(notes, excluded):
        main = _score(asked, candidate.body, candidate.head)
        if main <= 0:
            continue
        total = main + CONTEXT_WEIGHT * _score(around, candidate.body, candidate.head)
        scored.append((-total, candidate.note_id, candidate.index, candidate.paragraph))
    # 점수가 같으면 노트 id, 문단 순서로 정한다(같은 입력이면 같은 결과).
    scored.sort(key=lambda row: row[:3])
    return [row[3] for row in scored[:MAX_RESULTS]]


class NoteRetriever:
    """D1 노트 임시 검색. 공개 노트만 읽는다(역할 무관). 권한 확인은 DB 조회의 is_published 필터가 맡는다."""

    version = RETRIEVAL_VERSION
    source_kind = SOURCE_KIND

    def __init__(self, supabase: SupabaseClient):
        self._supabase = supabase

    def retrieve(self, user: SessionUser, question: str, context: RetrievalContext) -> Sequence[Paragraph]:
        notes = self._supabase.list_published_note_bodies()
        paragraphs = search_notes(notes, question, context)
        logger.info("stage=retrieve notes=%d paragraphs=%d", len(notes), len(paragraphs))
        return paragraphs
