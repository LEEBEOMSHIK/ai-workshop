from dataclasses import dataclass, replace
from enum import StrEnum


class RuntimeObservation(StrEnum):
    RESPONDING = "responding"
    NOT_OBSERVED = "not_observed"


@dataclass(frozen=True, slots=True)
class RuntimeNode:
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
    observation: RuntimeObservation = RuntimeObservation.NOT_OBSERVED

    def with_observation(self, observation: RuntimeObservation) -> "RuntimeNode":
        return replace(self, observation=observation)


@dataclass(frozen=True, slots=True)
class RuntimeStorage:
    id: str
    display_name: str
    purpose: str
    persistence: str


@dataclass(frozen=True, slots=True)
class CompatibilityLane:
    id: str
    display_name: str
    device: str
    runtime_target: str
    verification_state: str
    verification_note: str


@dataclass(frozen=True, slots=True)
class RuntimeTopology:
    schema_version: int
    topology_version: str
    environment_kind: str
    nodes: tuple[RuntimeNode, ...]
    storages: tuple[RuntimeStorage, ...]
    compatibility_lanes: tuple[CompatibilityLane, ...]

    def node(self, node_id: str) -> RuntimeNode:
        return next(node for node in self.nodes if node.id == node_id)

    def compatibility_lane(self, lane_id: str) -> CompatibilityLane:
        return next(lane for lane in self.compatibility_lanes if lane.id == lane_id)

    def compatibility(self, lane_id: str) -> CompatibilityLane:
        return self.compatibility_lane(lane_id)
