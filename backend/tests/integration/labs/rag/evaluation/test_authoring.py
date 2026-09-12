"""Guarded PostgreSQL authoring tests with synthetic rows and an explicit fake ES inspector."""

from collections.abc import Iterator
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ai_workshop.labs.rag.configurations.domain import (
    BM25_RETRIEVAL_PROFILE_ID,
    E5_INDEXING_PROFILE_ID,
    AnswerPolicyVersion,
)
from ai_workshop.labs.rag.configurations.repository import SqlAlchemyRagConfigurationRepository
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagIndexBuildRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
    StructuralElementRecord,
)
from ai_workshop.labs.rag.evaluation.authoring_schemas import AuthoringScope
from ai_workshop.labs.rag.models.document_processing import LEGACY_DOCUMENT_PROCESSING_PROFILE_ID
from ai_workshop.labs.rag.retrieval.domain import FrozenIndexIdentity
from ai_workshop.platform.assets.models import AssetVersionRecord
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.labs.rag.configurations.test_search_configuration_resolver import (
    _seed_actor_workspace,
)
from tests.integration.publishing_support import isolated_publishing_database
from tests.unit.labs.rag.configurations.test_configuration import _configuration

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("AI_WORKSHOP_CODEX_RUNNER_REFS", "{}")
        with isolated_publishing_database(patch) as database:
            command.upgrade(database.config, "head")
            yield database.database_url


