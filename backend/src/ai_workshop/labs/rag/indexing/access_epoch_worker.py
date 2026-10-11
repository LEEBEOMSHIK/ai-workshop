"""Celery startup/task boundaries reject a restored or unverified ES epoch."""

from collections.abc import Awaitable, Callable

from celery.signals import beat_init, task_prerun, worker_init  # type: ignore[import-untyped]

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.access_credentials import AccessCredentialError
from ai_workshop.labs.rag.indexing.access_epoch_runtime import verify_original_runtime
from ai_workshop.shared.asyncio_policy import configure_windows_selector_policy


def register_celery_admission(
    application: object,
    settings: Callable[[], Settings],
    verifier: Callable[..., Awaitable[None]] = verify_original_runtime,
) -> None:
    from asyncio import run

    def check(sender: object, *, non_es: bool = False) -> None:
        if getattr(sender, "app", None) is not application:
            return
        resolved = settings()
        if resolved.environment == "test" and resolved.elasticsearch_access_epoch_id is None:
            # Explicit offline/eager unit mode has no original deployment.
            # Configured epoch tests still exercise the admission boundary.
            return
        try:
            configure_windows_selector_policy()

            async def verified() -> None:
                await verifier(resolved, writer=not non_es, non_es=non_es)

            run(verified())
        except AccessCredentialError as exc:
            # Celery Signal.send catches ordinary exceptions. SystemExit must
            # terminate a denied startup/task instead of allowing execution.
            raise SystemExit(exc.code) from None

    def worker_start(sender: object, **_kwargs: object) -> None:
        check(sender)

    def beat_start(sender: object, **_kwargs: object) -> None:
        check(sender, non_es=True)

    def task_start(sender: object, **_kwargs: object) -> None:
        if getattr(sender, "name", "").startswith("ai_workshop.rag."):
            check(sender)

    worker_init.connect(worker_start, weak=False)
    beat_init.connect(beat_start, weak=False)
    task_prerun.connect(task_start, weak=False)
