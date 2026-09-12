from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.identity.authorization import (
    TechnologyDefinition,
    TechnologyRegistry,
)
from ai_workshop.platform.identity.authorization_repository import (
    SqlAlchemyAuthorizationRepository,
)
from ai_workshop.platform.identity.authorization_service import AuthorizationService
from ai_workshop.shared.db import get_session

TECHNOLOGY_REGISTRY = TechnologyRegistry((TechnologyDefinition(key="rag", label="RAG"),))


def get_authorization_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthorizationService:
    return AuthorizationService(
        SqlAlchemyAuthorizationRepository(session),
        TECHNOLOGY_REGISTRY,
    )
