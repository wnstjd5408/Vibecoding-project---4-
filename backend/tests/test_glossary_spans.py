"""E05 glossary_spans 위치 계산 (MEG-73 AC-2). 위치로 본문을 자르면 그 용어 글자가 나와야 한다.

본문은 모두 합성 데이터다. 위치는 파이썬 문자열 인덱스(= 유니코드 코드포인트)로 자른다.
"""

import time
import unicodedata

import pytest

from app import glossary_spans
from app.glossary_spans import Span, find_spans, normalize_key

TERMS = [(1, "해시"), (2, "해시테이블"), (3, "hashtable"), (4, "ip"), (5, "tcp/ip"), (6, "round robin"), (7, "exampleterm")]


def cut(body: str, spans: list[Span]) -> list[tuple[int, str]]:
    return [(span.term_id, body[span.start : span.end]) for span in spans]


def test_spec_example_1_positions():
    body = "이 노트는 ExampleTerm 을 설명합니다. UnknownWord 는 사전에 없습니다. ![그림](note-image:blk-1)"

    assert find_spans(body, [(7, "exampleterm")]) == [Span(term_id=7, start=6, end=17)]


def test_mixed_korean_english_emoji_body_cuts_back_to_the_terms():
    # 이모지(😀, 👍🏽)는 코드포인트 1~2개지만 UTF-16으로는 2~4칸이다. 위치가 코드포인트 기준인지 확인한다.
    body = "😀 해시테이블은 👍🏽 HashTable과 같다. TCP/IP 위의 IP 주소, Round  Robin 스케줄링 🚀 해시"

    spans = find_spans(body, TERMS)

    assert cut(body, spans) == [
        (2, "해시테이블"),
        (3, "HashTable"),
        (5, "TCP/IP"),
        (4, "IP"),
        (6, "Round  Robin"),
        (1, "해시"),
    ]
    assert body.index("해시테이블") == 2
    # UTF-16 위치였다면 😀 때문에 3이 된다.
    assert spans[0] == Span(term_id=2, start=2, end=7)


def test_longer_term_wins_when_terms_overlap():
    body = "해시테이블"

    assert cut(body, find_spans(body, [(1, "해시"), (2, "해시테이블")])) == [(2, "해시테이블")]


def test_english_term_needs_word_boundaries_but_korean_particles_are_fine():
    body = "SHIP과 zip은 IP가 아니다. ip6도 아니다. 해시는 해시를 해시로"

    assert cut(body, find_spans(body, [(4, "ip"), (1, "해시")])) == [(4, "IP"), (1, "해시"), (1, "해시"), (1, "해시")]


def test_case_and_whitespace_are_normalized_on_both_sides():
    body = "ROUND \t robin 과 round robin"

    spans = find_spans(body, [(6, "  Round   ROBIN ")])

    assert cut(body, spans) == [(6, "ROUND \t robin"), (6, "round robin")]


@pytest.mark.parametrize(
    "body", ["## Round\n\nRobin 문단", "round\nrobin", "round \r\n robin", "round\rrobin", "round\u2028robin", "round\u2029robin", "round\x85robin"]
)
def test_terms_do_not_match_across_line_breaks(body):
    # 제목과 다음 문단처럼 다른 블록에 걸친 강조를 만들지 않는다.
    assert find_spans(body, [(6, "round robin")]) == []


def test_overlapping_occurrences_of_the_same_term_are_all_candidates():
    # 앞쪽 "가나가"(2~5)가 더 긴 용어에 밀려도, 겹쳐 있던 뒤쪽 "가나가"(4~7)는 남는다.
    assert find_spans("다라가나가나가", [(1, "가나가"), (2, "다라가나")]) == [
        Span(term_id=2, start=0, end=4),
        Span(term_id=1, start=4, end=7),
    ]


