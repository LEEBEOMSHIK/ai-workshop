"""Complete sampled security categories through actual retained native sources.

Pure decoders/whole-map comparisons never issue this capability themselves.
Collector/context integration is separate; no native command is submitted here.
"""

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from pydantic import SecretStr

from ai_workshop.infrastructure.search.access_credentials import CredentialEnvelope
from ai_workshop.labs.rag.indexing.access_epoch_foreign_inventory import (
    DecodedForeignIndex,
    DecodedForeignInventory,
    OpaqueIndexObservation,
    decode_foreign_inventory,
)
from ai_workshop.labs.rag.indexing.access_epoch_index_inventory import (
    _integer,
    _load,
    require_same_private_inventory,
)
from ai_workshop.labs.rag.indexing.access_epoch_inventory_collection import (
    CapturedIndexInventory,
    CapturedPhysicalInventory,
    RecordedInventoryCollector,
)
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_security_descriptor_source import (
    ObservedSecurityDescriptor,
    OriginalSecurityDescriptorSource,
)
from ai_workshop.labs.rag.indexing.access_epoch_security_inventory import (
    DecodedMainSecurityIndex,
    decode_main_security_inventory,
)
from ai_workshop.labs.rag.indexing.access_epoch_security_transition import (
    require_main_security_transition,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    ReservedCutoverAction,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.access_epoch_unmanaged_inventory import (
    require_same_unmanaged_entries,
)

if TYPE_CHECKING:
    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext
    from ai_workshop.labs.rag.indexing.access_epoch_deployment import PreservedDeployment
    from ai_workshop.labs.rag.indexing.access_epoch_repository import AccessEpochReadback


def _denied() -> ValueError:
    return ValueError("security_inventory_native_denied")


def _seal(value: object, *, identity: bool = True) -> object:
    if value is None or type(value) in {str, int, bool, bytes}:
        return (type(value), value)
    if type(value) is UUID:
        return (UUID, str(value))
    if type(value) is datetime:
        return (datetime, value.isoformat())
    if type(value) is SecretStr:
        return (SecretStr, value.get_secret_value())
    if isinstance(value, StrEnum):
        return (type(value), str(value))
    if type(value) is tuple:
        return tuple(_seal(v, identity=identity) for v in value)
    if is_dataclass(value) and not isinstance(value, type):
        return (
            type(value),
            id(value) if identity else None,
            tuple(
                (f.name, _seal(getattr(value, f.name), identity=identity)) for f in fields(value)
            ),
        )
    raise _denied()


def _decode_categories(
    state: bytes,
    stats: bytes,
    cluster_uuid: str,
    cluster_name: str,
    node_id: str,
    descriptor: ObservedSecurityDescriptor,
    managed: tuple[str, ...],
    unmanaged: tuple[str, ...],
) -> tuple[DecodedForeignInventory, DecodedMainSecurityIndex]:
    """Structural join only. No caller packet can obtain source authority."""
    try:
        if (
            type(managed) is not tuple
            or type(unmanaged) is not tuple
            or any(type(n) is not str for n in managed + unmanaged)
            or len(set(managed + unmanaged)) != len(managed + unmanaged)
            or descriptor.primary_name in managed + unmanaged
        ):
            raise _denied()
        indices = _load(state)["metadata"]["indices"]
        selected = set(managed + unmanaged)
        if not selected <= set(indices):
            raise _denied()
        # Every RAG row must belong to the actual complete managed/unmanaged set.
        actual_rag = set()
        for name, row in indices.items():
            mapping = row["mappings"]
            if "_doc" in mapping:
                mapping = mapping["_doc"]
            meta = mapping.get("_meta", {})
            if "rag" in meta or "rag_index_resource" in meta:
                actual_rag.add(name)
        if actual_rag != selected:
            raise _denied()
        security = decode_main_security_inventory(
            state,
            stats,
            cluster_uuid=cluster_uuid,
            cluster_name=cluster_name,
            stable_node_id=node_id,
            descriptor=descriptor,
        )
        ordinary = tuple(sorted(set(indices) - selected - {security.name}))
        foreign = decode_foreign_inventory(
            state,
            stats,
            cluster_uuid=cluster_uuid,
            cluster_name=cluster_name,
            stable_node_id=node_id,
            foreign_names=ordinary,
        )
        if foreign.private_physical_inventory != security.private_physical_inventory:
            raise _denied()
        return foreign, security
    except Exception:
        raise _denied() from None


def _same_foreign_entries(before: DecodedForeignInventory, after: DecodedForeignInventory) -> None:
    """Category comparison; whole-map transition remains separately mandatory."""
    try:
        if (
            type(before) is not DecodedForeignInventory
            or type(after) is not DecodedForeignInventory
        ):
            raise _denied()

        def entries(value: DecodedForeignInventory) -> object:
            result = []
            for entry in value.entries:
                if (
                    type(entry) is not DecodedForeignIndex
                    or type(entry.observation) is not OpaqueIndexObservation
                ):
                    raise _denied()
                _integer(entry.observation.count)
                result.append((entry.name, entry.observation, entry.private_metadata))
            # deleted_docs stays diagnostic, all actual comparison fields retain
            # strict primitive types. Whole physical maps are checked separately.
            return _seal(
                (value.cluster_uuid, value.cluster_name, value.stable_node_id, tuple(result)),
                identity=False,
            )

        if entries(before) != entries(after):
            raise _denied()
    except Exception:
        raise _denied() from None


@dataclass(frozen=True, slots=True, eq=False)
class _SourceOrigin:
    collector: RecordedInventoryCollector = field(repr=False)
    objects: tuple[object, ...] = field(repr=False)
    credentials: tuple[CredentialEnvelope, ...] = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False)
