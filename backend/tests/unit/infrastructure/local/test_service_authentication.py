"""The child uses the actual authenticate response, which has no API-key metadata."""

from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.infrastructure.local.service_bootstrap_context import VerifiedLaunchCapability
from ai_workshop.infrastructure.local.service_entrypoint import _authenticate
from ai_workshop.infrastructure.search.access_credentials import AccessCredentialError
from tests.unit.infrastructure.search.test_access_credentials import public_settings


class Security:
    async def authenticate(self):
        return {
            "authentication_type": "api_key",
            "api_key": {
                "id": "synthetic-key-id",
                "name": "synthetic-key-name",
                "managed_by": "elasticsearch",
                "internal": False,
            },
        }


class Client:
    def __init__(self):
        self.security, self.closed = Security(), False

    async def close(self):
        self.closed = True


async def test_exact_protected_key_id_authenticates_without_unavailable_metadata(monkeypatch):
    from ai_workshop.infrastructure.local import service_entrypoint as entry

    client = Client()
    monkeypatch.setattr(entry, "create_elasticsearch", lambda _settings: client)
    capability = VerifiedLaunchCapability(
        uuid4(),
        "worker",
        "celery",
        1001,
        "synthetic-time",
        "writer",
        uuid4(),
        1,
        "synthetic-key-id",
        "a" * 64,
        (),
    )
    await _authenticate(public_settings(), capability)
    assert client.closed
    with pytest.raises(AccessCredentialError, match="credential_launch_denied"):
        await _authenticate(public_settings(), replace(capability, key_id="another-key-id"))
