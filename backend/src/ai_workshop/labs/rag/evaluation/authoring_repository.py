"""Authorized, bounded source selection; all source locks follow ingestion ordering."""

from dataclasses import asdict
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.configurations.domain import BM25_BASELINE_CONFIGURATION_VERSION_ID
from ai_workshop.labs.rag.configurations.models import (
    RagConfigurationRecord,
    RagConfigurationVersionRecord,
    RagConfigurationWorkspaceSubscriptionRecord,
)
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagIndexBuildRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
)
from ai_workshop.labs.rag.evaluation.authoring import (
    AuthoringBuild,
    AuthoringContext,
    AuthoringLimits,
)
from ai_workshop.labs.rag.evaluation.authoring_schemas import (
    AuthoringDocument,
    AuthoringDocumentMetadata,
    AuthoringDocumentsRequest,
    AuthoringDocumentsResponse,
    AuthoringEvidence,
    AuthoringScope,
    AuthoringSelection,
)
from ai_workshop.labs.rag.evaluation.domain import EvaluationDataset
from ai_workshop.labs.rag.evaluation.models import (
    EvaluationDatasetRecord,
    EvaluationRunConfigurationRecord,
    EvaluationRunRecord,
)
from ai_workshop.labs.rag.evaluation.repository import (
    FrozenIndexInspectorPort,
    SqlAlchemyEvaluationApplicationRepository,
)
from ai_workshop.labs.rag.ingestion.domain import RagIngestionError
from ai_workshop.labs.rag.ingestion.locking import lock_ingestion_source
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import workspace_read_allowed
from ai_workshop.platform.workspaces.repository import workspace_is_active
from ai_workshop.shared.errors import AppError


def _missing() -> AppError:
    return AppError("not_found", "The requested resource was not found.", 404)


def _stale() -> AppError:
    return AppError("evaluation_authoring_stale", "Reload the evaluation sources.", 409)


def _oversized() -> AppError:
    return AppError("evaluation_authoring_too_large", "Select fewer or smaller documents.", 422)


