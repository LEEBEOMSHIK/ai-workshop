from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity
from ai_workshop.platform.assets.purge_contracts import CleanupReceipt
from ai_workshop.platform.assets.purge_inventory_contracts import (
    BoundCleanupReceipt,
    DocumentTarget,
    FolderTarget,
    ParticipantInventory,
    PurgeInventory,
    assess_bound_purge,
    inventory_binding,
    proof_binding,
    retained_proof_binding,
)

WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000001")
JOB_ID = UUID("50000000-0000-0000-0000-000000000001")
OTHER_JOB_ID = UUID("50000000-0000-0000-0000-000000000002")
DOCUMENT_A = UUID("20000000-0000-0000-0000-000000000001")
DOCUMENT_B = UUID("20000000-0000-0000-0000-000000000002")
VERSION_A1 = UUID("30000000-0000-0000-0000-000000000001")
VERSION_A2 = UUID("30000000-0000-0000-0000-000000000002")
VERSION_B1 = UUID("30000000-0000-0000-0000-000000000003")
FOLDER_ID = UUID("60000000-0000-0000-0000-000000000001")
RAG_RESOURCE = UUID("40000000-0000-0000-0000-000000000001")
OBJECT_RESOURCE = UUID("40000000-0000-0000-0000-000000000002")
CHECKED_AT = datetime(2026, 9, 14, 12, 30, 45, 123456, tzinfo=UTC)


def _resource(
    participant: str = "rag", *, resource_id: UUID = RAG_RESOURCE, revision: int = 1
) -> ResourceIdentity:
    return ResourceIdentity(participant, "projection", resource_id, revision)


def _participant(
    participant: str = "rag",
    *,
    contract_version: int = 2,
    resources: tuple[ResourceIdentity, ...] | None = None,
    exhausted: bool = True,
    supported: bool = True,
    legacy_resolved: bool = True,
) -> ParticipantInventory:
    return ParticipantInventory(
        participant=participant,
        contract_version=contract_version,
        resources=(_resource(participant),) if resources is None else resources,
        exhausted=exhausted,
        supported=supported,
        legacy_resolved=legacy_resolved,
    )


def _inventory(
    *,
    job_id: UUID = JOB_ID,
    version: int = 4,
    documents: tuple[DocumentTarget, ...] | None = None,
    folders: tuple[FolderTarget, ...] = (),
    participants: tuple[ParticipantInventory, ...] | None = None,
) -> PurgeInventory:
    return PurgeInventory(
        workspace_id=WORKSPACE_ID,
        job_id=job_id,
        version=version,
        documents=(DocumentTarget(DOCUMENT_A, 7, (VERSION_A1, VERSION_A2)),)
        if documents is None
        else documents,
        folders=folders,
        participants=(_participant(),) if participants is None else participants,
    )


def _bound_receipt(
    inventory: PurgeInventory,
    *,
    participant: str = "rag",
    job_id: UUID | None = None,
    inventory_version: int | None = None,
    bound_inventory: str | None = None,
    contract_version: int = 2,
    attempt: int = 3,
    checked_at: datetime = CHECKED_AT,
    deleted: int = 1,
    retained_shared: int = 0,
    residual_owned: int = 0,
    verified: bool = True,
) -> BoundCleanupReceipt:
    return BoundCleanupReceipt(
        job_id=inventory.job_id if job_id is None else job_id,
        inventory_version=inventory.version if inventory_version is None else inventory_version,
        inventory_binding=inventory_binding(inventory)
        if bound_inventory is None
        else bound_inventory,
        participant_contract_version=contract_version,
        attempt=attempt,
        checked_at=checked_at,
        receipt=CleanupReceipt(
            participant,
            deleted,
            retained_shared,
            residual_owned,
            verified,
        ),
    )


def test_target_and_inventory_contracts_are_frozen() -> None:
    target = DocumentTarget(DOCUMENT_A, 7, (VERSION_A1,))
    inventory = _inventory()

    with pytest.raises(FrozenInstanceError):
        target.generation = 8  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        inventory.version = 5  # type: ignore[misc]


@pytest.mark.parametrize("generation", [0, -1, True, 1.5])
def test_targets_reject_non_positive_integer_generation(generation: object) -> None:
    with pytest.raises((TypeError, ValueError), match="generation"):
        DocumentTarget(DOCUMENT_A, generation, (VERSION_A1,))  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError), match="generation"):
        FolderTarget(FOLDER_ID, generation)  # type: ignore[arg-type]


