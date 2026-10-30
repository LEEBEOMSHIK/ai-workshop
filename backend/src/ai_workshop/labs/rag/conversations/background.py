"""Process-owned conversation work, independent of HTTP and the API event loop."""

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import AbstractAsyncContextManager
from contextvars import copy_context
from dataclasses import dataclass
from threading import Lock, Thread
from uuid import UUID

from ai_workshop.labs.rag.conversations.schemas import (
    ConversationDetail,
    ConversationStart,
    ConversationTurnCreate,
)
from ai_workshop.labs.rag.conversations.service import ConversationService
from ai_workshop.shared.asyncio_policy import create_selector_event_loop
from ai_workshop.shared.errors import AppError

logger = logging.getLogger(__name__)
ServiceFactory = Callable[[UUID], AbstractAsyncContextManager[ConversationService]]


@dataclass(frozen=True, slots=True)
class _Submission:
    slug: str
    actor_id: UUID
    request: ConversationStart | ConversationTurnCreate
    conversation_id: UUID | None = None


def _unavailable() -> AppError:
    return AppError(
        "conversation_background_unavailable", "Conversation execution is unavailable.", 503,
    )


def _failure() -> AppError:
    return AppError(
        "conversation_background_failed", "Conversation execution could not start.", 503,
    )


def _wrapped[T](future: Future[T]) -> asyncio.Future[T]:
    wrapped = asyncio.wrap_future(future)
    wrapped.add_done_callback(lambda value: None if value.cancelled() else value.exception())
    return wrapped


async def _join[T](future: Future[T]) -> T:
    wrapped = _wrapped(future)
    while not wrapped.done():
        try:
            await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            # Application shutdown must join owned cleanup, even after repeated cancellation.
            continue
    return wrapped.result()


class ConversationBackground:
    """All dependency contexts live in one dedicated loop; only immutable inputs cross it."""

    def __init__(self, factory: ServiceFactory) -> None:
        self._factory = factory
        self._lock = Lock()
        self._closed = False
        self._ready: Future[asyncio.AbstractEventLoop] = Future()
        self._shutdown: Future[None] | None = None
        self._thread: Thread | None = None
        # Accessed only by the worker loop.
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(
        self, slug: str, actor_id: UUID, request: ConversationStart,
    ) -> ConversationDetail:
        return await self._submit(_Submission(slug, actor_id, request.model_copy(deep=True)))

    async def submit(
        self, slug: str, actor_id: UUID, conversation_id: UUID, request: ConversationTurnCreate,
    ) -> ConversationDetail:
        return await self._submit(_Submission(
            slug, actor_id, request.model_copy(deep=True), conversation_id,
        ))

    async def _submit(self, submission: _Submission) -> ConversationDetail:
        accepted: Future[ConversationDetail] = Future()
        context = copy_context()

        def schedule(ready: Future[asyncio.AbstractEventLoop]) -> None:
            try:
                ready.result().call_soon_threadsafe(
                    self._start_job, submission, accepted, context=context,
                )
            except Exception:
                accepted.set_exception(_unavailable())

        with self._lock:
            if self._closed:
                raise _unavailable()
            if self._thread is None:
                self._thread = Thread(target=self._run_loop, name="rag-conversations", daemon=True)
                try:
                    self._thread.start()
                except Exception:
                    self._closed = True
                    self._ready.set_exception(_unavailable())
            # Register ownership before the first await, including cold thread startup.
            self._ready.add_done_callback(schedule)
        # Cancelling a browser waiter never cancels either the acceptance future or its job.
        return await asyncio.shield(_wrapped(accepted))

    def _run_loop(self) -> None:
        try:
            loop = create_selector_event_loop()
        except Exception:
            self._ready.set_exception(_unavailable())
            return
        asyncio.set_event_loop(loop)
        self._ready.set_result(loop)
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def _start_job(
        self, submission: _Submission, accepted: Future[ConversationDetail],
    ) -> None:
        operation = self._run(submission, accepted)
        try:
            task = asyncio.create_task(operation, name="rag-conversation")
        except Exception:
            operation.close()
            accepted.set_exception(_unavailable())
            return
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def _run(
        self, submission: _Submission, accepted: Future[ConversationDetail],
    ) -> None:
        def accept(detail: ConversationDetail) -> None:
            if not accepted.done():
                accepted.set_result(detail.model_copy(deep=True))

        try:
            async with self._factory(submission.actor_id) as service:
                if isinstance(submission.request, ConversationStart):
                    result = await service.start(
                        submission.slug, submission.actor_id, submission.request,
                        on_accepted=accept,
                    )
                else:
                    assert submission.conversation_id is not None
                    result = await service.submit(
                        submission.slug, submission.actor_id, submission.conversation_id,
                        submission.request, on_accepted=accept,
                    )
                accept(result)  # Replay and pre-execution terminal paths have no new reservation.
        except asyncio.CancelledError:
            if not accepted.done():
                accepted.set_exception(_unavailable())
            raise
        except AppError as error:
            if not accepted.done():
                accepted.set_exception(error)
            else:
                logger.error("conversation_background_failed")
        except Exception:
            if not accepted.done():
                accepted.set_exception(_failure())
            logger.error("conversation_background_failed")

    async def _drain(self, finished: Future[None]) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        finished.set_result(None)
        asyncio.get_running_loop().call_soon(asyncio.get_running_loop().stop)

    def _begin_shutdown(self, finished: Future[None]) -> None:
        asyncio.create_task(self._drain(finished), name="rag-conversations-shutdown")

    async def aclose(self) -> None:
        with self._lock:
            self._closed = True
            if self._thread is None:
                return
            first = self._shutdown is None
            if self._shutdown is None:
                self._shutdown = Future()
            finished, thread = self._shutdown, self._thread
        loop = await _join(self._ready)
        if first:
            loop.call_soon_threadsafe(self._begin_shutdown, finished)
        await _join(finished)
        joining = asyncio.create_task(asyncio.to_thread(thread.join))
        while not joining.done():
            try:
                await asyncio.shield(joining)
            except asyncio.CancelledError:
                continue
        joining.result()
