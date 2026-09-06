# RAG Document Processing and OCR Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an immutable document-processing profile, DOCX structure parsing with embedded-image PP-StructureV3 OCR, provenance-aware viewing, and an owner-only full configuration UI.

**Architecture:** Saved RAG configurations select a versioned `document_processing` profile independently from indexing, retrieval, and generation. DOCX parsing remains deterministic; only embedded images cross the OCR port, whose Paddle adapter uses locally pinned artifacts and never silently falls back. Parsing artifacts, ingestion identity, index builds, source locations, and admin summaries carry the exact processing profile and safe execution metadata.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Alembic, Celery, python-docx/lxml, PaddleOCR 3.7.0, PaddlePaddle 3.2.2, pytest, Next.js React, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-06-rag-document-processing-ocr-profile-design.md`

## Global Constraints

- Work only on `main`; do not create a feature worktree.
- Keep Platform independent from Labs/RAG and keep model runtimes behind ports.
- Private document bytes and OCR text remain local or in an approved on-premises environment.
- Runtime model downloads and Hosted OCR APIs are forbidden.
- The exact configured OCR pipeline must fail explicitly; Tesseract is an evaluation baseline, not fallback.
- Existing TXT, Markdown, and text-PDF configurations retain their behavior through a seeded legacy processing profile.
- Unit tests run without real models or network; real Paddle execution is a separately marked smoke gate.
- User-facing option labels do not expose UUIDs, object paths, endpoints, or secret references.
- PP-StructureV3 3.7.0 is provisioned with its complete enabled dependency graph: layout,
  general OCR, table OCR text-line orientation, table classification, wired/wireless structure
  and cell detection, and table orientation. Disabled formula, seal, chart and region models are
  absent; top-level text-line orientation remains disabled while the nested table OCR dependency
  is locally pinned.

### Task 11: Correct and provision the complete PP-StructureV3 runtime

**Files:**
- Create: `backend/alembic/versions/0019_seed_pp_structure_v3_profile.py`
- Create: `backend/alembic/versions/0020_correct_pp_structure_v3_profile.py`
- Modify: `backend/src/ai_workshop/labs/rag/models/domain.py`
- Modify: `backend/src/ai_workshop/labs/rag/models/document_processing.py`
- Modify: `backend/src/ai_workshop/labs/rag/ocr/contracts.py`
- Modify: `backend/src/ai_workshop/labs/rag/ocr/paddle_structure.py`
- Create: `model-profiles/rag/ocr/pp-structure-v3-v1.json`
- Create: `scripts/provision_rag_ocr_models.py`
- Create/Modify: focused model, migration, provisioner and real-runtime smoke tests

- [ ] Add RED tests for all ten unique model roles and exact PPStructureV3 3.7.0 arguments.
- [ ] Add RED tests for immutable manifest verification and fail-closed artifact provisioning.
- [ ] Add RED migration test for draft, non-default seeded model/profile identities.
- [ ] Seed the complete ten-model draft profile in forward-only migration 0019 without editing
  0017/0018. Because the applied v1 module flags described the nested table orientation model as
  globally disabled, retain that immutable history as failed and publish corrected draft v2 in 0020.
- [ ] Download only exact-revision official artifacts during the approved provisioning step.
- [ ] Verify every required file SHA-256 before installing the immutable cache directories.
- [ ] Run a network-disabled Windows CPU smoke for Korean text, bbox and a synthetic table.
- [ ] Update admin metadata tests, design/ADR, runbook and verification worklog.

---

### Task 1: Pin dependencies and prove the OCR runtime boundary

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Create: `backend/src/ai_workshop/labs/rag/ocr/contracts.py`
- Create: `backend/src/ai_workshop/labs/rag/ocr/paddle_structure.py`
- Create: `backend/tests/unit/labs/rag/ocr/test_paddle_structure.py`
- Create: `backend/tests/integration/labs/rag/ocr/test_paddle_structure_smoke.py`

**Interfaces:**
- Produces: `OcrProfileSpec`, `OcrRequest`, `OcrTextUnit`, `OcrTableCell`, `OcrResult`, `OcrRuntimePort`.
- Produces: `PaddleStructureV3Adapter.recognize(request: OcrRequest, profile: OcrProfileSpec) -> OcrResult`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_ocr_profile_requires_local_artifacts() -> None:
    with pytest.raises(OcrConfigurationError):
        OcrProfileSpec.create(
            pipeline="PP-StructureV3",
            detection_model="PP-OCRv5_server_det",
            recognition_model="korean_PP-OCRv5_mobile_rec",
            table_model="SLANet_plus",
            languages=("ko", "en"),
            artifact_directories={},
        )
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\labs\rag\ocr\test_paddle_structure.py -q`

