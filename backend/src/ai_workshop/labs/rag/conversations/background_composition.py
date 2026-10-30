"""Assemble fresh worker-loop resources while borrowing the app's single model host."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from uuid import UUID

from ai_workshop.config import Settings
from ai_workshop.labs.rag.conversations.service import ConversationService
from ai_workshop.labs.rag.domains.api import DomainSearchExecutor
from ai_workshop.labs.rag.domains.repository import (
    SqlAlchemyDomainConfigurationProvider,
    SqlAlchemyDomainRepository,
    SqlAlchemyDomainSearchConfigurationResolver,
)
from ai_workshop.labs.rag.domains.service import DomainService
from ai_workshop.labs.rag.generation.codex_composition import codex_services
from ai_workshop.labs.rag.generation.local_model_host import LocalModelHost
from ai_workshop.labs.rag.search.api import get_search_configuration_resolver, get_search_service
from ai_workshop.shared.db import create_engine, create_session_factory


@asynccontextmanager
async def background_conversation_service(
    settings: Settings, actor_id: UUID, local_model_host: LocalModelHost,
) -> AsyncIterator[ConversationService]:
    # Import at composition time: the HTTP module also exposes the runtime dependency.
    from ai_workshop.labs.rag.conversations.api import get_conversation_service

    async with AsyncExitStack() as stack:
        engine = create_engine(settings)
        stack.push_async_callback(engine.dispose)
        sessions = create_session_factory(engine)
        domain_session = await stack.enter_async_context(sessions.begin())
        search_session = await stack.enter_async_context(sessions())
        domains = DomainService(
            SqlAlchemyDomainRepository(domain_session),
            SqlAlchemyDomainConfigurationProvider(domain_session, settings, actor_id=actor_id),
        )
        codex = await stack.enter_async_context(codex_services(settings))
        search = await stack.enter_async_context(asynccontextmanager(get_search_service)(
            search_session, settings, get_search_configuration_resolver(search_session, settings),
            codex, local_model_host,
        ))
        executor = DomainSearchExecutor(
            domains, SqlAlchemyDomainSearchConfigurationResolver(domain_session, settings), search,
        )
        service = await stack.enter_async_context(asynccontextmanager(get_conversation_service)(
            settings, domains, executor,
        ))
        # Match HTTP search-session semantics: durable audit commits permit subsequent ACL reads.
        try:
            yield service
            await search_session.commit()
        except BaseException:
            await search_session.rollback()
            raise
