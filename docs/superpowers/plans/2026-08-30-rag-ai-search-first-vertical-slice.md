# RAG AI Search First Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first end-to-end asset-management RAG search slice from Markdown, TXT, and text-native PDF ingestion through permission-filtered BM25+dense+RRF retrieval, extractive evidence, semantic highlights, saved RAG configurations, and comparable evaluation runs.

**Architecture:** Keep Platform independent from Labs/RAG and compose cross-module workflows only in API and worker composition roots. PostgreSQL and the object store remain authoritative, Elasticsearch 9.5.2 is a rebuildable search projection, Redis is only the Celery broker, and user search stays synchronous. Technical Indexing/Retrieval profiles remain immutable; a user-facing Saved RAG Configuration references their exact versions.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2 async, Alembic, Celery 5.6, PostgreSQL 17, Redis 8, Elasticsearch 9.5.2 with elasticsearch-py 9.5, PyMuPDF 1.28, sentence-transformers 6, React, TypeScript, React Router, Vitest, Testing Library, Docker Compose.

**Spec:** `docs/labs/rag/designs/2026-08-30-ai-search-detailed-design.md`

## Global Constraints

- The first parser set is Markdown, TXT, and text-native PDF only.
- Use `multilingual-e5-base` as Model A with a 512-token ceiling and an initial 380-token chunk target.
- Use `BAAI/bge-m3` as Model B with an 8192-token ceiling and dense output only; do not enable its sparse or ColBERT outputs in the first comparison.
- Create a new Indexing Profile Version with `target_tokens=380` and `overlap_tokens=60`; never mutate baseline Version 1.
- BM25 and dense retrieval must receive the same workspace, folder, document-version, status, and permission filters before search.
- Combine BM25 and dense ranks in Python with RRF `k=60`; do not use Elasticsearch's licensed RRF feature.
- Do not use an LLM in initial ranking, evidence selection, or answer generation.
- Normal search accepts only READY projections and an evaluated default Saved RAG Configuration.
- Search experiments may use draft configurations but must label them experimental.
- The top answer is a source excerpt. Return `INSUFFICIENT_EVIDENCE` when the selected answer policy cannot support a direct answer.
- Elasticsearch is never the source of truth. Every hit must resolve to PostgreSQL and object-store provenance.
- Redis messages contain IDs and routing metadata only, never document text.
- Private documents and embeddings stay local; model downloads do not transmit document content.
- Saving a RAG configuration creates an immutable version and never changes the operational default.
- The only pre-created user-visible configuration is the BM25 baseline.
- Evaluation thresholds are stored in a versioned Evaluation Policy after baseline measurement; no configuration can pass without one.
- Access-control leakage tolerance is exactly zero.
- Unit tests run without Elasticsearch, model downloads, or network access by using ports and deterministic fakes.
- DOCX and scanned-PDF OCR are explicitly outside this plan and require separate implementation plans after this slice passes.

---

## File Map

### Backend modules

- `labs/rag/documents`: common document model, structural elements, provenance, retrieval chunks, evidence units, projection state, repositories.
- `labs/rag/parsing`: parser port, parser registry, TXT, Markdown, and PyMuPDF adapters.
- `labs/rag/chunking`: deterministic structural chunker and evidence-unit construction.
- `labs/rag/ingestion`: idempotent orchestration from AssetVersion to READY projection.
- `labs/rag/indexing`: dimension-aware index descriptors, Elasticsearch mapping, bulk projection, count verification, alias activation.
- `labs/rag/embeddings`: embedding port, sentence-transformers adapter, fake adapter, model cache.
- `labs/rag/retrieval`: scope resolution, BM25 and dense adapters, RRF, deduplication.
- `labs/rag/highlighting`: evidence selection, answer status, keyword and semantic spans.
- `labs/rag/configurations`: immutable user-facing Saved RAG Configurations and compatibility rules.
- `labs/rag/evaluation`: datasets, metrics, runs, policies, Celery evaluation task, promotion gate.
- `labs/rag/search`: synchronous application service, schemas, API, viewer resource API.

### Frontend modules

- `labs/rag/search`: search form, evidence-first result, related sources, text/PDF viewer.
- `labs/rag/configurations`: RAG configuration builder, saved list, compare view, model registry tab.

### Infrastructure and contracts

- `infrastructure/elasticsearch`: versioned mapping and index template JSON.
- `infrastructure/compose/compose.yaml`: Elasticsearch service and health dependency.
- `model-profiles/rag`: versioned built-in model catalog entries, E5/BGE Indexing Profiles, and retrieval baselines.
- `sample-data/public/rag`: synthetic search and evaluation fixtures only.
- `backend/alembic/versions/0006_rag_search_documents.py`: RAG projection and provenance schema.
- `backend/alembic/versions/0007_rag_configurations.py`: Saved RAG Configuration schema.
- `backend/alembic/versions/0008_rag_evaluation.py`: evaluation datasets, policies, runs, and cases.

---

### Task 1: Elasticsearch runtime and dependency foundation

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Modify: `backend/src/ai_workshop/config.py`
- Create: `backend/src/ai_workshop/infrastructure/search/elasticsearch.py`
- Create: `backend/src/ai_workshop/infrastructure/search/__init__.py`
- Modify: `backend/tests/unit/test_config.py`
- Create: `backend/tests/unit/infrastructure/search/test_elasticsearch_factory.py`
- Modify: `infrastructure/compose/compose.yaml`
- Create: `infrastructure/elasticsearch/README.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: existing `Settings`, FastAPI dependency injection, Docker Compose network.
- Produces: `create_elasticsearch(settings: Settings) -> AsyncElasticsearch` and settings `elasticsearch_url`, `elasticsearch_index_prefix`, `model_cache_root`.

- [ ] **Step 1: Add failing settings tests.**

```python
def test_rag_runtime_settings_have_local_defaults() -> None:
    settings = Settings(secret_key="x" * 32)
    assert settings.elasticsearch_url == "http://127.0.0.1:9200"
    assert settings.elasticsearch_index_prefix == "ai-workshop-rag"
    assert settings.model_cache_root.name == "models"
