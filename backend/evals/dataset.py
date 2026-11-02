"""Parse, validate and fingerprint golden sets without executing their contents."""

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .schema import ANSWER_BUCKETS, EXCEPTION_BUCKETS, Case, DatasetError, _text


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DatasetError("json: duplicate_key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise DatasetError("json: invalid_constant")


def load_cases(path: Path) -> list[Case]:
    cases = []
    try:
        with path.open(encoding="utf-8-sig") as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line, object_pairs_hook=_no_duplicates, parse_constant=_invalid_constant)
                    cases.append(Case.from_dict(data))
                except (ValueError, TypeError, RecursionError) as error:
                    reason = str(error) if isinstance(error, DatasetError) else "invalid_json"
                    raise DatasetError(f"line {number}: {reason}") from None
    except (OSError, UnicodeError):
        raise DatasetError("dataset: unreadable_utf8_file") from None
    return cases


def validate_dataset(cases: list[Case], *, final: bool) -> list[str]:
    """final=True checks the complete 20/40 allocation, not human approval."""
    if not cases:
        return ["dataset: empty"]
    errors = []
    seen_ids = set()
    partitions = {name: defaultdict(set) for name in ("group_id", "source_id", "source_text")}
    for index, case in enumerate(cases, 1):
        try:
            Case.from_dict(asdict(case))
        except (DatasetError, TypeError):
            errors.append(f"row {index}: invalid_schema")
            continue
        if case.case_id in seen_ids:
            errors.append(f"row {index}: duplicate_case_id")
        seen_ids.add(case.case_id)
        for name, values in partitions.items():
            values[getattr(case, name)].add(case.split)
        if (case.risk_bucket in ANSWER_BUCKETS) != (case.expected_response == "answer"):
            errors.append(f"row {index}: response_bucket")
    for name, values in partitions.items():
        if any(len(splits) > 1 for splits in values.values()):
            errors.append(f"dataset: cross_split_{name}")
    if final:
        counts = Counter(c.split for c in cases)
        if counts != {"dev": 20, "final": 40}:
            errors.append("dataset: split_count_expected_20_40")
        buckets = Counter(c.risk_bucket for c in cases if c.split == "final")
        for bucket in ANSWER_BUCKETS + EXCEPTION_BUCKETS:
            expected = 8 if bucket in ANSWER_BUCKETS else 2
            if buckets[bucket] != expected:
                errors.append(f"dataset: bucket_count_{bucket}_expected_{expected}")
    return errors


def _digest(data: object) -> str:
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def freeze_dataset(cases: list[Case], reviewer: str) -> dict:
    errors = validate_dataset(cases, final=True)
    if errors:
        raise DatasetError("freeze: invalid_dataset")
    if not _text(reviewer):
        raise DatasetError("freeze: reviewer_required")
    if any(c.review_status != "approved" for c in cases):
        raise DatasetError("freeze: unreviewed_cases")
    hashes = {c.case_id: _digest(asdict(c)) for c in sorted(cases, key=lambda c: c.case_id)}
    return {
        "schema_version": 1,
        "dataset_version": "sha256:" + _digest(hashes),
        "case_hashes": hashes,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": reviewer,
        "split_counts": dict(Counter(c.split for c in cases)),
        "subjects": sorted({c.subject for c in cases}),
        "provenance_counts": dict(Counter(c.provenance for c in cases)),
        "quality_evaluation": "not_run",
    }
