from __future__ import annotations

import json
import re
from typing import Protocol

from ai_workshop.config import PublishingLimits
from ai_workshop.platform.publishing.domain import PublicationAction, PublicationCommand
from ai_workshop.platform.publishing.package import PublicPersona, StudyContent
from ai_workshop.platform.publishing.public_store import PublicationReceipt
from ai_workshop.platform.publishing.repository import (
    PreparedPublication,
    PublishingRepository,
    PublishingStudy,
)
from ai_workshop.shared.errors import AppError

_PUBLIC_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_STORAGE_SLUG_MAX_CHARS = 200


class PublicationDelivery(Protocol):
    async def deliver(self, command: PublicationCommand) -> PublicationReceipt | None: ...


class PublishingService:
    def __init__(
        self,
        repository: PublishingRepository,
        delivery: PublicationDelivery,
        *,
        approved_personas: tuple[PublicPersona, ...],
        limits: PublishingLimits,
    ) -> None:
        self.repository = repository
        self.delivery = delivery
        self.approved_personas = approved_personas
        self.limits = limits

    @property
    def default_page_limit(self) -> int:
        return self.limits.page_default

    async def create(self, content: StudyContent) -> PublishingStudy:
        self._validate_content(content)
        return await self.repository.create(content)

    async def detail(self, slug: str) -> PublishingStudy:
        self._require_public_slug(slug)
        state = await self.repository.get(slug)
        if state is None:
            raise _not_found()
        return state

    async def list(self, *, offset: int, limit: int) -> tuple[PublishingStudy, ...]:
        if offset < 0 or limit < 1 or limit > self.limits.page_max:
            raise _invalid_input()
        return await self.repository.list(offset=offset, limit=limit)

    async def update(
        self,
        slug: str,
        *,
        expected_revision: int,
        content: StudyContent,
    ) -> PublishingStudy:
        self._require_public_slug(slug)
        self._validate_content(content)
        return await self.repository.update(
            slug,
            expected_revision=expected_revision,
            content=content,
        )

    async def publish(
        self,
        slug: str,
        *,
        expected_revision: int,
        expected_digest: str,
        request_id: str,
    ) -> PublishingStudy:
        return await self._execute(
            slug,
            action=PublicationAction.PUBLISH,
            expected_revision=expected_revision,
            expected_digest=expected_digest,
            request_id=request_id,
        )

    async def publish_initial(
        self,
        content: StudyContent,
        *,
        expected_digest: str,
        request_id: str,
    ) -> PublishingStudy:
        self._validate_content(content)
        self._validate_command_input(
            expected_digest=expected_digest,
            request_id=request_id,
        )
        prepared = await self.repository.prepare_initial_publication(
            content,
            expected_digest=expected_digest,
            request_id=request_id,
        )
        return await self._deliver_prepared(prepared)

    async def withdraw(
        self,
        slug: str,
        *,
        expected_revision: int,
        expected_digest: str,
        request_id: str,
    ) -> PublishingStudy:
        return await self._execute(
            slug,
            action=PublicationAction.WITHDRAW,
            expected_revision=expected_revision,
            expected_digest=expected_digest,
            request_id=request_id,
        )

    async def _execute(
        self,
        slug: str,
        *,
        action: PublicationAction,
        expected_revision: int,
        expected_digest: str,
        request_id: str,
    ) -> PublishingStudy:
        self._require_public_slug(slug)
        self._validate_command_input(
            expected_digest=expected_digest,
            request_id=request_id,
        )
        prepared = await self.repository.prepare_command(
            slug,
            action=action,
            expected_revision=expected_revision,
            expected_digest=expected_digest,
            request_id=request_id,
        )
        return await self._deliver_prepared(prepared)

    def _validate_command_input(
        self,
        *,
        expected_digest: str,
        request_id: str,
    ) -> None:
        if (
            not isinstance(request_id, str)
            or not request_id.strip()
            or len(request_id) > self.limits.request_id_max_chars
            or "\x00" in request_id
        ):
            raise _invalid_input()
        try:
            request_id.encode("utf-8")
        except UnicodeEncodeError:
            raise _invalid_input() from None
        if not isinstance(expected_digest, str) or _DIGEST.fullmatch(expected_digest) is None:
            raise _invalid_input()

    async def _deliver_prepared(
        self,
        prepared: PreparedPublication,
    ) -> PublishingStudy:
        if not prepared.should_deliver:
            return prepared.state
        try:
            receipt = await self.delivery.deliver(prepared.command)
        except AppError as exc:
            return await self.repository.record_delivery_failure(
                prepared.command.request_id,
                error_code=exc.code,
            )
        except Exception:
            return await self.repository.record_delivery_failure(
                prepared.command.request_id,
                error_code="publishing_delivery_failed",
            )
        if receipt is None:
            return await self.repository.record_delivery_failure(
                prepared.command.request_id,
                error_code="publishing_manual_delivery_pending",
            )
        return await self.repository.acknowledge(receipt)

    def _validate_content(self, content: StudyContent) -> None:
        if len(content.slug) > _STORAGE_SLUG_MAX_CHARS:
            raise _invalid_input()
        if content.persona is not None and content.persona not in self.approved_personas:
            raise AppError(
                "publishing_persona_not_approved",
                "The public persona is not approved.",
                422,
            )
        if len(content.title) > self.limits.title_max_chars:
            raise _invalid_input()
        for value in (
            content.summary,
            content.body,
            content.verification,
            content.limitations,
        ):
            if len(value) > self.limits.text_field_max_chars:
                raise _invalid_input()
        if len(content.topic_keys) > self.limits.max_collection_items:
            raise _invalid_input()
        persisted_strings = (
            content.slug,
            content.title,
            content.summary,
            *content.topic_keys,
            content.body,
            content.verification,
            content.limitations,
        )
        if content.persona is not None:
            persisted_strings += (content.persona.slug, content.persona.label)
        if any("\x00" in value for value in persisted_strings):
            raise _invalid_input()
        encoded = json.dumps(
            content.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(encoded) > self.limits.aggregate_content_max_bytes:
            raise _invalid_input()

    @staticmethod
    def _require_public_slug(slug: str) -> None:
        if (
            not isinstance(slug, str)
            or len(slug) > _STORAGE_SLUG_MAX_CHARS
            or _PUBLIC_SLUG.fullmatch(slug) is None
        ):
            raise _not_found()


def _invalid_input() -> AppError:
    return AppError("publishing_invalid_input", "The publishing request is invalid.", 422)


def _not_found() -> AppError:
    return AppError("not_found", "The requested resource was not found.", 404)
