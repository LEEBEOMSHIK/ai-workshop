"""Committed read preconditions, not fresh server observations or readiness.

No all-settled authority is fabricated from an absent pending-verifier issuer.
The fixed native/HTTPS observation assembly remains a separate prerequisite.
"""

import base64
import json
import re
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4
from weakref import ReferenceType, WeakKeyDictionary, WeakSet, ref

from pydantic import BaseModel, SecretStr

from ai_workshop.config import Settings
from ai_workshop.infrastructure.local.credential_store_windows import WindowsCredentialStore
from ai_workshop.infrastructure.search.access_credentials import SecuredStoreIdentity
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from ai_workshop.labs.rag.indexing.access_epoch_evidence_packets import _stored_control_manifest
from ai_workshop.labs.rag.indexing.access_epoch_keys import (
    KEY_ROLES,
    KeyActionReadback,
    SqlAlchemyEpochKeyRepository,
)
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_repository import (
    AccessEpochReadback,
    SqlAlchemyAccessEpochRepository,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    VerifiedAccessEpoch,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_repository import (
    SqlAlchemyAliasRecoveryRepository,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import FrozenAliasClaim
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding

if TYPE_CHECKING:
    from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
        NativeReadDependencies,
        NativeSecuredReadAssembly,
    )

type CommittedReadPhase = Literal["verified", "receipted"]


def _denied() -> ValueError:
    return ValueError("secured_read_binding_denied")


def _freeze(value: object) -> object:
    """Private primitive copy; nested UUID/secret/DTO mutation stays detectable."""
    if isinstance(value, SecretStr):
        return (type(value), value.get_secret_value())
    if type(value) is UUID:
        return ("uuid", value.int)
    if type(value) is datetime:
        return ("datetime", value.isoformat())
    if isinstance(value, Path):
        return (type(value), str(value))
    if isinstance(value, BaseModel):
        return (type(value), _freeze(value.model_dump()))
    if is_dataclass(value) and not isinstance(value, type):
        return (
            type(value),
            tuple((f.name, _freeze(getattr(value, f.name))) for f in fields(value)),
        )
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise _denied()
        return (dict, tuple(sorted((key, _freeze(item)) for key, item in value.items())))
    if isinstance(value, tuple | list):
        if type(value) not in {tuple, list}:
            raise _denied()
        return (type(value), tuple(_freeze(item) for item in value))
    if isinstance(value, StrEnum):
        return (type(value), value.value)
    if type(value) in {str, int, float, bool, type(None)}:
        return (type(value), value)
    raise _denied()


@dataclass(frozen=True, slots=True, eq=False)
class SecuredReadBinding:
    """Only checked persisted read prerequisites; no live sample is asserted."""

    nonce: UUID
    epoch_id: UUID
    execution_id: UUID
    ordinal: int
    phase: CommittedReadPhase


@dataclass(frozen=True, slots=True, repr=False)
class _Sample:
    evidence: VerifiedAccessEpoch
    state: AccessEpochReadback
    material: object


@dataclass(frozen=True, slots=True, repr=False)
class _Issued:
    owner: object
    binding: SecuredReadBinding
    binding_seal: object
    claim: FrozenAliasClaim
    claim_seal: object
    evidence_seal: object
    state_seal: object
    phase: CommittedReadPhase
    material_seal: object


@dataclass(frozen=True, slots=True, repr=False)
class _Association:
    owner: ReferenceType["NativeSecuredReadSource"]
    assembly: "NativeSecuredReadAssembly"
    dependencies: "NativeReadDependencies"


_ASSOCIATIONS: WeakKeyDictionary["NativeSecuredReadSource", _Association] = WeakKeyDictionary()
_NATIVE_SOURCES: WeakSet["NativeSecuredReadSource"] = WeakSet()


class NativeSecuredReadSource:
    """The component constructor binds memory values, without source authority.

    The exact issued-dependency constructor additionally checks the fixed native
    assembly; its queries use the guarded READ ONLY producer. Legacy component
    reads retain active repository locks/upsert and make no SELECT-only claim.
    Neither component establishes fresh server observations or readiness.
    """

    def __init__(
        self,
        settings: Settings,
        repository: SqlAlchemyAccessEpochRepository,
        store: WindowsCredentialStore,
        keys: SqlAlchemyEpochKeyRepository,
    ) -> None:
        self._settings, self._repository, self._store, self._keys = (
            settings,
            repository,
            store,
            keys,
        )
        self._objects = settings, repository, store, keys
        self._ports = store.protection, store.files
        self._root_text = str(PROJECT_ROOT)
        self._issued: dict[SecuredReadBinding, _Issued] = {}
        try:
            self._input_seal = self._signature()
            self._guard()
        except Exception:
            raise _denied() from None

    def _signature(self) -> object:
        r, s, k = self._repository, self._store, self._keys
        return (
            id(self),
            _freeze(self._settings),
            id(r),
            id(r.sessions),
            id(r.recovery),
            id(r.recovery.sessions),
            _freeze(r.binding),
            _freeze(r.recovery.binding),
            r.recovery.index_prefix,
            id(s),
            _freeze(s.root),
            id(s.protection),
            id(s.files),
            id(k),
            id(k.parent),
            str(PROJECT_ROOT),
        )

    @classmethod
    def _from_committed_dependencies(
        cls, assembly: "NativeSecuredReadAssembly", dependencies: "NativeReadDependencies"
    ) -> "NativeSecuredReadSource":
        """Source-private exact issued graph; does not assert fresh observations."""
        from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
            NativeReadDependencies,
            NativeSecuredReadAssembly,
        )

        if (
            cls is not NativeSecuredReadSource
            or type(assembly) is not NativeSecuredReadAssembly
            or type(dependencies) is not NativeReadDependencies
            or dependencies.phase != "committed"
        ):
            raise _denied()
        NativeSecuredReadAssembly.assert_issued(assembly, dependencies)
        source = cls(
            dependencies.settings,
            dependencies.repository,
            dependencies.store,
            dependencies.keys,
        )
        _ASSOCIATIONS[source] = _Association(ref(source), assembly, dependencies)
        _NATIVE_SOURCES.add(source)
        try:
            source._assert_committed_dependencies()
        except BaseException:
            _ASSOCIATIONS.pop(source, None)
            source._issued.clear()
            raise
        return source

    def _assert_committed_dependencies(self) -> None:
        """A component constructor or copied source cannot assert this origin."""
        if type(self) is not NativeSecuredReadSource or self not in _ASSOCIATIONS:
            raise _denied()
        self._guard()

    def _guard(self) -> None:
        association = _ASSOCIATIONS.get(self)
        if self in _NATIVE_SOURCES and association is None:
            raise _denied()
        if association is not None:
            from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
                NativeSecuredReadAssembly,
            )

            dependencies = association.dependencies
            if association.owner() is not self or self not in _NATIVE_SOURCES:
                raise _denied()
            NativeSecuredReadAssembly.assert_issued(association.assembly, dependencies)
            if dependencies.phase != "committed" or any(
                actual is not expected
                for actual, expected in zip(
                    self._objects,
                    (
                        dependencies.settings,
                        dependencies.repository,
                        dependencies.store,
                        dependencies.keys,
                    ),
                    strict=True,
                )
            ):
                raise _denied()
        settings, r, s, k = self._settings, self._repository, self._store, self._keys
        if (
            any(
                actual is not retained
                for actual, retained in zip((settings, r, s, k), self._objects, strict=True)
            )
            or type(settings) is not Settings
            or settings.environment != "local"
            or type(r) is not SqlAlchemyAccessEpochRepository
            or type(r.recovery) is not SqlAlchemyAliasRecoveryRepository
            or type(r.binding) is not IndexBinding
            or type(s) is not WindowsCredentialStore
            or type(k) is not SqlAlchemyEpochKeyRepository
            or k.parent is not r
            or r.recovery.sessions is not r.sessions
            or r.recovery.binding != r.binding
            or (r.binding.store_id, r.binding.cluster_uuid)
            != (settings.rag_index_store_id, settings.rag_index_cluster_uuid)
            or r.recovery.index_prefix != settings.elasticsearch_index_prefix
            or str(s.root) != self._root_text
            or str(PROJECT_ROOT) != self._root_text
            or s.protection is not self._ports[0]
            or s.files is not self._ports[1]
            or self._signature() != self._input_seal
        ):
            raise _denied()

    def _claim_guard(self, claim: FrozenAliasClaim, seal: object) -> None:
        self._guard()
        if (
            type(claim) is not FrozenAliasClaim
            or type(claim.revision) is not int
            or claim.revision <= 0
            or any(
                type(value) is not UUID or value.int == 0
                for value in (claim.request_id, claim.actor_id)
            )
            or _freeze(claim) != seal
        ):
            raise _denied()

    @staticmethod
    def _state_seal(state: AccessEpochReadback) -> object:
        return _freeze(
            (state.prepared, state.actions, state.old_server_stopped_at, state.executor_generation)
        )

    @staticmethod
    def _phase(state: AccessEpochReadback) -> CommittedReadPhase:
        if state.gate_state != "frozen":
            raise _denied()
        if state.phase == "verified" and state.operation_state == "open" and state.receipt is None:
            return "verified"
        if state.phase == "receipted" and state.operation_state == "closed" and state.receipt:
            return "receipted"
        raise _denied()

    def _validate_state(self, state: AccessEpochReadback, evidence: VerifiedAccessEpoch) -> None:
        phase = self._phase(state)
        if state.prepared is None or state.prepared.binding != evidence.binding:
            raise _denied()
        if (
            _stored_control_manifest(state.prepared, state)
            != dict(evidence.manifests)["control_settlement"]
        ):
            raise _denied()
        if len(state.actions) != len(CUTOVER_ORDER):
            raise _denied()
        preceding = 0
        seen: set[UUID] = set()
        for kind, row in zip(CUTOVER_ORDER, state.actions, strict=True):
            action = row.action
            if (
                action.kind != kind
                or type(action.sequence) is not int
                or action.sequence != preceding + 1
                or action.execution_id != UUID(evidence.binding.execution_id)
                or action.executor_generation != state.executor_generation
                or action.expected.preceding_sequence != preceding
                or action.action_id in seen
                or row.outcome != "settled"
                or row.manifest_json is None
                or type(row.event_sequence) is not int
                or row.event_sequence <= action.sequence
            ):
                raise _denied()
            seen.add(action.action_id)
            preceding = row.event_sequence
        if phase == "receipted":
            if state.receipt is None or state.receipt.proof is None:
                raise _denied()
            if canonical_json(state.receipt.proof.facts()) != evidence.proof_facts_json:
                raise _denied()

    async def _sample(self, claim: FrozenAliasClaim, seal: object) -> _Sample:
        if self in _ASSOCIATIONS:
            return await self._sample_committed(claim, seal)
        self._claim_guard(claim, seal)
        evidence = await self._repository.verified(claim)
        self._claim_guard(claim, seal)
        state = await self._repository.readback(claim)
        self._claim_guard(claim, seal)
        self._validate_state(state, evidence)
        floor = await self._repository.floor(self._repository.binding)
        self._claim_guard(claim, seal)
        expected = self._repository.floor_from_verified(evidence)
        if floor != expected:
            raise _denied()
        anchor = SecuredStoreIdentity(
            expected.store_id,
            expected.cluster_uuid,
            expected.ordinal,
            UUID(expected.access_epoch_id),
            expected.container_id,
            expected.stable_node_id,
            expected.route_sha256,
            expected.auth_sha256,
            expected.config_sha256,
            expected.ca_sha256,
        )
        if self._store.read_floor_anchor() != anchor:
            raise _denied()
        self._claim_guard(claim, seal)
        parent = next(x for x in state.actions if x.action.kind == CutoverActionKind.ISSUE_ROLE_KEY)
        assert state.prepared is not None
        ledger = await self._keys.read_completed(state.prepared, parent.action)
        self._claim_guard(claim, seal)
        return self._sample_material(claim, seal, evidence, state, anchor, ledger)

    def _sample_material(
        self,
        claim: FrozenAliasClaim,
        seal: object,
        evidence: VerifiedAccessEpoch,
        state: AccessEpochReadback,
        anchor: SecuredStoreIdentity,
        ledger: tuple[KeyActionReadback, ...],
    ) -> _Sample:
        self._claim_guard(claim, seal)
        parent = next(x for x in state.actions if x.action.kind == CutoverActionKind.ISSUE_ROLE_KEY)
        group = json.loads(parent.manifest_json or "null")
        deployment = json.loads(dict(evidence.manifests)["credential_deployment"])
        expected_deployment = group | {
            "epoch_id": evidence.binding.access_epoch_id,
            "ordinal": evidence.binding.ordinal,
        }
        if deployment != expected_deployment:
            raise _denied()
        latest = {x.action.role: x for x in ledger if x.action.kind == "issue"}
        if set(latest) != set(KEY_ROLES):
            raise _denied()
        material: list[object] = []
        for role in KEY_ROLES:
            row = latest[role]
            if row.outcome != "settled" or row.result is None or row.result.result != "issued":
                raise _denied()
            envelope = self._store.load(anchor.epoch_id, role)
            self._claim_guard(claim, seal)
            if (envelope.epoch_id, envelope.ordinal, envelope.role, envelope.key_id) != (
                anchor.epoch_id,
                anchor.ordinal,
                role,
                row.result.key_id,
            ):
                raise _denied()
            encoded = envelope.secret.get_secret_value()
            decoded = base64.b64decode(encoded, validate=True)
            key, separator, secret = decoded.partition(b":")
            if (
                len(encoded) > 1024
                or base64.b64encode(decoded).decode() != encoded
                or key != row.result.key_id.encode("ascii")
                or separator != b":"
                or re.fullmatch(rb"[A-Za-z0-9_-]{1,256}", secret) is None
            ):
                raise _denied()
            material.append(_freeze((row, envelope)))
        if self._store.read_floor_anchor() != anchor:
            raise _denied()
        self._claim_guard(claim, seal)
        return _Sample(evidence, state, (_freeze(anchor), tuple(material)))

    async def _sample_committed(
        self, claim: FrozenAliasClaim, seal: object, binding: SecuredReadBinding | None = None
    ) -> _Sample:
        """Only issued source-owned dependencies use the nonmutating producer.

        The existing unassociated component path is intentionally unchanged;
        it supplies no fixed-native source authority or READ ONLY guarantee.
        """
        from ai_workshop.labs.rag.indexing.access_epoch_committed_snapshot import (
            _read_committed_from_bound_source,
            _read_committed_from_dependencies,
        )

        self._assert_committed_dependencies()
        self._claim_guard(claim, seal)
        association = _ASSOCIATIONS[self]
        if binding is None:
            snapshot = await _read_committed_from_dependencies(
                association.assembly, association.dependencies, claim
            )
        else:
            snapshot = await _read_committed_from_bound_source(self, binding)
            self._entry(binding)
        self._assert_committed_dependencies()
        self._claim_guard(claim, seal)
        evidence, state = snapshot.evidence, snapshot.state
        self._validate_state(state, evidence)
        expected = self._repository.floor_from_verified(evidence)
        if snapshot.floor != expected:
            raise _denied()
        anchor = SecuredStoreIdentity(
            expected.store_id,
            expected.cluster_uuid,
            expected.ordinal,
            UUID(expected.access_epoch_id),
            expected.container_id,
            expected.stable_node_id,
            expected.route_sha256,
            expected.auth_sha256,
            expected.config_sha256,
            expected.ca_sha256,
        )
        if self._store.read_floor_anchor() != anchor:
            raise _denied()
        self._assert_committed_dependencies()
        return self._sample_material(claim, seal, evidence, state, anchor, snapshot.completed_keys)

    async def _bracket(self, claim: FrozenAliasClaim, seal: object) -> _Sample:
        first = await self._sample(claim, seal)
        self._claim_guard(claim, seal)
        second = await self._sample(claim, seal)
        self._claim_guard(claim, seal)
        if (
            _freeze(first.evidence) != _freeze(second.evidence)
            or self._state_seal(first.state) != self._state_seal(second.state)
            or first.material != second.material
            or (
                self._phase(first.state) == "receipted" and self._phase(second.state) != "receipted"
            )
        ):
            raise _denied()
        return second

    async def bind_verified(self, claim: FrozenAliasClaim) -> SecuredReadBinding:
        try:
            claim_seal = _freeze(claim)
            sample = await self._bracket(claim, claim_seal)
            self._claim_guard(claim, claim_seal)
            binding = sample.evidence.binding
            cap = SecuredReadBinding(
                uuid4(),
                UUID(binding.access_epoch_id),
                UUID(binding.execution_id),
                binding.ordinal,
                self._phase(sample.state),
            )
            self._issued[cap] = _Issued(
                self,
                cap,
                _freeze(cap),
                claim,
                claim_seal,
                _freeze(sample.evidence),
                self._state_seal(sample.state),
                cap.phase,
                sample.material,
            )
            return cap
        except Exception:
            raise _denied() from None

    def _entry(self, cap: SecuredReadBinding) -> _Issued:
        self._guard()
        if (
            type(cap) is not SecuredReadBinding
            or any(
                type(value) is not UUID or value.int == 0
                for value in (cap.nonce, cap.epoch_id, cap.execution_id)
            )
            or type(cap.ordinal) is not int
            or cap.ordinal <= 0
            or type(cap.phase) is not str
            or cap.phase not in {"verified", "receipted"}
        ):
            raise _denied()
        entry = self._issued.get(cap)
        if (
            type(cap) is not SecuredReadBinding
            or entry is None
            or entry.owner is not self
            or entry.binding is not cap
            or entry.binding_seal != _freeze(cap)
        ):
            raise _denied()
        self._claim_guard(entry.claim, entry.claim_seal)
        return entry

    def assert_bound(self, binding: SecuredReadBinding) -> None:
        try:
            self._entry(binding)
        except Exception:
            raise _denied() from None

    async def revalidate(self, binding: SecuredReadBinding) -> None:
        try:
            entry = self._entry(binding)
            sample = await self._bracket(entry.claim, entry.claim_seal)
            self._entry(binding)
            if (
                _freeze(sample.evidence) != entry.evidence_seal
                or self._state_seal(sample.state) != entry.state_seal
                or sample.material != entry.material_seal
                or (entry.phase == "receipted" and self._phase(sample.state) != "receipted")
            ):
                raise _denied()
        except Exception:
            raise _denied() from None

    async def _private_read_bound_sample(self, binding: SecuredReadBinding) -> _Sample:
        """Fresh ordinary data for the exact native source and retained binding.

        This private read never adopts component dependencies or mints authority.
        Each SQL await checks the retained source/binding, and two full samples
        must match the original committed evidence and protected credentials.
        """
        try:
            self._assert_committed_dependencies()
            entry = self._entry(binding)
            first = await self._sample_committed(entry.claim, entry.claim_seal, binding)
            self._entry(binding)
            second = await self._sample_committed(entry.claim, entry.claim_seal, binding)
            self._entry(binding)
            for sample in (first, second):
                if (
                    _freeze(sample.evidence) != entry.evidence_seal
                    or self._state_seal(sample.state) != entry.state_seal
                    or sample.material != entry.material_seal
                    or (entry.phase == "receipted" and self._phase(sample.state) != "receipted")
                ):
                    raise _denied()
            if self._phase(first.state) == "receipted" and self._phase(second.state) != "receipted":
                raise _denied()
            self._assert_committed_dependencies()
            self._entry(binding)
            return second
        except Exception:
            raise _denied() from None
