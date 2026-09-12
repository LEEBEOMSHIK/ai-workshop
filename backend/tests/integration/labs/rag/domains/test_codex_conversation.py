"""Disposable SQL authorization/slots/audits, real search/runtime; synthetic retrieval/process."""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text, update
from starlette.requests import Request

from ai_workshop.labs.rag.configurations.repository import SqlAlchemyRagConfigurationRepository
from ai_workshop.labs.rag.deployments.domain import DeploymentEnvironment
from ai_workshop.labs.rag.domains.api import DomainSearchExecutor
from ai_workshop.labs.rag.domains.schemas import DomainSearchRequest
from ai_workshop.labs.rag.domains.service import DomainSearchContext
from ai_workshop.labs.rag.generation.audit import SqlAlchemyGenerationAuditRepository
from ai_workshop.labs.rag.generation.codex_composition import CodexRequestRuntimeFactory
from ai_workshop.labs.rag.generation.codex_events import CodexEventResult, CodexTokenUsage
from ai_workshop.labs.rag.generation.codex_execution import CodexRequestExecutor
from ai_workshop.labs.rag.generation.codex_http_lifecycle import run_until_disconnect
from ai_workshop.labs.rag.generation.codex_slot_repository import SqlAlchemyCodexExecutionSlots
from ai_workshop.labs.rag.generation.codex_stream import CodexStreamResult
from ai_workshop.labs.rag.generation.codex_workspace import CodexWorkspaceResult
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.policies.domain import InstallationDataPolicyVersion, OutboundMode
from ai_workshop.labs.rag.policies.repository import SqlAlchemyDataPolicyRepository
from ai_workshop.labs.rag.policies.service import GenerationPolicyResolver
from ai_workshop.labs.rag.retrieval.domain import ResolvedSearchScope, SparseHit
from ai_workshop.labs.rag.search.configuration_port import (
    ResolvedExternalApproval,
    ResolvedWorkspacePolicyApproval,
)
from ai_workshop.labs.rag.search.schemas import SearchRequest
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.shared.errors import AppError
from ai_workshop.shared.request_context import correlation_id_context
from tests.integration import test_codex_verification_storage as verification_storage
from tests.integration.test_codex_approval_storage import SyntheticRegistry
from tests.unit.labs.rag.highlighting.test_evidence_selector import _source
from tests.unit.labs.rag.search.test_generation_policy_gate import _configuration, _service

pytestmark = pytest.mark.integration
database = verification_storage.database
setup = verification_storage.setup
APPROVAL = {
    "classification": "synthetic",
    "consented": True,
    "disclosure_version": "codex-external-generation-v1",
}


class SyntheticGroundedWorkspace:
    def __init__(self):
        self.calls = []
        self.failure = None

    def run(self, **values):
        self.calls.append(values)
        payload = json.loads(values["payload"].stdin)
        answer = (
            {"resolved_query": "synthetic fact"}
            if values["intent"].stage.value == "contextualize"
            else {
                "schema_version": 2,
                "status": "answered",
                "claims": [
                    {
                        "text": "synthetic fact",
                        "evidence_ids": [payload["evidence"][0]["evidence_id"]],
                    }
                ],
            }
        )
        content = self.failure or json.dumps(answer)
        return CodexWorkspaceResult(
            stream=CodexStreamResult(
                events=CodexEventResult(
                    content, "synthetic-thread", CodexTokenUsage(20, 0, 7, None, 0)
                ),
                active_processes_after_cleanup=0,
            ),
            process_termination_verified=True,
        )


