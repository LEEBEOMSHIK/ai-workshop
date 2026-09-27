"""Rollback-only checks: no databases, accounts, indexes or files are created."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import ai_workshop.main  # noqa: F401
from ai_workshop.config import get_settings
from ai_workshop.labs.rag.executions.domain import ExecutionIdentity, ExecutionOutcome
from ai_workshop.labs.rag.executions.repository import SqlAlchemyExecutionRecorder
from ai_workshop.shared.db import create_engine


@pytest.mark.asyncio
async def test_duplicate_turn_has_one_execution_and_terminal_state_cannot_reverse():
    engine = create_engine(get_settings())
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                actor = await connection.scalar(
                    text("SELECT id FROM users ORDER BY created_at LIMIT 1")
                )
                domain = await connection.scalar(
                    text("SELECT id FROM rag_domains ORDER BY created_at LIMIT 1")
                )
                assert actor and domain, "Existing account and domain are required"
                conversation, turn, request = uuid4(), uuid4(), uuid4()
                await connection.execute(
                    text("""INSERT INTO rag_conversations
                    (id,owner_id,domain_id,title,revision,created_at,updated_at)
                    VALUES (:id,:actor,:domain,'synthetic rollback check',1,now(),now())"""),
                    {"id": conversation, "actor": actor, "domain": domain},
                )
                await connection.execute(
                    text("""INSERT INTO rag_conversation_turns
                    (id,conversation_id,request_id,sequence,status,query,request,request_digest,
                    scope_identity,segment,dependencies,execution_terminated,created_at,updated_at)
                    VALUES (:id,:conversation,:request,1,'running','synthetic','{}',
                    :digest,:digest,1,'[]',false,now(),now())"""),
                    {
                        "id": turn,
                        "conversation": conversation,
                        "request": request,
                        "digest": "0" * 64,
                    },
                )
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                )
                recorder = SqlAlchemyExecutionRecorder(sessions)
                identity = ExecutionIdentity(actor_id=actor, turn_id=turn)
                await recorder.start(identity)
                await recorder.start(identity)
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM rag_executions WHERE turn_id=:id"), {"id": turn}
                    )
                    == 1
                )
                await connection.execute(
                    text("UPDATE rag_conversation_turns SET status='cancelled' WHERE id=:id"),
                    {"id": turn},
                )
                await recorder.finish(identity.execution_id, ExecutionOutcome(state="completed"))
                assert (
                    await connection.scalar(
                        text("SELECT status FROM rag_executions WHERE turn_id=:id"), {"id": turn}
                    )
                    == "cancelled"
                )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