```

- [ ] **Step 2: From `backend/`, run `uv run pytest tests/unit/test_config.py -q` and verify the new assertions fail with missing attributes.**

- [ ] **Step 3: Add exact dependencies and settings.**

```toml
"elasticsearch[async]>=9.5,<9.6",
"pymupdf>=1.28,<2.0",
"sentence-transformers>=6.0,<7.0",
```

```python
elasticsearch_url: str = "http://127.0.0.1:9200"
elasticsearch_index_prefix: str = "ai-workshop-rag"
model_cache_root: Path = Path(".local-data/models")
```

- [ ] **Step 4: Add a failing factory test that passes a Settings instance and asserts the client's configured host is the exact Elasticsearch URL.**

- [ ] **Step 5: Implement the async client factory without global network calls.**

```python
from elasticsearch import AsyncElasticsearch

def create_elasticsearch(settings: Settings) -> AsyncElasticsearch:
    return AsyncElasticsearch(settings.elasticsearch_url, request_timeout=30)
```

- [ ] **Step 6: Add Elasticsearch 9.5.2 to Compose with single-node mode, security disabled only for the local Compose network, a 1 GB JVM heap ceiling, a healthcheck, and an `elasticsearch-data` volume. Add `AI_WORKSHOP_ELASTICSEARCH_URL=http://elasticsearch:9200` to the backend anchor.**

- [ ] **Step 7: Run `uv lock`, the two unit test files, `uv run ruff check .`, `uv run mypy src`, and `docker compose -f infrastructure/compose/compose.yaml config --quiet`.**

- [ ] **Step 8: Commit only Task 1 files with `git commit -m "build:add-rag-search-runtime"`.**

### Task 2: Common document, provenance, and projection persistence

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/documents/__init__.py`
- Create: `backend/src/ai_workshop/labs/rag/documents/domain.py`
- Create: `backend/src/ai_workshop/labs/rag/documents/models.py`
- Create: `backend/src/ai_workshop/labs/rag/documents/repository.py`
- Create: `backend/alembic/versions/0006_rag_search_documents.py`
- Create: `backend/tests/unit/labs/rag/documents/test_document_domain.py`
- Create: `backend/tests/unit/labs/rag/documents/test_projection_state.py`
- Create: `backend/tests/integration/labs/rag/documents/test_document_repository.py`

**Interfaces:**
- Consumes: Platform `AssetVersion` UUID and immutable Profile UUID.
- Produces: `ParsedDocument`, `StructuralElement`, `SourceLocation`, `RetrievalChunk`, `EvidenceUnit`, `RagProjection`, `ProjectionStatus`, and `RagDocumentRepository`.

- [ ] **Step 1: Write failing tests for legal projection transitions and provenance completeness.**

```python
def test_projection_follows_required_stages() -> None:
    projection = RagProjection.pending(asset_version_id=uuid4(), indexing_profile_id=uuid4())
    for status in (
        ProjectionStatus.PARSING,
        ProjectionStatus.CHUNKING,
        ProjectionStatus.EMBEDDING,
        ProjectionStatus.INDEXING,
        ProjectionStatus.READY,
    ):
        projection = projection.transition(status)
    assert projection.status is ProjectionStatus.READY

def test_evidence_requires_source_location() -> None:
    with pytest.raises(ProvenanceError):
        EvidenceUnit.create(text="근거", location=None, ordinal=0)
```

- [ ] **Step 2: Run the two unit files and verify collection fails because the document domain does not exist.**

- [ ] **Step 3: Implement immutable dataclasses and enums.**

```python
class ProjectionStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    PARTIAL_READY = "partial_ready"

@dataclass(frozen=True, slots=True)
class SourceLocation:
    element_id: UUID
    page: int | None
    char_start: int
    char_end: int
    bbox: tuple[float, float, float, float] | None
```

- [ ] **Step 4: Define SQLAlchemy records for `rag_document_projections`, `rag_structural_elements`, `rag_retrieval_chunks`, `rag_evidence_units`, and `rag_index_builds`. Add uniqueness on `asset_version_id + indexing_profile_id` and `projection_id + ordinal`.**

- [ ] **Step 5: Write an integration test that stores one projection, one element, one chunk, and two evidence units and reloads all UUIDs, section paths, character offsets, and PDF coordinates unchanged.**

- [ ] **Step 6: Implement `RagDocumentRepository` and `SqlAlchemyRagDocumentRepository` with `add_projection`, `find_projection`, `save_parsed_document`, `replace_chunks`, and `mark_status`.**

- [ ] **Step 7: Run the unit and integration tests, `uv run alembic upgrade head` against the test database, `uv run alembic check`, Ruff, and mypy.**

- [ ] **Step 8: Commit Task 2 with `git commit -m "feat:add-rag-document-provenance"`.**

### Task 3: TXT, Markdown, and text-native PDF parsers

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/parsing/__init__.py`
- Create: `backend/src/ai_workshop/labs/rag/parsing/contracts.py`
- Create: `backend/src/ai_workshop/labs/rag/parsing/plain_text.py`
- Create: `backend/src/ai_workshop/labs/rag/parsing/markdown.py`
- Create: `backend/src/ai_workshop/labs/rag/parsing/pdf.py`
- Create: `backend/src/ai_workshop/labs/rag/parsing/registry.py`
- Create: `backend/src/ai_workshop/labs/rag/parsing/service.py`
- Create: `backend/tests/unit/labs/rag/parsing/test_plain_text_parser.py`
- Create: `backend/tests/unit/labs/rag/parsing/test_markdown_parser.py`
- Create: `backend/tests/unit/labs/rag/parsing/test_pdf_parser.py`
- Create: `backend/tests/unit/labs/rag/parsing/test_registry.py`
- Create: `backend/tests/fixtures/rag/sample_pdf.py`
- Create: `sample-data/public/rag/parser/sample.md`
- Create: `sample-data/public/rag/parser/sample.txt`

**Interfaces:**
- Consumes: local temporary `Path`, media type, original filename.
- Produces: `ParserPort.parse(request: ParseRequest) -> ParsedDocument` and `ParserRegistry.resolve(media_type, filename) -> ParserPort`.

- [ ] **Step 1: Write parser contract and failing registry tests.**

```python
@dataclass(frozen=True, slots=True)
class ParseRequest:
    path: Path
    media_type: str
    filename: str

class ParserPort(Protocol):
    def parse(self, request: ParseRequest) -> ParsedDocument:
        raise NotImplementedError
```

