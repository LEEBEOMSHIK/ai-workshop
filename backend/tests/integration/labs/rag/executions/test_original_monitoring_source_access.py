"""Opt-in original SQL source checks with synthetic metadata and outer rollback.

No existing source, permission, account or execution is modified. No source body,
file, index or model is read or created. This is SQL source authority verification,
not workspace permission revocation, browser or provider E2E.
"""

import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

import ai_workshop.main  # noqa: F401 -- register existing SQLAlchemy mappings
from ai_workshop.labs.rag.conversations.access import ConversationAccess
from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.labs.rag.executions.domain import (
    STAGES,
    CandidateObservation,
    ExecutionIdentity,
    ExecutionOutcome,
    SelectionObservation,
    StageObservation,
)
from ai_workshop.labs.rag.executions.models import ExecutionRecord
from ai_workshop.labs.rag.executions.read_repository import SqlAlchemyMonitoringRepository
from ai_workshop.labs.rag.executions.repository import SqlAlchemyExecutionRecorder
from ai_workshop.labs.rag.executions.schemas import ExecutionSearchRequest
from ai_workshop.labs.rag.executions.service import ExecutionReadService
from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import workspace_read_allowed
from ai_workshop.shared.db import create_engine
from ai_workshop.shared.errors import AppError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_ORIGINAL_MONITORING_SOURCE_ACCESS") != "1",
        reason="Explicit original monitoring source rollback verification is required.",
    ),
]


