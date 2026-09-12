"""Owner-authored evaluation data, never inferred labels or predicted source universes."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol
from uuid import UUID, uuid5

from sqlalchemy.exc import SQLAlchemyError

from ai_workshop.labs.rag.configurations.domain import BM25_BASELINE_CONFIGURATION_VERSION_ID
from ai_workshop.labs.rag.evaluation.authoring_schemas import (
    AuthoringDocument,
    AuthoringDocumentsRequest,
    AuthoringDocumentsResponse,
    AuthoringEvidence,
    AuthoringPreview,
    AuthoringRunRequest,
    AuthoringScope,
)
from ai_workshop.labs.rag.evaluation.domain import EvaluationDataset
from ai_workshop.labs.rag.evaluation.service import EvaluationApplicationService, EvaluationRunView
from ai_workshop.shared.errors import AppError

AUTHORING_NAMESPACE = UUID("d95b12bc-25b1-5fee-90b9-2fc8b8a42337")


@dataclass(frozen=True, slots=True)
class AuthoringLimits:
    max_documents: int = 20
    max_evidence_units: int = 1000
    max_response_bytes: int = 2_097_152
    max_cases: int = 50


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")


def dataset_id(actor_id: UUID, draft_id: UUID) -> UUID:
    return uuid5(AUTHORING_NAMESPACE, f"dataset:{actor_id}:{draft_id}")


@dataclass(frozen=True, slots=True)
class AuthoringBuild:
    asset_version_id: UUID
    projection_id: UUID
    index_build_id: UUID
    index_uuid: str
    mapping_version: int
    vector_dimension: int


@dataclass(frozen=True, slots=True)
class AuthoringContext:
    actor_id: UUID
    scope: AuthoringScope
    document_processing_profile_id: UUID
    indexing_profile_id: UUID
    documents: tuple[AuthoringDocument, ...]
    evidence: tuple[AuthoringEvidence, ...]
    builds: tuple[AuthoringBuild, ...]

    def preview(self) -> AuthoringPreview:
        result = AuthoringPreview(
            scope=self.scope,
            baseline_configuration_version_id=BM25_BASELINE_CONFIGURATION_VERSION_ID,
            document_processing_profile_id=self.document_processing_profile_id,
            indexing_profile_id=self.indexing_profile_id,
            documents=tuple(sorted(self.documents, key=lambda item: item.asset_version_id)),
            evidence=tuple(sorted(self.evidence, key=lambda item: item.id)),
            document_count=len(self.documents),
            evidence_count=len(self.evidence),
            scope_sha256="0" * 64,
        )
        fingerprint = sha256(
            canonical_bytes(
                {
                    "schema_version": 1,
                    "actor_id": self.actor_id,
                    "preview": result.model_dump(mode="json", exclude={"scope_sha256"}),
                    "builds": [
                        asdict(item)
                        for item in sorted(self.builds, key=lambda item: item.asset_version_id)
                    ],
                }
            )
        ).hexdigest()
        return result.model_copy(update={"scope_sha256": fingerprint})


def _invalid() -> AppError:
    return AppError(
        "evaluation_authoring_invalid", "Check the selected evidence and locations.", 422
    )


def build_fixture(
    context: AuthoringContext, request: AuthoringRunRequest, *, as_of: str
) -> dict[str, object]:
    units = {unit.id: unit for unit in context.evidence}
    cases = []
    for case in request.cases:
        if not set(case.expected_evidence_ids).issubset(units):
            raise _invalid()
        highlight = case.expected_highlight
        if highlight is not None:
            unit = units.get(highlight.evidence_unit_id)
            if (
                unit is None
                or unit.id not in case.expected_evidence_ids
                or highlight.document_id != unit.document_id
                or highlight.asset_version_id != unit.asset_version_id
                or highlight.page != unit.page
                or not (highlight.spans or highlight.bboxes)
            ):
                raise _invalid()
            previous_end = unit.start_char
            for start, end in sorted(highlight.spans):
                if (
                    start < previous_end
                    or start >= end
                    or end > unit.end_char
                    or end > unit.start_char + len(unit.text)
                ):
                    raise _invalid()
                previous_end = end
            for x0, y0, x1, y1 in highlight.bboxes:
                if (
                    x0 >= x1
                    or y0 >= y1
                    or unit.page is None
                    or not any(
                        bx0 <= x0 < x1 <= bx1 and by0 <= y0 < y1 <= by1
                        for bx0, by0, bx1, by1 in unit.bounding_boxes
                    )
                ):
                    raise _invalid()
            if len(highlight.bboxes) != len(set(highlight.bboxes)):
                raise _invalid()
        cases.append(
            {
                "id": str(
                    uuid5(
                        AUTHORING_NAMESPACE, f"case:{context.actor_id}:{request.draft_id}:{case.id}"
                    )
                ),
                "kind": "manual",
                "query": case.query,
                "query_sha256": sha256(case.query.encode("utf-8")).hexdigest(),
                "permission_scenario": {
                    "name": "authoring-scope",
                    "actor": "caller",
                    "workspace_ids": [str(item) for item in context.scope.workspace_ids],
                    "folder_ids": [],
                    "authorized_source_ids": sorted(str(item) for item in units),
                    "forbidden_source_ids": [],
                    "as_of": as_of,
                },
                "expected": {
                    "answer_status": case.expected_answer_status,
                    "evidence_unit_ids": sorted(str(item) for item in case.expected_evidence_ids),
                    "highlight": highlight.model_dump(mode="json")
                    if highlight is not None
                    else None,
                },
            }
        )
    return {
        "schema_version": 1,
        "id": str(dataset_id(context.actor_id, request.draft_id)),
        "name": request.dataset_name.strip(),
        "version": 1,
        "authoring_scope_sha256": context.preview().scope_sha256,
        "document_snapshot": [
            {
                "document_id": str(document.document_id),
                "asset_version_id": str(document.asset_version_id),
                "sha256": document.sha256,
                "active": True,
            }
            for document in sorted(context.documents, key=lambda item: item.asset_version_id)
        ],
        "cases": cases,
    }


class AuthoringRepositoryPort(Protocol):
    async def documents(
        self, actor_id: UUID, request: AuthoringDocumentsRequest
    ) -> AuthoringDocumentsResponse: ...
    async def resolve_scope(self, actor_id: UUID, scope: AuthoringScope) -> AuthoringContext: ...
    async def lock_draft(self, actor_id: UUID, draft_id: UUID) -> None: ...
    async def existing_dataset(
        self, actor_id: UUID, identifier: UUID
    ) -> EvaluationDataset | None: ...
    async def require_available_name(self, actor_id: UUID, name: str, identifier: UUID) -> None: ...
    async def validate_run(self, context: AuthoringContext, run_id: UUID) -> None: ...


class AuthoringService:
    def __init__(
        self,
        repository: AuthoringRepositoryPort,
        evaluation: EvaluationApplicationService,
        *,
        limits: AuthoringLimits,
        rollback: Callable[[], Awaitable[None]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.evaluation = evaluation
        self.limits = limits
        self.rollback = rollback
        self.clock = clock

    async def documents(
        self, actor_id: UUID, request: AuthoringDocumentsRequest
    ) -> AuthoringDocumentsResponse:
        try:
            return await self.repository.documents(actor_id, request)
        except SQLAlchemyError as exc:
            await self.rollback()
            raise AppError(
                "evaluation_authoring_stale", "Reload the evaluation sources.", 409
            ) from exc

    async def preview(self, actor_id: UUID, scope: AuthoringScope) -> AuthoringPreview:
        try:
            return (await self.repository.resolve_scope(actor_id, scope)).preview()
        except SQLAlchemyError as exc:
            await self.rollback()
            raise AppError(
                "evaluation_authoring_stale", "Reload the evaluation sources.", 409
            ) from exc

    async def run(self, actor_id: UUID, request: AuthoringRunRequest) -> EvaluationRunView:
        try:
            if len(request.cases) > self.limits.max_cases:
                raise AppError("evaluation_authoring_too_large", "Use fewer evaluation cases.", 422)
            await self.repository.lock_draft(actor_id, request.draft_id)
            context = await self.repository.resolve_scope(actor_id, request.scope())
            if context.preview().scope_sha256 != request.scope_sha256:
                raise AppError("evaluation_authoring_stale", "Reload the evaluation sources.", 409)
            identifier = dataset_id(actor_id, request.draft_id)
            existing = await self.repository.existing_dataset(actor_id, identifier)
            as_of = (
                existing.cases[0].permission_scenario.as_of
                if existing is not None
                else self.clock().isoformat()
            )
            fixture = build_fixture(context, request, as_of=as_of)
            if existing is not None and existing.fixture_bytes != canonical_bytes(fixture):
                raise AppError(
                    "evaluation_authoring_conflict",
                    "Use a new draft for changed evaluation data.",
                    409,
                )
            await self.repository.require_available_name(
                actor_id, request.dataset_name.strip(), identifier
            )

            async def validate_before_commit(run: EvaluationRunView) -> None:
                if run.dataset_snapshot_id != identifier:
                    raise AppError(
                        "evaluation_authoring_conflict",
                        "The evaluation draft conflicts with stored data.",
                        409,
                    )
                await self.repository.validate_run(context, run.id)
                fresh = await self.repository.resolve_scope(actor_id, request.scope())
                if fresh.preview().scope_sha256 != request.scope_sha256:
                    raise AppError(
                        "evaluation_authoring_stale", "Reload the evaluation sources.", 409
                    )

            return await self.evaluation.start_run(
                actor_id=actor_id,
                dataset_fixture=fixture,
                dataset_snapshot_id=None,
                evaluation_policy_version_id=None,
                configuration_version_ids=(request.configuration_version_id,),
                metric_definition_version=1,
                retrieval_k=request.retrieval_k,
                repetition_count=request.repetition_count,
                before_commit=validate_before_commit,
            )
        except BaseException as exc:
            await self.rollback()
            if isinstance(exc, SQLAlchemyError):
                raise AppError(
                    "evaluation_authoring_conflict",
                    "The evaluation draft conflicts with stored data.",
                    409,
                ) from exc
            raise