- [ ] **Step 2: Run `uv run pytest tests/unit/labs/rag/parsing -q` and verify imports fail.**

- [ ] **Step 3: Implement TXT decoding as UTF-8 with BOM support, CRLF normalization, paragraph boundaries, and explicit `unsupported_encoding` errors instead of silent replacement.**

- [ ] **Step 4: Implement the Markdown adapter for headings, paragraphs, list items, fenced-code exclusion from answer evidence, and source character offsets. Use a deterministic line-state parser so unit tests need no network or optional native package.**

- [ ] **Step 5: Add `sample_pdf.py` to generate a small PDF from fixed public synthetic text in the test temporary directory, then implement PyMuPDF extraction with page number, block order, character offsets, and span bounding boxes. Reject pages with no extractable text as `ocr_required`; do not commit a binary PDF fixture.**

- [ ] **Step 6: Add tests proving the same visible phrase maps to the expected heading path and that every PDF Evidence Unit remains inside its page bounds.**

- [ ] **Step 7: Implement `ParsingService.materialize_and_parse` to stream an ObjectStore object into `TemporaryDirectory`, call the selected parser, and remove temporary files in `finally`.**

- [ ] **Step 8: Run parser tests, Ruff, mypy, and commit with `git commit -m "feat:add-first-rag-parsers"`.**

### Task 4: Structural chunking and evidence-unit construction

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/chunking/__init__.py`
- Create: `backend/src/ai_workshop/labs/rag/chunking/contracts.py`
- Create: `backend/src/ai_workshop/labs/rag/chunking/service.py`
- Create: `backend/src/ai_workshop/labs/rag/chunking/sentences.py`
- Create: `backend/tests/unit/labs/rag/chunking/test_sentence_splitter.py`
- Create: `backend/tests/unit/labs/rag/chunking/test_structural_chunker.py`
- Create: `model-profiles/rag/indexing/e5-structure-aware-v2.yaml`
- Modify: `backend/tests/unit/labs/rag/models/test_profile_yaml.py`

**Interfaces:**
- Consumes: `ParsedDocument` and `ChunkingConfig(target_tokens=380, overlap_tokens=60)`.
- Produces: `ChunkingResult(chunks: tuple[RetrievalChunk, ...], evidence_units: tuple[EvidenceUnit, ...])`.

- [ ] **Step 1: Write failing sentence-boundary tests covering Korean punctuation, numbered clauses, list items, and table cells.**

- [ ] **Step 2: Write a failing chunker test proving no Evidence Unit is split, section paths are prepended as context, chunks stay at or below 440 tokens including context, and overlap is at most 60 tokens.**

- [ ] **Step 3: Define a deterministic `TokenCounter` port and use a character-independent fake in unit tests.**

```python
class TokenCounter(Protocol):
    def count(self, text: str) -> int:
        raise NotImplementedError
```

- [ ] **Step 4: Implement sentence, list-item, and table-cell Evidence Unit construction while preserving each unit's original `SourceLocation`.**

- [ ] **Step 5: Implement greedy structural packing with target 380, hard ceiling 440, overlap 60, and a single-unit overflow error that includes the element ID.**

- [ ] **Step 6: Add Indexing Profile Version 2 with `target_tokens: 380`, `overlap_tokens: 60`, the E5 embedding binding, and `evaluation_state: draft`. Extend YAML validation tests without changing Version 1.**

- [ ] **Step 7: Run chunking and profile tests, Ruff, mypy, then commit `git commit -m "feat:add-structure-aware-rag-chunking"`.**

### Task 5: Idempotent RAG ingestion orchestration

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/ingestion/__init__.py`
- Create: `backend/src/ai_workshop/labs/rag/ingestion/domain.py`
- Create: `backend/src/ai_workshop/labs/rag/ingestion/service.py`
- Create: `backend/src/ai_workshop/labs/rag/ingestion/tasks.py`
- Create: `backend/tests/unit/labs/rag/ingestion/test_ingestion_service.py`
- Create: `backend/tests/integration/labs/rag/ingestion/test_ingestion_task.py`
- Modify: `backend/src/ai_workshop/worker.py`
- Modify: `backend/src/ai_workshop/platform/assets/tasks.py`
- Modify: `backend/tests/integration/platform/assets/test_asset_task.py`

**Interfaces:**
- Consumes: verified `asset_version_id`, `indexing_profile_id`, parser, chunker, repositories, object store.
- Produces: `EnsureIndexedCommand`, `RagIngestionService.ensure_indexed(command) -> UUID`, and Celery task `ai_workshop.rag.ensure_indexed`.

- [ ] **Step 1: Write a failing idempotency test for the key `asset_version_id:indexing_profile_id:rag_ingestion`. Two requests must return the same active job or completed projection.**

- [ ] **Step 2: Write a failing lifecycle test asserting the exact status sequence PENDING, PARSING, CHUNKING, EMBEDDING, INDEXING, READY and terminal failure behavior.**

- [ ] **Step 3: Implement `EnsureIndexedCommand` and the ingestion service skeleton with one short transaction per stage boundary.**

```python
@dataclass(frozen=True, slots=True)
class EnsureIndexedCommand:
    asset_version_id: UUID
    indexing_profile_id: UUID
    requested_by: UUID
```

- [ ] **Step 4: Persist parsed JSON under `rag/parsed/{projection_id}.json` and chunk JSON under `rag/chunks/{projection_id}.json` before database status advances. Store only object keys and hashes in PostgreSQL.**

- [ ] **Step 5: Register the Celery task with JSON serialization and a `job_id` argument only. The task reloads every command parameter from PostgreSQL.**

- [ ] **Step 6: Change `AssetVerificationWorkflow.run` to return the verified AssetVersion ID. In `worker.py`, the composition root may ask the RAG configuration service for subscribed indexing profiles and enqueue RAG jobs; no Platform file may import `labs.rag`.**

- [ ] **Step 7: Add eager-mode integration tests for success, retry after parser failure, duplicate dispatch, and failure without automatic parser substitution.**

- [ ] **Step 8: Run affected asset, job, ingestion, worker tests, Ruff, mypy, and commit `git commit -m "feat:add-rag-ingestion-workflow"`.**

