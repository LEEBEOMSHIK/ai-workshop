"""Internal pending VERIFY producer, never complete operational support.

Owns actual prepared sources and route results. The later complete native
assembly must retain this same issuer; no partial final facade is exposed.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from ai_workshop.config import Settings
from ai_workshop.labs.rag.indexing.access_epoch_control_native import (
    NativeControlContext,
    _freeze,
    _none,
    _PreepochSources,
)
from ai_workshop.labs.rag.indexing.access_epoch_deployment import DeploymentCommands
from ai_workshop.labs.rag.indexing.access_epoch_final_auth_binding import FinalAuthBindingFactory
from ai_workshop.labs.rag.indexing.access_epoch_final_auth_process import (
    RecordedFinalAuthentication,
)
from ai_workshop.labs.rag.indexing.access_epoch_inventory_collection import (
    RecordedInventoryCollector,
)
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_namespace_source import (
    OriginalNamespaceSource,
    _unmanaged_signature,
)
from ai_workshop.labs.rag.indexing.access_epoch_namespace_source import (
    _signature as _namespace_signature,
)
from ai_workshop.labs.rag.indexing.access_epoch_native import (
    OriginalAccessEpochPreflight,
    OriginalDeploymentObservation,
    _observation_signature,
)
from ai_workshop.labs.rag.indexing.access_epoch_original_security import (
    ObservedOriginalSecurityAbsent,
    OriginalSecurityAbsenceReader,
)
from ai_workshop.labs.rag.indexing.access_epoch_repository import SqlAlchemyAccessEpochRepository
from ai_workshop.labs.rag.indexing.access_epoch_route_commands import (
    NativeRouteCommands,
    PinnedRouteRuntime,
)
from ai_workshop.labs.rag.indexing.access_epoch_route_process import (
    RecordedNativeRoutes,
    VerifiedNativeRoutes,
)
from ai_workshop.labs.rag.indexing.access_epoch_security_descriptor_source import (
    OriginalSecurityDescriptorSource,
    _capture_signature,
    _settings_signature,
)
from ai_workshop.labs.rag.indexing.access_epoch_security_descriptor_source import (
    _signature as _descriptor_signature,
)
from ai_workshop.labs.rag.indexing.access_epoch_security_inventory_native import (
    NativeSecurityInventory,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    ReservedCutoverAction,
    canonical_json,
)


def _denied() -> ValueError:
    return ValueError("native_pending_denied")


def _digest(value: str) -> str:
    if type(value) is not str or canonical_json(json.loads(value)) != value:
        raise _denied()
    return hashlib.sha256(value.encode()).hexdigest()


def _time(value: datetime) -> str:
    if type(value) is not datetime or value.utcoffset() != UTC.utcoffset(None):
        raise _denied()
    return value.isoformat(timespec="microseconds")


@dataclass(frozen=True, slots=True, eq=False)
class VerifiedNativeAccess:
    nonce: UUID
    parent: ReservedCutoverAction
    manifest_json: str
    observed_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class _Issued:
    signature: object
    graph: object
    route_source: RecordedNativeRoutes
    route_observation: VerifiedNativeRoutes


# One live context owns one verifier/route producer. Failed attempts cannot be
# bypassed by constructing a new producer object; no process-crash hydration.
_LIVE: dict[NativeControlContext, "NativePendingVerification"] = {}


class NativePendingVerification:
    def __init__(self, context: NativeControlContext) -> None:
        try:
            if type(context) is not NativeControlContext:
                raise _denied()
            if context in _LIVE:
                raise _denied()
            self._context = context
            self._identity = id(self)
            prepared = context._preflight_sources
            if type(prepared) is not _PreepochSources:
                raise _denied()
            self._commands = prepared.commands
            self._security = context._security_inventory
            if (
                type(self._commands) is not NativeRouteCommands
                or self._commands.context is not context
                or type(self._security) is not NativeSecurityInventory
                or self._security._context is not context
            ):
                raise _denied()
            self._static_signature = self._static_values()
            self._routes: RecordedNativeRoutes | None = None
            self._issued: dict[VerifiedNativeAccess, _Issued] = {}
            self._poisoned: set[str] = set()
            self._running = False
            _LIVE[context] = self
            self._static()
        except BaseException as error:
            if type(context) is NativeControlContext and _LIVE.get(context) is self:
                _LIVE.pop(context, None)
            if isinstance(error, Exception):
                raise _denied() from None
            raise

    def _static_values(self) -> object:
        c, commands = self._context, self._commands
        if type(commands) is not NativeRouteCommands:
            raise _denied()
        support = commands._support
        prepared = c._preflight_sources
        namespace = c._namespace_source
        if (
            type(c._settings) is not Settings
            or type(c._repository) is not SqlAlchemyAccessEpochRepository
            or type(c._original) is not OriginalAccessEpochPreflight
            or type(c._observation) is not OriginalDeploymentObservation
            or type(namespace) is not OriginalNamespaceSource
            or type(c._security_source) is not OriginalSecurityAbsenceReader
            or type(c._absence) is not ObservedOriginalSecurityAbsent
            or type(prepared) is not _PreepochSources
            or type(prepared.source) is not OriginalSecurityDescriptorSource
            or c._preflight_failed is not False
            or c._preflight_failed_signature != _freeze(False)
            or c._source_signature != c._signature()
            or c._preflight_signature != c._preflight_value_signature(prepared)
            or prepared.commands is not commands
            or commands.context is not c
            or c._security_inventory is not self._security
            or c._security_inventory_signature != (type(self._security), id(self._security))
            or self._security is None
            or self._security._context is not c
            or c._original.settings is not c._settings
            or c._original._observed.get(c._observation) != _observation_signature(c._observation)
            or namespace.settings is not c._settings
            or namespace.original is not c._original
            or namespace.observation is not c._observation
            or any(
                a is not b
                for a, b in zip(
                    namespace._sources, (c._settings, c._original, c._observation), strict=True
                )
            )
            or namespace._issued.get(c._namespace) != _namespace_signature(c._namespace)
            or c._security_source.identity is not c._original
            or c._security_source._issued.get(c._absence) != c._absence.manifest_json
            or c._absence.original != c._observation.identity
            or prepared.source.settings is not c._settings
            or prepared.source.original is not c._original
            or prepared.source.observation is not c._observation
            or prepared.source.process is not prepared.native
            or prepared.source._settings != _settings_signature(c._settings)
            or prepared.source._issued.get(prepared.descriptor)
            != _descriptor_signature(prepared.descriptor)
            or len(prepared.source._captures[prepared.descriptor]) != 5
            or prepared.source._capture_signatures.get(prepared.descriptor)
            != _capture_signature(prepared.source._captures[prepared.descriptor])
        ):
            raise _denied()
        # The actual descriptor issuer checks its retained native process and
        # original reader/executor links without performing external I/O.
        _none(prepared.source.assert_issued, prepared.descriptor)
        unmanaged = namespace._companions[c._namespace]
        namespace._assert_pair(c._namespace, unmanaged)  # Pure registry/primitive check.
        if (
            type(support) is not PinnedRouteRuntime
            or commands._support_started is not True
            or commands._support_failed is not False
            or commands._support_signature != _freeze(support)
            or commands._support_issued.get(support) != _freeze(support)
            or commands._template_signature != commands._templates()
        ):
            raise _denied()
        return (
            self._identity,
            id(self),
            id(c),
            id(c._repository),
            id(c._settings),
            id(c._original),
            id(c._observation),
            id(namespace),
            id(c._namespace),
            id(c._security_source),
            id(c._absence),
            id(prepared.source),
            id(prepared.descriptor),
            id(unmanaged),
            _unmanaged_signature(unmanaged),
            id(commands),
            id(support),
            id(c._security_inventory),
            _freeze(c._claim),
            _freeze(support),
            _settings_signature(c._settings),
        )

    def _static(self) -> None:
        try:
            if (
                self._identity != id(self)
                or self._static_signature != self._static_values()
                or _LIVE.get(self._context) is not self
            ):
                raise _denied()
        except Exception:
            raise _denied() from None

    @property
    def context(self) -> NativeControlContext:
        self._static()
        return self._context

    def assert_prepared(self) -> None:
        """Memory-only source association; no runtime/operational readiness."""
        self._static()

    def _graph(self) -> tuple[object, ...]:
        self._static()
        c = self._context
        c.assert_preflight_sources()
        c.assert_owned()
        deployment, factory, auth = c.deployment, c.final_auth_factory, c.final_authentication
        collector = c.final_inventory_issuer
        final, observation, inventory = c.final, c.final_auth, c.final_inventory
        security, preservation = c.final_security_inventory, c.final_preservation
        bootstrap, bootstrap_security, original = (
            c.bootstrap_inventory,
            c.bootstrap_security_inventory,
            c.original_inventory,
        )
        assets, repository, journal, native = c.tls_assets, c.repository, c.journal, c.native
        tls, store, keys, epoch, owner = c.tls, c.store, c.keys, c.epoch, c.held_owner
        if (
            type(deployment) is not DeploymentCommands
            or type(factory) is not FinalAuthBindingFactory
            or type(auth) is not RecordedFinalAuthentication
            or type(collector) is not RecordedInventoryCollector
            or final is None
            or observation is None
            or inventory is None
            or security is None
            or preservation is None
            or bootstrap is None
            or bootstrap_security is None
            or original is None
            or assets is None
            or tls is None
            or store is None
            or epoch is None
            or inventory.physical is not security.physical
            or security.source_origin.collector is not collector
            or security.preservation is not preservation
            or auth.final is not final
            or auth.factory is not factory
            or auth.repository is not repository
            or auth.journal is not journal
            or auth.native is not native
            or factory.repository is not repository
            or factory.deployment is not deployment
            or factory.tls is not tls
            or cast(object, factory.store) is not store
            or cast(object, factory.keys) is not keys
        ):
            raise _denied()
        binding = auth.binding
        security_issuer = self._security
        assert security_issuer is not None
        issuers = tuple(c._collectors[phase] for phase in ("original", "bootstrap", "final"))
        inventories = (original, bootstrap, inventory)
        caps = (
            ("final", final),
            ("final_auth", observation),
            ("final_inventory", inventory),
            ("final_security_inventory", security),
            ("final_preservation", preservation),
            ("bootstrap_inventory", bootstrap),
            ("bootstrap_security_inventory", bootstrap_security),
            ("original_inventory", original),
            ("tls_assets", assets),
        )

        def links() -> object:
            # Synchronous identity fixed point only; no additional issuer traversal.
            context_refs = (
                c._epoch,
                c._owner,
                c._repository,
                c._journal,
                c._native,
                c._tls,
                c._store,
                c._keys,
                c._deployment,
                c._final_auth_factory,
                c._final_authentication,
                c._security_inventory,
            )
            factory_refs = (
                auth.factory,
                auth.final,
                auth.repository,
                auth.journal,
                auth.native,
                auth.binding,
                factory.repository,
                factory.journal,
                factory.deployment,
                factory.tls,
                factory.store,
                factory.keys,
                factory.bootstrap_factory,
                factory.bootstrap,
                factory.bootstrap_factory.repository,
                factory.bootstrap_factory.journal,
                factory.bootstrap_factory.deployment,
                factory.keys.parent,
                tls.epoch,
                tls.repository,
                tls.journal,
                tls.bundles,
                store.files,
                store.protection,
            )
            reader_refs: list[object] = []
            for phase, issuer in zip(("original", "bootstrap", "final"), issuers, strict=True):
                reader = issuer.reader
                source = reader.factory
                if (
                    reader.commands.binding is not reader.binding
                    or reader.commands.issuer is not source
                ):
                    raise _denied()
                reader_refs.extend(
                    (
                        c._collectors.get(phase),
                        issuer.reader,
                        issuer._reader,
                        issuer._binding,
                        issuer.namespace_source,
                        issuer.namespace,
                        issuer._unmanaged,
                        reader.factory,
                        reader.binding,
                        reader.repository,
                        reader.journal,
                        reader.native,
                        reader.commands,
                        reader.commands.binding,
                        reader.commands.issuer,
                        source.epoch,
                        source.repository,
                        source.journal,
                        source.permissions,
                        source._sources,
                    )
                )
            return (
                tuple((type(x), id(x)) for x in context_refs + factory_refs + tuple(reader_refs)),
                tuple((name, type(c._caps.get(name)), id(c._caps.get(name))) for name, _ in caps),
                tuple((type(value), id(value)) for value in security.source_origin.objects),
                id(security.source_origin),
                id(bootstrap_security.source_origin),
                id(bootstrap_security.source_origin.collector),
                _freeze(tuple(issuer.reader.factory._sources for issuer in issuers)),
                _freeze(tuple(issuer.reader.binding for issuer in issuers)),
                _freeze((tls._owner, tls._root, tls._epoch_id, tls._base, store.root)),
                tuple(
                    (
                        id(issuer._secure.get(value)),
                        _freeze(issuer._secure.get(value)),
                        _freeze(issuer._secure_signatures.get(value)),
                    )
                    for issuer, value in zip(issuers[1:], inventories[1:], strict=True)
                ),
            )

        def values() -> object:
            # Existing pure collector signatures preserve private bytes and nested identities.
            return (
                _freeze(
                    (
                        epoch,
                        owner,
                        binding,
                        final,
                        observation,
                        assets,
                        preservation,
                        security,
                        bootstrap_security,
                    )
                ),
                tuple(
                    security_issuer._inventory_values(value, issuer)
                    for value, issuer in zip(inventories, issuers, strict=True)
                ),
            )

        before_links, before_values = links(), values()
        factory.assert_issued(binding)
        auth.assert_issued(observation)
        collector.assert_issued(inventory)
        security_issuer.assert_issued(security)
        deployment.assert_observed(final)
        tls.assert_issued(assets)
        material = tuple(tls._read(Path(path)) for path in assets.leaf_locations)
        if len(material) != 6 or any(type(x) is not bytes or not x for x in material):
            raise _denied()
        credentials = tuple(
            store.read_prepared(key.epoch_id, epoch.binding.ordinal, key.role, key.key_id)
            for key in binding.keys
        )
        if any(x is None for x in credentials):
            raise _denied()
        c.assert_owned()
        self._static()
        if (
            any(c._caps.get(name) is not cap for name, cap in caps)
            or c._collectors.get("final") is not collector
            or c._epoch is not epoch
            or c._owner is not owner
            or c._repository is not repository
            or c._journal is not journal
            or c._native is not native
            or c._tls is not tls
            or c._store is not store
            or c._keys is not keys
            or c._deployment is not deployment
            or c._final_auth_factory is not factory
            or c._final_authentication is not auth
            or auth.binding is not binding
            or links() != before_links
            or values() != before_values
        ):
            raise _denied()
        return (
            id(epoch),
            id(owner),
            id(journal),
            id(native),
            id(store),
            id(keys),
            id(tls),
            id(deployment),
            id(factory),
            id(auth),
            id(collector),
            id(original),
            id(bootstrap),
            id(inventory),
            id(security),
            id(preservation),
            id(observation),
            _freeze(final),
            _freeze(preservation),
            _freeze(observation),
            _freeze(binding),
            _freeze(assets),
            _freeze(credentials),
            material,
        )

    async def _state(self, parent: ReservedCutoverAction) -> Any:
        if (
            type(parent) is not ReservedCutoverAction
            or type(parent.kind) is not CutoverActionKind
            or parent.kind != CutoverActionKind.VERIFY_ACCESS
            or type(parent.action_id) is not UUID
            or type(parent.execution_id) is not UUID
            or type(parent.sequence) is not int
            or type(parent.executor_generation) is not str
            or type(parent.expected) is not ControlExpectedIdentity
            or type(parent.expected.preceding_sequence) is not int
        ):
            raise _denied()
        self._graph()
        c = self._context
        state = await c.revalidate()
        self._graph()
        if (
            type(parent) is not ReservedCutoverAction
            or type(parent.kind) is not CutoverActionKind
            or parent.kind != CutoverActionKind.VERIFY_ACCESS
            or type(parent.action_id) is not UUID
            or type(parent.execution_id) is not UUID
            or type(parent.sequence) is not int
            or type(parent.executor_generation) is not str
            or state.phase != "secured_started"
            or len(state.actions) != len(CUTOVER_ORDER)
            or tuple(r.action.kind for r in state.actions) != CUTOVER_ORDER
            or _freeze(state.actions[-1].action) != _freeze(parent)
            or state.actions[-1].outcome not in {"pending", "unknown"}
            or any(r.outcome != "settled" for r in state.actions[:-1])
        ):
            raise _denied()
        for row in state.actions:
            _time(row.observed_at)
            if row.observed_at > datetime.now(UTC):
                raise _denied()
            if row.outcome == "settled":
                if row.manifest_json is None:
                    raise _denied()
                _digest(row.manifest_json)
        graph = _freeze(self._graph())
        assert c.final_auth_factory is not None and c.final is not None
        assert c.final_authentication is not None
        fresh = await c.final_auth_factory.create(c.final)
        self._graph()
        c.final_auth_factory.assert_issued(fresh)
        retained = c.final_authentication.binding
        if _freeze(
            (fresh.epoch_id, fresh.execution_id, fresh.container_id, fresh.permissions, fresh.keys)
        ) != _freeze(
            (
                retained.epoch_id,
                retained.execution_id,
                retained.container_id,
                retained.permissions,
                retained.keys,
            )
        ):
            raise _denied()
        after = await c.revalidate()
        self._graph()
        if _freeze(after) != _freeze(state) or graph != _freeze(self._graph()):
            raise _denied()
        return state

    def _manifest(
        self, parent: ReservedCutoverAction, state: Any, routes: VerifiedNativeRoutes, now: datetime
    ) -> str:
        c = self._context
        assert c.epoch is not None and c.final is not None and c.final_inventory is not None
        assert c.final_auth is not None and c.tls_assets is not None
        assert c.final_preservation is not None and c.final_security_inventory is not None
        main, physical = c.final_security_inventory.security, c.final_inventory
        assert physical.unmanaged is not None
        return canonical_json(
            {
                "schema_version": 1,
                "kind": "native_final_access",
                "epoch_id": c.epoch.binding.access_epoch_id,
                "execution_id": str(parent.execution_id),
                "executor_generation": parent.executor_generation,
                "parent_action_id": str(parent.action_id),
                "parent_sequence": parent.sequence,
                "snapshot_sha256": c.claim.snapshot.sha256,
                "original_deployment_sha256": c.observation.identity.deployment_sha256,
                "final_container_id": c.final.container_id,
                "cluster_uuid": physical.topology.cluster_uuid,
                "stable_node_id": physical.topology.stable_node_id,
                "ephemeral_id": physical.topology.ephemeral_id,
                "jvm_start_at": _time(physical.topology.jvm_start_at),
                "issued_at": _time(now),
                "final_deployment_manifest_sha256": _digest(c.final.manifest_json),
                "tls_public_manifest_sha256": _digest(c.tls_assets.manifest_json),
                "authentication_manifest_sha256": _digest(c.final_auth.manifest_json),
                "preservation_manifest_sha256": _digest(c.final_preservation.manifest_json),
                "route_policy_sha256": _digest(routes.manifest_json),
                "inventory": {
                    "category_counts": {
                        "managed": len(physical.rag_entries),
                        "unmanaged": len(physical.unmanaged.entries),
                        "foreign": len(physical.foreign.entries),
                        "security": 1,
                    },
                    "security_index": {
                        "name": main.name,
                        "uuid": main.uuid,
                        "lucene_live_docs": main.count,
                    },
                },
                "prior_settled_actions": [
                    {
                        "action_id": str(row.action.action_id),
                        "kind": row.action.kind.value,
                        "sequence": row.action.sequence,
                        "event_sequence": row.event_sequence,
                        "manifest_sha256": _digest(row.manifest_json),
                        "observed_at": _time(row.observed_at),
                    }
                    for row in state.actions[:-1]
                ],
            }
        )

    def assert_issued(self, cap: VerifiedNativeAccess) -> None:
        try:
            if type(cap) is not VerifiedNativeAccess or cap not in self._issued:
                raise _denied()
            issued = self._issued[cap]
            if issued.signature != _freeze(cap) or issued.graph != _freeze(self._graph()):
                raise _denied()
            if self._routes is not issued.route_source:
                raise _denied()
            issued.route_source.assert_issued(issued.route_observation)
        except Exception:
            raise _denied() from None

    def route_source(self, cap: VerifiedNativeAccess) -> RecordedNativeRoutes:
        self.assert_issued(cap)
        return self._issued[cap].route_source

    def route_observation(self, cap: VerifiedNativeAccess) -> VerifiedNativeRoutes:
        self.assert_issued(cap)
        return self._issued[cap].route_observation

    async def verify(
        self, context: NativeControlContext, parent: ReservedCutoverAction
    ) -> VerifiedNativeAccess:
        candidate: VerifiedNativeAccess | None = None
        key = str(parent.action_id) if type(parent) is ReservedCutoverAction else "malformed"
        if self._running or key in self._poisoned:
            raise _denied()
        self._running = True
        try:
            if context is not self._context:
                raise _denied()
            before = await self._state(parent)
            graph = _freeze(self._graph())
            if self._routes is None:
                assert self._commands is not None
                self._routes = RecordedNativeRoutes(context, self._commands)
            routes = await self._routes.observe(parent)
            self._routes.assert_issued(routes)
            after = await self._state(parent)
            if _freeze(before) != _freeze(after) or graph != _freeze(self._graph()):
                raise _denied()
            now = datetime.now(UTC)
            if now < routes.observed_at or now < after.actions[-1].observed_at:
                raise _denied()
            candidate = VerifiedNativeAccess(
                uuid4(), parent, self._manifest(parent, after, routes, now), now
            )
            self._issued[candidate] = _Issued(_freeze(candidate), graph, self._routes, routes)
            self.assert_issued(candidate)
            return candidate
        except BaseException as error:
            self._poisoned.add(key)
            if candidate is not None:
                self._issued.pop(candidate, None)
            if isinstance(error, Exception):
                raise _denied() from None
            raise
        finally:
            self._running = False
