"""노트 본문에서 사전 용어 위치를 찾는다 (E05 glossary_spans, API spec v0.2 2.4·Q-N2).

본문은 바꾸지 않는다. 위치는 원문 body_markdown의 유니코드 코드포인트이고 시작 포함·끝 제외다.
찾기 규칙(2026-10-30 김준성 결정, MEG-73):
- NFC로 맞추고 영문 대소문자를 무시해 terms.key와 비교한다.
- (2026-10-30 김준성 확인) 줄 안의 공백 여러 개(탭 포함)는 key의 공백 하나와 같다. 줄바꿈은 넘지 않는다. 제목 줄과
  다음 줄처럼 줄바꿈 하나로도 블록이 바뀌므로 다른 블록에 걸친 강조를 막는다. 문단 안 soft break에 걸친 용어는 놓친다.
- 영문·숫자로 시작(끝)하는 용어는 바로 앞(뒤) 글자가 영문·숫자이면 일치로 보지 않는다(SHIP 속 IP).
  한글은 조사가 붙어도 일치한다.
- note-image: 토큰 안은 찾지 않는다. (2026-10-30 김준성 확인) 화면에 글자로 보이지 않는 링크 주소(](...))와 맨 URL
  안도 찾지 않는다. 링크가 아닌 `](...)` 모양 글자 안의 용어는 놓친다.
- 겹치면 긴 쪽을 남긴다. 길이가 같으면 앞에 나온 쪽, 그다음 term_id가 작은 쪽이다.
- 마크다운 백슬래시 이스케이프(백슬래시 + ASCII 문장부호)는 풀어서 비교한다. Notion 가져오기가 특수문자를
  이스케이프해 저장하므로 용어 `A*`는 본문의 `A` + 백슬래시 + `*`와 일치한다. 위치는 이스케이프 백슬래시를 포함한
  원문 구간이다(원문을 자른 뒤 이스케이프를 풀면 용어 글자가 된다). 코드(인라인 코드, 코드 블록) 안의 백슬래시는
  CommonMark처럼 글자 그대로 둔다. 가져오기도 코드는 이스케이프하지 않고 저장한다.
- 한계: 강조 표시 `*`와 글자 `*`를 구분하지 않는다(`**A**`에서 용어 `A*`가 일치할 수 있다). 마크다운 파서가 필요하다.
"""

import re
import unicodedata
from dataclasses import dataclass

# 글자로 보이지 않는 구간: 이미지 토큰(note-image:{notion_block_id}), 맨 URL, 마크다운 링크 주소.
# 소문자로 바꾼 본문에 쓴다. 링크 주소는 `]` 앞 백슬래시가 짝수 개(0개 포함)일 때만이다. 홀수 개면 `]`가
# 이스케이프된 글자라 링크가 아니다. 숨기는 구간은 그룹 1(`](...`)이다.
_HIDDEN = re.compile(r"note-image:[^\s)]*|(?:https?|ftp)://[^\s)<>\]]*")
_LINK_DESTINATION = re.compile(r"(?<!\\)(?:\\\\)*(\]\([^)\s]*)")
# 코드 블록 여는 줄(백틱·물결 3개 이상)과 인라인 코드의 백틱 묶음.
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})", re.MULTILINE)
_BACKTICKS = re.compile(r"`+")
# 줄 안의 공백. str.splitlines가 줄 끝으로 보는 글자(\n, \r, \v, \f, \x1c~\x1e, \x85, U+2028, U+2029)는 뺀다.
_LINE_SPACES = re.compile(r"[^\S\n\r\v\f\x1c-\x1e\x85\u2028\u2029]+")
_SPACES = re.compile(r"\s+")
# 마크다운 백슬래시 이스케이프(CommonMark: 백슬래시 뒤의 ASCII 문장부호 하나).
# 가져오기 스크립트(scripts/notion_content.py escaped)가 \ ` * _ { } [ ] < > ! | 앞에 백슬래시를 붙여 저장한다.
_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
_ASCII_LOWER = {code: code + 32 for code in range(ord("A"), ord("Z") + 1)}


@dataclass(frozen=True)
class Span:
    term_id: int
    start: int
    end: int


def _ascii_lower(text: str) -> str:
    # str.lower()는 비ASCII 글자(İ 등)에서 길이가 바뀔 수 있다. 영문만 바꿔 위치를 지킨다.
    return text.translate(_ASCII_LOWER)


def _is_word_char(char: str) -> bool:
    return char.isascii() and char.isalnum()


