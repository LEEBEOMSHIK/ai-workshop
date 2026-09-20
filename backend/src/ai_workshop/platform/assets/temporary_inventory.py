"""Read-only temporary inventory; observations cannot establish historical absence."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.purge_inventory_contracts import ParticipantInventory
from ai_workshop.platform.assets.temporary_contracts import (
    TEMPORARY_STATES,
    TemporaryBinding,
    TemporaryClaim,
    TemporaryOwnershipError,
)
from ai_workshop.platform.assets.temporary_models import TemporaryWorkspaceRecord
from ai_workshop.platform.assets.temporary_repository import PARTICIPANT, record_claim
from ai_workshop.shared.models import Base


class TemporaryInventoryStore(Protocol):
    @property
    def binding(self) -> TemporaryBinding: ...

    def observe(self, claim: TemporaryClaim) -> bool: ...


@dataclass(frozen=True)
class TemporaryInventory:
    resources: tuple[ResourceIdentity, ...]
    blockers: tuple[str, ...]
    complete: bool
    exhausted: bool = True

    @property
    def participant(self) -> ParticipantInventory:
        return ParticipantInventory(
            PARTICIPANT, 1, self.resources, self.exhausted, True, self.complete
        )


@dataclass(frozen=True)
class _Snapshot:
    documents: tuple[DocumentRecord, ...]
    versions: tuple[AssetVersionRecord, ...]
    workspaces: tuple[TemporaryWorkspaceRecord, ...]
    relations: tuple[AssetSourceRelationRecord, ...]

    def fingerprint(self) -> tuple[tuple[tuple[object, ...], ...], ...]:
        groups: tuple[tuple[Base, ...], ...] = (
            self.documents,
            self.versions,
            self.workspaces,
            self.relations,
        )
        return tuple(
            tuple(tuple(getattr(row, col.key) for col in row.__table__.columns) for row in rows)
            for rows in groups
        )


class TemporaryWorkspaceInventory:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], store: TemporaryInventoryStore
    ) -> None:
        self.sessions, self.store = sessions, store

    async def _snapshot(self, workspace_id: UUID, document_id: UUID) -> _Snapshot:
        async with self.sessions() as session:
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            await session.execute(text("SET TRANSACTION READ ONLY"))
            documents = tuple(
                await session.scalars(
                    select(DocumentRecord).where(
                        DocumentRecord.workspace_id == workspace_id,
                        DocumentRecord.id == document_id,
                    )
                )
            )
            versions = tuple(
                await session.scalars(
                    select(AssetVersionRecord)
                    .where(AssetVersionRecord.document_id.in_([row.id for row in documents]))
                    .order_by(AssetVersionRecord.id)
                )
            )
            rows = tuple(
                await session.scalars(
                    select(TemporaryWorkspaceRecord)
                    .where(
                        TemporaryWorkspaceRecord.workspace_id == workspace_id,
                        TemporaryWorkspaceRecord.document_id == document_id,
                    )
                    .order_by(TemporaryWorkspaceRecord.id)
                )
            )
            relations = tuple(
                await session.scalars(
                    select(AssetSourceRelationRecord)
                    .where(
                        AssetSourceRelationRecord.participant == PARTICIPANT,
                        or_(
                            (AssetSourceRelationRecord.workspace_id == workspace_id)
                            & (AssetSourceRelationRecord.document_id == document_id),
                            AssetSourceRelationRecord.resource_id.in_([row.id for row in rows]),
                        ),
                    )
                    .order_by(AssetSourceRelationRecord.id)
                )
            )
            return _Snapshot(documents, versions, rows, relations)

    async def collect(self, workspace_id: UUID, document_id: UUID) -> TemporaryInventory:
        """Trusted participant call; authorize source access before entering this boundary."""
        before = await self._snapshot(workspace_id, document_id)
        # No cutover/attestation exists for historical temp, HTTP spool or general jobs.
        # Even a cleaned bounded claim proves only its own token's observed absence.
        blockers = {"legacy_untracked", "http_spool_untracked", "job_provenance_untracked"}
        if not before.documents:
            blockers.add("source_unavailable")
        expected = set()
        versions = {row.id: row for row in before.versions}
        documents = {row.id: row for row in before.documents}
        resources = []
        for row in before.workspaces:
            resources.append(ResourceIdentity(PARTICIPANT, "workspace", row.id, row.revision))
            expected.add(
                (
                    row.workspace_id,
                    row.document_id,
                    row.asset_version_id,
                    "workspace",
                    row.id,
                    row.revision,
                    "source_copy",
                )
            )
            version, document = versions.get(row.asset_version_id), documents.get(row.document_id)
            if version is None or document is None or version.document_id != row.document_id:
                blockers.add("source_mismatch")
            elif row.generation != document.lifecycle_generation and row.state != "cleaned":
                blockers.add("generation_mismatch")
            if row.state == "open":
                blockers.add("writer_unconfirmed")
            elif row.state != "cleaned":
                blockers.add("cleanup_unconfirmed")
            if row.coverage != "bounded":
                blockers.add("runtime_unverified")
            try:
                claim = record_claim(row)
                if TEMPORARY_STATES.get(row.state) != row.revision:
                    blockers.add("state_conflict")
                if claim.binding != self.store.binding:
                    blockers.add("binding_mismatch")
                elif self.store.observe(claim):
                    blockers.add("temporary_present")
            except TemporaryOwnershipError as error:
                blockers.add(error.code)
            except Exception:
                blockers.add("observation_failed")
        actual = {
            (
                row.workspace_id,
                row.document_id,
                row.asset_version_id,
                row.kind,
                row.resource_id,
                row.resource_revision,
                row.relation_kind,
            )
            for row in before.relations
        }
        if actual != expected:
            blockers.add("relation_mismatch")
        after = await self._snapshot(workspace_id, document_id)
        if before.fingerprint() != after.fingerprint():
            blockers.add("inventory_changed")
        return TemporaryInventory(tuple(resources), tuple(sorted(blockers)), not blockers)