- [ ] **Step 3: Add `python-docx>=1.2,<2` to base dependencies and `paddleocr==3.7.0`, `paddlepaddle==3.2.2` to the `ocr` optional dependency**

```toml
[project.optional-dependencies]
ocr = [
  "paddleocr==3.7.0",
  "paddlepaddle==3.2.2",
]
```

Run: `uv lock --project backend`

- [ ] **Step 4: Implement typed OCR contracts and a lazy-import Paddle adapter**

```python
class OcrRuntimePort(Protocol):
    def recognize(self, request: OcrRequest, profile: OcrProfileSpec) -> OcrResult: ...

class PaddleStructureV3Adapter:
    def recognize(self, request: OcrRequest, profile: OcrProfileSpec) -> OcrResult:
        runtime = self._runtime_factory(profile)
        raw_results = runtime.predict(input=request.image_path)
        return normalize_paddle_results(raw_results, request=request, profile=profile)
```

The factory passes exact local `*_model_dir` values, disables formula/seal/chart modules, and raises `ocr_model_artifact_missing` before importing or invoking the runtime when any required artifact is absent.

- [ ] **Step 5: Run unit tests, Ruff, and mypy**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\labs\rag\ocr -q`

Run: `backend\.venv\Scripts\ruff.exe check backend\src\ai_workshop\labs\rag\ocr backend\tests\unit\labs\rag\ocr`

Run: `backend\.venv\Scripts\mypy.exe backend\src\ai_workshop\labs\rag\ocr`

- [ ] **Step 6: Install the optional OCR environment and run the no-content/import gate before downloading model artifacts**

Run: `uv sync --project backend --extra ocr --frozen`

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\labs\rag\ocr\test_paddle_structure_smoke.py -q -m integration`

Expected: package import/version gate passes; model execution skips with an explicit missing-artifact reason until approved artifacts are present.

- [ ] **Step 7: Commit the runtime boundary**

```text
git add backend/pyproject.toml backend/uv.lock backend/src/ai_workshop/labs/rag/ocr backend/tests/unit/labs/rag/ocr backend/tests/integration/labs/rag/ocr
git commit -m "feat: add pinned local OCR runtime boundary"
```

### Task 2: Add document-processing and OCR model/profile contracts

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/models/domain.py`
- Modify: `backend/src/ai_workshop/labs/rag/models/schemas.py`
- Modify: `backend/src/ai_workshop/labs/rag/models/service.py`
- Modify: `backend/src/ai_workshop/labs/rag/models/catalog.py`
- Modify: `backend/tests/unit/labs/rag/models/test_profiles.py`
- Modify: `backend/tests/unit/labs/rag/models/test_profile_yaml.py`
- Modify: `backend/tests/unit/labs/rag/models/test_model_catalog.py`

**Interfaces:**
- Produces: `ProfileKind.DOCUMENT_PROCESSING`.
- Produces: `ModelKind.OCR_TEXT_DETECTION`, `OCR_TEXT_RECOGNITION`, `OCR_TABLE_STRUCTURE`.
- Produces: `resolve_document_processing_spec(profile, models) -> DocumentProcessingSpec`.

- [ ] **Step 1: Add failing domain tests for exact OCR bindings and typed config**

```python
def test_document_processing_profile_requires_exact_ocr_roles() -> None:
    profile = make_document_processing_profile(bindings=())
    with pytest.raises(ProfileValidationError):
        validate_document_processing_profile(profile.config, profile.bindings)
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\labs\rag\models -q`

- [ ] **Step 3: Implement enums and validation**

```python
class ProfileKind(StrEnum):
    DOCUMENT_PROCESSING = "document_processing"
    INDEXING = "indexing"
    RETRIEVAL = "retrieval"
    GENERATION = "generation"
