import hashlib
import os
from collections.abc import AsyncIterator
from contextlib import suppress
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

    async def put_if_absent(
        self, key: str, source: AsyncIterator[bytes]
    ) -> StoredObject:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as target:
                async for chunk in source:
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            with suppress(FileExistsError):
                os.link(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return self._describe(destination, key)

    async def open(self, key: str) -> AsyncIterator[bytes]:
        with self._path(key).open("rb") as source:
            while chunk := source.read(1024 * 1024):
                yield chunk

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    @staticmethod
    def _describe(path: Path, key: str) -> StoredObject:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return StoredObject(key=key, size=size, sha256=digest.hexdigest())
