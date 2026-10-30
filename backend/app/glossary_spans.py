"""노트 본문에서 사전 용어 위치를 찾는다 (E05 glossary_spans, API spec v0.2 2.4·Q-N2).

본문은 바꾸지 않는다. 위치는 원문 body_markdown의 유니코드 코드포인트이고 시작 포함·끝 제외다.
찾기 규칙(2026-10-30 김준성 결정, MEG-73):
- NFC로 맞추고 영문 대소문자를 무시해 terms.key와 비교한다. 공백 여러 개·줄바꿈은 key의 공백 하나와 같다.
- 영문·숫자로 시작(끝)하는 용어는 바로 앞(뒤) 글자가 영문·숫자이면 일치로 보지 않는다(SHIP 속 IP).
  한글은 조사가 붙어도 일치한다.
- note-image: 토큰 안은 찾지 않는다.
- 겹치면 긴 쪽을 남긴다. 길이가 같으면 앞에 나온 쪽, 그다음 term_id가 작은 쪽이다.
"""

import re
import unicodedata
from dataclasses import dataclass

# 본문의 이미지 토큰(note-image:{notion_block_id}). 마크다운 이미지 주소 자리에 들어 있어 ')'나 공백에서 끝난다.
_IMAGE_TOKEN = re.compile(r"note-image:[^\s)]*")
_WORD_CHAR = re.compile(r"[A-Za-z0-9]")
_SPACES = re.compile(r"\s+")
_ASCII_LOWER = {code: code + 32 for code in range(ord("A"), ord("Z") + 1)}


@dataclass(frozen=True)
class Span:
    term_id: int
    start: int
    end: int


def _ascii_lower(text: str) -> str:
    # str.lower()는 비ASCII 글자(İ 등)에서 길이가 바뀔 수 있다. 영문만 바꿔 위치를 지킨다.
    return text.translate(_ASCII_LOWER)


def normalize_key(text: str) -> str:
    """용어 key 정규화(공백 정리·NFC·영문 소문자). 기술 검토 5절의 정규화 함수와 같은 규칙이다."""
    return _ascii_lower(_SPACES.sub(" ", unicodedata.normalize("NFC", text)).strip())


def _composes_with_previous(char: str) -> bool:
    """NFC가 앞 글자와 합칠 수 있는 글자. 결합 문자와 한글 중성·종성 자모다."""
    if unicodedata.combining(char):
        return True
    code = ord(char)
    return 0x1161 <= code <= 0x1175 or 0x11A8 <= code <= 0x11C2


def _nfc_with_offsets(body: str) -> tuple[str, list[int], list[bool]]:
    """본문을 NFC로 바꾸고 NFC 위치 → 원문 위치 대응을 만든다.

    합쳐질 수 있는 글자 묶음(앞 글자 + 뒤따르는 결합 문자·자모) 단위로 바꾼다. 묶음 안에서는 위치를
    나눌 수 없으므로 boundary[i]가 False인 NFC 위치에서 시작하거나 끝나는 일치는 버린다.
    offsets와 boundary는 NFC 길이 + 1개다(끝 위치 포함).
    """
    if unicodedata.is_normalized("NFC", body):
        return body, list(range(len(body) + 1)), [True] * (len(body) + 1)
    pieces: list[str] = []
    offsets: list[int] = []
    boundary: list[bool] = []
    start = 0
    for i in range(1, len(body) + 1):
        if i < len(body) and _composes_with_previous(body[i]):
            continue
        cluster = unicodedata.normalize("NFC", body[start:i])
        pieces.append(cluster)
        offsets.extend([start] * len(cluster))
        boundary.extend([True] + [False] * (len(cluster) - 1))
        start = i
    offsets.append(len(body))
    boundary.append(True)
    return "".join(pieces), offsets, boundary


def _key_pattern(key: str) -> re.Pattern[str]:
    pattern = r"\s+".join(re.escape(part) for part in key.split(" "))
    if _WORD_CHAR.fullmatch(key[0]):
        pattern = r"(?<![A-Za-z0-9])" + pattern
    if _WORD_CHAR.fullmatch(key[-1]):
        pattern += r"(?![A-Za-z0-9])"
    return re.compile(pattern)


def find_spans(body: str, terms: list[tuple[int, str]]) -> list[Span]:
    """terms는 (term_id, key) 목록이다. 본문 원문의 코드포인트 위치를 시작 순서로 돌려준다."""
    text, offsets, boundary = _nfc_with_offsets(body)
    text = _ascii_lower(text)
    blocked = [(m.start(), m.end()) for m in _IMAGE_TOKEN.finditer(text)]

    # 정규화하면 같은 key가 되는 용어는 term_id가 작은 쪽만 쓴다.
    by_key: dict[str, int] = {}
    for term_id, key in sorted(terms):
        normalized = normalize_key(key)
        if normalized:
            by_key.setdefault(normalized, term_id)

    candidates: list[tuple[int, int, int]] = []
    for key, term_id in by_key.items():
        for match in _key_pattern(key).finditer(text):
            start, end = match.start(), match.end()
            if not (boundary[start] and boundary[end]):
                continue
            if any(start < b_end and end > b_start for b_start, b_end in blocked):
                continue
            candidates.append((start, end, term_id))

    candidates.sort(key=lambda c: (-(c[1] - c[0]), c[0], c[2]))
    kept: list[tuple[int, int, int]] = []
    for start, end, term_id in candidates:
        if all(end <= k_start or start >= k_end for k_start, k_end, _ in kept):
            kept.append((start, end, term_id))
    kept.sort()
    return [Span(term_id=term_id, start=offsets[start], end=offsets[end]) for start, end, term_id in kept]
