from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.configurations.domain import BM25_RETRIEVAL_PROFILE_ID
from ai_workshop.labs.rag.models.catalog import (
    CatalogConflictError,
    ModelCatalogImporter,
    load_model_catalog,
)
from ai_workshop.labs.rag.models.domain import EvaluationState, Profile, ProfileKind
from ai_workshop.labs.rag.models.models import ModelDefinitionRecord, ProfileRecord
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
    inserted_ids: set[UUID] = set()
    try:
        async with sessions() as session:
            preexisting_ids = set(
                await session.scalars(
                    select(ModelDefinitionRecord.id).where(
                        ModelDefinitionRecord.id.in_(CATALOG_IDS)
                    )
                )
            )
        inserted_ids = set(CATALOG_IDS) - preexisting_ids
        async with sessions.begin() as session:
            first = await ModelCatalogImporter(
                SqlAlchemyModelRegistryRepository(session)
            ).import_definitions(definitions)
        async with sessions.begin() as session:
            second = await ModelCatalogImporter(
                SqlAlchemyModelRegistryRepository(session)
            ).import_definitions(definitions)
        assert (first.inserted, first.unchanged) == (
            len(inserted_ids),
            len(preexisting_ids),
        )
        assert (second.inserted, second.unchanged) == (0, 2)

        conflicting = replace(definitions[0], name="conflicting-catalog-name")
        async with sessions.begin() as session:
            with pytest.raises(CatalogConflictError):
                await ModelCatalogImporter(
                    SqlAlchemyModelRegistryRepository(session)
                ).import_definitions((conflicting,))
    finally:
        if inserted_ids:
            async with sessions.begin() as session:
                await session.execute(
                    delete(ModelDefinitionRecord).where(
                        ModelDefinitionRecord.id.in_(inserted_ids)
                    )
                )
        await engine.dispose()


@pytest.mark.asyncio
async def test_default_promotion_does_not_touch_referenced_non_default_profile() -> None:
    engine = create_engine(get_settings())
    sessions = create_session_factory(engine)
    target = Profile.create(
        kind=ProfileKind.RETRIEVAL,
        name=f"promotion-target-{uuid4()}",
        version=1,
        config={"bm25": {"analyzer": "standard", "top_k": 10}},
        bindings=(),
        evaluation_state=EvaluationState.PASSED,
    )
    try:
        async with sessions() as session:
            transaction = await session.begin()
            try:
                repository = SqlAlchemyModelRegistryRepository(session)
                await repository.add_profile(target)

                promoted = await repository.set_default(target.as_default())

                referenced = await session.get(
                    ProfileRecord, BM25_RETRIEVAL_PROFILE_ID
                )
                assert referenced is not None
                assert referenced.is_default is False
                assert promoted.is_default is True
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
