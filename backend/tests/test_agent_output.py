"""CS Agent 프롬프트 상한과 출력 검증 단위 테스트 (MEG-236, API spec v0.2 5절·5.3).

모델은 부르지 않는다. 데이터는 모두 합성이다.

- 사전 확인 상한: 상한을 모두 채운 최악의 입력으로 만든 실제 프롬프트도 max_prompt_chars·max_prompt_tokens 안에 든다.
- Mermaid 허용 문법: 노드와 화살표만 받고 click·스타일·주석·HTML·엔티티·아이콘 문법은 막는다.
- parse_output: state마다 성공 모양과 대표 실패 이유를 본다.
"""

import json

import pytest

from app.agent_output import (
    MAX_MERMAID_CHARS,
    MAX_MERMAID_LINES,
    MAX_PARAGRAPH_CHARS,
    MAX_PARAGRAPHS,
    MAX_QUESTION_CHARS,
    MAX_RECENT_ANSWER_CHARS,
    MAX_RECENT_TURNS,
    MAX_REPLY_TEXT_CHARS,
    MAX_SECTIONS,
    MAX_SELECTION_TOTAL_CHARS,
    MAX_SOURCE_SECTION_CHARS,
    MAX_SOURCE_TITLE_CHARS,
    MAX_TOPIC_CHARS,
    PROMPT_VERSION,
    OutputInvalid,
    PromptInput,
    _data,
    build_prompt,
    correction_allowed,
    max_prompt_chars,
    max_prompt_tokens,
    mermaid_allowed,
    parse_output,
)
from app.agent_retrieval import Paragraph
from app.ai_ledger import estimate_input_tokens

# UTF-8 4바이트 글자(이모지). 한 글자가 가장 많은 바이트를 차지하는 경우다.
WIDE = "😀"


def _worst_case_input(fill: str = WIDE) -> PromptInput:
    """모든 상한을 채우고 넘치게 준 입력. 선택 문맥은 1글자짜리를 상한 글자 수만큼(최대 줄 수) 넘치게 준다."""
    paragraph = Paragraph(
        source_kind="note",
        source_id="n-1",
        revision="r-1",
        title=fill * (MAX_SOURCE_TITLE_CHARS + 10),
        text=fill * (MAX_PARAGRAPH_CHARS + 10),
        section=fill * (MAX_SOURCE_SECTION_CHARS + 10),
    )
    return PromptInput(
        question=fill * (MAX_QUESTION_CHARS + 10),
        topic_label=fill * (MAX_TOPIC_CHARS + 10),
        selections=[fill] * (MAX_SELECTION_TOTAL_CHARS + 10),
        recent=[(fill * (MAX_QUESTION_CHARS + 10), fill * (MAX_RECENT_ANSWER_CHARS + 10))] * (MAX_RECENT_TURNS + 2),
        paragraphs=[paragraph] * (MAX_PARAGRAPHS + 1),
        clarification=fill * (MAX_REPLY_TEXT_CHARS + 10),
        allow_topic_check=True,
    )


# --- 사전 확인 상한 ---


@pytest.mark.parametrize("fill", [WIDE, "가", "<<<", ">>>"], ids=["emoji", "hangul", "open_marker", "close_marker"])
def test_worst_case_prompt_fits_max_prompt_chars(fill):
    prompt = build_prompt(_worst_case_input(fill))
    assert len(prompt) <= max_prompt_chars()


def test_worst_case_prompt_fits_max_prompt_tokens_with_ledger_estimate():
    prompt = build_prompt(_worst_case_input())
    # 원장 추정식(ai_ledger.estimate_input_tokens: UTF-8 바이트/2 올림 + 64)으로 본 실제 프롬프트가 사전 확인 상한 안에 든다.
    assert estimate_input_tokens(prompt) <= max_prompt_tokens()


def test_selection_lines_are_counted_per_selection():
    """선택 문맥은 줄마다 "- "와 줄바꿈이 붙는다. 1글자 선택을 상한 글자 수만큼 쌓아도 상한 안에 든다."""
    data = PromptInput(
        question="q",
        topic_label="t",
        selections=["x"] * MAX_SELECTION_TOTAL_CHARS,
        recent=[],
        paragraphs=[],
    )
    prompt = build_prompt(data)
    assert prompt.count("\n- x") == MAX_SELECTION_TOTAL_CHARS
    assert len(prompt) <= max_prompt_chars()


