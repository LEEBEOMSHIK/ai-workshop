"""Owned committed fresh observation; no cutover, pending verifier or READY grant.

Only the fixed original assembly constructs this source. Five Docker reads and
nine HTTPS reads are bracketed by real committed SQL/material checks. Deadline
expiry stops new work but never substitutes for the owned cleanup barrier.
"""

import asyncio
import json
import os
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from types import FunctionType
from typing import Any
from uuid import UUID, uuid4
from weakref import ReferenceType, WeakKeyDictionary, ref

from ai_workshop.infrastructure.local.control_process_windows import (
    NativeWindowsProcess,
    WindowsControlProcess,
)
from ai_workshop.labs.rag.indexing.access_epoch_auth_packets import (
    validate_authenticated_body,
    validate_privileges_body,
)
from ai_workshop.labs.rag.indexing.access_epoch_committed_https import (
    _CommittedHttpsMaterial,
    _read_committed_https_catalog,
)
from ai_workshop.labs.rag.indexing.access_epoch_committed_tls import NativeCommittedTlsReader
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT, _security_config
from ai_workshop.labs.rag.indexing.access_epoch_docker_packets import validate_docker_identity
from ai_workshop.labs.rag.indexing.access_epoch_https_read import _capture_https_read
from ai_workshop.labs.rag.indexing.access_epoch_process import _binary_sha
from ai_workshop.labs.rag.indexing.access_epoch_secured_read import (
    NativeSecuredReadSource,
    SecuredReadBinding,
    _freeze,
)
from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
    NativeReadDependencies,
    NativeSecuredReadAssembly,
)
from ai_workshop.labs.rag.indexing.access_epoch_secured_read_process import (
    SecuredDockerReadCatalog,
    _capture_docker_read,
)
from ai_workshop.labs.rag.indexing.access_epoch_server_packets import (
    ServerReadExpectation,
    validate_server_packets,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import canonical_json, strict_utc
from ai_workshop.labs.rag.indexing.alias_recovery_types import FrozenAliasClaim

_ATTEMPT_SECONDS = 240.0
_HASHES = (
    "http_ca_sha256",
    "transport_ca_sha256",
    "http_ca_der_sha256",
    "transport_ca_der_sha256",
    "http_leaf_der_sha256",
    "transport_leaf_der_sha256",
)
_NOTES = (
    "secured_read_cleanup_unverified",
    "secured_read_capture_unverified",
    "secured_https_cleanup_unverified",
    "fresh_secured_read_cleanup_unverified",
)


def _denied() -> ValueError:
    return ValueError("fresh_secured_read_denied")


def _notes(source: BaseException, target: BaseException) -> None:
    for note in _NOTES:
        if note in getattr(source, "__notes__", ()) and note not in getattr(
            target, "__notes__", ()
        ):
            target.add_note(note)


def _environment() -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in os.environ.items():
        name = key.upper()
        if name not in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}:
            continue
        if name in result or not value or "\0" in value:
            raise _denied()
        result[name] = value
    if "SYSTEMROOT" not in result:
        raise _denied()
    return result


def _config() -> tuple[object, bytes]:
    path = PROJECT_ROOT / "infrastructure/elasticsearch/elasticsearch-secured.yml"
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise _denied()
    before = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(before.st_mode)
        or not 0 < before.st_size <= 65536
        or getattr(before, "st_file_attributes", 0) & 0x400
    ):
        raise _denied()
    with path.open("rb") as stream:
        body = stream.read(65537)
    after = path.stat(follow_symlinks=False)

    def identity(value: os.stat_result) -> object:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            getattr(value, "st_file_attributes", 0),
        )

    if identity(before) != identity(after) or len(body) != before.st_size:
        raise _denied()
    _security_config(body)
    return identity(after), body


