"""Registered single-job writer launch uses the protected existing birth protocol."""

import importlib
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr

from ai_workshop.infrastructure.local.credential_store_windows import WindowsCredentialStore
from ai_workshop.infrastructure.local.service_launcher import ServiceLauncher
from ai_workshop.infrastructure.search.access_credentials import (
    AccessCredentialError,
    CredentialEnvelope,
)


async def test_ingestion_requires_one_bound_job_and_only_writer_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workshop.infrastructure.local import service_launcher as launcher_module

    monkeypatch.setattr(
        launcher_module,
        "approved_python",
        lambda _root: SimpleNamespace(executable=Path("C:/synthetic-conda/python.exe")),
    )
    fixtures: Any = importlib.import_module("tests.unit.infrastructure.local.test_service_launcher")
    protected, runtime = fixtures.ProtectedMemory(), fixtures.Runtime()
    store = WindowsCredentialStore("C:/synthetic-workshop", protected, protected)
    epoch = fixtures.identity()
    store.advance_floor_anchor(epoch)
    store.put(CredentialEnvelope(epoch.epoch_id, epoch.ordinal, "writer", "key", SecretStr("fake")))

    async def admitted(_value: object) -> None:
        return None

    launcher = ServiceLauncher("C:/synthetic-workshop", store, runtime, admitted)
    for ids in ((), (uuid4(), uuid4())):
        with pytest.raises(AccessCredentialError):
            await launcher.launch_registered("ingestion", epoch, bound_ids=ids)
    assert runtime.started == []
    before = dict(os.environ)
    child = await launcher.launch_registered("ingestion", epoch, bound_ids=(uuid4(),))
    assert child.module == "ai_workshop.labs.rag.indexing.access_epoch_ingestion_cli"
    assert child.role == "writer"
    assert len(runtime.started) == 1
    assert runtime.started[0][0][-1] == "ingestion"
    assert dict(os.environ) == before


@pytest.mark.parametrize("mode", ["valid", "missing", "extra", "malformed"])
def test_ingestion_entrypoint_verifies_bound_job_before_module(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    entry = importlib.import_module("ai_workshop.infrastructure.local.service_entrypoint")
    launch, epoch, job = uuid4(), uuid4(), uuid4()
    bound = {
        "valid": [str(job)],
        "missing": [],
        "extra": [str(job), str(uuid4())],
        "malformed": ["PRIVATE"],
    }[mode]
    authorized = {
        "kind": "authorized",
        "launch_id": str(launch),
        "service": "ingestion",
        "module": "ai_workshop.labs.rag.indexing.access_epoch_ingestion_cli",
        "role": "writer",
        "pid": os.getpid(),
        "creation_time": "123",
        "epoch_id": str(epoch),
        "ordinal": 1,
        "key_id": "fake",
        "bound_ids": bound,
    }
    calls: list[object] = []

    class Store:
        def read_floor_anchor(self) -> Any:
            return SimpleNamespace(epoch_id=epoch, ordinal=1)

        def write_launch_record(self, _id: object, value: Any) -> None:
            calls.append(value["kind"])

        def read_launch_record(self, _id: object) -> Any:
            return authorized

    async def authenticate(_settings: object, capability: Any) -> None:
        assert capability.bound_ids == (job,)
        calls.append("authenticated")

    def execute(module: str, *, run_name: str) -> None:
        assert module == "ai_workshop.labs.rag.indexing.access_epoch_ingestion_cli"
        assert run_name == "__main__"
        assert entry.sys.argv == ["access_epoch_ingestion_cli", "--job", str(job)]
        calls.append("run")

    monkeypatch.setenv("AI_WORKSHOP_ACCESS_LAUNCH_ID", str(launch))
    monkeypatch.setattr(entry.sys, "argv", ["service_entrypoint", "ingestion"])
    monkeypatch.setattr(entry, "NativeWindowsPrivateState", lambda _root: object())
    monkeypatch.setattr(entry, "WindowsCredentialStore", lambda *_args: Store())
    monkeypatch.setattr(entry, "process_identity", lambda _pid: ("123", None))
    monkeypatch.setattr(
        entry,
        "Settings",
        lambda **_kw: SimpleNamespace(
            elasticsearch_access_epoch_id=epoch,
            elasticsearch_access_epoch=1,
            elasticsearch_role="writer",
        ),
    )
    monkeypatch.setattr(entry, "_authenticate", authenticate)
    monkeypatch.setattr(entry, "register_verified_launch", lambda _cap: calls.append("registered"))
    monkeypatch.setattr(entry.runpy, "run_module", execute)
    if mode == "valid":
        entry.main()
        assert calls == ["hello", "authenticated", "registered", "ack", "run"]
    else:
        with pytest.raises(SystemExit, match="credential_launch_denied"):
            entry.main()
        assert "run" not in calls and "authenticated" not in calls
