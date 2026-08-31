import re
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from elastic_transport import ApiError, ConnectionTimeout
from elastic_transport import ConnectionError as ElasticsearchConnectionError
from sqlalchemy import select, update
from sqlalchemy.exc import (
    DisconnectionError,
    OperationalError,
)
from sqlalchemy.exc import (
    TimeoutError as SqlAlchemyTimeoutError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.labs.rag.documents.models import (
    RagIndexBuildRecord,
    RagProjectionRecord,
)
from ai_workshop.labs.rag.indexing.contracts import (
    IndexDescriptor,
    canonical_recovery_targets,
)
from ai_workshop.labs.rag.indexing.elasticsearch import ElasticsearchSearchIndex
from ai_workshop.labs.rag.ingestion.domain import RagIngestionError
from ai_workshop.labs.rag.ingestion.locking import lock_ingestion_source
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.shared.db import create_engine, create_session_factory

_SAFE_CAUSE_CLASS = re.compile(r"[^A-Za-z0-9_.]")
_MAX_REPORTED_FAILURES = 20


class AliasParitySearchIndexPort(Protocol):
    async def reconcile_active_targets(
        self, alias: str, index_names: Sequence[str]
    ) -> bool:
        raise NotImplementedError

    async def active_targets(self, alias: str) -> tuple[str, ...]:
        raise NotImplementedError


type AliasParitySearchIndexSession = Callable[
    [], AbstractAsyncContextManager[AliasParitySearchIndexPort]
]


@dataclass(frozen=True, slots=True)
class RagAliasParityFailure:
    profile_id: UUID
    error_code: str
    retryable: bool
    cause_class: str


@dataclass(frozen=True, slots=True)
class RagAliasParityResult:
    claimed: int
    reconciled: int
    failed: int
    failures: tuple[RagAliasParityFailure, ...] = ()


class RagAliasParityError(RuntimeError):
    def __init__(self, error_code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


class RagAliasParityRunError(RuntimeError):
    def __init__(self, result: RagAliasParityResult) -> None:
        super().__init__("Periodic RAG alias parity reconciliation had failures.")
        self.result = result


@dataclass(frozen=True, slots=True)
class _AuthoritativeTarget:
    asset_version_id: UUID
    document_id: UUID
    projection_id: UUID
    build_id: UUID
    index_name: str | None
    vector_dimension: int | None


@asynccontextmanager
async def _elasticsearch_session(
    settings: Settings,
) -> AsyncIterator[ElasticsearchSearchIndex]:
    client = create_elasticsearch(settings)
    try:
        yield ElasticsearchSearchIndex(client)
    finally:
        await client.close()


def _safe_cause_class(exc: BaseException) -> str:
    value = _SAFE_CAUSE_CLASS.sub("_", type(exc).__name__)[:100]
    return value or "Exception"


def _classify_failure(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, RagAliasParityError):
        return exc.error_code, exc.retryable
    if isinstance(
        exc,
        (OperationalError, DisconnectionError, SqlAlchemyTimeoutError),
    ):
        return "alias_parity_database_transient", True
    if isinstance(exc, (ElasticsearchConnectionError, ConnectionTimeout)):
        return "alias_parity_search_transient", True
    if isinstance(exc, ApiError):
        retryable = exc.meta.status == 429 or exc.meta.status >= 500
        return (
            "alias_parity_search_transient"
            if retryable
            else "alias_parity_search_rejected",
            retryable,
        )
    return "internal_error", False


class SqlAlchemyRagAliasParityReconciler:
    """Converge each profile alias from PostgreSQL truth in source -> profile order."""

    def __init__(
        self,
        settings: Settings,
        *,
        search_index_session: AliasParitySearchIndexSession | None = None,
        batch_size: int = 100,
    ) -> None:
        if batch_size < 1:
            raise ValueError("The alias parity batch size must be positive.")
        self.settings = settings
        self.search_index_session = search_index_session or (
            lambda: _elasticsearch_session(settings)
        )
        self.batch_size = batch_size

    async def run_once(
        self, *, profile_id: UUID | None = None
    ) -> RagAliasParityResult:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions() as session:
                statement = (
                    select(ProfileRecord.id)
                    .where(ProfileRecord.kind == "indexing")
                    .order_by(ProfileRecord.id)
                    .limit(self.batch_size)
                )
                if profile_id is not None:
                    statement = statement.where(ProfileRecord.id == profile_id)
                profile_ids = tuple(await session.scalars(statement))

            reconciled = 0
            failures: list[RagAliasParityFailure] = []
            for candidate_id in profile_ids:
                try:
                    async with sessions.begin() as session:
                        await self._reconcile_profile(session, candidate_id)
                    reconciled += 1
                except Exception as exc:
                    error_code, retryable = _classify_failure(exc)
                    if len(failures) < _MAX_REPORTED_FAILURES:
                        failures.append(
                            RagAliasParityFailure(
                                profile_id=candidate_id,
                                error_code=error_code,
                                retryable=retryable,
                                cause_class=_safe_cause_class(exc),
                            )
                        )
            return RagAliasParityResult(
                claimed=len(profile_ids),
                reconciled=reconciled,
                failed=len(profile_ids) - reconciled,
                failures=tuple(failures),
            )
        finally:
            await engine.dispose()

    async def _reconcile_profile(
        self,
        session: AsyncSession,
        profile_id: UUID,
    ) -> None:
        initial = await _authoritative_targets(session, profile_id)
        for asset_version_id in sorted(
            (target.asset_version_id for target in initial), key=str
        ):
            try:
                await lock_ingestion_source(session, asset_version_id)
            except RagIngestionError as exc:
                raise RagAliasParityError(
                    "alias_parity_membership_changed",
                    "The authoritative active source set changed before it could be locked.",
                    retryable=True,
                ) from exc

        profile = await session.scalar(
            select(ProfileRecord)
            .where(ProfileRecord.id == profile_id, ProfileRecord.kind == "indexing")
            .with_for_update()
        )
        if profile is None:
            raise RagAliasParityError(
                "alias_parity_profile_missing",
                "The indexing profile disappeared during alias reconciliation.",
                retryable=True,
            )

        current = await _authoritative_targets(session, profile_id)
        if current != initial:
            raise RagAliasParityError(
                "alias_parity_membership_changed",
                "The authoritative active source set changed while locks were acquired.",
                retryable=True,
            )

        builds = tuple(
            await session.scalars(
                select(RagIndexBuildRecord)
                .where(RagIndexBuildRecord.indexing_profile_id == profile_id)
                .order_by(RagIndexBuildRecord.id)
                .with_for_update()
            )
        )
        build_by_id = {build.id: build for build in builds}
        dimensions = {
            target.vector_dimension
            for target in current
            if target.vector_dimension is not None
        }
        if len(dimensions) != len({target.vector_dimension for target in current}):
            raise RagAliasParityError(
                "alias_parity_invalid_build",
                "The authoritative build set has incompatible vector dimensions.",
                retryable=False,
            )
        if len(dimensions) > 1 or any(dimension < 1 for dimension in dimensions):
            raise RagAliasParityError(
                "alias_parity_invalid_build",
                "The authoritative build set has incompatible vector dimensions.",
                retryable=False,
            )
        dimension = next(iter(dimensions), 1)
        descriptor = IndexDescriptor(dimension, "cosine")
        alias = descriptor.active_alias(
            self.settings.elasticsearch_index_prefix,
            profile_id,
        )
        intended_names: list[str] = []
        for target in current:
            build = build_by_id.get(target.build_id)
            expected_name = descriptor.concrete_index_name(
                self.settings.elasticsearch_index_prefix,
                profile_id,
                target.build_id,
            )
            if (
                build is None
                or build.status != "ready"
                or build.projection_id != target.projection_id
                or build.index_name != expected_name
                or target.index_name != expected_name
                or build.vector_dimension != dimension
            ):
                raise RagAliasParityError(
                    "alias_parity_invalid_build",
                    "An authoritative build does not match its immutable descriptor.",
                    retryable=False,
                )
            intended_names.append(expected_name)
        try:
            intended_targets = canonical_recovery_targets(alias, intended_names)
        except ValueError as exc:
            raise RagAliasParityError(
                "alias_parity_invalid_build",
                "The authoritative alias target set is not canonical.",
                retryable=False,
            ) from exc

        async with self.search_index_session() as search_index:
            acknowledged = await search_index.reconcile_active_targets(
                alias,
                intended_targets,
            )
            if not acknowledged:
                raise RagAliasParityError(
                    "alias_parity_activation_unacknowledged",
                    "Elasticsearch did not acknowledge alias parity recovery.",
                    retryable=True,
                )
            observed = await search_index.active_targets(alias)
        if observed != intended_targets:
            raise RagAliasParityError(
                "alias_parity_target_mismatch",
                "The observed alias target set did not match PostgreSQL truth.",
                retryable=True,
            )

        target_build_ids = tuple(target.build_id for target in current)
        await session.execute(
            update(RagIndexBuildRecord)
            .where(RagIndexBuildRecord.indexing_profile_id == profile_id)
            .values(is_active=RagIndexBuildRecord.id.in_(target_build_ids))
        )
        await session.flush()


async def _authoritative_targets(
    session: AsyncSession,
    profile_id: UUID,
) -> tuple[_AuthoritativeTarget, ...]:
    rows = (
        await session.execute(
            select(
                AssetVersionRecord.id,
                DocumentRecord.id,
                RagProjectionRecord.id,
                RagIndexBuildRecord.id,
                RagIndexBuildRecord.index_name,
                RagIndexBuildRecord.vector_dimension,
            )
            .join(
                RagProjectionRecord,
                RagProjectionRecord.asset_version_id == AssetVersionRecord.id,
            )
            .join(
                RagIndexBuildRecord,
                RagIndexBuildRecord.projection_id == RagProjectionRecord.id,
            )
            .join(
                DocumentRecord,
                DocumentRecord.id == AssetVersionRecord.document_id,
            )
            .where(
                RagProjectionRecord.indexing_profile_id == profile_id,
                RagProjectionRecord.status == ProjectionStatus.READY,
                RagIndexBuildRecord.indexing_profile_id == profile_id,
                RagIndexBuildRecord.status == "ready",
                AssetVersionRecord.status == VersionStatus.READY,
                DocumentRecord.active_version_id == AssetVersionRecord.id,
            )
            .order_by(AssetVersionRecord.id, RagIndexBuildRecord.id)
        )
    ).all()
    return tuple(_AuthoritativeTarget(*row) for row in rows)
