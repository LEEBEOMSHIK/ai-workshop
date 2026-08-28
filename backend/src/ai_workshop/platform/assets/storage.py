from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size: int
    sha256: str


class ObjectStore(Protocol):
    async def put(self, key: str, source: AsyncIterator[bytes]) -> StoredObject: ...
    async def open(self, key: str) -> AsyncIterator[bytes]: ...
    async def delete(self, key: str) -> None: ...
