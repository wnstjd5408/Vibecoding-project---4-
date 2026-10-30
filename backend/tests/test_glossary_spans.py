"""E05 glossary_spans 위치 계산 (MEG-73 AC-2). 위치로 본문을 자르면 그 용어 글자가 나와야 한다.

본문은 모두 합성 데이터다. 위치는 파이썬 문자열 인덱스(= 유니코드 코드포인트)로 자른다.
"""

import unicodedata

import pytest

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
    body = "ROUND\nrobin 과 round robin"

    spans = find_spans(body, [(6, "  Round   ROBIN ")])

    assert cut(body, spans) == [(6, "ROUND\nrobin"), (6, "round robin")]


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


def test_match_inside_a_composed_character_is_dropped():
    # "한"(ㅎ+ㅏ+ㄴ)의 앞부분 "하"는 원문에서 글자 경계가 아니라 자를 수 없다.
    body = unicodedata.normalize("NFD", "한글")

    assert find_spans(body, [(9, "하")]) == []


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