```

Validation requires parser routes and, when OCR is enabled, exactly one binding for each of the ten
enabled PP-StructureV3 runtime roles, supported language order, thresholds in `[0, 1]`, a versioned
output schema, and local/on-premises data policy.

- [ ] **Step 4: Implement resolver and safe response metadata**

The resolver converts frozen JSON plus model bindings into `DocumentProcessingSpec`; response schemas return display names, versions, evaluation state, and owner-only artifact metadata without filesystem paths or endpoints.

- [ ] **Step 5: Run model tests and static checks**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\labs\rag\models -q`

- [ ] **Step 6: Commit profile contracts**

```text
git add backend/src/ai_workshop/labs/rag/models backend/tests/unit/labs/rag/models
git commit -m "feat: add document processing profile contracts"
```

### Task 3: Persist the new profile identity with a forward migration

**Files:**
- Create: `backend/alembic/versions/0017_rag_document_processing_ocr.py`
- Modify: `backend/src/ai_workshop/labs/rag/configurations/models.py`
- Modify: `backend/src/ai_workshop/labs/rag/configurations/domain.py`
- Modify: `backend/src/ai_workshop/labs/rag/ingestion/models.py`
- Modify: `backend/src/ai_workshop/labs/rag/documents/models.py`
- Modify: `backend/tests/integration/test_migration_0017_rag_document_processing_ocr.py`
- Modify: `backend/tests/unit/labs/rag/configurations/test_configuration.py`

**Interfaces:**
- Produces: `LEGACY_DOCUMENT_PROCESSING_PROFILE_ID` and a non-null `document_processing_profile_id` on configuration versions, projections, and ingestion jobs.
- Changes ingestion identity to `(asset_version_id, document_processing_profile_id, indexing_profile_id)`.

- [ ] **Step 1: Write migration RED tests**

```python
assert migrated_configuration.document_processing_profile_id == LEGACY_DOCUMENT_PROCESSING_PROFILE_ID
assert migrated_projection.document_processing_profile_id == LEGACY_DOCUMENT_PROCESSING_PROFILE_ID
```

- [ ] **Step 2: Run the migration test and confirm RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\test_migration_0017_rag_document_processing_ocr.py -q -m integration`

- [ ] **Step 3: Implement forward-only migration and system profile seed**

The migration creates three OCR model definitions plus one draft PP-StructureV3 document-processing profile, creates the OCR-disabled passed legacy profile, backfills existing rows to the legacy profile, then adds non-null foreign keys and expanded unique constraints. The OCR profile cannot become a default until its environment-specific evaluation passes. The migration does not modify migrations `0001` through `0016`.

- [ ] **Step 4: Update ORM/domain types and constructors**

```python
@dataclass(frozen=True, slots=True)
class SavedRagConfiguration:
    document_processing_profile_id: UUID
    indexing_profile_id: UUID
    retrieval_profile_id: UUID
```

- [ ] **Step 5: Run configuration and migration tests**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\labs\rag\configurations backend\tests\integration\test_migration_0017_rag_document_processing_ocr.py -q`

- [ ] **Step 6: Commit migration and persistence types**

```text
git add backend/alembic/versions/0017_rag_document_processing_ocr.py backend/src/ai_workshop/labs/rag/configurations backend/src/ai_workshop/labs/rag/ingestion/models.py backend/src/ai_workshop/labs/rag/documents/models.py backend/tests
git commit -m "feat: persist document processing profile identity"
```

