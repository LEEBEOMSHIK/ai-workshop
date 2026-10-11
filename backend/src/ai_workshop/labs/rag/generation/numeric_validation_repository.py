"""Verify a receipt against an independently selected server execution and live sources."""

from collections.abc import Mapping
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagIndexBuildRecord,
    RagProjectionRecord,
)
from ai_workshop.labs.rag.generation.audit import GenerationExecutionAudit
from ai_workshop.labs.rag.generation.audit_models import GenerationExecutionAuditRecord
from ai_workshop.labs.rag.generation.numeric_proof_serialization import (
    numeric_payload_digest,
    rebuild_validated_numeric_payload,
)
from ai_workshop.labs.rag.generation.numeric_proof_types import (
    ExpectedNumericContext,
    NumericValidationBinding,
    ValidatedGenerationPayload,
)
from ai_workshop.labs.rag.generation.numeric_validation import ValidatedNumericGeneration
from ai_workshop.labs.rag.generation.numeric_validation_models import NumericValidationRecord
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.labs.rag.models.numeric_proof_policy import SOURCE_NUMERIC_PROOF_V1
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import workspace_read_allowed
from ai_workshop.shared.errors import AppError


def invalid() -> AppError:
    return AppError(
        "numeric_validation_binding_invalid", "저장된 계산 근거를 검증할 수 없습니다.", 409
    )


def binding_from_record(record: NumericValidationRecord) -> NumericValidationBinding:
    return NumericValidationBinding(
        record.id,
        record.audit_id,
        record.request_id,
        record.configuration_version_id,
        record.generation_profile_id,
        record.schema_version,
        record.policy_ref,
        record.policy_digest,
        record.catalogue_digest,
        record.payload_digest,
    )


async def numeric_storage_ready(session: AsyncSession) -> bool:
    try:
        return bool(
            await session.scalar(
                text(
                    "SELECT to_regclass('rag_generation_numeric_validations') IS NOT NULL "
                    "AND to_regprocedure('rag_require_generative_numeric_candidate(uuid,uuid)') "
                    "IS NOT NULL"
                )
            )
        )
    except Exception:
        return False


def prepare_receipt(
    audit: GenerationExecutionAudit, validated: ValidatedNumericGeneration
) -> NumericValidationRecord:
    payload = validated.payload
    if (
        payload is None
        or payload.schema_version != 3
        or not audit.policy_allowed
        or audit.safe_error_code is not None
        or audit.generation_profile_id != payload.generation_profile_id
        or audit.configuration_version_id != payload.configuration_version_id
        or payload.policy_ref != SOURCE_NUMERIC_PROOF_V1.ref
        or payload.policy_digest != SOURCE_NUMERIC_PROOF_V1.digest
        or audit.prompt_ref != "rag-codex-answer-v6"
        or audit.prompt_version != 6
        or (payload.status == "answered" and audit.status != "succeeded")
        or (payload.status == "insufficient_evidence" and audit.status != "allowed")
        or validated.outcome.status.value != payload.status
        or validated.outcome.text != payload.answer
        or audit.evidence_ids != validated.evidence_ids
        or any(
            identity not in audit.evidence_ids
            for claim in payload.claims
            for identity in claim.evidence_ids
        )
    ):
        raise invalid()
    # Recheck the canonical status/answer/claim contract before adding either row.
    record = NumericValidationRecord(
        id=uuid4(),
        audit_id=audit.id,
        request_id=payload.request_id,
        execution_id=audit.execution_id,
        configuration_version_id=payload.configuration_version_id,
        generation_profile_id=payload.generation_profile_id,
        schema_version=3,
        policy_ref=payload.policy_ref,
        policy_digest=payload.policy_digest,
        catalogue_digest=payload.catalogue_digest,
        payload_digest=numeric_payload_digest(payload),
        created_at=audit.created_at,
    )
    rebuilt = rebuild_validated_numeric_payload(
        status=payload.status,
        answer=payload.answer,
        claims=payload.claims,
        binding=binding_from_record(record),
    )
    if rebuilt != payload:
        raise invalid()
    return record


class SqlAlchemyNumericValidationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def expected_context_for_execution(
        self, *, actor_id: UUID, execution_id: UUID
    ) -> ExpectedNumericContext | None:
        audit = await self.session.scalar(
            select(GenerationExecutionAuditRecord).where(
                GenerationExecutionAuditRecord.execution_id == execution_id,
                GenerationExecutionAuditRecord.actor_id == actor_id,
                GenerationExecutionAuditRecord.status.in_(("succeeded", "allowed")),
            )
        )
        if audit is None:
            raise invalid()
        profile = await self.session.scalar(
            select(ProfileRecord).where(ProfileRecord.id == audit.generation_profile_id)
        )
        if profile is None:
            raise invalid()
        generation = profile.config.get("generation", {})
        if not isinstance(generation, Mapping):
            raise invalid()
        schema = generation.get("response_schema_version", 1)
        if schema in (1, 2):
            return None  # No new-table query on schema0061 legacy paths.
        if (
            schema != 3
            or generation.get("numeric_proof_policy_ref") != SOURCE_NUMERIC_PROOF_V1.ref
            or profile.config.get("prompt_ref") != "rag-codex-answer-v6"
        ):
            raise invalid()
        receipt = await self.session.scalar(
            select(NumericValidationRecord).where(
                NumericValidationRecord.execution_id == execution_id,
                NumericValidationRecord.audit_id == audit.id,
            )
        )
        if (
            receipt is None
            or receipt.configuration_version_id != audit.configuration_version_id
            or receipt.generation_profile_id != audit.generation_profile_id
            or receipt.policy_digest != SOURCE_NUMERIC_PROOF_V1.digest
        ):
            raise invalid()
        return ExpectedNumericContext(
            actor_id,
            execution_id,
            receipt.request_id,
            audit.configuration_version_id,
            audit.generation_profile_id,
            3,
            SOURCE_NUMERIC_PROOF_V1.ref,
            SOURCE_NUMERIC_PROOF_V1.digest,
            tuple(audit.evidence_ids),
        )

    async def verify_binding(
        self,
        binding: NumericValidationBinding,
        payload: ValidatedGenerationPayload,
        *,
        expected: ExpectedNumericContext,
    ) -> None:
        receipt = await self.session.get(
            NumericValidationRecord, binding.validation_id, populate_existing=True
        )
        if (
            receipt is None
            or binding_from_record(receipt) != binding
            or receipt.execution_id != expected.execution_id
            or receipt.request_id != expected.request_id
            or binding.configuration_version_id != expected.configuration_version_id
            or binding.generation_profile_id != expected.generation_profile_id
            or binding.schema_version != expected.schema_version
            or binding.policy_ref != expected.policy_ref
            or binding.policy_digest != expected.policy_digest
            or binding.policy_digest != SOURCE_NUMERIC_PROOF_V1.digest
            or numeric_payload_digest(payload) != binding.payload_digest
        ):
            raise invalid()
        if (
            rebuild_validated_numeric_payload(
                status=payload.status, answer=payload.answer, claims=payload.claims, binding=binding
            )
            != payload
        ):
            raise invalid()
        audit = await self.session.scalar(
            select(GenerationExecutionAuditRecord).where(
                GenerationExecutionAuditRecord.id == binding.audit_id
            )
        )
        if (
            audit is None
            or audit.actor_id != expected.actor_id
            or audit.execution_id != expected.execution_id
            or audit.configuration_version_id != expected.configuration_version_id
            or audit.generation_profile_id != expected.generation_profile_id
            or tuple(audit.evidence_ids) != expected.evidence_ids
            or not audit.policy_allowed
            or audit.status != ("succeeded" if payload.status == "answered" else "allowed")
        ):
            raise invalid()
        for claim in payload.claims:
            if any(identity not in expected.evidence_ids for identity in claim.evidence_ids):
                raise invalid()
            for identity in claim.evidence_ids:
                found = await self.session.scalar(
                    select(EvidenceUnitRecord.id)
                    .join(
                        RagProjectionRecord,
                        RagProjectionRecord.id == EvidenceUnitRecord.projection_id,
                    )
                    .join(
                        AssetVersionRecord,
                        AssetVersionRecord.id == RagProjectionRecord.asset_version_id,
                    )
                    .join(DocumentRecord, DocumentRecord.id == AssetVersionRecord.document_id)
                    .join(WorkspaceRecord, WorkspaceRecord.id == DocumentRecord.workspace_id)
                    .join(
                        RagIndexBuildRecord,
                        RagIndexBuildRecord.projection_id == RagProjectionRecord.id,
                    )
                    .where(
                        EvidenceUnitRecord.id == identity,
                        RagProjectionRecord.status == "ready",
                        AssetVersionRecord.status == "ready",
                        DocumentRecord.lifecycle == "active",
                        RagIndexBuildRecord.status == "ready",
                        workspace_read_allowed(expected.actor_id),
                    )
                )
                if found is None:
                    raise invalid()
            for proof in claim.calculations:
                if proof.policy_ref != binding.policy_ref:
                    raise invalid()
                for operand in proof.operands:
                    if operand.evidence_id not in claim.evidence_ids:
                        raise invalid()
                    found = await self.session.scalar(
                        select(EvidenceUnitRecord.id)
                        .join(
                            RagProjectionRecord,
                            RagProjectionRecord.id == EvidenceUnitRecord.projection_id,
                        )
                        .join(
                            AssetVersionRecord,
                            AssetVersionRecord.id == RagProjectionRecord.asset_version_id,
                        )
                        .join(DocumentRecord, DocumentRecord.id == AssetVersionRecord.document_id)
                        .join(WorkspaceRecord, WorkspaceRecord.id == DocumentRecord.workspace_id)
                        .join(
                            RagIndexBuildRecord,
                            RagIndexBuildRecord.projection_id == RagProjectionRecord.id,
                        )
                        .where(
                            EvidenceUnitRecord.id == operand.evidence_id,
                            EvidenceUnitRecord.element_id == operand.element_id,
                            EvidenceUnitRecord.retrieval_chunk_id == operand.chunk_id,
                            EvidenceUnitRecord.char_start + operand.token_start
                            == operand.char_start,
                            EvidenceUnitRecord.char_start + operand.token_end == operand.char_end,
                            EvidenceUnitRecord.char_end >= operand.char_end,
                            EvidenceUnitRecord.page.is_not_distinct_from(operand.page),
                            RagProjectionRecord.id == operand.projection_id,
                            RagProjectionRecord.status == "ready",
                            AssetVersionRecord.id == operand.asset_version_id,
                            AssetVersionRecord.status == "ready",
                            DocumentRecord.id == operand.document_id,
                            DocumentRecord.lifecycle == "active",
                            RagIndexBuildRecord.status == "ready",
                            workspace_read_allowed(expected.actor_id),
                        )
                    )
                    if found is None:
                        raise invalid()
