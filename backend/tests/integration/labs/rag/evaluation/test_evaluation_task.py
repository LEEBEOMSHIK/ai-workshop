import json
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from elasticsearch import AsyncElasticsearch
from psycopg import sql
from sqlalchemy import func, make_url, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_workshop.config import Settings, get_settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.configurations.domain import (
    BM25_RETRIEVAL_PROFILE_ID,
    E5_INDEXING_PROFILE_ID,
)
from ai_workshop.labs.rag.configurations.repository import (
    SqlAlchemyRagConfigurationRepository,
)
from ai_workshop.labs.rag.configurations.service import RagConfigurationService
from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.embeddings.contracts import EmbeddingPort
from ai_workshop.labs.rag.evaluation.domain import (
    EvaluationCase,
    load_evaluation_dataset,
)
from ai_workshop.labs.rag.evaluation.metrics import StableObservation
from ai_workshop.labs.rag.evaluation.models import (
    EvaluationCaseResultRecord,
    EvaluationDispatchRecord,
    EvaluationRunConfigurationRecord,
    EvaluationRunRecord,
)
from ai_workshop.labs.rag.evaluation.repository import (
    SqlAlchemyEvaluationApplicationRepository,
    SqlAlchemyEvaluationRepository,
)
from ai_workshop.labs.rag.evaluation.service import (
    CandidateExecutionInput,
    EvaluationApplicationService,
    EvaluationWorkflow,
    SearchExecutionObservation,
)
from ai_workshop.labs.rag.highlighting.domain import AnswerStatus
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, IndexDocument
from ai_workshop.labs.rag.indexing.elasticsearch import ElasticsearchSearchIndex
from ai_workshop.labs.rag.indexing.service import IndexingService
from ai_workshop.labs.rag.models.domain import EvaluationState, Profile, ProfileKind
from ai_workshop.labs.rag.models.repository import SqlAlchemyModelRegistryRepository
from ai_workshop.labs.rag.models.service import RagModelRegistryService
from ai_workshop.labs.rag.retrieval.domain import ActiveIndexAlias, ResolvedSearchScope
from ai_workshop.labs.rag.retrieval.elasticsearch import (
    ElasticsearchDenseRetriever,
    ElasticsearchSparseRetriever,
)
from ai_workshop.labs.rag.retrieval.service import HybridRetrievalService
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


