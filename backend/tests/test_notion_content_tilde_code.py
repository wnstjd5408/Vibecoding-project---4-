"""MEG-142: Notion 변환의 물결표 이스케이프와 인라인 코드 줄바꿈 규칙(합성 입력만 사용)."""

from unittest.mock import Mock

import pytest

from app.glossary_spans import find_spans
from scripts.notion_content import convert, rich_text

PAGE = "00000000-0000-4000-8000-000000000002"
BLOCK = "00000000-0000-4000-8000-000000000003"
TABLE = "00000000-0000-4000-8000-000000000004"
TOGGLE = "00000000-0000-4000-8000-000000000005"


def text(content, **annotations):
    return {"plain_text": content, "annotations": annotations}


def markdown(tree):
    notion = Mock()
    notion.children.side_effect = lambda block_id: tree[block_id]
    return convert(notion, PAGE).markdown


def paragraph(*items, block_id=BLOCK):
    return {"id": block_id, "type": "paragraph", "paragraph": {"rich_text": list(items)}}


@pytest.mark.parametrize("raw,expected", [
    ("~~~ 글 ~~~", r"\~\~\~ 글 \~\~\~"),
    ("1~3일 또는 5~10일, ~ 하나", r"1\~3일 또는 5\~10일, \~ 하나"),
    ("~", r"\~"),
])
def test_tilde_outside_code_is_escaped(raw, expected):
    assert rich_text([text(raw)]) == expected
    assert markdown({PAGE: [paragraph(text(raw))]}) == expected


def test_tilde_in_formatting_and_links_is_escaped():
    assert rich_text([text("a~b", bold=True)]) == r"**a\~b**"
    # 취소선 서식의 표시 문자 ~~는 그대로이고 안쪽 글자의 ~만 이스케이프한다.
    assert rich_text([text("a~b", strikethrough=True)]) == r"~~a\~b~~"
    linked = {"text": {"content": "~/x", "link": {"url": "https://example.test/a"}}, "plain_text": "~/x"}
    assert rich_text([linked]) == r"[\~/x](https://example.test/a)"


def test_tilde_inside_inline_code_is_unchanged():
    assert rich_text([text("a~~~b", code=True)]) == "` a~~~b `"


def test_tilde_inside_code_block_is_unchanged():
    tree = {PAGE: [{"id": BLOCK, "type": "code", "code": {"rich_text": [text("~~~\nx~y\n~~~")]}}]}
    assert markdown(tree) == "```\n~~~\nx~y\n~~~\n```"


@pytest.mark.parametrize("raw,expected", [
    ("a\nb", "` a b `"),
    ("a\r\nb", "` a b `"),
    ("a\rb", "` a b `"),
    ("a\n\nb", "` a  b `"),
    ("a\r\n\r\nb", "` a  b `"),
    ("a \n b", "` a   b `"),
    ("a\t\nb", "` a\t b `"),
    ("x\n", "` x  `"),
])
def test_inline_code_newlines_become_one_space_each(raw, expected):
    assert rich_text([text(raw, code=True)]) == expected


def test_inline_code_with_backticks_keeps_fence_length():
    assert rich_text([text("a`b\nc", code=True)]) == "`` a`b c ``"


def test_blank_line_in_inline_code_stays_one_paragraph():
    body = markdown({PAGE: [paragraph(text("a\n\nb", code=True))]})
    assert "\n\n" not in body


def test_table_cell_inline_code_has_no_br_but_plain_text_keeps_br():
    tree = {PAGE: [{"id": TABLE, "type": "table", "table": {"table_width": 2, "has_column_header": True}}],
            TABLE: [{"table_row": {"cells": [[text("H1")], [text("H2")]]}},
                    {"table_row": {"cells": [[text("a\nb", code=True)], [text("c\nd")]]}}]}
    body = markdown(tree)
    assert "| ` a b ` | c<br>d |" in body
    assert "` a<br>b `" not in body


def test_inline_code_in_list_and_toggle_children():
    tree = {PAGE: [{"id": TOGGLE, "type": "toggle", "has_children": True, "toggle": {"rich_text": [text("t")]}}],
            TOGGLE: [paragraph(text("x\n\ny", code=True), text(" ~ "), block_id=BLOCK)]}
    body = markdown(tree)
    assert "  - ` x  y ` \\~ " in body
    assert "\n\n    " not in body.split("  - ", 1)[1].split("\n", 1)[0]


def test_glossary_span_with_tilde_term_survives_escaping():
    body = markdown({PAGE: [paragraph(text("경로는 ~/home 입니다"))]})
    assert body == r"경로는 \~/home 입니다"
    spans = find_spans(body, [(1, "~/home")])
    assert [(s.term_id, body[s.start:s.end]) for s in spans] == [(1, r"\~/home")]


def test_glossary_span_ignores_tilde_fence_lookalike_after_escaping():
    body = markdown({PAGE: [paragraph(text("~~~ 용어 ~~~"))]})
    assert [(s.term_id, body[s.start:s.end]) for s in find_spans(body, [(1, "용어")])] == [(1, "용어")]
    # 이스케이프하지 않으면 틸드 울타리 코드 블록으로 보여 뒤의 용어를 놓친다.
    following = body + "\n\n다음 문단 용어"
    assert len(find_spans(following, [(1, "용어")])) == 2


def test_glossary_span_in_collapsed_inline_code_keeps_positions():
    # 인라인 코드 안의 용어도 기존처럼 찾고, 줄바꿈을 공백으로 바꿔도 뒤 문단의 위치 계산이 맞는다.
    body = markdown({PAGE: [paragraph(text("앞 "), text("용어\n뒤", code=True), text(" 용어"))]})
    assert body == "앞 ` 용어 뒤 ` 용어"
    spans = find_spans(body, [(1, "용어")])
    assert [body[s.start:s.end] for s in spans] == ["용어", "용어"]