def normalize_key(text: str) -> str:
    """용어 key 정규화(공백 정리·NFC·영문 소문자). 기술 검토 5절의 정규화 함수와 같은 규칙이다."""
    return _ascii_lower(_SPACES.sub(" ", unicodedata.normalize("NFC", text)).strip())


def _composing_starters() -> frozenset[str]:
    """결합 등급이 0인데 NFC가 앞 글자와 합칠 수 있는 글자(한글 중성·종성 자모, 일부 인도계 모음 기호 등).

    정준 분해가 두 글자인 문자의 두 번째 글자를 모은다. 조합 제외 문자까지 들어가 실제보다 조금 넓지만,
    넓으면 자를 수 없는 위치가 늘 뿐 결과가 틀리지 않는다. 한글 음절은 분해표에 없어 범위로 넣는다.
    """
    found = {chr(code) for code in range(0x1161, 0x1176)} | {chr(code) for code in range(0x11A8, 0x11C3)}
    for code in range(0x80, 0x30000):
        parts = unicodedata.decomposition(chr(code)).split()
        if len(parts) == 2 and not parts[0].startswith("<"):
            second = chr(int(parts[1], 16))
            if not unicodedata.combining(second):
                found.add(second)
    return frozenset(found)


# 가져올 때 한 번 만든다(약 0.05초, 74자).
_COMPOSING_STARTERS = _composing_starters()


def _joins_previous(char: str) -> bool:
    """NFC에서 앞 글자와 합쳐질 수 있는 글자. 이 글자 앞은 위치를 자를 수 있는 경계가 아니다."""
    return not char.isascii() and (unicodedata.combining(char) != 0 or char in _COMPOSING_STARTERS)


def _nfc_with_offsets(body: str) -> tuple[str, list[int], list[bool]]:
    """본문을 NFC로 바꾸고 NFC 위치 → 원문 위치 대응과 자를 수 있는 위치 표시를 만든다.

    합쳐질 수 있는 글자 묶음(앞 글자 + 뒤따르는 결합 문자·자모) 단위로 바꾼다. 묶음 안은 자를 수 없으므로
    boundary가 False인 위치에서 시작하거나 끝나는 일치는 버린다. 본문이 이미 NFC여도 같은 규칙을 쓴다.
    offsets와 boundary는 NFC 길이 + 1개다(끝 위치 포함).
    """
    if unicodedata.is_normalized("NFC", body):
        boundary = [not _joins_previous(char) for char in body]
        boundary.append(True)
        return body, list(range(len(body) + 1)), boundary
    pieces: list[str] = []
    offsets: list[int] = []
    boundary = []
    start = 0
    for i in range(1, len(body) + 1):
        if i < len(body) and _joins_previous(body[i]):
            continue
        cluster = unicodedata.normalize("NFC", body[start:i])
        pieces.append(cluster)
        offsets.extend([start] * len(cluster))
        boundary.extend([True] + [False] * (len(cluster) - 1))
        start = i
    offsets.append(len(body))
    boundary.append(True)
    return "".join(pieces), offsets, boundary


def _is_escaped(text: str, index: int) -> bool:
    """text[index] 바로 앞 백슬래시가 홀수 개면 그 글자는 이스케이프됐다."""
    count = 0
    while index - count > 0 and text[index - count - 1] == "\\":
        count += 1
    return count % 2 == 1


def _code_mask(text: str) -> bytearray:
    """코드 블록과 인라인 코드(구분 기호 포함) 위치를 1로 표시한다. 코드 안에서는 백슬래시가 이스케이프가 아니다.

    CommonMark를 단순화했다: 코드 블록은 같은 글자로 같거나 긴 닫는 줄까지(없으면 끝까지), 인라인 코드는
    이스케이프되지 않은 백틱 묶음부터 길이가 같은 다음 백틱 묶음까지다.
    """
    mask = bytearray(len(text))
    position = 0
    while (fence := _FENCE.search(text, position)) is not None:
        marker = fence.group(1)
        line_end = text.find("\n", fence.end())
        closing = None
        if line_end != -1:
            closing_line = re.compile(r"^ {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*$", re.MULTILINE)
            closing = closing_line.search(text, line_end + 1)
        end = closing.end() if closing else len(text)
        mask[fence.start() : end] = b"\x01" * (end - fence.start())
        position = max(end, fence.end())

    runs = [run for run in _BACKTICKS.finditer(text) if not mask[run.start()]]
    index = 0
    while index < len(runs):
        opener = runs[index]
        index += 1
        if _is_escaped(text, opener.start()):
            continue
        width = opener.end() - opener.start()
        for later in range(index, len(runs)):
            if runs[later].end() - runs[later].start() == width:
                mask[opener.start() : runs[later].end()] = b"\x01" * (runs[later].end() - opener.start())
                index = later + 1
                break
    return mask


