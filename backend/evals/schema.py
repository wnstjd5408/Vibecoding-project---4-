"""Version 1 golden-set contract; error messages never contain source values."""

import re
from dataclasses import dataclass, fields


ANSWER_BUCKETS = ("basic", "polysemy", "conditions", "precision")
EXCEPTION_BUCKETS = ("insufficient", "incorrect_source", "input_boundary", "injection")


class DatasetError(ValueError):
    """Safe diagnostic, suitable for a terminal without private data."""


def _text(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


@dataclass(frozen=True)
class Case:
    case_id: str
    group_id: str
    source_id: str
    split: str
    risk_bucket: str
    subject: str
    note_revision: int
    source_text: str
    start: int
    end: int
    term: str
    expected_response: str
    required_concepts: list[str]
    required_conditions: list[str]
    forbidden_errors: list[str]
    generation_evidence: list[str]
    grading_evidence: list[str]
    comprehension_questions: list[dict]
    author: str
    reviewer: str
    review_status: str
    provenance: str

    @classmethod
    def from_dict(cls, value: object) -> "Case":
        if not isinstance(value, dict) or set(value) != {f.name for f in fields(cls)}:
            raise DatasetError("schema: missing_or_unknown_fields")
        for name in ("case_id", "group_id", "source_id"):
            item = value[name]
            if not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", item):
                raise DatasetError(f"schema: {name}")
        for name in ("subject", "source_text", "term", "author"):
            if not _text(value[name]):
                raise DatasetError(f"schema: {name}")
        choices = {
            "split": ("dev", "final"),
            "risk_bucket": ANSWER_BUCKETS + EXCEPTION_BUCKETS,
            "expected_response": ("answer", "qualified", "abstain"),
            "review_status": ("draft", "approved"),
            "provenance": ("synthetic", "curated"),
        }
        for name, allowed in choices.items():
            if value[name] not in allowed:
                raise DatasetError(f"schema: {name}")
        for name in ("note_revision", "start", "end"):
            if type(value[name]) is not int:
                raise DatasetError(f"schema: {name}")
        if value["note_revision"] < 1:
            raise DatasetError("schema: note_revision")
        if not 0 <= value["start"] < value["end"] <= len(value["source_text"]):
            raise DatasetError("schema: selection_bounds")
        if value["source_text"][value["start"]:value["end"]] != value["term"]:
            raise DatasetError("schema: selection_mismatch")
        for name in ("required_concepts", "required_conditions", "forbidden_errors", "generation_evidence", "grading_evidence"):
            items = value[name]
            if not isinstance(items, list) or any(not _text(item) for item in items):
                raise DatasetError(f"schema: {name}")
            if len(set(items)) != len(items):
                raise DatasetError(f"schema: duplicate_{name}")
            if name in ("required_concepts", "forbidden_errors", "grading_evidence") and not items:
                raise DatasetError(f"schema: {name}")
        questions = value["comprehension_questions"]
        if not isinstance(questions, list) or not questions:
            raise DatasetError("schema: comprehension_questions")
        for q in questions:
            if not isinstance(q, dict) or set(q) != {"question", "key_points"}:
                raise DatasetError("schema: comprehension_questions")
            if not _text(q["question"]) or not isinstance(q["key_points"], list) or len(q["key_points"]) != 2:
                raise DatasetError("schema: comprehension_questions")
            if any(not _text(point) for point in q["key_points"]):
                raise DatasetError("schema: comprehension_questions")
        if not isinstance(value["reviewer"], str):
            raise DatasetError("schema: reviewer")
        if value["reviewer"] != "" and not _text(value["reviewer"]):
            raise DatasetError("schema: reviewer")
        if value["review_status"] == "approved" and not _text(value["reviewer"]):
            raise DatasetError("schema: reviewer")
        return cls(**value)
