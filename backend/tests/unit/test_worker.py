from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import DisconnectionError, IntegrityError, OperationalError, TimeoutError

import ai_workshop.worker as worker_module
from ai_workshop.config import Settings
from ai_workshop.labs.rag.indexing.recovery import (
    RagAliasParityFailure,
    RagAliasParityResult,
    RagAliasParityRunError,
)
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand
from ai_workshop.labs.rag.ingestion.handoff import (
    RagAssetHandoffIdentity,
    RagAssetHandoffResult,
    RagAssetHandoffRunError,
)
from ai_workshop.labs.rag.ingestion.stages import (
    ProductionChunkingStage,
    ProductionEmbeddingStage,
)
from ai_workshop.labs.rag.ingestion.tasks import create_rag_ingestion_workflow
from ai_workshop.platform.assets.tasks import AssetTaskError
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.worker import (
    ASSET_VERIFICATION_TASK,
    RAG_DISPATCH_RECONCILE_TASK,
    RAG_EVALUATION_DISPATCH_RECONCILE_TASK,
    RAG_EVALUATION_TASK,
    RAG_INGESTION_TASK,
    CeleryEvaluationRunSender,
    CeleryRagJobSender,
    VerifiedAssetSubscription,
    _log_handoff_run_error,
    _rag_error,
    _raise_on_alias_parity_failures,
    _raise_on_handoff_failures,
    celery_app,
    create_celery,
)


def test_celery_cli_app_is_available_without_loading_application_secrets() -> None:
    assert ASSET_VERIFICATION_TASK in celery_app.tasks
    assert RAG_DISPATCH_RECONCILE_TASK in celery_app.tasks
    assert RAG_EVALUATION_TASK in celery_app.tasks
    assert RAG_EVALUATION_DISPATCH_RECONCILE_TASK in celery_app.tasks
    assert celery_app.conf.beat_schedule["reconcile-rag-ingestion-dispatches"] == {
        "task": RAG_DISPATCH_RECONCILE_TASK,
        "schedule": 5.0,
    }
    assert celery_app.conf.beat_schedule["reconcile-rag-evaluation-dispatches"] == {
        "task": RAG_EVALUATION_DISPATCH_RECONCILE_TASK,
        "schedule": 5.0,
    }
    assert celery_app.conf.beat_schedule["reconcile-asset-verification-dispatches"] == {
        "task": "ai_workshop.assets.reconcile_dispatches",
        "schedule": 5.0,
    }
    assert celery_app.conf.beat_schedule["reconcile-rag-asset-handoffs"] == {
        "task": "ai_workshop.rag.reconcile_asset_handoffs",
        "schedule": 5.0,
    }


def test_handoff_beat_failure_is_logged_and_signaled_after_batch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    result = RagAssetHandoffResult(claimed=3, created=2, failed=1)

    with caplog.at_level("ERROR"), pytest.raises(RagAssetHandoffRunError):
        _raise_on_handoff_failures(result)

    assert "rag_asset_handoff_reconcile_failed claimed=3 created=2 failed=1" in caplog.text


def test_unknown_handoff_log_carries_bounded_exact_identities(
    caplog: pytest.LogCaptureFixture,
) -> None:
    identities = tuple(
        RagAssetHandoffIdentity(uuid4(), uuid4()) for _ in range(25)
    )
    error = RagAssetHandoffRunError(
        RagAssetHandoffResult(claimed=25, created=0, failed=25),
        identities=identities,
    )

    with caplog.at_level("ERROR"):
        _log_handoff_run_error(error)

    assert "rag_asset_handoff_reconcile_unexpected_failure" in caplog.text
    assert str(identities[0].asset_version_id) in caplog.text
    assert str(identities[0].indexing_profile_id) in caplog.text
    assert str(identities[19].asset_version_id) in caplog.text
    assert str(identities[20].asset_version_id) not in caplog.text


