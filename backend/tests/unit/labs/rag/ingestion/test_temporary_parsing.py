from pathlib import Path

import pytest

from ai_workshop.config import Settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.labs.rag.ingestion import tasks
from ai_workshop.platform.assets.temporary_contracts import TemporaryOwnershipError
from tests.unit.labs.rag.parsing.test_service import (
    FakeTemporaryService,
    MemoryObjectStore,
    asset_version,
    context,
)


async def test_production_parser_rejects_missing_context_before_engine_creation(
    monkeypatch, tmp_path
):
    def forbidden(*args):
        raise AssertionError("must reject before engine creation")

    monkeypatch.setattr(tasks, "create_engine", forbidden)
    parser = tasks.ProductionParsingStage(
        Settings(_env_file=None, secret_key="synthetic-test-secret" * 2), LocalObjectStore(tmp_path)
    )
    with pytest.raises(TemporaryOwnershipError, match="source_mismatch"):
        await parser.materialize_and_parse(asset_version(), "public.txt")


async def test_production_parser_disposes_engine_after_tracked_parse(monkeypatch, tmp_path: Path):
    events = []
    owner = context()
    temporary = FakeTemporaryService(tmp_path)
    sessions = object()

    class Engine:
        async def dispose(self):
            events.append("disposed")

    monkeypatch.setattr(tasks, "create_engine", lambda settings: Engine())
    monkeypatch.setattr(tasks, "create_session_factory", lambda engine: sessions)

    def temporary_factory(settings, supplied_sessions):
        assert supplied_sessions is sessions
        events.append("factory")
        return temporary

    monkeypatch.setattr(tasks, "create_temporary_service", temporary_factory)
    parser = tasks.ProductionParsingStage(
        Settings(_env_file=None, secret_key="synthetic-test-secret" * 2),
        MemoryObjectStore(b"synthetic public text")
    )
    result = await parser.materialize_and_parse(asset_version(), "private.txt", context=owner)
    assert result.elements[0].text == "synthetic public text"
    assert temporary.contexts == [owner]
    assert temporary.finished == [True]
    assert events == ["factory", "disposed"]


async def test_production_parser_disposes_engine_if_tracking_configuration_fails(
    monkeypatch, tmp_path
):
    events = []

    class Engine:
        async def dispose(self):
            events.append("disposed")

    monkeypatch.setattr(tasks, "create_engine", lambda settings: Engine())
    monkeypatch.setattr(tasks, "create_session_factory", lambda engine: object())

    def temporary_factory(*args):
        raise TemporaryOwnershipError("store_unavailable")

    monkeypatch.setattr(tasks, "create_temporary_service", temporary_factory)
    parser = tasks.ProductionParsingStage(
        Settings(_env_file=None, secret_key="synthetic-test-secret" * 2), LocalObjectStore(tmp_path)
    )
    with pytest.raises(TemporaryOwnershipError, match="store_unavailable"):
        await parser.materialize_and_parse(asset_version(), "private.txt", context=context())
    assert events == ["disposed"]
    assert list(tmp_path.iterdir()) == []


def test_sqlalchemy_lifecycle_execution_carries_exact_source_and_job():
    from types import SimpleNamespace
    from uuid import uuid4

    from ai_workshop.labs.rag.documents.domain import ProjectionStatus
    from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
    from ai_workshop.platform.assets.temporary_contracts import TemporaryContext

    version = asset_version()
    workspace_id, job_id = uuid4(), uuid4()
    rows = SimpleNamespace(
        ingestion=SimpleNamespace(
            job_id=job_id, projection_id=uuid4(), indexing_profile_id=uuid4(),
            requested_by=uuid4(), parsed_object_key=None, parsed_sha256=None,
            chunk_object_key=None, chunk_sha256=None, embedding_object_key=None,
            embedding_sha256=None, document_processing_profile_id=uuid4(),
        ),
        asset=version,
        document=SimpleNamespace(workspace_id=workspace_id, id=version.document_id,
                                 name="synthetic.txt"),
        profile=SimpleNamespace(config={"chunker": {"name": "structure-aware"}}),
        projection=SimpleNamespace(status=ProjectionStatus.PARSING),
        processing_spec=None,
    )
    execution = tasks.SqlAlchemyRagIngestionLifecycle(
        Settings(_env_file=None, secret_key="synthetic-test-secret" * 2)
    )._execution(rows)
    assert execution.temporary_context == TemporaryContext(
        SourceIdentity(workspace_id, version.document_id, version.id), job_id
    )
