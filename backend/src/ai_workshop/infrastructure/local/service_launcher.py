"""Fixed new-process launch; credential state never enters the parent env."""

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from ai_workshop.infrastructure.local.credential_store_windows import WindowsCredentialStore
from ai_workshop.infrastructure.search.access_credentials import (
    AccessCredentialError,
    ChildLifetime,
    RegisteredService,
    SecuredStoreIdentity,
    ServiceRole,
)

SERVICE_ROLES: dict[RegisteredService, ServiceRole | None] = {
    "api": "reader",
    "worker": "writer",
    "beat": None,
    "collector": "collector",
    "parity": "writer",
    "ingestion": "writer",
}
SERVICE_MODULES: dict[RegisteredService, str] = {
    "api": "uvicorn",
    "worker": "celery",
    "beat": "celery",
    "collector": "ai_workshop.labs.rag.indexing.alias_recovery_cli",
    "parity": "ai_workshop.labs.rag.indexing.access_epoch_parity_cli",
    "ingestion": "ai_workshop.labs.rag.indexing.access_epoch_ingestion_cli",
}


class ChildRuntimePort(Protocol):
    def start(
        self,
        argv: tuple[str, ...],
        env: dict[str, str],
        cwd: Path,
        identity: SecuredStoreIdentity,
        role: ServiceRole | None,
    ) -> ChildLifetime: ...
    async def wait_ack(self, launch_id: UUID, child: ChildLifetime) -> bool: ...


class ServiceLauncher:
    def __init__(
        self,
        root: str | Path,
        store: WindowsCredentialStore,
        runtime: ChildRuntimePort,
        admission: Callable[[SecuredStoreIdentity], Awaitable[None]],
    ) -> None:
        self.root, self.store, self.runtime, self.admission = Path(root), store, runtime, admission

    async def launch_registered(
        self,
        service: RegisteredService,
        epoch: SecuredStoreIdentity,
        *,
        bound_ids: tuple[UUID, ...] = (),
    ) -> ChildLifetime:
        if service not in SERVICE_ROLES or self.store.read_floor_anchor() != epoch:
            raise AccessCredentialError("access_epoch_mismatch")
        count = {"collector": 3, "parity": 1, "ingestion": 1}.get(service, 0)
        if len(bound_ids) != count or any(type(value) is not UUID for value in bound_ids):
            raise AccessCredentialError("credential_launch_denied")
        # The generic adapter gets an injected verifier; it has no Labs dependency.
        await self.admission(epoch)
        role = SERVICE_ROLES[service]
        credential = self.store.load(epoch.epoch_id, role) if role else None
        child_env = {
            k: v for k, v in os.environ.items() if not k.upper().startswith("AI_WORKSHOP_")
        }
        launch_id = uuid4()
        child_env.update(
            {
                "AI_WORKSHOP_ELASTICSEARCH_ACCESS_EPOCH_ID": str(epoch.epoch_id),
                "AI_WORKSHOP_ELASTICSEARCH_ACCESS_EPOCH": str(epoch.ordinal),
                "AI_WORKSHOP_ACCESS_LAUNCH_ID": str(launch_id),
            }
        )
        if credential:
            child_env["AI_WORKSHOP_ELASTICSEARCH_API_KEY"] = credential.secret.get_secret_value()
            child_env["AI_WORKSHOP_ELASTICSEARCH_ROLE"] = credential.role
        argv = (
            str(self.root / "backend/.venv/Scripts/python.exe"),
            "-m",
            "ai_workshop.infrastructure.local.service_entrypoint",
            service,
        )
        try:
            child = self.runtime.start(argv, child_env, self.root, epoch, role)
            if (
                child.epoch_id != epoch.epoch_id
                or child.role != role
                or child.environment_epoch != epoch.ordinal
                or child.module != SERVICE_MODULES[service]
            ):
                raise AccessCredentialError("credential_launch_denied")
            self.store.write_launch_record(
                launch_id,
                {
                    "kind": "authorized",
                    "launch_id": str(launch_id),
                    "service": service,
                    "module": SERVICE_MODULES[service],
                    "pid": child.pid,
                    "creation_time": child.creation_time,
                    "role": role,
                    "epoch_id": str(epoch.epoch_id),
                    "ordinal": epoch.ordinal,
                    "key_id": credential.key_id if credential else None,
                    "bound_ids": [str(value) for value in bound_ids],
                },
            )
            if not await self.runtime.wait_ack(launch_id, child):
                raise AccessCredentialError("credential_outcome_unknown")
            self.store.remove_launch_record(launch_id)
            return child
        except AccessCredentialError:
            raise
        except Exception:
            raise AccessCredentialError("credential_launch_denied") from None
