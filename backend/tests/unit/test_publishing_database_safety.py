from __future__ import annotations

from contextlib import AbstractContextManager
from types import SimpleNamespace

import pytest

from ai_workshop.config import Settings
from tests.integration import publishing_support
from tests.integration.publishing_support import validate_disposable_database_target

DATABASE = "ai_workshop_publishing_" + "a" * 32
ERROR = "unsafe_disposable_database_target"


def _settings(*, url: str, environment: str = "local") -> Settings:
    return Settings(
        _env_file=None,
        environment=environment,
        publishing_delivery_mode="manual" if environment == "production" else "local",
        secret_key="offline-test-secret-not-a-credential",
        database_url=url,
    )


def _validate(settings: Settings, database: str = DATABASE) -> None:
    validate_disposable_database_target(settings, database)


@pytest.mark.parametrize("environment", ["local", "test"])
@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_local_disposable_target_allowed(environment: str, host: str) -> None:
    _validate(
        _settings(
            environment=environment,
            url=f"postgresql+psycopg://test:test@{host}:5432/source",
        )
    )


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://test:test@db.example.test/source",
        "postgresql+psycopg://test:test@127.0.0.1/source?host=db.example.test",
        "postgresql+psycopg://test:test@127.0.0.1/source?hostaddr=192.0.2.1",
        "postgresql+psycopg://test:test@127.0.0.1/source?service=external",
        "postgresql+psycopg://test:test@127.0.0.1,db.example.test/source",
        "sqlite:///local.db",
    ],
)
def test_remote_or_overridden_connection_is_rejected(url: str) -> None:
    with pytest.raises(ValueError, match=f"^{ERROR}$"):
        _validate(_settings(url=url))


def test_production_environment_is_rejected() -> None:
    with pytest.raises(ValueError, match=f"^{ERROR}$"):
        _validate(
            _settings(
                environment="production",
                url="postgresql+psycopg://test:test@127.0.0.1/source",
            )
        )


@pytest.mark.parametrize("url", ["postgresql+psycopg:///source", "not a url"])
def test_missing_host_or_malformed_url_is_rejected_without_disclosure(url: str) -> None:
    with pytest.raises(ValueError) as exc_info:
        _validate(_settings(url=url))
    assert str(exc_info.value) == ERROR
    if url == "not a url":
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__suppress_context__


@pytest.mark.parametrize(
    "database",
    [
        "ai_workshop_publishing_" + "a" * 31,
        "ai_workshop_publishing_" + "g" * 32,
        "source",
    ],
)
def test_non_generated_or_source_database_name_is_rejected(database: str) -> None:
    with pytest.raises(ValueError, match=f"^{ERROR}$"):
        _validate(
            _settings(url="postgresql+psycopg://test:test@127.0.0.1/source"),
            database,
        )


@pytest.mark.parametrize("variable", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"])
def test_libpq_routing_environment_is_rejected(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, "configured")
    with pytest.raises(ValueError, match=f"^{ERROR}$"):
        _validate(_settings(url="postgresql+psycopg://test:test@127.0.0.1/source"))


def test_empty_libpq_routing_environment_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
        monkeypatch.setenv(variable, "")
    _validate(_settings(url="postgresql+psycopg://test:test@127.0.0.1/source"))


def test_connect_timeout_is_the_only_allowed_query_parameter() -> None:
    _validate(
        _settings(
            url="postgresql+psycopg://test:test@127.0.0.1/source?connect_timeout=2"
        )
    )


def test_unsafe_fixture_target_is_rejected_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(url="postgresql+psycopg://test:test@db.example.test/source")
    monkeypatch.setattr(publishing_support, "Settings", lambda **_kwargs: settings)

    def unexpected_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("database connection must not be attempted")

    monkeypatch.setattr(publishing_support.psycopg, "connect", unexpected_connect)

    with (
        pytest.raises(ValueError, match=f"^{ERROR}$"),
        publishing_support.isolated_publishing_database(monkeypatch),
    ):
        raise AssertionError("unsafe fixture must not yield")


class _RecordingConnection(AbstractContextManager["_RecordingConnection"]):
    def __init__(
        self,
        events: list[tuple[str, str]],
        *,
        fail_create: bool = False,
    ) -> None:
        self._events = events
        self._fail_create = fail_create

    def __enter__(self) -> _RecordingConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: object) -> None:
        rendered = repr(statement)
        action = "drop" if "DROP DATABASE" in rendered else "create"
        self._events.append((action, rendered))
        if action == "create" and self._fail_create:
            raise RuntimeError("synthetic create failure")


def _install_recording_fixture_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    events: list[tuple[str, str]],
    *,
    fail_create: bool = False,
) -> None:
    settings = _settings(url="postgresql+psycopg://test:test@127.0.0.1/source")
    monkeypatch.setattr(publishing_support, "Settings", lambda **_kwargs: settings)
    monkeypatch.setattr(
        publishing_support,
        "uuid4",
        lambda: SimpleNamespace(hex="b" * 32),
    )

    def connect(database_url: str, **_kwargs: object) -> _RecordingConnection:
        events.append(("connect", database_url))
        return _RecordingConnection(events, fail_create=fail_create)

    monkeypatch.setattr(publishing_support.psycopg, "connect", connect)


def test_create_failure_does_not_attempt_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, str]] = []
    _install_recording_fixture_dependencies(monkeypatch, events, fail_create=True)

    with (
        pytest.raises(RuntimeError, match="^synthetic create failure$"),
        publishing_support.isolated_publishing_database(monkeypatch),
    ):
        raise AssertionError("failed CREATE must not yield")

    assert [action for action, _detail in events] == ["connect", "create"]


def test_created_database_is_validated_in_order_before_exact_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str]] = []
    _install_recording_fixture_dependencies(monkeypatch, events)
    original_validator = publishing_support.validate_disposable_database_target
    original_name_guard = publishing_support._require_exact_database_name

    def record_validator(settings: Settings, database: str) -> None:
        events.append(("validator", database))
        original_validator(settings, database)

    def record_name_guard(database: str) -> None:
        events.append(("exact_name", database))
        original_name_guard(database)

    def record_current_database(_database_url: str, expected: str) -> None:
        events.append(("current_database", expected))

    monkeypatch.setattr(
        publishing_support, "validate_disposable_database_target", record_validator
    )
    monkeypatch.setattr(publishing_support, "_require_exact_database_name", record_name_guard)
    monkeypatch.setattr(publishing_support, "_assert_current_database", record_current_database)

    with publishing_support.isolated_publishing_database(monkeypatch) as database:
        events.append(("yield", database.name))

    expected = "ai_workshop_publishing_" + "b" * 32
    cleanup = events[events.index(("yield", expected)) + 1 :]
    assert [action for action, _detail in cleanup] == [
        "validator",
        "exact_name",
        "current_database",
        "connect",
        "drop",
    ]
    assert expected in cleanup[-1][1]
