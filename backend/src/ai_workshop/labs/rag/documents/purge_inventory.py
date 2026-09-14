from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
    StructuralElementRecord,
)
from ai_workshop.labs.rag.documents.provenance import (
    RAG_DERIVED_ARTIFACT_RELATION,
    RAG_DOCUMENT_SQL_PARTICIPANT,
    RAG_PROJECTION_BUNDLE_KIND,
)
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.purge_inventory_contracts import (
    DocumentTarget,
    ParticipantInventory,
)

RAG_DOCUMENT_SQL_CONTRACT_VERSION = 1

_SOURCE_INVALID = "rag_document_sql_source_invalid"
_INVENTORY_FAILED = "rag_document_sql_inventory_failed"


class RagDocumentSqlInventoryError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RagDocumentSqlInventory:
    def __init__(self, engine: AsyncEngine) -> None:
        if not isinstance(engine, AsyncEngine):
            raise TypeError("engine must be an AsyncEngine")
        self._engine = engine

    async def collect(
        self,
        workspace_id: UUID,
        documents: tuple[DocumentTarget, ...],
    ) -> ParticipantInventory:
        if not isinstance(workspace_id, UUID):
            raise TypeError("workspace_id must be a UUID")
        if type(documents) is not tuple or any(
            not isinstance(document, DocumentTarget) for document in documents
        ):
            raise TypeError("documents must be a tuple of DocumentTarget values")
        if len({document.document_id for document in documents}) != len(documents):
            raise RagDocumentSqlInventoryError(_SOURCE_INVALID)

        try:
            async with self._engine.connect() as connection, connection.begin():
                await connection.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                return await self._collect_snapshot(connection, workspace_id, documents)
        except RagDocumentSqlInventoryError:
            raise
        except Exception:
            raise RagDocumentSqlInventoryError(_INVENTORY_FAILED) from None

    async def _collect_snapshot(
        self,
        connection: AsyncConnection,
        workspace_id: UUID,
        documents: tuple[DocumentTarget, ...],
    ) -> ParticipantInventory:
        targets = {target.document_id: target for target in documents}
        document_ids = tuple(targets)
        document_rows = (
            await connection.execute(
                select(
                    DocumentRecord.id,
                    DocumentRecord.workspace_id,
                    DocumentRecord.lifecycle_generation,
                ).where(DocumentRecord.id.in_(document_ids))
            )
        ).all()
        if len(document_rows) != len(targets) or any(
            document_row.workspace_id != workspace_id
            or document_row.lifecycle_generation
            != targets[document_row.id].generation
            for document_row in document_rows
        ):
            raise RagDocumentSqlInventoryError(_SOURCE_INVALID)

        version_rows = (
            await connection.execute(
                select(AssetVersionRecord.id, AssetVersionRecord.document_id).where(
                    AssetVersionRecord.document_id.in_(document_ids)
                )
            )
        ).all()
        versions_by_document: dict[UUID, set[UUID]] = defaultdict(set)
        for version_row in version_rows:
            versions_by_document[version_row.document_id].add(version_row.id)
        if any(
            versions_by_document[target.document_id]
            != set(target.asset_version_ids)
            for target in documents
        ):
            raise RagDocumentSqlInventoryError(_SOURCE_INVALID)

        version_ids = tuple(
            version_id
            for target in documents
            for version_id in target.asset_version_ids
        )
        projection_rows = (
            await connection.execute(
                select(
                    RagProjectionRecord.id,
                    RagProjectionRecord.asset_version_id,
                    RagProjectionRecord.content_revision,
                ).where(RagProjectionRecord.asset_version_id.in_(version_ids))
            )
        ).all()
        projection_ids = tuple(row.id for row in projection_rows)

        relation_scope = []
        if version_ids:
            relation_scope.append(AssetSourceRelationRecord.asset_version_id.in_(version_ids))
        if projection_ids:
            relation_scope.append(AssetSourceRelationRecord.resource_id.in_(projection_ids))
        relation_rows: Sequence[
            Row[tuple[UUID, UUID, UUID, str, str, UUID, int, str]]
        ]
        if relation_scope:
            relation_rows = (
                await connection.execute(
                    select(
                        AssetSourceRelationRecord.workspace_id,
                        AssetSourceRelationRecord.document_id,
                        AssetSourceRelationRecord.asset_version_id,
                        AssetSourceRelationRecord.participant,
                        AssetSourceRelationRecord.kind,
                        AssetSourceRelationRecord.resource_id,
                        AssetSourceRelationRecord.resource_revision,
                        AssetSourceRelationRecord.relation_kind,
                    ).where(
                        AssetSourceRelationRecord.participant
                        == RAG_DOCUMENT_SQL_PARTICIPANT,
                        or_(*relation_scope),
                    )
                )
            ).all()
        else:
            relation_rows = ()

        expected_relations: set[tuple[UUID, UUID, UUID, UUID, int, str]] = set()
        resources: set[ResourceIdentity] = set()
        legacy_resolved = True
        source_by_version = {
            version_id: (target.document_id, workspace_id)
            for target in documents
            for version_id in target.asset_version_ids
        }
        for projection_row in projection_rows:
            if projection_row.content_revision is None:
                legacy_resolved = False
                continue
            document_id, expected_workspace_id = source_by_version[
                projection_row.asset_version_id
            ]
            expected_relations.add(
                (
                    expected_workspace_id,
                    document_id,
                    projection_row.asset_version_id,
                    projection_row.id,
                    projection_row.content_revision,
                    RAG_DERIVED_ARTIFACT_RELATION,
                )
            )
            resources.add(
                ResourceIdentity(
                    participant=RAG_DOCUMENT_SQL_PARTICIPANT,
                    kind=RAG_PROJECTION_BUNDLE_KIND,
                    resource_id=projection_row.id,
                    revision=projection_row.content_revision,
                )
            )

        supported = all(
            relation_row.kind == RAG_PROJECTION_BUNDLE_KIND
            for relation_row in relation_rows
        )
        actual_relations: set[tuple[UUID, UUID, UUID, UUID, int, str]] = set()
        for relation_row in relation_rows:
            resources.add(
                ResourceIdentity(
                    participant=relation_row.participant,
                    kind=relation_row.kind,
                    resource_id=relation_row.resource_id,
                    revision=relation_row.resource_revision,
                )
            )
            if relation_row.kind == RAG_PROJECTION_BUNDLE_KIND:
                actual_relations.add(
                    (
                        relation_row.workspace_id,
                        relation_row.document_id,
                        relation_row.asset_version_id,
                        relation_row.resource_id,
                        relation_row.resource_revision,
                        relation_row.relation_kind,
                    )
                )
        if actual_relations != expected_relations:
            legacy_resolved = False

        if projection_ids and not await _children_have_consistent_ownership(
            connection, projection_ids
        ):
            legacy_resolved = False

        ordered_resources = tuple(
            sorted(
                resources,
                key=lambda resource: (
                    resource.kind,
                    str(resource.resource_id),
                    resource.revision,
                ),
            )
        )
        return ParticipantInventory(
            participant=RAG_DOCUMENT_SQL_PARTICIPANT,
            contract_version=RAG_DOCUMENT_SQL_CONTRACT_VERSION,
            resources=ordered_resources,
            exhausted=True,
            supported=supported,
            legacy_resolved=legacy_resolved,
        )


