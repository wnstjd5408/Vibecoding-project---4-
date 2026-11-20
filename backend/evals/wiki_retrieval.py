"""WRAG-DEV no-cost wiki retrieval evaluation (MEG-251, wiki RAG design v0.3 sections 5-7).

Runs the app's WikiRetriever (wiki-keyword-v1) over a frozen dictionary snapshot and measures E1-E6
without any model, DB or network call. Targets are not set yet (MEG-163 W8), so every result is
MEASURED / NOT_JUDGED. Errors print only line numbers and fixed codes, never case text.
See WIKI_RETRIEVAL.md for the file formats and metric definitions.
"""

import argparse
import hashlib
import json
import logging
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent_note_search import CONTEXT_WEIGHT, note_chunks
from app.agent_retrieval import Paragraph, RetrievalContext
from app.agent_wiki_search import (
    CHUNK_RULE_VERSION,
    MAX_CHUNK_CHARS,
    MAX_PER_ENTRY,
    MAX_RESULTS,
    MENTION_BONUS,
    RETRIEVAL_VERSION,
    SOURCE_KIND,
    WIKI_REF_BONUS,
    WikiEntry,
    WikiRetriever,
    parse_wiki_ref,
    resolve_term,
    wiki_entries,
    wiki_source_id,
)
from app.auth import SessionUser

from .dataset import _invalid_constant, _no_duplicates
from .runner import private_path
from .schema import DatasetError

CASE_FORMAT = "wrag-dev-v1"
SNAPSHOT_FORMAT = "wrag-snapshot-v1"
RESULT_FORMAT = "wrag-retrieval-eval-v1"
# Routes that can be checked without a model, aliases or web search (design section 2). P2 needs aliases
# (MEG-198), P7 needs the model, P8 is web (out of T4) and P9 needs alias/page links that do not exist yet.
ROUTES = ("P1", "P3", "P4", "P5", "P6")
ACTIONS = ("open", "ask")
ORIGINS = ("none", "note", "wiki")
ROLES = ("member", "operator")
PROVENANCES = ("synthetic", "curated")
REVIEW_STATUSES = ("draft", "approved")
MAX_QUESTION_CHARS = 1000  # E27/E29 question limit (Q4 provisional)
FIELDS = (
    "case_id", "provenance", "author", "reviewer", "review_status", "action", "text", "role", "origin",
    "wiki_ref", "topic_label", "selections", "expected_route", "expected_term_id", "gold",
    "required_conditions", "forbidden_texts", "forbidden_source_ids",
)
_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SPACES = re.compile(r"\s+")
_EVAL_USER_ID = "00000000-0000-4000-8000-0000000000e0"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _normal(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def _strict_json(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_invalid_constant)


def _inside_git(path: Path) -> bool:
    path = path.resolve()
    return any((parent / ".git").exists() for parent in (path, *path.parents))


# --- loading ---


def load_snapshot(path: Path) -> dict[str, Any]:
    try:
        data = _strict_json(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError):
        raise DatasetError("snapshot: unreadable_utf8_file") from None
    except (ValueError, TypeError, RecursionError) as error:
        raise DatasetError(str(error) if isinstance(error, DatasetError) else "snapshot: invalid_json") from None
    if not isinstance(data, dict) or set(data) != {"format", "provenance", "terms"}:
        raise DatasetError("snapshot: invalid_shape")
    if data["format"] != SNAPSHOT_FORMAT:
        raise DatasetError("snapshot: unknown_format")
    if data["provenance"] not in PROVENANCES:
        raise DatasetError("snapshot: invalid_provenance")
    terms = data["terms"]
    if not isinstance(terms, list) or not all(isinstance(row, dict) for row in terms):
        raise DatasetError("snapshot: invalid_terms")
    ids = [row.get("id") for row in terms]
    if len(ids) != len(set(map(repr, ids))):
        raise DatasetError("snapshot: duplicate_term_id")
    return data


def load_cases(path: Path) -> list[tuple[int, dict[str, Any]]]:
    cases = []
    try:
        with path.open(encoding="utf-8-sig") as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    data = _strict_json(line)
                except (ValueError, TypeError, RecursionError) as error:
                    reason = str(error) if isinstance(error, DatasetError) else "invalid_json"
                    raise DatasetError(f"line {number}: {reason}") from None
                cases.append((number, data))
    except (OSError, UnicodeError):
        raise DatasetError("cases: unreadable_utf8_file") from None
    return cases


# --- validation ---


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _texts(value: Any, *, unique: bool = True) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) and item.strip() for item in value)
        and (not unique or len(value) == len(set(value)))
    )


