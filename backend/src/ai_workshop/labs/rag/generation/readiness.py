from collections.abc import Mapping
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings
from ai_workshop.labs.rag.configurations.repository import (
    SqlAlchemyRagConfigurationRepository,
)
from ai_workshop.labs.rag.generation.openai_compatible import LocalOpenAICompatibleRuntime
from ai_workshop.labs.rag.generation.profile import resolve_generation_profile
from ai_workshop.labs.rag.models.domain import (
    JsonValue,
    ModelDefinition,
    ModelKind,
    freeze_json,
)
from ai_workshop.labs.rag.models.models import ModelDefinitionRecord


class SqlAlchemyGenerationReadiness:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.profiles = SqlAlchemyRagConfigurationRepository(session)

    async def is_ready(self, profile_id: UUID) -> bool:
        if self.settings.generation_base_url is None:
            return False
        profile = await self.profiles.find_profile(profile_id)
        if profile is None:
            return False
        llm_bindings = tuple(
            item for item in profile.bindings if item.role is ModelKind.LLM
        )
        if len(llm_bindings) != 1:
            return False
        record = await self.session.get(ModelDefinitionRecord, llm_bindings[0].model_id)
        if record is None:
            return False
        frozen_config = freeze_json(cast(JsonValue, record.config))
        if not isinstance(frozen_config, Mapping):
            return False
        model = ModelDefinition(
            id=record.id,
            kind=ModelKind(record.kind),
            name=record.name,
            version=record.version,
            config=frozen_config,
        )
        try:
            resolved = resolve_generation_profile(profile, model)
            runtime = LocalOpenAICompatibleRuntime(
                base_url=self.settings.generation_base_url,
                api_key=(
                    self.settings.generation_api_key.get_secret_value()
                    if self.settings.generation_api_key is not None
                    else None
                ),
            )
        except ValueError:
            return False
        return await runtime.health(resolved)
