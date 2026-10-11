"""Private committed TLS candidate; no final factory or operational authority.

SQL/native/files are real producers in this candidate; offline tests replace
only low external transports. Seven repeated file samples are not an atomic
filesystem snapshot or proof that unseen changes never occurred.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast
from uuid import UUID, uuid4
from weakref import ReferenceType, WeakKeyDictionary, ref

from ai_workshop.infrastructure.local.tls_bundle import ProjectTlsBundles
from ai_workshop.infrastructure.local.windows_private_state import (
    NativeWindowsPrivateState,
    ProtectedFileRead,
)
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from ai_workshop.labs.rag.indexing.access_epoch_secured_read import (
    _ASSOCIATIONS,
    _NATIVE_SOURCES,
    NativeSecuredReadSource,
    SecuredReadBinding,
    _Association,
    _freeze,
    _Sample,
)
from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
    _ORIGINALS,
    NativeSecuredReadAssembly,
)
from ai_workshop.labs.rag.indexing.access_epoch_tls_packets import _binding, decode_tls_packet
from ai_workshop.labs.rag.indexing.access_epoch_types import CutoverActionKind, canonical_json
from ai_workshop.labs.rag.indexing.alias_recovery_types import utc_text

_FILES = tuple(
    f"{purpose}/{name}"
    for purpose in ("http", "transport")
    for name in ("node.key", "node.crt", "ca.crt")
)
_HASHES = (
    "http_ca_sha256",
    "transport_ca_sha256",
    "http_ca_der_sha256",
    "transport_ca_der_sha256",
    "http_leaf_der_sha256",
    "transport_leaf_der_sha256",
)


def _denied() -> ValueError:
    return ValueError("committed_tls_read_denied")


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class CommittedTlsObservation:
    nonce: UUID
    epoch_id: UUID
    action_id: UUID
    original_ipv4: str
    manifest_json: str
    phase: str


@dataclass(frozen=True, slots=True, repr=False)
class _Origin:
    owner: ReferenceType["NativeCommittedTlsReader"]
    source: NativeSecuredReadSource
    binding: SecuredReadBinding
    association: _Association
    native: NativeWindowsPrivateState
    root: str
    baseline: tuple[ProtectedFileRead, ...] | None
    manifest_json: str | None
    phase: str | None
    observations: dict[CommittedTlsObservation, object]


_ORIGINS: WeakKeyDictionary["NativeCommittedTlsReader", _Origin] = WeakKeyDictionary()


class NativeCommittedTlsReader:
    _source: NativeSecuredReadSource
    _binding: SecuredReadBinding
    _native: NativeWindowsPrivateState
    _root: str

    def __init__(self) -> None:
        raise _denied()

    @classmethod
    async def _open_bound_source(
        cls, source: NativeSecuredReadSource, binding: SecuredReadBinding
    ) -> "NativeCommittedTlsReader":
        reader: NativeCommittedTlsReader | None = None
        try:
            if cls is not NativeCommittedTlsReader or type(source) is not NativeSecuredReadSource:
                raise _denied()
            NativeSecuredReadSource._assert_committed_dependencies(source)
            NativeSecuredReadSource.assert_bound(source, binding)
            association = _ASSOCIATIONS[source]
            native = association.dependencies.private
            NativeWindowsPrivateState.assert_origin(native)
            reader = object.__new__(cls)
            reader._source, reader._binding, reader._native, reader._root = (
                source,
                binding,
                native,
                str(PROJECT_ROOT),
            )
            _ORIGINS[reader] = _Origin(
                ref(reader),
                source,
                binding,
                association,
                native,
                reader._root,
                None,
                None,
                None,
                {},
            )
            files, manifest, phase = await reader._fresh()
            origin = reader._guard()
            _ORIGINS[reader] = _Origin(
                origin.owner,
                source,
                binding,
                association,
                native,
                reader._root,
                files,
                manifest,
                phase,
                origin.observations,
            )
            reader._guard()
            return reader
        except BaseException as error:
            if reader is not None:
                reader._invalidate()
            if isinstance(error, Exception):
                raise _denied() from None
            raise

    def _memory(self) -> _Origin:
        origin = _ORIGINS.get(self)
        if (
            type(self) is not NativeCommittedTlsReader
            or origin is None
            or origin.owner() is not self
            or self._source is not origin.source
            or self._binding is not origin.binding
            or self._native is not origin.native
            or type(self._root) is not str
            or self._root != origin.root
            or origin.root != str(PROJECT_ROOT)
            or (
                origin.phase is not None
                and (type(origin.phase) is not str or origin.phase not in {"verified", "receipted"})
            )
        ):
            raise _denied()
        source, association = origin.source, origin.association
        assembly, dependencies = association.assembly, association.dependencies
        entry = source._issued.get(origin.binding)
        original = _ORIGINALS.get(assembly)
        dependency = assembly._issued.get(dependencies)
        if (
            _ASSOCIATIONS.get(source) is not association
            or association.owner() is not source
            or source not in _NATIVE_SOURCES
            or type(source._root_text) is not str
            or source._root_text != origin.root
            or type(source._ports) is not tuple
            or len(source._ports) != 2
            or any(port is not origin.native for port in source._ports)
            or any(
                actual is not expected
                for actual, expected in zip(
                    (source._settings, source._repository, source._store, source._keys),
                    (
                        dependencies.settings,
                        dependencies.repository,
                        dependencies.store,
                        dependencies.keys,
                    ),
                    strict=True,
                )
            )
            or any(
                actual is not retained
                for actual, retained in zip(
                    (source._settings, source._repository, source._store, source._keys),
                    source._objects,
                    strict=True,
                )
            )
            or NativeSecuredReadSource._signature(source) != source._input_seal
            or entry is None
            or entry.owner is not source
            or entry.binding is not origin.binding
            or entry.binding_seal != _freeze(origin.binding)
            or entry.claim_seal != _freeze(entry.claim)
            or assembly._closed is not False
            or original is None
            or original.owner is not assembly
            or original.settings is not assembly._settings
            or original.graph is not assembly._owned
            or original.seal is not assembly._seal
            or original.configuration != assembly._origin
            or NativeSecuredReadAssembly._signature(assembly) != assembly._seal
            or dependency is None
            or dependency.owner is not assembly
            or dependency.value is not dependencies
            or dependencies.phase != "committed"
            or dependency.seal != NativeSecuredReadAssembly._dependency_seal(assembly, dependencies)
        ):
            raise _denied()
        NativeWindowsPrivateState.assert_origin(origin.native)
        return origin

    def _guard(self) -> _Origin:
        origin = self._memory()
        NativeSecuredReadSource._assert_committed_dependencies(origin.source)
        NativeSecuredReadSource.assert_bound(origin.source, origin.binding)
        return self._memory()

    def _read_all(self) -> tuple[ProtectedFileRead, ...]:
        origin = self._guard()
        base = PROJECT_ROOT / ".local-data/access-epoch/private/tls" / str(origin.binding.epoch_id)
        paths = (base / "bundle.dpapi", *(base / "bind" / item for item in _FILES))
        result: list[ProtectedFileRead] = []
        for i, path in enumerate(paths):
            self._guard()
            limit = 262144 if i == 0 else 16384
            checked = NativeWindowsPrivateState.read_protected(
                origin.native, str(path), limit=limit
            )
            self._guard()
            if type(checked) is not ProtectedFileRead:
                raise _denied()
            result.append(checked)
        files = tuple(result)
        if origin.baseline is not None and files != origin.baseline:
            raise _denied()
        return files

    def _material(self, sample: _Sample, files: tuple[ProtectedFileRead, ...]) -> str:
        origin = self._guard()
        state = sample.state
        prepared = state.prepared
        if prepared is None or prepared.binding != sample.evidence.binding:
            raise _denied()
        tls = next(row for row in state.actions if row.action.kind is CutoverActionKind.PREPARE_TLS)
        stored: object = json.loads(tls.manifest_json or "null")
        if type(stored) is not dict:
            raise _denied()
        ip = cast(dict[str, object], stored).get("original_ipv4")
        if type(ip) is not str:
            raise _denied()
        public_binding = _binding(origin.binding.epoch_id, tls.action, ip)
        target = sha256(
            canonical_json(
                {
                    "preparation_kind": "local_files",
                    "schema_version": 1,
                    "epoch_id": str(origin.binding.epoch_id),
                    "execution_id": str(origin.binding.execution_id),
                    "original_ipv4": ip,
                    "files": list(_FILES),
                    "original_deployment_sha256": prepared.original.deployment_sha256,
                }
            ).encode()
        ).hexdigest()
        expected = json.loads(tls.action.expected.identity_json)
        if (
            expected["target_sha256"] != target
            or expected["scope_sha256"]
            != sha256(
                json.dumps([prepared.original.daemon_sha256, "ai-workshop"]).encode()
            ).hexdigest()
        ):
            raise _denied()
        self._guard()
        packet = NativeWindowsPrivateState.unprotect(origin.native, files[0].data)
        self._guard()
        if type(packet) is not bytes or packet == files[0].data:
            raise _denied()
        bundle = decode_tls_packet(
            packet, epoch_id=origin.binding.epoch_id, action=tls.action, original_ipv4=ip
        )
        bundles = ProjectTlsBundles(origin.native)
        now = datetime.now(UTC)
        self._guard()
        manifest = ProjectTlsBundles.validate(bundles, bundle, origin.binding.epoch_id, ip, now)
        self._guard()
        material = ProjectTlsBundles.materialize(bundles, bundle, origin.binding.epoch_id, ip, now)
        self._guard()
        if tuple(item.relative_path for item in material.files) != _FILES or tuple(
            item.content for item in material.files
        ) != tuple(item.data for item in files[1:]):
            raise _denied()
        public = public_binding | {
            "http_ca_sha256": manifest.http_ca_pem_sha256,
            "transport_ca_sha256": manifest.transport_ca_pem_sha256,
            "http_ca_der_sha256": manifest.http_ca_der_sha256,
            "transport_ca_der_sha256": manifest.transport_ca_der_sha256,
            "http_leaf_der_sha256": manifest.http_leaf_der_sha256,
            "transport_leaf_der_sha256": manifest.transport_leaf_der_sha256,
            "not_valid_after": utc_text(manifest.not_valid_after),
            "dns_sans": ["localhost", "elasticsearch"],
            "ip_sans": ["127.0.0.1", ip],
        }
        value = canonical_json(public)
        manifests = dict(sample.evidence.manifests)
        if value != tls.manifest_json or value != manifests["tls_public_ca"]:
            raise _denied()
        settled_deployment = next(
            row for row in state.actions if row.action.kind is CutoverActionKind.START_SECURED
        )
        if settled_deployment.manifest_json != manifests["new_deployment"]:
            raise _denied()
        deployment = json.loads(manifests["new_deployment"])
        if (
            type(deployment) is not dict
            or type(deployment.get("schema_version")) is not int
            or deployment.get("schema_version") != 2
            or deployment.get("kind") != "start_secured"
            or deployment.get("epoch_id") != str(origin.binding.epoch_id)
            or deployment.get("execution_id") != str(origin.binding.execution_id)
            or deployment.get("original_ipv4") != ip
            or deployment.get("tls_public_hashes") != {name: public[name] for name in _HASHES}
        ):
            raise _denied()
        return value

    async def _fresh(self) -> tuple[tuple[ProtectedFileRead, ...], str, str]:
        origin = self._guard()
        first = await NativeSecuredReadSource._private_read_bound_sample(
            origin.source, origin.binding
        )
        self._guard()
        if origin.phase == "receipted" and first.state.phase != "receipted":
            raise _denied()
        files = self._read_all()
        manifest = self._material(first, files)
        if self._read_all() != files:
            raise _denied()
        second = await NativeSecuredReadSource._private_read_bound_sample(
            origin.source, origin.binding
        )
        self._guard()
        if (
            _freeze(first.evidence) != _freeze(second.evidence)
            or NativeSecuredReadSource._state_seal(first.state)
            != NativeSecuredReadSource._state_seal(second.state)
            or first.material != second.material
            or (first.state.phase == "receipted" and second.state.phase != "receipted")
            or self._read_all() != files
            or (origin.manifest_json is not None and manifest != origin.manifest_json)
        ):
            raise _denied()
        phase = NativeSecuredReadSource._phase(second.state)
        if origin.phase == "receipted" and phase != "receipted":
            raise _denied()
        self._guard()
        return files, manifest, phase

    async def observe(self) -> CommittedTlsObservation:
        try:
            origin = self._guard()
            if origin.baseline is None or origin.manifest_json is None:
                raise _denied()
            _files, manifest, phase = await self._fresh()
            origin = self._guard()
            public = json.loads(manifest)
            value = CommittedTlsObservation(
                uuid4(),
                origin.binding.epoch_id,
                UUID(public["action_id"]),
                public["original_ipv4"],
                manifest,
                phase,
            )
            origin.observations[value] = _freeze(value)
            _ORIGINS[self] = _Origin(
                origin.owner,
                origin.source,
                origin.binding,
                origin.association,
                origin.native,
                origin.root,
                origin.baseline,
                origin.manifest_json,
                phase,
                origin.observations,
            )
            self.assert_observed(value)
            return value
        except BaseException as error:
            self._invalidate()
            if isinstance(error, Exception):
                raise _denied() from None
            raise

    def assert_observed(self, value: CommittedTlsObservation) -> None:
        try:
            origin = self._memory()
            if type(value) is not CommittedTlsObservation or origin.observations.get(
                value
            ) != _freeze(value):
                raise _denied()
        except Exception:
            raise _denied() from None

    def _invalidate(self) -> None:
        origin = _ORIGINS.get(self)
        if origin is not None and origin.owner() is self:
            _ORIGINS.pop(self, None)
            origin.observations.clear()

    def close(self) -> None:
        """Consume memory associations; the caller owns the assembly/session lifecycle."""
        try:
            self._memory()
        finally:
            self._invalidate()
