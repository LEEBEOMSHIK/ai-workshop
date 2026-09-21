from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from ai_workshop.labs.rag.conversations.domain import Conversation, Turn, reserve_turn
from ai_workshop.labs.rag.conversations.schemas import (
    ConversationDetail,
    ConversationSummary,
    ConversationTurnCreate,
    ConversationTurnResponse,
    RequestScope,
)
from ai_workshop.labs.rag.domains.api import DomainSearchExecutorPort
from ai_workshop.labs.rag.domains.schemas import DomainSearchRequest, DomainSearchResponse
from ai_workshop.labs.rag.domains.service import DomainService
from ai_workshop.labs.rag.search.schemas import ConversationTurnRequest
from ai_workshop.shared.errors import AppError


class ConversationRepository(Protocol):
    async def domain_id(self, slug: str) -> UUID: ...
    async def create(self, item: Conversation) -> None: ...
    async def list(self, owner_id: UUID, domain_id: UUID) -> list[Conversation]: ...

    async def record_termination(
        self,
        owner_id: UUID,
        domain_id: UUID,
        id: UUID,
        turn_id: UUID,
    ) -> None: ...
    def locked(
        self, owner_id: UUID, domain_id: UUID, id: UUID
    ) -> AbstractAsyncContextManager[Conversation]: ...


class ConversationAccessPort(Protocol):
    async def identity(self, actor_id: UUID, request: ConversationTurnCreate) -> str: ...
    async def visible(self, actor_id: UUID, turn: Turn, *, external: bool = False) -> bool: ...


