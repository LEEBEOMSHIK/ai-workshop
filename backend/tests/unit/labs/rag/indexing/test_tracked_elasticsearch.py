import asyncio
from copy import deepcopy
from dataclasses import replace
from typing import Any, cast
from uuid import UUID

import pytest
from elasticsearch import AsyncElasticsearch

from ai_workshop.labs.rag.indexing.contracts import IndexDocument
from ai_workshop.labs.rag.indexing.tracked_elasticsearch import (
    IndexPreparationFailed,
    TrackedElasticsearchIndex,
    index_input_fingerprint,
)
from ai_workshop.labs.rag.indexing.tracking_contracts import (
    IndexBinding,
    IndexResource,
    IndexTrackingError,
    index_chunk_ids_fingerprint,
)


def fixture() -> tuple[IndexResource, list[IndexDocument]]:
    ids = [UUID(int=i) for i in range(1, 10)]
    documents = [
        IndexDocument(
            ids[8],
            ids[1],
            ids[5],
            ids[3],
            None,
            (),
            "ready",
            "Synthetic",
            (),
            "Synthetic text",
            (),
            (0.1, 0.2),
            ids[0],
            ids[7],
        )
    ]
    resource = IndexResource(
        *ids[:8],
        revision=1,
        binding=IndexBinding("test_store", "test-cluster"),
        index_name=f"rag-{ids[7]}-{ids[0]}",
        alias=f"rag-{ids[7]}-active",
        mapping_version=1,
        vector_dimension=2,
        similarity="cosine",
        index_uuid=None,
        input_fingerprint=index_input_fingerprint(documents),
        chunk_ids_sha256=index_chunk_ids_fingerprint([documents[0].chunk_id]),
    )
    return resource, documents