### Task 4: Carry profile identity through configuration APIs and ingestion

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/configurations/schemas.py`
- Modify: `backend/src/ai_workshop/labs/rag/configurations/service.py`
- Modify: `backend/src/ai_workshop/labs/rag/configurations/repository.py`
- Modify: `backend/src/ai_workshop/labs/rag/ingestion/domain.py`
- Modify: `backend/src/ai_workshop/labs/rag/ingestion/repository.py`
- Modify: `backend/src/ai_workshop/labs/rag/ingestion/service.py`
- Modify: `backend/src/ai_workshop/labs/rag/ingestion/handoff.py`
- Modify: `backend/src/ai_workshop/labs/rag/ingestion/stages.py`
- Modify: `backend/tests/integration/labs/rag/configurations/test_configuration_api.py`
- Modify: `backend/tests/unit/labs/rag/ingestion/test_ingestion_service.py`

**Interfaces:**
- Consumes: document-processing profile domain and persisted IDs from Tasks 2–3.
- Produces: `SavedRagConfigurationCreate.document_processing_profile_id` and a resolved `DocumentProcessingSpec` on `IngestionExecution`.

- [ ] **Step 1: Write failing API and ingestion identity tests**

```python
assert response.json()["document_processing_profile_id"] == str(profile_id)
assert execution.document_processing_profile_id == profile_id
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\labs\rag\configurations\test_configuration_api.py backend\tests\unit\labs\rag\ingestion\test_ingestion_service.py -q`

- [ ] **Step 3: Update service/repository reads, writes, locks, and idempotency keys**

All configuration validation verifies the selected kind. All ingestion creation, handoff failure identity, redelivery, supersession, and readiness paths carry the exact document-processing profile without querying a latest profile.

- [ ] **Step 4: Run handoff, recovery, and configuration regressions**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\labs\rag\ingestion backend\tests\integration\labs\rag\ingestion backend\tests\integration\labs\rag\configurations -q`

- [ ] **Step 5: Commit application wiring**

```text
git add backend/src/ai_workshop/labs/rag/configurations backend/src/ai_workshop/labs/rag/ingestion backend/tests
git commit -m "feat: resolve document processing in RAG ingestion"
```

### Task 5: Extend provenance and artifact serialization for embedded images

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/documents/domain.py`
- Modify: `backend/src/ai_workshop/labs/rag/ingestion/serialization.py`
- Modify: `backend/src/ai_workshop/labs/rag/search/schemas.py`
- Modify: `backend/src/ai_workshop/labs/rag/indexing/contracts.py`
- Modify: `backend/src/ai_workshop/labs/rag/indexing/elasticsearch.py`
- Modify: `backend/tests/unit/labs/rag/documents/test_document_domain.py`
- Modify: `backend/tests/unit/labs/rag/ingestion/test_ingestion_service.py`
- Modify: `backend/tests/unit/labs/rag/indexing/test_elasticsearch_adapter.py`

**Interfaces:**
- Produces: additive `SourceLocation.source_kind`, `source_part`, `image_sha256`, `bbox` and `table_cell` metadata.
- Produces: serialization schema version that round-trips old text/PDF locations and new DOCX-image locations.

- [ ] **Step 1: Write failing round-trip and validation tests**

```python
location = SourceLocation.docx_image(
    element_id=element_id,
    source_part="word/media/image1.png",
    image_sha256="a" * 64,
    bbox=(0.1, 0.2, 0.7, 0.4),
)
assert deserialize_parsed_document(serialize_parsed_document(document)).elements[0].location == location
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\labs\rag\documents backend\tests\unit\labs\rag\ingestion -q`

- [ ] **Step 3: Implement additive provenance fields and backward-compatible deserialization**

Old artifacts without `source_kind`, `source_part`, `image_sha256`, or `table_cell` deserialize to the existing text/PDF semantics. Image bbox values are normalized to `[0, 1]` and rejected when unordered or out of bounds.

- [ ] **Step 4: Map new fields into Elasticsearch and search responses**

Search documents retain exact source kind and image identity so evidence selection cannot manufacture a viewer target.

- [ ] **Step 5: Run serialization, indexing, highlighting, and search schema tests**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\labs\rag\ingestion backend\tests\unit\labs\rag\indexing backend\tests\unit\labs\rag\highlighting -q`