def _search_text(text: str) -> tuple[str, list[int], bytearray]:
    """찾기용 글, 찾기용 위치 → text 위치 대응(길이 + 1개), 보이지 않는 구간 표시를 만든다.

    1. 줄 안의 공백 묶음을 공백 하나로 줄인다.
    2. 보이지 않는 구간(_HIDDEN, _LINK_DESTINATION)을 이스케이프가 남은 글에서 표시한다.
    3. 코드 밖의 백슬래시 이스케이프를 풀어 화면에 보이는 글자로 맞춘다. 풀린 글자의 위치는 백슬래시 위치로
       대응시켜 용어가 이스케이프된 글자로 시작해도 원문 구간이 백슬래시부터 시작한다.
    """
    pieces: list[str] = []
    positions: list[int] = []
    cursor = 0
    for match in _LINE_SPACES.finditer(text):
        pieces.append(text[cursor : match.start()])
        positions.extend(range(cursor, match.start()))
        pieces.append(" ")
        positions.append(match.start())
        cursor = match.end()
    pieces.append(text[cursor:])
    positions.extend(range(cursor, len(text)))
    positions.append(len(text))
    collapsed = "".join(pieces)

    hidden = bytearray(len(collapsed))
    for match in _HIDDEN.finditer(collapsed):
        hidden[match.start() : match.end()] = b"\x01" * (match.end() - match.start())
    for match in _LINK_DESTINATION.finditer(collapsed):
        hidden[match.start(1) : match.end(1)] = b"\x01" * (match.end(1) - match.start(1))

    # 대부분의 노트에는 백슬래시가 없다. 그때는 이스케이프를 풀 것이 없어 그대로 쓴다.
    if "\\" not in collapsed:
        return collapsed, positions, hidden

    code = _code_mask(collapsed)
    out: list[str] = []
    out_positions: list[int] = []
    out_hidden = bytearray()
    cursor = 0
    for match in _ESCAPE.finditer(collapsed):
        if code[match.start()]:
            continue
        out.append(collapsed[cursor : match.start()])
        out_positions.extend(positions[cursor : match.start()])
        out_hidden += hidden[cursor : match.start()]
        out.append(match.group(1))
        out_positions.append(positions[match.start()])
        out_hidden.append(hidden[match.start()] | hidden[match.start() + 1])
        cursor = match.end()
    out.append(collapsed[cursor:])
    out_positions.extend(positions[cursor:])
    out_hidden += hidden[cursor:]
    return "".join(out), out_positions, out_hidden


def find_spans(body: str, terms: list[tuple[int, str]]) -> list[Span]:
    """terms는 (term_id, key) 목록이다. 본문 원문의 코드포인트 위치를 시작 순서로 돌려준다.

    용어마다 str.find로 겹치는 출현까지 모두 후보로 모은 뒤, 긴 후보부터 빈 자리에만 놓는다.
    비용은 대략 (용어 수 × 본문 길이)의 C 문자열 검색 + 후보 길이의 합이다.
    """
    nfc, offsets, boundary = _nfc_with_offsets(body)
    text, positions, hidden = _search_text(_ascii_lower(nfc))

    # 정규화하면 같은 key가 되는 용어는 term_id가 작은 쪽만 쓴다.
    by_key: dict[str, int] = {}
    for term_id, key in sorted(terms):
        normalized = normalize_key(key)
        if normalized:
            by_key.setdefault(normalized, term_id)

    candidates: list[tuple[int, int, int]] = []
    for key, term_id in by_key.items():
        word_start, word_end = _is_word_char(key[0]), _is_word_char(key[-1])
        index = text.find(key)
        while index != -1:
            end = index + len(key)
            if (
                not (word_start and index > 0 and _is_word_char(text[index - 1]))
                and not (word_end and end < len(text) and _is_word_char(text[end]))
                and boundary[positions[index]]
                and boundary[positions[end]]
                and hidden.find(1, index, end) == -1
            ):
                candidates.append((index, end, term_id))
            index = text.find(key, index + 1)

    candidates.sort(key=lambda c: (c[0] - c[1], c[0], c[2]))
    taken = bytearray(len(text))
    kept: list[tuple[int, int, int]] = []
    for start, end, term_id in candidates:
        if taken.find(1, start, end) == -1:
            taken[start:end] = b"\x01" * (end - start)
            kept.append((start, end, term_id))
    kept.sort()
    return [
        Span(term_id=term_id, start=offsets[positions[start]], end=offsets[positions[end]])
        for start, end, term_id in kept
    ]
