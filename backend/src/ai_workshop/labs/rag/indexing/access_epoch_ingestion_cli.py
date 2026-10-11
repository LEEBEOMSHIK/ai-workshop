"""One registered job through the normal pipeline; no broker acknowledgement or retry."""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import text

from ai_workshop.config import Settings
from ai_workshop.infrastructure.local.service_bootstrap_context import (
    VerifiedLaunchCapability,
    current_verified_launch,
)
from ai_workshop.infrastructure.local.service_launcher import SERVICE_MODULES
from ai_workshop.infrastructure.local.windows_process import process_identity
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from ai_workshop.labs.rag.indexing.access_epoch_runtime import (
    require_launch_role,
    verify_original_runtime,
)
from ai_workshop.labs.rag.ingestion.error_policy import classify_ingestion_error
from ai_workshop.labs.rag.ingestion.tasks import create_rag_ingestion_workflow
from ai_workshop.shared.asyncio_policy import configure_windows_selector_policy
from ai_workshop.shared.db import create_engine


class _Parser:
    def parse_args(self, argv: Sequence[str] | None = None) -> argparse.Namespace:
        try:
            args = list(sys.argv[1:] if argv is None else argv)
            if len(args) != 2 or args[0] != "--job":
                raise ValueError
            job = UUID(args[1])
            if str(job) != args[1]:
                raise ValueError
            return argparse.Namespace(job=job)
        except Exception:
            raise ValueError("access_epoch_ingestion_arguments") from None


def parser() -> _Parser:
    return _Parser()


def _birth(settings: Settings, job: UUID) -> VerifiedLaunchCapability:
    value = current_verified_launch()
    if (
        type(job) is not UUID
        or type(value) is not VerifiedLaunchCapability
        or value.service != "ingestion"
        or value.module != SERVICE_MODULES["ingestion"]
        or value.role != "writer"
        or type(value.pid) is not int
        or value.pid != os.getpid()
        or type(value.ordinal) is not int
        or value.ordinal < 1
        or type(value.bound_ids) is not tuple
        or value.bound_ids != (job,)
        or any(type(item) is not UUID for item in value.bound_ids)
        or settings.environment != "local"
        or settings.elasticsearch_access_epoch_id is None
        or value.epoch_id != settings.elasticsearch_access_epoch_id
        or value.ordinal != settings.elasticsearch_access_epoch
        or settings.elasticsearch_role != "writer"
    ):
        raise ValueError("access_epoch_ingestion_denied")
    require_launch_role(settings, writer=True)
    created, _image = process_identity(value.pid)
    if created != value.creation_time:
        raise ValueError("access_epoch_ingestion_denied")
    return value


@dataclass(frozen=True, slots=True)
class _Target:
    job_id: UUID
    projection_id: UUID
    indexing_profile_id: UUID
    document_processing_profile_id: UUID
    asset_version_id: UUID


def _decode_target(row: Mapping[str, object], job: UUID, *, completed: bool) -> _Target:
    ids = tuple(
        row.get(name)
        for name in (
            "job_id",
            "projection_id",
            "indexing_profile_id",
            "document_processing_profile_id",
            "asset_version_id",
        )
    )
    if (
        any(type(value) is not UUID for value in ids)
        or ids[0] != job
        or row.get("gate_state") != "admitted"
        or row.get("open_alias") is not False
        or row.get("dispatch_status") != "pending"
        or row.get("job_stage") != ("ready" if completed else "queued")
        or any(
            row.get(name) is not True
            for name in (
                "source_valid",
                "profiles_valid",
                "command_valid",
            )
        )
        or (row.get("job_status"), row.get("projection_status"))
        != (("succeeded", "ready") if completed else ("queued", "pending"))
    ):
        raise ValueError("access_epoch_ingestion_denied")
    if completed:
        counts = tuple(
            row.get(name)
            for name in (
                "parsed_element_count",
                "chunk_count",
                "embedding_count",
                "indexed_document_count",
            )
        )
        if (
            any(type(count) is not int or count <= 0 for count in counts)
            or counts[1] != counts[2]
            or counts[1] != counts[3]
            or row.get("index_alias_verified") is not True
        ):
            raise ValueError("access_epoch_ingestion_denied")
    return _Target(*(cast(UUID, value) for value in ids))


