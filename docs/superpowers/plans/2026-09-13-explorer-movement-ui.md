# Explorer Movement UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use TDD and independent spec/quality review.

**Goal:** Connect confirmed single document/folder moves and internal drag-and-drop to the reviewed server contract without widening RAG selection.

**Architecture:** Platform Assets owns typed move requests, movement state and reusable dialog/tree hooks. DomainFileCabinet composes domain preflight and revalidates selected documents after committed moves; ConversationPage only receives selection invalidation. Server-side current-location integrity is already verified. No new drag-and-drop dependency.

**Tech Stack:** Existing Next.js/React/TypeScript, CSS modules and design tokens, browser DragEvent, Vitest/Testing Library.

Review-driven consumer refinement: `assets/LibraryViewer.tsx` receives an optional keyboard ownership flag so its capture-phase Escape handler cannot close the underlying viewer before the move dialog. Existing default behavior remains unchanged.

**Spec:** `docs/superpowers/specs/2026-09-13-explorer-movement-design.md` sections2,3,6 (already approved). Prior server and RAG changes remain uncommitted on main.

## Global Constraints

- main only; preserve all existing dirty files and references. No staging/commit/push/worktree or cleanup.
- No backend changes, migration, restart, live data moves/uploads, external model calls, dependency install or new root artifacts.
- 동일 기능을 내부 드래그앤드롭으로 실행할 수 있다. 외부 OS 파일 드롭을 이동으로 해석하지 않는다.
- 1회에 문서 또는 폴더 하나만 이동한다. 다중 이동, 자동 폴더 병합, 공간 간 이동은 지원하지 않는다.
- 드롭 시에도 출발 위치와 목적지를 보여주는 같은 이동 확인 창을 사용한다. 명시 확인 전에는 서버를 변경하지 않는다.
- 서버 성공 후 조회 실패는 '이동 완료, 목록 새로고침 필요'로 구분하고 이동 POST를 재전송하지 않는다.
- 새 위치가 대화의 고정 폴더 범위 밖이면 선택을 무효로 안내하고 명시 재선택을 요구한다. 검색 범위를 확대하지 않는다.
- No invented metadata_revision fallback. Missing/noninteger/nonpositive revision means movement unavailable until compatible API deployment.
- Existing file browser navigation/preview/upload/new-version/member permissions stay intact. No OS drop upload behavior, rename/trash, mobile DnD or arbitrary new menus.
- Scratch only `.local-data/project-agent-work/explorer-movement-ui/`; synthetic fixtures; no actual account or document payloads.

## Task 1: Confirmed moves, internal DnD and selection integrity

**Files:**
- Modify `frontend/src/features/assets/api.ts`, `DocumentBrowser.tsx`, `LibraryTree.tsx`, `DocumentLibrary.module.css`.
- Create `frontend/src/features/assets/movement.ts`, `useAssetMovement.ts`, `MoveDialog.tsx`, `MoveDialog.module.css` as needed for the distinct policy/state/dialog responsibilities, avoiding general framework abstractions.
- Modify `frontend/src/features/rag/domains/DomainFileCabinet.tsx`, `frontend/src/features/rag/conversation/DocumentSelectionPanel.tsx`, `ConversationPage.tsx` only for post-movement selection/revalidation and nested dialog handling.
- New focused tests: `frontend/src/features/assets/movement.test.ts`, `DocumentBrowser.movement.test.tsx`, `MoveDialog.test.tsx`, `frontend/src/features/rag/domains/DomainFileCabinet.movement.test.tsx`; extend existing `LibraryTree.test.tsx`, `DocumentSelectionPanel.test.tsx`, `ConversationPage.test.tsx` only when the real consumer behavior needs it.
- Do not edit backend/generated schema/other prior tests to bypass contracts. Main owns docs/WORKBOARD.

**Consumed API:** Generated `components["schemas"]["AssetMoveRequest"]`, `DocumentMoveResponse`, `FolderMoveResponse`, existing DocumentSummary/FolderSummary metadata_revision, ApiError, browseLibrary/getLibraryDocument, current capabilities and domain browse/getDocument adapters.

**Produced interfaces:**