def test_document_target_rejects_empty_or_duplicate_asset_versions() -> None:
    with pytest.raises(ValueError, match="asset_version_ids"):
        DocumentTarget(DOCUMENT_A, 1, ())
    with pytest.raises(ValueError, match="asset_version_ids"):
        DocumentTarget(DOCUMENT_A, 1, (VERSION_A1, VERSION_A1))


@pytest.mark.parametrize("contract_version", [0, -1, True, 1.5])
def test_participant_inventory_rejects_invalid_contract_version(contract_version: object) -> None:
    with pytest.raises((TypeError, ValueError), match="contract_version"):
        _participant(contract_version=contract_version)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["exhausted", "supported", "legacy_resolved"])
@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_participant_inventory_requires_actual_boolean_flags(field: str, value: object) -> None:
    values: dict[str, object] = {
        "participant": "rag",
        "contract_version": 2,
        "resources": (_resource(),),
        "exhausted": True,
        "supported": True,
        "legacy_resolved": True,
    }
    values[field] = value

    with pytest.raises(TypeError, match=field):
        ParticipantInventory(**values)  # type: ignore[arg-type]


def test_empty_participant_resources_still_require_explicit_exhaustion() -> None:
    complete_empty = _participant(resources=(), exhausted=True)
    incomplete_empty = _participant(resources=(), exhausted=False)

    complete = _inventory(participants=(complete_empty,))
    incomplete = _inventory(participants=(incomplete_empty,))

    assert assess_bound_purge(
        inventory=complete,
        required_participants=frozenset({"rag"}),
        receipts=(_bound_receipt(complete, deleted=0),),
        attempt=3,
        writers_stopped=True,
        references_cleared=True,
    ).online_complete
    assert (
        "inventory_incomplete"
        in assess_bound_purge(
            inventory=incomplete,
            required_participants=frozenset({"rag"}),
            receipts=(_bound_receipt(incomplete, deleted=0),),
            attempt=3,
            writers_stopped=True,
            references_cleared=True,
        ).reasons
    )


def test_participant_inventory_rejects_duplicate_or_cross_participant_resources() -> None:
    resource = _resource()
    with pytest.raises(ValueError, match="resources"):
        _participant(resources=(resource, resource))
    with pytest.raises(ValueError, match="participant"):
        _participant("objects", resources=(resource,))


def test_inventory_rejects_duplicate_targets_and_participants() -> None:
    document = DocumentTarget(DOCUMENT_A, 1, (VERSION_A1,))
    folder = FolderTarget(FOLDER_ID, 1)
    participant = _participant()

    with pytest.raises(ValueError, match="documents"):
        _inventory(documents=(document, document))
    with pytest.raises(ValueError, match="folders"):
        _inventory(documents=(), folders=(folder, folder))
    with pytest.raises(ValueError, match="participants"):
        _inventory(participants=(participant, participant))


def test_folder_only_inventory_can_complete_but_empty_target_inventory_cannot() -> None:
    folder_only = _inventory(documents=(), folders=(FolderTarget(FOLDER_ID, 5),))
    empty = _inventory(documents=(), folders=())

    assert assess_bound_purge(
        inventory=folder_only,
        required_participants=frozenset({"rag"}),
        receipts=(_bound_receipt(folder_only),),
        attempt=3,
        writers_stopped=True,
        references_cleared=True,
    ).online_complete
    assert (
        "inventory_incomplete"
        in assess_bound_purge(
            inventory=empty,
            required_participants=frozenset({"rag"}),
            receipts=(_bound_receipt(empty),),
            attempt=3,
            writers_stopped=True,
            references_cleared=True,
        ).reasons
    )


def test_inventory_binding_is_stable_across_input_order() -> None:
    documents = (
        DocumentTarget(DOCUMENT_A, 7, (VERSION_A2, VERSION_A1)),
        DocumentTarget(DOCUMENT_B, 4, (VERSION_B1,)),
    )
    participants = (
        _participant(),
        _participant(
            "objects",
            contract_version=5,
            resources=(_resource("objects", resource_id=OBJECT_RESOURCE, revision=8),),
        ),
    )
    first = _inventory(
        documents=documents,
        folders=(FolderTarget(FOLDER_ID, 3),),
        participants=participants,
    )
    second = _inventory(
        documents=tuple(reversed(documents)),
        folders=first.folders,
        participants=tuple(reversed(participants)),
    )

    assert inventory_binding(first) == inventory_binding(second)
    assert len(inventory_binding(first)) == 64