@asynccontextmanager
async def conversation(database):
    fixture, audit_engine, slot_engine, audit, lookup, _, verification = await setup(database)
    session = None
    token = correlation_id_context.set(str(uuid4()))
    try:
        actor, version = fixture.intent.actor_id, fixture.intent.configuration_version_id
        assert (
            await verification.verify(
                actor_id=actor,
                configuration_version_id=version,
                consented=True,
                disclosure_version=APPROVAL["disclosure_version"],
            )
        ).ready
        verified = await lookup.load(actor_id=actor, configuration_version_id=version)
        assert verified is not None
        session = audit._sessions()
        configs = SqlAlchemyRagConfigurationRepository(session)
        saved = await configs.find_version_visible(version, actor)
        approval = await SqlAlchemyDataPolicyRepository(
            session
        ).get_external_approval_for_configuration(version)
        assert saved is not None and approval is not None
        resolved = replace(
            _configuration(approval=None),
            configuration_id=saved.id,
            configuration_version_id=version,
            generation_profile=verified.profile,
            indexing_profile_id=saved.indexing_profile_id,
            workspace_ids=saved.workspace_ids,
            answer_policy_version_id=saved.answer_policy_version.id,
            external_approval=ResolvedExternalApproval(
                version,
                approval.deployment_version_id,
                approval.installation_policy_version_id,
                approval.disclosure_version,
                tuple(
                    ResolvedWorkspacePolicyApproval(item.workspace_id, item.policy_version_id)
                    for item in approval.workspace_policies
                ),
            ),
        )
        resolved = replace(
            resolved,
            active_index_alias=replace(
                resolved.active_index_alias, indexing_profile_id=saved.indexing_profile_id
            ),
        )
        revision = fixture.intent.evidence_revisions[0].revision_id
        asset = await session.get(AssetVersionRecord, revision)
        evidence = _source(
            1, "synthetic fact", asset_version_id=revision, document_id=asset.document_id
        )
        evidence = replace(
            evidence, chunk=replace(evidence.chunk, workspace_id=saved.workspace_ids[0])
        )
        await session.rollback()

        class Retrieval:
            sources = (evidence,)

            async def resolve(self, **values):
                if "hits" in values:
                    return self.sources
                return ResolvedSearchScope(
                    saved.workspace_ids,
                    tuple(values["folder_ids"]),
                    asset_version_ids=(revision,),
                    index_build_ids=(evidence.chunk.index_build_id,),
                )

            async def search_sparse(self, **values):
                return tuple(
                    SparseHit(item.chunk, i + 1, 1.0) for i, item in enumerate(self.sources)
                )

        retrieval = Retrieval()
        policies = GenerationPolicyResolver(SqlAlchemyDataPolicyRepository(session))
        decision = await policies.resolve(
            deployment=verified.profile.deployment, workspace_ids=saved.workspace_ids
        )
        await session.rollback()
        service, *_ = _service(configuration=resolved, decision=decision)
        service.generation_policy_resolver = policies
        service.generation_audit_repository = SqlAlchemyGenerationAuditRepository(session)
        service.scope_resolver = service.sparse_retriever = service.source_resolver = retrieval
        service.turn_signer = ConversationTurnSigner(b"synthetic-signing-key-at-least-32-bytes")
        workspace = SyntheticGroundedWorkspace()
        executor = CodexRequestExecutor(
            registry=SyntheticRegistry(),
            source=fixture.source,
            slots=SqlAlchemyCodexExecutionSlots(slot_engine),
            workspace=workspace,
            clock=fixture.source._clock,
            audit=audit,
            correlation_id=UUID(correlation_id_context.get()),
        )
        service.codex_runtime_factory = CodexRequestRuntimeFactory(executor, verification)
        domain, connection = uuid4(), uuid4()

        class Boundary:
            async def resolve_search(self, **values):
                assert values["actor_id"] == actor
                assert values["connection_version_id"] == connection
                return DomainSearchContext(
                    actor,
                    domain,
                    connection,
                    version,
                    saved.id,
                    tuple(values["workspace_ids"]),
                    tuple(values["folder_ids"]),
                )

        class Resolver:
            async def resolve(self, requested_id, requested_actor):
                assert (requested_id, requested_actor) == (saved.id, actor)
                return resolved

            async def resolve_domain_version(self, requested_version, requested_actor):
                assert (requested_version, requested_actor) == (version, actor)
                return resolved

        service.configuration_resolver = Resolver()
        domain_executor = DomainSearchExecutor(Boundary(), Resolver(), service)
        yield fixture, service, domain_executor, workspace, session, resolved, retrieval, connection
    finally:
        correlation_id_context.reset(token)
        if session is not None:
            await session.close()
        await audit_engine.dispose()
        await slot_engine.dispose()
        await fixture.close()


