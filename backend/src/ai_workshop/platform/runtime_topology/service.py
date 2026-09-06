from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_workshop.platform.runtime_topology.domain import (
    CompatibilityLane,
    RuntimeNode,
    RuntimeObservation,
    RuntimeStorage,
    RuntimeTopology,
)


class RuntimeTopologyManifestError(ValueError):
    """Raised when the safe topology manifest is invalid."""


SafeId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*$")]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _NodeManifest(_StrictModel):
    id: SafeId
    display_name: str
    kind: Literal["process", "service", "job", "tool"]
    runtime_target: str
    process_role: str
    dependencies: tuple[SafeId, ...]
    storages: tuple[SafeId, ...]
    capabilities: tuple[str, ...]
    activation: str
    healthcheck_declared: bool


class _StorageManifest(_StrictModel):
    id: SafeId
    display_name: str
    purpose: str
    persistence: Literal["ephemeral", "persistent"]


class _CompatibilityManifest(_StrictModel):
    id: SafeId
    display_name: str
    device: Literal["cpu", "gpu"]
    runtime_target: str
    verification_state: Literal["verified", "unverified"]
    verification_note: str


class _TopologyManifest(_StrictModel):
    schema_version: Literal[1]
    topology_version: SafeId
    environment_kind: Literal["local-compose"]
    nodes: tuple[_NodeManifest, ...]
    storages: tuple[_StorageManifest, ...]
    compatibility: tuple[_CompatibilityManifest, ...]


class RuntimeTopologyService:
    def __init__(self, manifest_path: Path | None = None) -> None:
        self._manifest_path = manifest_path

    def load(self) -> RuntimeTopology:
        try:
            payload = yaml.safe_load(self._read_manifest())
            manifest = _TopologyManifest.model_validate(payload)
            self._validate_references(manifest)
        except (OSError, UnicodeError, yaml.YAMLError, ValidationError, ValueError) as error:
            if isinstance(error, RuntimeTopologyManifestError):
                raise
            raise RuntimeTopologyManifestError(
                f"invalid runtime topology manifest: {error}"
            ) from error

        nodes = tuple(
            RuntimeNode(
                **node.model_dump(),
                observation=(
                    RuntimeObservation.RESPONDING
                    if node.id == "api"
                    else RuntimeObservation.NOT_OBSERVED
                ),
            )
            for node in manifest.nodes
        )
        return RuntimeTopology(
            schema_version=manifest.schema_version,
            topology_version=manifest.topology_version,
            environment_kind=manifest.environment_kind,
            nodes=nodes,
            storages=tuple(RuntimeStorage(**item.model_dump()) for item in manifest.storages),
            compatibility_lanes=tuple(
                CompatibilityLane(**item.model_dump()) for item in manifest.compatibility
            ),
        )

    def _read_manifest(self) -> str:
        if self._manifest_path is not None:
            return self._manifest_path.read_text(encoding="utf-8")
        resource = files("ai_workshop.platform.runtime_topology").joinpath(
            "runtime-topology-v1.yaml"
        )
        return resource.read_text(encoding="utf-8")

    @staticmethod
    def _validate_references(manifest: _TopologyManifest) -> None:
        RuntimeTopologyService._require_unique(
            (node.id for node in manifest.nodes), "node"
        )
        RuntimeTopologyService._require_unique(
            (storage.id for storage in manifest.storages), "storage"
        )
        RuntimeTopologyService._require_unique(
            (lane.id for lane in manifest.compatibility), "compatibility"
        )
        node_ids = {node.id for node in manifest.nodes}
        storage_ids = {storage.id for storage in manifest.storages}
        for node in manifest.nodes:
            for dependency in node.dependencies:
                if dependency not in node_ids:
                    raise RuntimeTopologyManifestError(
                        f"invalid runtime topology manifest: unknown dependency {dependency}"
                    )
            for storage in node.storages:
                if storage not in storage_ids:
                    raise RuntimeTopologyManifestError(
                        f"invalid runtime topology manifest: unknown storage {storage}"
                    )

    @staticmethod
    def _require_unique(values: Iterable[str], label: str) -> None:
        seen: set[str] = set()
        for value in values:
            if value in seen:
                raise RuntimeTopologyManifestError(
                    f"invalid runtime topology manifest: duplicate {label} id {value}"
                )
            seen.add(value)