async def _children_have_consistent_ownership(
    connection: AsyncConnection,
    projection_ids: tuple[UUID, ...],
) -> bool:
    element_rows = (
        await connection.execute(
            select(StructuralElementRecord.id, StructuralElementRecord.projection_id).where(
                StructuralElementRecord.projection_id.in_(projection_ids)
            )
        )
    ).all()
    chunk_rows = (
        await connection.execute(
            select(RetrievalChunkRecord.id, RetrievalChunkRecord.projection_id).where(
                RetrievalChunkRecord.projection_id.in_(projection_ids)
            )
        )
    ).all()
    element_owners = {row.id: row.projection_id for row in element_rows}
    chunk_owners = {row.id: row.projection_id for row in chunk_rows}

    evidence_rows = (
        await connection.execute(
            select(
                EvidenceUnitRecord.projection_id,
                EvidenceUnitRecord.retrieval_chunk_id,
                EvidenceUnitRecord.element_id,
            ).where(
                or_(
                    EvidenceUnitRecord.projection_id.in_(projection_ids),
                    EvidenceUnitRecord.retrieval_chunk_id.in_(tuple(chunk_owners)),
                    EvidenceUnitRecord.element_id.in_(tuple(element_owners)),
                )
            )
        )
    ).all()
    return all(
        row.projection_id in projection_ids
        and chunk_owners.get(row.retrieval_chunk_id) == row.projection_id
        and element_owners.get(row.element_id) == row.projection_id
        for row in evidence_rows
    )
