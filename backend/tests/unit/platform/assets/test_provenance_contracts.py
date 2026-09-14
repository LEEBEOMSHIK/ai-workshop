from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from ai_workshop.platform.assets.provenance_contracts import (
    ResourceIdentity,
    SourceIdentity,
    SourceRelation,
)

WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("20000000-0000-0000-0000-000000000001")
OTHER_DOCUMENT_ID = UUID("20000000-0000-0000-0000-000000000002")
ASSET_VERSION_ID = UUID("30000000-0000-0000-0000-000000000001")
OTHER_ASSET_VERSION_ID = UUID("30000000-0000-0000-0000-000000000002")
RESOURCE_ID = UUID("40000000-0000-0000-0000-000000000001")


def test_source_identity_is_frozen_and_uses_all_three_opaque_ids() -> None:
    source = SourceIdentity(WORKSPACE_ID, DOCUMENT_ID, ASSET_VERSION_ID)

    assert source != SourceIdentity(WORKSPACE_ID, OTHER_DOCUMENT_ID, ASSET_VERSION_ID)
    assert source != SourceIdentity(WORKSPACE_ID, DOCUMENT_ID, OTHER_ASSET_VERSION_ID)
    with pytest.raises(FrozenInstanceError):
        source.document_id = OTHER_DOCUMENT_ID  # type: ignore[misc]


def test_independent_documents_with_the_same_bytes_remain_distinct_identities() -> None:
    first = SourceIdentity(WORKSPACE_ID, DOCUMENT_ID, ASSET_VERSION_ID)
    second = SourceIdentity(WORKSPACE_ID, OTHER_DOCUMENT_ID, OTHER_ASSET_VERSION_ID)

    assert first != second


def test_one_resource_can_be_related_to_multiple_sources() -> None:
    resource = ResourceIdentity("rag", "projection", RESOURCE_ID, 3)

    relations = {
        SourceRelation(
            SourceIdentity(WORKSPACE_ID, DOCUMENT_ID, ASSET_VERSION_ID),
            resource,
            "derived_artifact",
        ),
        SourceRelation(
            SourceIdentity(WORKSPACE_ID, OTHER_DOCUMENT_ID, OTHER_ASSET_VERSION_ID),
            resource,
            "derived_artifact",
        ),
    }

    assert len(relations) == 2
    assert {relation.resource for relation in relations} == {resource}


@pytest.mark.parametrize("field", ["workspace_id", "document_id", "asset_version_id"])
def test_source_identity_rejects_non_uuid_fields(field: str) -> None:
    values: dict[str, object] = {
        "workspace_id": WORKSPACE_ID,
        "document_id": DOCUMENT_ID,
        "asset_version_id": ASSET_VERSION_ID,
    }
    values[field] = str(values[field])

    with pytest.raises(TypeError, match=field):
        SourceIdentity(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["participant", "kind"])
@pytest.mark.parametrize("value", ["", "UPPER", "has-dash", "has space", "a" * 81])
def test_resource_identity_rejects_invalid_machine_keys(field: str, value: str) -> None:
    values: dict[str, object] = {
        "participant": "rag",
        "kind": "projection",
        "resource_id": RESOURCE_ID,
        "revision": 1,
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        ResourceIdentity(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("revision", [0, -1, True, 1.5])
def test_resource_identity_rejects_non_positive_integer_revision(revision: object) -> None:
    with pytest.raises((TypeError, ValueError), match="revision"):
        ResourceIdentity("rag", "projection", RESOURCE_ID, revision)  # type: ignore[arg-type]


def test_resource_identity_rejects_non_uuid_resource_id() -> None:
    with pytest.raises(TypeError, match="resource_id"):
        ResourceIdentity("rag", "projection", str(RESOURCE_ID), 1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "relation_kind",
    ["source_copy", "derived_artifact", "authored_reference"],
)
def test_source_relation_accepts_each_defined_relation_kind(relation_kind: str) -> None:
    relation = SourceRelation(
        SourceIdentity(WORKSPACE_ID, DOCUMENT_ID, ASSET_VERSION_ID),
        ResourceIdentity("rag", "projection", RESOURCE_ID, 1),
        relation_kind,
    )

    assert relation.relation_kind == relation_kind


@pytest.mark.parametrize("relation_kind", ["", "shared", "SOURCE_COPY", "source-copy"])
def test_source_relation_rejects_unknown_relation_kind(relation_kind: str) -> None:
    with pytest.raises(ValueError, match="relation_kind"):
        SourceRelation(
            SourceIdentity(WORKSPACE_ID, DOCUMENT_ID, ASSET_VERSION_ID),
            ResourceIdentity("rag", "projection", RESOURCE_ID, 1),
            relation_kind,
        )


def test_source_relation_rejects_untyped_nested_values() -> None:
    source = SourceIdentity(WORKSPACE_ID, DOCUMENT_ID, ASSET_VERSION_ID)
    resource = ResourceIdentity("rag", "projection", RESOURCE_ID, 1)

    with pytest.raises(TypeError, match="source"):
        SourceRelation(resource, resource, "source_copy")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="resource"):
        SourceRelation(source, source, "source_copy")  # type: ignore[arg-type]
