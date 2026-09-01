#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.project_agents.contracts import load_activation_rules, validate_repository
from scripts.project_agents.selection import (
    UnknownActivationSignalError,
    select_required_roles,
)

ACTIVATION_RULES_PATH = Path("docs/project-agents/governance/activation-rules.md")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate project development agent contracts.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="validate role contracts")
    validate_parser.add_argument("--root", type=Path, required=True, help="repository root")
    select_parser = subparsers.add_parser("select", help="select mandatory roles for activation signals")
    select_parser.add_argument("--root", type=Path, required=True, help="repository root")
    select_parser.add_argument(
        "--signal",
        action="append",
        required=True,
        help="activation signal; repeat for each signal",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "validate":
        issues = validate_repository(arguments.root)
        for issue in issues:
            print(f"{issue.path}: {issue.code}: {issue.message}")
        return 1 if issues else 0
    try:
        rules = load_activation_rules(arguments.root / ACTIVATION_RULES_PATH)
        roles = select_required_roles(arguments.signal, rules)
    except UnknownActivationSignalError as error:
        parser.error(str(error))
    for role_id in roles:
        print(role_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
