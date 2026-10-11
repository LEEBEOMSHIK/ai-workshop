"""Issue source-bound inventory read capabilities, never submit helpers or prove data.

Original reads require issued history and application retirement. Secure reads
derive collector credentials from completed role issuance and protected TLS.
No caller phase flag, admin credential or final-auth DTO mints this authority.
"""

import base64
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID, uuid4

from pydantic import SecretStr

from ai_workshop.infrastructure.search.access_credentials import CredentialEnvelope
from ai_workshop.labs.rag.indexing.access_epoch_app_retirement import (
    AppRetirementObservation,
    RecordedAppRetirement,
)
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap import BootstrapCommands
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_binding import BootstrapBindingFactory
from ai_workshop.labs.rag.indexing.access_epoch_deployment import (
    PROJECT_ROOT,
    DeploymentCommands,
    ObservedDeployment,
)
from ai_workshop.labs.rag.indexing.access_epoch_final_auth_binding import (
    CompletedKeyReadPort,
    PreparedCredentialReadPort,
)
from ai_workshop.labs.rag.indexing.access_epoch_history_gate import (
    OriginalHistoryGate,
    VerifiedHistoricalControls,
)
from ai_workshop.labs.rag.indexing.access_epoch_keys import KEY_ROLES, KeyActionReadback
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.access_epoch_process import ReservationReadPort
from ai_workshop.labs.rag.indexing.access_epoch_repository import AccessEpochReadback
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_tls import AccessEpochTls
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
)


def _denied() -> ValueError:
    return ValueError("inventory_read_binding_unverified")


def _assert_none(check: Callable[..., object], *args: object) -> None:
    if check(*args) is not None:
        raise _denied()


async def _assert_async_none(check: Callable[..., Awaitable[object]], *args: object) -> None:
    if await check(*args) is not None:
        raise _denied()


def _permission_values(
    permissions: AccessEpochPermissions,
) -> tuple[str, tuple[tuple[str, str | None], ...]]:
    """Snapshot scalar values; frozen objects can be mutated by object.__setattr__."""
    if (
        type(permissions) is not AccessEpochPermissions
        or type(permissions.prefix) is not str
        or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,90}", permissions.prefix) is None
        or type(permissions.namespaces) is not tuple
        or not permissions.namespaces
    ):
        raise _denied()
    namespaces: list[tuple[str, str | None]] = []
    for namespace in permissions.namespaces:
        if (
            type(namespace) is not tuple
            or len(namespace) != 2
            or type(namespace[0]) is not UUID
            or namespace[1] is not None
            and type(namespace[1]) is not UUID
        ):
            raise _denied()
        namespaces.append(
            (str(namespace[0]), str(namespace[1]) if namespace[1] is not None else None)
        )
    if len(set(namespaces)) != len(namespaces):
        raise _denied()
    return permissions.prefix, tuple(namespaces)


@dataclass(frozen=True, slots=True, eq=False)
class InventoryReadBinding:
    phase: Literal["original", "bootstrap", "final"]
    nonce: UUID
    epoch_id: UUID
    execution_id: UUID
    parent_action_id: UUID
    container_id: str
    permissions: AccessEpochPermissions
    collector_secret: SecretStr | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class _OriginalSources:
    history: OriginalHistoryGate
    apps: RecordedAppRetirement


@dataclass(frozen=True, slots=True)
class _SecureSources:
    keys: CompletedKeyReadPort
    deployment: DeploymentCommands
    bootstrap_factory: BootstrapBindingFactory
    bootstrap: BootstrapCommands
    tls: AccessEpochTls
    store: PreparedCredentialReadPort


