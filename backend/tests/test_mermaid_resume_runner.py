"""Offline state-machine regression: the PowerShell harness intercepts Docker and uv."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_resume_runner_offline():
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is not installed; run tests/powershell/mermaid_resume.ps1 separately")
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(Path(__file__).parent / "powershell/mermaid_resume.ps1")],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("PASS ") == 10
