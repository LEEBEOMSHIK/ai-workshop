from ai_workshop.config import Settings
from ai_workshop.worker import ASSET_VERIFICATION_TASK, celery_app, create_celery


def test_celery_cli_app_is_available_without_loading_application_secrets() -> None:
    assert ASSET_VERIFICATION_TASK in celery_app.tasks


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
