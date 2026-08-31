from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Literal, cast
from uuid import UUID

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.embeddings import SentenceTransformerEmbedding
from ai_workshop.labs.rag.embeddings.contracts import EmbeddingModelConfig, EmbeddingPort
from ai_workshop.labs.rag.evaluation.domain import EvaluationCase
from ai_workshop.labs.rag.evaluation.metrics import (
    AccessExposure,
    BoundingBox,
    CharacterSpan,
    HighlightObservation,
    StableObservation,
)
from ai_workshop.labs.rag.evaluation.repository import SqlAlchemyEvaluationRepository
from ai_workshop.labs.rag.evaluation.service import (
    CandidateExecutionInput,
    EvaluationSearchPort,
    EvaluationWorkflow,
    SearchExecutionObservation,
    capture_worker_runtime,
)
from ai_workshop.labs.rag.highlighting.domain import (
    AnswerPolicy,
    AnswerStatus,
    EvidenceSource,
)
from ai_workshop.labs.rag.highlighting.service import EvidenceSelector
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.models.domain import (
    EvaluationState,
    JsonValue,
    ModelDefinition,
    ModelKind,
    Profile,
    ProfileKind,
    ProfileModelBinding,
    freeze_json,
)
from ai_workshop.labs.rag.retrieval.domain import (
    FrozenIndexIdentity,
    FrozenIndexTarget,
    FusedHit,
    ResolvedSearchScope,
    RetrievedChunk,
)
from ai_workshop.labs.rag.retrieval.elasticsearch import (
    ElasticsearchDenseRetriever,
    ElasticsearchSparseRetriever,
    require_concrete_frozen_indices,
)
from ai_workshop.labs.rag.retrieval.service import HybridRetrievalService
from ai_workshop.shared.db import create_engine, create_session_factory
from ai_workshop.shared.errors import AppError


@dataclass(frozen=True, slots=True)
class FrozenResolvedScope:
    value: ResolvedSearchScope

    async def resolve(
        self,
        *,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
    ) -> ResolvedSearchScope:
        del actor_id
        if (
            workspace_ids != self.value.workspace_ids
            or folder_ids != self.value.folder_ids
        ):
            raise RuntimeError("The resolved Evaluation Search scope changed.")
        return self.value


@dataclass(frozen=True, slots=True)
class _FrozenConfiguration:
    indexing_profile_id: UUID
    retrieval_profile: Profile
    answer_policy_version_id: UUID
    answer_policy: AnswerPolicy
    embedding: EmbeddingPort


class FrozenSourceResolver:
    def __init__(self, snapshot: dict[str, object]) -> None:
        raw_sources = cast(list[dict[str, object]], snapshot.get("sources", []))
        self.sources = {
            UUID(str(item["chunk_id"])): item for item in raw_sources
        }

    def resolve(
        self,
        *,
        indexing_profile_id: UUID,
        hits: tuple[FusedHit, ...],
    ) -> tuple[EvidenceSource, ...]:
        resolved: list[EvidenceSource] = []
        for hit in hits:
            if not isinstance(hit.chunk_id, UUID) or hit.chunk is None:
                continue
            frozen = self.sources.get(hit.chunk_id)
            if frozen is None:
                continue
            if (
                UUID(str(frozen["indexing_profile_id"])) != indexing_profile_id
                or UUID(str(frozen["index_build_id"]))
                != hit.chunk.index_build_id
                or UUID(str(frozen["projection_id"])) != hit.chunk.projection_id
                or UUID(str(frozen["asset_version_id"]))
                != hit.chunk.asset_version_id
            ):
                raise RuntimeError("The frozen Evaluation source manifest drifted.")
            evidence = tuple(
                EvidenceUnit(
                    id=UUID(str(item["id"])),
                    chunk_id=hit.chunk_id,
                    projection_id=UUID(str(frozen["projection_id"])),
                    ordinal=int(cast(int, item["ordinal"])),
                    text=str(item["text"]),
                    location=SourceLocation(
                        element_id=UUID(str(item["element_id"])),
                        page=(
                            int(cast(int, item["page"]))
                            if item.get("page") is not None
                            else None
                        ),
                        char_start=int(cast(int, item["char_start"])),
                        char_end=int(cast(int, item["char_end"])),
                        bbox=(
                            cast(
                                tuple[float, float, float, float],
                                tuple(
                                    float(value)
                                    for value in cast(list[float], item["bbox"])
                                ),
                            )
                            if item.get("bbox") is not None
                            else None
                        ),
                    ),
                )
                for item in cast(list[dict[str, object]], frozen["evidence_units"])
            )
            workspace = cast(dict[str, object], frozen["workspace"])
            folder = cast(dict[str, object] | None, frozen.get("folder"))
            resolved.append(
                EvidenceSource(
                    document_id=UUID(str(frozen["document_id"])),
                    asset_version_number=int(
                        cast(int, frozen["asset_version_number"])
                    ),
                    media_type=str(frozen["media_type"]),
                    chunk=RetrievedChunk(
                        chunk_id=hit.chunk_id,
                        projection_id=UUID(str(frozen["projection_id"])),
                        asset_version_id=UUID(str(frozen["asset_version_id"])),
                        workspace_id=UUID(str(workspace["id"])),
                        folder_id=(
                            UUID(str(folder["id"])) if folder is not None else None
                        ),
                        index_build_id=UUID(str(frozen["index_build_id"])),
                        title=str(frozen["title"]),
                        section_path=tuple(
                            str(item)
                            for item in cast(list[str], frozen["section_path"])
                        ),
                        text=str(frozen["chunk_text"]),
                        evidence_units=evidence,
                    ),
                    fused_score=hit.score,
                )
            )
        return tuple(resolved)