def _process_signature(native: WindowsControlProcess) -> object:
    _assert_process_code()
    if (
        type(native) is not WindowsControlProcess
        or type(native._native) is not NativeWindowsProcess
    ):
        raise _denied()
    if native._limit != 2097152 or native._max_wait_ms != 10000 or native._input_limit != 65536:
        raise _denied()
    low = native._native
    for instance in (native, low):
        if any(
            name in vars(instance)
            for name, function in vars(type(instance)).items()
            if type(function) is FunctionType
        ):
            raise _denied()
    libraries = []
    for library in (low._kernel, low._security):
        entries = []
        for name, function in sorted(vars(library).items()):
            if name.startswith("_") or not callable(function):
                continue
            entries.append(
                (
                    name,
                    id(function),
                    getattr(function, "__code__", None),
                    tuple(getattr(function, "argtypes", ()) or ()),
                    getattr(function, "restype", None),
                )
            )
        libraries.append((id(library), library._name, library._handle, tuple(entries)))
    return (id(native), id(low), tuple(libraries))


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class FreshSecuredObservation:
    nonce: UUID
    epoch_id: UUID
    execution_id: UUID
    ordinal: int
    start_at: datetime
    end_at: datetime
    phase: str
    public_json: str


@dataclass(slots=True, repr=False)
class _Origin:
    owner: ReferenceType["NativeFreshSecuredReadSource"]
    assembly: NativeSecuredReadAssembly
    dependencies: NativeReadDependencies
    source: NativeSecuredReadSource
    configuration: tuple[object, bytes]
    docker_sha: str
    environment: dict[str, str]
    natives: list[WindowsControlProcess] = field(default_factory=list)
    native_seals: dict[WindowsControlProcess, object] = field(default_factory=dict)
    ownership: object = None
    claim: FrozenAliasClaim | None = None
    claim_seal: object = None
    binding: SecuredReadBinding | None = None
    tls: NativeCommittedTlsReader | None = None
    baseline: object = None
    phase: str | None = None
    running: asyncio.Task[Any] | None = None
    completed: asyncio.Future[tuple[str, ...]] | None = None
    cleanup: asyncio.Task[None] | None = None
    closed: bool = False
    poisoned: bool = False
    issued: dict[FreshSecuredObservation, "_Issued"] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, repr=False)
class _Issued:
    owner: object
    value: FreshSecuredObservation
    seal: object
    source: NativeSecuredReadSource
    binding: SecuredReadBinding
    tls: NativeCommittedTlsReader
    packet_hashes: tuple[str, ...]


def _ownership(origin: _Origin) -> object:
    return (
        id(origin.assembly),
        id(origin.dependencies),
        id(origin.source),
        id(origin.natives),
        id(origin.native_seals),
        id(origin.issued),
        str(PROJECT_ROOT),
        origin.configuration,
        origin.docker_sha,
        tuple(sorted(origin.environment.items())),
    )


_ORIGINS: WeakKeyDictionary["NativeFreshSecuredReadSource", _Origin] = WeakKeyDictionary()
_PROCESS_CODE = tuple(
    (
        cls,
        name,
        function,
        function.__code__,
        _freeze(function.__defaults__),
        _freeze(function.__kwdefaults__),
    )
    for cls in (WindowsControlProcess, NativeWindowsProcess)
    for name, function in vars(cls).items()
    if type(function) is FunctionType
)


def _assert_process_code() -> None:
    for kind, name, function, code, defaults, keywords in _PROCESS_CODE:
        if (
            getattr(kind, name) is not function
            or function.__code__ is not code
            or _freeze(function.__defaults__) != defaults
            or _freeze(function.__kwdefaults__) != keywords
        ):
            raise _denied()


