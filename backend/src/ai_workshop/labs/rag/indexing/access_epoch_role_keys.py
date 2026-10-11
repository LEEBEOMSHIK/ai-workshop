"""Drive the committed role-key child group without repeating an unknown POST.

This is private bootstrap orchestration, not a native executor or startup
capability. The command port must record and fence every submitted OS helper.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, Protocol, cast
from uuid import UUID

from pydantic import SecretStr

from ai_workshop.infrastructure.search.access_credentials import CredentialEnvelope, ServiceRole
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap import (
    BootstrapCommand,
    BootstrapCommands,
    BootstrapKeyObservation,
)
from ai_workshop.labs.rag.indexing.access_epoch_keys import (
    KEY_ROLES,
    KeyActionReadback,
    KeyResult,
    ReservedKeyAction,
    SqlAlchemyEpochKeyRepository,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError


@dataclass(frozen=True, slots=True, eq=False)
class PrivateBootstrapResult:
    exit_code: int
    stdout: bytes = field(repr=False)


class BootstrapCommandPort(Protocol):
    async def execute(
        self, command: BootstrapCommand, reservation: ReservedKeyAction | None
    ) -> PrivateBootstrapResult: ...


class PreparedCredentialPort(Protocol):
    def put(self, envelope: CredentialEnvelope) -> None: ...
    def read_prepared(
        self, epoch_id: UUID, ordinal: int, role: ServiceRole, key_id: str
    ) -> CredentialEnvelope | None: ...


class BootstrapRoleKeyGroup:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        parent: ReservedCutoverAction,
        repository: SqlAlchemyEpochKeyRepository,
        builder: BootstrapCommands,
        commands: BootstrapCommandPort,
        credentials: PreparedCredentialPort,
        assert_owned: Callable[[], None],
        password: SecretStr,
    ) -> None:
        self.epoch, self.parent, self.repository = epoch, parent, repository
        self.builder, self.commands, self.credentials = builder, commands, credentials
        self.assert_owned, self.password = assert_owned, password

    def _owned(self) -> None:
        try:
            if (
                type(self.epoch) is not PreparedAccessEpoch
                or type(self.parent) is not ReservedCutoverAction
                or self.parent.kind != CutoverActionKind.ISSUE_ROLE_KEY
                or self.parent.execution_id != UUID(self.epoch.binding.execution_id)
                or self.builder.binding.epoch_id != UUID(self.epoch.binding.access_epoch_id)
                or self.builder.binding.execution_id != self.parent.execution_id
            ):
                raise ValueError
            if self.assert_owned() is not None:
                raise ValueError
        except Exception:
            raise AliasRecoveryError("rag_alias_proof_invalid") from None

    async def _rows(self) -> tuple[KeyActionReadback, ...]:
        self._owned()
        rows = await self.repository.readback(self.epoch, self.parent)
        self._owned()
        return rows

    async def _execute(
        self, command: BootstrapCommand, action: ReservedKeyAction | None = None
    ) -> PrivateBootstrapResult:
        self._owned()
        result = await self.commands.execute(command, action)
        self._owned()
        if type(result) is not PrivateBootstrapResult:
            raise ValueError("bootstrap_result_unknown")
        return result

    async def _unknown(self, action: ReservedKeyAction) -> None:
        self._owned()
        await self.repository.mark_unknown(self.epoch, action)
        self._owned()

    async def _settle(
        self,
        action: ReservedKeyAction,
        outcome: Literal["issued", "issued_inaccessible", "invalidated"],
        key_id: str,
    ) -> None:
        self._owned()
        await self.repository.settle(
            self.epoch,
            action,
            KeyResult(
                outcome,
                key_id,
                action.role,
                action.issuance_id,
                action.permissions_sha256,
                datetime.now(UTC),
            ),
        )
        self._owned()

    def _prepared(self, action: ReservedKeyAction, key_id: str) -> CredentialEnvelope | None:
        self._owned()
        value = self.credentials.read_prepared(
            UUID(self.epoch.binding.access_epoch_id),
            self.epoch.binding.ordinal,
            action.role,
            key_id,
        )
        self._owned()
        if value is not None and (
            type(value) is not CredentialEnvelope
            or (value.epoch_id, value.ordinal, value.role, value.key_id)
            != (
                UUID(self.epoch.binding.access_epoch_id),
                self.epoch.binding.ordinal,
                action.role,
                key_id,
            )
        ):
            raise ValueError("bootstrap_credential_unknown")
        return value

    async def _lookup(self, action: ReservedKeyAction) -> BootstrapKeyObservation | None:
        command = self.builder.lookup_key(self.password, action.role, action.issuance_id)
        result = await self._execute(command)
        return self.builder.decode_lookup(command, result.exit_code, result.stdout)

    async def _recover(self, row: KeyActionReadback) -> bool:
        action = row.action
        try:
            observed = await self._lookup(action)
            if observed is None:
                return False
            if action.kind == "invalidate":
                if observed.key_id != action.key_id or not observed.invalidated:
                    return False
                await self._settle(action, "invalidated", observed.key_id)
            else:
                if observed.invalidated:
                    return False
                prepared = self._prepared(action, observed.key_id)
                await self._settle(
                    action, "issued" if prepared else "issued_inaccessible", observed.key_id
                )
            return True
        except Exception:
            self._owned()
            return False

    async def _issue(self, role: ServiceRole, replaces: UUID | None) -> bool:
        descriptor = cast(dict[str, object], self.builder.permissions_descriptor(role))
        permissions = sha256(canonical_json(descriptor).encode()).hexdigest()
        self._owned()
        action = await self.repository.reserve_issue(
            self.epoch, self.parent, role, permissions, replaces=replaces
        )
        self._owned()
        try:
            command = self.builder.issue_key(self.password, role, action.issuance_id)
            result = await self._execute(command, action)
            issued = self.builder.decode_issued(command, result.exit_code, result.stdout)
            envelope = CredentialEnvelope(
                issued.epoch_id,
                self.epoch.binding.ordinal,
                issued.role,
                issued.key_id,
                issued.encoded,
            )
            self._owned()
            self.credentials.put(envelope)
            self._owned()
            if self._prepared(action, issued.key_id) != envelope:
                raise ValueError("bootstrap_credential_unknown")
            await self._settle(action, "issued", issued.key_id)
            return True
        except Exception:
            await self._unknown(action)
            return False

    async def _invalidate(self, issue: KeyActionReadback) -> bool:
        try:
            observed = await self._lookup(issue.action)
            if (
                observed is None
                or observed.invalidated
                or issue.result is None
                or (observed.key_id != issue.result.key_id)
            ):
                return False
        except Exception:
            self._owned()
            return False
        self._owned()
        action = await self.repository.reserve_invalidation(
            self.epoch, self.parent, issue.action.issuance_id, observed.key_id
        )
        self._owned()
        try:
            command = self.builder.invalidate_key(self.password, observed)
            result = await self._execute(command, action)
            key_id = self.builder.decode_invalidated(command, result.exit_code, result.stdout)
            # The destructive response and an authenticated fresh GET agree.
            final = await self._lookup(action)
            if final is None or final.key_id != key_id or not final.invalidated:
                raise ValueError("bootstrap_invalidation_unknown")
            await self._settle(action, "invalidated", key_id)
            return True
        except Exception:
            await self._unknown(action)
            return False

    async def advance(self) -> dict[str, object] | None:
        rows = await self._rows()
        unresolved = next((x for x in rows if x.outcome != "settled"), None)
        if unresolved is not None and not await self._recover(unresolved):
            return None
        for role in KEY_ROLES:
            rows = await self._rows()
            issues = [x for x in rows if x.action.role == role and x.action.kind == "issue"]
            issue = issues[-1] if issues else None
            if issue is not None and issue.result is not None:
                if issue.result.result == "issued":
                    if self._prepared(issue.action, issue.result.key_id) is None:
                        raise AliasRecoveryError("rag_alias_proof_invalid")
                    continue
                if issue.result.result != "issued_inaccessible":
                    raise AliasRecoveryError("rag_alias_proof_invalid")
                revoked = any(
                    x.action.kind == "invalidate"
                    and x.action.issuance_id == issue.action.issuance_id
                    and x.outcome == "settled"
                    and x.result is not None
                    and x.result.result == "invalidated"
                    for x in rows
                )
                if not revoked and not await self._invalidate(issue):
                    return None
            if not await self._issue(role, issue.action.issuance_id if issue else None):
                return None
        self._owned()
        manifest = await self.repository.complete_manifest(self.epoch, self.parent)
        self._owned()
        return manifest