class FakeES:
    def __init__(self) -> None:
        self.indices = self
        self.cluster = "test-cluster"
        self.name: str | None = None
        self.mapping: dict[str, Any] = {}
        self.uuid = "physical-uuid"
        self.aliases: dict[str, Any] = {}
        self.records: dict[str, Any] = {}
        self.events: list[str] = []
        self.options_values: dict[str, Any] = {}
        self.kind = "indices"
        self.failed_shards = 0
        self.bulk_error: BaseException | None = None
        self.partial_bulk = False
        self.pending_records: dict[str, Any] = {}

    def options(self, **kwargs: Any) -> "FakeES":
        self.options_values = kwargs
        return self

    async def info(self) -> dict[str, Any]:
        return {"cluster_uuid": self.cluster}

    async def resolve_index(self, **kwargs: Any) -> dict[str, Any]:
        result: dict[str, Any] = {"indices": [], "aliases": [], "data_streams": []}
        if self.name:
            result[self.kind] = [{"name": self.name, "attributes": ["open"]}]
        return result

    async def create(self, *, index: str, mappings: dict[str, Any]) -> dict[str, Any]:
        self.events.append("create")
        self.name, self.mapping = index, deepcopy(mappings)
        return {"acknowledged": True, "shards_acknowledged": True, "index": index}

    async def get(self, **kwargs: Any) -> dict[str, Any]:
        return {
            self.name: {
                "settings": {"index": {"uuid": self.uuid}},
                "mappings": self.mapping,
                "aliases": self.aliases,
            }
        }

    async def bulk(self, *, operations: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        self.events.append("bulk")
        if self.bulk_error:
            raise self.bulk_error
        items = []
        for action, source in zip(operations[::2], operations[1::2], strict=True):
            key = action["index"]["_id"]
            self.records[key] = deepcopy(source)
            items.append({"index": {"_id": key, "_index": self.name, "status": 201}})
        if self.partial_bulk:
            items[0]["index"]["error"] = {"reason": "SECRET url credential vector text"}
            items[0]["index"]["status"] = 400
        return {"errors": self.partial_bulk, "items": items}

    async def refresh(self, **kwargs: Any) -> dict[str, Any]:
        self.records.update(self.pending_records)
        self.pending_records.clear()
        return {"_shards": {"total": 1, "successful": 1, "failed": self.failed_shards}}

    async def count(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "count": len(self.records),
            "_shards": {"total": 1, "successful": 1, "failed": self.failed_shards},
        }

    async def search(self, **kwargs: Any) -> dict[str, Any]:
        hits = [
            {"_id": key, "_index": self.name, "_source": value, "sort": [value["chunk_id"]]}
            for key, value in sorted(self.records.items())
            if not kwargs.get("search_after") or value["chunk_id"] > kwargs["search_after"][0]
        ]
        return {
            "timed_out": False,
            "_shards": {"total": 1, "successful": 1, "failed": self.failed_shards},
            "hits": {
                "total": {"value": len(self.records), "relation": "eq"},
                "hits": hits[: kwargs["size"]],
            },
        }


async def prepared() -> tuple[FakeES, IndexResource, list[IndexDocument]]:
    resource, documents = fixture()
    fake = FakeES()

    async def identity(value: str) -> None:
        fake.events.append("identity")

    await TrackedElasticsearchIndex(cast(AsyncElasticsearch, fake), resource.binding).prepare(
        resource, documents, identity
    )
    return fake, replace(resource, index_uuid=fake.uuid), documents


@pytest.mark.asyncio
async def test_create_identity_commit_precedes_bulk_and_preserves_descriptor() -> None:
    fake, resource, documents = await prepared()
    assert fake.events == ["create", "identity", "bulk"]
    assert set(fake.mapping["_meta"]["rag"]) == {
        "mapping_version",
        "index_build_id",
        "projection_id",
        "indexing_profile_id",
        "vector_dimension",
    }
    assert fake.mapping["_meta"]["rag_index_resource"]["input_fingerprint"] == (
        resource.input_fingerprint
    )
    assert fake.options_values == {
        "max_retries": 0,
        "retry_on_timeout": False,
        "retry_on_status": (),
    }
    fake.aliases = {resource.alias: {}, "owner-extra-alias": {}}
    observation = await TrackedElasticsearchIndex(
        cast(AsyncElasticsearch, fake), resource.binding
    ).observe(resource, [documents[0].chunk_id])
    assert observation.exists and observation.chunk_count == 1
    assert observation.aliases == tuple(sorted(fake.aliases))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    ["cluster", "uuid", "legacy", "alias", "stream", "mapping", "owner", "id", "chunk", "shard"],
)
async def test_conflicts_never_write(fault: str) -> None:
    fake, resource, documents = await prepared()
    fake.events.clear()
    if fault == "cluster":
        fake.cluster = "wrong-cluster"
    elif fault == "uuid":
        fake.uuid = "replacement"
    elif fault == "legacy":
        del fake.mapping["_meta"]["rag_index_resource"]
    elif fault in ("alias", "stream"):
        fake.kind = "aliases" if fault == "alias" else "data_streams"
    elif fault == "mapping":
        fake.mapping["properties"]["embedding"]["dims"] = 3
    elif fault == "owner":
        next(iter(fake.records.values()))["workspace_id"] = str(UUID(int=99))
    elif fault == "id":
        fake.records["other-id"] = fake.records.pop(str(documents[0].chunk_id))
    elif fault == "chunk":
        source = fake.records.pop(str(documents[0].chunk_id))
        source["chunk_id"] = str(UUID(int=100))
        fake.records[source["chunk_id"]] = source
    else:
        fake.failed_shards = 1

    async def identity(value: str) -> None:
        fake.events.append("identity")

    with pytest.raises(IndexTrackingError):
        await TrackedElasticsearchIndex(cast(AsyncElasticsearch, fake), resource.binding).prepare(
            resource, documents, identity
        )
    assert "bulk" not in fake.events and "create" not in fake.events


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["timeout", "cancel", "partial", "callback"])
async def test_write_failure_is_sanitized_without_replay(fault: str) -> None:
    resource, documents = fixture()
    fake = FakeES()
    if fault == "timeout":
        fake.bulk_error = TimeoutError("SECRET url credential vector text")
    if fault == "cancel":
        fake.bulk_error = asyncio.CancelledError("SECRET")
    fake.partial_bulk = fault == "partial"

    async def identity(value: str) -> None:
        if fault == "callback":
            raise RuntimeError("SECRET database")

    with pytest.raises(IndexTrackingError) as exc:
        await TrackedElasticsearchIndex(cast(AsyncElasticsearch, fake), resource.binding).prepare(
            resource, documents, identity
        )
    assert exc.value.code == (
        "rag_index_observation_failed" if fault == "partial" else "rag_index_writer_unconfirmed"
    )
    assert "SECRET" not in str(exc.value)
    assert exc.value.__context__ is None or exc.value.__suppress_context__
    assert isinstance(exc.value, IndexPreparationFailed)
    assert exc.value.writer_confirmed_ended is (fault == "partial")
    assert fake.events.count("bulk") == (0 if fault == "callback" else 1)


