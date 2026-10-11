"""A fixed child verifies its protected birth record before importing an app."""

import asyncio
import hashlib
import json
import os
import runpy
import sys
import time
from pathlib import Path
from typing import cast
from uuid import UUID

from ai_workshop.config import Settings
from ai_workshop.infrastructure.local.credential_store_windows import WindowsCredentialStore
from ai_workshop.infrastructure.local.service_bootstrap_context import (
    VerifiedLaunchCapability,
    register_verified_launch,
)
from ai_workshop.infrastructure.local.service_launcher import SERVICE_MODULES, SERVICE_ROLES
from ai_workshop.infrastructure.local.windows_private_state import NativeWindowsPrivateState
from ai_workshop.infrastructure.local.windows_process import process_identity
from ai_workshop.infrastructure.search.access_credentials import (
    AccessCredentialError,
)
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.shared.asyncio_policy import configure_windows_selector_policy


async def _authenticate(settings: Settings, capability: VerifiedLaunchCapability) -> None:
    if capability.role is None:
        if settings.elasticsearch_api_key is not None:
            raise AccessCredentialError("credential_launch_denied")
        return
    client = create_elasticsearch(settings)
    try:
        response = await client.security.authenticate()
        key = response.get("api_key", {})
        if key.get("id") != capability.key_id or response.get("authentication_type") != "api_key":
            raise AccessCredentialError("credential_launch_denied")
    finally:
        await client.close()


def main() -> None:
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in SERVICE_ROLES:
            raise AccessCredentialError("credential_launch_denied")
        service = sys.argv[1]
        root = Path(__file__).absolute().parents[5]
        native = NativeWindowsPrivateState(root)
        store = WindowsCredentialStore(root, native, native)
        launch_id = UUID(os.environ["AI_WORKSHOP_ACCESS_LAUNCH_ID"])
        pid = os.getpid()
        created, _image = process_identity(pid)
        floor = store.read_floor_anchor()
        if floor is None:
            raise AccessCredentialError("credential_launch_denied")
        store.write_launch_record(
            launch_id,
            {
                "kind": "hello",
                "pid": pid,
                "creation_time": created,
                "service": service,
                "epoch_id": str(floor.epoch_id),
                "ordinal": floor.ordinal,
            },
        )
        deadline = time.monotonic() + 30
        authorized = None
        while time.monotonic() < deadline:
            record = store.read_launch_record(launch_id)
            if record and record.get("kind") == "authorized":
                authorized = record
                break
            time.sleep(0.05)
        if (
            authorized is None
            or authorized.get("pid") != pid
            or authorized.get("creation_time") != created
            or authorized.get("service") != service
            or authorized.get("module") != SERVICE_MODULES[service]
            or authorized.get("role") != SERVICE_ROLES[service]
            or authorized.get("epoch_id") != str(floor.epoch_id)
            or authorized.get("ordinal") != floor.ordinal
            or authorized.get("launch_id") != str(launch_id)
        ):
            raise AccessCredentialError("credential_launch_denied")
        ids = authorized.get("bound_ids")
        count = {"collector": 3, "parity": 1, "ingestion": 1}.get(service, 0)
        if (
            type(ids) is not list
            or len(ids) != count
            or any(type(v) is not str or str(UUID(v)) != v for v in ids)
        ):
            raise AccessCredentialError("credential_launch_denied")
        capability = VerifiedLaunchCapability(
            launch_id,
            service,
            SERVICE_MODULES[service],
            pid,
            created,
            SERVICE_ROLES[service],
            floor.epoch_id,
            floor.ordinal,
            cast(str | None, authorized["key_id"]),
            hashlib.sha256(
                json.dumps(authorized, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            tuple(UUID(value) for value in ids),
        )
        settings = Settings(_env_file=root / ".env")  # type: ignore[call-arg]
        if (
            settings.elasticsearch_access_epoch_id != floor.epoch_id
            or settings.elasticsearch_access_epoch != floor.ordinal
            or settings.elasticsearch_role != capability.role
        ):
            raise AccessCredentialError("credential_launch_denied")
        configure_windows_selector_policy()
        asyncio.run(_authenticate(settings, capability))
        register_verified_launch(capability)
        store.write_launch_record(launch_id, {**authorized, "kind": "ack"})
        arguments = {
            "api": [
                "uvicorn",
                "ai_workshop.main:app",
                "--loop",
                "ai_workshop.shared.asyncio_policy:create_selector_event_loop",
                "--host",
                "127.0.0.1",
                "--port",
                "18000",
            ],
            "worker": [
                "celery",
                "-A",
                "ai_workshop.worker:celery_app",
                "worker",
                "--pool=solo",
                "--loglevel=INFO",
            ],
            "beat": [
                "celery",
                "-A",
                "ai_workshop.worker:celery_app",
                "beat",
                "--loglevel=INFO",
                "--schedule",
                ".local-data/celerybeat-schedule",
            ],
            "collector": [
                "alias_recovery_cli",
                "recover-access-epoch",
                "--operation",
                str(capability.bound_ids[0]),
                "--actor",
                str(capability.bound_ids[1]),
                "--request",
                str(capability.bound_ids[2]),
            ]
            if service == "collector"
            else [],
            "parity": ["access_epoch_parity_cli", "--profile", str(capability.bound_ids[0])]
            if service == "parity"
            else [],
            "ingestion": ["access_epoch_ingestion_cli", "--job", str(capability.bound_ids[0])]
            if service == "ingestion"
            else [],
        }
        sys.argv = arguments[service]
        runpy.run_module(SERVICE_MODULES[service], run_name="__main__")
    except Exception:
        # Startup errors never print raw SDK, configuration or authentication content.
        raise SystemExit("credential_launch_denied") from None


if __name__ == "__main__":
    main()
