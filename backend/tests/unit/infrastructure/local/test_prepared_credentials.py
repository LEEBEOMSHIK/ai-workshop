"""Private pre-floor recovery never grants runtime startup admission."""

import base64
import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import SecretStr

from ai_workshop.infrastructure.local.credential_store_windows import WindowsCredentialStore
from ai_workshop.infrastructure.search.access_credentials import (
    AccessCredentialError,
    CredentialEnvelope,
)


class Memory:
    def __init__(self):
        self.files = {}

    def protect(self, value):
        return b"synthetic-protected:" + value

    def unprotect(self, value):
        assert value.startswith(b"synthetic-protected:")
        return value.removeprefix(b"synthetic-protected:")

    def write(self, path, value):
        self.files[path] = value

    def read(self, path):
        return self.files.get(path)

    def remove(self, path):
        self.files.pop(path, None)


def case():
    memory = Memory()
    store = WindowsCredentialStore(Path("C:/synthetic-root"), memory, memory)
    envelope = CredentialEnvelope(
        UUID(int=101),
        1,
        "reader",
        "synthetic-key",
        SecretStr(base64.b64encode(b"synthetic-key:synthetic-secret").decode()),
    )
    store.put(envelope)
    return memory, store, envelope


def test_private_prepared_readback_matches_exact_key_but_load_still_requires_floor():
    memory, store, envelope = case()
    assert store.read_prepared(envelope.epoch_id, 1, "reader", envelope.key_id) == envelope
    assert store.read_floor_anchor() is None
    with pytest.raises(AccessCredentialError, match="access_epoch_mismatch"):
        store.load(envelope.epoch_id, "reader")


@pytest.mark.parametrize("field", ["epoch_id", "ordinal", "role", "key_id", "secret", "extra"])
def test_mismatched_or_malformed_private_staging_is_never_treated_as_missing(field):
    memory, store, envelope = case()
    path = next(iter(memory.files))
    payload = json.loads(memory.unprotect(memory.files[path]))
    if field == "ordinal":
        payload[field] = True
    elif field == "extra":
        payload[field] = "synthetic-private-marker"
    elif field == "secret":
        payload[field] = base64.b64encode(b"wrong-id:synthetic-secret").decode()
    else:
        payload[field] = "other"
    memory.files[path] = memory.protect(json.dumps(payload).encode())
    with pytest.raises(AccessCredentialError, match="credential_store_denied") as error:
        store.read_prepared(envelope.epoch_id, 1, "reader", envelope.key_id)
    assert "synthetic-private-marker" not in str(error.value)


def test_absent_staging_is_none_without_creating_files_or_anchor():
    memory, store, envelope = case()
    memory.files.clear()
    assert store.read_prepared(envelope.epoch_id, 1, "reader", envelope.key_id) is None
    assert memory.files == {}
