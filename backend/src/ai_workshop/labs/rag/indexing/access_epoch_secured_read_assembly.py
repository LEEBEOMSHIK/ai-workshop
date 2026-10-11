"""Constructor-owned dependencies, not server/epoch/receipt/readiness authority.

Public construction loads only the fixed original configuration. Private offline
construction is an implementation test seam; it does not attest an endpoint.
No connection, key or private file is created by the SQL dependency constructor.
"""

import asyncio
import ctypes
import os
import stat
from _ctypes import CFuncPtr
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import FunctionType, MethodType
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql.psycopg import PGDialectAsync_psycopg
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy.util import greenlet_spawn

from ai_workshop.config import Settings
from ai_workshop.infrastructure.local.credential_store_windows import WindowsCredentialStore
from ai_workshop.infrastructure.local.windows_private_state import NativeWindowsPrivateState
from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from ai_workshop.labs.rag.indexing.access_epoch_keys import SqlAlchemyEpochKeyRepository
from ai_workshop.labs.rag.indexing.access_epoch_repository import SqlAlchemyAccessEpochRepository
from ai_workshop.labs.rag.indexing.access_epoch_secured_read import _freeze
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding

_ROOT_TEXT = str(PROJECT_ROOT)
_NATIVE_FUNCTIONS = {
    "kernel": ("GetCurrentProcess", "LocalFree", "CloseHandle", "MoveFileExW"),
    "advapi": (
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
    "crypt": ("CryptProtectData", "CryptUnprotectData"),
}
_NATIVE_METHODS = ("protect", "unprotect", "read", "write", "remove", "_check_path", "_check_acl")


def _denied() -> ValueError:
    return ValueError("secured_read_assembly_denied")


@dataclass(frozen=True, slots=True, eq=False)
class NativeReadDependencies:
    """Exact retained graph only. No settled phase or live observation is asserted."""

    nonce: UUID = field(repr=False)
    phase: Literal["context", "committed"] = field(repr=False)
    settings: Settings = field(repr=False)
    repository: SqlAlchemyAccessEpochRepository = field(repr=False)
    keys: SqlAlchemyEpochKeyRepository = field(repr=False)
    store: WindowsCredentialStore = field(repr=False)
    private: NativeWindowsPrivateState = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class _Issued:
    owner: object
    value: NativeReadDependencies
    seal: object
    context: NativeControlContext | None
    journal: ProtectedControlJournal | None
    references: tuple[object, ...]


@dataclass(frozen=True, slots=True, repr=False)
class _Original:
    owner: object
    settings: Settings
    configuration: object
    graph: tuple[object, ...]
    seal: object


_ORIGINALS: dict[object, _Original] = {}


class NativeSecuredReadAssembly:
    """Fixed factory. Not a way to adopt an arbitrary repository or native port."""

    _settings: Settings
    _engine: AsyncEngine
    _sessions: async_sessionmaker[AsyncSession]
    _repository: SqlAlchemyAccessEpochRepository
    _sync_engine: Engine
    _pool: AsyncAdaptedQueuePool
    _dialect: PGDialectAsync_psycopg
    _owned: tuple[object, ...]
    _origin: object
    _closed: bool
    _issued: dict[NativeReadDependencies, _Issued]
    _once: dict[FunctionType, tuple[object, FunctionType, bool]]
    _references: dict[int, object]
    _seal: object

    def __init__(self) -> None:
        raise _denied()

    @classmethod
    def _build(cls, settings: Settings) -> "NativeSecuredReadAssembly":
        """Source-owned offline constructor; callers have no public custom-DSN API."""
        if (
            type(settings) is not Settings
            or settings.environment != "local"
            or settings.rag_index_store_id is None
            or settings.rag_index_cluster_uuid is None
        ):
            raise _denied()
        url = make_url(settings.database_url)
        if url.drivername != "postgresql+psycopg" or url.query:
            raise _denied()
        engine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            echo=False,
            hide_parameters=True,
        )
        sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        repository = SqlAlchemyAccessEpochRepository(
            sessions,
            IndexBinding(settings.rag_index_store_id, settings.rag_index_cluster_uuid),
            settings.elasticsearch_index_prefix,
        )
        self = object.__new__(cls)
        self._settings, self._engine, self._sessions, self._repository = (
            settings,
            engine,
            sessions,
            repository,
        )
        self._sync_engine = engine.sync_engine
        if (
            type(engine.sync_engine.pool) is not AsyncAdaptedQueuePool
            or type(engine.sync_engine.dialect) is not PGDialectAsync_psycopg
        ):
            raise _denied()
        self._pool = engine.sync_engine.pool
        self._dialect = engine.sync_engine.dialect
        self._owned = (
            settings,
            engine,
            sessions,
            repository,
            self._sync_engine,
            self._pool,
            self._dialect,
            repository.recovery,
        )
        self._origin = None
        self._closed = False
        self._issued = {}
        self._once = {}
        self._references = {id(value): value for value in self._owned}
        self._default_dispatch()
        self._seal = self._signature()
        self._guard()
        return self

    @classmethod
    @asynccontextmanager
    async def open_original(cls) -> AsyncIterator["NativeSecuredReadAssembly"]:
        """Configuration/SID reads are real I/O; SQL construction opens no connection."""
        assembly: NativeSecuredReadAssembly | None = None
        try:
            before = cls._configuration()
            settings = load_original_settings(Path(_ROOT_TEXT))
            assembly = cls._build(settings)
            if cls._configuration() != before:
                raise _denied()
            assembly._origin = before
            _ORIGINALS[assembly] = _Original(
                assembly, settings, before, assembly._owned, assembly._seal
            )
            assembly._guard()
        except BaseException as error:
            if assembly is not None:
                with suppress(BaseException):
                    await assembly.close()
            if isinstance(error, Exception):
                raise _denied() from None
            raise
        assert assembly is not None
        try:
            yield assembly
        except BaseException:
            with suppress(BaseException):
                await assembly.close()
            raise
        else:
            await assembly.close()

    @staticmethod
    def _configuration() -> object:
        path = Path(_ROOT_TEXT) / ".env"
        before = path.stat(follow_symlinks=False)
        if (
            str(PROJECT_ROOT) != _ROOT_TEXT
            or not stat.S_ISREG(before.st_mode)
            or path.is_symlink()
            or getattr(before, "st_file_attributes", 0) & 0x400
            or any(name.startswith("AI_WORKSHOP_") for name in os.environ)
        ):
            raise _denied()
        raw = path.read_bytes()
        after = path.stat(follow_symlinks=False)

        def identity(info: os.stat_result) -> object:
            return (
                info.st_dev,
                info.st_ino,
                info.st_mode,
                info.st_size,
                info.st_mtime_ns,
                getattr(info, "st_file_attributes", 0),
            )

        if identity(before) != identity(after):
            raise _denied()
        return (identity(after), raw)  # Private only, never a public hash/manifest.

    def _retain(self, value: object) -> tuple[type[object], int]:
        self._references[id(value)] = value
        return type(value), id(value)

    def _value(self, value: object, depth: int = 0) -> object:
        if depth > 8:
            raise _denied()
        if type(value) in {str, bool, int, float, bytes, type(None)}:
            return type(value), value
        if type(value) in {dict, list, tuple} or type(value).__name__ == "immutabledict":
            if isinstance(value, dict):
                if any(type(key) is not str for key in value):
                    raise _denied()
                return type(value), tuple(
                    sorted((str(k), self._value(v, depth + 1)) for k, v in value.items())
                )
            sequence = cast(tuple[object, ...] | list[object], value)
            return type(value), tuple(self._value(v, depth + 1) for v in sequence)
        if isinstance(value, FunctionType):
            if value.__qualname__ == "only_once.<locals>.go":
                cells = value.__closure__
                if cells is None or len(cells) != 3:
                    raise _denied()
                first, once, retry = (cell.cell_contents for cell in cells)
                if type(first) is not FunctionType or type(once) is not list or retry is not True:
                    raise _denied()
                previous = self._once.get(value)
                if previous is None:
                    if len(once) != 1 or once[0] is not first:
                        raise _denied()
                    self._once[value] = once, first, False
                else:
                    old_list, old_first, consumed = previous
                    if (
                        once is not old_list
                        or first is not old_first
                        or (once != [] and (consumed or len(once) != 1 or once[0] is not first))
                    ):
                        raise _denied()
                    self._once[value] = old_list, old_first, consumed or once == []
                return (
                    self._retain(value),
                    value.__code__,
                    self._value(value.__defaults__),
                    tuple(self._retain(cell) for cell in cells),
                    self._value(first, depth + 1),
                    self._retain(once),
                    retry,
                )
            return (
                self._retain(value),
                value.__code__,
                self._value(value.__defaults__, depth + 1),
                self._value(value.__kwdefaults__, depth + 1),
                tuple(
                    (self._retain(cell), self._value(cell.cell_contents, depth + 1))
                    for cell in value.__closure__ or ()
                ),
            )
        if isinstance(value, MethodType):
            return self._retain(value.__self__), self._value(value.__func__, depth + 1)
        return self._retain(value)

    @staticmethod
    def _url(url: URL) -> object:
        if type(url) is not URL:
            raise _denied()
        return _freeze(
            (
                url.drivername,
                url.username,
                url.password,
                url.host,
                url.port,
                url.database,
                dict(url.query),
            )
        )

    def _dispatch(self, target: Any) -> object:
        def listeners(name: str) -> Any:
            value = getattr(target.dispatch, name)
            return value._clslevel.get(target, ()) if isinstance(target, type) else value

        return tuple(
            (name, tuple(self._value(fn) for fn in listeners(name)))
            for name in target.dispatch._event_names
        )

    def _default_dispatch(self) -> None:
        """An initial inherited user handler is never a constructor default."""
        for target in (self._sync_engine, self._dialect, AsyncSession.sync_session_class):
            for name in cast(tuple[str, ...], target.dispatch._event_names):
                value = getattr(target.dispatch, name)
                handlers = value._clslevel.get(target, ()) if isinstance(target, type) else value
                if list(handlers):
                    raise _denied()
        for name in cast(tuple[str, ...], self._pool.dispatch._event_names):
            handlers = list(getattr(self._pool.dispatch, name))
            if name != "connect":
                if handlers:
                    raise _denied()
                continue
            expected = (
                ("sqlalchemy.engine.create", "create_engine.<locals>.on_connect"),
                ("sqlalchemy.util.langhelpers", "only_once.<locals>.go"),
            )
            if (
                len(handlers) != 2
                or tuple(
                    (fn.__module__, fn.__qualname__) for fn in handlers if type(fn) is FunctionType
                )
                != expected
            ):
                raise _denied()

    def _signature(self) -> object:
        engine, pool, dialect, maker, r = (
            self._sync_engine,
            self._pool,
            self._dialect,
            self._sessions,
            self._repository,
        )
        creator = pool._creator
        if (
            type(creator) is not FunctionType
            or creator.__module__ != "sqlalchemy.engine.create"
            or creator.__qualname__ != "create_engine.<locals>.connect"
            or creator.__closure__ is None
            or len(creator.__closure__) != 3
        ):
            raise _denied()
        arguments, parameters, bound_dialect = (x.cell_contents for x in creator.__closure__)
        connect_args = cast(
            Callable[[URL], tuple[list[object], dict[str, object]]], dialect.create_connect_args
        )
        wanted_args, wanted_params = connect_args(make_url(self._settings.database_url))
        if bound_dialect is not dialect or self._value((arguments, dict(parameters))) != (
            self._value((wanted_args, wanted_params))
        ):
            raise _denied()
        return (
            _freeze(self._settings),
            str(PROJECT_ROOT),
            self._url(engine.url),
            self._value(maker.class_),
            self._value(maker.kw),
            self._value(AsyncSession.sync_session_class),
            self._dispatch(AsyncSession.sync_session_class),
            self._value(AsyncSession.__init__),
            self._value(AsyncSession.execute),
            self._value(AsyncSession.sync_session_class.execute),
            self._value(maker.__call__),
            self._value(engine.connect),
            self._value(engine.raw_connection),
            self._value(engine._connection_cls),
            self._value(pool.connect),
            self._value(pool._do_get),
            self._value(pool._create_connection),
            self._value(pool.dispose),
            self._value(pool.recreate),
            engine.echo,
            engine.hide_parameters,
            self._value(engine._execution_options),
            self._value(pool._pre_ping),
            self._value(pool._recycle),
            self._value(pool.size()),
            self._value(pool._max_overflow),
            self._value(pool._timeout),
            self._value(pool._creator),
            self._value(pool._invoke_creator),
            self._value(dialect.connect),
            self._value(dialect.create_connect_args),
            self._value(dialect.dbapi),
            self._value(dialect.dbapi.connect),
            self._value(dialect.dbapi.psycopg),
            self._value(dialect.dbapi.psycopg.AsyncConnection.connect),
            self._value(dialect.dbapi.psycopg.connect),
            self._value(dialect.on_connect),
            self._value(dialect.initialize),
            self._value(dialect.do_rollback),
            self._dispatch(engine),
            self._dispatch(pool),
            self._dispatch(dialect),
            self._value(r.clock),
            _freeze(r.binding),
            _freeze(r.recovery.binding),
            _freeze(r.recovery.index_prefix),
        )

    def _guard(self) -> None:
        if self._closed:
            raise _denied()
        settings, engine, maker, r = self._settings, self._engine, self._sessions, self._repository
        objects = (
            settings,
            engine,
            maker,
            r,
            engine.sync_engine,
            engine.sync_engine.pool,
            engine.sync_engine.dialect,
            r.recovery,
        )
        if (
            any(a is not b for a, b in zip(objects, self._owned, strict=True))
            or type(settings) is not Settings
            or type(engine) is not AsyncEngine
            or type(engine.sync_engine) is not Engine
            or type(maker) is not async_sessionmaker
            or type(self._pool) is not AsyncAdaptedQueuePool
            or type(self._dialect) is not PGDialectAsync_psycopg
            or cast(object, self._pool._dialect) is not self._dialect
            or r.sessions is not maker
            or r.recovery.sessions is not maker
            or set(maker.kw) != {"bind", "autoflush", "expire_on_commit"}
            or maker.kw["bind"] is not engine
            or maker.kw["autoflush"] is not True
            or maker.kw["expire_on_commit"] is not False
            or maker.class_ is not AsyncSession
            or engine.sync_engine.echo is not False
            or engine.sync_engine.hide_parameters is not True
            or self._origin is not None
            and self._configuration() != self._origin
            or self._signature() != self._seal
        ):
            raise _denied()

    @property
    def control_repository(self) -> SqlAlchemyAccessEpochRepository:
        self._source_guard()
        return self._repository

    def _source_guard(self) -> None:
        self._safe_guard()
        entry = _ORIGINALS.get(self)
        if (
            entry is None
            or entry.owner is not self
            or entry.settings is not self._settings
            or entry.graph is not self._owned
            or entry.seal is not self._seal
            or entry.configuration != self._configuration()
            or entry.configuration != self._origin
        ):
            raise _denied()

    def _safe_guard(self) -> None:
        try:
            self._guard()
        except Exception:
            raise _denied() from None

    def _native_seal(self, native: NativeWindowsPrivateState) -> object:
        try:
            NativeWindowsPrivateState.assert_origin(native)
        except Exception:
            raise _denied() from None
        if (
            type(native) is not NativeWindowsPrivateState
            or str(native.root) != _ROOT_TEXT
            or str(native.private) != str(Path(_ROOT_TEXT) / ".local-data/access-epoch/private")
            or type(native.owner) is not str
            or not native.owner.startswith("S-1-")
        ):
            raise _denied()
        values: list[object] = [
            self._retain(native),
            _freeze((native.root, native.private, native.owner)),
        ]
        for attribute, names in _NATIVE_FUNCTIONS.items():
            dll = getattr(native, attribute)
            if (
                getattr(dll, "_name", None)
                != {
                    "kernel": "kernel32",
                    "advapi": "advapi32",
                    "crypt": "crypt32",
                }[attribute]
            ):
                raise _denied()
            functions: list[object] = []
            for name in names:
                fn = getattr(dll, name)
                address = None
                if isinstance(fn, CFuncPtr):
                    address = ctypes.cast(fn, ctypes.c_void_p).value
                functions.append(
                    (
                        name,
                        self._retain(fn),
                        address,
                        self._value(fn.argtypes),
                        self._value(fn.restype),
                    )
                )
            values.append(
                (
                    self._retain(dll),
                    self._value(dll._name),
                    self._value(dll._handle),
                    tuple(functions),
                )
            )
        values.append(tuple(self._value(getattr(native, name)) for name in _NATIVE_METHODS))
        return tuple(values)

    def _dependency_seal(self, value: NativeReadDependencies) -> object:
        if (
            type(value) is not NativeReadDependencies
            or type(value.nonce) is not UUID
            or value.nonce.int == 0
            or type(value.phase) is not str
            or value.phase not in {"context", "committed"}
            or value.settings is not self._settings
            or value.repository is not self._repository
            or type(value.keys) is not SqlAlchemyEpochKeyRepository
            or value.keys.parent is not self._repository
            or type(value.store) is not WindowsCredentialStore
            or value.store.files is not value.private
            or value.store.protection is not value.private
            or str(value.store.root) != _ROOT_TEXT
        ):
            raise _denied()
        return (
            _freeze((value.nonce, value.phase)),
            self._retain(value.keys),
            self._value(value.keys.clock),
            self._retain(value.store),
            _freeze(value.store.root),
            self._native_seal(value.private),
        )

    def _context_private(
        self, journal: ProtectedControlJournal | None, store: WindowsCredentialStore
    ) -> NativeWindowsPrivateState:
        """Association check only; it does not issue context or journal authority."""
        if (
            type(journal) is not ProtectedControlJournal
            or type(store) is not WindowsCredentialStore
            or str(journal.root) != _ROOT_TEXT
            or type(journal.files) is not NativeWindowsPrivateState
            or journal.files is not journal.protection
            or journal.files is not store.files
            or journal.files is not store.protection
        ):
            raise _denied()
        private = journal.files
        self._native_seal(private)
        return private

    def _publish(
        self,
        phase: Literal["context", "committed"],
        keys: SqlAlchemyEpochKeyRepository,
        store: WindowsCredentialStore,
        private: NativeWindowsPrivateState,
        context: NativeControlContext | None,
    ) -> NativeReadDependencies:
        self._source_guard()
        journal = None if context is None else context.journal
        if context is not None and self._context_private(journal, store) is not private:
            raise _denied()
        value = NativeReadDependencies(
            uuid4(), phase, self._settings, self._repository, keys, store, private
        )
        signature = self._dependency_seal(value)
        self._source_guard()
        self._issued[value] = _Issued(
            self,
            value,
            signature,
            context,
            journal,
            (value, keys, store, private, context, journal),
        )
        try:
            self.assert_issued(value)
        except BaseException:
            self._issued.pop(value, None)
            raise
        return value

    def bind_committed(self) -> NativeReadDependencies:
        try:
            self._source_guard()
            private = NativeWindowsPrivateState(Path(_ROOT_TEXT))
            self._source_guard()
            store = WindowsCredentialStore(Path(_ROOT_TEXT), private, private)
            keys = SqlAlchemyEpochKeyRepository(self._repository)
            return self._publish("committed", keys, store, private, None)
        except Exception:
            raise _denied() from None

    def bind_context(self, context: NativeControlContext) -> NativeReadDependencies:
        try:
            self._source_guard()
            if type(context) is not NativeControlContext:
                raise _denied()
            context.assert_owned()
            store, keys = context.store, context.keys
            if (
                context.settings is not self._settings
                or context.repository is not self._repository
                or type(store) is not WindowsCredentialStore
                or type(keys) is not SqlAlchemyEpochKeyRepository
                or type(store.files) is not NativeWindowsPrivateState
                or store.files is not store.protection
            ):
                raise _denied()
            context.assert_owned()
            private = self._context_private(context.journal, store)
            return self._publish("context", keys, store, private, context)
        except Exception:
            raise _denied() from None

    def assert_issued(self, value: NativeReadDependencies) -> None:
        try:
            self._source_guard()
            entry = self._issued.get(value)
            if (
                entry is None
                or entry.owner is not self
                or entry.value is not value
                or entry.seal != self._dependency_seal(value)
            ):
                raise _denied()
            if entry.context is not None:
                context = entry.context
                context.assert_owned()
                if (
                    context.settings is not value.settings
                    or context.repository is not value.repository
                    or context.store is not value.store
                    or context.keys is not value.keys
                    or context.journal is not entry.journal
                    or entry.journal is None
                    or self._context_private(entry.journal, value.store) is not value.private
                ):
                    raise _denied()
            self._source_guard()
        except Exception:
            raise _denied() from None

    async def close(self) -> None:
        """Consume before awaiting; dispose only the pool constructed by this owner."""
        if self._closed:
            return
        self._closed = True
        self._issued.clear()
        original = _ORIGINALS.pop(self, None)
        pool = self._owned[5] if original is None else original.graph[5]
        if type(pool) is not AsyncAdaptedQueuePool:
            raise _denied()
        task = asyncio.create_task(greenlet_spawn(pool.dispose))
        primary: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                if primary is None:
                    primary = exc
        try:
            task.result()
        except Exception:
            if primary is None:
                raise _denied() from None
        if primary is not None:
            raise primary
