"""Guarded disposable PostgreSQL, real gate/slots/audit and explicit fake workspace."""

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from importlib import import_module
from importlib.util import find_spec
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.labs.rag.generation.codex_events import CodexEventResult, CodexTokenUsage
from ai_workshop.labs.rag.generation.codex_execution import CodexRequestExecutor
from ai_workshop.labs.rag.generation.codex_slot_repository import SqlAlchemyCodexExecutionSlots
from ai_workshop.labs.rag.generation.codex_stream import CodexStreamResult
from ai_workshop.labs.rag.generation.codex_verification import CodexVerificationService
from ai_workshop.labs.rag.generation.codex_workspace import CodexWorkspaceResult
from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)
from tests.integration.test_codex_approval_storage import SyntheticRegistry, _seed

pytestmark = pytest.mark.integration


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[IsolatedPublishingDatabase]:
    with isolated_publishing_database(monkeypatch) as isolated:
        command.upgrade(isolated.config, "0028_codex_execution_slots")
        yield isolated


class SyntheticWorkspace:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        content = (
            '{"resolved_query":"synthetic check"}'
            if kwargs["intent"].stage.value == "contextualize"
            else '{"schema_version":2,"status":"insufficient_evidence","claims":[]}'
        )
        return CodexWorkspaceResult(
            stream=CodexStreamResult(
                events=CodexEventResult(
                    content, "synthetic-thread", CodexTokenUsage(20, 0, 5, None, 0)
                ),
                active_processes_after_cleanup=0,
            ),
            process_termination_verified=True,
        )


async def setup(database):
    name = "ai_workshop.labs.rag.generation.codex_verification_repository"
    assert find_spec(name) is not None, "verification/audit persistence adapter is missing"
    module = import_module(name)
    await asyncio.to_thread(command.upgrade, database.config, "0031_evidence_reapproval")
    fixture = await _seed(database.database_url, issue=False, wire=True)
    audit_engine = create_async_engine(database.database_url)
    slot_engine = create_async_engine(database.database_url)
    repository = module.SqlAlchemyCodexVerificationRepository(audit_engine)
    lookup = module.SqlAlchemyCodexVerificationLookup(
        async_sessionmaker(audit_engine), environment="test"
    )
    workspace = SyntheticWorkspace()
    executor = CodexRequestExecutor(
        registry=SyntheticRegistry(),
        source=fixture.source,
        slots=SqlAlchemyCodexExecutionSlots(slot_engine),
        workspace=workspace,
        clock=fixture.source._clock,
        audit=repository,
    )
    service = CodexVerificationService(
        lookup=lookup,
        proofs=repository,
        registry=SyntheticRegistry(),
        executor=executor,
        environment="test",
    )
    return fixture, audit_engine, slot_engine, repository, lookup, workspace, service


async def test_real_current_gate_consumes_two_stages_and_persists_body_free_proof(database):
    fixture, audit_engine, slot_engine, repository, lookup, workspace, service = await setup(
        database
    )
    try:
        arguments = dict(
            actor_id=fixture.intent.actor_id,
            configuration_version_id=fixture.intent.configuration_version_id,
        )
        assert not (await service.status(**arguments)).ready and not workspace.calls
        result = await service.verify(
            **arguments, consented=True, disclosure_version="codex-external-generation-v1"
        )
        assert result.ready and result.observed_provider_model_id is None
        assert len(workspace.calls) == 2
        assert (await service.status(**arguments)).ready and len(workspace.calls) == 2
        async with audit_engine.connect() as connection:
            for table, expected in (
                ("rag_codex_verification_attempts", 1),
                ("rag_codex_stage_audits", 2),
                ("rag_codex_call_consumptions", 2),
                ("rag_codex_execution_slots", 0),
            ):
                assert await connection.scalar(text(f"SELECT count(*) FROM {table}")) == expected
            audits = (
                (await connection.execute(text("SELECT details FROM rag_codex_stage_audits")))
                .scalars()
                .all()
            )
            assert all(item["payload_sha256"] for item in audits)
            assert "Synthetic connectivity check" not in repr(audits)
        assert (
            await lookup.load(
                actor_id=uuid4(), configuration_version_id=fixture.intent.configuration_version_id
            )
            is None
        )
    finally:
        await audit_engine.dispose()
        await slot_engine.dispose()
        await fixture.close()