def test_alias_parity_beat_logs_safe_profile_failures_and_signals(
    caplog: pytest.LogCaptureFixture,
) -> None:
    first_profile_id = uuid4()
    second_profile_id = uuid4()
    result = RagAliasParityResult(
        claimed=3,
        reconciled=1,
        failed=2,
        failures=(
            RagAliasParityFailure(
                first_profile_id,
                "alias_parity_search_transient",
                True,
                "ConnectionTimeout",
            ),
            RagAliasParityFailure(
                second_profile_id,
                "alias_parity_invalid_build",
                False,
                "RagAliasParityError",
            ),
        ),
    )

    with caplog.at_level("ERROR"), pytest.raises(RagAliasParityRunError) as raised:
        _raise_on_alias_parity_failures(result)

    assert raised.value.result is result
    assert str(first_profile_id) in caplog.text
    assert str(second_profile_id) in caplog.text
    assert "alias_parity_search_transient" in caplog.text
    assert "alias_parity_invalid_build" in caplog.text


def test_worker_registers_every_table_referenced_by_jobs() -> None:
    referenced_tables = {
        foreign_key.column.table.name for foreign_key in JobRecord.__table__.foreign_keys
    }

    assert referenced_tables == {"asset_versions", "users", "workspaces"}


def test_test_environment_executes_celery_tasks_eagerly_without_a_result_backend() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="x" * 32,
        redis_url="redis://unused:6379/0",
    )
    app = create_celery(settings)

    @app.task(name="tests.echo")
    def echo(value: str) -> str:
        return value

    result = echo.delay("stored")

    assert result.get() == "stored"
    assert app.conf.result_backend is None
    assert "ai_workshop.assets.verify_stored" in app.tasks


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("statement", {}, OSError("connection lost")),
        TimeoutError("pool timeout"),
        DisconnectionError("connection invalidated"),
    ],
)
def test_only_transient_sqlalchemy_database_signals_are_retryable(error: Exception) -> None:
    _code, retryable = _rag_error(error)

    assert retryable is True


def test_integrity_error_is_never_classified_as_retryable() -> None:
    error = IntegrityError("insert", {}, ValueError("constraint violation"))

    _code, retryable = _rag_error(error)

    assert retryable is False


def test_reconciler_sender_sends_only_the_persisted_job_id() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="x" * 32,
        redis_url="redis://unused:6379/0",
    )
    job_id = uuid4()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    application = create_celery(settings)
    task = application.tasks[RAG_INGESTION_TASK]
    task.delay = lambda *args, **kwargs: calls.append((args, kwargs))  # type: ignore[method-assign]

    CeleryRagJobSender(application).send(job_id)

    assert calls == [((str(job_id),), {})]


def test_evaluation_sender_sends_only_the_persisted_run_id() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="x" * 32,
        redis_url="redis://unused:6379/0",
    )
    run_id = uuid4()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    application = create_celery(settings)
    task = application.tasks[RAG_EVALUATION_TASK]
    task.delay = lambda *args, **kwargs: calls.append((args, kwargs))  # type: ignore[method-assign]

    CeleryEvaluationRunSender(application).send(run_id)

    assert calls == [((str(run_id),), {})]


def test_evaluation_task_reloads_the_persisted_run_id_only() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="x" * 32,
        redis_url="redis://unused:6379/0",
    )
    run_id = uuid4()
    calls: list[UUID] = []

    class Workflow:
        async def run(self, persisted_run_id: UUID) -> None:
            calls.append(persisted_run_id)

    app = create_celery(
        settings,
        evaluation_workflow_factory=lambda _settings: Workflow(),  # type: ignore[arg-type]
    )

    result = app.tasks[RAG_EVALUATION_TASK].delay(str(run_id))

    assert result.get() is None
    assert calls == [run_id]


def test_evaluation_task_uses_late_ack_and_worker_loss_redelivery() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="x" * 32,
        redis_url="redis://unused:6379/0",
    )
    task = create_celery(settings).tasks[RAG_EVALUATION_TASK]

    assert task.acks_late is True
    assert task.reject_on_worker_lost is True


def test_rag_ingestion_task_uses_late_ack_and_worker_loss_redelivery() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="x" * 32,
        redis_url="redis://unused:6379/0",
    )
    task = create_celery(settings).tasks[RAG_INGESTION_TASK]

    assert task.acks_late is True
    assert task.reject_on_worker_lost is True
    assert task.max_retries == 1


def test_production_chunking_and_embedding_share_one_pinned_model_runtime() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="x" * 32,
        redis_url="redis://unused:6379/0",
    )

    workflow = create_rag_ingestion_workflow(settings)

    assert isinstance(workflow.chunker, ProductionChunkingStage)
    assert isinstance(workflow.embeddings, ProductionEmbeddingStage)
    assert workflow.chunker.runtime_provider is workflow.embeddings.runtime_provider


