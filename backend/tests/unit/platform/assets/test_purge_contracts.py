import pytest

from ai_workshop.platform.assets.purge_contracts import (
    CleanupReceipt,
    PurgeDecision,
    assess_purge,
)


def _assess(
    *,
    required_participants: frozenset[str] = frozenset({"objects"}),
    receipts: tuple[CleanupReceipt, ...] = (
        CleanupReceipt("objects", 0, 0, 0, True),
    ),
    inventory_complete: bool = True,
    writers_stopped: bool = True,
    references_cleared: bool = True,
) -> PurgeDecision:
    return assess_purge(
        required_participants=required_participants,
        receipts=receipts,
        inventory_complete=inventory_complete,
        writers_stopped=writers_stopped,
        references_cleared=references_cleared,
    )


def test_zero_deleted_is_not_proof_of_absence() -> None:
    result = _assess(receipts=(CleanupReceipt("objects", 0, 0, 1, True),))

    assert not result.online_complete
    assert "owned_residuals" in result.reasons


def test_verified_zero_counts_prove_absence() -> None:
    assert _assess().online_complete


def test_verified_shared_objects_are_preserved_not_counted_as_residuals() -> None:
    result = _assess(receipts=(CleanupReceipt("objects", 2, 1, 0, True),))

    assert result.online_complete


@pytest.mark.parametrize(
    ("required_participants", "receipts"),
    [
        (frozenset({"objects", "projections"}), (CleanupReceipt("objects", 1, 0, 0, True),)),
        (frozenset({"objects"}), (CleanupReceipt("unknown", 1, 0, 0, True),)),
        (
            frozenset({"objects"}),
            (CleanupReceipt("objects", 1, 0, 0, True), CleanupReceipt("objects", 0, 0, 0, True)),
        ),
    ],
    ids=("missing", "unknown", "duplicate"),
)
def test_receipt_participant_mismatch_blocks_completion(
    required_participants: frozenset[str], receipts: tuple[CleanupReceipt, ...]
) -> None:
    result = _assess(required_participants=required_participants, receipts=receipts)

    assert not result.online_complete
    assert "participant_mismatch" in result.reasons


def test_unverified_cleanup_blocks_completion() -> None:
    result = _assess(receipts=(CleanupReceipt("objects", 1, 0, 0, False),))

    assert not result.online_complete
    assert "cleanup_unverified" in result.reasons


def test_active_writers_block_completion() -> None:
    result = _assess(writers_stopped=False)

    assert not result.online_complete
    assert "writers_active" in result.reasons


def test_remaining_references_block_completion() -> None:
    result = _assess(references_cleared=False)

    assert not result.online_complete
    assert "references_remaining" in result.reasons


@pytest.mark.parametrize("required_participants", [frozenset({"objects"}), frozenset()])
def test_incomplete_or_empty_inventory_blocks_completion(
    required_participants: frozenset[str],
) -> None:
    result = _assess(
        required_participants=required_participants,
        receipts=() if not required_participants else (CleanupReceipt("objects", 0, 0, 0, True),),
        inventory_complete=not required_participants,
    )

    assert not result.online_complete
    assert "inventory_incomplete" in result.reasons


@pytest.mark.parametrize("participant", ["", "   ", "\t"])
def test_blank_receipt_participant_is_rejected(participant: str) -> None:
    with pytest.raises(ValueError, match="participant"):
        CleanupReceipt(participant, 0, 0, 0, True)


@pytest.mark.parametrize("field", ["deleted", "retained_shared", "residual_owned"])
@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_invalid_receipt_count_is_rejected(field: str, value: object) -> None:
    values: dict[str, object] = {
        "participant": "objects",
        "deleted": 0,
        "retained_shared": 0,
        "residual_owned": 0,
        "verified": True,
    }
    values[field] = value

    with pytest.raises((TypeError, ValueError), match=field):
        CleanupReceipt(**values)  # type: ignore[arg-type]


def test_all_failures_are_reported_in_safe_order() -> None:
    result = assess_purge(
        required_participants=frozenset(),
        receipts=(CleanupReceipt("objects", 0, 0, 1, False),),
        inventory_complete=False,
        writers_stopped=False,
        references_cleared=False,
    )

    assert result.reasons == (
        "inventory_incomplete",
        "writers_active",
        "references_remaining",
        "participant_mismatch",
        "cleanup_unverified",
        "owned_residuals",
    )