def test_fingerprint_is_order_independent_but_covers_payload_and_rejects_duplicates() -> None:
    _, documents = fixture()
    other = replace(documents[0], chunk_id=UUID(int=90))
    assert index_input_fingerprint([other, documents[0]]) == index_input_fingerprint(
        [documents[0], other]
    )
    assert index_input_fingerprint(documents) != index_input_fingerprint(
        [replace(documents[0], text="Changed")]
    )
    with pytest.raises(IndexTrackingError):
        index_input_fingerprint([documents[0], documents[0]])


@pytest.mark.asyncio
async def test_unreserved_absent_resource_is_observable_without_mutations() -> None:
    resource, _ = fixture()
    resource = replace(resource, input_fingerprint=None, chunk_ids_sha256=None)
    fake = FakeES()
    result = await TrackedElasticsearchIndex(
        cast(AsyncElasticsearch, fake), resource.binding
    ).observe(resource, [])
    assert not result.exists and result.index_uuid is None
    assert result.chunk_count == 0 and result.aliases == () and fake.events == []


@pytest.mark.asyncio
async def test_observe_expected_ids_must_match_reserved_set() -> None:
    fake, resource, _ = await prepared()
    fake.events.clear()
    with pytest.raises(IndexTrackingError, match="rag_index_input_conflict"):
        await TrackedElasticsearchIndex(cast(AsyncElasticsearch, fake), resource.binding).observe(
            resource, [UUID(int=987)]
        )
    assert fake.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["input", "dimension", "nan", "binding", "missing_uuid"])
async def test_invalid_input_never_mutates(fault: str) -> None:
    resource, documents = fixture()
    fake = FakeES()
    binding = resource.binding
    if fault == "input":
        documents = [replace(documents[0], text="Changed input")]
    elif fault in ("dimension", "nan"):
        documents = [
            replace(documents[0], embedding=(0.1,) if fault == "dimension" else (float("nan"), 0.1))
        ]
        if fault == "dimension":
            resource = replace(resource, input_fingerprint=index_input_fingerprint(documents))
    elif fault == "binding":
        binding = IndexBinding("other_store", "test-cluster")
    else:
        resource = replace(resource, index_uuid="lost-existing-uuid")

    async def identity(value: str) -> None:
        fake.events.append("identity")

    with pytest.raises(IndexTrackingError):
        await TrackedElasticsearchIndex(cast(AsyncElasticsearch, fake), binding).prepare(
            resource, documents, identity
        )
    assert fake.events == []


@pytest.mark.asyncio
async def test_observe_reads_all_pages_and_detects_foreign_final_record() -> None:
    resource, documents = fixture()
    documents = [replace(documents[0], chunk_id=UUID(int=value)) for value in range(1, 503)]
    resource = replace(
        resource,
        input_fingerprint=index_input_fingerprint(documents),
        chunk_ids_sha256=index_chunk_ids_fingerprint([doc.chunk_id for doc in documents]),
    )
    fake = FakeES()

    async def identity(value: str) -> None:
        pass

    adapter = TrackedElasticsearchIndex(cast(AsyncElasticsearch, fake), resource.binding)
    result = await adapter.prepare(resource, documents, identity)
    assert result.chunk_count == 502
    fake.records[str(documents[-1].chunk_id)]["projection_id"] = str(UUID(int=999))
    with pytest.raises(IndexTrackingError):
        await adapter.observe(resource, [doc.chunk_id for doc in documents])


