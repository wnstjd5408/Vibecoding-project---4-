"""MEG-208: code blocks inside nested lists/toggles stay real fences and keep their text.

Synthetic Notion blocks only; no real service is contacted.
"""

import itertools
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from markdown_it import MarkdownIt

from app.glossary_spans import find_spans
from scripts.notion_content import convert

PAGE = "00000000-0000-4000-8000-000000000001"
KINDS = ["bulleted_list_item", "numbered_list_item", "to_do", "toggle", "quote", "callout"]
GOLDEN = json.loads((Path(__file__).parent / "fixtures/notion_list_nesting_golden.json").read_text(encoding="utf-8"))
MD = MarkdownIt()
CODE = "x = 1"
MERMAID = "graph TD\n  A-->B"


def block(n, kind, text="", language=None, children=False):
    data = {"rich_text": [{"plain_text": text}]}
    if language is not None:
        data["language"] = language
    if kind == "to_do":
        data["checked"] = False
    return {"id": f"00000000-0000-4000-8000-{n:012d}", "type": kind, kind: data, "has_children": children}


def body_for(path, code=CODE, language=None):
    """Markdown for a code block nested under the container kinds in `path` (outermost first)."""
    tree, parent, n = {}, PAGE, 10
    for kind in path:
        tree[parent] = [block(n, kind, "t", children=True)]
        parent = f"00000000-0000-4000-8000-{n:012d}"
        n += 1
    tree[parent] = [block(n, "code", code, language)]
    notion = Mock()
    notion.children.side_effect = lambda block_id: tree[block_id]
    return convert(notion, PAGE).markdown


def fences(body):
    return [t for t in MD.parse(body) if t.type == "fence"]


def name(path):
    return " > ".join(path)


PATHS_UP_TO_3 = [p for depth in (1, 2, 3) for p in itertools.product(KINDS, repeat=depth)]
PATHS_4 = list(itertools.product(KINDS, repeat=4))


@pytest.mark.parametrize("path", PATHS_UP_TO_3, ids=name)
def test_nested_code_block_is_a_single_fence_with_language_and_text(path):
    # AC-1, AC-2: a parser must read exactly one fence whose info and text match the Notion block.
    body = body_for(path, MERMAID, "mermaid")
    found = fences(body)
    assert len(found) == 1, body
    assert found[0].info == "mermaid" and found[0].content.rstrip("\n") == MERMAID


def test_four_level_nesting_is_all_fences():
    broken = [name(p) for p in PATHS_4 if len(fences(body_for(p, language="python"))) != 1]
    assert broken == []


def test_structures_that_were_already_correct_keep_their_exact_output():
    # AC-2: golden output was produced by the code before MEG-208 for every structure that parsed correctly.
    assert len(GOLDEN) == 228
    changed = [key for key, expected in GOLDEN.items() if body_for(tuple(key.split(" > "))) != expected]
    assert changed == []


@pytest.mark.parametrize("char", ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", " ", " ", "\x85"],
                         ids=["VT", "FF", "FS", "GS", "RS", "LS", "PS", "NEL"])
@pytest.mark.parametrize("path", [
    ("bulleted_list_item",), ("numbered_list_item",), ("to_do",),
    ("bulleted_list_item", "toggle"), ("toggle", "bulleted_list_item"),
], ids=name)
def test_code_text_with_line_separator_like_characters_is_kept(path, char):
    # AC-3: only "\n" separates lines in code text; these characters stay where they are.
    code = f"a{char}b\nc"
    body = body_for(path, code)
    found = fences(body)
    assert len(found) == 1 and char in body
    assert found[0].content.rstrip("\n") == code


def test_glossary_spans_treat_nested_code_as_code():
    # AC-4: in bullet > toggle > code, "**A**" is literal text, so the term "a*" matches inside the code.
    body = body_for(("bulleted_list_item", "toggle"), "**A**", "mermaid")
    spans = find_spans(body, [(1, "a*"), (2, "mermaid")])
    assert [(s.term_id, body[s.start:s.end]) for s in spans] == [(1, "A*")]


@pytest.mark.parametrize("kind, marker", [("bulleted_list_item", "- "), ("numbered_list_item", "1. "), ("to_do", "- [ ] ")])
@pytest.mark.parametrize("kids, suffix", [
    ([("paragraph", "x"), ("paragraph", "")], "x\n    "),           # trailing empty block
    ([("paragraph", "")], ""),                                        # only an empty block
    ([("paragraph", ""), ("paragraph", "x")], "    \n    \n    x"),  # empty block first
], ids=["trailing-empty", "only-empty", "empty-first"])
def test_empty_child_blocks_keep_their_previous_output(kind, marker, kids, suffix):
    # Expected strings are the output of the code before MEG-208 (measured, not guessed).
    tree = {PAGE: [block(10, kind, "t", children=True)],
            "00000000-0000-4000-8000-000000000010": [block(11 + i, k, text) for i, (k, text) in enumerate(kids)]}
    notion = Mock()
    notion.children.side_effect = lambda block_id: tree[block_id]
    lead = f"{marker}t\n\n"
    expected = lead + ("    " + suffix if suffix and not suffix.startswith("    ") else suffix)
    assert convert(notion, PAGE).markdown == expected


def test_carriage_return_in_nested_code_text_is_kept():
    # Before MEG-208 splitlines() treated "\r\n" as one break and dropped the "\r" from list-child code.
    assert body_for(("bulleted_list_item",), "a\r\nb") == "- t\n\n    ```\n    a\r\n    b\n    ```"
