"""Additive migration and downgrade gates in a UUID disposable database."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from tests.integration.labs.rag.indexing.test_resource_repository import seed_resource
from tests.integration.labs.rag.ingestion.test_artifact_repository import _isolated_database_at


@pytest.fixture(autouse=True)
def ensure_legacy_document_processing_profile():
    """Prevent the parent fixture from connecting before UUID isolation exists."""


def test_empty_upgrade_and_downgrade():
    with _isolated_database_at("0041_rag_artifact_provenance") as database:
        command.upgrade(database.config, "0042_rag_index_resources")
        command.downgrade(database.config, "0041_rag_artifact_provenance")
        command.upgrade(database.config, "0042_rag_index_resources")


def test_nonempty_ledger_blocks_downgrade():
    import asyncio

    with _isolated_database_at("0042_rag_index_resources") as database:

        async def seed():
            engine = create_async_engine(database.database_url)
            try:
                async with async_sessionmaker(engine).begin() as session:
                    await seed_resource(session)
            finally:
                await engine.dispose()

        asyncio.run(seed())
        with pytest.raises(RuntimeError, match="rag_index_downgrade_blocked"):
            command.downgrade(database.config, "0041_rag_artifact_provenance")


def test_orphan_participant_relation_blocks_downgrade():
    import asyncio

    from sqlalchemy import delete

    from ai_workshop.labs.rag.indexing.resource_models import RagIndexResourceRecord

    with _isolated_database_at("0042_rag_index_resources") as database:

        async def seed_relation_only():
            engine = create_async_engine(database.database_url)
            try:
                async with async_sessionmaker(engine).begin() as session:
                    resource = await seed_resource(session)
                    await session.execute(
                        delete(RagIndexResourceRecord).where(
                            RagIndexResourceRecord.build_id == resource.build_id
                        )
                    )
            finally:
                await engine.dispose()

        asyncio.run(seed_relation_only())
        with pytest.raises(RuntimeError, match="rag_index_downgrade_blocked"):
            command.downgrade(database.config, "0041_rag_artifact_provenance")
