"""Prepare the current wiki contract's request JSON without calling a model."""
import argparse
import json
from pathlib import Path

from .runner import private_path
from .schema import DatasetError
from .wiki_v044 import VERSION, canonical, digest, request


def prepare(stage, base, policy=None):
    value = request(stage, base, policy)
    return {
        "version": VERSION,
        "stage": stage,
        "request": value,
        "request_hash": digest(value),
        "model_calls": 0,
        "semantic_status": "NOT_EVALUATED",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("evidence", "correction", "generation"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.stage == "generation") != (args.policy is not None):
        parser.error("--policy is required only for generation")
    try:
        output = private_path(args.output)
        base = json.loads(args.input.read_text(encoding="utf-8"))
        policy = json.loads(args.policy.read_text(encoding="utf-8")) if args.policy else None
        result = prepare(args.stage, base, policy)
        # Never overwrite an approval, ledger or previous request.
        with output.open("xb") as handle:
            handle.write(canonical(result).encode("utf-8"))
    except (OSError, ValueError, TypeError, KeyError, DatasetError):
        parser.exit(2, "Request preparation failed; check input contract and private output path.\n")
    print("Prepared one request; model calls: 0; semantic quality: not evaluated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
