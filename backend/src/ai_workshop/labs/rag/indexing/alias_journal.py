"""Commit request ownership independently of alias callers' source locks."""

import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.indexing.alias_models import AliasOperationRecord
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding, IndexTrackingError


class AliasJournal:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def reserve(
        self,
        binding: IndexBinding,
        alias: str,
        indexing_profile_id: UUID,
        processing_profile_id: UUID,
        targets: tuple[str, ...],
    ) -> UUID:
        if (
            any(
                re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,254}", name) is None
                for name in (alias, *targets)
            )
            or tuple(sorted(set(targets))) != targets
            or alias in targets
        ):
            raise IndexTrackingError("rag_index_input_conflict")
        operation_id = uuid4()
        try:
            async with self.sessions.begin() as session:
                created = await session.scalar(
                    insert(AliasOperationRecord)
                    .values(
                        id=operation_id,
                        store_id=binding.store_id,
                        cluster_uuid=binding.cluster_uuid,
                        alias=alias,
                        indexing_profile_id=indexing_profile_id,
                        document_processing_profile_id=processing_profile_id,
                        targets=list(targets),
                        state="open",
                    )
                    .on_conflict_do_nothing(
                        index_elements=["cluster_uuid", "alias"],
                        index_where=text("state = 'open'"),
                    )
                    .returning(AliasOperationRecord.id)
                )
                if created is None:
                    raise IndexTrackingError("rag_index_attempt_busy")
        except SQLAlchemyError:
            raise IndexTrackingError("rag_index_writer_unconfirmed") from None
        return operation_id

    async def finish(self, operation_id: UUID) -> None:
        try:
            async with self.sessions.begin() as session:
                row = await session.scalar(
                    select(AliasOperationRecord)
                    .where(AliasOperationRecord.id == operation_id)
                    .with_for_update()
                )
                if row is None:
                    raise IndexTrackingError("rag_index_writer_unconfirmed")
                if row.state == "closed":
                    return
                row.state = "closed"
                row.result_code = "confirmed"
                row.closed_at = datetime.now(UTC)
        except SQLAlchemyError:
            raise IndexTrackingError("rag_index_writer_unconfirmed") from None
