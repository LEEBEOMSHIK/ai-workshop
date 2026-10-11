"""HTTP search session supports durable audit commits and later authority checks."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import get_settings
from ai_workshop.shared.db import create_engine, create_session_factory


async def get_search_session() -> AsyncIterator[AsyncSession]:
    engine = create_engine(get_settings())
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            try:
                # Audit commits are durable before the final source ACL query.
                # A begin() context would prohibit that query after audit commit.
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
    finally:
        await engine.dispose()
