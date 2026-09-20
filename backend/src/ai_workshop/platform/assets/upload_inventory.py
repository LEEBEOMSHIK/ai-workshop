"""Read-only original ownership inventory; private locators never leave this boundary."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity, SourceIdentity
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.purge_inventory_contracts import ParticipantInventory
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.storage import StoredObject
from ai_workshop.platform.assets.upload_contracts import (
    OriginalFileObservation,
    OriginalStoreBinding,
    UploadAttempt,
    UploadClaim,
    UploadOwnershipError,
)
from ai_workshop.platform.assets.upload_models import OriginalResourceRecord, UploadAttemptRecord
from ai_workshop.shared.errors import AppError
from ai_workshop.shared.models import Base

PARTICIPANT = "platform_originals"


class OriginalInventoryStore(Protocol):
    @property
    def binding(self) -> OriginalStoreBinding: ...

    def observe(self, claim: UploadClaim) -> OriginalFileObservation: ...


@dataclass(frozen=True)
class OriginalInventory:
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
class UnattachedUpload:
    attempt_id: UUID
    source: SourceIdentity
    state: str
    revision: int
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class UnattachedUploads:
    items: tuple[UnattachedUpload, ...]
    blockers: tuple[str, ...]
    complete: bool
    exhausted: bool = True


@dataclass(frozen=True)
class _Snapshot:
    documents: tuple[DocumentRecord, ...]
    versions: tuple[AssetVersionRecord, ...]
    attempts: tuple[UploadAttemptRecord, ...]
    originals: tuple[OriginalResourceRecord, ...]
    relations: tuple[AssetSourceRelationRecord, ...]

    def fingerprint(self) -> tuple[tuple[tuple[object, ...], ...], ...]:
        # All queried scalar fields participate, including generation and relation identity.
        groups: tuple[tuple[Base, ...], ...] = (
            self.documents,
            self.versions,
            self.attempts,
            self.originals,
            self.relations,
        )
        return tuple(
            tuple(tuple(getattr(row, col.key) for col in row.__table__.columns) for row in rows)
            for rows in groups
        )


class OriginalUploadInventory:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], store: OriginalInventoryStore
    ) -> None:
        self.sessions = sessions
        self.store = store

    async def _snapshot(
        self, workspace_id: UUID, document_id: UUID | None, user_id: UUID | None = None
    ) -> _Snapshot:
        # A fresh transaction for each side of physical inspection prevents an ORM cache
        # or a repeatable-read transaction from hiding a newly committed reservation.
        async with self.sessions() as session:
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            await session.execute(text("SET TRANSACTION READ ONLY"))
            if user_id is not None and not await SqlAlchemyAssetRepository(
                session
            ).has_workspace_access(user_id, workspace_id):
                raise AppError("not_found", "The requested resource was not found.", 404)
            documents_query = select(DocumentRecord).where(
                DocumentRecord.workspace_id == workspace_id
            )
            attempts_query = select(UploadAttemptRecord).where(
                UploadAttemptRecord.workspace_id == workspace_id
            )
            originals_query = select(OriginalResourceRecord).where(
                OriginalResourceRecord.workspace_id == workspace_id
            )
            source_scope = AssetSourceRelationRecord.workspace_id == workspace_id
            if document_id is not None:
                documents_query = documents_query.where(DocumentRecord.id == document_id)
                attempts_query = attempts_query.where(
                    UploadAttemptRecord.document_id == document_id
                )
                originals_query = originals_query.where(
                    OriginalResourceRecord.document_id == document_id
                )
                source_scope = source_scope & (AssetSourceRelationRecord.document_id == document_id)
            documents = tuple(await session.scalars(documents_query.order_by(DocumentRecord.id)))
            versions = tuple(
                await session.scalars(
                    select(AssetVersionRecord)
                    .where(AssetVersionRecord.document_id.in_([row.id for row in documents]))
                    .order_by(AssetVersionRecord.id)
                )
            )
            attempts = tuple(await session.scalars(attempts_query.order_by(UploadAttemptRecord.id)))
            originals = tuple(
                await session.scalars(originals_query.order_by(OriginalResourceRecord.id))
            )
            identities = {row.id for row in attempts} | {row.id for row in originals}
            relations = tuple(
                await session.scalars(
                    select(AssetSourceRelationRecord)
                    .where(
                        AssetSourceRelationRecord.participant == PARTICIPANT,
                        or_(source_scope, AssetSourceRelationRecord.resource_id.in_(identities)),
                    )
                    .order_by(AssetSourceRelationRecord.id)
                )
            )
            return _Snapshot(documents, versions, attempts, originals, relations)

    def _inspect_attempt(self, row: UploadAttemptRecord) -> set[str]:
        blockers: set[str] = set()
        if row.state == "open":
            blockers.add("writer_unconfirmed")
        elif row.state == "published":
            blockers.add("unattached_upload")
        elif row.state == "discarding":
            blockers.add("cleanup_unconfirmed")
        try:
            claim = UploadClaim(
                row.id,
                SourceIdentity(row.workspace_id, row.document_id, row.asset_version_id),
                row.user_id,
                row.folder_id,
                row.new_document,
                OriginalStoreBinding(row.store_id, row.binding_id),
                row.suffix,
                row.generation,
            )
            UploadAttempt(claim, row.state, row.revision, row.size, row.sha256)
            if (row.canonical_key, row.temporary_key) != (claim.canonical_key, claim.temporary_key):
                return blockers | {"identity_mismatch"}
            if self.store.binding != claim.binding:
                return blockers | {"binding_mismatch"}
            observed = self.store.observe(claim)
            if observed.temporary_exists:
                blockers.add("temporary_present")
            if row.state == "abandoned":
                if observed.canonical is not None or observed.temporary_exists:
                    blockers.add("abandoned_files_present")
            elif row.state in {"attached", "published"}:
                if row.size is None or row.sha256 is None:
                    return blockers | {"content_mismatch"}
                expected = StoredObject(claim.canonical_key, row.size, row.sha256)
                if observed.canonical is None:
                    blockers.add("canonical_missing")
                elif observed.canonical != expected:
                    blockers.add("content_mismatch")
        except UploadOwnershipError as error:
            blockers.add(error.code)
        except (TypeError, ValueError):
            blockers.add("invalid_claim")
        except Exception:
            # Provider details and paths must not be copied into public diagnostics.
            blockers.add("observation_failed")
        return blockers

    def _reconcile(self, snapshot: _Snapshot) -> set[str]:
        blockers: set[str] = set()
        attempts = {row.id: row for row in snapshot.attempts}
        originals = {row.id: row for row in snapshot.originals}
        versions = {row.id: row for row in snapshot.versions}
        documents = {row.id: row for row in snapshot.documents}
        tracked_versions: set[UUID] = set()
        expected_relations: set[tuple[object, ...]] = set()
        for row in snapshot.originals:
            attempt = attempts.get(row.id)
            version = versions.get(row.asset_version_id)
            if (
                attempt is None
                or version is None
                or attempt.state != "attached"
                or (attempt.workspace_id, attempt.document_id, attempt.asset_version_id)
                != (row.workspace_id, row.document_id, row.asset_version_id)
                or row.revision != 1
                or version.document_id != row.document_id
            ):
                blockers.add("attachment_mismatch")
                continue
            tracked_versions.add(version.id)
            if (version.object_key, version.size, version.sha256) != (
                attempt.canonical_key,
                attempt.size,
                attempt.sha256,
            ):
                blockers.add("content_mismatch")
            expected_relations.add(
                (
                    row.workspace_id,
                    row.document_id,
                    row.asset_version_id,
                    "original",
                    row.id,
                    row.revision,
                    "source_copy",
                )
            )
        actual_relations = {
            (
                row.workspace_id,
                row.document_id,
                row.asset_version_id,
                row.kind,
                row.resource_id,
                row.resource_revision,
                row.relation_kind,
            )
            for row in snapshot.relations
        }
        if actual_relations != expected_relations:
            blockers.add("relation_mismatch")
        if set(versions) - tracked_versions:
            blockers.add("legacy_untracked")
        for reservation in snapshot.attempts:
            if reservation.state == "attached" and reservation.id not in originals:
                blockers.add("attachment_mismatch")
            if reservation.state in {"open", "published"} and not reservation.new_document:
                document = documents.get(reservation.document_id)
                if document is None:
                    blockers.add("source_unavailable")
                elif document.lifecycle_generation != reservation.generation:
                    blockers.add("generation_mismatch")
        return blockers

    async def collect(self, workspace_id: UUID, document_id: UUID) -> OriginalInventory:
        """Trusted participant boundary; callers must authorize document access separately."""
        before = await self._snapshot(workspace_id, document_id)
        blockers = self._reconcile(before)
        if not before.documents and not before.attempts:
            blockers.add("source_unavailable")
        resources = {
            ResourceIdentity(PARTICIPANT, "original", row.id, row.revision)
            for row in before.originals
        }
        for row in before.attempts:
            blockers.update(self._inspect_attempt(row))
            if row.state != "attached":
                resources.add(ResourceIdentity(PARTICIPANT, "upload_attempt", row.id, row.revision))
        after = await self._snapshot(workspace_id, document_id)
        if before.fingerprint() != after.fingerprint():
            blockers.add("inventory_changed")
        return OriginalInventory(
            tuple(sorted(resources, key=lambda item: (item.kind, str(item.resource_id)))),
            tuple(sorted(blockers)),
            not blockers,
        )

    async def list_unattached(self, user_id: UUID, workspace_id: UUID) -> UnattachedUploads:
        before = await self._snapshot(workspace_id, None, user_id)
        items: list[UnattachedUpload] = []
        blockers: set[str] = set()
        for row in before.attempts:
            if row.state == "attached":
                continue
            reasons = self._inspect_attempt(row)
            if any(resource.id == row.id for resource in before.originals):
                reasons.add("attachment_mismatch")
            if any(relation.resource_id == row.id for relation in before.relations):
                reasons.add("relation_mismatch")
            if row.state in {"open", "published"} and not row.new_document:
                document = next(
                    (item for item in before.documents if item.id == row.document_id), None
                )
                if document is None:
                    reasons.add("source_unavailable")
                elif document.lifecycle_generation != row.generation:
                    reasons.add("generation_mismatch")
            blockers.update(reasons)
            items.append(
                UnattachedUpload(
                    row.id,
                    SourceIdentity(row.workspace_id, row.document_id, row.asset_version_id),
                    row.state,
                    row.revision,
                    tuple(sorted(reasons)),
                )
            )
        after = await self._snapshot(workspace_id, None, user_id)
        if before.fingerprint() != after.fingerprint():
            blockers.add("inventory_changed")
        return UnattachedUploads(tuple(items), tuple(sorted(blockers)), not blockers)