- [ ] **Step 6: Commit provenance support**

```text
git add backend/src/ai_workshop/labs/rag/documents backend/src/ai_workshop/labs/rag/ingestion/serialization.py backend/src/ai_workshop/labs/rag/search/schemas.py backend/src/ai_workshop/labs/rag/indexing backend/tests
git commit -m "feat: add OCR image provenance"
```

### Task 6: Implement DOCX structure parsing and embedded-image OCR

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/parsing/docx.py`
- Modify: `backend/src/ai_workshop/labs/rag/parsing/contracts.py`
- Modify: `backend/src/ai_workshop/labs/rag/parsing/registry.py`
- Modify: `backend/src/ai_workshop/labs/rag/parsing/service.py`
- Modify: `backend/src/ai_workshop/labs/rag/ingestion/tasks.py`
- Create: `backend/tests/fixtures/rag/sample_docx.py`
- Create: `backend/tests/unit/labs/rag/parsing/test_docx_parser.py`
- Modify: `backend/tests/unit/labs/rag/parsing/test_registry.py`
- Modify: `backend/tests/unit/labs/rag/parsing/test_service.py`

**Interfaces:**
- Consumes: `OcrRuntimePort`, `DocumentProcessingSpec`, and image provenance from earlier tasks.
- Produces: `DocxStructureParser.parse(request: ParseRequest) -> ParsedDocument`.

- [ ] **Step 1: Create a synthetic DOCX fixture and failing order/OCR tests**

```python
def test_docx_preserves_paragraph_table_image_order(fake_ocr: FakeOcrRuntime) -> None:
    parsed = parser(fake_ocr).parse(make_docx_request())
    assert [item.kind for item in parsed.elements] == [
        "heading", "paragraph", "table_cell", "ocr_text", "paragraph"
    ]
    assert parsed.elements[3].text == "운용 한도 7%"
```

- [ ] **Step 2: Run DOCX parser tests and confirm RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\labs\rag\parsing\test_docx_parser.py -q`

- [ ] **Step 3: Implement safe DOCX package parsing**

Use `python-docx`/lxml for body-order paragraphs and tables, relationship-resolved embedded images, heading/list semantics, and bounded decompressed size/count checks. Reject encrypted, malformed, external-link, unsupported-image, and zip-bomb-like packages with distinct safe error codes.

- [ ] **Step 4: Invoke OCR only for deterministic eligible images**

Hash original image bytes, skip only configured tiny/icon cases with a recorded reason, deduplicate `(image_sha256, ocr_profile_version)` within the Asset Version, and map accepted OCR lines/table cells into structural elements. Low-confidence units retain provenance and warnings but are not evidence eligible.

- [ ] **Step 5: Register DOCX MIME/suffix and wire resolved profile/runtime into parsing**

`application/vnd.openxmlformats-officedocument.wordprocessingml.document` and `.docx` resolve only to `DocxStructureParser`; conflicting MIME/suffix still fails closed.

- [ ] **Step 6: Run all parsing and chunking tests**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\labs\rag\parsing backend\tests\unit\labs\rag\chunking -q`

- [ ] **Step 7: Commit DOCX/OCR parsing**

```text
git add backend/src/ai_workshop/labs/rag/parsing backend/src/ai_workshop/labs/rag/ingestion/tasks.py backend/tests/fixtures/rag/sample_docx.py backend/tests/unit/labs/rag/parsing
git commit -m "feat: parse DOCX structure and OCR embedded images"
```

### Task 7: Add authorized DOCX image viewing and OCR highlights

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/search/viewer.py`
- Modify: `backend/src/ai_workshop/labs/rag/search/api.py`
- Modify: `backend/src/ai_workshop/labs/rag/search/schemas.py`
- Modify: `backend/tests/unit/labs/rag/search/test_source_repository.py`
- Modify: `backend/tests/integration/labs/rag/search/test_search_api.py`
- Modify: `frontend/src/features/rag/search/SourceViewer.tsx`
- Modify: `frontend/src/features/rag/search/SourceViewer.test.tsx`