async def test_append_only_attempt_and_stage_rows_and_nonempty_downgrade_refusal(database):
    fixture, audit_engine, slot_engine, repository, _, workspace, service = await setup(database)
    try:
        await service.verify(
            actor_id=fixture.intent.actor_id,
            configuration_version_id=fixture.intent.configuration_version_id,
            consented=True,
            disclosure_version="codex-external-generation-v1",
        )
        attempt = await repository.latest_attempt(fixture.intent.configuration_version_id)
        assert attempt is not None
        await repository.append_attempt(
            replace(
                attempt,
                id=uuid4(),
                success=False,
                safe_error_code="codex_verification_failed",
                usage_present=False,
            )
        )
        assert not (
            await service.status(
                actor_id=fixture.intent.actor_id,
                configuration_version_id=fixture.intent.configuration_version_id,
            )
        ).ready
        for table in ("rag_codex_verification_attempts", "rag_codex_stage_audits"):
            async with audit_engine.connect() as connection:
                with pytest.raises(DBAPIError):
                    await connection.execute(text(f"DELETE FROM {table}"))
                await connection.rollback()
        with pytest.raises(Exception, match="evidence_reapproval_downgrade_requires_empty_tables"):
            await asyncio.to_thread(
                command.downgrade, database.config, "0028_codex_execution_slots"
            )
    finally:
        await audit_engine.dispose()
        await slot_engine.dispose()
        await fixture.close()


async def test_empty_migration_roundtrip_preserves_previous_tables(database):
    name = "ai_workshop.labs.rag.generation.codex_verification_repository"
    assert find_spec(name) is not None
    await asyncio.to_thread(command.upgrade, database.config, "0029_codex_verification")
    await asyncio.to_thread(command.downgrade, database.config, "0028_codex_execution_slots")
    engine = create_async_engine(database.database_url)
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT to_regclass('rag_codex_stage_audits')"))
                is None
            )
            assert (
                await connection.scalar(text("SELECT to_regclass('rag_codex_execution_slots')"))
                is not None
            )
    finally:
        await engine.dispose()


async def test_admin_evidence_metadata_scope_exact_hash_and_explicit_revocation(database):
    from ai_workshop.labs.rag.generation.codex_authorization import EvidenceClassification
    from ai_workshop.labs.rag.generation.codex_composition import CodexEvidenceAdministration
    from ai_workshop.shared.errors import AppError

    await asyncio.to_thread(command.upgrade, database.config, "0031_evidence_reapproval")
    fixture = await _seed(database.database_url, issue=False, wire=True)
    try:
        service = CodexEvidenceAdministration(
            fixture.sessions, source=fixture.source, environment="test"
        )
        actor_id, workspace_id = fixture.intent.actor_id, fixture.intent.workspace_ids[0]
        listed = await service.list_evidence(actor_id=actor_id, workspace_id=workspace_id)
        assert len(listed) == 1 and listed[0].content_sha256 == "a" * 64
        assert listed[0].approval_classification == "synthetic"
        assert "object_key" not in repr(listed) and "synthetic question" not in repr(listed)
        with pytest.raises(AppError):
            await service.list_evidence(actor_id=uuid4(), workspace_id=workspace_id)
        with pytest.raises(AppError):
            await service.list_evidence(actor_id=actor_id, workspace_id=uuid4())
        with pytest.raises(AppError):
            await service.approve(
                actor_id=actor_id,
                revision_id=listed[0].revision_id,
                content_sha256="b" * 64,
                classification=EvidenceClassification.PUBLIC,
                expected_generation=1,
                request_id=uuid4(),
            )
        assert (await service.list_evidence(actor_id=actor_id, workspace_id=workspace_id))[
            0
        ].approval_classification == "synthetic"
        await service.revoke(
            actor_id=actor_id,
            revision_id=listed[0].revision_id,
            expected_generation=1,
            request_id=uuid4(),
        )
        revoked = (await service.list_evidence(actor_id=actor_id, workspace_id=workspace_id))[0]
        assert revoked.revoked and revoked.approval_classification is None
        assert revoked.approval_generation == 2
        assert [item.action for item in revoked.approval_history] == ["approve", "revoke"]
        await service.approve(
            actor_id=actor_id,
            revision_id=listed[0].revision_id,
            content_sha256="a" * 64,
            classification=EvidenceClassification.PUBLIC,
            expected_generation=2,
            request_id=uuid4(),
        )
        reapproved = (await service.list_evidence(actor_id=actor_id, workspace_id=workspace_id))[0]
        assert reapproved.approval_generation == 3 and not reapproved.revoked
        assert reapproved.provider == "development_codex_exec"
        assert len(reapproved.approval_history) == 3
    finally:
        await fixture.close()


