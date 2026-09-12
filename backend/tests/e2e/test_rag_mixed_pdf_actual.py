"""Opt-in real OCR/E5/ES pipeline, optionally through a dedicated Celery worker.

By default only broker delivery is replaced and production workflows run inline.
AI_WORKSHOP_MIXED_PDF_ACTUAL_QUEUE=1 uses Redis and an isolated worker instead.
Both modes use a unique migrated database, index prefix, and temporary object store.
"""

import asyncio
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pymupdf
import pytest
from alembic.config import Config
from elasticsearch import Elasticsearch
from fastapi.testclient import TestClient
from PIL import Image
from psycopg import sql
from redis import Redis
from sqlalchemy import make_url

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand
from ai_workshop.labs.rag.ingestion.repository import SqlAlchemyRagIngestionCommandRepository
from ai_workshop.labs.rag.ingestion.service import RagIngestionService
from ai_workshop.labs.rag.ingestion.tasks import create_rag_ingestion_workflow
from ai_workshop.main import create_app
from ai_workshop.platform.assets.tasks import create_asset_verification_workflow
from ai_workshop.shared.db import create_engine, create_session_factory
from ai_workshop.worker import (
    RAG_DISPATCH_RECONCILE_TASK,
    CeleryJobDispatcher,
    create_celery,
    get_job_dispatcher,
)
from alembic import command
from tests.integration.labs.rag.ocr.test_paddle_structure_smoke import create_smoke_fixture

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROCESSING_ID = "00000000-0000-0000-0000-000000000211"
INDEXING_ID = "00000000-0000-0000-0000-000000000201"
BM25_ID = "00000000-0000-0000-0000-000000000202"


def _queue_application():  # type: ignore[no-untyped-def]
    application = create_celery(get_settings())
    namespace = os.environ["AI_WORKSHOP_SMOKE_QUEUE_NAMESPACE"]
    assert namespace.startswith("mixed-pdf-queue-")
    application.conf.update(
        task_default_queue=namespace,
        broker_transport_options={"global_keyprefix": f"{namespace}:"},
        worker_enable_remote_control=True,
    )
    assert not application.conf.task_always_eager
    return application


@contextmanager
def _queue_worker(tmp_path: Path) -> Iterator[None]:
    namespace = os.environ["AI_WORKSHOP_SMOKE_QUEUE_NAMESPACE"]
    with (tmp_path / "worker.log").open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", (
                "import sys; sys.path.insert(0, 'backend'); "
                "from tests.e2e.test_rag_mixed_pdf_actual import _queue_application; "
                "a = _queue_application(); "
                "a.worker_main(['worker', '--pool=solo', '--concurrency=1', "
                "'--hostname=' + a.conf.task_default_queue + '@isolated', "
                "'--without-gossip', '--without-mingle', '--without-heartbeat', "
                "'--loglevel=INFO'])"
            )],
            cwd=BACKEND_ROOT.parent,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                assert process.poll() is None, "Isolated Celery worker failed to start"
                if " ready." in (tmp_path / "worker.log").read_text(errors="replace"):
                    break
                time.sleep(0.25)
            else:
                pytest.fail("Isolated Celery worker did not become ready within 30 seconds")
            yield
            assert process.poll() is None, "Isolated Celery worker exited unexpectedly"
        finally:
            if process.poll() is None:
                application = _queue_application()
                application.control.broadcast(
                    "shutdown", destination=[f"{namespace}@isolated"],
                )
                # The worker exits first, then its Windows venv launcher exits.
                # A timeout is a failed cleanup, never a successful parent-only kill.
                process.wait(timeout=30)
            with Redis.from_url(get_settings().redis_url) as broker:
                keys = list(broker.scan_iter(match=f"{namespace}:*"))
                if keys:
                    assert all(key.startswith(f"{namespace}:".encode()) for key in keys)
                    broker.delete(*keys)
                assert not list(broker.scan_iter(match=f"{namespace}:*"))