```ts
export type AssetMoveRequest = components["schemas"]["AssetMoveRequest"];
export type DocumentMoveResult = components["schemas"]["DocumentMoveResponse"];
export type FolderMoveResult = components["schemas"]["FolderMoveResponse"];
export function moveDocument(workspaceId: string, documentId: string, body: AssetMoveRequest, signal?: AbortSignal): Promise<DocumentMoveResult>;
export function moveFolder(workspaceId: string, folderId: string, body: AssetMoveRequest, signal?: AbortSignal): Promise<FolderMoveResult>;

// movement.ts: internal UI identity, not an authorization token or public API.
export type MoveSource = {
  kind: "document" | "folder";
  id: string;
  workspaceId: string;
  name: string;
  parentId: string | null;
  revision: number;
};
export type MoveResult = DocumentMoveResult | FolderMoveResult;
// DocumentBrowser composition hooks, optional for the plain library.
beforeMove?: (source: MoveSource, destinationId: string | null, signal: AbortSignal) => Promise<void>;
onMoveCommitted?: (source: MoveSource, result: MoveResult) => Promise<void> | void;
// A lost POST response invalidates the initiating selection without claiming commit.
onMoveUncertain?: (source: MoveSource) => void;
onMoveRejected?: (source: MoveSource) => void;
onMoveScopeInvalidated?: () => void;
// DomainFileCabinet -> selection panel -> ConversationPage: marks current selection unsafe.
onSelectionInvalidated?: () => void;
```

Use existing route/request patterns and encode IDs. POST body is exactly `{destination_folder_id, expected_revision}`; no silent automatic retry. Move functions return the generated typed result. Pure eligibility rules are named in movement.ts, not scattered UI business comparisons.

- [x] **RED policy/request tests:** no-op current parent, missing revision refusal, self/known descendant refusal, exact POST URL/body and no fallback. Test move confirmation through real DocumentBrowser with mocked HTTP only:

```tsx
await user.click(screen.getByRole("button", {name: "자료.txt 이동"}));
expect(movePosts()).toHaveLength(0);
// Choose destination B in the real dialog, then explicitly confirm.
await user.click(screen.getByRole("button", {name: "여기로 이동"}));
expect(movePosts()).toHaveLength(1);
expect(JSON.parse(movePosts()[0].body)).toEqual({destination_folder_id: "folder-b", expected_revision: 3});
```

Build complete synthetic pages/capabilities and literal expected bodies; do not assert mocked component existence. Run `node node_modules/vitest/vitest.mjs run src/features/assets/movement.test.ts src/features/assets/DocumentBrowser.movement.test.tsx --pool=threads --maxWorkers=1` from frontend and record expected feature assertion failures before production edits.

