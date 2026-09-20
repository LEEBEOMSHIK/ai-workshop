"""Planned-source wrapper over native temporary allocation; no fabricated source claim."""

from pathlib import Path

from ai_workshop.infrastructure.object_store.temporary import (
    TemporaryWorkspace,
    TrackedTemporaryStore,
)
from ai_workshop.platform.assets.intake_contracts import UploadIntakeClaim
from ai_workshop.platform.assets.temporary_contracts import (
    TemporaryBinding,
    TemporaryOwnershipError,
)


class TrackedIntakeStore:
    def __init__(self, root: Path, binding: TemporaryBinding) -> None:
        self._allocations = TrackedTemporaryStore(root, binding)

    @property
    def binding(self) -> TemporaryBinding:
        return self._allocations.binding

    def _validate(self, claim: UploadIntakeClaim) -> None:
        if type(claim) is not UploadIntakeClaim:
            raise TemporaryOwnershipError("invalid_claim")
        try:
            claim.__post_init__()
            claim.source.__post_init__()
            claim.binding.__post_init__()
        except (ValueError, TypeError, AttributeError):
            raise TemporaryOwnershipError("invalid_claim") from None
        if claim.binding != self.binding:
            raise TemporaryOwnershipError("binding_mismatch")

    def create(self, claim: UploadIntakeClaim) -> TemporaryWorkspace:
        self._validate(claim)
        if (
            claim.state != "open"
            or claim.revision != 1
            or claim.original_attempt_id is not None
            or claim.attached
        ):
            raise TemporaryOwnershipError("ownership_unconfirmed")
        return self._allocations._create_allocation(claim.id, claim.binding)

    def observe(self, claim: UploadIntakeClaim) -> bool:
        self._validate(claim)
        return self._allocations._observe_allocation(claim.id, claim.binding)
