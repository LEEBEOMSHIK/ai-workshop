from dataclasses import dataclass


@dataclass(frozen=True)
class CleanupReceipt:
    participant: str
    deleted: int
    retained_shared: int
    residual_owned: int
    verified: bool

    def __post_init__(self) -> None:
        if not self.participant.strip():
            raise ValueError("participant must not be blank")
        for field_name in ("deleted", "retained_shared", "residual_owned"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")


@dataclass(frozen=True)
class PurgeDecision:
    online_complete: bool
    reasons: tuple[str, ...]


def assess_purge(
    *,
    required_participants: frozenset[str],
    receipts: tuple[CleanupReceipt, ...],
    inventory_complete: bool,
    writers_stopped: bool,
    references_cleared: bool,
) -> PurgeDecision:
    reasons: list[str] = []
    if not inventory_complete or not required_participants:
        reasons.append("inventory_incomplete")
    if not writers_stopped:
        reasons.append("writers_active")
    if not references_cleared:
        reasons.append("references_remaining")

    names = [receipt.participant for receipt in receipts]
    if len(names) != len(set(names)) or set(names) != required_participants:
        reasons.append("participant_mismatch")
    if any(not receipt.verified for receipt in receipts):
        reasons.append("cleanup_unverified")
    if any(receipt.residual_owned for receipt in receipts):
        reasons.append("owned_residuals")

    return PurgeDecision(online_complete=not reasons, reasons=tuple(reasons))
