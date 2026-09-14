import re
from dataclasses import dataclass
from uuid import UUID

_MACHINE_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,79}")
_RELATION_KINDS = frozenset({"source_copy", "derived_artifact", "authored_reference"})


def _validate_machine_identifier(value: object, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if _MACHINE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a machine identifier")


def _validate_uuid(value: object, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be a UUID")


def _validate_positive_integer(value: object, field_name: str) -> None:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")


@dataclass(frozen=True)
class SourceIdentity:
    workspace_id: UUID
    document_id: UUID
    asset_version_id: UUID

    def __post_init__(self) -> None:
        _validate_uuid(self.workspace_id, "workspace_id")
        _validate_uuid(self.document_id, "document_id")
        _validate_uuid(self.asset_version_id, "asset_version_id")


@dataclass(frozen=True)
class ResourceIdentity:
    participant: str
    kind: str
    resource_id: UUID
    revision: int

    def __post_init__(self) -> None:
        _validate_machine_identifier(self.participant, "participant")
        _validate_machine_identifier(self.kind, "kind")
        _validate_uuid(self.resource_id, "resource_id")
        _validate_positive_integer(self.revision, "revision")


@dataclass(frozen=True)
class SourceRelation:
    source: SourceIdentity
    resource: ResourceIdentity
    relation_kind: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceIdentity):
            raise TypeError("source must be a SourceIdentity")
        if not isinstance(self.resource, ResourceIdentity):
            raise TypeError("resource must be a ResourceIdentity")
        if type(self.relation_kind) is not str:
            raise TypeError("relation_kind must be a string")
        if self.relation_kind not in _RELATION_KINDS:
            raise ValueError("relation_kind is not supported")
