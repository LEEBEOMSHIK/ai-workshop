from pathlib import Path

import pytest

from ai_workshop.platform.runtime_topology.domain import RuntimeObservation
from ai_workshop.platform.runtime_topology.service import (
    RuntimeTopologyManifestError,
    RuntimeTopologyService,
)


def test_default_manifest_describes_services_storage_and_compatibility() -> None:
    topology = RuntimeTopologyService().load()

    assert {node.id for node in topology.nodes} == {
        "api",
        "beat",
        "e2e",
        "elasticsearch",
        "migrate",
        "model-tools",
        "object-store-init",
        "ocr-linux-cpu-smoke",
        "postgres",
        "redis",
        "worker",
    }
    assert {storage.id for storage in topology.storages} == {
        "elasticsearch-data",
        "model-cache",
        "object-data",
        "postgres-data",
        "redis-data",
    }
    assert topology.node("api").observation is RuntimeObservation.RESPONDING
    assert topology.node("worker").observation is RuntimeObservation.NOT_OBSERVED
    assert topology.compatibility("windows-cpu").verification_state == "verified"
    assert topology.compatibility("linux-cpu").verification_state == "unverified"
    assert topology.compatibility("linux-gpu").verification_state == "unverified"


def test_manifest_rejects_unknown_fields(tmp_path: Path) -> None:
    manifest = tmp_path / "runtime.yaml"
    manifest.write_text(
        """
schema_version: 1
topology_version: local-compose-v1
environment_kind: local-compose
nodes: []
storages: []
compatibility: []
secret: must-not-be-accepted
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeTopologyManifestError, match="invalid runtime topology manifest"):
        RuntimeTopologyService(manifest_path=manifest).load()


def test_manifest_rejects_dangling_dependency_and_storage_references(tmp_path: Path) -> None:
    manifest = tmp_path / "runtime.yaml"
    manifest.write_text(
        """
schema_version: 1
topology_version: local-compose-v1
environment_kind: local-compose
nodes:
  - id: api
    display_name: API
    kind: process
    runtime_target: runtime-core
    process_role: http-api
    dependencies: [missing-service]
    storages: [missing-storage]
    capabilities: [http]
    activation: default
    healthcheck_declared: true
storages: []
compatibility: []
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeTopologyManifestError, match="unknown dependency missing-service"):
        RuntimeTopologyService(manifest_path=manifest).load()


def test_manifest_rejects_duplicate_node_ids(tmp_path: Path) -> None:
    manifest = tmp_path / "runtime.yaml"
    manifest.write_text(
        """
schema_version: 1
topology_version: local-compose-v1
environment_kind: local-compose
nodes:
  - &node
    id: api
    display_name: API
    kind: process
    runtime_target: runtime-core
    process_role: http-api
    dependencies: []
    storages: []
    capabilities: [http]
    activation: default
    healthcheck_declared: true
  - *node
storages: []
compatibility: []
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeTopologyManifestError, match="duplicate node id api"):
        RuntimeTopologyService(manifest_path=manifest).load()