def _case_shape(case: Any) -> str | None:
    """Fixed error code for the first problem in one case's own fields, or None."""
    if not isinstance(case, dict):
        return "not_an_object"
    missing = [name for name in FIELDS if name not in case]
    if missing:
        return "missing_field"
    if set(case) - set(FIELDS):
        return "unknown_field"
    if not isinstance(case["case_id"], str) or not _CASE_ID.fullmatch(case["case_id"]):
        return "invalid_case_id"
    if case["provenance"] not in PROVENANCES:
        return "invalid_provenance"
    if not isinstance(case["author"], str) or not case["author"].strip():
        return "invalid_author"
    if case["review_status"] not in REVIEW_STATUSES or not isinstance(case["reviewer"], str):
        return "invalid_review"
    if case["review_status"] == "approved" and not case["reviewer"].strip():
        return "approved_without_reviewer"
    if case["action"] not in ACTIONS:
        return "invalid_action"
    if not isinstance(case["text"], str) or not case["text"].strip():
        return "invalid_text"
    if case["role"] not in ROLES:
        return "invalid_role"
    if case["origin"] not in ORIGINS:
        return "invalid_origin"
    if case["wiki_ref"] is not None and not isinstance(case["wiki_ref"], str):
        return "invalid_wiki_ref"
    if not isinstance(case["topic_label"], str):
        return "invalid_topic_label"
    selections = case["selections"]
    if not isinstance(selections, list) or not all(
        isinstance(item, dict) and set(item) == {"note_id", "text"} and _is_int(item["note_id"]) and item["note_id"] > 0
        and isinstance(item["text"], str) and item["text"].strip()
        for item in selections
    ):
        return "invalid_selections"
    if case["expected_route"] not in ROUTES:
        return "route_not_evaluable"
    if case["expected_term_id"] is not None and not (_is_int(case["expected_term_id"]) and case["expected_term_id"] > 0):
        return "invalid_expected_term_id"
    gold = case["gold"]
    if not isinstance(gold, list) or not all(
        isinstance(item, dict) and set(item) == {"source_id", "section", "text_sha256"}
        and isinstance(item["source_id"], str) and parse_wiki_ref(item["source_id"]) is not None
        and (item["section"] is None or isinstance(item["section"], str))
        and isinstance(item["text_sha256"], str) and _SHA256.fullmatch(item["text_sha256"])
        for item in gold
    ):
        return "invalid_gold"
    if len({canonical(item) for item in gold}) != len(gold):
        return "duplicate_gold"
    if not _texts(case["required_conditions"]):
        return "invalid_required_conditions"
    if not _texts(case["forbidden_texts"]) or not _texts(case["forbidden_source_ids"]):
        return "invalid_forbidden"
    return _case_rules(case)


def _case_rules(case: dict[str, Any]) -> str | None:
    route, action = case["expected_route"], case["action"]
    if action == "open":
        if route not in ("P1", "P4"):
            return "route_action_mismatch"
        if (route == "P1") != (case["expected_term_id"] is not None):
            return "open_term_mismatch"
        if case["origin"] != "none" or case["wiki_ref"] is not None or case["selections"] or case["topic_label"]:
            return "open_has_context"
        if case["gold"] or case["required_conditions"]:
            return "open_has_evidence"
        return None
    if route not in ("P3", "P5", "P6"):
        return "route_action_mismatch"
    if len(case["text"]) > MAX_QUESTION_CHARS:
        return "question_too_long"
    if case["expected_term_id"] is not None:
        return "ask_has_expected_term"
    if (case["origin"] == "wiki") != (case["wiki_ref"] is not None):
        return "wiki_ref_origin_mismatch"
    if case["wiki_ref"] is not None and parse_wiki_ref(case["wiki_ref"]) is None:
        return "invalid_wiki_ref"
    if route == "P3" and case["origin"] != "wiki":
        return "p3_needs_wiki_origin"
    if route == "P5" and case["origin"] == "wiki":
        return "p5_is_not_wiki_origin"
    if (route == "P6") == bool(case["gold"]):
        return "route_gold_mismatch"
    if route == "P6" and case["required_conditions"]:
        return "no_evidence_has_conditions"
    return None


