from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import delete

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.models.catalog import (
    CatalogConflictError,
    ModelCatalogImporter,
    load_model_catalog,
)
from ai_workshop.labs.rag.models.models import ModelDefinitionRecord
from ai_workshop.labs.rag.models.repository import SqlAlchemyModelRegistryRepository
from ai_workshop.shared.db import create_engine, create_session_factory

pytestmark = pytest.mark.integration

CATALOG_ROOT = Path(__file__).resolve().parents[6] / "model-profiles" / "rag" / "models"
CATALOG_IDS = (
    UUID("00000000-0000-0000-0000-000000000101"),
    UUID("00000000-0000-0000-0000-000000000102"),
)


@pytest.mark.asyncio
async def test_postgres_catalog_import_is_noop_only_for_identical_definitions() -> None:
    engine = create_engine(get_settings())
    sessions = create_session_factory(engine)
    definitions = load_model_catalog(CATALOG_ROOT)
    try:
        async with sessions.begin() as session:
            await session.execute(
                delete(ModelDefinitionRecord).where(ModelDefinitionRecord.id.in_(CATALOG_IDS))
            )
        async with sessions.begin() as session:
            first = await ModelCatalogImporter(
                SqlAlchemyModelRegistryRepository(session)
            ).import_definitions(definitions)
        async with sessions.begin() as session:
            second = await ModelCatalogImporter(
                SqlAlchemyModelRegistryRepository(session)
            ).import_definitions(definitions)
        assert (first.inserted, first.unchanged) == (2, 0)
        assert (second.inserted, second.unchanged) == (0, 2)

        conflicting = replace(definitions[0], name="conflicting-catalog-name")
        async with sessions.begin() as session:
            with pytest.raises(CatalogConflictError):
                await ModelCatalogImporter(
                    SqlAlchemyModelRegistryRepository(session)
                ).import_definitions((conflicting,))
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(ModelDefinitionRecord).where(ModelDefinitionRecord.id.in_(CATALOG_IDS))
            )
        await engine.dispose()
