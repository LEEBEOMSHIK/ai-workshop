"""Authoritative daemon readback after a recorded, completed Compose helper.

Read-only observations never authorize a launch or retry. Raw daemon/config
responses remain private and are reduced by the fixed deployment decoder.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Protocol

from ai_workshop.labs.rag.indexing.access_epoch_deployment import (
    PROJECT_ROOT,
    DeploymentCommands,
    ObservedDeployment,
    RawDeploymentReadback,
)
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_process import ReservationReadPort
from ai_workshop.labs.rag.indexing.access_epoch_repository import AccessEpochReadback
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_tls import AccessEpochTls
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlSettlement,
    CutoverActionKind,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
    CommandExecutor,
    FixedCommand,
    ReadOnlyCommandExecutor,
)

_KINDS = {CutoverActionKind.START_BOOTSTRAP, CutoverActionKind.START_SECURED}
_HASHES = (
    "http_ca_sha256",
    "transport_ca_sha256",
    "http_ca_der_sha256",
    "transport_ca_der_sha256",
    "http_leaf_der_sha256",
    "transport_leaf_der_sha256",
)


def _denied() -> ValueError:
    return ValueError("deployment_settlement_denied")


class DeploymentReadPort(Protocol):
    async def read(
        self, kind: CutoverActionKind, public_hashes: tuple[str, ...]
    ) -> RawDeploymentReadback: ...


class FixedDeploymentDaemonReads:
    def __init__(self, executor: CommandExecutor) -> None:
        self.executor = ReadOnlyCommandExecutor(executor)

    async def read(
        self, kind: CutoverActionKind, public_hashes: tuple[str, ...]
    ) -> RawDeploymentReadback:
        # All selectors are fixed original daemon/service/image/volume/network.
        # Failed/missing inspect never means absence or settlement.
        async def read(command: FixedCommand, limit: int = 4_194_304) -> bytes:
            raw = await self.executor.run(command)
            if type(raw) is not str or len(raw.encode()) > limit:
                raise _denied()
            return raw.encode()

        try:
            if type(kind) is not CutoverActionKind or kind not in _KINDS:
                raise _denied()
            daemon = json.loads(await read(FixedCommand.ORIGINAL_DAEMON_ID, 8192))
            if type(daemon) is not dict or set(daemon) != {"id", "os"}:
                raise _denied()
            return RawDeploymentReadback(
                canonical_json({"ID": daemon["id"], "OSType": daemon["os"]}).encode(),
                await read(FixedCommand.SELECTED_SLOT_CONTAINER),
                await read(FixedCommand.SELECTED_IMAGE_RAW),
                await read(FixedCommand.SELECTED_VOLUME_RAW),
                None
                if kind == CutoverActionKind.START_BOOTSTRAP
                else await read(FixedCommand.SELECTED_NETWORK_RAW),
                await read(FixedCommand.ORIGINAL_ALL_IDS),
                public_hashes,
                await read(FixedCommand.SELECTED_SECURITY_CONFIG, 16384),
            )
        except Exception:
            raise _denied() from None


class DeploymentDaemonSettlement:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        builder: DeploymentCommands,
        tls: AccessEpochTls,
        reads: DeploymentReadPort,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.epoch, self.repository, self.journal = epoch, repository, journal
        self.builder, self.tls, self.reads, self.clock = builder, tls, reads, clock

    def _owned(self) -> None:
        self.journal._owned()
        if (
            self.journal.root != PROJECT_ROOT
            or self.builder.epoch != self.epoch
            or self.journal.owner.execution_id.hex != self.builder.execution_id.hex
            or sha256(
                json.dumps([self.epoch.original.daemon_sha256, "ai-workshop"]).encode()
            ).hexdigest()
            != self.journal.scope
        ):
            raise _denied()

    def _state(self, state: AccessEpochReadback, action: ReservedCutoverAction) -> None:
        self._owned()
        if (
            type(action) is not ReservedCutoverAction
            or action.kind not in _KINDS
            or state.prepared != self.epoch
            or state.executor_generation != self.journal.owner.executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or state.phase in {None, "verified", "receipted"}
            or not state.actions
            or state.actions[-1].action != action
            or state.actions[-1].outcome not in {"pending", "unknown"}
            or tuple(x.action.kind for x in state.actions)
            != CUTOVER_ORDER[: CUTOVER_ORDER.index(action.kind) + 1]
            or json.loads(action.expected.identity_json).get("target_sha256")
            != self.builder.target_sha256(action.kind)
        ):
            raise _denied()
        sequence = 0
        for index, row in enumerate(state.actions):
            if (
                type(row.action.sequence) is not int
                or type(row.event_sequence) is not int
                or type(row.action.expected.preceding_sequence) is not int
                or row.action.execution_id != self.journal.owner.execution_id
                or row.action.executor_generation != self.journal.owner.executor_generation
                or row.action.sequence != sequence + 1
                or row.action.expected.preceding_sequence != sequence
                or row.event_sequence < row.action.sequence
                or index < len(state.actions) - 1
                and (
                    row.outcome != "settled"
                    or row.manifest_json is None
                    or row.event_sequence <= row.action.sequence
                )
                or row.outcome == "pending"
                and (row.manifest_json is not None or row.event_sequence != row.action.sequence)
                or row.outcome == "unknown"
                and row.event_sequence <= row.action.sequence
            ):
                raise _denied()
            sequence = row.event_sequence
        record = self.journal.read(action)
        if (
            record is None
            or record.action != action
            or record.state != "process_finished"
            or type(record.exit_code) is not int
            or record.exit_code != 0
            or record.child is None
        ):
            raise _denied()

    async def observe(
        self, action: ReservedCutoverAction, *, predecessor: ObservedDeployment | None = None
    ) -> tuple[ObservedDeployment, ControlSettlement]:
        try:
            self._owned()
            before = await self.repository.readback(self.epoch.binding.claim)
            self._state(before, action)
            if action.kind == CutoverActionKind.START_SECURED:
                self.builder.assert_observed(predecessor)  # type: ignore[arg-type]
                row = next(
                    x for x in before.actions if x.action.kind == CutoverActionKind.START_BOOTSTRAP
                )
                if (
                    predecessor is None
                    or row.action.action_id != predecessor.action_id
                    or row.manifest_json != predecessor.manifest_json
                ):
                    raise _denied()
            elif predecessor is not None:
                raise _denied()
            tls_action = before.actions[CUTOVER_ORDER.index(CutoverActionKind.PREPARE_TLS)].action
            observed = None
            for _ in range(2):
                assets = await self.tls.read_settled(tls_action)
                self._owned()
                self.tls.assert_issued(assets)
                if assets.manifest_json != self.builder.tls.manifest_json:
                    raise _denied()
                manifest = json.loads(assets.manifest_json)
                packet = await self.reads.read(
                    action.kind, tuple(manifest[name] for name in _HASHES)
                )
                self._owned()
                now = self.clock()
                if type(now) is not datetime or now.utcoffset() != timedelta(0):
                    raise _denied()
                current = self.builder.decode_daemon(
                    action, packet, predecessor=predecessor, observed_at=now
                )
                if observed is not None:
                    old, new = json.loads(observed.manifest_json), json.loads(current.manifest_json)
                    old.pop("observed_at")
                    new.pop("observed_at")
                    if old != new:
                        raise _denied()
                observed = current
            after = await self.repository.readback(self.epoch.binding.claim)
            self._state(after, action)
            if after != before or observed is None:
                raise _denied()
            self.builder.assert_observed(observed)
            return observed, ControlSettlement(
                action.action_id,
                action.execution_id,
                action.executor_generation,
                "settled",
                observed.manifest_json,
                now,
            )
        except Exception:
            raise _denied() from None