def test_empty_selections_do_not_add_lines():
    """빈 선택 문맥은 글자 수 상한에 잡히지 않으므로 줄을 만들지 않는다(줄 수가 상한 없이 늘지 않게)."""
    data = PromptInput(question="q", topic_label="t", selections=[""] * 5000, recent=[], paragraphs=[])
    prompt = build_prompt(data)
    assert "\n- " not in prompt.split("<<<선택 문맥 시작>>>")[1].split("<<<선택 문맥 끝>>>")[0]
    assert len(prompt) <= max_prompt_chars()


def test_marker_replacement_keeps_codepoint_length():
    text = "<<<a>>>b<<<"
    assert _data(text) == "‹‹‹a›››b‹‹‹"
    assert len(_data(text)) == len(text)


# --- Mermaid 허용 문법 (spec 5.3) ---


@pytest.mark.parametrize(
    "source",
    [
        "flowchart LR\n  A[요청] --> B[응답]",
        "graph TD\n  A --> B\n  B --> C",
        "flowchart TB;\n  A((원)) -->|예| B{결정}",
        'flowchart LR\n  A["따옴표 (괄호)"] --> B([스타디움])',
        "flowchart LR\n  A -.-> B\n  B ==> C\n  C --- D",
        "flowchart LR\r\n  A --> B\r\n",
        "flowchart RL\n  A[요청] --> B[응답];",
        "flowchart LR\n" + "\n".join(f"  N{i} --> N{i + 1}" for i in range(MAX_MERMAID_LINES - 1)),
        'flowchart LR\n  A["세미콜론; 허용"] --> B',
        "flowchart LR\n  A[번호 #9829] --> B",
    ],
    ids=[
        "basic",
        "graph_keyword",
        "shapes_and_edge_label",
        "quoted_label_with_parens",
        "arrow_kinds",
        "crlf",
        "trailing_semicolon",
        "max_lines",
        "quoted_semicolon",
        "hash_without_entity",
    ],
)
def test_mermaid_allowed_accepts(source):
    assert mermaid_allowed(source) is True


@pytest.mark.parametrize(
    "source",
    [
        "flowchart LR",
        "A --> B\nB --> C",
        "sequenceDiagram\n  A->>B: hi",
        'flowchart LR\n  A --> B\n  click A href "https://x"',
        "flowchart LR\n  A --> B\n  click A callback",
        "flowchart LR\n  A --> B\n  style A fill:#f9f",
        "flowchart LR\n  A --> B\n  classDef red fill:#f00",
        "flowchart LR\n  A --> B\n  class A red",
        "flowchart LR\n  A:::red --> B",
        "flowchart LR\n  A --> B\n  linkStyle 0 stroke:#f00",
        "flowchart LR\n  subgraph S\n  A --> B\n  end",
        "flowchart LR\n  %% 주석\n  A --> B",
        "%%{init: {'theme': 'dark'}}%%\nflowchart LR\n  A --> B",
        "flowchart LR\n  A[<b>굵게</b>] --> B",
        'flowchart LR\n  A["<img src=x>"] --> B',
        'flowchart LR\n  A["javascript:alert(1)"] --> B',
        'flowchart LR\n  A["JavaScript:alert(1)"] --> B',
        "flowchart LR\n  A@{ shape: rect } --> B",
        "flowchart LR\n  end --> B",
        "flowchart LR\n  A --> Click",
        "flowchart LR\n  A --> direction",
        "flowchart LR\n  A[a|b] --> B",
        "flowchart LR\n  A[`md`] --> B",
        'flowchart LR\n  A["#quot;인용#quot;"] --> B',
        'flowchart LR\n  A["하트 #9829;"] --> B',
        'flowchart LR\n  A["#QUOT;"] --> B',
        "flowchart LR\n  A[fa:fa-user 사용자] --> B",
        'flowchart LR\n  A["FA:fa-car 차"] --> B',
        "flowchart LR\n" + "\n".join(f"  N{i} --> N{i + 1}" for i in range(MAX_MERMAID_LINES)),
        "flowchart LR\n  A[" + "가" * MAX_MERMAID_CHARS + "] --> B",
    ],
    ids=[
        "header_only",
        "no_header",
        "other_diagram_type",
        "click_href",
        "click_callback",
        "style",
        "classdef",
        "class",
        "class_shorthand",
        "linkstyle",
        "subgraph",
        "comment",
        "init_directive",
        "html_label",
        "html_in_quoted_label",
        "javascript_url",
        "javascript_url_upper",
        "shape_syntax",
        "reserved_end",
        "reserved_click_mixed_case",
        "reserved_direction",
        "pipe_in_label",
        "backtick_label",
        "entity_named",
        "entity_numeric",
        "entity_upper",
        "font_awesome",
        "font_awesome_upper",
        "too_many_lines",
        "too_long",
    ],
)
def test_mermaid_allowed_rejects(source):
    assert mermaid_allowed(source) is False


