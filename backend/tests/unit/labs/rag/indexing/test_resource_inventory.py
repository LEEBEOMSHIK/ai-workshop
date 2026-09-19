from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import create_async_engine

from ai_workshop.labs.rag.indexing.resource_inventory import RagIndexInventory, _Snapshot
from ai_workshop.labs.rag.indexing.tracked_elasticsearch import TrackedIndexObservation
from ai_workshop.labs.rag.indexing.tracking_contracts import (
    IndexResource,
    IndexTrackingError,
    index_chunk_ids_fingerprint,
)
from ai_workshop.platform.assets.purge_inventory_contracts import DocumentTarget


def row(**values: object) -> RowMapping:
    return cast(RowMapping, MappingProxyType(values))


def change(original: RowMapping, **values: object) -> RowMapping:
    return row(**(dict(original) | values))


def snapshot(*, prepared: bool = False) -> _Snapshot:
    workspace, document, version, projection, build, job, processing, indexing, chunk = (
        uuid4() for _ in range(9)
    )
    resource = row(
        build_id=build,
        projection_id=projection,
        job_id=job,
        workspace_id=workspace,
        document_id=document,
        asset_version_id=version,
        document_processing_profile_id=processing,
        indexing_profile_id=indexing,
        revision=1,
        store_id="synthetic",
        cluster_uuid="test-cluster",
        index_name="test-index",
        alias="test-active",
        name_contract_version=1,
        mapping_version=1,
        vector_dimension=3,
        similarity="cosine",
        index_uuid="test-uuid" if prepared else None,
        input_fingerprint="a" * 64 if prepared else None,
        chunk_ids_sha256=index_chunk_ids_fingerprint((chunk,)) if prepared else None,
    )
    return _Snapshot(
        documents=(
            row(
                id=document,
                workspace_id=workspace,
                lifecycle_generation=1,
                active_version_id=version,
            ),
        ),
        versions=(row(id=version, document_id=document, status="stored"),),
        projections=(
            row(
                id=projection,
                asset_version_id=version,
                document_processing_profile_id=processing,
                indexing_profile_id=indexing,
                status="indexing",
                content_revision=1,
            ),
        ),
        builds=(
            row(
                id=build,
                projection_id=projection,
                document_processing_profile_id=processing,
                indexing_profile_id=indexing,
                status="prepared" if prepared else "building",
                is_active=False,
                index_name="test-index" if prepared else None,
                expected_document_count=1 if prepared else None,
                indexed_document_count=1 if prepared else None,
                vector_dimension=3 if prepared else None,
            ),
        ),
        ingestions=(
            row(
                job_id=job,
                projection_id=projection,
                asset_version_id=version,
                document_processing_profile_id=processing,
                indexing_profile_id=indexing,
                index_build_id=build,
                chunk_count=1 if prepared else None,
                embedding_count=1 if prepared else None,
                indexed_document_count=1 if prepared else None,
                index_alias_verified=False,
            ),
        ),
        jobs=(
            row(
                id=job,
                workspace_id=workspace,
                asset_version_id=version,
                type="rag_ingestion",
                status="running",
                stage="indexing",
            ),
        ),
        profiles=(
            row(id=processing, kind="document_processing"),
            row(id=indexing, kind="indexing"),
        ),
        resources=(resource,),
        attempts=(
            row(
                id=uuid4(),
                build_id=build,
                operation="prepare",
                state="closed",
                result_code="prepared",
                closed_at=datetime.now(UTC),
            ),
        )
        if prepared
        else (),
        relations=(
            row(
                id=uuid4(),
                participant="rag_index_resources",
                workspace_id=workspace,
                document_id=document,
                asset_version_id=version,
                kind="index_build",
                resource_id=build,
                resource_revision=1,
                relation_kind="derived_artifact",
            ),
        ),
        chunks=(row(id=chunk, projection_id=projection),) if prepared else (),
    )


