# Document Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task with independent review.

**Goal:** Company/personal folder navigation, scoped uploads and independent TXT/MD/PDF viewing.
**Architecture:** Platform Assets owns bounded library queries and verified originals; neutral infrastructure renders PDF. React consumes typed same-origin APIs without Labs dependencies.
**Tech Stack:** Existing FastAPI/SQLAlchemy/PostgreSQL/ObjectStore/PyMuPDF, Next.js/React/TypeScript/CSS modules.
**Spec:** `docs/superpowers/specs/2026-09-09-document-library-design.md`

## Execution status — 2026-09-09

Tasks 1–3 implementation and automated code gates have passed, including independent task reviews,
the whole-feature review and its one final fix/re-review wave. Main final frontend regression is
55 tests across 8 files with no warnings; types, scoped lint and API parity pass. Backend verification
and issue-resolution evidence are recorded in `docs/worklogs/2026-09-09-document-library.md`.
Authenticated read-only desktop/responsive acceptance remains pending user re-login. Do not treat
the original checklists below as full live acceptance or repeat completed implementation work.
No commit/push, live data change or cache cleanup was performed. WORKBOARD owns the next action.

## Global Constraints

- 현재 main에서만 작업하며 기존 변경·원본·공간·정책을 보존한다.
- Platform은 Labs/RAG를 import하지 않는다.
- RAG 구독·색인·임베딩·검색 평가·외부 AI 승인은 열람의 선행 조건이 아니다.
- 최초 TXT/Markdown escaped text, PDF local page images; Office/HTML explicit download-only.
- No move/rename/trash, approval relocation, automatic model/OCR calls, live data writes or packages.
- Each implementation uses RED/GREEN tests, frozen baseline/diff/report and independent review.
- Artifacts only `.local-data/project-agent-work/document-library/`; no worktrees, git commits or broad cleanup by agents.
- Backend runtime settings and frontend design tokens carry limits; IDs/paths/keys remain server-authoritative.

### Task 1: Bounded authorized library and folder uploads

**Files:** `backend/src/ai_workshop/platform/assets/{api,schemas,service,repository}.py`, new `library.py`, `library_repository.py`, `library_api.py`; `backend/src/ai_workshop/config.py`; unit assets tests and new `test_asset_library.py`, existing asset API tests and isolated SQL tests.
**Produces:** existing DocumentResponse adds workspace_id, folder_id, active_version_id, latest_version_id (all actual server values, folder/active nullable); original list consumers remain compatible.

New GET `/api/v1/workspaces/{workspace_id}/library` query `folder_id` nullable(root), `folder_cursor`, `document_cursor`, `limit` optional.
Response contract:
```ts
type LibraryPage = {
  workspace: WorkspaceSummary;
  folder: FolderResponse | null;
  ancestors: FolderResponse[]; // root-to-parent, excludes current
  folders: (FolderResponse & { has_children: boolean })[];
  documents: DocumentResponse[];
  next_folder_cursor: string | null;
  next_document_cursor: string | null;
};
```
New GET `/api/v1/workspaces/{workspace_id}/library/documents/{document_id}` returns DocumentResponse after exact workspace ownership; permits restoring selected documents outside currently paged rows.
New GET same document prefix `/versions` returns `{items: AssetVersionResponse[], next_cursor: string|null}` using `cursor`/`limit`, descending `(number,id)` and document/workspace-bound cursor. Existing unpaged versions endpoint stays unchanged for old consumers; the new library never uses it. Exact URL-selected old version metadata/content resolves via Task2 preview, independent of loaded version pages.

- [ ] Freeze changed-file baseline before edits in task-1/baseline. Test foreign folder upload denied before storage put, blank/oversize folder name denied, root/child scoped listing and unrelated-document lookup denial.
```python
with pytest.raises(AppError) as failure:
    await service.upload(user=member, workspace_id=allowed_space, folder_id=foreign_folder,
                         filename="synthetic.md", media_type="text/markdown", content=chunks())
assert failure.value.status_code == 404  # use actual AppError status property
assert store.writes == []
```
- [ ] Run focused tests and record expected missing behavior RED (not broken fixture setup).
- [ ] Implement scoped queries with authorization and workspace expiry before rows, direct-child only filtering, sorted `(name,id)` keyset cursors with version/workspace/folder/kind scope validation. Invalid/cross-scope cursor 422; inaccessible folder 404. Each list fetches limit+1, never loads entire workspace/versions.
- [ ] Settings: library_page_size default50, max200; library_max_depth default64. Cursor input max4096 chars, all decoded shapes strict. Ancestor cycles/depth overflow fail safe; bounded has_children EXISTS checks. Concurrent sibling folder creation serialized using a named workspace-scoped transaction advisory lock, preserving existing create API. Trim and length1..180 names in service and schema. Check upload folder membership before storage write.
- [ ] Tests: pagination ties, root vs child, foreign/expired/member, malformed cursor, max limits, metadata active/latest difference, folder duplicate under two sessions. Use existing isolated SQL harness; no user DB writes. Run related unit/API, Ruff and mypy touched modules.
- [ ] Freeze task-1/report.md, review.patch and manifest with baseline/current hashes. Main reviews and regenerates OpenAPI before frontend implementation.

### Task 2: Verified original and bounded PDF preview

