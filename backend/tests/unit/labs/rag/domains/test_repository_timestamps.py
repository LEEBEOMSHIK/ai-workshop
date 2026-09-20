"""Real ORM timestamp expiry must be refreshed through the awaited session boundary."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, create_autospec
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import MissingGreenlet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session

from ai_workshop.labs.rag.domains.models import (
    RagDomainConnectionVersionRecord,
    RagDomainRecord,
)
from ai_workshop.labs.rag.domains.repository import SqlAlchemyDomainRepository, _to_domain


@pytest.mark.parametrize("operation", ["update", "activate", "deactivate"])
async def test_domain_mutation_refreshes_expired_timestamp_before_conversion(
    operation: str,
) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE rag_domains (id CHAR(32) PRIMARY KEY, slug VARCHAR(80), "
            "display_name VARCHAR(180), description VARCHAR(1000), "
            "active_connection_version_id CHAR(32), created_by CHAR(32), "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
    try:
        with Session(engine, expire_on_commit=False) as persistence:
            record = RagDomainRecord(
                id=uuid4(), slug="synthetic-domain", display_name="Before",
                description="Synthetic description", active_connection_version_id=uuid4(),
                created_by=uuid4(), created_at=datetime(2020, 1, 1, tzinfo=UTC),
                updated_at=datetime(2020, 1, 1, tzinfo=UTC),
            )
            persistence.add(record)
            persistence.flush()
            original = _to_domain(record)
            explicit_refresh = False

            def reject_implicit_column_load(state: ORMExecuteState) -> None:
                if state.is_column_load and not explicit_refresh:
                    raise MissingGreenlet("Timestamp load requires an awaited refresh.")

            event.listen(persistence, "do_orm_execute", reject_implicit_column_load)

            async def flush() -> None:
                persistence.flush()
                assert "updated_at" in inspect(record).expired_attributes

            async def refresh(instance: object, attribute_names: list[str]) -> None:
                nonlocal explicit_refresh
                assert instance is record
                explicit_refresh = True
                try:
                    persistence.refresh(instance, attribute_names=attribute_names)
                finally:
                    explicit_refresh = False

            session = create_autospec(AsyncSession, instance=True)
            connection_record = RagDomainConnectionVersionRecord(id=uuid4(), domain_id=record.id)
            session.get = AsyncMock(
                return_value=connection_record if operation == "activate" else record,
            )
            session.scalar = AsyncMock(return_value=record)
            session.flush = AsyncMock(side_effect=flush)
            session.refresh = AsyncMock(side_effect=refresh)
            repository = SqlAlchemyDomainRepository(cast(AsyncSession, session))

            if operation == "update":
                result = await repository.update_domain(replace(original, display_name="After"))
                assert result.display_name == "After"
            elif operation == "activate":
                result = await repository.set_active_connection(record.id, connection_record.id)
                assert result.active_connection_version_id == connection_record.id
            else:
                result = await repository.set_active_connection(record.id, None)
                assert result.active_connection_version_id is None

            assert result.updated_at is not None and original.updated_at is not None
            assert result.updated_at.year > original.updated_at.year
            assert "updated_at" not in inspect(record).expired_attributes
            session.refresh.assert_awaited_once_with(record, attribute_names=["updated_at"])
    finally:
        engine.dispose()
