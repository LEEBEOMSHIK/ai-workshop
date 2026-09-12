"""Real SQL gates over synthetic raw observations; no retrieval or model execution."""

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ai_workshop.labs.rag.configurations.domain import (
    BM25_BASELINE_CONFIGURATION_VERSION_ID,
    BM25_RETRIEVAL_PROFILE_ID,
    E5_INDEXING_PROFILE_ID,
    AnswerPolicyVersion,
)
from ai_workshop.labs.rag.configurations.models import RagConfigurationVersionRecord
from ai_workshop.labs.rag.configurations.repository import SqlAlchemyRagConfigurationRepository
from ai_workshop.labs.rag.evaluation.models import (
    EvaluationCaseResultRecord,
    EvaluationPolicyRecord,
    EvaluationRunConfigurationRecord,
    EvaluationRunRecord,
)
from ai_workshop.labs.rag.models.domain import EvaluationState
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.labs.rag.configurations.test_search_configuration_resolver import (
    _seed_actor_workspace,
)
from tests.integration.publishing_support import isolated_publishing_database
from tests.integration.test_migration_0010_rag_evaluation import _seed_qualifying_evidence
from tests.unit.labs.rag.configurations.test_configuration import _configuration

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("AI_WORKSHOP_CODEX_RUNNER_REFS", "{}")
        with isolated_publishing_database(patch) as database:
            command.upgrade(database.config, "head")
            _seed_qualifying_evidence(database.database_url)
            _seed_qualifying_evidence(database.database_url)
            with psycopg.connect(
                database.database_url.replace("postgresql+psycopg:", "postgresql:")
            ) as connection:
                connection.execute(
                    "UPDATE rag_configuration_versions "
                    "SET evaluation_state='passed', is_default=true WHERE id=%s",
                    (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                )
            yield database.database_url


def clone(record, **changes):
    values = {
        column.name: getattr(record, column.name)
        for column in record.__table__.columns
        if column.name not in {"id", "created_at", "updated_at"}
    }
    return type(record)(**(values | changes))


async def seed(session: AsyncSession, broken=""):
    template = await session.scalar(
        select(EvaluationRunRecord).order_by(EvaluationRunRecord.created_at)
    )
    template_candidate = await session.scalar(
        select(EvaluationRunConfigurationRecord).where(
            EvaluationRunConfigurationRecord.run_id == template.id,
            EvaluationRunConfigurationRecord.configuration_version_id
            == BM25_BASELINE_CONFIGURATION_VERSION_ID,
        )
    )
    actor = template.owner_id
    other, workspace, _ = await _seed_actor_workspace(
        session, label="other", with_active_asset=False
    )
    repository = SqlAlchemyRagConfigurationRepository(session)
    name = f"Synthetic acceptance {uuid4()}"
    identity, number = await repository.get_or_create_identity(actor, name)
    answer_policy = AnswerPolicyVersion.create(
        configuration_id=identity,
        version=number,
        min_semantic_score=0.8,
        min_keyword_coverage=0.7,
        require_complete_provenance=True,
        conflict_mode="separate_sources",
    )
    configuration = replace(
        _configuration(),
        id=identity,
        owner_id=actor,
        name=name,
        version=number,
        answer_policy_version_id=answer_policy.id,
        answer_policy_version=answer_policy,
        indexing_profile_id=E5_INDEXING_PROFILE_ID,
        retrieval_profile_id=BM25_RETRIEVAL_PROFILE_ID,
        workspace_ids=(workspace,),
    )
    await repository.add(configuration)
    original_policy = await session.get(
        EvaluationPolicyRecord, template.evaluation_policy_version_id
    )
    policy = original_policy
    if broken in {"policy_owner", "dataset"}:
        changes = (
            {"owner_id": other}
            if broken == "policy_owner"
            else {
                "dataset_snapshot_id": await session.scalar(
                    select(EvaluationRunRecord.dataset_snapshot_id).where(
                        EvaluationRunRecord.dataset_snapshot_id != template.dataset_snapshot_id
                    )
                )
            }
        )
        policy = clone(original_policy, version=2, **changes)
        session.add(policy)
        await session.flush()
    changes = {"evaluation_policy_version_id": policy.id}
    if broken == "run_owner":
        changes["owner_id"] = other
    elif broken == "no_policy":
        changes["evaluation_policy_version_id"] = None
    elif broken == "k":
        changes["retrieval_k"] = 9
    elif broken == "run_failed":
        changes["status"] = "failed"
    elif broken == "run_failure":
        changes["failure"] = "synthetic_failure"
    elif broken in {"fixture_sha256", "document_snapshot_sha256", "query_set_sha256"}:
        changes[broken] = "f" * 64
    run = clone(template, **changes)
    session.add(run)
    await session.flush()
    candidate = clone(
        template_candidate,
        run_id=run.id,
        configuration_version_id=configuration.version_id,
        answer_policy_version_id=configuration.answer_policy_version_id,
        status="pending",
        completed_at=None,
    )
    if broken == "candidate_policy":
        candidate.answer_policy_version_id = template_candidate.answer_policy_version_id
    session.add(candidate)
    await session.flush()
    rows = (
        await session.scalars(
            select(EvaluationCaseResultRecord).where(
                EvaluationCaseResultRecord.run_configuration_id == template_candidate.id
            )
        )
    ).all()
    for row in rows:
        session.add(clone(row, run_configuration_id=candidate.id))
    await session.flush()
    if broken in {"candidate_failed", "other_pass"}:
        candidate.status = "failed"
        candidate.failure = "synthetic_failure"
        candidate.completed_at = datetime.now(UTC)
    elif broken != "incomplete":
        candidate.status = "completed"
        candidate.completed_at = datetime.now(UTC)
    else:
        candidate.recall_at_k = None
    await session.flush()
    if broken == "other_pass":
        passing = clone(
            candidate,
            run_id=template.id,
            ordinal=1,
            status="pending",
            failure=None,
            completed_at=None,
        )
        session.add(passing)
        await session.flush()
        for row in rows:
            session.add(clone(row, run_configuration_id=passing.id))
        await session.flush()
        passing.status = "completed"
        passing.completed_at = datetime.now(UTC)
        await session.flush()
    return repository, configuration, actor, other, policy, run


async def defaults(session):
    return tuple(
        (
            await session.execute(
                select(
                    RagConfigurationVersionRecord.id, RagConfigurationVersionRecord.is_default
                ).order_by(RagConfigurationVersionRecord.id)
            )
        ).all()
    )


async def test_accepts_exact_older_version_and_repeats_without_changing_defaults(database_url):
    engine = create_async_engine(database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            repository, config, actor, _, policy, run = await seed(session)
            _, number = await repository.get_or_create_identity(actor, config.name)
            newer_policy = replace(config.answer_policy_version, id=uuid4(), version=number)
            newer = replace(
                config,
                version_id=uuid4(),
                version=number,
                answer_policy_version=newer_policy,
                answer_policy_version_id=newer_policy.id,
            )
            await repository.add(newer)
            before = await defaults(session)
            assert any(flag for _, flag in before)
            for _ in range(2):
                result = await repository.accept_evaluation(
                    config.id, config.version_id, run.id, actor
                )
                assert result.configuration.version_id == config.version_id
                assert result.configuration.evaluation_state is EvaluationState.PASSED
                assert result.configuration.is_default is False
                assert result.evaluation_run_id == run.id
                assert result.evaluation_policy_version_id == policy.id
                assert await defaults(session) == before
            assert (
                await session.get(RagConfigurationVersionRecord, newer.version_id)
            ).evaluation_state == "pending"
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "broken",
    [
        "actor",
        "identity",
        "version",
        "run",
        "run_owner",
        "policy_owner",
        "no_policy",
        "k",
        "run_failed",
        "run_failure",
        "candidate_failed",
        "incomplete",
        "other_pass",
        "dataset",
        "fixture_sha256",
        "document_snapshot_sha256",
        "query_set_sha256",
        "candidate_policy",
    ],
)
async def test_rejects_explicit_invalid_evidence_without_state_changes(database_url, broken):
    engine = create_async_engine(database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            repository, config, actor, other, _, run = await seed(session, broken)
            identity_id, version_id, run_id, actor_id = config.id, config.version_id, run.id, actor
            if broken == "actor":
                actor_id = other
            elif broken == "identity":
                identity_id = uuid4()
            elif broken == "version":
                version_id = uuid4()
            elif broken == "run":
                run_id = uuid4()
            before = await defaults(session)
            with pytest.raises(AppError) as caught:
                await repository.accept_evaluation(identity_id, version_id, run_id, actor_id)
            assert caught.value.status_code in {404, 409}
            assert await defaults(session) == before
            assert (
                await session.get(RagConfigurationVersionRecord, config.version_id)
            ).evaluation_state == "pending"
    finally:
        await engine.dispose()


@pytest.mark.parametrize("concurrent_action", ["new_version", "repeat", "wrong_version"])
async def test_identity_lock_serializes_acceptance_with_version_creation_and_repeats(
    database_url, concurrent_action
):
    engine = create_async_engine(database_url)
    pending = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as initial:
            repository, config, actor, _, _, run = await seed(initial)
            await initial.commit()
            before = await defaults(initial)
            config_id, version_id, run_id = config.id, config.version_id, run.id
            # Finish this read transaction before competing sessions.
            await initial.rollback()
        async with AsyncSession(engine, expire_on_commit=False) as holder:
            first = SqlAlchemyRagConfigurationRepository(holder)
            _, number = await first.get_or_create_identity(actor, config.name)
            next_policy = replace(config.answer_policy_version, id=uuid4(), version=number)
            newer = replace(
                config,
                version_id=uuid4(),
                version=number,
                answer_policy_version=next_policy,
                answer_policy_version_id=next_policy.id,
            )
            if concurrent_action != "repeat":
                await first.add(newer)
            else:
                await first.accept_evaluation(config_id, version_id, run_id, actor)

            started = asyncio.Event()
            pid = None

            async def competitor():
                nonlocal pid
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    pid = await session.scalar(text("SELECT pg_backend_pid()"))
                    started.set()
                    second = SqlAlchemyRagConfigurationRepository(session)
                    requested_version = (
                        newer.version_id if concurrent_action == "wrong_version" else version_id
                    )
                    try:
                        result = await second.accept_evaluation(
                            config_id, requested_version, run_id, actor
                        )
                        await session.commit()
                        return result
                    except AppError as exc:
                        return exc.code

            pending = asyncio.create_task(competitor())
            async with asyncio.timeout(5):
                await started.wait()
                async with engine.connect() as observer:
                    while not await observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
                    ):
                        assert not pending.done()
                        await asyncio.sleep(0.01)
            assert not pending.done()
            await holder.commit()
            result = await asyncio.wait_for(pending, 5)
            if concurrent_action == "wrong_version":
                assert result == "evaluation_policy_required"
            else:
                assert result.configuration.version_id == version_id
                assert result.configuration.evaluation_state is EvaluationState.PASSED
        async with AsyncSession(engine) as check:
            after = dict(await defaults(check))
            assert all(after[key] == value for key, value in before)
            if concurrent_action != "repeat":
                assert after[newer.version_id] is False
                assert (
                    await check.get(RagConfigurationVersionRecord, newer.version_id)
                ).evaluation_state == "pending"
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await engine.dispose()
