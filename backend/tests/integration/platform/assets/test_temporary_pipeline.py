"""Exercise committed ownership through native storage, parsers and the real PDF worker."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.infrastructure.document_formats.pdf_preview import PdfPreviewRenderer
from ai_workshop.infrastructure.object_store.temporary import TrackedTemporaryStore
from ai_workshop.labs.rag.parsing.contracts import ParseRequest
from ai_workshop.labs.rag.parsing.plain_text import PlainTextParser
from ai_workshop.labs.rag.parsing.registry import ParserRegistry
from ai_workshop.labs.rag.parsing.service import ParsingService
from ai_workshop.platform.assets.domain import AssetVersion, VersionStatus
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.temporary_contracts import (
    TemporaryBinding,
    TemporaryContext,
    TemporaryOwnershipError,
)
from ai_workshop.platform.assets.temporary_models import TemporaryWorkspaceRecord
from ai_workshop.platform.assets.temporary_repository import TemporaryJournal
from ai_workshop.platform.assets.temporary_service import TemporaryWorkspaceService
from tests.integration.platform.assets.test_temporary_repository import database, seed  # noqa: F401


@pytest.fixture(autouse=True)
def ensure_legacy_document_processing_profile() -> None:
    pass


class SourceStore:
    async def open(self, key: str) -> AsyncIterator[bytes]:
        yield b"Synthetic pipeline paragraph."


class OpaqueParser(PlainTextParser):
    def parse(self, request: ParseRequest):
        request.opaque_runtime_started()
        raise RuntimeError("synthetic opaque runtime failure")


@pytest.mark.skipif(os.name != "nt", reason="Tracked temporary mutation requires Windows")
def test_pipeline_commits_cleanup_and_retains_unknown_writers_and_files(
    database,  # noqa: F811
    tmp_path: Path,
):
    async def run():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            context = await seed(sessions)
            binding = TemporaryBinding("temporary_pipeline", uuid4())
            root = tmp_path / "store"
            root.mkdir()
            (root / ".ai-workshop-temporary-store.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "store_id": binding.store_id,
                        "binding_id": str(binding.binding_id),
                    }
                ),
                encoding="utf-8",
            )
            store = TrackedTemporaryStore(root, binding)
            service = TemporaryWorkspaceService(TemporaryJournal(sessions), store)
            version = AssetVersion(
                id=context.source.asset_version_id,
                document_id=context.source.document_id,
                number=1,
                object_key="synthetic/source",
                sha256="a" * 64,
                media_type="text/plain",
                size=29,
                status=VersionStatus.STORED,
            )
            parser = ParsingService(
                SourceStore(), ParserRegistry((PlainTextParser(),)), temporary_service=service
            )
            parsed = await parser.materialize_and_parse(version, "synthetic.txt", context=context)
            assert parsed.elements[0].text == "Synthetic pipeline paragraph."

            renderer = PdfPreviewRenderer(
                max_pages=2,
                max_pixels=20_000,
                timeout_seconds=10,
                max_concurrent=1,
                temporary_service=service,
            )
            with pymupdf.open() as pdf:
                page = pdf.new_page(width=120, height=80)
                page.insert_text((10, 30), "Synthetic pipeline PDF")
                content = bytes(pdf.tobytes())
            viewer_context = TemporaryContext(context.source)
            assert (await renderer.inspect(content, context=viewer_context)).page_count == 1
            rendered = await renderer.render_page(content, 1, context=viewer_context)
            assert rendered.content.startswith(b"\x89PNG\r\n\x1a\n")
            pixmap = pymupdf.Pixmap(rendered.content)
            assert (pixmap.width, pixmap.height) == (120, 80)
            async with sessions() as session:
                rows = list(await session.scalars(select(TemporaryWorkspaceRecord)))
                assert len(rows) == 3
                for row in rows:
                    assert (row.state, row.revision) == ("cleaned", 4)
                    assert not (root / str(row.id)).exists()
                    assert row.asset_version_id == context.source.asset_version_id
                    relation = await session.scalar(
                        select(AssetSourceRelationRecord).where(
                            AssetSourceRelationRecord.resource_id == row.id
                        )
                    )
                    assert relation.resource_revision == 4
                    assert relation.asset_version_id == row.asset_version_id
                    assert row.job_id == (context.job_id if row.purpose == "parsing" else None)

            opaque = ParsingService(
                SourceStore(), ParserRegistry((OpaqueParser(),)), temporary_service=service
            )
            with pytest.raises(RuntimeError, match="synthetic opaque runtime failure"):
                await opaque.materialize_and_parse(version, "synthetic.txt", context=context)
            async with sessions() as session:
                unknown = await session.scalar(
                    select(TemporaryWorkspaceRecord).where(TemporaryWorkspaceRecord.state == "open")
                )
                assert unknown is not None and unknown.revision == 1
                unknown_root = root / str(unknown.id)
                assert unknown_root.is_dir()
                assert len(list(unknown_root.iterdir())) == 1
                relation = await session.scalar(
                    select(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.resource_id == unknown.id
                    )
                )
                assert relation.resource_revision == 1

            lease = await service.open(context, "parsing", coverage="bounded")
            owned = lease.workspace.create_file("owned.bin")
            owned.write_bytes(b"synthetic owned")
            foreign = lease.workspace.root / "unknown.bin"
            foreign.write_bytes(b"synthetic unknown")
            with pytest.raises(TemporaryOwnershipError):
                await lease.finish(writer_confirmed=True)
            assert owned.read_bytes() == b"synthetic owned"
            assert foreign.read_bytes() == b"synthetic unknown"
            async with sessions() as session:
                blocked = await session.get(TemporaryWorkspaceRecord, lease.claim.id)
                assert (blocked.state, blocked.revision) == ("cleaning", 3)
                relation = await session.scalar(
                    select(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.resource_id == lease.claim.id
                    )
                )
                assert relation.resource_revision == 3
        finally:
            await engine.dispose()

    asyncio.run(run())
