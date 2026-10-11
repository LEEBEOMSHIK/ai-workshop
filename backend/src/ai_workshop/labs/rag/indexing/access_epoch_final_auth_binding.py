"""Bind final checks to settled role ledger and actual protected credentials.

No caller key tuple, boolean or public JSON can mint this capability. Creating a
binding does not submit a command or settle the final verification action.
"""

from hashlib import sha256
from typing import Protocol
from uuid import UUID, uuid4

from ai_workshop.infrastructure.search.access_credentials import CredentialEnvelope, ServiceRole
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap import (
    BootstrapCommands,
    BootstrapIssuedKey,
)
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_binding import BootstrapBindingFactory
from ai_workshop.labs.rag.indexing.access_epoch_deployment import (
    PROJECT_ROOT,
    DeploymentCommands,
    ObservedDeployment,
)
from ai_workshop.labs.rag.indexing.access_epoch_final_auth import FinalAuthBinding
from ai_workshop.labs.rag.indexing.access_epoch_keys import KEY_ROLES, KeyActionReadback
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
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
    return ValueError("final_auth_binding_unverified")


class CompletedKeyReadPort(Protocol):
    parent: ReservationReadPort

    async def read_completed(
        self, epoch: PreparedAccessEpoch, parent: ReservedCutoverAction
    ) -> tuple[KeyActionReadback, ...]: ...


class PreparedCredentialReadPort(Protocol):
    def read_prepared(
        self, epoch: UUID, ordinal: int, role: ServiceRole, key_id: str
    ) -> CredentialEnvelope: ...


