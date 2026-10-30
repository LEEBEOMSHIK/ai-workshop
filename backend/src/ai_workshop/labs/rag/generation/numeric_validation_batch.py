"""Bounded, list-only context reads; final numeric/source verification stays live."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.generation.audit_models import GenerationExecutionAuditRecord as Audit
from ai_workshop.labs.rag.generation.numeric_proof_types import ExpectedNumericContext
from ai_workshop.labs.rag.generation.numeric_validation_models import (
    NumericValidationRecord as Receipt,
)
from ai_workshop.labs.rag.generation.numeric_validation_repository import (
    SqlAlchemyNumericValidationRepository,
    invalid,
)
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.labs.rag.models.numeric_proof_policy import SOURCE_NUMERIC_PROOF_V1

CONTEXT_BATCH_SIZE = 64


class _Audit(NamedTuple):
    id: UUID
    execution_id: UUID
    actor_id: UUID
    configuration_version_id: UUID
    generation_profile_id: UUID
    evidence_ids: tuple[UUID, ...]
    status: str
    policy_allowed: bool


class _Receipt(NamedTuple):
    execution_id: UUID
    audit_id: UUID
    request_id: UUID
    configuration_version_id: UUID
    generation_profile_id: UUID
    policy_digest: str
    id: UUID
    schema_version: int
    policy_ref: str
    catalogue_digest: str
    payload_digest: str


@dataclass(frozen=True)
class _Authority:
    audits: dict[UUID, tuple[_Audit, ...]]
    profiles: dict[UUID, object]
    receipts: dict[UUID, tuple[_Receipt, ...]]


def _generation(config: object) -> Mapping[str, object] | None:
    if not isinstance(config, Mapping):
        return None
    generation = config.get("generation", {})
    return generation if isinstance(generation, Mapping) else None


async def _read(
    session: AsyncSession, actor_id: UUID, execution_ids: tuple[UUID, ...]
) -> _Authority:
    if not execution_ids:
        return _Authority({}, {}, {})
    rows = (await session.execute(select(
        Audit.id, Audit.execution_id, Audit.actor_id, Audit.configuration_version_id,
        Audit.generation_profile_id, Audit.evidence_ids, Audit.status, Audit.policy_allowed,
    ).where(
        Audit.execution_id.in_(execution_ids), Audit.actor_id == actor_id,
        Audit.status.in_(("succeeded", "allowed")),
    ))).all()
    audits: dict[UUID, tuple[_Audit, ...]] = {}
    for row in rows:
        audit = _Audit(
            row[0], row[1], row[2], row[3], row[4], tuple(row[5]), row[6], row[7],
        )
        audits[audit.execution_id] = (*audits.get(audit.execution_id, ()), audit)
    # Order is irrelevant for authority comparison, never used to select a duplicate.
    audits = {id: tuple(sorted(items, key=lambda row: row.id.int)) for id, items in audits.items()}
    singles = [items[0] for items in audits.values() if len(items) == 1]
    profile_ids = {
        item.generation_profile_id for items in audits.values() for item in items
    }
    profiles: dict[UUID, object] = {}
    if profile_ids:
        profile_rows = (await session.execute(select(ProfileRecord.id, ProfileRecord.config).where(
            ProfileRecord.id.in_(profile_ids),
        ))).all()
        profiles = {id: deepcopy(config) for id, config in profile_rows}
    numeric = [item for item in singles if (
        (generation := _generation(profiles.get(item.generation_profile_id))) is not None
        and generation.get("response_schema_version", 1) == 3
    )]
    receipts: dict[UUID, tuple[_Receipt, ...]] = {}
    if numeric:
        receipt_rows = (await session.execute(select(
            Receipt.execution_id, Receipt.audit_id, Receipt.request_id,
            Receipt.configuration_version_id, Receipt.generation_profile_id, Receipt.policy_digest,
            Receipt.id, Receipt.schema_version, Receipt.policy_ref, Receipt.catalogue_digest,
            Receipt.payload_digest,
        ).where(
            Receipt.execution_id.in_([item.execution_id for item in numeric]),
            Receipt.audit_id.in_([item.id for item in numeric]),
        ))).all()
        for row in receipt_rows:
            receipt = _Receipt(*row)
            receipts[receipt.execution_id] = (*receipts.get(receipt.execution_id, ()), receipt)
    return _Authority(audits, profiles, receipts)


class NumericValidationBatch(SqlAlchemyNumericValidationRepository):
    """Overrides context lookup only; inherited verify_binding always re-queries SQL."""

    def __init__(
        self, session: AsyncSession, actor_id: UUID, execution_ids: tuple[UUID, ...],
        authority: _Authority,
    ) -> None:
        super().__init__(session)
        self._actor_id = actor_id
        self._execution_ids = execution_ids
        self._authority = authority
        self._fallback: dict[UUID, ExpectedNumericContext | None] = {}

    @classmethod
    async def prepare(
        cls, session: AsyncSession, *, actor_id: UUID, execution_ids: Sequence[UUID]
    ) -> "NumericValidationBatch":
        if len(execution_ids) > CONTEXT_BATCH_SIZE:
            raise ValueError("Numeric context batch exceeds its bound")
        ids = tuple(dict.fromkeys(execution_ids))
        return cls(session, actor_id, ids, await _read(session, actor_id, ids))

    async def expected_context_for_execution(
        self, *, actor_id: UUID, execution_id: UUID
    ) -> ExpectedNumericContext | None:
        if actor_id != self._actor_id or execution_id not in self._execution_ids:
            raise invalid()
        audits = self._authority.audits.get(execution_id, ())
        if len(audits) > 1:
            # Preserve the original query's first-row semantics; never choose via a dict.
            expected = await super().expected_context_for_execution(
                actor_id=actor_id, execution_id=execution_id,
            )
            self._fallback[execution_id] = expected
            return expected
        if not audits:
            raise invalid()
        audit = audits[0]
        config = self._authority.profiles.get(audit.generation_profile_id)
        generation = _generation(config)
        if generation is None or not isinstance(config, Mapping):
            raise invalid()
        schema = generation.get("response_schema_version", 1)
        if schema in (1, 2):
            return None
        if (
            schema != 3
            or generation.get("numeric_proof_policy_ref") != SOURCE_NUMERIC_PROOF_V1.ref
            or config.get("prompt_ref") != "rag-codex-answer-v6"
        ):
            raise invalid()
        receipts = self._authority.receipts.get(execution_id, ())
        if len(receipts) != 1:
            raise invalid()
        receipt = receipts[0]
        if (
            receipt.audit_id != audit.id
            or receipt.configuration_version_id != audit.configuration_version_id
            or receipt.generation_profile_id != audit.generation_profile_id
            or receipt.policy_digest != SOURCE_NUMERIC_PROOF_V1.digest
        ):
            raise invalid()
        return ExpectedNumericContext(
            actor_id, execution_id, receipt.request_id, audit.configuration_version_id,
            audit.generation_profile_id, 3, SOURCE_NUMERIC_PROOF_V1.ref,
            SOURCE_NUMERIC_PROOF_V1.digest, audit.evidence_ids,
        )

    async def revalidate(self) -> None:
        # Scalar projections bypass the ORM identity map and profile selectin relationships.
        if await _read(self.session, self._actor_id, self._execution_ids) != self._authority:
            raise invalid()
        for execution_id, expected in self._fallback.items():
            if await super().expected_context_for_execution(
                actor_id=self._actor_id, execution_id=execution_id,
            ) != expected:
                raise invalid()
