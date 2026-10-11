"""CurrentUser-protected private state, read only at controlled startup."""

import base64
import json
import re
from dataclasses import asdict, fields
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from pydantic import SecretStr

from ai_workshop.infrastructure.search.access_credentials import (
    AccessCredentialError,
    CredentialEnvelope,
    SecuredStoreIdentity,
    ServiceRole,
)


class ProtectionPort(Protocol):
    def protect(self, data: bytes) -> bytes: ...
    def unprotect(self, data: bytes) -> bytes: ...


class PrivateFilePort(Protocol):
    def write(self, path: str, data: bytes) -> None: ...
    def read(self, path: str) -> bytes | None: ...
    def remove(self, path: str) -> None: ...


def identity_json(value: SecuredStoreIdentity) -> bytes:
    data = asdict(value)
    data["epoch_id"] = str(value.epoch_id)
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def identity_from_json(data: bytes) -> SecuredStoreIdentity:
    value = json.loads(data)
    if type(value) is not dict or set(value) != {f.name for f in fields(SecuredStoreIdentity)}:
        raise ValueError("invalid_identity")
    if type(value["ordinal"]) is not int or value["ordinal"] <= 0:
        raise ValueError("invalid_identity")
    for name in ("container_id", "route_sha256", "auth_sha256", "config_sha256", "ca_sha256"):
        if type(value[name]) is not str or re.fullmatch(r"[0-9a-f]{64}", value[name]) is None:
            raise ValueError("invalid_identity")
    for name in ("store_id", "cluster_uuid", "stable_node_id"):
        if (
            type(value[name]) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value[name]) is None
        ):
            raise ValueError("invalid_identity")
    epoch_id = UUID(value["epoch_id"])
    if str(epoch_id) != value["epoch_id"]:
        raise ValueError("invalid_identity")
    return SecuredStoreIdentity(
        value["store_id"],
        value["cluster_uuid"],
        value["ordinal"],
        epoch_id,
        value["container_id"],
        value["stable_node_id"],
        value["route_sha256"],
        value["auth_sha256"],
        value["config_sha256"],
        value["ca_sha256"],
    )