async def test_real_sql_first_question_signed_domain_followup_and_separate_durable_audits(database):
    async with conversation(database) as (
        fixture,
        service,
        domain,
        workspace,
        session,
        config,
        _,
        connection,
    ):
        arguments = dict(slug="synthetic", actor_id=fixture.intent.actor_id)
        values = dict(
            connection_version_id=connection,
            query="synthetic fact",
            workspace_ids=list(config.workspace_ids),
            codex_input_approval=APPROVAL,
        )
        first = await asyncio.wait_for(
            domain.execute(**arguments, request=DomainSearchRequest(**values)), 8
        )
        assert first.generation.status == "answered" and first.generation.citations
        assert first.generation.execution.model_identity_status == "unknown"
        second = await domain.execute(
            **arguments,
            request=DomainSearchRequest(
                **values,
                history=[
                    {"role": "user", "content": "synthetic fact"},
                    {
                        "role": "assistant",
                        "content": first.generation.text,
                        "turn_id": first.generation.turn_id,
                        "validation_token": first.generation.validation_token,
                    },
                ],
            ),
        )
        assert second.generation.status == "answered" and len(workspace.calls) == 3
        intents = [item["intent"] for item in workspace.calls]
        assert len({item.approval_id for item in intents}) == 3
        assert intents[0].request_id != intents[1].request_id == intents[2].request_id
        assert intents[1].stage.value == "contextualize" and intents[2].stage.value == "generate"
        details = (
            (await session.execute(text("SELECT details FROM rag_codex_stage_audits")))
            .scalars()
            .all()
        )
        actual = [item for item in details if item["correlation_id"] is not None]
        assert len(actual) == 3 and {item["correlation_id"] for item in actual} == {
            correlation_id_context.get()
        }
        assert await session.scalar(text("SELECT count(*) FROM rag_codex_call_consumptions")) == 5
        assert await session.scalar(text("SELECT count(*) FROM rag_codex_execution_slots")) == 0
        assert (
            await session.scalar(text("SELECT count(*) FROM rag_generation_execution_audits")) == 2
        )
        assert all("synthetic fact" not in json.dumps(item) for item in details)


@pytest.mark.parametrize(
    "approval",
    [
        None,
        {**APPROVAL, "consented": False},
        {**APPROVAL, "disclosure_version": "external-generation-v1"},
    ],
)
async def test_real_sql_absent_or_stale_question_consent_never_launches(database, approval):
    async with conversation(database) as (fixture, service, _, workspace, session, config, _, _):
        with pytest.raises(AppError) as caught:
            await service.search(
                actor_id=fixture.intent.actor_id,
                request=SearchRequest(
                    query="synthetic fact",
                    configuration_id=config.configuration_id,
                    workspace_ids=list(config.workspace_ids),
                    experimental=True,
                    codex_input_approval=approval,
                ),
            )
        assert caught.value.code == "codex_input_approval_required" and not workspace.calls


async def test_actual_model_failure_is_durable_and_body_free(database):
    async with conversation(database) as (fixture, service, _, workspace, session, config, _, _):
        workspace.failure = "synthetic-invalid-final-json"
        with pytest.raises(AppError) as caught:
            await service.search(
                actor_id=fixture.intent.actor_id,
                request=SearchRequest(
                    query="synthetic fact",
                    configuration_id=config.configuration_id,
                    workspace_ids=list(config.workspace_ids),
                    experimental=True,
                    codex_input_approval=APPROVAL,
                ),
            )
        assert caught.value.code == "structured_output_invalid"
        await session.rollback()
        records = (
            (await session.execute(text("SELECT details FROM rag_codex_stage_audits")))
            .scalars()
            .all()
        )
        failed = [item for item in records if item["correlation_id"] is not None]
        assert (
            len(failed) == 1
            and failed[0]["outcome"] == "failed"
            and failed[0]["usage"]["output_tokens"] == 7
        )
        assert workspace.failure not in json.dumps(records)
        assert await session.scalar(text("SELECT count(*) FROM rag_codex_execution_slots")) == 0


