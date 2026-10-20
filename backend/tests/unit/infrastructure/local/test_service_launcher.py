"""Only new fixed children receive current role keys; parent state is unchanged."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr

from ai_workshop.infrastructure.local.credential_store_windows import WindowsCredentialStore
from ai_workshop.infrastructure.local.service_launcher import ServiceLauncher
from ai_workshop.infrastructure.search.access_credentials import (
    AccessCredentialError,
    ChildLifetime,
    CredentialEnvelope,
    SecuredStoreIdentity,
)


@pytest.fixture(autouse=True)
def approved_runtime(monkeypatch):
    from ai_workshop.infrastructure.local import service_launcher as module

    monkeypatch.setattr(
        module,
        "approved_python",
        lambda root: SimpleNamespace(
            executable=Path("C:/synthetic-conda/python.exe"), sha256="a" * 64
        ),
        raising=False,
    )


class ProtectedMemory:
    def __init__(self):
        self.files, self.plaintexts = {}, {}
        self.denied = False

    def protect(self, data):
        opaque = uuid4().bytes
        self.plaintexts[opaque] = data
        return opaque

    def unprotect(self, data):
        return self.plaintexts[data]

    def write(self, path, data):
        if self.denied:
            raise OSError("private error must not escape")
        self.files[path] = data

    def read(self, path):
        if self.denied:
            raise OSError("private error must not escape")
        return self.files.get(path)

    def remove(self, path):
        self.files.pop(path, None)


class Runtime:
    def __init__(self):
        self.started = []

    def start(self, argv, env, cwd, identity, role):
        from ai_workshop.infrastructure.local.service_launcher import SERVICE_MODULES

        self.started.append((argv, dict(env), cwd))
        return ChildLifetime(
            1001,
            "synthetic-creation",
            SERVICE_MODULES[argv[3]],
            role,
            identity.epoch_id,
            identity.ordinal,
        )

    async def wait_ack(self, launch_id, child):
        return True


def identity(ordinal=1):
    return SecuredStoreIdentity(
        "rag",
        "cluster",
        ordinal,
        uuid4(),
        "a" * 64,
        "stable",
        "b" * 64,
        "c" * 64,
        "d" * 64,
        "e" * 64,
    )


async def test_only_fixed_new_worker_gets_one_current_key_without_parent_mutation():
    protected, runtime = ProtectedMemory(), Runtime()
    store = WindowsCredentialStore("C:/synthetic-workshop", protected, protected)
    epoch = identity()
    store.advance_floor_anchor(epoch)
    secret = uuid4().hex
    store.put(CredentialEnvelope(epoch.epoch_id, 1, "writer", "key-id", SecretStr(secret)))
    before = dict(os.environ)

    async def admitted(_identity):
        return None

    launcher = ServiceLauncher("C:/synthetic-workshop", store, runtime, admitted)
    child = await launcher.launch_registered("worker", epoch)
    assert dict(os.environ) == before
    assert child.role == "writer" and child.environment_epoch == 1
    assert runtime.started[0][1]["AI_WORKSHOP_ELASTICSEARCH_API_KEY"] == secret
    assert runtime.started[0][0][0] == str(Path("C:/synthetic-conda/python.exe"))
    assert runtime.started[0][0][1:3] == (
        "-m",
        "ai_workshop.infrastructure.local.service_entrypoint",
    )
    assert secret not in repr(child) and secret not in repr(store)


async def test_non_es_beat_has_no_key_and_mismatched_floor_never_starts():
    protected, runtime = ProtectedMemory(), Runtime()
    store = WindowsCredentialStore("C:/synthetic-workshop", protected, protected)
    epoch = identity()
    store.advance_floor_anchor(epoch)

    async def admitted(_identity):
        return None

    launcher = ServiceLauncher("C:/synthetic-workshop", store, runtime, admitted)
    await launcher.launch_registered("beat", epoch)
    assert "AI_WORKSHOP_ELASTICSEARCH_API_KEY" not in runtime.started[0][1]
    with pytest.raises(AccessCredentialError, match="access_epoch_mismatch"):
        await launcher.launch_registered("worker", identity(2))
    assert len(runtime.started) == 1


def test_floor_cannot_decrease_or_substitute_and_private_errors_are_sanitized():
    protected = ProtectedMemory()
    store = WindowsCredentialStore("C:/synthetic-workshop", protected, protected)
    current = identity(2)
    store.advance_floor_anchor(current)
    for wrong in (identity(1), identity(2)):
        with pytest.raises(AccessCredentialError, match="access_epoch_mismatch"):
            store.advance_floor_anchor(wrong)
    protected.denied = True
    with pytest.raises(AccessCredentialError, match="credential_store_denied") as error:
        store.read_floor_anchor()
    assert "private error" not in str(error.value)


async def test_collector_requires_exact_bound_claim_before_starting():
    protected, runtime = ProtectedMemory(), Runtime()
    store = WindowsCredentialStore("C:/synthetic-workshop", protected, protected)
    epoch = identity()
    store.advance_floor_anchor(epoch)
    store.put(
        CredentialEnvelope(
            epoch.epoch_id,
            epoch.ordinal,
            "collector",
            "synthetic-key-id",
            SecretStr("synthetic-transient-key"),
        )
    )

    async def admitted(_identity):
        return None

    launcher = ServiceLauncher("C:/synthetic-workshop", store, runtime, admitted)
    with pytest.raises(AccessCredentialError):
        await launcher.launch_registered("collector", epoch)
    assert runtime.started == []
    await launcher.launch_registered("collector", epoch, bound_ids=(uuid4(), uuid4(), uuid4()))
    assert runtime.started[0][0][-1] == "collector"


async def test_wrong_interpreter_never_starts_and_runtime_error_is_sanitized(monkeypatch):
    from ai_workshop.infrastructure.local import service_launcher as module
    from ai_workshop.infrastructure.local.python_runtime import PythonRuntimeError

    protected, runtime = ProtectedMemory(), Runtime()
    store = WindowsCredentialStore("C:/synthetic-workshop", protected, protected)
    epoch = identity()
    store.advance_floor_anchor(epoch)

    def denied(root):
        raise PythonRuntimeError()

    async def admitted(_identity):
        monkeypatch.setattr(module, "approved_python", denied)

    launcher = ServiceLauncher("C:/synthetic-workshop", store, runtime, admitted)
    with pytest.raises(AccessCredentialError, match="^credential_launch_denied$"):
        await launcher.launch_registered("beat", epoch)
    assert runtime.started == []