@pytest.mark.parametrize(
    "restriction",
    [
        "asset_not_ready",
        "projection_not_ready",
        "document_trashed",
        "wrong_asset_revision",
        "wrong_projection_revision",
    ],
)
async def test_source_authority_hides_detail_list_and_statistics_then_recovers(
    monkeypatch: pytest.MonkeyPatch, restriction: str
) -> None:
    for key in list(os.environ):
        if key.upper().startswith("AI_WORKSHOP_"):
            monkeypatch.delenv(key)
    settings = load_original_settings(Path(__file__).resolve().parents[6])
    engine = create_engine(settings)

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(_connection: Connection) -> None:
        raise AssertionError("Original source verification must never COMMIT.")

    document, version, other_version, projection, other_projection = (uuid4() for _ in range(5))
    policy, batch, conversation, turn, execution, request = (uuid4() for _ in range(6))
    child_turn, child_execution, child_request = (uuid4() for _ in range(3))
    synthetic_rows = (
        ("documents", document),
        ("asset_versions", version),
        ("asset_versions", other_version),
        ("rag_document_projections", projection),
        ("rag_document_projections", other_projection),
        ("asset_retention_policies", policy),
        ("asset_trash_batches", batch),
        ("rag_conversations", conversation),
        ("rag_conversation_turns", turn),
        ("rag_executions", execution),
        ("rag_conversation_turns", child_turn),
        ("rag_executions", child_execution),
    )
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "0061_alias_recovery"
                ), "Require existing schema0061; do not migrate in this test."
                actor = await connection.scalar(
                    text("SELECT id FROM users WHERE role='owner' AND is_active LIMIT 1")
                )
                domain = await connection.scalar(
                    text("SELECT id FROM rag_domains ORDER BY created_at LIMIT 1")
                )
                assert actor and domain, "An existing active owner and domain are required."
                source = (
                    await connection.execute(
                        select(
                            DocumentRecord.workspace_id,
                            RagProjectionRecord.document_processing_profile_id,
                            RagProjectionRecord.indexing_profile_id,
                        )
                        .join(WorkspaceRecord, WorkspaceRecord.id == DocumentRecord.workspace_id)
                        .join(
                            AssetVersionRecord, AssetVersionRecord.document_id == DocumentRecord.id
                        )
                        .join(
                            RagProjectionRecord,
                            RagProjectionRecord.asset_version_id == AssetVersionRecord.id,
                        )
                        .where(
                            DocumentRecord.lifecycle == "active",
                            AssetVersionRecord.status == "ready",
                            RagProjectionRecord.status == "ready",
                            workspace_read_allowed(actor),
                        )
                        .limit(1)
                    )
                ).first()
                assert source is not None, "Existing authorized READY source metadata is required."
                workspace, processing_profile, indexing_profile = source
                await connection.execute(
                    text("""INSERT INTO documents
                    (id,workspace_id,name,created_at,updated_at)
                    VALUES (:id,:workspace,'Synthetic source authority fixture',now(),now())"""),
                    {"id": document, "workspace": workspace},
                )
                for number, version_id, projection_id in (
                    (1, version, projection),
                    (2, other_version, other_projection),
                ):
                    await connection.execute(
                        text("""INSERT INTO asset_versions
                        (id,document_id,number,object_key,sha256,media_type,size,status,
                        created_at,updated_at)
                        VALUES (:id,:document,:number,:object_key,:digest,'text/plain',1,
                        'ready',now(),now())"""),
                        {
                            "id": version_id,
                            "document": document,
                            "number": number,
                            "object_key": f"synthetic-source-check/{version_id}",
                            "digest": "0" * 64,
                        },
                    )
                    await connection.execute(
                        text("""INSERT INTO rag_document_projections
                        (id,asset_version_id,document_processing_profile_id,indexing_profile_id,
                        status,created_at,updated_at)
                        VALUES (:id,:version,:processing,:indexing,'ready',now(),now())"""),
                        {
                            "id": projection_id,
                            "version": version_id,
                            "processing": processing_profile,
                            "indexing": indexing_profile,
                        },
                    )
                await connection.execute(
                    text("""UPDATE documents SET active_version_id=:version WHERE id=:id"""),
                    {"id": document, "version": version},
                )
                await connection.execute(
                    text("""INSERT INTO asset_retention_policies
                    (id,workspace_id,version,days,created_by,created_at)
                    SELECT :id,:workspace,coalesce(max(version),0)+1,1,:actor,now()
                    FROM asset_retention_policies WHERE workspace_id=:workspace"""),
                    {"id": policy, "workspace": workspace, "actor": actor},
                )
                await connection.execute(
                    text("""INSERT INTO asset_trash_batches
                    (id,workspace_id,actor_id,policy_version_id,trashed_at,purge_after,created_at)
                    VALUES (:id,:workspace,:actor,:policy,now(),now()+interval '1 day',now())"""),
                    {"id": batch, "workspace": workspace, "actor": actor, "policy": policy},
                )
                await connection.execute(
                    text("""INSERT INTO rag_conversations
                    (id,owner_id,domain_id,title,revision,created_at,updated_at)
                    VALUES (:id,:actor,:domain,'Synthetic source check',1,now(),now())"""),
                    {"id": conversation, "actor": actor, "domain": domain},
                )
                query = f"Synthetic source access question {request}"
                for sequence, turn_id, request_id, dependencies in (
                    (1, turn, request, []),
                    (2, child_turn, child_request, [str(turn)]),
                ):
                    await connection.execute(
                        text("""INSERT INTO rag_conversation_turns
                    (id,conversation_id,request_id,sequence,status,query,request,request_digest,
                    scope_identity,segment,dependencies,execution_terminated,created_at,updated_at)
                    VALUES (:id,:conversation,:request,:sequence,'running',:query,
                    cast(:scope AS jsonb),
                    :digest,:digest,1,cast(:dependencies AS jsonb),false,now(),now())"""),
                        {
                            "id": turn_id,
                            "conversation": conversation,
                            "request": request_id,
                            "sequence": sequence,
                            "dependencies": json.dumps(dependencies),
                            "query": query,
                            "scope": json.dumps({"workspace_ids": [str(workspace)]}),
                            "digest": "0" * 64,
                        },
                    )
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                )
                recorder = SqlAlchemyExecutionRecorder(sessions)
                selection = SelectionObservation(
                    candidates=[
                        CandidateObservation(
                            document_id=document,
                            asset_version_id=version,
                            projection_id=projection,
                            evidence_unit_id=uuid4(),
                            selected=True,
                            reason="selected",
                        )
                    ],
                    candidate_count=1,
                    selected_count=1,
                )
                for turn_id, execution_id in ((turn, execution), (child_turn, child_execution)):
                    await recorder.start(
                        ExecutionIdentity(
                            execution_id=execution_id, actor_id=actor, turn_id=turn_id
                        )
                    )
                    for stage in STAGES:
                        await recorder.record(
                            execution_id,
                            StageObservation(
                                stage=stage,
                                state="failed" if stage == "generation" else "completed",
                                duration_ms=12.5,
                                reason="generation_failed" if stage == "generation" else None,
                                selection=selection
                                if stage == "selection" and turn_id == turn
                                else None,
                            ),
                        )
                    await recorder.finish(
                        execution_id,
                        ExecutionOutcome(state="failed", error_code="generation_failed"),
                    )
                    await connection.execute(
                        text("""UPDATE rag_conversation_turns SET status='failed',
                    error_code='generation_failed',execution_terminated=true WHERE id=:id"""),
                        {"id": turn_id},
                    )
                access = ConversationAccess(sessions)
                repository = SqlAlchemyMonitoringRepository(sessions)
                monitoring = ExecutionReadService(repository, access)
                search = ExecutionSearchRequest(query=query, kind="conversation", status="failed")

                async def assert_visible() -> None:
                    for execution_id in (execution, child_execution):
                        detail = await monitoring.detail(actor, execution_id)
                        assert detail.id == execution_id and detail.observation_complete
                    listed = await monitoring.search(actor, search)
                    assert listed.total == listed.failed_count == listed.duration_count == 2
                    assert {item.id for item in listed.items} == {execution, child_execution}
                    assert listed.median_ms is not None and listed.p95_ms is not None

                await assert_visible()
                restriction_transaction = await connection.begin_nested()
                try:
                    if restriction == "asset_not_ready":
                        await connection.execute(
                            text("UPDATE asset_versions SET status='failed' WHERE id=:id"),
                            {"id": version},
                        )
                    elif restriction == "projection_not_ready":
                        await connection.execute(
                            text(
                                "UPDATE rag_document_projections SET status='failed' WHERE id=:id"
                            ),
                            {"id": projection},
                        )
                    elif restriction == "document_trashed":
                        await connection.execute(
                            text("""UPDATE documents SET lifecycle='trashed',trash_batch_id=:batch,
                            trashed_at=now(),purge_after=now()+interval '1 day' WHERE id=:id"""),
                            {"id": document, "batch": batch},
                        )
                    else:
                        async with sessions.begin() as session:
                            row = await session.get(ExecutionRecord, execution)
                            assert row is not None
                            changed = json.loads(json.dumps(row.stages))
                            candidate = changed["selection"]["selection"]["candidates"][0]
                            field, replacement = (
                                ("asset_version_id", other_version)
                                if restriction == "wrong_asset_revision"
                                else ("projection_id", other_projection)
                            )
                            candidate[field] = str(replacement)
                            row.stages = changed
                    entry = await repository.find(actor, execution)
                    assert entry is not None and entry.execution is not None
                    assert (
                        await access.visible(
                            actor,
                            replace(entry.turn, response={"observations": entry.execution.stages}),
                        )
                        is False
                    )
                    child = await repository.find(actor, child_execution)
                    assert child is not None and child.execution is not None
                    assert child.turn.dependencies == [turn]
                    # Child has no source identity of its own: only closure traversal can hide it.
                    assert (
                        await access.visible(
                            actor,
                            replace(child.turn, response={"observations": child.execution.stages}),
                        )
                        is True
                    )
                    for turn_id, execution_id in ((turn, execution), (child_turn, child_execution)):
                        with pytest.raises(AppError) as denied:
                            await monitoring.detail(actor, execution_id)
                        assert denied.value.code == "not_found" and denied.value.status_code == 404
                        with pytest.raises(AppError) as denied_legacy:
                            await monitoring.legacy(actor, turn_id)
                        assert denied_legacy.value.status_code == 404
                    hidden = await monitoring.search(actor, search)
                    assert hidden.items == [] and hidden.next_cursor is None
                    assert hidden.total == hidden.failed_count == hidden.insufficient_count == 0
                    assert hidden.duration_count == hidden.duration_missing == 0
                    assert hidden.median_ms is None and hidden.p95_ms is None
                finally:
                    await restriction_transaction.rollback()
                await assert_visible()
            finally:
                await transaction.rollback()
                for table, identity in synthetic_rows:
                    assert (
                        await connection.scalar(
                            text(f"SELECT count(*) FROM {table} WHERE id=:id"), {"id": identity}
                        )
                        == 0
                    ), "Synthetic metadata must not survive rollback."
                await connection.rollback()
    except SQLAlchemyError:
        raise AssertionError("Original synthetic source SQL verification failed.") from None
    finally:
        await engine.dispose()