def _current_paragraphs(entries: list[WikiEntry]) -> dict[tuple[str, str | None, str], str]:
    """(source_id, section, text_sha256) -> text for every paragraph the retriever could return now."""
    out = {}
    for entry in entries:
        for chunk in note_chunks(entry.body):
            out[(wiki_source_id(entry.term_id), chunk.section, sha256(chunk.text))] = chunk.text
    return out


def validate(snapshot: dict[str, Any], cases: list[tuple[int, dict[str, Any]]]) -> list[str]:
    """Fixed-code errors (no case text). Gold, terms and wiki_ref must exist in the snapshot."""
    if not cases:
        return ["cases: empty"]
    entries, _ = wiki_entries(snapshot["terms"])
    known = {entry.term_id for entry in entries}
    paragraphs = _current_paragraphs(entries)
    errors, seen = [], set()
    for number, case in cases:
        code = _case_shape(case)
        if code is None and case["case_id"] in seen:
            code = "duplicate_case_id"
        if code is None:
            code = _snapshot_rules(case, known, paragraphs)
        if code is not None:
            errors.append(f"line {number}: {code}")
            continue
        seen.add(case["case_id"])
    return errors


def _snapshot_rules(case, known, paragraphs) -> str | None:
    if case["expected_term_id"] is not None and case["expected_term_id"] not in known:
        return "term_not_in_snapshot"
    if case["wiki_ref"] is not None and parse_wiki_ref(case["wiki_ref"]) not in known:
        return "wiki_ref_not_in_snapshot"
    gold_texts = []
    for item in case["gold"]:
        text = paragraphs.get((item["source_id"], item["section"], item["text_sha256"]))
        if text is None:
            return "gold_not_in_snapshot"
        gold_texts.append(_normal(text))
    for condition in case["required_conditions"]:
        if not any(_normal(condition) in text for text in gold_texts):
            return "condition_not_in_gold"
    return None


def check_private_inputs(snapshot: dict[str, Any], cases, snapshot_path: Path, cases_path: Path) -> None:
    """Curated (real) material must live outside any git work tree (backend/evals/README.md rule)."""
    if snapshot["provenance"] == "curated" and _inside_git(snapshot_path):
        raise DatasetError("snapshot: curated_inside_git")
    if any(case.get("provenance") == "curated" for _, case in cases if isinstance(case, dict)) and _inside_git(cases_path):
        raise DatasetError("cases: curated_inside_git")


# --- run ---


class _SnapshotSource:
    def __init__(self, rows):
        self.rows = rows

    def list_wiki_entries(self):
        return self.rows


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": numerator, "denominator": denominator,
            "rate": None if denominator == 0 else round(numerator / denominator, 4)}


def _context(case: dict[str, Any]) -> RetrievalContext:
    return RetrievalContext(
        conversation_id=f"wrag-{case['case_id']}",
        origin=case["origin"],
        note_id=case["selections"][0]["note_id"] if case["origin"] == "note" and case["selections"] else None,
        topic_label=case["topic_label"],
        selection_note_ids=tuple(item["note_id"] for item in case["selections"]),
        selection_texts=tuple(item["text"] for item in case["selections"]),
        wiki_ref=case["wiki_ref"],
    )


def _leaks(case: dict[str, Any], paragraphs: list[Paragraph], messages: list[str]) -> dict[str, int]:
    forbidden_texts = [_normal(text) for text in case["forbidden_texts"]]
    forbidden_ids = set(case["forbidden_source_ids"])
    output = 0
    for paragraph in paragraphs:
        text = _normal(paragraph.text)
        output += paragraph.source_kind != SOURCE_KIND
        output += paragraph.source_id in forbidden_ids
        output += sum(forbidden in text for forbidden in forbidden_texts)
    # Logs must carry only stage and counts: no question, selection, paragraph or forbidden text (S10).
    secrets = [_normal(case["text"]), *(_normal(item["text"]) for item in case["selections"]),
               *(_normal(p.text) for p in paragraphs), *forbidden_texts]
    secrets = [secret for secret in secrets if secret]
    log = sum(secret in _normal(message) for message in messages for secret in secrets)
    return {"output": output, "log": log}


