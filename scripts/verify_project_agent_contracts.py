#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.project_agents.contracts import validate_repository


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate project development agent contracts.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="validate role contracts")
    validate_parser.add_argument("--root", type=Path, required=True, help="repository root")
    arguments = parser.parse_args()

    if arguments.command == "validate":
        issues = validate_repository(arguments.root)
        for issue in issues:
            print(f"{issue.path}: {issue.code}: {issue.message}")
        return 1 if issues else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
