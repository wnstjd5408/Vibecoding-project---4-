"""WRAG-DEV 무과금 위키 검색 평가 명령(MEG-251 AC-3·AC-4, 설계 v0.3 6·7절).

합성 사례(tests/fixtures/wrag_dev)로 E1~E6이 돌고 결과에 검색 identity가 묶이는지, 형식 오류·비공개 자료 규칙을 본다.
소켓을 막는다. 모델·DB·네트워크를 부르지 않는다.
"""

import copy
import json
import logging
import socket
from pathlib import Path

import pytest

from evals import wiki_retrieval as wr
from evals.schema import DatasetError

FIXTURES = Path(__file__).parent / "fixtures" / "wrag_dev"
SNAPSHOT = FIXTURES / "snapshot.json"
CASES = FIXTURES / "cases.jsonl"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


@pytest.fixture
def snapshot():
    return wr.load_snapshot(SNAPSHOT)


@pytest.fixture
def cases():
    return [case for _, case in wr.load_cases(CASES)]


def numbered(cases):
    return list(enumerate(cases, 1))


def write_cases(path: Path, cases) -> Path:
    path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8")
    return path


# --- 합성 WRAG-DEV ---


def test_the_repository_fixture_is_synthetic_and_valid(snapshot, cases):
    assert snapshot["provenance"] == "synthetic" and {case["provenance"] for case in cases} == {"synthetic"}
    assert wr.validate(snapshot, numbered(cases)) == []
    assert {case["expected_route"] for case in cases} == set(wr.ROUTES)


def test_the_run_measures_e1_to_e6_and_binds_the_retrieval_identity(snapshot, cases):
    result = wr.evaluate(snapshot, cases, k=5)
    assert (result["status"], result["verdict"], result["model_calls"]) == ("MEASURED", "NOT_JUDGED", 0)
    identity = result["identity"]
    assert identity["retriever_version"] == "wiki-keyword-v1"
    assert identity["chunk_rule_version"] == "note-chunks-v1" and identity["max_chunk_chars"] == 1500
    assert identity["k"] == 5
    assert identity["snapshot"]["term_rows"] == 7 and identity["snapshot"]["entries"] == 4
    assert identity["snapshot"]["skipped_rows"] == 3 and len(identity["snapshot"]["snapshot_sha256"]) == 64
    assert identity["dataset"]["cases"] == len(cases) and len(identity["dataset"]["dataset_sha256"]) == 64
    metrics = result["metrics"]
    assert set(metrics) == {"E1_route", "E2_page_link", "E3_recall_at_5", "E3_gold_paragraphs_at_5",
                            "E4_required_conditions", "E5_no_evidence", "E6_leaks"}
    # 합성 셋에서 관측한 값이다. 품질 목표 달성의 근거가 아니다(W8).
    assert metrics["E1_route"] == {"numerator": 12, "denominator": 12, "rate": 1.0}
    assert metrics["E2_page_link"]["denominator"] == 4 and metrics["E3_recall_at_5"]["denominator"] == 6
    assert metrics["E4_required_conditions"]["denominator"] == 2 and metrics["E5_no_evidence"]["denominator"] == 2
    assert metrics["E6_leaks"] == {"output": 0, "log": 0, "cases": 8}


def test_identity_changes_with_the_snapshot_and_k(snapshot, cases):
    base = wr.evaluate(snapshot, cases)["identity"]
    changed = copy.deepcopy(snapshot)
    changed["terms"][0]["glossary_revision"] += 1
    assert wr.evaluate(changed, cases)["identity"]["snapshot"]["snapshot_sha256"] != base["snapshot"]["snapshot_sha256"]
    smaller = wr.evaluate(snapshot, cases, k=1)
    assert smaller["identity"]["k"] == 1 and "E3_recall_at_1" in smaller["metrics"]
    with pytest.raises(DatasetError):
        wr.evaluate(snapshot, cases, k=6)


def test_a_retrieval_miss_is_measured_not_hidden(snapshot, cases):
    # 사전에 없는 말만 묻는 사례를 정답이 있는 사례로 바꾸면 E3이 떨어지고 E1도 어긋난다.
    case = next(c for c in cases if c["case_id"] == "WRAG-DEV-001")
    case["text"] = "양자 컴퓨터의 큐비트"
    metrics = wr.evaluate(snapshot, cases)["metrics"]
    assert metrics["E3_recall_at_5"]["numerator"] == 5 and metrics["E1_route"]["numerator"] == 11


def test_the_result_has_ids_and_hashes_but_no_question_or_dictionary_text(snapshot, cases):
    text = json.dumps(wr.evaluate(snapshot, cases), ensure_ascii=False)
    for case in cases:
        if case["action"] == "ask":
            assert case["text"] not in text
    for row in snapshot["terms"]:
        entry = row["glossary_entries"]
        if entry:
            for line in entry["body_markdown"].split("\n"):
                if line and not line.startswith("#"):
                    assert line not in text


# --- E6 누출 판정 ---


def test_a_leak_into_the_log_is_counted(snapshot, cases, monkeypatch):
    real = wr.WikiRetriever.retrieve

    def leaky(self, user, question, context):
        logging.getLogger("app.agent").info("question=%s", question)
        return real(self, user, question, context)

    monkeypatch.setattr(wr.WikiRetriever, "retrieve", leaky)
    leaks = wr.evaluate(snapshot, cases)["metrics"]["E6_leaks"]
    # 질문 8개가 모두 로그에 나온다. WRAG-DEV-006은 질문에 금지 문자열도 들어 있어 하나 더 센다.
    assert leaks["log"] == 9 and leaks["output"] == 0


