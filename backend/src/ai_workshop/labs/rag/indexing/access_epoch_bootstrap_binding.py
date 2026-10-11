"""Compose bootstrap grammar from issued observations and current committed state.

This grants no submission ticket and does not generate passwords or API keys.
"""

import hashlib
import json
from uuid import UUID

from ai_workshop.labs.rag.indexing.access_epoch_bootstrap import (
    BootstrapBinding,
    BootstrapCommands,
)
from ai_workshop.labs.rag.indexing.access_epoch_deployment import (
    PROJECT_ROOT,
    DeploymentCommands,
    ObservedDeployment,
)
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_original_security import (
    ObservedOriginalSecurityAbsent,
    OriginalSecurityAbsenceReader,
)
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.access_epoch_process import ReservationReadPort
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_types import CutoverActionKind
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import DOCKER_EXE


def _denied() -> ValueError:
    return ValueError("bootstrap_binding_unverified")


class BootstrapBindingFactory:
    def __init__(
        self,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        deployment: DeploymentCommands,
        security: OriginalSecurityAbsenceReader,
    ) -> None:
        self.repository, self.journal = repository, journal
        self.deployment, self.security = deployment, security
        self._issued: dict[BootstrapCommands, BootstrapBinding] = {}

    def _owned(self) -> None:
        self.journal.lock.assert_owned(self.journal.owner)
        if (
            self.journal.root != PROJECT_ROOT
            or str(self.journal.owner.execution_id) != self.deployment.epoch.binding.execution_id
            or self.journal.lock.scope_sha256
            != hashlib.sha256(
                json.dumps([self.deployment.epoch.original.daemon_sha256, "ai-workshop"]).encode()
            ).hexdigest()
        ):
            raise _denied()

    async def create(
        self,
        bootstrap: ObservedDeployment,
        absence: ObservedOriginalSecurityAbsent,
        permissions: AccessEpochPermissions,
    ) -> BootstrapCommands:
        try:
            self._owned()
            epoch = self.deployment.epoch
            self.deployment.assert_observed(bootstrap)
            self.security.assert_original(absence, epoch.original)
            if (
                bootstrap.kind != CutoverActionKind.START_BOOTSTRAP
                or str(bootstrap.execution_id) != epoch.binding.execution_id
                or type(permissions) is not AccessEpochPermissions
            ):
                raise _denied()
            state = await self.repository.readback(epoch.binding.claim)
            self._owned()
            if (
                state.prepared != epoch
                or state.executor_generation != self.journal.owner.executor_generation
                or state.operation_state != "open"
                or state.gate_state != "frozen"
                or state.receipt is not None
                or state.phase in {None, "verified", "receipted"}
                or not state.actions
                or len(state.actions) > CUTOVER_ORDER.index(CutoverActionKind.STOP_BOOTSTRAP)
                or tuple(x.action.kind for x in state.actions)
                != CUTOVER_ORDER[: len(state.actions)]
            ):
                raise _denied()
            sequence = 0
            for i, row in enumerate(state.actions):
                if (
                    row.action.execution_id != self.journal.owner.execution_id
                    or row.action.executor_generation != self.journal.owner.executor_generation
                    or row.action.sequence <= sequence
                    or row.outcome not in {"settled", "pending", "unknown"}
                    or row.outcome != "settled"
                    and i != len(state.actions) - 1
                    or row.outcome == "settled"
                    and row.manifest_json is None
                ):
                    raise _denied()
                sequence = row.event_sequence
            started = [x for x in state.actions if x.action.action_id == bootstrap.action_id]
            if (
                len(started) != 1
                or started[0].action.kind != CutoverActionKind.START_BOOTSTRAP
                or started[0].outcome != "settled"
                or started[0].manifest_json != bootstrap.manifest_json
            ):
                raise _denied()
            binding = BootstrapBinding(
                DOCKER_EXE,
                "npipe:////./pipe/dockerDesktopLinuxEngine",
                bootstrap.container_id,
                UUID(epoch.binding.access_epoch_id),
                UUID(epoch.binding.execution_id),
                True,
            )
            commands = BootstrapCommands(binding, permissions)
            self._issued[commands] = binding
            self._owned()
            return commands
        except Exception:
            raise _denied() from None

    def assert_issued(self, commands: BootstrapCommands) -> None:
        try:
            self._owned()
            if (
                type(commands) is not BootstrapCommands
                or commands not in self._issued
                or commands.binding != self._issued[commands]
            ):
                raise _denied()
        except Exception:
            raise _denied() from None
