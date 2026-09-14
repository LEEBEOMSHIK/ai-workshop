from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.assets.provenance_contracts import (
    ResourceIdentity,
    SourceIdentity,
    SourceRelation,
)
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord

_RELATION_UNIQUE = "uq_asset_source_relations_source_resource_relation"
_CURRENT_CONFLICT = "asset_provenance_current_conflict"


class ProvenanceConflictError(RuntimeError):
    def __init__(self) -> None:
        self.code = _CURRENT_CONFLICT
        super().__init__(self.code)


class ProvenanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register(self, relation: SourceRelation) -> None:
        statement = (
            insert(AssetSourceRelationRecord)
            .values(
                workspace_id=relation.source.workspace_id,
                document_id=relation.source.document_id,
                asset_version_id=relation.source.asset_version_id,
                participant=relation.resource.participant,
                kind=relation.resource.kind,
                resource_id=relation.resource.resource_id,
                resource_revision=relation.resource.revision,
                relation_kind=relation.relation_kind,
            )
            .on_conflict_do_nothing(constraint=_RELATION_UNIQUE)
        )
        await self.session.execute(statement)
        await self.session.flush()

    async def replace_current(
        self,
        expected: SourceRelation,
        replacement: SourceRelation,
    ) -> None:
        if (
            replacement.source != expected.source
            or replacement.resource.participant != expected.resource.participant
            or replacement.resource.kind != expected.resource.kind
            or replacement.resource.resource_id != expected.resource.resource_id
            or replacement.resource.revision != expected.resource.revision + 1
            or replacement.relation_kind != expected.relation_kind
        ):
            raise ProvenanceConflictError()

        records = list(
            await self.session.scalars(
                select(AssetSourceRelationRecord)
                .where(
                    AssetSourceRelationRecord.participant
                    == expected.resource.participant,
                    AssetSourceRelationRecord.kind == expected.resource.kind,
                    AssetSourceRelationRecord.resource_id
                    == expected.resource.resource_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if len(records) != 1 or _relation(records[0]) != expected:
            raise ProvenanceConflictError()

        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(AssetSourceRelationRecord)
                .where(
                    AssetSourceRelationRecord.id == records[0].id,
                    AssetSourceRelationRecord.workspace_id
                    == expected.source.workspace_id,
                    AssetSourceRelationRecord.document_id
                    == expected.source.document_id,
                    AssetSourceRelationRecord.asset_version_id
                    == expected.source.asset_version_id,
                    AssetSourceRelationRecord.participant
                    == expected.resource.participant,
                    AssetSourceRelationRecord.kind == expected.resource.kind,
                    AssetSourceRelationRecord.resource_id
                    == expected.resource.resource_id,
                    AssetSourceRelationRecord.resource_revision
                    == expected.resource.revision,
                    AssetSourceRelationRecord.relation_kind
                    == expected.relation_kind,
                )
                .values(resource_revision=replacement.resource.revision)
            ),
        )
        if result.rowcount != 1:
            raise ProvenanceConflictError()
        await self.session.flush()

    async def list_for_source(
        self,
        source: SourceIdentity,
    ) -> tuple[SourceRelation, ...]:
        records = (
            await self.session.scalars(
                select(AssetSourceRelationRecord)
                .where(
                    AssetSourceRelationRecord.workspace_id == source.workspace_id,
                    AssetSourceRelationRecord.document_id == source.document_id,
                    AssetSourceRelationRecord.asset_version_id
                    == source.asset_version_id,
                )
                .order_by(
                    AssetSourceRelationRecord.participant,
                    AssetSourceRelationRecord.kind,
                    AssetSourceRelationRecord.resource_id,
                    AssetSourceRelationRecord.resource_revision,
                    AssetSourceRelationRecord.relation_kind,
                )
            )
        ).all()
        return tuple(_relation(record) for record in records)

    async def list_for_resource(
        self,
        workspace_id: UUID,
        resource: ResourceIdentity,
    ) -> tuple[SourceRelation, ...]:
        records = (
            await self.session.scalars(
                select(AssetSourceRelationRecord)
                .where(
                    AssetSourceRelationRecord.workspace_id == workspace_id,
                    AssetSourceRelationRecord.participant == resource.participant,
                    AssetSourceRelationRecord.kind == resource.kind,
                    AssetSourceRelationRecord.resource_id == resource.resource_id,
                    AssetSourceRelationRecord.resource_revision == resource.revision,
                )
                .order_by(
                    AssetSourceRelationRecord.document_id,
                    AssetSourceRelationRecord.asset_version_id,
                    AssetSourceRelationRecord.relation_kind,
                )
            )
        ).all()
        return tuple(_relation(record) for record in records)


def _relation(record: AssetSourceRelationRecord) -> SourceRelation:
    return SourceRelation(
        source=SourceIdentity(
            workspace_id=record.workspace_id,
            document_id=record.document_id,
            asset_version_id=record.asset_version_id,
        ),
        resource=ResourceIdentity(
            participant=record.participant,
            kind=record.kind,
            resource_id=record.resource_id,
            revision=record.resource_revision,
        ),
        relation_kind=record.relation_kind,
    )