class ExactExpectedSearch:
    async def execute(
        self,
        *,
        actor_id: UUID,
        candidate: CandidateExecutionInput,
        case: EvaluationCase,
    ) -> SearchExecutionObservation:
        del actor_id, candidate
        highlight = case.expected_highlight
        return SearchExecutionObservation(
            stable=StableObservation(
                retrieved_evidence_ids=tuple(sorted(case.expected_evidence_ids)),
                answer_status=case.expected_answer_status,
                answer_evidence_ids=tuple(sorted(case.expected_evidence_ids)),
                conflict_evidence_ids=(),
                related_evidence_ids=(),
                highlight_kind=highlight.kind if highlight else None,
                highlight_spans=highlight.spans if highlight else (),
                highlight_bboxes=highlight.bboxes if highlight else (),
            ),
            exposures=(),
            duration_ms=10.0,
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


@pytest.mark.asyncio
async def test_durable_run_persists_raw_cases_and_policy_gate_promotes_exact_version(
    isolated_evaluation_database_url: str,
) -> None:
    engine = create_async_engine(isolated_evaluation_database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            actor_id = await _seed_actor_and_workspaces(session)
            configuration_service = RagConfigurationService(
                SqlAlchemyRagConfigurationRepository(session),
                NoIngestionJobs(),
                commit=session.commit,
            )
            first = await configuration_service.create(
                owner_id=actor_id,
                name="caller BM25 A",
                indexing_profile_id=E5_INDEXING_PROFILE_ID,
                retrieval_profile_id=BM25_RETRIEVAL_PROFILE_ID,
                generation_profile_id=None,
                min_semantic_score=0.0,
                min_keyword_coverage=0.0,
                require_complete_provenance=True,
                conflict_mode="separate_sources",
                workspace_ids=(COMPANY_ID, PERSONAL_ID),
            )
            second = await configuration_service.create(
                owner_id=actor_id,
                name="caller BM25 B",
                indexing_profile_id=E5_INDEXING_PROFILE_ID,
                retrieval_profile_id=BM25_RETRIEVAL_PROFILE_ID,
                generation_profile_id=None,
                min_semantic_score=0.0,
                min_keyword_coverage=0.0,
                require_complete_provenance=True,
                conflict_mode="separate_sources",
                workspace_ids=(COMPANY_ID, PERSONAL_ID),
            )
            evaluation_repository = SqlAlchemyEvaluationApplicationRepository(session)
            dataset = await evaluation_repository.add_or_get_dataset(
                actor_id,
                load_evaluation_dataset(FIXTURE.read_bytes()),
            )
            await session.commit()
            evaluation_service = EvaluationApplicationService(
                evaluation_repository, commit=session.commit
            )
            policy = await evaluation_service.create_policy(
                actor_id=actor_id,
                dataset_snapshot_id=dataset.id,
                min_recall_at_k=1.0,
                min_mrr=1.0,
                min_ndcg=1.0,
                min_supported_precision=1.0,
                max_false_grounding_rate=0.0,
                min_highlight_iou=1.0,
                max_p50_latency_ms=10.0,
                max_p95_latency_ms=10.0,
                max_access_leaks=0,
                required_reproducibility=1.0,
            )
            run = await evaluation_service.start_run(
                actor_id=actor_id,
                dataset_fixture=None,
                dataset_snapshot_id=dataset.id,
                evaluation_policy_version_id=policy.id,
                configuration_version_ids=(
                    first.configuration.version_id,
                    second.configuration.version_id,
                ),
                repetition_count=2,
            )
            assert [item.configuration_version_id for item in run.candidates] == [
                first.configuration.version_id,
                second.configuration.version_id,
            ]
            assert await session.get(EvaluationDispatchRecord, run.id) is not None

        await EvaluationWorkflow(
            SqlAlchemyEvaluationRepository(sessions), ExactExpectedSearch()
        ).run(run.id)

        async with sessions.begin() as session:
            interrupted = await session.get(EvaluationRunRecord, run.id)
            assert interrupted is not None
            interrupted.status = "running"
            interrupted.claimed_at = datetime.now(UTC) - timedelta(minutes=31)
            interrupted.claim_token = uuid4()
            interrupted.finished_at = None
        await EvaluationWorkflow(
            SqlAlchemyEvaluationRepository(sessions), ExactExpectedSearch()
        ).run(run.id)

        async with sessions() as session:
            stored_run = await session.get(EvaluationRunRecord, run.id)
            assert stored_run is not None and stored_run.status == "completed"
            candidates = list(
                await session.scalars(
                    select(EvaluationRunConfigurationRecord)
                    .where(EvaluationRunConfigurationRecord.run_id == run.id)
                    .order_by(EvaluationRunConfigurationRecord.ordinal)
                )
            )
            assert [item.status for item in candidates] == ["completed", "completed"]
            assert candidates[0].component_snapshot["configuration"]["version_id"] == str(
                first.configuration.version_id
            )
            assert candidates[0].component_snapshot["configuration"]["workspace_ids"] == [
                str(COMPANY_ID),
                str(PERSONAL_ID),
            ]
            assert (
                await session.scalar(
                    select(func.count()).select_from(EvaluationCaseResultRecord)
                )
                == 24
            )
            configuration_service = RagConfigurationService(
                SqlAlchemyRagConfigurationRepository(session),
                NoIngestionJobs(),
                commit=session.commit,
            )
            promoted = await configuration_service.promote_default(
                first.configuration.id, actor_id
            )
            assert promoted.version_id == first.configuration.version_id
            assert promoted.is_default is True
            assert promoted.evaluation_state.value == "passed"
            with pytest.raises(AppError) as stale_identity:
                await configuration_service.promote_default(uuid4(), actor_id)
            assert stale_identity.value.status_code == 404
    finally:
        await engine.dispose()


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


class FixedScope:
    def __init__(self, workspace_id: UUID) -> None:
        self.scope = ResolvedSearchScope((workspace_id,), ())

    async def resolve(
        self,
        *,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
    ) -> ResolvedSearchScope:
        del actor_id
        assert workspace_ids == self.scope.workspace_ids
        assert folder_ids == ()
        return self.scope


class RealElasticsearchCandidateSearch:
    def __init__(
        self,
        *,
        client: AsyncElasticsearch,
        profiles: dict[UUID, tuple[UUID, Profile, int]],
        index_prefix: str,
    ) -> None:
        self.sparse = ElasticsearchSparseRetriever(client)
        self.dense = ElasticsearchDenseRetriever(client)
        self.profiles = profiles
        self.index_prefix = index_prefix

    async def execute(
        self,
        *,
        actor_id: UUID,
        candidate: CandidateExecutionInput,
        case: EvaluationCase,
    ) -> SearchExecutionObservation:
        indexing_profile_id, retrieval_profile, dimension = self.profiles[
            candidate.configuration_version_id
        ]
        embedding = DeterministicDenseEmbedding(dimension)
        started = perf_counter()
        hits = await HybridRetrievalService(
            scope_resolver=FixedScope(COMPANY_ID),
            embedding=embedding,
            sparse_retriever=self.sparse,
            dense_retriever=self.dense,
        ).search(
            actor_id=actor_id,
            query=case.query,
            workspace_ids=(COMPANY_ID,),
            folder_ids=(),
            indexing_profile_id=indexing_profile_id,
            retrieval_profile=retrieval_profile,
            index_alias=ActiveIndexAlias(
                IndexDescriptor(dimension, "cosine"),
                self.index_prefix,
                indexing_profile_id,
            ),
            result_limit=10,
        )
        retrieved = tuple(
            evidence.id
            for hit in hits
            if hit.chunk is not None
            for evidence in hit.chunk.evidence_units
        )
        matched = tuple(item for item in retrieved if item in case.expected_evidence_ids)
        highlight = case.expected_highlight if matched else None
        return SearchExecutionObservation(
            stable=StableObservation(
                retrieved_evidence_ids=retrieved,
                answer_status=(
                    case.expected_answer_status
                    if matched
                    else AnswerStatus.INSUFFICIENT_EVIDENCE
                ),
                answer_evidence_ids=matched[:1],
                conflict_evidence_ids=(),
                related_evidence_ids=tuple(item for item in retrieved if item not in matched),
                highlight_kind=highlight.kind if highlight else None,
                highlight_spans=highlight.spans if highlight else (),
                highlight_bboxes=highlight.bboxes if highlight else (),
            ),
            exposures=(),
            duration_ms=(perf_counter() - started) * 1000.0,
        )


def _mini_fixture() -> bytes:
    queries = (
        (
            UUID("00000000-0000-0000-0000-000000001101"),
            "위험등급 코드 A-17의 의미는?",
            EVIDENCE_A,
            "keyword",
        ),
        (
            UUID("00000000-0000-0000-0000-000000001102"),
            "환매를 미리 알려야 하는 기간은?",
            EVIDENCE_B,
            "semantic",
        ),
    )
    fixture = {
        "schema_version": 1,
        "id": str(UUID("00000000-0000-0000-0000-000000001200")),
        "name": "real same snapshot",
        "version": 1,
        "document_snapshot": [
            {"asset_version_id": str(uuid4()), "sha256": "a" * 64, "active": True}
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
                    "allowed_source_ids": [str(evidence_id)],
                    "forbidden_source_ids": [],
                    "as_of": "2026-08-31T00:00:00Z",
                },
                "expected": {
                    "answer_status": "supported",
                    "evidence_unit_ids": [str(evidence_id)],
                    "highlight": {
                        "kind": kind,
                        "spans": [[0, 4]],
                        "bboxes": [],
                    },
                },
            }
            for case_id, query, evidence_id, kind in queries
        ],
    }
    return json.dumps(fixture, ensure_ascii=False, indent=2).encode("utf-8")


