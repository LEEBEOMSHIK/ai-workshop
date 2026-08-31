import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.configurations.models import (
    AnswerPolicyVersionRecord,
    RagConfigurationRecord,
    RagConfigurationVersionRecord,
    RagConfigurationWorkspaceSubscriptionRecord,
)
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagIndexBuildRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
)
from ai_workshop.labs.rag.evaluation.dispatch import EvaluationDispatchClaim
from ai_workshop.labs.rag.evaluation.domain import (
    CandidateStatus,
    EvaluationDataset,
    EvaluationMetrics,
    EvaluationPolicy,
    EvaluationRunStatus,
    PermissionScenario,
    load_evaluation_dataset,
)
from ai_workshop.labs.rag.evaluation.metrics import (
    AccessExposure,
    BoundingBox,
    CharacterSpan,
    HighlightObservation,
    StableObservation,
)
from ai_workshop.labs.rag.evaluation.models import (
    EvaluationCaseResultRecord,
    EvaluationDatasetCaseRecord,
    EvaluationDatasetRecord,
    EvaluationDispatchRecord,
    EvaluationPolicyRecord,
    EvaluationRunConfigurationRecord,
    EvaluationRunRecord,
)
from ai_workshop.labs.rag.evaluation.service import (
    CandidateExecutionInput,
    CandidateIndexBuildSnapshot,
    CaseEvaluationResult,
    EvaluationCandidateView,
    EvaluationRunClaim,
    EvaluationRunView,
    SearchExecutionObservation,
)
from ai_workshop.labs.rag.highlighting.domain import AnswerStatus, HighlightKind
from ai_workshop.labs.rag.models.models import (
    ModelDefinitionRecord,
    ProfileModelBindingRecord,
    ProfileRecord,
)
from ai_workshop.labs.rag.retrieval.domain import FrozenIndexIdentity
from ai_workshop.labs.rag.retrieval.elasticsearch import (
    FrozenIndexDriftError,
    FrozenIndexReindexRequiredError,
)
from ai_workshop.platform.assets.models import (
    AssetVersionRecord,
    DocumentRecord,
    FolderRecord,
)
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.shared.errors import AppError


class EvaluationDispatchClaimLostError(RuntimeError):
    pass


class EvaluationRunClaimLostError(RuntimeError):
    pass


def _dataset_domain(record: EvaluationDatasetRecord) -> EvaluationDataset:
    dataset = load_evaluation_dataset(record.fixture_bytes)
    if (
        dataset.name != record.name
        or dataset.version != record.version
        or dataset.fixture_sha256 != record.fixture_sha256
        or dataset.document_snapshot_sha256 != record.document_snapshot_sha256
        or dataset.query_set_sha256 != record.query_set_sha256
        or len(dataset.cases) != record.case_count
        or [dict(item) for item in dataset.document_snapshot] != record.document_snapshot
        or dataset.document_snapshot_bytes != record.document_snapshot_bytes
        or dataset.query_set_bytes != record.query_set_bytes
    ):
        raise RuntimeError("The immutable Evaluation Dataset snapshot is corrupt.")
    return replace(dataset, id=record.id)


def _policy_domain(record: EvaluationPolicyRecord) -> EvaluationPolicy:
    return EvaluationPolicy(
        id=record.id,
        owner_id=record.owner_id,
        dataset_snapshot_id=record.dataset_snapshot_id,
        version=record.version,
        metric_definition_version=record.metric_definition_version,
        retrieval_k=record.retrieval_k,
        recall_at_k=record.min_recall_at_k,
        mrr=record.min_mrr,
        ndcg=record.min_ndcg,
        supported_precision=record.min_supported_precision,
        max_false_grounding_rate=record.max_false_grounding_rate,
        min_highlight_iou=record.min_highlight_iou,
        max_p50_latency_ms=record.max_p50_latency_ms,
        max_p95_latency_ms=record.max_p95_latency_ms,
        max_access_leaks=record.max_access_leaks,
        required_reproducibility=record.required_reproducibility,
    ).validate()


def _metrics(record: EvaluationRunConfigurationRecord) -> EvaluationMetrics | None:
    values = (
        record.recall_at_k,
        record.mrr,
        record.ndcg,
        record.supported_precision,
        record.false_grounding_rate,
        record.highlight_iou,
        record.p50_latency_ms,
        record.p95_latency_ms,
        record.access_leaks,
        record.reproducibility,
    )
    if any(value is None for value in values):
        return None
    return EvaluationMetrics(
        recall_at_k=cast(float, record.recall_at_k),
        mrr=cast(float, record.mrr),
        ndcg=cast(float, record.ndcg),
        supported_precision=cast(float, record.supported_precision),
        false_grounding_rate=cast(float, record.false_grounding_rate),
        highlight_iou=cast(float, record.highlight_iou),
        p50_latency_ms=cast(float, record.p50_latency_ms),
        p95_latency_ms=cast(float, record.p95_latency_ms),
        access_leaks=cast(int, record.access_leaks),
        reproducibility=cast(float, record.reproducibility),
    )


def _scenario_json(value: object) -> dict[str, object]:
    scenario = cast(PermissionScenario, value)
    return {
        "name": scenario.name,
        "actor": scenario.actor,
        "workspace_ids": [str(item) for item in scenario.workspace_ids],
        "folder_ids": [str(item) for item in scenario.folder_ids],
        "authorized_source_ids": sorted(
            str(item) for item in scenario.authorized_source_ids
        ),
        "forbidden_source_ids": sorted(
            str(item) for item in scenario.forbidden_source_ids
        ),
        "as_of": scenario.as_of,
    }


def _scenario_domain(value: dict[str, object]) -> PermissionScenario:
    return PermissionScenario(
        name=str(value["name"]),
        actor=str(value["actor"]),
        workspace_ids=tuple(UUID(item) for item in cast(list[str], value["workspace_ids"])),
        folder_ids=tuple(UUID(item) for item in cast(list[str], value["folder_ids"])),
        authorized_source_ids=frozenset(
            UUID(item) for item in cast(list[str], value["authorized_source_ids"])
        ),
        forbidden_source_ids=frozenset(
            UUID(item) for item in cast(list[str], value["forbidden_source_ids"])
        ),
        as_of=str(value["as_of"]),
    )