class ConversationService:
    def __init__(
        self,
        repository: ConversationRepository,
        access: ConversationAccessPort,
        domains: DomainService,
        executor: DomainSearchExecutorPort,
    ) -> None:
        self.repository, self.access, self.domains, self.executor = (
            repository,
            access,
            domains,
            executor,
        )

    async def create(self, slug: str, actor_id: UUID, title: str | None) -> ConversationDetail:
        await self.domains.detail_for_actor(slug, actor_id)
        domain_id = await self.repository.domain_id(slug)
        now = datetime.now(UTC)
        item = Conversation(
            uuid4(), actor_id, domain_id, title or f"새 대화 {now:%Y-%m-%d %H:%M}", 1, now, now
        )
        await self.repository.create(item)
        return await self._view(item)

    async def list_for_actor(self, slug: str, actor_id: UUID) -> list[ConversationSummary]:
        domain_id = await self.repository.domain_id(slug)
        return [self._summary(item) for item in await self.repository.list(actor_id, domain_id)]

    async def detail(self, slug: str, actor_id: UUID, id: UUID) -> ConversationDetail:
        domain_id = await self.repository.domain_id(slug)
        async with self.repository.locked(actor_id, domain_id, id) as item:
            item.recover(datetime.now(UTC))
        return await self._view(item)

    async def rename(
        self, slug: str, actor_id: UUID, id: UUID, title: str, revision: int
    ) -> ConversationDetail:
        domain_id = await self.repository.domain_id(slug)
        async with self.repository.locked(actor_id, domain_id, id) as item:
            item.require_revision(revision)
            item.title = title
            item.touch(datetime.now(UTC))
        return await self._view(item)

    async def delete(self, slug: str, actor_id: UUID, id: UUID, revision: int) -> None:
        domain_id = await self.repository.domain_id(slug)
        async with self.repository.locked(actor_id, domain_id, id) as item:
            item.require_revision(revision)
            now = datetime.now(UTC)
            item.deleted_at = now
            for turn in item.turns:
                if turn.status == "running":
                    turn.status, turn.updated_at = "cancelled", now
                    turn.error_code = "conversation_deleted"
                # Tombstone retains ownership/replay metadata, not conversation bodies.
                turn.query, turn.response, turn.request = "", None, {}
            item.title = "Deleted conversation"
            item.touch(now)

    async def cancel(
        self, slug: str, actor_id: UUID, id: UUID, request_id: UUID
    ) -> ConversationDetail:
        domain_id = await self.repository.domain_id(slug)
        async with self.repository.locked(actor_id, domain_id, id) as item:
            target = next((turn for turn in item.turns if turn.request_id == request_id), None)
            if target is None:
                raise AppError("not_found", "The requested turn was not found.", 404)
            if target.status == "running":
                target.status, target.error_code = "cancelled", "conversation_cancelled"
                target.updated_at = datetime.now(UTC)
                item.touch(target.updated_at)
        return await self._view(item)

    async def submit(
        self, slug: str, actor_id: UUID, id: UUID, request: ConversationTurnCreate
    ) -> ConversationDetail:
        domain_id = await self.repository.domain_id(slug)
        # Replay is checked before current scope validation: it never triggers another call.
        async with self.repository.locked(actor_id, domain_id, id) as item:
            item.recover(datetime.now(UTC))
            existing = next(
                (turn for turn in item.turns if turn.request_id == request.request_id), None
            )
            if existing is not None:
                reserve_turn(item, request, existing.scope_identity, datetime.now(UTC))
        if existing is not None:
            return await self._view(item)
        await self.domains.resolve_search(
            slug=slug,
            actor_id=actor_id,
            connection_version_id=request.connection_version_id,
            workspace_ids=tuple(request.workspace_ids),
            folder_ids=tuple(request.folder_ids),
            document_ids=tuple(request.document_ids) if request.document_ids is not None else None,
        )
        identity = await self.access.identity(actor_id, request)
        async with self.repository.locked(actor_id, domain_id, id) as item:
            turn, created = reserve_turn(item, request, identity, datetime.now(UTC))
        if not created:
            return await self._view(item)
        task: asyncio.Task[DomainSearchResponse] | None = None
        result: DomainSearchResponse | None = None
        error: str | None = None
        cancelled = False
        try:
            history, dependencies = await self._history(item, turn, request)
            async with self.repository.locked(actor_id, domain_id, id) as current:
                target = next(value for value in current.turns if value.id == turn.id)
                if target.status != "running":
                    target.execution_terminated = True
                    target.updated_at = datetime.now(UTC)
                    current.touch(target.updated_at)
                    return await self._view(current)
                target.dependencies = dependencies
            data = request.model_dump(exclude={"request_id", "expected_revision"})
            if data.get("document_ids") is None:
                data.pop("document_ids", None)
            data["history"] = history
            task = asyncio.create_task(
                self.executor.execute(
                    slug=slug,
                    actor_id=actor_id,
                    request=DomainSearchRequest.model_validate(data),
                )
            )
            while not task.done():
                done, _ = await asyncio.wait({task}, timeout=0.5)
                if done:
                    break
                async with self.repository.locked(actor_id, domain_id, id) as current:
                    target = next(value for value in current.turns if value.id == turn.id)
                    if target.status != "running":
                        cancelled = True
                        task.cancel()
                        break
            result = await task
        except asyncio.CancelledError:
            cancelled = True
        except AppError as exc:
            error = exc.code
        except Exception:
            # Never persist provider exception messages or private tracebacks.
            error = "conversation_execution_failed"
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        try:
            async with self.repository.locked(actor_id, domain_id, id) as current:
                target = next(value for value in current.turns if value.id == turn.id)
                target.execution_terminated = True
                if target.status == "running":
                    target.status = "cancelled" if cancelled else "failed" if error else "completed"
                    target.error_code = "conversation_cancelled" if cancelled else error
                    target.response = result.model_dump(mode="json") if result is not None else None
                target.updated_at = datetime.now(UTC)
                current.touch(target.updated_at)
        except AppError as exc:
            if exc.status_code == 404:
                await self.repository.record_termination(actor_id, domain_id, id, turn.id)
                raise AppError("not_found", "The conversation was deleted.", 404) from None
            raise
        return await self._view(current)

    async def _history(
        self, item: Conversation, current: Turn, request: ConversationTurnCreate
    ) -> tuple[list[ConversationTurnRequest], list[UUID]]:
        visible = await self._visible_turns(item, external=request.codex_input_approval is not None)
        history: list[ConversationTurnRequest] = []
        dependencies: list[UUID] = []
        for turn in item.turns:
            if turn.id == current.id or turn.segment != current.segment or not visible[turn.id]:
                continue
            if turn.status != "completed" or turn.response is None:
                continue
            approval = turn.request.get("codex_input_approval")
            if request.codex_input_approval is not None and (
                not isinstance(approval, dict)
                or approval.get("consented") is not True
                or approval.get("classification") not in {"public", "synthetic"}
                or approval.get("disclosure_version")
                != request.codex_input_approval.disclosure_version
            ):
                continue
            response = DomainSearchResponse.model_validate(turn.response)
            generation = response.generation
            if (
                generation.status != "answered"
                or not generation.text
                or not generation.validation_token
            ):
                continue
            history.extend(
                [
                    ConversationTurnRequest(role="user", content=turn.query),
                    ConversationTurnRequest(
                        role="assistant",
                        content=generation.text,
                        turn_id=generation.turn_id,
                        validation_token=generation.validation_token,
                    ),
                ]
            )
            dependencies.append(turn.id)
        return history[-20:], dependencies[-10:]

    async def _visible_turns(
        self, item: Conversation, *, external: bool = False
    ) -> dict[UUID, bool]:
        visible: dict[UUID, bool] = {}
        for turn in item.turns:
            approval = turn.request.get("codex_input_approval")
            if external and (
                not isinstance(approval, dict)
                or approval.get("consented") is not True
                or approval.get("classification") not in {"public", "synthetic"}
            ):
                visible[turn.id] = False
                continue
            visible[turn.id] = all(
                visible.get(id, False) for id in turn.dependencies
            ) and await self.access.visible(
                item.owner_id,
                turn,
                external=external,
            )
        return visible

    async def _view(self, item: Conversation) -> ConversationDetail:
        visible = await self._visible_turns(item)
        turns = []
        for turn in item.turns:
            allowed = visible[turn.id]
            turns.append(
                ConversationTurnResponse(
                    id=turn.id,
                    request_id=turn.request_id,
                    sequence=turn.sequence,
                    status=turn.status,
                    query=turn.query if allowed else "",
                    response=(
                        DomainSearchResponse.model_validate(turn.response)
                        if allowed and turn.response
                        else None
                    ),
                    request_scope=RequestScope.model_validate(turn.request) if allowed else None,
                    segment=turn.segment,
                    error_code=turn.error_code if allowed else "conversation_source_unavailable",
                    redacted=not allowed,
                    created_at=turn.created_at,
                    updated_at=turn.updated_at,
                    execution_terminated=turn.execution_terminated,
                )
            )
        return ConversationDetail(**self._summary(item).model_dump(), turns=turns)

    @staticmethod
    def _summary(item: Conversation) -> ConversationSummary:
        return ConversationSummary(
            id=item.id,
            title=item.title,
            revision=item.revision,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
