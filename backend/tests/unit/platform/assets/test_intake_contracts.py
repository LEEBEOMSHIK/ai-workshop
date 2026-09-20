from dataclasses import FrozenInstanceError, replace
from uuid import uuid4

import pytest

from ai_workshop.platform.assets.intake_contracts import UploadIntakeClaim
from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.temporary_contracts import TemporaryBinding


def claim():
    return UploadIntakeClaim(
        uuid4(),
        SourceIdentity(uuid4(), uuid4(), uuid4()),
        uuid4(),
        True,
        TemporaryBinding("temporary", uuid4()),
    )


def test_planned_claim_is_immutable_and_revisions_include_optional_link_and_attachment():
    initial = claim()
    with pytest.raises(FrozenInstanceError):
        initial.state = "closed"
    linked = replace(initial, original_attempt_id=uuid4(), revision=2)
    attached = replace(linked, attached=True, revision=3)
    assert replace(attached, state="cleaned", revision=6).attached
    assert replace(initial, state="cleaned", revision=4).original_attempt_id is None


@pytest.mark.parametrize(
    "changes",
    [
        {"revision": True},
        {"revision": 0},
        {"state": "unknown"},
        {"attached": True},
        {"original_attempt_id": uuid4()},
        {"generation": 1},
        {"new_document": False},
        {"user_id": "bad"},
        {"state": "closed", "revision": 1},
        {"revision": 2},
    ],
)
def test_invalid_snapshot_combinations(changes):
    with pytest.raises((ValueError, TypeError)):
        replace(claim(), **changes)