**Files:** new `platform/assets/originals.py`, `originals_api.py`, tests `test_asset_originals.py`; minimal assets api inclusion/config changes; neutral `infrastructure/document_formats/pdf_preview.py` and `pdf_preview_worker.py`, renderer tests. Existing RAG viewer change only for pure renderer reuse with unchanged RAG permission/normalization behavior.
**Consumes:** Task1 scoped document identity and existing ObjectStore.open. Resolve exact version with bounded document/version query, not find_document_for_user's full version hydration.
**Produces:**
```ts
type OriginalPreview = {
  document_id: string; asset_version_id: string; version: number; name: string;
  kind: "text" | "markdown" | "pdf" | "unsupported";
  size: number; text: string | null; page_count: number | null;
};
```
GET `/api/v1/documents/{document_id}/versions/{version_id}/preview` returns above.
GET same prefix `/pdf/pages/{page_number}` returns PNG.
GET same prefix `/content` returns explicit safe attachment bytes.

- [ ] RED synthetic unit/API tests proving exact version rights/READY, foreign denied before read, historic READY usable, corruption/oversize/missing original fails before returning body, UTF8 BOM/nonBMP preserved.
```python
preview = await originals.preview(user=member, document_id=doc.id, version_id=old_ready.id)
assert preview.text == "합성 문서\n안녕하세요"
assert preview.asset_version_id == old_ready.id
```
- [ ] Implement complete bounded bytes read, size+SHA validation and final authorization recheck before response/render output. No verify-then-reopen, no absolute path leak, no streaming unverified content. Select kind from exact stored version suffix and actual content; never current document filename/upload MIME alone. Decode text UTF8-sig strict; render HTML/other only unsupported metadata/download.
- [ ] Settings defaults: original_max_bytes=50MiB, text_preview_max_bytes=2MiB, pdf_max_pages=1000, pdf_max_pixels=16_000_000, pdf_timeout_seconds=15, pdf_max_concurrent=2. Reject invalid bounds at startup. Limits reject explicitly, never silent truncation.
- [ ] Run trusted PDF worker in separately terminable local process with bounded verified input/output, no shell commands derived from user data, no credentials/environment forwarding beyond required runtime. Explicitly parse PDF, verify page/pixel bounds before pixmap; bound concurrent work. Timeout/cancel/error terminate and reap worker, release slot; never claim thread cancellation kills native renderer. Use no persistent preview cache or new external dependency. Neutral renderer extraction preserves existing RAG tests.
- [ ] Return private/no-store + nosniff. Validate attachment name and Content-Disposition safely. 404 unauthorized/missing version,409 notREADY,413 bounds,422 unsupported preview/invalid PDF/page/encoding,503 storage/integrity unavailable; errors body-free. Unsupported preview metadata still200 with download option.
- [ ] Actual synthetic two-page PDF rendering and subprocess timeout/cancel/slot cleanup tests; role/expiry/recheck races via isolated SQL. Run type/lint and existing RAG viewer regression. Freeze task-2 artifacts.

### Task 3: File explorer and document viewer UI

**Files:** workspace list/page/create form scoped layout; assets api/DocumentPage/DocumentBrowser/UploadDialog; new assets LibraryTree, LibraryViewer and small focused hooks/CSS/tests; workspace documents route and tests; route helper; generated schema after Task2.
**Consumes:** Task1 LibraryPage/doc lookup + bounded library versions, Task2 OriginalPreview/PNG/download.

- [ ] RED tests for real space label/kind, creation form collapsed, selecting folder drives scoped GET and upload folder_id, file click opens exact active version, unsupported preview shows explicit limitation, no mutation on navigation.
```tsx
await user.click(screen.getByRole("button", { name: "합성 문서.md 열기" }));
expect(await screen.findByText("합성 문서 원문")).toBeVisible();
await user.click(screen.getByRole("button", { name: "문서 닫기" }));
expect(screen.getByRole("button", { name: "합성 문서.md 열기" })).toHaveFocus();
```
- [ ] Group accessible real workspace kinds, lazy expandable folder tree (fully tested tree keys or nested disclosure navigation with aria-current), bounded load-more controls, current breadcrumbs. Use initial scoped SSR data; server guard/cookie/failure behavior unchanged. URL query folder/document/version restoration uses actual server metadata, not assumptions about loaded pages. Unknown/inaccessible IDs safe error, no fallback to different content.
- [ ] Folder creation and upload target selected folder; refresh exact page after mutation, distinguish job status from original READY/RAG ready. Latest vs active version labels and historical version selection. Existing upload/new-version/duplicate handling preserved.
- [ ] Text preview is escaped preformatted source with wrapping toggle if needed; PDF page previous/next and readable image; download only explicit click. Abort/ignore stale loads on scope/version changes; revoke blob URLs on close/change/unmount. Nonmodal desktop pane + small-screen expanded view, close/expand, keyboard focus safe, busy/error/empty/retry states.
- [ ] Shared file-management container/CSS tokens align header/form/list and use available desktop width. Do not alter admin/game/RAG search global widths. Long names/URLs wrap without horizontal page overflow. Company/personal labels from enum, no actual IDs hardcoded.
- [ ] Run focused vitest incl old upload/workspace/SourceViewer, tsc, scoped lint; real browser read-only existing synthetic TXT/MD file and responsive widths. No approval/mutation action in live browser. Freeze task-3 artifacts.

### Integration and handoff (main)

- [ ] Independent task reviews and final combined scope/security review; resolve findings through implementer.
- [ ] Regenerate/check API schema; run focused backend/frontend regressions, static checks and actual safe read-only runtime verification after owner-process-only backend restart if required.
- [ ] Update approved spec/ADR/runbook/WORKBOARD with verified scope and remaining Office/move/approval stages; recent completed<=5.
- [ ] Report implemented vs unverified separately. No whole RAG-ready claim, no auto approval or live fixture writes. Retain active review artifacts until canonical handoff and cache-policy cleanup gate.