@pytest.mark.parametrize(
    "changed",
    [
        _inventory(job_id=OTHER_JOB_ID),
        _inventory(version=5),
        _inventory(documents=(DocumentTarget(DOCUMENT_A, 8, (VERSION_A1, VERSION_A2)),)),
        _inventory(participants=(_participant(contract_version=3),)),
        _inventory(participants=(_participant(resources=(_resource(revision=2),)),)),
        _inventory(participants=(_participant(exhausted=False),)),
    ],
    ids=("job", "version", "generation", "contract", "revision", "flag"),
)
def test_inventory_binding_changes_for_each_bound_contract_dimension(
    changed: PurgeInventory,
) -> None:
    assert inventory_binding(changed) != inventory_binding(_inventory())


@pytest.mark.parametrize("field", ["inventory_version", "participant_contract_version", "attempt"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_bound_receipt_rejects_invalid_positive_integer_fields(field: str, value: object) -> None:
    inventory = _inventory()
    values: dict[str, object] = {
        "job_id": JOB_ID,
        "inventory_version": 4,
        "inventory_binding": inventory_binding(inventory),
        "participant_contract_version": 2,
        "attempt": 3,
        "checked_at": CHECKED_AT,
        "receipt": CleanupReceipt("rag", 1, 0, 0, True),
    }
    values[field] = value

    with pytest.raises((TypeError, ValueError), match=field):
        BoundCleanupReceipt(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "checked_at",
    [
        datetime(2026, 9, 14, 12, 30),
        datetime(2026, 9, 14, 12, 30, tzinfo=timezone(timedelta(hours=9))),
    ],
    ids=("naive", "non_utc"),
)
def test_bound_receipt_requires_utc_aware_checked_at(checked_at: datetime) -> None:
    with pytest.raises(ValueError, match="checked_at"):
        _bound_receipt(_inventory(), checked_at=checked_at)


@pytest.mark.parametrize("verified", [0, 1, "true", None])
def test_bound_receipt_requires_actual_boolean_verification(verified: object) -> None:
    with pytest.raises(TypeError, match="verified"):
        _bound_receipt(_inventory(), verified=verified)  # type: ignore[arg-type]


@pytest.mark.parametrize("binding", ["", "0" * 63, "G" * 64, "A" * 64])
def test_bound_receipt_rejects_noncanonical_inventory_binding(binding: str) -> None:
    with pytest.raises(ValueError, match="inventory_binding"):
        _bound_receipt(_inventory(), bound_inventory=binding)


def test_bound_assessment_defaults_cannot_complete() -> None:
    inventory = _inventory()

    decision = assess_bound_purge(
        inventory=inventory,
        required_participants=frozenset({"rag"}),
        receipts=(_bound_receipt(inventory),),
        attempt=3,
    )

    assert not decision.online_complete
    assert decision.reasons == ("writers_active", "references_remaining")


@pytest.mark.parametrize(
    "receipt_change",
    [
        {"job_id": OTHER_JOB_ID},
        {"inventory_version": 3},
        {"bound_inventory": "0" * 64},
        {"contract_version": 3},
        {"attempt": 2},
    ],
    ids=("job", "inventory_version", "binding", "contract", "attempt"),
)
def test_bound_assessment_rejects_stale_or_mismatched_receipt(
    receipt_change: dict[str, object],
) -> None:
    inventory = _inventory()
    receipt = _bound_receipt(inventory, **receipt_change)  # type: ignore[arg-type]

    decision = assess_bound_purge(
        inventory=inventory,
        required_participants=frozenset({"rag"}),
        receipts=(receipt,),
        attempt=3,
        writers_stopped=True,
        references_cleared=True,
    )

    assert not decision.online_complete
    assert "inventory_incomplete" in decision.reasons


@pytest.mark.parametrize(
    "participants",
    [
        (_participant(exhausted=False),),
        (_participant(supported=False),),
        (_participant(legacy_resolved=False),),
    ],
    ids=("page_not_exhausted", "unsupported", "legacy_unresolved"),
)
def test_incomplete_participant_inventory_blocks_completion(
    participants: tuple[ParticipantInventory, ...],
) -> None:
    inventory = _inventory(participants=participants)

    decision = assess_bound_purge(
        inventory=inventory,
        required_participants=frozenset({"rag"}),
        receipts=(_bound_receipt(inventory),),
        attempt=3,
        writers_stopped=True,
        references_cleared=True,
    )

    assert not decision.online_complete
    assert "inventory_incomplete" in decision.reasons


def test_missing_and_duplicate_receipts_block_completion() -> None:
    inventory = _inventory()
    receipt = _bound_receipt(inventory)

    missing = assess_bound_purge(
        inventory=inventory,
        required_participants=frozenset({"rag"}),
        receipts=(),
        attempt=3,
        writers_stopped=True,
        references_cleared=True,
    )
    duplicate = assess_bound_purge(
        inventory=inventory,
        required_participants=frozenset({"rag"}),
        receipts=(receipt, receipt),
        attempt=3,
        writers_stopped=True,
        references_cleared=True,
    )

    assert "participant_mismatch" in missing.reasons
    assert "participant_mismatch" in duplicate.reasons


def test_required_participants_must_match_trusted_inventory_participants() -> None:
    inventory = _inventory()

    decision = assess_bound_purge(
        inventory=inventory,
        required_participants=frozenset({"rag", "objects"}),
        receipts=(_bound_receipt(inventory),),
        attempt=3,
        writers_stopped=True,
        references_cleared=True,
    )

    assert not decision.online_complete
    assert "inventory_incomplete" in decision.reasons
    assert "participant_mismatch" in decision.reasons


def test_mixed_residual_and_retained_shared_objects_block_completion() -> None:
    inventory = _inventory()

    decision = assess_bound_purge(
        inventory=inventory,
        required_participants=frozenset({"rag"}),
        receipts=(_bound_receipt(inventory, retained_shared=2, residual_owned=1),),
        attempt=3,
        writers_stopped=True,
        references_cleared=True,
    )

    assert not decision.online_complete
    assert "owned_residuals" in decision.reasons


def test_proof_binding_is_stable_across_receipt_order() -> None:
    participants = (
        _participant(),
        _participant(
            "objects",
            contract_version=5,
            resources=(_resource("objects", resource_id=OBJECT_RESOURCE),),
        ),
    )
    inventory = _inventory(participants=participants)
    rag = _bound_receipt(inventory)
    objects = _bound_receipt(
        inventory,
        participant="objects",
        contract_version=5,
        checked_at=CHECKED_AT + timedelta(seconds=1),
    )

    required_participants = frozenset({"rag", "objects"})

    assert proof_binding(
        inventory=inventory,
        receipts=(rag, objects),
        required_participants=required_participants,
    ) == proof_binding(
        inventory=inventory,
        receipts=(objects, rag),
        required_participants=required_participants,
    )


@pytest.mark.parametrize(
    "receipt_change",
    [
        {"attempt": 4},
        {"checked_at": CHECKED_AT + timedelta(microseconds=1)},
        {"deleted": 2},
        {"retained_shared": 1},
        {"residual_owned": 1},
        {"verified": False},
    ],
    ids=("attempt", "checked_at", "deleted", "retained_shared", "residual", "verified"),
)
def test_proof_binding_changes_with_verification_result(
    receipt_change: dict[str, object],
) -> None:
    inventory = _inventory()

    assert proof_binding(
        inventory=inventory,
        receipts=(_bound_receipt(inventory, **receipt_change),),  # type: ignore[arg-type]
        required_participants=frozenset({"rag"}),
    ) != proof_binding(
        inventory=inventory,
        receipts=(_bound_receipt(inventory),),
        required_participants=frozenset({"rag"}),
    )


def test_proof_binding_rejects_partial_duplicate_or_mismatched_receipts() -> None:
    inventory = _inventory()
    receipt = _bound_receipt(inventory)

    with pytest.raises(ValueError, match="receipts"):
        proof_binding(
            inventory=inventory,
            receipts=(),
            required_participants=frozenset({"rag"}),
        )
    with pytest.raises(ValueError, match="receipts"):
        proof_binding(
            inventory=inventory,
            receipts=(receipt, receipt),
            required_participants=frozenset({"rag"}),
        )
    with pytest.raises(ValueError, match="receipts"):
        proof_binding(
            inventory=inventory,
            receipts=(replace(receipt, job_id=OTHER_JOB_ID),),
            required_participants=frozenset({"rag"}),
        )


def test_proof_binding_rejects_inventory_missing_trusted_participant() -> None:
    inventory = _inventory()

    with pytest.raises(ValueError, match="required_participants"):
        proof_binding(
            inventory=inventory,
            receipts=(_bound_receipt(inventory),),
            required_participants=frozenset({"rag", "objects"}),
        )


def test_proof_binding_rejects_inventory_with_extra_participant() -> None:
    participants = (
        _participant(),
        _participant(
            "objects",
            contract_version=5,
            resources=(_resource("objects", resource_id=OBJECT_RESOURCE),),
        ),
    )
    inventory = _inventory(participants=participants)

    with pytest.raises(ValueError, match="required_participants"):
        proof_binding(
            inventory=inventory,
            receipts=(
                _bound_receipt(inventory),
                _bound_receipt(
                    inventory,
                    participant="objects",
                    contract_version=5,
                ),
            ),
            required_participants=frozenset({"rag"}),
        )


def test_proof_binding_rejects_empty_trusted_participant_set() -> None:
    inventory = _inventory()

    with pytest.raises(ValueError, match="required_participants"):
        proof_binding(
            inventory=inventory,
            receipts=(_bound_receipt(inventory),),
            required_participants=frozenset(),
        )


def test_retained_proof_binding_recomputes_without_detailed_resources() -> None:
    inventory = _inventory()
    receipts = (_bound_receipt(inventory),)

    assert retained_proof_binding(
        workspace_id=inventory.workspace_id,
        job_id=inventory.job_id,
        inventory_version=inventory.version,
        inventory_binding=inventory_binding(inventory),
        documents=inventory.documents,
        folders=inventory.folders,
        receipts=receipts,
        required_participants=frozenset({"rag"}),
    ) == proof_binding(
        inventory=inventory,
        receipts=receipts,
        required_participants=frozenset({"rag"}),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"job_id": OTHER_JOB_ID},
        {"inventory_version": 5},
        {"inventory_binding": "f" * 64},
    ],
    ids=("job", "version", "binding"),
)
def test_retained_proof_binding_rejects_receipt_identity_mismatch(
    change: dict[str, object],
) -> None:
    inventory = _inventory()

    with pytest.raises(ValueError, match="receipts"):
        retained_proof_binding(
            workspace_id=inventory.workspace_id,
            job_id=inventory.job_id,
            inventory_version=inventory.version,
            inventory_binding=inventory_binding(inventory),
            documents=inventory.documents,
            folders=inventory.folders,
            receipts=(replace(_bound_receipt(inventory), **change),),  # type: ignore[arg-type]
            required_participants=frozenset({"rag"}),
        )