def _index_documents(
    *,
    actor_id: UUID,
    dimension: int,
    projection_id: UUID,
    build_id: UUID,
) -> tuple[IndexDocument, ...]:
    values = (
        (EVIDENCE_A, "위험등급 코드 A-17은 고위험 상품을 뜻한다."),
        (EVIDENCE_B, "환매 신청은 영업일 기준 7일 전에 알려야 한다."),
    )
    embedding = DeterministicDenseEmbedding(dimension)
    documents: list[IndexDocument] = []
    for ordinal, (evidence_id, text) in enumerate(values):
        chunk_id = uuid4()
        evidence = EvidenceUnit(
            id=evidence_id,
            chunk_id=chunk_id,
            projection_id=projection_id,
            ordinal=0,
            text=text,
            location=SourceLocation(
                element_id=uuid4(),
                page=None,
                char_start=0,
                char_end=len(text),
                bbox=None,
            ),
        )
        documents.append(
            IndexDocument(
                chunk_id=chunk_id,
                projection_id=projection_id,
                asset_version_id=uuid4(),
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
    return tuple(documents)


@pytest.mark.asyncio
async def test_real_bm25_e5_bge_compare_the_same_snapshot_with_caller_saved_configs(
    isolated_evaluation_database_url: str,
) -> None:
    settings = Settings(
        _env_file=None,
        secret_key="task11-real-search-secret-key-value",
        database_url=isolated_evaluation_database_url,
        elasticsearch_url="http://host.docker.internal:9200",
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
            repository = SqlAlchemyEvaluationApplicationRepository(session)
            dataset = await repository.add_or_get_dataset(
                actor_id, load_evaluation_dataset(_mini_fixture())
            )
            await session.commit()
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
                repetition_count=2,
            )
            configuration_repository = SqlAlchemyRagConfigurationRepository(session)
            profiles = {
                BM25_RETRIEVAL_PROFILE_ID: await configuration_repository.find_profile(
                    BM25_RETRIEVAL_PROFILE_ID
                ),
                e5_hybrid.id: await configuration_repository.find_profile(e5_hybrid.id),
                BGE_RETRIEVAL_PROFILE_ID: await configuration_repository.find_profile(
                    BGE_RETRIEVAL_PROFILE_ID
                ),
            }
        indexer = IndexingService(
            ElasticsearchSearchIndex(client), index_prefix=settings.elasticsearch_index_prefix
        )
        for indexing_id, dimension in (
            (E5_INDEXING_PROFILE_ID, 768),
            (BGE_INDEXING_PROFILE_ID, 1024),
        ):
            projection_id = uuid4()
            build_id = uuid4()
            indexed = await indexer.index_projection(
                descriptor=IndexDescriptor(dimension, "cosine"),
                profile_id=indexing_id,
                build_id=build_id,
                projection_id=projection_id,
                expected_chunk_count=2,
                documents=_index_documents(
                    actor_id=actor_id,
                    dimension=dimension,
                    projection_id=projection_id,
                    build_id=build_id,
                ),
            )
            concrete_indices.append(indexed.index_name)
        bm25_profile = profiles[BM25_RETRIEVAL_PROFILE_ID]
        e5_profile = profiles[e5_hybrid.id]
        bge_profile = profiles[BGE_RETRIEVAL_PROFILE_ID]
        assert bm25_profile is not None
        assert e5_profile is not None
        assert bge_profile is not None
        candidate_profiles: dict[UUID, tuple[UUID, Profile, int]] = {
            configurations[0].version_id: (
                E5_INDEXING_PROFILE_ID,
                bm25_profile,
                768,
            ),
            configurations[1].version_id: (
                E5_INDEXING_PROFILE_ID,
                e5_profile,
                768,
            ),
            configurations[2].version_id: (
                BGE_INDEXING_PROFILE_ID,
                bge_profile,
                1024,
            ),
        }
        await EvaluationWorkflow(
            SqlAlchemyEvaluationRepository(sessions),
            RealElasticsearchCandidateSearch(
                client=client,
                profiles=candidate_profiles,
                index_prefix=settings.elasticsearch_index_prefix,
            ),
        ).run(run.id)
        async with sessions() as session:
            candidates = list(
                await session.scalars(
                    select(EvaluationRunConfigurationRecord)
                    .where(EvaluationRunConfigurationRecord.run_id == run.id)
                    .order_by(EvaluationRunConfigurationRecord.ordinal)
                )
            )
            assert [item.configuration_version_id for item in candidates] == [
                item.version_id for item in configurations
            ]
            assert all(item.status == "completed" for item in candidates)
            assert all(item.recall_at_k == 1.0 for item in candidates)
            assert all(item.reproducibility == 1.0 for item in candidates)
            snapshot_versions = {
                item.component_snapshot["configuration"]["version_id"]
                for item in candidates
            }
            assert snapshot_versions == {
                str(item.version_id) for item in configurations
            }
    finally:
        if concrete_indices:
            await client.indices.delete(index=",".join(concrete_indices), ignore_unavailable=True)
        await client.close()
        await engine.dispose()
