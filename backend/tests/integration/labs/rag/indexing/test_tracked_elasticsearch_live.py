"""Opt-in smoke against an explicitly provisioned loopback test Elasticsearch."""

import os
import re
from dataclasses import replace
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from elasticsearch import AsyncElasticsearch

from ai_workshop.labs.rag.indexing.contracts import IndexDocument
from ai_workshop.labs.rag.indexing.tracked_elasticsearch import (
    TrackedElasticsearchIndex,
    index_input_fingerprint,
)
from ai_workshop.labs.rag.indexing.tracking_contracts import (
    IndexBinding,
    IndexResource,
    IndexTrackingError,
    index_chunk_ids_fingerprint,
)


def _test_url() -> str:
    value = os.environ.get("AI_WORKSHOP_INDEX_TEST_ES_URL")
    if not value:
        pytest.skip("Explicit temporary test Elasticsearch URL is required")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or not 49152 <= parsed.port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        pytest.fail("Only an explicit loopback high-port temporary test endpoint is allowed")
    return value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tracked_prepare_observe_and_reject_foreign_identity_live() -> None:
    url = _test_url()
    token = uuid4().hex
    name = f"test-rag-index-provenance-{token}"
    assert re.fullmatch(r"test-rag-index-provenance-[0-9a-f]{32}", name)
    ids = [uuid4() for _ in range(9)]
    document = IndexDocument(
        ids[8],
        ids[1],
        ids[5],
        ids[3],
        None,
        (),
        "ready",
        "Synthetic smoke",
        (),
        "Synthetic integration content",
        (),
        (0.1, 0.2),
        ids[0],
        ids[7],
    )
    async with AsyncElasticsearch(url, max_retries=0, retry_on_timeout=False) as client:
        info = await client.info()
        binding = IndexBinding("temporary_index_smoke", info["cluster_uuid"])
        resource = IndexResource(
            build_id=ids[0],
            projection_id=ids[1],
            job_id=ids[2],
            workspace_id=ids[3],
            document_id=ids[4],
            asset_version_id=ids[5],
            document_processing_profile_id=ids[6],
            indexing_profile_id=ids[7],
            revision=1,
            binding=binding,
            index_name=name,
            alias=f"{name}-active",
            mapping_version=1,
            vector_dimension=2,
            similarity="cosine",
            index_uuid=None,
            input_fingerprint=index_input_fingerprint([document]),
            chunk_ids_sha256=index_chunk_ids_fingerprint([document.chunk_id]),
        )
        adapter = TrackedElasticsearchIndex(client, binding)
        # Never delete/adopt a name that existed before this test claimed it.
        assert not await client.indices.exists(index=name)
        claimed = False
        identities: list[str] = []

        async def identity(value: str) -> None:
            identities.append(value)
            assert (await client.count(index=name))["count"] == 0

        try:
            claimed = True
            prepared = await adapter.prepare(resource, [document], identity)
            assert prepared.exists and prepared.chunk_count == 1
            assert identities == [prepared.index_uuid]
            resource = replace(resource, index_uuid=prepared.index_uuid)
            observed = await adapter.observe(resource, [document.chunk_id])
            assert observed == prepared
            mapping = (await client.indices.get_mapping(index=name))[name]["mappings"]
            assert set(mapping["_meta"]["rag"]) == {
                "mapping_version",
                "index_build_id",
                "projection_id",
                "indexing_profile_id",
                "vector_dimension",
            }
            assert mapping["_meta"]["rag_index_resource"]["resource_id"] == str(resource.build_id)
            with pytest.raises(IndexTrackingError, match="rag_index_identity_conflict"):
                await adapter.observe(
                    replace(resource, index_uuid="replacement"), [document.chunk_id]
                )
            source = document.to_projection()
            source["workspace_id"] = str(uuid4())
            await client.index(index=name, id=str(document.chunk_id), document=source, refresh=True)
            with pytest.raises(IndexTrackingError, match="rag_index_identity_conflict"):
                await adapter.observe(resource, [document.chunk_id])
        finally:
            if claimed:
                # Exact generated name only; never wildcard, alias, or cluster cleanup.
                await client.options(ignore_status=404).indices.delete(index=name)
                assert not await client.indices.exists(index=name)
