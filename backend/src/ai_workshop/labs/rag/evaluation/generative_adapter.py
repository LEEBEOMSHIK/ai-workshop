"""Frozen evaluation inputs; current authorization remains in the shared pipeline."""

from dataclasses import replace
from typing import cast
from uuid import UUID

from ai_workshop.labs.rag.evaluation.domain import EvaluationCase
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
    ) -> None:
        self.frozen, self.configurations = frozen, configurations
        self.access = access
        # Supplied only by the authorized evaluation submission, never a monitoring read.
        self.input_approval = input_approval

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
        # Immutable profile records are resolved by exact version; only current transfer
        # approval is taken from the resolver. Retrieval never follows the active alias.
        configuration = replace(
            configuration,
            active_index_alias=target,
            embedding=frozen.embedding,
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
                history=cast(dict, sources.get("case_histories", {})).get(str(case.id), []),
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
