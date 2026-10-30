"""Frozen evaluation inputs; current authorization remains in the shared pipeline."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from functools import partial
from typing import Any, cast
from uuid import UUID

from ai_workshop.labs.rag.evaluation.domain import EvaluationCase
from ai_workshop.labs.rag.evaluation.embedding_reuse import FrozenEmbeddingResults
from ai_workshop.labs.rag.evaluation.generative_access import FrozenEvaluationAccess
from ai_workshop.labs.rag.evaluation.service import CandidateExecutionInput
from ai_workshop.labs.rag.evaluation.tasks import FrozenSourceResolver, ProductionEvaluationSearch
from ai_workshop.labs.rag.generation.codex_admin_api import CodexInputApprovalRequest
from ai_workshop.labs.rag.highlighting.domain import EvidenceSource
from ai_workshop.labs.rag.retrieval.domain import (
    FusedHit,
    ResolvedSearchScope,
    SelectedDocumentIdentity,
)
from ai_workshop.labs.rag.search.configuration_port import SearchConfigurationResolverPort
from ai_workshop.labs.rag.search.pipeline import PipelineInput
from ai_workshop.labs.rag.search.schemas import SearchRequest
from ai_workshop.shared.errors import AppError


class FrozenGenerativeSources:
    def __init__(self, snapshot: dict[str, object], actor_id: UUID) -> None:
        self.resolver, self.actor_id = FrozenSourceResolver(snapshot), actor_id

    async def resolve(
        self,
        *,
        actor_id: UUID,
        indexing_profile_id: UUID,
        hits: tuple[FusedHit, ...],
    ) -> tuple[EvidenceSource, ...]:
        if actor_id != self.actor_id:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return self.resolver.resolve(indexing_profile_id=indexing_profile_id, hits=hits)


class FrozenGenerativeAdapter:
    def __init__(
        self,
        frozen: ProductionEvaluationSearch,
        configurations: SearchConfigurationResolverPort,
        access: FrozenEvaluationAccess,
        *,
        input_approval: CodexInputApprovalRequest | None = None,
        embedding_results: FrozenEmbeddingResults | None = None,
    ) -> None:
        self.frozen, self.configurations = frozen, configurations
        self.access = access
        # Supplied only by the authorized evaluation submission, never a monitoring read.
        self.input_approval = input_approval
        self.embedding_results = embedding_results

    async def prepare(
        self,
        actor_id: UUID,
        candidate: CandidateExecutionInput,
        case: EvaluationCase,
    ) -> PipelineInput:
        target = await self.frozen.prepare_target(candidate)
        frozen = self.frozen._resolve_configuration(candidate, target)
        scenario = self.frozen._resolve_scope(candidate, case, actor_id)
        configuration = await self.configurations.resolve_version(
            candidate.configuration_version_id,
            actor_id,
        )
        snapshot = candidate.component_snapshot
        sources = candidate.execution_snapshot
        if snapshot is None or sources is None:
            raise AppError("evaluation_snapshot_missing", "The frozen input is missing.", 409)
        profile = configuration.generation_profile
        profiles = cast(list[dict[str, object]], snapshot.get("profiles", []))
        matching = [p for p in profiles if profile and p.get("id") == str(profile.profile_id)]
        if (
            profile is None
            or len(matching) != 1
            or matching[0].get("version") != profile.profile_version
            or configuration.configuration_id != candidate.configuration_id
            or configuration.indexing_profile_id != frozen.indexing_profile_id
            or configuration.retrieval_profile.id != frozen.retrieval_profile.id
            or configuration.answer_policy_version_id != frozen.answer_policy_version_id
            or not set(scenario.workspace_ids).issubset(configuration.workspace_ids)
        ):
            raise AppError("evaluation_profile_drift", "The frozen configuration changed.", 409)
        owned_factory = frozen.request_owned_embedding_factory
        if self.embedding_results is not None and owned_factory is not None:
            owned_factory = partial(
                self.embedding_results.bound,
                namespace=_embedding_result_namespace(actor_id, candidate, case),
                factory=owned_factory,
                dimension=frozen.embedding.dimension,
            )
        # Immutable profile records are resolved by exact version; only current transfer
        # approval is taken from the resolver. Retrieval never follows the active alias.
        configuration = replace(
            configuration,
            active_index_alias=target,
            embedding=frozen.embedding,
            # Use the exact frozen model's ownership, never the current resolver's
            # factory. Production runtimes release before generation; injected
            # borrowed ports remain borrowed.
            request_owned_embedding_factory=owned_factory,
            retrieval_profile=frozen.retrieval_profile,
            answer_policy=frozen.answer_policy,
            query_max_tokens=frozen.query_max_tokens,
        )
        rows = cast(list[dict[str, object]], sources.get("sources", []))
        identities = tuple(
            dict.fromkeys(
                SelectedDocumentIdentity(
                    UUID(str(row["document_id"])),
                    UUID(str(row["asset_version_id"])),
                    UUID(str(row["projection_id"])),
                    UUID(str(row["index_build_id"])),
                )
                for row in rows
                if UUID(str(row["index_build_id"])) in target.index_build_ids
                and UUID(str(cast(dict[str, object], row["workspace"])["id"]))
                in scenario.workspace_ids
                and (
                    not scenario.folder_ids
                    or (
                        isinstance(row.get("folder"), dict)
                        and UUID(str(cast(dict[str, object], row["folder"])["id"]))
                        in scenario.folder_ids
                    )
                )
            )
        )
        if not identities:
            raise AppError("evaluation_scope_empty", "No authorized frozen sources remain.", 409)

        async def revalidate(needed: tuple[SelectedDocumentIdentity, ...]) -> None:
            await self.access.validate(
                actor_id, needed, scenario.workspace_ids, scenario.folder_ids, configuration
            )

        return PipelineInput(
            actor_id=actor_id,
            request=SearchRequest(
                query=case.query,
                configuration_id=configuration.configuration_id,
                workspace_ids=list(scenario.workspace_ids),
                folder_ids=list(scenario.folder_ids),
                top_k=candidate.retrieval_k,
                history=cast(dict[str, Any], sources.get("case_histories", {})).get(
                    str(case.id), []
                ),
                experimental=True,
                codex_input_approval=self.input_approval,
            ),
            configuration=configuration,
            resolved_scope=ResolvedSearchScope(
                workspace_ids=scenario.workspace_ids,
                folder_ids=scenario.folder_ids,
                active_only=False,
                asset_version_ids=target.asset_version_ids,
                index_build_ids=target.index_build_ids,
                authorized_documents=identities,
            ),
            source_resolver=FrozenGenerativeSources(dict(sources), actor_id),
            frozen_access=revalidate,
        )


def _embedding_result_namespace(
    actor_id: UUID, candidate: CandidateExecutionInput, case: EvaluationCase,
) -> str:
    scenario = case.permission_scenario
    identity = {
        "actor_id": str(actor_id),
        "candidate_id": str(candidate.id),
        "configuration_id": str(candidate.configuration_id),
        "configuration_version_id": str(candidate.configuration_version_id),
        "case_id": str(case.id),
        "component_snapshot": candidate.component_snapshot,
        "execution_snapshot": candidate.execution_snapshot,
        "permission_scenario": {
            "name": scenario.name,
            "actor": scenario.actor,
            "workspace_ids": [str(value) for value in scenario.workspace_ids],
            "folder_ids": [str(value) for value in scenario.folder_ids],
            "authorized_source_ids": sorted(str(value) for value in scenario.authorized_source_ids),
            "forbidden_source_ids": sorted(str(value) for value in scenario.forbidden_source_ids),
            "as_of": scenario.as_of,
        },
    }
    encoded = json.dumps(
        identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False, default=_snapshot_mapping,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_mapping(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError("The frozen embedding identity must contain JSON values.")
