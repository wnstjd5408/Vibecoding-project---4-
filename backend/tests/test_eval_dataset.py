"""Synthetic inputs: catch invalid contracts, leakage and false approval."""

import copy
import json
import subprocess
import sys
from dataclasses import asdict, replace

import pytest

from evals.dataset import freeze_dataset, load_cases, validate_dataset
from evals.schema import Case, DatasetError


def record(index=0, split="dev", bucket="basic", response="answer"):
    source = f"🧠 용어{index}는 합성 시험을 위한 개념이다."
    return dict(
        case_id=f"C{index}", group_id=f"G{index}", source_id=f"S{index}",
        split=split, risk_bucket=bucket, subject="synthetic",
        note_revision=1, source_text=source, start=2, end=4 + len(str(index)),
        term=f"용어{index}", expected_response=response,
        required_concepts=["핵심 정의"], required_conditions=[],
        forbidden_errors=["조건을 뒤집음"], generation_evidence=[],
        grading_evidence=["합성 정답 근거"],
        comprehension_questions=[{"question": "뜻은?", "key_points": ["정의", "문맥"]}],
        author="fixture-author", reviewer="fixture-reviewer", review_status="approved",
        provenance="synthetic",
    )


def full_set():
    rows = [record(i) for i in range(20)]
    for bucket in ("basic", "polysemy", "conditions", "precision"):
        for _ in range(8):
            rows.append(record(len(rows), "final", bucket))
    for bucket in ("insufficient", "incorrect_source", "input_boundary", "injection"):
        for _ in range(2):
            rows.append(record(len(rows), "final", bucket, "qualified"))
    return [Case.from_dict(row) for row in rows]


def write_rows(path, rows):
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")


def test_unicode_offsets_and_complete_distribution():
    assert validate_dataset(full_set(), final=True) == []
    assert Case.from_dict(record()).source_text[2:5] == "용어0"


@pytest.mark.parametrize("field,value", [
    ("start", True), ("note_revision", 0), ("note_revision", "1"),
    ("end", 999), ("start", -1), ("end", 2), ("start", 3),
    ("required_concepts", []), ("required_conditions", [""]),
    ("grading_evidence", []), ("generation_evidence", "secret"),
    ("split", "test"), ("expected_response", "maybe"),
    ("risk_bucket", "unknown"), ("review_status", "unknown"),
    ("reviewer", ""), ("provenance", "unknown"),
    ("comprehension_questions", [{"question": "?", "key_points": []}]),
])
def test_rejects_invalid_fields_without_echoing_values(field, value):
    row = record()
    row[field] = value
    with pytest.raises(DatasetError) as error:
        Case.from_dict(row)
    assert "secret" not in str(error.value)
    assert row["source_text"] not in str(error.value)


def test_missing_and_unknown_fields_are_rejected():
    row = record()
    del row["required_conditions"]
    with pytest.raises(DatasetError):
        Case.from_dict(row)
    row = record()
    row["unexpected-secret"] = "sensitive"
    with pytest.raises(DatasetError) as error:
        Case.from_dict(row)
    assert "unexpected-secret" not in str(error.value)


def test_draft_is_valid_but_cannot_be_frozen():
    cases = full_set()
    cases[0] = replace(cases[0], review_status="draft", reviewer="")
    assert validate_dataset(cases, final=True) == []
    with pytest.raises(DatasetError, match="unreviewed"):
        freeze_dataset(cases, reviewer="human")


@pytest.mark.parametrize("field", ["group_id", "source_id", "source_text"])
def test_cross_split_leakage_even_with_distinct_case_ids(field):
    cases = full_set()
    changes = {field: getattr(cases[0], field)}
    if field == "source_text":
        changes.update(term=cases[0].term, start=cases[0].start, end=cases[0].end)
    cases[20] = replace(cases[20], **changes)
    assert any("cross_split" in e for e in validate_dataset(cases, final=True))


def test_duplicate_ids_and_empty_dataset():
    cases = full_set()
    cases[1] = replace(cases[1], case_id=cases[0].case_id)
    assert any("duplicate_case_id" in e for e in validate_dataset(cases, final=True))
    assert validate_dataset([], final=False)


def test_different_context_windows_of_same_note_revision_are_valid():
    cases = full_set()
    cases[1] = replace(cases[1], source_id=cases[0].source_id)
    assert validate_dataset(cases, final=True) == []


def test_nonempty_draft_reviewer_must_be_utf8():
    row = record()
    row.update(review_status="draft", reviewer="\ud800")
    with pytest.raises(DatasetError):
        Case.from_dict(row)


def test_final_checks_counts_and_bucket_response_consistency():
    cases = full_set()
    assert any("count" in e for e in validate_dataset(cases[:-1], final=True))
    cases[20] = replace(cases[20], risk_bucket="conditions")
    assert any("bucket_count" in e for e in validate_dataset(cases, final=True))
    cases[0] = replace(cases[0], expected_response="abstain")
    assert any("response_bucket" in e for e in validate_dataset(cases, final=False))


def test_load_jsonl_bom_bad_json_duplicate_keys_and_nonobject(tmp_path):
    path = tmp_path / "cases.jsonl"
    write_rows(path, [record()])
    assert len(load_cases(path)) == 1
    path.write_text("\ufeff" + path.read_text(encoding="utf-8"), encoding="utf-8")
    assert len(load_cases(path)) == 1
    for text in ('{"secret": bad}', '{"a":1,"a":2}', '[]', 'null', '{"x":NaN}'):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(DatasetError) as error:
            load_cases(path)
        assert "secret" not in str(error.value)


def test_freeze_hash_stable_for_order_but_sensitive_to_content():
    cases = full_set()
    first = freeze_dataset(cases, reviewer="human")
    second = freeze_dataset(list(reversed(cases)), reviewer="human")
    assert first["dataset_version"] == second["dataset_version"]
    assert first["split_counts"] == {"dev": 20, "final": 40}
    assert len(first["case_hashes"]) == 60
    assert "source_text" not in json.dumps(first)
    changed = copy.deepcopy(cases)
    changed[0] = replace(changed[0], required_conditions=["追加条件"])
    assert freeze_dataset(changed, reviewer="human")["dataset_version"] != first["dataset_version"]
    with pytest.raises(DatasetError):
        freeze_dataset(cases, reviewer=" ")


def cli(*args):
    return subprocess.run([sys.executable, "-m", "evals", *map(str, args)], capture_output=True, text=True)


def test_cli_valid_invalid_and_freeze_no_overwrite(tmp_path):
    path = tmp_path / "cases.jsonl"
    write_rows(path, [asdict(c) for c in full_set()])
    result = cli("validate", "--dataset", path, "--final")
    assert result.returncode == 0, result.stderr
    assert "60" in result.stdout
    dest = tmp_path / "manifest.json"
    result = cli("freeze", "--dataset", path, "--reviewer", "human", "--output", dest)
    assert result.returncode == 0, result.stderr
    old = dest.read_bytes()
    assert cli("freeze", "--dataset", path, "--reviewer", "human", "--output", dest).returncode == 1
    assert dest.read_bytes() == old
    path.write_text('{"private": bad}', encoding="utf-8")
    result = cli("validate", "--dataset", path)
    assert result.returncode == 1
    assert "private" not in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_refuses_manifest_inside_git_repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").write_text("gitdir: external", encoding="utf-8")
    path = tmp_path / "cases.jsonl"
    write_rows(path, [asdict(c) for c in full_set()])
    dest = root / "manifest.json"
    assert cli("freeze", "--dataset", path, "--reviewer", "human", "--output", dest).returncode == 1
    assert not dest.exists()
