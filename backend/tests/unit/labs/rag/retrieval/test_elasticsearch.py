from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch import ApiError, AsyncElasticsearch, BadRequestError, TransportError

from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.retrieval.domain import (
    ActiveIndexAlias,
    FrozenIndexIdentity,
    FrozenIndexTarget,
    ResolvedSearchScope,
    SearchBackendUnavailableError,
)
from ai_workshop.labs.rag.retrieval.elasticsearch import (
    ElasticsearchDenseRetriever,
    ElasticsearchSparseRetriever,
    build_scope_filter,
    require_concrete_frozen_indices,
)


class RecordingClient:
    def __init__(
        self,
        response: dict[str, object],
        *,
        failure: Exception | None = None,
    ) -> None:
        self.response = response
        self.failure = failure
        self.calls: list[dict[str, object]] = []
        self.frozen_identity: FrozenIndexIdentity | None = None
        self.indices = RecordingIndices(self)

    async def search(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        if self.frozen_identity is not None:
            raw_hits = cast(
                list[dict[str, Any]],
                cast(dict[str, Any], self.response["hits"])["hits"],
            )
            source = cast(dict[str, Any], raw_hits[0]["_source"])
            source["projection_id"] = str(self.frozen_identity.projection_id)
            source["index_build_id"] = str(self.frozen_identity.index_build_id)
            source["indexing_profile_id"] = str(
                self.frozen_identity.indexing_profile_id
            )
            source["rag_mapping_version"] = self.frozen_identity.mapping_version
        return self.response

    async def open_point_in_time(self, **kwargs: Any) -> dict[str, str]:
        return {"id": "pit-id"}

    async def close_point_in_time(self, **kwargs: Any) -> dict[str, bool]:
        return {"succeeded": True}


class RecordingIndices:
    def __init__(self, owner: RecordingClient) -> None:
        self.owner = owner

    async def resolve_index(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "indices": [{"name": kwargs["name"], "aliases": []}],
            "aliases": [],
            "data_streams": [],
        }

    async def get(self, **kwargs: Any) -> dict[str, Any]:
        identity = self.owner.frozen_identity
        assert identity is not None
        return {
            identity.index_name: {
                "settings": {"index": {"uuid": identity.index_uuid}},
                "mappings": {
                    "_meta": {
                        "rag": {
                            "mapping_version": identity.mapping_version,
                            "index_build_id": str(identity.index_build_id),
                            "projection_id": str(identity.projection_id),
                            "indexing_profile_id": str(identity.indexing_profile_id),
                            "vector_dimension": identity.vector_dimension,
                        }
                    }
                },
            }
        }


class ResolvingIndices:
    def __init__(
        self,
        response: dict[str, object],
        identity: FrozenIndexIdentity | None,
    ) -> None:
        self.response = response
        self.identity = identity
        self.calls: list[dict[str, object]] = []

    async def resolve_index(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return self.response

    async def get(self, **kwargs: object) -> dict[str, object]:
        assert self.identity is not None
        return {
            self.identity.index_name: {
                "settings": {"index": {"uuid": self.identity.index_uuid}},
                "mappings": {
                    "_meta": {
                        "rag": {
                            "mapping_version": self.identity.mapping_version,
                            "index_build_id": str(self.identity.index_build_id),
                            "projection_id": str(self.identity.projection_id),
                            "indexing_profile_id": str(
                                self.identity.indexing_profile_id
                            ),
                            "vector_dimension": self.identity.vector_dimension,
                        }
                    }
                },
            }
        }


class ResolvingClient:
    def __init__(
        self,
        response: dict[str, object],
        identity: FrozenIndexIdentity | None = None,
    ) -> None:
        self.indices = ResolvingIndices(response, identity)


def _response() -> dict[str, object]:
    chunk_id = "00000000-0000-0000-0000-000000000801"
    projection_id = "00000000-0000-0000-0000-000000000802"
    return {
        "hits": {
            "hits": [
                {
                    "_score": 2.5,
                    "_source": {
                        "chunk_id": chunk_id,
                        "projection_id": projection_id,
                        "asset_version_id": "00000000-0000-0000-0000-000000000803",
                        "workspace_id": "00000000-0000-0000-0000-000000000804",
                        "folder_id": "00000000-0000-0000-0000-000000000805",
                        "index_build_id": "00000000-0000-0000-0000-000000000806",
                        "title": "Synthetic source",
                        "section_path": ["Policy", "Limits"],
                        "text": "Synthetic evidence text",
                        "evidence_units": [
                            {
                                "id": "00000000-0000-0000-0000-000000000807",
                                "chunk_id": chunk_id,
                                "projection_id": projection_id,
                                "ordinal": 0,
                                "text": "Synthetic evidence text",
                                "element_id": "00000000-0000-0000-0000-000000000808",
                                "page": 2,
                                "char_start": 10,
                                "char_end": 33,
                                "bbox": [1.0, 2.0, 3.0, 4.0],
                            }
                        ],
                    },
                }
            ]
        }
    }


def _active_alias(profile_id: UUID | None = None) -> ActiveIndexAlias:
    return ActiveIndexAlias(
        descriptor=IndexDescriptor(vector_dimension=2, similarity="cosine"),
        index_prefix="ai-workshop-rag",
        indexing_profile_id=profile_id or uuid4(),
    )


def _api_error(status: int) -> ApiError:
    error_type = BadRequestError if status == 400 else ApiError
    return error_type(
        f"Elasticsearch status {status}",
        meta=ApiResponseMeta(
            status=status,
            http_version="1.1",
            headers=HttpHeaders(),
            duration=0.01,
            node=NodeConfig("http", "localhost", 9200),
        ),
        body={"error": {"type": "synthetic_test_error"}},
    )


def test_active_scope_without_authoritative_lifecycle_is_match_none() -> None:
    actor_id = uuid4()

    filters = build_scope_filter(
        actor_id,
        ResolvedSearchScope((uuid4(),), ()),
    )

    assert filters[-1] == {"match_none": {}}
    assert not any("asset_version_id" in str(item) for item in filters)
    assert not any("index_build_id" in str(item) for item in filters)


@pytest.mark.asyncio
async def test_sparse_and_dense_use_equivalent_acl_prefilters_and_hide_vectors() -> None:
    actor_id = UUID("00000000-0000-0000-0000-000000000809")
    workspace_id = UUID("00000000-0000-0000-0000-000000000804")
    folder_id = UUID("00000000-0000-0000-0000-000000000805")
    asset_version_ids = (
        UUID("00000000-0000-0000-0000-000000000803"),
        UUID("00000000-0000-0000-0000-000000000813"),
    )
    index_build_ids = (
        UUID("00000000-0000-0000-0000-000000000806"),
        UUID("00000000-0000-0000-0000-000000000816"),
    )
    scope = ResolvedSearchScope(
        (workspace_id,),
        (folder_id,),
        asset_version_ids=asset_version_ids,
        index_build_ids=index_build_ids,
    )
    client = RecordingClient(_response())
    sparse = ElasticsearchSparseRetriever(cast(AsyncElasticsearch, client))
    dense = ElasticsearchDenseRetriever(cast(AsyncElasticsearch, client))
    alias = _active_alias()

    sparse_hits = await sparse.search_sparse(
        index_alias=alias,
        query="synthetic",
        actor_id=actor_id,
        scope=scope,
        top_k=5,
    )
    dense_hits = await dense.search_dense(
        index_alias=alias,
        query_vector=(1.0, 0.0),
        actor_id=actor_id,
        scope=scope,
        top_k=5,
    )

    sparse_filter = cast(dict[str, Any], client.calls[0]["query"])["bool"]["filter"]
    dense_filter = cast(dict[str, Any], client.calls[1]["knn"])["filter"]["bool"][
        "filter"
    ]
    assert sparse_filter == dense_filter == [
        {"terms": {"workspace_id": [str(workspace_id)]}},
        {"term": {"allowed_user_ids": str(actor_id)}},
        {"terms": {"folder_id": [str(folder_id)]}},
        {"term": {"status": "ready"}},
        {"terms": {"asset_version_id": [str(item) for item in asset_version_ids]}},
        {"terms": {"index_build_id": [str(item) for item in index_build_ids]}},
    ]
    assert all(
        "embedding" not in cast(dict[str, list[str]], call["source"])["includes"]
        for call in client.calls
    )
    assert sparse_hits[0].chunk == dense_hits[0].chunk
    evidence = sparse_hits[0].chunk.evidence_units[0]
    assert evidence.location.bbox == (1.0, 2.0, 3.0, 4.0)
    assert evidence.location.char_start == 10
    assert evidence.projection_id == sparse_hits[0].chunk.projection_id
    assert [call["index"] for call in client.calls] == [alias.name, alias.name]


@pytest.mark.asyncio
async def test_frozen_target_searches_each_validated_physical_index_separately() -> None:
    profile_id = uuid4()
    build_ids = (UUID("00000000-0000-0000-0000-000000000806"),)
    projection_id = UUID("00000000-0000-0000-0000-000000000802")
    descriptor = IndexDescriptor(vector_dimension=2, similarity="cosine")
    identity = FrozenIndexIdentity(
        descriptor.concrete_index_name(
            "task11-evaluation", profile_id, build_ids[0]
        ),
        "index-uuid",
        build_ids[0],
        projection_id,
        profile_id,
        2,
        1,
    )
    target = FrozenIndexTarget(
        descriptor=descriptor,
        index_prefix="task11-evaluation",
        indexing_profile_id=profile_id,
        identities=(identity,),
        asset_version_ids=(UUID("00000000-0000-0000-0000-000000000803"),),
    )
    client = RecordingClient(_response())
    client.frozen_identity = identity
    sparse = ElasticsearchSparseRetriever(cast(AsyncElasticsearch, client))
    dense = ElasticsearchDenseRetriever(cast(AsyncElasticsearch, client))
    scope = ResolvedSearchScope(
        (UUID("00000000-0000-0000-0000-000000000804"),),
        (),
        active_only=False,
        asset_version_ids=target.asset_version_ids,
        index_build_ids=target.index_build_ids,
    )

    await sparse.search_sparse(
        index_alias=target,
        query="synthetic",
        actor_id=uuid4(),
        scope=scope,
        top_k=5,
    )
    await dense.search_dense(
        index_alias=target,
        query_vector=(1.0, 0.0),
        actor_id=uuid4(),
        scope=scope,
        top_k=5,
    )

    assert len(client.calls) == 2
    assert all("index" not in call and "pit" in call for call in client.calls)


@pytest.mark.asyncio
async def test_frozen_target_resolution_rejects_exact_name_alias_before_search() -> None:
    profile_id = uuid4()
    build_id = uuid4()
    descriptor = IndexDescriptor(vector_dimension=2, similarity="cosine")
    target = FrozenIndexTarget(
        descriptor=descriptor,
        index_prefix="task11-evaluation",
        indexing_profile_id=profile_id,
        identities=(
            FrozenIndexIdentity(
                descriptor.concrete_index_name(
                    "task11-evaluation", profile_id, build_id
                ),
                "index-uuid",
                build_id,
                uuid4(),
                profile_id,
                2,
                1,
            ),
        ),
        asset_version_ids=(uuid4(),),
    )
    client = ResolvingClient(
        {
            "indices": [],
            "aliases": [
                {"name": target.index_names[0], "indices": ["redirected-index"]}
            ],
            "data_streams": [],
        }
    )

    with pytest.raises(ValueError, match="concrete physical index"):
        await require_concrete_frozen_indices(
            cast(AsyncElasticsearch, client), target
        )

    assert client.indices.calls == [
        {"name": target.index_names[0], "expand_wildcards": "open"}
    ]


@pytest.mark.asyncio
async def test_frozen_target_resolution_accepts_only_its_exact_concrete_index() -> None:
    profile_id = uuid4()
    build_id = uuid4()
    descriptor = IndexDescriptor(vector_dimension=2, similarity="cosine")
    target = FrozenIndexTarget(
        descriptor=descriptor,
        index_prefix="task11-evaluation",
        indexing_profile_id=profile_id,
        identities=(
            FrozenIndexIdentity(
                descriptor.concrete_index_name(
                    "task11-evaluation", profile_id, build_id
                ),
                "index-uuid",
                build_id,
                uuid4(),
                profile_id,
                2,
                1,
            ),
        ),
        asset_version_ids=(uuid4(),),
    )
    client = ResolvingClient(
        {
            "indices": [{"name": target.index_names[0], "aliases": []}],
            "aliases": [],
            "data_streams": [],
        },
        target.identities[0],
    )

    await require_concrete_frozen_indices(cast(AsyncElasticsearch, client), target)

    assert client.indices.calls == [
        {"name": target.index_names[0], "expand_wildcards": "open"}
    ]


@pytest.mark.asyncio
async def test_retrievers_reject_concrete_stale_index_before_elasticsearch() -> None:
    client = RecordingClient(_response())
    sparse = ElasticsearchSparseRetriever(cast(AsyncElasticsearch, client))
    dense = ElasticsearchDenseRetriever(cast(AsyncElasticsearch, client))
    scope = ResolvedSearchScope((uuid4(),), ())
    concrete_index = "ai-workshop-rag-profile-stale-build"

    with pytest.raises(ValueError, match="resolved index target"):
        await sparse.search_sparse(
            index_alias=cast(ActiveIndexAlias, concrete_index),
            query="synthetic",
            actor_id=uuid4(),
            scope=scope,
            top_k=5,
        )
    with pytest.raises(ValueError, match="resolved index target"):
        await dense.search_dense(
            index_alias=cast(ActiveIndexAlias, concrete_index),
            query_vector=(1.0, 0.0),
            actor_id=uuid4(),
            scope=scope,
            top_k=5,
        )

    assert client.calls == []


@pytest.mark.asyncio
async def test_retrievers_reject_non_ready_scope_before_elasticsearch() -> None:
    client = RecordingClient(_response())
    sparse = ElasticsearchSparseRetriever(cast(AsyncElasticsearch, client))
    dense = ElasticsearchDenseRetriever(cast(AsyncElasticsearch, client))
    alias = _active_alias()
    scope = ResolvedSearchScope((uuid4(),), (), ready_only=False)

    with pytest.raises(ValueError, match="READY"):
        await sparse.search_sparse(
            index_alias=alias,
            query="synthetic",
            actor_id=uuid4(),
            scope=scope,
            top_k=5,
        )
    with pytest.raises(ValueError, match="READY"):
        await dense.search_dense(
            index_alias=alias,
            query_vector=(1.0, 0.0),
            actor_id=uuid4(),
            scope=scope,
            top_k=5,
        )

    assert client.calls == []


@pytest.mark.asyncio
async def test_retrievers_wrap_elasticsearch_transport_failures_as_operational() -> None:
    failure = TransportError("backend unavailable")
    client = RecordingClient(_response(), failure=failure)
    sparse = ElasticsearchSparseRetriever(cast(AsyncElasticsearch, client))
    dense = ElasticsearchDenseRetriever(cast(AsyncElasticsearch, client))
    alias = _active_alias()
    scope = ResolvedSearchScope((uuid4(),), ())

    with pytest.raises(SearchBackendUnavailableError) as sparse_error:
        await sparse.search_sparse(
            index_alias=alias,
            query="synthetic",
            actor_id=uuid4(),
            scope=scope,
            top_k=5,
        )
    with pytest.raises(SearchBackendUnavailableError) as dense_error:
        await dense.search_dense(
            index_alias=alias,
            query_vector=(1.0, 0.0),
            actor_id=uuid4(),
            scope=scope,
            top_k=5,
        )

    assert sparse_error.value.__cause__ is failure
    assert dense_error.value.__cause__ is failure


@pytest.mark.asyncio
async def test_retrievers_propagate_deterministic_bad_request_unchanged() -> None:
    failure = _api_error(400)
    client = RecordingClient(_response(), failure=failure)
    sparse = ElasticsearchSparseRetriever(cast(AsyncElasticsearch, client))
    dense = ElasticsearchDenseRetriever(cast(AsyncElasticsearch, client))
    alias = _active_alias()
    scope = ResolvedSearchScope((uuid4(),), ())

    with pytest.raises(BadRequestError) as sparse_error:
        await sparse.search_sparse(
            index_alias=alias,
            query="synthetic",
            actor_id=uuid4(),
            scope=scope,
            top_k=5,
        )
    with pytest.raises(BadRequestError) as dense_error:
        await dense.search_dense(
            index_alias=alias,
            query_vector=(1.0, 0.0),
            actor_id=uuid4(),
            scope=scope,
            top_k=5,
        )

    assert sparse_error.value is failure
    assert dense_error.value is failure


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_retryable_elasticsearch_status_is_operational(status: int) -> None:
    failure = _api_error(status)
    client = RecordingClient(_response(), failure=failure)
    sparse = ElasticsearchSparseRetriever(cast(AsyncElasticsearch, client))

    with pytest.raises(SearchBackendUnavailableError) as error:
        await sparse.search_sparse(
            index_alias=_active_alias(),
            query="synthetic",
            actor_id=uuid4(),
            scope=ResolvedSearchScope((uuid4(),), ()),
            top_k=5,
        )

    assert error.value.__cause__ is failure


@pytest.mark.asyncio
async def test_retriever_propagates_programming_defect_unchanged() -> None:
    failure = TypeError("client contract defect")
    client = RecordingClient(_response(), failure=failure)
    sparse = ElasticsearchSparseRetriever(cast(AsyncElasticsearch, client))

    with pytest.raises(TypeError) as error:
        await sparse.search_sparse(
            index_alias=_active_alias(),
            query="synthetic",
            actor_id=uuid4(),
            scope=ResolvedSearchScope((uuid4(),), ()),
            top_k=5,
        )

    assert error.value is failure
