import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
import pytest
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.engine import Engine

from ai_workshop.config import Settings, get_settings
from alembic import command
from tests.integration import rag_isolation_support as support

pytest_plugins = ["pytester"]


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@remote.example/db",
        "postgresql+psycopg://u:p@127.0.0.1/db?host=remote.example",
        "postgresql+psycopg://u:p@127.0.0.1/db?service=production",
        "sqlite:///local.db",
    ],
)
def test_unsafe_provisioning_url_rejected_before_connection(url: str) -> None:
    with pytest.raises(ValueError):
        support.validated_urls("test", url, "ai_workshop_rag_test_" + "a" * 32)


def test_production_environment_rejected() -> None:
    with pytest.raises(ValueError):
        support.validated_urls(
            "production",
            "postgresql+psycopg://u:p@localhost/db",
            "ai_workshop_rag_test_" + "a" * 32,
        )


@pytest.mark.parametrize(
    "target",
    [
        "ai_workshop_local_clean",
        "postgres",
        "ai_workshop_rag_test_bad",
        "ai_workshop_rag_test_" + "a" * 32 + "_extra",
    ],
)
def test_existing_or_malformed_database_targets_rejected(target: str) -> None:
    with pytest.raises(ValueError):
        support.validated_urls("local", "postgresql+psycopg://u:p@localhost/db", target)


def test_provisioning_uses_only_admin_postgres_and_exact_disposable_target() -> None:
    admin, isolated = support.validated_urls(
        "local",
        "postgresql+psycopg://u:p@127.0.0.1:15432/ai_workshop_local_clean",
        "ai_workshop_rag_test_" + "a" * 32,
    )
    assert admin == "postgresql://u:p@127.0.0.1:15432/postgres"
    assert isolated == "postgresql+psycopg://u:p@127.0.0.1:15432/ai_workshop_rag_test_" + "a" * 32


def test_cleanup_failure_does_not_skip_remaining_resources(tmp_path: Path) -> None:
    artifact = tmp_path / "fixture.txt"
    artifact.write_text("synthetic", encoding="utf-8")
    completed: list[str] = []

    def failed_es() -> None:
        raise RuntimeError("synthetic ES failure")

    def drop_db() -> None:
        completed.append("database")

    with pytest.raises(ExceptionGroup) as caught:
        support.cleanup_all([failed_es, drop_db, artifact.unlink])
    assert completed == ["database"]
    assert not artifact.exists()
    assert str(caught.value.exceptions[0]) == "synthetic ES failure"


@pytest.mark.parametrize("drop_fails", [False, True])
def test_seed_failure_still_attempts_cleanup_and_restores_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drop_fails: bool,
) -> None:
    actions: list[str] = []
    base = Settings(  # type: ignore[call-arg]
        _env_file=None,
        secret_key=SecretStr("test-secret-value-that-is-long-enough"),
        database_url="postgresql+psycopg://u:p@localhost/dev",
    )

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def execute(self, statement: object) -> "Connection":
            actions.append(str(statement))
            if drop_fails and "DROP DATABASE" in str(statement):
                raise RuntimeError("synthetic DROP failure")
            return self

    monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: Connection())
    monkeypatch.setattr(command, "upgrade", lambda *a: None)
    monkeypatch.setenv("AI_WORKSHOP_SECRET_KEY", "restoration-probe-secret-long-enough")
    watched_keys = (
        "AI_WORKSHOP_ENVIRONMENT",
        "AI_WORKSHOP_DATABASE_URL",
        "AI_WORKSHOP_SECRET_KEY",
        "AI_WORKSHOP_OBJECT_STORE_ROOT",
        "AI_WORKSHOP_ELASTICSEARCH_INDEX_PREFIX",
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
    )
    before_environment = {key: os.environ.get(key) for key in watched_keys}
    get_settings.cache_clear()
    before_settings = get_settings()
    listeners: list[Callable[..., Any]] = []
    real_listen = event.listen

    def record_listener(target: object, name: str, callback: Callable[..., Any]) -> None:
        listeners.append(callback)
        real_listen(target, name, callback)

    monkeypatch.setattr(event, "listen", record_listener)
    with (
        pytest.raises(ExceptionGroup if drop_fails else RuntimeError) as caught,
        support.isolated_resources(base, tmp_path),
    ):
        active = get_settings()
        assert active.database_url != base.database_url
        root = active.object_store_root
        (root / "synthetic.txt").write_text("test", encoding="utf-8")
        raise RuntimeError("seed failed")
    if drop_fails:
        assert isinstance(caught.value, ExceptionGroup)
        assert str(caught.value.exceptions[0]) == "synthetic DROP failure"
        assert isinstance(caught.value.__context__, RuntimeError)
        assert str(caught.value.__context__) == "seed failed"
    else:
        assert str(caught.value) == "seed failed"
    assert any("CREATE DATABASE" in action for action in actions)
    assert any("DROP DATABASE" in action for action in actions)
    assert not root.exists()
    assert {key: os.environ.get(key) for key in watched_keys} == before_environment
    restored = get_settings()
    assert restored == before_settings
    assert restored is not active
    assert listeners and not any(event.contains(Engine, "do_connect", item) for item in listeners)
    with pytest.raises(ValueError, match="outside the active test namespace"):
        support.create_isolated_elasticsearch(
            active.model_copy(
                update={"elasticsearch_index_prefix": active.elasticsearch_index_prefix + "-probe"}
            )
        )
    get_settings.cache_clear()


