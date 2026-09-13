# RAG Movement Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Follow TDD and independent review gates.

**Goal:** Keep live RAG retrieval and prepared evidence inside the user's current scope after document/folder movement without reindexing.

**Architecture:** Current DB authorization resolves full immutable document/asset/projection/build identities for every live scope. Both Elasticsearch candidate branches filter exact indexed identities rather than stale indexed folder positions. Application-side fresh checks compare prepared source identities before generation; frozen evaluation retains snapshot semantics.

**Tech Stack:** Existing Python/FastAPI, SQLAlchemy/PostgreSQL, Elasticsearch sparse+dense, pytest.

**Spec:** `docs/superpowers/specs/2026-09-13-explorer-movement-design.md` §5–6, already approved. Server move code is implemented and reviewed in the working tree.

## Global Constraints

- main only; preserve previous uncommitted assets/frontend changes and references. No staging/commit/push/worktree by agents.
- No live migration, restart, real document move/upload, external LLM call, model download or dependency installation.
- Existing backend/.venv only; pytest `-p no:cacheprovider`, Python `-B`, Ruff `--no-cache`.
- 권한 및 지식 공간 필터는 BM25와 벡터 검색 전에 적용한다.
- 개별 ID 집합의 임의 교차 조합을 허용된 근거로 인정하지 않는다.
- frozen 평가는 기록된 snapshot/물리 색인 계약을 유지하고 현재 폴더 의미로 소급 변경하지 않는다.
- 이동은 재파싱·재임베딩 사유가 아니다.
- 실사용 이동 UI는 이번 작업에서도 추가하지 않는다. Source handoff and live rollout are separate gates.
- Temporary task records only `.local-data/project-agent-work/rag-movement-integrity/` per project policy.

## Task 1: Exact live search scope and pre-generation integrity

**Files:**
- Modify `backend/src/ai_workshop/labs/rag/retrieval/{domain,scope,elasticsearch,service}.py`.
- Create `backend/src/ai_workshop/labs/rag/retrieval/integrity.py` for exact-identity subset validation (not another runtime/framework).
- Modify `backend/src/ai_workshop/labs/rag/search/{service,repository}.py` only for current-source hydration and prepared-evidence checks.
- Modify affected tests under `backend/tests/unit/labs/rag/{retrieval,search,evaluation}` and narrowly required synthetic scope fixtures elsewhere under backend/tests.
- Create `backend/tests/integration/labs/rag/retrieval/test_movement_integrity.py` using the existing `isolated_rag_resources` helper.
- Do not modify assets implementation, frontend, models, schema migration, settings, WORKBOARD or docs.

**Interfaces and binding decisions:**

```python
# Append to ResolvedSearchScope, preserve existing selected_documents semantics.
authorized_documents: tuple[SelectedDocumentIdentity, ...] = ()

def require_authorized_identities(
    required: tuple[SelectedDocumentIdentity, ...],
    current: ResolvedSearchScope,
) -> None:
    if not set(required).issubset(current.authorized_documents):
        raise AppError("conversation_scope_changed", "The search scope changed. Select sources again.", 409)
```

`authorized_documents` contains every exact READY lifecycle identity resolved from DB for live workspace/folder/document scopes. `selected_documents`, selected count limits and fingerprints retain their explicit-document-only public meaning. Never populate missing live authority by zipping independent asset/build lists or inventing synthetic IDs in production.

Current Elasticsearch mapping has no document_id. Its asset_version_id is immutably joined to one Document in DB. Therefore represent the DB-authorized four-part identity in ES as an OR of exact AND(asset_version_id, projection_id, index_build_id) tuples; document ownership is proved by the DB join and verified again from authoritative EvidenceSource.document_id. Do not add a mapping field/reindex merely for movement.

```python
{"bool": {"minimum_should_match": 1, "should": [
    {"bool": {"filter": [
        {"term": {"asset_version_id": str(identity.asset_version_id)}},
        {"term": {"projection_id": str(identity.projection_id)}},
        {"term": {"index_build_id": str(identity.index_build_id)}},
    ]}} for identity in scope.authorized_documents
]}}
```

Live search retains workspace/ACL/READY prefilters but not indexed folder_id. Empty/missing authority yields match_none or no candidate calls, never broad fallback. Target validation must continue distinguishing ActiveIndexAlias from FrozenIndexTarget; frozen still uses existing physical-index/ACL/folder/snapshot filters, PIT and drift checks.

