"""Public synthetic regressions, not private model outputs or sealed cases."""
import json
import socket

import pytest

from evals.schema import DatasetError
from evals.wiki_live import _validate_wiki
from evals.wiki_quality import style_warnings


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def output(example="가상 문서 편집에서 마지막 삭제를 취소하려고 최근 기록을 먼저 꺼냅니다.[1]"):
    return {"summary": ["요약", "조건", "제한"],
            "explanation": "**정의**\n합성 정의[1]\n**작동 원리**\n합성 원리[1]\n**활용 예시**\n" + example + "\n**주의사항**\n합성 제한[1]",
            "source_ids": ["1"]}


def test_extra_object_close_is_rejected():
    text = json.dumps(output()).replace(', "source_ids"', '}, "source_ids"')
    with pytest.raises(DatasetError, match="invalid_json"):
        _validate_wiki(text, {"1": "synthetic"})


@pytest.mark.parametrize("kind", ["missing_section", "empty_section", "unknown_citation", "wrong_summary_count"])
def test_structure_regressions_are_rejected(kind):
    obj = output()
    if kind == "missing_section":
        obj["explanation"] = obj["explanation"].replace("**활용 예시**", "다른 제목")
    elif kind == "empty_section":
        obj = output("[1]")
    elif kind == "unknown_citation":
        obj["explanation"] += "[9]"
        obj["source_ids"].append("9")
    else:
        obj["summary"].pop()
    with pytest.raises(DatasetError):
        _validate_wiki(json.dumps(obj), {"1": "synthetic"})


@pytest.mark.parametrize("text,expected", [
    ("구체물은 변환 요청입니다.", ["review_label_in_prose"]),
    ("대기가 끝났습니다. 7초는 설명용 예시입니다.", ["unintroduced_numeric_disclaimer"]),
    ("7초 동안 기다린다고 가정합니다. 7초는 설명용 예시입니다.", []),
    ("편집자가 삭제 기록을 꺼내 복구에 사용합니다.", []),
])
def test_known_style_failure_and_control_pairs(text, expected):
    assert style_warnings(text) == expected


def test_valid_format_does_not_prove_example_quality():
    # Deliberately abstract text passes mechanical checks. Human review must
    # evaluate actor/concrete object/problem/application; do not claim quality O.
    checked = _validate_wiki(json.dumps(output("개념을 적용하여 작업을 처리합니다.[1]")), {"1": "synthetic"})
    assert checked["source_ids"] == ["1"]
    assert style_warnings(checked["explanation"]) == []