def _snapshot_identity(snapshot: dict[str, Any], entries: list[WikiEntry], skipped: int) -> dict[str, Any]:
    chunks = [chunk for entry in entries for chunk in note_chunks(entry.body)]
    return {
        "format": SNAPSHOT_FORMAT,
        "provenance": snapshot["provenance"],
        "term_rows": len(snapshot["terms"]),
        "entries": len(entries),
        "skipped_rows": skipped,
        "paragraphs": len(chunks),
        "snapshot_sha256": sha256(canonical(sorted(snapshot["terms"], key=lambda row: canonical(row.get("id"))))),
        "entries_sha256": sha256(canonical([
            [entry.term_id, entry.key, entry.label, entry.revision, sha256(entry.body)] for entry in entries
        ])),
    }


def _dataset_identity(cases: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(cases, key=lambda case: case["case_id"])
    return {
        "format": CASE_FORMAT,
        "cases": len(cases),
        "dataset_sha256": sha256(canonical(ordered)),
        "provenance": dict(sorted(Counter(case["provenance"] for case in cases).items())),
        "review_status": dict(sorted(Counter(case["review_status"] for case in cases).items())),
    }


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "max": None}
    return {"count": len(values), "mean": round(statistics.fmean(values), 2),
            "median": round(statistics.median(values), 2), "max": max(values)}


