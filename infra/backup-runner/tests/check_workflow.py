"""Offline checks: parse deployment template and exercise lifecycle failures with fake AWS."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.load((ROOT / "templates/db-backup.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
BASH = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")


class WorkflowSafety(unittest.TestCase):
    def test_trusted_triggers_only(self):
        self.assertEqual(set(WORKFLOW["on"]), {"schedule", "workflow_dispatch"})
        self.assertEqual(WORKFLOW["concurrency"]["cancel-in-progress"], "false")
        for job in ("start", "stop"):
            guard = WORKFLOW["jobs"][job]["if"]
            self.assertIn("github.event.repository.private == true", guard)
            self.assertIn("github.ref == 'refs/heads/main'", guard)

    def test_backup_pin_and_cleanup(self):
        backup = WORKFLOW["jobs"]["backup"]
        self.assertEqual(backup["needs"], "start")
        self.assertIn("backup-fixed-ip", backup["runs-on"])
        checkout = backup["steps"][0]["with"]
        self.assertEqual(checkout["ref"], "${{ vars.SOURCE_COMMIT }}")
        self.assertEqual(checkout["persist-credentials"], "false")
        self.assertEqual(backup["steps"][-1]["if"], "always()")
        self.assertIn("always()", WORKFLOW["jobs"]["stop"]["if"])
        self.assertEqual(WORKFLOW["jobs"]["stop"]["needs"], ["start", "backup"])
        for job in WORKFLOW["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], r"@[a-f0-9]{40}$")

    def execute_lifecycle(self, job, fail_at="", instance="i-0123456789abcdef0"):
        script = WORKFLOW["jobs"][job]["steps"][-1]["run"]
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.txt"
            # No actual AWS executable can run: the shell function replaces it.
            fake = '''aws() {
  printf '%s\\n' "$*" >> "$TRACE_FILE"
  if [[ "$*" == "$FAIL_AT" ]]; then return 1; fi
  return 0
}
'''
            result = subprocess.run(
                [BASH, "-c", fake + script], capture_output=True, text=True,
                env={**os.environ, "TRACE_FILE": trace.as_posix(), "FAIL_AT": fail_at, "INSTANCE_ID": instance},
                timeout=10,
            )
            return result.returncode, trace.read_text().splitlines() if trace.exists() else []

    def test_start_order(self):
        code, trace = self.execute_lifecycle("start")
        self.assertEqual(code, 0)
        self.assertEqual([line.split()[1] for line in trace], ["wait", "start-instances", "wait"])
        self.assertIn("instance-stopped", trace[0])
        self.assertIn("instance-status-ok", trace[-1])

    def test_failed_wait_never_starts_instance(self):
        code, trace = self.execute_lifecycle("start", "ec2 wait instance-stopped --instance-ids i-0123456789abcdef0")
        self.assertNotEqual(code, 0)
        self.assertEqual(len(trace), 1)

    def test_stop_waits_for_actual_stop(self):
        code, trace = self.execute_lifecycle("stop")
        self.assertEqual(code, 0)
        self.assertIn("stop-instances", trace[0])
        self.assertIn("instance-stopped", trace[-1])

    def test_invalid_instance_does_not_call_aws(self):
        for job in ("start", "stop"):
            code, trace = self.execute_lifecycle(job, instance="invalid")
            self.assertNotEqual(code, 0)
            self.assertEqual(trace, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
