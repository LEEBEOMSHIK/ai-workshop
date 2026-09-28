from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.configurations.repository import SqlAlchemyRagConfigurationRepository
from ai_workshop.labs.rag.evaluation.generative import (
    ExpectedAnswerRule,
    GenerativeAcceptancePolicy,
)
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativeJudgmentRecord,
    GenerativePolicyRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_read import run_detail
from ai_workshop.labs.rag.evaluation.generative_repository import GenerativeRepository, unavailable
from ai_workshop.labs.rag.evaluation.generative_schemas import (
    GenerativeAcceptanceView,
    GenerativePolicyCreate,
    GenerativePolicyView,
    GenerativeReviewRequest,
    GenerativeRunCreate,
    GenerativeRunView,
)
from ai_workshop.labs.rag.evaluation.repository import SqlAlchemyEvaluationApplicationRepository
from ai_workshop.labs.rag.generation.codex_admin_api import require_codex_mutation
from ai_workshop.labs.rag.retrieval.elasticsearch import ElasticsearchFrozenIndexInspector
from ai_workshop.platform.identity.api import require_owner
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/rag/generative-evaluations",
    tags=["rag-generative-evaluation"],
    dependencies=[Depends(no_store)],
)
Actor = Annotated[User, Depends(require_owner)]
Session = Annotated[AsyncSession, Depends(get_session)]