### Task 6: Elasticsearch index builds and BM25 projection

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/indexing/__init__.py`
- Create: `backend/src/ai_workshop/labs/rag/indexing/contracts.py`
- Create: `backend/src/ai_workshop/labs/rag/indexing/domain.py`
- Create: `backend/src/ai_workshop/labs/rag/indexing/elasticsearch.py`
- Create: `backend/src/ai_workshop/labs/rag/indexing/service.py`
- Create: `backend/tests/unit/labs/rag/indexing/test_index_descriptor.py`
- Create: `backend/tests/unit/labs/rag/indexing/test_projection_document.py`
- Create: `backend/tests/integration/labs/rag/indexing/test_elasticsearch_index.py`
- Create: `infrastructure/elasticsearch/rag-chunks-v1.json`

**Interfaces:**
- Consumes: READY-to-index chunks, evidence units, Indexing Profile Version, workspace ACL keys.
- Produces: `SearchIndexPort`, `IndexDescriptor(vector_dimension, similarity)`, `IndexingService.index_projection`, concrete index `{prefix}-{profile_id}-{build_id}`, and read alias `{prefix}-{profile_id}-active`.

- [ ] **Step 1: Write failing tests for deterministic index names, immutable concrete indices, 768- and 1024-dimension descriptors, and alias activation only after count verification.**

- [ ] **Step 2: Write a failing projection test that asserts these fields: `chunk_id`, `projection_id`, `asset_version_id`, `workspace_id`, `folder_id`, `allowed_user_ids`, `status`, `title`, `section_path`, `text`, `evidence_units`, `embedding`, and `index_build_id`.**

- [ ] **Step 3: Define the port.**

```python
class SearchIndexPort(Protocol):
    async def create(self, descriptor: IndexDescriptor) -> None:
        raise NotImplementedError
    async def bulk_upsert(self, index_name: str, documents: Sequence[IndexDocument]) -> int:
        raise NotImplementedError
    async def count_projection(self, index_name: str, projection_id: UUID) -> int:
        raise NotImplementedError
    async def activate(self, alias: str, index_name: str) -> None:
        raise NotImplementedError
```

- [ ] **Step 4: Add a mapping builder with text fields for BM25, keyword ACL fields, nested evidence metadata, and a cosine `dense_vector` whose `dims` comes from the immutable `IndexDescriptor`. Keep `rag-chunks-v1.json` as the reviewed 768-dimension E5 exemplar and test generation for both 768 and 1024 dimensions. Do not enable an Elasticsearch `semantic_text` field or licensed RRF.**

- [ ] **Step 5: Implement bulk indexing with stable document IDs equal to chunk UUIDs and `refresh=false`. Verify expected chunk count before the database records READY and before alias activation.**

- [ ] **Step 6: Run unit tests without Elasticsearch. Then start the Compose Elasticsearch service and run the explicit integration marker test proving BM25 finds a Korean product name and rejects a mismatched workspace filter.**

- [ ] **Step 7: Run Ruff, mypy, Compose config, and commit `git commit -m "feat:add-rag-bm25-index-projection"`.**

### Task 7: Local E5 embedding and dense projection

**Files:**
- Create: `backend/src/ai_workshop/cli.py`
- Create: `backend/src/ai_workshop/labs/rag/embeddings/__init__.py`
- Create: `backend/src/ai_workshop/labs/rag/embeddings/contracts.py`
- Create: `backend/src/ai_workshop/labs/rag/embeddings/sentence_transformers.py`
- Create: `backend/src/ai_workshop/labs/rag/embeddings/fake.py`
- Create: `backend/src/ai_workshop/labs/rag/models/catalog.py`
- Create: `backend/tests/unit/labs/rag/embeddings/test_model_config.py`
- Create: `backend/tests/unit/labs/rag/embeddings/test_sentence_transformer_adapter.py`
- Create: `backend/tests/unit/labs/rag/models/test_model_catalog.py`
- Create: `backend/tests/integration/labs/rag/embeddings/test_e5_smoke.py`
- Create: `model-profiles/rag/models/multilingual-e5-base-v1.yaml`
- Create: `model-profiles/rag/models/bge-m3-v1.yaml`
- Modify: `backend/pyproject.toml`
- Modify: `backend/src/ai_workshop/platform/identity/cli.py`
- Modify: `backend/src/ai_workshop/labs/rag/ingestion/service.py`
- Modify: `backend/src/ai_workshop/labs/rag/indexing/service.py`
- Modify: `backend/src/ai_workshop/shared/model_registry.py`
- Modify: `infrastructure/compose/compose.yaml`

**Interfaces:**
- Consumes: pinned built-in Model Definition or an equivalently validated owner-registered definition, and local model cache.
- Produces: idempotent model-catalog import, dimension-configured `EmbeddingPort.encode_documents`, `EmbeddingPort.encode_query`, normalized vectors, and `SentenceTransformerEmbedding`; the E5 definition produces 768 floats.

- [ ] **Step 1: Write failing validation tests requiring `repo_id`, 40-character `revision`, `dimension`, `max_tokens`, `query_prefix`, `document_prefix`, `normalize`, `device`, `dtype`, `output_mode`, and `data_policy=local_only`. Reject `revision=main`, non-local data policy, and output dimensions that disagree with the definition.**

- [ ] **Step 2: Define the embedding port.**

```python
class EmbeddingPort(Protocol):
    dimension: int
    def count_tokens(self, text: str) -> int:
        raise NotImplementedError
    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError
    def encode_query(self, text: str) -> list[float]:
        raise NotImplementedError