**Interfaces:**
- Produces: authorized image-part endpoint scoped by actor, Asset Version, Projection, element, and image SHA-256.
- Produces: source viewer modes `normalized_text`, `pdf_page`, and `docx_image`.

- [ ] **Step 1: Write failing privacy and viewer tests**

```python
response = await client.get(docx_image_url, headers=other_user_headers)
assert response.status_code == 404
```

- [ ] **Step 2: Run viewer tests and confirm RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\labs\rag\search\test_search_api.py -q`

- [ ] **Step 3: Implement authorized DOCX image extraction**

Re-authorize the immutable source tuple, verify original Asset size/SHA-256, resolve only the image part recorded in the parsed artifact, verify its SHA-256, and return bytes with the validated media type. Never accept an object key or zip member name directly from the URL.

- [ ] **Step 4: Render image bbox overlays in the frontend**

Use the response-provided normalized bbox, label OCR highlights as semantic/OCR evidence, and retain the existing exact-vs-semantic distinction. Provide text fallback and keyboard-accessible evidence navigation.

- [ ] **Step 5: Run backend and frontend viewer tests**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\labs\rag\search backend\tests\unit\labs\rag\search -q`

Run: `pnpm --dir frontend vitest run src/features/rag/search/SourceViewer.test.tsx`

- [ ] **Step 6: Commit the viewer**

```text
git add backend/src/ai_workshop/labs/rag/search backend/tests frontend/src/features/rag/search
git commit -m "feat: view DOCX OCR evidence at source"
```

### Task 8: Add the owner document-processing configuration UI

**Files:**
- Modify: `frontend/src/features/rag/configurations/api.ts`
- Modify: `frontend/src/features/rag/configurations/packageSummary.ts`
- Modify: `frontend/src/features/rag/configurations/ConfigurationBuilder.tsx`
- Create: `frontend/src/features/rag/configurations/DocumentProcessingDetails.tsx`
- Modify: `frontend/src/features/rag/configurations/ConfigurationStudioPage.test.tsx`
- Modify: `frontend/src/features/rag/configurations/packageSummary.test.ts`
- Modify: `frontend/src/features/rag/models/ModelLabPage.tsx`
- Modify: `frontend/src/features/rag/models/ModelLabPage.test.tsx`
- Modify: `frontend/src/shared/api/schema.d.ts`

**Interfaces:**
- Consumes: typed document-processing profile and safe model metadata APIs.
- Produces: first fieldset `문서 처리 구성` and expandable `전체 OCR 구성 보기`.

- [ ] **Step 1: Write failing accessible UI tests**

```tsx
expect(screen.getByRole("group", { name: "문서 처리 구성" })).toBeVisible();
await user.click(screen.getByText("전체 OCR 구성 보기"));
expect(screen.getByText("PP-StructureV3")).toBeVisible();
expect(screen.getByText("korean_PP-OCRv5_mobile_rec")).toBeVisible();
expect(screen.queryByText(documentProcessingProfile.id)).not.toBeInTheDocument();
```

- [ ] **Step 2: Run focused frontend tests and confirm RED**

Run: `pnpm --dir frontend vitest run src/features/rag/configurations/ConfigurationStudioPage.test.tsx src/features/rag/configurations/packageSummary.test.ts`

- [ ] **Step 3: Add selection, summary, compatibility, and reindex warning**

The normal select option is `프로파일 표시명 v버전 · DOCX/OCR · 평가 상태`. The summary shows parser routes and OCR enabled/disabled. Changing the processing profile warns that a new parse/chunk/index build is required.

