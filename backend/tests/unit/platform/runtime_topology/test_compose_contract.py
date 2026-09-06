import tomllib
from pathlib import Path
from typing import Any

import yaml

from ai_workshop.platform.runtime_topology.service import RuntimeTopologyService

REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
COMPOSE_PATH = REPOSITORY_ROOT / "infrastructure" / "compose" / "compose.yaml"
PYPROJECT_PATH = REPOSITORY_ROOT / "backend" / "pyproject.toml"


def load_compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def service_runtime_target(service: dict[str, Any]) -> str:
    build = service.get("build")
    if isinstance(build, dict):
        return str(build["target"])
    return str(service["image"])


def service_dependencies(service: dict[str, Any]) -> tuple[str, ...]:
    dependencies = service.get("depends_on", {})
    if isinstance(dependencies, list):
        return tuple(sorted(str(item) for item in dependencies))
    return tuple(sorted(str(item) for item in dependencies))


def service_storages(
    service: dict[str, Any], named_volumes: set[str]
) -> tuple[str, ...]:
    topology_override = service.get("x-ai-workshop-topology", {})
    if "storages" in topology_override:
        return tuple(sorted(str(item) for item in topology_override["storages"]))
    result: list[str] = []
    for mount in service.get("volumes", []):
        source = str(mount).split(":", maxsplit=1)[0]
        if source in named_volumes:
            result.append(source)
    return tuple(sorted(result))


def test_compose_matches_safe_topology_execution_contract() -> None:
    compose = load_compose()
    topology = RuntimeTopologyService().load()
    services = compose["services"]
    named_volumes = set(compose["volumes"])

    assert set(services) == {node.id for node in topology.nodes}
    assert named_volumes == {storage.id for storage in topology.storages}
    for node in topology.nodes:
        service = services[node.id]
        assert service_runtime_target(service) == node.runtime_target
        assert service_dependencies(service) == tuple(sorted(node.dependencies))
        assert service_storages(service, named_volumes) == tuple(sorted(node.storages))
        assert tuple(service.get("profiles", [])) == (
            () if node.activation == "default" else (node.activation,)
        )
        assert ("healthcheck" in service) is node.healthcheck_declared


def test_worker_alone_uses_cpu_ocr_target() -> None:
    services = load_compose()["services"]

    assert services["worker"]["build"]["target"] == "runtime-ocr-cpu"
    assert services["worker"]["build"]["platforms"] == ["linux/amd64"]
    assert services["worker"]["platform"] == "linux/amd64"
    assert services["api"]["build"]["target"] == "runtime-core"
    assert services["beat"]["build"]["target"] == "runtime-core"
    assert services["object-store-init"]["build"]["target"] == "runtime-core"
    assert services["ocr-linux-cpu-smoke"]["build"]["target"] == "runtime-ocr-cpu"
    assert services["ocr-linux-cpu-smoke"]["build"]["platforms"] == ["linux/amd64"]
    assert services["ocr-linux-cpu-smoke"]["platform"] == "linux/amd64"


def test_cpu_ocr_extra_is_explicit_and_the_ambiguous_extra_is_absent() -> None:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    extras = pyproject["project"]["optional-dependencies"]

    assert "ocr" not in extras
    assert extras["ocr-cpu"] == [
        "paddleocr==3.7.0",
        "paddlepaddle==3.2.2",
        "paddlex[ocr]==3.7.2",
    ]


def test_linux_cpu_smoke_is_offline_non_root_and_uses_read_only_artifacts() -> None:
    service = load_compose()["services"]["ocr-linux-cpu-smoke"]

    assert service["network_mode"] == "none"
    assert service["user"] == "10001:10001"
    assert service["environment"]["AI_WORKSHOP_OCR_SMOKE_MANIFEST_PATH"] == (
        "/app/model-profiles/rag/ocr/pp-structure-v3-v1.json"
    )
    assert service["environment"]["AI_WORKSHOP_MODEL_CACHE_ROOT"] == "/models"
    assert "model-cache:/models:ro" in service["volumes"]
    assert "../../model-profiles:/app/model-profiles:ro" in service["volumes"]
