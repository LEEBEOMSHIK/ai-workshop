"""Test-only resource isolation for the audited RAG integration modules."""

import os
import re
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from elasticsearch import AsyncElasticsearch, Elasticsearch, NotFoundError
from psycopg import sql
from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url

from ai_workshop.config import Settings, get_settings
from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATTERN = re.compile(r"ai_workshop_rag_test_[0-9a-f]{32}")
_active_es_prefix: str | None = None
_es_used = False


def validated_urls(environment: str, base_url: str, database: str) -> tuple[str, str]:
    url = make_url(base_url)
    try:
        loopback = url.host == "localhost" or ip_address(url.host or "").is_loopback
    except ValueError:
        loopback = False
    if (
        environment not in {"local", "test"}
        or url.drivername != "postgresql+psycopg"
        or not loopback
        or url.query
        or DATABASE_PATTERN.fullmatch(database) is None
        or any(
            key in os.environ for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS")
        )
    ):
        raise ValueError(
            "RAG tests require a loopback PostgreSQL disposable target without URL overrides"
        )
    return (
        url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False),
        url.set(database=database).render_as_string(hide_password=False),
    )


def cleanup_all(actions: list[Callable[[], object]]) -> None:
    errors: list[Exception] = []
    for action in actions:
        try:
            action()
        except Exception as error:
            errors.append(error)
    if errors:
        raise ExceptionGroup("RAG test resource cleanup failed", errors)


def validate_elasticsearch_url(url: str) -> None:
    parsed = urlsplit(url)
    try:
        loopback = parsed.hostname == "localhost" or ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        loopback = False
    if not loopback or parsed.scheme not in {"http", "https"} or parsed.query or parsed.fragment:
        raise ValueError("RAG test Elasticsearch must use a loopback endpoint")


def create_isolated_elasticsearch(settings: Settings) -> AsyncElasticsearch:
    global _es_used
    validate_elasticsearch_url(settings.elasticsearch_url)
    if _active_es_prefix is None or not settings.elasticsearch_index_prefix.startswith(
        _active_es_prefix + "-"
    ):
        raise ValueError("Elasticsearch prefix is outside the active test namespace")
    _es_used = True
    return AsyncElasticsearch(settings.elasticsearch_url, request_timeout=5, max_retries=0)


def cleanup_owned_indices(indices: Any, prefix: str) -> None:
    try:
        names = indices.get(index=prefix + "*", allow_no_indices=True, ignore_unavailable=True)
    except NotFoundError:
        return
    for name in names:
        if not isinstance(name, str) or not name.startswith(prefix) or "*" in name or "," in name:
            raise ValueError("Elasticsearch returned an unowned index")
    cleanup_all(
        [partial(indices.delete, index=name, ignore_unavailable=True) for name in names]
    )


def is_reparse_point(path: Path) -> bool:
    return path.is_symlink() or bool(
        getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def remove_owned_objects(root: Path, parent: Path, token: str) -> None:
    if root.parent != parent.resolve() or not root.name.startswith(f"rag-test-{token}-"):
        raise ValueError("Unexpected test object root")
    for ancestor in (root, *root.parents):
        if is_reparse_point(ancestor):
            raise ValueError("Refusing test cleanup through a reparse point")
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in (*directories, *files):
            if is_reparse_point(Path(directory) / name):
                raise ValueError("Refusing test cleanup containing a reparse point")
    shutil.rmtree(root)


def validate_runtime_connection(parameters: dict[str, Any], database: str) -> None:
    host = parameters.get("host", "")
    try:
        loopback = host == "localhost" or ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if (
        not loopback
        or parameters.get("dbname") != database
        or any(key in parameters for key in ("service", "hostaddr", "options"))
    ):
        raise ValueError("Refusing connection outside the active disposable RAG database")


@contextmanager
def isolated_resources(base: Settings, parent: Path) -> Iterator[None]:
    """An outer scope protects even seed/setup and existing cleanup failures."""
    global _active_es_prefix, _es_used
    token = uuid4().hex
    database = f"ai_workshop_rag_test_{token}"
    administrative_url, isolated_url = validated_urls(base.environment, base.database_url, database)
    validate_elasticsearch_url(base.elasticsearch_url)
    object_root = Path(tempfile.mkdtemp(prefix=f"rag-test-{token}-", dir=parent)).resolve()
    environment = pytest.MonkeyPatch()
    created = False
    listening = False

    def guard(dialect: Any, record: Any, args: Any, parameters: dict[str, Any]) -> None:
        validate_runtime_connection(parameters, database)

    def restore_environment() -> None:
        global _active_es_prefix, _es_used
        if listening:
            event.remove(Engine, "do_connect", guard)
        environment.undo()
        get_settings.cache_clear()
        _active_es_prefix = None
        _es_used = False

    def drop_database() -> None:
        if created:
            # Only this successfully created exact database is ever a DROP target.
            validated_urls(base.environment, base.database_url, database)
            with psycopg.connect(
                administrative_url, autocommit=True, connect_timeout=5
            ) as connection:
                connection.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
                )
            print(f"rag_test_database_dropped={database}")

    def cleanup_elasticsearch() -> None:
        if not _es_used:
            return
        prefix = f"rag-test-{token}-"
        print(f"rag_test_es_cleanup_namespace={prefix}")
        with Elasticsearch(base.elasticsearch_url, request_timeout=5, max_retries=0) as client:
            cleanup_owned_indices(client.indices, prefix)

    try:
        _active_es_prefix = f"rag-test-{token}"
        _es_used = False
        environment.setenv("AI_WORKSHOP_ENVIRONMENT", "test")
        environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
        environment.setenv("AI_WORKSHOP_SECRET_KEY", "rag-test-only-secret-key-long-enough")
        environment.setenv("AI_WORKSHOP_OBJECT_STORE_ROOT", str(object_root))
        environment.setenv("AI_WORKSHOP_ELASTICSEARCH_INDEX_PREFIX", f"rag-test-{token}")
        environment.setenv("HF_HUB_OFFLINE", "1")
        environment.setenv("TRANSFORMERS_OFFLINE", "1")
        get_settings.cache_clear()
        with psycopg.connect(administrative_url, autocommit=True, connect_timeout=5) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        created = True
        print(
            f"rag_test_database_created={database}; object_root={object_root}; "
            f"es_prefix=rag-test-{token}"
        )
        event.listen(Engine, "do_connect", guard)
        listening = True
        command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
        yield
    finally:
        cleanup_all(
            [
                cleanup_elasticsearch,
                drop_database,
                lambda: remove_owned_objects(object_root, parent, token),
                restore_environment,
            ]
        )


@pytest.fixture(autouse=True)
def isolated_rag_resources(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    # The legacy profile fixture explicitly depends on this before its first write.
    with isolated_resources(get_settings(), tmp_path_factory.getbasetemp()):
        yield
