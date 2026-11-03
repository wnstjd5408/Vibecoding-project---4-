import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from check_staging_ruleset import POLICY, validate


class RulesetTest(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads(POLICY.read_text(encoding="utf-8"))

    def actual_snapshot(self):
        snapshot = copy.deepcopy(self.policy)
        snapshot.update(id=42, source_type="Repository",
                        source="wnstjd5408/Vibecoding-project---4-",
                        current_user_can_bypass="never")
        return snapshot

    def test_actual_rejects_wrong_or_unknown_repository(self):
        for key, value in [("source", "someone/temporary-test-repo"),
                           ("source", None), ("source_type", "Organization"),
                           ("source_type", None)]:
            with self.subTest(key=key, value=value):
                snapshot = self.actual_snapshot()
                snapshot[key] = value
                self.assertTrue(validate(snapshot, actual=True))

    def test_actual_requires_positive_integer_ruleset_id(self):
        for value in [None, True, 0, -1, "42", 42.0]:
            with self.subTest(value=value):
                snapshot = self.actual_snapshot()
                snapshot["id"] = value
                self.assertTrue(validate(snapshot, actual=True))

    def test_actual_rejects_proposal_with_only_bypass_evidence(self):
        self.policy["current_user_can_bypass"] = "never"
        self.assertTrue(validate(self.policy, actual=True))

    def test_proposal_is_not_actual_evidence(self):
        self.assertEqual(validate(self.policy), [])
        self.assertTrue(validate(self.policy, actual=True))

    def test_actual_requires_visible_bypass_list_and_never(self):
        self.policy = self.actual_snapshot()
        self.assertEqual(validate(self.policy, actual=True), [])
        del self.policy["bypass_actors"]
        self.assertTrue(validate(self.policy, actual=True))

    def test_wrong_scope_inactive_and_bypass_are_rejected(self):
        mutations = [
            ("enforcement", "disabled"), ("enforcement", "evaluate"),
            ("target", "tag"), ("bypass_actors", [{"actor_type": "RepositoryRole", "actor_id": 5, "bypass_mode": "always"}]),
            ("conditions", {"ref_name": {"include": ["refs/heads/*"], "exclude": []}}),
            ("conditions", {"ref_name": {"include": ["refs/heads/staging"], "exclude": ["refs/heads/staging"]}}),
        ]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                policy = copy.deepcopy(self.policy)
                policy[key] = value
                self.assertTrue(validate(policy))

    def test_every_required_rule_is_checked(self):
        for index in range(4):
            policy = copy.deepcopy(self.policy)
            policy["rules"].pop(index)
            self.assertTrue(validate(policy))

    def test_duplicate_and_linear_history_are_rejected(self):
        for rule in [self.policy["rules"][0], {"type": "required_linear_history"}]:
            policy = copy.deepcopy(self.policy)
            policy["rules"].append(rule)
            self.assertTrue(validate(policy))

    def test_approval_guards(self):
        for key, value in [("required_approving_review_count", 0), ("required_approving_review_count", True),
                           ("dismiss_stale_reviews_on_push", False), ("require_code_owner_review", False),
                           ("allowed_merge_methods", ["merge", "squash"])]:
            with self.subTest(key=key):
                policy = copy.deepcopy(self.policy)
                policy["rules"][2]["parameters"][key] = value
                self.assertTrue(validate(policy))

    def test_strict_and_creation_guards(self):
        for key, value in [("strict_required_status_checks_policy", False), ("do_not_enforce_on_create", True)]:
            policy = copy.deepcopy(self.policy)
            policy["rules"][3]["parameters"][key] = value
            self.assertTrue(validate(policy))

    def test_check_name_app_and_duplicates(self):
        for key, value in [("context", "Product tests"), ("context", "Check PR metadata"),
                           ("integration_id", None), ("integration_id", 123)]:
            policy = copy.deepcopy(self.policy)
            policy["rules"][3]["parameters"]["required_status_checks"][1][key] = value
            self.assertTrue(validate(policy))

    def test_api_metadata_and_reordering_are_allowed(self):
        self.policy = self.actual_snapshot()
        self.policy.update(created_at="2026-11-03T00:00:00Z")
        self.policy["rules"].reverse()
        self.policy["rules"][0]["parameters"]["required_status_checks"].reverse()
        self.assertEqual(validate(self.policy, actual=True), [])

    def test_malformed_structure_fails(self):
        for data in [None, [], {}, {"rules": [None]}, {"rules": [{"type": []}]}]:
            self.assertTrue(validate(data))

    def test_cli_missing_invalid_and_unknown_snapshot_fail(self):
        script = Path(__file__).with_name("check_staging_ruleset.py")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            for content in [None, "{", "[]", "{}"]:
                if content is not None:
                    path.write_text(content, encoding="utf-8")
                result = subprocess.run([sys.executable, str(script), str(path), "--actual"], capture_output=True)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn(b"Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
