"""Request access, idempotency and atomic decisions against disposable PostgreSQL."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.config import Settings
from ai_workshop.labs.rag.generation.codex_approval_models import EvidenceApprovalEventRecord
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.labs.rag.configurations.test_search_configuration_resolver import (
    _seed_actor_workspace,
)
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[IsolatedPublishingDatabase]:
    with isolated_publishing_database(monkeypatch) as isolated:
        command.upgrade(isolated.config, "head")
        yield isolated


@pytest.mark.asyncio
async def test_requests_are_private_idempotent_and_resolved_atomically(database) -> None:
    from ai_workshop.labs.rag.generation.evidence_approval_request_schemas import (
        EvidenceApprovalRequestCreate,
        EvidenceApprovalRequestDecision,
    )
    from ai_workshop.labs.rag.generation.evidence_approval_requests import EvidenceApprovalRequests

    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = EvidenceApprovalRequests(
        sessions, Settings(secret_key="request-tests-secret-32-characters")
    )
    try:
        async with sessions.begin() as session:
            owner, workspace, revision = await _seed_actor_workspace(
                session,
                label="requests",
                with_active_asset=True,
            )
            member, _, _ = await _seed_actor_workspace(
                session, label="member", with_active_asset=False
            )
            other, _, _ = await _seed_actor_workspace(
                session, label="other", with_active_asset=False
            )
            await session.execute(
                update(UserRecord).where(UserRecord.id == member).values(role="member")
            )
            await session.execute(
                update(WorkspaceRecord).where(WorkspaceRecord.id == workspace).values(kind="team")
            )
            session.add_all(
                [
                    WorkspaceMembershipRecord(
                        workspace_id=workspace, user_id=member, role="member"
                    ),
                    WorkspaceMembershipRecord(workspace_id=workspace, user_id=other, role="member"),
                ]
            )
        assert revision is not None
        context = await service.list(actor_id=member, revision_id=revision)
        assert context.context.approval_generation == 0
        assert context.items == []
        body = EvidenceApprovalRequestCreate(
            request_id=uuid4(),
            revision_id=revision,
            provider="development_codex_exec",
            expected_approval_generation=0,
        )
        created = await service.create(actor_id=member, body=body)
        assert created.status == "pending"
        assert (await service.create(actor_id=member, body=body)).id == created.id
        duplicate = body.model_copy(update={"request_id": uuid4()})
        assert (await service.create(actor_id=member, body=duplicate)).id == created.id
        assert (await service.list(actor_id=other)).items == []
        assert len((await service.list(actor_id=owner, admin=True)).items) == 1
        with pytest.raises(AppError) as denied:
            await service.list(actor_id=member, admin=True)
        assert denied.value.status_code == 403
        decision = EvidenceApprovalRequestDecision(
            request_id=uuid4(),
            expected_state_revision=0,
            decision="approve",
            expected_approval_generation=0,
            classification="synthetic",
            content_sha256="b" * 64,
        )
        with pytest.raises(AppError):
            await service.decide(actor_id=owner, id=created.id, body=decision)
        assert (await service.list(actor_id=member)).items[0].status == "pending"
        decision = decision.model_copy(update={"content_sha256": "a" * 64})
        resolved = await service.decide(actor_id=owner, id=created.id, body=decision)
        assert resolved.status == "approved"
        assert resolved.state_revision == 1
        assert (await service.decide(actor_id=owner, id=created.id, body=decision)).id == created.id
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(EvidenceApprovalEventRecord))
                == 1
            )
        page = await service.list(actor_id=member, revision_id=revision)
        assert page.context.approval_generation == 1
        assert page.context.approval_status == "approved"
        assert page.items[0].status == "approved"
        # The original create receipt stays bound to its request after resolution.
        assert (await service.create(actor_id=member, body=duplicate)).status == "approved"
        with pytest.raises(AppError) as stale:
            await service.create(
                actor_id=member, body=body.model_copy(update={"request_id": uuid4()})
            )
        assert stale.value.status_code == 409
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_creates_and_decisions_preserve_one_result_and_rejection_history(
    database,
) -> None:
    from ai_workshop.labs.rag.generation.evidence_approval_request_schemas import (
        EvidenceApprovalRequestCreate,
        EvidenceApprovalRequestDecision,
    )
    from ai_workshop.labs.rag.generation.evidence_approval_requests import EvidenceApprovalRequests

    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = EvidenceApprovalRequests(
        sessions,
        Settings(
            secret_key="request-tests-secret-32-characters",
            library_page_size=1,
            library_max_page_size=2,
        ),
    )
    try:
        async with sessions.begin() as session:
            actor, _, revision = await _seed_actor_workspace(
                session, label="race", with_active_asset=True
            )
        assert revision is not None
        body = EvidenceApprovalRequestCreate(
            request_id=uuid4(),
            revision_id=revision,
            provider="development_codex_exec",
            expected_approval_generation=0,
        )
        rows = await asyncio.gather(
            *(
                service.create(actor_id=actor, body=body.model_copy(update={"request_id": uuid4()}))
                for _ in range(4)
            )
        )
        assert len({row.id for row in rows}) == 1
        reject = EvidenceApprovalRequestDecision(
            request_id=uuid4(),
            expected_state_revision=0,
            decision="reject",
            expected_approval_generation=0,
        )
        decisions = await asyncio.gather(
            service.decide(actor_id=actor, id=rows[0].id, body=reject),
            service.decide(
                actor_id=actor,
                id=rows[0].id,
                body=reject.model_copy(update={"request_id": uuid4()}),
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(row, AppError) and row.status_code == 409 for row in decisions) == 1
        assert (
            sum(not isinstance(row, Exception) and row.status == "rejected" for row in decisions)
            == 1
        )
        second = await service.create(actor_id=actor, body=body)
        assert second.id != rows[0].id
        page = await service.list(actor_id=actor, revision_id=revision)
        assert len(page.items) == 1 and page.next_cursor
        next_page = await service.list(
            actor_id=actor, revision_id=revision, cursor=page.next_cursor
        )
        assert [row.id for row in page.items + next_page.items] == [rows[0].id, second.id]
        assert next_page.next_cursor is None
        assert next_page.context.approval_generation == 0
        exact = reject.model_copy(update={"request_id": uuid4()})
        exact_replays = await asyncio.gather(
            *(service.decide(actor_id=actor, id=second.id, body=exact) for _ in range(4))
        )
        assert [item.status for item in exact_replays] == ["rejected"] * 4
        with pytest.raises(AppError):
            await service.list(actor_id=actor, cursor=page.next_cursor)
        with pytest.raises(AppError):
            await service.list(actor_id=actor, limit=3)
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(EvidenceApprovalEventRecord))
                == 0
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_requester_lost_membership_blocks_owner_decision_and_self_replay(database) -> None:
    from ai_workshop.labs.rag.generation.evidence_approval_request_schemas import (
        EvidenceApprovalRequestCreate,
        EvidenceApprovalRequestDecision,
    )
    from ai_workshop.labs.rag.generation.evidence_approval_requests import EvidenceApprovalRequests

    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = EvidenceApprovalRequests(
        sessions, Settings(secret_key="request-tests-secret-32-characters")
    )
    try:
        async with sessions.begin() as session:
            actor, workspace, revision = await _seed_actor_workspace(
                session, label="lost", with_active_asset=True
            )
            owner, _, _ = await _seed_actor_workspace(
                session, label="still-owner", with_active_asset=False
            )
            await session.execute(
                update(WorkspaceRecord).where(WorkspaceRecord.id == workspace).values(kind="team")
            )
            session.add(
                WorkspaceMembershipRecord(workspace_id=workspace, user_id=owner, role="owner")
            )
        assert revision is not None
        body = EvidenceApprovalRequestCreate(
            request_id=uuid4(),
            revision_id=revision,
            provider="development_codex_exec",
            expected_approval_generation=0,
        )
        row = await service.create(actor_id=actor, body=body)
        async with sessions.begin() as session:
            await session.execute(
                delete(WorkspaceMembershipRecord).where(
                    WorkspaceMembershipRecord.workspace_id == workspace,
                    WorkspaceMembershipRecord.user_id == actor,
                )
            )
        with pytest.raises(AppError):
            await service.create(actor_id=actor, body=body)
        with pytest.raises(AppError):
            await service.decide(
                actor_id=owner,
                id=row.id,
                body=EvidenceApprovalRequestDecision(
                    request_id=uuid4(),
                    expected_state_revision=0,
                    decision="reject",
                    expected_approval_generation=0,
                ),
            )
        assert (await service.list(actor_id=actor)).items == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_revocation_reapproval_cas_and_late_decision_replay_never_restore_approval(
    database,
) -> None:
    from ai_workshop.labs.rag.deployments.domain import DeploymentEnvironment
    from ai_workshop.labs.rag.generation.codex_approval_repository import (
        SqlAlchemyCodexAuthorizationSource,
    )
    from ai_workshop.labs.rag.generation.codex_authorization import EvidenceClassification
    from ai_workshop.labs.rag.generation.evidence_approval_request_schemas import (
        EvidenceApprovalRequestCreate,
        EvidenceApprovalRequestDecision,
    )
    from ai_workshop.labs.rag.generation.evidence_approval_requests import EvidenceApprovalRequests

    engine = create_async_engine(database.database_url)
    consume = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source = SqlAlchemyCodexAuthorizationSource(
        sessions, consumption_engine=consume, environment=DeploymentEnvironment.DEVELOPMENT
    )
    service = EvidenceApprovalRequests(
        sessions, Settings(secret_key="request-tests-secret-32-characters")
    )
    try:
        async with sessions.begin() as session:
            actor, _, revision = await _seed_actor_workspace(
                session, label="reapprove", with_active_asset=True
            )
        assert revision is not None
        row = await service.create(
            actor_id=actor,
            body=EvidenceApprovalRequestCreate(
                request_id=uuid4(),
                revision_id=revision,
                provider="development_codex_exec",
                expected_approval_generation=0,
            ),
        )
        decision = EvidenceApprovalRequestDecision(
            request_id=uuid4(),
            expected_state_revision=0,
            decision="approve",
            expected_approval_generation=0,
            classification="synthetic",
            content_sha256="a" * 64,
        )
        await source.approve_evidence(
            actor_id=actor,
            revision_id=revision,
            content_sha256="a" * 64,
            classification=EvidenceClassification.SYNTHETIC,
            expected_generation=0,
            request_id=uuid4(),
        )
        await source.revoke_evidence(
            actor_id=actor, revision_id=revision, expected_generation=1, request_id=uuid4()
        )
        with pytest.raises(AppError) as stale:
            await service.decide(actor_id=actor, id=row.id, body=decision)
        assert stale.value.status_code == 409
        decision = decision.model_copy(update={"expected_approval_generation": 2})
        await service.decide(actor_id=actor, id=row.id, body=decision)
        # Existing owner endpoint and new request endpoint serialize against the same asset.
        results = await asyncio.gather(
            source.revoke_evidence(
                actor_id=actor, revision_id=revision, expected_generation=3, request_id=uuid4()
            ),
            service.decide(actor_id=actor, id=row.id, body=decision),
            return_exceptions=True,
        )
        assert not any(isinstance(result, Exception) for result in results)
        page = await service.list(actor_id=actor, revision_id=revision)
        assert page.items[0].status == "approved"
        assert page.context.approval_status == "revoked"
        assert page.context.approval_generation == 4
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(EvidenceApprovalEventRecord))
                == 4
            )
    finally:
        await engine.dispose()
        await consume.dispose()


@pytest.mark.asyncio
async def test_decision_storage_failure_rolls_back_approval_event_and_request(database) -> None:
    from sqlalchemy import event

    from ai_workshop.labs.rag.generation.evidence_approval_request_schemas import (
        EvidenceApprovalRequestCreate,
        EvidenceApprovalRequestDecision,
    )
    from ai_workshop.labs.rag.generation.evidence_approval_requests import EvidenceApprovalRequests

    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = EvidenceApprovalRequests(
        sessions, Settings(secret_key="request-tests-secret-32-characters")
    )
    try:
        async with sessions.begin() as session:
            actor, _, revision = await _seed_actor_workspace(
                session, label="rollback", with_active_asset=True
            )
        row = await service.create(
            actor_id=actor,
            body=EvidenceApprovalRequestCreate(
                request_id=uuid4(),
                revision_id=revision,
                provider="development_codex_exec",
                expected_approval_generation=0,
            ),
        )

        def fail_request_update(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("UPDATE rag_evidence_approval_requests SET"):
                raise RuntimeError("injected storage failure after lifecycle flush")

        event.listen(engine.sync_engine, "before_cursor_execute", fail_request_update)
        with pytest.raises(RuntimeError, match="injected storage failure"):
            await service.decide(
                actor_id=actor,
                id=row.id,
                body=EvidenceApprovalRequestDecision(
                    request_id=uuid4(),
                    expected_state_revision=0,
                    decision="approve",
                    expected_approval_generation=0,
                    classification="synthetic",
                    content_sha256="a" * 64,
                ),
            )
        event.remove(engine.sync_engine, "before_cursor_execute", fail_request_update)
        page = await service.list(actor_id=actor, revision_id=revision)
        assert page.context.approval_generation == 0
        assert page.items[0].status == "pending"
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(EvidenceApprovalEventRecord))
                == 0
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_filtered_list_reads_context_and_request_from_one_snapshot(database) -> None:
    import psycopg
    from sqlalchemy import event

    from ai_workshop.labs.rag.generation.evidence_approval_request_schemas import (
        EvidenceApprovalRequestCreate,
    )
    from ai_workshop.labs.rag.generation.evidence_approval_requests import EvidenceApprovalRequests

    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = EvidenceApprovalRequests(
        sessions, Settings(secret_key="request-tests-secret-32-characters")
    )
    try:
        async with sessions.begin() as session:
            actor, _, revision = await _seed_actor_workspace(
                session, label="snapshot", with_active_asset=True
            )
        row = await service.create(
            actor_id=actor,
            body=EvidenceApprovalRequestCreate(
                request_id=uuid4(),
                revision_id=revision,
                provider="development_codex_exec",
                expected_approval_generation=0,
            ),
        )
        fired = False

        def concurrent_resolution(conn, cursor, statement, parameters, context, executemany):
            nonlocal fired
            if fired or "FROM rag_evidence_approval_states" not in statement:
                return
            fired = True
            with psycopg.connect(
                database.database_url.replace("postgresql+psycopg://", "postgresql://")
            ) as other:
                other.execute(
                    """INSERT INTO rag_evidence_approval_states
                    (revision_id,provider,generation,status,content_sha256,classification,approved_at)
                    VALUES (%s,'development_codex_exec',1,'approved',%s,'synthetic',now())""",
                    (revision, "a" * 64),
                )
                request_id = uuid4()
                other.execute(
                    """INSERT INTO rag_evidence_approval_events
                    (revision_id,provider,generation,action,actor_id,occurred_at,classification,
                     content_sha256,request_id,request_digest)
                    VALUES (%s,'development_codex_exec',1,'approve',%s,now(),
                            'synthetic',%s,%s,%s)""",
                    (revision, actor, "a" * 64, request_id, "b" * 64),
                )
                other.execute(
                    """UPDATE rag_evidence_approval_requests SET status='approved',
                    state_revision=1,resolved_at=now(),resolved_by=%s,decision_request_id=%s,
                    decision_digest=%s WHERE id=%s""",
                    (actor, request_id, "b" * 64, row.id),
                )

        event.listen(engine.sync_engine, "after_cursor_execute", concurrent_resolution)
        page = await service.list(actor_id=actor, revision_id=revision)
        event.remove(engine.sync_engine, "after_cursor_execute", concurrent_resolution)
        assert fired
        assert page.context.approval_generation == 0
        assert page.items[0].status == "pending"
        refreshed = await service.list(actor_id=actor, revision_id=revision)
        assert refreshed.context.approval_generation == 1
        assert refreshed.items[0].status == "approved"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_second_request_can_link_matching_current_approval_without_new_grant(
    database,
) -> None:
    from ai_workshop.labs.rag.generation.evidence_approval_request_schemas import (
        EvidenceApprovalRequestCreate,
        EvidenceApprovalRequestDecision,
    )
    from ai_workshop.labs.rag.generation.evidence_approval_requests import EvidenceApprovalRequests

    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = EvidenceApprovalRequests(
        sessions, Settings(secret_key="request-tests-secret-32-characters")
    )
    try:
        async with sessions.begin() as session:
            owner, workspace, revision = await _seed_actor_workspace(
                session, label="link", with_active_asset=True
            )
            requester, _, _ = await _seed_actor_workspace(
                session, label="second", with_active_asset=False
            )
            await session.execute(
                update(WorkspaceRecord).where(WorkspaceRecord.id == workspace).values(kind="team")
            )
            session.add(
                WorkspaceMembershipRecord(workspace_id=workspace, user_id=requester, role="member")
            )
        body = EvidenceApprovalRequestCreate(
            request_id=uuid4(),
            revision_id=revision,
            provider="development_codex_exec",
            expected_approval_generation=0,
        )
        first = await service.create(actor_id=owner, body=body)
        second = await service.create(actor_id=requester, body=body)
        decision = EvidenceApprovalRequestDecision(
            request_id=uuid4(),
            expected_state_revision=0,
            decision="approve",
            expected_approval_generation=0,
            classification="synthetic",
            content_sha256="a" * 64,
        )
        await service.decide(actor_id=owner, id=first.id, body=decision)
        for changes in (
            {"expected_approval_generation": 0},
            {"classification": "public"},
            {"content_sha256": "b" * 64},
        ):
            with pytest.raises(AppError) as denied:
                await service.decide(
                    actor_id=owner,
                    id=second.id,
                    body=decision.model_copy(
                        update={"request_id": uuid4(), "expected_approval_generation": 1, **changes}
                    ),
                )
            assert denied.value.status_code == 409
        linked = await service.decide(
            actor_id=owner,
            id=second.id,
            body=decision.model_copy(
                update={"request_id": uuid4(), "expected_approval_generation": 1}
            ),
        )
        assert linked.status == "approved"
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(EvidenceApprovalEventRecord))
                == 1
            )
        assert (
            await service.list(actor_id=requester, revision_id=revision)
        ).context.approval_generation == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("inaccessible", ["personal", "expired", "membership"])
@pytest.mark.parametrize("actor_role", ["member", "owner"])
async def test_owner_cannot_bypass_current_document_access(
    database, inaccessible: str, actor_role: str
) -> None:
    from ai_workshop.labs.rag.generation.evidence_approval_request_schemas import (
        EvidenceApprovalRequestCreate,
        EvidenceApprovalRequestDecision,
    )
    from ai_workshop.labs.rag.generation.evidence_approval_requests import EvidenceApprovalRequests

    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = EvidenceApprovalRequests(
        sessions, Settings(secret_key="request-tests-secret-32-characters")
    )
    try:
        async with sessions.begin() as session:
            requester, workspace, revision = await _seed_actor_workspace(
                session, label="private", with_active_asset=True
            )
            owner, _, _ = await _seed_actor_workspace(
                session, label="owner", with_active_asset=False
            )
            await session.execute(
                update(UserRecord).where(UserRecord.id == owner).values(role=actor_role)
            )
            if inaccessible != "membership":
                session.add(
                    WorkspaceMembershipRecord(workspace_id=workspace, user_id=owner, role="owner")
                )
        assert revision is not None
        pending = await service.create(
            actor_id=requester,
            body=EvidenceApprovalRequestCreate(
                request_id=uuid4(),
                revision_id=revision,
                provider="development_codex_exec",
                expected_approval_generation=0,
            ),
        )
        if inaccessible == "expired":
            async with sessions.begin() as session:
                await session.execute(
                    update(WorkspaceRecord)
                    .where(WorkspaceRecord.id == workspace)
                    .values(kind="temporary", expires_at=datetime.now(UTC) - timedelta(seconds=1))
                )
        with pytest.raises(AppError) as denied:
            await service.list(actor_id=owner, revision_id=revision)
        assert denied.value.status_code == 404
        assert (await service.list(actor_id=owner)).items == []
        if actor_role == "owner":
            assert (await service.list(actor_id=owner, admin=True)).items == []
        with pytest.raises(AppError) as denied_decision:
            await service.decide(
                actor_id=owner,
                id=pending.id,
                body=EvidenceApprovalRequestDecision(
                    request_id=uuid4(),
                    expected_state_revision=0,
                    decision="reject",
                    expected_approval_generation=0,
                ),
            )
        assert denied_decision.value.status_code == (404 if actor_role == "owner" else 403)
        with pytest.raises(AppError):
            await service.create(
                actor_id=owner,
                body=EvidenceApprovalRequestCreate(
                    request_id=uuid4(),
                    revision_id=revision,
                    provider="development_codex_exec",
                    expected_approval_generation=0,
                ),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_rejects_incomplete_resolution_and_history_mutation(database) -> None:
    from sqlalchemy.exc import DBAPIError

    from ai_workshop.labs.rag.generation.evidence_approval_request_models import (
        EvidenceApprovalRequestReceiptRecord,
        EvidenceApprovalRequestRecord,
    )
    from ai_workshop.labs.rag.generation.evidence_approval_request_schemas import (
        EvidenceApprovalRequestCreate,
        EvidenceApprovalRequestDecision,
    )
    from ai_workshop.labs.rag.generation.evidence_approval_requests import EvidenceApprovalRequests

    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = EvidenceApprovalRequests(
        sessions, Settings(secret_key="request-tests-secret-32-characters")
    )
    try:
        async with sessions.begin() as session:
            actor, _, revision = await _seed_actor_workspace(
                session, label="immutable", with_active_asset=True
            )
        row = await service.create(
            actor_id=actor,
            body=EvidenceApprovalRequestCreate(
                request_id=uuid4(),
                revision_id=revision,
                provider="development_codex_exec",
                expected_approval_generation=0,
            ),
        )
        with pytest.raises(DBAPIError):
            async with sessions.begin() as session:
                await session.execute(
                    update(EvidenceApprovalRequestRecord)
                    .where(EvidenceApprovalRequestRecord.id == row.id)
                    .values(
                        status="rejected",
                        state_revision=1,
                        resolved_at=datetime.now(UTC),
                        resolved_by=actor,
                        decision_request_id=uuid4(),
                        decision_digest=None,
                    )
                )
        await service.decide(
            actor_id=actor,
            id=row.id,
            body=EvidenceApprovalRequestDecision(
                request_id=uuid4(),
                expected_state_revision=0,
                decision="reject",
                expected_approval_generation=0,
            ),
        )
        for statement in (
            update(EvidenceApprovalRequestRecord)
            .where(EvidenceApprovalRequestRecord.id == row.id)
            .values(status="approved"),
            delete(EvidenceApprovalRequestRecord).where(EvidenceApprovalRequestRecord.id == row.id),
            update(EvidenceApprovalRequestReceiptRecord).values(request_digest="b" * 64),
        ):
            with pytest.raises(DBAPIError):
                async with sessions.begin() as session:
                    await session.execute(statement)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "create_replay", "decision", "decision_replay"])
async def test_temporary_expiry_during_receipt_lock_denies_mutation_or_replay(
    database, monkeypatch, operation
) -> None:
    from sqlalchemy import event

    from ai_workshop.labs.rag.generation import evidence_approval_request_access as access
    from ai_workshop.labs.rag.generation.evidence_approval_request_schemas import (
        EvidenceApprovalRequestCreate,
        EvidenceApprovalRequestDecision,
    )
    from ai_workshop.labs.rag.generation.evidence_approval_requests import EvidenceApprovalRequests

    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = EvidenceApprovalRequests(
        sessions, Settings(secret_key="request-tests-secret-32-characters")
    )
    expired = False

    class AdvancingClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + (timedelta(hours=1) if expired else timedelta())

    def finish_lock(conn, cursor, statement, parameters, context, executemany):
        nonlocal expired
        if statement.startswith("SELECT pg_advisory_xact_lock("):
            expired = True

    try:
        async with sessions.begin() as session:
            actor, workspace, revision = await _seed_actor_workspace(
                session, label="expiry-wait", with_active_asset=True
            )
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == workspace)
                .values(kind="temporary", expires_at=datetime.now(UTC) + timedelta(minutes=30))
            )
        body = EvidenceApprovalRequestCreate(
            request_id=uuid4(),
            revision_id=revision,
            provider="development_codex_exec",
            expected_approval_generation=0,
        )
        decision = EvidenceApprovalRequestDecision(
            request_id=uuid4(),
            expected_state_revision=0,
            decision="reject",
            expected_approval_generation=0,
        )
        row = None
        if operation != "create":
            row = await service.create(actor_id=actor, body=body)
        if operation == "decision_replay":
            await service.decide(actor_id=actor, id=row.id, body=decision)
        monkeypatch.setattr(access, "datetime", AdvancingClock)
        event.listen(engine.sync_engine, "after_cursor_execute", finish_lock)
        with pytest.raises(AppError) as denied:
            if operation.startswith("create"):
                await service.create(actor_id=actor, body=body)
            else:
                await service.decide(actor_id=actor, id=row.id, body=decision)
        assert denied.value.status_code == 404
        assert expired
    finally:
        await engine.dispose()