class NativeFreshSecuredReadSource:
    def __init__(self) -> None:
        raise _denied()

    @classmethod
    @asynccontextmanager
    async def open_committed(cls) -> AsyncIterator["NativeFreshSecuredReadSource"]:
        if cls is not NativeFreshSecuredReadSource:
            raise _denied()
        async with NativeSecuredReadAssembly.open_original() as assembly:
            value: NativeFreshSecuredReadSource | None = None
            try:
                _assert_process_code()
                deps = assembly.bind_committed()
                source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
                value = object.__new__(cls)
                _ORIGINS[value] = _Origin(
                    ref(value),
                    assembly,
                    deps,
                    source,
                    _config(),
                    _binary_sha(),
                    _environment(),
                )
                _ORIGINS[value].ownership = _ownership(_ORIGINS[value])
                value._static()
                yield value
            except BaseException as primary:
                if value is not None:
                    try:
                        await value.close()
                    except BaseException as cleanup_error:
                        _notes(cleanup_error, primary)
                        if not isinstance(cleanup_error, asyncio.CancelledError):
                            primary.add_note("fresh_secured_read_cleanup_unverified")
                if isinstance(primary, Exception):
                    denial = _denied()
                    _notes(primary, denial)
                    raise denial from None
                raise
            else:
                assert value is not None
                await value.close()

    def _memory(self) -> _Origin:
        origin = _ORIGINS.get(self)
        if (
            type(self) is not NativeFreshSecuredReadSource
            or origin is None
            or origin.owner() is not self
            or origin.closed
            or origin.poisoned
            or type(origin.closed) is not bool
            or type(origin.poisoned) is not bool
            or origin.ownership != _ownership(origin)
            or (
                origin.phase is not None
                and (type(origin.phase) is not str or origin.phase not in {"verified", "receipted"})
            )
            or type(origin.natives) is not list
            or type(origin.native_seals) is not dict
            or len(origin.natives) != len(origin.native_seals)
            or set(origin.natives) != set(origin.native_seals)
            or any(
                origin.native_seals[native] != _process_signature(native)
                for native in origin.natives
            )
            or origin.environment != _environment()
        ):
            raise _denied()
        _assert_process_code()
        if origin.claim is not None and _freeze(origin.claim) != origin.claim_seal:
            raise _denied()
        if origin.tls is not None:
            tls = NativeCommittedTlsReader._memory(origin.tls)
            if (
                tls.source is not origin.source
                or tls.binding is not origin.binding
                or tls.association.assembly is not origin.assembly
                or tls.association.dependencies is not origin.dependencies
            ):
                raise _denied()
        return origin

    def _static(self) -> _Origin:
        origin = self._memory()
        NativeSecuredReadAssembly.assert_issued(origin.assembly, origin.dependencies)
        NativeSecuredReadSource._assert_committed_dependencies(origin.source)
        if origin.configuration != _config() or origin.docker_sha != _binary_sha():
            raise _denied()
        return self._memory()

    def _new_native(self) -> WindowsControlProcess:
        origin = self._static()
        native = WindowsControlProcess(max_output_bytes=2097152, max_wait_ms=10000)
        origin.natives.append(native)
        origin.native_seals[native] = _process_signature(native)
        self._memory()
        return native

    async def _material(self, deadline: float) -> _CommittedHttpsMaterial:
        origin = self._static()
        if monotonic() >= deadline or origin.binding is None or origin.tls is None:
            raise _denied()
        value = await _read_committed_https_catalog(origin.source, origin.binding, origin.tls)
        origin = self._static()
        if monotonic() >= deadline:
            raise _denied()
        catalog = value.catalog
        signature = (
            (
                _freeze(catalog.epoch_id),
                _freeze(catalog.permissions),
                sha256(catalog.http_ca_pem).hexdigest(),
                catalog.http_leaf_sha256,
                _freeze(catalog.keys),
            ),
            _freeze(value.sample.evidence),
            NativeSecuredReadSource._state_seal(value.sample.state),
            value.sample.material,
        )
        if (
            origin.baseline is not None
            and signature != origin.baseline
            or origin.phase == "receipted"
            and value.phase != "receipted"
        ):
            raise _denied()
        origin.baseline, origin.phase = signature, value.phase
        return value

    async def observe_committed(self, claim: FrozenAliasClaim) -> FreshSecuredObservation:
        origin = self._static()
        if origin.running is not None or type(claim) is not FrozenAliasClaim:
            raise _denied()
        if origin.claim is not None and claim is not origin.claim:
            raise _denied()
        task = asyncio.current_task()
        if task is None:
            raise _denied()
        completed: asyncio.Future[tuple[str, ...]] = asyncio.get_running_loop().create_future()
        origin.running = task
        origin.completed = completed
        failure_notes: tuple[str, ...] = ()
        start, deadline, nonce = datetime.now(UTC), monotonic() + _ATTEMPT_SECONDS, uuid4()
        try:
            async with asyncio.timeout(_ATTEMPT_SECONDS):
                if origin.binding is None:
                    origin.claim, origin.claim_seal = claim, _freeze(claim)
                    origin.binding = await NativeSecuredReadSource.bind_verified(
                        origin.source, claim
                    )
                    self._static()
                    origin.tls = await NativeCommittedTlsReader._open_bound_source(
                        origin.source, origin.binding
                    )
                    self._static()
                initial = await self._material(deadline)
                binding = origin.binding
                facts = json.loads(initial.sample.evidence.proof_facts_json)
                manifests = dict(initial.sample.evidence.manifests)
                deployment, tls = (
                    json.loads(manifests["new_deployment"]),
                    json.loads(manifests["tls_public_ca"]),
                )
                docker_catalog = SecuredDockerReadCatalog(
                    facts["new_container_id"], json.loads(manifests["protected_image"])["image_id"]
                )
                capture_binding = canonical_json(
                    {
                        "schema_version": 1,
                        "epoch_id": str(binding.epoch_id),
                        "execution_id": str(binding.execution_id),
                        "ordinal": binding.ordinal,
                        "nonce": str(nonce),
                        "binding_nonce": str(binding.nonce),
                    }
                )
                docker = []
                for slot in range(5):
                    native = self._new_native()
                    await self._material(deadline)
                    output = await _capture_docker_read(
                        catalog=docker_catalog,
                        native=native,
                        files=origin.dependencies.private,
                        nonce=nonce,
                        slot=slot,
                        binding_json=capture_binding,
                        environment=origin.environment,
                    )
                    await self._material(deadline)
                    if output.stderr or not output.stdout:
                        raise _denied()
                    docker.append(output.stdout)
                current = validate_docker_identity(
                    *docker,
                    deployment_manifest_json=manifests["new_deployment"],
                    original_image_json=manifests["protected_image"],
                    original_volume_json=manifests["original_volume_identity"],
                    secured_config=origin.configuration[1],
                    tls_public_hashes={name: tls[name] for name in _HASHES},
                )
                if (
                    current.epoch_id != binding.epoch_id
                    or current.execution_id != binding.execution_id
                    or current.container_id != facts["new_container_id"]
                    or current.started_at != strict_utc(facts["new_server_started_at"])
                ):
                    raise _denied()
                expected = ServerReadExpectation(
                    "9.5.2",
                    facts["cluster_uuid"],
                    current.cluster_name,
                    facts["stable_node_id"],
                    facts["new_ephemeral_id"],
                    strict_utc(facts["new_jvm_start_at"]),
                    current.started_at,
                    deployment["original_ipv4"],
                )
                packets = []
                packet_hashes = [sha256(body).hexdigest() for body in docker]
                for slot in range(9):
                    material = await self._material(deadline)
                    response = await _capture_https_read(material.catalog, slot)
                    final = await self._material(deadline)
                    packet_hashes.append(sha256(response.body).hexdigest())
                    if slot < 3:
                        packets.append(response.body)
                    else:
                        key = material.catalog.keys[(slot - 3) // 2]
                        if slot % 2:
                            validate_authenticated_body(
                                response.body, key_id=key.key_id, key_name=key.key_name
                            )
                        else:
                            validate_privileges_body(
                                response.body,
                                epoch_id=binding.epoch_id,
                                permissions=material.catalog.permissions,
                                role=key.role,
                            )
                end = datetime.now(UTC)
                server = validate_server_packets(
                    expected, info=packets[0], state=packets[1], nodes=packets[2], sampled_at=end
                )
                self._static()
                if end < start or monotonic() >= deadline:
                    raise _denied()
                public = canonical_json(
                    {
                        "schema_version": 1,
                        "server": json.loads(server),
                        "config": {
                            "secured_yaml_sha256": sha256(origin.configuration[1]).hexdigest(),
                            "public_security_profile": "project_http_tls_transport_mtls",
                        },
                        "tls": {name: tls[name] for name in _HASHES},
                        "auth_policy": json.loads(manifests["auth_policy"])["auth_policy"],
                        "key_ids": {key.role: key.key_id for key in final.catalog.keys},
                    }
                )
                observation = FreshSecuredObservation(
                    nonce,
                    binding.epoch_id,
                    binding.execution_id,
                    binding.ordinal,
                    start,
                    end,
                    final.phase,
                    public,
                )
                assert origin.tls is not None
                origin.issued[observation] = _Issued(
                    self,
                    observation,
                    _freeze(observation),
                    origin.source,
                    binding,
                    origin.tls,
                    tuple(packet_hashes),
                )
                self.assert_observed(observation)
                return observation
        except BaseException as primary:
            origin.poisoned = True
            origin.issued.clear()
            if isinstance(primary, TimeoutError) and isinstance(
                primary.__cause__, asyncio.CancelledError
            ):
                _notes(primary.__cause__, primary)
            failure_notes = tuple(
                note for note in _NOTES if note in getattr(primary, "__notes__", ())
            )
            if isinstance(primary, Exception):
                denial = _denied()
                _notes(primary, denial)
                raise denial from None
            raise
        finally:
            origin.running = None
            origin.completed = None
            completed.set_result(failure_notes)

    def assert_observed(self, observation: FreshSecuredObservation) -> None:
        origin = self._memory()
        entry = origin.issued.get(observation)
        if (
            type(observation) is not FreshSecuredObservation
            or type(entry) is not _Issued
            or entry.owner is not self
            or entry.value is not observation
            or entry.source is not origin.source
            or entry.binding is not origin.binding
            or entry.tls is not origin.tls
            or entry.seal != _freeze(observation)
        ):
            raise _denied()

    async def close(self) -> None:
        origin = _ORIGINS.get(self)
        if (
            type(self) is not NativeFreshSecuredReadSource
            or origin is None
            or origin.owner() is not self
        ):
            raise _denied()
        if origin.cleanup is None:
            origin.closed, origin.poisoned = True, True
            origin.issued.clear()
            running, completed = origin.running, origin.completed
            if running is asyncio.current_task():
                running, completed = None, None
            origin.cleanup = asyncio.create_task(self._close_owned(origin, running, completed))
        primary: BaseException | None = None
        while not origin.cleanup.done():
            try:
                await asyncio.shield(origin.cleanup)
            except asyncio.CancelledError as error:
                primary = primary or error
            except BaseException:
                break
        try:
            origin.cleanup.result()
        except BaseException as error:
            if primary is None:
                primary = error
            else:
                _notes(error, primary)
        if primary is not None:
            if isinstance(primary, Exception):
                denial = _denied()
                _notes(primary, denial)
                raise denial from None
            raise primary

    @staticmethod
    async def _close_owned(
        origin: _Origin,
        running: asyncio.Task[Any] | None,
        completed: asyncio.Future[tuple[str, ...]] | None,
    ) -> None:
        primary: BaseException | None = None
        if running is not None and completed is not None:
            running.cancel()
            while not completed.done():
                try:
                    await asyncio.shield(completed)
                except asyncio.CancelledError as error:
                    primary = primary or error
            for note in completed.result():
                primary = primary or _denied()
                primary.add_note(note)
        try:
            if origin.tls is not None:
                # This reader owns only memory associations; its own error path
                # may already have invalidated them. Disposal belongs here.
                NativeCommittedTlsReader._invalidate(origin.tls)
        except BaseException:
            primary = primary or _denied()
            primary.add_note("fresh_secured_read_cleanup_unverified")
        try:
            await NativeSecuredReadAssembly.close(origin.assembly)
        except BaseException as error:
            primary = primary or error
            _notes(error, primary)
            if isinstance(error, Exception):
                primary.add_note("fresh_secured_read_cleanup_unverified")
        if primary is not None:
            raise primary
