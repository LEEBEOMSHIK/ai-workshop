from importlib import import_module
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.generation.numeric_restore import verify_numeric_views
from ai_workshop.labs.rag.generation.numeric_validation_repository import (
    SqlAlchemyNumericValidationRepository,
)
from ai_workshop.labs.rag.models.numeric_proof_policy import SOURCE_NUMERIC_PROOF_V1
from ai_workshop.shared.errors import AppError


def batch_type():
    return import_module(
        "ai_workshop.labs.rag.generation.numeric_validation_batch"
    ).NumericValidationBatch


def rows(values):
    return MagicMock(all=lambda: values)


def fixture(count=3, schema=1):
    actor, profile = uuid4(), uuid4()
    ids = [uuid4() for _ in range(count)]
    audits = [(uuid4(), id, actor, uuid4(), profile, [uuid4()], "succeeded", True) for id in ids]
    config = {
        "generation": {"response_schema_version": schema}, "prompt_ref": "rag-codex-answer-v6",
    }
    if schema == 3:
        config["generation"]["numeric_proof_policy_ref"] = SOURCE_NUMERIC_PROOF_V1.ref
    profiles = [(profile, config)]
    session = AsyncMock()
    return actor, ids, audits, profiles, session


async def test_legacy_64_uses_four_scalar_queries_and_no_relationship_or_receipt():
    actor, ids, audits, profiles, session = fixture(64)
    session.execute.side_effect = [rows(audits), rows(profiles), rows(audits), rows(profiles)]
    batch = await batch_type().prepare(session, actor_id=actor, execution_ids=ids)
    for id in ids:
        assert await batch.expected_context_for_execution(actor_id=actor, execution_id=id) is None
    await batch.revalidate()
    assert session.execute.await_count == 4
    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert all("numeric_validations" not in sql for sql in statements)
    assert all("model_bindings" not in sql for sql in statements)
    assert "rag_profiles.config" in statements[1]
    assert "rag_profiles.name" not in statements[1]


async def test_empty_has_no_queries_and_bound_is_enforced():
    session = AsyncMock()
    batch = await batch_type().prepare(session, actor_id=uuid4(), execution_ids=[])
    await batch.revalidate()
    session.execute.assert_not_awaited()
    with pytest.raises(ValueError):
        await batch_type().prepare(
            session, actor_id=uuid4(), execution_ids=[uuid4() for _ in range(65)],
        )


@pytest.mark.parametrize("change", ["audit", "profile", "missing"])
async def test_fresh_authority_changes_are_rejected(change):
    actor, ids, audits, profiles, session = fixture(1)
    changed_audits, changed_profiles = list(audits), list(profiles)
    if change == "audit":
        changed_audits[0] = (*audits[0][:-1], False)
    elif change == "profile":
        changed_profiles = [(profiles[0][0], {"generation": {"response_schema_version": 2}})]
    else:
        changed_audits = []
    session.execute.side_effect = [
        rows(audits), rows(profiles), rows(changed_audits), rows(changed_profiles),
    ]
    batch = await batch_type().prepare(session, actor_id=actor, execution_ids=ids)
    with pytest.raises(AppError):
        await batch.revalidate()


async def test_missing_context_fails_only_when_that_execution_is_verified():
    actor, ids, audits, profiles, session = fixture(2)
    session.execute.side_effect = [rows(audits[:1]), rows(profiles)]
    batch = await batch_type().prepare(session, actor_id=actor, execution_ids=ids)
    assert await batch.expected_context_for_execution(actor_id=actor, execution_id=ids[0]) is None
    with pytest.raises(AppError):
        await batch.expected_context_for_execution(actor_id=actor, execution_id=ids[1])
    with pytest.raises(AppError):
        await batch.expected_context_for_execution(actor_id=uuid4(), execution_id=ids[0])


async def test_duplicate_audit_uses_original_single_context_path(monkeypatch):
    actor, ids, audits, profiles, session = fixture(1)
    duplicate = (uuid4(), *audits[0][1:])
    session.execute.side_effect = [rows([*audits, duplicate]), rows(profiles)]
    original = AsyncMock(return_value=None)
    monkeypatch.setattr(
        SqlAlchemyNumericValidationRepository, "expected_context_for_execution", original,
    )
    batch = await batch_type().prepare(session, actor_id=actor, execution_ids=ids)
    assert await batch.expected_context_for_execution(actor_id=actor, execution_id=ids[0]) is None
    original.assert_awaited_once_with(actor_id=actor, execution_id=ids[0])
    assert session.execute.await_count == 2


async def test_schema3_receipt_is_scoped_and_final_verifier_is_not_overridden():
    actor, ids, audits, profiles, session = fixture(1, 3)
    audit = audits[0]
    receipt = (ids[0], audit[0], uuid4(), audit[3], audit[4], SOURCE_NUMERIC_PROOF_V1.digest,
               uuid4(), 3, SOURCE_NUMERIC_PROOF_V1.ref, "a" * 64, "b" * 64)
    session.execute.side_effect = [rows(audits), rows(profiles), rows([receipt])]
    batch = await batch_type().prepare(session, actor_id=actor, execution_ids=ids)
    expected = await batch.expected_context_for_execution(actor_id=actor, execution_id=ids[0])
    assert expected.execution_id == ids[0] and expected.evidence_ids == tuple(audit[5])
    assert batch_type().verify_binding is SqlAlchemyNumericValidationRepository.verify_binding
    assert ids[0] in session.execute.call_args.args[0].compile().params["execution_id_1"]


async def test_legacy_restore_still_rejects_injected_numeric_fields_without_receipt_query():
    actor, ids, audits, profiles, session = fixture(1)
    session.execute.side_effect = [rows(audits), rows(profiles)]
    batch = await batch_type().prepare(session, actor_id=actor, execution_ids=ids)
    with pytest.raises(AppError):
        await verify_numeric_views(
            batch, actor_id=actor, execution_id=ids[0], status="answered", answer="synthetic",
            claims=[], binding=MagicMock(),
        )
    assert session.execute.await_count == 2


async def test_mutable_projection_value_does_not_change_saved_authority():
    actor, ids, audits, profiles, session = fixture(1)
    session.execute.side_effect = [rows(audits), rows(profiles), rows(audits), rows(profiles)]
    batch = await batch_type().prepare(session, actor_id=actor, execution_ids=ids)
    profiles[0][1]["generation"]["response_schema_version"] = 2
    with pytest.raises(AppError):
        await batch.revalidate()


@pytest.mark.parametrize("receipt_field", [1, 3, 4, 5])
async def test_schema3_mismatched_receipt_context_is_rejected(receipt_field):
    actor, ids, audits, profiles, session = fixture(1, 3)
    audit = audits[0]
    receipt = [ids[0], audit[0], uuid4(), audit[3], audit[4], SOURCE_NUMERIC_PROOF_V1.digest,
               uuid4(), 3, SOURCE_NUMERIC_PROOF_V1.ref, "a" * 64, "b" * 64]
    receipt[receipt_field] = "0" * 64 if receipt_field == 5 else uuid4()
    session.execute.side_effect = [rows(audits), rows(profiles), rows([tuple(receipt)])]
    batch = await batch_type().prepare(session, actor_id=actor, execution_ids=ids)
    with pytest.raises(AppError):
        await batch.expected_context_for_execution(actor_id=actor, execution_id=ids[0])
