"""Actual fixed native graph over finite synthetic external transports only.

Distinct fixture names avoid module/plugin graph shadowing in combined runs.
No original environment, database, private file or native process is used.
"""

import builtins
import io
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
import pytest_asyncio
from psycopg.types import TypeInfo

from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
    NativeReadDependencies,
    NativeSecuredReadAssembly,
)
from ai_workshop.labs.rag.indexing.alias_models import AliasRecoveryReceiptRecord
from ai_workshop.labs.rag.models.models import ProfileRecord
from tests.unit.labs.rag.indexing import native_sql_row_transport_support as wire
from tests.unit.labs.rag.indexing.native_private_material_transport_support import MaterialTransport
from tests.unit.labs.rag.indexing.test_access_epoch_secured_read import case
from tests.unit.labs.rag.indexing.test_access_epoch_secured_read_assembly import missing_hstore

pytest_plugins = ["tests.unit.labs.rag.indexing.test_access_epoch_secured_read_assembly"]
type Graph = tuple[wire.RelationalRows, NativeSecuredReadAssembly, NativeReadDependencies, Any]


@pytest.fixture
def protected_transport(
    factory: Callable[[], Awaitable[NativeSecuredReadAssembly]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> MaterialTransport:
    return MaterialTransport(monkeypatch, tmp_path)


@pytest_asyncio.fixture
async def sql_graph(
    factory: Callable[[], Awaitable[NativeSecuredReadAssembly]],
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> AsyncIterator[Graph]:
    # Only the already admitted fixed synthetic configuration file transport.
    raw = (
        b'AI_WORKSHOP_DATABASE_URL="postgresql+psycopg://synthetic:synthetic@127.0.0.1:15432/ai_workshop_local_clean"\n'
        b'AI_WORKSHOP_SECRET_KEY="synthetic-secret-value-00000000000000"\n'
        b'AI_WORKSHOP_RAG_INDEX_STORE_ID="rag"\n'
        b'AI_WORKSHOP_RAG_INDEX_CLUSTER_UUID="cluster"\n'
    )
    fixed = PROJECT_ROOT / ".env"
    previous_open, previous_io, previous_read = builtins.open, io.open, Path.read_bytes
    # The parent fixture already routes this exact file to synthetic bytes/stat.
    # Keep its real low stat size consistent with our admitted synthetic content.
    padding = len(previous_read(fixed)) - len(raw)
    assert padding >= 2
    raw += b"#" + b" " * (padding - 2) + b"\n"
    assert fixed.stat().st_size == len(raw)

    def matches(path: Any) -> bool:
        return isinstance(path, str | Path) and Path(path) == fixed

    def opened(path: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        return (
            (io.BytesIO(raw) if "b" in mode else io.StringIO(raw.decode()))
            if matches(path)
            else previous_open(path, mode, *args, **kwargs)
        )

    def io_opened(path: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        return (
            (io.BytesIO(raw) if "b" in mode else io.StringIO(raw.decode()))
            if matches(path)
            else previous_io(path, mode, *args, **kwargs)
        )

    monkeypatch.setattr(builtins, "open", opened)
    monkeypatch.setattr(io, "open", io_opened)
    monkeypatch.setattr(
        Path, "read_bytes", lambda path: raw if matches(path) else previous_read(path)
    )
    store = wire.RelationalRows()
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", store.connect)
    monkeypatch.setattr(TypeInfo, "fetch", missing_hstore)
    assembly = await factory()
    deps = assembly.bind_committed()
    c = await case()
    assert deps.settings.rag_index_store_id == c.settings.rag_index_store_id
    assert deps.settings.rag_index_cluster_uuid == c.settings.rag_index_cluster_uuid
    assert deps.settings.elasticsearch_index_prefix == c.settings.elasticsearch_index_prefix
    phase = getattr(request, "param", None)
    if phase is None:
        callspec = getattr(request.node, "callspec", None)
        phase = "verified" if callspec is None else callspec.params.get("graph", "verified")
    assert phase in {"verified", "receipted"}
    if phase == "receipted":
        await c.repository.close_access_epoch(c.claim, c.proof)
        receipt = next(
            row for key, row in c.db.rows.items() if key[0] is AliasRecoveryReceiptRecord
        )
        receipt.access_epoch_id = UUID(c.epoch.binding.access_epoch_id)
        receipt.execution_id = UUID(c.epoch.binding.execution_id)
        c.db.rows = {key: row for key, row in c.db.rows.items() if key[0] is not ProfileRecord}
    for record in c.db.rows.values():
        store.seed(record)
    try:
        yield store, assembly, deps, c
    finally:
        await assembly.close()
        assert all(connection.closed for connection in store.connections)


@pytest.fixture
def material_graph(protected_transport: MaterialTransport, sql_graph: Graph) -> Any:
    store, assembly, dependencies, data = sql_graph
    for fixed, ciphertext in data.memory.files.items():
        protected_transport.seed(fixed, ciphertext)
    return store, assembly, dependencies, data, protected_transport
