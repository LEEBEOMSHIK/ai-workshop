# Explorer Movement Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Follow the checked task boundaries and preserve unrelated changes.

**Goal:** Implement the transactional Platform document/folder movement API before exposing movement in the cabinet.

**Architecture:** Platform owns metadata revisions, hierarchy validation and movement transactions. Existing workspace write locks serialize create/move with permission changes. RAG search integrity and frontend movement are dependent follow-up slices; neither is exposed by this server slice.

**Tech Stack:** Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, existing pytest environment.

**Spec:** `docs/superpowers/specs/2026-09-13-explorer-movement-design.md` (approved by user on 2026-09-13).

## Global Constraints

- Work on main as explicitly requested; no new worktree, staging, commit or push by subagents.
- Preserve existing uncommitted frontend changes and references. No real document moves, uploads, live migration or service restart.
- Use existing `backend/.venv`; no dependencies, environments or pytest cache installation/creation.
- Folder/Document 각각에 `metadata_revision` non-null/default1/check>=1을 추가한다.
- 원본 bytes, object_key, SHA-256, 문서·버전·Asset·projection·build·chunk ID, 승인 이력은 바꾸지 않는다.
- 잠금 순서는 기존 workspace 행 → 정렬된 사용자 membership 행 → 수정 대상 행 순서로 유지한다. 중복 hierarchy advisory 잠금은 추가하지 않는다.
- 같은 위치 no-op도 현재 권한과 expected_revision을 검증한 뒤 revision을 증가시키지 않는다.
- 검색 정합성 검증 전에는 이동 UI를 노출하지 않는다.
- Temporary role handoff files belong only in `.local-data/project-agent-work/explorer-movement-server/`; repository policy overrides the skill's default scratch location.

## Task 1: Transactional server movement and metadata contract

**Files:**
- Modify `backend/src/ai_workshop/platform/assets/{models,domain,repository,library_repository,schemas,service,api}.py`.
- Create `backend/src/ai_workshop/platform/assets/movement.py` for movement service and hierarchy policy; keep handlers thin.
- Create `backend/alembic/versions/0034_asset_metadata_revision.py` after verifying revision head.
- Create `backend/tests/unit/platform/assets/test_asset_movement.py`.
- Create `backend/tests/integration/platform/assets/test_asset_movement.py` using the existing `isolated_publishing_database` fixture helper.
- Update existing affected assets unit/integration tests for DTO and repository contracts.
- Do not edit frontend, RAG, WORKBOARD or live settings.

**Interfaces:**

```python
class AssetMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination_folder_id: UUID | None
    expected_revision: Annotated[int, Field(strict=True, ge=1)]
```

Produce POST `/api/v1/workspaces/{workspace_id}/documents/{document_id}/move` and `/api/v1/workspaces/{workspace_id}/folders/{folder_id}/move`.
Both responses contain `id`, `workspace_id`, `name`, `metadata_revision`, `changed`; document response uses `folder_id`, folder response uses `parent_id`.
Add metadata_revision to all folder/document responses from the true stored/domain value, never a UI default.
Stable AppError codes distinguish revision conflict, folder-name collision, cycle, depth exceeded and invalid existing hierarchy. Use 404 for unreadable/wrong-workspace targets and permission denial before disclosing revisions; stale revision is 409.

- [x] Write RED unit tests for strict payload (missing destination/revision, bool, string, zero, unknown fields), default revision, same-position no-op, stale no-op, null round trip, folder cycle and subtree depth.

```python
@pytest.mark.parametrize("revision", [True, "1", 0])
def test_move_revision_is_strict(revision):
    with pytest.raises(ValidationError):
        AssetMoveRequest(destination_folder_id=None, expected_revision=revision)
```

- [x] Run from backend: `.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider tests/unit/platform/assets/test_asset_movement.py -q`; record expected missing implementation/assertion failure, not environment failure.
- [x] Implement metadata migration/domain mappings and repository movement under existing workspace write lock. The conditional write must include expected revision, use one transaction, and count the affected row.

```python
statement = update(DocumentRecord).where(
    DocumentRecord.id == document_id,
    DocumentRecord.workspace_id == workspace_id,
    DocumentRecord.metadata_revision == expected_revision,
).values(folder_id=destination_folder_id, metadata_revision=expected_revision + 1)
```

Read source/destination under the lock; verify same workspace before conflict details. For folders inspect full affected subtree plus destination ancestry, reject self/descendant, broken graph and `destination_depth + subtree_height > library_max_depth`. Reuse this depth validation in create_folder under its existing lock. Preserve stripped sibling-name policy including null parent; allow same-named documents. Do not move bytes, reindex or enqueue jobs.
- [x] Add isolated PostgreSQL integration tests: migration upgrade from0033/default1/check>=1/downgrade; document/folder move top and back; unchanged versions/hash/objectkeys; same revision two concurrent requests yield one success; A→B/B→A cannot create a cycle; create/move duplicate sibling race; create/move depth race; revoked writer waiting on the workspace lock is denied; cross-workspace and personal nonowner denial; rollback/no-op revision behavior; stale worker version persistence must not overwrite current location.
- [x] Run `.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider tests/unit/platform/assets tests/integration/platform/assets/test_asset_movement.py -q`; integration tests may operate ONLY on helper-created `ai_workshop_publishing_<uuid>` databases, never live DB tables. Report permission/environment failure honestly and keep UI unavailable if tests cannot run.
- [x] Run existing environment Ruff with `--no-cache` over changed files and mypy over assets. Self-review diff and report exact commands/results, changed files, API error codes, migration compatibility and remaining evidence gaps. No commit.

## Task 2: Independent server contract and concurrency review

**Files:** Read Task1 diff, report and approved spec. No production edits.

**Interfaces:** Consumes Task1 API/metadata contract; produces spec-compliance and quality verdict with file:line findings.

- [x] Review lock order against `platform/workspaces/permissions.py`, commit/rollback against session dependency and update row count against stale requests.
- [x] Check fresh permission/source/destination reads, cycle/subtree depth, null collision, unrelated immutable IDs and worker persistence.
- [x] Compare tests with every Task1 acceptance case; distinguish executed evidence from skipped checks.
- [x] Send concrete findings to original implementer and review only subsequent fixes. Do not duplicate already evidenced test runs without a named doubt.

## Task 3: Contract handoff and rollout gate

**Files:** `frontend/src/shared/api/schema.d.ts` generated via existing script; affected typed fixtures if required; `WORKBOARD.md`; `docs/worklogs/2026-09-13-explorer-movement-server.md`.

- [x] After server review, run `node openapi-ts.config.mjs` from frontend and `node node_modules/typescript/bin/tsc --noEmit --pretty false`. Add explicit revision1 to synthetic fixture objects only where required by generated types; never synthesize revision for live responses.
- [x] Run frontend existing assets tests and lint for amended fixtures. Run backend relevant regression once with current code. Record real results.
- [x] Record server-only completion and next RAG exact-identity search/pre-generation validation slice. Keep movement UI absent until that slice is verified. State live0033 remains unchanged; applying0034/restarting requires the separate backup/restore maintenance scope in the approved spec.

## Preflight coverage

This plan implements spec sections3–4 and server verification in section6. Section1 is already implemented. Sections2 and5 are deliberately dependent slices, not claims of completion here; no frontend move action is added. Task1 produces metadata fields consumed by Task3 generation. Task2 is read-only and independent from Task1. Task3 may update synthetic frontend fixtures without altering prior UI behavior.
