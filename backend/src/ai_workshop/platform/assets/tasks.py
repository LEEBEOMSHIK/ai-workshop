import hashlib
from typing import Protocol
from uuid import UUID

from ai_workshop.config import Settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.platform.assets.domain import AssetVersion
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.storage import ObjectStore
from ai_workshop.platform.jobs.domain import JobStatus
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository
from ai_workshop.shared.db import create_engine, create_session_factory


class AssetTaskError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class AssetVerificationLifecycle(Protocol):
    async def begin(self, job_id: UUID) -> AssetVersion | None: ...

    async def succeed(self, job_id: UUID) -> None: ...

    async def fail(
        self,
        job_id: UUID,
        *,
        error_code: str,
        error_message: str,
    ) -> None: ...


class AssetVerificationWorkflow:
    def __init__(
        self,
        lifecycle: AssetVerificationLifecycle,
        object_store: ObjectStore,
    ) -> None:
        self.lifecycle = lifecycle
        self.object_store = object_store

    async def run(self, job_id: UUID) -> None:
        version = await self.lifecycle.begin(job_id)
        if version is None:
            return
        try:
            await verify_stored_asset(self.object_store, version)
        except AssetTaskError as exc:
            await self.lifecycle.fail(
                job_id,
                error_code=exc.code,
                error_message=str(exc),
            )
            raise
        await self.lifecycle.succeed(job_id)


class SqlAlchemyAssetVerificationLifecycle:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def begin(self, job_id: UUID) -> AssetVersion | None:
        engine = create_engine(self.settings)
        session_factory = create_session_factory(engine)
        version: AssetVersion | None = None
        error: AssetTaskError | None = None
        try:
            async with session_factory.begin() as session:
                jobs = SqlAlchemyJobRepository(session)
                job = await jobs.find_by_id(job_id)
                if job is None:
                    error = AssetTaskError(
                        "job_not_found",
                        "The background job does not exist.",
                        retryable=False,
                    )
                elif job.status is JobStatus.SUCCEEDED:
                    return None
                elif job.status is JobStatus.FAILED:
                    error = AssetTaskError(
                        "job_terminal",
                        "The background job is already in a terminal state.",
                        retryable=False,
                    )
                else:
                    if job.status is JobStatus.QUEUED:
                        job.start(stage="verifying_object")
                        await jobs.update(job)
                    version = await SqlAlchemyAssetRepository(session).find_version(
                        job.asset_version_id
                    )
                    if version is None:
                        job.fail(
                            error_code="asset_version_not_found",
                            error_message="The asset version does not exist.",
                        )
                        await jobs.update(job)
                        error = AssetTaskError(
                            "asset_version_not_found",
                            "The asset version does not exist.",
                            retryable=False,
                        )
        finally:
            await engine.dispose()
        if error is not None:
            raise error
        return version

    async def succeed(self, job_id: UUID) -> None:
        engine = create_engine(self.settings)
        session_factory = create_session_factory(engine)
        try:
            async with session_factory.begin() as session:
                jobs = SqlAlchemyJobRepository(session)
                job = await jobs.find_by_id(job_id)
                if job is None:
                    raise AssetTaskError(
                        "job_not_found",
                        "The background job does not exist.",
                        retryable=False,
                    )
                if job.status is JobStatus.SUCCEEDED:
                    return
                job.succeed(stage="stored")
                await jobs.update(job)
        finally:
            await engine.dispose()

    async def fail(
        self,
        job_id: UUID,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        engine = create_engine(self.settings)
        session_factory = create_session_factory(engine)
        try:
            async with session_factory.begin() as session:
                jobs = SqlAlchemyJobRepository(session)
                job = await jobs.find_by_id(job_id)
                if job is None:
                    return
                if job.status is JobStatus.FAILED:
                    return
                job.fail(error_code=error_code, error_message=error_message)
                await jobs.update(job)
        finally:
            await engine.dispose()


def create_asset_verification_workflow(settings: Settings) -> AssetVerificationWorkflow:
    return AssetVerificationWorkflow(
        SqlAlchemyAssetVerificationLifecycle(settings),
        LocalObjectStore(settings.object_store_root),
    )


async def verify_stored_asset(object_store: ObjectStore, version: AssetVersion) -> None:
    digest = hashlib.sha256()
    size = 0
    try:
        async for chunk in object_store.open(version.object_key):
            digest.update(chunk)
            size += len(chunk)
    except OSError as exc:
        raise AssetTaskError(
            "object_unavailable",
            "The stored object could not be read.",
            retryable=True,
        ) from exc
    if digest.hexdigest() != version.sha256 or size != version.size:
        raise AssetTaskError(
            "checksum_mismatch",
            "The stored object does not match its recorded checksum.",
            retryable=False,
        )
