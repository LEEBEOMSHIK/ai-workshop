from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterator
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ai_workshop.labs.rag.configurations.domain import (
    BM25_BASELINE_CONFIGURATION_VERSION_ID,
)
from ai_workshop.labs.rag.configurations.models import RagConfigurationVersionRecord
from ai_workshop.labs.rag.evaluation.domain import (
    EvaluationRunStatus,
    load_evaluation_dataset,
)
from ai_workshop.labs.rag.evaluation.models import (
    EvaluationRunConfigurationRecord,
    EvaluationRunRecord,
)
from ai_workshop.labs.rag.evaluation.repository import (
    SqlAlchemyEvaluationApplicationRepository,
)
from ai_workshop.labs.rag.evaluation.service import EvaluationApplicationService
from ai_workshop.learning_composition import EvaluationReferenceHandler
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.learning.models import LearningRecordRevisionRow, LearningRecordRow
from ai_workshop.platform.learning.references import ReferenceStatus
from ai_workshop.platform.learning.schemas import ReferenceKey
from ai_workshop.shared.db import create_session_factory, get_session
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.learning_support import (
    IsolatedLearningDatabase,
    isolated_learning_database,
)

pytestmark = pytest.mark.integration

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EVALUATION_FIXTURE = REPOSITORY_ROOT / "sample-data/public/rag/evaluation/search-v1.json"
HISTORICAL_RUN_CREATED_AT = datetime(2018, 2, 3, 4, 5, 6, 789000, tzinfo=UTC)


def _user(user_id: UUID, label: str) -> User:
    email = f"{label}@example.test"
    return User(
        id=user_id,
        display_name=label,
        email=email,
        normalized_email=email,
        password_hash="fixture-hash",
        role=UserRole.OWNER,
    )


async def _add_user(session: AsyncSession, user: User) -> None:
    await session.execute(
        text(
            """
            INSERT INTO users (
                id, display_name, email, normalized_email, password_hash,
                role, is_active
            ) VALUES (
                :id, :display_name, :email, :email, :password_hash,
                :role, true
            )
            """
        ),
        {
            "id": user.id,
            "display_name": user.display_name,
            "email": user.email,
            "password_hash": user.password_hash,
            "role": user.role.value,
        },
    )


def _note(
    title: str, body: str, references: list[dict[str, str | None]] | None = None
) -> dict[str, object]:
    return {
        "title": title,
        "body": body,
        "kind": "note",
        "topic_keys": ["rag"],
        "domain_labels": ["synthetic"],
        "experiment": None,
        "references": references or [],
    }


def _experiment(
    title: str,
    body: str,
    *,
    evaluation_reference: dict[str, str | None],
    dataset_reference: dict[str, str | None],
) -> dict[str, object]:
    return {
        "title": title,
        "body": body,
        "kind": "experiment",
        "topic_keys": ["rag"],
        "domain_labels": ["synthetic"],
        "experiment": {
            "purpose": "revision 보존 확인",
            "hypothesis": None,
            "dataset_snapshot": dataset_reference,
            "configurations": [],
            "environment": None,
            "procedure": None,
            "observations": None,
            "metrics": [],
            "limitations": None,
            "conclusion": None,
            "next_steps": [],
            "status": "planned",
            "troubleshooting": None,
        },
        "references": [evaluation_reference],
    }


def _error_code(response: Response) -> str:
    return str(response.json()["error"]["code"])


@pytest.fixture
def migrated_learning_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[IsolatedLearningDatabase]:
    with isolated_learning_database(monkeypatch) as database:
        command.upgrade(database.config, "0024_learning_records")
        yield database


