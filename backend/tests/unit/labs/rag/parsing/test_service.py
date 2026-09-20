from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.documents.domain import ParsedDocument
from ai_workshop.labs.rag.parsing.contracts import ParseRequest, ParserPort
from ai_workshop.labs.rag.parsing.service import ParsingService
from ai_workshop.platform.assets.domain import AssetVersion, VersionStatus
from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.storage import ObjectStore, StoredObject
from ai_workshop.platform.assets.temporary_contracts import TemporaryContext


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


async def test_materialize_and_parse_removes_temp_source_after_success(tmp_path: Path) -> None:
    parser = RecordingParser()
    service = ParsingService(
        MemoryObjectStore(b"public parser source"), SingleParserRegistry(parser),
        temporary_service=FakeTemporaryService(tmp_path)
    )

    parsed = await service.materialize_and_parse(asset_version(), "public.txt", context=context())

    assert parsed.asset_version_id == asset_version().id
    assert parser.request_path is not None
    assert not parser.request_path.exists()
    assert not parser.request_path.parent.exists()


async def test_materialize_and_parse_removes_temp_source_after_parser_failure(
    tmp_path: Path,
) -> None:
    parser = RecordingParser(failure=RuntimeError("parser failed"))
    service = ParsingService(
        MemoryObjectStore(b"public parser source"), SingleParserRegistry(parser),
        temporary_service=FakeTemporaryService(tmp_path)
    )

    with pytest.raises(RuntimeError, match="parser failed"):
        await service.materialize_and_parse(asset_version(), "public.txt", context=context())

    assert parser.request_path is not None
    assert not parser.request_path.exists()
    assert not parser.request_path.parent.exists()


class FakeWorkspace:
    def __init__(self, root: Path) -> None:
        self.root = root / str(uuid4())
        self.root.mkdir()
        self.files: list[Path] = []

    def create_file(self, name: str) -> Path:
        path = self.root / name
        path.touch(exist_ok=False)
        self.files.append(path)
        return path

    def discard(self) -> None:
        for path in self.files:
            path.unlink()
        self.root.rmdir()

    def close(self) -> None:
        pass


class FakeTemporaryService:
    def __init__(self, root: Path, *, fail: bool = False) -> None:
        self.root = root
        self.fail = fail
        self.finished: list[bool] = []
        self.contexts: list[TemporaryContext] = []

    async def open(self, context: TemporaryContext, purpose: str, *, coverage: str):
        self.contexts.append(context)
        assert purpose == "parsing"
        assert coverage == "runtime_unverified"
        if self.fail:
            raise RuntimeError("reservation rejected")
        return FakeLease(FakeWorkspace(self.root), self.finished)


class FakeLease:
    def __init__(self, workspace: FakeWorkspace, finished: list[bool]) -> None:
        self.workspace = workspace
        self.finished = finished

    async def finish(self, *, writer_confirmed: bool) -> None:
        self.finished.append(writer_confirmed)
        if writer_confirmed:
            self.workspace.discard()


def context() -> TemporaryContext:
    version = asset_version()
    return TemporaryContext(SourceIdentity(uuid4(), version.document_id, version.id), uuid4())


async def test_reservation_failure_does_not_materialize(tmp_path: Path) -> None:
    parser = RecordingParser()
    temporary = FakeTemporaryService(tmp_path, fail=True)
    service = ParsingService(MemoryObjectStore(b"public parser source"),
                             SingleParserRegistry(parser), temporary_service=temporary)
    with pytest.raises(RuntimeError, match="reservation rejected"):
        await service.materialize_and_parse(asset_version(), "../private.txt", context=context())
    assert parser.request_path is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", [None, RuntimeError("opaque failed")])
async def test_opaque_runtime_preserves_open_workspace(tmp_path: Path, failure) -> None:
    class OpaqueParser(RecordingParser):
        def parse(self, request: ParseRequest) -> ParsedDocument:
            request.mark_opaque_runtime_started()
            return super().parse(request)

    parser = OpaqueParser(failure=failure)
    temporary = FakeTemporaryService(tmp_path)
    owner = context()
    service = ParsingService(MemoryObjectStore(b"public parser source"),
                             SingleParserRegistry(parser), temporary_service=temporary)
    try:
        await service.materialize_and_parse(asset_version(), "../private.txt", context=owner)
    except RuntimeError:
        assert failure is not None
    assert temporary.contexts == [owner]
    assert temporary.finished == [False]
    assert parser.request_path.exists()
    assert parser.request_path.name != "private.txt"


async def test_context_mismatch_rejects_before_reservation(tmp_path: Path) -> None:
    from ai_workshop.platform.assets.temporary_contracts import TemporaryOwnershipError

    parser = RecordingParser()
    temporary = FakeTemporaryService(tmp_path)
    service = ParsingService(MemoryObjectStore(b"public parser source"),
                             SingleParserRegistry(parser), temporary_service=temporary)
    mismatched = TemporaryContext(SourceIdentity(uuid4(), uuid4(), uuid4()))
    with pytest.raises(TemporaryOwnershipError, match="source_mismatch"):
        await service.materialize_and_parse(asset_version(), "public.txt", context=mismatched)
    assert temporary.contexts == []
    assert list(tmp_path.iterdir()) == []