def test_a_forbidden_entry_reaching_the_output_is_counted(snapshot, cases):
    leaked = copy.deepcopy(snapshot)
    # 어긋난 행(source ai)을 사전 항목처럼 바꾸면 금지 자료가 결과에 나온다.
    leaked["terms"][5]["source"] = "glossary"
    assert wr.evaluate(leaked, cases)["metrics"]["E6_leaks"]["output"] >= 1


# --- 형식 검사 ---


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda c: c.pop("gold"), "missing_field"),
        (lambda c: c.update(extra=1), "unknown_field"),
        (lambda c: c.update(expected_route="P7"), "route_not_evaluable"),
        (lambda c: c.update(expected_route="P2"), "route_not_evaluable"),
        (lambda c: c.update(review_status="approved"), "approved_without_reviewer"),
        (lambda c: c.update(expected_route="P6"), "route_gold_mismatch"),
        (lambda c: c.update(origin="wiki"), "wiki_ref_origin_mismatch"),
        (lambda c: c.update(gold=[{**c["gold"][0], "text_sha256": "0" * 64}]), "gold_not_in_snapshot"),
        (lambda c: c.update(required_conditions=["사전에 없는 조건 문장"]), "condition_not_in_gold"),
        (lambda c: c.update(text="가" * 1001), "question_too_long"),
        (lambda c: c.update(role="anonymous"), "invalid_role"),
    ],
)
def test_invalid_cases_report_only_line_and_code(snapshot, cases, change, code):
    change(cases[0])
    assert wr.validate(snapshot, numbered(cases)) == [f"line 1: {code}"]


def test_wiki_ref_and_page_ids_must_exist_in_the_snapshot(snapshot, cases):
    wiki = next(c for c in cases if c["origin"] == "wiki")
    wiki["wiki_ref"] = "glossary:105"  # 지운 항목
    opened = next(c for c in cases if c["expected_route"] == "P1")
    opened["expected_term_id"] = 107  # terms 행만 있는 항목
    errors = wr.validate(snapshot, numbered(cases))
    assert sorted(e.split(": ")[1] for e in errors) == ["term_not_in_snapshot", "wiki_ref_not_in_snapshot"]


def test_duplicate_case_ids_and_an_empty_set_fail(snapshot, cases):
    assert wr.validate(snapshot, []) == ["cases: empty"]
    assert wr.validate(snapshot, numbered([cases[0], cases[0]])) == ["line 2: duplicate_case_id"]


def test_snapshot_shape_is_checked(tmp_path):
    bad = tmp_path / "snapshot.json"
    bad.write_text(json.dumps({"format": "wrag-snapshot-v1", "provenance": "synthetic", "terms": [{"id": 1}, {"id": 1}]}),
                   encoding="utf-8")
    with pytest.raises(DatasetError, match="duplicate_term_id"):
        wr.load_snapshot(bad)
    bad.write_text('{"format": "x", "format": "y"}', encoding="utf-8")
    with pytest.raises(DatasetError, match="duplicate_key"):
        wr.load_snapshot(bad)


# --- 명령과 비공개 자료 규칙 ---


def test_the_command_validates_and_writes_a_new_private_result(tmp_path, capsys):
    assert wr.main(["validate", "--snapshot", str(SNAPSHOT), "--cases", str(CASES)]) == 0
    output = tmp_path / "result.json"
    assert wr.main(["run", "--snapshot", str(SNAPSHOT), "--cases", str(CASES), "--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["format"] == "wrag-retrieval-eval-v1" and result["identity"]["k"] == 5
    # 이전 결과를 덮어쓰지 않는다.
    assert wr.main(["run", "--snapshot", str(SNAPSHOT), "--cases", str(CASES), "--output", str(output)]) == 1
    assert "output_exists" in capsys.readouterr().err


def test_the_output_must_be_outside_git():
    inside = Path(__file__).resolve().parent / "wrag-result.json"
    assert wr.main(["run", "--snapshot", str(SNAPSHOT), "--cases", str(CASES), "--output", str(inside)]) == 1
    assert not inside.exists()


def test_curated_cases_inside_git_are_refused(tmp_path, cases, capsys):
    cases[0]["provenance"] = "curated"
    inside = Path(__file__).resolve().parent / "fixtures" / "wrag_dev" / "curated-check.jsonl"
    try:
        write_cases(inside, cases)
        assert wr.main(["validate", "--snapshot", str(SNAPSHOT), "--cases", str(inside)]) == 1
        assert "curated_inside_git" in capsys.readouterr().err
    finally:
        inside.unlink(missing_ok=True)
    outside = write_cases(tmp_path / "cases.jsonl", cases)
    assert wr.main(["validate", "--snapshot", str(SNAPSHOT), "--cases", str(outside)]) == 0


def test_invalid_k_is_an_argument_error():
    with pytest.raises(SystemExit) as raised:
        wr.main(["run", "--snapshot", str(SNAPSHOT), "--cases", str(CASES), "--output", "x.json", "--k", "0"])
    assert raised.value.code == 2


def test_errors_print_no_case_text(tmp_path, cases, capsys):
    cases[0]["expected_route"] = "P9"
    path = write_cases(tmp_path / "cases.jsonl", cases)
    assert wr.main(["validate", "--snapshot", str(SNAPSHOT), "--cases", str(path)]) == 1
    err = capsys.readouterr().err
    assert err.strip() == "line 1: route_not_evaluable" and cases[0]["text"] not in err
