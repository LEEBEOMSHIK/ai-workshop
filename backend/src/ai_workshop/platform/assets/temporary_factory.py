"""Production composition; absence of tracking never enables OS temp fallback."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.config import Settings
from ai_workshop.platform.assets.temporary_contracts import TemporaryBinding, TemporaryContext
from ai_workshop.platform.assets.temporary_service import TemporaryLease, TemporaryWorkspaceService
from ai_workshop.shared.errors import AppError


def create_temporary_service(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
) -> TemporaryWorkspaceService:
    if (
        settings.temporary_store_root is None
        or settings.temporary_store_id is None
        or settings.temporary_store_binding_id is None
    ):
        raise AppError("temporary_storage_unavailable", "Temporary storage is not ready.", 503)
    from ai_workshop.infrastructure.object_store.temporary import TrackedTemporaryStore
    from ai_workshop.platform.assets.temporary_repository import TemporaryJournal

    return TemporaryWorkspaceService(
        TemporaryJournal(sessions),
        TrackedTemporaryStore(
            settings.temporary_store_root,
            TemporaryBinding(settings.temporary_store_id, settings.temporary_store_binding_id),
        ),
    )


class ConfiguredTemporaryService:
    """Defers configuration checks until a request actually needs temporary bytes."""

    def __init__(self, settings: Settings, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.settings = settings
        self.sessions = sessions

    async def open(
        self,
        context: TemporaryContext,
        purpose: str,
        *,
        coverage: str = "runtime_unverified",
    ) -> TemporaryLease:
        return await create_temporary_service(self.settings, self.sessions).open(
            context,
            purpose,
            coverage=coverage,
        )
