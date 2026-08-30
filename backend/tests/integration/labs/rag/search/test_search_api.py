from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pymupdf
import pytest
from fastapi.testclient import TestClient

from ai_workshop.labs.rag.documents.domain import (
    EvidenceUnit,
    ParsedDocument,
    SourceLocation,
    StructuralElement,
)
from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingModelConfig,
    EmbeddingPort,
    EmbeddingRuntimeUnavailableError,
)
from ai_workshop.labs.rag.embeddings.sentence_transformers import (
    SentenceTransformerEmbedding,
)
from ai_workshop.labs.rag.highlighting.domain import AnswerPolicy, EvidenceSource
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.ingestion.serialization import serialize_parsed_document
from ai_workshop.labs.rag.models.domain import Profile, ProfileKind
from ai_workshop.labs.rag.retrieval.domain import (
    ActiveIndexAlias,
    DenseHit,
    FusedHit,
    ResolvedSearchScope,
    RetrievedChunk,
    SearchBackendUnavailableError,
    SparseHit,
)
from ai_workshop.labs.rag.search import viewer as viewer_module
from ai_workshop.labs.rag.search.api import get_search_service, get_viewer_service
from ai_workshop.labs.rag.search.configuration_port import (
    ResolvedSearchConfiguration,
    SearchConfigurationResolverPort,
)
from ai_workshop.labs.rag.search.service import (
    SearchApplicationService,
    SearchSourceResolverPort,
)
from ai_workshop.labs.rag.search.viewer import (
    ViewerResource,
    ViewerResourceAccessRepositoryPort,
    ViewerService,
)
from ai_workshop.main import create_app
from ai_workshop.platform.assets.storage import StoredObject
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.shared.errors import AppError

ACTOR_ID = UUID("10000000-0000-0000-0000-000000000001")
OTHER_ACTOR_ID = UUID("10000000-0000-0000-0000-000000000002")
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")
PRIVATE_WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000002")
CONFIGURATION_ID = UUID("30000000-0000-0000-0000-000000000001")
CONFIGURATION_VERSION_ID = UUID("30000000-0000-0000-0000-000000000002")
POLICY_VERSION_ID = UUID("30000000-0000-0000-0000-000000000003")
INDEXING_PROFILE_ID = UUID("40000000-0000-0000-0000-000000000001")


def owner() -> User:
    return User(
        id=ACTOR_ID,
        display_name="Owner",
        email="owner@example.com",
        normalized_email="owner@example.com",
        password_hash="hash",
        role=UserRole.OWNER,
    )


class RecordingEmbedding(EmbeddingPort):
    dimension = 2

    def __init__(
        self,
        vectors: dict[str, list[float]] | None = None,
        *,
        document_error: Exception | None = None,
    ) -> None:
        self.vectors = vectors or {}
        self.document_error = document_error
        self.encoded_documents: list[str] = []

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def count_query_tokens(self, text: str) -> int:
        return len(text.split())

    def encode_query(self, text: str) -> list[float]:
        return list(self.vectors.get(text, [1.0, 0.0]))

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.encoded_documents.extend(texts)
        if self.document_error is not None:
            raise self.document_error
        return [list(self.vectors.get(text, [0.0, 1.0])) for text in texts]


class InMemorySearchConfigurationResolver(SearchConfigurationResolverPort):
    def __init__(self, configuration: ResolvedSearchConfiguration | None) -> None:
        self.configuration = configuration
        self.calls: list[tuple[UUID, UUID]] = []

    async def resolve(
        self,
        configuration_id: UUID,
        actor_id: UUID,
    ) -> ResolvedSearchConfiguration:
        self.calls.append((configuration_id, actor_id))
        if self.configuration is None or configuration_id != self.configuration.configuration_id:
            from ai_workshop.shared.errors import AppError

            raise AppError("not_found", "The requested resource was not found.", 404)
        return self.configuration


class RecordingScopeResolver:
    async def resolve(
        self,
        *,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
    ) -> ResolvedSearchScope:
        assert actor_id == ACTOR_ID
        return ResolvedSearchScope(workspace_ids, folder_ids)


