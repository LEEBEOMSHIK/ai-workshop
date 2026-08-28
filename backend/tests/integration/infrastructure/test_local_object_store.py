from collections.abc import AsyncIterator

import pytest

from ai_workshop.infrastructure.object_store.local import LocalObjectStore


async def chunks() -> AsyncIterator[bytes]:
    yield b"asset-management"
    yield b"-rag"


@pytest.mark.asyncio
async def test_local_object_store_writes_and_reads_with_checksum(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)

    stored = await store.put("workspace/document/version.bin", chunks())

    assert stored.size == 20
    assert stored.sha256 == "81e0c23f0fe7830d340831e89ebd3d9acfa2826409cd471c24c63c4095942c0f"
    assert b"".join([part async for part in store.open(stored.key)]) == b"asset-management-rag"


@pytest.mark.asyncio
async def test_local_object_store_rejects_root_escape(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)

    with pytest.raises(ValueError, match="outside object store"):
        await store.put("../private.txt", chunks())