@pytest.mark.asyncio
async def test_existing_unrefreshed_foreign_owner_blocks_bulk() -> None:
    fake, resource, documents = await prepared()
    fake.events.clear()
    source = deepcopy(documents[0].to_projection())
    source["workspace_id"] = str(UUID(int=800))
    fake.pending_records[str(documents[0].chunk_id)] = source

    async def identity(value: str) -> None:
        pass

    with pytest.raises(IndexTrackingError):
        await TrackedElasticsearchIndex(cast(AsyncElasticsearch, fake), resource.binding).prepare(
            resource, documents, identity
        )
    assert "bulk" not in fake.events


@pytest.mark.asyncio
async def test_prepare_allows_unassigned_replica_in_refresh_only() -> None:
    class SingleNodeES(FakeES):
        async def refresh(self, **kwargs: Any) -> dict[str, Any]:
            await super().refresh(**kwargs)
            return {"_shards": {"total": 2, "successful": 1, "failed": 0}}

    resource, documents = fixture()
    fake = SingleNodeES()

    async def identity(value: str) -> None:
        pass

    adapter = TrackedElasticsearchIndex(cast(AsyncElasticsearch, fake), resource.binding)
    assert (await adapter.prepare(resource, documents, identity)).chunk_count == 1
    # Cover the refresh before ownership inspection on a repeated prepare too.
    assert (await adapter.prepare(resource, documents, identity)).chunk_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["count", "search"])
async def test_incomplete_count_and_search_shards_still_fail(operation: str) -> None:
    fake, resource, documents = await prepared()
    original = getattr(fake, operation)

    async def incomplete(**kwargs: Any) -> dict[str, Any]:
        result = await original(**kwargs)
        result["_shards"] = {"total": 2, "successful": 1, "failed": 0}
        return cast(dict[str, Any], result)

    setattr(fake, operation, incomplete)
    with pytest.raises(IndexTrackingError, match="rag_index_observation_failed"):
        await TrackedElasticsearchIndex(cast(AsyncElasticsearch, fake), resource.binding).observe(
            resource, [documents[0].chunk_id]
        )


@pytest.mark.asyncio
async def test_input_conflict_proves_no_writer_started() -> None:
    resource, documents = fixture()
    fake = FakeES()

    async def identity(value: str) -> None:
        pytest.fail("Input conflict must precede the callback")

    with pytest.raises(IndexPreparationFailed) as exc:
        await TrackedElasticsearchIndex(cast(AsyncElasticsearch, fake), resource.binding).prepare(
            resource, [replace(documents[0], text="different")], identity
        )
    assert exc.value.code == "rag_index_input_conflict"
    assert exc.value.writer_confirmed_ended
    assert fake.events == []


@pytest.mark.asyncio
async def test_create_timeout_preserves_unknown_writer() -> None:
    class CreateTimeoutES(FakeES):
        async def create(self, **kwargs: Any) -> dict[str, Any]:
            self.events.append("create")
            raise TimeoutError("synthetic backend private response")

    resource, documents = fixture()
    fake = CreateTimeoutES()

    async def identity(value: str) -> None:
        pytest.fail("No identity was received")

    with pytest.raises(IndexPreparationFailed) as exc:
        await TrackedElasticsearchIndex(cast(AsyncElasticsearch, fake), resource.binding).prepare(
            resource, documents, identity
        )
    assert not exc.value.writer_confirmed_ended
    assert exc.value.code == "rag_index_writer_unconfirmed"
    assert fake.events == ["create"]
