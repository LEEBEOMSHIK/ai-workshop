"""Startup and writer admission compare independent DB, private and live identities."""

from collections.abc import Awaitable, Callable

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.access_credentials import (
    AccessCredentialError,
    SecuredStoreIdentity,
)

type FloorLoader = Callable[[Settings], Awaitable[tuple[SecuredStoreIdentity | None, bool]]]
type AnchorLoader = Callable[[], SecuredStoreIdentity | None]
type SecuredProbe = Callable[[Settings], Awaitable[SecuredStoreIdentity]]


class AccessEpochAdmission:
    def __init__(self, load: FloorLoader, anchor: AnchorLoader, probe: SecuredProbe) -> None:
        self.load, self.anchor, self.probe = load, anchor, probe

    async def verify(
        self, settings: Settings, *, writer: bool = False, non_es: bool = False
    ) -> None:
        try:
            floor, active = await self.load(settings)
            anchor = self.anchor()
            if floor is None and anchor is None:
                if active or settings.elasticsearch_access_epoch_id is not None:
                    raise AccessCredentialError("access_epoch_mismatch")
                return
            if floor is None or floor != anchor or active:
                raise AccessCredentialError("access_epoch_mismatch")
            if (
                settings.elasticsearch_access_epoch_id != floor.epoch_id
                or settings.elasticsearch_access_epoch != floor.ordinal
                or not settings.elasticsearch_url.startswith("https://")
                or settings.elasticsearch_ca_certs is None
            ):
                raise AccessCredentialError("access_epoch_mismatch")
            if non_es:
                if (
                    settings.elasticsearch_api_key is not None
                    or settings.elasticsearch_role is not None
                ):
                    raise AccessCredentialError("access_epoch_mismatch")
                return
            if settings.elasticsearch_api_key is None or settings.elasticsearch_role is None:
                raise AccessCredentialError("elasticsearch_capability_required")
            if writer and settings.elasticsearch_role != "writer":
                raise AccessCredentialError("elasticsearch_capability_required")
            if await self.probe(settings) != floor:
                raise AccessCredentialError("access_epoch_mismatch")
        except AccessCredentialError:
            raise
        except Exception:
            raise AccessCredentialError("access_epoch_mismatch") from None
