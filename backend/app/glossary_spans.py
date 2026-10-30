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

import bisect
import re
import unicodedata
from dataclasses import dataclass

# 글자로 보이지 않는 구간: 이미지 토큰(note-image:{notion_block_id}), 맨 URL, 마크다운 링크 주소.
# 소문자로 바꾼 본문에 쓴다. 링크 주소는 `]` 앞 백슬래시가 짝수 개(0개 포함)일 때만이다. 홀수 개면 `]`가
# 이스케이프된 글자라 링크가 아니다. 숨기는 구간은 그룹 1(`](...`)이다.
_HIDDEN = re.compile(r"note-image:[^\s)]*|(?:https?|ftp)://[^\s)<>\]]*")
_LINK_DESTINATION = re.compile(r"(?<!\\)(?:\\\\)*(\]\([^)\s]*)")
# 코드 블록 여는 줄(백틱·물결 3개 이상). 가져오기는 토글·목록 안의 블록을 "  - " 뒤나 4칸 들여쓴 줄에 쓰므로
# 앞의 들여쓰기와 목록 표시(-, +, *, 1. 1))를 받는다. 그룹 1은 펜스 앞부분, 2는 펜스, 3은 info(언어 이름 등)다.
_FENCE_OPEN = re.compile(r"([ \t]*(?:(?:[-+*]|\d{1,9}[.)])[ \t]+)*)(`{3,}|~{3,})([^\n]*)")
_BACKTICKS = re.compile(r"`+")
# 인라인 코드는 문단을 넘지 않는다. 빈 줄(공백·\r만 있는 줄 포함)이 문단 경계다.
_BLANK_LINE = re.compile(r"\n[ \t\r]*\n")
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

    공백을 합치기 전의 글에 쓴다. CommonMark를 가져오기 형식(scripts/notion_content.py)에 맞춰 단순화했다.
    - 코드 블록: 여는 줄(들여쓰기·목록 표시 허용)부터, 같은 글자가 여는 줄 이상 이어지고 나머지가 공백·\\r뿐인
      닫는 줄까지다. 닫는 줄이 없으면 끝까지다. 백틱 펜스의 info에 백틱이 있으면 펜스가 아니라 인라인 코드다.
    - 인라인 코드: 백틱 묶음부터 같은 문단 안의 길이가 같은 다음 묶음까지다. 묶음의 첫 백틱이 이스케이프됐으면
      나머지 백틱이 여는 묶음이다. 닫는 묶음 앞의 백슬래시는 코드 글자라 따지지 않는다.
    - 목록 안 코드 블록: 여는 줄에 목록 표시가 있거나 4칸 이상 들여썼으면, 그 펜스 글자 위치보다 덜 들여쓴
      줄(빈 줄 제외)에서 목록 항목과 함께 끝난다.
    - 하지 않는 것: 4칸 들여쓴 코드 블록(가져오기는 목록 자식 줄을 4칸 들여쓰므로 코드로 보면 안 된다).
    """
    mask = bytearray(len(text))
    if "```" in text or "~~~" in text:
        _mask_fenced_blocks(text, mask)
    if "`" in text:
        _mask_code_spans(text, mask)
    return mask


def _mask_fenced_blocks(text: str, mask: bytearray) -> None:
    lines: list[tuple[int, int]] = []
    start = 0
    while start <= len(text):
        end = text.find("\n", start)
        end = len(text) if end == -1 else end
        lines.append((start, end))
        start = end + 1

    index = 0
    while index < len(lines):
        line_start, line_end = lines[index]
        index += 1
        fence = _FENCE_OPEN.fullmatch(text, line_start, line_end)
        if fence is None or (fence.group(2)[0] == "`" and "`" in fence.group(3)):
            continue
        char, width = fence.group(2)[0], len(fence.group(2))
        prefix = fence.group(1)
        # 목록 항목 안의 코드 블록은 항목이 끝나면 함께 끝난다. 맨 앞(0~3칸)의 코드 블록은 들여쓰기로 끝나지 않는다.
        # 한계: 항목 내용 칸 대신 펜스 글자 칸을 기준으로 삼고 탭을 1칸으로 센다. 가져오기는 한 항목의 모든 줄을
        # 같은 칸 수의 공백으로 들여쓰므로 차이가 나지 않는다.
        container = len(prefix) if prefix.strip() or len(prefix) >= 4 else 0
        block_end = len(text)
        while index < len(lines):
            next_start, next_end = lines[index]
            line = text[next_start:next_end]
            stripped = line.strip(" \t\r")
            if container and stripped and len(line) - len(line.lstrip(" \t")) < container:
                block_end = lines[index - 1][1]
                break
            index += 1
            if len(stripped) >= width and stripped == char * len(stripped):
                block_end = next_end
                break
        mask[line_start:block_end] = b"\x01" * (block_end - line_start)


def _mask_code_spans(text: str, mask: bytearray) -> None:
    breaks = [match.start() for match in _BLANK_LINE.finditer(text)]
    runs = [(run.start(), run.end()) for run in _BACKTICKS.finditer(text) if not mask[run.start()]]
    # 길이별 묶음 번호 목록. 여는 묶음마다 같은 길이의 다음 묶음을 이분 탐색으로 찾는다(짝이 없는 묶음이 많아도
    # 문단 끝까지 훑지 않는다).
    by_width: dict[int, list[int]] = {}
    for number, (run_start, run_end) in enumerate(runs):
        by_width.setdefault(run_end - run_start, []).append(number)
    index = 0
    while index < len(runs):
        opener_start, opener_end = runs[index]
        index += 1
        if _is_escaped(text, opener_start):
            opener_start += 1
            if opener_start == opener_end:
                continue
        candidates = by_width.get(opener_end - opener_start, [])
        later = bisect.bisect_left(candidates, index)
        if later == len(candidates):
            continue
        closer_start, closer_end = runs[candidates[later]]
        next_break = bisect.bisect_right(breaks, opener_start)
        if next_break < len(breaks) and closer_start >= breaks[next_break]:
            continue
        mask[opener_start:closer_end] = b"\x01" * (closer_end - opener_start)
        index = candidates[later] + 1


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

    # 코드 판정은 들여쓰기·줄 끝이 그대로인 원래 글에서 한다.
    code = _code_mask(text)
    out: list[str] = []
    out_positions: list[int] = []
    out_hidden = bytearray()
    cursor = 0
    for match in _ESCAPE.finditer(collapsed):
        if code[positions[match.start()]]:
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
