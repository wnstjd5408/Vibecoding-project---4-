"""CLI only validates/freezes files; it has no live model execution command."""

import argparse
import json
import sys
from pathlib import Path

from .dataset import freeze_dataset, load_cases, validate_dataset
from .schema import DatasetError
from .runner import RunConfig, run
from .runner import private_path
from .scoring import templates, score


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline golden-set data validation")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--dataset", type=Path, required=True)
    validate.add_argument("--final", action="store_true", help="check full 20/40 distribution, not approval")
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--dataset", type=Path, required=True)
    freeze.add_argument("--reviewer", required=True)
    freeze.add_argument("--output", type=Path, required=True)
    execute = commands.add_parser("run")
    execute.add_argument("--dataset", type=Path, required=True)
    execute.add_argument("--manifest", type=Path, required=True)
    execute.add_argument("--config", type=Path, required=True)
    execute.add_argument("--output-dir", type=Path, required=True)
    mode = execute.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--fake", action="store_true")
    for command in ("review-template", "report"):
        sub = commands.add_parser(command)
        sub.add_argument("--dataset", type=Path, required=True)
        sub.add_argument("--state", type=Path, required=True)
        sub.add_argument("--output", type=Path, required=True)
        if command == "report":
            sub.add_argument("--reviews", type=Path, required=True)
            sub.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    try:
        cases = load_cases(args.dataset)
        if args.command in ("review-template", "report"):
            state = json.loads(args.state.read_text(encoding="utf-8"))
            version = freeze_dataset(cases, "verify")["dataset_version"]
            if version != state["identity"]["dataset_version"]:
                raise DatasetError("score: dataset_mismatch")
            result = templates(cases, state) if args.command == "review-template" else score(
                cases, state, json.loads(args.reviews.read_text(encoding="utf-8")), seed=args.seed)
            with private_path(args.output).open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
            print("SAVED: offline human-review artifact")
            return 0
        if args.command == "run":
            result = run(cases, json.loads(args.manifest.read_text(encoding="utf-8")),
                         RunConfig(**json.loads(args.config.read_text(encoding="utf-8"))),
                         args.output_dir, dry_run=args.dry_run)
            print(json.dumps(result if args.dry_run else {
                "mode": "fake", "provider_calls": 0,
                "slots": len(result["slots"]),
                "unknown": sum(x["status"] in ("started", "unknown") for x in result["slots"].values()),
            }))
            return 0
        errors = validate_dataset(cases, final=args.command == "freeze" or args.final)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        if args.command == "freeze":
            dest = args.output.resolve()
            if any((parent / ".git").exists() for parent in (dest.parent, *dest.parents)):
                raise DatasetError("freeze: output_must_be_outside_git")
            manifest = freeze_dataset(cases, args.reviewer)
            with dest.open("x", encoding="utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False, indent=2)
            print(f"FROZEN: {len(cases)} cases; model quality not evaluated")
        else:
            drafts = sum(c.review_status == "draft" for c in cases)
            print(f"VALID: {len(cases)} cases; {drafts} drafts; structural validation only")
        return 0
    except DatasetError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError:
        print("file: inaccessible_or_already_exists", file=sys.stderr)
        return 1
    except (ValueError, TypeError, KeyError):
        print("run: invalid_input_or_state", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
