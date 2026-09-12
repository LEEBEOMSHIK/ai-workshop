from __future__ import annotations

from dataclasses import replace

import pytest

from ai_workshop.config import PublishingLimits
from ai_workshop.platform.publishing.domain import (
    PublicationAction,
    PublicationCommand,
    PublicationDraft,
)
from ai_workshop.platform.publishing.package import (
    PublicPersona,
    StudyContent,
    StudySnapshot,
    snapshot_digest,
)
from ai_workshop.platform.publishing.public_store import PublicationReceipt
from ai_workshop.platform.publishing.repository import (
    PendingPublicationCommand,
    PreparedPublication,
    PublishingRepository,
    PublishingStudy,
)
from ai_workshop.platform.publishing.service import PublicationDelivery, PublishingService
from ai_workshop.shared.errors import AppError


def content(**changes: object) -> StudyContent:
    values: dict[str, object] = {
        "slug": "example-study",
        "title": "Example study",
        "summary": "A public summary.",
        "topic_keys": ("rag",),
        "body": "Public body text.",
        "verification": "Verified with a deterministic fixture.",
        "limitations": "Synthetic data only.",
        "persona": None,
    }
    values.update(changes)
    return StudyContent.model_validate(values)


class MemoryPublishingRepository(PublishingRepository):
    def __init__(self) -> None:
        self.studies: dict[str, PublishingStudy] = {}
        self.commands: dict[str, PublicationCommand] = {}
        self.command_requests: dict[str, PendingPublicationCommand] = {}
        self.create_calls = 0
        self.get_calls = 0
        self.prepare_calls = 0
        self.initial_prepare_calls = 0

    async def create(self, study_content: StudyContent) -> PublishingStudy:
        self.create_calls += 1
        if study_content.slug in self.studies:
            raise AppError("publishing_slug_conflict", "The public slug already exists.", 409)
        state = PublishingStudy(
            draft=PublicationDraft(StudySnapshot(revision=1, content=study_content))
        )
        self.studies[study_content.slug] = state
        return state

    async def get(self, slug: str) -> PublishingStudy | None:
        self.get_calls += 1
        return self.studies.get(slug)

    async def prepare_initial_publication(
        self,
        study_content: StudyContent,
        *,
        expected_digest: str,
        request_id: str,
    ) -> PreparedPublication:
        self.initial_prepare_calls += 1
        if study_content.slug not in self.studies:
            await self.create(study_content)
        return await self.prepare_command(
            study_content.slug,
            action=PublicationAction.PUBLISH,
            expected_revision=1,
            expected_digest=expected_digest,
            request_id=request_id,
        )

    async def list(self, *, offset: int, limit: int) -> tuple[PublishingStudy, ...]:
        return tuple(self.studies[key] for key in sorted(self.studies))[offset : offset + limit]

    async def update(
        self,
        slug: str,
        *,
        expected_revision: int,
        content: StudyContent,
    ) -> PublishingStudy:
        state = self.studies.get(slug)
        if state is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        updated = replace(
            state,
            draft=state.draft.revise(content, expected_revision=expected_revision),
        )
        self.studies[slug] = updated
        return updated

    async def prepare_command(
        self,
        slug: str,
        *,
        action: PublicationAction,
        expected_revision: int,
        expected_digest: str,
        request_id: str,
    ) -> PreparedPublication:
        self.prepare_calls += 1
        existing = self.commands.get(request_id)
        if existing is not None:
            original = self.command_requests[request_id]
            expected_identity = (
                existing.slug == slug
                and original.action is action
                and original.expected_revision == expected_revision
                and original.expected_digest == expected_digest
            )
            if not expected_identity:
                raise AppError(
                    "publishing_request_conflict",
                    "The publishing request conflicts with an earlier request.",
                    409,
                )
            current = self.studies[existing.slug]
            return PreparedPublication(
                state=current,
                command=existing,
                should_deliver=(
                    current.last_request_id == request_id
                    and current.applied_sequence < existing.sequence
                ),
            )

        state = self.studies.get(slug)
        if state is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        if expected_digest != snapshot_digest(state.draft.snapshot):
            raise AppError("publishing_digest_conflict", "The public package has changed.", 409)
        if action is PublicationAction.PUBLISH:
            approved = state.draft.approve(
                expected_revision=expected_revision,
                expected_digest=expected_digest,
            )
            draft, command = approved.publish(request_id=request_id)
        else:
            if expected_revision != state.draft.snapshot.revision:
                raise AppError("publishing_revision_conflict", "The draft has changed.", 409)
            draft, command = state.draft.withdraw(request_id=request_id)
        pending_command = PendingPublicationCommand(
            action=action,
            expected_revision=expected_revision,
            expected_digest=expected_digest,
            request_id=request_id,
        )
        prepared = replace(
            state,
            draft=draft,
            desired_action=action,
            last_request_id=request_id,
            delivery_error_code=None,
            pending_command=pending_command,
        )
        self.studies[slug] = prepared
        self.commands[request_id] = command
        self.command_requests[request_id] = pending_command
        return PreparedPublication(state=prepared, command=command, should_deliver=True)

    async def acknowledge(self, receipt: PublicationReceipt) -> PublishingStudy:
        command = self.commands[receipt.request_id]
        assert receipt == PublicationReceipt(
            slug=command.slug,
            sequence=command.sequence,
            request_id=command.request_id,
            action=command.action,
        )
        current = self.studies[receipt.slug]
        if receipt.sequence > current.applied_sequence:
            current = replace(
                current,
                applied_sequence=receipt.sequence,
                applied_action=receipt.action,
                applied_revision=(
                    command.snapshot.revision
                    if command.action is PublicationAction.PUBLISH
                    and command.snapshot is not None
                    else None
                ),
                delivery_error_code=None,
                pending_command=None,
            )
            self.studies[receipt.slug] = current
        return current

    async def record_delivery_failure(
        self,
        request_id: str,
        *,
        error_code: str,
    ) -> PublishingStudy:
        command = self.commands[request_id]
        current = self.studies[command.slug]
        if current.last_request_id == request_id:
            current = replace(current, delivery_error_code=error_code)
            self.studies[command.slug] = current
        return current


