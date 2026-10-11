from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from ai_workshop.labs.rag.deployments.domain import ExecutionLocation, ProviderKind
from ai_workshop.labs.rag.generation.audit import (
    GenerationExecutionAudit,
    SqlAlchemyGenerationAuditRepository,
)
from ai_workshop.labs.rag.generation.numeric_proof_serialization import numeric_payload_digest
from ai_workshop.labs.rag.generation.numeric_proof_types import ExpectedNumericContext
from ai_workshop.labs.rag.generation.numeric_validation import validated_numeric_abstention
from ai_workshop.shared.errors import AppError

from .numeric_proof_fixtures import numeric_fixture


def values():
    fixture = numeric_fixture(())
    payload = validated_numeric_abstention(
        catalogue=fixture.catalogue,
        profile=fixture.profile,
        request_id=fixture.catalogue.request_id,
        configuration_version_id=UUID(int=20),
    )
    audit = GenerationExecutionAudit(
        UUID(int=40),
        UUID(int=41),
        UUID(int=20),
        fixture.profile.profile_id,
        UUID(int=42),
        UUID(int=43),
        (),
        ProviderKind.DEVELOPMENT_CODEX_EXEC,
        "synthetic-model",
        ExecutionLocation.EXTERNAL,
        True,
        True,
        None,
        "rag-codex-answer-v6",
        6,
        (),
        None,
        None,
        0,
        None,
        None,
        None,
        None,
        "allowed",
        None,
        UUID(int=44),
        datetime.now(UTC),
        UUID(int=45),
    )
    return payload, audit


class MemorySession:
    def __init__(self):
        self.rows = []
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.scalar = AsyncMock()
        self.get = AsyncMock()

    def add(self, value):
        self.rows.append(value)

    def add_all(self, values):
        self.rows.extend(values)


async def test_audit_and_numeric_receipt_share_transaction_without_internal_commit():
    validated, audit = values()
    session = MemorySession()
    repository = SqlAlchemyGenerationAuditRepository(session)
    binding = await repository.add_validated(audit, validated)
    assert binding.payload_digest == numeric_payload_digest(validated.payload)
    assert {row.__tablename__ for row in session.rows} == {
        "rag_generation_execution_audits",
        "rag_generation_numeric_validations",
    }
    session.commit.assert_not_awaited()
    await repository.commit()
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("mutation", ["failed", "denied", "profile", "configuration", "evidence"])
async def test_failed_or_unbound_result_never_creates_receipt(mutation):
    validated, audit = values()
    changes = {
        "failed": {"status": "failed"},
        "denied": {"policy_allowed": False},
        "profile": {"generation_profile_id": UUID(int=99)},
        "configuration": {"configuration_version_id": UUID(int=99)},
        "evidence": {"evidence_ids": (UUID(int=99),)},
    }
    session = MemorySession()
    with pytest.raises(AppError):
        await SqlAlchemyGenerationAuditRepository(session).add_validated(
            replace(audit, **changes[mutation]), validated
        )
    assert session.rows == []


async def test_commit_failure_rolls_back_without_exposing_driver_error():
    session = MemorySession()
    session.commit.side_effect = RuntimeError("synthetic private driver detail")
    with pytest.raises(AppError) as error:
        await SqlAlchemyGenerationAuditRepository(session).commit()
    assert "driver" not in str(error.value)
    session.rollback.assert_awaited_once()


async def test_cancelled_commit_rolls_back_and_preserves_cancellation():
    from asyncio import CancelledError

    session = MemorySession()
    session.commit.side_effect = CancelledError()
    with pytest.raises(CancelledError):
        await SqlAlchemyGenerationAuditRepository(session).commit()
    session.rollback.assert_awaited_once()


async def test_schema0061_legacy_queries_do_not_require_numeric_table():
    from ai_workshop.labs.rag.generation.numeric_validation_repository import (
        SqlAlchemyNumericValidationRepository,
    )

    session = MemorySession()
    session.scalar.side_effect = [
        SimpleNamespace(
            actor_id=UUID(int=41),
            configuration_version_id=UUID(int=20),
            generation_profile_id=UUID(int=10),
        ),
        SimpleNamespace(config={"generation": {"response_schema_version": 2}}),
    ]
    assert (
        await SqlAlchemyNumericValidationRepository(session).expected_context_for_execution(
            actor_id=UUID(int=41), execution_id=UUID(int=45)
        )
        is None
    )
    assert len(session.scalar.await_args_list) == 2
    assert all(
        "rag_generation_numeric_validations" not in str(call.args[0])
        for call in session.scalar.await_args_list
    )