- [x] Add RED tests in retrieval test_scope.py/test_elasticsearch.py and a focused search test_movement_integrity.py: live folder scopes now retain exact identities; sparse/dense equivalent exact tuple filters; no stale folder clause; empty/missing allowlist fail-closed; cross-paired asset/projection/build fails; frozen filters unchanged. Run `.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider tests/unit/labs/rag/retrieval tests/unit/labs/rag/search/test_movement_integrity.py -q` from backend and record actual failing assertions before implementation.
- [x] Implement DB lifecycle propagation and exact filters. Preserve existing profile, active/READY, ACL and deterministic ranking rules. Query branch validation cannot be bypassed by active_only=False on an active alias.
- [x] Add RED then implement fresh-scope checks around candidate retrieval and prepared-source use. Hybrid's post-embedding resolve currently discards the returned scope; SearchApplicationService.revalidate_access also discards it. Do not allow removed prepared candidates/evidence to silently survive these boundaries. Both branches must share a validated source snapshot. Before LLM generate, validate exact identities from prepared authoritative sources (including returned related sources) against fresh DB authority. A used source leaving a fixed folder, losing permission or changing active version/build aborts with existing scope-changed409/no generation call. A movement-only unrestricted explicit document retains identity/fingerprint and can continue; unrelated changes must not be presented as permission to widen scope. Preserve audit sanitization and previous errors; no metadata/body leakage in new errors.
- [x] Prove current displayed folder comes from fresh DB DocumentRecord metadata, not ES hit.folder_id or stale ORM identity map. Avoid changing frozen source semantics; do not modify historical snapshots.
- [x] Add isolated real PostgreSQL+Elasticsearch test with deterministic synthetic vectors (no model download): create scoped source A/destination B, immutable READY lifecycle and index source folderA; move via existing AssetMovementService; assert BM25 and dense excludeA/includeB without touching/rebuilding ES. Assert raw index still saysA while authoritative source saysB. Folder move preserves descendants' folder IDs and identities. Exercise original viewer/citation by stable IDs and existing source authorization, plus frozen old-snapshot retrieval. Snapshot synthetic bytes/hash/version IDs/object keys and relevant projection/build/chunk rows before/after movement. All data is test-owned; never seed live DB.
- [x] Use `tests.integration.rag_isolation_support.isolated_rag_resources` and `create_isolated_elasticsearch` for exact test DB/ES namespace guards and cleanup. Read helper before running. If real service unavailable, report exact blocker; do not install/start infrastructure or claim real retrieval success. Existing isolated PG-only source repository test is safe through this helper; avoid broad integration suites.
- [x] Run focused GREEN and regression: `.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider tests/unit/labs/rag/retrieval tests/unit/labs/rag/search tests/unit/labs/rag/evaluation -q`; then exact isolated `tests/integration/labs/rag/retrieval/test_movement_integrity.py` and `test_search_scope_repository.py`. Amend only contract-affected synthetic fixtures, not assertions to weaken filtering. Run `mypy --cache-dir=nul` on changed production modules and Ruff `--no-cache` on changed paths.
- [x] Self-review and write `.local-data/project-agent-work/rag-movement-integrity/task-1-report.md` with exact RED/GREEN commands/results, files, real vs mocked tests, known limits and isolation cleanup. No commit. Report concurrency/race guarantees precisely: DB revalidation before generation is not a lock held across a network call.

## Task 2: Independent security and integration review

**Inputs:** Task1 report/diff and approved spec. Read-only; no implementation.

- [x] Check exact live tuple filtering vs Cartesian broadening; missing authority denial; active/frozen target separation; both candidate branches share scope.
- [x] Check prepared evidence against fresh full tuples, fixed-folder move-out rejection, unrestricted explicit identity continuity, active-version/permission revocation and fresh display hydration.
- [x] Check isolation/cleanup and real ES assertions; no reindex, new runtime model, live migration or UI exposure.
- [x] Return spec/quality verdicts with file:line findings; original implementer fixes, independent reviewer rechecks. No redundant suite runs without named doubt.

## Task 3: Main verification and source handoff

**Files:** `docs/labs/rag/design.md`, `docs/decisions/0023-domain-cabinet-conversation.md`, `WORKBOARD.md`, `docs/worklogs/2026-09-13-rag-movement-integrity.md`.

- [x] Main reruns relevant final tests/static checks proportionate to the diff and reads all results. Final broad independent review verifies module connections, frozen regression and honest rollout status.
- [x] Record current-location source selection and exact identity boundary in canonical docs before implementation, then actual outcomes in worklog; keep WORKBOARD recent completed items at5.
- [x] Hand off next move-menu/DnD stage only if required real retrieval/source gates pass. No live0034 apply/restart in this task; preserve current live data and user's dirty code. No automatic push.

## Preflight

Task1 owns retrieval+search implementation and consumed internal scope interface together, avoiding parallel writers. Task2 only reads Task1. Task3 only changes docs and verifies. Public selected-document DTO semantics stay unchanged; new authority is internal. Server0034 is used only by isolated tests. Full live data/evaluation migration and UI remain outside this plan.