@pytest.mark.parametrize("initially_approved", [False, True])
async def test_evidence_listing_keeps_state_and_history_in_one_snapshot(
    database, initially_approved
):
    from ai_workshop.labs.rag.generation.codex_composition import CodexEvidenceAdministration

    await asyncio.to_thread(command.upgrade, database.config, "0031_evidence_reapproval")
    fixture = await _seed(database.database_url, issue=False, approve=initially_approved)
    actor_id = fixture.intent.actor_id
    revision_id = fixture.intent.evidence_revisions[0].revision_id
    transitioned = False

    def commit_transition_after_state_read(
        connection, cursor, statement, parameters, context, many
    ):
        nonlocal transitioned
        if transitioned or "LEFT OUTER JOIN rag_evidence_approval_states" not in statement:
            return
        transitioned = True
        # Real independent PostgreSQL commit between the two SELECTs, in the guarded DB.
        # The event hook controls only timing; reads and writes are real SQL.
        url = database.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url, connect_timeout=5) as writer:
            if initially_approved:
                writer.execute(
                    "UPDATE rag_evidence_approval_states "
                    "SET generation=2, status='revoked', revoked_at=now() WHERE revision_id=%s",
                    (revision_id,),
                )
            else:
                writer.execute(
                    "INSERT INTO rag_evidence_approval_states "
                    "(revision_id, provider, generation, status, content_sha256, "
                    "classification, approved_at) "
                    "VALUES (%s, 'development_codex_exec', 1, 'approved', %s, 'synthetic', now())",
                    (revision_id, "a" * 64),
                )
            writer.execute(
                "INSERT INTO rag_evidence_approval_events "
                "(revision_id, provider, generation, action, actor_id, occurred_at, "
                "classification, content_sha256, request_id, request_digest) "
                "VALUES (%s, 'development_codex_exec', %s, %s, %s, now(), 'synthetic', %s, %s, %s)",
                (
                    revision_id,
                    2 if initially_approved else 1,
                    "revoke" if initially_approved else "approve",
                    actor_id,
                    "a" * 64,
                    uuid4(),
                    "d" * 64,
                ),
            )

    event.listen(
        fixture.snapshot_engine.sync_engine,
        "after_cursor_execute",
        commit_transition_after_state_read,
    )
    try:
        service = CodexEvidenceAdministration(
            fixture.sessions, source=fixture.source, environment="test"
        )
        arguments = dict(actor_id=actor_id, workspace_id=fixture.intent.workspace_ids[0])
        listed = (await service.list_evidence(**arguments))[0]
        assert transitioned
        assert listed.approval_generation == (1 if initially_approved else 0)
        assert len(listed.approval_history) == listed.approval_generation
        assert not listed.revoked
        if initially_approved:
            assert listed.approval_history[-1].action == "approve"
        current = (await service.list_evidence(**arguments))[0]
        assert current.approval_generation == (2 if initially_approved else 1)
        assert current.approval_history[-1].generation == current.approval_generation
        assert current.revoked is initially_approved
        assert current.approval_history[-1].action == (
            "revoke" if initially_approved else "approve"
        )
    finally:
        event.remove(
            fixture.snapshot_engine.sync_engine,
            "after_cursor_execute",
            commit_transition_after_state_read,
        )
        await fixture.close()


