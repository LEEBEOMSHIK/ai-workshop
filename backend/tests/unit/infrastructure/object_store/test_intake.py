import json
import os
from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.infrastructure.object_store.intake import TrackedIntakeStore
from ai_workshop.platform.assets.intake_contracts import UploadIntakeClaim
from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.temporary_contracts import (
    TemporaryBinding,
    TemporaryOwnershipError,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native allocation")


def setup(tmp_path):
    binding = TemporaryBinding("http_test", uuid4())
    (tmp_path / ".ai-workshop-temporary-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "store_id": binding.store_id,
                "binding_id": str(binding.binding_id),
            }
        ),
        encoding="utf-8",
    )
    claim = UploadIntakeClaim(
        uuid4(), SourceIdentity(uuid4(), uuid4(), uuid4()), uuid4(), True, binding
    )
    return TrackedIntakeStore(tmp_path, binding), claim


def test_planned_source_can_allocate_without_forging_document_claim(tmp_path):
    store, claim = setup(tmp_path)
    workspace = store.create(claim)
    try:
        payload = workspace.create_file("payload.bin")
        payload.write_bytes(b"synthetic upload")
        assert store.observe(claim)
        workspace.discard()
        assert not store.observe(claim)
    finally:
        workspace.close()


def test_stale_or_wrong_binding_cannot_allocate(tmp_path):
    store, claim = setup(tmp_path)
    for invalid in [
        replace(claim, state="closed", revision=2),
        replace(claim, original_attempt_id=uuid4(), revision=2),
        replace(claim, binding=TemporaryBinding("other", uuid4())),
    ]:
        with pytest.raises(TemporaryOwnershipError):
            store.create(invalid)
    assert not (tmp_path / str(claim.id)).exists()


def test_other_file_is_preserved_by_intake_cleanup(tmp_path):
    store, claim = setup(tmp_path)
    workspace = store.create(claim)
    try:
        payload = workspace.create_file("payload.bin")
        payload.write_bytes(b"synthetic upload")
        foreign = workspace.root / "foreign.txt"
        foreign.write_bytes(b"synthetic foreign")
        with pytest.raises(TemporaryOwnershipError):
            workspace.discard()
        assert payload.read_bytes() == b"synthetic upload"
        assert foreign.read_bytes() == b"synthetic foreign"
    finally:
        workspace.close()