- [x] **Implement policy/API and movement state:** one pending move per mounted workspace, invalidated on navigation/workspace/domain change/unmount. Store source identity+actual revision and drag session only in this mounted browser; browser external text is not parsed as a command. Use native custom MIME plus in-memory token/source matching; ignore Files/text/URI payloads and mismatched/stale tokens. Prevent browser navigation on external file drops in the relevant surfaces without uploading them. Drag end clears session without destroying a dialog already opened by drop.
- [x] **Implement dialog and keyboard path:** labelled modal with source and destination breadcrumbs, top-level destination, paginated folder drilldown via existing browse adapter; choose destination only after current read succeeds. Current destination gives no-op message/no POST. Folder self/descendant disabled using authoritative destination ancestors; unknown data is never guessed safe. Server remains final depth/name/permission authority. Enter/Space buttons, trapped Tab, Escape/cancel pre-submit, focus restore to opener or browser heading; stop Escape/Tab propagation to the enclosing DocumentSelectionPanel. Pending confirmation cannot duplicate or claim server rollback; block close while submitting and distinguish uncertain network failure from known rejection.
- [x] **Connect tree/file rows:** per-source movement button with accessible unique name, internal drag affordance, valid/forbidden drop highlight and `dropEffect`, top-level and folder destinations. Keep navigation/open/expand independent and no nested buttons. Retain ordinary browser semantics; do not add incomplete ARIA tree roles. Use existing file CSS variables, wrapping action groups, min-width0 and narrow layout without horizontal overflow. Source readOnly/capability pending/revoked/missing revision prevents drag and commands.
- [x] **Confirm preflight and errors:** re-read exact source metadata and authoritative destination; if revision/position changed, show conflict and require explicit refresh/reconfirmation instead of silently substituting revision. Check domain source and destination through beforeMove, preserve browser current scope mutation lock and abort guards. Friendly stable mappings for asset_revision_conflict/folder_exists/folder_cycle/folder_depth_exceeded/folder_hierarchy_invalid/not_found.401/403/404 revoke stale write affordances.409 prompts fresh metadata/destination reads and explicit reconfirm; no auto replay. Unknown network outcome requires refresh rather than blindly retrying POST.
- [x] **Success reconciliation:** after known successful POST, mark committed before any revalidation callback/read. Refresh current page, actual source parent and destination page plus root/ancestry to invalidate tree caches; use returned DB snapshots, not fabricated folders or stale ensured rows. Preserve navigation generation and avoid late response overwriting a new workspace/selection. Keep stable open document identity if still valid, update viewer metadata from fresh DB, keep current folder by ID for folder moves. On refresh failure expose refresh-only recovery, never another move confirmation for the already committed action. Loading additional folder/document pages remains duplicate-safe.
- [x] **Domain selection:** after committed document/folder move, re-read selected IDs through domain adapter. Preserve ID selection and refresh metadata for position-only unrestricted changes. If a selected source leaves retained folder bounds or changes active version/loses access, require explicit reselection; do not silently drop one document and search the remainder. Notify enclosing ConversationPage so closing the panel without Apply cannot leave canSend enabled with stale selected docs. Reuse requiresScopeRevision and existing scope-change/reset behavior, no automatic workspace/folder widening. Block applying selection during revalidation; late response cannot overwrite newer selection/domain/workspace. Fixed folder bounds restrict search selection, not permitted move destinations within the same authorized workspace.
- [x] **GREEN/full focused tests:** cancellation/focus, external and stale drag rejection, same-parent no-op, self/descendant, denied/loading rights, exactrevision,409 explicit refresh,revoke,duplicateclick,committed refresh failure,late response after navigation/unmount; selected unrestricted position preserved, fixed-boundary invalidation including close-without-apply, related nested modal Escape handling. Run affected asset/domain/conversation test suites with actual API adapters and mocked fetch. Run `node node_modules/typescript/bin/tsc --noEmit --pretty false --incremental false`, `node node_modules/eslint/bin/eslint.js . --max-warnings 0` and `node openapi-ts.config.mjs --check` from frontend. No dependency installs/build against active .next.
- [x] Self-review and report `.local-data/project-agent-work/explorer-movement-ui/task-1-report.md`: exact files/RED/GREEN, mock vs actual UI boundary, limitations, no live migrations, no commit. Stop writes before independent review. Escalate new backend/API requirements instead of widening scope.

## Task 2: Independent task review

- [x] Read scoped before/after diff plus new files and implementation report. Check payload trust, same-workspace/revision/permission gates, duplicate mutation lifecycle, committed-vs-refresh failure, nested modal keyboard and RAG no-widening consumer.
- [x] Return separate spec and quality verdicts with file:line findings. Original implementer fixes Critical/Important, followed by scoped independent re-review. No redundant suite execution without concrete missing evidence.

## Task 3: Main verification, browser check and source handoff

- [x] Main reruns focused tests, nonincremental typecheck, full lint and schema check; read exit codes. Verify actual browser menu/dialog/drop using synthetic intercepted API responses only if available, without live writes or restart; clearly distinguish from live backend E2E. If login/environment prevents safe UI inspection, retain that specific unverified boundary rather than weakening authority.
- [x] Main updates approved spec/ADR status, worklog `docs/worklogs/2026-09-13-explorer-movement-ui.md`, WORKBOARD current and latest5. Request final broad independent source-handoff review.
- [x] Record remaining coordinated0034 migration/restart and user data validation separately. No automatic deployment/commit/push. Preserve uncommitted handoff artifacts under project policy.

## Preflight

Task1 owns tightly coupled movement and parent selection lifecycle; no parallel writers. Task2 reads implementation only. Task3 owns docs and independent execution. Existing generated move DTOs are sufficient, no backend contract change. Confirm-first same-workspace movement and fixed search range are intentionally separate. Runtime revision gate protects old API responses while server cutover stays outside this task.
