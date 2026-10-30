"""CLI only validates/freezes files; it has no live model execution command."""

import argparse
import json
import sys
from pathlib import Path

from .dataset import freeze_dataset, load_cases, validate_dataset
from .schema import DatasetError


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
    args = parser.parse_args()
    try:
        cases = load_cases(args.dataset)
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


if __name__ == "__main__":
    sys.exit(main())
