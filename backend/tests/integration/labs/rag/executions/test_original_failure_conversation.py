"""Original SQL service integration with test-only faults and outer rollback.

Actual conversation/access/observer/monitoring code is exercised. The executor is
a fault injector: no retrieval, provider, HTTP/browser or model E2E is claimed.
"""

import os
from pathlib import Path
from typing import Never
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_sessionmaker

import ai_workshop.main  # noqa: F401 -- register existing SQLAlchemy mappings
from ai_workshop.labs.rag.conversations.access import ConversationAccess
from ai_workshop.labs.rag.conversations.repository import SqlAlchemyConversationRepository
from ai_workshop.labs.rag.conversations.schemas import ConversationStart
from ai_workshop.labs.rag.conversations.service import ConversationService
from ai_workshop.labs.rag.domains.repository import (
    SqlAlchemyDomainConfigurationProvider,
    SqlAlchemyDomainRepository,
)
from ai_workshop.labs.rag.domains.service import DomainService
from ai_workshop.labs.rag.executions.domain import STAGES, SelectionObservation
from ai_workshop.labs.rag.executions.observer import current_observer
from ai_workshop.labs.rag.executions.read_repository import SqlAlchemyMonitoringRepository
from ai_workshop.labs.rag.executions.repository import SqlAlchemyExecutionRecorder
from ai_workshop.labs.rag.executions.schemas import ExecutionSearchRequest
from ai_workshop.labs.rag.executions.service import ExecutionReadService
from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
from ai_workshop.shared.db import create_engine
from ai_workshop.shared.errors import AppError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_ORIGINAL_FAILURE_CONVERSATION") != "1",
        reason="Explicit original failure-conversation rollback verification is required.",
    ),
]


class FaultExecutor:
    def __init__(self, failure: str) -> None:
        self.failure = failure
        self.calls = 0
        self.selection = SelectionObservation(candidate_count=3, selected_count=1)

    async def preflight(self, **values: object) -> None:
        # Domain/access checks are real; concrete provider preflight is excluded.
        pass

    async def execute(self, **values: object) -> Never:
        self.calls += 1
        observer = current_observer.get()
        assert observer is not None
        await observer.end("request")
        await observer.begin("contextualization")
        await observer.end("contextualization")
        await observer.begin("retrieval")
        await observer.end("retrieval")
        await observer.begin("selection")
        await observer.end("selection", selection=self.selection)
        await observer.begin("generation")
        if self.failure == "citation_validation_failed":
            await observer.end("generation")
            await observer.begin("citation_validation")
            await observer.end(
                "citation_validation", state="failed", reason="exact_value_not_supported"
            )
        if self.failure == "unexpected":
            raise RuntimeError("synthetic_private_provider_detail")
        raise AppError(self.failure, "Synthetic safe failure.", 502)