```

- [ ] **Step 3: Implement a deterministic fake that hashes tokens into a fixed-size normalized vector and use it in all default unit tests.**

- [ ] **Step 4: Add model catalog YAML parsing and an idempotent `ai-workshop register-rag-models` command. Move root CLI dispatch to `ai_workshop.cli` while retaining `bootstrap-owner`. Catalog E5 at revision `d128750597153bb5987e10b1c3493a34e5a4502a` and BGE-M3 at revision `5617a9f61b028005a4858fdac845db406aefb181`; an existing identical name/version is a no-op and a conflicting definition is an error. This imports technical Model Definitions only, never Saved RAG Configurations.**

- [ ] **Step 5: Implement the sentence-transformers adapter with `trust_remote_code=False`, the configured full revision, local cache folder, explicit device/dtype, model-specific prefixes, normalization, output-mode validation, dimension validation, and batch size from the profile. E5 uses `query: ` and `passage: ` prefixes.**

- [ ] **Step 6: Extend ingestion so EMBEDDING writes vectors only after chunk persistence and INDEXING receives chunk/vector pairs with equal counts. Reject token overflow and dimension mismatch before Elasticsearch writes.**

- [ ] **Step 7: Mount a named read-write model cache volume only into worker and explicit model tools, not the frontend. Add no document content to that volume.**

- [ ] **Step 8: Add an opt-in smoke test guarded by `AI_WORKSHOP_MODEL_SMOKE=1` that loads the pinned E5 revision, emits 768 values, and keeps document text local. Default tests must skip it.**

- [ ] **Step 9: Run catalog, CLI, embedding, and ingestion tests, Ruff, mypy, then commit `git commit -m "feat:add-local-e5-embeddings"`.**

### Task 8: Permission scope, BM25+dense retrieval, and Python RRF

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/retrieval/__init__.py`
- Create: `backend/src/ai_workshop/labs/rag/retrieval/domain.py`
- Create: `backend/src/ai_workshop/labs/rag/retrieval/scope.py`
- Create: `backend/src/ai_workshop/labs/rag/retrieval/rrf.py`
- Create: `backend/src/ai_workshop/labs/rag/retrieval/elasticsearch.py`
- Create: `backend/src/ai_workshop/labs/rag/retrieval/service.py`
- Create: `backend/tests/unit/labs/rag/retrieval/test_scope.py`
- Create: `backend/tests/unit/labs/rag/retrieval/test_rrf.py`
- Create: `backend/tests/unit/labs/rag/retrieval/test_service.py`
- Create: `backend/tests/integration/labs/rag/retrieval/test_hybrid_search.py`

**Interfaces:**
- Consumes: caller UUID, requested workspace/folder IDs, Retrieval Profile Version, query embedding, active index alias.
- Produces: `ResolvedSearchScope`, `SparseHit`, `DenseHit`, `FusedHit`, `rrf_fuse`, and `HybridRetrievalService.search`.

- [ ] **Step 1: Write failing scope tests: company membership passes, own personal workspace passes, another personal workspace returns not found, expired temporary workspace is excluded, and an empty authorized scope is rejected before Elasticsearch.**

- [ ] **Step 2: Define one immutable filter object and require both retriever calls to receive the same instance.**

```python
@dataclass(frozen=True, slots=True)
class ResolvedSearchScope:
    workspace_ids: tuple[UUID, ...]
    folder_ids: tuple[UUID, ...]
    active_only: bool = True
    ready_only: bool = True
```

- [ ] **Step 3: Write RRF tests for disjoint hits, duplicate chunk IDs, tie-breaking by best individual rank, and stable ordering.**

```python
def test_rrf_combines_duplicate_chunk() -> None:
    result = rrf_fuse(
        sparse=[RankedHit("a", 1), RankedHit("b", 2)],
        dense=[RankedHit("b", 1), RankedHit("c", 2)],
        k=60,
    )
    assert result[0].chunk_id == "b"
```

- [ ] **Step 4: Implement separate Elasticsearch BM25 and kNN requests with the same bool filter. Request only IDs, scores, provenance, text, section path, and evidence metadata; exclude stored vectors from responses.**

- [ ] **Step 5: Run both requests in an `asyncio.TaskGroup` after permission resolution and query embedding complete. Do not share an AsyncSession between the tasks.**

- [ ] **Step 6: Treat either branch failure as `hybrid_search_unavailable`. BM25-only behavior must use its own Retrieval Profile and must not be an exception fallback.**

- [ ] **Step 7: Add an integration test with company and private-personal chunks proving both BM25 and kNN prefilters prevent the private chunk from entering candidates.**

- [ ] **Step 8: Run retrieval tests, Ruff, mypy, and commit `git commit -m "feat:add-permission-filtered-hybrid-retrieval"`.**

### Task 9: Evidence selection, semantic highlights, search API, and viewer resources

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/highlighting/__init__.py`
- Create: `backend/src/ai_workshop/labs/rag/highlighting/domain.py`
- Create: `backend/src/ai_workshop/labs/rag/highlighting/service.py`
- Create: `backend/src/ai_workshop/labs/rag/search/__init__.py`
- Create: `backend/src/ai_workshop/labs/rag/search/configuration_port.py`
- Create: `backend/src/ai_workshop/labs/rag/search/schemas.py`
- Create: `backend/src/ai_workshop/labs/rag/search/service.py`
- Create: `backend/src/ai_workshop/labs/rag/search/api.py`
- Create: `backend/tests/unit/labs/rag/highlighting/test_evidence_selector.py`
- Create: `backend/tests/unit/labs/rag/highlighting/test_highlights.py`
- Create: `backend/tests/integration/labs/rag/search/test_search_api.py`
- Modify: `backend/src/ai_workshop/main.py`

**Interfaces:**
- Consumes: fused chunks, Evidence Units, query, embedding port, `SearchConfigurationResolverPort`, versioned Answer Policy, caller scope.
- Produces: `AnswerStatus`, `HighlightKind`, `EvidenceAnswer`, `SearchResponse`, `POST /api/v1/rag/search`, and viewer-resource endpoints.

- [ ] **Step 1: Write failing evidence tests for exact keyword spans, whole-unit semantic spans, missing provenance, conflicting top sources, and insufficient evidence.**

```python
class AnswerStatus(StrEnum):
    SUPPORTED = "supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"

class HighlightKind(StrEnum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
```

- [ ] **Step 2: Implement `AnswerPolicy` with explicit `min_semantic_score`, `min_keyword_coverage`, `require_complete_provenance=True`, and `conflict_mode="separate_sources"`. Reject search if the selected configuration lacks a policy version.**

- [ ] **Step 3: Implement keyword normalization and original-text offset mapping. For semantic selection, encode only Evidence Units from the top fused chunks and select units meeting the policy score. Never ask Elasticsearch to highlight vector fields.**

- [ ] **Step 4: Define `SearchConfigurationResolverPort.resolve(configuration_id, actor_id) -> ResolvedSearchConfiguration` and implement the synchronous search application service against that port. Use an in-memory resolver in Task 9 tests; Task 10 supplies the persistent Saved RAG Configuration adapter before the slice is operational.**

```python
class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    configuration_id: UUID
    workspace_ids: list[UUID] = Field(min_length=1)
    folder_ids: list[UUID] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=50)