class WindowsCredentialStore:
    def __init__(
        self, root: str | Path, protection: ProtectionPort, files: PrivateFilePort
    ) -> None:
        self.root = Path(root)
        self.protection, self.files = protection, files

    def _path(self, relative: str) -> str:
        return str(self.root / ".local-data/access-epoch/private" / relative)

    def _read(self, relative: str) -> bytes | None:
        try:
            data = self.files.read(self._path(relative))
            return None if data is None else self.protection.unprotect(data)
        except Exception:
            raise AccessCredentialError("credential_store_denied") from None

    def _write(self, relative: str, data: bytes) -> None:
        try:
            self.files.write(self._path(relative), self.protection.protect(data))
        except Exception:
            raise AccessCredentialError("credential_store_denied") from None

    def read_floor_anchor(self) -> SecuredStoreIdentity | None:
        data = self._read("floor.dpapi")
        try:
            return identity_from_json(data) if data is not None else None
        except Exception:
            raise AccessCredentialError("credential_store_denied") from None

    def advance_floor_anchor(self, floor: SecuredStoreIdentity) -> None:
        try:
            if identity_from_json(identity_json(floor)) != floor:
                raise ValueError("invalid_identity")
        except Exception:
            raise AccessCredentialError("credential_store_denied") from None
        previous = self.read_floor_anchor()
        if previous == floor:
            return
        if previous and (
            floor.ordinal <= previous.ordinal
            or floor.store_id != previous.store_id
            or floor.cluster_uuid != previous.cluster_uuid
        ):
            raise AccessCredentialError("access_epoch_mismatch")
        self._write("floor.dpapi", identity_json(floor))
        if self.read_floor_anchor() != floor:
            raise AccessCredentialError("credential_outcome_unknown")

    def put(self, envelope: CredentialEnvelope) -> None:
        if (
            envelope.role not in {"reader", "writer", "collector"}
            or type(envelope.ordinal) is not int
            or envelope.ordinal <= 0
        ):
            raise AccessCredentialError("credential_store_denied")
        relative = f"{envelope.epoch_id}/{envelope.role}.dpapi"
        value = json.dumps(
            {
                "epoch_id": str(envelope.epoch_id),
                "ordinal": envelope.ordinal,
                "role": envelope.role,
                "key_id": envelope.key_id,
                "secret": envelope.secret.get_secret_value(),
            },
            sort_keys=True,
        ).encode()
        existing = self._read(relative)
        if existing is not None and existing != value:
            raise AccessCredentialError("access_epoch_mismatch")
        self._write(relative, value)

    def load(self, epoch_id: UUID, role: ServiceRole) -> CredentialEnvelope:
        floor = self.read_floor_anchor()
        if (
            floor is None
            or floor.epoch_id != epoch_id
            or role not in {"reader", "writer", "collector"}
        ):
            raise AccessCredentialError("access_epoch_mismatch")
        try:
            data = self._read(f"{epoch_id}/{role}.dpapi")
            value = json.loads(data) if data else None
            if type(value) is not dict or set(value) != {
                "epoch_id",
                "ordinal",
                "role",
                "key_id",
                "secret",
            }:
                raise ValueError("invalid_envelope")
            if (
                value["epoch_id"] != str(epoch_id)
                or value["role"] != role
                or type(value["ordinal"]) is not int
                or value["ordinal"] != floor.ordinal
            ):
                raise ValueError("invalid_envelope")
            if any(type(value[k]) is not str or not value[k] for k in ("key_id", "secret")):
                raise ValueError("invalid_envelope")
            return CredentialEnvelope(
                epoch_id,
                floor.ordinal,
                role,
                value["key_id"],
                SecretStr(value["secret"]),
            )
        except Exception:
            raise AccessCredentialError("credential_store_denied") from None

    def read_prepared(
        self, epoch_id: UUID, ordinal: int, role: ServiceRole, key_id: str
    ) -> CredentialEnvelope | None:
        """Private issuance recovery only; does not load or advance a runtime floor."""
        try:
            if (
                type(epoch_id) is not UUID
                or epoch_id.int == 0
                or type(ordinal) is not int
                or ordinal <= 0
                or type(role) is not str
                or role not in {"reader", "writer", "collector"}
                or type(key_id) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", key_id) is None
            ):
                raise ValueError
            data = self._read(f"{epoch_id}/{role}.dpapi")
            if data is None:
                return None
            if len(data) > 8192:
                raise ValueError

            def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
                value: dict[str, object] = {}
                for name, item in pairs:
                    if name in value:
                        raise ValueError
                    value[name] = item
                return value

            value = json.loads(data, object_pairs_hook=unique)
            if type(value) is not dict or set(value) != {
                "epoch_id",
                "ordinal",
                "role",
                "key_id",
                "secret",
            }:
                raise ValueError
            if (
                value["epoch_id"] != str(epoch_id)
                or type(value["ordinal"]) is not int
                or value["ordinal"] != ordinal
                or value["role"] != role
                or value["key_id"] != key_id
                or type(value["secret"]) is not str
                or not 1 <= len(value["secret"]) <= 1024
            ):
                raise ValueError
            decoded = base64.b64decode(value["secret"], validate=True)
            if base64.b64encode(decoded).decode("ascii") != value["secret"]:
                raise ValueError
            credential_id, separator, credential_secret = decoded.partition(b":")
            if (
                credential_id != key_id.encode("ascii")
                or separator != b":"
                or re.fullmatch(rb"[A-Za-z0-9_-]{1,256}", credential_secret) is None
            ):
                raise ValueError
            return CredentialEnvelope(epoch_id, ordinal, role, key_id, SecretStr(value["secret"]))
        except Exception:
            raise AccessCredentialError("credential_store_denied") from None

    def write_launch_record(self, launch_id: UUID, data: dict[str, object]) -> None:
        self._write(f"launches/{launch_id}.dpapi", json.dumps(data, sort_keys=True).encode())

    def read_launch_record(self, launch_id: UUID) -> dict[str, object] | None:
        try:
            data = self._read(f"launches/{launch_id}.dpapi")
            result = json.loads(data) if data else None
            if result is not None and type(result) is not dict:
                raise ValueError("invalid_launch")
            return cast(dict[str, object] | None, result)
        except Exception:
            raise AccessCredentialError("credential_store_denied") from None

    def remove_launch_record(self, launch_id: UUID) -> None:
        try:
            self.files.remove(self._path(f"launches/{launch_id}.dpapi"))
        except Exception:
            raise AccessCredentialError("credential_store_denied") from None
