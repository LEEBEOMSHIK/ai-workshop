from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity
from ai_workshop.platform.assets.purge_contracts import CleanupReceipt
from ai_workshop.platform.assets.purge_inventory_contracts import (
    BoundCleanupReceipt,
    DocumentTarget,
    FolderTarget,
    ParticipantInventory,
    PurgeInventory,
)
from ai_workshop.platform.assets.purge_inventory_models import (
    AssetPurgeInventoryParticipantRecord,
    AssetPurgeInventoryRecord,
    AssetPurgeInventoryResourceRecord,
    AssetPurgeInventoryTargetRecord,
    AssetPurgeReceiptRecord,
)
from ai_workshop.platform.assets.purge_proof_models import (
    AssetPurgeProofParticipantRecord,
    AssetPurgeProofTargetRecord,
)


def _add_inventory_details(
    session: AsyncSession,
    inventory_id: UUID,
    inventory: PurgeInventory,
) -> None:
    targets: list[AssetPurgeInventoryTargetRecord] = []
    for document in inventory.documents:
        targets.extend(
            AssetPurgeInventoryTargetRecord(
                workspace_id=inventory.workspace_id,
                inventory_id=inventory_id,
                target_kind="document",
                target_id=document.document_id,
                generation=document.generation,
                asset_version_id=asset_version_id,
            )
            for asset_version_id in document.asset_version_ids
        )
    targets.extend(
        AssetPurgeInventoryTargetRecord(
            workspace_id=inventory.workspace_id,
            inventory_id=inventory_id,
            target_kind="folder",
            target_id=folder.folder_id,
            generation=folder.generation,
            asset_version_id=None,
        )
        for folder in inventory.folders
    )
    session.add_all(targets)
    for participant in inventory.participants:
        session.add(
            AssetPurgeInventoryParticipantRecord(
                workspace_id=inventory.workspace_id,
                inventory_id=inventory_id,
                participant=participant.participant,
                contract_version=participant.contract_version,
                exhausted=participant.exhausted,
                supported=participant.supported,
                legacy_resolved=participant.legacy_resolved,
            )
        )
        session.add_all(
            AssetPurgeInventoryResourceRecord(
                workspace_id=inventory.workspace_id,
                inventory_id=inventory_id,
                participant=participant.participant,
                kind=resource.kind,
                resource_id=resource.resource_id,
                resource_revision=resource.revision,
            )
            for resource in participant.resources
        )


async def _reconstruct_inventory(
    session: AsyncSession,
    record: AssetPurgeInventoryRecord,
) -> PurgeInventory:
    targets = (
        await session.scalars(
            select(AssetPurgeInventoryTargetRecord)
            .where(AssetPurgeInventoryTargetRecord.inventory_id == record.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    participants = (
        await session.scalars(
            select(AssetPurgeInventoryParticipantRecord)
            .where(AssetPurgeInventoryParticipantRecord.inventory_id == record.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    resources = (
        await session.scalars(
            select(AssetPurgeInventoryResourceRecord)
            .where(AssetPurgeInventoryResourceRecord.inventory_id == record.id)
            .execution_options(populate_existing=True)
        )
    ).all()

    document_data: dict[UUID, tuple[int, list[UUID]]] = {}
    folders: list[FolderTarget] = []
    for target in targets:
        if target.target_kind == "folder":
            folders.append(FolderTarget(target.target_id, target.generation))
            continue
        if target.asset_version_id is None:
            raise ValueError("persisted document target is missing an asset version")
        generation, version_ids = document_data.setdefault(
            target.target_id,
            (target.generation, []),
        )
        if generation != target.generation:
            raise ValueError("persisted document target has mixed generations")
        version_ids.append(target.asset_version_id)

    resources_by_participant: dict[str, list[ResourceIdentity]] = {
        participant.participant: [] for participant in participants
    }
    for resource in resources:
        resources_by_participant[resource.participant].append(
            ResourceIdentity(
                participant=resource.participant,
                kind=resource.kind,
                resource_id=resource.resource_id,
                revision=resource.resource_revision,
            )
        )
    return PurgeInventory(
        workspace_id=record.workspace_id,
        job_id=record.job_id,
        version=record.version,
        documents=tuple(
            DocumentTarget(document_id, generation, tuple(sorted(version_ids)))
            for document_id, (generation, version_ids) in sorted(
                document_data.items(), key=lambda item: str(item[0])
            )
        ),
        folders=tuple(sorted(folders, key=lambda item: str(item.folder_id))),
        participants=tuple(
            ParticipantInventory(
                participant=participant.participant,
                contract_version=participant.contract_version,
                resources=tuple(
                    sorted(
                        resources_by_participant[participant.participant],
                        key=lambda item: (
                            item.kind,
                            str(item.resource_id),
                            item.revision,
                        ),
                    )
                ),
                exhausted=participant.exhausted,
                supported=participant.supported,
                legacy_resolved=participant.legacy_resolved,
            )
            for participant in sorted(participants, key=lambda item: item.participant)
        ),
    )


def _add_proof_details(
    session: AsyncSession,
    proof_id: UUID,
    inventory: PurgeInventory,
    receipts: tuple[BoundCleanupReceipt, ...],
) -> None:
    targets: list[AssetPurgeProofTargetRecord] = []
    for document in inventory.documents:
        targets.extend(
            AssetPurgeProofTargetRecord(
                proof_id=proof_id,
                target_kind="document",
                target_id=document.document_id,
                generation=document.generation,
                asset_version_id=asset_version_id,
            )
            for asset_version_id in document.asset_version_ids
        )
    targets.extend(
        AssetPurgeProofTargetRecord(
            proof_id=proof_id,
            target_kind="folder",
            target_id=folder.folder_id,
            generation=folder.generation,
            asset_version_id=None,
        )
        for folder in inventory.folders
    )
    session.add_all(targets)
    session.add_all(
        AssetPurgeProofParticipantRecord(
            proof_id=proof_id,
            participant=receipt.receipt.participant,
            contract_version=receipt.participant_contract_version,
            attempt=receipt.attempt,
            checked_at=receipt.checked_at.astimezone(UTC),
            deleted=receipt.receipt.deleted,
            retained_shared=receipt.receipt.retained_shared,
            residual_owned=receipt.receipt.residual_owned,
            verified=receipt.receipt.verified,
        )
        for receipt in receipts
    )


def _bound_receipt(
    *,
    job_id: UUID,
    inventory_version: int,
    record: AssetPurgeReceiptRecord,
) -> BoundCleanupReceipt:
    return BoundCleanupReceipt(
        job_id=job_id,
        inventory_version=inventory_version,
        inventory_binding=record.binding,
        participant_contract_version=record.contract_version,
        attempt=record.attempt,
        checked_at=_utc(record.checked_at),
        receipt=CleanupReceipt(
            participant=record.participant,
            deleted=record.deleted,
            retained_shared=record.retained_shared,
            residual_owned=record.residual_owned,
            verified=record.verified,
        ),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("persisted receipt timestamp must be timezone-aware")
    return value.astimezone(UTC)
