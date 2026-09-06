from pydantic import BaseModel, ConfigDict

from ai_workshop.platform.runtime_topology.domain import (
    CompatibilityLane,
    RuntimeNode,
    RuntimeStorage,
    RuntimeTopology,
)


class _ResponseModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class RuntimeNodeResponse(_ResponseModel):
    id: str
    display_name: str
    kind: str
    runtime_target: str
    process_role: str
    dependencies: tuple[str, ...]
    storages: tuple[str, ...]
    capabilities: tuple[str, ...]
    activation: str
    healthcheck_declared: bool
    observation: str

    @classmethod
    def from_domain(cls, node: RuntimeNode) -> "RuntimeNodeResponse":
        return cls(
            id=node.id,
            display_name=node.display_name,
            kind=node.kind,
            runtime_target=node.runtime_target,
            process_role=node.process_role,
            dependencies=node.dependencies,
            storages=node.storages,
            capabilities=node.capabilities,
            activation=node.activation,
            healthcheck_declared=node.healthcheck_declared,
            observation=node.observation,
        )


class RuntimeStorageResponse(_ResponseModel):
    id: str
    display_name: str
    purpose: str
    persistence: str

    @classmethod
    def from_domain(cls, storage: RuntimeStorage) -> "RuntimeStorageResponse":
        return cls(
            id=storage.id,
            display_name=storage.display_name,
            purpose=storage.purpose,
            persistence=storage.persistence,
        )


class CompatibilityLaneResponse(_ResponseModel):
    id: str
    display_name: str
    device: str
    runtime_target: str
    verification_state: str
    verification_note: str

    @classmethod
    def from_domain(cls, lane: CompatibilityLane) -> "CompatibilityLaneResponse":
        return cls(
            id=lane.id,
            display_name=lane.display_name,
            device=lane.device,
            runtime_target=lane.runtime_target,
            verification_state=lane.verification_state,
            verification_note=lane.verification_note,
        )


class RuntimeTopologyResponse(_ResponseModel):
    schema_version: int
    topology_version: str
    environment_kind: str
    nodes: tuple[RuntimeNodeResponse, ...]
    storages: tuple[RuntimeStorageResponse, ...]
    compatibility: tuple[CompatibilityLaneResponse, ...]

    @classmethod
    def from_domain(cls, topology: RuntimeTopology) -> "RuntimeTopologyResponse":
        return cls(
            schema_version=topology.schema_version,
            topology_version=topology.topology_version,
            environment_kind=topology.environment_kind,
            nodes=tuple(RuntimeNodeResponse.from_domain(node) for node in topology.nodes),
            storages=tuple(
                RuntimeStorageResponse.from_domain(storage) for storage in topology.storages
            ),
            compatibility=tuple(
                CompatibilityLaneResponse.from_domain(lane)
                for lane in topology.compatibility_lanes
            ),
        )
