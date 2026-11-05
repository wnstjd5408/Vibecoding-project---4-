"""Synthetic whitespace regressions; no remote data."""
import pytest
from markdown_it import MarkdownIt
from scripts.notion_content import rich_text
from app.glossary_spans import find_spans


@pytest.mark.parametrize("raw", [" 용어 ", "용어 ", "\t용어\t", "😀한글 ", " A* ", "", " \t\n", "첫줄\n다음줄 "])
@pytest.mark.parametrize("annotations", [{"bold": True}, {"italic": True}, {"bold": True, "italic": True}])
def test_whitespace_and_text_are_preserved(raw, annotations):
    body = rich_text([{"plain_text": raw, "annotations": annotations}])
    tokens = MarkdownIt().parseInline(body)[0].children
    visible = "".join("\n" if t.type in {"softbreak", "hardbreak"} else t.content for t in tokens if t.type in {"text", "softbreak", "hardbreak"})
    assert visible == raw
    if raw.strip():
        assert any(t.type in {"strong_open", "em_open"} for t in tokens)
    else:
        assert body == raw


def test_code_link_literal_and_span():
    items = [
        {"plain_text": "😀 "},
        {"plain_text": "한글용어 ", "annotations": {"bold": True}},
        {"plain_text": "A* ", "annotations": {"italic": True}},
        {"plain_text": " x* ", "annotations": {"code": True, "bold": True}},
        {"plain_text": " 링크 ", "annotations": {"bold": True}, "text": {"link": {"url": "https://example.test"}}},
    ]
    body = rich_text(items)
    assert "**한글용어** " in body
    assert "*A\\** " in body
    assert "`  x*  `" in body
    assert "[ **링크** ](https://example.test)" in body
    spans = find_spans(body, [(1, "한글용어")])
    assert len(spans) == 1
    assert body[spans[0].start:spans[0].end] == "한글용어"


def test_adjacent_identical_runs_and_blank_lines():
    items = [{"plain_text": value, "annotations": {"bold": True}} for value in ["앞", "뒤 ", "\n\n다음\t"]]
    assert rich_text(items) == "**앞뒤** \n\n**다음**\t"
    assert [i["plain_text"] for i in items] == ["앞", "뒤 ", "\n\n다음\t"]
