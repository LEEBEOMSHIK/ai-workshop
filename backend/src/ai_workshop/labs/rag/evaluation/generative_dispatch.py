from datetime import UTC, datetime, timedelta
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.config import Settings
from ai_workshop.labs.rag.evaluation.generative_models import GenerativeRunRecord
from ai_workshop.labs.rag.evaluation.generative_repository import GenerativeRepository
from ai_workshop.labs.rag.evaluation.generative_workflow import GenerativeWorkflow
from ai_workshop.shared.db import create_engine, create_session_factory


async def dispatch_pending(sessions: async_sessionmaker[AsyncSession], celery: Celery) -> None:
    now = datetime.now(UTC)
    await GenerativeRepository(sessions).interrupt_stale(now - timedelta(minutes=10))
    async with sessions.begin() as session:
        rows = (
            await session.scalars(
                select(GenerativeRunRecord)
                .where(
                    GenerativeRunRecord.status == "pending",
                    or_(
                        GenerativeRunRecord.dispatched_at.is_(None),
                        GenerativeRunRecord.dispatched_at < now - timedelta(minutes=2),
                    ),
                )
                .with_for_update(skip_locked=True)
                .limit(5)
            )
        ).all()
        ids = [r.id for r in rows]
        for row in rows:
            row.dispatched_at = now
    for id in ids:
        # Delivery failures leave pending work durable and eligible after the backoff.
        celery.send_task("ai_workshop.rag.evaluate_generative_run", args=[str(id)])


async def execute_run(settings: Settings, id: UUID) -> None:
    engine = create_engine(settings)
    try:
        await GenerativeWorkflow(create_session_factory(engine), settings).run(id)
    finally:
        await engine.dispose()