def test_link_addresses_and_bare_urls_are_not_matched():
    body = "[IP 문서](https://example.test/ip?q=ip) 참고: https://ip.example.test/a 그리고 IP"

    # 링크 글자(IP 문서)와 본문 끝의 IP만 찾는다. 링크 주소·맨 URL 안은 화면에 글자로 보이지 않는다.
    assert cut(body, find_spans(body, [(4, "ip")])) == [(4, "IP"), (4, "IP")]
    assert find_spans(body, [(4, "ip")])[-1].end == len(body)


ESCAPED_TERMS = [(21, "A*"), (22, "__init__"), (23, "std::vector<T>")]


def unescape(text: str) -> str:
    return glossary_spans._ESCAPE.sub(r"\1", text)


def test_markdown_escaped_terms_match_and_cut_includes_the_backslashes():
    # Notion 가져오기는 A* 를 "A\*"로, __init__ 을 "\_\_init\_\_"로 저장한다(scripts/notion_content.py escaped).
    body = "알고리즘 A\\* 와 \\_\\_init\\_\\_ 그리고 std::vector\\<T\\> 끝"

    spans = find_spans(body, ESCAPED_TERMS)

    assert cut(body, spans) == [(21, "A\\*"), (22, "\\_\\_init\\_\\_"), (23, "std::vector\\<T\\>")]
    # 원문 구간에서 이스케이프를 풀면 용어 글자다(AC-2의 원문 기준).
    assert [unescape(text) for _, text in cut(body, spans)] == ["A*", "__init__", "std::vector<T>"]


def test_escaped_backslash_and_escaped_bracket():
    # "\\"는 백슬래시 한 글자다. "\](" 는 이스케이프된 ] 라서 링크 주소가 아니다.
    assert cut("a\\\\b", find_spans("a\\\\b", [(1, "a\\b")])) == [(1, "a\\\\b")]
    assert cut("x\\](ip) ip", find_spans("x\\](ip) ip", [(4, "ip")])) == [(4, "ip"), (4, "ip")]


def test_link_after_an_escaped_backslash_still_hides_its_address():
    # "[dir\\](ip/route)"의 링크 글자는 "dir\"이고 ]는 진짜 링크 닫힘이다. 주소 안의 ip는 찾지 않는다.
    body = "[dir\\\\](ip/route) ip"

    assert [span.start for span in find_spans(body, [(4, "ip")])] == [len(body) - 2]


@pytest.mark.parametrize(
    "body",
    [
        "코드 `a\\*b` 끝",
        "코드 ``a\\*b`` 끝",
        "```\nx = a\\*b\n```",
        "~~~~\nx = a\\*b\n~~~~",
        "```python\nx = a\\*b",  # 닫히지 않은 코드 블록은 끝까지 코드다
    ],
)
def test_backslashes_inside_code_are_literal(body):
    # 가져오기는 코드를 이스케이프하지 않는다. 코드 속 "a\*b"는 화면에 a\*b로 보이므로 용어 a*b가 아니다.
    assert find_spans(body, [(1, "a*b")]) == []
    # 반대로 백슬래시가 든 용어는 코드 안에서 그대로 찾는다.
    assert cut(body, find_spans(body, [(2, "a\\*b")])) == [(2, "a\\*b")]


def test_escaped_backtick_does_not_open_code():
    body = "글자 \\` 다음 A\\* 와 \\` 끝"

    assert cut(body, find_spans(body, [(21, "A*")])) == [(21, "A\\*")]


def test_body_without_backslashes_skips_the_escape_pass():
    text = "보통 노트 ip"

    search, positions, hidden = glossary_spans._search_text(text)

    assert (search, positions, bytes(hidden)) == (text, list(range(len(text) + 1)), bytes(len(text)))


