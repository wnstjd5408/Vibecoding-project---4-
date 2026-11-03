"""Read-only validation of the proposed policy or a GitHub ruleset GET response.

No network requests or writes. Exit 0 means configuration matches, never that
GitHub enforced it in a real push/merge. Missing fields fail closed.
"""

import argparse
import json
from pathlib import Path
import sys


POLICY = Path(__file__).resolve().parents[1] / ".github/rulesets/staging-protection.json"


def validate(data: dict, *, actual: bool = False) -> list[str]:
    errors = []

    def expect(value, expected, name):
        # JSON booleans must not be accepted as integers (True == 1 in Python).
        if type(value) is not type(expected) or value != expected:
            errors.append(f"{name}: missing or differs from approved proposal")

    if not isinstance(data, dict):
        return ["ruleset must be a JSON object"]
    for key, value in {
        "name": "staging-protection", "target": "branch", "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["refs/heads/staging"], "exclude": []}},
    }.items():
        expect(data.get(key), value, key)
    if actual:
        expect(data.get("current_user_can_bypass"), "never", "current_user_can_bypass")
    rules = data.get("rules")
    if not isinstance(rules, list) or any(not isinstance(r, dict) for r in rules):
        return errors + ["rules must be an array of objects"]
    types = [r.get("type") for r in rules]
    expected_types = {"deletion", "non_fast_forward", "pull_request", "required_status_checks"}
    if len(types) != 4 or any(not isinstance(t, str) for t in types) or set(types) != expected_types:
        return errors + ["rules: missing, duplicate or unexpected rule type"]
    by_type = {r["type"]: r for r in rules}
    expected_parameters = {
        "pull_request": {
            "required_approving_review_count": 1,
            "dismiss_stale_reviews_on_push": True,
            "require_code_owner_review": True,
            "require_last_push_approval": False,
            "required_review_thread_resolution": False,
            "allowed_merge_methods": ["squash"],
        },
        "required_status_checks": {
            "strict_required_status_checks_policy": True,
            "do_not_enforce_on_create": False,
        },
    }
    for rule, params in expected_parameters.items():
        actual_params = by_type[rule].get("parameters")
        if not isinstance(actual_params, dict):
            errors.append(f"{rule}: missing parameters")
            continue
        for key, value in params.items():
            expect(actual_params.get(key), value, f"{rule}.{key}")
    status = by_type["required_status_checks"].get("parameters")
    checks = status.get("required_status_checks") if isinstance(status, dict) else None
    wanted = {"Check PR metadata", "Product CI"}
    if not isinstance(checks, list) or len(checks) != 2 or any(not isinstance(c, dict) for c in checks):
        errors.append("required_status_checks: expected exactly two checks")
    else:
        contexts = [c.get("context") for c in checks]
        if any(not isinstance(c, str) for c in contexts) or set(contexts) != wanted:
            errors.append("required_status_checks: incorrect check names")
        for check in checks:
            expect(check.get("integration_id"), 15368, "required_status_checks.integration_id")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=POLICY)
    parser.add_argument("--actual", action="store_true", help="Require GET response bypass evidence too")
    args = parser.parse_args()
    try:
        data = json.loads(args.path.read_text(encoding="utf-8-sig"))
        errors = validate(data, actual=args.actual)
    except (OSError, ValueError) as exc:
        print(f"FAIL: cannot read ruleset ({type(exc).__name__})", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    kind = "Snapshot configuration" if args.actual else "Proposed configuration (not applied)"
    print(f"PASS: {kind}. Actual push/merge enforcement is NOT verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
