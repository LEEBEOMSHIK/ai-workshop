"""Reproducible sequential schedules, separate from any execution mechanism."""

import random

from .contracts import Attempt, Phase, Plan, Settings, Snapshot, Target, digest


def build_plan(snapshot: Snapshot, settings: Settings, targets: tuple[Target, ...]) -> Plan:
    ordered_targets = tuple(sorted(targets, key=lambda target: target.engine))
    cases = [case for case in snapshot.cases if case.allowed_chunk_ids]
    random.Random(settings.seed).shuffle(cases)
    attempts: list[Attempt] = []
    rounds: list[tuple[Phase, int]] = [
        ("first_observed", 0),
        *(("warmup", number) for number in range(settings.warmups)),
        *(("repeated", number) for number in range(settings.repeats)),
    ]
    for round_number, (phase, repeat) in enumerate(rounds):
        for case_number, case in enumerate(cases):
            # Rotate the first engine without running any of the three concurrently.
            offset = (round_number + case_number + settings.seed) % 3
            rotated = (*ordered_targets[offset:], *ordered_targets[:offset])
            for target in rotated:
                attempts.append(
                    Attempt(
                        attempt_id=f"{target.engine}:{case.case_id}:{phase}:{repeat}",
                        engine=target.engine,
                        case_id=case.case_id,
                        phase=phase,
                        repeat=repeat,
                    )
                )
    return Plan(
        snapshot_digest=digest(snapshot),
        settings=settings,
        targets=ordered_targets,
        attempts=tuple(attempts),
    )


def validate_plan(snapshot: Snapshot, plan: Plan) -> None:
    if digest(snapshot) != plan.snapshot_digest:
        raise ValueError("snapshot digest does not match plan")
    expected = build_plan(snapshot, plan.settings, plan.targets)
    if digest(expected) != digest(plan):
        raise ValueError("plan does not match the canonical schedule")