class ProductionEvaluationSearch(EvaluationSearchPort):
    """Executes exact configuration versions with DB-free model/ES boundaries."""

    def __init__(
        self,
        settings: Settings,
        *,
        embedding_factory: Callable[[EmbeddingModelConfig], EmbeddingPort] | None = None,
    ) -> None:
        self.settings = settings
        self.elasticsearch = create_elasticsearch(settings)
        self.embedding_factory = embedding_factory or (
            lambda config: SentenceTransformerEmbedding(
                config,
                cache_folder=self.settings.model_cache_root,
            )
        )

    async def close(self) -> None:
        await self.elasticsearch.close()

    async def execute(
        self,
        *,
        actor_id: UUID,
        candidate: CandidateExecutionInput,
        case: EvaluationCase,
    ) -> SearchExecutionObservation:
        evaluation_case = case
        started = perf_counter()
        dimensions = {item.vector_dimension for item in candidate.index_builds}
        profile_ids = {item.indexing_profile_id for item in candidate.index_builds}
        mapping_versions = {item.mapping_version for item in candidate.index_builds}
        if len(dimensions) != 1 or len(profile_ids) != 1 or len(mapping_versions) != 1:
            raise RuntimeError("The frozen Evaluation index manifest is incompatible.")
        target = FrozenIndexTarget(
            descriptor=IndexDescriptor(
                next(iter(dimensions)),
                "cosine",
                mapping_version=next(iter(mapping_versions)),
            ),
            index_prefix=self.settings.elasticsearch_index_prefix,
            indexing_profile_id=next(iter(profile_ids)),
            identities=tuple(
                FrozenIndexIdentity(
                    index_name=item.index_name,
                    index_uuid=item.index_uuid,
                    index_build_id=item.index_build_id,
                    projection_id=item.projection_id,
                    indexing_profile_id=item.indexing_profile_id,
                    vector_dimension=item.vector_dimension,
                    mapping_version=item.mapping_version,
                )
                for item in candidate.index_builds
            ),
            asset_version_ids=tuple(
                item.asset_version_id
                for item in candidate.index_builds
                if item.active_at_snapshot
            ),
        )
        await require_concrete_frozen_indices(self.elasticsearch, target)
        configuration = self._resolve_configuration(candidate, target)
        scenario = evaluation_case.permission_scenario
        allowed_workspaces = (
            scenario.workspace_ids if candidate.is_system else candidate.workspace_ids
        )
        if not set(scenario.workspace_ids).issubset(allowed_workspaces):
            return _denied_observation(started)
        scope = self._resolve_scope(candidate, evaluation_case, actor_id)
        frozen_scope = ResolvedSearchScope(
            workspace_ids=scope.workspace_ids,
            folder_ids=scope.folder_ids,
            active_only=False,
            ready_only=True,
            asset_version_ids=target.asset_version_ids,
            index_build_ids=target.index_build_ids,
        )
        hits = await HybridRetrievalService(
            scope_resolver=FrozenResolvedScope(frozen_scope),
            embedding=configuration.embedding,
            sparse_retriever=ElasticsearchSparseRetriever(self.elasticsearch),
            dense_retriever=ElasticsearchDenseRetriever(self.elasticsearch),
        ).search(
            actor_id=actor_id,
            query=evaluation_case.query,
            workspace_ids=frozen_scope.workspace_ids,
            folder_ids=frozen_scope.folder_ids,
            indexing_profile_id=configuration.indexing_profile_id,
            retrieval_profile=configuration.retrieval_profile,
            index_alias=target,
            result_limit=candidate.retrieval_k,
        )
        if candidate.execution_snapshot is None:
            raise RuntimeError("The frozen Evaluation execution snapshot is unavailable.")
        sources = FrozenSourceResolver(dict(candidate.execution_snapshot)).resolve(
            indexing_profile_id=configuration.indexing_profile_id,
            hits=hits,
        )
        policy = configuration.answer_policy
        if policy is None or configuration.answer_policy_version_id is None:
            raise AppError(
                "answer_policy_missing",
                "The selected search configuration has no answer policy version.",
                409,
            )
        selection = EvidenceSelector(configuration.embedding).select(
            query=evaluation_case.query.strip(),
            sources=sources,
            policy=policy,
        )
        answer = selection.answer
        conflicts = selection.conflicts
        selected = tuple(item for item in ((answer,) if answer else ()) + conflicts)
        selected_ids = {item.evidence.id for item in selected}
        related_ids = tuple(
            evidence.id
            for source in sources
            for evidence in source.chunk.evidence_units
            if evidence.id not in selected_ids
        )
        retrieved_ids = tuple(
            evidence.id for source in sources for evidence in source.chunk.evidence_units
        )
        highlights = tuple(
            ("answer" if selected_item is answer else "conflict", selected_item, item)
            for selected_item in selected
            for item in selected_item.highlights
        )
        exposures: list[AccessExposure] = []
        exposures.extend(
            AccessExposure("retrieval", evidence.id)
            for hit in hits
            if hit.chunk is not None
            for evidence in hit.chunk.evidence_units
        )
        for source in sources:
            for evidence in source.chunk.evidence_units:
                exposures.append(
                    AccessExposure(
                        "case_output",
                        evidence.id,
                    )
                )
        for selected_item in selected:
            surface = "answer" if selected_item is answer else "conflict"
            exposures.append(
                AccessExposure(
                    surface,
                    selected_item.evidence.id,
                )
            )
        exposures.extend(
            AccessExposure("related_source", evidence_id)
            for evidence_id in related_ids
        )
        exposures.extend(
            AccessExposure("highlight", item.evidence_unit_id)
            for _, _, item in highlights
        )
        return SearchExecutionObservation(
            stable=StableObservation(
                retrieved_evidence_ids=retrieved_ids,
                answer_status=selection.status,
                answer_evidence_ids=(answer.evidence.id,) if answer else (),
                conflict_evidence_ids=tuple(item.evidence.id for item in conflicts),
                related_evidence_ids=related_ids,
                highlight_kind=highlights[0][2].kind if highlights else None,
                # Structured highlights below keep answer/conflict coordinates separate.
                highlight_spans=(),
                highlight_bboxes=(),
                highlights=tuple(
                    HighlightObservation(
                        surface=surface,
                        document_id=selected_item.source.document_id,
                        asset_version_id=selected_item.source.chunk.asset_version_id,
                        evidence_unit_id=item.evidence_unit_id,
                        page=item.page,
                        kind=item.kind,
                        spans=(CharacterSpan(item.char_start, item.char_end),)
                        if item.bbox is None
                        else (),
                        bboxes=(BoundingBox(*item.bbox),)
                        if item.bbox is not None
                        else (),
                    )
                    for surface, selected_item, item in highlights
                ),
            ),
            exposures=tuple(exposures),
            duration_ms=(perf_counter() - started) * 1000.0,
        )

    def _resolve_scope(
        self,
        candidate: CandidateExecutionInput,
        case: EvaluationCase,
        actor_id: UUID,
    ) -> ResolvedSearchScope:
        snapshot = candidate.execution_snapshot
        if snapshot is None:
            raise RuntimeError("The frozen Evaluation execution snapshot is unavailable.")
        scopes = [
            item
            for item in cast(
                list[dict[str, object]], snapshot.get("permission_scopes", [])
            )
            if item.get("case_id") == str(case.id)
        ]
        if len(scopes) != 1:
            raise RuntimeError("The frozen Evaluation permission scope is unavailable.")
        scope = scopes[0]
        scenario = case.permission_scenario
        if (
            scope.get("actor_id") != str(actor_id)
            or cast(list[str], scope["workspace_ids"])
            != [str(item) for item in scenario.workspace_ids]
            or cast(list[str], scope["folder_ids"])
            != [str(item) for item in scenario.folder_ids]
            or set(cast(list[str], scope["authorized_source_ids"]))
            != {str(item) for item in scenario.authorized_source_ids}
            or set(cast(list[str], scope["forbidden_source_ids"]))
            != {str(item) for item in scenario.forbidden_source_ids}
            or scope.get("as_of") != scenario.as_of
        ):
            raise RuntimeError("The frozen Evaluation permission scope drifted.")
        return ResolvedSearchScope(
            workspace_ids=scenario.workspace_ids,
            folder_ids=scenario.folder_ids,
            active_only=False,
            ready_only=True,
        )

    def _resolve_configuration(
        self,
        candidate: CandidateExecutionInput,
        target: FrozenIndexTarget,
    ) -> _FrozenConfiguration:
        snapshot = candidate.component_snapshot
        execution_snapshot = candidate.execution_snapshot
        if snapshot is None or execution_snapshot is None:
            raise RuntimeError("The frozen Evaluation component snapshot is unavailable.")
        manifest_candidates = [
            item
            for item in cast(
                list[dict[str, object]], execution_snapshot.get("candidates", [])
            )
            if item.get("configuration_version_id")
            == str(candidate.configuration_version_id)
        ]
        component_without_hash = {
            key: value
            for key, value in snapshot.items()
            if key != "execution_snapshot_sha256"
        }
        if (
            len(manifest_candidates) != 1
            or manifest_candidates[0].get("component_snapshot")
            != component_without_hash
        ):
            raise RuntimeError("The frozen Evaluation component manifest drifted.")
        configuration = cast(dict[str, object], snapshot["configuration"])
        if configuration.get("version_id") != str(candidate.configuration_version_id):
            raise RuntimeError("The frozen Evaluation configuration version drifted.")
        profiles = cast(list[dict[str, object]], snapshot["profiles"])
        indexing = next(
            (
                item
                for item in profiles
                if item.get("id") == str(target.indexing_profile_id)
                and item.get("kind") == ProfileKind.INDEXING.value
            ),
            None,
        )
        retrieval_id = next(
            profile_id
            for profile_id in (
                item.get("id") for item in profiles if item.get("kind") == "retrieval"
            )
            if profile_id is not None
        )
        retrieval = next(item for item in profiles if item.get("id") == retrieval_id)
        if indexing is None:
            raise RuntimeError("The frozen Evaluation indexing profile is unavailable.")
        retrieval_config = cast(dict[str, JsonValue], retrieval["config"])
        if retrieval_config.get("indexing_profile_id") != str(target.indexing_profile_id):
            raise RuntimeError("The frozen Evaluation retrieval profile is incompatible.")
        bindings = cast(list[dict[str, object]], snapshot["bindings"])
        embedding_bindings = [
            item
            for item in bindings
            if item.get("profile_id") == str(target.indexing_profile_id)
            and item.get("role") == ModelKind.EMBEDDING.value
        ]
        if len(embedding_bindings) != 1:
            raise RuntimeError("The frozen Evaluation embedding binding is unavailable.")
        model_id = str(embedding_bindings[0]["model_id"])
        model_raw = next(
            (
                item
                for item in cast(list[dict[str, object]], snapshot["models"])
                if item.get("id") == model_id
            ),
            None,
        )
        if model_raw is None:
            raise RuntimeError("The frozen Evaluation embedding model is unavailable.")
        model_config = cast(dict[str, JsonValue], model_raw["config"])
        frozen_model_config = freeze_json(model_config)
        if not isinstance(frozen_model_config, Mapping):
            raise RuntimeError("The frozen Evaluation model config is invalid.")
        model = ModelDefinition(
            id=UUID(model_id),
            kind=ModelKind(str(model_raw["kind"])),
            name=str(model_raw["name"]),
            version=int(cast(int, model_raw["version"])),
            config=frozen_model_config,
        )
        indexing_config = cast(dict[str, JsonValue], indexing["config"])
        embedding_profile = indexing_config.get("embedding")
        if not isinstance(embedding_profile, dict):
            raise RuntimeError("The frozen Evaluation embedding profile is unavailable.")
        embedding_config = EmbeddingModelConfig.from_definition(
            model,
            profile_config=embedding_profile,
        )
        if embedding_config.dimension != target.descriptor.vector_dimension:
            raise RuntimeError("The frozen Evaluation model/index dimension drifted.")
        frozen_retrieval_config = freeze_json(retrieval_config)
        if not isinstance(frozen_retrieval_config, Mapping):
            raise RuntimeError("The frozen Evaluation retrieval config is invalid.")
        retrieval_profile = Profile(
            id=UUID(str(retrieval["id"])),
            kind=ProfileKind.RETRIEVAL,
            name=str(retrieval["name"]),
            version=int(cast(int, retrieval["version"])),
            config=frozen_retrieval_config,
            bindings=tuple(
                ProfileModelBinding(
                    role=ModelKind(str(item["role"])),
                    model_id=UUID(str(item["model_id"])),
                )
                for item in bindings
                if item.get("profile_id") == str(retrieval["id"])
            ),
            evaluation_state=EvaluationState.DRAFT,
        )
        policy = cast(dict[str, object], snapshot["answer_policy"])
        answer_policy = AnswerPolicy(
            min_semantic_score=float(cast(float, policy["min_semantic_score"])),
            min_keyword_coverage=float(
                cast(float, policy["min_keyword_coverage"])
            ),
            require_complete_provenance=bool(policy["require_complete_provenance"]),
            conflict_mode=cast(
                Literal["separate_sources"], str(policy["conflict_mode"])
            ),
        )
        return _FrozenConfiguration(
            indexing_profile_id=target.indexing_profile_id,
            retrieval_profile=retrieval_profile,
            answer_policy_version_id=UUID(str(policy["id"])),
            answer_policy=answer_policy,
            embedding=self.embedding_factory(embedding_config),
        )


