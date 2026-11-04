"""Offline JSON CLI: never opens a socket, loads app settings, or calls a model."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from pydantic import TypeAdapter, ValidationError

from .analysis import analyze
from .contracts import Observations, Plan, Settings, Snapshot, Target, digest
from .planning import build_plan, validate_plan
from .requests import build_request

MAX_INPUT_BYTES = 32 * 1024 * 1024


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON keys are not allowed")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError("non-finite JSON constants are not allowed")


def _read(path: Path) -> object:
    with path.open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("input exceeds the 32 MiB offline preparation limit")
    return cast(
        object,
        json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        ),
    )


def _write_new(path: Path, value: object) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    # Exclusive creation: preserve every previously recorded plan/result.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded)


def prepare_bundle(snapshot: Snapshot, plan: Plan) -> dict[str, object]:
    validate_plan(snapshot, plan)
    return {
        "schema_version": 1,
        "mode": "offline_preparation_only",
        "plan_digest": digest(plan),
        "plan": plan.model_dump(mode="json"),
        "requests": [
            build_request(snapshot, case, target, plan.settings)
            for case in snapshot.cases
            for target in plan.targets
        ],
    }


def _load_plan(snapshot: Snapshot, path: Path) -> Plan:
    raw = _read(path)
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "mode",
        "plan_digest",
        "plan",
        "requests",
    }:
        raise ValueError("expected a complete prepare output bundle")
    plan = Plan.model_validate(raw["plan"])
    # Python equality treats True == 1.0. JSON types are part of the sealed
    # executable request, so compare canonical encodings rather than objects.
    expected = prepare_bundle(snapshot, plan)
    if json.dumps(raw, sort_keys=True, allow_nan=False) != json.dumps(
        expected, sort_keys=True, allow_nan=False
    ):
        raise ValueError("prepared bundle or request content has changed")
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="Validate a public synthetic snapshot")
    validate.add_argument("--snapshot", required=True, type=Path)
    prepare = subparsers.add_parser(
        "prepare", help="Write requests and a schedule; execute nothing"
    )
    prepare.add_argument("--snapshot", required=True, type=Path)
    prepare.add_argument("--settings", required=True, type=Path)
    prepare.add_argument("--targets", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    score = subparsers.add_parser(
        "score", help="Analyze imported observations; not execution proof"
    )
    score.add_argument("--snapshot", required=True, type=Path)
    score.add_argument("--plan", required=True, type=Path)
    score.add_argument("--observations", required=True, type=Path)
    score.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        snapshot = Snapshot.model_validate(_read(args.snapshot))
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "status": "valid_public_synthetic_snapshot",
                        "snapshot_digest": digest(snapshot),
                        "chunks": len(snapshot.chunks),
                        "cases": len(snapshot.cases),
                        "dimension": snapshot.profile.dimension,
                    }
                )
            )
        elif args.command == "prepare":
            settings = Settings.model_validate(_read(args.settings))
            targets = TypeAdapter(tuple[Target, ...]).validate_python(_read(args.targets))
            plan = build_plan(snapshot, settings, targets)
            _write_new(args.output, prepare_bundle(snapshot, plan))
            print(
                json.dumps(
                    {
                        "status": "prepared_not_executed",
                        "plan_digest": digest(plan),
                        "scheduled_attempts": len(plan.attempts),
                    }
                )
            )
        else:
            plan = _load_plan(snapshot, args.plan)
            observations = Observations.model_validate(_read(args.observations))
            report = analyze(snapshot, plan, observations)
            _write_new(args.output, report)
            print(
                json.dumps(
                    {
                        "status": "analysis_written",
                        "execution_verified": False,
                        "evidence_kind": observations.evidence_kind,
                    }
                )
            )
    except ValidationError as exc:
        # Never echo raw vectors, unexpected secrets, or private input fields to logs.
        print(f"Invalid comparison input ({exc.error_count()} validation errors).", file=sys.stderr)
        return 2
    except (OSError, ValueError, UnicodeError, RecursionError):
        print(
            "Comparison input/output rejected; validate JSON and use a new output path.",
            file=sys.stderr,
        )
        return 2
    return 0
