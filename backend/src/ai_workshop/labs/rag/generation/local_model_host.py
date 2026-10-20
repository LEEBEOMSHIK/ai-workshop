"""Process-owned local model cache and termination-aware single-worker admission."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_workshop.labs.rag.generation.execution import GenerationProviderError


class LocalModelSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    revision: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    snapshot_path: Path
    device: Literal["cpu"] = "cpu"
    dtype: Literal["float32", "bfloat16"] = "float32"
    max_input_tokens: int = Field(gt=0)

    @field_validator("snapshot_path")
    @classmethod
    def absolute_snapshot(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("A local model requires an absolute snapshot directory.")
        return value


@dataclass(frozen=True, slots=True)
class LocalModelOutput:
    text: str
    input_tokens: int
    output_tokens: int
    truncated: bool = False


class LocalModelEngine(Protocol):
    def generate(
        self, *, system_prompt: str, user_content: str, max_output_tokens: int,
        temperature: float, stop: Event, deadline: float,
    ) -> LocalModelOutput: ...


def _load_default_engine(spec: LocalModelSpec) -> LocalModelEngine:
    # Keep optional native dependencies out of API import/startup and mock tests.
    from ai_workshop.labs.rag.generation.local_transformers import TransformersEngine

    return TransformersEngine(spec)


class LocalModelHost:
    """One model and one admitted worker, shared by request-scoped adapters.

    Cancellation is cooperative: a native call may overrun its deadline. Admission
    remains held until its thread has actually returned, including repeated cancel.
    """

    def __init__(
        self, *, loader: Callable[[LocalModelSpec], LocalModelEngine] | None = None,
    ) -> None:
        self._loader = loader or _load_default_engine
        self._admission = Lock()
        self._state = Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-local-model")
        self._engine: LocalModelEngine | None = None
        self._spec: LocalModelSpec | None = None
        self._closed = False
        self._stop: Event | None = None
        self._worker: Future[object] | None = None

    async def run[T](
        self, spec: LocalModelSpec,
        operation: Callable[[LocalModelEngine, Event, float], T], *, timeout: float,
    ) -> T:
        with self._state:
            if self._closed:
                raise GenerationProviderError("deployment_not_ready", retryable=False)
            if not self._admission.acquire(blocking=False):
                raise GenerationProviderError("provider_busy", retryable=True)
            stop = Event()
            deadline = monotonic() + timeout
            self._stop = stop
            worker = self._executor.submit(self._execute, spec, operation, stop, deadline)
            self._worker = cast(Future[object], worker)
        try:
            try:
                async with asyncio.timeout(timeout):
                    result = await asyncio.shield(_wrap(worker))
            except TimeoutError:
                stop.set()
                if await _drain(worker):
                    raise asyncio.CancelledError from None
                raise GenerationProviderError("provider_timeout", retryable=True) from None
            except asyncio.CancelledError:
                stop.set()
                await _drain(worker)
                raise
            if self._closed:
                raise GenerationProviderError("deployment_not_ready", retryable=False)
            if monotonic() >= deadline:
                raise GenerationProviderError("provider_timeout", retryable=True)
            return result
        finally:
            with self._state:
                self._stop = None
                self._worker = None
                self._admission.release()

    def _execute[T](
        self, spec: LocalModelSpec,
        operation: Callable[[LocalModelEngine, Event, float], T],
        stop: Event, deadline: float,
    ) -> T:
        error: GenerationProviderError | None = None
        loading = True
        try:
            if self._spec != spec or self._engine is None:
                self._engine = None
                self._spec = None
                self._engine = self._loader(spec)
                self._spec = spec
            loading = False
            if stop.is_set() or monotonic() >= deadline:
                raise GenerationProviderError("provider_timeout", retryable=True)
            return operation(self._engine, stop, deadline)
        except GenerationProviderError as caught:
            error = GenerationProviderError(caught.code, retryable=caught.retryable)
        except Exception:
            error = GenerationProviderError(
                "deployment_not_ready" if loading else "provider_invalid_response", retryable=False,
            )
        self._engine = None
        self._spec = None
        raise error

    async def aclose(self) -> None:
        with self._state:
            self._closed = True
            if self._stop is not None:
                self._stop.set()
            worker = self._worker
        cancelled = False
        if worker is not None:
            cancelled = await _drain(worker)
        self._engine = None
        self._spec = None
        self._executor.shutdown(wait=False)
        if cancelled:
            raise asyncio.CancelledError


async def _drain[T](worker: Future[T]) -> bool:
    """Shield ownership cleanup from repeated cancellation; observe all exceptions."""
    cancelled = False
    wrapped = _wrap(worker)
    while not worker.done():
        try:
            await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if not worker.cancelled():
        worker.exception()
    return cancelled


def _wrap[T](worker: Future[T]) -> asyncio.Future[T]:
    wrapped = asyncio.wrap_future(worker)
    # Cancellation abandons the original await, but must still observe errors.
    wrapped.add_done_callback(lambda result: None if result.cancelled() else result.exception())
    return wrapped
