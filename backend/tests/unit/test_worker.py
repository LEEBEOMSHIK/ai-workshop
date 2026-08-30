import pytest
from sqlalchemy.exc import DisconnectionError, IntegrityError, OperationalError, TimeoutError

from ai_workshop.config import Settings
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.worker import ASSET_VERIFICATION_TASK, _rag_error, celery_app, create_celery


def test_celery_cli_app_is_available_without_loading_application_secrets() -> None:
    assert ASSET_VERIFICATION_TASK in celery_app.tasks


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