async def test_request_composition_uses_distinct_owned_pools_and_real_gate_with_fake_stream(
    database, monkeypatch
):
    from ai_workshop.config import Settings
    from ai_workshop.labs.rag.generation import codex_composition as composition

    await asyncio.to_thread(command.upgrade, database.config, "0031_evidence_reapproval")
    fixture = await _seed(database.database_url, issue=False, wire=True)
    engines = []
    closes = []
    workspace = SyntheticWorkspace()

    def engine_factory(settings):
        engine = create_async_engine(database.database_url)
        engines.append(engine)
        return engine

    original_dispose = type(fixture.snapshot_engine).dispose

    async def dispose(engine, *args, **kwargs):
        if engine in engines:
            closes.append(engine)
        await original_dispose(engine, *args, **kwargs)

    monkeypatch.setattr(composition, "create_engine", engine_factory)
    monkeypatch.setattr(composition, "codex_registry", lambda settings: SyntheticRegistry())
    monkeypatch.setattr(composition, "CodexWorkspaceExecutor", lambda **kwargs: workspace)
    monkeypatch.setattr(type(fixture.snapshot_engine), "dispose", dispose)
    try:
        async with composition.codex_services(
            Settings(secret_key="x" * 32, _env_file=None)
        ) as services:
            assert len(engines) == 4 and len({id(engine.pool) for engine in engines}) == 4
            assert not workspace.calls and not closes
            result = await services.verification.verify(
                actor_id=fixture.intent.actor_id,
                configuration_version_id=fixture.intent.configuration_version_id,
                consented=True,
                disclosure_version="codex-external-generation-v1",
            )
            assert result.ready and len(workspace.calls) == 2
        assert closes == list(reversed(engines))
    finally:
        await fixture.close()


async def test_listing_does_not_classify_new_revision_and_exact_public_approval_is_explicit(
    database,
):
    from ai_workshop.labs.rag.generation.codex_authorization import EvidenceClassification
    from ai_workshop.labs.rag.generation.codex_composition import CodexEvidenceAdministration
    from ai_workshop.platform.assets.domain import VersionStatus
    from ai_workshop.platform.assets.models import AssetVersionRecord

    await asyncio.to_thread(command.upgrade, database.config, "0031_evidence_reapproval")
    fixture = await _seed(database.database_url, issue=False, wire=True)
    revision_id = uuid4()
    try:
        existing_id = fixture.intent.evidence_revisions[0].revision_id
        async with fixture.sessions() as session, session.begin():
            existing = await session.get(AssetVersionRecord, existing_id)
            assert existing is not None
            session.add(
                AssetVersionRecord(
                    id=revision_id,
                    document_id=existing.document_id,
                    number=2,
                    object_key="synthetic-new-revision.txt",
                    sha256="d" * 64,
                    media_type="text/plain",
                    size=20,
                    status=VersionStatus.READY,
                )
            )
        service = CodexEvidenceAdministration(
            fixture.sessions, source=fixture.source, environment="test"
        )
        arguments = dict(
            actor_id=fixture.intent.actor_id, workspace_id=fixture.intent.workspace_ids[0]
        )
        for _ in range(2):
            listed = await service.list_evidence(**arguments)
            pending = next(item for item in listed if item.revision_id == revision_id)
            assert pending.approval_classification is None and pending.approved_at is None
        await service.approve(
            actor_id=fixture.intent.actor_id,
            revision_id=revision_id,
            content_sha256="d" * 64,
            classification=EvidenceClassification.PUBLIC,
            expected_generation=0,
            request_id=uuid4(),
        )
        approved = next(
            item
            for item in await service.list_evidence(**arguments)
            if item.revision_id == revision_id
        )
        assert approved.approval_classification == "public" and approved.approved_at is not None
    finally:
        await fixture.close()
