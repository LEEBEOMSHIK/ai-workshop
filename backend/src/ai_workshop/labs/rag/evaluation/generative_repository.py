import hashlib
import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.evaluation.domain import EvaluationDataset
from ai_workshop.labs.rag.evaluation.generative import (
    ExpectedAnswerRule,
    PrivateGenerativeResult,
)
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativePolicyRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.repository import SqlAlchemyEvaluationApplicationRepository
from ai_workshop.shared.errors import AppError


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def unavailable() -> AppError:
    return AppError("not_found", "The evaluation is unavailable.", 404)


class GenerativeRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @staticmethod
    async def retry_failed(session: AsyncSession, actor_id: UUID, run_id: UUID) -> None:
        run = await session.scalar(
            select(GenerativeRunRecord)
            .where(
                GenerativeRunRecord.id == run_id,
                GenerativeRunRecord.owner_id == actor_id,
            )
            .with_for_update()
        )
        if run is None:
            raise unavailable()
        if run.status != "failed":
            raise AppError("evaluation_retry_unavailable", "Only a failed run can be retried.", 409)
        rows = (
            await session.scalars(
                select(GenerativeAttemptRecord)
                .where(
                    GenerativeAttemptRecord.run_id == run_id,
                )
                .order_by(GenerativeAttemptRecord.attempt_number)
            )
        ).all()
        latest = {(r.configuration_version_id, r.case_id, r.repetition): r for r in rows}
        failed = [r for r in latest.values() if r.status in {"failed", "interrupted"}]
        if not failed:
            raise AppError("evaluation_retry_unavailable", "No failed attempts remain.", 409)
        run.status, run.claim_token, run.claimed_at, run.finished_at = "pending", None, None, None
        run.dispatched_at = None
        await session.flush()
        for old in failed:
            session.add(
                GenerativeAttemptRecord(
                    id=uuid4(),
                    run_id=run_id,
                    configuration_version_id=old.configuration_version_id,
                    case_id=old.case_id,
                    repetition=old.repetition,
                    attempt_number=old.attempt_number + 1,
                    execution_id=uuid4(),
                    status="pending",
                )
            )
        await session.flush()

    @staticmethod
    async def submit(
        session: AsyncSession,
        freezer: SqlAlchemyEvaluationApplicationRepository,
        *,
        actor_id: UUID,
        request_id: UUID,
        dataset: EvaluationDataset,
        policy_id: UUID,
        versions: tuple[UUID, ...],
        rules: dict[UUID, ExpectedAnswerRule],
        repetitions: int,
        input_approval: dict[str, object] | None,
        retrieval_k: int = 10,
        case_histories: dict[str, list[dict[str, object]]] | None = None,
    ) -> GenerativeRunRecord:
        # A transaction-level owner lock serializes idempotency checks and insertions.
        from ai_workshop.platform.identity.models import UserRecord

        await session.scalar(select(UserRecord).where(UserRecord.id == actor_id).with_for_update())
        existing = await session.scalar(
            select(GenerativeRunRecord).where(
                GenerativeRunRecord.owner_id == actor_id,
                GenerativeRunRecord.request_id == request_id,
            )
        )
        if existing is not None:
            if (
                existing.dataset_snapshot_id != dataset.id
                or existing.policy_id != policy_id
                or existing.repetition_count != repetitions
                or existing.expected_rules
                != {str(k): v.model_dump(mode="json") for k, v in rules.items()}
                or existing.input_approval != input_approval
                or existing.snapshot.get("retrieval_k", 10) != retrieval_k
                or existing.snapshot.get("case_histories", {}) != (case_histories or {})
                or [
                    c["configuration_version_id"]
                    for c in cast(list[dict[str, object]], existing.snapshot["candidates"])
                ]
                != [str(v) for v in versions]
            ):
                raise AppError("request_conflict", "The request ID belongs to other inputs.", 409)
            return existing
        policy = await session.get(GenerativePolicyRecord, policy_id)
        if policy is None or policy.owner_id != actor_id:
            raise unavailable()
        if not versions or len(versions) != len(set(versions)) or not 2 <= repetitions <= 5:
            raise AppError("invalid_evaluation_input", "Invalid candidates or repetitions.", 422)
        if set(rules) != {case.id for case in dataset.cases}:
            raise AppError("expected_rules_incomplete", "Every frozen case requires a rule.", 422)
        if not set(case_histories or {}).issubset(str(case.id) for case in dataset.cases):
            raise AppError("history_case_mismatch", "History belongs to an unknown case.", 422)
        if any(len(turns) > 20 for turns in (case_histories or {}).values()):
            raise AppError(
                "history_limit_exceeded", "At most twenty frozen turns are allowed.", 422
            )
        for case in dataset.cases:
            expected_status = (
                "answered"
                if case.expected_answer_status == "supported"
                else "insufficient_evidence"
            )
            if rules[case.id].expected_answer_status != expected_status:
                raise AppError(
                    "expected_rule_mismatch", "Rule status differs from the dataset.", 422
                )
            required = {v for group in rules[case.id].required_evidence_groups for v in group}
            if not required.issubset(case.expected_evidence_ids):
                raise AppError(
                    "expected_rule_mismatch", "Rule evidence differs from the dataset.", 422
                )
        snapshots = []
        for version in versions:
            item = await freezer._configuration_snapshot(version, actor_id, dataset)
            if item is None or item[0].generation_profile_id is None:
                raise AppError(
                    "generation_profile_required", "An exact generation profile is required.", 409
                )
            snapshots.append(item)
        snapshot = await freezer._execution_snapshot(
            actor_id=actor_id,
            dataset=dataset,
            snapshots=snapshots,
        )
        snapshot["retrieval_k"] = retrieval_k
        snapshot["case_histories"] = case_histories or {}
        raw = canonical(snapshot)
        expected = {str(k): v.model_dump(mode="json") for k, v in rules.items()}
        run = GenerativeRunRecord(
            id=uuid4(),
            owner_id=actor_id,
            request_id=request_id,
            dataset_snapshot_id=dataset.id,
            policy_id=policy_id,
            metric_version="generative-v1",
            snapshot=snapshot,
            snapshot_bytes=raw,
            snapshot_digest=hashlib.sha256(raw).hexdigest(),
            expected_rules=expected,
            rules_digest=hashlib.sha256(canonical(expected)).hexdigest(),
            repetition_count=repetitions,
            input_approval=input_approval,
            status="pending",
        )
        session.add(run)
        await session.flush()
        for version in versions:
            for case in dataset.cases:
                for repetition in range(repetitions):
                    session.add(
                        GenerativeAttemptRecord(
                            id=uuid4(),
                            run_id=run.id,
                            configuration_version_id=version,
                            case_id=case.id,
                            repetition=repetition,
                            attempt_number=1,
                            execution_id=uuid4(),
                            status="pending",
                        )
                    )
        await session.flush()
        return run

    async def claim_run(self, run_id: UUID, environment: dict[str, object]) -> UUID | None:
        async with self.sessions.begin() as session:
            run = await session.scalar(
                select(GenerativeRunRecord)
                .where(
                    GenerativeRunRecord.id == run_id,
                )
                .with_for_update()
            )
            if run is None or run.status != "pending":
                return None
            token = uuid4()
            run.status, run.claim_token, run.claimed_at = "running", token, datetime.now(UTC)
            run.runtime_environment = environment
            return token

    async def heartbeat(self, run_id: UUID, token: UUID) -> bool:
        async with self.sessions.begin() as session:
            run = await session.scalar(
                select(GenerativeRunRecord)
                .where(
                    GenerativeRunRecord.id == run_id,
                )
                .with_for_update()
            )
            if run is None or run.status != "running" or run.claim_token != token:
                return False
            run.claimed_at = datetime.now(UTC)
            return True

    async def interrupt_stale(self, before: datetime) -> int:
        # A lost worker is never replayed automatically: a provider may have answered.
        async with self.sessions.begin() as session:
            runs = (
                await session.scalars(
                    select(GenerativeRunRecord)
                    .where(
                        GenerativeRunRecord.status == "running",
                        GenerativeRunRecord.claimed_at < before,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for run in runs:
                attempts = (
                    await session.scalars(
                        select(GenerativeAttemptRecord)
                        .where(
                            GenerativeAttemptRecord.run_id == run.id,
                            GenerativeAttemptRecord.status.in_(("pending", "running")),
                        )
                        .with_for_update()
                    )
                ).all()
                for attempt in attempts:
                    attempt.claim_token = run.claim_token
                    attempt.status = "interrupted"
                    attempt.error_code = "evaluation_worker_interrupted"
                    attempt.finished_at = datetime.now(UTC)
                # The attempt guard requires the current parent claim while fencing children.
                await session.flush()
                run.status = "failed"
                run.claim_token = None
                run.claimed_at = None
                run.finished_at = datetime.now(UTC)
            return len(runs)

    async def claim_attempt(self, attempt_id: UUID, token: UUID) -> GenerativeAttemptRecord | None:
        async with self.sessions.begin() as session:
            row = await session.get(GenerativeAttemptRecord, attempt_id)
            if row is None:
                return None
            run = await session.scalar(
                select(GenerativeRunRecord)
                .where(
                    GenerativeRunRecord.id == row.run_id,
                )
                .with_for_update()
            )
            if run is None or run.status != "running" or run.claim_token != token:
                return None
            await session.refresh(row, with_for_update=True)
            if row.status != "pending":
                return None
            row.claim_token, row.status = token, "running"
            await session.flush()
            return row

    async def complete_attempt(
        self,
        attempt_id: UUID,
        token: UUID,
        result: PrivateGenerativeResult,
        *,
        error_code: str | None = None,
    ) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(GenerativeAttemptRecord, attempt_id)
            if row is None:
                raise unavailable()
            run = await session.scalar(
                select(GenerativeRunRecord)
                .where(
                    GenerativeRunRecord.id == row.run_id,
                )
                .with_for_update()
            )
            await session.refresh(row, with_for_update=True)
            if (
                run is None
                or run.status != "running"
                or run.claim_token != token
                or row.status != "running"
                or row.claim_token != token
            ):
                raise AppError("evaluation_claim_lost", "The execution claim has expired.", 409)
            if result.observation.execution_id != row.execution_id:
                raise ValueError("Observation belongs to another execution.")
            row.result = result.model_dump(mode="json")
            row.result_bytes, row.result_digest = canonical(row.result), result.digest()
            row.error_code, row.finished_at = error_code, datetime.now(UTC)
            row.status = "failed" if error_code else "completed"

    async def finish_run(self, run_id: UUID, token: UUID) -> None:
        async with self.sessions.begin() as session:
            run = await session.scalar(
                select(GenerativeRunRecord)
                .where(
                    GenerativeRunRecord.id == run_id,
                )
                .with_for_update()
            )
            if run is None or run.status != "running" or run.claim_token != token:
                raise AppError("evaluation_claim_lost", "The execution claim has expired.", 409)
            rows = (
                await session.scalars(
                    select(GenerativeAttemptRecord)
                    .where(
                        GenerativeAttemptRecord.run_id == run_id,
                    )
                    .order_by(GenerativeAttemptRecord.attempt_number)
                )
            ).all()
            latest = {(r.configuration_version_id, r.case_id, r.repetition): r for r in rows}
            if any(r.status in {"pending", "running"} for r in latest.values()):
                raise AppError("evaluation_incomplete", "Attempts remain unfinished.", 409)
            run.status = (
                "completed" if all(r.status == "completed" for r in latest.values()) else "failed"
            )
            run.claim_token, run.claimed_at, run.finished_at = None, None, datetime.now(UTC)
