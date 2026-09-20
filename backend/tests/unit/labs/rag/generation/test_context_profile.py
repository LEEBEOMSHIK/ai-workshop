from dataclasses import replace

import pytest

from ai_workshop.labs.rag.generation.profile import resolve_evidence_budget


def test_context_budget_is_explicit_and_legacy_is_unchanged():
    assert resolve_evidence_budget({}) is None
    budget = resolve_evidence_budget({"context_evidence": {
        "version": 1, "max_groups": 8, "max_units": 32, "max_characters": 12000,
    }, "prompt_ref": "rag-codex-answer-v4"})
    assert budget is not None and budget.max_groups == 8
    assert replace(budget, max_groups=1).max_units == 32


@pytest.mark.parametrize("value", [True, 0, -1, "8"])
def test_bad_context_limits_are_rejected(value):
    with pytest.raises(ValueError):
        resolve_evidence_budget({"context_evidence": {
            "version": 1, "max_groups": value, "max_units": 32, "max_characters": 12000,
        }, "prompt_ref": "rag-codex-answer-v4"})
