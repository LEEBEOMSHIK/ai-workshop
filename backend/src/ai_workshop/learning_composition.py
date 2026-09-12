from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.evaluation.repository import (
    SqlAlchemyEvaluationApplicationRepository,
)
from ai_workshop.labs.rag.evaluation.service import (
    EvaluationApplicationService,
    EvaluationRunView,
)
from ai_workshop.platform.learning.references import (
    ReferenceResolver,
    ReferenceStatus,
    ReferenceView,
)
from ai_workshop.platform.learning.repository import (
    LearningRepository,
    SqlAlchemyLearningRepository,
)
from ai_workshop.platform.learning.schemas import ReferenceKey
from ai_workshop.platform.learning.service import LearningCursorCodec, LearningService
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError


class ReferenceHandler(Protocol):
    async def resolve(self, actor_id: UUID, key: ReferenceKey) -> ReferenceView: ...


class EvaluationDetailPort(Protocol):
    async def detail(self, run_id: UUID, actor_id: UUID) -> EvaluationRunView: ...


@dataclass(frozen=True, slots=True)
class ServiceReferenceDefinition:
    key: str
    label: str
    href: str | None


SERVICE_REFERENCES = (
    ServiceReferenceDefinition(
        key="rag.search",
        label="RAG search",
        href="/workshop/rag/search",
    ),
)


class LearningReferenceResolver(ReferenceResolver):
    def __init__(self, handlers: Mapping[str, ReferenceHandler]) -> None:
        self._handlers = dict(handlers)

    async def resolve(self, actor_id: UUID, key: ReferenceKey) -> ReferenceView:
        handler = self._handlers.get(key.kind)
        if handler is None:
            return ReferenceView.unavailable()
        return await handler.resolve(actor_id, key)


class LearningRecordReferenceHandler:
    def __init__(self, repository: LearningRepository) -> None:
        self._repository = repository

    async def resolve(self, actor_id: UUID, key: ReferenceKey) -> ReferenceView:
        try:
            record_id = UUID(key.target)
            revision = _optional_positive_revision(key.version)
        except ValueError:
            return ReferenceView.unavailable()
        if revision is None:
            record = await self._repository.get_owned(record_id, actor_id)
        else:
            record = await self._repository.get_revision_owned(
                record_id, revision, actor_id
            )
        if record is None:
            return ReferenceView.unavailable()
        return ReferenceView(
            status=ReferenceStatus.AVAILABLE,
            label=record.draft.title,
            href=f"/workshop/learning/{record.id}",
            key=key,
        )


class ServiceReferenceHandler:
    def __init__(self, definitions: tuple[ServiceReferenceDefinition, ...]) -> None:
        self._definitions = {definition.key: definition for definition in definitions}

    async def resolve(self, actor_id: UUID, key: ReferenceKey) -> ReferenceView:
        del actor_id
        if key.version is not None:
            return ReferenceView.unavailable()
        definition = self._definitions.get(key.target)
        if definition is None:
            return ReferenceView.unavailable()
        return ReferenceView(
            status=ReferenceStatus.AVAILABLE,
            label=definition.label,
            href=definition.href,
            key=key,
        )


class EvaluationReferenceHandler:
    def __init__(self, service: EvaluationDetailPort) -> None:
        self._service = service

    async def resolve(self, actor_id: UUID, key: ReferenceKey) -> ReferenceView:
        if key.version is not None:
            return ReferenceView.unavailable()
        try:
            run_id = UUID(key.target)
        except ValueError:
            return ReferenceView.unavailable()
        try:
            run = await self._service.detail(run_id, actor_id)
        except AppError as exc:
            if exc.code == "not_found" and exc.status_code == 404:
                return ReferenceView.unavailable()
            raise
        return ReferenceView(
            status=ReferenceStatus.AVAILABLE,
            label=f"RAG evaluation · {run.status.value}",
            href=None,
            key=key,
        )


def _optional_positive_revision(value: str | None) -> int | None:
    if value is None:
        return None
    revision = int(value)
    if revision < 1:
        raise ValueError("revision must be positive")
    return revision


def get_learning_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LearningService:
    repository = SqlAlchemyLearningRepository(session)
    evaluation_service = EvaluationApplicationService(
        SqlAlchemyEvaluationApplicationRepository(session)
    )
    resolver = LearningReferenceResolver(
        {
            "learning.record": LearningRecordReferenceHandler(repository),
            "service": ServiceReferenceHandler(SERVICE_REFERENCES),
            "rag.evaluation": EvaluationReferenceHandler(evaluation_service),
        }
    )
    return LearningService(
        repository,
        resolver,
        settings.learning_limits,
        LearningCursorCodec(
            settings.secret_key.get_secret_value(),
            max_length=settings.learning_limits.cursor_max_chars,
        ),
        commit=session.commit,
    )
