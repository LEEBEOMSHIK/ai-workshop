"""Explicit synthetic workspace provider for process-lifecycle tests."""

from pathlib import Path
from uuid import uuid4

from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.temporary_contracts import TemporaryContext

CONTEXT = TemporaryContext(SourceIdentity(uuid4(), uuid4(), uuid4()))


class FakeWorkspace:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir()

    def create_file(self, name: str) -> Path:
        path = self.root / name
        path.touch(exist_ok=False)
        return path


class FakeLease:
    def __init__(self, root: Path):
        self.workspace = FakeWorkspace(root)
        self.confirmed = None

    async def finish(self, *, writer_confirmed: bool) -> None:
        self.confirmed = writer_confirmed


class FakeTemporaryService:
    def __init__(self, root: Path):
        self.root = root
        self.leases = []
        self.contexts = []

    async def open(self, context, purpose, *, coverage):
        self.contexts.append((context, purpose, coverage))
        lease = FakeLease(self.root / uuid4().hex)
        self.leases.append(lease)
        return lease
