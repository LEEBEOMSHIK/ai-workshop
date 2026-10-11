"""An application cannot enter readiness while the floor disagrees."""

import pytest
from fastapi.testclient import TestClient

from ai_workshop.infrastructure.search.access_credentials import AccessCredentialError
from ai_workshop.labs.rag.indexing.access_epoch_admission import AccessEpochAdmission
from ai_workshop.main import create_app
from tests.unit.infrastructure.local.test_service_launcher import identity
from tests.unit.infrastructure.search.test_access_credentials import public_settings


def test_application_lifespan_requires_actual_admission_before_serving():
    floor = identity()
    settings = public_settings(elasticsearch_access_epoch_id=floor.epoch_id)

    async def load(_settings):
        return floor, False

    async def probe(_settings):
        raise AssertionError("Must reject before I/O")

    admission = AccessEpochAdmission(load, lambda: None, probe)

    async def startup():
        await admission.verify(settings)

    with (
        pytest.raises(AccessCredentialError, match="access_epoch_mismatch"),
        TestClient(create_app(startup_admission=startup)),
    ):
        pytest.fail("Server must not become ready")