def evaluate(snapshot: dict[str, Any], cases: list[dict[str, Any]], k: int = MAX_RESULTS) -> dict[str, Any]:
    """Measure E1-E6 for already validated cases. Returns ids, hashes and counts only (no case or dictionary text)."""
    if not 1 <= k <= MAX_RESULTS:
        raise DatasetError("run: invalid_k")
    entries, skipped = wiki_entries(snapshot["terms"])
    retriever = WikiRetriever(_SnapshotSource(snapshot["terms"]))
    agent_logger = logging.getLogger("app.agent")

    per_case, latencies, counts, chars = [], [], [], []
    e1 = e2 = e3 = e3_gold = e4 = e5 = 0
    e2_n = e3_n = e3_gold_n = e4_n = e5_n = 0
    leaks_output = leaks_log = 0
    for case in cases:
        row: dict[str, Any] = {"case_id": case["case_id"], "action": case["action"],
                               "expected_route": case["expected_route"]}
        if case["action"] == "open":
            resolved = resolve_term(case["text"], entries)
            row["route"] = "P1" if resolved is not None else "P4"
            row["resolved_term_id"] = resolved
            row["e2_match"] = resolved == case["expected_term_id"]
            e2_n += 1
            e2 += row["e2_match"]
        else:
            capture = _Capture()
            previous = agent_logger.level
            agent_logger.addHandler(capture)
            agent_logger.setLevel(logging.DEBUG)
            try:
                started = time.perf_counter()
                found = list(retriever.retrieve(SessionUser(_EVAL_USER_ID, case["role"]), case["text"], _context(case)))
                latencies.append(round((time.perf_counter() - started) * 1000, 3))
            finally:
                agent_logger.removeHandler(capture)
                agent_logger.setLevel(previous)
            top = found[:k]
            top_keys = {(p.source_id, p.section, sha256(p.text)) for p in top}
            row["route"] = "P6" if not found else ("P3" if case["origin"] == "wiki" else "P5")
            row["returned"] = [{"rank": rank, "source_id": p.source_id, "revision": p.revision, "section": p.section,
                                "text_sha256": sha256(p.text), "chars": len(p.text)}
                               for rank, p in enumerate(found, 1)]
            counts.append(len(found))
            chars.append(sum(len(p.text) for p in found))
            if case["gold"]:
                gold_keys = {(g["source_id"], g["section"], g["text_sha256"]) for g in case["gold"]}
                hit_gold = len(gold_keys & top_keys)
                row["e3_hit"] = hit_gold > 0
                row["e3_gold_found"] = hit_gold
                e3_n += 1
                e3 += row["e3_hit"]
                e3_gold_n += len(gold_keys)
                e3_gold += hit_gold
                texts = [_normal(p.text) for p in top]
                kept = sum(any(_normal(condition) in text for text in texts) for condition in case["required_conditions"])
                row["e4_conditions_kept"] = kept
                row["e4_conditions"] = len(case["required_conditions"])
                e4_n += len(case["required_conditions"])
                e4 += kept
            else:
                row["e5_no_evidence"] = not found
                e5_n += 1
                e5 += row["e5_no_evidence"]
            leaks = _leaks(case, found, capture.messages)
            row["e6_leaks"] = leaks
            leaks_output += leaks["output"]
            leaks_log += leaks["log"]
        row["e1_match"] = row["route"] == case["expected_route"]
        e1 += row["e1_match"]
        per_case.append(row)

    ask_cases = sum(case["action"] == "ask" for case in cases)
    return {
        "format": RESULT_FORMAT,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "MEASURED",
        # Targets, holdout and reviewers are decided after measurement (MEG-163 W8, MEG-164). No pass/fail here.
        "verdict": "NOT_JUDGED",
        "model_calls": 0,
        "identity": {
            "dataset": _dataset_identity(cases),
            "snapshot": _snapshot_identity(snapshot, entries, skipped),
            "retriever_version": RETRIEVAL_VERSION,
            "chunk_rule_version": CHUNK_RULE_VERSION,
            "max_chunk_chars": MAX_CHUNK_CHARS,
            "k": k,
            "search_params": {
                "max_results": MAX_RESULTS, "max_per_entry": MAX_PER_ENTRY, "wiki_ref_bonus": WIKI_REF_BONUS,
                "mention_bonus": MENTION_BONUS, "context_weight": CONTEXT_WEIGHT,
            },
        },
        "metrics": {
            "E1_route": _ratio(e1, len(cases)),
            "E2_page_link": _ratio(e2, e2_n),
            f"E3_recall_at_{k}": _ratio(e3, e3_n),
            f"E3_gold_paragraphs_at_{k}": _ratio(e3_gold, e3_gold_n),
            "E4_required_conditions": _ratio(e4, e4_n),
            "E5_no_evidence": _ratio(e5, e5_n),
            "E6_leaks": {"output": leaks_output, "log": leaks_log, "cases": ask_cases},
        },
        "measurements": {
            "paragraphs_returned": _stats(counts),
            "chars_returned": _stats(chars),
            "latency_ms": _stats(latencies),
        },
        "cases": per_case,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WRAG-DEV no-cost wiki retrieval evaluation (no model calls)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "run"):
        sub = commands.add_parser(name)
        sub.add_argument("--snapshot", type=Path, required=True)
        sub.add_argument("--cases", type=Path, required=True)
        if name == "run":
            sub.add_argument("--output", type=Path, required=True)
            sub.add_argument("--k", type=int, default=MAX_RESULTS)
    args = parser.parse_args(argv)
    if args.command == "run" and not 1 <= args.k <= MAX_RESULTS:
        parser.error(f"--k must be between 1 and {MAX_RESULTS}")
    try:
        snapshot = load_snapshot(args.snapshot)
        cases = load_cases(args.cases)
        check_private_inputs(snapshot, cases, args.snapshot, args.cases)
        errors = validate(snapshot, cases)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        if args.command == "validate":
            print(f"OK: {len(cases)} cases; format only, not a quality judgement")
            return 0
        output = private_path(args.output)
        result = evaluate(snapshot, [case for _, case in cases], k=args.k)
        # Never overwrite an earlier result.
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
    except DatasetError as error:
        print(str(error), file=sys.stderr)
        return 1
    except FileExistsError:
        print("run: output_exists", file=sys.stderr)
        return 1
    except OSError:
        print("run: output_unwritable", file=sys.stderr)
        return 1
    print(f"SAVED: {len(cases)} cases measured; model calls: 0; verdict: NOT_JUDGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