class Inspector:
    def __init__(self, *, exists: bool = False, aliases: tuple[str, ...] = ()) -> None:
        self.exists = exists
        self.aliases = aliases
        self.observed_ids: tuple[UUID, ...] | None = None

    async def observe(
        self, resource: IndexResource, expected_chunk_ids: Sequence[UUID]
    ) -> TrackedIndexObservation:
        self.observed_ids = tuple(expected_chunk_ids)
        return TrackedIndexObservation(
            self.exists,
            "test-uuid" if self.exists else None,
            len(expected_chunk_ids) if self.exists else 0,
            self.aliases,
        )


class SnapshotInventory(RagIndexInventory):
    def __init__(self, first: _Snapshot, inspector: Inspector, final: _Snapshot | None = None):
        super().__init__(create_async_engine("postgresql+psycopg://unused"), inspector)
        self.snapshots = [first, final or first]

    async def _read_snapshot(
        self, workspace_id: UUID, targets: tuple[DocumentTarget, ...]
    ) -> _Snapshot:
        return self.snapshots.pop(0)


async def collect(state: _Snapshot, inspector: Inspector | None = None):
    return await SnapshotInventory(state, inspector or Inspector()).collect(uuid4(), ())


@pytest.mark.asyncio
async def test_reserved_absent_resource_and_prepared_exact_input_are_complete() -> None:
    reserved = await collect(snapshot())
    assert reserved.exhausted and reserved.legacy_resolved and reserved.supported
    state = snapshot(prepared=True)
    inspector = Inspector(exists=True)
    prepared = await collect(state, inspector)
    assert prepared.exhausted and prepared.legacy_resolved and prepared.supported
    assert inspector.observed_ids == (state.chunks[0]["id"],)
    assert set(asdict(prepared)) == {
        "participant",
        "contract_version",
        "resources",
        "exhausted",
        "supported",
        "legacy_resolved",
    }
    assert "test-index" not in repr(prepared)


@pytest.mark.asyncio
async def test_open_attempt_prevents_exhaustion_even_when_index_is_absent() -> None:
    state = snapshot()
    state = replace(
        state,
        attempts=(
            row(
                id=uuid4(),
                build_id=state.builds[0]["id"],
                operation="prepare",
                state="open",
                result_code=None,
                closed_at=None,
            ),
        ),
    )
    result = await collect(state)
    assert not result.exhausted


@pytest.mark.asyncio
async def test_missing_prepared_index_is_not_successful_absence() -> None:
    result = await collect(snapshot(prepared=True))
    assert not result.exhausted and not result.legacy_resolved


@pytest.mark.asyncio
@pytest.mark.parametrize("aliases", [("test-active",), ("unregistered-alias",)])
async def test_alias_mismatch_or_external_membership_prevents_exhaustion(aliases: tuple[str, ...]):
    result = await collect(snapshot(prepared=True), Inspector(exists=True, aliases=aliases))
    assert not result.exhausted


@pytest.mark.asyncio
async def test_equal_count_replaced_sql_chunk_cannot_change_reserved_input() -> None:
    state = snapshot(prepared=True)
    state = replace(state, chunks=(change(state.chunks[0], id=uuid4()),))
    result = await collect(state, Inspector(exists=True))
    assert not result.exhausted and not result.legacy_resolved


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing", "stale", "foreign", "unknown_kind"])
async def test_relations_are_reconciled_in_both_directions(mutation: str) -> None:
    state = snapshot()
    if mutation == "missing":
        state = replace(state, relations=())
    elif mutation == "stale":
        state = replace(state, relations=(change(state.relations[0], resource_revision=2),))
    elif mutation == "foreign":
        state = replace(state, relations=(change(state.relations[0], document_id=uuid4()),))
    else:
        state = replace(state, relations=(change(state.relations[0], kind="unknown"),))
    result = await collect(state)
    assert not result.legacy_resolved
    if mutation == "unknown_kind":
        assert not result.supported


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    [
        "projections",
        "builds",
        "ingestions",
        "jobs",
        "resources",
        "attempts",
        "relations",
        "chunks",
        "documents",
        "versions",
    ],
)
async def test_any_database_set_change_during_observation_is_rejected(field: str) -> None:
    first = snapshot(prepared=True)
    final = replace(first, **{field: ()})
    with pytest.raises(IndexTrackingError, match="^rag_index_inventory_changed$"):
        await SnapshotInventory(first, Inspector(exists=True), final).collect(uuid4(), ())


