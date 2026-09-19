"""Durable admission and conservative completion for shared alias requests."""

from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding, IndexTrackingError

type ClusterProbe = Callable[[], Awaitable[str]]


class AliasJournalPort(Protocol):
    async def reserve(
        self,
        binding: IndexBinding,
        alias: str,
        indexing_profile_id: UUID,
        processing_profile_id: UUID,
        targets: tuple[str, ...],
    ) -> UUID: ...

    async def finish(self, operation_id: UUID) -> None: ...


async def alias_cluster_uuid(settings: Settings) -> str:
    client = create_elasticsearch(settings)
    try:
        response = await client.options(
            max_retries=0,
            retry_on_timeout=False,
            retry_on_status=(),
        ).info()
        value = response.get("cluster_uuid")
        if not isinstance(value, str) or not value:
            raise IndexTrackingError("rag_index_binding_mismatch")
        return value
    except IndexTrackingError:
        raise
    except Exception:
        raise IndexTrackingError("rag_index_observation_failed") from None
    finally:
        await client.close()


async def run_alias_operation(
    journal: AliasJournalPort,
    binding: IndexBinding,
    alias: str,
    indexing_profile_id: UUID,
    processing_profile_id: UUID,
    targets: tuple[str, ...],
    cluster: ClusterProbe,
    mutate: Callable[[], Awaitable[bool]],
    observe: Callable[[], Awaitable[tuple[str, ...]]],
) -> None:
    """Caller retains scope locks; journal commits independently before mutation.

    Any failure after reservation is conservative: only an exact acknowledged
    completion closes the journal. Cancellation also leaves the reservation open.
    """
    if await cluster() != binding.cluster_uuid:
        raise IndexTrackingError("rag_index_binding_mismatch")
    operation_id = await journal.reserve(
        binding,
        alias,
        indexing_profile_id,
        processing_profile_id,
        targets,
    )
    try:
        if await mutate() is not True or await observe() != targets:
            raise IndexTrackingError("rag_index_writer_unconfirmed")
        await journal.finish(operation_id)
    except Exception:
        raise IndexTrackingError("rag_index_writer_unconfirmed") from None
