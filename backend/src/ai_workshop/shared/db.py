from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ai_workshop.config import Settings, get_settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_recycle=300,
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


class RequestDatabase:
    """One HTTP lifespan owns the pool, never a session or authorization result.

    Lazy construction avoids a connection configuration dependency for health-only
    apps. Construction has no await point, so concurrent requests on this app's
    event loop cannot create competing pools. Workers keep their explicit owners.
    """

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._factory: async_sessionmaker[AsyncSession] | None = None
        self._closed = False

    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._closed:
            raise RuntimeError("Database lifespan is not running.")
        if self._factory is None:
            self._engine = create_engine(get_settings())
            self._factory = create_session_factory(self._engine)
        return self._factory

    async def aclose(self) -> None:
        self._closed = True
        engine, self._engine = self._engine, None
        self._factory = None
        if engine is not None:
            await engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database = getattr(request.app.state, "request_database", None)
    if not isinstance(database, RequestDatabase):
        raise RuntimeError("Database lifespan is not running.")
    async with database.session_factory().begin() as session:
        yield session
