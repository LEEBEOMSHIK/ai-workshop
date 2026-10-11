"""Fixed native cutover assembly; no CLI admission or invented final evidence.

The full verifier is a mandatory actual production class, loaded from one fixed
module before any original application/control action. Issuer capabilities are
retained for this live context only; this is not crash hydration or takeover.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from pydantic import SecretStr

from ai_workshop.config import Settings
from ai_workshop.infrastructure.local.control_process_windows import WindowsControlProcess
from ai_workshop.infrastructure.local.credential_store_windows import WindowsCredentialStore
from ai_workshop.infrastructure.local.cutover_control_windows import (
    HeldControlLock,
    WindowsControlLock,
)
from ai_workshop.infrastructure.local.process_retirement_windows import WindowsProcessRetirement
from ai_workshop.infrastructure.local.tls_bundle import ProjectTlsBundles
from ai_workshop.infrastructure.local.windows_private_state import NativeWindowsPrivateState
from ai_workshop.infrastructure.search.access_credentials import ServiceRole
from ai_workshop.labs.rag.indexing.access_epoch_admin_process import (
    BootstrapAdministrator,
    RecordedBootstrapAdministrator,
)
from ai_workshop.labs.rag.indexing.access_epoch_app_retirement import (
    AppRetirementObservation,
    FreshAppRetirementTicket,
    RecordedAppRetirement,
)
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap import BootstrapCommands
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_audits import (
    ObservedBootstrapSecurity,
    RecordedBootstrapAudits,
)
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_binding import BootstrapBindingFactory
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_retirement import (
    BootstrapDaemonSettlement,
    FixedBootstrapDockerReads,
    RecordedBootstrapRetirement,
)
from ai_workshop.labs.rag.indexing.access_epoch_deployment import (
    PROJECT_ROOT,
    DeploymentCommands,
    ObservedDeployment,
    PreservedDeployment,
    RetiredPredecessor,
)
from ai_workshop.labs.rag.indexing.access_epoch_deployment_process import (
    FixedDeploymentInventory,
    RecordedDeploymentControlProcess,
)
from ai_workshop.labs.rag.indexing.access_epoch_deployment_settlement import (
    DeploymentDaemonSettlement,
    FixedDeploymentDaemonReads,
)
from ai_workshop.labs.rag.indexing.access_epoch_final_auth import FinalAuthObservation
from ai_workshop.labs.rag.indexing.access_epoch_final_auth_binding import (
    CompletedKeyReadPort,
    FinalAuthBindingFactory,
    PreparedCredentialReadPort,
)
from ai_workshop.labs.rag.indexing.access_epoch_final_auth_process import (
    FreshFinalAuthTicket,
    RecordedFinalAuthentication,
)
from ai_workshop.labs.rag.indexing.access_epoch_history import OriginalHistoricalReceiptReader
from ai_workshop.labs.rag.indexing.access_epoch_history_gate import (
    OriginalHistoryGate,
    VerifiedHistoricalControls,
)
from ai_workshop.labs.rag.indexing.access_epoch_inventory_binding import InventoryReadBindingFactory
from ai_workshop.labs.rag.indexing.access_epoch_inventory_collection import (
    CapturedIndexInventory,
    RecordedInventoryCollector,
)
from ai_workshop.labs.rag.indexing.access_epoch_inventory_process import RecordedInventoryReads
from ai_workshop.labs.rag.indexing.access_epoch_key_process import RecordedBootstrapKeyCommands
from ai_workshop.labs.rag.indexing.access_epoch_keys import SqlAlchemyEpochKeyRepository
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER, ControlOwnership
from ai_workshop.labs.rag.indexing.access_epoch_namespace_source import (
    OriginalNamespacePermissions,
    OriginalNamespaceSource,
    OriginalUnmanagedPhysical,
)
from ai_workshop.labs.rag.indexing.access_epoch_native import (
    OriginalAccessEpochPreflight,
    OriginalDeploymentObservation,
)
from ai_workshop.labs.rag.indexing.access_epoch_original_apps import (
    OriginalApplicationAllowlistIssuer,
    OriginalApplicationSourceReader,
)
from ai_workshop.labs.rag.indexing.access_epoch_original_security import (
    ObservedOriginalSecurityAbsent,
    OriginalSecurityAbsenceReader,
)
from ai_workshop.labs.rag.indexing.access_epoch_process import RecordedOriginalControlProcess
from ai_workshop.labs.rag.indexing.access_epoch_repository import (
    AccessEpochReadback,
    SqlAlchemyAccessEpochRepository,
)
from ai_workshop.labs.rag.indexing.access_epoch_role_keys import BootstrapRoleKeyGroup
from ai_workshop.labs.rag.indexing.access_epoch_security_descriptor_source import (
    ObservedSecurityDescriptor,
    OriginalSecurityDescriptorSource,
)
from ai_workshop.labs.rag.indexing.access_epoch_settlement import OriginalDaemonSettlement
from ai_workshop.labs.rag.indexing.access_epoch_submission import (
    FreshSubmissionTicket,
    ProtectedControlJournal,
)
from ai_workshop.labs.rag.indexing.access_epoch_tls import AccessEpochTls, PreparedTlsAssets
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    ControlSettlement,
    CutoverActionKind,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import FrozenAliasClaim

if TYPE_CHECKING:
    from ai_workshop.labs.rag.indexing.access_epoch_route_commands import NativeRouteCommands
    from ai_workshop.labs.rag.indexing.access_epoch_security_inventory_native import (
        MainSecurityCompletion,
        NativeSecurityInventory,
    )


@dataclass(frozen=True, slots=True, eq=False)
class _PreepochSources:
    native: WindowsControlProcess
    source: OriginalSecurityDescriptorSource
    descriptor: ObservedSecurityDescriptor
    commands: NativeRouteCommands


_FINAL_MODULE = "ai_workshop.labs.rag.indexing.access_epoch_verification_native"


def _denied() -> ValueError:
    return ValueError("native_control_denied")


def _unsupported() -> ValueError:
    return ValueError("native_control_unsupported")


def _none(check: Callable[..., object], *args: object) -> None:
    if check(*args) is not None:
        raise _denied()


def _freeze(value: object) -> object:
    """Private immutable signature; never published or hashed into manifests."""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if isinstance(value, UUID):
        if type(value) is not UUID:
            raise _denied()
        return ("uuid", str(value))
    if isinstance(value, datetime):
        if type(value) is not datetime:
            raise _denied()
        return ("datetime", value.isoformat())
    if isinstance(value, Path):
        return ("path", str(value))
    if is_dataclass(value) and not isinstance(value, type):
        return (
            type(value),
            tuple((f.name, _freeze(getattr(value, f.name))) for f in fields(value)),
        )
    if isinstance(value, (list, tuple)):
        return (type(value), tuple(_freeze(x) for x in value))
    if isinstance(value, dict):
        return (dict, tuple(sorted((k, _freeze(v)) for k, v in value.items())))
    if value is None or type(value) in {str, int, bool, bytes}:
        return (type(value), value)
    return (type(value), id(value))


class NativeControlContext:
    """Retained actual sources and issued observations; no public setters."""

    def __init__(
        self,
        settings: Settings,
        repository: SqlAlchemyAccessEpochRepository,
        claim: FrozenAliasClaim,
        original: OriginalAccessEpochPreflight,
        observation: OriginalDeploymentObservation,
        namespace_source: OriginalNamespaceSource,
        namespace: OriginalNamespacePermissions,
        security_source: OriginalSecurityAbsenceReader,
        absence: ObservedOriginalSecurityAbsent,
    ) -> None:
        self._settings, self._repository, self._claim = settings, repository, claim
        self._original, self._observation = original, observation
        self._namespace_source, self._namespace = namespace_source, namespace
        self._security_source, self._absence = security_source, absence
        self._preflight_started = False
        self._preflight_failed = False
        self._preflight_failed_signature = _freeze(False)
        self._preflight_sources: _PreepochSources | None = None
        self._preflight_signature: object = None
        self._security_inventory: NativeSecurityInventory | None = None
        self._security_inventory_signature: object = (type(None), id(None))
        self._source_signature = self._signature()
        self._epoch: PreparedAccessEpoch | None = None
        self._owner: HeldControlLock | None = None
        self._lock: WindowsControlLock | None = None
        self._journal: ProtectedControlJournal | None = None
        self._native: WindowsControlProcess | None = None
        self._store: WindowsCredentialStore | None = None
        self._tls: AccessEpochTls | None = None
        self._deployment: DeploymentCommands | None = None
        self._apps: RecordedAppRetirement | None = None
        self._history: OriginalHistoryGate | None = None
        self._history_ticket: VerifiedHistoricalControls | None = None
        self._bootstrap_factory: BootstrapBindingFactory | None = None
        self._bootstrap_commands: BootstrapCommands | None = None
        self._administrator: RecordedBootstrapAdministrator | None = None
        self._audits: RecordedBootstrapAudits | None = None
        self._keys: SqlAlchemyEpochKeyRepository | None = None
        self._final_auth_factory: FinalAuthBindingFactory | None = None
        self._final_authentication: RecordedFinalAuthentication | None = None
        self._collectors: dict[str, RecordedInventoryCollector] = {}
        self._caps: dict[str, object] = {}
        self._cap_signatures: dict[str, object] = {}
        self._runtime_signature: object = None
        self._verification: Any = None
        self.assert_sources()

    def _signature(self) -> object:
        return (
            _freeze(self._preflight_started),
            id(self._settings),
            id(self._repository),
            _freeze(self._claim),
            id(self._original),
            id(self._observation),
            _freeze(self._observation),
            id(self._namespace_source),
            id(self._namespace),
            _freeze(self._namespace),
            id(self._security_source),
            id(self._absence),
            _freeze(self._absence),
        )

    def assert_sources(self) -> None:
        try:
            if (
                _freeze(self._preflight_failed) != self._preflight_failed_signature
                or type(self._settings) is not Settings
                or type(self._repository) is not SqlAlchemyAccessEpochRepository
                or type(self._claim) is not FrozenAliasClaim
                or type(self._original) is not OriginalAccessEpochPreflight
                or type(self._observation) is not OriginalDeploymentObservation
                or type(self._namespace_source) is not OriginalNamespaceSource
                or type(self._namespace) is not OriginalNamespacePermissions
                or type(self._security_source) is not OriginalSecurityAbsenceReader
                or type(self._absence) is not ObservedOriginalSecurityAbsent
                or self._original.settings is not self._settings
                or self._namespace_source.settings is not self._settings
                or self._namespace_source.original is not self._original
                or self._namespace_source.observation is not self._observation
                or self._security_source.identity is not self._original
                or self._observation.snapshot_sha256 != self._claim.snapshot.sha256
                or self._namespace.snapshot_sha256 != self._claim.snapshot.sha256
                or self._namespace.original_deployment_sha256
                != self._observation.identity.deployment_sha256
                or self._signature() != self._source_signature
            ):
                raise _denied()
            _none(self._original.assert_observed, self._observation)
            _none(self._namespace_source.assert_issued, self._namespace)
            _none(self._security_source.assert_original, self._absence, self._observation.identity)
            self._assert_preflight_binding()
        except Exception:
            raise _denied() from None

    def _assert_preflight_binding(self) -> None:
        value = self._preflight_sources
        if value is None:
            if self._preflight_signature is not None:
                raise _denied()
            return
        from ai_workshop.labs.rag.indexing.access_epoch_route_commands import NativeRouteCommands

        if (
            self._preflight_started is not True
            or type(value) is not _PreepochSources
            or self._preflight_signature != self._preflight_value_signature(value)
            or type(value.native) is not WindowsControlProcess
            or type(value.source) is not OriginalSecurityDescriptorSource
            or type(value.descriptor) is not ObservedSecurityDescriptor
            or type(value.commands) is not NativeRouteCommands
            or value.source.settings is not self._settings
            or value.source.original is not self._original
            or value.source.observation is not self._observation
            or value.source.process is not value.native
            or value.descriptor.snapshot_sha256 != self._claim.snapshot.sha256
            or value.descriptor.original_deployment_sha256
            != self._observation.identity.deployment_sha256
            or value.commands.context is not self
        ):
            raise _denied()
        _none(value.source.assert_issued, value.descriptor)

    @staticmethod
    def _preflight_value_signature(value: _PreepochSources) -> object:
        return (
            id(value),
            id(value.native),
            id(value.source),
            id(value.descriptor),
            _freeze(value.descriptor),
            id(value.commands),
        )

    async def prepare_sources(self) -> None:
        """Own actual readonly producers before any epoch/control admission."""
        self.assert_sources()
        if self._preflight_started or self._epoch is not None:
            raise _denied()
        self._preflight_started = True
        self._source_signature = self._signature()
        try:
            native = WindowsControlProcess()
            source = OriginalSecurityDescriptorSource(
                self._settings, self._original, self._observation, native
            )
            descriptor = await source.observe(self._claim.snapshot)
            self.assert_sources()
            _none(source.assert_issued, descriptor)
            from ai_workshop.labs.rag.indexing.access_epoch_route_commands import (
                NativeRouteCommands,
            )

            commands = NativeRouteCommands(self)
            await commands.observe_support()
            self.assert_sources()
            _none(source.assert_issued, descriptor)
            _none(commands.assert_supported)
            value = _PreepochSources(native, source, descriptor, commands)
            self._preflight_sources = value
            self._preflight_signature = self._preflight_value_signature(value)
            self.assert_preflight_sources()
            from ai_workshop.labs.rag.indexing.access_epoch_security_inventory_native import (
                NativeSecurityInventory,
            )

            issuer = NativeSecurityInventory(self)
            self._security_inventory = issuer
            self._security_inventory_signature = (type(issuer), id(issuer))
            if self.security_inventory_issuer is not issuer:
                raise _denied()
        except BaseException as exc:
            self._preflight_failed = True
            self._preflight_failed_signature = _freeze(True)
            self._preflight_sources = None
            self._preflight_signature = None
            self._security_inventory = None
            self._security_inventory_signature = (type(None), id(None))
            if isinstance(exc, Exception):
                raise _denied() from None
            raise

    def assert_preflight_sources(self) -> None:
        self.assert_sources()
        if self._preflight_failed or self._preflight_sources is None:
            raise _denied()
        _none(self._preflight_sources.commands.assert_supported)

    @property
    def descriptor_source(self) -> OriginalSecurityDescriptorSource | None:
        self.assert_sources()
        return None if self._preflight_sources is None else self._preflight_sources.source

    @property
    def security_descriptor(self) -> ObservedSecurityDescriptor | None:
        self.assert_sources()
        return None if self._preflight_sources is None else self._preflight_sources.descriptor

    @property
    def route_commands(self) -> NativeRouteCommands | None:
        self.assert_sources()
        return None if self._preflight_sources is None else self._preflight_sources.commands

    @property
    def security_inventory_issuer(self) -> NativeSecurityInventory | None:
        self.assert_sources()
        issuer = self._security_inventory
        if self._security_inventory_signature != (type(issuer), id(issuer)):
            raise _denied()
        if issuer is not None:
            from ai_workshop.labs.rag.indexing.access_epoch_security_inventory_native import (
                NativeSecurityInventory,
            )

            if type(issuer) is not NativeSecurityInventory or issuer.context is not self:
                raise _denied()
        return issuer

    @property
    def unmanaged(self) -> OriginalUnmanagedPhysical:
        self.assert_sources()
        return self._namespace_source.unmanaged(self._namespace)

    def assert_owned(self) -> None:
        self.assert_sources()
        if self._lock is None or self._owner is None or self._epoch is None:
            raise _denied()
        self._lock.assert_owned(self._owner)
        if self._runtime_signature != self._runtime_values():
            raise _denied()
        if (
            self._epoch.original != self._observation.identity
            or self._epoch.binding.claim != self._claim
        ):
            raise _denied()
        if self._epoch.binding.execution_id != str(self._owner.execution_id):
            raise _denied()

    def _runtime_values(self) -> object:
        return (
            _freeze(self._epoch),
            id(self._epoch),
            id(self._owner),
            _freeze(self._owner),
            id(self._lock),
            id(self._journal),
            id(self._native),
            id(self._store),
            id(self._keys),
            None
            if self._journal is None
            else (
                str(self._journal.root),
                id(self._journal.lock),
                id(self._journal.owner),
                self._journal.scope,
                id(self._journal.protection),
                id(self._journal.files),
            ),
        )

    async def revalidate(self) -> AccessEpochReadback:
        self.assert_owned()
        state = await self.repository.readback(self.claim)
        self.assert_owned()
        if (
            state.prepared != self._epoch
            or self._owner is None
            or state.executor_generation != self._owner.executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
        ):
            raise _denied()
        sequence = 0
        for row in state.actions:
            a = row.action
            if (
                type(a) is not ReservedCutoverAction
                or type(a.sequence) is not int
                or type(row.event_sequence) is not int
                or a.execution_id != self._owner.execution_id
                or a.executor_generation != self._owner.executor_generation
                or a.sequence != sequence + 1
                or type(a.expected.preceding_sequence) is not int
                or a.expected.preceding_sequence != sequence
                or row.event_sequence < a.sequence
            ):
                raise _denied()
            sequence = row.event_sequence
        if tuple(row.action.kind for row in state.actions) != CUTOVER_ORDER[: len(state.actions)]:
            raise _denied()
        return state

    def _retain(self, name: str, value: object) -> None:
        self.assert_owned()
        if name in self._caps and self._caps[name] is not value:
            raise _denied()
        self._caps[name], self._cap_signatures[name] = value, _freeze(value)

    def _retain_reobserved(self, name: str, value: object) -> None:
        """Equal reissuance is admitted only by its exact actual source issuer."""
        self.assert_owned()
        if name == "app_retirement" and type(self._apps) is RecordedAppRetirement:
            _none(self._apps.assert_issued, value)
        elif name == "credential" and type(self._administrator) is RecordedBootstrapAdministrator:
            _none(self._administrator.assert_credential, value)
        elif (
            name in {"admin_security", "historical_security"}
            and type(self._audits) is RecordedBootstrapAudits
        ):
            _none(self._audits.assert_issued, value)
        elif name == "tls_assets" and type(self._tls) is AccessEpochTls:
            _none(self._tls.assert_issued, value)
        elif (
            name == "final_auth" and type(self._final_authentication) is RecordedFinalAuthentication
        ):
            _none(self._final_authentication.assert_issued, value)
        else:
            raise _denied()
        self.assert_owned()
        if name in self._caps:
            signature = self._cap_signatures[name]
            if signature != _freeze(self._caps[name]) or signature != _freeze(value):
                raise _denied()
            return  # Retain the original issuer object, including private credentials.
        self._retain(name, value)

    def _cap(self, name: str) -> object | None:
        value = self._caps.get(name)
        if value is not None:
            self.assert_owned()
            if self._cap_signatures.get(name) != _freeze(value):
                raise _denied()
        return value

    @property
    def settings(self) -> Settings:
        self.assert_sources()
        return self._settings

    @property
    def repository(self) -> SqlAlchemyAccessEpochRepository:
        self.assert_sources()
        return self._repository

    @property
    def claim(self) -> FrozenAliasClaim:
        self.assert_sources()
        return self._claim

    @property
    def original(self) -> OriginalAccessEpochPreflight:
        self.assert_sources()
        return self._original

    @property
    def observation(self) -> OriginalDeploymentObservation:
        self.assert_sources()
        return self._observation

    @property
    def namespace_source(self) -> OriginalNamespaceSource:
        self.assert_sources()
        return self._namespace_source

    @property
    def namespace(self) -> OriginalNamespacePermissions:
        self.assert_sources()
        return self._namespace

    @property
    def security_source(self) -> OriginalSecurityAbsenceReader:
        self.assert_sources()
        return self._security_source

    @property
    def absence(self) -> ObservedOriginalSecurityAbsent:
        self.assert_sources()
        return self._absence

    @property
    def epoch(self) -> PreparedAccessEpoch | None:
        self.assert_sources()
        return self._epoch

    @property
    def held_owner(self) -> HeldControlLock | None:
        self.assert_sources()
        return self._owner

    @property
    def journal(self) -> ProtectedControlJournal | None:
        self.assert_sources()
        return self._journal

    @property
    def native(self) -> WindowsControlProcess | None:
        self.assert_sources()
        return self._native

    @property
    def store(self) -> WindowsCredentialStore | None:
        self.assert_sources()
        return self._store

    @property
    def tls(self) -> AccessEpochTls | None:
        self.assert_sources()
        return self._tls

    @property
    def deployment(self) -> DeploymentCommands | None:
        self.assert_sources()
        return self._deployment

    @property
    def apps(self) -> RecordedAppRetirement | None:
        self.assert_sources()
        return self._apps

    @property
    def history(self) -> OriginalHistoryGate | None:
        self.assert_sources()
        return self._history

    @property
    def history_ticket(self) -> VerifiedHistoricalControls | None:
        self.assert_sources()
        return self._history_ticket

    @property
    def bootstrap_factory(self) -> BootstrapBindingFactory | None:
        self.assert_sources()
        return self._bootstrap_factory

    @property
    def bootstrap_commands(self) -> BootstrapCommands | None:
        self.assert_sources()
        return self._bootstrap_commands

    @property
    def administrator(self) -> RecordedBootstrapAdministrator | None:
        self.assert_sources()
        return self._administrator

    @property
    def audits(self) -> RecordedBootstrapAudits | None:
        self.assert_sources()
        return self._audits

    @property
    def keys(self) -> SqlAlchemyEpochKeyRepository | None:
        self.assert_sources()
        return self._keys

    @property
    def final_auth_factory(self) -> FinalAuthBindingFactory | None:
        self.assert_sources()
        return self._final_auth_factory

    @property
    def final_authentication(self) -> RecordedFinalAuthentication | None:
        self.assert_sources()
        return self._final_authentication

    @property
    def app_retirement(self) -> AppRetirementObservation | None:
        value = cast(AppRetirementObservation | None, self._cap("app_retirement"))
        if value is not None:
            if type(value) is not AppRetirementObservation or self._apps is None:
                raise _denied()
            self._apps.assert_issued(value)
        return value

    @property
    def tls_assets(self) -> PreparedTlsAssets | None:
        value = cast(PreparedTlsAssets | None, self._cap("tls_assets"))
        if value is not None:
            if type(value) is not PreparedTlsAssets or self._tls is None:
                raise _denied()
            self._tls.assert_issued(value)
        return value

    @property
    def bootstrap(self) -> ObservedDeployment | None:
        value = cast(ObservedDeployment | None, self._cap("bootstrap"))
        if value is not None:
            if type(value) is not ObservedDeployment or self._deployment is None:
                raise _denied()
            self._deployment.assert_observed(value)
        return value

    @property
    def final(self) -> ObservedDeployment | None:
        value = cast(ObservedDeployment | None, self._cap("final"))
        if value is not None:
            if type(value) is not ObservedDeployment or self._deployment is None:
                raise _denied()
            self._deployment.assert_observed(value)
        return value

    @property
    def credential(self) -> BootstrapAdministrator | None:
        value = cast(BootstrapAdministrator | None, self._cap("credential"))
        if value is not None:
            if type(value) is not BootstrapAdministrator or self._administrator is None:
                raise _denied()
            self._administrator.assert_credential(value)
        return value

    @property
    def admin_security(self) -> ObservedBootstrapSecurity | None:
        value = cast(ObservedBootstrapSecurity | None, self._cap("admin_security"))
        if value is not None:
            if type(value) is not ObservedBootstrapSecurity or self._audits is None:
                raise _denied()
            self._audits.assert_issued(value)
        return value

    @property
    def historical_security(self) -> ObservedBootstrapSecurity | None:
        value = cast(ObservedBootstrapSecurity | None, self._cap("historical_security"))
        if value is not None:
            if type(value) is not ObservedBootstrapSecurity or self._audits is None:
                raise _denied()
            self._audits.assert_issued(value)
        return value

    @property
    def final_auth(self) -> FinalAuthObservation | None:
        value = cast(FinalAuthObservation | None, self._cap("final_auth"))
        if value is not None:
            if type(value) is not FinalAuthObservation or self._final_authentication is None:
                raise _denied()
            self._final_authentication.assert_issued(value)
        return value

    def _assert_inventory_origin(self, value: CapturedIndexInventory) -> None:
        physical = value.physical
        if (
            type(value) is not CapturedIndexInventory
            or physical is None
            or value.unmanaged is None
            or physical.namespace_source is not self._namespace_source
            or physical.namespace is not self._namespace
            or physical.unmanaged_source is not self.unmanaged
            or value.unmanaged is not physical.unmanaged_passes[1]
        ):
            raise _denied()

    @property
    def original_inventory(self) -> CapturedIndexInventory | None:
        value = cast(CapturedIndexInventory | None, self._cap("original_inventory"))
        if value is not None:
            self._collectors["original"].assert_issued(value)
            self._assert_inventory_origin(value)
        return value

    @property
    def original_inventory_issuer(self) -> RecordedInventoryCollector | None:
        self.assert_sources()
        value = self._collectors.get("original")
        if value is not None and type(value) is not RecordedInventoryCollector:
            raise _denied()
        return value

    @property
    def bootstrap_inventory(self) -> CapturedIndexInventory | None:
        value = cast(CapturedIndexInventory | None, self._cap("bootstrap_inventory"))
        if value is not None:
            self._collectors["bootstrap"].assert_issued(value)
            self._assert_inventory_origin(value)
        return value

    @property
    def bootstrap_inventory_issuer(self) -> RecordedInventoryCollector | None:
        self.assert_sources()
        value = self._collectors.get("bootstrap")
        if value is not None and type(value) is not RecordedInventoryCollector:
            raise _denied()
        return value

    @property
    def final_inventory(self) -> CapturedIndexInventory | None:
        value = cast(CapturedIndexInventory | None, self._cap("final_inventory"))
        if value is not None:
            self._collectors["final"].assert_issued(value)
            self._assert_inventory_origin(value)
        return value

    @property
    def final_inventory_issuer(self) -> RecordedInventoryCollector | None:
        self.assert_sources()
        value = self._collectors.get("final")
        if value is not None and type(value) is not RecordedInventoryCollector:
            raise _denied()
        return value

    def _security_completion(self, phase: str) -> MainSecurityCompletion | None:
        from ai_workshop.labs.rag.indexing.access_epoch_security_inventory_native import (
            MainSecurityCompletion,
        )

        value = cast(MainSecurityCompletion | None, self._cap(phase + "_security_inventory"))
        if value is not None:
            issuer = self.security_inventory_issuer
            if type(value) is not MainSecurityCompletion or issuer is None or value.phase != phase:
                raise _denied()
            _none(issuer.assert_issued, value)
            completed = self._cap(phase + "_inventory")
            collector = self._collectors.get(phase)
            if (
                type(completed) is not CapturedIndexInventory
                or type(collector) is not RecordedInventoryCollector
                or completed.physical is not value.physical
                or collector._secure.get(completed) != (issuer, value)
            ):
                raise _denied()
            _none(collector.assert_issued, completed)
        return value

    @property
    def bootstrap_security_inventory(self) -> MainSecurityCompletion | None:
        return self._security_completion("bootstrap")

    @property
    def final_security_inventory(self) -> MainSecurityCompletion | None:
        return self._security_completion("final")

    @property
    def bootstrap_preservation(self) -> PreservedDeployment | None:
        value = cast(PreservedDeployment | None, self._cap("bootstrap_preservation"))
        if value is not None and (
            type(value) is not PreservedDeployment
            or self._deployment is None
            or self.bootstrap is None
            or value.deployment is not self.bootstrap
            or self._deployment._preserved.get(self.bootstrap) is not value
        ):
            raise _denied()
        return value

    @property
    def final_preservation(self) -> PreservedDeployment | None:
        value = cast(PreservedDeployment | None, self._cap("final_preservation"))
        if value is not None and (
            type(value) is not PreservedDeployment
            or self._deployment is None
            or self.final is None
            or value.deployment is not self.final
            or self._deployment._preserved.get(self.final) is not value
        ):
            raise _denied()
        return value

    @property
    def verification(self) -> object | None:
        return cast(object, self._verification)

    @property
    def verified_native(self) -> object | None:
        value = self._cap("verified_native")
        if value is not None and (
            self._verification is None or self._verification.assert_issued(value) is not None
        ):
            raise _denied()
        return value


class ConcreteNativeCutoverControl:
    """Closed twelve-action port; unsupported producers prevent any control."""

    def __init__(self, context: NativeControlContext) -> None:
        if type(context) is not NativeControlContext:
            raise _denied()
        context.assert_sources()
        self.context = context
        self._context = context
        self._port_id = uuid4()
        self._ownership: ControlOwnership | None = None
        self._ownership_signature: object = None
        self._acquired = False
        self._running = False
        self._closed = False
        self._prepared: set[CutoverActionKind] = set()
        self._tickets: dict[CutoverActionKind, object] = {}
        self._expected_signatures: dict[CutoverActionKind, object] = {}
        self._attempted_actions: set[UUID] = set()
        self._original_process: RecordedOriginalControlProcess | None = None
        self._original_settlement: OriginalDaemonSettlement | None = None
        self._deployment_process: RecordedDeploymentControlProcess | None = None
        self._deployment_settlement: DeploymentDaemonSettlement | None = None
        self._bootstrap_retirement: RecordedBootstrapRetirement | None = None
        self._bootstrap_settlement: BootstrapDaemonSettlement | None = None
        self._key_group: BootstrapRoleKeyGroup | None = None
        self._key_parent: ReservedCutoverAction | None = None
        self._verification: Any = None
        self._verification_module: Any = None
        self._verification_failed = False
        self._results: dict[UUID, ControlSettlement] = {}
        self._result_signatures: dict[UUID, object] = {}

    @property
    def control_port_id(self) -> UUID:
        return self._port_id

    def assert_supported(self) -> None:
        """Factory calls this before controller.advance can create an epoch."""
        self._context.assert_sources()
        if self._closed or self.context is not self._context:
            raise _denied()
        if type(self._verification_failed) is not bool or self._verification_failed:
            raise _unsupported()
        try:
            self._context.assert_preflight_sources()
            if self._verification is None:
                self._support()
            else:
                self._assert_verification_support()
        except BaseException as error:
            self._discard_verification()
            if isinstance(error, Exception):
                raise _unsupported() from None
            raise

    def _discard_verification(self) -> None:
        self._verification_failed = True
        self._verification = None
        self._verification_module = None
        self._context._verification = None

    def _assert_verification_support(self) -> None:
        instance, module = self._verification, self._verification_module
        if (
            instance is None
            or module is None
            or type(instance) is not module.NativeFinalVerification
            or instance.context is not self._context
            or self._context.verification is not instance
            or not callable(instance.assert_supported)
        ):
            raise _unsupported()
        _none(instance.assert_supported)
        self._context.assert_preflight_sources()
        if (
            self._verification is not instance
            or self._verification_module is not module
            or self._context.verification is not instance
            or instance.context is not self._context
        ):
            raise _unsupported()

    def _support(self) -> None:
        module = importlib.import_module(_FINAL_MODULE)
        cls = module.NativeFinalVerification
        if not isinstance(cls, type) or cls.__module__ != _FINAL_MODULE:
            raise _unsupported()
        instance = cast(Any, cls)(self._context)
        if type(instance) is not cls or cast(Any, instance).context is not self._context:
            raise _unsupported()
        if (
            not callable(cast(Any, instance).verify)
            or not callable(cast(Any, instance).assert_issued)
            or not callable(cast(Any, instance).assert_supported)
        ):
            raise _unsupported()
        _none(cast(Any, instance).assert_supported)
        self._context.assert_preflight_sources()
        if (
            self._context.verification is not None
            or cast(Any, instance).context is not self._context
        ):
            raise _unsupported()
        self._verification_module, self._verification = module, instance
        self._context._verification = instance
        self._assert_verification_support()

    async def acquire(self, execution_id: UUID, executor_generation: str) -> ControlOwnership:
        if self._closed or self.context is not self._context:
            raise _denied()
        if self._acquired:
            retained = self._ownership
            if (
                retained is None
                or type(execution_id) is not UUID
                or type(executor_generation) is not str
                or execution_id != retained.execution_id
                or executor_generation != retained.executor_generation
            ):
                raise _denied()
            await self._state(retained)
            return retained  # Same live held session; never recursive native acquire.
        self._acquired = True
        self._context.assert_sources()
        self.assert_supported()  # No lock/journal/source mutation if incomplete.
        try:
            valid = (
                type(execution_id) is UUID
                and execution_id.int != 0
                and type(executor_generation) is str
                and str(UUID(executor_generation)) == executor_generation
            )
        except Exception:
            valid = False
        if not valid:
            raise _denied()
        c = self._context
        state = await c.repository.readback(c.claim)
        c.assert_sources()
        epoch = state.prepared
        if (
            epoch is None
            or epoch.binding.execution_id != str(execution_id)
            or epoch.binding.claim != c.claim
            or epoch.original != c.observation.identity
            or state.executor_generation != executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
        ):
            raise _denied()
        # This live context cannot hydrate capabilities after control has begun.
        if state.actions:
            raise _unsupported()
        lock = WindowsControlLock(epoch.original.daemon_sha256, "ai-workshop")
        owner: HeldControlLock | None = None
        try:
            owner = lock.acquire(execution_id, executor_generation)
            private = NativeWindowsPrivateState(PROJECT_ROOT)
            NativeWindowsPrivateState.assert_origin(private)
            journal = ProtectedControlJournal(
                PROJECT_ROOT, private, private, lock, owner, lock.scope_sha256
            )
            c._epoch, c._lock, c._owner, c._journal = epoch, lock, owner, journal
            c._native = WindowsControlProcess()
            c._store = WindowsCredentialStore(PROJECT_ROOT, private, private)
            c._keys = SqlAlchemyEpochKeyRepository(c.repository)
            c._runtime_signature = c._runtime_values()
            c._tls = AccessEpochTls(
                epoch,
                c.repository,
                journal,
                ProjectTlsBundles(private),
                c.observation.original_ipv4,
            )
            history_reader = OriginalHistoricalReceiptReader(PROJECT_ROOT, private, private)
            c._history = OriginalHistoryGate(
                epoch, c.repository, journal, history_reader, c.original
            )
            self._original_process = RecordedOriginalControlProcess(
                epoch, c.repository, journal, c._native, PROJECT_ROOT
            )
            self._original_settlement = OriginalDaemonSettlement(
                epoch, c.repository, journal, c.original.executor
            )
            ownership = ControlOwnership(execution_id, executor_generation, self._port_id)
            self._ownership, self._ownership_signature = ownership, _freeze(ownership)
            c._history_ticket = await c._history.verify()
            self._owned(ownership)
            reader = OriginalApplicationSourceReader()
            issuer = OriginalApplicationAllowlistIssuer(epoch, c.repository, journal, reader)
            c._apps = RecordedAppRetirement(
                epoch, c.repository, journal, issuer, WindowsProcessRetirement()
            )
            await self._state(ownership)
            return ownership
        except BaseException as exc:
            if owner is not None:
                with suppress(BaseException):
                    lock.close(owner)
            self._closed = True
            if isinstance(exc, Exception):
                raise _denied() from None
            raise

    def _owned(self, ownership: ControlOwnership) -> None:
        if (
            self._closed
            or self.context is not self._context
            or ownership is not self._ownership
            or type(ownership) is not ControlOwnership
            or _freeze(ownership) != self._ownership_signature
            or ownership.control_port_id != self._port_id
        ):
            raise _denied()
        self._context.assert_owned()

    async def _state(self, ownership: ControlOwnership) -> AccessEpochReadback:
        self._owned(ownership)
        state = await self._context.revalidate()
        self._owned(ownership)
        if self._context._history is None or self._context._history_ticket is None:
            raise _denied()
        await self._context._history.assert_verified(self._context._history_ticket)
        self._owned(ownership)
        for i, row in enumerate(state.actions):
            if (
                row.outcome not in {"pending", "unknown", "settled"}
                or row.outcome != "settled"
                and i < len(state.actions) - 1
                or row.outcome == "settled"
                and (row.manifest_json is None or row.event_sequence <= row.action.sequence)
                or row.outcome == "pending"
                and (row.manifest_json is not None or row.event_sequence != row.action.sequence)
                or row.outcome == "unknown"
                and row.event_sequence <= row.action.sequence
            ):
                raise _denied()
        return state

    async def assert_owned(self, ownership: ControlOwnership) -> None:
        await self._state(ownership)

    def _runtime(
        self,
    ) -> tuple[
        NativeControlContext, PreparedAccessEpoch, ProtectedControlJournal, WindowsControlProcess
    ]:
        c = self._context
        c.assert_owned()
        if c.epoch is None or c.journal is None or c.native is None:
            raise _denied()
        return c, c.epoch, c.journal, c.native

    async def _deployment_ready(self) -> None:
        c, epoch, journal, native = self._runtime()
        if c._deployment is not None:
            return
        if c._tls is None or c.original_inventory is None:
            raise _denied()
        state = await c.revalidate()
        row = next(x for x in state.actions if x.action.kind == CutoverActionKind.PREPARE_TLS)
        assets = await c._tls.read_settled(row.action)
        c.assert_owned()
        c._tls.assert_issued(assets)
        c._retain_reobserved("tls_assets", assets)
        observed = c.observation
        c._deployment = DeploymentCommands(
            epoch,
            assets,
            observed.image.manifest_digest,
            observed.cluster_name,
            observed.network_subnet,
            observed.network_gateway,
            tuple(x.observation for x in c.original_inventory.rag_entries),
        )
        self._deployment_process = RecordedDeploymentControlProcess(
            epoch,
            c.repository,
            c._deployment,
            journal,
            native,
            FixedDeploymentInventory(c.original.executor),
        )
        self._deployment_settlement = DeploymentDaemonSettlement(
            epoch,
            c.repository,
            journal,
            c._deployment,
            c._tls,
            FixedDeploymentDaemonReads(c.original.executor),
        )

    async def _administrator_ready(self) -> None:
        c, epoch, journal, native = self._runtime()
        if c._administrator is not None:
            return
        if c._deployment is None or c.bootstrap is None:
            raise _denied()
        factory = BootstrapBindingFactory(c.repository, journal, c._deployment, c.security_source)
        commands = await factory.create(c.bootstrap, c.absence, c.namespace.permissions)
        c.assert_owned()
        factory.assert_issued(commands)
        c._bootstrap_factory, c._bootstrap_commands = factory, commands
        administrator = RecordedBootstrapAdministrator(
            epoch,
            c.repository,
            c._deployment,
            c.bootstrap,
            commands,
            journal,
            native,
            PROJECT_ROOT,
            factory,
        )
        c._administrator = administrator
        c._audits = RecordedBootstrapAudits(administrator, factory, c.repository, journal, native)

    def _closed_parent_target(self, kind: CutoverActionKind) -> str:
        c, epoch, journal, _ = self._runtime()
        if kind not in {CutoverActionKind.REVOKE_HISTORICAL, CutoverActionKind.ISSUE_ROLE_KEY}:
            raise _denied()
        if (
            c.bootstrap is None
            or c.credential is None
            or c.admin_security is None
            or c._bootstrap_factory is None
            or c._bootstrap_commands is None
        ):
            raise _denied()
        c._bootstrap_factory.assert_issued(c._bootstrap_commands)
        target: dict[str, object] = {
            "schema_version": 1,
            "kind": kind.value,
            "epoch_id": epoch.binding.access_epoch_id,
            "execution_id": epoch.binding.execution_id,
            "executor_generation": journal.owner.executor_generation,
            "request_id": str(c.claim.request_id),
            "snapshot_sha256": c.claim.snapshot.sha256,
            "gate_revision": c.claim.revision,
            "scope_sha256": journal.scope,
            "bootstrap_action_id": str(c.bootstrap.action_id),
            "bootstrap_container_id": c.bootstrap.container_id,
            "administrator_action_id": str(c.credential.action_id),
            "administrator_submission_id": str(c.credential.submission_id),
            "administrator_audit": json.loads(c.admin_security.manifest_json),
        }
        if kind == CutoverActionKind.ISSUE_ROLE_KEY:
            if c.historical_security is None:
                raise _denied()
            target["historical_audit"] = json.loads(c.historical_security.manifest_json)
            target["roles"] = ["reader", "writer", "collector"]
            target["permissions"] = {
                role: sha256(
                    canonical_json(
                        dict(c._bootstrap_commands.permissions_descriptor(cast(ServiceRole, role)))
                    ).encode()
                ).hexdigest()
                for role in ("reader", "writer", "collector")
            }
        return sha256(canonical_json(target).encode()).hexdigest()

    async def _final_ready(self) -> None:
        c, _, journal, native = self._runtime()
        if c._final_authentication is not None:
            return
        if (
            c._keys is None
            or c._deployment is None
            or c._bootstrap_factory is None
            or c._bootstrap_commands is None
            or c._tls is None
            or c._store is None
            or c.final is None
        ):
            raise _denied()
        factory = FinalAuthBindingFactory(
            c.repository,
            cast(CompletedKeyReadPort, c._keys),
            journal,
            c._deployment,
            c._bootstrap_factory,
            c._bootstrap_commands,
            c._tls,
            cast(PreparedCredentialReadPort, c._store),
        )
        binding = await factory.create(c.final)
        c.assert_owned()
        factory.assert_issued(binding)
        c._final_auth_factory = factory
        c._final_authentication = RecordedFinalAuthentication(
            factory, binding, c._deployment, c.final, c.repository, journal, native
        )

    async def expected(
        self,
        epoch: PreparedAccessEpoch,
        kind: CutoverActionKind,
        sequence: int,
        ownership: ControlOwnership,
    ) -> ControlExpectedIdentity:
        if (
            self._running
            or type(kind) is not CutoverActionKind
            or kind not in CUTOVER_ORDER
            or type(epoch) is not PreparedAccessEpoch
            or type(sequence) is not int
            or kind in self._prepared
        ):
            raise _denied()
        self._running = True
        try:
            state = await self._state(ownership)
            if (
                type(kind) is not CutoverActionKind
                or kind not in CUTOVER_ORDER
                or epoch != self._context.epoch
                or type(sequence) is not int
                or sequence != (state.actions[-1].event_sequence if state.actions else 0)
                or tuple(x.action.kind for x in state.actions)
                != CUTOVER_ORDER[: CUTOVER_ORDER.index(kind)]
                or any(x.outcome != "settled" for x in state.actions)
            ):
                raise _denied()
            self._prepared.add(kind)
            c, _, journal, native = self._runtime()
            ticket: object
            if kind == CutoverActionKind.STOP_REGISTERED_APPS:
                if c._apps is None:
                    raise _denied()
                ticket = await c._apps.prepare()
            elif kind in {CutoverActionKind.STOP_OLD, CutoverActionKind.RETIRE_OLD}:
                if self._original_process is None:
                    raise _denied()
                ticket = await self._original_process.prepare(kind)
            elif kind == CutoverActionKind.PREPARE_TLS:
                if c._tls is None:
                    raise _denied()
                ticket = await c._tls.prepare()
            elif kind in {CutoverActionKind.START_BOOTSTRAP, CutoverActionKind.START_SECURED}:
                await self._deployment_ready()
                if self._deployment_process is None:
                    raise _denied()
                ticket = await self._deployment_process.prepare(kind)
            elif kind == CutoverActionKind.BOOTSTRAP_ADMIN:
                await self._administrator_ready()
                if c._administrator is None:
                    raise _denied()
                ticket = await c._administrator.prepare()
            elif kind in {CutoverActionKind.REVOKE_HISTORICAL, CutoverActionKind.ISSUE_ROLE_KEY}:
                ticket = journal.prepare_expected(kind, sequence, self._closed_parent_target(kind))
            elif kind in {CutoverActionKind.STOP_BOOTSTRAP, CutoverActionKind.RETIRE_BOOTSTRAP}:
                if c._deployment is None or c.bootstrap is None:
                    raise _denied()
                if self._bootstrap_retirement is None:
                    self._bootstrap_retirement = RecordedBootstrapRetirement(
                        epoch,
                        c.repository,
                        journal,
                        native,
                        PROJECT_ROOT,
                        c._deployment,
                        c.bootstrap,
                    )
                    self._bootstrap_settlement = BootstrapDaemonSettlement(
                        epoch,
                        c.repository,
                        journal,
                        c._deployment,
                        c.bootstrap,
                        FixedBootstrapDockerReads(c._deployment, c.bootstrap),
                    )
                ticket = await self._bootstrap_retirement.prepare(kind)
            elif kind == CutoverActionKind.VERIFY_ACCESS:
                await self._final_ready()
                if c._final_authentication is None:
                    raise _denied()
                ticket = await c._final_authentication.prepare()
            else:
                raise _denied()
            if type(ticket) not in {
                FreshSubmissionTicket,
                FreshAppRetirementTicket,
                FreshFinalAuthTicket,
            }:
                raise _denied()
            expected = cast(Any, ticket).expected
            if (
                type(expected) is not ControlExpectedIdentity
                or expected.preceding_sequence != sequence
            ):
                raise _denied()
            await self._state(ownership)
            self._tickets[kind], self._expected_signatures[kind] = ticket, _freeze(ticket)
            return expected
        except Exception:
            raise _denied() from None
        finally:
            self._running = False

    async def _inventory(self, action: ReservedCutoverAction, phase: str) -> CapturedIndexInventory:
        c, epoch, journal, native = self._runtime()
        retained = cast(CapturedIndexInventory | None, c._cap(phase + "_inventory"))
        if retained is not None:
            issuer = c._collectors[phase]
            issuer.assert_issued(retained)
            await issuer.reader.revalidate(action)
            c.assert_owned()
            return retained
        if phase in c._collectors:
            raise _denied()  # Previous attempt must not be reopened with a new issuer.
        if phase == "original":
            if (
                c._history is None
                or c._history_ticket is None
                or c._apps is None
                or c.app_retirement is None
            ):
                raise _denied()
            factory = InventoryReadBindingFactory.for_original(
                epoch, c.repository, journal, c.namespace.permissions, c._history, c._apps
            )
            binding = await factory.create_original(action, c.app_retirement, c._history_ticket)
        else:
            if (
                c._keys is None
                or c._deployment is None
                or c._bootstrap_factory is None
                or c._bootstrap_commands is None
                or c._tls is None
                or c._store is None
            ):
                raise _denied()
            factory = InventoryReadBindingFactory.for_secure(
                c.repository,
                cast(CompletedKeyReadPort, c._keys),
                journal,
                c._deployment,
                c._bootstrap_factory,
                c._bootstrap_commands,
                c._tls,
                cast(PreparedCredentialReadPort, c._store),
            )
            observed = c.bootstrap if phase == "bootstrap" else c.final
            if observed is None:
                raise _denied()
            binding = (
                await factory.create_bootstrap(action, observed)
                if phase == "bootstrap"
                else await factory.create_final(action, observed)
            )
        c.assert_owned()
        collector = RecordedInventoryCollector(
            RecordedInventoryReads(factory, binding, c.repository, journal, native),
            namespace_source=c.namespace_source,
            namespace=c.namespace,
        )
        c._collectors[phase] = collector
        if phase == "original":
            result = await collector.collect(action)
        else:
            security_issuer = c.security_inventory_issuer
            if security_issuer is None:
                raise _denied()
            physical = await collector.capture_physical(action)
            security_cap = await security_issuer.observe(action, collector, physical)
            c.assert_owned()
            result = await collector.complete_secure(
                action, physical, security_issuer, security_cap
            )
            c.assert_owned()
            security_issuer.assert_issued(security_cap)
            c._retain(phase + "_security_inventory", security_cap)
            c._retain(phase + "_preservation", security_cap.preservation)
        c.assert_owned()
        collector.assert_issued(result)
        c._retain(phase + "_inventory", result)
        return result

    async def _parent(
        self, action: ReservedCutoverAction, ownership: ControlOwnership
    ) -> AccessEpochReadback:
        state = await self._state(ownership)
        if (
            type(action) is not ReservedCutoverAction
            or type(action.action_id) is not UUID
            or type(action.execution_id) is not UUID
            or type(action.kind) is not CutoverActionKind
            or type(action.expected) is not ControlExpectedIdentity
            or type(action.expected.identity_json) is not str
            or not state.actions
            or state.actions[-1].action != action
            or state.actions[-1].outcome not in {"pending", "unknown"}
            or action.kind not in CUTOVER_ORDER
        ):
            raise _denied()
        return state

    async def _predecessor(self, action: ReservedCutoverAction) -> RetiredPredecessor:
        c = self._context
        state = await c.revalidate()
        kind = (
            CutoverActionKind.RETIRE_OLD
            if action.kind == CutoverActionKind.START_BOOTSTRAP
            else CutoverActionKind.RETIRE_BOOTSTRAP
        )
        row = next(x for x in state.actions if x.action.kind == kind)
        if row.outcome != "settled" or row.manifest_json is None:
            raise _denied()
        return RetiredPredecessor(
            row.action,
            ControlSettlement(
                row.action.action_id,
                row.action.execution_id,
                row.action.executor_generation,
                "settled",
                row.manifest_json,
                row.observed_at,
            ),
            None if action.kind == CutoverActionKind.START_BOOTSTRAP else c.bootstrap,
        )

    def _settled(self, action: ReservedCutoverAction, manifest: str) -> ControlSettlement:
        self._context.assert_owned()
        if type(manifest) is not str or canonical_json(json.loads(manifest)) != manifest:
            raise _denied()
        return ControlSettlement(
            action.action_id,
            action.execution_id,
            action.executor_generation,
            "settled",
            manifest,
            datetime.now(UTC),
        )

    async def _dispatch(
        self, action: ReservedCutoverAction, ticket: object | None
    ) -> ControlSettlement | None:
        c, _, journal, _ = self._runtime()
        kind = action.kind
        fresh = ticket is not None
        if kind == CutoverActionKind.STOP_REGISTERED_APPS:
            if c._apps is None:
                raise _denied()
            if fresh:
                if type(ticket) is not FreshAppRetirementTicket:
                    raise _denied()
                value = await c._apps.run(action, ticket)
            else:
                old = self._tickets.get(kind)
                if type(old) is not FreshAppRetirementTicket:
                    return None
                value = await c._apps.recover(action, old.allowlist)
            c._apps.assert_issued(value)
            c._retain_reobserved("app_retirement", value)
            return self._settled(action, value.manifest_json)
        if kind in {CutoverActionKind.STOP_OLD, CutoverActionKind.RETIRE_OLD}:
            if self._original_process is None or self._original_settlement is None:
                raise _denied()
            if kind == CutoverActionKind.STOP_OLD:
                if not fresh and c.original_inventory is None:
                    return None
                await self._inventory(action, "original")
            if fresh:
                if type(ticket) is not FreshSubmissionTicket:
                    raise _denied()
                await self._original_process.run(action, ticket)
            return await self._original_settlement.observe(action)
        if kind == CutoverActionKind.PREPARE_TLS:
            if c._tls is None:
                raise _denied()
            assets = (
                await c._tls.execute(action, cast(FreshSubmissionTicket, ticket))
                if fresh
                else await c._tls.reconcile(action)
            )
            c._tls.assert_issued(assets)
            c._retain_reobserved("tls_assets", assets)
            return self._settled(action, assets.manifest_json)
        if kind in {CutoverActionKind.START_BOOTSTRAP, CutoverActionKind.START_SECURED}:
            if self._deployment_process is None or self._deployment_settlement is None:
                raise _denied()
            if fresh:
                await self._deployment_process.run(
                    action, cast(FreshSubmissionTicket, ticket), await self._predecessor(action)
                )
            observed, result = await self._deployment_settlement.observe(
                action,
                predecessor=None if kind == CutoverActionKind.START_BOOTSTRAP else c.bootstrap,
            )
            if c._deployment is None:
                raise _denied()
            c._deployment.assert_observed(observed)
            name = "bootstrap" if kind == CutoverActionKind.START_BOOTSTRAP else "final"
            retained = c.bootstrap if name == "bootstrap" else c.final
            if retained is not None:
                old_packet = json.loads(retained.manifest_json)
                new_packet = json.loads(observed.manifest_json)
                old_packet.pop("observed_at")
                new_packet.pop("observed_at")
                prior = self._results.get(action.action_id)
                if (
                    old_packet != new_packet
                    or prior is None
                    or self._result_signatures.get(action.action_id) != _freeze(prior)
                    or prior.manifest_json != retained.manifest_json
                ):
                    raise _denied()
                return ControlSettlement(
                    prior.action_id,
                    prior.execution_id,
                    prior.executor_generation,
                    prior.outcome,
                    prior.manifest_json,
                    result.observed_at,
                )
            c._retain(name, observed)
            return result
        if kind == CutoverActionKind.BOOTSTRAP_ADMIN:
            if c._administrator is None or c._audits is None:
                raise _denied()
            credential = (
                await c._administrator.run(action, cast(FreshSubmissionTicket, ticket))
                if fresh
                else await c._administrator.recover(action)
            )
            c._administrator.assert_credential(credential)
            c._retain_reobserved("credential", credential)
            security = await c._audits.run(action, credential)
            c._audits.assert_issued(security)
            c._retain_reobserved("admin_security", security)
            return self._settled(
                action,
                canonical_json(
                    {
                        "schema_version": 1,
                        "kind": "bootstrap_administrator_verified",
                        "action_id": str(action.action_id),
                        "execution_id": str(action.execution_id),
                        "executor_generation": action.executor_generation,
                        "container_id": credential.container_id,
                        "submission_id": str(credential.submission_id),
                        "security": json.loads(security.manifest_json),
                    }
                ),
            )
        if kind == CutoverActionKind.REVOKE_HISTORICAL:
            if c._audits is None or c.credential is None:
                raise _denied()
            if fresh:
                journal.begin(action, cast(FreshSubmissionTicket, ticket))
            else:
                if journal.read(action) is None:
                    return None
            security = await c._audits.run(action, c.credential)
            c._audits.assert_issued(security)
            c._retain_reobserved("historical_security", security)
            return self._settled(action, security.manifest_json)
        if kind == CutoverActionKind.ISSUE_ROLE_KEY:
            if (
                c._keys is None
                or c._bootstrap_commands is None
                or c._store is None
                or c.credential is None
            ):
                raise _denied()
            if fresh:
                journal.begin(action, cast(FreshSubmissionTicket, ticket))
            elif journal.read(action) is None:
                return None
            if self._key_group is None:
                if not fresh:
                    return None
                runner = RecordedBootstrapKeyCommands(
                    cast(PreparedAccessEpoch, c.epoch),
                    action,
                    c.repository,
                    c._keys,
                    c._bootstrap_commands,
                    journal,
                    cast(WindowsControlProcess, c.native),
                    PROJECT_ROOT,
                )
                self._key_group = BootstrapRoleKeyGroup(
                    cast(PreparedAccessEpoch, c.epoch),
                    action,
                    c._keys,
                    c._bootstrap_commands,
                    runner,
                    c._store,
                    c.assert_owned,
                    c.credential.password,
                )
                self._key_parent = action
            if action != self._key_parent:
                raise _denied()
            manifest = await self._key_group.advance()
            if manifest is None:
                return None
            return self._settled(action, canonical_json(manifest))
        if kind in {CutoverActionKind.STOP_BOOTSTRAP, CutoverActionKind.RETIRE_BOOTSTRAP}:
            if self._bootstrap_retirement is None or self._bootstrap_settlement is None:
                raise _denied()
            if kind == CutoverActionKind.STOP_BOOTSTRAP:
                if not fresh and c.bootstrap_inventory is None:
                    return None
                await self._inventory(action, "bootstrap")
            if fresh:
                await self._bootstrap_retirement.run(action, cast(FreshSubmissionTicket, ticket))
            return await self._bootstrap_settlement.observe(action)
        if kind == CutoverActionKind.VERIFY_ACCESS:
            if c._final_authentication is None or self._verification is None:
                raise _unsupported()
            auth = await c._final_authentication.run(
                action, cast(FreshFinalAuthTicket, ticket) if fresh else None
            )
            c._final_authentication.assert_issued(auth)
            c._retain_reobserved("final_auth", auth)
            if not fresh and c.final_inventory is None:
                return None
            await self._inventory(action, "final")
            verified = await self._verification.verify(c, action)
            c.assert_owned()
            if (
                type(verified) is not self._verification_module.VerifiedNativeAccess
                or self._verification.assert_issued(verified) is not None
                or type(verified.observed_at) is not datetime
                or verified.observed_at.utcoffset() != UTC.utcoffset(None)
                or verified.observed_at > datetime.now(UTC)
                or type(verified.manifest_json) is not str
                or canonical_json(json.loads(verified.manifest_json)) != verified.manifest_json
            ):
                raise _denied()
            c._retain("verified_native", verified)
            return ControlSettlement(
                action.action_id,
                action.execution_id,
                action.executor_generation,
                "settled",
                verified.manifest_json,
                verified.observed_at,
            )
        raise _denied()

    async def execute(
        self, action: ReservedCutoverAction, ownership: ControlOwnership
    ) -> ControlSettlement:
        if self._running:
            raise _denied()
        self._running = True
        try:
            state = await self._parent(action, ownership)
            ticket = self._tickets.get(action.kind)
            if (
                state.actions[-1].outcome != "pending"
                or action.action_id in self._attempted_actions
                or ticket is None
                or self._expected_signatures.get(action.kind) != _freeze(ticket)
                or cast(Any, ticket).expected != action.expected
            ):
                raise _denied()
            self._attempted_actions.add(action.action_id)
            result = await self._dispatch(action, ticket)
            await self._parent(action, ownership)
            if result is None:
                return ControlSettlement(
                    action.action_id,
                    action.execution_id,
                    action.executor_generation,
                    "unknown",
                    canonical_json(
                        {"schema_version": 1, "kind": action.kind.value, "state": "unresolved"}
                    ),
                    datetime.now(UTC),
                )
            self._results[action.action_id] = result
            self._result_signatures[action.action_id] = _freeze(result)
            return result
        except Exception:
            raise _denied() from None
        finally:
            self._running = False

    async def reconcile(
        self, action: ReservedCutoverAction, ownership: ControlOwnership
    ) -> ControlSettlement | None:
        if self._running:
            raise _denied()
        self._running = True
        try:
            await self._parent(action, ownership)
            result = await self._dispatch(action, None)
            fresh_state = await self._parent(action, ownership)
            prior = self._results.get(action.action_id)
            if prior is not None:
                same_manifest = result is not None and result.manifest_json == prior.manifest_json
                if (
                    result is not None
                    and not same_manifest
                    and (
                        action.kind == CutoverActionKind.RETIRE_OLD
                        and type(self._original_settlement) is OriginalDaemonSettlement
                        or action.kind == CutoverActionKind.RETIRE_BOOTSTRAP
                        and type(self._bootstrap_settlement) is BootstrapDaemonSettlement
                    )
                ):
                    # Actual absence reobservation has a new confirmation time;
                    # keep the original retirement evidence, never rewrite it.
                    old_packet = json.loads(prior.manifest_json)
                    new_packet = json.loads(result.manifest_json)
                    old_packet.pop("retired_at")
                    new_packet.pop("retired_at")
                    same_manifest = old_packet == new_packet
                if (
                    result is None
                    or type(result) is not ControlSettlement
                    or self._result_signatures.get(action.action_id) != _freeze(prior)
                    or prior.action_id != action.action_id
                    or prior.execution_id != action.execution_id
                    or prior.executor_generation != action.executor_generation
                    or result.action_id != prior.action_id
                    or result.execution_id != prior.execution_id
                    or result.executor_generation != prior.executor_generation
                    or result.outcome != prior.outcome
                    or not same_manifest
                ):
                    raise _denied()
                latest = fresh_state.actions[-1].observed_at
                if prior.observed_at >= latest:
                    return prior  # Exact idempotence while chronology still permits it.
                if result.observed_at < latest:
                    raise _denied()
                observed = ControlSettlement(
                    prior.action_id,
                    prior.execution_id,
                    prior.executor_generation,
                    prior.outcome,
                    prior.manifest_json,
                    result.observed_at,
                )
                self._results[action.action_id] = observed
                self._result_signatures[action.action_id] = _freeze(observed)
                return observed
            return result
        except Exception:
            self._owned(ownership)
            return None
        finally:
            self._running = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        c = self._context
        if c._lock is not None and c._owner is not None:
            c._lock.close(c._owner)