@pytest.mark.parametrize(
    "failure", ["generation_timeout", "citation_validation_failed", "unexpected"]
)
async def test_failed_question_replay_reload_and_monitoring(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    for key in list(os.environ):
        if key.upper().startswith("AI_WORKSHOP_"):
            monkeypatch.delenv(key)
    settings = load_original_settings(Path(__file__).resolve().parents[6])
    engine = create_engine(settings)
    engine.sync_engine.hide_parameters = True

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(_connection: Connection) -> None:
        raise AssertionError("Original failure-conversation verification must never COMMIT.")

    request_id = uuid4()
    created: list[tuple[str, UUID]] = []
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "0063_rag_numeric_proof"
                ), "Require existing schema0063; do not migrate in this test."
                actor = await connection.scalar(
                    text("SELECT id FROM users WHERE role='owner' AND is_active LIMIT 1")
                )
                domain = (
                    (
                        await connection.execute(
                            text("""SELECT id,slug,active_connection_version_id FROM rag_domains
                        WHERE active_connection_version_id IS NOT NULL
                        ORDER BY created_at LIMIT 1""")
                        )
                    )
                    .mappings()
                    .first()
                )
                assert actor and domain, (
                    "An existing active owner and connected domain are required."
                )
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                )
                access = ConversationAccess(sessions)
                executor = FaultExecutor(failure)

                async def authority(slug: str, actor_id: UUID) -> None:
                    async with sessions() as session:
                        await DomainService(
                            SqlAlchemyDomainRepository(session),
                            SqlAlchemyDomainConfigurationProvider(
                                session, settings, actor_id=actor_id
                            ),
                        ).detail_for_actor(slug, actor_id)

                async with sessions() as session:
                    domains = DomainService(
                        SqlAlchemyDomainRepository(session),
                        SqlAlchemyDomainConfigurationProvider(session, settings, actor_id=actor),
                    )
                    view = await domains.detail_for_actor(domain["slug"], actor)
                    if not view.ready or not view.allowed_workspace_ids:
                        raise AssertionError(
                            "Existing domain is not ready: " + ",".join(view.reason_codes)
                        )
                    service = ConversationService(
                        SqlAlchemyConversationRepository(sessions),
                        access,
                        domains,
                        executor,
                        recorder=SqlAlchemyExecutionRecorder(sessions),
                        final_authority=authority,
                    )
                    request = ConversationStart(
                        request_id=request_id,
                        query="Synthetic failure persistence question?",
                        connection_version_id=domain["active_connection_version_id"],
                        workspace_ids=list(view.allowed_workspace_ids),
                    )
                    first = await service.start(domain["slug"], actor, request)
                    turn = first.turns[0]
                    assert turn.execution_id is not None
                    created.extend(
                        [
                            ("rag_conversations", first.id),
                            ("rag_conversation_turns", turn.id),
                            ("rag_executions", turn.execution_id),
                        ]
                    )
                    expected_code = (
                        "conversation_execution_failed" if failure == "unexpected" else failure
                    )
                    assert turn.status == "failed" and turn.error_code == expected_code
                    assert turn.execution_terminated and turn.observation_complete
                    assert turn.response is None and not turn.redacted
                    replay = await service.start(domain["slug"], actor, request)
                    reload = await service.detail(domain["slug"], actor, first.id)
                    status = await service.start_status(domain["slug"], actor, request_id)
                    for restored in (replay, reload, status):
                        assert restored.id == first.id and len(restored.turns) == 1
                        assert restored.turns[0].execution_id == turn.execution_id
                        assert restored.turns[0].error_code == expected_code
                        assert restored.turns[0].observation_complete is True
                    with pytest.raises(AppError) as conflict:
                        await service.start(
                            domain["slug"],
                            actor,
                            request.model_copy(update={"query": "Changed synthetic question?"}),
                        )
                    assert conflict.value.status_code == 409
                    assert executor.calls == 1
                    for table, identity in created:
                        assert (
                            await connection.scalar(
                                text(f"SELECT count(*) FROM {table} WHERE id=:id"), {"id": identity}
                            )
                            == 1
                        )
                    monitoring = ExecutionReadService(
                        SqlAlchemyMonitoringRepository(sessions), access
                    )
                    detail = await monitoring.detail(actor, turn.execution_id)
                    fresh = await monitoring.detail(actor, turn.execution_id)
                    assert detail.model_dump() == fresh.model_dump()
                    assert detail.error_code == expected_code and detail.status == "failed"
                    assert detail.observation_complete and detail.generation is None
                    observations = {row.stage: row for row in detail.stages}
                    assert set(observations) == set(STAGES)
                    assert observations["persistence"].state == "completed"
                    assert observations["retrieval"].duration_ms is not None
                    assert observations["selection"].selection == executor.selection
                    expected_stage = (
                        "citation_validation"
                        if failure == "citation_validation_failed"
                        else "generation"
                    )
                    assert detail.failed_stage == expected_stage
                    assert observations[expected_stage].state == "failed"
                    assert observations[expected_stage].reason == (
                        "exact_value_not_supported"
                        if failure == "citation_validation_failed"
                        else expected_code
                    )
                    listed = await monitoring.search(
                        actor,
                        ExecutionSearchRequest(
                            query=request.query,
                            kind="conversation",
                            status="failed",
                            domain_id=domain["id"],
                        ),
                    )
                    assert listed.total == listed.failed_count == 1
                    assert listed.items[0].id == turn.execution_id
                    assert listed.insufficient_count == 0
                    assert current_observer.get() is None
                    assert "synthetic_private_provider_detail" not in caplog.text
                    assert "execution_observation_incomplete" not in caplog.text
            finally:
                await transaction.rollback()
                for table, identity in created:
                    assert (
                        await connection.scalar(
                            text(f"SELECT count(*) FROM {table} WHERE id=:id"), {"id": identity}
                        )
                        == 0
                    ), "Synthetic rows must not survive rollback."
                for table in ("rag_conversation_turns", "rag_conversation_starts"):
                    assert (
                        await connection.scalar(
                            text(f"SELECT count(*) FROM {table} WHERE request_id=:id"),
                            {"id": request_id},
                        )
                        == 0
                    ), "Synthetic request ledger must not survive rollback."
                await connection.rollback()
    finally:
        await engine.dispose()