async def test_http_service_sql_lifecycle_is_owner_only_and_rechecks_real_references(
    migrated_learning_database: IsolatedLearningDatabase,
) -> None:
    with nullcontext(migrated_learning_database) as database:
        engine = create_async_engine(
            database.database_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
        )
        sessions = create_session_factory(engine)
        owner_a = _user(uuid4(), "owner-a")
        owner_b = _user(uuid4(), "owner-b")
        run_id = uuid4()
        candidate_id = uuid4()
        execution_bytes = b'{"fixture":"read-only ownership lookup"}'
        execution_hash = hashlib.sha256(execution_bytes).hexdigest()

        try:
            async with sessions.begin() as session:
                await _add_user(session, owner_a)
                await _add_user(session, owner_b)
                evaluation_repository = SqlAlchemyEvaluationApplicationRepository(session)
                dataset = await evaluation_repository.add_or_get_dataset(
                    owner_a.id,
                    load_evaluation_dataset(EVALUATION_FIXTURE.read_bytes()),
                )
                configuration = await session.get(
                    RagConfigurationVersionRecord,
                    BM25_BASELINE_CONFIGURATION_VERSION_ID,
                )
                assert configuration is not None
                session.add(
                    EvaluationRunRecord(
                        id=run_id,
                        owner_id=owner_a.id,
                        dataset_snapshot_id=dataset.id,
                        evaluation_policy_version_id=None,
                        status=EvaluationRunStatus.PENDING.value,
                        fixture_sha256=dataset.fixture_sha256,
                        document_snapshot_sha256=dataset.document_snapshot_sha256,
                        query_set_sha256=dataset.query_set_sha256,
                        execution_snapshot={"fixture": "read-only ownership lookup"},
                        execution_snapshot_bytes=execution_bytes,
                        execution_snapshot_sha256=execution_hash,
                        runtime_environment={"execution": "not-run"},
                        worker_runtime_environment=None,
                        metric_definition_version=1,
                        retrieval_k=10,
                        repetition_count=2,
                        candidate_count=1,
                        claimed_at=None,
                        claim_token=None,
                        finished_at=None,
                        failure=None,
                        created_at=HISTORICAL_RUN_CREATED_AT,
                        updated_at=HISTORICAL_RUN_CREATED_AT,
                    )
                )
                await session.flush()
                session.add(
                    EvaluationRunConfigurationRecord(
                        id=candidate_id,
                        run_id=run_id,
                        configuration_version_id=configuration.id,
                        ordinal=0,
                        indexing_profile_id=configuration.indexing_profile_id,
                        retrieval_profile_id=configuration.retrieval_profile_id,
                        answer_policy_version_id=configuration.answer_policy_version_id,
                        generation_profile_id=configuration.generation_profile_id,
                        component_snapshot={
                            "models": [],
                            "execution_snapshot_sha256": execution_hash,
                        },
                        status="pending",
                        failure=None,
                        recall_at_k=None,
                        mrr=None,
                        ndcg=None,
                        supported_precision=None,
                        false_grounding_rate=None,
                        highlight_iou=None,
                        p50_latency_ms=None,
                        p95_latency_ms=None,
                        access_leaks=None,
                        reproducibility=None,
                        completed_at=None,
                    )
                )

            async with sessions() as session:
                evaluation_service = EvaluationApplicationService(
                    SqlAlchemyEvaluationApplicationRepository(session)
                )
                persisted_created_at = await session.scalar(
                    select(EvaluationRunRecord.created_at).where(EvaluationRunRecord.id == run_id)
                )
                detail = await evaluation_service.detail(run_id, owner_a.id)
                listed = await evaluation_service.list(owner_a.id, limit=20)
                assert persisted_created_at == HISTORICAL_RUN_CREATED_AT
                assert detail.created_at == persisted_created_at
                assert [item.created_at for item in listed] == [persisted_created_at]
                assert detail.candidates[0].id == candidate_id
                with pytest.raises(AppError) as hidden:
                    await evaluation_service.detail(run_id, owner_b.id)
                assert (hidden.value.status_code, hidden.value.code) == (404, "not_found")
                assert await evaluation_service.list(owner_b.id, limit=20) == ()

                handler = EvaluationReferenceHandler(evaluation_service)
                evaluation_key = ReferenceKey(
                    kind="rag.evaluation", target=str(run_id), version=None
                )
                visible = await handler.resolve(owner_a.id, evaluation_key)
                denied = await handler.resolve(owner_b.id, evaluation_key)
                missing = await handler.resolve(
                    owner_a.id,
                    ReferenceKey(kind="rag.evaluation", target=str(uuid4()), version=None),
                )
                assert visible.status is ReferenceStatus.AVAILABLE
                assert visible.label == "RAG evaluation · pending"
                assert visible.href is None
                assert denied == missing
                assert denied.status is ReferenceStatus.UNAVAILABLE
                assert denied.label is None and denied.href is None and denied.key is None

            actor = {"current": owner_a}

            async def override_session() -> AsyncIterator[AsyncSession]:
                async with sessions() as session:
                    yield session

            app = create_app()
            app.dependency_overrides[get_session] = override_session
            app.dependency_overrides[get_current_user] = lambda: actor["current"]
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                target_title = "권한 회수 대상 제목"
                target_body = "권한 회수 대상 비공개 본문"
                target_response = await client.post(
                    "/api/v1/learning/records",
                    json=_note(target_title, target_body),
                )
                assert target_response.status_code == 201
                target_id = UUID(target_response.json()["id"])
                learning_reference = {
                    "kind": "learning.record",
                    "target": str(target_id),
                    "version": None,
                }
                evaluation_reference = {
                    "kind": "rag.evaluation",
                    "target": str(run_id),
                    "version": None,
                }
                note_v1 = _note(
                    "통합 lifecycle 메모",
                    "revision 1 원문",
                    [learning_reference, evaluation_reference],
                )
                created = await client.post("/api/v1/learning/records", json=note_v1)
                assert created.status_code == 201
                created_json = created.json()
                record_id = UUID(created_json["id"])
                assert created_json["revision"] == 1
                assert [item["status"] for item in created_json["reference_views"]] == [
                    "available",
                    "available",
                ]

                fresh = await client.get(f"/api/v1/learning/records/{record_id}")
                assert fresh.status_code == 200
                assert fresh.json()["draft"] == created_json["draft"]
                assert fresh.json()["created_at"] == created_json["created_at"]

                experiment_v2 = _experiment(
                    "통합 lifecycle 실험",
                    "revision 2 실험 본문",
                    evaluation_reference=evaluation_reference,
                    dataset_reference=learning_reference,
                )
                updated = await client.put(
                    f"/api/v1/learning/records/{record_id}",
                    json={"expected_revision": 1, "draft": experiment_v2},
                )
                assert updated.status_code == 200
                assert updated.json()["revision"] == 2
                assert updated.json()["draft"]["kind"] == "experiment"
                assert updated.json()["dataset_reference_view"]["status"] == "available"

                stale_title = "절대 저장되면 안 되는 stale 제목"
                stale_body = "절대 저장되면 안 되는 stale 본문"
                stale = await client.put(
                    f"/api/v1/learning/records/{record_id}",
                    json={
                        "expected_revision": 1,
                        "draft": _note(stale_title, stale_body),
                    },
                )
                assert stale.status_code == 409
                assert _error_code(stale) == "learning_revision_conflict"

                actor["current"] = owner_b
                hidden_responses = [
                    await client.get(f"/api/v1/learning/records/{record_id}"),
                    await client.get(f"/api/v1/learning/records/{record_id}/revisions/1"),
                    await client.put(
                        f"/api/v1/learning/records/{record_id}",
                        json={"expected_revision": 2, "draft": _note("타인", "타인")},
                    ),
                    await client.post(
                        f"/api/v1/learning/records/{record_id}/archive",
                        json={"expected_revision": 2},
                    ),
                    await client.post(
                        f"/api/v1/learning/records/{record_id}/restore",
                        json={"expected_revision": 2},
                    ),
                ]
                foreign_list = await client.get("/api/v1/learning/records")
                assert foreign_list.status_code == 200
                assert foreign_list.json()["items"] == []
                for response in hidden_responses:
                    assert response.status_code == 404
                    assert _error_code(response) == "not_found"
                    assert "통합 lifecycle" not in response.text
                    assert "revision 2 실험 본문" not in response.text
                    assert str(record_id) not in response.text

                actor["current"] = owner_a
                archived = await client.post(
                    f"/api/v1/learning/records/{record_id}/archive",
                    json={"expected_revision": 2},
                )
                assert archived.status_code == 200
                assert archived.json()["revision"] == 3
                assert archived.json()["archived_at"] is not None
                assert archived.json()["reference_views"] == [
                    {
                        "status": "available",
                        "label": "RAG evaluation · pending",
                        "href": None,
                        "key": evaluation_reference,
                    }
                ]
                assert archived.json()["dataset_reference_view"] == {
                    "status": "available",
                    "label": target_title,
                    "href": f"/workshop/learning/{target_id}",
                    "key": learning_reference,
                }

                archived_edit = await client.put(
                    f"/api/v1/learning/records/{record_id}",
                    json={
                        "expected_revision": 3,
                        "draft": _note("보관 중 변경 금지", "보관 중 변경 금지 본문"),
                    },
                )
                assert archived_edit.status_code == 409
                assert _error_code(archived_edit) == "learning_record_archived"

                restored = await client.post(
                    f"/api/v1/learning/records/{record_id}/restore",
                    json={"expected_revision": 3},
                )
                assert restored.status_code == 200
                assert restored.json()["revision"] == 4
                assert restored.json()["archived_at"] is None
                assert restored.json()["reference_views"] == [
                    {
                        "status": "available",
                        "label": "RAG evaluation · pending",
                        "href": None,
                        "key": evaluation_reference,
                    }
                ]
                assert restored.json()["dataset_reference_view"] == {
                    "status": "available",
                    "label": target_title,
                    "href": f"/workshop/learning/{target_id}",
                    "key": learning_reference,
                }

                final_detail = await client.get(f"/api/v1/learning/records/{record_id}")
                final_list = await client.get(
                    "/api/v1/learning/records?kind=experiment&archived=false"
                )
                revision_1 = await client.get(f"/api/v1/learning/records/{record_id}/revisions/1")
                revision_2 = await client.get(f"/api/v1/learning/records/{record_id}/revisions/2")
                assert final_detail.status_code == 200
                assert final_detail.json()["revision"] == 4
                assert final_detail.json()["draft"]["body"] == "revision 2 실험 본문"
                assert [item["id"] for item in final_list.json()["items"]] == [str(record_id)]
                assert revision_1.json()["draft"]["kind"] == "note"
                assert revision_1.json()["draft"]["body"] == "revision 1 원문"
                assert revision_2.json()["draft"]["kind"] == "experiment"

            async with sessions.begin() as session:
                await session.execute(
                    update(LearningRecordRow)
                    .where(LearningRecordRow.id == target_id)
                    .values(owner_id=owner_b.id)
                )

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                current_after_revocation = await client.get(f"/api/v1/learning/records/{record_id}")
                history_after_revocation = await client.get(
                    f"/api/v1/learning/records/{record_id}/revisions/1"
                )
                experiment_history_after_revocation = await client.get(
                    f"/api/v1/learning/records/{record_id}/revisions/2"
                )
                for response in (
                    current_after_revocation,
                    history_after_revocation,
                    experiment_history_after_revocation,
                ):
                    assert response.status_code == 200
                    assert str(target_id) not in response.text
                    assert target_title not in response.text
                    assert target_body not in response.text
                    assert response.json()["unavailable_reference_count"] == 1
                assert (
                    current_after_revocation.json()["draft"]["experiment"]["dataset_snapshot"]
                    is None
                )
                assert current_after_revocation.json()["dataset_reference_view"] == {
                    "status": "unavailable",
                    "label": None,
                    "href": None,
                    "key": None,
                }
                assert history_after_revocation.json()["draft"]["references"] == [
                    evaluation_reference
                ]

            async with sessions() as session:
                current = await session.get(LearningRecordRow, record_id)
                revisions = list(
                    await session.scalars(
                        select(LearningRecordRevisionRow)
                        .where(LearningRecordRevisionRow.record_id == record_id)
                        .order_by(LearningRecordRevisionRow.revision)
                    )
                )
                assert current is not None
                assert current.owner_id == owner_a.id
                assert current.current_revision == 4
                assert [item.revision for item in revisions] == [1, 2, 3, 4]
                assert [item.archived_at is not None for item in revisions] == [
                    False,
                    False,
                    True,
                    False,
                ]
                assert revisions[0].draft["body"] == "revision 1 원문"
                assert revisions[1].draft["body"] == "revision 2 실험 본문"
                persisted_payload = str([item.draft for item in revisions])
                assert stale_title not in persisted_payload
                assert stale_body not in persisted_payload
                assert "보관 중 변경 금지" not in persisted_payload
        finally:
            await engine.dispose()