def test_retained_proof_binding_rejects_mixed_attempts_and_duplicate_targets() -> None:
    participants = (
        _participant(),
        _participant(
            "objects",
            contract_version=5,
            resources=(_resource("objects", resource_id=OBJECT_RESOURCE),),
        ),
    )
    inventory = _inventory(participants=participants)
    receipts = (
        _bound_receipt(inventory),
        _bound_receipt(
            inventory,
            participant="objects",
            contract_version=5,
            attempt=4,
        ),
    )

    with pytest.raises(ValueError, match="receipts"):
        retained_proof_binding(
            workspace_id=inventory.workspace_id,
            job_id=inventory.job_id,
            inventory_version=inventory.version,
            inventory_binding=inventory_binding(inventory),
            documents=inventory.documents,
            folders=inventory.folders,
            receipts=receipts,
            required_participants=frozenset({"rag", "objects"}),
        )
    with pytest.raises(ValueError, match="documents"):
        retained_proof_binding(
            workspace_id=inventory.workspace_id,
            job_id=inventory.job_id,
            inventory_version=inventory.version,
            inventory_binding=inventory_binding(inventory),
            documents=(inventory.documents[0], inventory.documents[0]),
            folders=inventory.folders,
            receipts=(
                receipts[0],
                replace(receipts[1], attempt=receipts[0].attempt),
            ),
            required_participants=frozenset({"rag", "objects"}),
        )


def test_retained_proof_binding_requires_at_least_one_target() -> None:
    inventory = _inventory()

    with pytest.raises(ValueError, match="target"):
        retained_proof_binding(
            workspace_id=inventory.workspace_id,
            job_id=inventory.job_id,
            inventory_version=inventory.version,
            inventory_binding=inventory_binding(inventory),
            documents=(),
            folders=(),
            receipts=(_bound_receipt(inventory),),
            required_participants=frozenset({"rag"}),
        )