@pytest.mark.parametrize("denial", ["member", "production", "revoked_evidence", "revoked_policy"])
async def test_current_sql_authority_denials_never_launch(database, denial):
    async with conversation(database) as (fixture, service, _, workspace, session, config, _, _):
        actor = fixture.intent.actor_id
        if denial == "member":
            await session.execute(
                update(UserRecord).where(UserRecord.id == actor).values(role="member")
            )
            await session.commit()
        elif denial == "production":
            fixture.source._environment = DeploymentEnvironment.PRODUCTION
        elif denial == "revoked_evidence":
            await fixture.source.revoke_evidence(
                actor_id=actor,
                revision_id=fixture.intent.evidence_revisions[0].revision_id,
                expected_generation=1,
                request_id=uuid4(),
            )
        elif denial == "revoked_policy":
            repository = SqlAlchemyDataPolicyRepository(session)
            policy = await repository.installation_policy_id(for_update=True)
            await repository.add_installation_version(
                InstallationDataPolicyVersion.create(
                    policy_id=policy,
                    version=await repository.next_installation_version(policy),
                    mode=OutboundMode.DENY,
                    approved_providers=(),
                    changed_by=actor,
                )
            )
            await session.commit()
        with pytest.raises(AppError):
            await service.search(
                actor_id=actor,
                request=SearchRequest(
                    query="synthetic fact",
                    configuration_id=config.configuration_id,
                    workspace_ids=list(config.workspace_ids),
                    experimental=True,
                    codex_input_approval=APPROVAL,
                ),
            )
        assert not workspace.calls
        assert await session.scalar(text("SELECT count(*) FROM rag_codex_call_consumptions")) == 2
        assert await session.scalar(text("SELECT count(*) FROM rag_codex_execution_slots")) == 0


async def test_asgi_disconnect_joins_real_coordinator_gate_audit_and_sql_slot(database):
    async with conversation(database) as (fixture, service, _, workspace, session, config, _, _):
        started, cancelled = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()

        def blocked(**values):
            workspace.calls.append(values)
            loop.call_soon_threadsafe(started.set)
            assert values["cancellation"].wait(5)
            loop.call_soon_threadsafe(cancelled.set)
            assert release.wait(5)
            return CodexWorkspaceResult(
                failure="codex_workspace_cancelled", process_termination_verified=True
            )

        workspace.run = blocked
        messages = asyncio.Queue()
        request = Request(
            {"type": "http", "method": "POST", "path": "/synthetic"}, receive=messages.get
        )
        operation = service.search(
            actor_id=fixture.intent.actor_id,
            request=SearchRequest(
                query="synthetic fact",
                configuration_id=config.configuration_id,
                workspace_ids=list(config.workspace_ids),
                experimental=True,
                codex_input_approval=APPROVAL,
            ),
        )
        task = asyncio.create_task(run_until_disconnect(request, operation))
        try:
            await asyncio.wait_for(started.wait(), 5)
            await messages.put({"type": "http.disconnect"})
            await asyncio.wait_for(cancelled.wait(), 2)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            async with fixture.consume_engine.connect() as connection:
                assert (
                    await connection.scalar(text("SELECT count(*) FROM rag_codex_execution_slots"))
                    == 1
                )
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await session.rollback()
        assert await session.scalar(text("SELECT count(*) FROM rag_codex_execution_slots")) == 0
        records = (
            (await session.execute(text("SELECT details FROM rag_codex_stage_audits")))
            .scalars()
            .all()
        )
        cancelled_records = [item for item in records if item["correlation_id"] is not None]
        assert len(cancelled_records) == 1 and cancelled_records[0]["outcome"] == "cancelled"
        assert cancelled_records[0]["process_termination_verified"] is True
        assert await session.scalar(text("SELECT count(*) FROM rag_codex_call_consumptions")) == 3
        assert (
            await session.scalar(text("SELECT count(*) FROM rag_generation_execution_audits")) == 0
        )


