"""퀴즈 응답 구조 검증 (MEG-86, API spec 5.2·5.6)."""

import json

import pytest

from app.ai_ledger import api_error_for
from app.ai_quiz import QuizItemDraft, parse_quiz_items
from app.bedrock import AiCallError

ITEM = {"question": "TCP 3-way handshake의 두 번째 단계는?", "answer": "SYN-ACK", "explanation": "근거", "difficulty": "중"}


def test_accepts_a_list_or_an_items_object_and_drops_extra_keys():
    expected = [QuizItemDraft(ITEM["question"], "SYN-ACK", "근거", "중")]

    assert parse_quiz_items(json.dumps([ITEM], ensure_ascii=False)) == expected
    assert parse_quiz_items(json.dumps({"items": [{**ITEM, "extra": 1}]}, ensure_ascii=False)) == expected


@pytest.mark.parametrize("opening", ["```json", "```JSON", "```", "```jsonc "])
def test_accepts_a_json_code_fence(opening):
    text = opening + "\n" + json.dumps([ITEM], ensure_ascii=False) + "\n```"

    assert len(parse_quiz_items(text)) == 1


def test_trims_whitespace_in_fields():
    [item] = parse_quiz_items(json.dumps([{**ITEM, "answer": "  SYN-ACK \n"}]))

    assert item.answer == "SYN-ACK"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        "{}",
        '{"items": "x"}',
        "[1]",
        json.dumps([{k: v for k, v in ITEM.items() if k != "answer"}]),
        json.dumps([{**ITEM, "question": "  "}]),
        json.dumps([{**ITEM, "explanation": 3}]),
        json.dumps([{**ITEM, "difficulty": "어려움"}]),
        "설명: " + json.dumps([ITEM]),
    ],
)
def test_broken_structures_are_a_502_response_error(text):
    with pytest.raises(AiCallError) as error:
        parse_quiz_items(text)

    assert (error.value.step, error.value.code) == ("response", "InvalidQuizJson")
    assert api_error_for(error.value).code == "ai_unavailable"


def test_expected_count_must_match():
    text = json.dumps([ITEM, ITEM], ensure_ascii=False)

    assert len(parse_quiz_items(text, expected_count=2)) == 2
    with pytest.raises(AiCallError):
        parse_quiz_items(text, expected_count=3)


def test_error_does_not_echo_the_response():
    with pytest.raises(AiCallError) as error:
        parse_quiz_items("비밀 응답 원문")

    assert "비밀" not in str(error.value)