def _denied_observation(started: float) -> SearchExecutionObservation:
    return SearchExecutionObservation(
        stable=StableObservation(
            retrieved_evidence_ids=(),
            answer_status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            answer_evidence_ids=(),
            conflict_evidence_ids=(),
            related_evidence_ids=(),
            highlight_kind=None,
            highlight_spans=(),
            highlight_bboxes=(),
        ),
        exposures=(),
        duration_ms=(perf_counter() - started) * 1000.0,
    )


class ClosingEvaluationWorkflow(EvaluationWorkflow):
    def __init__(
        self,
        repository: SqlAlchemyEvaluationRepository,
        search: ProductionEvaluationSearch,
        close_repository: Callable[[], Awaitable[None]],
        runtime_provider: Callable[[], dict[str, object]],
    ) -> None:
        super().__init__(repository, search, runtime_provider=runtime_provider)
        self.production_search = search
        self.close_repository = close_repository

    async def run(self, run_id: UUID) -> None:
        try:
            await super().run(run_id)
        finally:
            await self.production_search.close()
            await self.close_repository()


def create_evaluation_workflow(settings: Settings) -> EvaluationWorkflow:
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    search = ProductionEvaluationSearch(settings)
    workflow = ClosingEvaluationWorkflow(
        SqlAlchemyEvaluationRepository(sessions),
        search,
        engine.dispose,
        lambda: capture_worker_runtime(environment=settings.environment),
    )
    return workflow