# --- parse_output (spec 5절) ---

FIGURE = {
    "mermaid": "flowchart LR\n  A[요청] --> B[응답]",
    "caption": "흐름",
    "alt_text": "요청에서 응답으로",
    "source_refs": [2],
    "after_section": 1,
}


def _parse(payload, *, paragraph_count=2, allow_topic_check=True):
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return parse_output(text, paragraph_count, current_topic="운영체제", allow_topic_check=allow_topic_check)


def test_parse_answered_with_figure_and_suggestions():
    parsed = _parse(
        {
            "state": "answered",
            "sections": [{"heading": "핵심", "body": "설명 [1]"}, {"body": "  둘째\r\n줄  "}],
            "figures": [FIGURE, {**FIGURE, "mermaid": 'flowchart LR\n  A --> B\n  click A href "https://x"'}],
            "suggestions": ["다음 질문", "다음 질문", "둘", "셋", "넷"],
        }
    )
    assert parsed.result == {
        "state": "answered",
        "sections": [{"heading": "핵심", "body": "설명 [1]"}, {"body": "둘째\n줄"}],
        "figures": [{"figure_id": "f-1", "kind": "diagram", **FIGURE}],
        "suggestions": ["다음 질문", "둘", "셋"],
    }
    assert parsed.refs == (1, 2)


def test_parse_answered_inside_json_fence_without_figures():
    body = json.dumps({"state": "answered", "sections": [{"body": "설명 [2]"}]}, ensure_ascii=False)
    parsed = _parse(f"```json\n{body}\n```")
    assert parsed.result == {"state": "answered", "sections": [{"body": "설명 [2]"}], "suggestions": []}
    assert parsed.refs == (2,)


def test_parse_partial():
    parsed = _parse(
        {"state": "partial", "sections": [{"body": "일부 설명 [1]"}], "limitation": "나머지는 근거 문단에 없습니다."}
    )
    assert parsed.result == {
        "state": "partial",
        "sections": [{"body": "일부 설명 [1]"}],
        "limitation": "나머지는 근거 문단에 없습니다.",
    }
    assert parsed.refs == (1,)


def test_parse_clarify():
    parsed = _parse({"state": "clarify", "clarify": {"prompt": "어느 뜻인가요?", "options": ["프로세스", "스레드"]}})
    assert parsed.result == {
        "state": "clarify",
        "clarify": {
            "prompt": "어느 뜻인가요?",
            "options": [{"option_id": "o-1", "label": "프로세스"}, {"option_id": "o-2", "label": "스레드"}],
        },
    }
    assert parsed.refs == ()


def test_parse_correction():
    parsed = _parse(
        {
            "state": "correction",
            "sections": [{"body": "바로잡은 설명 [1]"}],
            "corrections": [{"note_excerpt": "노트 문장", "corrected": "고친 내용 [1]", "source_refs": [2, 2]}],
        }
    )
    assert parsed.result == {
        "state": "correction",
        "sections": [{"body": "바로잡은 설명 [1]"}],
        "corrections": [{"note_excerpt": "노트 문장", "corrected": "고친 내용 [1]", "source_refs": [2]}],
        "unresolved": [],
    }
    assert parsed.refs == (1, 2)


def test_parse_topic_check_uses_server_topic():
    parsed = _parse({"state": "topic_check", "sections": [{"body": "무시 [9]"}]})
    assert parsed.result == {"state": "topic_check", "topic_check": {"current_topic": "운영체제"}}
    assert parsed.refs == ()


def test_parse_topic_check_rejected_when_not_allowed():
    with pytest.raises(OutputInvalid) as error:
        _parse({"state": "topic_check"}, allow_topic_check=False)
    assert error.value.reason == "state"