def test_asset_verification_uses_late_ack_worker_loss_and_bounded_retry() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="x" * 32,
        redis_url="redis://unused:6379/0",
    )
    task = create_celery(settings).tasks[ASSET_VERIFICATION_TASK]

    assert task.acks_late is True
    assert task.reject_on_worker_lost is True
    assert task.max_retries == 3


def test_asset_verification_retries_a_retryable_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_version_id = uuid4()

    class Workflow:
        def __init__(self) -> None:
            self.attempts = 0

        async def run(self, _job_id: UUID) -> UUID:
            self.attempts += 1
            if self.attempts == 1:
                raise AssetTaskError(
                    "object_unavailable",
                    "Synthetic object outage.",
                    retryable=True,
                )
            return asset_version_id

    class Subscriptions:
        async def for_asset(
            self, _asset_version_id: UUID
        ) -> tuple[VerifiedAssetSubscription, ...]:
            return ()

    workflow = Workflow()
    monkeypatch.setattr(
        worker_module,
        "create_asset_verification_workflow",
        lambda _settings: workflow,
    )
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="x" * 32,
        redis_url="redis://unused:6379/0",
    )

    app = create_celery(
        settings,
        rag_subscriptions=Subscriptions(),
    )
    app.conf.task_eager_propagates = False
    result = app.tasks[ASSET_VERIFICATION_TASK].delay(str(uuid4()))

    assert result.get() is None
    assert workflow.attempts == 2


def test_asset_verification_does_not_retry_a_permanent_checksum_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Workflow:
        def __init__(self) -> None:
            self.attempts = 0

        async def run(self, _job_id: UUID) -> UUID:
            self.attempts += 1
            raise AssetTaskError(
                "checksum_mismatch",
                "Synthetic checksum mismatch.",
                retryable=False,
            )

    workflow = Workflow()
    monkeypatch.setattr(
        worker_module,
        "create_asset_verification_workflow",
        lambda _settings: workflow,
    )
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="x" * 32,
        redis_url="redis://unused:6379/0",
    )
    task = create_celery(settings).tasks[ASSET_VERIFICATION_TASK]

    with pytest.raises(RuntimeError, match="checksum_mismatch"):
        task.delay(str(uuid4()))

    assert workflow.attempts == 1


def test_verified_asset_enqueues_distinct_profiles_with_job_ids_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_version_id = uuid4()
    first_profile_id = uuid4()
    second_profile_id = uuid4()
    first_requester = uuid4()
    duplicate_requester = uuid4()

    class VerificationWorkflow:
        async def run(self, job_id: UUID) -> UUID:
            del job_id
            return asset_version_id

    class Subscriptions:
        async def for_asset(
            self, verified_asset_version_id: UUID
        ) -> tuple[VerifiedAssetSubscription, ...]:
            assert verified_asset_version_id == asset_version_id
            return (
                VerifiedAssetSubscription(first_profile_id, first_requester),
                VerifiedAssetSubscription(first_profile_id, duplicate_requester),
                VerifiedAssetSubscription(second_profile_id, first_requester),
            )

    commands: list[EnsureIndexedCommand] = []
    persisted_job_ids: list[UUID] = []

    async def ensure_job(
        settings: Settings,
        command: EnsureIndexedCommand,
    ) -> UUID:
        del settings
        commands.append(command)
        job_id = uuid4()
        persisted_job_ids.append(job_id)
        return job_id

    monkeypatch.setattr(
        worker_module,
        "create_asset_verification_workflow",
        lambda _settings: VerificationWorkflow(),
    )
    monkeypatch.setattr(worker_module, "_ensure_rag_job", ensure_job)
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="x" * 32,
        redis_url="redis://unused:6379/0",
    )
    app = create_celery(settings, rag_subscriptions=Subscriptions())
    dispatched: list[str] = []
    app.tasks[RAG_INGESTION_TASK].delay = lambda job_id: dispatched.append(job_id)  # type: ignore[method-assign]

    app.tasks[ASSET_VERIFICATION_TASK].delay(str(uuid4()))

    assert [command.indexing_profile_id for command in commands] == [
        first_profile_id,
        second_profile_id,
    ]
    assert [command.requested_by for command in commands] == [
        first_requester,
        first_requester,
    ]
    assert len(persisted_job_ids) == 2
    assert dispatched == []
