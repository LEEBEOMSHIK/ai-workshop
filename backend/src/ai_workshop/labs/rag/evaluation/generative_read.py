from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.conversations.access import source_identities
from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.labs.rag.evaluation.generative import (
    CorrectnessJudgment,
    ExpectedAnswerRule,
    JudgmentStatus,
    PrivateGenerativeResult,
    evaluate_generative,
    judge_propositions,
)
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativeJudgmentRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_repository import unavailable
from ai_workshop.labs.rag.evaluation.generative_schemas import (
    GenerativeAttemptView,
    GenerativeRunView,
    GenerativeSourceView,
)
from ai_workshop.labs.rag.evaluation.models import EvaluationDatasetCaseRecord
from ai_workshop.labs.rag.executions.models import ExecutionRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import workspace_read_allowed


async def visible_run(session: AsyncSession, actor_id: UUID, run: GenerativeRunRecord) -> bool:
    if run.owner_id != actor_id:
        return False
    for document, version, projection in source_identities(run.snapshot):
        found = await session.scalar(
            select(DocumentRecord.id)
            .join(
                WorkspaceRecord,
                WorkspaceRecord.id == DocumentRecord.workspace_id,
            )
            .join(AssetVersionRecord, AssetVersionRecord.document_id == DocumentRecord.id)
            .join(
                RagProjectionRecord,
                RagProjectionRecord.asset_version_id == AssetVersionRecord.id,
            )
            .where(
                DocumentRecord.id == document,
                DocumentRecord.lifecycle == "active",
                AssetVersionRecord.id == version,
                AssetVersionRecord.status == "ready",
                RagProjectionRecord.id == projection,
                RagProjectionRecord.status == "ready",
                workspace_read_allowed(actor_id),
            )
        )
        if found is None:
            return False
    return True


async def run_detail(session: AsyncSession, actor_id: UUID, run_id: UUID) -> GenerativeRunView:
    run = await session.scalar(
        select(GenerativeRunRecord)
        .where(
            GenerativeRunRecord.id == run_id,
            GenerativeRunRecord.owner_id == actor_id,
        )
        .execution_options(populate_existing=True)
    )
    if run is None or not await visible_run(session, actor_id, run):
        raise unavailable()
    cases = (
        await session.scalars(
            select(EvaluationDatasetCaseRecord).where(
                EvaluationDatasetCaseRecord.dataset_snapshot_id == run.dataset_snapshot_id,
            )
        )
    ).all()
    queries = {case.id: case.query_bytes.decode("utf-8") for case in cases}
    attempts = (
        await session.scalars(
            select(GenerativeAttemptRecord)
            .where(
                GenerativeAttemptRecord.run_id == run.id,
            )
            .order_by(
                GenerativeAttemptRecord.configuration_version_id,
                GenerativeAttemptRecord.case_id,
                GenerativeAttemptRecord.repetition,
                GenerativeAttemptRecord.attempt_number,
            )
        )
    ).all()
    executions = set(
        (
            await session.scalars(
                select(ExecutionRecord.id).where(
                    ExecutionRecord.evaluation_attempt_id.in_([a.id for a in attempts]),
                    ExecutionRecord.actor_id == actor_id,
                )
            )
        ).all()
    )
    judgment_rows = (
        await session.scalars(
            select(GenerativeJudgmentRecord)
            .where(
                GenerativeJudgmentRecord.attempt_id.in_([a.id for a in attempts]),
            )
            .order_by(GenerativeJudgmentRecord.created_at, GenerativeJudgmentRecord.id)
        )
    ).all()
    judgments = {j.attempt_id: j for j in judgment_rows}
    sources: dict[UUID, GenerativeSourceView] = {}
    for row in cast(list[dict[str, object]], run.snapshot.get("sources", [])):
        for unit in cast(list[dict[str, object]], row["evidence_units"]):
            id = UUID(str(unit["id"]))
            sources[id] = GenerativeSourceView(
                evidence_id=id,
                document_id=UUID(str(row["document_id"])),
                asset_version_id=UUID(str(row["asset_version_id"])),
                projection_id=UUID(str(row["projection_id"])),
                title=str(row["title"]),
                page=cast(int | None, unit.get("page")),
            )
    views = []
    for attempt in attempts:
        result = PrivateGenerativeResult.model_validate(attempt.result) if attempt.result else None
        rule = ExpectedAnswerRule.model_validate(run.expected_rules[str(attempt.case_id)])
        judgment = judge_propositions(result, rule) if result else None
        review = judgments.get(attempt.id)
        if (
            review
            and result
            and review.result_digest == result.digest()
            and review.rule_digest == rule.digest()
        ):
            judgment = CorrectnessJudgment(
                status=cast(JudgmentStatus, review.status),
                provenance="reviewer",
                rule_version=rule.version,
                rule_digest=review.rule_digest,
                result_digest=review.result_digest,
                reviewer_id=review.reviewer_id,
                reviewed_at=review.created_at,
                reason=review.reason,
            )
        views.append(
            GenerativeAttemptView(
                id=attempt.id,
                configuration_version_id=attempt.configuration_version_id,
                case_id=attempt.case_id,
                query=queries[attempt.case_id],
                repetition=attempt.repetition,
                attempt_number=attempt.attempt_number,
                status=attempt.status,
                execution_id=attempt.execution_id if attempt.execution_id in executions else None,
                result_digest=attempt.result_digest,
                answer=result.answer if result else None,
                observation=result.observation if result else None,
                metrics=evaluate_generative(result.observation, rule, judgment) if result else None,
                judgment=judgment,
                error_code=attempt.error_code,
                sources=[
                    sources[id] for id in result.observation.cited_evidence_ids if id in sources
                ]
                if result
                else [],
            )
        )
    if not await visible_run(session, actor_id, run):
        raise unavailable()
    return GenerativeRunView(
        id=run.id,
        dataset_snapshot_id=run.dataset_snapshot_id,
        policy_id=run.policy_id,
        rules_digest=run.rules_digest,
        status=run.status,
        created_at=run.created_at,
        repetition_count=run.repetition_count,
        attempts=views,
    )
