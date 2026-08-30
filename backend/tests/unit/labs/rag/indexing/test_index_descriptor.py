from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, IndexDocument
from ai_workshop.labs.rag.indexing.elasticsearch import build_mapping
from ai_workshop.labs.rag.indexing.service import IndexingService

PROFILE_ID = UUID("00000000-0000-0000-0000-000000000101")
BUILD_ID = UUID("00000000-0000-0000-0000-000000000201")
PROJECTION_ID = UUID("00000000-0000-0000-0000-000000000301")
CHUNK_ID = UUID("00000000-0000-0000-0000-000000000401")


class RecordingIndex:
    def __init__(
        self,
        *,
        counted: int = 1,
        bulk_result: int | None = None,
        activation_acknowledged: bool = True,
        active_targets: tuple[str, ...] | None = None,
    ) -> None:
        self.counted = counted
        self.bulk_result = bulk_result
        self.activation_acknowledged = activation_acknowledged
        self._active_targets = active_targets
        self.events: list[str] = []
        self.indices: set[str] = set()
        self.document_ids_by_index: dict[str, set[UUID]] = {}
        self.last_activated_index: str | None = None

    async def create(self, descriptor: IndexDescriptor) -> None:
        assert descriptor.index_name is not None
        self.events.append(f"create:{descriptor.index_name}")
        self.indices.add(descriptor.index_name)

    async def bulk_upsert(self, index_name: str, documents: Sequence[IndexDocument]) -> int:
        self.events.append(f"bulk:{index_name}:{len(documents)}")
        self.document_ids_by_index.setdefault(index_name, set()).update(
            document.chunk_id for document in documents
        )
        return len(documents) if self.bulk_result is None else self.bulk_result

    async def count_projection(self, index_name: str, projection_id: UUID) -> int:
        self.events.append(f"count:{index_name}:{projection_id}")
        return self.counted

    async def activate(self, alias: str, index_name: str) -> bool:
        self.events.append(f"activate:{alias}:{index_name}")
        self.last_activated_index = index_name
        return self.activation_acknowledged

    async def active_targets(self, alias: str) -> tuple[str, ...]:
        self.events.append(f"targets:{alias}")
        if self._active_targets is not None:
            return self._active_targets
        assert self.last_activated_index is not None
        return (self.last_activated_index,)


def _document(
    *,
    chunk_id: UUID = CHUNK_ID,
    evidence: EvidenceUnit | None = None,
) -> IndexDocument:
    return IndexDocument(
        chunk_id=chunk_id,
        projection_id=PROJECTION_ID,
        asset_version_id=UUID("00000000-0000-0000-0000-000000000405"),
        workspace_id=UUID("00000000-0000-0000-0000-000000000406"),
        folder_id=None,
        allowed_user_ids=(UUID("00000000-0000-0000-0000-000000000408"),),
        status="ready",
        title="상품 설명서",
        section_path=("상품",),
        text="한국상품 설명",
        evidence_units=(evidence,) if evidence is not None else (),
        embedding=None,
        index_build_id=BUILD_ID,
    )


def _service(index: RecordingIndex) -> IndexingService:
    return IndexingService(index, index_prefix="ai-workshop-rag")


async def _index_one(service: IndexingService, document: IndexDocument | None = None) -> None:
    await service.index_projection(
        descriptor=IndexDescriptor(vector_dimension=768, similarity="cosine"),
        profile_id=PROFILE_ID,
        build_id=BUILD_ID,
        projection_id=PROJECTION_ID,
        expected_chunk_count=1,
        documents=(_document() if document is None else document,),
    )


def test_descriptor_generates_immutable_concrete_name_and_active_alias() -> None:
    descriptor = IndexDescriptor(vector_dimension=768, similarity="cosine")

    assert descriptor.concrete_index_name("ai-workshop-rag", PROFILE_ID, BUILD_ID) == (
        "ai-workshop-rag-00000000-0000-0000-0000-000000000101-"
        "00000000-0000-0000-0000-000000000201"
    )
    assert descriptor.active_alias("ai-workshop-rag", PROFILE_ID) == (
        "ai-workshop-rag-00000000-0000-0000-0000-000000000101-active"
    )


@pytest.mark.parametrize("dimension", [768, 1024])
def test_mapping_uses_descriptor_dimension_and_cosine_similarity(dimension: int) -> None:
    mapping = build_mapping(IndexDescriptor(vector_dimension=dimension, similarity="cosine"))

    assert mapping["mappings"]["properties"]["embedding"] == {
        "type": "dense_vector",
        "dims": dimension,
        "similarity": "cosine",
    }
    assert mapping["mappings"]["properties"]["workspace_id"]["type"] == "keyword"
    assert mapping["mappings"]["properties"]["allowed_user_ids"]["type"] == "keyword"
    assert mapping["mappings"]["properties"]["evidence_units"]["type"] == "nested"


@pytest.mark.asyncio
async def test_count_mismatch_never_activates_alias() -> None:
    index = RecordingIndex(counted=0)

    with pytest.raises(ValueError, match="count mismatch"):
        await _index_one(_service(index))

    assert index.events[-1].startswith("count:")
    assert not any(event.startswith("activate:") for event in index.events)


