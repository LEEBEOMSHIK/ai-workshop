from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import ParsedDocument
from ai_workshop.labs.rag.parsing.contracts import ParseRequest, ParserPort
from ai_workshop.labs.rag.parsing.service import ParsingService
from ai_workshop.platform.assets.domain import AssetVersion, VersionStatus
from ai_workshop.platform.assets.storage import ObjectStore, StoredObject


class MemoryObjectStore(ObjectStore):
    def __init__(self, data: bytes) -> None:
        self.data = data

    async def put(self, key: str, source: AsyncIterator[bytes]) -> StoredObject:
        raise NotImplementedError

    async def open(self, key: str) -> AsyncIterator[bytes]:
        yield self.data

    async def delete(self, key: str) -> None:
        raise NotImplementedError


class RecordingParser(ParserPort):
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.request_path: Path | None = None

    def parse(self, request: ParseRequest) -> ParsedDocument:
        self.request_path = request.path
        assert request.path.read_bytes() == b"public parser source"
        if self.failure is not None:
            raise self.failure
        return ParsedDocument(
            asset_version_id=request.asset_version_id,
            parser_name="recording",
            parser_version="test",
            elements=(),
        )


class SingleParserRegistry:
    def __init__(self, parser: ParserPort) -> None:
        self.parser = parser

    def resolve(self, media_type: str, filename: str) -> ParserPort:
        return self.parser


def asset_version() -> AssetVersion:
    return AssetVersion(
        id=UUID("44444444-4444-4444-4444-444444444444"),
        document_id=UUID("55555555-5555-5555-5555-555555555555"),
        number=1,
        object_key="workspace/public.txt",
        sha256="0" * 64,
        media_type="text/plain",
        size=20,
        status=VersionStatus.STORED,
    )


async def test_materialize_and_parse_removes_temp_source_after_success() -> None:
    parser = RecordingParser()
    service = ParsingService(
        MemoryObjectStore(b"public parser source"), SingleParserRegistry(parser)
    )

    parsed = await service.materialize_and_parse(asset_version(), "public.txt")

    assert parsed.asset_version_id == asset_version().id
    assert parser.request_path is not None
    assert not parser.request_path.exists()
    assert not parser.request_path.parent.exists()


async def test_materialize_and_parse_removes_temp_source_after_parser_failure() -> None:
    parser = RecordingParser(failure=RuntimeError("parser failed"))
    service = ParsingService(
        MemoryObjectStore(b"public parser source"), SingleParserRegistry(parser)
    )

    with pytest.raises(RuntimeError, match="parser failed"):
        await service.materialize_and_parse(asset_version(), "public.txt")

    assert parser.request_path is not None
    assert not parser.request_path.exists()
    assert not parser.request_path.parent.exists()
