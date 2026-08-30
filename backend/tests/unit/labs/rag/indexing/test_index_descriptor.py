from uuid import UUID

import pytest

from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.indexing.elasticsearch import build_mapping
from ai_workshop.labs.rag.indexing.service import IndexingService


class RecordingIndex:
    def __init__(self, *, counted: int) -> None:
        self.counted = counted
        self.events: list[str] = []

    async def create(self, descriptor: IndexDescriptor) -> None:
        self.events.append(f"create:{descriptor.index_name}")

    async def bulk_upsert(self, index_name: str, documents: tuple[object, ...]) -> int:
        self.events.append(f"bulk:{index_name}:{len(documents)}")
        return len(documents)

    async def count_projection(self, index_name: str, projection_id: UUID) -> int:
        self.events.append(f"count:{index_name}:{projection_id}")
        return self.counted

    async def activate(self, alias: str, index_name: str) -> None:
        self.events.append(f"activate:{alias}:{index_name}")


def test_descriptor_generates_immutable_concrete_name_and_active_alias() -> None:
    profile_id = UUID("00000000-0000-0000-0000-000000000101")
    build_id = UUID("00000000-0000-0000-0000-000000000201")

    descriptor = IndexDescriptor(vector_dimension=768, similarity="cosine")

    assert descriptor.concrete_index_name("ai-workshop-rag", profile_id, build_id) == (
        "ai-workshop-rag-00000000-0000-0000-0000-000000000101-"
        "00000000-0000-0000-0000-000000000201"
    )
    assert descriptor.active_alias("ai-workshop-rag", profile_id) == (
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
    index = RecordingIndex(counted=1)
    service = IndexingService(index, index_prefix="ai-workshop-rag")
    projection_id = UUID("00000000-0000-0000-0000-000000000301")

    with pytest.raises(ValueError, match="count mismatch"):
        await service.index_projection(
            descriptor=IndexDescriptor(vector_dimension=768, similarity="cosine"),
            profile_id=UUID("00000000-0000-0000-0000-000000000101"),
            build_id=UUID("00000000-0000-0000-0000-000000000201"),
            projection_id=projection_id,
            expected_chunk_count=2,
            documents=(),
        )

    assert index.events[-1].startswith("count:")
    assert not any(event.startswith("activate:") for event in index.events)
