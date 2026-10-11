"""Commit each role issuance/invalidation before I/O; never reissue an unknown.

Only nonsecret key identity/results are stored here. The fixed controller must
derive a result from authenticated exact server metadata and private store reads.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.infrastructure.search.access_credentials import ServiceRole
from ai_workshop.labs.rag.indexing.access_epoch_models import AccessEpochKeyEventRecord
from ai_workshop.labs.rag.indexing.access_epoch_repository import (
    SqlAlchemyAccessEpochRepository,
    _prepared,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

KEY_ROLES: tuple[ServiceRole, ...] = ("reader", "writer", "collector")


def _conflict() -> AliasRecoveryError:
    return AliasRecoveryError("rag_alias_claim_conflict")


@dataclass(frozen=True, slots=True)
class ReservedKeyAction:
    action_id: UUID
    execution_id: UUID
    parent_action_id: UUID
    sequence: int
    executor_generation: str
    role: ServiceRole
    issuance_id: UUID
    kind: Literal["issue", "invalidate"]
    key_id: str | None
    replaces_issuance_id: UUID | None
    permissions_sha256: str


@dataclass(frozen=True, slots=True)
class KeyResult:
    result: Literal["issued", "issued_inaccessible", "invalidated"]
    key_id: str
    role: ServiceRole
    issuance_id: UUID
    permissions_sha256: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class KeyActionReadback:
    action: ReservedKeyAction
    outcome: Literal["pending", "unknown", "settled"]
    result: KeyResult | None


def _action(row: AccessEpochKeyEventRecord) -> ReservedKeyAction:
    return ReservedKeyAction(
        row.action_id,
        row.execution_id,
        row.parent_action_id,
        row.action_sequence,
        row.executor_generation,
        cast(ServiceRole, row.role),
        row.issuance_id,
        cast(Literal["issue", "invalidate"], row.kind),
        row.key_id,
        row.replaces_issuance_id,
        row.permissions_sha256,
    )


def _readback(events: list[AccessEpochKeyEventRecord]) -> tuple[KeyActionReadback, ...]:
    latest: dict[UUID, AccessEpochKeyEventRecord] = {}
    for event in sorted(events, key=lambda x: x.sequence):
        latest[event.action_id] = event
    result = []
    for row in latest.values():
        settled = None
        if row.outcome == "settled":
            wire = json.loads(row.manifest_json or "null")
            settled = KeyResult(
                wire["result"],
                wire["key_id"],
                wire["role"],
                UUID(wire["issuance_id"]),
                wire["permissions_sha256"],
                row.observed_at,
            )
        result.append(
            KeyActionReadback(
                _action(row), cast(Literal["pending", "unknown", "settled"], row.outcome), settled
            )
        )
    return tuple(result)


def key_group_manifest(
    parent: ReservedCutoverAction, events: list[AccessEpochKeyEventRecord]
) -> dict[str, object] | None:
    rows = _readback(events)
    if any(x.outcome != "settled" for x in rows):
        return None
    latest = {x.action.role: x for x in rows if x.action.kind == "issue"}
    if set(latest) != set(KEY_ROLES) or any(
        x.result is None or x.result.result != "issued" for x in latest.values()
    ):
        return None
    results = {role: cast(KeyResult, latest[role].result) for role in KEY_ROLES}
    if len({x.key_id for x in results.values()}) != len(KEY_ROLES):
        return None
    return {
        "schema_version": 1,
        "execution_id": str(parent.execution_id),
        "parent_action_id": str(parent.action_id),
        "keys": {role: results[role].key_id for role in KEY_ROLES},
        "issuances": {role: str(latest[role].action.issuance_id) for role in KEY_ROLES},
        "permissions": {role: latest[role].action.permissions_sha256 for role in KEY_ROLES},
    }


class SqlAlchemyEpochKeyRepository:
    def __init__(
        self,
        parent: SqlAlchemyAccessEpochRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.parent, self.clock = parent, clock
        self._fresh: dict[UUID, ReservedKeyAction] = {}

    def consume_fresh(self, action: ReservedKeyAction) -> None:
        """A clean commit ACK is required; an old pending row never mints this permit."""
        if (
            type(action) is not ReservedKeyAction
            or self._fresh.pop(action.action_id, None) is not action
        ):
            raise _conflict()

    async def _lock(
        self,
        session: AsyncSession,
        epoch: PreparedAccessEpoch,
        parent: ReservedCutoverAction,
        *,
        completed: bool = False,
    ) -> None:
        row = await self.parent._locked(session, epoch.binding.claim)
        if row is None:
            raise _conflict()
        execution = await self.parent._execution(session, row)
        events = await self.parent._events(session, execution.id)
        if (
            _prepared(row, execution, epoch.binding.claim) != epoch
            or not events
            or parent.kind != CutoverActionKind.ISSUE_ROLE_KEY
            or parent.execution_id != execution.id
            or parent.executor_generation != execution.executor_generation
        ):
            raise _conflict()
        matching = [x for x in events if x.action_id == parent.action_id]
        allowed = {"settled"} if completed else {"pending", "unknown"}
        if not matching or matching[-1].outcome not in allowed:
            raise _conflict()
        from ai_workshop.labs.rag.indexing.access_epoch_repository import _action as parent_action

        if parent_action(matching[0]) != parent or (
            not completed and events[-1].action_id != parent.action_id
        ):
            raise _conflict()

    async def read_completed(
        self, epoch: PreparedAccessEpoch, parent: ReservedCutoverAction
    ) -> tuple[KeyActionReadback, ...]:
        """Read the settled exact group for final checks; grants no fresh permit.

        Mutation/recovery methods still require the active pending parent. This
        read additionally compares actual child truth with the settled manifest.
        """
        try:
            async with self.parent.sessions.begin() as session:
                await self._lock(session, epoch, parent, completed=True)
                events = await self._events(session, parent)
                manifest = key_group_manifest(parent, events)
                parents = await self.parent._events(session, parent.execution_id)
                latest = [x for x in parents if x.action_id == parent.action_id][-1]
                if manifest is None or canonical_json(manifest) != latest.manifest_json:
                    raise _conflict()
                return _readback(events)
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def _events(
        self, session: AsyncSession, parent: ReservedCutoverAction
    ) -> list[AccessEpochKeyEventRecord]:
        return list(
            (
                await session.scalars(
                    select(AccessEpochKeyEventRecord)
                    .where(
                        AccessEpochKeyEventRecord.execution_id == parent.execution_id,
                        AccessEpochKeyEventRecord.parent_action_id == parent.action_id,
                    )
                    .order_by(AccessEpochKeyEventRecord.sequence)
                )
            ).all()
        )

    async def readback(
        self, epoch: PreparedAccessEpoch, parent: ReservedCutoverAction
    ) -> tuple[KeyActionReadback, ...]:
        try:
            async with self.parent.sessions.begin() as session:
                await self._lock(session, epoch, parent)
                return _readback(await self._events(session, parent))
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def reserve_issue(
        self,
        epoch: PreparedAccessEpoch,
        parent: ReservedCutoverAction,
        role: ServiceRole,
        permissions_sha256: str,
        *,
        replaces: UUID | None = None,
    ) -> ReservedKeyAction:
        if (
            type(role) is not str
            or role not in KEY_ROLES
            or type(permissions_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", permissions_sha256) is None
            or (replaces is not None and type(replaces) is not UUID)
        ):
            raise _conflict()
        try:
            async with self.parent.sessions.begin() as session:
                await self._lock(session, epoch, parent)
                events = await self._events(session, parent)
                rows = _readback(events)
                if any(x.outcome != "settled" for x in rows):
                    raise _conflict()
                latest = {x.action.role: x for x in rows if x.action.kind == "issue"}
                needed = next(
                    (
                        r
                        for r in KEY_ROLES
                        if r not in latest
                        or latest[r].result is None
                        or latest[r].result.result != "issued"
                    ),
                    None,
                )
                if needed != role:
                    raise _conflict()
                old = latest.get(role)
                if old is None:
                    if replaces is not None:
                        raise _conflict()
                elif (
                    old.result is None
                    or old.result.result != "issued_inaccessible"
                    or replaces != old.action.issuance_id
                    or permissions_sha256 != old.action.permissions_sha256
                    or not any(
                        x.action.kind == "invalidate"
                        and x.outcome == "settled"
                        and x.action.issuance_id == replaces
                        and x.result is not None
                        and x.result.result == "invalidated"
                        and x.result.key_id == old.result.key_id
                        for x in rows
                    )
                ):
                    raise _conflict()
                reserved = await self._reserve(
                    session,
                    parent,
                    events,
                    role,
                    uuid4(),
                    "issue",
                    None,
                    replaces,
                    permissions_sha256,
                )
            self._fresh[reserved.action_id] = reserved
            return reserved
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def reserve_invalidation(
        self,
        epoch: PreparedAccessEpoch,
        parent: ReservedCutoverAction,
        issuance_id: UUID,
        key_id: str,
    ) -> ReservedKeyAction:
        try:
            async with self.parent.sessions.begin() as session:
                await self._lock(session, epoch, parent)
                events = await self._events(session, parent)
                rows = _readback(events)
                matching = [x for x in rows if x.action.issuance_id == issuance_id]
                if (
                    type(issuance_id) is not UUID
                    or len(matching) != 1
                    or any(x.outcome != "settled" for x in rows)
                ):
                    raise _conflict()
                prior = matching[0]
                if (
                    prior.action.kind != "issue"
                    or prior.result is None
                    or prior.result.result != "issued_inaccessible"
                    or prior.result.key_id != key_id
                ):
                    raise _conflict()
                reserved = await self._reserve(
                    session,
                    parent,
                    events,
                    prior.action.role,
                    issuance_id,
                    "invalidate",
                    key_id,
                    None,
                    prior.action.permissions_sha256,
                )
            self._fresh[reserved.action_id] = reserved
            return reserved
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def _reserve(
        self,
        session: AsyncSession,
        parent: ReservedCutoverAction,
        events: list[AccessEpochKeyEventRecord],
        role: ServiceRole,
        issuance_id: UUID,
        kind: Literal["issue", "invalidate"],
        key_id: str | None,
        replaces: UUID | None,
        permissions_sha256: str,
    ) -> ReservedKeyAction:
        sequence = max([0, *[x.sequence for x in events]]) + 1
        row = AccessEpochKeyEventRecord(
            id=uuid4(),
            execution_id=parent.execution_id,
            parent_action_id=parent.action_id,
            action_id=uuid4(),
            sequence=sequence,
            action_sequence=sequence,
            executor_generation=parent.executor_generation,
            role=role,
            issuance_id=issuance_id,
            kind=kind,
            key_id=key_id,
            replaces_issuance_id=replaces,
            permissions_sha256=permissions_sha256,
            outcome="pending",
            manifest_json=None,
            observed_at=self.clock(),
        )
        session.add(row)
        await session.flush()
        return _action(row)

    async def _append(
        self, epoch: PreparedAccessEpoch, action: ReservedKeyAction, result: KeyResult | None
    ) -> None:
        if type(action) is not ReservedKeyAction or (
            result is not None and type(result) is not KeyResult
        ):
            raise _conflict()
        try:
            async with self.parent.sessions.begin() as session:
                epoch_row = await self.parent._locked(session, epoch.binding.claim)
                if epoch_row is None:
                    raise _conflict()
                execution = await self.parent._execution(session, epoch_row)
                parent_events = await self.parent._events(session, execution.id)
                matching = [
                    x
                    for x in parent_events
                    if x.action_id == action.parent_action_id and x.outcome == "pending"
                ]
                if len(matching) != 1:
                    raise _conflict()
                from ai_workshop.labs.rag.indexing.access_epoch_repository import (
                    _action as parent_action,
                )

                parent = parent_action(matching[0])
                await self._lock(session, epoch, parent)
                events = await self._events(session, parent)
                own = [x for x in events if x.action_id == action.action_id]
                if not own or _action(own[0]) != action:
                    raise _conflict()
                last = own[-1]
                now = self.clock() if result is None else result.observed_at
                if (
                    type(now) is not datetime
                    or now.utcoffset() != timedelta(0)
                    or now < last.observed_at
                ):
                    raise _conflict()
                if result is None:
                    outcome, manifest = (
                        "unknown",
                        canonical_json({"schema_version": 1, "result": "unknown"}),
                    )
                else:
                    if (
                        type(result) is not KeyResult
                        or result.role != action.role
                        or type(result.issuance_id) is not UUID
                        or result.issuance_id != action.issuance_id
                        or result.permissions_sha256 != action.permissions_sha256
                        or type(result.key_id) is not str
                        or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", result.key_id) is None
                        or result.result
                        not in (
                            {"issued", "issued_inaccessible"}
                            if action.kind == "issue"
                            else {"invalidated"}
                        )
                        or (action.kind == "invalidate" and result.key_id != action.key_id)
                    ):
                        raise _conflict()
                    outcome = "settled"
                    manifest = canonical_json(
                        {
                            "schema_version": 1,
                            "result": result.result,
                            "role": result.role,
                            "issuance_id": str(result.issuance_id),
                            "permissions_sha256": result.permissions_sha256,
                            "key_id": result.key_id,
                        }
                    )
                if last.outcome == outcome and last.manifest_json == manifest:
                    return
                if last.outcome == "settled":
                    raise _conflict()
                row = AccessEpochKeyEventRecord(
                    id=uuid4(),
                    execution_id=action.execution_id,
                    parent_action_id=action.parent_action_id,
                    action_id=action.action_id,
                    sequence=max(x.sequence for x in events) + 1,
                    action_sequence=action.sequence,
                    executor_generation=action.executor_generation,
                    role=action.role,
                    issuance_id=action.issuance_id,
                    kind=action.kind,
                    key_id=action.key_id,
                    replaces_issuance_id=action.replaces_issuance_id,
                    permissions_sha256=action.permissions_sha256,
                    outcome=outcome,
                    manifest_json=manifest,
                    observed_at=now,
                )
                session.add(row)
                await session.flush()
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def settle(
        self, epoch: PreparedAccessEpoch, action: ReservedKeyAction, result: KeyResult
    ) -> None:
        if type(result) is not KeyResult:
            raise _conflict()
        await self._append(epoch, action, result)

    async def mark_unknown(self, epoch: PreparedAccessEpoch, action: ReservedKeyAction) -> None:
        await self._append(epoch, action, None)

    async def complete_manifest(
        self, epoch: PreparedAccessEpoch, parent: ReservedCutoverAction
    ) -> dict[str, object] | None:
        try:
            async with self.parent.sessions.begin() as session:
                await self._lock(session, epoch, parent)
                return key_group_manifest(parent, await self._events(session, parent))
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None
