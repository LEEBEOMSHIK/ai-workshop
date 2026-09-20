"""Commit boundaries for a live document temporary-workspace capability."""

from pathlib import Path
from typing import Protocol

from ai_workshop.platform.assets.temporary_contracts import (
    TemporaryBinding,
    TemporaryClaim,
    TemporaryContext,
    TemporaryOwnershipError,
)


class TemporaryWorkspace(Protocol):
    @property
    def root(self) -> Path: ...

    def create_file(self, name: str) -> Path: ...
    def discard(self) -> None: ...
    def close(self) -> None: ...


class TemporaryStore(Protocol):
    @property
    def binding(self) -> TemporaryBinding: ...

    def create(self, claim: TemporaryClaim) -> TemporaryWorkspace: ...
    def observe(self, claim: TemporaryClaim) -> bool: ...


class TemporaryJournalPort(Protocol):
    async def reserve(
        self,
        context: TemporaryContext,
        purpose: str,
        binding: TemporaryBinding,
        *,
        coverage: str,
    ) -> TemporaryClaim: ...

    async def transition(self, claim: TemporaryClaim, *, expected_state: str) -> None: ...


class TemporaryServicePort(Protocol):
    async def open(
        self,
        context: TemporaryContext,
        purpose: str,
        *,
        coverage: str = "runtime_unverified",
    ) -> "TemporaryLease": ...


class TemporaryLease:
    def __init__(
        self,
        claim: TemporaryClaim,
        workspace: TemporaryWorkspace,
        journal: TemporaryJournalPort,
        store: TemporaryStore,
    ) -> None:
        self.claim = claim
        self.workspace = workspace
        self._journal = journal
        self._store = store
        self._finished = False

    async def finish(self, *, writer_confirmed: bool) -> None:
        if self._finished or type(writer_confirmed) is not bool:
            raise TemporaryOwnershipError("invalid_state")
        # A failed or cancelled finalization must never be retried with this capability.
        self._finished = True
        try:
            if not writer_confirmed:
                return
            await self._journal.transition(self.claim, expected_state="open")
            await self._journal.transition(self.claim, expected_state="closed")
            self.workspace.discard()
            if self._store.observe(self.claim):
                raise TemporaryOwnershipError("cleanup_unconfirmed")
            await self._journal.transition(self.claim, expected_state="cleaning")
        except TemporaryOwnershipError:
            raise
        except Exception:
            raise TemporaryOwnershipError("cleanup_failed") from None
        finally:
            self.workspace.close()


class TemporaryWorkspaceService:
    def __init__(self, journal: TemporaryJournalPort, store: TemporaryStore) -> None:
        self.journal = journal
        self.store = store

    async def open(
        self,
        context: TemporaryContext,
        purpose: str,
        *,
        coverage: str = "runtime_unverified",
    ) -> TemporaryLease:
        # No outer caller transaction may hold source/job locks here.
        try:
            claim = await self.journal.reserve(
                context, purpose, self.store.binding, coverage=coverage
            )
            workspace = self.store.create(claim)
        except TemporaryOwnershipError:
            raise
        except Exception:
            raise TemporaryOwnershipError("storage_unavailable") from None
        return TemporaryLease(claim, workspace, self.journal, self.store)