class MutableDelivery(PublicationDelivery):
    def __init__(self) -> None:
        self.calls: list[PublicationCommand] = []
        self.error: AppError | None = None
        self.manual = False

    async def deliver(self, command: PublicationCommand) -> PublicationReceipt | None:
        self.calls.append(command)
        if self.error is not None:
            raise self.error
        if self.manual:
            return None
        return PublicationReceipt(
            slug=command.slug,
            sequence=command.sequence,
            request_id=command.request_id,
            action=command.action,
        )


def service_for(
    repository: MemoryPublishingRepository,
    delivery: MutableDelivery,
    *,
    personas: tuple[PublicPersona, ...] = (),
    limits: PublishingLimits | None = None,
) -> PublishingService:
    return PublishingService(
        repository,
        delivery,
        approved_personas=personas,
        limits=limits or PublishingLimits(),
    )


@pytest.mark.asyncio
async def test_create_rejects_unregistered_persona_before_persistence() -> None:
    repository = MemoryPublishingRepository()
    service = service_for(
        repository,
        MutableDelivery(),
        personas=(PublicPersona(slug="reviewer", label="Approved reviewer"),),
    )

    with pytest.raises(AppError) as failure:
        await service.create(
            content(persona=PublicPersona(slug="reviewer", label="Account-derived label"))
        )

    assert (failure.value.code, failure.value.status_code) == (
        "publishing_persona_not_approved",
        422,
    )
    assert repository.create_calls == 0


@pytest.mark.asyncio
async def test_create_enforces_aggregate_and_collection_limits_before_persistence() -> None:
    repository = MemoryPublishingRepository()
    service = service_for(
        repository,
        MutableDelivery(),
        limits=PublishingLimits(
            max_collection_items=1,
            aggregate_content_max_bytes=200,
        ),
    )

    for rejected in (
        content(topic_keys=("rag", "retrieval")),
        content(body="x" * 300),
    ):
        with pytest.raises(AppError) as failure:
            await service.create(rejected)
        assert (failure.value.code, failure.value.status_code) == (
            "publishing_invalid_input",
            422,
        )

    assert repository.create_calls == 0


