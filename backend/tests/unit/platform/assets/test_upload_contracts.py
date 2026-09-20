from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.upload_contracts import (
    OriginalStoreBinding,
    UploadAttempt,
    UploadClaim,
    UploadOwnershipError,
)


def claim() -> UploadClaim:
    return UploadClaim(
        uuid4(),
        SourceIdentity(uuid4(), uuid4(), uuid4()),
        uuid4(),
        None,
        True,
        OriginalStoreBinding("originals", uuid4()),
        ".txt",
    )


def test_exact_keys_and_frozen_claim() -> None:
    item = claim()
    prefix = f"{item.source.workspace_id}/{item.source.document_id}/"
    assert item.canonical_key == prefix + item.attempt_id.hex + ".txt"
    assert item.temporary_key == prefix + "." + item.attempt_id.hex + ".upload.tmp"


@pytest.mark.parametrize(
    "field,value",
    [
        ("suffix", ".TXT"),
        ("suffix", "../x"),
        ("new_document", 1),
        ("attempt_id", "bad"),
        ("generation", True),
        ("generation", 0),
        ("source", None),
    ],
)
def test_invalid_claim(field: str, value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        replace(claim(), **{field: value})


@pytest.mark.parametrize(
    "state,revision,size,digest",
    [
        ("open", 2, None, None),
        ("published", 2, None, None),
        ("attached", 2, 1, "a" * 64),
        ("published", 2, True, "a" * 64),
        ("published", 2, 1, "A" * 64),
        ("unknown", 1, None, None),
    ],
)
def test_invalid_attempt(state: str, revision: int, size: int | None, digest: str | None) -> None:
    with pytest.raises((TypeError, ValueError)):
        UploadAttempt(claim(), state, revision, size, digest)


def test_error_never_accepts_arbitrary_private_text() -> None:
    with pytest.raises(ValueError):
        UploadOwnershipError("private/path/secret")


def test_discarding_fences_attachment_and_retains_content() -> None:
    item = claim()
    assert UploadAttempt(item, "discarding", 3, 1, "a" * 64).revision == 3
    assert UploadAttempt(item, "abandoned", 4, 1, "a" * 64).revision == 4
    with pytest.raises(ValueError):
        UploadAttempt(item, "abandoned", 3, 1, "a" * 64)


def test_planned_identity_has_no_foreign_keys_and_resources_restrict() -> None:
    from ai_workshop.platform.assets.upload_models import (
        OriginalResourceRecord,
        UploadAttemptRecord,
    )

    assert not UploadAttemptRecord.__table__.foreign_keys
    constraints = list(OriginalResourceRecord.__table__.foreign_key_constraints)
    assert len(constraints) == 3
    assert all(item.ondelete == "RESTRICT" for item in constraints)