- [ ] **Step 4: Add owner-only full details**

The details component renders the pipeline, ten model roles, languages, thresholds, execution
location/device/readiness, artifact source/revision/SHA-256/license state, and latest evaluation. It
does not render UUID, local path, endpoint, secret reference, or raw JSON.

- [ ] **Step 5: Regenerate OpenAPI TypeScript schema and run frontend gates**

Run: `backend\.venv\Scripts\python.exe backend\tools\export_openapi.py`

Run: `pnpm --dir frontend api:generate`

Run: `pnpm --dir frontend vitest run src/features/rag/configurations src/features/rag/models`

Run: `pnpm --dir frontend exec tsc --noEmit`

Run: `pnpm --dir frontend lint`

- [ ] **Step 6: Commit admin UI**

```text
git add frontend/src/features/rag/configurations frontend/src/features/rag/models frontend/src/shared/api/schema.d.ts
git commit -m "feat: show full OCR configuration to owners"
```

### Task 9: Add end-to-end readiness, failure, and privacy coverage

**Files:**
- Modify: `backend/tests/e2e/test_rag_search_flow.py`
- Modify: `backend/tests/contract/test_openapi.py`
- Create: `backend/tests/e2e/test_rag_docx_ocr_flow.py`
- Modify: `frontend/src/features/rag/search/SearchPage.test.tsx`
- Modify: `docs/runbooks/local-development.md`
- Create: `docs/worklogs/2026-09-06-rag-docx-ocr-verification.md`
- Modify: `WORKBOARD.md`

**Interfaces:**
- Verifies the full upload → processing → hybrid retrieval → OCR highlight → authorized source loop.

- [ ] **Step 1: Write E2E tests with a deterministic fake OCR runtime**

```python
assert search_response["answer"]["evidence"][0]["location"]["source_kind"] == "docx_image"
assert viewer_response.status_code == 200
assert unauthorized_viewer_response.status_code == 404
```

- [ ] **Step 2: Run E2E tests and confirm failures before final wiring**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\e2e\test_rag_docx_ocr_flow.py -q`

- [ ] **Step 3: Complete readiness and safe error wiring**

Configured artifact/runtime absence reports exact owner remediation, blocks affected document processing, preserves unrelated ready projections, and never returns document text or filesystem paths in errors.

- [ ] **Step 4: Run full automated gates**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\unit -q`

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\contract backend\tests\integration backend\tests\e2e -q`

Run: `backend\.venv\Scripts\ruff.exe check backend\src backend\tests`

Run: `backend\.venv\Scripts\mypy.exe backend\src`

Run: `pnpm --dir frontend test`

Run: `pnpm --dir frontend exec tsc --noEmit`

Run: `pnpm --dir frontend lint`

Run: `pnpm --dir frontend build`

- [ ] **Step 5: Run real local Paddle smoke only with approved model artifacts**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\labs\rag\ocr\test_paddle_structure_smoke.py -q -m integration`

Record exact package versions, model revisions/SHA-256, Windows CPU time/memory, recognized text, bbox validity, and whether the same manifest is ready for Linux execution. Do not claim Linux GPU verification from a Windows run.

- [ ] **Step 6: Update runbook, worklog, and workboard**

Document local non-Docker OCR worker startup, required model-directory environment references, offline behavior, failure remediation, completed gates, remaining Linux smoke, and selected next task. Keep recent completed work at five entries or fewer.

- [ ] **Step 7: Run repository/document checks and commit final integration**

Run: `backend\.venv\Scripts\python.exe scripts\verify_project_agent_contracts.py validate --root .`

Run: `git diff --check`

```text
git add WORKBOARD.md docs/runbooks/local-development.md docs/worklogs/2026-09-06-rag-docx-ocr-verification.md backend/tests frontend/src/features/rag/search
git commit -m "test: verify DOCX OCR RAG flow"
```
