"""Read-only, body-free inventory of registered index resources."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Select, or_, select, tuple_
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ai_workshop.labs.rag.documents.models import (
    RagIndexBuildRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
)
from ai_workshop.labs.rag.indexing.alias_models import AliasOperationRecord
from ai_workshop.labs.rag.indexing.fence_models import RagIndexWriteFenceRecord
from ai_workshop.labs.rag.indexing.resource_models import (
    RagIndexAttemptRecord,
    RagIndexResourceRecord,
)
from ai_workshop.labs.rag.indexing.tracked_elasticsearch import TrackedIndexObservation
from ai_workshop.labs.rag.indexing.tracking_contracts import (
    INDEX_RESULT_CODES,
    IndexBinding,
    IndexResource,
    IndexTrackingError,
    index_chunk_ids_fingerprint,
)
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.purge_inventory_contracts import (
    DocumentTarget,
    ParticipantInventory,
)
from ai_workshop.platform.jobs.domain import JobType
from ai_workshop.platform.jobs.models import JobRecord

RAG_INDEX_INVENTORY_CONTRACT_VERSION = 1
_PARTICIPANT = "rag_index_resources"
_KIND = "index_build"


class IndexInspector(Protocol):
    async def observe(
        self, resource: IndexResource, expected_chunk_ids: Sequence[UUID]
    ) -> TrackedIndexObservation: ...


@dataclass(frozen=True, slots=True)
class _Snapshot:
    documents: tuple[RowMapping, ...]
    versions: tuple[RowMapping, ...]
    projections: tuple[RowMapping, ...]
    builds: tuple[RowMapping, ...]
    ingestions: tuple[RowMapping, ...]
    jobs: tuple[RowMapping, ...]
    profiles: tuple[RowMapping, ...]
    resources: tuple[RowMapping, ...]
    attempts: tuple[RowMapping, ...]
    relations: tuple[RowMapping, ...]
    chunks: tuple[RowMapping, ...]
    alias_operations: tuple[RowMapping, ...] = ()
    fences: tuple[RowMapping, ...] = ()


class RagIndexInventory:
    def __init__(self, engine: AsyncEngine, inspector: IndexInspector) -> None:
        if not isinstance(engine, AsyncEngine):
            raise TypeError("engine must be an AsyncEngine")
        self._engine = engine
        self._inspector = inspector

    async def collect(
        self, workspace_id: UUID, documents: tuple[DocumentTarget, ...]
    ) -> ParticipantInventory:
        if not isinstance(workspace_id, UUID):
            raise TypeError("workspace_id must be a UUID")
        if type(documents) is not tuple or any(
            not isinstance(document, DocumentTarget) for document in documents
        ):
            raise TypeError("documents must be a tuple of DocumentTarget values")
        if len({d.document_id for d in documents}) != len(documents):
            raise IndexTrackingError("rag_index_inventory_incomplete")
        first = await self._read_snapshot(workspace_id, documents)
        result = await self._inspect(first)
        try:
            final = await self._read_snapshot(workspace_id, documents)
        except IndexTrackingError as error:
            if error.code == "rag_index_inventory_incomplete":
                raise IndexTrackingError("rag_index_inventory_changed") from None
            raise
        if first != final:
            raise IndexTrackingError("rag_index_inventory_changed")
        return result

    async def _read_snapshot(
        self, workspace_id: UUID, targets: tuple[DocumentTarget, ...]
    ) -> _Snapshot:
        try:
            async with self._engine.connect() as connection, connection.begin():
                await connection.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                return await self._snapshot(connection, workspace_id, targets)
        except IndexTrackingError:
            raise
        except Exception:
            raise IndexTrackingError("rag_index_observation_failed") from None

    async def _snapshot(
        self,
        connection: AsyncConnection,
        workspace_id: UUID,
        targets: tuple[DocumentTarget, ...],
    ) -> _Snapshot:
        async def rows(statement: Select[Any]) -> tuple[RowMapping, ...]:
            return tuple((await connection.execute(statement)).mappings())

        document_ids = tuple(d.document_id for d in targets)
        documents = await rows(
            select(
                DocumentRecord.id,
                DocumentRecord.workspace_id,
                DocumentRecord.lifecycle_generation,
                DocumentRecord.active_version_id,
                DocumentRecord.lifecycle,
            )
            .where(DocumentRecord.id.in_(document_ids))
            .order_by(DocumentRecord.id)
        )
        by_id = {r["id"]: r for r in documents}
        if len(documents) != len(targets) or any(
            by_id[t.document_id]["workspace_id"] != workspace_id
            or by_id[t.document_id]["lifecycle_generation"] != t.generation
            for t in targets
        ):
            raise IndexTrackingError("rag_index_inventory_incomplete")
        versions = await rows(
            select(
                AssetVersionRecord.id,
                AssetVersionRecord.document_id,
                AssetVersionRecord.status,
            )
            .where(AssetVersionRecord.document_id.in_(document_ids))
            .order_by(AssetVersionRecord.id)
        )
        if any(
            {r["id"] for r in versions if r["document_id"] == t.document_id}
            != set(t.asset_version_ids)
            for t in targets
        ):
            raise IndexTrackingError("rag_index_inventory_incomplete")
        version_ids = tuple(r["id"] for r in versions)
        p = RagProjectionRecord.__table__
        projections = await rows(
            select(p).where(p.c.asset_version_id.in_(version_ids)).order_by(p.c.id)
        )
        projection_ids = tuple(r["id"] for r in projections)
        i = RagIngestionJobRecord.__table__
        ingestions = await rows(
            select(i)
            .where(
                or_(
                    i.c.asset_version_id.in_(version_ids),
                    i.c.projection_id.in_(projection_ids),
                )
            )
            .order_by(i.c.job_id)
        )
        ingestion_ids = tuple(r["job_id"] for r in ingestions)
        b = RagIndexBuildRecord.__table__
        builds = await rows(
            select(b)
            .where(
                or_(
                    b.c.projection_id.in_(projection_ids),
                    b.c.id.in_(tuple(r["index_build_id"] for r in ingestions)),
                )
            )
            .order_by(b.c.id)
        )
        build_ids = tuple(r["id"] for r in builds)
        j = JobRecord.__table__
        jobs = await rows(
            select(
                *(
                    j.c[k]
                    for k in (
                        "id",
                        "user_id",
                        "workspace_id",
                        "asset_version_id",
                        "type",
                        "status",
                        "stage",
                        "attempt",
                        "error_code",
                        "started_at",
                        "finished_at",
                        "updated_at",
                    )
                )
            )
            .where(
                or_(
                    j.c.id.in_(ingestion_ids),
                    j.c.asset_version_id.in_(version_ids) & (j.c.type == JobType.RAG_INGESTION),
                )
            )
            .order_by(j.c.id)
        )
        rel = AssetSourceRelationRecord.__table__
        source_scope = or_(
            rel.c.document_id.in_(document_ids), rel.c.asset_version_id.in_(version_ids)
        )
        source_relations = await rows(
            select(rel)
            .where(
                rel.c.participant == _PARTICIPANT,
                source_scope,
            )
            .order_by(rel.c.id)
        )
        r = RagIndexResourceRecord.__table__
        resources = await rows(
            select(r)
            .where(
                or_(
                    r.c.document_id.in_(document_ids),
                    r.c.asset_version_id.in_(version_ids),
                    r.c.projection_id.in_(projection_ids),
                    r.c.build_id.in_(build_ids),
                    r.c.job_id.in_(tuple(row["id"] for row in jobs)),
                    r.c.build_id.in_(tuple(row["resource_id"] for row in source_relations)),
                )
            )
            .order_by(r.c.build_id)
        )
        resource_ids = tuple(row["build_id"] for row in resources)
        relations = await rows(
            select(rel)
            .where(
                rel.c.participant == _PARTICIPANT,
                or_(source_scope, rel.c.resource_id.in_(build_ids + resource_ids)),
            )
            .order_by(rel.c.id)
        )
        a = RagIndexAttemptRecord.__table__
        attempts = await rows(
            select(a).where(a.c.build_id.in_(resource_ids + build_ids)).order_by(a.c.id)
        )
        profile_ids = tuple(
            {
                row[key]
                for row in (*projections, *builds, *ingestions, *resources)
                for key in ("document_processing_profile_id", "indexing_profile_id")
            }
        )
        profiles = await rows(
            select(
                ProfileRecord.id,
                ProfileRecord.kind,
                ProfileRecord.version,
                ProfileRecord.updated_at,
            )
            .where(ProfileRecord.id.in_(profile_ids))
            .order_by(ProfileRecord.id)
        )
        chunks = await rows(
            select(RetrievalChunkRecord.id, RetrievalChunkRecord.projection_id)
            .where(RetrievalChunkRecord.projection_id.in_(projection_ids))
            .order_by(RetrievalChunkRecord.id)
        )
        scopes = tuple({(r["indexing_profile_id"], r["document_processing_profile_id"])
                        for r in (*projections, *builds, *resources)})
        alias_operations = await rows(select(AliasOperationRecord.__table__).where(
            tuple_(AliasOperationRecord.indexing_profile_id,
                   AliasOperationRecord.document_processing_profile_id).in_(scopes),
        ).order_by(AliasOperationRecord.id))
        fences = await rows(select(RagIndexWriteFenceRecord.__table__).where(
            RagIndexWriteFenceRecord.document_id.in_(document_ids),
        ).order_by(RagIndexWriteFenceRecord.document_id))
        return _Snapshot(
            documents,
            versions,
            projections,
            builds,
            ingestions,
            jobs,
            profiles,
            resources,
            attempts,
            relations,
            chunks,
            alias_operations,
            fences,
        )

    async def _inspect(self, snapshot: _Snapshot) -> ParticipantInventory:
        builds = {r["id"]: r for r in snapshot.builds}
        projections = {r["id"]: r for r in snapshot.projections}
        ingestions = {r["job_id"]: r for r in snapshot.ingestions}
        jobs = {r["id"]: r for r in snapshot.jobs}
        profiles = {r["id"]: r["kind"] for r in snapshot.profiles}
        versions = {r["id"]: r for r in snapshot.versions}
        documents = {r["id"]: r for r in snapshot.documents}
        resources: set[ResourceIdentity] = set()
        expected_relations: set[tuple[object, ...]] = set()
        exhausted = supported = legacy_resolved = True
        tracked = {r["build_id"] for r in snapshot.resources}
        if set(builds) != tracked:
            legacy_resolved = False
        if set(jobs) != set(ingestions):
            legacy_resolved = False
        if any(a["state"] == "open" for a in snapshot.attempts):
            exhausted = False
        if any(a["state"] == "open" for a in snapshot.alias_operations):
            exhausted = False
        if any(a["build_id"] not in tracked for a in snapshot.attempts):
            legacy_resolved = exhausted = False
        ingestion: RowMapping | None
        for ingestion in snapshot.ingestions:
            projection = projections.get(ingestion["projection_id"])
            job = jobs.get(ingestion["job_id"])
            version = versions.get(ingestion["asset_version_id"])
            document = documents.get(version["document_id"]) if version else None
            if (
                projection is None
                or job is None
                or document is None
                or job["type"] != JobType.RAG_INGESTION
                or job["workspace_id"] != document["workspace_id"]
                or job["asset_version_id"] != ingestion["asset_version_id"]
                or any(
                    projection[k] != ingestion[k]
                    for k in (
                        "asset_version_id",
                        "document_processing_profile_id",
                        "indexing_profile_id",
                    )
                )
            ):
                legacy_resolved = False
            if ingestion["index_build_id"] is not None:
                build = builds.get(ingestion["index_build_id"])
                if build is None or build["projection_id"] != ingestion["projection_id"]:
                    legacy_resolved = False
            elif (
                ingestion["indexed_document_count"] is not None
                or ingestion["index_alias_verified"]
                or (job is not None and job["status"] == "succeeded")
            ):
                legacy_resolved = False
        for projection in snapshot.projections:
            if (
                profiles.get(projection["document_processing_profile_id"]) != "document_processing"
                or profiles.get(projection["indexing_profile_id"]) != "indexing"
            ):
                legacy_resolved = False
            owned = [i for i in snapshot.ingestions if i["projection_id"] == projection["id"]]
            if len(owned) != 1:
                legacy_resolved = False
            if projection["status"] in {"ready", "partial_ready"} and not any(
                b["projection_id"] == projection["id"] for b in snapshot.builds
            ):
                legacy_resolved = False
        for row in snapshot.resources:
            resources.add(ResourceIdentity(_PARTICIPANT, _KIND, row["build_id"], row["revision"]))
            expected_relations.add(
                (
                    row["workspace_id"],
                    row["document_id"],
                    row["asset_version_id"],
                    _KIND,
                    row["build_id"],
                    row["revision"],
                    "derived_artifact",
                )
            )
            build = builds.get(row["build_id"])
            ingestion = ingestions.get(row["job_id"])
            projection = projections.get(row["projection_id"])
            version = versions.get(row["asset_version_id"])
            document = documents.get(row["document_id"])
            if (
                build is None
                or ingestion is None
                or projection is None
                or version is None
                or document is None
                or version["document_id"] != row["document_id"]
                or document["workspace_id"] != row["workspace_id"]
                or ingestion["index_build_id"] != row["build_id"]
                or any(
                    build[k] != row[k]
                    for k in (
                        "projection_id",
                        "document_processing_profile_id",
                        "indexing_profile_id",
                    )
                )
                or any(
                    ingestion[k] != row[k]
                    for k in (
                        "projection_id",
                        "asset_version_id",
                        "document_processing_profile_id",
                        "indexing_profile_id",
                    )
                )
                or profiles.get(row["document_processing_profile_id"]) != "document_processing"
                or profiles.get(row["indexing_profile_id"]) != "indexing"
            ):
                legacy_resolved = False
                continue
            if row["name_contract_version"] != 1:
                supported = exhausted = False
                continue
            resource = _resource(row)
            if build["index_name"] not in {None, resource.index_name} or (
                build["vector_dimension"] not in {None, resource.vector_dimension}
            ):
                legacy_resolved = exhausted = False
            attempts = [a for a in snapshot.attempts if a["build_id"] == resource.build_id]
            if bool(attempts) != (resource.input_fingerprint is not None):
                legacy_resolved = exhausted = False
            for attempt in attempts:
                if attempt["operation"] != "prepare" or attempt["state"] not in {"open", "closed"}:
                    supported = exhausted = False
                elif attempt["state"] == "open":
                    exhausted = False
                    if attempt["result_code"] is not None or attempt["closed_at"] is not None:
                        legacy_resolved = False
                elif (
                    attempt["result_code"] not in INDEX_RESULT_CODES or attempt["closed_at"] is None
                ):
                    legacy_resolved = exhausted = False
            expected_ids = tuple(
                c["id"] for c in snapshot.chunks if c["projection_id"] == resource.projection_id
            )
            prepared = build["status"] in {"prepared", "ready"} or build["is_active"]
            if prepared and (
                resource.input_fingerprint is None
                or row["chunk_ids_sha256"] != index_chunk_ids_fingerprint(expected_ids)
                or build["index_name"] != resource.index_name
                or build["vector_dimension"] != resource.vector_dimension
                or any(
                    value != len(expected_ids)
                    for value in (
                        build["expected_document_count"],
                        build["indexed_document_count"],
                        ingestion["chunk_count"],
                        ingestion["embedding_count"],
                    )
                )
                or ingestion["indexed_document_count"] not in {None, len(expected_ids)}
                or (
                    (build["status"] == "ready" or ingestion["index_alias_verified"])
                    and ingestion["indexed_document_count"] != len(expected_ids)
                )
                or not any(
                    a["state"] == "closed" and a["result_code"] == "prepared" for a in attempts
                )
            ):
                exhausted = legacy_resolved = False
            try:
                observation = await self._inspector.observe(resource, expected_ids)
            except IndexTrackingError:
                raise
            except Exception:
                raise IndexTrackingError("rag_index_observation_failed") from None
            if not observation.exists:
                if prepared or resource.index_uuid is not None:
                    exhausted = legacy_resolved = False
            else:
                if (
                    resource.index_uuid is None
                    or observation.index_uuid != resource.index_uuid
                    or resource.input_fingerprint is None
                    or row["chunk_ids_sha256"] != index_chunk_ids_fingerprint(expected_ids)
                ):
                    exhausted = legacy_resolved = False
                if set(observation.aliases) - {resource.alias}:
                    exhausted = False
                if (resource.alias in observation.aliases) != build["is_active"]:
                    exhausted = False
            if build["is_active"] and (
                projection["status"] != "ready"
                or document["active_version_id"] != resource.asset_version_id
                or not ingestion["index_alias_verified"]
            ):
                exhausted = False
        actual_relations: set[tuple[object, ...]] = set()
        for relation in snapshot.relations:
            resources.add(
                ResourceIdentity(
                    _PARTICIPANT,
                    relation["kind"],
                    relation["resource_id"],
                    relation["resource_revision"],
                )
            )
            if relation["kind"] != _KIND:
                supported = False
            actual_relations.add(
                tuple(
                    relation[k]
                    for k in (
                        "workspace_id",
                        "document_id",
                        "asset_version_id",
                        "kind",
                        "resource_id",
                        "resource_revision",
                        "relation_kind",
                    )
                )
            )
        if actual_relations != expected_relations:
            legacy_resolved = False
        return ParticipantInventory(
            _PARTICIPANT,
            RAG_INDEX_INVENTORY_CONTRACT_VERSION,
            tuple(sorted(resources, key=lambda r: (r.kind, str(r.resource_id), r.revision))),
            exhausted,
            supported,
            legacy_resolved,
        )


def _resource(row: RowMapping) -> IndexResource:
    return IndexResource(
        build_id=row["build_id"],
        projection_id=row["projection_id"],
        job_id=row["job_id"],
        workspace_id=row["workspace_id"],
        document_id=row["document_id"],
        asset_version_id=row["asset_version_id"],
        document_processing_profile_id=row["document_processing_profile_id"],
        indexing_profile_id=row["indexing_profile_id"],
        revision=row["revision"],
        binding=IndexBinding(row["store_id"], row["cluster_uuid"]),
        index_name=row["index_name"],
        alias=row["alias"],
        mapping_version=row["mapping_version"],
        vector_dimension=row["vector_dimension"],
        similarity=row["similarity"],
        index_uuid=row["index_uuid"],
        input_fingerprint=row["input_fingerprint"],
        chunk_ids_sha256=row["chunk_ids_sha256"],
    )
