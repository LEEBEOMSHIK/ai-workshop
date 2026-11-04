"""Frozen input contracts. These artifacts are not live authorization credentials."""

import hashlib
import json
import math
import struct
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Engine = Literal["elasticsearch", "pgvector", "qdrant"]
Phase = Literal["first_observed", "warmup", "repeated"]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class EmbeddingProfile(FrozenModel):
    model_id: Text
    model_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    dimension: Annotated[int, Field(strict=True, gt=0, le=4096)]
    normalized: Literal[True] = True
    dtype: Literal["float32"] = "float32"
    metric: Literal["cosine"] = "cosine"


class Identity(FrozenModel):
    chunk_id: UUID
    workspace_id: UUID
    document_id: UUID
    asset_version_id: UUID
    projection_id: UUID
    index_build_id: UUID


def float32_vector(value: object) -> tuple[float, ...]:
    if not isinstance(value, (tuple, list)) or not value:
        raise ValueError("vector must be a nonempty numeric array")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError("vector must contain numeric values")
        try:
            rounded = float(struct.unpack("!f", struct.pack("!f", item))[0])
        except (OverflowError, struct.error) as exc:
            raise ValueError("vector must fit finite float32") from exc
        if not math.isfinite(rounded):
            raise ValueError("vector must contain finite float32 values")
        result.append(rounded)
    return tuple(result)


class Chunk(Identity):
    vector: tuple[float, ...]

    _float32 = field_validator("vector", mode="before")(float32_vector)


class QueryCase(FrozenModel):
    case_id: UUID
    vector: tuple[float, ...]
    allowed_chunk_ids: tuple[UUID, ...]
    relevant_chunk_ids: tuple[UUID, ...] | None = None
    forbidden_chunk_ids: tuple[UUID, ...] = ()
    bm25_chunk_ids: tuple[UUID, ...] = ()

    _float32 = field_validator("vector", mode="before")(float32_vector)

    @model_validator(mode="after")
    def validate_sets(self) -> Self:
        for values in (
            self.allowed_chunk_ids,
            self.relevant_chunk_ids or (),
            self.forbidden_chunk_ids,
            self.bm25_chunk_ids,
        ):
            if len(set(values)) != len(values):
                raise ValueError("case IDs must not contain duplicates")
        allowed = set(self.allowed_chunk_ids)
        if not set(self.relevant_chunk_ids or ()) <= allowed:
            raise ValueError("relevant IDs must be allowed")
        if not set(self.bm25_chunk_ids) <= allowed:
            raise ValueError("BM25 IDs must be allowed")
        if allowed.intersection(self.forbidden_chunk_ids):
            raise ValueError("forbidden IDs must not be allowed")
        return self


class Snapshot(FrozenModel):
    schema_version: Literal[1] = 1
    classification: Literal["public_synthetic"] = "public_synthetic"
    snapshot_id: UUID
    captured_at: datetime
    permission_revision: Digest
    profile: EmbeddingProfile
    chunks: Annotated[tuple[Chunk, ...], Field(min_length=1)]
    cases: Annotated[tuple[QueryCase, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        chunk_ids = {chunk.chunk_id for chunk in self.chunks}
        if len(chunk_ids) != len(self.chunks):
            raise ValueError("chunk IDs must be unique")
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("case IDs must be unique")
        # A build cannot describe multiple source generations or workspaces.
        builds: dict[UUID, tuple[UUID, UUID, UUID, UUID]] = {}
        documents: dict[UUID, UUID] = {}
        assets: dict[UUID, UUID] = {}
        projections: dict[UUID, UUID] = {}
        for chunk in self.chunks:
            if documents.setdefault(chunk.document_id, chunk.workspace_id) != chunk.workspace_id:
                raise ValueError("document has conflicting workspace provenance")
            if assets.setdefault(chunk.asset_version_id, chunk.document_id) != chunk.document_id:
                raise ValueError("asset version has conflicting document provenance")
            if projections.setdefault(chunk.projection_id, chunk.asset_version_id) != (
                chunk.asset_version_id
            ):
                raise ValueError("projection has conflicting asset provenance")
            source = (
                chunk.workspace_id,
                chunk.document_id,
                chunk.asset_version_id,
                chunk.projection_id,
            )
            if builds.setdefault(chunk.index_build_id, source) != source:
                raise ValueError("index build has conflicting provenance")
        vectors = tuple(chunk.vector for chunk in self.chunks) + tuple(
            case.vector for case in self.cases
        )
        for vector in vectors:
            if len(vector) != self.profile.dimension:
                raise ValueError("vector dimension differs from profile")
            norm = math.sqrt(math.fsum(value * value for value in vector))
            if not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
                raise ValueError("vectors must be L2 normalized")
        for case in self.cases:
            if not set((*case.allowed_chunk_ids, *case.forbidden_chunk_ids)) <= chunk_ids:
                raise ValueError("case refers to unknown chunk IDs")
        return self


class Settings(FrozenModel):
    k: PositiveInt = 10
    candidate_k: PositiveInt = 30
    rrf_k: NonnegativeInt = 60
    repeats: Annotated[int, Field(strict=True, ge=2, le=1000)] = 20
    warmups: Annotated[int, Field(strict=True, ge=0, le=100)] = 1
    seed: NonnegativeInt = 0
    concurrency: Literal[1] = 1

    @model_validator(mode="after")
    def validate_k(self) -> Self:
        if self.k > self.candidate_k:
            raise ValueError("candidate_k must be at least k")
        return self


class Target(FrozenModel):
    engine: Engine
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")]
    version: Text
    platform: Text
    index_configuration: Text
    readiness: Literal["planned", "observed"] = "planned"


class Attempt(FrozenModel):
    attempt_id: Text
    engine: Engine
    case_id: UUID
    phase: Phase
    repeat: NonnegativeInt


class Plan(FrozenModel):
    schema_version: Literal[1] = 1
    snapshot_digest: Digest
    settings: Settings
    targets: tuple[Target, ...]
    attempts: tuple[Attempt, ...]

    @model_validator(mode="after")
    def validate_targets(self) -> Self:
        if len(self.targets) != 3 or {target.engine for target in self.targets} != {
            "elasticsearch",
            "pgvector",
            "qdrant",
        }:
            raise ValueError("exactly one target per engine is required")
        if len({attempt.attempt_id for attempt in self.attempts}) != len(self.attempts):
            raise ValueError("attempt IDs must be unique")
        return self


class Hit(Identity):
    score: Annotated[float, Field(strict=True)]


class ResourceObservation(FrozenModel):
    method: Text
    scope: Text
    cpu_process_ms: Annotated[float, Field(strict=True, ge=0)] | None = None
    rss_peak_bytes: NonnegativeInt | None = None
    container_memory_peak_bytes: NonnegativeInt | None = None
    storage_bytes: NonnegativeInt | None = None


class Observation(FrozenModel):
    attempt_id: Text
    status: Literal["ok", "error", "timeout", "unavailable"]
    elapsed_ms: Annotated[float, Field(strict=True, ge=0)] | None = None
    hits: tuple[Hit, ...] = ()
    resources: ResourceObservation | None = None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status == "ok" and self.elapsed_ms is None:
            raise ValueError("successful observations require elapsed_ms")
        if self.status != "ok" and self.hits:
            raise ValueError("failed observations cannot contain scored hits")
        return self


class Observations(FrozenModel):
    schema_version: Literal[1] = 1
    plan_digest: Digest
    evidence_kind: Literal["synthetic", "imported_unverified"]
    records: tuple[Observation, ...]


def digest(value: BaseModel) -> str:
    encoded = json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
