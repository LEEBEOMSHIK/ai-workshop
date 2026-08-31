import json
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Never, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import delete, make_url, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_workshop.config import Settings, get_settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.configurations.domain import (
    BM25_BASELINE_CONFIGURATION_VERSION_ID,
    BM25_RETRIEVAL_PROFILE_ID,
    E5_INDEXING_PROFILE_ID,
)
from ai_workshop.labs.rag.configurations.repository import (
    SqlAlchemyRagConfigurationRepository,
)
from ai_workshop.labs.rag.configurations.service import RagConfigurationService
from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagIndexBuildRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
    StructuralElementRecord,
)
from ai_workshop.labs.rag.embeddings.contracts import EmbeddingPort
from ai_workshop.labs.rag.evaluation.domain import (
    load_evaluation_dataset,
)
from ai_workshop.labs.rag.evaluation.models import (
    EvaluationCaseResultRecord,
    EvaluationRunConfigurationRecord,
    EvaluationRunRecord,
)
from ai_workshop.labs.rag.evaluation.repository import (
    SqlAlchemyEvaluationApplicationRepository,
    SqlAlchemyEvaluationRepository,
)
from ai_workshop.labs.rag.evaluation.service import (
    EvaluationApplicationService,
    EvaluationWorkflow,
    evaluate_case,
)
from ai_workshop.labs.rag.evaluation.tasks import ProductionEvaluationSearch
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, IndexDocument
from ai_workshop.labs.rag.indexing.elasticsearch import ElasticsearchSearchIndex
from ai_workshop.labs.rag.indexing.service import IndexingService
from ai_workshop.labs.rag.models.domain import EvaluationState, ProfileKind
from ai_workshop.labs.rag.models.repository import SqlAlchemyModelRegistryRepository
from ai_workshop.labs.rag.models.service import RagModelRegistryService
from ai_workshop.labs.rag.retrieval.elasticsearch import (
    ElasticsearchFrozenIndexInspector,
    FrozenIndexReindexRequiredError,
)
from ai_workshop.platform.assets.models import (
    AssetVersionRecord,
    DocumentRecord,
    FolderRecord,
)
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.shared.errors import AppError
from alembic import command

pytestmark = pytest.mark.integration
BACKEND_ROOT = Path(__file__).resolve().parents[5]
REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
FIXTURE = REPOSITORY_ROOT / "sample-data/public/rag/evaluation/search-v1.json"
COMPANY_ID = UUID("00000000-0000-0000-0000-000000000801")
PERSONAL_ID = UUID("00000000-0000-0000-0000-000000000802")
EXPIRED_ID = UUID("00000000-0000-0000-0000-000000000804")
BGE_INDEXING_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000204")
BGE_RETRIEVAL_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000205")
E5_MODEL_ID = UUID("00000000-0000-0000-0000-000000000101")
EVIDENCE_A = UUID("00000000-0000-0000-0000-000000001001")
EVIDENCE_B = UUID("00000000-0000-0000-0000-000000001002")
BGE_EVIDENCE_A = UUID("00000000-0000-0000-0000-000000001003")
BGE_EVIDENCE_B = UUID("00000000-0000-0000-0000-000000001004")
FORBIDDEN_PRIVATE = UUID("00000000-0000-0000-0000-000000001005")
FORBIDDEN_INACTIVE = UUID("00000000-0000-0000-0000-000000001006")
DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000001301")
ASSET_VERSION_ID = UUID("00000000-0000-0000-0000-000000001302")


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def isolated_evaluation_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    base_url = get_settings().database_url
    database = f"ai_workshop_t11_task_{uuid4().hex}"
    administrative = _database_url(base_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    isolated_url = _database_url(base_url, database)
    try:
        monkeypatch.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
        get_settings.cache_clear()
        command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
        yield isolated_url
    finally:
        get_settings.cache_clear()
        with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )


class NoIngestionJobs:
    async def ensure_indexed(self, command: object) -> UUID:
        del command
        raise AssertionError("No active assets are seeded for this test.")


class LegacyIndexInspector:
    async def describe(self, index_name: str) -> Never:
        raise FrozenIndexReindexRequiredError(
            f"Frozen index {index_name} has no immutable RAG metadata; reindex required."
        )