```

- [ ] **Step 5: Return a top evidence answer, source document/version/location, keyword or semantic highlight spans, Saved RAG Configuration Version, conflicts, and a deduplicated related-source list. Related sources alone must never change the answer to SUPPORTED.**

- [ ] **Step 6: Add authorized viewer endpoints for normalized text and PDF page images. Resolve every resource through Asset Version and workspace access before streaming object-store content; unauthorized resources return 404.**

- [ ] **Step 7: Add API tests for SUPPORTED, INSUFFICIENT_EVIDENCE, conflict separation, private-source exclusion, inactive-version exclusion, and hybrid-branch failure.**

- [ ] **Step 8: Register the router, regenerate OpenAPI and TypeScript schema, run contract tests and `pnpm --dir frontend api:check`.**

- [ ] **Step 9: Run backend tests, Ruff, mypy, and commit `git commit -m "feat:add-grounded-rag-search-api"`.**

### Task 10: Immutable Saved RAG Configurations

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/configurations/__init__.py`
- Create: `backend/src/ai_workshop/labs/rag/configurations/domain.py`
- Create: `backend/src/ai_workshop/labs/rag/configurations/models.py`
- Create: `backend/src/ai_workshop/labs/rag/configurations/repository.py`
- Create: `backend/src/ai_workshop/labs/rag/configurations/service.py`
- Create: `backend/src/ai_workshop/labs/rag/configurations/schemas.py`
- Create: `backend/src/ai_workshop/labs/rag/configurations/api.py`
- Create: `backend/alembic/versions/0007_rag_configurations.py`
- Create: `backend/tests/unit/labs/rag/configurations/test_configuration.py`
- Create: `backend/tests/integration/labs/rag/configurations/test_configuration_api.py`
- Create: `backend/tests/integration/labs/rag/configurations/test_search_configuration_resolver.py`
- Modify: `backend/src/ai_workshop/main.py`
- Modify: `backend/src/ai_workshop/worker.py`
- Modify: `backend/src/ai_workshop/labs/rag/search/service.py`

**Interfaces:**
- Consumes: owner, exact Indexing/Retrieval/optional Generation Profile IDs, and validated Answer Policy fields.
- Produces: `AnswerPolicyVersion`, `SavedRagConfiguration`, immutable versions, list/create/default APIs, and subscribed indexing-profile IDs for new Asset Versions.

- [ ] **Step 1: Write failing compatibility tests: retrieval profile must reference the chosen indexing profile, generation is null in V1, Answer Policy versions and saved configuration versions are immutable, and default promotion requires PASSED.**

- [ ] **Step 2: Implement the aggregate.**

```python
@dataclass(frozen=True, slots=True)
class SavedRagConfiguration:
    id: UUID
    owner_id: UUID | None
    name: str
    version: int
    indexing_profile_id: UUID
    retrieval_profile_id: UUID
    generation_profile_id: UUID | None
    answer_policy_version_id: UUID
    evaluation_state: EvaluationState
    is_system: bool
    is_default: bool
```

- [ ] **Step 3: Add `rag_answer_policy_versions`, `rag_configurations`, and `rag_configuration_versions`. Store validated extractive-policy fields in the policy version, reference that immutable UUID from each configuration version, enforce unique owner/name/version, immutable profile foreign keys, one passed default partial index, and a system-baseline flag.**

- [ ] **Step 4: Seed one versioned extractive Answer Policy and only `BM25 기준선` as a system Saved RAG Configuration. It references the E5 Version 2 Indexing Profile for common parsing/chunking, the BM25-only Retrieval Profile, and that policy version. Do not seed E5 or BGE hybrid saved configurations.**

- [ ] **Step 5: Implement `GET/POST /api/v1/rag/configurations`, `GET /configurations/{id}`, and `POST /configurations/{id}/default`. A POST with an existing owner/name creates version N+1.**

- [ ] **Step 6: When a configuration is saved, enqueue ensure-indexed jobs for active Asset Versions in its selected workspaces. After new asset verification, the worker composition root enqueues distinct subscribed indexing profiles.**

- [ ] **Step 7: Implement the persistent `SearchConfigurationResolverPort` adapter and add API/integration tests proving only system baseline plus the caller's saved configurations appear, saving does not change default, another owner cannot inspect configuration existence, and search resolves exact immutable component versions.**

- [ ] **Step 8: Run migration checks, configuration and worker tests, contract generation, Ruff, mypy, and commit `git commit -m "feat:add-saved-rag-configurations"`.**