class FinalAuthBindingFactory:
    def __init__(
        self,
        repository: ReservationReadPort,
        keys: CompletedKeyReadPort,
        journal: ProtectedControlJournal,
        deployment: DeploymentCommands,
        bootstrap_factory: BootstrapBindingFactory,
        bootstrap: BootstrapCommands,
        tls: AccessEpochTls,
        store: PreparedCredentialReadPort,
    ) -> None:
        self.repository, self.keys, self.journal, self.deployment = (
            repository,
            keys,
            journal,
            deployment,
        )
        self.bootstrap_factory, self.bootstrap, self.tls, self.store = (
            bootstrap_factory,
            bootstrap,
            tls,
            store,
        )
        self._issued: dict[FinalAuthBinding, FinalAuthBinding] = {}
        self._owned()

    def _owned(self) -> None:
        self.journal._owned()
        if (
            self.journal.root != PROJECT_ROOT
            or self.bootstrap_factory.repository is not self.repository
            or self.keys.parent is not self.repository
            or self.bootstrap_factory.journal is not self.journal
            or self.bootstrap_factory.deployment is not self.deployment
            or self.deployment.epoch.binding.execution_id != str(self.journal.owner.execution_id)
        ):
            raise _denied()
        self.bootstrap_factory.assert_issued(self.bootstrap)

    def _state(self, state: AccessEpochReadback, final: ObservedDeployment) -> None:
        self._owned()
        self.deployment.assert_observed(final)
        if (
            final.kind != CutoverActionKind.START_SECURED
            or state.prepared != self.deployment.epoch
            or state.executor_generation != self.journal.owner.executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or state.phase != "secured_started"
            or len(state.actions) not in {len(CUTOVER_ORDER) - 1, len(CUTOVER_ORDER)}
            or tuple(x.action.kind for x in state.actions) != CUTOVER_ORDER[: len(state.actions)]
        ):
            raise _denied()
        sequence = 0
        for i, row in enumerate(state.actions):
            if (
                type(row.action.sequence) is not int
                or type(row.event_sequence) is not int
                or type(row.action.expected.preceding_sequence) is not int
                or row.action.execution_id != self.journal.owner.execution_id
                or row.action.executor_generation != self.journal.owner.executor_generation
                or row.action.sequence != sequence + 1
                or row.action.expected.preceding_sequence != sequence
                or row.outcome not in {"settled", "pending", "unknown"}
                or row.outcome != "settled"
                and i != len(CUTOVER_ORDER) - 1
                or row.outcome == "settled"
                and (row.manifest_json is None or row.event_sequence <= row.action.sequence)
                or row.outcome == "pending"
                and (row.manifest_json is not None or row.event_sequence != row.action.sequence)
                or row.outcome == "unknown"
                and row.event_sequence <= row.action.sequence
            ):
                raise _denied()
            sequence = row.event_sequence
        started = state.actions[CUTOVER_ORDER.index(CutoverActionKind.START_SECURED)]
        if (
            started.action.action_id != final.action_id
            or started.manifest_json != final.manifest_json
        ):
            raise _denied()

    async def create(self, final: ObservedDeployment) -> FinalAuthBinding:
        try:
            self._owned()
            epoch = self.deployment.epoch
            before = await self.repository.readback(epoch.binding.claim)
            self._state(before, final)
            tls_row = before.actions[CUTOVER_ORDER.index(CutoverActionKind.PREPARE_TLS)]
            material = await self.tls.read_settled(tls_row.action)
            self._owned()
            self.tls.assert_issued(material)
            if material.manifest_json != self.deployment.tls.manifest_json:
                raise _denied()
            parent = before.actions[CUTOVER_ORDER.index(CutoverActionKind.ISSUE_ROLE_KEY)]
            rows = await self.keys.read_completed(epoch, parent.action)
            self._owned()
            if type(rows) is not tuple or any(
                x.outcome != "settled" or x.result is None for x in rows
            ):
                raise _denied()
            latest = {x.action.role: x for x in rows if x.action.kind == "issue"}
            if set(latest) != set(KEY_ROLES):
                raise _denied()
            bindings = []
            group: dict[str, object] = {
                "schema_version": 1,
                "execution_id": str(parent.action.execution_id),
                "parent_action_id": str(parent.action.action_id),
                "keys": {},
                "issuances": {},
                "permissions": {},
            }
            key_ids, issuances, descriptors = {}, {}, {}
            for role in KEY_ROLES:
                row = latest[role]
                result = row.result
                if result is None:
                    raise _denied()
                descriptor = sha256(
                    canonical_json(self.bootstrap.permissions_descriptor(role)).encode()
                ).hexdigest()
                if (
                    result.result != "issued"
                    or result.role != role
                    or row.action.role != role
                    or row.action.parent_action_id != parent.action.action_id
                    or row.action.execution_id != self.journal.owner.execution_id
                    or row.action.executor_generation != self.journal.owner.executor_generation
                    or result.issuance_id != row.action.issuance_id
                    or row.action.permissions_sha256 != descriptor
                    or result.permissions_sha256 != descriptor
                ):
                    raise _denied()
                envelope = self.store.read_prepared(
                    UUID(epoch.binding.access_epoch_id), epoch.binding.ordinal, role, result.key_id
                )
                self._owned()
                if (
                    type(envelope) is not CredentialEnvelope
                    or envelope.epoch_id != UUID(epoch.binding.access_epoch_id)
                    or type(envelope.ordinal) is not int
                    or envelope.ordinal != epoch.binding.ordinal
                    or envelope.role != role
                    or envelope.key_id != result.key_id
                ):
                    raise _denied()
                key_ids[role], issuances[role], descriptors[role] = (
                    result.key_id,
                    str(row.action.issuance_id),
                    descriptor,
                )
                bindings.append(
                    BootstrapIssuedKey(
                        result.key_id,
                        f"ai-workshop-{envelope.epoch_id}-{role}-{row.action.issuance_id}",
                        envelope.epoch_id,
                        row.action.issuance_id,
                        role,
                        envelope.secret,
                    )
                )
            group.update(keys=key_ids, issuances=issuances, permissions=descriptors)
            if len(set(key_ids.values())) != 3 or canonical_json(group) != parent.manifest_json:
                raise _denied()
            after = await self.repository.readback(epoch.binding.claim)
            self._state(after, final)
            if before != after:
                raise _denied()
            binding = FinalAuthBinding(
                uuid4(),
                UUID(epoch.binding.access_epoch_id),
                final.execution_id,
                final.container_id,
                self.bootstrap.permissions,
                tuple(bindings),
            )
            self._issued[binding] = binding
            return binding
        except Exception:
            raise _denied() from None

    def assert_issued(self, binding: FinalAuthBinding) -> None:
        try:
            self._owned()
            if type(binding) is not FinalAuthBinding or self._issued.get(binding) is not binding:
                raise _denied()
        except Exception:
            raise _denied() from None