@pytest.mark.asyncio
async def test_unacknowledged_alias_activation_never_claims_verified_success() -> None:
    index = RecordingIndex(activation_acknowledged=False)

    with pytest.raises(ValueError, match="acknowledge"):
        await _index_one(_service(index))

    assert not any(event.startswith("targets:") for event in index.events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "active_targets",
    [
        ("another-concrete-index",),
        ("another-concrete-index", "second-concrete-index"),
    ],
)
async def test_alias_verification_rejects_wrong_or_multiple_targets(
    active_targets: tuple[str, ...],
) -> None:
    index = RecordingIndex(active_targets=active_targets)

    with pytest.raises(ValueError, match="exclusively"):
        await _index_one(_service(index))

    assert index.events[-1].startswith("targets:")


@pytest.mark.asyncio
async def test_successful_indexing_verifies_alias_after_count_and_activation() -> None:
    index = RecordingIndex()
    service = _service(index)

    await _index_one(service)

    assert [event.split(":")[0] for event in index.events] == [
        "create",
        "bulk",
        "count",
        "activate",
        "targets",
    ]
    assert await service.revalidate_active_target(
        profile_id=PROFILE_ID,
        build_id=BUILD_ID,
        descriptor=IndexDescriptor(vector_dimension=768, similarity="cosine"),
    ) is True


@pytest.mark.asyncio
async def test_prepare_finishes_bulk_and_count_without_activating_alias() -> None:
    index = RecordingIndex()
    service = _service(index)

    prepared = await service.prepare_projection(
        descriptor=IndexDescriptor(vector_dimension=768, similarity="cosine"),
        profile_id=PROFILE_ID,
        build_id=BUILD_ID,
        projection_id=PROJECTION_ID,
        expected_chunk_count=1,
        documents=(_document(),),
    )

    assert [event.split(":")[0] for event in index.events] == ["create", "bulk", "count"]
    assert prepared.build_id == BUILD_ID
    assert prepared.indexed_document_count == 1
    assert prepared.alias_verified is False


@pytest.mark.asyncio
async def test_activation_ack_and_exclusive_revalidation_are_a_separate_boundary() -> None:
    index = RecordingIndex()
    service = _service(index)
    prepared = await service.prepare_projection(
        descriptor=IndexDescriptor(vector_dimension=768, similarity="cosine"),
        profile_id=PROFILE_ID,
        build_id=BUILD_ID,
        projection_id=PROJECTION_ID,
        expected_chunk_count=1,
        documents=(_document(),),
    )
    index.events.clear()

    activated = await service.activate_prepared(prepared)

    assert activated.alias_verified is True
    assert [event.split(":")[0] for event in index.events] == ["activate", "targets"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("expected_chunk_count", "documents"),
    [
        (0, ()),
        (2, (_document(),)),
        (2, (_document(), _document())),
    ],
)
async def test_incomplete_or_duplicate_input_never_writes(
    expected_chunk_count: int,
    documents: tuple[IndexDocument, ...],
) -> None:
    index = RecordingIndex(counted=expected_chunk_count)

    with pytest.raises(ValueError):
        await _service(index).index_projection(
            descriptor=IndexDescriptor(vector_dimension=768, similarity="cosine"),
            profile_id=PROFILE_ID,
            build_id=BUILD_ID,
            projection_id=PROJECTION_ID,
            expected_chunk_count=expected_chunk_count,
            documents=documents,
        )

    assert index.events == []


@pytest.mark.asyncio
async def test_partial_bulk_accounting_never_activates_alias() -> None:
    index = RecordingIndex(bulk_result=0)

    with pytest.raises(ValueError, match="did not write every supplied chunk"):
        await _index_one(_service(index))

    assert [event.split(":")[0] for event in index.events] == ["create", "bulk"]


@pytest.mark.asyncio
async def test_evidence_with_wrong_parent_never_reaches_elasticsearch() -> None:
    evidence = EvidenceUnit(
        id=UUID("00000000-0000-0000-0000-000000000404"),
        chunk_id=UUID("00000000-0000-0000-0000-000000000499"),
        ordinal=0,
        text="근거",
        location=SourceLocation(
            UUID("00000000-0000-0000-0000-000000000400"), 1, 0, 2, None
        ),
        projection_id=PROJECTION_ID,
    )
    index = RecordingIndex()

    with pytest.raises(ValueError, match="containing chunk"):
        await _index_one(_service(index), _document(evidence=evidence))

    assert index.events == []


@pytest.mark.asyncio
async def test_evidence_with_wrong_projection_never_reaches_elasticsearch() -> None:
    evidence = EvidenceUnit(
        id=UUID("00000000-0000-0000-0000-000000000404"),
        chunk_id=CHUNK_ID,
        ordinal=0,
        text="근거",
        location=SourceLocation(
            UUID("00000000-0000-0000-0000-000000000400"), 1, 0, 2, None
        ),
        projection_id=UUID("00000000-0000-0000-0000-000000000399"),
    )
    index = RecordingIndex()

    with pytest.raises(ValueError, match="containing projection"):
        await _index_one(_service(index), _document(evidence=evidence))

    assert index.events == []


@pytest.mark.asyncio
async def test_same_build_retries_converge_and_distinct_builds_are_isolated() -> None:
    index = RecordingIndex()
    service = _service(index)
    descriptor = IndexDescriptor(vector_dimension=768, similarity="cosine")

    await _index_one(service)
    await _index_one(service)
    second_build = UUID("00000000-0000-0000-0000-000000000202")
    await service.index_projection(
        descriptor=descriptor,
        profile_id=PROFILE_ID,
        build_id=second_build,
        projection_id=PROJECTION_ID,
        expected_chunk_count=1,
        documents=(replace(_document(), index_build_id=second_build),),
    )

    assert len(index.indices) == 2
    assert all(len(document_ids) == 1 for document_ids in index.document_ids_by_index.values())
