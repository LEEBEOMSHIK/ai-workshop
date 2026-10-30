import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.domain import GeneratedClaim
from ai_workshop.labs.rag.generation.numeric_catalogue import build_source_value_catalogue
from ai_workshop.labs.rag.generation.numeric_proof_types import ExpectedNumericContext
from ai_workshop.labs.rag.generation.numeric_validation_repository import (
    SqlAlchemyNumericValidationRepository,
    binding_from_record,
    prepare_receipt,
)
from ai_workshop.shared.errors import AppError

from .numeric_proof_fixtures import numeric_fixture
from .test_numeric_validation import claim, validate
from .test_numeric_validation_repository import values


class Session:
    def __init__(self, receipt, audit, evidence):
        self.receipt, self.audit = receipt, audit
        self.metadata = {item.evidence_id: (
            item.evidence_id, item.element_id, item.chunk_id, item.page, item.char_start,
            item.char_end, item.projection_id, item.asset_version_id, item.document_id,
        ) for item in evidence}
        self.source_queries = []
        self.transform = lambda rows, operand: rows
        self.failure = None

    async def get(self, model, id, **kwargs):
        assert kwargs == {"populate_existing": True}
        return self.receipt

    async def scalar(self, statement):
        if statement.column_descriptions[0]["entity"].__name__ == "GenerationExecutionAuditRecord":
            return self.audit
        self.source_queries.append(statement)
        if self.failure:
            raise self.failure
        return next(iter(self.metadata), None)

    async def execute(self, statement):
        self.source_queries.append(statement)
        if self.failure:
            raise self.failure
        ids = next(v for v in statement.compile().params.values() if isinstance(v, list))
        operand = len(statement.selected_columns) > 1
        rows = [self.metadata[id] if operand else (id,) for id in ids if id in self.metadata]
        return SimpleNamespace(all=lambda: self.transform(rows, operand))


def setup(count=2, proof=False, same_evidence=False, page=1):
    texts = ("0.30% 0.20%",) if same_evidence else ("0.30%", "0.20%")
    fixture = numeric_fixture(texts if proof else ("0.30%",) * count)
    if page is None:
        evidence = tuple(replace(item, page=None) for item in fixture.evidence)
        fixture = replace(fixture, evidence=evidence, catalogue=build_source_value_catalogue(
            evidence, request_id=fixture.catalogue.request_id,
            configuration_version_id=UUID(int=20), profile=fixture.profile,
        ))
    generated = claim(fixture, "result 0.10%p") if proof else GeneratedClaim(
        "0.30%", fixture.catalogue.evidence_ids,
    )
    validated = validate(fixture, generated)
    assert validated.payload is not None
    _, original = values()
    audit = replace(original, status="succeeded", evidence_ids=fixture.catalogue.evidence_ids)
    receipt = prepare_receipt(audit, validated)
    binding = binding_from_record(receipt)
    expected = ExpectedNumericContext(
        audit.actor_id, audit.execution_id, binding.request_id, audit.configuration_version_id,
        audit.generation_profile_id, 3, binding.policy_ref, binding.policy_digest,
        audit.evidence_ids,
    )
    session = Session(receipt, audit, fixture.evidence)
    return session, binding, validated.payload, expected


@pytest.mark.parametrize("count,queries", [(1, 1), (64, 1), (65, 2), (129, 3)])
async def test_evidence_query_count_has_64_bound(count, queries):
    session, binding, payload, expected = setup(count)
    await SqlAlchemyNumericValidationRepository(session).verify_binding(
        binding, payload, expected=expected,
    )
    assert len(session.source_queries) == queries
    assert all("rag_index_builds.status" in str(sql) for sql in session.source_queries)


async def test_proof_uses_fresh_second_phase_and_duplicate_build_rows_are_safe():
    session, binding, payload, expected = setup(proof=True)
    session.transform = lambda rows, operand: rows + rows
    await SqlAlchemyNumericValidationRepository(session).verify_binding(
        binding, payload, expected=expected,
    )
    assert len(session.source_queries) == 2
    assert [len(sql.selected_columns) for sql in session.source_queries] == [1, 9]


@pytest.mark.parametrize("field", [1, 2, 3, 4, 5, 6, 7, 8])
async def test_every_operand_position_is_checked(field):
    session, binding, payload, expected = setup(proof=True)

    def corrupt(rows, operand):
        if not operand:
            return rows
        row = list(rows[0])
        row[field] = UUID(int=9000) if field in (1, 2, 6, 7, 8) else -100
        return [tuple(row), *rows[1:]]

    session.transform = corrupt
    with pytest.raises(AppError):
        await SqlAlchemyNumericValidationRepository(session).verify_binding(
            binding, payload, expected=expected,
        )


async def test_operand_phase_rechecks_source_revocation():
    session, binding, payload, expected = setup(proof=True)
    session.transform = lambda rows, operand: [] if operand else rows
    with pytest.raises(AppError):
        await SqlAlchemyNumericValidationRepository(session).verify_binding(
            binding, payload, expected=expected,
        )


@pytest.mark.parametrize("same_page", [False, True])
async def test_null_page_matches_only_null(same_page):
    session, binding, payload, expected = setup(proof=True, page=None)
    if not same_page:
        session.metadata = {id: (*row[:3], 1, *row[4:]) for id, row in session.metadata.items()}
        with pytest.raises(AppError):
            await SqlAlchemyNumericValidationRepository(session).verify_binding(
                binding, payload, expected=expected,
            )
    else:
        await SqlAlchemyNumericValidationRepository(session).verify_binding(
            binding, payload, expected=expected,
        )


async def test_same_evidence_two_operand_positions_are_both_checked():
    session, binding, payload, expected = setup(proof=True, same_evidence=True)
    operands = payload.claims[0].calculations[0].operands
    assert operands[0].evidence_id == operands[1].evidence_id
    assert operands[0].char_end < operands[1].char_end
    await SqlAlchemyNumericValidationRepository(session).verify_binding(
        binding, payload, expected=expected,
    )
    id = operands[0].evidence_id
    row = session.metadata[id]
    session.metadata[id] = (*row[:5], operands[0].char_end, *row[6:])
    with pytest.raises(AppError):
        await SqlAlchemyNumericValidationRepository(session).verify_binding(
            binding, payload, expected=expected,
        )


@pytest.mark.parametrize("failure", [RuntimeError("synthetic"), asyncio.CancelledError()])
async def test_source_error_and_cancellation_are_not_hidden(failure):
    session, binding, payload, expected = setup()
    session.failure = failure
    with pytest.raises(type(failure)) as caught:
        await SqlAlchemyNumericValidationRepository(session).verify_binding(
            binding, payload, expected=expected,
        )
    assert caught.value is failure
