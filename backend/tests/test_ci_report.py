"""Required CI groups must not pass when a runner only emits skipped tests."""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_test_report.py"


@pytest.mark.parametrize("xml,expected", [
    ('<testsuites><testsuite><testcase name="ok"/></testsuite></testsuites>', 0),
    ('<testsuite><testcase name="ok"/></testsuite>', 0),
    ('<testsuites><testsuite tests="0"/></testsuites>', 1),
    ('<testsuite><testcase><skipped/></testcase></testsuite>', 1),
    ('<testsuite><testcase/><testcase><skipped/></testcase></testsuite>', 1),
    ('<testsuite><testcase><failure/></testcase></testsuite>', 1),
    ('<testsuite><testcase><error/></testcase></testsuite>', 1),
    ('<testsuite><error/></testsuite>', 1),
    ('<not-junit><testcase/></not-junit>', 1),
    ('broken xml', 1),
    (None, 1),
])
def test_required_report_exit_code(tmp_path, xml, expected):
    report = tmp_path / "report.xml"
    if xml is not None:
        report.write_text(xml, encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), str(report)], capture_output=True)
    assert result.returncode == expected