def _wait_for_job(sync_url: str, job_id: UUID) -> None:
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        with psycopg.connect(sync_url) as connection:
            row = connection.execute(
                "SELECT status, error_code FROM jobs WHERE id = %s", (job_id,),
            ).fetchone()
        assert row is not None
        assert row[0] != "failed", f"Queued ingestion failed: {row[1]}"
        if row[0] == "succeeded":
            return
        time.sleep(1)
    pytest.fail("Isolated Celery ingestion did not finish within 600 seconds")


class _InlineDelivery:
    def verify_asset(self, job_id: UUID) -> None:
        # Retain upload/outbox writes; replace only the broker transport.
        asyncio.run(create_asset_verification_workflow(get_settings()).run(job_id))


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("AI_WORKSHOP_MIXED_PDF_ACTUAL_SMOKE") != "1",
    reason="Set AI_WORKSHOP_MIXED_PDF_ACTUAL_SMOKE=1 with local OCR/E5/PG/ES ready.",
)
def test_actual_mixed_pdf_upload_search_and_authorized_viewer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native PDF title must not hide raster text/table from search evidence."""
    base = get_settings()
    url = make_url(base.database_url).update_query_dict({"connect_timeout": "10"})
    database = f"ai_workshop_mixed_{uuid4().hex}"
    prefix = f"mixed-pdf-smoke-{uuid4().hex}"
    admin_url = url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False,
    )
    sync_url = url.set(drivername="postgresql", database=database).render_as_string(
        hide_password=False,
    )
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        monkeypatch.setenv(
            "AI_WORKSHOP_DATABASE_URL",
            url.set(database=database).render_as_string(hide_password=False),
        )
        # Keep Windows object keys below MAX_PATH even under the audited basetemp.
        monkeypatch.setenv("AI_WORKSHOP_OBJECT_STORE_ROOT", str(tmp_path.parent / "o"))
        monkeypatch.setenv("AI_WORKSHOP_MODEL_CACHE_ROOT", str(base.model_cache_root.resolve()))
        monkeypatch.setenv("AI_WORKSHOP_ELASTICSEARCH_INDEX_PREFIX", prefix)
        monkeypatch.setenv("AI_WORKSHOP_ENVIRONMENT", "local")
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
        monkeypatch.setenv("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        get_settings.cache_clear()
        command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
        queue_mode = os.environ.get("AI_WORKSHOP_MIXED_PDF_ACTUAL_QUEUE") == "1"
        monkeypatch.setenv("AI_WORKSHOP_SMOKE_QUEUE_NAMESPACE", f"mixed-pdf-queue-{uuid4().hex}")
        with _queue_worker(tmp_path) if queue_mode else nullcontext():
            _exercise_pipeline(tmp_path, sync_url, queue_mode=queue_mode)
    finally:
        # Enumerate only this run's namespace, then delete exact concrete names.
        try:
            with Elasticsearch(base.elasticsearch_url) as search:
                indices = search.indices.get(index=f"{prefix}-*", allow_no_indices=True)
                for name in indices:
                    assert name.startswith(f"{prefix}-")
                    search.indices.delete(index=name)
        finally:
            get_settings.cache_clear()
            with psycopg.connect(admin_url, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
                )


def _exercise_pipeline(tmp_path: Path, sync_url: str, *, queue_mode: bool) -> None:
    fixture = create_smoke_fixture(
        tmp_path,
        platform="windows" if sys.platform == "win32" else "linux",
    )
    source = tmp_path / "mixed-public-policy.pdf"
    with pymupdf.open() as document:
        for image, height in ((fixture.text_image, 280), (fixture.table_image, 460)):
            page = document.new_page(width=600, height=height)
            page.insert_text((30, 35), "PUBLIC MIXED DOCUMENT NATIVE HEADING", fontsize=14)
            page.insert_image(pymupdf.Rect(0, 80, 600, height - 20), filename=str(image))
        document.save(source)
    app = create_app()
    if queue_mode:
        dispatcher = CeleryJobDispatcher(get_settings())
        dispatcher.application = _queue_application()
        app.dependency_overrides[get_job_dispatcher] = lambda: dispatcher
    else:
        app.dependency_overrides[get_job_dispatcher] = _InlineDelivery
    with TestClient(app) as client:
        owner = client.post(
            "/api/v1/setup/owner",
            json={
                "display_name": "Synthetic smoke owner",
                "email": "mixed@example.com",
                "password": "public-synthetic-password",
                "password_confirmation": "public-synthetic-password",
            },
        )
        assert owner.status_code == 201, owner.text
        workspaces = client.get("/api/v1/workspaces")
        assert workspaces.status_code == 200
        workspace_id = next(w["id"] for w in workspaces.json() if w["kind"] == "personal")
        upload = client.post(
            f"/api/v1/workspaces/{workspace_id}/documents",
            files={
                "file": (source.name, source.read_bytes(), "application/pdf"),
            },
        )
        assert upload.status_code == 201, upload.text
        versions = client.get(f"/api/v1/documents/{upload.json()['id']}/versions").json()
        asset_id = versions[-1]["id"]
        if queue_mode:
            deadline = time.monotonic() + 90
            while versions[-1]["status"] != "ready" and time.monotonic() < deadline:
                time.sleep(1)
                versions = client.get(
                    f"/api/v1/documents/{upload.json()['id']}/versions",
                ).json()
        assert versions[-1]["status"] == "ready"
        hybrid = client.post(
            "/api/v1/rag/profiles/retrieval",
            json={
                "name": "mixed-pdf-actual-hybrid",
                "version": 1,
                "bindings": [],
                "evaluation_state": "draft",
                "config": {
                    "indexing_profile_id": INDEXING_ID,
                    "bm25": {"analyzer": "standard", "top_k": 30},
                    "dense": {"top_k": 30},
                    "rrf": {"k": 60},
                    "reranker": {"enabled": False},
                },
            },
        )
        assert hybrid.status_code == 201, hybrid.text
        configurations = []
        for retrieval_id in (BM25_ID, hybrid.json()["id"]):
            saved = client.post(
                "/api/v1/rag/configurations",
                json={
                    "name": f"Mixed PDF {retrieval_id}",
                    "document_processing_profile_id": PROCESSING_ID,
                    "indexing_profile_id": INDEXING_ID,
                    "retrieval_profile_id": retrieval_id,
                    "workspace_ids": [workspace_id],
                    "answer_policy": {"min_semantic_score": 0.0, "min_keyword_coverage": 0.5},
                },
            )
            assert saved.status_code == 201, saved.text
            configurations.append(saved.json())
        job_id = asyncio.run(_ingest(UUID(asset_id), UUID(owner.json()["id"]), queue_mode))
        if queue_mode:
            _wait_for_job(sync_url, job_id)
        with psycopg.connect(sync_url) as connection:
            row = connection.execute(
                "SELECT id, status FROM rag_document_projections WHERE asset_version_id = %s "
                "AND document_processing_profile_id = %s",
                (asset_id, PROCESSING_ID),
            ).fetchone()
            assert row is not None and row[1] == "ready"
            projection_id = str(row[0])
        normalized_url = f"/api/v1/rag/sources/{asset_id}/normalized-text"
        params = {"projection_id": projection_id}
        normalized = client.get(normalized_url, params=params)
        assert normalized.status_code == 200, normalized.text
        parsed = normalized.json()
        assert parsed["parser_name"] == "pymupdf-ocr"
        assert parsed["parser_version"] == "2"
        elements = parsed["elements"]
        assert any("NATIVE HEADING" in e["text"] for e in elements)
        for page_number, tokens in ((1, fixture.text_tokens), (2, fixture.table_tokens)):
            eligible = [
                e
                for e in elements
                if e["location"]["page"] == page_number
                and e["kind"].startswith("ocr_")
                and e["evidence_eligible"]
            ]
            assert all(token in " ".join(e["text"] for e in eligible) for token in tokens)
            assert all(e["location"]["bbox"] is not None for e in eligible)
        assert any(e["kind"] == "ocr_table_cell" for e in elements)
        for configuration in configurations:
            ready = client.get(f"/api/v1/rag/configurations/{configuration['id']}")
            assert ready.json()["search_ready"] is True
            for query, expected_page in ((fixture.text_tokens[0], 1), (fixture.table_tokens[0], 2)):
                result = client.post(
                    "/api/v1/rag/search",
                    json={
                        "query": query,
                        "configuration_id": configuration["id"],
                        "workspace_ids": [workspace_id],
                        "experimental": True,
                    },
                )
                assert result.status_code == 200, result.text
                answer = result.json()["answer"]
                assert answer is not None, result.text
                assert query in answer["excerpt"]
                location = answer["source"]["location"]
                assert location["page"] == expected_page
                assert location["source_kind"] == "pdf_page"
                assert location["bbox"] is not None
                assert answer["source"]["asset_version_id"] == asset_id
                assert answer["source"]["projection_id"] == projection_id
                evidence_element = next(
                    e for e in elements if e["id"] == answer["source"]["element_id"]
                )
                assert evidence_element["kind"].startswith("ocr_")
                assert answer["highlights"]
                assert all(h["kind"] == "keyword" for h in answer["highlights"])
                assert all(h["page"] == expected_page for h in answer["highlights"])
                if expected_page == 1:
                    # "운용" covers part of the OCR line, so has no measured word box.
                    assert all(h["bbox"] is None for h in answer["highlights"])
                else:
                    # "주식" is the complete measured table cell.
                    assert all(h["bbox"] == location["bbox"] for h in answer["highlights"])
        semantic = client.post(
            "/api/v1/rag/search",
            json={
                "query": "투자 가능한 최대 비중이 얼마인지 알려주세요",
                "configuration_id": configurations[-1]["id"],
                "workspace_ids": [workspace_id],
                "experimental": True,
            },
        )
        assert semantic.status_code == 200, semantic.text
        semantic_answer = semantic.json()["answer"]
        assert semantic_answer is not None, semantic.text
        semantic_source = semantic_answer["source"]
        semantic_element = next(e for e in elements if e["id"] == semantic_source["element_id"])
        assert semantic_element["kind"].startswith("ocr_")
        assert semantic_source["location"]["source_kind"] == "pdf_page"
        assert semantic_answer["semantic_score"] > 0
        assert semantic_answer["highlights"]
        for highlight in semantic_answer["highlights"]:
            assert highlight["kind"] == "semantic"
            assert highlight["page"] == semantic_source["location"]["page"]
            assert highlight["bbox"] == semantic_source["location"]["bbox"]
            assert highlight["bbox"] is not None
        page_url = f"/api/v1/rag/sources/{asset_id}/pdf/pages/2"
        page = client.get(page_url, params=params)
        assert page.status_code == 200
        assert page.headers["content-type"] == "image/png"
        with Image.open(BytesIO(page.content)) as rendered:
            assert rendered.size == (600, 460)
        client.cookies.clear()
        assert client.get(page_url, params=params).status_code == 401
        assert client.get(normalized_url, params=params).status_code == 401


async def _ingest(asset_id: UUID, owner_id: UUID, queue_mode: bool) -> UUID:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine).begin() as session:
            job_id = await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(session),
            ).ensure_indexed(
                EnsureIndexedCommand(
                    asset_version_id=asset_id,
                    indexing_profile_id=UUID(INDEXING_ID),
                    requested_by=owner_id,
                    document_processing_profile_id=UUID(PROCESSING_ID),
                )
            )
    finally:
        await engine.dispose()
    if queue_mode:
        application = _queue_application()
        application.tasks[RAG_DISPATCH_RECONCILE_TASK].delay()
    else:
        await create_rag_ingestion_workflow(settings).run(job_id)
    return job_id