class InventoryReadBindingFactory:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        permissions: AccessEpochPermissions,
        sources: _OriginalSources | _SecureSources,
    ) -> None:
        self.epoch, self.repository, self.journal, self.permissions = (
            epoch,
            repository,
            journal,
            permissions,
        )
        self._sources = sources
        self._permissions_identity = permissions
        self._permissions_values = _permission_values(permissions)
        self._issued: dict[InventoryReadBinding, tuple[object, ...]] = {}
        self._owned()

    @classmethod
    def for_original(
        cls,
        epoch: PreparedAccessEpoch,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        permissions: AccessEpochPermissions,
        history: OriginalHistoryGate,
        apps: RecordedAppRetirement,
    ) -> "InventoryReadBindingFactory":
        try:
            return cls(epoch, repository, journal, permissions, _OriginalSources(history, apps))
        except Exception:
            raise _denied() from None

    @classmethod
    def for_secure(
        cls,
        repository: ReservationReadPort,
        keys: CompletedKeyReadPort,
        journal: ProtectedControlJournal,
        deployment: DeploymentCommands,
        bootstrap_factory: BootstrapBindingFactory,
        bootstrap: BootstrapCommands,
        tls: AccessEpochTls,
        store: PreparedCredentialReadPort,
    ) -> "InventoryReadBindingFactory":
        try:
            return cls(
                deployment.epoch,
                repository,
                journal,
                bootstrap.permissions,
                _SecureSources(keys, deployment, bootstrap_factory, bootstrap, tls, store),
            )
        except Exception:
            raise _denied() from None

    @property
    def bootstrap(self) -> BootstrapCommands:
        if type(self._sources) is not _SecureSources:
            raise _denied()
        return self._sources.bootstrap

    @property
    def tls(self) -> AccessEpochTls:
        if type(self._sources) is not _SecureSources:
            raise _denied()
        return self._sources.tls

    def _owned(self) -> None:
        self.journal._owned()
        if (
            self.journal.root != PROJECT_ROOT
            or type(self.epoch) is not PreparedAccessEpoch
            or type(self.permissions) is not AccessEpochPermissions
            or self.permissions is not self._permissions_identity
            or _permission_values(self.permissions) != self._permissions_values
            or self.epoch.binding.execution_id != str(self.journal.owner.execution_id)
            or self.journal.scope
            != hashlib.sha256(
                json.dumps([self.epoch.original.daemon_sha256, "ai-workshop"]).encode()
            ).hexdigest()
        ):
            raise _denied()
        source = self._sources
        if type(source) is _OriginalSources:
            if (
                source.history.epoch != self.epoch
                or source.apps.epoch != self.epoch
                or source.history.repository is not self.repository
                or source.apps.repository is not self.repository
                or source.history.journal is not self.journal
                or source.apps.journal is not self.journal
            ):
                raise _denied()
        elif type(source) is _SecureSources:
            if (
                source.deployment.epoch != self.epoch
                or source.keys.parent is not self.repository
                or source.bootstrap_factory.repository is not self.repository
                or source.bootstrap_factory.journal is not self.journal
                or source.bootstrap_factory.deployment is not source.deployment
                or source.bootstrap.permissions is not self.permissions
            ):
                raise _denied()
            _assert_none(source.bootstrap_factory.assert_issued, source.bootstrap)
        else:
            raise _denied()

    def _state(
        self, state: AccessEpochReadback, parent: ReservedCutoverAction, kind: CutoverActionKind
    ) -> None:
        self._owned()
        if type(parent) is not ReservedCutoverAction:
            raise _denied()
        self.journal._action_valid(parent)
        phase = {
            CutoverActionKind.STOP_OLD: "prepared",
            CutoverActionKind.STOP_BOOTSTRAP: "old_retired",
            CutoverActionKind.VERIFY_ACCESS: "secured_started",
        }[kind]
        count = CUTOVER_ORDER.index(kind) + 1
        if (
            type(state) is not AccessEpochReadback
            or state.prepared != self.epoch
            or state.executor_generation != self.journal.owner.executor_generation
            or state.phase != phase
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or parent.kind != kind
            or len(state.actions) != count
            or tuple(row.action.kind for row in state.actions) != CUTOVER_ORDER[:count]
            or state.actions[-1].action != parent
            or state.actions[-1].outcome not in {"pending", "unknown"}
        ):
            raise _denied()
        sequence = 0
        for index, row in enumerate(state.actions):
            self.journal._action_valid(row.action)
            if (
                type(row.event_sequence) is not int
                or row.action.sequence != sequence + 1
                or row.action.expected.preceding_sequence != sequence
                or row.outcome not in {"settled", "pending", "unknown"}
                or index < count - 1
                and row.outcome != "settled"
                or row.outcome == "settled"
                and (
                    type(row.manifest_json) is not str or row.event_sequence <= row.action.sequence
                )
                or row.outcome == "pending"
                and (row.manifest_json is not None or row.event_sequence != row.action.sequence)
                or row.outcome == "unknown"
                and row.event_sequence <= row.action.sequence
            ):
                raise _denied()
            sequence = row.event_sequence

    @staticmethod
    def _signature(value: InventoryReadBinding) -> tuple[object, ...]:
        return (
            value.phase,
            str(value.nonce),
            str(value.epoch_id),
            str(value.execution_id),
            str(value.parent_action_id),
            value.container_id,
            _permission_values(value.permissions),
            value.collector_secret.get_secret_value() if value.collector_secret else None,
        )

    def _issue(
        self,
        phase: Literal["original", "bootstrap", "final"],
        parent: ReservedCutoverAction,
        container: str,
        secret: SecretStr | None,
    ) -> InventoryReadBinding:
        self._owned()
        if type(container) is not str or re.fullmatch(r"[0-9a-f]{64}", container) is None:
            raise _denied()
        value = InventoryReadBinding(
            phase,
            uuid4(),
            UUID(self.epoch.binding.access_epoch_id),
            self.journal.owner.execution_id,
            parent.action_id,
            container,
            self.permissions,
            secret,
        )
        self._issued[value] = self._signature(value)
        return value

    async def create_original(
        self,
        parent: ReservedCutoverAction,
        retirement: AppRetirementObservation,
        history_ticket: VerifiedHistoricalControls,
    ) -> InventoryReadBinding:
        try:
            self._owned()
            source = self._sources
            if type(source) is not _OriginalSources:
                raise _denied()
            before = await self.repository.readback(self.epoch.binding.claim)
            self._state(before, parent, CutoverActionKind.STOP_OLD)
            _assert_none(source.apps.assert_issued, retirement)
            row = before.actions[0]
            if (
                type(retirement) is not AppRetirementObservation
                or retirement.action_id != row.action.action_id
                or retirement.execution_id != self.journal.owner.execution_id
                or retirement.executor_generation != self.journal.owner.executor_generation
                or retirement.manifest_json != row.manifest_json
            ):
                raise _denied()
            await _assert_async_none(source.history.assert_verified, history_ticket)
            self._owned()
            after = await self.repository.readback(self.epoch.binding.claim)
            self._state(after, parent, CutoverActionKind.STOP_OLD)
            _assert_none(source.apps.assert_issued, retirement)
            if before != after:
                raise _denied()
            return self._issue("original", parent, self.epoch.original.container_id, None)
        except Exception:
            raise _denied() from None

    async def create_bootstrap(
        self, parent: ReservedCutoverAction, bootstrap: ObservedDeployment
    ) -> InventoryReadBinding:
        return await self._create_secure(parent, bootstrap, "bootstrap")

    async def create_final(
        self, parent: ReservedCutoverAction, final: ObservedDeployment
    ) -> InventoryReadBinding:
        return await self._create_secure(parent, final, "final")

    async def _create_secure(
        self,
        parent: ReservedCutoverAction,
        observed: ObservedDeployment,
        phase: Literal["bootstrap", "final"],
    ) -> InventoryReadBinding:
        try:
            self._owned()
            source = self._sources
            if type(source) is not _SecureSources:
                raise _denied()
            kind = (
                CutoverActionKind.STOP_BOOTSTRAP
                if phase == "bootstrap"
                else CutoverActionKind.VERIFY_ACCESS
            )
            started_kind = (
                CutoverActionKind.START_BOOTSTRAP
                if phase == "bootstrap"
                else CutoverActionKind.START_SECURED
            )
            before = await self.repository.readback(self.epoch.binding.claim)
            self._state(before, parent, kind)
            _assert_none(source.deployment.assert_observed, observed)
            started = before.actions[CUTOVER_ORDER.index(started_kind)]
            if (
                type(observed) is not ObservedDeployment
                or observed.kind != started_kind
                or observed.execution_id != self.journal.owner.execution_id
                or observed.action_id != started.action.action_id
                or observed.manifest_json != started.manifest_json
            ):
                raise _denied()
            tls_row = before.actions[CUTOVER_ORDER.index(CutoverActionKind.PREPARE_TLS)]
            material = await source.tls.read_settled(tls_row.action)
            self._owned()
            _assert_none(source.tls.assert_issued, material)
            if (
                material.manifest_json != source.deployment.tls.manifest_json
                or material.manifest_json != tls_row.manifest_json
            ):
                raise _denied()
            key_parent = before.actions[CUTOVER_ORDER.index(CutoverActionKind.ISSUE_ROLE_KEY)]
            rows = await source.keys.read_completed(self.epoch, key_parent.action)
            self._owned()
            collector = self._credentials(source, rows, key_parent.action, key_parent.manifest_json)
            after_rows = await source.keys.read_completed(self.epoch, key_parent.action)
            self._owned()
            if (
                rows != after_rows
                or self._credentials(
                    source, after_rows, key_parent.action, key_parent.manifest_json
                )
                != collector
            ):
                raise _denied()
            after = await self.repository.readback(self.epoch.binding.claim)
            self._state(after, parent, kind)
            _assert_none(source.deployment.assert_observed, observed)
            if before != after:
                raise _denied()
            return self._issue(phase, parent, observed.container_id, collector)
        except Exception:
            raise _denied() from None

    def _credentials(
        self,
        source: _SecureSources,
        rows: tuple[KeyActionReadback, ...],
        parent: ReservedCutoverAction,
        manifest: str | None,
    ) -> SecretStr:
        if type(rows) is not tuple or any(
            type(row) is not KeyActionReadback or row.outcome != "settled" or row.result is None
            for row in rows
        ):
            raise _denied()
        latest = {row.action.role: row for row in rows if row.action.kind == "issue"}
        if set(latest) != set(KEY_ROLES):
            raise _denied()
        keys, issuances, descriptors = {}, {}, {}
        collector = None
        for role in KEY_ROLES:
            row = latest[role]
            result = row.result
            descriptor = hashlib.sha256(
                canonical_json(source.bootstrap.permissions_descriptor(role)).encode()
            ).hexdigest()
            if (
                result is None
                or result.result != "issued"
                or result.role != role
                or row.action.parent_action_id != parent.action_id
                or row.action.execution_id != self.journal.owner.execution_id
                or row.action.executor_generation != self.journal.owner.executor_generation
                or result.issuance_id != row.action.issuance_id
                or row.action.permissions_sha256 != descriptor
                or result.permissions_sha256 != descriptor
            ):
                raise _denied()
            envelope = source.store.read_prepared(
                UUID(self.epoch.binding.access_epoch_id),
                self.epoch.binding.ordinal,
                role,
                result.key_id,
            )
            self._owned()
            if (
                type(envelope) is not CredentialEnvelope
                or envelope.epoch_id != UUID(self.epoch.binding.access_epoch_id)
                or type(envelope.ordinal) is not int
                or envelope.ordinal != self.epoch.binding.ordinal
                or envelope.role != role
                or envelope.key_id != result.key_id
                or type(envelope.secret) is not SecretStr
            ):
                raise _denied()
            encoded = envelope.secret.get_secret_value()
            if not 1 <= len(encoded) <= 1024:
                raise _denied()
            decoded = base64.b64decode(encoded, validate=True)
            key_id, separator, secret = decoded.partition(b":")
            if (
                base64.b64encode(decoded).decode("ascii") != encoded
                or key_id != result.key_id.encode("ascii")
                or separator != b":"
                or re.fullmatch(rb"[A-Za-z0-9_-]{1,256}", secret) is None
            ):
                raise _denied()
            keys[role], issuances[role], descriptors[role] = (
                result.key_id,
                str(row.action.issuance_id),
                descriptor,
            )
            if role == "collector":
                collector = envelope.secret
        if (
            len(set(keys.values())) != len(KEY_ROLES)
            or canonical_json(
                {
                    "schema_version": 1,
                    "execution_id": str(parent.execution_id),
                    "parent_action_id": str(parent.action_id),
                    "keys": keys,
                    "issuances": issuances,
                    "permissions": descriptors,
                }
            )
            != manifest
            or collector is None
        ):
            raise _denied()
        return collector

    def assert_issued(self, binding: InventoryReadBinding) -> None:
        try:
            self._owned()
            if (
                type(binding) is not InventoryReadBinding
                or binding.permissions is not self._permissions_identity
                or self._issued.get(binding) != self._signature(binding)
            ):
                raise _denied()
        except Exception:
            raise _denied() from None
