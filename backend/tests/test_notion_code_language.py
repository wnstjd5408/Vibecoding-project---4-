"""MEG-149: Notion code block language survives as a Markdown fence info string.

Synthetic Notion blocks only; no real service is contacted.
"""

import re
from unittest.mock import Mock

import pytest

from app.glossary_spans import find_spans
from scripts.notion_content import convert

PAGE = "00000000-0000-4000-8000-000000000001"


def block(n, kind, text="", language=None, children=False):
    data = {"rich_text": [{"plain_text": text}]}
    if language is not None:
        data["language"] = language
    return {"id": f"00000000-0000-4000-8000-{n:012d}", "type": kind, kind: data, "has_children": children}


def body_of(tree):
    notion = Mock()
    notion.children.side_effect = lambda block_id: tree[block_id]
    return convert(notion, PAGE).markdown


def one_code(text, language):
    return body_of({PAGE: [block(2, "code", text, language)]})


MERMAID = "graph TD\n  A-->B"


def test_mermaid_keeps_language_and_code_text():
    assert one_code(MERMAID, "mermaid") == f"```mermaid\n{MERMAID}\n```"


@pytest.mark.parametrize("language, expected", [
    ("python", "python"),
    ("JavaScript", "javascript"),
    ("c++", "c++"),
    ("c#", "c#"),
    ("objective-c", "objective-c"),
    ("Visual Basic", "visual-basic"),
    ("  Shell  ", "shell"),
])
def test_general_languages_are_normalised_and_kept(language, expected):
    assert one_code("x = 1", language) == f"```{expected}\nx = 1\n```"


@pytest.mark.parametrize("language", [
    None,                    # key absent
    "",                      # empty
    "   ",
    "plain text",            # Notion's "no language" choice
    "Plain Text",
    "py\nthon",              # newline would split the opening fence line
    "py```thon",             # backticks would close or break the fence
    "`",
    "a`b",
    "<script>",
    "한글",
    "a" * 33,                # longer than the allowed length
    "x/y",
    123,                     # wrong type
    ["python"],
])
def test_missing_or_invalid_language_falls_back_to_bare_fence(language):
    body = one_code("x = 1", language)
    assert body == "```\nx = 1\n```"


def test_valid_language_boundary_length_is_kept():
    assert one_code("x", "a" * 32) == "```" + "a" * 32 + "\nx\n```"


def test_longer_fence_when_code_contains_backticks_keeps_language():
    code = "echo ```\nhi\n```"
    body = one_code(code, "mermaid")
    assert body == f"````mermaid\n{code}\n````"
    # Exactly one opening and one closing line at the outer fence width.
    assert len(re.findall(r"(?m)^````", body)) == 2


def test_hostile_language_cannot_inject_extra_lines_or_fences():
    body = one_code("print(1)", "python\n```\n# injected")
    assert body == "```\nprint(1)\n```"


def test_language_inside_toggle_list_item_is_kept_with_indent():
    tree = {PAGE: [block(2, "toggle", "t", children=True)],
            "00000000-0000-4000-8000-000000000002": [block(3, "code", MERMAID, "mermaid")]}
    body = body_of(tree)
    assert "  - ```mermaid\n    graph TD\n      A-->B\n    ```" in body


def test_mixed_languages_in_one_page_stay_in_order():
    body = body_of({PAGE: [block(2, "code", "a", "python"), block(3, "paragraph", "mid"),
                           block(4, "code", MERMAID, "mermaid"), block(5, "code", "z", "plain text")]})
    assert body.split("\n\n") == ["```python\na\n```", "mid", f"```mermaid\n{MERMAID}\n```", "```\nz\n```"]


@pytest.mark.parametrize("body", [
    "```python\nx = python\n```",
    "- ```python\n  x = python\n  ```",
    "intro\n\n```c++\nc++\n```",
])
def test_glossary_spans_skip_the_language_name_but_find_code_text(body):
    term = "c++" if "c++" in body else "python"
    spans = find_spans(body, [(1, term)])
    assert [body[s.start:s.end] for s in spans] == [term]
    # The one match is in the code text, not on the opening fence line.
    assert body.count("\n", 0, spans[0].start) >= (2 if body.startswith("intro") else 1)


def test_glossary_spans_prose_term_is_still_found_next_to_a_labelled_fence():
    body = body_of({PAGE: [block(2, "paragraph", "python 설명"), block(3, "code", "x", "python")]})
    spans = find_spans(body, [(1, "python")])
    assert [(s.start, s.end) for s in spans] == [(0, 6)]


def test_glossary_spans_find_literal_stars_in_labelled_code_like_bare_code():
    # In code, `*` is a visible character (MEG-143): term "a*" matches inside **A**.
    labelled = body_of({PAGE: [block(2, "code", "**A**", "python")]})
    bare = body_of({PAGE: [block(2, "code", "**A**", None)]})
    assert labelled.startswith("```python\n") and bare.startswith("```\n")
    assert len(find_spans(labelled, [(1, "a*")])) == len(find_spans(bare, [(1, "a*")])) == 1
