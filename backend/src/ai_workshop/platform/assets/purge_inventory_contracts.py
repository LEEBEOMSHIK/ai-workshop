import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from ai_workshop.platform.assets.provenance_contracts import (
    ResourceIdentity,
    _validate_machine_identifier,
    _validate_positive_integer,
    _validate_uuid,
)
from ai_workshop.platform.assets.purge_contracts import (
    CleanupReceipt,
    PurgeDecision,
    assess_purge,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _validate_tuple(value: object, field_name: str) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{field_name} must be a tuple")


def _validate_actual_bool(value: object, field_name: str) -> None:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a boolean")


@dataclass(frozen=True)
class DocumentTarget:
    document_id: UUID
    generation: int
    asset_version_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        _validate_uuid(self.document_id, "document_id")
        _validate_positive_integer(self.generation, "generation")
        _validate_tuple(self.asset_version_ids, "asset_version_ids")
        if not self.asset_version_ids:
            raise ValueError("asset_version_ids must not be empty")
        for asset_version_id in self.asset_version_ids:
            _validate_uuid(asset_version_id, "asset_version_ids")
        if len(self.asset_version_ids) != len(set(self.asset_version_ids)):
            raise ValueError("asset_version_ids must not contain duplicates")


@dataclass(frozen=True)
class FolderTarget:
    folder_id: UUID
    generation: int

    def __post_init__(self) -> None:
        _validate_uuid(self.folder_id, "folder_id")
        _validate_positive_integer(self.generation, "generation")


@dataclass(frozen=True)
class ParticipantInventory:
    participant: str
    contract_version: int
    resources: tuple[ResourceIdentity, ...]
    exhausted: bool
    supported: bool
    legacy_resolved: bool

    def __post_init__(self) -> None:
        _validate_machine_identifier(self.participant, "participant")
        _validate_positive_integer(self.contract_version, "contract_version")
        _validate_tuple(self.resources, "resources")
        for resource in self.resources:
            if not isinstance(resource, ResourceIdentity):
                raise TypeError("resources must contain ResourceIdentity values")
            if resource.participant != self.participant:
                raise ValueError("resource participant must match participant")
        if len(self.resources) != len(set(self.resources)):
            raise ValueError("resources must not contain duplicates")
        _validate_actual_bool(self.exhausted, "exhausted")
        _validate_actual_bool(self.supported, "supported")
        _validate_actual_bool(self.legacy_resolved, "legacy_resolved")


@dataclass(frozen=True)
class PurgeInventory:
    workspace_id: UUID
    job_id: UUID
    version: int
    documents: tuple[DocumentTarget, ...]
    folders: tuple[FolderTarget, ...]
    participants: tuple[ParticipantInventory, ...]

    def __post_init__(self) -> None:
        _validate_uuid(self.workspace_id, "workspace_id")
        _validate_uuid(self.job_id, "job_id")
        _validate_positive_integer(self.version, "version")
        _validate_tuple(self.documents, "documents")
        _validate_tuple(self.folders, "folders")
        _validate_tuple(self.participants, "participants")
        if any(not isinstance(document, DocumentTarget) for document in self.documents):
            raise TypeError("documents must contain DocumentTarget values")
        if any(not isinstance(folder, FolderTarget) for folder in self.folders):
            raise TypeError("folders must contain FolderTarget values")
        if any(
            not isinstance(participant, ParticipantInventory) for participant in self.participants
        ):
            raise TypeError("participants must contain ParticipantInventory values")
        if len({target.document_id for target in self.documents}) != len(self.documents):
            raise ValueError("documents must not contain duplicate document ids")
        if len({target.folder_id for target in self.folders}) != len(self.folders):
            raise ValueError("folders must not contain duplicate folder ids")
        if len({item.participant for item in self.participants}) != len(self.participants):
            raise ValueError("participants must not contain duplicate participant keys")


@dataclass(frozen=True)
class BoundCleanupReceipt:
    job_id: UUID
    inventory_version: int
    inventory_binding: str
    participant_contract_version: int
    attempt: int
    checked_at: datetime
    receipt: CleanupReceipt

    def __post_init__(self) -> None:
        _validate_uuid(self.job_id, "job_id")
        _validate_positive_integer(self.inventory_version, "inventory_version")
        if type(self.inventory_binding) is not str:
            raise TypeError("inventory_binding must be a string")
        if _SHA256.fullmatch(self.inventory_binding) is None:
            raise ValueError("inventory_binding must be a lowercase SHA-256 digest")
        _validate_positive_integer(
            self.participant_contract_version,
            "participant_contract_version",
        )
        _validate_positive_integer(self.attempt, "attempt")
        if not isinstance(self.checked_at, datetime):
            raise TypeError("checked_at must be a datetime")
        try:
            offset = self.checked_at.utcoffset()
        except (OverflowError, ValueError) as error:
            raise ValueError("checked_at must be UTC-aware") from error
        if self.checked_at.tzinfo is None or offset != timedelta(0):
            raise ValueError("checked_at must be UTC-aware")
        if not isinstance(self.receipt, CleanupReceipt):
            raise TypeError("receipt must be a CleanupReceipt")
        _validate_machine_identifier(self.receipt.participant, "receipt participant")
        _validate_actual_bool(self.receipt.verified, "verified")


def _inventory_payload(inventory: PurgeInventory) -> dict[str, Any]:
    documents = [
        {
            "asset_version_ids": sorted(str(item) for item in target.asset_version_ids),
            "document_id": str(target.document_id),
            "generation": target.generation,
        }
        for target in sorted(inventory.documents, key=lambda item: str(item.document_id))
    ]
    folders = [
        {"folder_id": str(target.folder_id), "generation": target.generation}
        for target in sorted(inventory.folders, key=lambda item: str(item.folder_id))
    ]
    participants = [
        {
            "contract_version": item.contract_version,
            "exhausted": item.exhausted,
            "legacy_resolved": item.legacy_resolved,
            "participant": item.participant,
            "resources": [
                {
                    "kind": resource.kind,
                    "participant": resource.participant,
                    "resource_id": str(resource.resource_id),
                    "revision": resource.revision,
                }
                for resource in sorted(
                    item.resources,
                    key=lambda resource: (
                        resource.participant,
                        resource.kind,
                        str(resource.resource_id),
                        resource.revision,
                    ),
                )
            ],
            "supported": item.supported,
        }
        for item in sorted(inventory.participants, key=lambda item: item.participant)
    ]
    return {
        "documents": documents,
        "folders": folders,
        "job_id": str(inventory.job_id),
        "participants": participants,
        "version": inventory.version,
        "workspace_id": str(inventory.workspace_id),
    }


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def inventory_binding(inventory: PurgeInventory) -> str:
    if not isinstance(inventory, PurgeInventory):
        raise TypeError("inventory must be a PurgeInventory")
    return _canonical_sha256(_inventory_payload(inventory))


def _inventory_is_complete(
    inventory: PurgeInventory,
    required_participants: frozenset[str],
) -> bool:
    inventory_participants = {item.participant for item in inventory.participants}
    return (
        bool(inventory.documents or inventory.folders)
        and bool(required_participants)
        and inventory_participants == required_participants
        and all(
            item.exhausted and item.supported and item.legacy_resolved
            for item in inventory.participants
        )
    )


def _validate_required_participants(
    required_participants: object,
) -> frozenset[str]:
    if type(required_participants) is not frozenset:
        raise TypeError("required_participants must be a frozenset")
    for participant in required_participants:
        _validate_machine_identifier(participant, "required participant")
    return required_participants


def _receipt_matches_inventory(
    receipt: BoundCleanupReceipt,
    *,
    inventory: PurgeInventory,
    expected_binding: str,
    contracts: dict[str, int],
    attempt: int,
) -> bool:
    participant = receipt.receipt.participant
    return (
        receipt.job_id == inventory.job_id
        and receipt.inventory_version == inventory.version
        and receipt.inventory_binding == expected_binding
        and contracts.get(participant) == receipt.participant_contract_version
        and receipt.attempt == attempt
    )


def assess_bound_purge(
    *,
    inventory: PurgeInventory,
    required_participants: frozenset[str],
    receipts: tuple[BoundCleanupReceipt, ...],
    attempt: int,
    writers_stopped: bool = False,
    references_cleared: bool = False,
) -> PurgeDecision:
    if not isinstance(inventory, PurgeInventory):
        raise TypeError("inventory must be a PurgeInventory")
    required_participants = _validate_required_participants(required_participants)
    _validate_tuple(receipts, "receipts")
    if any(not isinstance(receipt, BoundCleanupReceipt) for receipt in receipts):
        raise TypeError("receipts must contain BoundCleanupReceipt values")
    _validate_positive_integer(attempt, "attempt")
    _validate_actual_bool(writers_stopped, "writers_stopped")
    _validate_actual_bool(references_cleared, "references_cleared")

    expected_binding = inventory_binding(inventory)
    contracts = {item.participant: item.contract_version for item in inventory.participants}
    bindings_complete = all(
        _receipt_matches_inventory(
            receipt,
            inventory=inventory,
            expected_binding=expected_binding,
            contracts=contracts,
            attempt=attempt,
        )
        for receipt in receipts
    )

    return assess_purge(
        required_participants=required_participants,
        receipts=tuple(receipt.receipt for receipt in receipts),
        inventory_complete=(
            _inventory_is_complete(inventory, required_participants) and bindings_complete
        ),
        writers_stopped=writers_stopped,
        references_cleared=references_cleared,
    )


def _receipt_payload(receipt: BoundCleanupReceipt) -> dict[str, Any]:
    return {
        "attempt": receipt.attempt,
        "checked_at": receipt.checked_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "inventory_binding": receipt.inventory_binding,
        "inventory_version": receipt.inventory_version,
        "job_id": str(receipt.job_id),
        "participant_contract_version": receipt.participant_contract_version,
        "receipt": {
            "deleted": receipt.receipt.deleted,
            "participant": receipt.receipt.participant,
            "residual_owned": receipt.receipt.residual_owned,
            "retained_shared": receipt.receipt.retained_shared,
            "verified": receipt.receipt.verified,
        },
    }


def _retained_inventory_payload(
    *,
    workspace_id: UUID,
    job_id: UUID,
    inventory_version: int,
    inventory_binding: str,
    documents: tuple[DocumentTarget, ...],
    folders: tuple[FolderTarget, ...],
    receipts: tuple[BoundCleanupReceipt, ...],
) -> dict[str, Any]:
    return {
        "binding": inventory_binding,
        "documents": [
            {
                "asset_version_ids": sorted(
                    str(item) for item in target.asset_version_ids
                ),
                "document_id": str(target.document_id),
                "generation": target.generation,
            }
            for target in sorted(documents, key=lambda item: str(item.document_id))
        ],
        "folders": [
            {"folder_id": str(target.folder_id), "generation": target.generation}
            for target in sorted(folders, key=lambda item: str(item.folder_id))
        ],
        "job_id": str(job_id),
        "participants": [
            {
                "contract_version": receipt.participant_contract_version,
                "participant": receipt.receipt.participant,
            }
            for receipt in sorted(
                receipts,
                key=lambda item: item.receipt.participant,
            )
        ],
        "version": inventory_version,
        "workspace_id": str(workspace_id),
    }


def retained_proof_binding(
    *,
    workspace_id: UUID,
    job_id: UUID,
    inventory_version: int,
    inventory_binding: str,
    documents: tuple[DocumentTarget, ...],
    folders: tuple[FolderTarget, ...],
    receipts: tuple[BoundCleanupReceipt, ...],
    required_participants: frozenset[str],
) -> str:
    """Recompute the canonical proof digest from retained, body-free fields.

    This integrity digest does not authenticate a publisher or prove deletion.
    """

    _validate_uuid(workspace_id, "workspace_id")
    _validate_uuid(job_id, "job_id")
    _validate_positive_integer(inventory_version, "inventory_version")
    if type(inventory_binding) is not str:
        raise TypeError("inventory_binding must be a string")
    if _SHA256.fullmatch(inventory_binding) is None:
        raise ValueError("inventory_binding must be a lowercase SHA-256 digest")
    _validate_tuple(documents, "documents")
    _validate_tuple(folders, "folders")
    _validate_tuple(receipts, "receipts")
    if any(not isinstance(document, DocumentTarget) for document in documents):
        raise TypeError("documents must contain DocumentTarget values")
    if any(not isinstance(folder, FolderTarget) for folder in folders):
        raise TypeError("folders must contain FolderTarget values")
    if any(not isinstance(receipt, BoundCleanupReceipt) for receipt in receipts):
        raise TypeError("receipts must contain BoundCleanupReceipt values")
    if not documents and not folders:
        raise ValueError("at least one retained target is required")
    if len({target.document_id for target in documents}) != len(documents):
        raise ValueError("documents must not contain duplicate document ids")
    if len({target.folder_id for target in folders}) != len(folders):
        raise ValueError("folders must not contain duplicate folder ids")

    required_participants = _validate_required_participants(required_participants)
    receipt_participants = [receipt.receipt.participant for receipt in receipts]
    attempts = {receipt.attempt for receipt in receipts}
    receipts_match = all(
        receipt.job_id == job_id
        and receipt.inventory_version == inventory_version
        and receipt.inventory_binding == inventory_binding
        for receipt in receipts
    )
    if (
        not required_participants
        or set(receipt_participants) != required_participants
        or len(receipt_participants) != len(set(receipt_participants))
        or len(attempts) != 1
        or not receipts_match
    ):
        raise ValueError("receipts must be complete and bound to the retained inventory")

    return _canonical_sha256(
        {
            "inventory": _retained_inventory_payload(
                workspace_id=workspace_id,
                job_id=job_id,
                inventory_version=inventory_version,
                inventory_binding=inventory_binding,
                documents=documents,
                folders=folders,
                receipts=receipts,
            ),
            "receipts": [
                _receipt_payload(receipt)
                for receipt in sorted(
                    receipts,
                    key=lambda item: item.receipt.participant,
                )
            ],
        }
    )


def proof_binding(
    *,
    inventory: PurgeInventory,
    receipts: tuple[BoundCleanupReceipt, ...],
    required_participants: frozenset[str],
) -> str:
    if not isinstance(inventory, PurgeInventory):
        raise TypeError("inventory must be a PurgeInventory")
    required_participants = _validate_required_participants(required_participants)
    _validate_tuple(receipts, "receipts")
    if any(not isinstance(receipt, BoundCleanupReceipt) for receipt in receipts):
        raise TypeError("receipts must contain BoundCleanupReceipt values")

    inventory_participants = {item.participant for item in inventory.participants}
    if (
        not required_participants
        or inventory_participants != required_participants
    ):
        raise ValueError(
            "required_participants must exactly match inventory participants"
        )
    receipt_participants = [receipt.receipt.participant for receipt in receipts]
    attempts = {receipt.attempt for receipt in receipts}
    expected_binding = inventory_binding(inventory)
    contracts = {item.participant: item.contract_version for item in inventory.participants}
    matches = all(
        _receipt_matches_inventory(
            receipt,
            inventory=inventory,
            expected_binding=expected_binding,
            contracts=contracts,
            attempt=receipt.attempt,
        )
        for receipt in receipts
    )
    if (
        not _inventory_is_complete(inventory, required_participants)
        or set(receipt_participants) != required_participants
        or len(receipt_participants) != len(set(receipt_participants))
        or len(attempts) != 1
        or not matches
    ):
        raise ValueError("receipts must be complete and bound to the inventory")

    return retained_proof_binding(
        workspace_id=inventory.workspace_id,
        job_id=inventory.job_id,
        inventory_version=inventory.version,
        inventory_binding=expected_binding,
        documents=inventory.documents,
        folders=inventory.folders,
        receipts=receipts,
        required_participants=required_participants,
    )