class SparseRetriever:
    def __init__(
        self,
        hits: tuple[SparseHit, ...],
        failure: Exception | None = None,
    ) -> None:
        self.hits = hits
        self.failure = failure

    async def search_sparse(
        self,
        *,
        index_alias: ActiveIndexAlias,
        query: str,
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[SparseHit, ...]:
        del index_alias, query, actor_id, scope, top_k
        if self.failure is not None:
            raise self.failure
        return self.hits


class DenseRetriever:
    def __init__(
        self,
        hits: tuple[DenseHit, ...] = (),
        failure: Exception | None = None,
    ) -> None:
        self.hits = hits
        self.failure = failure

    async def search_dense(
        self,
        *,
        index_alias: ActiveIndexAlias,
        query_vector: tuple[float, ...],
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[DenseHit, ...]:
        del index_alias, query_vector, actor_id, scope, top_k
        if self.failure is not None:
            raise self.failure
        return self.hits


class AuthoritativeSourceResolver(SearchSourceResolverPort):
    def __init__(self, sources: tuple[EvidenceSource, ...]) -> None:
        self.sources = sources
        self.calls: list[tuple[UUID, UUID, tuple[UUID | str, ...]]] = []

    async def resolve(
        self,
        *,
        actor_id: UUID,
        indexing_profile_id: UUID,
        hits: tuple[FusedHit, ...],
    ) -> tuple[EvidenceSource, ...]:
        self.calls.append(
            (actor_id, indexing_profile_id, tuple(item.chunk_id for item in hits))
        )
        hit_ids = {item.chunk_id for item in hits}
        return tuple(source for source in self.sources if source.chunk.chunk_id in hit_ids)


def _retrieval_profile(*, hybrid: bool = False) -> Profile:
    config: dict[str, object] = {"bm25": {"top_k": 10}}
    if hybrid:
        config.update(
            {
                "dense": {"top_k": 10},
                "rrf": {"k": 60},
                "indexing_profile_id": str(INDEXING_PROFILE_ID),
            }
        )
    return Profile.create(
        kind=ProfileKind.RETRIEVAL,
        name="test retrieval",
        version=1,
        config=config,  # type: ignore[arg-type]
        bindings=(),
    )


def _configuration(
    embedding: EmbeddingPort,
    *,
    hybrid: bool = False,
    with_policy: bool = True,
) -> ResolvedSearchConfiguration:
    return ResolvedSearchConfiguration(
        configuration_id=CONFIGURATION_ID,
        configuration_version_id=CONFIGURATION_VERSION_ID,
        configuration_version=3,
        indexing_profile_id=INDEXING_PROFILE_ID,
        retrieval_profile=_retrieval_profile(hybrid=hybrid),
        answer_policy_version_id=POLICY_VERSION_ID if with_policy else None,
        answer_policy=(
            AnswerPolicy(
                min_semantic_score=0.8,
                min_keyword_coverage=1.0,
                require_complete_provenance=True,
                conflict_mode="separate_sources",
            )
            if with_policy
            else None
        ),
        active_index_alias=ActiveIndexAlias(
            IndexDescriptor(vector_dimension=2, similarity="cosine"),
            "ai-workshop-rag",
            INDEXING_PROFILE_ID,
        ),
        embedding=embedding,
    )


def test_resolved_configuration_rejects_a_non_fail_closed_v1_policy() -> None:
    configuration = _configuration(RecordingEmbedding())
    assert configuration.answer_policy is not None
    object.__setattr__(
        configuration.answer_policy,
        "require_complete_provenance",
        False,
    )

    with pytest.raises(ValueError, match="complete provenance"):
        replace(configuration)


def _source(
    value: int,
    text: str,
    *,
    workspace_id: UUID = WORKSPACE_ID,
) -> EvidenceSource:
    chunk_id = UUID(f"50000000-0000-0000-0000-{value:012d}")
    projection_id = UUID(f"60000000-0000-0000-0000-{value:012d}")
    evidence = EvidenceUnit(
        id=UUID(f"70000000-0000-0000-0000-{value:012d}"),
        chunk_id=chunk_id,
        projection_id=projection_id,
        ordinal=0,
        text=text,
        location=SourceLocation(
            element_id=UUID(f"80000000-0000-0000-0000-{value:012d}"),
            page=None,
            char_start=value * 100,
            char_end=value * 100 + len(text),
            bbox=None,
        ),
    )
    return EvidenceSource(
        document_id=UUID(f"90000000-0000-0000-0000-{value:012d}"),
        asset_version_number=value,
        media_type="text/plain",
        chunk=RetrievedChunk(
            chunk_id=chunk_id,
            projection_id=projection_id,
            asset_version_id=UUID(f"a0000000-0000-0000-0000-{value:012d}"),
            workspace_id=workspace_id,
            folder_id=None,
            index_build_id=UUID(f"b0000000-0000-0000-0000-{value:012d}"),
            title=f"source-{value}.txt",
            section_path=("약관",),
            text=text,
            evidence_units=(evidence,),
        ),
        fused_score=1.0 / value,
    )


def _search_service(
    *,
    sources: tuple[EvidenceSource, ...],
    embedding: RecordingEmbedding | None = None,
    sparse_failure: Exception | None = None,
    hybrid: bool = False,
    with_policy: bool = True,
) -> tuple[
    SearchApplicationService,
    InMemorySearchConfigurationResolver,
    AuthoritativeSourceResolver,
    RecordingEmbedding,
]:
    exact_embedding = embedding or RecordingEmbedding()
    resolver = InMemorySearchConfigurationResolver(
        _configuration(exact_embedding, hybrid=hybrid, with_policy=with_policy)
    )
    source_resolver = AuthoritativeSourceResolver(sources)
    sparse_hits = tuple(
        SparseHit(source.chunk, rank=index, score=10.0 / index)
        for index, source in enumerate(sources, start=1)
    )
    service = SearchApplicationService(
        configuration_resolver=resolver,
        scope_resolver=RecordingScopeResolver(),
        sparse_retriever=SparseRetriever(sparse_hits, sparse_failure),
        dense_retriever=DenseRetriever(),
        source_resolver=source_resolver,
    )
    return service, resolver, source_resolver, exact_embedding


def _post_search(service: SearchApplicationService, query: str = "환매 수수료"):
    app = create_app()
    app.dependency_overrides[get_current_user] = owner
    app.dependency_overrides[get_search_service] = lambda: service
    with TestClient(app) as client:
        return client.post(
            "/api/v1/rag/search",
            json={
                "query": query,
                "configuration_id": str(CONFIGURATION_ID),
                "workspace_ids": [str(WORKSPACE_ID)],
                "folder_ids": [],
                "top_k": 10,
            },
        )


def test_supported_search_returns_extractive_answer_and_authenticated_actor() -> None:
    source = _source(1, "환매 수수료는 1%입니다.")
    service, resolver, source_resolver, _ = _search_service(sources=(source,))

    response = _post_search(service)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "supported"
    assert payload["answer"]["excerpt"] == source.chunk.evidence_units[0].text
    assert payload["answer"]["source"]["asset_version_id"] == str(
        source.chunk.asset_version_id
    )
    assert payload["answer"]["source"]["document_id"] == str(source.document_id)
    assert payload["answer"]["source"]["projection_id"] == str(
        source.chunk.projection_id
    )
    assert payload["answer"]["source"]["evidence_unit_id"] == str(
        source.chunk.evidence_units[0].id
    )
    assert payload["configuration_version"] == {
        "configuration_id": str(CONFIGURATION_ID),
        "version_id": str(CONFIGURATION_VERSION_ID),
        "version": 3,
    }
    assert resolver.calls == [(CONFIGURATION_ID, ACTOR_ID)]
    assert source_resolver.calls[0][0] == ACTOR_ID


def test_related_source_alone_never_changes_insufficient_status() -> None:
    source = _source(1, "관련 운용 지침입니다.")
    service, _, _, _ = _search_service(sources=(source,))

    response = _post_search(service)

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["answer"] is None
    assert [item["asset_version_id"] for item in response.json()["related_sources"]] == [
        str(source.chunk.asset_version_id)
    ]


def test_conflicting_sources_are_returned_separately() -> None:
    first = _source(1, "최소 가입 금액은 100만원입니다.")
    second = _source(2, "최소 가입 금액은 200만원입니다.")
    service, _, _, _ = _search_service(sources=(first, second))

    response = _post_search(service, query="최소 가입 금액")

    assert response.status_code == 200
    assert response.json()["conflict_state"] == "separate_sources"
    assert response.json()["answer"]["excerpt"] == first.chunk.evidence_units[0].text
    assert [item["excerpt"] for item in response.json()["conflicts"]] == [
        second.chunk.evidence_units[0].text
    ]
    assert response.json()["related_sources"] == []


def test_unproven_wording_difference_remains_a_related_source() -> None:
    first = _source(1, "최소 가입 금액은 100만원입니다.")
    second = _source(2, "100만원이 최소 가입 금액으로 적용됩니다.")
    service, _, _, _ = _search_service(sources=(first, second))

    response = _post_search(service, query="최소 가입 금액")

    assert response.status_code == 200
    assert response.json()["conflict_state"] == "none"
    assert response.json()["conflicts"] == []
    assert [item["asset_version_id"] for item in response.json()["related_sources"]] == [
        str(second.chunk.asset_version_id)
    ]


def test_private_and_inactive_candidates_are_removed_before_semantic_encoding() -> None:
    public = _source(1, "가입 후 해지 조건입니다.")
    private = _source(2, "비공개 개인 문서 본문", workspace_id=PRIVATE_WORKSPACE_ID)
    inactive = _source(3, "비활성 구버전 본문")
    embedding = RecordingEmbedding(
        {
            "환매 요건": [1.0, 0.0],
            public.chunk.evidence_units[0].text: [1.0, 0.0],
        }
    )
    service, resolver, _, _ = _search_service(
        sources=(public, private, inactive),
        embedding=embedding,
    )
    service.source_resolver = AuthoritativeSourceResolver((public,))

    response = _post_search(service, query="환매 요건")

    assert response.status_code == 200
    assert response.json()["status"] == "supported"
    assert embedding.encoded_documents == [public.chunk.evidence_units[0].text]
    assert private.chunk.evidence_units[0].text not in response.text
    assert inactive.chunk.evidence_units[0].text not in response.text
    assert resolver.calls == [(CONFIGURATION_ID, ACTOR_ID)]


def test_bm25_only_retrieval_can_select_semantic_evidence() -> None:
    source = _source(1, "가입 후 해지 조건입니다.")
    embedding = RecordingEmbedding(
        {
            "상품 유동성": [1.0, 0.0],
            source.chunk.evidence_units[0].text: [1.0, 0.0],
        }
    )
    service, _, _, _ = _search_service(sources=(source,), embedding=embedding)

    response = _post_search(service, query="상품 유동성")

    assert response.status_code == 200
    assert response.json()["status"] == "supported"
    assert response.json()["answer"]["highlights"][0]["kind"] == "semantic"


def test_evidence_embedding_runtime_failure_is_a_typed_api_outage() -> None:
    source = _source(1, "가입 후 해지 조건입니다.")
    embedding = RecordingEmbedding(
        document_error=EmbeddingRuntimeUnavailableError("model process unavailable")
    )
    service, _, _, _ = _search_service(sources=(source,), embedding=embedding)

    response = _post_search(service, query="상품 유동성")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "evidence_embedding_unavailable"


class DocumentEncodingFailureModel:
    def __init__(self, failure: Exception) -> None:
        self.failure = failure
        self.calls: list[list[str]] = []
        self.tokenizer = lambda *args, **kwargs: {"input_ids": [1, 2]}

    def get_sentence_embedding_dimension(self) -> int:
        return 2

    def encode(self, texts: Sequence[str], **kwargs: object) -> list[list[float]]:
        del kwargs
        exact_texts = list(texts)
        self.calls.append(exact_texts)
        if exact_texts[0].startswith("passage: "):
            raise self.failure
        return [[1.0, 0.0] for _ in exact_texts]


@pytest.mark.parametrize("failure_type", [OSError, RuntimeError])
def test_bm25_semantic_path_maps_production_document_runtime_failure_to_503(
    tmp_path: Path,
    failure_type: type[Exception],
) -> None:
    source = _source(1, "가입 후 해지 조건입니다.")
    failure = failure_type("production document encoding failed")
    model = DocumentEncodingFailureModel(failure)
    embedding = SentenceTransformerEmbedding(
        EmbeddingModelConfig(
            repo_id="synthetic/local-model",
            revision="a" * 40,
            dimension=2,
            max_tokens=32,
            query_prefix="query: ",
            document_prefix="passage: ",
            normalize=True,
            device="cpu",
            dtype="float32",
            output_mode="dense",
            data_policy="local_only",
            batch_size=2,
        ),
        cache_folder=tmp_path,
        loader=lambda *args, **kwargs: model,
    )
    resolver = InMemorySearchConfigurationResolver(_configuration(embedding))
    source_resolver = AuthoritativeSourceResolver((source,))
    service = SearchApplicationService(
        configuration_resolver=resolver,
        scope_resolver=RecordingScopeResolver(),
        sparse_retriever=SparseRetriever((SparseHit(source.chunk, rank=1, score=10.0),)),
        dense_retriever=DenseRetriever(),
        source_resolver=source_resolver,
    )

    response = _post_search(service, query="상품 유동성")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "evidence_embedding_unavailable"
    assert model.calls == [
        ["query: 상품 유동성"],
        ["passage: 가입 후 해지 조건입니다."],
    ]


def test_evidence_embedding_programming_defect_propagates() -> None:
    source = _source(1, "가입 후 해지 조건입니다.")
    embedding = RecordingEmbedding(document_error=ValueError("wrong vector batch"))
    service, _, _, _ = _search_service(sources=(source,), embedding=embedding)

    with pytest.raises(ValueError, match="wrong vector batch"):
        _post_search(service, query="상품 유동성")


def test_hybrid_branch_failure_is_an_explicit_api_failure() -> None:
    service, _, _, _ = _search_service(
        sources=(_source(1, "환매 수수료는 1%입니다."),),
        sparse_failure=SearchBackendUnavailableError("sparse unavailable"),
        hybrid=True,
    )

    response = _post_search(service)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "hybrid_search_unavailable"


def test_configuration_without_answer_policy_is_rejected_before_retrieval() -> None:
    service, _, source_resolver, _ = _search_service(
        sources=(_source(1, "환매 수수료는 1%입니다."),),
        with_policy=False,
    )

    response = _post_search(service)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "answer_policy_missing"
    assert source_resolver.calls == []


class MemoryViewerAccessRepository(ViewerResourceAccessRepositoryPort):
    def __init__(self, resource: ViewerResource | None) -> None:
        self.resource = resource
        self.calls: list[tuple[UUID, UUID, UUID]] = []

    async def resolve(
        self,
        *,
        actor_id: UUID,
        asset_version_id: UUID,
        projection_id: UUID,
    ) -> ViewerResource | None:
        self.calls.append((actor_id, asset_version_id, projection_id))
        if (
            self.resource is None
            or self.resource.asset_version_id != asset_version_id
            or self.resource.projection_id != projection_id
        ):
            return None
        return self.resource


class MemoryObjectStore:
    def __init__(self, values: dict[str, bytes]) -> None:
        self.values = values
        self.open_calls: list[str] = []

    async def put(self, key: str, source: AsyncIterator[bytes]) -> StoredObject:
        del key, source
        raise AssertionError("viewer never writes objects")

    async def open(self, key: str) -> AsyncIterator[bytes]:
        self.open_calls.append(key)
        content = self.values[key]
        yield content

    async def delete(self, key: str) -> None:
        del key
        raise AssertionError("viewer never deletes objects")


def _parsed_artifact(asset_version_id: UUID) -> bytes:
    element_id = UUID("c0000000-0000-0000-0000-000000000001")
    return serialize_parsed_document(
        ParsedDocument(
            asset_version_id=asset_version_id,
            parser_name="plain-text",
            parser_version="1",
            elements=(
                StructuralElement(
                    id=element_id,
                    ordinal=0,
                    kind="paragraph",
                    text="정규화된 공개 테스트 문장",
                    section_path=("개요",),
                    location=SourceLocation(element_id, None, 0, 15, None),
                    parser_name="plain-text",
                    parser_version="1",
                    confidence=1.0,
                ),
            ),
        )
    )


def _pdf_bytes() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Public synthetic PDF page")
    content = document.tobytes()
    document.close()
    return content


class _RenderDocument:
    page_count = 1

    def __init__(self, page: object | None = None, error: Exception | None = None) -> None:
        self.page = page
        self.error = error

    def load_page(self, page_index: int) -> object:
        assert page_index == 0
        if self.error is not None:
            raise self.error
        assert self.page is not None
        return self.page

    def close(self) -> None:
        return None


class _RenderPage:
    def __init__(self, pixmap: object | None = None, error: Exception | None = None) -> None:
        self.pixmap = pixmap
        self.error = error

    def get_pixmap(self, *, alpha: bool) -> object:
        assert alpha is False
        if self.error is not None:
            raise self.error
        assert self.pixmap is not None
        return self.pixmap


class _RenderPixmap:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def tobytes(self, output: str) -> bytes:
        assert output == "png"
        if self.error is not None:
            raise self.error
        return b"synthetic-png"


def _assert_pdf_render_503(error: AppError) -> None:
    assert error.status_code == 503
    assert error.code == "source_artifact_invalid"


def test_pdf_open_operational_error_is_typed_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_open(*, stream: bytes, filetype: str) -> object:
        del stream, filetype
        raise OSError("synthetic open failure")

    monkeypatch.setattr(viewer_module.pymupdf, "open", fail_open)

    with pytest.raises(AppError) as caught:
        viewer_module._render_pdf_page(b"synthetic", 1)

    _assert_pdf_render_503(caught.value)


def test_pdf_load_page_operational_error_is_typed_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _RenderDocument(error=RuntimeError("synthetic load failure"))
    monkeypatch.setattr(viewer_module.pymupdf, "open", lambda **_kwargs: document)

    with pytest.raises(AppError) as caught:
        viewer_module._render_pdf_page(b"synthetic", 1)

    _assert_pdf_render_503(caught.value)


def test_pdf_get_pixmap_operational_error_is_typed_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _RenderDocument(page=_RenderPage(error=OSError("synthetic raster failure")))
    monkeypatch.setattr(viewer_module.pymupdf, "open", lambda **_kwargs: document)

    with pytest.raises(AppError) as caught:
        viewer_module._render_pdf_page(b"synthetic", 1)

    _assert_pdf_render_503(caught.value)


def test_pdf_png_conversion_operational_error_is_typed_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _RenderDocument(
        page=_RenderPage(pixmap=_RenderPixmap(RuntimeError("synthetic PNG failure")))
    )
    monkeypatch.setattr(viewer_module.pymupdf, "open", lambda **_kwargs: document)

    with pytest.raises(AppError) as caught:
        viewer_module._render_pdf_page(b"synthetic", 1)

    _assert_pdf_render_503(caught.value)


def test_pdf_page_bound_remains_nondisclosing_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _RenderDocument(page=_RenderPage(pixmap=_RenderPixmap()))
    monkeypatch.setattr(viewer_module.pymupdf, "open", lambda **_kwargs: document)

    with pytest.raises(AppError) as caught:
        viewer_module._render_pdf_page(b"synthetic", 2)

    assert caught.value.status_code == 404
    assert caught.value.code == "not_found"


def test_pdf_render_programming_defect_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _RenderDocument(error=TypeError("synthetic programming defect"))
    monkeypatch.setattr(viewer_module.pymupdf, "open", lambda **_kwargs: document)

    with pytest.raises(TypeError, match="synthetic programming defect"):
        viewer_module._render_pdf_page(b"synthetic", 1)


def _viewer_resource(*, media_type: str, original: bytes, parsed: bytes) -> ViewerResource:
    return ViewerResource(
        document_id=UUID("d0000000-0000-0000-0000-000000000001"),
        asset_version_id=UUID("d0000000-0000-0000-0000-000000000002"),
        asset_version_number=4,
        workspace_id=WORKSPACE_ID,
        folder_id=None,
        projection_id=UUID("d0000000-0000-0000-0000-000000000003"),
        title="source.pdf" if media_type == "application/pdf" else "source.txt",
        media_type=media_type,
        original_object_key="authorized/original",
        original_size=len(original),
        original_sha256=sha256(original).hexdigest(),
        parsed_object_key="authorized/parsed",
        parsed_sha256=sha256(parsed).hexdigest(),
    )


def _viewer_client(
    repository: MemoryViewerAccessRepository,
    store: MemoryObjectStore,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = owner
    app.dependency_overrides[get_viewer_service] = lambda: ViewerService(repository, store)
    return TestClient(app)


def test_text_and_pdf_viewers_independently_reauthorize_exact_resource() -> None:
    pdf = _pdf_bytes()
    parsed = _parsed_artifact(UUID("d0000000-0000-0000-0000-000000000002"))
    resource = _viewer_resource(media_type="application/pdf", original=pdf, parsed=parsed)
    repository = MemoryViewerAccessRepository(resource)
    store = MemoryObjectStore(
        {"authorized/original": pdf, "authorized/parsed": parsed}
    )

    with _viewer_client(repository, store) as client:
        text_response = client.get(
            f"/api/v1/rag/sources/{resource.asset_version_id}/normalized-text",
            params={"projection_id": str(resource.projection_id)},
        )
        pdf_response = client.get(
            f"/api/v1/rag/sources/{resource.asset_version_id}/pdf/pages/1",
            params={"projection_id": str(resource.projection_id)},
        )

    assert text_response.status_code == 200
    assert text_response.json()["elements"][0]["text"] == "정규화된 공개 테스트 문장"
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"] == "image/png"
    assert pdf_response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert repository.calls == [
        (ACTOR_ID, resource.asset_version_id, resource.projection_id),
        (ACTOR_ID, resource.asset_version_id, resource.projection_id),
    ]


def test_unauthorized_or_inactive_viewer_resource_is_404_before_object_access() -> None:
    repository = MemoryViewerAccessRepository(None)
    store = MemoryObjectStore({})
    asset_version_id = UUID("e0000000-0000-0000-0000-000000000001")
    projection_id = UUID("e0000000-0000-0000-0000-000000000002")

    with _viewer_client(repository, store) as client:
        response = client.get(
            f"/api/v1/rag/sources/{asset_version_id}/normalized-text",
            params={"projection_id": str(projection_id)},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert repository.calls == [(ACTOR_ID, asset_version_id, projection_id)]
    assert store.open_calls == []


def test_normalized_viewer_rejects_unsupported_content_before_object_access() -> None:
    original = b"synthetic"
    asset_version_id = UUID("f0000000-0000-0000-0000-000000000001")
    parsed = _parsed_artifact(asset_version_id)
    resource = ViewerResource(
        document_id=UUID("f0000000-0000-0000-0000-000000000002"),
        asset_version_id=asset_version_id,
        asset_version_number=1,
        workspace_id=WORKSPACE_ID,
        folder_id=None,
        projection_id=UUID("f0000000-0000-0000-0000-000000000003"),
        title="unsupported.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        original_object_key="authorized/original",
        original_size=len(original),
        original_sha256=sha256(original).hexdigest(),
        parsed_object_key="authorized/parsed",
        parsed_sha256=sha256(parsed).hexdigest(),
    )
    repository = MemoryViewerAccessRepository(resource)
    store = MemoryObjectStore(
        {"authorized/original": original, "authorized/parsed": parsed}
    )

    with _viewer_client(repository, store) as client:
        response = client.get(
            f"/api/v1/rag/sources/{resource.asset_version_id}/normalized-text",
            params={"projection_id": str(resource.projection_id)},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert store.open_calls == []
