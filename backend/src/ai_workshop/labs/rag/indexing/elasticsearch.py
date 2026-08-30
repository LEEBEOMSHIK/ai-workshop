from collections.abc import Sequence
from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch, NotFoundError

from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, IndexDocument


def build_mapping(descriptor: IndexDescriptor) -> dict[str, Any]:
    return {
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "chunk_id": {"type": "keyword"},
                "projection_id": {"type": "keyword"},
                "asset_version_id": {"type": "keyword"},
                "workspace_id": {"type": "keyword"},
                "folder_id": {"type": "keyword"},
                "allowed_user_ids": {"type": "keyword"},
                "status": {"type": "keyword"},
                "title": {"type": "text"},
                "section_path": {"type": "text"},
                "text": {"type": "text"},
                "evidence_units": {
                    "type": "nested",
                    "properties": {
                        "id": {"type": "keyword"},
                        "chunk_id": {"type": "keyword"},
                        "projection_id": {"type": "keyword"},
                        "ordinal": {"type": "integer"},
                        "text": {"type": "text"},
                        "element_id": {"type": "keyword"},
                        "page": {"type": "integer"},
                        "char_start": {"type": "integer"},
                        "char_end": {"type": "integer"},
                        "bbox": {"type": "float"},
                    },
                },
                "embedding": {
                    "type": "dense_vector",
                    "dims": descriptor.vector_dimension,
                    "similarity": descriptor.similarity,
                },
                "index_build_id": {"type": "keyword"},
            },
        }
    }


class ElasticsearchSearchIndex:
    def __init__(self, client: AsyncElasticsearch) -> None:
        self.client = client

    async def create(self, descriptor: IndexDescriptor) -> None:
        if descriptor.index_name is None:
            raise ValueError("An Elasticsearch index descriptor requires a concrete index name.")
        if await self.client.indices.exists(index=descriptor.index_name):
            return
        await self.client.indices.create(index=descriptor.index_name, **build_mapping(descriptor))

    async def bulk_upsert(self, index_name: str, documents: Sequence[IndexDocument]) -> int:
        if not documents:
            return 0
        operations: list[dict[str, Any]] = []
        for document in documents:
            operations.extend(
                [
                    {"index": {"_index": index_name, "_id": str(document.chunk_id)}},
                    document.to_projection(),
                ]
            )
        response = await self.client.bulk(operations=operations, refresh=False)
        if response["errors"]:
            failures = [item for item in response["items"] if "error" in item["index"]]
            raise RuntimeError(
                f"Elasticsearch bulk indexing failed for {len(failures)} document(s)."
            )
        return len(documents)

    async def count_projection(self, index_name: str, projection_id: UUID) -> int:
        await self.client.indices.refresh(index=index_name)
        response = await self.client.count(
            index=index_name,
            query={"term": {"projection_id": str(projection_id)}},
        )
        return int(response["count"])

    async def activate(self, alias: str, index_name: str) -> bool:
        try:
            current_indices = list(await self.client.indices.get_alias(name=alias))
        except NotFoundError:
            current_indices = []
        actions: list[dict[str, dict[str, str]]] = [
            {"remove": {"index": existing_index, "alias": alias}}
            for existing_index in current_indices
        ]
        actions.append({"add": {"index": index_name, "alias": alias}})
        response = await self.client.indices.update_aliases(actions=actions)
        return bool(response.get("acknowledged", False))

    async def active_targets(self, alias: str) -> tuple[str, ...]:
        try:
            response = await self.client.indices.get_alias(name=alias)
        except NotFoundError:
            return ()
        return tuple(response)