class SqlAlchemyAuthoringRepository:
    def __init__(
        self, session: AsyncSession, *, inspector: FrozenIndexInspectorPort, limits: AuthoringLimits
    ) -> None:
        self.session = session
        self.inspector = inspector
        self.limits = limits

    async def documents(
        self, actor_id: UUID, request: AuthoringDocumentsRequest
    ) -> AuthoringDocumentsResponse:
        version = await self._authorize(actor_id, request)
        statement = (
            select(DocumentRecord, AssetVersionRecord, RagProjectionRecord, RagIndexBuildRecord)
            .join(
                AssetVersionRecord,
                AssetVersionRecord.id == DocumentRecord.active_version_id,
            )
            .outerjoin(
                RagProjectionRecord,
                and_(
                    RagProjectionRecord.asset_version_id == AssetVersionRecord.id,
                    RagProjectionRecord.document_processing_profile_id
                    == version.document_processing_profile_id,
                    RagProjectionRecord.indexing_profile_id == version.indexing_profile_id,
                ),
            )
            .outerjoin(
                RagIndexBuildRecord, RagIndexBuildRecord.projection_id == RagProjectionRecord.id
            )
            .where(
                DocumentRecord.workspace_id.in_(request.workspace_ids),
            )
            .order_by(DocumentRecord.id)
            .limit(request.limit + 1)
        )
        if request.cursor is not None:
            statement = statement.where(DocumentRecord.id > request.cursor)
        rows = (await self.session.execute(statement)).all()
        return AuthoringDocumentsResponse(
            documents=tuple(
                AuthoringDocumentMetadata(
                    document_id=document.id,
                    workspace_id=document.workspace_id,
                    asset_version_id=asset.id,
                    title=document.name,
                    number=asset.number,
                    ready=(
                        asset.status == "ready"
                        and projection is not None
                        and projection.status == "ready"
                        and build is not None
                        and build.status == "ready"
                        and build.document_processing_profile_id
                        == version.document_processing_profile_id
                        and build.indexing_profile_id == version.indexing_profile_id
                        and build.expected_document_count is not None
                        and build.expected_document_count > 0
                        and build.indexed_document_count == build.expected_document_count
                        and build.vector_dimension is not None
                        and build.index_name is not None
                    ),
                )
                for document, asset, projection, build in rows[: request.limit]
            ),
            next_cursor=rows[request.limit - 1][0].id if len(rows) > request.limit else None,
        )

    async def lock_draft(self, actor_id: UUID, draft_id: UUID) -> None:
        await self.session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(f"evaluation-authoring:{actor_id}:{draft_id}", 0)
                )
            )
        )

    async def existing_dataset(self, actor_id: UUID, identifier: UUID) -> EvaluationDataset | None:
        return await SqlAlchemyEvaluationApplicationRepository(self.session).find_dataset_visible(
            identifier, actor_id
        )

    async def require_available_name(self, actor_id: UUID, name: str, identifier: UUID) -> None:
        existing = await self.session.scalar(
            select(EvaluationDatasetRecord.id).where(
                EvaluationDatasetRecord.owner_id == actor_id,
                EvaluationDatasetRecord.name == name,
                EvaluationDatasetRecord.version == 1,
                EvaluationDatasetRecord.id != identifier,
            )
        )
        if existing is not None:
            raise AppError(
                "evaluation_authoring_conflict", "Use another name for new evaluation data.", 409
            )

    async def validate_run(self, context: AuthoringContext, run_id: UUID) -> None:
        run = await self.session.get(EvaluationRunRecord, run_id)
        if run is None or run.owner_id != context.actor_id:
            raise _stale()
        candidates = tuple(
            await self.session.scalars(
                select(EvaluationRunConfigurationRecord).where(
                    EvaluationRunConfigurationRecord.run_id == run_id
                )
            )
        )
        if {item.configuration_version_id for item in candidates} != {
            context.scope.configuration_version_id,
            BM25_BASELINE_CONFIGURATION_VERSION_ID,
        }:
            raise _stale()
        expected = sorted(
            (asdict(item) for item in context.builds),
            key=lambda item: str(item["asset_version_id"]),
        )
        try:
            for candidate in candidates:
                builds = cast(list[dict[str, object]], candidate.component_snapshot["index_builds"])
                actual = [
                    asdict(
                        AuthoringBuild(
                            UUID(str(item["asset_version_id"])),
                            UUID(str(item["projection_id"])),
                            UUID(str(item["index_build_id"])),
                            str(item["index_uuid"]),
                            int(cast(int, item["mapping_version"])),
                            int(cast(int, item["vector_dimension"])),
                        )
                    )
                    for item in builds
                ]
                if sorted(actual, key=lambda item: str(item["asset_version_id"])) != expected:
                    raise _stale()
            documents = {str(item.asset_version_id): item for item in context.documents}
            units = []
            for source in cast(list[dict[str, object]], run.execution_snapshot["sources"]):
                document = documents[str(source["asset_version_id"])]
                if (
                    str(document.document_id) != source["document_id"]
                    or document.sha256 != source["asset_sha256"]
                    or document.number != source["asset_version_number"]
                    or document.title != source["title"]
                    or str(document.workspace_id)
                    != cast(dict[str, object], source["workspace"])["id"]
                ):
                    raise _stale()
                for item in cast(list[dict[str, object]], source["evidence_units"]):
                    units.append(
                        AuthoringEvidence.model_validate(
                            {
                                "id": item["id"],
                                "document_id": source["document_id"],
                                "asset_version_id": source["asset_version_id"],
                                "projection_id": source["projection_id"],
                                "index_build_id": source["index_build_id"],
                                "text": item["text"],
                                "element_id": item["element_id"],
                                "page": item["page"],
                                "start_char": item["char_start"],
                                "end_char": item["char_end"],
                                "bounding_boxes": [] if item["bbox"] is None else [item["bbox"]],
                            }
                        )
                    )
            if tuple(sorted(units, key=lambda item: item.id)) != context.preview().evidence:
                raise _stale()
        except (KeyError, TypeError, ValueError) as exc:
            raise _stale() from exc

    async def _authorize(
        self, actor_id: UUID, selection: AuthoringSelection
    ) -> RagConfigurationVersionRecord:
        version = await self.session.scalar(
            select(RagConfigurationVersionRecord)
            .join(
                RagConfigurationRecord,
                RagConfigurationRecord.id == RagConfigurationVersionRecord.configuration_id,
            )
            .where(
                RagConfigurationVersionRecord.id == selection.configuration_version_id,
                RagConfigurationRecord.owner_id == actor_id,
            )
            .with_for_update(read=True, of=(RagConfigurationRecord, RagConfigurationVersionRecord))
            .execution_options(populate_existing=True)
        )
        if version is None:
            raise _missing()
        subscriptions = set(
            await self.session.scalars(
                select(RagConfigurationWorkspaceSubscriptionRecord.workspace_id).where(
                    RagConfigurationWorkspaceSubscriptionRecord.configuration_version_id
                    == version.id,
                    RagConfigurationWorkspaceSubscriptionRecord.workspace_id.in_(
                        selection.workspace_ids
                    ),
                )
            )
        )
        if subscriptions != set(selection.workspace_ids):
            raise _missing()
        spaces = tuple(
            await self.session.scalars(
                select(WorkspaceRecord.id)
                .where(
                    WorkspaceRecord.id.in_(selection.workspace_ids),
                    workspace_read_allowed(actor_id),
                    workspace_is_active(),
                )
                .order_by(WorkspaceRecord.id)
                .with_for_update(read=True)
            )
        )
        memberships = tuple(
            await self.session.scalars(
                select(WorkspaceMembershipRecord.workspace_id)
                .where(
                    WorkspaceMembershipRecord.workspace_id.in_(spaces),
                    WorkspaceMembershipRecord.user_id == actor_id,
                )
                .order_by(WorkspaceMembershipRecord.workspace_id)
                .with_for_update(read=True)
            )
        )
        if set(memberships) != set(selection.workspace_ids):
            raise _missing()
        baseline = await self.session.get(
            RagConfigurationVersionRecord, BM25_BASELINE_CONFIGURATION_VERSION_ID
        )
        if baseline is None or (
            baseline.document_processing_profile_id != version.document_processing_profile_id
            or baseline.indexing_profile_id != version.indexing_profile_id
        ):
            raise AppError(
                "evaluation_authoring_incompatible",
                "Select a candidate with the BM25 processing/indexing pair.",
                409,
            )
        return version

    async def resolve_scope(self, actor_id: UUID, scope: AuthoringScope) -> AuthoringContext:
        version = await self._authorize(actor_id, scope)
        if len(scope.asset_version_ids) > self.limits.max_documents:
            raise _oversized()
        visible = set(
            await self.session.scalars(
                select(AssetVersionRecord.id)
                .join(DocumentRecord, DocumentRecord.id == AssetVersionRecord.document_id)
                .where(
                    AssetVersionRecord.id.in_(scope.asset_version_ids),
                    DocumentRecord.workspace_id.in_(scope.workspace_ids),
                )
            )
        )
        if visible != set(scope.asset_version_ids):
            raise _missing()
        documents = []
        # This is the same Asset Version -> Document order used by source activation/ingestion.
        for asset_id in scope.asset_version_ids:
            try:
                source = await lock_ingestion_source(self.session, asset_id, require_active=False)
            except RagIngestionError as exc:
                raise _stale() from exc
            await self.session.refresh(source.asset)
            await self.session.refresh(source.document)
            if source.document.workspace_id not in scope.workspace_ids:
                raise _missing()
            if source.document.active_version_id != asset_id or source.asset.status != "ready":
                raise _stale()
            documents.append(
                AuthoringDocument(
                    document_id=source.document.id,
                    workspace_id=source.document.workspace_id,
                    asset_version_id=asset_id,
                    title=source.document.name,
                    number=source.asset.number,
                    sha256=source.asset.sha256,
                )
            )
        projections = tuple(
            await self.session.scalars(
                select(RagProjectionRecord)
                .where(
                    RagProjectionRecord.asset_version_id.in_(scope.asset_version_ids),
                    RagProjectionRecord.document_processing_profile_id
                    == version.document_processing_profile_id,
                    RagProjectionRecord.indexing_profile_id == version.indexing_profile_id,
                )
                .order_by(RagProjectionRecord.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if len(projections) != len(documents) or any(
            item.status != "ready" for item in projections
        ):
            raise _stale()
        projection_ids = tuple(item.id for item in projections)
        builds = tuple(
            await self.session.scalars(
                select(RagIndexBuildRecord)
                .where(RagIndexBuildRecord.projection_id.in_(projection_ids))
                .order_by(RagIndexBuildRecord.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if len(builds) != len(documents) or any(
            item.status != "ready"
            or item.index_name is None
            or item.vector_dimension is None
            or item.document_processing_profile_id != version.document_processing_profile_id
            or item.indexing_profile_id != version.indexing_profile_id
            or item.expected_document_count is None
            or item.expected_document_count < 1
            or item.indexed_document_count != item.expected_document_count
            for item in builds
        ):
            raise _stale()
        # Row locks on projections/chunks also block new child inserts via FK key-share locks.
        chunk_ids = tuple(
            await self.session.scalars(
                select(RetrievalChunkRecord.id)
                .where(RetrievalChunkRecord.projection_id.in_(projection_ids))
                .order_by(RetrievalChunkRecord.id)
                .limit(self.limits.max_evidence_units + 1)
                .with_for_update()
            )
        )
        if len(chunk_ids) > self.limits.max_evidence_units:
            raise _oversized()
        evidence_ids = tuple(
            await self.session.scalars(
                select(EvidenceUnitRecord.id)
                .where(EvidenceUnitRecord.projection_id.in_(projection_ids))
                .order_by(EvidenceUnitRecord.id)
                .limit(self.limits.max_evidence_units + 1)
                .with_for_update()
            )
        )
        count = len(evidence_ids)
        if count > self.limits.max_evidence_units:
            raise _oversized()
        if not count or not chunk_ids:
            raise _stale()
        chunk_bytes = await self.session.scalar(
            select(func.coalesce(func.sum(func.octet_length(RetrievalChunkRecord.text)), 0)).where(
                RetrievalChunkRecord.id.in_(chunk_ids)
            )
        )
        text_bytes = await self.session.scalar(
            select(func.coalesce(func.sum(func.octet_length(EvidenceUnitRecord.text)), 0)).where(
                EvidenceUnitRecord.id.in_(evidence_ids)
            )
        )
        if text_bytes is None or chunk_bytes is None:
            raise _stale()
        if (
            text_bytes > self.limits.max_response_bytes
            or chunk_bytes > self.limits.max_response_bytes
        ):
            raise _oversized()
        evidence = tuple(
            await self.session.scalars(
                select(EvidenceUnitRecord)
                .where(EvidenceUnitRecord.projection_id.in_(projection_ids))
                .order_by(EvidenceUnitRecord.id)
                .limit(self.limits.max_evidence_units + 1)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if len(evidence) != count:
            raise _stale()
        by_projection = {item.id: item for item in projections}
        by_asset = {item.asset_version_id: item for item in documents}
        by_build = {item.projection_id: item for item in builds}
        identities = []
        for build in builds:
            assert build.index_name is not None and build.vector_dimension is not None
            try:
                actual = await self.inspector.describe(build.index_name)
            except Exception as exc:
                raise _stale() from exc
            if (
                actual.index_name != build.index_name
                or actual.index_build_id != build.id
                or actual.projection_id != build.projection_id
                or actual.indexing_profile_id != build.indexing_profile_id
                or actual.vector_dimension != build.vector_dimension
            ):
                raise _stale()
            identities.append(
                AuthoringBuild(
                    by_projection[build.projection_id].asset_version_id,
                    build.projection_id,
                    build.id,
                    actual.index_uuid,
                    actual.mapping_version,
                    actual.vector_dimension,
                )
            )
        units = tuple(
            AuthoringEvidence(
                id=item.id,
                document_id=by_asset[
                    by_projection[item.projection_id].asset_version_id
                ].document_id,
                asset_version_id=by_projection[item.projection_id].asset_version_id,
                projection_id=item.projection_id,
                index_build_id=by_build[item.projection_id].id,
                text=item.text,
                element_id=item.element_id,
                page=item.page,
                start_char=item.char_start,
                end_char=item.char_end,
                bounding_boxes=(
                    ()
                    if item.bbox is None
                    else (cast(tuple[float, float, float, float], tuple(item.bbox)),)
                ),
            )
            for item in evidence
        )
        if {item.asset_version_id for item in units} != set(scope.asset_version_ids):
            raise _stale()
        context = AuthoringContext(
            actor_id,
            scope,
            version.document_processing_profile_id,
            version.indexing_profile_id,
            tuple(documents),
            units,
            tuple(identities),
        )
        if (
            len(context.preview().model_dump_json().encode("utf-8"))
            > self.limits.max_response_bytes
        ):
            raise _oversized()
        return context
