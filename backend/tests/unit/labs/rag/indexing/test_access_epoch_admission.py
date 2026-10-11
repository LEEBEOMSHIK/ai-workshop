"""Real admission refuses restored config and disagreement between independent floors."""

from dataclasses import replace

import pytest

from ai_workshop.infrastructure.search.access_credentials import AccessCredentialError
from ai_workshop.labs.rag.indexing.access_epoch_admission import AccessEpochAdmission
from tests.unit.infrastructure.local.test_service_launcher import identity
from tests.unit.infrastructure.search.test_access_credentials import public_settings


async def test_public_non_es_startup_allowed_but_writer_requires_capability():
    floor = identity()
    settings = public_settings(elasticsearch_access_epoch_id=floor.epoch_id)

    async def load(_settings):
        return floor, False

    async def probe(_settings):
        raise AssertionError("Non-ES admission must not create a client")

    admission = AccessEpochAdmission(load, lambda: floor, probe)
    await admission.verify(settings, non_es=True)
    with pytest.raises(AccessCredentialError, match="elasticsearch_capability_required"):
        await admission.verify(settings, writer=True)


@pytest.mark.parametrize(
    "condition", ["anchor_missing", "db_missing", "old_config", "unknown", "wrong_server"]
)
async def test_current_floor_is_not_inferred_from_config_or_server_name(condition):
    from uuid import uuid4

    from pydantic import SecretStr

    floor = identity(2)
    settings = public_settings(
        elasticsearch_access_epoch_id=floor.epoch_id,
        elasticsearch_access_epoch=2,
        elasticsearch_role="writer",
        elasticsearch_api_key=SecretStr(uuid4().hex),
    )
    db_floor, anchor, observed, active = floor, floor, floor, False
    if condition == "anchor_missing":
        anchor = None
    elif condition == "db_missing":
        db_floor = None
    elif condition == "old_config":
        settings.elasticsearch_access_epoch = 1
    elif condition == "unknown":
        active = True
    else:
        observed = replace(floor, container_id="f" * 64)

    async def load(_settings):
        return db_floor, active

    async def probe(_settings):
        return observed

    admission = AccessEpochAdmission(load, lambda: anchor, probe)
    with pytest.raises(AccessCredentialError, match="access_epoch_mismatch"):
        await admission.verify(settings, writer=True)