class MainSecurityCompletion:
    nonce: UUID
    parent: ReservedCutoverAction = field(repr=False)
    phase: str
    physical: CapturedPhysicalInventory = field(repr=False)
    foreign: DecodedForeignInventory = field(repr=False)
    security: DecodedMainSecurityIndex = field(repr=False)
    original: CapturedIndexInventory = field(repr=False)
    original_issuer: RecordedInventoryCollector = field(repr=False)
    prior_bootstrap: CapturedIndexInventory | None = field(repr=False)
    preservation: "PreservedDeployment" = field(repr=False)
    source_origin: _SourceOrigin = field(repr=False)


class NativeSecurityInventory:
    def __init__(self, context: "NativeControlContext") -> None:
        try:
            from ai_workshop.labs.rag.indexing.access_epoch_control_native import (
                NativeControlContext,
            )
            from ai_workshop.labs.rag.indexing.access_epoch_route_commands import (
                NativeRouteCommands,
            )

            if type(context) is not NativeControlContext:
                raise _denied()
            # Retained source checks include current local configuration reads;
            # no control submission or network observation is performed here.
            context.assert_sources()
            source, descriptor, commands = (
                context.descriptor_source,
                context.security_descriptor,
                context.route_commands,
            )
            if (
                type(source) is not OriginalSecurityDescriptorSource
                or type(descriptor) is not ObservedSecurityDescriptor
                or type(commands) is not NativeRouteCommands
                or commands.context is not context
            ):
                raise _denied()
            source.assert_issued(descriptor)
            self._context, self._source, self._descriptor, self._commands = (
                context,
                source,
                descriptor,
                commands,
            )
            self._static_signature = self._static_values()
            self._attempted: set[str] = set()
            self._issued: dict[MainSecurityCompletion, object] = {}
        except Exception:
            raise _denied() from None

    def _static_values(self) -> object:
        c = self._context
        prepared = c._preflight_sources
        if prepared is None:
            raise _denied()
        # Primitive pins only; _static separately retains both full source guards.
        return (
            id(self),
            id(c),
            id(c._settings),
            id(c._repository),
            id(c._original),
            id(c._observation),
            id(c._namespace_source),
            id(c._namespace),
            id(c._security_source),
            id(c._absence),
            id(prepared.source),
            id(prepared.descriptor),
            id(prepared.commands),
            _seal(c._claim),
            _seal(self._descriptor),
        )

    def _static(self) -> None:
        if self._static_signature != self._static_values():
            raise _denied()
        self._context.assert_sources()
        self._source.assert_issued(self._descriptor)

    @property
    def context(self) -> "NativeControlContext":
        try:
            self._static()
            return self._context
        except Exception:
            raise _denied() from None

    @staticmethod
    def _inventory_values(
        value: CapturedIndexInventory, issuer: RecordedInventoryCollector
    ) -> object:
        """Pure fixed-point snapshot; actual issuer assertions remain separate."""
        if (
            type(value) is not CapturedIndexInventory
            or type(issuer) is not RecordedInventoryCollector
            or type(value.physical) is not CapturedPhysicalInventory
        ):
            raise _denied()
        return (
            _seal((value.nonce, value.parent_action_id, value.phase)),
            _seal((value.cluster_bytes, value.identity_bytes, value.nodes_bytes)),
            issuer._signature(value),
            issuer._physical_signature(value.physical),
        )

    def _objects(self, phase: str, collector: RecordedInventoryCollector) -> tuple[object, ...]:
        c = self.context
        c.assert_preflight_sources()
        c.assert_owned()
        prepared = c._preflight_sources
        if prepared is None:
            raise _denied()
        if type(phase) is not str or phase not in {"bootstrap", "final"}:
            raise _denied()
        if c.security_inventory_issuer is not self:
            raise _denied()
        from ai_workshop.infrastructure.local.credential_store_windows import WindowsCredentialStore
        from ai_workshop.labs.rag.indexing.access_epoch_admin_process import (
            RecordedBootstrapAdministrator,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_app_retirement import RecordedAppRetirement
        from ai_workshop.labs.rag.indexing.access_epoch_bootstrap import BootstrapCommands
        from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_audits import (
            RecordedBootstrapAudits,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_binding import (
            BootstrapBindingFactory,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_deployment import DeploymentCommands
        from ai_workshop.labs.rag.indexing.access_epoch_history_gate import OriginalHistoryGate
        from ai_workshop.labs.rag.indexing.access_epoch_keys import SqlAlchemyEpochKeyRepository
        from ai_workshop.labs.rag.indexing.access_epoch_tls import AccessEpochTls

        administrator, apps, bootstrap, audits = (
            c.administrator,
            c.apps,
            c.bootstrap_commands,
            c.audits,
        )
        bootstrap_factory, deployment, history = c.bootstrap_factory, c.deployment, c.history
        keys, tls, store = c.keys, c.tls, c.store
        expected = (
            (administrator, RecordedBootstrapAdministrator),
            (apps, RecordedAppRetirement),
            (bootstrap, BootstrapCommands),
            (audits, RecordedBootstrapAudits),
            (bootstrap_factory, BootstrapBindingFactory),
            (deployment, DeploymentCommands),
            (history, OriginalHistoryGate),
            (keys, SqlAlchemyEpochKeyRepository),
            (tls, AccessEpochTls),
            (store, WindowsCredentialStore),
        )
        if any(type(value) is not kind for value, kind in expected):
            raise _denied()
        app_retirement, history_ticket, credential = (
            c.app_retirement,
            c.history_ticket,
            c.credential,
        )
        admin_security, historical_security, tls_assets = (
            c.admin_security,
            c.historical_security,
            c.tls_assets,
        )
        caps = (
            app_retirement,
            history_ticket,
            credential,
            admin_security,
            historical_security,
            tls_assets,
        )
        original, original_issuer = c.original_inventory, c.original_inventory_issuer
        if any(value is None for value in caps) or original is None:
            raise _denied()
        active = c.bootstrap if phase == "bootstrap" else c.final
        epoch, owner, repository, journal, native = (
            c.epoch,
            c.held_owner,
            c.repository,
            c.journal,
            c.native,
        )
        namespace_source, namespace, security_source = (
            c.namespace_source,
            c.namespace,
            c.security_source,
        )
        if active is None or epoch is None or journal is None or native is None:
            raise _denied()
        reader = collector.reader
        factory, binding = reader.factory, reader.binding
        registered = (
            c.bootstrap_inventory_issuer if phase == "bootstrap" else c.final_inventory_issuer
        )
        if (
            registered is not collector
            or factory.repository is not repository
            or factory.journal is not journal
            or factory.epoch is not epoch
            or factory.bootstrap is not bootstrap
            or factory.tls is not tls
            or reader.native is not native
            or collector.namespace_source is not namespace_source
            or collector.namespace is not namespace
            or binding.phase != phase
            or binding.permissions is not namespace.permissions
        ):
            raise _denied()
        secure = factory._sources
        from ai_workshop.labs.rag.indexing.access_epoch_inventory_binding import _SecureSources

        if type(secure) is not _SecureSources:
            raise _denied()
        if any(
            a is not b
            for a, b in (
                (secure.keys, keys),
                (secure.deployment, deployment),
                (secure.bootstrap_factory, bootstrap_factory),
                (secure.store, store),
            )
        ):
            raise _denied()
        assert deployment is not None and bootstrap_factory is not None
        assert administrator is not None and audits is not None
        assert (
            credential is not None
            and admin_security is not None
            and historical_security is not None
        )
        if (
            apps is None
            or history is None
            or bootstrap is None
            or tls is None
            or keys is None
            or apps.repository is not repository
            or apps.journal is not journal
            or history.repository is not repository
            or history.journal is not journal
            or history.epoch is not epoch
            or apps.epoch is not epoch
            or deployment.epoch is not epoch
            or deployment.tls is not tls_assets
            or keys.parent is not repository
            or bootstrap_factory.security is not security_source
            or administrator.binding_factory is not bootstrap_factory
            or administrator.builder is not bootstrap
            or administrator.repository is not repository
            or administrator.journal is not journal
            or administrator.native is not native
            or audits.administrator is not administrator
            or audits.factory is not bootstrap_factory
            or audits.repository is not repository
            or audits.journal is not journal
            or audits.native is not native
        ):
            raise _denied()
        # Only memory primitive seals are retained within this synchronous call.
        primitive_caps = _seal((caps, active, binding, namespace))
        deployment.assert_observed(active)
        bootstrap_factory.assert_issued(bootstrap)
        administrator.assert_credential(credential)
        audits.assert_issued(admin_security)
        audits.assert_issued(historical_security)
        if type(original_issuer) is not RecordedInventoryCollector:
            raise _denied()
        original_values = self._inventory_values(original, original_issuer)
        original_issuer.assert_issued(original)
        extra: tuple[object, ...] = ()
        final_factory = final_authentication = final_auth = prior = prior_issuer = None
        final_binding = None
        final_values = prior_values = None
        if phase == "final":
            from ai_workshop.labs.rag.indexing.access_epoch_final_auth_binding import (
                FinalAuthBindingFactory,
            )
            from ai_workshop.labs.rag.indexing.access_epoch_final_auth_process import (
                RecordedFinalAuthentication,
            )

            final_factory, final_authentication, final_auth = (
                c.final_auth_factory,
                c.final_authentication,
                c.final_auth,
            )
            prior, prior_issuer = c.bootstrap_inventory, c.bootstrap_inventory_issuer
            if (
                type(final_factory) is not FinalAuthBindingFactory
                or type(final_authentication) is not RecordedFinalAuthentication
                or final_auth is None
                or prior is None
                or type(prior_issuer) is not RecordedInventoryCollector
            ):
                raise _denied()
            if (
                final_authentication.factory is not final_factory
                or final_authentication.repository is not repository
                or final_authentication.journal is not journal
                or final_authentication.native is not native
                or final_authentication.final is not active
            ):
                raise _denied()
            final_binding = final_authentication.binding
            final_values = _seal((final_auth, final_binding))
            prior_values = self._inventory_values(prior, prior_issuer)
            final_authentication.assert_issued(final_auth)
            prior_issuer.assert_issued(prior)
            extra = (
                final_factory,
                final_authentication,
                final_auth,
                final_binding,
                prior,
                prior_issuer,
            )
        c.assert_owned()
        if (
            self._context is not c
            or c._preflight_sources is not prepared
            or self._source is not prepared.source
            or self._descriptor is not prepared.descriptor
            or self._commands is not prepared.commands
            or c._security_inventory is not self
            or c._epoch is not epoch
            or c._owner is not owner
            or c._repository is not repository
            or c._journal is not journal
            or c._native is not native
            or c._namespace_source is not namespace_source
            or c._namespace is not namespace
            or c._security_source is not security_source
            or c._administrator is not administrator
            or c._apps is not apps
            or c._bootstrap_commands is not bootstrap
            or c._audits is not audits
            or c._bootstrap_factory is not bootstrap_factory
            or c._deployment is not deployment
            or c._history is not history
            or c._keys is not keys
            or c._tls is not tls
            or c._store is not store
            or c._history_ticket is not history_ticket
            or c._collectors.get(phase) is not collector
            or c._collectors.get("original") is not original_issuer
            or any(
                c._caps.get(name) is not cap
                for name, cap in (
                    ("app_retirement", app_retirement),
                    ("credential", credential),
                    ("admin_security", admin_security),
                    ("historical_security", historical_security),
                    ("tls_assets", tls_assets),
                    ("original_inventory", original),
                    ("bootstrap" if phase == "bootstrap" else "final", active),
                )
            )
            or collector.reader is not reader
            or reader.factory is not factory
            or reader.binding is not binding
            or reader.native is not native
            or collector.namespace_source is not namespace_source
            or collector.namespace is not namespace
            or factory.repository is not repository
            or factory.journal is not journal
            or factory.epoch is not epoch
            or factory.bootstrap is not bootstrap
            or factory.tls is not tls
            or factory._sources is not secure
            or cast(object, secure.keys) is not keys
            or secure.deployment is not deployment
            or secure.bootstrap_factory is not bootstrap_factory
            or cast(object, secure.store) is not store
            or binding.phase != phase
            or binding.permissions is not namespace.permissions
            or apps.repository is not repository
            or apps.journal is not journal
            or apps.epoch is not epoch
            or history.repository is not repository
            or history.journal is not journal
            or history.epoch is not epoch
            or deployment.epoch is not epoch
            or deployment.tls is not tls_assets
            or keys.parent is not repository
            or bootstrap_factory.security is not security_source
            or bootstrap_factory.repository is not repository
            or bootstrap_factory.journal is not journal
            or bootstrap_factory.deployment is not deployment
            or administrator.binding_factory is not bootstrap_factory
            or administrator.builder is not bootstrap
            or administrator.repository is not repository
            or administrator.journal is not journal
            or administrator.native is not native
            or audits.administrator is not administrator
            or audits.factory is not bootstrap_factory
            or audits.repository is not repository
            or audits.journal is not journal
            or audits.native is not native
            or primitive_caps != _seal((caps, active, binding, namespace))
            or original_values != self._inventory_values(original, original_issuer)
        ):
            raise _denied()
        if phase == "final":
            assert final_factory is not None and final_authentication is not None
            assert prior is not None and prior_issuer is not None
            if (
                c._final_auth_factory is not final_factory
                or c._final_authentication is not final_authentication
                or c._caps.get("final_auth") is not final_auth
                or c._caps.get("bootstrap_inventory") is not prior
                or c._collectors.get("bootstrap") is not prior_issuer
                or final_authentication.binding is not final_binding
                or final_authentication.factory is not final_factory
                or final_authentication.repository is not repository
                or final_authentication.journal is not journal
                or final_authentication.native is not native
                or final_authentication.final is not active
                or final_factory.repository is not repository
                or final_factory.journal is not journal
                or final_factory.deployment is not deployment
                or final_factory.tls is not tls
                or final_factory.bootstrap_factory is not bootstrap_factory
                or final_factory.bootstrap is not bootstrap
                or cast(object, final_factory.keys) is not keys
                or cast(object, final_factory.store) is not store
                or final_values != _seal((final_auth, final_binding))
                or prior_values != self._inventory_values(prior, prior_issuer)
            ):
                raise _denied()
        return (
            c,
            epoch,
            owner,
            journal,
            native,
            collector,
            reader,
            factory,
            binding,
            active,
            original,
            original_issuer,
            *(v for v, _ in expected),
            *caps,
            *extra,
        )

    @staticmethod
    def _parent(parent: ReservedCutoverAction) -> str:
        if (
            type(parent) is not ReservedCutoverAction
            or type(parent.action_id) is not UUID
            or type(parent.execution_id) is not UUID
            or type(parent.sequence) is not int
            or type(parent.kind) is not CutoverActionKind
            or parent.kind
            not in {CutoverActionKind.STOP_BOOTSTRAP, CutoverActionKind.VERIFY_ACCESS}
            or type(parent.executor_generation) is not str
        ):
            raise _denied()
        return "bootstrap" if parent.kind is CutoverActionKind.STOP_BOOTSTRAP else "final"

    async def _fresh(
        self,
        parent: ReservedCutoverAction,
        collector: RecordedInventoryCollector,
        physical: CapturedPhysicalInventory,
        phase: str,
    ) -> tuple["AccessEpochReadback", tuple[CredentialEnvelope, ...]]:
        objects = self._objects(phase, collector)
        collector.assert_physical_issued(physical)
        if physical.parent is not parent or physical.phase != phase:
            raise _denied()
        await collector.reader.revalidate(parent)
        if tuple(id(x) for x in objects) != tuple(id(x) for x in self._objects(phase, collector)):
            raise _denied()
        c = self.context
        assert c.epoch is not None and c.history is not None and c.history_ticket is not None
        await c.history.assert_verified(c.history_ticket)
        self._objects(phase, collector)
        state = await c.repository.readback(c.claim)
        self._objects(phase, collector)
        collector.reader.factory._state(state, parent, parent.kind)
        original = c.original_inventory
        assert original is not None and original.physical is not None
        row = state.actions[CUTOVER_ORDER.index(CutoverActionKind.STOP_OLD)]
        if row.action != original.physical.parent or row.outcome != "settled":
            raise _denied()
        app = state.actions[CUTOVER_ORDER.index(CutoverActionKind.STOP_REGISTERED_APPS)]
        revoke = state.actions[CUTOVER_ORDER.index(CutoverActionKind.REVOKE_HISTORICAL)]
        admin = state.actions[CUTOVER_ORDER.index(CutoverActionKind.BOOTSTRAP_ADMIN)]
        assert c.app_retirement is not None and c.historical_security is not None
        assert c.admin_security is not None and c.credential is not None
        if (
            app.manifest_json != c.app_retirement.manifest_json
            or revoke.manifest_json != c.historical_security.manifest_json
            or admin.action.action_id != c.credential.action_id
            or admin.manifest_json
            != canonical_json(
                {
                    "schema_version": 1,
                    "kind": "bootstrap_administrator_verified",
                    "action_id": str(admin.action.action_id),
                    "execution_id": str(admin.action.execution_id),
                    "executor_generation": admin.action.executor_generation,
                    "container_id": c.credential.container_id,
                    "submission_id": str(c.credential.submission_id),
                    "security": _load(c.admin_security.manifest_json.encode("utf-8")),
                }
            )
        ):
            raise _denied()
        active = c.bootstrap if phase == "bootstrap" else c.final
        assert active is not None
        issued = await (
            collector.reader.factory.create_bootstrap(parent, active)
            if phase == "bootstrap"
            else collector.reader.factory.create_final(parent, active)
        )
        self._objects(phase, collector)
        bound = collector.reader.binding
        names = (
            "phase",
            "epoch_id",
            "execution_id",
            "parent_action_id",
            "container_id",
            "permissions",
            "collector_secret",
        )
        if _seal(tuple(getattr(issued, n) for n in names)) != _seal(
            tuple(getattr(bound, n) for n in names)
        ):
            raise _denied()
        if phase == "final":
            assert c.final_auth_factory is not None and c.final is not None
            auth_binding = await c.final_auth_factory.create(c.final)
            self._objects(phase, collector)
            assert c.final_authentication is not None
            old_auth = c.final_authentication.binding
            auth_fields = ("epoch_id", "execution_id", "container_id", "permissions", "keys")
            if _seal(tuple(getattr(auth_binding, n) for n in auth_fields), identity=False) != _seal(
                tuple(getattr(old_auth, n) for n in auth_fields), identity=False
            ):
                raise _denied()
        assert c.keys is not None and c.store is not None
        key_parent = state.actions[CUTOVER_ORDER.index(CutoverActionKind.ISSUE_ROLE_KEY)]
        rows = await c.keys.read_completed(c.epoch, key_parent.action)
        self._objects(phase, collector)
        from ai_workshop.labs.rag.indexing.access_epoch_keys import KEY_ROLES

        latest = {r.action.role: r for r in rows if r.action.kind == "issue"}
        if set(latest) != set(KEY_ROLES):
            raise _denied()
        credentials = []
        for role in KEY_ROLES:
            result = latest[role].result
            if result is None:
                raise _denied()
            credential = c.store.read_prepared(
                UUID(c.epoch.binding.access_epoch_id), c.epoch.binding.ordinal, role, result.key_id
            )
            self._objects(phase, collector)
            if type(credential) is not CredentialEnvelope:
                raise _denied()
            credentials.append(credential)
        collector.assert_physical_issued(physical)
        return state, tuple(credentials)

    @staticmethod
    def _inventory_seal(
        value: CapturedIndexInventory, issuer: RecordedInventoryCollector
    ) -> object:
        # The actual collector owns the closed primitive/capture signature. Its
        # physical provenance contains opaque source objects, never generic data.
        if (
            type(value) is not CapturedIndexInventory
            or type(issuer) is not RecordedInventoryCollector
            or type(value.physical) is not CapturedPhysicalInventory
        ):
            raise _denied()
        issuer.assert_issued(value)
        issuer.assert_physical_issued(value.physical)
        return (
            CapturedIndexInventory,
            id(value),
            id(issuer),
            issuer._signature(value),
            id(value.physical),
            issuer._physical_signature(value.physical),
        )

    def _origin_seal(self, value: object, cap: MainSecurityCompletion) -> object:
        if type(value) is CapturedIndexInventory:
            if value is cap.original:
                return self._inventory_seal(value, cap.original_issuer)
            if value is cap.prior_bootstrap:
                issuer = self.context.bootstrap_inventory_issuer
                if type(issuer) is not RecordedInventoryCollector:
                    raise _denied()
                return self._inventory_seal(value, issuer)
            raise _denied()
        return _seal(value) if is_dataclass(value) else None

    def _signature(self, cap: MainSecurityCompletion) -> object:
        if type(cap.nonce) is not UUID or type(cap.source_origin) is not _SourceOrigin:
            raise _denied()
        return (
            _seal(cap.parent),
            cap.phase,
            id(cap.physical),
            _seal(cap.foreign),
            _seal(cap.security),
            id(cap.original),
            id(cap.original_issuer),
            id(cap.prior_bootstrap),
            _seal(cap.preservation),
            id(cap.source_origin),
            str(cap.nonce),
            tuple((id(x), self._origin_seal(x, cap)) for x in cap.source_origin.objects),
            _seal(cap.source_origin.credentials, identity=False),
        )

    def assert_issued(self, cap: MainSecurityCompletion) -> None:
        try:
            if type(cap) is not MainSecurityCompletion or self._issued.get(cap) != self._signature(
                cap
            ):
                raise _denied()
            objects = self._objects(cap.phase, cap.source_origin.collector)
            if any(a is not b for a, b in zip(objects, cap.source_origin.objects, strict=True)):
                raise _denied()
            cap.source_origin.collector.assert_physical_issued(cap.physical)
            cap.original_issuer.assert_issued(cap.original)
            c = self.context
            assert c.deployment is not None
            assert c.store is not None
            for credential in cap.source_origin.credentials:
                current = c.store.read_prepared(
                    credential.epoch_id, credential.ordinal, credential.role, credential.key_id
                )
                c.assert_owned()
                if _seal(current, identity=False) != _seal(credential, identity=False):
                    raise _denied()
            active = c.bootstrap if cap.phase == "bootstrap" else c.final
            assert active is not None
            if c.deployment._preserved.get(active) is not cap.preservation:
                raise _denied()
        except Exception:
            raise _denied() from None

    async def observe(
        self,
        parent: ReservedCutoverAction,
        collector: RecordedInventoryCollector,
        physical: CapturedPhysicalInventory,
    ) -> MainSecurityCompletion:
        candidate: MainSecurityCompletion | None = None
        try:
            self._static()
            phase = self._parent(parent)
            key = str(parent.action_id)
            if key in self._attempted:
                raise _denied()
            self._attempted.add(key)
            if (
                type(collector) is not RecordedInventoryCollector
                or type(physical) is not CapturedPhysicalInventory
            ):
                raise _denied()
            before, credentials = await self._fresh(parent, collector, physical, phase)
            before_signature = _seal((before, credentials), identity=False)
            c = self.context
            original, original_issuer = c.original_inventory, c.original_inventory_issuer
            assert (
                original is not None
                and original_issuer is not None
                and original.physical is not None
            )
            prior = c.bootstrap_inventory if phase == "final" else None
            passes = [dict(physical.first_packets), dict(physical.last_packets)]
            managed = tuple(e.observation.name for e in physical.rag_entries)
            unmanaged = tuple(e.name for e in physical.unmanaged_passes[1].entries)
            t = physical.topology
            decoded = [
                _decode_categories(
                    p["cluster_state"],
                    p["nodes_docs"],
                    t.cluster_uuid,
                    t.cluster_name,
                    t.stable_node_id,
                    self._descriptor,
                    managed,
                    unmanaged,
                )
                for p in passes
            ]
            _same_foreign_entries(decoded[0][0], decoded[1][0])
            if decoded[0][1] != decoded[1][1]:
                raise _denied()
            require_same_private_inventory(original.rag_entries, physical.rag_entries)
            assert original.unmanaged is not None
            require_same_unmanaged_entries(original.unmanaged, physical.unmanaged_passes[1])
            _same_foreign_entries(original.foreign, decoded[1][0])
            old_packets = (
                dict(original.physical.first_packets),
                dict(original.physical.last_packets),
            )
            for packets, (_, main) in zip(passes, decoded, strict=True):
                if (
                    main.private_physical_inventory
                    != physical.unmanaged_passes[1].private_physical_inventory
                ):
                    raise _denied()
                if prior is None:
                    for old in old_packets:
                        require_main_security_transition(
                            old["cluster_state"], packets["cluster_state"], main
                        )
                else:
                    assert prior.physical is not None and prior.unmanaged is not None
                    require_same_private_inventory(prior.rag_entries, physical.rag_entries)
                    require_same_unmanaged_entries(prior.unmanaged, physical.unmanaged_passes[1])
                    _same_foreign_entries(prior.foreign, decoded[1][0])
                    bt = prior.topology
                    prior_decoded = []
                    for p in (
                        dict(prior.physical.first_packets),
                        dict(prior.physical.last_packets),
                    ):
                        pf, bm = _decode_categories(
                            p["cluster_state"],
                            p["nodes_docs"],
                            bt.cluster_uuid,
                            bt.cluster_name,
                            bt.stable_node_id,
                            self._descriptor,
                            tuple(e.observation.name for e in prior.rag_entries),
                            tuple(e.name for e in prior.unmanaged.entries),
                        )
                        prior_decoded.append(bm)
                        _same_foreign_entries(prior.foreign, pf)
                        for old in old_packets:
                            require_main_security_transition(
                                old["cluster_state"],
                                p["cluster_state"],
                                bm,
                                final_state=packets["cluster_state"],
                                final=main,
                            )
                    if prior_decoded[0] != prior_decoded[1]:
                        raise _denied()
            active = c.bootstrap if phase == "bootstrap" else c.final
            assert active is not None and c.deployment is not None
            existing = c.deployment._preserved.get(active)
            if existing is None:
                preservation = c.deployment.decode_preservation(
                    active,
                    passes[1]["cluster_info"],
                    passes[1]["identity_state"],
                    passes[1]["nodes_info"],
                    tuple(e.observation for e in physical.rag_entries),
                    observed_at=datetime.now(UTC),
                )
            else:
                retained = (
                    c.bootstrap_preservation if phase == "bootstrap" else c.final_preservation
                )
                if retained is not existing or (
                    existing.stable_node_id,
                    existing.ephemeral_id,
                    existing.jvm_started_at,
                ) != (t.stable_node_id, t.ephemeral_id, t.jvm_start_at):
                    raise _denied()
                preservation = existing
            after, after_credentials = await self._fresh(parent, collector, physical, phase)
            if before_signature != _seal((after, after_credentials), identity=False):
                raise _denied()
            origin = _SourceOrigin(collector, self._objects(phase, collector), after_credentials)
            candidate = MainSecurityCompletion(
                uuid4(),
                parent,
                phase,
                physical,
                decoded[1][0],
                decoded[1][1],
                original,
                original_issuer,
                prior,
                preservation,
                origin,
            )
            self._issued[candidate] = self._signature(candidate)
            self.assert_issued(candidate)
            return candidate
        except BaseException as exc:
            if candidate is not None:
                self._issued.pop(candidate, None)
            if isinstance(exc, Exception):
                raise _denied() from None
            raise