async def _seed_actor_and_workspaces(session: AsyncSession) -> UUID:
    actor_id = uuid4()
    session.add(
        UserRecord(
            id=actor_id,
            display_name="Evaluation Owner",
            email=f"{actor_id}@example.test",
            normalized_email=f"{actor_id}@example.test",
            password_hash="fixture-hash",
            role="owner",
            is_active=True,
        )
    )
    await session.flush()
    for workspace_id, kind in (
        (COMPANY_ID, "company"),
        (PERSONAL_ID, "personal"),
        (EXPIRED_ID, "temporary"),
    ):
        session.add(
            WorkspaceRecord(
                id=workspace_id,
                name=f"Evaluation {kind}",
                kind=kind,
                created_by=actor_id,
                expires_at=(
                    None
                    if kind != "temporary"
                    else datetime(2026, 8, 30, tzinfo=UTC)
                ),
            )
        )
        await session.flush()
        session.add(
            WorkspaceMembershipRecord(
                workspace_id=workspace_id,
                user_id=actor_id,
                role="owner",
            )
        )
    await session.commit()
    return actor_id


class DeterministicDenseEmbedding(EmbeddingPort):
    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def count_query_tokens(self, text: str) -> int:
        return self.count_tokens(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        vector[0 if "A-17" in text else 1 if "환매" in text else 2] = 1.0
        return vector

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def encode_query(self, text: str) -> list[float]:
        return self._vector(text)


def _mini_fixture() -> bytes:
    queries = (
        (
            UUID("00000000-0000-0000-0000-000000001101"),
            "위험등급 코드 A-17의 의미는?",
            EVIDENCE_A,
            BGE_EVIDENCE_A,
            "keyword",
        ),
        (
            UUID("00000000-0000-0000-0000-000000001102"),
            "환매를 미리 알려야 하는 기간은?",
            EVIDENCE_B,
            BGE_EVIDENCE_B,
            "semantic",
        ),
    )
    fixture = {
        "schema_version": 1,
        "id": str(UUID("00000000-0000-0000-0000-000000001200")),
        "name": "real same snapshot",
        "version": 1,
        "document_snapshot": [
            {
                "document_id": str(DOCUMENT_ID),
                "asset_version_id": str(ASSET_VERSION_ID),
                "sha256": "a" * 64,
                "active": True,
            }
        ],
        "cases": [
            {
                "id": str(case_id),
                "kind": "same_snapshot",
                "query": query,
                "query_sha256": sha256(query.encode("utf-8")).hexdigest(),
                "permission_scenario": {
                    "name": "company-owner",
                    "actor": "caller",
                    "workspace_ids": [str(COMPANY_ID)],
                    "folder_ids": [],
                    "authorized_source_ids": [
                        str(EVIDENCE_A),
                        str(EVIDENCE_B),
                        str(BGE_EVIDENCE_A),
                        str(BGE_EVIDENCE_B),
                    ],
                    "forbidden_source_ids": [
                        str(FORBIDDEN_PRIVATE),
                        str(FORBIDDEN_INACTIVE),
                    ],
                    "as_of": "2026-08-31T00:00:00Z",
                },
                "expected": {
                    "answer_status": "supported",
                    "evidence_unit_ids": [str(evidence_id), str(bge_evidence_id)],
                    "highlight": {
                        "surface": "answer",
                        "document_id": str(DOCUMENT_ID),
                        "asset_version_id": str(ASSET_VERSION_ID),
                        "evidence_unit_id": str(evidence_id),
                        "page": None,
                        "kind": kind,
                        "spans": [[0, 4]],
                        "bboxes": [],
                    },
                },
            }
            for case_id, query, evidence_id, bge_evidence_id, kind in queries
        ],
    }
    return json.dumps(fixture, ensure_ascii=False, indent=2).encode("utf-8")


async def _seed_projection(
    *,
    session: AsyncSession,
    actor_id: UUID,
    indexing_profile_id: UUID,
    dimension: int,
    projection_id: UUID,
    build_id: UUID,
    index_name: str,
    evidence_ids: tuple[UUID, UUID],
) -> tuple[IndexDocument, ...]:
    values = (
        (EVIDENCE_A, "위험등급 코드 A-17은 고위험 상품을 뜻한다."),
        (EVIDENCE_B, "환매 신청은 영업일 기준 7일 전에 알려야 한다."),
    )
    embedding = DeterministicDenseEmbedding(dimension)
    documents: list[IndexDocument] = []
    session.add(
        RagProjectionRecord(
            id=projection_id,
            asset_version_id=ASSET_VERSION_ID,
            indexing_profile_id=indexing_profile_id,
            status="ready",
        )
    )
    await session.flush()
    pending_evidence: list[EvidenceUnitRecord] = []
    for ordinal, (evidence_id, text) in enumerate(
        zip(evidence_ids, (item[1] for item in values), strict=True)
    ):
        chunk_id = uuid4()
        element_id = uuid4()
        evidence = EvidenceUnit(
            id=evidence_id,
            chunk_id=chunk_id,
            projection_id=projection_id,
            ordinal=0,
            text=text,
            location=SourceLocation(
                element_id=element_id,
                page=None,
                char_start=0,
                char_end=len(text),
                bbox=None,
            ),
        )
        session.add(
            StructuralElementRecord(
                id=element_id,
                projection_id=projection_id,
                ordinal=ordinal,
                kind="paragraph",
                text=text,
                section_path=["public fixture"],
                page=None,
                char_start=0,
                char_end=len(text),
                bbox=None,
                parser_name="task11-fixture",
                parser_version="1",
                confidence=1.0,
            )
        )
        session.add(
            RetrievalChunkRecord(
                id=chunk_id,
                projection_id=projection_id,
                ordinal=ordinal,
                text=text,
                section_path=["public fixture"],
            )
        )
        pending_evidence.append(
            EvidenceUnitRecord(
                id=evidence_id,
                projection_id=projection_id,
                retrieval_chunk_id=chunk_id,
                ordinal=0,
                text=text,
                element_id=element_id,
                page=None,
                char_start=0,
                char_end=len(text),
                bbox=None,
            )
        )
        documents.append(
            IndexDocument(
                chunk_id=chunk_id,
                projection_id=projection_id,
                asset_version_id=ASSET_VERSION_ID,
                workspace_id=COMPANY_ID,
                folder_id=None,
                allowed_user_ids=(actor_id,),
                status="ready",
                title=f"same snapshot {ordinal}",
                section_path=("public fixture",),
                text=text,
                evidence_units=(evidence,),
                embedding=tuple(embedding.encode_documents((text,))[0]),
                index_build_id=build_id,
            )
        )
    await session.flush()
    session.add_all(pending_evidence)
    await session.flush()
    session.add(
        RagIndexBuildRecord(
            id=build_id,
            projection_id=projection_id,
            indexing_profile_id=indexing_profile_id,
            index_name=index_name,
            expected_document_count=4,
            indexed_document_count=4,
            vector_dimension=dimension,
            status="ready",
            is_active=True,
        )
    )
    for evidence_id, allowed_users, asset_id in (
        (FORBIDDEN_PRIVATE, (uuid4(),), ASSET_VERSION_ID),
        (FORBIDDEN_INACTIVE, (actor_id,), uuid4()),
    ):
        chunk_id = uuid4()
        evidence = EvidenceUnit(
            id=evidence_id,
            chunk_id=chunk_id,
            projection_id=projection_id,
            ordinal=0,
            text="A-17 환매 private inactive",
            location=SourceLocation(uuid4(), None, 0, 24, None),
        )
        documents.append(
            IndexDocument(
                chunk_id=chunk_id,
                projection_id=projection_id,
                asset_version_id=asset_id,
                workspace_id=COMPANY_ID,
                folder_id=None,
                allowed_user_ids=allowed_users,
                status="ready",
                title="must never surface",
                section_path=("forbidden",),
                text=evidence.text,
                evidence_units=(evidence,),
                embedding=tuple(embedding.encode_documents((evidence.text,))[0]),
                index_build_id=build_id,
            )
        )
    return tuple(documents)


@pytest.mark.asyncio
async def test_real_bm25_e5_bge_compare_the_same_snapshot_with_caller_saved_configs(
    isolated_evaluation_database_url: str,
) -> None:
    settings = Settings(  # type: ignore[call-arg,arg-type]
        _env_file=None,
        secret_key="task11-real-search-secret-key-value",
        database_url=isolated_evaluation_database_url,
        elasticsearch_url="http://127.0.0.1:9200",
        elasticsearch_index_prefix=f"task11-{uuid4().hex}",
    )
    engine = create_async_engine(isolated_evaluation_database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    client = create_elasticsearch(settings)
    concrete_indices: list[str] = []
    try:
        async with sessions() as session:
            actor_id = await _seed_actor_and_workspaces(session)
            registry = RagModelRegistryService(SqlAlchemyModelRegistryRepository(session))
            e5_hybrid = await registry.register_profile(
                kind=ProfileKind.RETRIEVAL,
                name="task11-e5-hybrid",
                version=1,
                config={
                    "bm25": {"analyzer": "standard", "top_k": 30},
                    "dense": {"top_k": 30},
                    "rrf": {"k": 60},
                    "indexing_profile_id": str(E5_INDEXING_PROFILE_ID),
                    "reranker": {"enabled": False},
                },
                bindings=(),
                evaluation_state=EvaluationState.DRAFT,
            )
            await session.commit()
            configuration_service = RagConfigurationService(
                SqlAlchemyRagConfigurationRepository(session),
                NoIngestionJobs(),
                commit=session.commit,
            )
            configurations = []
            for name, indexing_id, retrieval_id in (
                ("caller BM25", E5_INDEXING_PROFILE_ID, BM25_RETRIEVAL_PROFILE_ID),
                ("caller E5", E5_INDEXING_PROFILE_ID, e5_hybrid.id),
                ("caller BGE-M3", BGE_INDEXING_PROFILE_ID, BGE_RETRIEVAL_PROFILE_ID),
            ):
                result = await configuration_service.create(
                    owner_id=actor_id,
                    name=name,
                    indexing_profile_id=indexing_id,
                    retrieval_profile_id=retrieval_id,
                    generation_profile_id=None,
                    min_semantic_score=0.0,
                    min_keyword_coverage=0.0,
                    require_complete_provenance=True,
                    conflict_mode="separate_sources",
                    workspace_ids=(COMPANY_ID,),
                )
                configurations.append(result.configuration)
            session.add(
                DocumentRecord(
                    id=DOCUMENT_ID,
                    workspace_id=COMPANY_ID,
                    folder_id=None,
                    name="same immutable snapshot.pdf",
                    active_version_id=ASSET_VERSION_ID,
                )
            )
            await session.flush()
            session.add(
                AssetVersionRecord(
                    id=ASSET_VERSION_ID,
                    document_id=DOCUMENT_ID,
                    number=1,
                    object_key=f"task11/{ASSET_VERSION_ID}.pdf",
                    sha256="a" * 64,
                    media_type="text/plain",
                    size=100,
                    status="ready",
                )
            )
            await session.flush()
            indexer = IndexingService(
                ElasticsearchSearchIndex(client),
                index_prefix=settings.elasticsearch_index_prefix,
            )
            index_specs: list[
                tuple[UUID, int, UUID, UUID, str, tuple[IndexDocument, ...]]
            ] = []
            for indexing_id, dimension, evidence_ids in (
                (E5_INDEXING_PROFILE_ID, 768, (EVIDENCE_A, EVIDENCE_B)),
                (
                    BGE_INDEXING_PROFILE_ID,
                    1024,
                    (BGE_EVIDENCE_A, BGE_EVIDENCE_B),
                ),
            ):
                projection_id = uuid4()
                build_id = uuid4()
                index_name = IndexDescriptor(
                    dimension, "cosine"
                ).concrete_index_name(
                    settings.elasticsearch_index_prefix, indexing_id, build_id
                )
                documents = await _seed_projection(
                    session=session,
                    actor_id=actor_id,
                    indexing_profile_id=indexing_id,
                    dimension=dimension,
                    projection_id=projection_id,
                    build_id=build_id,
                    index_name=index_name,
                    evidence_ids=evidence_ids,
                )
                index_specs.append(
                    (
                        indexing_id,
                        dimension,
                        projection_id,
                        build_id,
                        index_name,
                        documents,
                    )
                )
            await session.commit()
            for (
                indexing_id,
                dimension,
                projection_id,
                build_id,
                index_name,
                documents,
            ) in index_specs:
                indexed = await indexer.index_projection(
                    descriptor=IndexDescriptor(dimension, "cosine"),
                    profile_id=indexing_id,
                    build_id=build_id,
                    projection_id=projection_id,
                    expected_chunk_count=4,
                    documents=documents,
                )
                assert indexed.index_name == index_name
                concrete_indices.append(index_name)
            repository = SqlAlchemyEvaluationApplicationRepository(
                session,
                index_inspector=ElasticsearchFrozenIndexInspector(client),
            )
            dataset = await repository.add_or_get_dataset(
                actor_id, load_evaluation_dataset(_mini_fixture())
            )
            await session.commit()
            legacy_repository = SqlAlchemyEvaluationApplicationRepository(
                session,
                index_inspector=LegacyIndexInspector(),
            )
            with pytest.raises(AppError) as legacy_error:
                await EvaluationApplicationService(
                    legacy_repository, commit=session.commit
                ).start_run(
                    actor_id=actor_id,
                    dataset_fixture=None,
                    dataset_snapshot_id=dataset.id,
                    evaluation_policy_version_id=None,
                    configuration_version_ids=(configurations[0].version_id,),
                    metric_definition_version=1,
                    retrieval_k=10,
                    repetition_count=2,
                )
            assert legacy_error.value.code == "evaluation_index_reindex_required"
            run = await EvaluationApplicationService(
                repository, commit=session.commit
            ).start_run(
                actor_id=actor_id,
                dataset_fixture=None,
                dataset_snapshot_id=dataset.id,
                evaluation_policy_version_id=None,
                configuration_version_ids=tuple(
                    item.version_id for item in configurations
                ),
                metric_definition_version=1,
                retrieval_k=10,
                repetition_count=2,
            )
            runtime_mismatch_run = await EvaluationApplicationService(
                repository, commit=session.commit
            ).start_run(
                actor_id=actor_id,
                dataset_fixture=None,
                dataset_snapshot_id=dataset.id,
                evaluation_policy_version_id=None,
                configuration_version_ids=(configurations[0].version_id,),
                metric_definition_version=1,
                retrieval_k=10,
                repetition_count=2,
            )
            execution_repository = SqlAlchemyEvaluationRepository(sessions)
            first_runtime = {
                "application_revision": "worker-a",
                "device": "cpu",
                "packages": {"sentence-transformers": "6.0.0"},
            }
            first_claim = await execution_repository.claim_run(
                runtime_mismatch_run.id, first_runtime
            )
            assert first_claim is not None
            partial_candidate = first_claim.candidates[0]
            partial_case = first_claim.dataset.cases[0]
            await execution_repository.mark_candidate_running(
                partial_candidate.id, first_claim.claim_token
            )
            partial_search = ProductionEvaluationSearch(
                settings,
                embedding_factory=lambda config: DeterministicDenseEmbedding(
                    config.dimension
                ),
            )
            try:
                partial_observations = tuple(
                    [
                        await partial_search.execute(
                            actor_id=actor_id,
                            candidate=partial_candidate,
                            case=partial_case,
                        )
                        for _ in range(first_claim.repetition_count)
                    ]
                )
            finally:
                await partial_search.close()
            await execution_repository.add_case_result(
                partial_candidate.id,
                first_claim.claim_token,
                evaluate_case(
                    partial_case,
                    0,
                    partial_observations,
                    retrieval_k=first_claim.retrieval_k,
                ),
            )
            await session.execute(
                update(EvaluationRunRecord)
                .where(EvaluationRunRecord.id == runtime_mismatch_run.id)
                .values(claimed_at=datetime.now(UTC) - timedelta(minutes=31))
            )
            await session.commit()
            same_runtime_claim = await execution_repository.claim_run(
                runtime_mismatch_run.id, first_runtime
            )
            assert same_runtime_claim is not None
            assert await execution_repository.find_case_result(
                partial_candidate.id, partial_case.id
            ) is not None
            await session.execute(
                update(EvaluationRunRecord)
                .where(EvaluationRunRecord.id == runtime_mismatch_run.id)
                .values(claimed_at=datetime.now(UTC) - timedelta(minutes=31))
            )
            await session.commit()
            mismatched_claim = await execution_repository.claim_run(
                runtime_mismatch_run.id,
                {
                    "application_revision": "worker-b",
                    "device": "cuda",
                    "packages": {"sentence-transformers": "6.1.0"},
                },
            )
            assert mismatched_claim is None
            mismatched_run = await session.get(
                EvaluationRunRecord, runtime_mismatch_run.id
            )
            assert mismatched_run is not None
            await session.refresh(mismatched_run)
            assert mismatched_run.worker_runtime_environment == first_runtime
            assert mismatched_run.status == "failed"
            assert mismatched_run.failure == "runtime_fingerprint_mismatch"
            mismatched_candidates = list(
                await session.scalars(
                    select(EvaluationRunConfigurationRecord).where(
                        EvaluationRunConfigurationRecord.run_id
                        == runtime_mismatch_run.id
                    )
                )
            )
            assert mismatched_candidates
            assert all(item.status == "failed" for item in mismatched_candidates)
            assert len(
                list(
                    await session.scalars(
                        select(EvaluationCaseResultRecord)
                        .join(EvaluationRunConfigurationRecord)
                        .where(
                            EvaluationRunConfigurationRecord.run_id
                            == runtime_mismatch_run.id
                        )
                    )
                )
            ) == 1
            document = await session.get(DocumentRecord, DOCUMENT_ID)
            assert document is not None
            document.active_version_id = None
            document.name = "mutated after evaluation snapshot.pdf"
            replacement_folder = FolderRecord(
                workspace_id=COMPANY_ID,
                parent_id=None,
                name="post-snapshot-folder",
            )
            session.add(replacement_folder)
            await session.flush()
            document.folder_id = replacement_folder.id
            await session.execute(
                delete(WorkspaceMembershipRecord).where(
                    WorkspaceMembershipRecord.workspace_id == COMPANY_ID,
                    WorkspaceMembershipRecord.user_id == actor_id,
                )
            )
            for chunk in await session.scalars(select(RetrievalChunkRecord)):
                chunk.text = "mutated chunk bytes after run creation"
                chunk.section_path = ["mutated"]
            for evidence in await session.scalars(select(EvidenceUnitRecord)):
                evidence.text = "mutated evidence bytes after run creation"
                evidence.char_start = 1
                evidence.char_end = 8
            for build in await session.scalars(select(RagIndexBuildRecord)):
                build.is_active = False
            await session.commit()
        production_search = ProductionEvaluationSearch(
            settings,
            embedding_factory=lambda config: DeterministicDenseEmbedding(
                config.dimension
            ),
        )
        try:
            await EvaluationWorkflow(
                SqlAlchemyEvaluationRepository(sessions),
                production_search,
                runtime_provider=lambda: {
                    "application_revision": "task11-integration",
                    "device": "cpu",
                    "execution_role": "celery-worker",
                },
            ).run(run.id)
        finally:
            await production_search.close()
        async with sessions() as session:
            candidates = list(
                await session.scalars(
                    select(EvaluationRunConfigurationRecord)
                    .where(EvaluationRunConfigurationRecord.run_id == run.id)
                    .order_by(EvaluationRunConfigurationRecord.ordinal)
                )
            )
            assert [item.configuration_version_id for item in candidates] == [
                BM25_BASELINE_CONFIGURATION_VERSION_ID,
                *(item.version_id for item in configurations),
            ]
            diagnostic_results = list(
                await session.scalars(select(EvaluationCaseResultRecord))
            )
            assert [(item.status, item.failure) for item in candidates] == [
                ("completed", None),
                ("completed", None),
                ("completed", None),
                ("completed", None),
            ], [
                (
                    item.run_configuration_id,
                    [raw["answer_status"] for raw in item.raw_observations],
                    item.recall_at_k,
                    item.highlight_iou,
                )
                for item in diagnostic_results
            ]
            assert all(item.recall_at_k == 0.5 for item in candidates)
            assert all(item.access_leaks == 0 for item in candidates)
            assert all(item.reproducibility == 1.0 for item in candidates)
            snapshot_versions = {
                cast(
                    dict[str, object], item.component_snapshot["configuration"]
                )["version_id"]
                for item in candidates
            }
            assert snapshot_versions == {
                str(BM25_BASELINE_CONFIGURATION_VERSION_ID),
                *(str(item.version_id) for item in configurations),
            }
            stored_run = await session.get(EvaluationRunRecord, run.id)
            assert stored_run is not None
            assert len(stored_run.execution_snapshot_sha256) == 64
            assert stored_run.execution_snapshot_bytes
            assert all(
                item.component_snapshot["execution_snapshot_sha256"]
                == stored_run.execution_snapshot_sha256
                for item in candidates
            )
            assert stored_run.worker_runtime_environment == {
                "application_revision": "task11-integration",
                "device": "cpu",
                "execution_role": "celery-worker",
            }
            raw_results = list(await session.scalars(select(EvaluationCaseResultRecord)))
            forbidden = {str(FORBIDDEN_PRIVATE), str(FORBIDDEN_INACTIVE)}
            assert raw_results
            assert all(
                forbidden.isdisjoint(
                    {
                        evidence_id
                        for observation in result.raw_observations
                        for field in (
                            "retrieved_evidence_ids",
                            "answer_evidence_ids",
                            "related_evidence_ids",
                        )
                        for evidence_id in cast(list[str], observation[field])
                    }
                )
                for result in raw_results
            )
    finally:
        if concrete_indices:
            await client.indices.delete(index=",".join(concrete_indices), ignore_unavailable=True)
        await client.close()
        await engine.dispose()
