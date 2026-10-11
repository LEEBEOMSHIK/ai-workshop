"""Explicit original DB trial only; no server/model/worker or durable migration."""

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_ORIGINAL_NUMERIC_PROOF") != "1",
        reason="Explicit original numeric proof rollback verification is required.",
    ),
]


async def test_numeric_trial_roundtrip_and_gate(monkeypatch):
    from .original_numeric_proof_support import original_trial

    async with original_trial(monkeypatch) as trial:
        await trial.check_roundtrip()
        await trial.check_gate()


async def test_missing_forged_or_cross_bound_receipt_rejected(monkeypatch):
    from .original_numeric_proof_support import original_trial

    async with original_trial(monkeypatch) as trial:
        await trial.reject_mutation("control")
        for mutation in (
            "missing-receipt",
            "missing-envelope",
            "whole-cross-execution",
            "policy",
            "profile",
            "request",
            "payload",
            "origin",
            "span",
            "self-citation",
            "downgrade",
        ):
            await trial.reject_mutation(mutation)


async def test_insufficient_and_legacy_gate_compatibility(monkeypatch):
    from .original_numeric_proof_support import original_trial

    async with original_trial(monkeypatch) as trial:
        await trial.check_insufficient()
        await trial.check_legacy()


async def test_trial_rollback_restores_schema_and_rows(monkeypatch):
    from .original_numeric_proof_support import original_trial

    async with original_trial(monkeypatch) as trial:
        await trial.check_gate()
    # The context manager independently compares all protected rows, gate OID/
    # definition and schema0061 after rollback before this test can succeed.
