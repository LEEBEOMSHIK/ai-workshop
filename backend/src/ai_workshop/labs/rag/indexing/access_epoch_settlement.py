"""Settle only exact synchronous old-ID stop/rm, with authoritative readback.

No command submission, history admission, proof issuance, or absent-inspect guess.
An unresolved/lost child ACK is not converted to success by target absence.
"""

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast

from ai_workshop.labs.rag.indexing.access_epoch_process import (
    ReservationReadPort,
    original_control_target,
)
from ai_workshop.labs.rag.indexing.access_epoch_repository import AccessEpochReadback
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlSettlement,
    CutoverActionKind,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
    strict_utc,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
    CONTAINER,
    CONTEXT_ENDPOINT_DIGEST,
    DAEMON,
    ORIGINAL_IMAGE_ID,
    CommandExecutor,
    FixedCommand,
    ReadOnlyCommandExecutor,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import utc_text


def _denied() -> ValueError:
    return ValueError("cutover_daemon_settlement_denied")


def original_daemon_sha256() -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "id": DAEMON,
                "os": "linux",
                "endpoint_sha256": CONTEXT_ENDPOINT_DIGEST,
            }
        ).encode()
    ).hexdigest()


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise _denied()
        result[key] = value
    return result


def _json(raw: str) -> dict[str, object]:
    if type(raw) is not str or len(raw) > 8192:
        raise _denied()
    value = json.loads(raw, object_pairs_hook=_pairs)
    if type(value) is not dict:
        raise _denied()
    return cast(dict[str, object], value)


def _docker_time(value: object, *, ceil: bool = False) -> datetime:
    if (
        type(value) is not str
        or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z",
            value,
        )
        is None
    ):
        raise _denied()
    result = datetime.fromisoformat(value)
    fraction = value.split(".")[1][:-1] if "." in value else ""
    if ceil and len(fraction) > 6 and any(c != "0" for c in fraction[6:]):
        result += timedelta(microseconds=1)
    return result


class OriginalDaemonSettlement:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        executor: CommandExecutor,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.epoch, self.repository, self.journal = epoch, repository, journal
        self.executor, self.clock = ReadOnlyCommandExecutor(executor), clock

    def _owned(self) -> None:
        self.journal.lock.assert_owned(self.journal.owner)
        if (
            self.epoch.binding.execution_id != str(self.journal.owner.execution_id)
            or self.epoch.original.container_id != CONTAINER
            or self.epoch.original.daemon_sha256 != original_daemon_sha256()
            or hashlib.sha256(
                json.dumps(
                    [
                        self.epoch.original.daemon_sha256,
                        "ai-workshop",
                    ]
                ).encode()
            ).hexdigest()
            != self.journal.lock.scope_sha256
        ):
            raise _denied()

    async def _read(self, command: FixedCommand) -> str:
        self._owned()
        result = await self.executor.run(command)
        self._owned()
        return result

    def _state(self, state: AccessEpochReadback, action: ReservedCutoverAction) -> None:
        if (
            type(action) is not ReservedCutoverAction
            or action.kind not in {CutoverActionKind.STOP_OLD, CutoverActionKind.RETIRE_OLD}
            or state.prepared != self.epoch
            or state.executor_generation != self.journal.owner.executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or not state.actions
            or state.actions[-1].action != action
            or state.actions[-1].outcome not in {"pending", "unknown"}
            or state.actions[-1].outcome == "pending"
            and (
                state.actions[-1].manifest_json is not None
                or state.actions[-1].event_sequence != action.sequence
            )
            or state.actions[-1].outcome == "unknown"
            and state.actions[-1].event_sequence <= action.sequence
            or any(x.outcome != "settled" for x in state.actions[:-1])
        ):
            raise _denied()
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
        expected = _json(action.expected.identity_json)
        if expected.get("target_sha256") != original_control_target(self.epoch, action.kind):
            raise _denied()
        for item in state.actions:
            if (
                item.action.execution_id != action.execution_id
                or item.action.executor_generation != action.executor_generation
            ):
                raise _denied()

    async def observe(self, action: ReservedCutoverAction) -> ControlSettlement:
        try:
            self._owned()
            state = await self.repository.readback(self.epoch.binding.claim)
            self._owned()
            self._state(state, action)
            daemon = _json(await self._read(FixedCommand.ORIGINAL_DAEMON_ID))
            if daemon != {"id": DAEMON, "os": "linux"}:
                raise _denied()
            now = self.clock()
            if type(now) is not datetime or now.utcoffset() != timedelta(0):
                raise _denied()
            manifest: dict[str, object] = {
                "container_id": CONTAINER,
                "daemon_sha256": original_daemon_sha256(),
                "action_id": str(action.action_id),
                "sequence": action.sequence,
                "method": "exact_synchronous_command_and_terminal_readback",
            }
            if action.kind == CutoverActionKind.STOP_OLD:
                metadata = _json(await self._read(FixedCommand.ORIGINAL_STOP_METADATA))
                if (
                    set(metadata)
                    != {
                        "container_id",
                        "image_id",
                        "running",
                        "restarting",
                        "dead",
                        "pid",
                        "started_at",
                        "finished_at",
                    }
                    or metadata["container_id"] != CONTAINER
                    or metadata["image_id"] != ORIGINAL_IMAGE_ID
                    or any(metadata[k] is not False for k in ("running", "restarting", "dead"))
                    or type(metadata["pid"]) is not int
                    or metadata["pid"] != 0
                ):
                    raise _denied()
                started = _docker_time(metadata["started_at"])
                finished = _docker_time(metadata["finished_at"], ceil=True)
                if not started <= self.epoch.original.jvm_start_at <= finished <= now:
                    raise _denied()
                manifest.update(
                    finished_at=utc_text(finished),
                    started_at_docker=metadata["started_at"],
                    finished_at_docker=metadata["finished_at"],
                )
            else:
                stops = [
                    x for x in state.actions[:-1] if x.action.kind == CutoverActionKind.STOP_OLD
                ]
                if len(stops) != 1 or stops[0].manifest_json is None:
                    raise _denied()
                stop = _json(stops[0].manifest_json)
                if (
                    stop.get("container_id") != CONTAINER
                    or stop.get("daemon_sha256") != original_daemon_sha256()
                    or stop.get("action_id") != str(stops[0].action.action_id)
                    or stop.get("method") != "exact_synchronous_command_and_terminal_readback"
                    or strict_utc(stop.get("finished_at")) != state.old_server_stopped_at
                    or state.old_server_stopped_at is None
                    or state.old_server_stopped_at > now
                ):
                    raise _denied()
                raw = await self._read(FixedCommand.ORIGINAL_ALL_IDS)
                if type(raw) is not str or len(raw) > 1024 * 1024:
                    raise _denied()
                ids = raw.splitlines()
                if (
                    len(set(ids)) != len(ids)
                    or CONTAINER in ids
                    or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in ids)
                ):
                    raise _denied()
                manifest.update(
                    retired_at=utc_text(now), stopped_action_id=str(stops[0].action.action_id)
                )
            # Awaited observations may race a committed transition or lose ownership.
            fresh = await self.repository.readback(self.epoch.binding.claim)
            self._owned()
            self._state(fresh, action)
            if fresh != state:
                raise _denied()
            return ControlSettlement(
                action.action_id,
                action.execution_id,
                action.executor_generation,
                "settled",
                canonical_json(manifest),
                now,
            )
        except Exception:
            raise _denied() from None