async def test_authoritative_schema3_context_uses_real_top_level_prompt_contract():
    from ai_workshop.labs.rag.generation.numeric_validation_repository import (
        SqlAlchemyNumericValidationRepository,
    )

    validated, audit = values()
    session = MemorySession()
    binding = await SqlAlchemyGenerationAuditRepository(session).add_validated(audit, validated)
    session.scalar.side_effect = [
        audit,
        SimpleNamespace(
            config={
                "prompt_ref": "rag-codex-answer-v6",
                "generation": {
                    "response_schema_version": 3,
                    "numeric_proof_policy_ref": "source-numeric-proof-v1",
                },
            }
        ),
        session.rows[-1],
    ]
    context = await SqlAlchemyNumericValidationRepository(session).expected_context_for_execution(
        actor_id=audit.actor_id, execution_id=audit.execution_id
    )
    assert (
        context.request_id == binding.request_id and context.policy_digest == binding.policy_digest
    )


@pytest.mark.parametrize(
    "mutation", ["missing", "actor", "execution", "payload", "policy", "profile"]
)
async def test_changed_or_cross_execution_binding_cannot_restore(mutation):
    from ai_workshop.labs.rag.generation.numeric_validation_repository import (
        SqlAlchemyNumericValidationRepository,
    )

    validated, audit = values()
    session = MemorySession()
    binding = await SqlAlchemyGenerationAuditRepository(session).add_validated(audit, validated)
    receipt = session.rows[-1]
    session.get.return_value = None if mutation == "missing" else receipt
    session.scalar.return_value = (
        SimpleNamespace(**{**audit.__dict__}) if hasattr(audit, "__dict__") else audit
    )
    expected = ExpectedNumericContext(
        audit.actor_id,
        audit.execution_id,
        binding.request_id,
        audit.configuration_version_id,
        audit.generation_profile_id,
        3,
        binding.policy_ref,
        binding.policy_digest,
        (),
    )
    if mutation == "actor":
        expected = replace(expected, actor_id=UUID(int=99))
    if mutation == "execution":
        expected = replace(expected, execution_id=UUID(int=99))
    if mutation == "policy":
        binding = replace(binding, policy_digest="0" * 64)
    if mutation == "profile":
        binding = replace(binding, generation_profile_id=UUID(int=99))
    payload = (
        replace(validated.payload, catalogue_digest="0" * 64)
        if mutation == "payload"
        else validated.payload
    )
    with pytest.raises(AppError):
        await SqlAlchemyNumericValidationRepository(session).verify_binding(
            binding, payload, expected=expected
        )


async def test_direct_numeric_claim_is_not_restored_after_source_revocation():
    from ai_workshop.labs.rag.generation.domain import GeneratedClaim, StructuredGeneration
    from ai_workshop.labs.rag.generation.numeric_validation import NumericProofValidator
    from ai_workshop.labs.rag.generation.numeric_validation_repository import (
        SqlAlchemyNumericValidationRepository,
    )

    fixture = numeric_fixture(("0.30%",))
    validated = NumericProofValidator().validate(
        StructuredGeneration(3, (GeneratedClaim("0.30%", fixture.catalogue.evidence_ids),)),
        evidence=fixture.evidence,
        catalogue=fixture.catalogue,
        profile=fixture.profile,
        request_id=fixture.catalogue.request_id,
        configuration_version_id=UUID(int=20),
    )
    _, original = values()
    audit = replace(original, status="succeeded", evidence_ids=fixture.catalogue.evidence_ids)
    session = MemorySession()
    binding = await SqlAlchemyGenerationAuditRepository(session).add_validated(audit, validated)
    session.get.return_value = session.rows[-1]
    session.scalar.side_effect = [audit, None]
    expected = ExpectedNumericContext(
        audit.actor_id,
        audit.execution_id,
        binding.request_id,
        audit.configuration_version_id,
        audit.generation_profile_id,
        3,
        binding.policy_ref,
        binding.policy_digest,
        audit.evidence_ids,
    )
    with pytest.raises(AppError):
        await SqlAlchemyNumericValidationRepository(session).verify_binding(
            binding, validated.payload, expected=expected
        )
