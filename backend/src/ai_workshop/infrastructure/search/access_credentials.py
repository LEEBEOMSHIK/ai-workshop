"""Generic service capabilities, without any RAG imports or secret audit data."""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from pydantic import SecretStr

type ServiceRole = Literal["reader", "writer", "collector"]
type RegisteredService = Literal["api", "worker", "beat", "collector", "parity", "ingestion"]


@dataclass(frozen=True, slots=True)
class CredentialEnvelope:
    epoch_id: UUID
    ordinal: int
    role: ServiceRole
    key_id: str
    secret: SecretStr = field(repr=False)


@dataclass(frozen=True, slots=True)
class SecuredStoreIdentity:
    store_id: str
    cluster_uuid: str
    ordinal: int
    epoch_id: UUID
    container_id: str
    stable_node_id: str
    route_sha256: str
    auth_sha256: str
    config_sha256: str
    ca_sha256: str


@dataclass(frozen=True, slots=True)
class ChildLifetime:
    pid: int
    creation_time: str
    module: str
    role: ServiceRole | None
    epoch_id: UUID
    environment_epoch: int
    launcher_pid: int | None = None
    launcher_creation_time: str | None = None


class AccessCredentialError(ValueError):
    """Finite codes only; no native error, path or secret is interpolated."""

    def __init__(self, code: str) -> None:
        if code not in {
            "elasticsearch_capability_required",
            "access_epoch_mismatch",
            "credential_store_denied",
            "credential_launch_denied",
            "credential_outcome_unknown",
            "elasticsearch_tls_invalid",
        }:
            raise ValueError("invalid_access_credential_code")
        self.code = code
        super().__init__(code)
