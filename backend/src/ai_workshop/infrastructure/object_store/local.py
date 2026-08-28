import hashlib
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

from ai_workshop.platform.assets.storage import StoredObject


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("Object key points outside object store.")
        return candidate

    async def put(self, key: str, source: AsyncIterator[bytes]) -> StoredObject:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("xb") as target:
                async for chunk in source:
                    target.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return StoredObject(key=key, size=size, sha256=digest.hexdigest())

    async def open(self, key: str) -> AsyncIterator[bytes]:
        with self._path(key).open("rb") as source:
            while chunk := source.read(1024 * 1024):
                yield chunk

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