SECTION = [{"body": "설명 [1]"}]


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ("설명만 있는 글", "json"),
        ("[]", "json"),
        ("```json\n{\"state\": \"answered\"}", "json"),
        ({"sections": SECTION}, "state"),
        ({"state": "no_evidence"}, "state"),
        ({"state": "answered", "sections": []}, "sections"),
        ({"state": "answered", "sections": [{"body": "b [1]"}] * (MAX_SECTIONS + 1)}, "sections"),
        ({"state": "answered", "sections": ["설명 [1]"]}, "sections"),
        ({"state": "answered", "sections": [{"heading": "h"}]}, "section_body"),
        ({"state": "answered", "sections": [{"body": "   "}]}, "section_body"),
        ({"state": "answered", "sections": [{"body": "널\x00 [1]"}]}, "section_body"),
        ({"state": "answered", "sections": [{"heading": "h" * 101, "body": "b [1]"}]}, "section_heading"),
        ({"state": "answered", "sections": [{"body": "범위 밖 [3]"}]}, "citation_range"),
        ({"state": "answered", "sections": [{"body": "영 [0]"}]}, "citation_range"),
        ({"state": "answered", "sections": [{"body": "인용 없음"}]}, "no_citation"),
        ({"state": "answered", "sections": [{"body": "코드 안 `a[1]`만"}]}, "no_citation"),
        ({"state": "answered", "sections": SECTION, "suggestions": "질문"}, "suggestions"),
        ({"state": "answered", "sections": SECTION, "suggestions": [1]}, "suggestions"),
        ({"state": "partial", "sections": SECTION}, "limitation"),
        ({"state": "partial", "sections": SECTION, "limitation": "인용 [1]"}, "limitation"),
        ({"state": "clarify", "clarify": "뜻?"}, "clarify"),
        ({"state": "clarify", "clarify": {"prompt": "뜻?", "options": ["하나"]}}, "clarify"),
        ({"state": "clarify", "clarify": {"prompt": "뜻?", "options": ["a", "b", "c", "d", "e"]}}, "clarify"),
        ({"state": "clarify", "clarify": {"prompt": "뜻?", "options": ["같음", "같음"]}}, "clarify"),
        ({"state": "clarify", "clarify": {"options": ["a", "b"]}}, "clarify"),
        ({"state": "correction", "sections": SECTION}, "corrections"),
        (
            {"state": "correction", "sections": SECTION, "corrections": [{"note_excerpt": "n", "corrected": "c [1]"}]},
            "corrections",
        ),
        (
            {
                "state": "correction",
                "sections": SECTION,
                "corrections": [{"note_excerpt": "n", "corrected": "c [1]", "source_refs": [5]}],
            },
            "corrections",
        ),
        (
            {
                "state": "correction",
                "sections": SECTION,
                "corrections": [{"note_excerpt": "n", "corrected": "c [9]", "source_refs": [1]}],
            },
            "citation_range",
        ),
        (
            {
                "state": "correction",
                "sections": SECTION,
                "corrections": [{"note_excerpt": "n", "corrected": "c [1]", "source_refs": [1]}],
                "unresolved": "문장",
            },
            "unresolved",
        ),
    ],
    ids=[
        "not_json",
        "json_array",
        "unclosed_fence",
        "missing_state",
        "unknown_state",
        "empty_sections",
        "too_many_sections",
        "section_not_object",
        "missing_body",
        "blank_body",
        "nul_in_body",
        "heading_too_long",
        "citation_above_range",
        "citation_zero",
        "no_citation",
        "citation_only_in_code",
        "suggestions_not_list",
        "suggestion_not_text",
        "partial_without_limitation",
        "partial_limitation_cites",
        "clarify_not_object",
        "clarify_one_option",
        "clarify_five_options",
        "clarify_duplicate_options",
        "clarify_without_prompt",
        "correction_without_corrections",
        "correction_without_source_refs",
        "correction_source_ref_out_of_range",
        "correction_citation_out_of_range",
        "unresolved_not_list",
    ],
)
def test_parse_output_rejects(payload, reason):
    with pytest.raises(OutputInvalid) as error:
        _parse(payload)
    assert error.value.reason == reason


# --- 노트 근거만 있을 때 교정 금지 (MEG-237, spec 0절 T4 전 임시 예외) ---


def _paragraph(kind: str) -> Paragraph:
    return Paragraph(source_kind=kind, source_id="1", revision="1", title="제목", text="본문")


def test_correction_is_allowed_only_when_some_evidence_is_not_a_note():
    assert correction_allowed([_paragraph("note"), _paragraph("note")]) is False
    assert correction_allowed([_paragraph("note"), _paragraph("wiki")]) is True
    assert correction_allowed([]) is False


def test_a_note_only_prompt_drops_the_correction_rule_and_fields():
    base = _worst_case_input("가")
    with_correction = build_prompt(base)
    without = build_prompt(PromptInput(**{**base.__dict__, "allow_correction": False}))
    assert "corrections [" in with_correction and "state를 correction으로 하고" in with_correction
    assert "corrections" not in without and "state를 correction으로 하지 않습니다" in without
    assert len(without) <= max_prompt_chars()