@pytest.fixture
async def session(database_url):
    engine = create_async_engine(database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


class Inspector:
    def __init__(self, build):
        self.calls = []
        self.identity = FrozenIndexIdentity(
            index_name=build.index_name,
            index_uuid="synthetic-physical-index",
            index_build_id=build.id,
            projection_id=build.projection_id,
            indexing_profile_id=build.indexing_profile_id,
            vector_dimension=768,
            mapping_version=1,
        )

    async def describe(self, index_name):
        self.calls.append(index_name)
        assert index_name == self.identity.index_name
        return self.identity


async def seed(
    session,
    *,
    processing_profile_id=LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
    indexing_profile_id=E5_INDEXING_PROFILE_ID,
):
    actor, workspace, asset = await _seed_actor_workspace(
        session, label="authoring", with_active_asset=True
    )
    config_repo = SqlAlchemyRagConfigurationRepository(session)
    identity, number = await config_repo.get_or_create_identity(actor, "Synthetic authoring")
    policy = AnswerPolicyVersion.create(
        configuration_id=identity,
        version=number,
        min_semantic_score=0.8,
        min_keyword_coverage=0.7,
        require_complete_provenance=True,
        conflict_mode="separate_sources",
    )
    config = replace(
        _configuration(),
        id=identity,
        owner_id=actor,
        name="Synthetic authoring",
        answer_policy_version=policy,
        answer_policy_version_id=policy.id,
        document_processing_profile_id=processing_profile_id,
        indexing_profile_id=indexing_profile_id,
        retrieval_profile_id=BM25_RETRIEVAL_PROFILE_ID,
        workspace_ids=(workspace,),
    )
    await config_repo.add(config)
    projection = RagProjectionRecord(
        asset_version_id=asset,
        document_processing_profile_id=LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
        indexing_profile_id=E5_INDEXING_PROFILE_ID,
        status="ready",
    )
    session.add(projection)
    await session.flush()
    element = StructuralElementRecord(
        projection_id=projection.id,
        ordinal=0,
        kind="paragraph",
        text="가😀나다",
        section_path=[],
        char_start=10,
        char_end=14,
        parser_name="synthetic",
        parser_version="1",
    )
    chunk = RetrievalChunkRecord(
        projection_id=projection.id, ordinal=0, text="가😀나다", section_path=[]
    )
    session.add_all([element, chunk])
    await session.flush()
    evidence = EvidenceUnitRecord(
        projection_id=projection.id,
        retrieval_chunk_id=chunk.id,
        ordinal=0,
        text="가😀나다",
        element_id=element.id,
        char_start=10,
        char_end=14,
    )
    build = RagIndexBuildRecord(
        projection_id=projection.id,
        document_processing_profile_id=LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
        indexing_profile_id=E5_INDEXING_PROFILE_ID,
        index_name=f"synthetic-{uuid4().hex}",
        expected_document_count=1,
        indexed_document_count=1,
        vector_dimension=768,
        status="ready",
        is_active=True,
    )
    session.add_all([evidence, build])
    await session.flush()
    scope = AuthoringScope(
        configuration_version_id=config.version_id,
        workspace_ids=(workspace,),
        asset_version_ids=(asset,),
    )
    return actor, scope, build, evidence


@pytest.mark.parametrize("profile_kind", ["document_processing", "indexing"])
@pytest.mark.parametrize("operation", ["documents", "preview", "run"])
async def test_candidate_bm25_pair_mismatch_rejected_before_source_or_dataset_access(
    session, profile_kind, operation
):
    from sqlalchemy import func

    from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits, AuthoringService
    from ai_workshop.labs.rag.evaluation.authoring_repository import SqlAlchemyAuthoringRepository
    from ai_workshop.labs.rag.evaluation.authoring_schemas import (
        AuthoringDocumentsRequest,
        AuthoringRunRequest,
    )
    from ai_workshop.labs.rag.evaluation.models import (
        EvaluationDatasetRecord,
        EvaluationDispatchRecord,
        EvaluationRunRecord,
    )
    from ai_workshop.labs.rag.evaluation.repository import SqlAlchemyEvaluationApplicationRepository
    from ai_workshop.labs.rag.evaluation.service import EvaluationApplicationService
    from ai_workshop.labs.rag.models.models import ProfileRecord

    original_id = (
        LEGACY_DOCUMENT_PROCESSING_PROFILE_ID
        if profile_kind == "document_processing"
        else E5_INDEXING_PROFILE_ID
    )
    original = await session.get(ProfileRecord, original_id)
    alternate = ProfileRecord(
        kind=profile_kind,
        name=f"Synthetic incompatible {uuid4()}",
        version=1,
        config=original.config,
        evaluation_state="pending",
        is_default=False,
    )
    session.add(alternate)
    await session.flush()
    actor, scope, build, _ = await seed(
        session,
        processing_profile_id=(
            alternate.id
            if profile_kind == "document_processing"
            else LEGACY_DOCUMENT_PROCESSING_PROFILE_ID
        ),
        indexing_profile_id=alternate.id if profile_kind == "indexing" else E5_INDEXING_PROFILE_ID,
    )
    await session.commit()
    inspector = Inspector(build)
    limits = AuthoringLimits()
    repository = SqlAlchemyAuthoringRepository(session, inspector=inspector, limits=limits)
    application = EvaluationApplicationService(
        SqlAlchemyEvaluationApplicationRepository(session, index_inspector=inspector),
        commit=session.commit,
    )
    service = AuthoringService(repository, application, limits=limits, rollback=session.rollback)
    models = (EvaluationDatasetRecord, EvaluationRunRecord, EvaluationDispatchRecord)
    before = [await session.scalar(select(func.count()).select_from(model)) for model in models]
    observed = []

    def inspect_sql(_conn, _cursor, statement, _parameters, _context, _many):
        observed.append(statement.lower())

    engine = session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", inspect_sql)
    try:
        with pytest.raises(AppError) as caught:
            if operation == "documents":
                await repository.documents(
                    actor,
                    AuthoringDocumentsRequest(
                        configuration_version_id=scope.configuration_version_id,
                        workspace_ids=scope.workspace_ids,
                    ),
                )
            elif operation == "preview":
                await service.preview(actor, scope)
            else:
                await service.run(
                    actor,
                    AuthoringRunRequest(
                        **scope.model_dump(),
                        scope_sha256="a" * 64,
                        draft_id=uuid4(),
                        dataset_name="Synthetic incompatible evaluation",
                        retrieval_k=3,
                        repetition_count=2,
                        retention_confirmed=True,
                        cases=[
                            {
                                "id": uuid4(),
                                "query": "Synthetic absent fact?",
                                "expected_answer_status": "insufficient_evidence",
                                "expected_evidence_ids": [],
                                "expected_highlight": None,
                            }
                        ],
                    ),
                )
        assert caught.value.code == "evaluation_authoring_incompatible"
        assert caught.value.status_code == 409
    finally:
        event.remove(engine, "before_cursor_execute", inspect_sql)
    forbidden = (
        EvidenceUnitRecord.__tablename__,
        RetrievalChunkRecord.__tablename__,
        StructuralElementRecord.__tablename__,
        *(model.__tablename__ for model in models),
    )
    assert not any(table in sql for table in forbidden for sql in observed)
    assert inspector.calls == []
    after = [await session.scalar(select(func.count()).select_from(model)) for model in models]
    assert after == before


async def test_preview_contains_complete_sanitized_actual_evidence(session):
    from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits
    from ai_workshop.labs.rag.evaluation.authoring_repository import SqlAlchemyAuthoringRepository

    actor, scope, build, evidence = await seed(session)
    inspector = Inspector(build)
    repository = SqlAlchemyAuthoringRepository(
        session, inspector=inspector, limits=AuthoringLimits()
    )
    context = await repository.resolve_scope(actor, scope)
    preview = context.preview()
    assert preview.evidence_count == 1
    assert preview.evidence[0].id == evidence.id
    assert preview.evidence[0].text == "가😀나다"
    assert preview.evidence[0].start_char == 10
    assert preview.documents[0].asset_version_id == scope.asset_version_ids[0]
    assert build.index_name not in preview.model_dump_json()
    assert "object_key" not in preview.model_dump_json()
    assert "synthetic-physical-index" not in preview.model_dump_json()


@pytest.mark.parametrize("changed", ["actor", "workspace", "version", "asset"])
async def test_authorization_and_scope_checks_precede_body_access(session, changed):
    from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits
    from ai_workshop.labs.rag.evaluation.authoring_repository import SqlAlchemyAuthoringRepository

    actor, scope, build, _ = await seed(session)
    if changed == "actor":
        actor = uuid4()
    elif changed == "workspace":
        scope = scope.model_copy(update={"workspace_ids": (uuid4(),)})
    elif changed == "version":
        scope = scope.model_copy(update={"configuration_version_id": uuid4()})
    else:
        scope = scope.model_copy(update={"asset_version_ids": (uuid4(),)})
    observed = []
    connection = await session.connection()

    def inspect_sql(_conn, _cursor, statement, _parameters, _context, _many):
        observed.append(statement)

    event.listen(connection.sync_connection, "before_cursor_execute", inspect_sql)
    inspector = Inspector(build)
    repository = SqlAlchemyAuthoringRepository(
        session, inspector=inspector, limits=AuthoringLimits()
    )
    with pytest.raises(AppError) as caught:
        await repository.resolve_scope(actor, scope)
    assert caught.value.status_code == 404
    assert not any("rag_evidence_units" in sql for sql in observed)
    assert inspector.calls == []


async def test_not_ready_source_is_not_silently_omitted(session):
    from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits
    from ai_workshop.labs.rag.evaluation.authoring_repository import SqlAlchemyAuthoringRepository

    actor, scope, build, _ = await seed(session)
    asset = await session.get(AssetVersionRecord, scope.asset_version_ids[0])
    asset.status = "stored"
    await session.flush()
    repository = SqlAlchemyAuthoringRepository(
        session, inspector=Inspector(build), limits=AuthoringLimits()
    )
    with pytest.raises(AppError) as caught:
        await repository.resolve_scope(actor, scope)
    assert caught.value.status_code == 409


async def test_metadata_pages_are_independent_of_preview_corpus_caps(session):
    from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits
    from ai_workshop.labs.rag.evaluation.authoring_repository import SqlAlchemyAuthoringRepository
    from ai_workshop.labs.rag.evaluation.authoring_schemas import AuthoringDocumentsRequest

    actor, scope, build, _ = await seed(session)
    inspector = Inspector(build)
    repository = SqlAlchemyAuthoringRepository(
        session, inspector=inspector, limits=AuthoringLimits(max_documents=1, max_response_bytes=1)
    )
    result = await repository.documents(
        actor,
        AuthoringDocumentsRequest(
            configuration_version_id=scope.configuration_version_id,
            workspace_ids=scope.workspace_ids,
            limit=1,
        ),
    )
    assert result.documents[0].asset_version_id == scope.asset_version_ids[0]
    assert result.documents[0].ready is True
    assert "text" not in result.model_dump_json()
    assert inspector.calls == []
    assert result.next_cursor is None


def run_request(context):
    from ai_workshop.labs.rag.evaluation.authoring_schemas import AuthoringRunRequest

    unit = context.evidence[0]
    return AuthoringRunRequest(
        **context.scope.model_dump(),
        scope_sha256=context.preview().scope_sha256,
        draft_id=uuid4(),
        dataset_name="Synthetic initial evaluation",
        retrieval_k=3,
        repetition_count=2,
        retention_confirmed=True,
        cases=[
            {
                "id": uuid4(),
                "query": "가의 뜻?",
                "expected_answer_status": "supported",
                "expected_evidence_ids": [unit.id],
                "expected_highlight": {
                    "kind": "keyword",
                    "document_id": unit.document_id,
                    "asset_version_id": unit.asset_version_id,
                    "evidence_unit_id": unit.id,
                    "page": unit.page,
                    "spans": [[unit.start_char, unit.start_char + 1]],
                },
            }
        ],
    )


async def service_fixture(session):
    from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits, AuthoringService
    from ai_workshop.labs.rag.evaluation.authoring_repository import SqlAlchemyAuthoringRepository
    from ai_workshop.labs.rag.evaluation.repository import SqlAlchemyEvaluationApplicationRepository
    from ai_workshop.labs.rag.evaluation.service import EvaluationApplicationService

    actor, scope, build, _ = await seed(session)
    inspector = Inspector(build)
    limits = AuthoringLimits()
    repository = SqlAlchemyAuthoringRepository(session, inspector=inspector, limits=limits)
    application = EvaluationApplicationService(
        SqlAlchemyEvaluationApplicationRepository(session, index_inspector=inspector),
        commit=session.commit,
    )
    service = AuthoringService(repository, application, limits=limits, rollback=session.rollback)
    context = await repository.resolve_scope(actor, scope)
    await session.commit()
    return actor, context, inspector, repository, service


async def test_authored_run_persists_real_snapshot_and_identical_draft_reuses_dataset(session):
    from sqlalchemy import func

    from ai_workshop.labs.rag.configurations.domain import BM25_BASELINE_CONFIGURATION_VERSION_ID
    from ai_workshop.labs.rag.evaluation.models import EvaluationDatasetRecord, EvaluationRunRecord

    actor, context, _, _, service = await service_fixture(session)
    request = run_request(context)
    first = await service.run(actor, request)
    second = await service.run(actor, request)
    assert first.id != second.id
    assert first.dataset_snapshot_id == second.dataset_snapshot_id
    assert await session.scalar(select(func.count()).select_from(EvaluationDatasetRecord)) == 1
    record = await session.get(EvaluationRunRecord, first.id)
    assert record.status == "pending"
    assert record.evaluation_policy_version_id is None
    assert {candidate.configuration_version_id for candidate in first.candidates} == {
        BM25_BASELINE_CONFIGURATION_VERSION_ID,
        context.scope.configuration_version_id,
    }
    assert record.execution_snapshot["sources"][0]["evidence_units"][0]["id"] == str(
        context.evidence[0].id
    )


async def test_final_snapshot_identity_drift_rolls_back_dataset_run_and_dispatch(session):
    from sqlalchemy import func

    from ai_workshop.labs.rag.evaluation.models import (
        EvaluationDatasetRecord,
        EvaluationDispatchRecord,
        EvaluationRunRecord,
    )

    actor, context, inspector, _, service = await service_fixture(session)
    models = (EvaluationDatasetRecord, EvaluationRunRecord, EvaluationDispatchRecord)
    before = [await session.scalar(select(func.count()).select_from(model)) for model in models]
    original = inspector.describe

    async def drift(index_name):
        value = await original(index_name)
        # Preview was call 1, run reauthorization call 2; subsequent final snapshot differs.
        return (
            replace(value, index_uuid="replaced-physical") if len(inspector.calls) >= 3 else value
        )

    inspector.describe = drift
    with pytest.raises(AppError) as caught:
        await service.run(actor, run_request(context))
    assert caught.value.code == "evaluation_authoring_stale"
    after = [await session.scalar(select(func.count()).select_from(model)) for model in models]
    assert after == before


async def test_authored_run_uses_exact_processing_projection_in_final_snapshot(session):
    from ai_workshop.labs.rag.evaluation.models import EvaluationRunRecord
    from ai_workshop.labs.rag.models.models import ProfileRecord

    actor, context, _, _, service = await service_fixture(session)
    processing = await session.get(ProfileRecord, LEGACY_DOCUMENT_PROCESSING_PROFILE_ID)
    alternate = ProfileRecord(
        kind="document_processing",
        name=f"Synthetic alternate {uuid4()}",
        version=1,
        config=processing.config,
        evaluation_state="pending",
        is_default=False,
    )
    session.add(alternate)
    await session.flush()
    projection = RagProjectionRecord(
        asset_version_id=context.scope.asset_version_ids[0],
        document_processing_profile_id=alternate.id,
        indexing_profile_id=E5_INDEXING_PROFILE_ID,
        status="ready",
    )
    session.add(projection)
    await session.flush()
    session.add(
        RagIndexBuildRecord(
            projection_id=projection.id,
            document_processing_profile_id=alternate.id,
            indexing_profile_id=E5_INDEXING_PROFILE_ID,
            index_name=f"alternate-{uuid4().hex}",
            expected_document_count=1,
            indexed_document_count=1,
            vector_dimension=768,
            status="ready",
        )
    )
    await session.commit()
    result = await service.run(actor, run_request(context))
    record = await session.get(EvaluationRunRecord, result.id)
    assert {item["projection_id"] for item in record.execution_snapshot["sources"]} == {
        str(context.builds[0].projection_id)
    }


@pytest.mark.parametrize("changed", ["name", "query", "scope"])
async def test_same_draft_canonical_content_changes_are_rejected(session, changed):
    from sqlalchemy import func

    from ai_workshop.labs.rag.evaluation.models import EvaluationRunRecord

    actor, context, _, _, service = await service_fixture(session)
    request = run_request(context)
    await service.run(actor, request)
    before = await session.scalar(select(func.count()).select_from(EvaluationRunRecord))
    if changed == "name":
        changed_request = request.model_copy(update={"dataset_name": "Changed synthetic name"})
    elif changed == "query":
        changed_request = request.model_copy(
            update={
                "cases": (
                    request.cases[0].model_copy(update={"query": "Different synthetic question"}),
                )
            }
        )
    else:
        changed_request = request.model_copy(update={"scope_sha256": "0" * 64})
    with pytest.raises(AppError) as caught:
        await service.run(actor, changed_request)
    assert caught.value.code == (
        "evaluation_authoring_stale" if changed == "scope" else "evaluation_authoring_conflict"
    )
    assert await session.scalar(select(func.count()).select_from(EvaluationRunRecord)) == before


async def test_different_draft_cannot_overwrite_existing_owner_name(session):
    actor, context, _, _, service = await service_fixture(session)
    request = run_request(context)
    original = await service.run(actor, request)
    with pytest.raises(AppError) as caught:
        await service.run(actor, request.model_copy(update={"draft_id": uuid4()}))
    assert caught.value.code == "evaluation_authoring_conflict"
    assert (await service.run(actor, request)).dataset_snapshot_id == original.dataset_snapshot_id


async def test_metadata_later_page_can_select_small_ready_source_despite_large_unready_source(
    session,
):
    from uuid import UUID

    from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits
    from ai_workshop.labs.rag.evaluation.authoring_repository import SqlAlchemyAuthoringRepository
    from ai_workshop.labs.rag.evaluation.authoring_schemas import AuthoringDocumentsRequest
    from ai_workshop.platform.assets.models import DocumentRecord

    actor, scope, build, _ = await seed(session)
    # Fixed lowest UUID puts this intentionally unready source on the first page.
    document = DocumentRecord(
        id=UUID(int=1), workspace_id=scope.workspace_ids[0], name="Large unready synthetic"
    )
    session.add(document)
    await session.flush()
    asset = AssetVersionRecord(
        document_id=document.id,
        number=1,
        object_key="synthetic/not-read",
        sha256="b" * 64,
        media_type="text/plain",
        size=10**8,
        status="stored",
    )
    session.add(asset)
    await session.flush()
    document.active_version_id = asset.id
    await session.flush()
    repository = SqlAlchemyAuthoringRepository(
        session, inspector=Inspector(build), limits=AuthoringLimits(max_documents=1)
    )
    request = AuthoringDocumentsRequest(
        configuration_version_id=scope.configuration_version_id,
        workspace_ids=scope.workspace_ids,
        limit=1,
    )
    first = await repository.documents(actor, request)
    assert first.documents[0].ready is False
    assert first.next_cursor == document.id
    second = await repository.documents(
        actor, request.model_copy(update={"cursor": first.next_cursor})
    )
    assert second.next_cursor is None
    assert second.documents[0].asset_version_id == scope.asset_version_ids[0]
    assert (await repository.resolve_scope(actor, scope)).preview().complete is True


@pytest.mark.parametrize("limit", ["evidence", "text_bytes", "response_bytes"])
async def test_preview_caps_fail_without_truncation_and_precount_precedes_body_fetch(
    session, limit
):
    from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits
    from ai_workshop.labs.rag.evaluation.authoring_repository import SqlAlchemyAuthoringRepository

    actor, scope, build, evidence = await seed(session)
    if limit == "evidence":
        session.add(
            EvidenceUnitRecord(
                projection_id=evidence.projection_id,
                retrieval_chunk_id=evidence.retrieval_chunk_id,
                ordinal=1,
                text="Extra synthetic",
                element_id=evidence.element_id,
                char_start=20,
                char_end=35,
            )
        )
    await session.flush()
    limits = (
        AuthoringLimits(max_evidence_units=1)
        if limit == "evidence"
        else AuthoringLimits(max_response_bytes=1 if limit == "text_bytes" else 100)
    )
    observed = []
    connection = await session.connection()
    event.listen(
        connection.sync_connection,
        "before_cursor_execute",
        lambda _a, _b, statement, _d, _e, _f: observed.append(statement),
    )
    repository = SqlAlchemyAuthoringRepository(session, inspector=Inspector(build), limits=limits)
    with pytest.raises(AppError) as caught:
        await repository.resolve_scope(actor, scope)
    assert caught.value.code == "evaluation_authoring_too_large"
    if limit != "response_bytes":
        assert not any(
            sql.startswith("SELECT rag_evidence_units.id, rag_evidence_units.projection_id")
            for sql in observed
        )


async def test_text_size_check_runs_after_bounded_child_identity_locks(session):
    from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits
    from ai_workshop.labs.rag.evaluation.authoring_repository import SqlAlchemyAuthoringRepository

    actor, scope, build, _ = await seed(session)
    observed = []
    connection = await session.connection()
    event.listen(
        connection.sync_connection,
        "before_cursor_execute",
        lambda _a, _b, statement, _d, _e, _f: observed.append(statement),
    )
    await SqlAlchemyAuthoringRepository(
        session, inspector=Inspector(build), limits=AuthoringLimits()
    ).resolve_scope(actor, scope)
    locked = next(
        i
        for i, sql in enumerate(observed)
        if sql.startswith("SELECT rag_evidence_units.id \n") and "FOR UPDATE" in sql
    )
    measured = next(
        i for i, sql in enumerate(observed) if "octet_length(rag_evidence_units.text)" in sql
    )
    assert locked < measured


@pytest.mark.parametrize("mutation", ["membership", "active_version"])
@pytest.mark.parametrize("first", ["writer", "author"])
async def test_authoring_serializes_permission_and_active_version_changes(
    database_url, mutation, first
):
    import asyncio

    from sqlalchemy import delete, text

    from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits, AuthoringService
    from ai_workshop.labs.rag.evaluation.authoring_repository import SqlAlchemyAuthoringRepository
    from ai_workshop.labs.rag.evaluation.repository import SqlAlchemyEvaluationApplicationRepository
    from ai_workshop.labs.rag.evaluation.service import EvaluationApplicationService
    from ai_workshop.labs.rag.ingestion.locking import lock_ingestion_source
    from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord

    engine = create_async_engine(database_url)
    tasks = []
    release = asyncio.Event()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as initial:
            actor, context, inspector, _, _ = await service_fixture(initial)
            replacement = AssetVersionRecord(
                document_id=context.documents[0].document_id,
                number=2,
                object_key=f"synthetic/replacement/{uuid4()}",
                sha256="b" * 64,
                media_type="text/plain",
                size=12,
                status="ready",
            )
            initial.add(replacement)
            await initial.commit()
            replacement_id = replacement.id
        request = run_request(context)
        author_ready, writer_ready = asyncio.Event(), asyncio.Event()
        pids = {}

        async def author():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                pids["author"] = await session.scalar(text("SELECT pg_backend_pid()"))
                limits = AuthoringLimits()
                repo = SqlAlchemyAuthoringRepository(session, inspector=inspector, limits=limits)
                original = repo.validate_run

                async def pause_before_commit(ctx, run_id):
                    await original(ctx, run_id)
                    author_ready.set()
                    if first == "author":
                        await release.wait()

                repo.validate_run = pause_before_commit
                app = EvaluationApplicationService(
                    SqlAlchemyEvaluationApplicationRepository(session, index_inspector=inspector),
                    commit=session.commit,
                )
                service = AuthoringService(repo, app, limits=limits, rollback=session.rollback)
                if first == "writer":
                    author_ready.set()
                try:
                    return await service.run(actor, request)
                except AppError as exc:
                    return exc.code

        async def writer():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                pids["writer"] = await session.scalar(text("SELECT pg_backend_pid()"))
                if first == "author":
                    writer_ready.set()
                if mutation == "membership":
                    await session.execute(
                        delete(WorkspaceMembershipRecord).where(
                            WorkspaceMembershipRecord.user_id == actor,
                            WorkspaceMembershipRecord.workspace_id
                            == context.scope.workspace_ids[0],
                        )
                    )
                else:
                    source = await lock_ingestion_source(
                        session, replacement_id, require_active=False
                    )
                    source.document.active_version_id = replacement_id
                    await session.flush()
                writer_ready.set()
                if first == "writer":
                    await release.wait()
                await session.commit()

        leader = asyncio.create_task(writer() if first == "writer" else author())
        tasks.append(leader)
        await asyncio.wait_for(writer_ready.wait() if first == "writer" else author_ready.wait(), 5)
        follower = asyncio.create_task(author() if first == "writer" else writer())
        tasks.append(follower)
        await asyncio.wait_for(author_ready.wait() if first == "writer" else writer_ready.wait(), 5)
        follower_name = "author" if first == "writer" else "writer"
        async with asyncio.timeout(5):
            async with engine.connect() as observer:
                while not await observer.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                    {"pid": pids[follower_name]},
                ):
                    assert not follower.done()
                    await asyncio.sleep(0.01)
        assert not follower.done()
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 5)
        result = results[1] if first == "writer" else results[0]
        if first == "writer":
            assert result == (
                "not_found" if mutation == "membership" else "evaluation_authoring_stale"
            )
        else:
            assert result.dataset_snapshot_id is not None
            assert await author() == (
                "not_found" if mutation == "membership" else "evaluation_authoring_stale"
            )
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await engine.dispose()


