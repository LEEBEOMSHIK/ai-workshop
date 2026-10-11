"""Real SQLAlchemy transaction regression; no network, models or original DB writes."""

from asyncio import CancelledError
from contextlib import asynccontextmanager
from importlib import import_module
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import Column, Integer, String, create_engine, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ai_workshop.labs.rag.generation.audit import SqlAlchemyGenerationAuditRepository
from ai_workshop.labs.rag.search.api import (
    get_search_configuration_resolver,
    get_search_service,
)
from ai_workshop.shared.errors import AppError

Base = declarative_base()


class SyntheticAudit(Base):
    __tablename__ = "synthetic_audit"
    id = Column(Integer, primary_key=True)
    value = Column(String, nullable=False)


@pytest.fixture
def search_dependency(monkeypatch):
    dependency = get_type_hints(get_search_service, include_extras=True)["session"].__metadata__[0]
    provider = dependency.dependency
    configuration_dependency = get_type_hints(
        get_search_configuration_resolver, include_extras=True
    )["session"].__metadata__[0]
    assert configuration_dependency.dependency is provider
    module = import_module(provider.__module__)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    lifecycle = SimpleNamespace(dispose=AsyncMock(), opened=0, closed=0)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(expire_on_commit=False) as session:
            session.sync_session.bind = engine
            lifecycle.opened += 1
            try:
                yield session
            finally:
                lifecycle.closed += 1

    @asynccontextmanager
    async def begin():
        async with sessions() as session, session.begin():
            yield session

    sessions.begin = begin
    monkeypatch.setattr(module, "create_engine", lambda settings: lifecycle)
    monkeypatch.setattr(module, "create_session_factory", lambda actual: sessions)
    monkeypatch.setattr(module, "get_settings", lambda: object())
    try:
        yield provider, engine, lifecycle
    finally:
        engine.dispose()


@pytest.mark.parametrize("has_evidence", [False, True])
async def test_search_can_recheck_authority_after_durable_audit_commit(
    search_dependency, has_evidence
):
    provider, engine, lifecycle = search_dependency
    dependency = provider()
    session = await anext(dependency)
    try:
        value = "succeeded" if has_evidence else "allowed"
        session.add(SyntheticAudit(value=value))
        await SqlAlchemyGenerationAuditRepository(session).commit()
        # Both generated and no-evidence outcomes must execute the final source ACL check.
        assert await session.scalar(select(literal(1))) == 1
        with pytest.raises(StopAsyncIteration):
            await anext(dependency)
    finally:
        await dependency.aclose()
    with engine.connect() as connection:
        assert connection.scalar(select(SyntheticAudit.value)) == value
    assert lifecycle.opened == lifecycle.closed == 1
    lifecycle.dispose.assert_awaited_once()


async def test_failed_final_authority_preserves_committed_audit_and_rolls_back_later_work(
    search_dependency,
):
    provider, engine, lifecycle = search_dependency
    dependency = provider()
    session = await anext(dependency)
    try:
        session.add(SyntheticAudit(value="durable"))
        await SqlAlchemyGenerationAuditRepository(session).commit()
        assert await session.scalar(select(literal(1))) == 1
        session.add(SyntheticAudit(value="discard"))
        await session.flush()
        error = AppError("not_found", "Synthetic revoked authority", 404)
        with pytest.raises(AppError) as caught:
            await dependency.athrow(error)
        assert caught.value is error
    finally:
        await dependency.aclose()
    with engine.connect() as connection:
        assert connection.scalars(select(SyntheticAudit.value)).all() == ["durable"]
    assert lifecycle.opened == lifecycle.closed == 1
    lifecycle.dispose.assert_awaited_once()


async def test_success_commits_remaining_search_work(search_dependency):
    provider, engine, lifecycle = search_dependency
    dependency = provider()
    session = await anext(dependency)
    session.add(SyntheticAudit(value="complete"))
    with pytest.raises(StopAsyncIteration):
        await anext(dependency)
    with engine.connect() as connection:
        assert connection.scalar(select(SyntheticAudit.value)) == "complete"
    assert lifecycle.opened == lifecycle.closed == 1
    lifecycle.dispose.assert_awaited_once()


async def test_cancel_rolls_back_remaining_work_and_disposes_engine(search_dependency):
    provider, engine, lifecycle = search_dependency
    dependency = provider()
    session = await anext(dependency)
    session.add(SyntheticAudit(value="cancelled"))
    await session.flush()
    with pytest.raises(CancelledError):
        await dependency.athrow(CancelledError())
    with engine.connect() as connection:
        assert connection.scalars(select(SyntheticAudit.value)).all() == []
    assert lifecycle.opened == lifecycle.closed == 1
    lifecycle.dispose.assert_awaited_once()