def _observation_json(value: SearchExecutionObservation) -> dict[str, object]:
    stable = value.stable
    source_ids = {
        (item.surface, cast(UUID, item.evidence_id)): item.source_id
        for item in value.exposures
    }
    stable_payload: dict[str, object] = {
        "retrieved_evidence_ids": [str(item) for item in stable.retrieved_evidence_ids],
        "retrieved_ranked": [
            {
                "rank": rank,
                "evidence_id": str(evidence_id),
                "source_id": str(source_ids[("retrieval", evidence_id)]),
            }
            for rank, evidence_id in enumerate(stable.retrieved_evidence_ids, start=1)
        ],
        "answer_status": stable.answer_status.value,
        "answer_evidence_ids": [str(item) for item in stable.answer_evidence_ids],
        "conflict_evidence_ids": [str(item) for item in stable.conflict_evidence_ids],
        "related_evidence_ids": [str(item) for item in stable.related_evidence_ids],
        "answer_sources": [
            {
                "evidence_id": str(item),
                "source_id": str(source_ids[("answer", item)]),
            }
            for item in stable.answer_evidence_ids
        ],
        "conflict_sources": [
            {
                "evidence_id": str(item),
                "source_id": str(source_ids[("conflict", item)]),
            }
            for item in stable.conflict_evidence_ids
        ],
        "related_sources": [
            {
                "evidence_id": str(item),
                "source_id": str(source_ids[("related_source", item)]),
            }
            for item in stable.related_evidence_ids
        ],
        "highlight_kind": stable.highlight_kind.value if stable.highlight_kind else None,
        "highlight_spans": [[item.start, item.end] for item in stable.highlight_spans],
        "highlight_bboxes": [
            [item.x0, item.y0, item.x1, item.y1] for item in stable.highlight_bboxes
        ],
        "highlights": [
            {
                "surface": item.surface,
                "document_id": str(item.document_id),
                "asset_version_id": str(item.asset_version_id),
                "evidence_unit_id": str(item.evidence_unit_id),
                "source_id": str(
                    source_ids[(f"{item.surface}_highlight", item.evidence_unit_id)]
                ),
                "page": item.page,
                "kind": item.kind.value,
                "spans": [[span.start, span.end] for span in item.spans],
                "bboxes": [
                    [box.x0, box.y0, box.x1, box.y1] for box in item.bboxes
                ],
            }
            for item in stable.highlights
        ],
    }
    signature = hashlib.sha256(
        json.dumps(
            stable_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        **stable_payload,
        "exposures": [
            {
                "surface": item.surface,
                "source_id": str(item.source_id),
                "evidence_id": str(item.evidence_id),
            }
            for item in value.exposures
        ],
        "duration_ms": value.duration_ms,
        "repetition_signature_sha256": signature,
    }


def _observation_domain(value: dict[str, object]) -> SearchExecutionObservation:
    highlight = value.get("highlight_kind")
    return SearchExecutionObservation(
        stable=StableObservation(
            retrieved_evidence_ids=tuple(
                UUID(item)
                for item in cast(list[str], value["retrieved_evidence_ids"])
            ),
            answer_status=AnswerStatus(str(value["answer_status"])),
            answer_evidence_ids=tuple(
                UUID(item) for item in cast(list[str], value["answer_evidence_ids"])
            ),
            conflict_evidence_ids=tuple(
                UUID(item)
                for item in cast(list[str], value["conflict_evidence_ids"])
            ),
            related_evidence_ids=tuple(
                UUID(item)
                for item in cast(list[str], value["related_evidence_ids"])
            ),
            highlight_kind=HighlightKind(str(highlight)) if highlight is not None else None,
            highlight_spans=tuple(
                CharacterSpan(int(item[0]), int(item[1]))
                for item in cast(list[list[int]], value["highlight_spans"])
            ),
            highlight_bboxes=tuple(
                BoundingBox(*(float(coordinate) for coordinate in item))
                for item in cast(list[list[float]], value["highlight_bboxes"])
            ),
            highlights=tuple(
                HighlightObservation(
                    surface=str(item["surface"]),
                    document_id=UUID(str(item["document_id"])),
                    asset_version_id=UUID(str(item["asset_version_id"])),
                    evidence_unit_id=UUID(str(item["evidence_unit_id"])),
                    page=(
                        int(cast(int, item["page"]))
                        if item.get("page") is not None
                        else None
                    ),
                    kind=HighlightKind(str(item["kind"])),
                    spans=tuple(
                        CharacterSpan(int(span[0]), int(span[1]))
                        for span in cast(list[list[int]], item["spans"])
                    ),
                    bboxes=tuple(
                        BoundingBox(*(float(coordinate) for coordinate in box))
                        for box in cast(list[list[float]], item["bboxes"])
                    ),
                )
                for item in cast(
                    list[dict[str, object]], value.get("highlights", [])
                )
            ),
        ),
        exposures=tuple(
            AccessExposure(
                surface=str(item["surface"]),
                source_id=UUID(str(item["source_id"])),
                evidence_id=UUID(str(item["evidence_id"])),
            )
            for item in cast(list[dict[str, object]], value["exposures"])
        ),
        duration_ms=float(cast(str | int | float, value["duration_ms"])),
    )


def _case_domain(record: EvaluationCaseResultRecord) -> CaseEvaluationResult:
    return CaseEvaluationResult(
        evaluation_case_id=record.evaluation_case_id,
        ordinal=record.ordinal,
        query_sha256=record.query_sha256,
        permission_scenario=_scenario_domain(record.permission_scenario),
        expected_evidence_ids=frozenset(UUID(item) for item in record.expected_evidence_ids),
        raw_observations=tuple(
            _observation_domain(item) for item in record.raw_observations
        ),
        duration_ms=record.duration_ms,
        recall_at_k=record.recall_at_k,
        reciprocal_rank=record.reciprocal_rank,
        ndcg=record.ndcg,
        correct_supported=record.correct_supported,
        false_grounding=record.false_grounding,
        highlight_iou=record.highlight_iou,
        access_leaks=record.access_leaks,
        reproducible=record.reproducible,
    )


class FrozenIndexInspectorPort(Protocol):
    async def describe(self, index_name: str) -> FrozenIndexIdentity: ...


class SqlAlchemyEvaluationApplicationRepository:
    def __init__(
        self,
        session: AsyncSession,
        *,
        index_inspector: FrozenIndexInspectorPort | None = None,
    ) -> None:
        self.session = session
        self.index_inspector = index_inspector

    async def add_or_get_dataset(
        self, actor_id: UUID, dataset: EvaluationDataset
    ) -> EvaluationDataset:
        existing = await self.session.scalar(
            select(EvaluationDatasetRecord).where(
                EvaluationDatasetRecord.owner_id == actor_id,
                EvaluationDatasetRecord.fixture_sha256 == dataset.fixture_sha256,
            )
        )
        if existing is not None:
            if existing.fixture_bytes != dataset.fixture_bytes:
                raise RuntimeError("A dataset hash collision was detected.")
            return _dataset_domain(existing)
        record_id = dataset.id
        if await self.session.get(EvaluationDatasetRecord, record_id) is not None:
            record_id = uuid4()
        record = EvaluationDatasetRecord(
            id=record_id,
            owner_id=actor_id,
            name=dataset.name,
            version=dataset.version,
            fixture_bytes=dataset.fixture_bytes,
            fixture_sha256=dataset.fixture_sha256,
            document_snapshot=[dict(item) for item in dataset.document_snapshot],
            document_snapshot_bytes=dataset.document_snapshot_bytes,
            document_snapshot_sha256=dataset.document_snapshot_sha256,
            query_set_sha256=dataset.query_set_sha256,
            query_set_bytes=dataset.query_set_bytes,
            case_count=len(dataset.cases),
        )
        self.session.add(record)
        await self.session.flush()
        fixture = cast(dict[str, object], json.loads(dataset.fixture_bytes))
        raw_cases = cast(list[dict[str, object]], fixture["cases"])
        for ordinal, (case, raw_case) in enumerate(
            zip(dataset.cases, raw_cases, strict=True)
        ):
            canonical = json.dumps(
                raw_case,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            expected = cast(dict[str, object], raw_case["expected"])
            self.session.add(
                EvaluationDatasetCaseRecord(
                    id=case.id,
                    dataset_snapshot_id=record_id,
                    ordinal=ordinal,
                    canonical_case_bytes=canonical,
                    canonical_case_sha256=hashlib.sha256(canonical).hexdigest(),
                    query_bytes=case.query.encode("utf-8"),
                    query_sha256=case.query_sha256,
                    permission_scenario=_scenario_json(case.permission_scenario),
                    expected_evidence_ids=sorted(
                        str(item) for item in case.expected_evidence_ids
                    ),
                    authorized_source_ids=sorted(
                        str(item)
                        for item in case.permission_scenario.authorized_source_ids
                    ),
                    forbidden_source_ids=sorted(
                        str(item)
                        for item in case.permission_scenario.forbidden_source_ids
                    ),
                    expected_highlight=cast(
                        dict[str, object] | None, expected.get("highlight")
                    ),
                )
            )
        await self.session.flush()
        return replace(dataset, id=record_id)

    async def find_dataset_visible(
        self, dataset_snapshot_id: UUID, actor_id: UUID
    ) -> EvaluationDataset | None:
        record = await self.session.scalar(
            select(EvaluationDatasetRecord).where(
                EvaluationDatasetRecord.id == dataset_snapshot_id,
                EvaluationDatasetRecord.owner_id == actor_id,
            )
        )
        return _dataset_domain(record) if record is not None else None

    async def next_policy_version(
        self, actor_id: UUID, dataset_snapshot_id: UUID
    ) -> int:
        latest = await self.session.scalar(
            select(func.max(EvaluationPolicyRecord.version)).where(
                EvaluationPolicyRecord.owner_id == actor_id,
                EvaluationPolicyRecord.dataset_snapshot_id == dataset_snapshot_id,
            )
        )
        return int(latest or 0) + 1

    async def add_policy(
        self, actor_id: UUID, policy: EvaluationPolicy
    ) -> EvaluationPolicy:
        if policy.owner_id != actor_id:
            raise AppError("not_found", "The requested resource was not found.", 404)
        record = EvaluationPolicyRecord(
            id=policy.id,
            owner_id=actor_id,
            dataset_snapshot_id=policy.dataset_snapshot_id,
            version=policy.version,
            metric_definition_version=policy.metric_definition_version,
            retrieval_k=policy.retrieval_k,
            min_recall_at_k=policy.recall_at_k,
            min_mrr=policy.mrr,
            min_ndcg=policy.ndcg,
            min_supported_precision=policy.supported_precision,
            max_false_grounding_rate=policy.max_false_grounding_rate,
            min_highlight_iou=policy.min_highlight_iou,
            max_p50_latency_ms=policy.max_p50_latency_ms,
            max_p95_latency_ms=policy.max_p95_latency_ms,
            max_access_leaks=policy.max_access_leaks,
            required_reproducibility=policy.required_reproducibility,
        )
        self.session.add(record)
        await self.session.flush()
        return _policy_domain(record)

    async def _configuration_snapshot(
        self, version_id: UUID, actor_id: UUID, dataset: EvaluationDataset
    ) -> tuple[RagConfigurationVersionRecord, dict[str, object]] | None:
        configuration_row = (
            await self.session.execute(
                select(RagConfigurationVersionRecord, RagConfigurationRecord)
                .join(
                    RagConfigurationRecord,
                    RagConfigurationRecord.id
                    == RagConfigurationVersionRecord.configuration_id,
                )
                .where(
                    RagConfigurationVersionRecord.id == version_id,
                    or_(
                        RagConfigurationRecord.is_system.is_(True),
                        RagConfigurationRecord.owner_id == actor_id,
                    ),
                )
            )
        ).one_or_none()
        if configuration_row is None:
            return None
        version, identity = configuration_row
        profiles = list(
            await self.session.scalars(
                select(ProfileRecord).where(
                    ProfileRecord.id.in_(
                        tuple(
                            item
                            for item in (
                                version.indexing_profile_id,
                                version.retrieval_profile_id,
                                version.generation_profile_id,
                            )
                            if item is not None
                        )
                    )
                )
            )
        )
        bindings = list(
            await self.session.scalars(
                select(ProfileModelBindingRecord).where(
                    ProfileModelBindingRecord.profile_id.in_([item.id for item in profiles])
                )
            )
        )
        models = list(
            await self.session.scalars(
                select(ModelDefinitionRecord).where(
                    ModelDefinitionRecord.id.in_([item.model_id for item in bindings])
                )
            )
        )
        policy = await self.session.get(
            AnswerPolicyVersionRecord, version.answer_policy_version_id
        )
        if policy is None:
            raise RuntimeError("The immutable Answer Policy is unavailable.")
        workspace_ids = tuple(
            await self.session.scalars(
                select(RagConfigurationWorkspaceSubscriptionRecord.workspace_id)
                .where(
                    RagConfigurationWorkspaceSubscriptionRecord.configuration_version_id
                    == version.id
                )
                .order_by(RagConfigurationWorkspaceSubscriptionRecord.workspace_id)
            )
        )
        document_items = tuple(
            cast(dict[str, object], item) for item in dataset.document_snapshot
        )
        asset_ids = tuple(
            UUID(str(item["asset_version_id"])) for item in document_items
        )
        index_rows = (
            await self.session.execute(
                select(
                    AssetVersionRecord,
                    DocumentRecord,
                    RagProjectionRecord,
                    RagIndexBuildRecord,
                )
                .join(DocumentRecord, DocumentRecord.id == AssetVersionRecord.document_id)
                .join(
                    RagProjectionRecord,
                    RagProjectionRecord.asset_version_id == AssetVersionRecord.id,
                )
                .join(
                    RagIndexBuildRecord,
                    RagIndexBuildRecord.projection_id == RagProjectionRecord.id,
                )
                .where(
                    AssetVersionRecord.id.in_(asset_ids),
                    RagProjectionRecord.indexing_profile_id
                    == version.indexing_profile_id,
                    RagIndexBuildRecord.indexing_profile_id
                    == version.indexing_profile_id,
                    RagIndexBuildRecord.status == "ready",
                )
            )
        ).all()
        rows_by_asset = {row[0].id: row for row in index_rows}
        frozen_builds: list[dict[str, object]] = []
        for item in document_items:
            asset_id = UUID(str(item["asset_version_id"]))
            frozen_row = rows_by_asset.get(asset_id)
            if frozen_row is None:
                raise AppError(
                    "evaluation_snapshot_drift",
                    "Every frozen Asset Version requires an exact READY index build.",
                    409,
                )
            asset, document, projection, build = frozen_row
            expected_active = bool(item["active"])
            if (
                document.id != UUID(str(item["document_id"]))
                or asset.sha256 != str(item["sha256"])
                or expected_active != (document.active_version_id == asset.id)
                or build.index_name is None
                or build.vector_dimension is None
            ):
                raise AppError(
                    "evaluation_snapshot_drift",
                    "The dataset no longer matches its exact document/index snapshot.",
                    409,
                )
            if self.index_inspector is None:
                raise AppError(
                    "evaluation_index_reindex_required",
                    "Evaluation run creation requires an exact Elasticsearch index identity.",
                    409,
                )
            try:
                es_identity = await self.index_inspector.describe(build.index_name)
            except FrozenIndexReindexRequiredError as exc:
                raise AppError(
                    "evaluation_index_reindex_required",
                    "The exact physical index must be reindexed with immutable RAG metadata.",
                    409,
                ) from exc
            except FrozenIndexDriftError as exc:
                raise AppError(
                    "evaluation_snapshot_drift",
                    "The exact physical index no longer matches the database build.",
                    409,
                ) from exc
            if (
                es_identity.index_name != build.index_name
                or es_identity.index_build_id != build.id
                or es_identity.projection_id != projection.id
                or es_identity.indexing_profile_id != build.indexing_profile_id
                or es_identity.vector_dimension != build.vector_dimension
            ):
                raise AppError(
                    "evaluation_snapshot_drift",
                    "The physical index descriptor does not match the exact database build.",
                    409,
                )
            frozen_builds.append(
                {
                    "asset_version_id": str(asset.id),
                    "projection_id": str(projection.id),
                    "index_build_id": str(build.id),
                    "index_name": build.index_name,
                    "indexing_profile_id": str(build.indexing_profile_id),
                    "vector_dimension": build.vector_dimension,
                    "index_uuid": es_identity.index_uuid,
                    "mapping_version": es_identity.mapping_version,
                    "active_at_snapshot": expected_active,
                }
            )
        snapshot: dict[str, object] = {
            "configuration": {
                "id": str(identity.id),
                "version_id": str(version.id),
                "version": version.version,
                "is_system": identity.is_system,
                "workspace_ids": [str(item) for item in workspace_ids],
            },
            "profiles": [
                {
                    "id": str(item.id),
                    "kind": item.kind,
                    "name": item.name,
                    "version": item.version,
                    "config": item.config,
                }
                for item in sorted(profiles, key=lambda value: str(value.id))
            ],
            "bindings": [
                {
                    "id": str(item.id),
                    "profile_id": str(item.profile_id),
                    "role": item.role,
                    "model_id": str(item.model_id),
                }
                for item in sorted(bindings, key=lambda value: str(value.id))
            ],
            "models": [
                {
                    "id": str(item.id),
                    "kind": item.kind,
                    "name": item.name,
                    "version": item.version,
                    "config": item.config,
                }
                for item in sorted(models, key=lambda value: str(value.id))
            ],
            "answer_policy": {
                "id": str(policy.id),
                "version": policy.version,
                "mode": policy.mode,
                "min_semantic_score": policy.min_semantic_score,
                "min_keyword_coverage": policy.min_keyword_coverage,
                "require_complete_provenance": policy.require_complete_provenance,
                "conflict_mode": policy.conflict_mode,
            },
            "index_builds": frozen_builds,
        }
        return version, snapshot

    async def create_run(
        self,
        *,
        actor_id: UUID,
        dataset: EvaluationDataset,
        evaluation_policy_version_id: UUID | None,
        configuration_version_ids: tuple[UUID, ...],
        metric_definition_version: int,
        retrieval_k: int,
        repetition_count: int,
        runtime_environment: object,
    ) -> EvaluationRunView:
        if not configuration_version_ids or len(configuration_version_ids) != len(
            set(configuration_version_ids)
        ):
            raise AppError("invalid_evaluation", "Evaluation candidates must be unique.", 422)
        workspace_ids = tuple(
            dict.fromkeys(
                workspace_id
                for case in dataset.cases
                for workspace_id in case.permission_scenario.workspace_ids
            )
        )
        authorized = set(
            await self.session.scalars(
                select(WorkspaceMembershipRecord.workspace_id).where(
                    WorkspaceMembershipRecord.user_id == actor_id,
                    WorkspaceMembershipRecord.workspace_id.in_(workspace_ids),
                )
            )
        )
        if authorized != set(workspace_ids):
            raise AppError("not_found", "The requested resource was not found.", 404)
        if evaluation_policy_version_id is not None:
            policy = await self.session.scalar(
                select(EvaluationPolicyRecord).where(
                    EvaluationPolicyRecord.id == evaluation_policy_version_id,
                    EvaluationPolicyRecord.owner_id == actor_id,
                    EvaluationPolicyRecord.dataset_snapshot_id == dataset.id,
                    EvaluationPolicyRecord.metric_definition_version
                    == metric_definition_version,
                    EvaluationPolicyRecord.retrieval_k == retrieval_k,
                )
            )
            if policy is None:
                raise AppError("not_found", "The requested resource was not found.", 404)
        snapshots = [
            await self._configuration_snapshot(version_id, actor_id, dataset)
            for version_id in configuration_version_ids
        ]
        if any(item is None for item in snapshots):
            raise AppError("not_found", "The requested resource was not found.", 404)
        exact_snapshots = [item for item in snapshots if item is not None]
        execution_snapshot = await self._execution_snapshot(
            actor_id=actor_id,
            dataset=dataset,
            snapshots=exact_snapshots,
        )
        execution_snapshot_bytes = json.dumps(
            execution_snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        execution_snapshot_sha256 = hashlib.sha256(
            execution_snapshot_bytes
        ).hexdigest()
        run = EvaluationRunRecord(
            owner_id=actor_id,
            dataset_snapshot_id=dataset.id,
            evaluation_policy_version_id=evaluation_policy_version_id,
            status=EvaluationRunStatus.PENDING,
            fixture_sha256=dataset.fixture_sha256,
            document_snapshot_sha256=dataset.document_snapshot_sha256,
            query_set_sha256=dataset.query_set_sha256,
            execution_snapshot=execution_snapshot,
            execution_snapshot_bytes=execution_snapshot_bytes,
            execution_snapshot_sha256=execution_snapshot_sha256,
            runtime_environment=dict(cast(dict[str, object], runtime_environment)),
            worker_runtime_environment=None,
            metric_definition_version=metric_definition_version,
            retrieval_k=retrieval_k,
            repetition_count=repetition_count,
            candidate_count=len(configuration_version_ids),
        )
        self.session.add(run)
        await self.session.flush()
        for ordinal, item in enumerate(exact_snapshots):
            version, snapshot = item
            snapshot = {
                **snapshot,
                "execution_snapshot_sha256": execution_snapshot_sha256,
            }
            self.session.add(
                EvaluationRunConfigurationRecord(
                    run_id=run.id,
                    configuration_version_id=version.id,
                    ordinal=ordinal,
                    indexing_profile_id=version.indexing_profile_id,
                    retrieval_profile_id=version.retrieval_profile_id,
                    answer_policy_version_id=version.answer_policy_version_id,
                    generation_profile_id=version.generation_profile_id,
                    component_snapshot=snapshot,
                    status=CandidateStatus.PENDING,
                )
            )
        self.session.add(EvaluationDispatchRecord(run_id=run.id))
        await self.session.flush()
        return await self._view(run)

    async def _execution_snapshot(
        self,
        *,
        actor_id: UUID,
        dataset: EvaluationDataset,
        snapshots: list[tuple[RagConfigurationVersionRecord, dict[str, object]]],
    ) -> dict[str, object]:
        build_ids = tuple(
            UUID(str(build["index_build_id"]))
            for _, snapshot in snapshots
            for build in cast(list[dict[str, object]], snapshot["index_builds"])
        )
        rows = (
            await self.session.execute(
                select(
                    RetrievalChunkRecord,
                    RagProjectionRecord,
                    RagIndexBuildRecord,
                    AssetVersionRecord,
                    DocumentRecord,
                    WorkspaceRecord,
                )
                .join(
                    RagProjectionRecord,
                    RagProjectionRecord.id == RetrievalChunkRecord.projection_id,
                )
                .join(
                    RagIndexBuildRecord,
                    RagIndexBuildRecord.projection_id == RagProjectionRecord.id,
                )
                .join(
                    AssetVersionRecord,
                    AssetVersionRecord.id == RagProjectionRecord.asset_version_id,
                )
                .join(DocumentRecord, DocumentRecord.id == AssetVersionRecord.document_id)
                .join(WorkspaceRecord, WorkspaceRecord.id == DocumentRecord.workspace_id)
                .where(RagIndexBuildRecord.id.in_(build_ids))
                .order_by(RagIndexBuildRecord.id, RetrievalChunkRecord.id)
            )
        ).all()
        chunk_ids = tuple(row[0].id for row in rows)
        evidence_rows = list(
            await self.session.scalars(
                select(EvidenceUnitRecord)
                .where(EvidenceUnitRecord.retrieval_chunk_id.in_(chunk_ids))
                .order_by(
                    EvidenceUnitRecord.retrieval_chunk_id,
                    EvidenceUnitRecord.ordinal,
                )
            )
        )
        evidence_by_chunk: dict[UUID, list[EvidenceUnitRecord]] = {
            chunk_id: [] for chunk_id in chunk_ids
        }
        for evidence in evidence_rows:
            evidence_by_chunk[evidence.retrieval_chunk_id].append(evidence)
        folder_ids = tuple(
            {row[4].folder_id for row in rows if row[4].folder_id is not None}
        )
        folders = {
            folder.id: folder
            for folder in await self.session.scalars(
                select(FolderRecord).where(FolderRecord.id.in_(folder_ids))
            )
        }
        sources: list[dict[str, object]] = []
        for chunk, projection, build, version, document, workspace in rows:
            folder = folders.get(document.folder_id)
            sources.append(
                {
                    "indexing_profile_id": str(build.indexing_profile_id),
                    "index_build_id": str(build.id),
                    "index_name": build.index_name,
                    "projection_id": str(projection.id),
                    "workspace": {
                        "id": str(workspace.id),
                        "name": workspace.name,
                        "kind": str(workspace.kind),
                    },
                    "folder": (
                        {
                            "id": str(folder.id),
                            "name": folder.name,
                            "parent_id": str(folder.parent_id)
                            if folder.parent_id is not None
                            else None,
                        }
                        if folder is not None
                        else None
                    ),
                    "document_id": str(document.id),
                    "title": document.name,
                    "asset_version_id": str(version.id),
                    "asset_version_number": version.number,
                    "asset_sha256": version.sha256,
                    "media_type": version.media_type,
                    "chunk_id": str(chunk.id),
                    "chunk_text": chunk.text,
                    "section_path": list(chunk.section_path),
                    "evidence_units": [
                        {
                            "id": str(evidence.id),
                            "source_id": str(evidence.id),
                            "ordinal": evidence.ordinal,
                            "text": evidence.text,
                            "element_id": str(evidence.element_id),
                            "page": evidence.page,
                            "char_start": evidence.char_start,
                            "char_end": evidence.char_end,
                            "bbox": evidence.bbox,
                        }
                        for evidence in evidence_by_chunk[chunk.id]
                    ],
                }
            )
        return {
            "schema_version": 1,
            "actor_id": str(actor_id),
            "dataset_fixture_sha256": dataset.fixture_sha256,
            "permission_scopes": [
                {
                    "case_id": str(case.id),
                    "actor_id": str(actor_id),
                    "workspace_ids": [
                        str(item) for item in case.permission_scenario.workspace_ids
                    ],
                    "folder_ids": [
                        str(item) for item in case.permission_scenario.folder_ids
                    ],
                    "authorized_source_ids": sorted(
                        str(item)
                        for item in case.permission_scenario.authorized_source_ids
                    ),
                    "forbidden_source_ids": sorted(
                        str(item)
                        for item in case.permission_scenario.forbidden_source_ids
                    ),
                    "as_of": case.permission_scenario.as_of,
                }
                for case in dataset.cases
            ],
            "candidates": [
                {
                    "configuration_version_id": str(version.id),
                    "component_snapshot": snapshot,
                }
                for version, snapshot in snapshots
            ],
            "sources": sources,
        }

    async def _view(self, run: EvaluationRunRecord) -> EvaluationRunView:
        candidates = list(
            await self.session.scalars(
                select(EvaluationRunConfigurationRecord)
                .where(EvaluationRunConfigurationRecord.run_id == run.id)
                .order_by(EvaluationRunConfigurationRecord.ordinal)
            )
        )
        candidate_views: list[EvaluationCandidateView] = []
        for candidate in candidates:
            cases = list(
                await self.session.scalars(
                    select(EvaluationCaseResultRecord)
                    .where(
                        EvaluationCaseResultRecord.run_configuration_id == candidate.id
                    )
                    .order_by(EvaluationCaseResultRecord.ordinal)
                )
            )
            candidate_views.append(
                EvaluationCandidateView(
                    id=candidate.id,
                    configuration_version_id=candidate.configuration_version_id,
                    ordinal=candidate.ordinal,
                    status=CandidateStatus(candidate.status),
                    failure=candidate.failure,
                    metrics=_metrics(candidate),
                    case_results=tuple(_case_domain(item) for item in cases),
                )
            )
        return EvaluationRunView(
            id=run.id,
            owner_id=run.owner_id,
            dataset_snapshot_id=run.dataset_snapshot_id,
            evaluation_policy_version_id=run.evaluation_policy_version_id,
            status=EvaluationRunStatus(run.status),
            fixture_sha256=run.fixture_sha256,
            document_snapshot_sha256=run.document_snapshot_sha256,
            query_set_sha256=run.query_set_sha256,
            execution_snapshot_sha256=run.execution_snapshot_sha256,
            runtime_environment=run.runtime_environment,
            worker_runtime_environment=run.worker_runtime_environment,
            metric_definition_version=run.metric_definition_version,
            retrieval_k=run.retrieval_k,
            repetition_count=run.repetition_count,
            failure=run.failure,
            candidates=tuple(candidate_views),
        )

    async def detail_visible(
        self, run_id: UUID, actor_id: UUID
    ) -> EvaluationRunView | None:
        run = await self.session.scalar(
            select(EvaluationRunRecord).where(
                EvaluationRunRecord.id == run_id,
                EvaluationRunRecord.owner_id == actor_id,
            )
        )
        return await self._view(run) if run is not None else None

    async def list_visible(
        self, actor_id: UUID, limit: int
    ) -> tuple[EvaluationRunView, ...]:
        runs = list(
            await self.session.scalars(
                select(EvaluationRunRecord)
                .where(EvaluationRunRecord.owner_id == actor_id)
                .order_by(EvaluationRunRecord.created_at.desc(), EvaluationRunRecord.id)
                .limit(limit)
            )
        )
        return tuple([await self._view(run) for run in runs])


class SqlAlchemyEvaluationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def claim_run(
        self, run_id: UUID, worker_runtime_environment: Mapping[str, object]
    ) -> EvaluationRunClaim | None:
        now = datetime.now(UTC)
        async with self.sessions.begin() as session:
            run = await session.scalar(
                select(EvaluationRunRecord)
                .where(
                    EvaluationRunRecord.id == run_id,
                    or_(
                        EvaluationRunRecord.status == EvaluationRunStatus.PENDING,
                        and_(
                            EvaluationRunRecord.status == EvaluationRunStatus.RUNNING,
                            EvaluationRunRecord.claimed_at
                            < now - timedelta(minutes=30),
                        ),
                    ),
                )
                .with_for_update(skip_locked=True)
            )
            if run is None:
                return None
            dataset_record = await session.get(
                EvaluationDatasetRecord, run.dataset_snapshot_id
            )
            if dataset_record is None:
                raise RuntimeError("The immutable Evaluation Dataset is unavailable.")
            dataset = _dataset_domain(dataset_record)
            if (
                run.fixture_sha256 != dataset.fixture_sha256
                or run.document_snapshot_sha256 != dataset.document_snapshot_sha256
                or run.query_set_sha256 != dataset.query_set_sha256
                or json.loads(run.execution_snapshot_bytes) != run.execution_snapshot
                or hashlib.sha256(run.execution_snapshot_bytes).hexdigest()
                != run.execution_snapshot_sha256
            ):
                raise RuntimeError("The Evaluation Run snapshot no longer matches.")
            runtime_fingerprint = cast(
                dict[str, object],
                json.loads(
                    json.dumps(
                        worker_runtime_environment,
                        allow_nan=False,
                        sort_keys=True,
                    )
                ),
            )
            if (
                run.worker_runtime_environment is not None
                and run.worker_runtime_environment != runtime_fingerprint
            ):
                await session.execute(
                    update(EvaluationRunConfigurationRecord)
                    .where(
                        EvaluationRunConfigurationRecord.run_id == run.id,
                        EvaluationRunConfigurationRecord.status.in_(
                            (CandidateStatus.PENDING, CandidateStatus.RUNNING)
                        ),
                    )
                    .values(
                        status=CandidateStatus.FAILED,
                        failure="runtime_fingerprint_mismatch",
                        completed_at=now,
                    )
                )
                run.status = EvaluationRunStatus.FAILED
                run.failure = "runtime_fingerprint_mismatch"
                run.finished_at = now
                run.claim_token = None
                run.claimed_at = None
                return None
            token = uuid4()
            run.status = EvaluationRunStatus.RUNNING
            run.claim_token = token
            run.claimed_at = now
            if run.worker_runtime_environment is None:
                run.worker_runtime_environment = runtime_fingerprint
            candidates = list(
                await session.scalars(
                    select(EvaluationRunConfigurationRecord)
                    .where(
                        EvaluationRunConfigurationRecord.run_id == run.id,
                        EvaluationRunConfigurationRecord.status.in_(
                            (CandidateStatus.PENDING, CandidateStatus.RUNNING)
                        ),
                    )
                    .order_by(EvaluationRunConfigurationRecord.ordinal)
                )
            )
            execution_candidates: list[CandidateExecutionInput] = []
            for item in candidates:
                component_snapshot = item.component_snapshot
                configuration_snapshot = cast(
                    dict[str, object], component_snapshot["configuration"]
                )
                execution_candidates.append(
                    CandidateExecutionInput(
                        id=item.id,
                        configuration_id=UUID(str(configuration_snapshot["id"])),
                        configuration_version_id=item.configuration_version_id,
                        ordinal=item.ordinal,
                        index_builds=tuple(
                            CandidateIndexBuildSnapshot(
                                asset_version_id=UUID(str(build["asset_version_id"])),
                                projection_id=UUID(str(build["projection_id"])),
                                index_build_id=UUID(str(build["index_build_id"])),
                                index_name=str(build["index_name"]),
                                indexing_profile_id=UUID(
                                    str(build["indexing_profile_id"])
                                ),
                                vector_dimension=int(
                                    cast(int, build["vector_dimension"])
                                ),
                                index_uuid=str(build["index_uuid"]),
                                mapping_version=int(cast(int, build["mapping_version"])),
                                active_at_snapshot=bool(build["active_at_snapshot"]),
                            )
                            for build in cast(
                                list[dict[str, object]],
                                component_snapshot["index_builds"],
                            )
                        ),
                        retrieval_k=run.retrieval_k,
                        workspace_ids=tuple(
                            UUID(value)
                            for value in cast(
                                list[str], configuration_snapshot["workspace_ids"]
                            )
                        ),
                        is_system=bool(configuration_snapshot["is_system"]),
                        component_snapshot=component_snapshot,
                        execution_snapshot=run.execution_snapshot,
                    )
                )
            return EvaluationRunClaim(
                run_id=run.id,
                claim_token=token,
                owner_id=run.owner_id,
                dataset=dataset,
                metric_definition_version=run.metric_definition_version,
                retrieval_k=run.retrieval_k,
                repetition_count=run.repetition_count,
                candidates=tuple(execution_candidates),
            )

    async def heartbeat(self, run_id: UUID, claim_token: UUID) -> None:
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(EvaluationRunRecord)
                .where(
                    EvaluationRunRecord.id == run_id,
                    EvaluationRunRecord.status == EvaluationRunStatus.RUNNING,
                    EvaluationRunRecord.claim_token == claim_token,
                )
                .values(claimed_at=datetime.now(UTC))
            )
            if getattr(result, "rowcount", 0) != 1:
                raise EvaluationRunClaimLostError(
                    "Evaluation Run claim token is invalid."
                )

    async def _candidate_with_claim(
        self, session: AsyncSession, candidate_id: UUID, claim_token: UUID
    ) -> EvaluationRunConfigurationRecord:
        candidate = await session.scalar(
            select(EvaluationRunConfigurationRecord)
            .join(
                EvaluationRunRecord,
                EvaluationRunRecord.id == EvaluationRunConfigurationRecord.run_id,
            )
            .where(
                EvaluationRunConfigurationRecord.id == candidate_id,
                EvaluationRunRecord.status == EvaluationRunStatus.RUNNING,
                EvaluationRunRecord.claim_token == claim_token,
            )
            .with_for_update()
        )
        if candidate is None:
            raise EvaluationRunClaimLostError("Evaluation Run claim token is invalid.")
        return candidate

    async def mark_candidate_running(
        self, candidate_id: UUID, claim_token: UUID
    ) -> None:
        async with self.sessions.begin() as session:
            candidate = await self._candidate_with_claim(session, candidate_id, claim_token)
            if candidate.status not in (CandidateStatus.PENDING, CandidateStatus.RUNNING):
                raise EvaluationRunClaimLostError("Evaluation candidate cannot be restarted.")
            candidate.status = CandidateStatus.RUNNING

    async def find_case_result(
        self, candidate_id: UUID, evaluation_case_id: UUID
    ) -> CaseEvaluationResult | None:
        async with self.sessions() as session:
            record = await session.scalar(
                select(EvaluationCaseResultRecord).where(
                    EvaluationCaseResultRecord.run_configuration_id == candidate_id,
                    EvaluationCaseResultRecord.evaluation_case_id == evaluation_case_id,
                )
            )
            return _case_domain(record) if record is not None else None

    async def add_case_result(
        self,
        candidate_id: UUID,
        claim_token: UUID,
        result: CaseEvaluationResult,
    ) -> None:
        async with self.sessions.begin() as session:
            await self._candidate_with_claim(session, candidate_id, claim_token)
            dataset_snapshot_id = await session.scalar(
                select(EvaluationRunRecord.dataset_snapshot_id)
                .join(
                    EvaluationRunConfigurationRecord,
                    EvaluationRunConfigurationRecord.run_id == EvaluationRunRecord.id,
                )
                .where(EvaluationRunConfigurationRecord.id == candidate_id)
            )
            if dataset_snapshot_id is None:
                raise EvaluationRunClaimLostError("Evaluation candidate is unavailable.")
            existing = await session.scalar(
                select(EvaluationCaseResultRecord).where(
                    EvaluationCaseResultRecord.run_configuration_id == candidate_id,
                    EvaluationCaseResultRecord.evaluation_case_id
                    == result.evaluation_case_id,
                )
            )
            if existing is not None:
                return
            session.add(
                EvaluationCaseResultRecord(
                    run_configuration_id=candidate_id,
                    dataset_snapshot_id=dataset_snapshot_id,
                    evaluation_case_id=result.evaluation_case_id,
                    ordinal=result.ordinal,
                    query_sha256=result.query_sha256,
                    permission_scenario=_scenario_json(result.permission_scenario),
                    expected_evidence_ids=sorted(
                        str(item) for item in result.expected_evidence_ids
                    ),
                    raw_observations=[
                        _observation_json(item) for item in result.raw_observations
                    ],
                    duration_ms=result.duration_ms,
                    recall_at_k=result.recall_at_k,
                    reciprocal_rank=result.reciprocal_rank,
                    ndcg=result.ndcg,
                    correct_supported=result.correct_supported,
                    false_grounding=result.false_grounding,
                    highlight_iou=result.highlight_iou,
                    access_leaks=result.access_leaks,
                    reproducible=result.reproducible,
                )
            )

    async def complete_candidate(
        self, candidate_id: UUID, claim_token: UUID, metrics: EvaluationMetrics
    ) -> None:
        async with self.sessions.begin() as session:
            candidate = await self._candidate_with_claim(session, candidate_id, claim_token)
            candidate.status = CandidateStatus.COMPLETED
            candidate.failure = None
            candidate.recall_at_k = metrics.recall_at_k
            candidate.mrr = metrics.mrr
            candidate.ndcg = metrics.ndcg
            candidate.supported_precision = metrics.supported_precision
            candidate.false_grounding_rate = metrics.false_grounding_rate
            candidate.highlight_iou = metrics.highlight_iou
            candidate.p50_latency_ms = metrics.p50_latency_ms
            candidate.p95_latency_ms = metrics.p95_latency_ms
            candidate.access_leaks = metrics.access_leaks
            candidate.reproducibility = metrics.reproducibility
            candidate.completed_at = datetime.now(UTC)

    async def fail_candidate(
        self, candidate_id: UUID, claim_token: UUID, failure: str
    ) -> None:
        async with self.sessions.begin() as session:
            candidate = await self._candidate_with_claim(session, candidate_id, claim_token)
            candidate.status = CandidateStatus.FAILED
            candidate.failure = failure[:700]
            candidate.completed_at = datetime.now(UTC)

    async def complete_run(self, run_id: UUID, claim_token: UUID) -> None:
        await self._finish_run(run_id, claim_token, EvaluationRunStatus.COMPLETED, None)

    async def fail_run(self, run_id: UUID, claim_token: UUID, failure: str) -> None:
        await self._finish_run(run_id, claim_token, EvaluationRunStatus.FAILED, failure)

    async def _finish_run(
        self,
        run_id: UUID,
        claim_token: UUID,
        status: EvaluationRunStatus,
        failure: str | None,
    ) -> None:
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(EvaluationRunRecord)
                .where(
                    EvaluationRunRecord.id == run_id,
                    EvaluationRunRecord.status == EvaluationRunStatus.RUNNING,
                    EvaluationRunRecord.claim_token == claim_token,
                )
                .values(
                    status=status,
                    failure=failure[:700] if failure else None,
                    finished_at=datetime.now(UTC),
                    claim_token=None,
                    claimed_at=None,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                raise EvaluationRunClaimLostError("Evaluation Run claim token is invalid.")


class SqlAlchemyEvaluationDispatchRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def claim_ready(
        self,
        *,
        now: datetime,
        stale_before: datetime,
        limit: int,
    ) -> tuple[EvaluationDispatchClaim, ...]:
        async with self.sessions.begin() as session:
            records = (
                await session.scalars(
                    select(EvaluationDispatchRecord)
                    .join(
                        EvaluationRunRecord,
                        EvaluationRunRecord.id == EvaluationDispatchRecord.run_id,
                    )
                    .where(
                        EvaluationRunRecord.status.in_(
                            (EvaluationRunStatus.PENDING, EvaluationRunStatus.RUNNING)
                        ),
                        or_(
                            and_(
                                EvaluationDispatchRecord.status == "pending",
                                EvaluationDispatchRecord.available_at <= now,
                            ),
                            and_(
                                EvaluationDispatchRecord.status == "claimed",
                                EvaluationDispatchRecord.claimed_at <= stale_before,
                            ),
                            and_(
                                EvaluationDispatchRecord.status == "sent",
                                EvaluationDispatchRecord.sent_at <= stale_before,
                                or_(
                                    EvaluationRunRecord.status
                                    == EvaluationRunStatus.PENDING,
                                    EvaluationRunRecord.claimed_at <= stale_before,
                                ),
                            ),
                        )
                    )
                    .order_by(
                        EvaluationDispatchRecord.available_at,
                        EvaluationDispatchRecord.created_at,
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            claims: list[EvaluationDispatchClaim] = []
            for record in records:
                token = uuid4()
                record.status = "claimed"
                record.claimed_at = now
                record.claim_token = token
                record.attempt_count += 1
                record.sent_at = None
                claims.append(
                    EvaluationDispatchClaim(record.run_id, token, record.attempt_count)
                )
            await session.flush()
        return tuple(claims)

    async def mark_sent(
        self,
        claim: EvaluationDispatchClaim,
        *,
        now: datetime,
    ) -> None:
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(EvaluationDispatchRecord)
                .where(
                    EvaluationDispatchRecord.run_id == claim.run_id,
                    EvaluationDispatchRecord.status == "claimed",
                    EvaluationDispatchRecord.claim_token == claim.claim_token,
                )
                .values(
                    status="sent",
                    sent_at=now,
                    claimed_at=None,
                    claim_token=None,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                raise EvaluationDispatchClaimLostError(
                    "Evaluation dispatch claim token is no longer valid."
                )

    async def mark_failed(
        self,
        claim: EvaluationDispatchClaim,
        *,
        now: datetime,
        retry_at: datetime,
        error: str,
    ) -> None:
        del now
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(EvaluationDispatchRecord)
                .where(
                    EvaluationDispatchRecord.run_id == claim.run_id,
                    EvaluationDispatchRecord.status == "claimed",
                    EvaluationDispatchRecord.claim_token == claim.claim_token,
                )
                .values(
                    status="pending",
                    available_at=retry_at,
                    claimed_at=None,
                    claim_token=None,
                    last_error=error[:700],
                    sent_at=None,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                raise EvaluationDispatchClaimLostError(
                    "Evaluation dispatch claim token is no longer valid."
                )