async def test_cancelled_final_validation_rolls_back_all_authored_records(session):
    import asyncio

    from sqlalchemy import func

    from ai_workshop.labs.rag.evaluation.models import (
        EvaluationDatasetRecord,
        EvaluationDispatchRecord,
        EvaluationRunRecord,
    )

    actor, context, _, repository, service = await service_fixture(session)
    models = (EvaluationDatasetRecord, EvaluationRunRecord, EvaluationDispatchRecord)
    before = [await session.scalar(select(func.count()).select_from(model)) for model in models]

    async def cancel(_context, _run_id):
        raise asyncio.CancelledError()

    repository.validate_run = cancel
    with pytest.raises(asyncio.CancelledError):
        await service.run(actor, run_request(context))
    assert [
        await session.scalar(select(func.count()).select_from(model)) for model in models
    ] == before


async def test_same_actor_draft_advisory_lock_reuses_canonical_dataset_under_concurrency(
    database_url,
):
    import asyncio

    from sqlalchemy import func, text

    from ai_workshop.labs.rag.evaluation.authoring import (
        AuthoringLimits,
        AuthoringService,
        dataset_id,
    )
    from ai_workshop.labs.rag.evaluation.authoring_repository import SqlAlchemyAuthoringRepository
    from ai_workshop.labs.rag.evaluation.models import EvaluationDatasetRecord
    from ai_workshop.labs.rag.evaluation.repository import SqlAlchemyEvaluationApplicationRepository
    from ai_workshop.labs.rag.evaluation.service import EvaluationApplicationService

    engine = create_async_engine(database_url)
    pending = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as initial:
            actor, context, inspector, _, _ = await service_fixture(initial)
        request = run_request(context)
        limits = AuthoringLimits()

        def compose(session):
            repo = SqlAlchemyAuthoringRepository(session, inspector=inspector, limits=limits)
            app = EvaluationApplicationService(
                SqlAlchemyEvaluationApplicationRepository(session, index_inspector=inspector),
                commit=session.commit,
            )
            return AuthoringService(repo, app, limits=limits, rollback=session.rollback)

        async with AsyncSession(engine, expire_on_commit=False) as holder:
            first = compose(holder)
            await first.repository.lock_draft(actor, request.draft_id)
            started = asyncio.Event()
            pid = None

            async def competitor():
                nonlocal pid
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    pid = await session.scalar(text("SELECT pg_backend_pid()"))
                    started.set()
                    return await compose(session).run(actor, request)

            pending = asyncio.create_task(competitor())
            await asyncio.wait_for(started.wait(), 5)
            async with asyncio.timeout(5):
                async with engine.connect() as observer:
                    while not await observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
                    ):
                        assert not pending.done()
                        await asyncio.sleep(0.01)
            first_run = await first.run(actor, request)
            second_run = await asyncio.wait_for(pending, 5)
            assert first_run.id != second_run.id
            assert (
                first_run.dataset_snapshot_id
                == second_run.dataset_snapshot_id
                == dataset_id(actor, request.draft_id)
            )
            assert (
                await holder.scalar(
                    select(func.count())
                    .select_from(EvaluationDatasetRecord)
                    .where(EvaluationDatasetRecord.owner_id == actor)
                )
                == 1
            )
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await engine.dispose()
