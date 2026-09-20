"""Fresh read-only intake reconciliation; expose opaque identities and fixed codes only."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.platform.assets.intake_contracts import UploadIntakeClaim
from ai_workshop.platform.assets.intake_models import UploadIntakeRecord
from ai_workshop.platform.assets.intake_repository import PARTICIPANT, record_claim
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.purge_inventory_contracts import ParticipantInventory
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.temporary_contracts import TemporaryBinding
from ai_workshop.platform.assets.upload_models import OriginalResourceRecord, UploadAttemptRecord
from ai_workshop.platform.assets.upload_repository import claim_from_record
from ai_workshop.shared.errors import AppError
from ai_workshop.shared.models import Base


class IntakeInventoryStore(Protocol):
    @property
    def binding(self) -> TemporaryBinding: ...

    def observe(self, claim: UploadIntakeClaim) -> bool: ...


@dataclass(frozen=True)
class IntakeInventory:
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
class UnattachedIntake:
    intake_id: UUID
    state: str
    revision: int
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class UnattachedIntakes:
    items: tuple[UnattachedIntake, ...]
    blockers: tuple[str, ...]
    complete: bool
    exhausted: bool = True


@dataclass(frozen=True)
class _Snapshot:
    intakes: tuple[UploadIntakeRecord, ...]
    documents: tuple[DocumentRecord, ...]
    versions: tuple[AssetVersionRecord, ...]
    attempts: tuple[UploadAttemptRecord, ...]
    originals: tuple[OriginalResourceRecord, ...]
    relations: tuple[AssetSourceRelationRecord, ...]

    def fingerprint(self) -> tuple[tuple[tuple[object, ...], ...], ...]:
        groups: tuple[tuple[Base, ...], ...] = (
            self.intakes,
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


class UploadIntakeInventory:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], store: IntakeInventoryStore
    ) -> None:
        self.sessions, self.store = sessions, store

    async def _snapshot(
        self, workspace_id: UUID, document_id: UUID | None, user_id: UUID | None = None
    ) -> _Snapshot:
        async with self.sessions() as session:
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            await session.execute(text("SET TRANSACTION READ ONLY"))
            if user_id is not None and not await SqlAlchemyAssetRepository(
                session
            ).has_workspace_access(user_id, workspace_id):
                raise AppError("not_found", "The requested resource was not found.", 404)
            scope = UploadIntakeRecord.workspace_id == workspace_id
            docs = DocumentRecord.workspace_id == workspace_id
            relation_scope = AssetSourceRelationRecord.workspace_id == workspace_id
            if document_id is not None:
                scope &= UploadIntakeRecord.document_id == document_id
                docs &= DocumentRecord.id == document_id
                relation_scope &= AssetSourceRelationRecord.document_id == document_id
            intakes = tuple(
                await session.scalars(
                    select(UploadIntakeRecord).where(scope).order_by(UploadIntakeRecord.id)
                )
            )
            documents = tuple(
                await session.scalars(
                    select(DocumentRecord).where(docs).order_by(DocumentRecord.id)
                )
            )
            versions = tuple(
                await session.scalars(
                    select(AssetVersionRecord)
                    .where(AssetVersionRecord.document_id.in_([row.id for row in documents]))
                    .order_by(AssetVersionRecord.id)
                )
            )
            ids = [
                row.original_attempt_id for row in intakes if row.original_attempt_id is not None
            ]
            attempts = tuple(
                await session.scalars(
                    select(UploadAttemptRecord)
                    .where(UploadAttemptRecord.id.in_(ids))
                    .order_by(UploadAttemptRecord.id)
                )
            )
            originals = tuple(
                await session.scalars(
                    select(OriginalResourceRecord)
                    .where(OriginalResourceRecord.id.in_(ids))
                    .order_by(OriginalResourceRecord.id)
                )
            )
            relations = tuple(
                await session.scalars(
                    select(AssetSourceRelationRecord)
                    .where(
                        AssetSourceRelationRecord.participant.in_(
                            [PARTICIPANT, "platform_originals"]
                        ),
                        or_(
                            relation_scope,
                            AssetSourceRelationRecord.resource_id.in_(
                                [row.id for row in intakes] + ids
                            ),
                        ),
                    )
                    .order_by(AssetSourceRelationRecord.id)
                )
            )
            return _Snapshot(intakes, documents, versions, attempts, originals, relations)

    def _inspect(self, row: UploadIntakeRecord) -> set[str]:
        blockers: set[str] = set()
        if row.state == "open":
            blockers.add("writer_unconfirmed")
        elif row.state != "cleaned":
            blockers.add("cleanup_unconfirmed")
        try:
            claim = record_claim(row)
            if claim.binding != self.store.binding:
                return blockers | {"binding_mismatch"}
            observed = self.store.observe(claim)
            if type(observed) is not bool:
                blockers.add("observation_failed")
            elif observed:
                blockers.add("temporary_present")
        except (ValueError, TypeError):
            blockers.add("invalid_claim")
        except Exception:
            blockers.add("observation_failed")
        return blockers

    def _reconcile(self, snapshot: _Snapshot) -> set[str]:
        # No migration can prove absence of historical, untracked HTTP spool files.
        blockers: set[str] = {"legacy_untracked"}
        attempts = {row.id: row for row in snapshot.attempts}
        originals = {row.id: row for row in snapshot.originals}
        versions = {row.id: row for row in snapshot.versions}
        documents = {row.id: row for row in snapshot.documents}
        expected = set()
        tracked = set()
        for row in snapshot.intakes:
            try:
                claim = record_claim(row)
            except (ValueError, TypeError):
                blockers.add("invalid_claim")
                continue
            attempt = attempts.get(claim.original_attempt_id) if claim.original_attempt_id else None
            original = (
                originals.get(claim.original_attempt_id) if claim.original_attempt_id else None
            )
            if claim.original_attempt_id is not None:
                try:
                    candidate = claim_from_record(attempt) if attempt is not None else None
                    if candidate is None or (
                        candidate.source,
                        candidate.user_id,
                        candidate.new_document,
                        candidate.generation,
                    ) != (claim.source, claim.user_id, claim.new_document, claim.generation):
                        blockers.add("original_mismatch")
                except (ValueError, TypeError):
                    blockers.add("original_mismatch")
            if claim.attached:
                tracked.add(claim.source.asset_version_id)
                expected.add(
                    (
                        row.workspace_id,
                        row.document_id,
                        row.asset_version_id,
                        "intake",
                        row.id,
                        row.revision,
                        "source_copy",
                    )
                )
                version = versions.get(row.asset_version_id)
                if (
                    original is None
                    or attempt is None
                    or attempt.state != "attached"
                    or (original.workspace_id, original.document_id, original.asset_version_id)
                    != (row.workspace_id, row.document_id, row.asset_version_id)
                ):
                    blockers.add("attachment_mismatch")
                elif version is None or (version.object_key, version.size, version.sha256) != (
                    attempt.canonical_key,
                    attempt.size,
                    attempt.sha256,
                ):
                    blockers.add("source_mismatch")
                if original is not None:
                    matches = [
                        r
                        for r in snapshot.relations
                        if r.participant == "platform_originals" and r.resource_id == original.id
                    ]
                    if len(matches) != 1 or (
                        matches[0].workspace_id,
                        matches[0].document_id,
                        matches[0].asset_version_id,
                        matches[0].kind,
                        matches[0].resource_revision,
                        matches[0].relation_kind,
                    ) != (
                        row.workspace_id,
                        row.document_id,
                        row.asset_version_id,
                        "original",
                        1,
                        "source_copy",
                    ):
                        blockers.add("original_relation_mismatch")
            elif original is not None or (attempt is not None and attempt.state == "attached"):
                blockers.add("attachment_mismatch")
            if not claim.new_document and claim.state == "open":
                document = documents.get(row.document_id)
                if document is None or document.lifecycle != "active":
                    blockers.add("source_unavailable")
                elif document.lifecycle_generation != claim.generation:
                    blockers.add("generation_mismatch")
        actual = {
            (
                r.workspace_id,
                r.document_id,
                r.asset_version_id,
                r.kind,
                r.resource_id,
                r.resource_revision,
                r.relation_kind,
            )
            for r in snapshot.relations
            if r.participant == PARTICIPANT
        }
        if expected != actual:
            blockers.add("relation_mismatch")
        if set(versions) - tracked:
            blockers.add("legacy_untracked")
        return blockers

    async def collect(self, workspace_id: UUID, document_id: UUID) -> IntakeInventory:
        """Trusted participant boundary; caller separately authorizes the document."""
        before = await self._snapshot(workspace_id, document_id)
        blockers = self._reconcile(before)
        if not before.documents and not before.intakes:
            blockers.add("source_unavailable")
        for row in before.intakes:
            blockers.update(self._inspect(row))
        after = await self._snapshot(workspace_id, document_id)
        if before.fingerprint() != after.fingerprint():
            blockers.add("inventory_changed")
        resources = tuple(
            ResourceIdentity(PARTICIPANT, "intake", row.id, row.revision) for row in before.intakes
        )
        return IntakeInventory(resources, tuple(sorted(blockers)), not blockers)

    async def list_unattached(self, user_id: UUID, workspace_id: UUID) -> UnattachedIntakes:
        before = await self._snapshot(workspace_id, None, user_id)
        blockers = self._reconcile(before)
        items = []
        for row in before.intakes:
            if row.attached:
                continue
            reasons = self._inspect(row)
            blockers.update(reasons)
            items.append(UnattachedIntake(row.id, row.state, row.revision, tuple(sorted(reasons))))
        after = await self._snapshot(workspace_id, None, user_id)
        if before.fingerprint() != after.fingerprint():
            blockers.add("inventory_changed")
        return UnattachedIntakes(tuple(items), tuple(sorted(blockers)), not blockers)