@pytest.mark.asyncio
async def test_publish_acknowledges_exact_receipt_and_returns_applied_state() -> None:
    repository = MemoryPublishingRepository()
    delivery = MutableDelivery()
    service = service_for(repository, delivery)
    created = await service.create(content())

    published = await service.publish(
        "example-study",
        expected_revision=created.snapshot.revision,
        expected_digest=created.digest,
        request_id="publish-one",
    )

    assert len(delivery.calls) == 1
    assert published.desired_action is PublicationAction.PUBLISH
    assert published.applied_sequence == published.sequence == 1
    assert published.applied_action is PublicationAction.PUBLISH
    assert published.applied_revision == 1
    assert published.delivery_pending is False
    assert published.delivery_error_code is None


@pytest.mark.asyncio
async def test_initial_publication_uses_repository_guard_and_delivery_flow() -> None:
    repository = MemoryPublishingRepository()
    delivery = MutableDelivery()
    service = service_for(repository, delivery)
    initial_content = content()
    digest = snapshot_digest(StudySnapshot(revision=1, content=initial_content))

    published = await service.publish_initial(
        initial_content,
        expected_digest=digest,
        request_id="initial-reviewed-example-study",
    )

    assert repository.initial_prepare_calls == 1
    assert repository.create_calls == 1
    assert [command.sequence for command in delivery.calls] == [1]
    assert published.applied_action is PublicationAction.PUBLISH
    assert published.applied_revision == 1


@pytest.mark.asyncio
async def test_failed_delivery_is_durable_and_same_request_retries_same_command() -> None:
    repository = MemoryPublishingRepository()
    delivery = MutableDelivery()
    delivery.error = AppError(
        "publishing_store_unavailable",
        "The public study store is unavailable.",
        503,
    )
    service = service_for(repository, delivery)
    created = await service.create(content())

    pending = await service.publish(
        "example-study",
        expected_revision=1,
        expected_digest=created.digest,
        request_id="publish-one",
    )
    assert pending.sequence == 1
    assert pending.applied_sequence == 0
    assert pending.delivery_pending is True
    assert pending.delivery_error_code == "publishing_store_unavailable"
    assert pending.pending_command is not None
    assert pending.pending_command.action is PublicationAction.PUBLISH
    assert pending.pending_command.expected_revision == 1
    assert pending.pending_command.expected_digest == created.digest
    assert pending.pending_command.request_id == "publish-one"

    delivery.error = None
    retried = await service.publish(
        "example-study",
        expected_revision=1,
        expected_digest=created.digest,
        request_id="publish-one",
    )

    assert [command.sequence for command in delivery.calls] == [1, 1]
    assert retried.sequence == 1
    assert retried.applied_sequence == 1
    assert retried.delivery_pending is False
    assert retried.pending_command is None


@pytest.mark.asyncio
async def test_replay_of_superseded_request_returns_current_state_without_delivery() -> None:
    repository = MemoryPublishingRepository()
    delivery = MutableDelivery()
    delivery.error = AppError("publishing_store_unavailable", "Unavailable.", 503)
    service = service_for(repository, delivery)
    created = await service.create(content())
    await service.publish(
        "example-study",
        expected_revision=1,
        expected_digest=created.digest,
        request_id="publish-one",
    )
    delivery.error = None
    withdrawn = await service.withdraw(
        "example-study",
        expected_revision=1,
        expected_digest=created.digest,
        request_id="withdraw-two",
    )
    call_count = len(delivery.calls)

    replay = await service.publish(
        "example-study",
        expected_revision=1,
        expected_digest=created.digest,
        request_id="publish-one",
    )

    assert len(delivery.calls) == call_count
    assert replay.sequence == withdrawn.sequence == 2
    assert replay.desired_action is PublicationAction.WITHDRAW
    assert replay.applied_action is PublicationAction.WITHDRAW
    assert replay.delivery_pending is False
    assert replay.last_request_id == "withdraw-two"