@pytest.mark.asyncio
async def test_raw_inspector_error_does_not_escape() -> None:
    class BrokenInspector(Inspector):
        async def observe(self, resource: IndexResource, expected_chunk_ids: Sequence[UUID]):
            raise RuntimeError("secret document https://credential@internal")

    with pytest.raises(IndexTrackingError, match="^rag_index_observation_failed$"):
        await collect(snapshot(), BrokenInspector())


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["building", "prepared", "ready", "failed"])
async def test_all_build_states_are_listed(status: str) -> None:
    state = snapshot(prepared=True)
    state = replace(state, builds=(change(state.builds[0], status=status),))
    result = await collect(state, Inspector(exists=True))
    assert result.resources[0].resource_id == state.builds[0]["id"]


@pytest.mark.asyncio
async def test_projection_profile_mismatch_is_unresolved() -> None:
    state = snapshot()
    state = replace(state, projections=(change(state.projections[0], indexing_profile_id=uuid4()),))
    assert not (await collect(state)).legacy_resolved


@pytest.mark.asyncio
async def test_unregistered_build_and_orphan_ledger_are_unresolved() -> None:
    state = snapshot()
    assert not (await collect(replace(state, resources=()))).legacy_resolved
    assert not (await collect(replace(state, builds=()))).legacy_resolved


@pytest.mark.asyncio
async def test_reserved_build_name_conflict_is_unresolved_before_prepare() -> None:
    state = snapshot()
    state = replace(state, builds=(change(state.builds[0], index_name="foreign-index"),))
    assert not (await collect(state)).legacy_resolved


@pytest.mark.asyncio
async def test_orphan_open_attempt_is_not_exhausted() -> None:
    state = snapshot()
    state = replace(
        state,
        resources=(),
        attempts=(
            row(
                id=uuid4(),
                build_id=state.builds[0]["id"],
                operation="prepare",
                state="open",
                result_code=None,
                closed_at=None,
            ),
        ),
    )
    result = await collect(state)
    assert not result.exhausted and not result.legacy_resolved


@pytest.mark.asyncio
async def test_no_build_still_requires_valid_profile_kind() -> None:
    state = snapshot()
    state = replace(
        state,
        builds=(),
        resources=(),
        relations=(),
        ingestions=(change(state.ingestions[0], index_build_id=None),),
        profiles=tuple(change(p, kind="generation") for p in state.profiles),
    )
    assert not (await collect(state)).legacy_resolved


@pytest.mark.asyncio
async def test_failed_existing_index_without_prepare_attempt_is_unresolved() -> None:
    state = snapshot(prepared=True)
    state = replace(state, attempts=(), builds=(change(state.builds[0], status="failed"),))
    result = await collect(state, Inspector(exists=True))
    assert not result.exhausted and not result.legacy_resolved


@pytest.mark.asyncio
async def test_succeeded_ingestion_without_build_is_not_normal_pre_index_state() -> None:
    state = snapshot()
    state = replace(
        state,
        builds=(),
        resources=(),
        relations=(),
        ingestions=(change(state.ingestions[0], index_build_id=None),),
        jobs=(change(state.jobs[0], status="succeeded"),),
    )
    assert not (await collect(state)).legacy_resolved


@pytest.mark.asyncio
@pytest.mark.parametrize("readiness_verified", [False, True])
async def test_ingestion_indexed_count_is_optional_until_readiness_verification(
    readiness_verified: bool,
) -> None:
    state = snapshot(prepared=True)
    state = replace(
        state,
        ingestions=(
            change(
                state.ingestions[0],
                indexed_document_count=None,
                index_alias_verified=readiness_verified,
            ),
        ),
    )
    result = await collect(state, Inspector(exists=True))
    assert result.exhausted is (not readiness_verified)
    assert result.legacy_resolved is (not readiness_verified)
