from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.assets.models import (
    AssetVersionRecord,
    DocumentRecord,
    FolderRecord,
)
from ai_workshop.platform.assets.purge_inventory_contracts import (
    BoundCleanupReceipt,
    PurgeInventory,
    assess_bound_purge,
    inventory_binding,
    proof_binding,
)
from ai_workshop.platform.assets.purge_inventory_models import (
    AssetPurgeInventoryParticipantRecord,
    AssetPurgeInventoryRecord,
    AssetPurgeReceiptRecord,
)
from ai_workshop.platform.assets.purge_inventory_storage import (
    _add_inventory_details,
    _add_proof_details,
    _bound_receipt,
    _reconstruct_inventory,
)
from ai_workshop.platform.assets.purge_models import AssetPurgeJobRecord
from ai_workshop.platform.assets.purge_proof_models import (
    AssetPurgeProofRecord,
)
from ai_workshop.platform.assets.trash_models import (
    AssetRetentionPolicyRecord,
    AssetTrashBatchRecord,
)


class PurgeInventoryRepository:
    """Internal persistence adapter; it does not authorize or execute deletion."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_inventory(self, inventory: PurgeInventory) -> None:
        if not isinstance(inventory, PurgeInventory):
            raise TypeError("inventory must be a PurgeInventory")
        job = await self._lock_job(inventory.workspace_id, inventory.job_id)
        if job.status == "purged":
            raise ValueError("completed job cannot accept an inventory")

        await self._require_exact_batch_targets(inventory, job.trash_batch_id)
        latest_version = await self.session.scalar(
            select(func.max(AssetPurgeInventoryRecord.version)).where(
                AssetPurgeInventoryRecord.workspace_id == inventory.workspace_id,
                AssetPurgeInventoryRecord.job_id == inventory.job_id,
            )
        )
        expected_version = 1 if latest_version is None else latest_version + 1
        if inventory.version != expected_version:
            raise ValueError(
                f"inventory version must be the next sequential version {expected_version}"
            )

        record = AssetPurgeInventoryRecord(
            workspace_id=inventory.workspace_id,
            job_id=inventory.job_id,
            version=inventory.version,
            binding=inventory_binding(inventory),
        )
        self.session.add(record)
        await self.session.flush()
        _add_inventory_details(self.session, record.id, inventory)
        await self.session.flush()

    async def load_inventory(
        self,
        workspace_id: UUID,
        job_id: UUID,
        version: int,
    ) -> PurgeInventory | None:
        record = await self.session.scalar(
            select(AssetPurgeInventoryRecord).where(
                AssetPurgeInventoryRecord.workspace_id == workspace_id,
                AssetPurgeInventoryRecord.job_id == job_id,
                AssetPurgeInventoryRecord.version == version,
            ).execution_options(populate_existing=True)
        )
        if record is None:
            return None
        inventory = await _reconstruct_inventory(self.session, record)
        if inventory_binding(inventory) != record.binding:
            raise ValueError("persisted inventory details do not match its binding")
        return inventory

    async def save_receipt(
        self,
        workspace_id: UUID,
        receipt: BoundCleanupReceipt,
    ) -> None:
        if not isinstance(receipt, BoundCleanupReceipt):
            raise TypeError("receipt must be a BoundCleanupReceipt")
        job = await self._lock_job(workspace_id, receipt.job_id)
        if job.status == "purged":
            raise ValueError("completed job cannot accept a receipt")
        if job.attempt_count != receipt.attempt:
            raise ValueError("receipt attempt must match the current job attempt")

        inventory_record = await self.session.scalar(
            select(AssetPurgeInventoryRecord)
            .where(
                AssetPurgeInventoryRecord.workspace_id == workspace_id,
                AssetPurgeInventoryRecord.job_id == receipt.job_id,
            )
            .order_by(AssetPurgeInventoryRecord.version.desc())
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            inventory_record is None
            or receipt.inventory_version != inventory_record.version
            or receipt.inventory_binding != inventory_record.binding
        ):
            raise ValueError("receipt must match the latest inventory")
        participant = await self.session.scalar(
            select(AssetPurgeInventoryParticipantRecord).where(
                AssetPurgeInventoryParticipantRecord.workspace_id == workspace_id,
                AssetPurgeInventoryParticipantRecord.inventory_id
                == inventory_record.id,
                AssetPurgeInventoryParticipantRecord.participant
                == receipt.receipt.participant,
            ).execution_options(populate_existing=True)
        )
        if (
            participant is None
            or participant.contract_version
            != receipt.participant_contract_version
        ):
            raise ValueError("receipt participant contract must match the inventory")
        duplicate = await self.session.scalar(
            select(AssetPurgeReceiptRecord).where(
                AssetPurgeReceiptRecord.inventory_id == inventory_record.id,
                AssetPurgeReceiptRecord.participant == receipt.receipt.participant,
                AssetPurgeReceiptRecord.attempt == receipt.attempt,
            )
        )
        if duplicate is not None:
            raise ValueError("duplicate receipt for inventory participant attempt")

        self.session.add(
            AssetPurgeReceiptRecord(
                workspace_id=workspace_id,
                inventory_id=inventory_record.id,
                participant=receipt.receipt.participant,
                attempt=receipt.attempt,
                checked_at=receipt.checked_at.astimezone(UTC),
                binding=receipt.inventory_binding,
                contract_version=receipt.participant_contract_version,
                deleted=receipt.receipt.deleted,
                retained_shared=receipt.receipt.retained_shared,
                residual_owned=receipt.receipt.residual_owned,
                verified=receipt.receipt.verified,
            )
        )
        await self.session.flush()

    async def store_proof(
        self,
        *,
        inventory: PurgeInventory,
        receipts: tuple[BoundCleanupReceipt, ...],
        required_participants: frozenset[str],
        actor_id: UUID,
        policy_version: int,
        finished_at: datetime,
        writers_stopped: bool = False,
        references_cleared: bool = False,
    ) -> UUID:
        """Store a candidate proof without deleting details or completing the job.

        Caller booleans feed the pure contract only. They do not authenticate current
        writer, authorization, or reference evidence; a future completion service must
        verify those gates before using this internal adapter in its transaction.
        """

        if not isinstance(inventory, PurgeInventory):
            raise TypeError("inventory must be a PurgeInventory")
        if type(receipts) is not tuple or any(
            not isinstance(receipt, BoundCleanupReceipt) for receipt in receipts
        ):
            raise TypeError("receipts must be a tuple of BoundCleanupReceipt values")
        if type(actor_id) is not UUID:
            raise TypeError("actor_id must be a UUID")
        if isinstance(policy_version, bool) or not isinstance(policy_version, int):
            raise TypeError("policy_version must be an integer")
        if policy_version <= 0:
            raise ValueError("policy_version must be positive")
        if not isinstance(finished_at, datetime):
            raise TypeError("finished_at must be a datetime")
        if finished_at.tzinfo is None or finished_at.utcoffset() != timedelta(0):
            raise ValueError("finished_at must be UTC-aware")

        job = await self._lock_job(inventory.workspace_id, inventory.job_id)
        if job.status != "purging" or job.attempt_count <= 0:
            raise ValueError("proof requires an active purge execution")
        batch_context = (
            await self.session.execute(
                select(
                    AssetTrashBatchRecord.actor_id,
                    AssetRetentionPolicyRecord.version,
                )
                .join(
                    AssetRetentionPolicyRecord,
                    AssetRetentionPolicyRecord.id
                    == AssetTrashBatchRecord.policy_version_id,
                )
                .where(
                    AssetTrashBatchRecord.workspace_id == inventory.workspace_id,
                    AssetTrashBatchRecord.id == job.trash_batch_id,
                )
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if batch_context is None:
            raise ValueError("purge batch policy context is missing")
        batch_actor_id, batch_policy_version = batch_context
        if actor_id != batch_actor_id:
            raise ValueError("proof actor must match the purge batch actor")
        if policy_version != batch_policy_version:
            raise ValueError("proof policy version must match the purge batch policy")

        inventory_record = await self.session.scalar(
            select(AssetPurgeInventoryRecord)
            .where(
                AssetPurgeInventoryRecord.workspace_id == inventory.workspace_id,
                AssetPurgeInventoryRecord.job_id == inventory.job_id,
            )
            .order_by(AssetPurgeInventoryRecord.version.desc())
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if inventory_record is None:
            raise ValueError("persisted inventory is missing")
        persisted_inventory = await _reconstruct_inventory(
            self.session, inventory_record
        )
        if (
            inventory.version != inventory_record.version
            or inventory_binding(inventory) != inventory_record.binding
            or inventory_binding(persisted_inventory) != inventory_record.binding
        ):
            raise ValueError("candidate must match the persisted latest inventory")

        receipt_records = (
            await self.session.scalars(
                select(AssetPurgeReceiptRecord)
                .where(
                    AssetPurgeReceiptRecord.inventory_id == inventory_record.id,
                    AssetPurgeReceiptRecord.attempt == job.attempt_count,
                )
                .order_by(AssetPurgeReceiptRecord.participant)
                .execution_options(populate_existing=True)
            )
        ).all()
        persisted_receipts = tuple(
            _bound_receipt(
                job_id=inventory.job_id,
                inventory_version=inventory.version,
                record=record,
            )
            for record in receipt_records
        )
        if (
            not persisted_receipts
            or len(receipts) != len(persisted_receipts)
            or frozenset(receipts) != frozenset(persisted_receipts)
            or any(receipt.attempt != job.attempt_count for receipt in receipts)
        ):
            raise ValueError("candidate receipts must exactly match persisted receipts")
        decision = assess_bound_purge(
            inventory=persisted_inventory,
            required_participants=required_participants,
            receipts=persisted_receipts,
            attempt=job.attempt_count,
            writers_stopped=writers_stopped,
            references_cleared=references_cleared,
        )
        if not decision.online_complete:
            raise ValueError("proof candidate must be complete")
        duplicate = await self.session.scalar(
            select(AssetPurgeProofRecord.id).where(
                AssetPurgeProofRecord.workspace_id == inventory.workspace_id,
                AssetPurgeProofRecord.job_id == inventory.job_id,
            )
        )
        if duplicate is not None:
            raise ValueError("proof already exists for purge job")

        proof = AssetPurgeProofRecord(
            workspace_id=inventory.workspace_id,
            job_id=inventory.job_id,
            inventory_version=inventory.version,
            inventory_binding=inventory_record.binding,
            binding=proof_binding(
                inventory=persisted_inventory,
                receipts=persisted_receipts,
                required_participants=required_participants,
            ),
            actor_id=actor_id,
            policy_version=policy_version,
            finished_at=finished_at.astimezone(UTC),
        )
        self.session.add(proof)
        await self.session.flush()
        _add_proof_details(
            self.session,
            proof.id,
            persisted_inventory,
            persisted_receipts,
        )
        await self.session.flush()
        return proof.id

    async def _lock_job(
        self,
        workspace_id: UUID,
        job_id: UUID,
    ) -> AssetPurgeJobRecord:
        job = await self.session.scalar(
            select(AssetPurgeJobRecord)
            .where(
                AssetPurgeJobRecord.workspace_id == workspace_id,
                AssetPurgeJobRecord.id == job_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None:
            raise ValueError("purge job does not match workspace")
        return job

    async def _require_exact_batch_targets(
        self,
        inventory: PurgeInventory,
        batch_id: UUID,
    ) -> None:
        locked_batch_id = await self.session.scalar(
            select(AssetTrashBatchRecord.id)
            .where(
                AssetTrashBatchRecord.workspace_id == inventory.workspace_id,
                AssetTrashBatchRecord.id == batch_id,
            )
            .with_for_update()
        )
        if locked_batch_id is None:
            raise ValueError("purge batch does not match workspace")
        document_rows = (
            await self.session.execute(
                select(
                    DocumentRecord.id,
                    DocumentRecord.lifecycle_generation,
                )
                .where(
                    DocumentRecord.workspace_id == inventory.workspace_id,
                    DocumentRecord.trash_batch_id == batch_id,
                )
                .with_for_update()
            )
        ).all()
        folder_rows = (
            await self.session.execute(
                select(
                    FolderRecord.id,
                    FolderRecord.lifecycle_generation,
                )
                .where(
                    FolderRecord.workspace_id == inventory.workspace_id,
                    FolderRecord.trash_batch_id == batch_id,
                )
                .with_for_update()
            )
        ).all()
        version_rows = (
            await self.session.execute(
                select(AssetVersionRecord.document_id, AssetVersionRecord.id)
                .join(
                    DocumentRecord,
                    DocumentRecord.id == AssetVersionRecord.document_id,
                )
                .where(
                    DocumentRecord.workspace_id == inventory.workspace_id,
                    DocumentRecord.trash_batch_id == batch_id,
                )
                .with_for_update(of=AssetVersionRecord)
            )
        ).all()

        versions_by_document: dict[UUID, set[UUID]] = {
            document_id: set() for document_id, _ in document_rows
        }
        for document_id, asset_version_id in version_rows:
            versions_by_document[document_id].add(asset_version_id)
        expected_documents = {
            document_id: (generation, frozenset(versions_by_document[document_id]))
            for document_id, generation in document_rows
        }
        actual_documents = {
            target.document_id: (
                target.generation,
                frozenset(target.asset_version_ids),
            )
            for target in inventory.documents
        }
        expected_folders = {
            folder_id: generation for folder_id, generation in folder_rows
        }
        actual_folders = {
            target.folder_id: target.generation for target in inventory.folders
        }
        if (
            expected_documents != actual_documents
            or expected_folders != actual_folders
            or any(not versions for _, versions in expected_documents.values())
        ):
            raise ValueError(
                "inventory targets, versions, and generations must exactly match the batch"
            )
