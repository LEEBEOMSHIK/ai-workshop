"""Original connection, existing public snapshot; all synthetic writes roll back."""

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

import ai_workshop.main  # noqa: F401
from ai_workshop.config import get_settings
from ai_workshop.labs.rag.evaluation.generative import (
    ClaimCitation,
    GenerativeObservation,
    PrivateGenerativeResult,
)
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_read import run_detail
from ai_workshop.labs.rag.evaluation.generative_repository import GenerativeRepository, canonical
from ai_workshop.shared.db import create_engine


async def test_original_json_storage_and_authorized_view_preserve_exact_claim_boundaries():
    engine = create_engine(get_settings())
    run_id, attempt_id, execution_id = (uuid4() for _ in range(3))
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
                )
                async with sessions() as session:
                    template = await session.get(
                        GenerativeRunRecord, UUID("b5cd916f-01fa-43c1-8cd2-37a5655c2394"),
                    )
                    assert template is not None, "Existing approved synthetic evaluation required"
                    original = await session.scalar(
                        select(GenerativeAttemptRecord).where(
                            GenerativeAttemptRecord.run_id == template.id,
                            GenerativeAttemptRecord.status == "completed",
                            func.jsonb_array_length(
                                GenerativeAttemptRecord.result["citations"],
                            ) > 0,
                        ).order_by(GenerativeAttemptRecord.created_at).limit(1),
                    )
                    assert original is not None and original.result is not None
                    previous = PrivateGenerativeResult.model_validate(original.result)
                    assert previous.citations, "Existing cited synthetic answer required"
                    citation_ids = previous.citations[0].evidence_ids
                    configuration_id, case_id = original.configuration_version_id, original.case_id
                    owner_id = template.owner_id
                    session.add(GenerativeRunRecord(
                        id=run_id, owner_id=owner_id, request_id=uuid4(),
                        dataset_snapshot_id=template.dataset_snapshot_id,
                        policy_id=template.policy_id, snapshot=template.snapshot,
                        snapshot_bytes=template.snapshot_bytes,
                        snapshot_digest=template.snapshot_digest,
                        expected_rules=template.expected_rules, rules_digest=template.rules_digest,
                        repetition_count=template.repetition_count,
                        input_approval=template.input_approval,
                    ))
                    await session.flush()
                    session.add(GenerativeAttemptRecord(
                        id=attempt_id, run_id=run_id,
                        configuration_version_id=configuration_id, case_id=case_id,
                        repetition=0, attempt_number=1, execution_id=execution_id,
                    ))
                    await session.commit()
                repository = GenerativeRepository(sessions)
                token = await repository.claim_run(run_id, {"fixture": "synthetic rollback"})
                assert token is not None
                assert await repository.claim_attempt(attempt_id, token) is not None
                texts = ("Synthetic sentence. Still one claim", "and the next claim.")
                result = PrivateGenerativeResult(
                    observation=GenerativeObservation(
                        execution_id=execution_id, generation_status="answered",
                        retrieved_evidence_ids=citation_ids, selected_evidence_ids=citation_ids,
                        cited_evidence_ids=citation_ids, citation_valid=True,
                    ),
                    answer=" ".join(texts),
                    citations=tuple(
                        ClaimCitation(claim_index=i, evidence_ids=citation_ids, claim_text=value)
                        for i, value in enumerate(texts)
                    ),
                )
                await repository.complete_attempt(attempt_id, token, result)
                async with sessions() as session:
                    stored = await session.get(GenerativeAttemptRecord, attempt_id)
                    assert stored is not None
                    assert stored.result == result.model_dump(mode="json")
                    assert stored.result_bytes == canonical(stored.result)
                    assert stored.result_digest == result.digest()
                    detail = await run_detail(session, owner_id, run_id)
                    attempt = next(a for a in detail.attempts if a.id == attempt_id)
                    assert [c.claim_text for c in attempt.claim_citations] == list(texts)
                    assert attempt.result_digest == result.digest()
            finally:
                await transaction.rollback()
            assert connection.get_transaction() is None
            assert await connection.scalar(
                select(GenerativeRunRecord.id).where(GenerativeRunRecord.id == run_id),
            ) is None
            assert await connection.scalar(
                select(GenerativeAttemptRecord.id).where(GenerativeAttemptRecord.id == attempt_id),
            ) is None
    finally:
        await engine.dispose()