def test_actual_pytest_fixture_lifecycle_provisions_before_async_legacy_seed(
    pytester: pytest.Pytester,
) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    pytester.makepyfile(
        test_offline_lifecycle=f"""
import sys
sys.path.insert(0, {str(backend_root)!r})
import asyncio
from contextlib import asynccontextmanager
import pytest
import psycopg
from alembic import command
from ai_workshop.config import get_settings
from tests.integration import rag_isolation_support as support
from tests.integration.labs.rag.ingestion import conftest as legacy
from tests.integration.labs.rag.ingestion.conftest import (
    ensure_legacy_document_processing_profile,
)
events = []

@pytest.fixture
def offline_boundaries(monkeypatch):
    monkeypatch.setenv("AI_WORKSHOP_SECRET_KEY", "offline-fixture-secret-at-least-32")
    monkeypatch.setenv("AI_WORKSHOP_ENVIRONMENT", "test")
    monkeypatch.setenv("AI_WORKSHOP_DATABASE_URL", "postgresql+psycopg://u:p@localhost/dev")
    monkeypatch.setenv("AI_WORKSHOP_ELASTICSEARCH_URL", "http://127.0.0.1:9200")
    get_settings.cache_clear()
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement):
            events.append("drop" if "DROP DATABASE" in str(statement) else "create")
    monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: Connection())
    async def migration_probe(): pass
    def migrate(*args):
        asyncio.run(migration_probe())
        events.append("migrate")
    monkeypatch.setattr(command, "upgrade", migrate)
    class FakeEngine:
        async def dispose(self): pass
    class Session:
        async def get(self, *args):
            assert "ai_workshop_rag_test_" in get_settings().database_url
            assert events == ["create", "migrate"]
            events.append("legacy")
            return object()
    class Sessions:
        @asynccontextmanager
        async def begin(self): yield Session()
    monkeypatch.setattr(legacy, "create_engine", lambda settings: FakeEngine())
    monkeypatch.setattr(legacy, "create_session_factory", lambda engine: Sessions())
    yield
    assert events == ["create", "migrate", "legacy", "body", "drop"]
    get_settings.cache_clear()

@pytest.fixture(autouse=True)
def isolated_rag_resources(offline_boundaries, tmp_path_factory):
    yield from support.isolated_rag_resources.__wrapped__(tmp_path_factory)

@pytest.fixture
def rag_isolation_ready(offline_boundaries, request):
    # The real synchronous barrier runs after external I/O has been disabled.
    return legacy.rag_isolation_ready.__wrapped__(request)

def test_body():
    assert events == ["create", "migrate", "legacy"]
    events.append("body")
"""
    )
    result = pytester.runpytest_subprocess("-q", "--tb=short")
    result.assert_outcomes(passed=1)


def test_runtime_connection_rejects_real_database_before_driver_call() -> None:
    with pytest.raises(ValueError):
        support.validate_runtime_connection(
            {"host": "127.0.0.1", "dbname": "ai_workshop_local_clean"},
            "ai_workshop_rag_test_" + "a" * 32,
        )


@pytest.mark.parametrize("name", ["PGHOSTADDR", "PGSERVICE", "PGOPTIONS"])
def test_libpq_environment_override_is_rejected(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "unsafe")
    with pytest.raises(ValueError):
        support.validated_urls(
            "local", "postgresql+psycopg://u:p@localhost/dev", "ai_workshop_rag_test_" + "a" * 32
        )


def test_remote_elasticsearch_rejected() -> None:
    with pytest.raises(ValueError):
        support.validate_elasticsearch_url("https://remote.example:9200")


def test_object_cleanup_rejects_reparse_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "rag-test-abc-root"
    root.mkdir()
    (root / "keep.txt").write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(support, "is_reparse_point", lambda path: path == root)
    with pytest.raises(ValueError):
        support.remove_owned_objects(root, tmp_path, "abc")
    assert (root / "keep.txt").exists()


def test_seed_error_is_preserved_when_cleanup_also_fails() -> None:
    def fail_cleanup() -> None:
        raise ValueError("cleanup failure")

    with pytest.raises(ExceptionGroup) as caught:
        try:
            raise RuntimeError("seed failure")
        finally:
            support.cleanup_all([fail_cleanup])
    assert isinstance(caught.value.__context__, RuntimeError)
    assert str(caught.value.__context__) == "seed failure"


def test_elasticsearch_cleanup_deletes_only_exact_owned_names_and_continues_after_failure() -> None:
    attempted: list[str] = []

    class Indices:
        def get(self, **kwargs: object) -> dict[str, object]:
            return {"rag-test-abc-one": {}, "rag-test-abc-two": {}}

        def delete(self, *, index: str, ignore_unavailable: bool) -> None:
            attempted.append(index)
            if index.endswith("one"):
                raise RuntimeError("ES delete failed")

    with pytest.raises(ExceptionGroup):
        support.cleanup_owned_indices(Indices(), "rag-test-abc-")
    assert attempted == ["rag-test-abc-one", "rag-test-abc-two"]


def test_elasticsearch_cleanup_rejects_unowned_inventory_before_any_delete() -> None:
    class Indices:
        def get(self, **kwargs: object) -> dict[str, object]:
            return {"rag-test-abc-one": {}, "real-production-index": {}}

        def delete(self, **kwargs: object) -> None:
            pytest.fail("No deletion is allowed after an invalid inventory")

    with pytest.raises(ValueError):
        support.cleanup_owned_indices(Indices(), "rag-test-abc-")