async def _read_target(settings: Settings, job: UUID, *, completed: bool) -> _Target:
    if not settings.rag_index_cluster_uuid or not settings.rag_index_store_id:
        raise ValueError("access_epoch_ingestion_denied")
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text("""
SELECT i.job_id, i.projection_id, i.indexing_profile_id,
 i.document_processing_profile_id, i.asset_version_id,
 j.status AS job_status, j.stage AS job_stage, p.status AS projection_status, g.state AS gate_state,
 d.status AS dispatch_status,
 (a.status='ready' AND doc.lifecycle='active' AND doc.active_version_id=a.id
  AND NOT EXISTS(SELECT 1 FROM rag_index_write_fences f WHERE f.document_id=doc.id))
 AS source_valid,
 (ip.kind='indexing' AND pp.kind='document_processing') AS profiles_valid,
 (j.type='rag_ingestion' AND j.asset_version_id=i.asset_version_id
  AND j.user_id=i.requested_by AND j.workspace_id=doc.workspace_id
  AND p.asset_version_id=i.asset_version_id AND p.indexing_profile_id=i.indexing_profile_id
  AND p.document_processing_profile_id=i.document_processing_profile_id) AS command_valid,
 EXISTS(SELECT 1 FROM rag_alias_operations o WHERE o.cluster_uuid=:cluster
  AND o.indexing_profile_id=i.indexing_profile_id AND o.state='open') AS open_alias,
 i.parsed_element_count, i.chunk_count, i.embedding_count, i.indexed_document_count,
 i.index_alias_verified
FROM rag_ingestion_jobs i JOIN jobs j ON j.id=i.job_id
 JOIN rag_document_projections p ON p.id=i.projection_id
 JOIN asset_versions a ON a.id=i.asset_version_id
 JOIN documents doc ON doc.id=a.document_id
 JOIN rag_profiles ip ON ip.id=i.indexing_profile_id
 JOIN rag_profiles pp ON pp.id=i.document_processing_profile_id
 JOIN rag_ingestion_dispatches d ON d.job_id=i.job_id
 JOIN rag_alias_cluster_gates g ON g.cluster_uuid=:cluster
WHERE i.job_id=:job
"""),
                        {"job": job, "cluster": settings.rag_index_cluster_uuid},
                    )
                )
                .mappings()
                .all()
            )
        if len(rows) != 1:
            raise ValueError("access_epoch_ingestion_denied")
        return _decode_target(dict(rows[0]), job, completed=completed)
    except Exception:
        raise ValueError("access_epoch_ingestion_denied") from None
    finally:
        await engine.dispose()


def _summary(job: UUID | None, code: str | None) -> dict[str, object]:
    return {
        "job_id": str(job) if type(job) is UUID else None,
        "projection_id": None,
        "workflow_completed": False,
        "dispatch": "not_observed",
        "error_code": code,
    }


async def run(job: UUID) -> dict[str, object]:
    output = _summary(job, "access_epoch_ingestion_denied")
    try:
        path = PROJECT_ROOT / ".env"
        if path.is_symlink() or not path.is_file():
            raise ValueError
        settings = Settings(_env_file=path)  # type: ignore[call-arg]
        born = _birth(settings, job)
        await verify_original_runtime(settings, writer=True)
        if _birth(settings, job) is not born:
            raise ValueError
        target = await _read_target(settings, job, completed=False)
        if _birth(settings, job) is not born:
            raise ValueError
    except Exception:
        return output
    try:
        projection = await create_rag_ingestion_workflow(settings).run(job)
    except Exception as error:
        code, retryable = classify_ingestion_error(error)
        # A normal child has no job-wide lease authorizing shared failure. Neither
        # a fresh status tuple nor this exception supplies that missing authority.
        if code in {
            "artifact_attempt_busy",
            "rag_index_attempt_busy",
            "rag_index_writer_unconfirmed",
        }:
            output["error_code"] = "ingestion_owner_unsettled"
        else:
            output["error_code"] = (
                "ingestion_retryable_unsettled" if retryable else "terminal_failure_unsettled"
            )
        return output
    output["error_code"] = "ingestion_completion_unconfirmed"
    try:
        if type(projection) is not UUID or projection != target.projection_id:
            return output
        if await _read_target(settings, job, completed=True) != target:
            return output
        if _birth(settings, job) is not born:
            return output
    except Exception:
        return output
    output.update(
        projection_id=str(projection), workflow_completed=True, dispatch="pending", error_code=None
    )
    return output


def main(argv: Sequence[str] | None = None) -> None:
    try:
        args = parser().parse_args(argv)
    except ValueError:
        print(json.dumps(_summary(None, "access_epoch_ingestion_arguments"), sort_keys=True))
        raise SystemExit(2) from None
    try:
        configure_windows_selector_policy()
        output = asyncio.run(run(args.job))
    except Exception:
        output = _summary(args.job, "ingestion_completion_unconfirmed")
    print(json.dumps(output, sort_keys=True))
    if output["error_code"] is not None:
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