async def test_mixed_approved_and_unapproved_immutable_revisions_never_launch(database):
    async with conversation(database) as (
        fixture,
        service,
        _,
        workspace,
        session,
        config,
        retrieval,
        _,
    ):
        document, revision = uuid4(), uuid4()
        session.add(
            DocumentRecord(
                id=document,
                workspace_id=config.workspace_ids[0],
                folder_id=None,
                name="synthetic-unapproved.txt",
                active_version_id=revision,
            )
        )
        await session.flush()
        session.add(
            AssetVersionRecord(
                id=revision,
                document_id=document,
                number=1,
                object_key="synthetic/" + str(revision),
                sha256="b" * 64,
                media_type="text/plain",
                size=30,
                status="ready",
            )
        )
        await session.commit()
        first = _source(
            1,
            "최소 가입 금액은 100만원입니다.",
            document_id=retrieval.sources[0].document_id,
            asset_version_id=fixture.intent.evidence_revisions[0].revision_id,
        )
        second = _source(
            2, "최소 가입 금액은 200만원입니다.", document_id=document, asset_version_id=revision
        )
        retrieval.sources = tuple(
            replace(item, chunk=replace(item.chunk, workspace_id=config.workspace_ids[0]))
            for item in (first, second)
        )
        with pytest.raises(AppError) as caught:
            await service.search(
                actor_id=fixture.intent.actor_id,
                request=SearchRequest(
                    query="최소 가입 금액",
                    configuration_id=config.configuration_id,
                    workspace_ids=list(config.workspace_ids),
                    experimental=True,
                    codex_input_approval=APPROVAL,
                ),
            )
        assert caught.value.code == "codex_authorization_evidence_not_approved"
        assert not workspace.calls
        assert await session.scalar(text("SELECT count(*) FROM rag_codex_call_consumptions")) == 2


async def test_production_composition_factory_captures_correlation_once_for_real_sql_search(
    database, monkeypatch
):
    from sqlalchemy.ext.asyncio import create_async_engine

    from ai_workshop.config import Settings
    from ai_workshop.labs.rag.generation import codex_composition as composition

    async with conversation(database) as (fixture, service, _, workspace, session, config, _, _):
        engines = []

        def engine_factory(_settings):
            engine = create_async_engine(database.database_url)
            engines.append(engine)
            return engine

        monkeypatch.setattr(composition, "create_engine", engine_factory)
        monkeypatch.setattr(composition, "codex_registry", lambda settings: SyntheticRegistry())
        monkeypatch.setattr(composition, "CodexWorkspaceExecutor", lambda **values: workspace)
        public_correlation = correlation_id_context.get()
        async with composition.codex_services(
            Settings(_env_file=None, secret_key="x" * 32, codex_runner_refs={})
        ) as services:
            assert len(engines) == 4 and len({id(engine.pool) for engine in engines}) == 4
            service.codex_runtime_factory = services.runtime_factory
            # Capture happens at composition, not once per stage or from a mutable context later.
            changed = correlation_id_context.set(str(uuid4()))
            try:
                result = await service.search(
                    actor_id=fixture.intent.actor_id,
                    request=SearchRequest(
                        query="synthetic fact",
                        configuration_id=config.configuration_id,
                        workspace_ids=list(config.workspace_ids),
                        experimental=True,
                        codex_input_approval=APPROVAL,
                    ),
                )
            finally:
                correlation_id_context.reset(changed)
        assert result.generation.status.value == "answered" and len(workspace.calls) == 1
        rows = (
            (await session.execute(text("SELECT details FROM rag_codex_stage_audits")))
            .scalars()
            .all()
        )
        actual = [row for row in rows if row["correlation_id"] is not None]
        assert len(actual) == 1 and actual[0]["correlation_id"] == public_correlation
