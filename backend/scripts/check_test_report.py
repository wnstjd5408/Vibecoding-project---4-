"""Fail closed on missing, empty, skipped or unsuccessful required JUnit tests."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def check_report(path: Path) -> str:
    root = ET.parse(path).getroot()
    if root.tag not in {"testsuites", "testsuite"}:
        raise ValueError("expected a JUnit testsuite or testsuites root")
    cases = list(root.iter("testcase"))
    counts = {tag: len(list(root.iter(tag))) for tag in ("skipped", "failure", "error")}
    if not cases or any(counts.values()):
        raise ValueError(f"required tests: collected={len(cases)}, {counts}")
    return f"required tests: passed={len(cases)}, skipped=0, failures=0, errors=0"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_test_report.py REPORT.xml", file=sys.stderr)
        return 1
    try:
        print(check_report(Path(sys.argv[1])))
    except (OSError, ET.ParseError, ValueError) as exc:
        print(f"required test report rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