@pytest.mark.asyncio
async def test_manual_delivery_queues_without_claiming_public_application() -> None:
    repository = MemoryPublishingRepository()
    delivery = MutableDelivery()
    delivery.manual = True
    service = service_for(repository, delivery)
    created = await service.create(content())

    pending = await service.publish(
        "example-study",
        expected_revision=1,
        expected_digest=created.digest,
        request_id="manual-publish",
    )

    assert pending.sequence == 1
    assert pending.applied_sequence == 0
    assert pending.delivery_pending is True
    assert pending.delivery_error_code == "publishing_manual_delivery_pending"
    assert pending.pending_command is not None
    assert pending.pending_command.request_id == "manual-publish"


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", [f"request-{chr(0xD800)}", "request-\x00id"])
async def test_invalid_request_id_is_rejected_before_repository_io(
    request_id: str,
) -> None:
    repository = MemoryPublishingRepository()
    service = service_for(repository, MutableDelivery())
    created = await service.create(content())

    with pytest.raises(AppError) as failure:
        await service.publish(
            "example-study",
            expected_revision=1,
            expected_digest=created.digest,
            request_id=request_id,
        )

    assert (failure.value.code, failure.value.status_code) == (
        "publishing_invalid_input",
        422,
    )
    assert repository.prepare_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", [f"study-{chr(0xD800)}", "study-\x00slug", "../private"])
async def test_invalid_admin_slug_is_safe_not_found_before_repository_io(slug: str) -> None:
    repository = MemoryPublishingRepository()
    service = service_for(repository, MutableDelivery())

    with pytest.raises(AppError) as failure:
        await service.detail(slug)

    assert (failure.value.code, failure.value.status_code) == ("not_found", 404)
    assert repository.get_calls == 0


@pytest.mark.asyncio
async def test_valid_non_bmp_request_id_remains_supported() -> None:
    repository = MemoryPublishingRepository()
    service = service_for(repository, MutableDelivery())
    created = await service.create(content())

    published = await service.publish(
        "example-study",
        expected_revision=1,
        expected_digest=created.digest,
        request_id="publish-emoji-한",
    )

    assert published.last_request_id == "publish-emoji-한"
    assert published.delivery_pending is False


@pytest.mark.asyncio
async def test_create_rejects_slug_over_storage_capacity_before_repository_io() -> None:
    repository = MemoryPublishingRepository()
    service = service_for(repository, MutableDelivery())

    with pytest.raises(AppError) as failure:
        await service.create(content(slug="s" * 201))

    assert (failure.value.code, failure.value.status_code) == (
        "publishing_invalid_input",
        422,
    )
    assert repository.create_calls == 0


@pytest.mark.asyncio
async def test_detail_rejects_slug_over_storage_capacity_before_repository_io() -> None:
    repository = MemoryPublishingRepository()
    service = service_for(repository, MutableDelivery())

    with pytest.raises(AppError) as failure:
        await service.detail("s" * 201)

    assert (failure.value.code, failure.value.status_code) == ("not_found", 404)
    assert repository.get_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"title": "title\x00marker"},
        {"summary": "summary\x00marker"},
        {"body": "body\x00marker"},
        {"verification": "verification\x00marker"},
        {"limitations": "limitations\x00marker"},
    ],
)
async def test_create_rejects_nul_content_before_repository_io(
    changes: dict[str, object],
) -> None:
    repository = MemoryPublishingRepository()
    service = service_for(repository, MutableDelivery())

    with pytest.raises(AppError) as failure:
        await service.create(content(**changes))

    assert (failure.value.code, failure.value.status_code) == (
        "publishing_invalid_input",
        422,
    )
    assert repository.create_calls == 0


@pytest.mark.asyncio
async def test_create_rejects_nul_persona_label_before_repository_io() -> None:
    persona = PublicPersona(slug="reviewer", label="reviewer\x00marker")
    repository = MemoryPublishingRepository()
    service = service_for(repository, MutableDelivery(), personas=(persona,))

    with pytest.raises(AppError) as failure:
        await service.create(content(persona=persona))

    assert (failure.value.code, failure.value.status_code) == (
        "publishing_invalid_input",
        422,
    )
    assert repository.create_calls == 0
