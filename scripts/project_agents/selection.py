#!/usr/bin/env python3
"""Selection of mandatory project-agent roles from activation signals."""
from __future__ import annotations

from collections.abc import Iterable

from .contracts import ActivationRule


class UnknownActivationSignalError(ValueError):
    """Raised when a requested activation signal has no configured rule."""


def select_required_roles(
    signals: Iterable[str], rules: Iterable[ActivationRule]
) -> tuple[str, ...]:
    """Return the sorted, duplicate-free mandatory role baseline for signals."""
    requested_signals = frozenset(signals)
    rule_list = tuple(rules)
    known_signals = frozenset(rule.signal for rule in rule_list)
    unknown_signals = sorted(requested_signals - known_signals)
    if unknown_signals:
        raise UnknownActivationSignalError(
            f"unknown activation signal(s): {', '.join(unknown_signals)}"
        )
    return tuple(
        sorted(
            {
                role_id
                for rule in rule_list
                if rule.signal in requested_signals
                for role_id in rule.required_roles
            }
        )
    )