def test_image_tokens_are_never_matched():
    body = "![ip](note-image:blk-ip-hashtable) 본문의 ip"

    spans = find_spans(body, [(4, "ip"), (3, "hashtable")])

    # 대체 글자(alt)의 ip는 글자라 찾고, 토큰 안의 ip·hashtable은 찾지 않는다.
    assert cut(body, spans) == [(4, "ip"), (4, "ip")]
    assert all(span.start < body.index("note-image:") or span.start > body.index(")") for span in spans)


def test_nfd_body_positions_point_into_the_original_text():
    # macOS 등에서 온 NFD 본문(한글 자모 분리)도 NFC 용어와 맞추고, 위치는 원문(NFD) 기준으로 준다.
    body = unicodedata.normalize("NFD", "앞 해시테이블 뒤") + " 😀 café"

    spans = find_spans(body, [(2, "해시테이블"), (8, "café")])

    assert [unicodedata.normalize("NFC", text) for _, text in cut(body, spans)] == ["해시테이블", "café"]
    # NFD로 "앞"은 자모 3개(ㅇㅏㅍ) + 공백이라 해시테이블은 원문 4번째 코드포인트부터다.
    # 해·시·테·이는 자모 2개씩, 블은 3개(ㅂㅡㄹ)라 11칸을 차지한다.
    assert spans[0] == Span(term_id=2, start=4, end=15)
    assert spans[1].end == len(body)


def test_match_inside_a_composed_character_is_dropped():
    # "한"(ㅎ+ㅏ+ㄴ)의 앞부분 "하"는 원문에서 글자 경계가 아니라 자를 수 없다.
    body = unicodedata.normalize("NFD", "한글")

    assert find_spans(body, [(9, "하")]) == []


def test_combining_mark_blocks_a_match_whether_or_not_the_body_is_nfc():
    # 합쳐지지 않는 결합 문자(밑줄 U+0332) 앞은 자를 수 없다. 본문의 다른 곳이 NFD여도 결과가 같아야 한다.
    nfc_body = "cafe̲"
    mixed_body = nfc_body + " " + unicodedata.normalize("NFD", "한")

    assert find_spans(nfc_body, [(1, "cafe")]) == find_spans(mixed_body, [(1, "cafe")]) == []


def test_starter_that_composes_under_nfc_is_handled():
    # 오리야 문자 U+0B47 + U+0B3E는 결합 등급이 둘 다 0이지만 NFC에서 U+0B4B 하나가 된다.
    body = "ୋ"

    assert find_spans(body, [(1, "ୋ")]) == [Span(term_id=1, start=0, end=2)]


def test_long_body_with_many_terms_stays_fast():
    # 명세의 본문 상한(20만 자, 임시)과 PostgREST 최대 행(1000)에 가까운 경우. O(n^2)였을 때는 90초가 넘었다.
    terms = [(i, f"용어{i}") for i in range(1000)] + [(5000, "ai"), (5001, "db"), (5002, "큐")]
    body = ("ai와 db와 큐를 쓰는 노트 " * 15_000)[:200_000]

    started = time.perf_counter()
    spans = find_spans(body, terms)

    assert len(spans) > 30_000
    assert time.perf_counter() - started < 5


def test_keys_that_normalize_the_same_use_the_smaller_term_id():
    body = "TCP"

    assert find_spans(body, [(12, "TCP"), (11, "tcp")]) == [Span(term_id=11, start=0, end=3)]


@pytest.mark.parametrize("key", ["", "   "])
def test_empty_keys_are_ignored(key):
    assert find_spans("  아무 본문  ", [(1, key)]) == []


def test_normalize_key_matches_the_tr_rules():
    assert normalize_key("  Round\tROBIN ") == "round robin"
    assert normalize_key(unicodedata.normalize("NFD", "해시")) == "해시"
    # 영문만 소문자로 바꾼다. 다른 문자는 길이가 바뀌지 않게 그대로 둔다.
    assert normalize_key("İP") == "İp"


def test_empty_body_has_no_spans():
    assert find_spans("", TERMS) == []
