"""Actual Celery signals cannot swallow denied epoch admission."""

from dataclasses import dataclass

import pytest
from celery.signals import beat_init, task_prerun, worker_init

from ai_workshop.labs.rag.indexing.access_epoch_admission import AccessEpochAdmission
from ai_workshop.labs.rag.indexing.access_epoch_worker import register_celery_admission
from tests.unit.infrastructure.local.test_service_launcher import identity
from tests.unit.infrastructure.search.test_access_credentials import public_settings


@dataclass(eq=False)
class Sender:
    app: object
    name: str = ""


def test_denied_worker_and_stale_task_exit_before_execution():
    application = object()
    floor = identity()
    settings = public_settings(elasticsearch_access_epoch_id=floor.epoch_id)

    async def load(_settings):
        return floor, False

    async def probe(_settings):
        raise AssertionError("Must deny before ES I/O")

    admission = AccessEpochAdmission(load, lambda: None, probe)
    register_celery_admission(application, lambda: settings, admission.verify)
    sender = Sender(app=application, name="ai_workshop.rag.ensure_indexed")
    for signal in (worker_init, task_prerun):
        with pytest.raises(SystemExit, match="access_epoch_mismatch"):
            signal.send(sender=sender)


def test_beat_uses_key_free_admission_and_ignores_other_applications():
    application = object()
    calls = []

    async def verify(_settings, **kwargs):
        calls.append(kwargs)

    settings = public_settings()
    register_celery_admission(application, lambda: settings, verify)
    beat_init.send(sender=Sender(app=application))
    beat_init.send(sender=Sender(app=object()))
    assert calls == [{"writer": False, "non_es": True}]