### Task 11: Comparable evaluation runs and default-promotion gate

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/evaluation/__init__.py`
- Create: `backend/src/ai_workshop/labs/rag/evaluation/domain.py`
- Create: `backend/src/ai_workshop/labs/rag/evaluation/metrics.py`
- Create: `backend/src/ai_workshop/labs/rag/evaluation/models.py`
- Create: `backend/src/ai_workshop/labs/rag/evaluation/repository.py`
- Create: `backend/src/ai_workshop/labs/rag/evaluation/service.py`
- Create: `backend/src/ai_workshop/labs/rag/evaluation/tasks.py`
- Create: `backend/src/ai_workshop/labs/rag/evaluation/schemas.py`
- Create: `backend/src/ai_workshop/labs/rag/evaluation/api.py`
- Create: `backend/alembic/versions/0008_rag_evaluation.py`
- Create: `backend/tests/unit/labs/rag/evaluation/test_metrics.py`
- Create: `backend/tests/unit/labs/rag/evaluation/test_promotion_policy.py`
- Create: `backend/tests/integration/labs/rag/evaluation/test_evaluation_task.py`
- Create: `backend/tests/integration/labs/rag/embeddings/test_bge_m3_smoke.py`
- Create: `sample-data/public/rag/evaluation/search-v1.json`
- Create: `model-profiles/rag/indexing/bge-m3-structure-aware-v1.yaml`
- Create: `model-profiles/rag/retrieval/hybrid-bge-m3-rrf-v1.yaml`
- Modify: `backend/src/ai_workshop/worker.py`
- Modify: `backend/src/ai_workshop/main.py`
- Modify: `backend/src/ai_workshop/labs/rag/embeddings/sentence_transformers.py`
- Modify: `backend/src/ai_workshop/labs/rag/indexing/service.py`

**Interfaces:**
- Consumes: frozen dataset snapshot, caller permission scenario, Saved RAG Configuration Versions, search service.
- Produces: `EvaluationDataset`, `EvaluationPolicy`, `EvaluationRun`, metrics, compare API, and promotion decision.

- [ ] **Step 1: Create a synthetic public evaluation fixture with at least 12 cases: exact code, Korean paraphrase, numeric clause, table cell, insufficient evidence, conflicting sources, company access, personal isolation, temporary expiry, inactive version, semantic highlight, and keyword highlight. Each case names expected Evidence Unit IDs.**

- [ ] **Step 2: Write failing metric tests with hand-calculated Recall@K, reciprocal rank, nDCG, SUPPORTED precision, false-grounding rate, highlight intersection-over-union, P50, and P95.**

- [ ] **Step 3: Implement pure metric functions and exact stable rounding only at serialization boundaries. Keep raw per-case observations.**

- [ ] **Step 4: Add tables for dataset snapshots, policies, runs, run configurations, and case results. Store document snapshot hash, query set hash, caller scenario, environment, durations, failures, and exact configuration version IDs.**

- [ ] **Step 5: Implement `POST /api/v1/rag/evaluation-runs`, `GET /evaluation-runs/{id}`, and `POST /evaluation-policies`. Policy creation requires all metric thresholds plus `max_access_leaks=0` and `required_reproducibility=1.0`.**

- [ ] **Step 6: Implement Celery evaluation with only `run_id` in Redis. Run every configuration on the same dataset snapshot and permission scenario; persist failures instead of removing a failed candidate.**

- [ ] **Step 7: Write promotion tests proving no policy means no pass, one access leak blocks pass, missing metric blocks pass, and only a PASSED configuration may become the sole operational default.**

- [ ] **Step 8: Use the cataloged BGE-M3 revision `5617a9f61b028005a4858fdac845db406aefb181` with dimension 1024 and maximum input 8192, then add `bge-m3-structure-aware-v1` and `hybrid-bge-m3-rrf-v1` as draft technical profiles. Configure the shared sentence-transformers adapter for BGE dense output only, explicitly disabling sparse and ColBERT outputs. Do not create a user-visible Saved RAG Configuration.**

- [ ] **Step 9: Add an opt-in BGE smoke test guarded by `AI_WORKSHOP_MODEL_SMOKE=1` that emits 1024 normalized values. Add an integration test that creates E5 and BGE Saved RAG Configurations through the same service a user calls, builds separate 768- and 1024-dimension indices over one frozen snapshot, and compares BM25, E5 hybrid, and BGE hybrid in one Evaluation Run. The test must prove these two test-created configurations are not global seeds.**

- [ ] **Step 10: Run evaluation tests, migration checks, worker tests, contract generation, Ruff, mypy, and commit `git commit -m "feat:add-rag-configuration-evaluation"`.**

### Task 12: Evidence-first search and source viewer UI

**Files:**
- Create: `frontend/src/labs/rag/search/api.ts`
- Create: `frontend/src/labs/rag/search/SearchPage.tsx`
- Create: `frontend/src/labs/rag/search/SearchPage.test.tsx`
- Create: `frontend/src/labs/rag/search/EvidenceAnswer.tsx`
- Create: `frontend/src/labs/rag/search/EvidenceAnswer.test.tsx`
- Create: `frontend/src/labs/rag/search/SourceViewer.tsx`
- Create: `frontend/src/labs/rag/search/SourceViewer.test.tsx`
- Create: `frontend/src/labs/rag/search/RelatedSources.tsx`
- Modify: `frontend/src/app/router.tsx`
- Modify: `frontend/src/app/styles.css`

**Interfaces:**
- Consumes: generated OpenAPI search, viewer, workspace, and configuration contracts.
- Produces: `/rag/search` and `/rag/sources/:assetVersionId` routes with evidence-first rendering.

- [ ] **Step 1: Write a failing SearchPage test that selects company and personal scopes explicitly, selects a saved configuration, submits a query, and renders the top evidence before related sources.**

```tsx
expect(await screen.findByRole("heading", { name: "확인된 근거" })).toBeVisible();
expect(screen.getByText("관련 문서")).toBeVisible();
expect(
  screen.getByRole("heading", { name: "확인된 근거" }).compareDocumentPosition(
    screen.getByText("관련 문서"),
  ),
).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
```

- [ ] **Step 2: Write failing answer tests for SUPPORTED, INSUFFICIENT_EVIDENCE, keyword badge, semantic badge, provenance warning, and conflicting-source separation.**

- [ ] **Step 3: Implement typed API functions and route loader/action behavior using the shared client and `credentials: include`. Do not send all accessible workspace IDs unless the user selected them.**

- [ ] **Step 4: Implement SearchPage, EvidenceAnswer, and RelatedSources with document name, immutable version, workspace badge, page/section location, configuration version, and exact source excerpt.**

- [ ] **Step 5: Implement SourceViewer for normalized TXT/Markdown spans and PDF page images with coordinate overlays. Use semantic and keyword styles that remain distinguishable without color alone.**

- [ ] **Step 6: Ensure a related document never appears as a top answer when status is INSUFFICIENT_EVIDENCE. Preserve the related list below the explicit no-answer state.**

- [ ] **Step 7: Run targeted Vitest tests, typecheck, lint, build, and accessibility role assertions.**

- [ ] **Step 8: Commit `git commit -m "feat:add-evidence-first-rag-search-ui"`.**

### Task 13: RAG configuration studio and comparison UI

**Files:**
- Create: `frontend/src/labs/rag/configurations/api.ts`
- Create: `frontend/src/labs/rag/configurations/ConfigurationStudioPage.tsx`
- Create: `frontend/src/labs/rag/configurations/ConfigurationStudioPage.test.tsx`
- Create: `frontend/src/labs/rag/configurations/ConfigurationBuilder.tsx`
- Create: `frontend/src/labs/rag/configurations/SavedConfigurationList.tsx`
- Create: `frontend/src/labs/rag/configurations/ComparisonPanel.tsx`
- Create: `frontend/src/labs/rag/configurations/ComparisonPanel.test.tsx`
- Modify: `frontend/src/labs/rag/models/ModelLabPage.tsx`
- Modify: `frontend/src/labs/rag/models/ModelLabPage.test.tsx`
- Modify: `frontend/src/app/router.tsx`

**Interfaces:**
- Consumes: model definitions, atomic profiles, Saved RAG Configuration, evaluation run APIs.
- Produces: `/rag/configurations` with RAG 구성, 비교 실험, 모델 레지스트리 tabs.

- [ ] **Step 1: Write a failing saved-list test proving the first load contains BM25 기준선 and no automatic E5 or BGE saved configuration.**

- [ ] **Step 2: Write a failing builder test that changes embedding from E5 to BGE, displays a new-index warning, saves a named configuration, and adds only that saved configuration to the list.**

- [ ] **Step 3: Implement the builder with Parser, Chunker, Embedding, BM25, Dense, RRF, Answer Policy, and disabled V1 LLM controls. Derive Dense from the selected Indexing Profile rather than allowing an incompatible second embedding choice.**

- [ ] **Step 4: Write a failing comparison test: BM25 is always included, only saved configurations can be checked, unmeasured cells say 평가 전, and promotion is disabled before PASSED.**

- [ ] **Step 5: Implement ComparisonPanel, start-run polling with manual refresh first, per-metric results, failed-case links, and the promotion gate. Do not invent metric values while a run is pending.**

- [ ] **Step 6: Refactor ModelLabPage into the model-registry tab without changing existing model registration behavior. Remove BM25 and RRF from model rows because they are retrieval methods.**

- [ ] **Step 7: Run all RAG frontend tests, typecheck, lint, build, and API contract check.**

- [ ] **Step 8: Commit `git commit -m "feat:add-rag-configuration-studio"`.**

### Task 14: Full-stack verification, runbook, and workboard handoff

**Files:**
- Create: `backend/tests/e2e/test_rag_search_flow.py`
- Modify: `scripts/smoke.ps1`
- Modify: `docs/runbooks/local-development.md`
- Modify: `AGENTS.md`
- Modify: `WORKBOARD.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: complete first vertical slice.
- Produces: reproducible local startup, smoke verification, and next-work handoff.