def test_agent_v3_rules_cover_the_l1_failure_modes():
    # MEG-275 4-C: CSA-DEV v1 L1에서 X가 난 동작마다 규칙이 하나씩 있다.
    base = _worst_case_input("가")
    prompt = build_prompt(base)
    note_only = build_prompt(PromptInput(**{**base.__dict__, "allow_correction": False}))
    assert "방법, 절차, 권고, 원인은 덧붙이지 않습니다" in prompt
    assert "인용 번호를 붙이지 않고, 질문의 맥락으로만" in prompt
    assert "근거 문단에서 이 질문의 답을 찾지 못했습니다." in prompt
    assert "직전 질문과 답이 다룬 대상으로 해석합니다" in prompt
    assert "서로 다른 대상을 가리키면" in prompt
    assert "근거 문단이 있어도 답하지 말고 state를 topic_check로" in prompt
    assert "선택한 노트 문장이 근거 문단과 다릅니다" in note_only
    # 주제 확인이 꺼진 턴에는 주제 규칙이 없다.
    assert "topic_check" not in build_prompt(PromptInput(**{**base.__dict__, "allow_topic_check": False}))


def test_agent_v4_rules_cover_the_remaining_l1_failure_modes():
    # MEG-275 5-B: CSA-DEV v2 L1의 남은 X(핵심 누락, "근거에 없다" 오판, 노트 문장 확인, 한 뜻만 다룬 다의어)마다 규칙이 있다.
    base = _worst_case_input("가")
    prompt = build_prompt(base)
    note_only = build_prompt(PromptInput(**{**base.__dict__, "allow_correction": False}))
    assert PROMPT_VERSION == "agent-v4"
    assert "그 내용을 빠뜨리지 말고 답의 중심으로 씁니다" in prompt
    assert "근거 문단에 나온 변경과 특징 가운데 질문과 관계있는 것을 사실대로 전합니다" in prompt
    assert "다른 대상을 다룬 문단의 내용은 답으로 쓰지 않습니다" in prompt
    assert "\"근거에 없다\"거나 \"설명하지 않는다\"고 쓰지 않습니다" in prompt
    # 답하는 문단이 없을 때의 고정 문장(서버가 no_evidence로 바꿈)은 그대로 쓰게 한다. 새 규칙이 이 경로를 막지 않는다.
    assert "질문에 답하는 문단이 하나도 없을 때는 아래 규칙의 고정 문장을 그대로 씁니다" in prompt
    assert prompt.index("고정 문장을 그대로 씁니다") < prompt.index("근거 문단에서 이 질문의 답을 찾지 못했습니다.")
    assert "sections와 limitation이 서로 어긋나지 않게 합니다" in prompt
    assert "근거 문단이 그중 하나만 다루더라도 그 하나로 답을 정하지 말고 state를 clarify로" in prompt
    assert "그 문장과 맞닿은 설명(정의, 차이, 동작)을 찾아" in note_only
    # 교정이 허용된 턴(위키 근거)에는 노트 문장 확인 규칙 대신 교정 규칙이 들어간다.
    assert "그 문장과 맞닿은 설명" not in prompt


def test_parse_correction_becomes_answered_when_not_allowed():
    payload = {
        "state": "correction",
        "sections": [{"body": "설명 [1]"}],
        "corrections": [{"note_excerpt": "노트 문장", "corrected": "고친 내용 [2]", "source_refs": [2]}],
        "figures": [FIGURE],
    }
    parsed = parse_output(json.dumps(payload, ensure_ascii=False), 2, current_topic="t", allow_topic_check=True,
                          allow_correction=False)
    # 교정 항목(과 그 인용)은 버리고 본문만 answered로 받는다. 본문 인용만 출처가 된다.
    assert parsed.result == {"state": "answered", "sections": [{"body": "설명 [1]"}], "suggestions": []}
    assert parsed.refs == (1,)
    # 본문 검증은 그대로다: 인용 없는 본문은 형식 실패다.
    with pytest.raises(OutputInvalid):
        parse_output(json.dumps({**payload, "sections": [{"body": "인용 없음"}]}, ensure_ascii=False), 2,
                     current_topic="t", allow_topic_check=True, allow_correction=False)
    # 다른 상태는 그대로 받는다.
    answered = {"state": "answered", "sections": [{"body": "설명 [1]"}]}
    assert parse_output(json.dumps(answered, ensure_ascii=False), 2, current_topic="t", allow_topic_check=True,
                        allow_correction=False).result["state"] == "answered"