async def freezer(
    session: Session,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[SqlAlchemyEvaluationApplicationRepository]:
    client = create_elasticsearch(settings)
    try:
        yield SqlAlchemyEvaluationApplicationRepository(
            session,
            index_inspector=ElasticsearchFrozenIndexInspector(client),
        )
    finally:
        await client.close()


@router.post("/policies", response_model=GenerativePolicyView, status_code=201)
async def create_policy(
    body: GenerativePolicyCreate, actor: Actor, session: Session
) -> GenerativePolicyView:
    row = GenerativePolicyRecord(
        id=uuid4(),
        owner_id=actor.id,
        name=body.name,
        version=body.definition.version,
        definition=body.definition.model_dump(mode="json"),
        digest=body.definition.digest(),
    )
    existing = await session.scalar(
        select(GenerativePolicyRecord).where(
            GenerativePolicyRecord.owner_id == actor.id,
            GenerativePolicyRecord.name == body.name,
            GenerativePolicyRecord.version == body.definition.version,
        )
    )
    if existing:
        if existing.digest != row.digest:
            raise AppError("policy_version_conflict", "Save a new policy version.", 409)
        row = existing
    else:
        session.add(row)
        await session.commit()
    return GenerativePolicyView(id=row.id, **body.model_dump())


@router.get("/policies", response_model=list[GenerativePolicyView])
async def policies(actor: Actor, session: Session) -> list[GenerativePolicyView]:
    rows = (
        await session.scalars(
            select(GenerativePolicyRecord)
            .where(
                GenerativePolicyRecord.owner_id == actor.id,
            )
            .order_by(GenerativePolicyRecord.created_at.desc())
            .limit(100)
        )
    ).all()
    return [
        GenerativePolicyView(
            id=r.id, name=r.name, definition=GenerativeAcceptancePolicy.model_validate(r.definition)
        )
        for r in rows
    ]


@router.post("", response_model=GenerativeRunView, status_code=202)
async def submit(
    body: GenerativeRunCreate,
    request: Request,
    actor: Actor,
    session: Session,
    settings: Annotated[Settings, Depends(get_settings)],
    snapshotter: Annotated[SqlAlchemyEvaluationApplicationRepository, Depends(freezer)],
) -> GenerativeRunView:
    if body.input_approval is not None:
        require_codex_mutation(request, settings)
    dataset = await snapshotter.find_dataset_visible(body.dataset_snapshot_id, actor.id)
    if dataset is None:
        raise unavailable()
    row = await GenerativeRepository.submit(
        session,
        snapshotter,
        actor_id=actor.id,
        request_id=body.request_id,
        dataset=dataset,
        policy_id=body.policy_id,
        versions=tuple(body.configuration_version_ids),
        rules=body.expected_rules,
        repetitions=body.repetition_count,
        retrieval_k=body.retrieval_k,
        case_histories={
            str(case): [turn.model_dump(mode="json") for turn in turns]
            for case, turns in body.case_histories.items()
        },
        input_approval=body.input_approval.model_dump(mode="json") if body.input_approval else None,
    )
    await session.flush()
    result = await run_detail(session, actor.id, row.id)
    await session.commit()
    # The existing worker's reconciler delivers durable pending runs. Reads never start work.
    return result


@router.get("", response_model=list[GenerativeRunView])
async def list_runs(actor: Actor, session: Session) -> list[GenerativeRunView]:
    ids = (
        await session.scalars(
            select(GenerativeRunRecord.id)
            .where(
                GenerativeRunRecord.owner_id == actor.id,
            )
            .order_by(GenerativeRunRecord.created_at.desc())
            .limit(100)
        )
    ).all()
    visible = []
    for id in ids:
        try:
            visible.append(await run_detail(session, actor.id, id))
        except AppError as exc:
            if exc.code != "not_found":
                raise
    return visible


@router.get("/{run_id}", response_model=GenerativeRunView)
async def detail(run_id: UUID, actor: Actor, session: Session) -> GenerativeRunView:
    return await run_detail(session, actor.id, run_id)


@router.post("/{run_id}/retry", response_model=GenerativeRunView, status_code=202)
async def retry(
    run_id: UUID,
    actor: Actor,
    session: Session,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> GenerativeRunView:
    await run_detail(session, actor.id, run_id)
    row = await session.get(GenerativeRunRecord, run_id)
    if row is not None and row.input_approval:
        require_codex_mutation(request, settings)
    await GenerativeRepository.retry_failed(session, actor.id, run_id)
    await session.flush()
    result = await run_detail(session, actor.id, run_id)
    await session.commit()
    return result


@router.post("/{run_id}/attempts/{attempt_id}/judgments", response_model=GenerativeRunView)
async def judge(
    run_id: UUID,
    attempt_id: UUID,
    body: GenerativeReviewRequest,
    actor: Actor,
    session: Session,
) -> GenerativeRunView:
    await run_detail(session, actor.id, run_id)
    run = await session.get(GenerativeRunRecord, run_id)
    attempt = await session.get(GenerativeAttemptRecord, attempt_id)
    if run is None or attempt is None or attempt.run_id != run_id:
        raise unavailable()
    if attempt.result_digest != body.result_digest or attempt.status != "completed":
        raise AppError("result_digest_mismatch", "Reload the exact completed result.", 409)
    rule = ExpectedAnswerRule.model_validate(run.expected_rules[str(attempt.case_id)])
    session.add(
        GenerativeJudgmentRecord(
            id=uuid4(),
            attempt_id=attempt.id,
            reviewer_id=actor.id,
            result_digest=body.result_digest,
            rule_digest=rule.digest(),
            status=body.status,
            reason=body.reason,
        )
    )
    await session.flush()
    result = await run_detail(session, actor.id, run_id)
    await session.commit()
    return result


@router.post("/{run_id}/accept/{version_id}", response_model=GenerativeAcceptanceView)
async def accept(
    run_id: UUID, version_id: UUID, actor: Actor, session: Session
) -> GenerativeAcceptanceView:
    await run_detail(session, actor.id, run_id)
    try:
        metrics = await SqlAlchemyRagConfigurationRepository(session).accept_generative_evaluation(
            version_id=version_id,
            evaluation_run_id=run_id,
            actor_id=actor.id,
        )
        await session.commit()
    except DBAPIError as exc:
        await session.rollback()
        if getattr(exc.orig, "sqlstate", None) != "P0001":
            raise
        raise AppError(
            "generative_evaluation_not_qualified",
            "생성형 평가의 근거·정답 검토·반복 사례 또는 저장된 승격 기준을 충족하지 못했습니다.",
            409,
        ) from None
    return GenerativeAcceptanceView(
        run_id=run_id, configuration_version_id=version_id, metrics=metrics
    )