- [ ] **Step 1: Add an E2E flow: owner login, company/personal workspaces, synthetic Markdown/TXT/PDF uploads, object verification, RAG ingestion, READY wait, save E5 hybrid configuration, permission-filtered search, source-viewer fetch, comparison run, and promotion rejection before policy pass.**

- [ ] **Step 2: Add a second-user E2E scenario proving no private document ID, title, excerpt, related source, highlight, or evaluation case leaks across users.**

- [ ] **Step 3: Extend Compose smoke to start Elasticsearch, wait for cluster health, run migrations, verify worker health, load only public fixtures, execute RAG E2E, and leave development volumes untouched.**

- [ ] **Step 4: Update the runbook with Elasticsearch memory requirements, model-cache initialization, optional E5 download, indexing status, evaluation commands, and recovery from FAILED projections without deleting volumes.**

- [ ] **Step 5: Update AGENTS.md with the implemented RAG stage while preserving the 200-line limit. Link detailed procedures instead of duplicating them.**

- [ ] **Step 6: Update WORKBOARD.md: move this slice into recent completion, keep at most five items, and set the next plan to DOCX support before scanned-PDF OCR.**

- [ ] **Step 7: Run the complete verification suite.**

```powershell
cd backend
uv lock --check
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run alembic check

cd ../frontend
pnpm test --run
pnpm typecheck
pnpm lint
pnpm build
pnpm api:check

cd ..
docker compose -f infrastructure/compose/compose.yaml config --quiet
./scripts/smoke.ps1
git diff --check
```

- [ ] **Step 8: Confirm all commands exit 0, AGENTS.md is at most 200 lines, WORKBOARD recent completion is at most five items, and no model weights, source documents, embeddings, generated indices, .idea, or local caches are staged.**

- [ ] **Step 9: Commit only Task 14 files with `git commit -m "docs:complete-first-rag-search-slice"`.**

---

## Completion Checklist

- [ ] Markdown, TXT, and text-native PDF reach READY through the real worker.
- [ ] Every search hit resolves to immutable document version and source location.
- [ ] BM25 and dense retrieval use identical pre-search permission filters.
- [ ] Python RRF combines the two ranked lists and BM25-only remains an explicit baseline.
- [ ] One frozen evaluation snapshot compares BM25, E5 hybrid, and BGE-M3 dense hybrid using model-specific 768- and 1024-dimension indices.
- [ ] The top answer is an extractive source and unsupported questions return INSUFFICIENT_EVIDENCE.
- [ ] Keyword and semantic highlights are visibly and structurally distinct.
- [ ] Company, personal, and temporary scopes remain separated unless explicitly selected.
- [ ] Only BM25 baseline and user-saved RAG configurations appear in the saved list.
- [ ] Saved configurations are immutable, comparable, and cannot become default without a passed Evaluation Policy.
- [ ] Evaluation stores exact dataset, permission scenario, configuration version, metrics, failures, and latency.
- [ ] Access leakage is zero in unit, integration, and E2E tests.
- [ ] OpenAPI, generated TypeScript, tests, static checks, builds, Compose config, and smoke all pass.

## Follow-up Plan Boundaries

1. DOCX parser and viewer support using the same ParsedDocument, RetrievalChunk, EvidenceUnit, and SourceLocation contracts.
2. Scanned-PDF OCR with engine/version recording, confidence warnings, coordinate reconciliation, and evaluation.
3. Reranker comparison after the BM25+E5/BGE baselines are measured.
4. LLM generation only after evidence precision and citation behavior meet an approved Evaluation Policy.

## Verified Dependency References

- Elastic server and client compatibility: https://www.elastic.co/docs/reference/elasticsearch/clients/python
- Elasticsearch 9.5.2 container: https://www.docker.elastic.co/r/elasticsearch/elasticsearch
- elasticsearch-py 9.5.0: https://pypi.org/project/elasticsearch/
- PyMuPDF 1.28.2: https://pypi.org/project/pymupdf/
- sentence-transformers 6.0.0: https://pypi.org/project/sentence-transformers/
- multilingual-e5-base pinned revision: https://huggingface.co/intfloat/multilingual-e5-base/commit/d128750597153bb5987e10b1c3493a34e5a4502a
- BGE-M3 pinned revision: https://huggingface.co/BAAI/bge-m3/commit/5617a9f61b028005a4858fdac845db406aefb181
