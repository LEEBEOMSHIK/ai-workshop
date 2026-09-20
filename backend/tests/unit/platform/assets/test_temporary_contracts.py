from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.temporary_contracts import (
    TemporaryBinding,
    TemporaryClaim,
    TemporaryContext,
    TemporaryOwnershipError,
    next_temporary_state,
)


def test_claim_is_immutable_and_rejects_invalid_purpose() -> None:
    context = TemporaryContext(SourceIdentity(uuid4(), uuid4(), uuid4()))
    binding = TemporaryBinding("temporary", uuid4())
    claim = TemporaryClaim(uuid4(), context, "parsing", binding, 1, "bounded")
    with pytest.raises(FrozenInstanceError):
        claim.generation = 2  # type: ignore[misc]
    with pytest.raises(TemporaryOwnershipError, match="invalid_claim"):
        TemporaryClaim(uuid4(), context, "private path", binding, 1, "bounded")


def test_only_forward_state_transitions_are_supported() -> None:
    assert next_temporary_state("open") == ("closed", 2)
    assert next_temporary_state("closed") == ("cleaning", 3)
    assert next_temporary_state("cleaning") == ("cleaned", 4)
    with pytest.raises(TemporaryOwnershipError, match="state_conflict"):
        next_temporary_state("cleaned")


def test_error_never_echoes_arbitrary_provider_details() -> None:
    assert str(TemporaryOwnershipError("C:/private/document")) == "ownership_failed"
