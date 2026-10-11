"""Offline real SQLAlchemy graph; only low Win32/DBAPI transports are fake."""

import asyncio
import builtins
import ctypes
import importlib
import io
import os
from copy import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import Pool

from ai_workshop.config import Settings
from ai_workshop.infrastructure.local.cutover_control_windows import WindowsControlLock
from ai_workshop.infrastructure.local.windows_private_state import SidAndAttributes
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from tests.unit.labs.rag.indexing.test_access_epoch_submission import Kernel


def module() -> Any:
    name = "ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly"
    assert importlib.util.find_spec(name) is not None, "fixed assembly missing"
    return importlib.import_module(name)


class Function:
    def __init__(self, implementation: Any) -> None:
        self.implementation = implementation
        self.argtypes: object = None
        self.restype: object = ctypes.c_int

    def __call__(self, *args: Any) -> Any:
        return self.implementation(*args)


def win32(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """No DLL loading, SID query, original path access or private file write."""
    calls: list[str] = []
    owner = ctypes.create_unicode_buffer("S-1-5-21-12345")

    def token(_process: object, _rights: object, output: Any) -> bool:
        output._obj.value = 41
        return True

    def information(_token: object, _kind: object, output: Any, _size: Any, size: Any) -> bool:
        size._obj.value = ctypes.sizeof(SidAndAttributes)
        if output is not None:
            value = ctypes.cast(output, ctypes.POINTER(SidAndAttributes)).contents
            value.sid = 42
        return output is not None

    def sid(_sid: object, output: Any) -> bool:
        output._obj.value = ctypes.cast(owner, ctypes.c_wchar_p).value
        return True

    def dll(name: str, **_options: object) -> Any:
        calls.append(name)
        native = SimpleNamespace(_name=name, _handle=len(calls))
        names = {
            "kernel32": ("GetCurrentProcess", "LocalFree", "CloseHandle", "MoveFileExW"),
            "advapi32": (
                "OpenProcessToken",
                "GetTokenInformation",
                "ConvertSidToStringSidW",
                "GetNamedSecurityInfoW",
                "GetSecurityDescriptorControl",
                "GetAce",
                "ConvertStringSecurityDescriptorToSecurityDescriptorW",
                "GetSecurityDescriptorOwner",
                "GetSecurityDescriptorDacl",
                "SetNamedSecurityInfoW",
            ),
            "crypt32": ("CryptProtectData", "CryptUnprotectData"),
        }
        for function in names[name]:
            implementation = {
                "OpenProcessToken": token,
                "GetTokenInformation": information,
                "ConvertSidToStringSidW": sid,
            }.get(function, lambda *_args: True)
            setattr(native, function, Function(implementation))
        return native

    monkeypatch.setattr(ctypes, "WinDLL", dll)
    return calls


def settings() -> Settings:
    return cast(
        Settings,
        cast(Any, Settings)(
            _env_file=None,
            database_url="postgresql+psycopg://synthetic:synthetic@127.0.0.1:15432/synthetic",
            secret_key="synthetic-secret-value-00000000000000",
            rag_index_store_id="synthetic",
            rag_index_cluster_uuid="synthetic-cluster",
        ),
    )


@pytest_asyncio.fixture
async def factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Fixed factory and loader are real; fixed .env reads use external file transport."""
    raw = (
        b'AI_WORKSHOP_DATABASE_URL="postgresql+psycopg://synthetic:synthetic@127.0.0.1:15432/ai_workshop_local_clean"\n'
        b'AI_WORKSHOP_SECRET_KEY="synthetic-secret-value-00000000000000"\n'
        b'AI_WORKSHOP_RAG_INDEX_STORE_ID="synthetic"\n'
        b'AI_WORKSHOP_RAG_INDEX_CLUSTER_UUID="synthetic-cluster"\n'
    )
    temporary = tmp_path / "synthetic-config"
    temporary.write_bytes(raw)
    fixed = PROJECT_ROOT / ".env"
    real_path_stat, real_stat = Path.stat, os.stat
    real_open, real_io_open, real_read = builtins.open, io.open, Path.read_bytes

    def is_fixed(path: Any) -> bool:
        return isinstance(path, str | Path) and Path(path) == fixed

    def path_stat(path: Path, *args: Any, **kwargs: Any) -> Any:
        return (
            real_path_stat(temporary, *args, **kwargs)
            if is_fixed(path)
            else real_path_stat(path, *args, **kwargs)
        )

    def os_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        return (
            real_stat(temporary, *args, **kwargs)
            if is_fixed(path)
            else real_stat(path, *args, **kwargs)
        )

    def opened(path: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if is_fixed(path):
            return io.BytesIO(raw) if "b" in mode else io.StringIO(raw.decode())
        return real_open(path, mode, *args, **kwargs)

    def io_opened(path: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if is_fixed(path):
            return io.BytesIO(raw) if "b" in mode else io.StringIO(raw.decode())
        return real_io_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", path_stat)
    monkeypatch.setattr(os, "stat", os_stat)
    monkeypatch.setattr(builtins, "open", opened)
    monkeypatch.setattr(io, "open", io_opened)
    monkeypatch.setattr(Path, "read_bytes", lambda path: raw if is_fixed(path) else real_read(path))
    calls = win32(monkeypatch)
    managers: list[Any] = []

    async def build() -> Any:
        manager = module().NativeSecuredReadAssembly.open_original()
        assembly = await manager.__aenter__()
        managers.append(manager)
        return assembly

    cast(Any, build).calls = calls
    yield build
    for manager in reversed(managers):
        await manager.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_actual_constructed_dependencies_are_retained_and_disposal_consumes(
    factory: Any,
) -> None:
    calls = factory.calls
    assembly = await factory()
    try:
        assert calls == []  # Offline engine construction does not read the SID.
        bound = assembly.bind_committed()
        assembly.assert_issued(bound)
        assert calls == ["kernel32", "advapi32", "crypt32"]
        assert bound.repository is assembly.control_repository
        assert bound.keys.parent is bound.repository
        assert bound.store.files is bound.store.protection is bound.private
        assert assembly._engine.sync_engine.pool.checkedout() == 0
        assert "synthetic-secret" not in repr(bound)
        assert "synthetic@" not in repr(bound)
        with pytest.raises(ValueError, match="secured_read_assembly_denied"):
            assembly.assert_issued(copy(bound))
    finally:
        await assembly.close()
    with pytest.raises(ValueError, match="secured_read_assembly_denied"):
        assembly.assert_issued(bound)


@pytest.mark.parametrize(
    "mutation",
    [
        "url",
        "maker",
        "maker_class",
        "maker_bind",
        "maker_option",
        "sync_engine",
        "pool",
        "pool_dialect",
        "dialect",
        "creator",
        "creator_args",
        "creator_params",
        "dbapi",
        "driver_connect",
        "engine_listener",
        "dialect_listener",
        "pool_listener",
        "clock",
        "settings",
        "hide_parameters",
        "pool_options",
        "native_dll",
        "native_owner",
        "native_root",
        "native_function",
        "native_function_args",
        "native_handle",
        "keys_clock",
        "pool_get",
        "connection_class",
        "session_execute",
        "dialect_connect",
    ],
)
@pytest.mark.asyncio
async def test_nested_constructor_input_mutation_is_denied(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    factory: Any,
) -> None:
    assembly = await factory()
    try:
        bound = assembly.bind_committed()
        engine = assembly._engine.sync_engine
        pool = engine.pool
        dialect = engine.dialect
        maker = bound.repository.sessions
        creator = cast(Any, pool)._creator
        if mutation == "url":
            engine.url = engine.url.set(password="different")
        elif mutation == "maker":
            bound.repository.sessions = copy(maker)
        elif mutation == "maker_class":
            maker.class_ = cast(Any, type("OtherSession", (AsyncSession,), {}))
        elif mutation == "maker_bind":
            maker.kw["bind"] = copy(assembly._engine)
        elif mutation == "maker_option":
            maker.kw["autoflush"] = 1
        elif mutation == "sync_engine":
            assembly._engine.sync_engine = copy(engine)
        elif mutation == "pool":
            engine.pool = copy(pool)
        elif mutation == "pool_dialect":
            cast(Any, pool)._dialect = copy(dialect)
        elif mutation == "dialect":
            engine.dialect = copy(dialect)
        elif mutation == "creator":
            cast(Any, pool)._creator = lambda: None
        elif mutation == "creator_args":
            creator.__closure__[0].cell_contents.append("different")
        elif mutation == "creator_params":
            params = dict(creator.__closure__[1].cell_contents)
            creator.__closure__[1].cell_contents = params | {"host": "different"}
        elif mutation == "dbapi":
            dialect.dbapi = copy(dialect.dbapi)
        elif mutation == "driver_connect":
            monkeypatch.setattr(dialect.dbapi.psycopg.AsyncConnection, "connect", lambda: None)
        elif mutation == "engine_listener":
            event.listen(engine, "before_cursor_execute", lambda *_args: None)
        elif mutation == "dialect_listener":
            event.listen(engine, "do_connect", lambda *_args: None)
        elif mutation == "pool_listener":
            event.listen(pool, "connect", lambda *_args: None)
        elif mutation == "clock":
            bound.repository.clock = lambda: None
        elif mutation == "settings":
            assembly._settings.database_url += "?application_name=drift"
        elif mutation == "hide_parameters":
            engine.hide_parameters = False
        elif mutation == "pool_options":
            cast(Any, pool)._recycle = True
        elif mutation == "native_dll":
            bound.private.crypt = copy(bound.private.crypt)
        elif mutation == "native_owner":
            bound.private.owner = "different"
        elif mutation == "native_root":
            bound.private.root = bound.private.root / "different"
        elif mutation == "native_function":
            cast(Any, bound.private.crypt).CryptProtectData = copy(
                bound.private.crypt.CryptProtectData
            )
        elif mutation == "native_function_args":
            bound.private.kernel.LocalFree.argtypes = []
        elif mutation == "native_handle":
            cast(Any, bound.private.kernel)._handle = 999
        elif mutation == "keys_clock":
            bound.keys.clock = lambda: None
        elif mutation == "pool_get":
            cast(Any, pool)._do_get = lambda: None
        elif mutation == "connection_class":
            cast(Any, engine)._connection_cls = lambda *_args: None
        elif mutation == "session_execute":
            monkeypatch.setattr(AsyncSession, "execute", lambda *_args: None)
        elif mutation == "dialect_connect":
            dialect.connect = lambda *_args: None
        with pytest.raises(ValueError, match="secured_read_assembly_denied"):
            assembly.assert_issued(bound)
    finally:
        await assembly.close()


@pytest.mark.asyncio
async def test_foreign_issuer_and_transferred_registry_are_denied(
    factory: Any,
) -> None:
    first = await factory()
    second = await factory()
    try:
        bound = first.bind_committed()
        second._issued = dict(first._issued)
        with pytest.raises(ValueError, match="secured_read_assembly_denied"):
            second.assert_issued(bound)
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_direct_constructor_and_foreign_context_never_supply_authority(factory: Any) -> None:
    with pytest.raises(ValueError, match="secured_read_assembly_denied"):
        module().NativeSecuredReadAssembly()
    assembly = await factory()
    try:
        with pytest.raises(ValueError, match="secured_read_assembly_denied"):
            assembly.bind_context(SimpleNamespace(repository=assembly.control_repository))
    finally:
        await assembly.close()


@pytest.mark.asyncio
async def test_offline_constructor_cannot_publish_original_dependencies() -> None:
    assembly = module().NativeSecuredReadAssembly._build(settings())
    try:
        with pytest.raises(ValueError, match="secured_read_assembly_denied"):
            assembly.bind_committed()
        with pytest.raises(ValueError, match="secured_read_assembly_denied"):
            _ = assembly.control_repository
    finally:
        await assembly.close()


@pytest.mark.asyncio
async def test_late_sid_transport_config_mutation_prevents_publication(
    factory: Any,
) -> None:
    assembly = await factory()
    # Mutation is in an actual external SID query, not an issuer/guard replacement.
    import ctypes as port

    load = cast(Any, port.WinDLL)

    def late(name: str, **kwargs: Any) -> Any:
        dll = load(name, **kwargs)
        if name == "advapi32":
            original = dll.OpenProcessToken.implementation

            def changed(*args: Any) -> Any:
                result = original(*args)
                assembly._settings.database_url += "?application_name=drift"
                return result

            dll.OpenProcessToken.implementation = changed
        return dll

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(port, "WinDLL", late)
        with pytest.raises(ValueError, match="secured_read_assembly_denied"):
            assembly.bind_committed()
    assert assembly._issued == {}


@pytest.mark.asyncio
async def test_cancellation_in_sid_transport_never_publishes(factory: Any) -> None:
    assembly = await factory()
    load = cast(Any, ctypes.WinDLL)

    def cancelled(name: str, **kwargs: Any) -> Any:
        dll = load(name, **kwargs)
        if name == "advapi32":

            def cancel(*_args: Any) -> Any:
                raise asyncio.CancelledError()

            dll.OpenProcessToken.implementation = cancel
        return dll

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ctypes, "WinDLL", cancelled)
        with pytest.raises(asyncio.CancelledError):
            assembly.bind_committed()
    assert assembly._issued == {}


class Cursor:
    """External psycopg cursor transport; all SQLAlchemy initialization is actual."""

    arraysize = 1
    rowcount = 1
    description = [("value", 25, None, None, None, None, None)]
    pgresult = SimpleNamespace(status=2)

    def __init__(self) -> None:
        self.rows: list[tuple[str]] = []

    async def execute(self, query: Any, *_args: Any, **_kwargs: Any) -> None:
        sql = str(query).lower()
        responses = {
            "select pg_catalog.version()": "PostgreSQL 16.4 synthetic",
            "select current_schema()": "public",
            "show transaction isolation level": "read committed",
            "show standard_conforming_strings": "on",
            "select 1": "1",
            ";": "1",  # Actual psycopg dialect's empty-statement ping.
        }
        assert sql in responses, "unreviewed fake DBAPI SQL"
        self.rows = [(responses[sql],)]

    async def fetchall(self) -> list[tuple[str]]:
        return self.rows

    def _close(self) -> None:
        pass


class Driver:
    autocommit = False
    closed = False
    info = SimpleNamespace(transaction_status=0)

    @staticmethod
    async def connect(*_args: Any, **_kwargs: Any) -> "Driver":
        return Driver()

    def cursor(self, *_args: Any, **_kwargs: Any) -> Cursor:
        return Cursor()

    def add_notice_handler(self, _handler: Any) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def set_autocommit(self, value: bool) -> None:
        self.autocommit = value

    async def close(self) -> None:
        self.closed = True


async def missing_hstore(_connection: Any, _name: str) -> None:
    return None


@pytest.mark.asyncio
async def test_actual_default_first_connect_and_learned_state_are_allowed(
    factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg
    from psycopg.types import TypeInfo

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", Driver.connect)
    monkeypatch.setattr(TypeInfo, "fetch", missing_hstore)
    assembly = await factory()
    cap = assembly.bind_committed()
    assert assembly._engine.dialect.server_version_info is None
    async with assembly._engine.connect():
        assembly.assert_issued(cap)
    assert assembly._engine.dialect.server_version_info == (16, 4)
    assert assembly._engine.dialect.default_schema_name == "public"
    assembly.assert_issued(cap)
    # Reusing the same installed once-handler does not re-run initialization.
    async with assembly._engine.connect():
        assembly.assert_issued(cap)


@pytest.mark.asyncio
async def test_binding_nested_uuid_and_exact_phase_types_are_sealed(factory: Any) -> None:
    assembly = await factory()
    bound = assembly.bind_committed()
    old = bound.nonce.int
    object.__setattr__(bound.nonce, "int", old + 1)
    with pytest.raises(ValueError, match="secured_read_assembly_denied"):
        assembly.assert_issued(bound)


@pytest.mark.asyncio
async def test_revalidation_retains_bounded_unique_references(factory: Any) -> None:
    assembly = await factory()
    cap = assembly.bind_committed()
    assembly.assert_issued(cap)
    count = len(assembly._references)
    for _ in range(10):
        assembly.assert_issued(cap)
    assert len(assembly._references) == count


@pytest.mark.asyncio
async def test_before_publication_equal_foreign_engine_graph_cannot_be_adopted(
    factory: Any,
) -> None:
    first, second = await factory(), await factory()
    for name in ("_engine", "_sessions", "_repository", "_sync_engine", "_pool", "_dialect"):
        setattr(first, name, getattr(second, name))
    first._owned = (first._settings, *second._owned[1:])
    first._seal = second._seal
    with pytest.raises(ValueError, match="secured_read_assembly_denied"):
        first.bind_committed()


@pytest.mark.asyncio
async def test_case_insensitive_environment_override_after_factory_is_denied(
    factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assembly = await factory()
    cap = assembly.bind_committed()
    monkeypatch.setenv("ai_workshop_database_url", "synthetic-override")
    with pytest.raises(ValueError, match="secured_read_assembly_denied"):
        assembly.assert_issued(cap)


@pytest.mark.asyncio
async def test_fixed_config_source_bytes_drift_is_denied(
    factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assembly = await factory()
    cap = assembly.bind_committed()
    read = Path.read_bytes
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda path: read(path) + b"\n" if path == PROJECT_ROOT / ".env" else read(path),
    )
    with pytest.raises(ValueError, match="secured_read_assembly_denied"):
        assembly.assert_issued(cap)


@pytest.mark.asyncio
async def test_repeated_cancel_waits_for_owned_pool_cleanup_and_consumes_association(
    factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg
    from psycopg.types import TypeInfo

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", Driver.connect)
    monkeypatch.setattr(TypeInfo, "fetch", missing_hstore)
    entered, release = asyncio.Event(), asyncio.Event()
    closed: list[bool] = []

    async def close(driver: Driver) -> None:
        entered.set()
        await release.wait()
        driver.closed = True
        closed.append(True)

    monkeypatch.setattr(Driver, "close", close)
    assembly = await factory()
    cap = assembly.bind_committed()
    async with assembly._engine.connect():
        pass
    closing = asyncio.create_task(assembly.close())
    await asyncio.wait_for(entered.wait(), 2)
    closing.cancel("first")
    await asyncio.sleep(0)
    closing.cancel("second")
    await asyncio.sleep(0)
    assert not closing.done()
    with pytest.raises(ValueError, match="secured_read_assembly_denied"):
        assembly.assert_issued(cap)
    release.set()
    with pytest.raises(asyncio.CancelledError) as error:
        await asyncio.wait_for(closing, 2)
    assert error.value.args == ("first",)
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("target, name", [(Engine, "before_cursor_execute"), (Pool, "connect")])
async def test_initial_inherited_user_listener_is_not_constructor_authority(
    factory: Any,
    target: Any,
    name: str,
) -> None:
    def injected(*_args: Any) -> None:
        return None

    event.listen(target, name, injected)
    try:
        with pytest.raises(ValueError, match="secured_read_assembly_denied"):
            await factory()
    finally:
        event.remove(target, name, injected)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_failed_postpublication_check_discards_candidate(
    factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    """Same actual external-file failure boundary as unchanged independent repro."""
    assembly = await factory()
    read = Path.read_bytes
    retained: list[Any] = []

    def fail(path: Path) -> bytes:
        if path == PROJECT_ROOT / ".env" and assembly._issued and not retained:
            retained.extend(assembly._issued)
            if cancel:
                raise asyncio.CancelledError("synthetic cancellation")
            raise ValueError("synthetic configuration read failure")
        return read(path)

    with monkeypatch.context() as port:
        port.setattr(Path, "read_bytes", fail)
        with pytest.raises(asyncio.CancelledError if cancel else ValueError) as error:
            assembly.bind_committed()
    if cancel:
        assert error.value.args == ("synthetic cancellation",)
    assert len(retained) == 1
    with pytest.raises(ValueError, match="secured_read_assembly_denied"):
        assembly.assert_issued(retained[0])


class Interrupted(BaseException):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [asyncio.CancelledError, Interrupted])
async def test_original_constructor_interruption_consumes_registered_assembly(
    factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
) -> None:
    mod = module()
    before = set(mod._ORIGINALS)
    read = Path.read_bytes
    retained: list[Any] = []

    def cancel(path: Path) -> bytes:
        created = [candidate for candidate in mod._ORIGINALS if candidate not in before]
        if path == PROJECT_ROOT / ".env" and created and not retained:
            retained.extend(created)
            raise error_type("synthetic construction interruption")
        return read(path)

    manager = mod.NativeSecuredReadAssembly.open_original()
    with monkeypatch.context() as ports:
        ports.setattr(Path, "read_bytes", cancel)
        with pytest.raises(error_type) as error:
            await manager.__aenter__()
    assert error.value.args == ("synthetic construction interruption",)
    assert len(retained) == 1
    assembly = retained[0]
    try:
        with pytest.raises(ValueError, match="secured_read_assembly_denied"):
            _ = assembly.control_repository
        assert assembly._closed
        assert assembly not in mod._ORIGINALS
    finally:
        await assembly.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [None, "store_files", "store_protection", "both_store_ports"])
async def test_context_private_port_identity_component_uses_actual_journal(
    factory: Any,
    mutation: str | None,
) -> None:
    """Pure port association only; no positive NativeControlContext/DAG is minted."""
    assembly = await factory()
    bound = assembly.bind_committed()
    lock = WindowsControlLock(uuid4().hex * 2, "synthetic-association", native=cast(Any, Kernel)())
    owner = lock.acquire(uuid4(), str(uuid4()))
    try:
        journal = ProtectedControlJournal(
            PROJECT_ROOT, bound.private, bound.private, lock, owner, lock.scope_sha256
        )
        assert hasattr(assembly, "_context_private"), "context native identity check missing"
        assert assembly._context_private(journal, bound.store) is bound.private
        replacement = copy(bound.private)
        if mutation in {"store_files", "both_store_ports"}:
            bound.store.files = replacement
        if mutation in {"store_protection", "both_store_ports"}:
            bound.store.protection = replacement
        if mutation is not None:
            with pytest.raises(ValueError, match="secured_read_assembly_denied"):
                assembly._context_private(journal, bound.store)
    finally:
        lock.close(owner)
