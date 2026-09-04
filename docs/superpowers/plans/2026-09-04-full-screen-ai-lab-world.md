# Full-Screen AI Lab World Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the separate card-style public landing and Lab list with one full-viewport AI laboratory world shared by `/` and `/labs`, including an accessible RAG manager dialog anchored to the character on desktop and presented as a bottom panel on mobile.

**Architecture:** Both public routes render the same server component and validated public catalog state. The RAG room remains DOM/CSS, while the client-only character component owns dialog state, focus, scroll lock, viewport measurement, and a pure positioning function. No backend, database, RAG runtime, or public catalog schema/content changes are allowed.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript 5.9, CSS Modules, Vitest, Testing Library, jsdom

**Spec:** `docs/superpowers/specs/2026-09-03-full-screen-ai-lab-world-design.md`

## Global Constraints

- `/` and `/labs` each return `200` and render the same `LabWorldPage`; `/labs` does not redirect.
- Render only Labs present in the validated public catalog; do not add future Lab placeholders.
- The current RAG catalog data, schema, backend API, database, and migrations do not change.
- Use accessible DOM and CSS only; do not add Canvas, WebGL, a game engine, or a new runtime dependency.
- Desktop and tablet use a character-anchored dialog that flips and clamps inside the viewport; widths below `48rem` use a safe-area-aware bottom panel.
- Preserve `role="dialog"`, `aria-modal="true"`, close-button initial focus, focus containment, Escape close, and trigger focus restoration.
- Keep the character trigger anchor stationary; animate only an inner visual layer.
- Use `100vh` and `100dvh`, allow vertical document scrolling, and prevent horizontal overflow.
- `prefers-reduced-motion: reduce` removes nonessential character and status animations.
- Main Codex alone stages and commits. Task agents edit and test only; reviewers never implement the change they approve.
- Preserve unrelated `references/`, locked pytest temporary paths, and all user-owned changes.

---

### Task 1: Share one validated public world across both routes

**Files:**
- Modify: `frontend/src/features/public-labs/catalog.ts`
- Modify: `frontend/src/features/public-labs/catalog.test.ts`
- Modify: `frontend/src/features/public-labs/LabWorldPage.tsx`
- Modify: `frontend/src/features/public-labs/LabWorldPage.test.tsx`
- Modify: `frontend/src/app/page.tsx`
- Create: `frontend/src/app/page.test.tsx`
- Modify: `frontend/src/app/(public)/labs/page.tsx`
- Modify: `frontend/src/app/(public)/labs/page.test.tsx`
- Delete after replacement: `frontend/src/features/home/HomePage.tsx`
- Delete after replacement: `frontend/src/features/home/HomePage.test.tsx`

**Interfaces:**
- Produces: `PublicLabCatalogResult = { status: "ready"; labs: readonly PublicLab[] } | { status: "error"; labs: readonly [] }`
- Produces: `loadPublicLabCatalog(input?: unknown): PublicLabCatalogResult`
- Consumes: existing `parsePublicLabCatalog(input)` and unchanged `public-labs.json`
- Produces: `LabWorldPage({ catalog }: { catalog: PublicLabCatalogResult })`
- Produces: both route modules export `metadata.alternates.canonical` as `/`

- [ ] **Step 1: Add failing catalog boundary tests**

Add tests with literal expectations:

```ts
expect(loadPublicLabCatalog({ labs: [] })).toEqual({ status: "ready", labs: [] });
expect(loadPublicLabCatalog({ labs: [{ invalid: true }] })).toEqual({
  status: "error",
  labs: [],
});
```

The production change these catch is an invalid catalog escaping into the route as an exception or being silently replaced with hardcoded RAG data.

- [ ] **Step 2: Run the catalog test and verify RED**

Run from `frontend/`:

```text
pnpm exec vitest run src/features/public-labs/catalog.test.ts
```

Expected: FAIL because `loadPublicLabCatalog` is not exported.

- [ ] **Step 3: Implement the catalog result boundary**

Implement a pure wrapper that uses the imported manifest only when `input` is omitted:

```ts
export type PublicLabCatalogResult =
  | { status: "ready"; labs: readonly PublicLab[] }
  | { status: "error"; labs: readonly [] };

export function loadPublicLabCatalog(
  input: unknown = publicLabsManifest,
): PublicLabCatalogResult {
  try {
    return { status: "ready", labs: parsePublicLabCatalog(input) };
  } catch {
    return { status: "error", labs: [] };
  }
}
```

Do not change `parsePublicLabCatalog` or the manifest.

- [ ] **Step 4: Verify the catalog test GREEN**

Run the Step 2 command. Expected: all catalog tests PASS.

- [ ] **Step 5: Add failing route and world-state tests**

Test these observable outcomes with real components:

```ts
const ready = loadPublicLabCatalog();
render(<LabWorldPage catalog={ready} />);
expect(screen.getByRole("heading", { name: "AI 기술 관리자들이 일하는 연구소" })).toBeVisible();
expect(screen.getByRole("region", { name: "RAG 기술 연구실" })).toBeVisible();

render(<LabWorldPage catalog={{ status: "ready", labs: [] }} />);
expect(screen.getByText("현재 공개된 연구실을 준비하고 있습니다")).toBeVisible();
expect(screen.getByRole("navigation", { name: "공개 전시실" })).toBeVisible();
expect(screen.queryByText("RAG 기술 연구실")).not.toBeInTheDocument();

render(<LabWorldPage catalog={{ status: "error", labs: [] }} />);
expect(screen.getByRole("alert")).toHaveTextContent("연구실 정보를 불러오지 못했습니다");
expect(screen.getByRole("navigation", { name: "공개 전시실" })).toBeVisible();
expect(screen.queryByText("RAG 기술 연구실")).not.toBeInTheDocument();
```

For both route tests, render the route result and assert the same world heading and RAG manager button. Also assert that no `AI Lab 둘러보기` link remains on `/` and that both modules export `/` as `metadata.alternates.canonical`.

- [ ] **Step 6: Run route/world tests and verify RED**

```text
pnpm exec vitest run src/features/public-labs/LabWorldPage.test.tsx src/app/page.test.tsx "src/app/(public)/labs/page.test.tsx"
```

Expected: FAIL because `/` still renders `HomePage`, `LabWorldPage` accepts `labs`, and empty/error states do not exist.

- [ ] **Step 7: Implement the shared world route**

Make both route files call the same component with the same loader result:

```tsx
export default function HomeRoute() {
  return <LabWorldPage catalog={loadPublicLabCatalog()} />;
}
```

```tsx
export default function LabsRoute() {
  return <LabWorldPage catalog={loadPublicLabCatalog()} />;
}
```

Both route modules export Next.js metadata with `alternates: { canonical: "/" }`. This declares `/` as the search canonical without redirecting `/labs`.

Refactor `LabWorldPage` to render:

- `PublicNavigation`
- one world heading `AI 기술 관리자들이 일하는 연구소`
- a status HUD explaining that visible rooms come from published Labs
- one semantic room region per catalog Lab, labelled by its Lab heading
- the existing `AgentCharacter` with `variant="working"`
- the specified ready-empty status or error alert while keeping public navigation available

Remove `HomePage` only after no import remains. Do not hardcode a RAG fallback.

- [ ] **Step 8: Verify Task 1 GREEN and regression scope**

Run:

```text
pnpm exec vitest run src/features/public-labs/catalog.test.ts src/features/public-labs/LabWorldPage.test.tsx src/app/page.test.tsx "src/app/(public)/labs/page.test.tsx"
```

Expected: all listed tests PASS.

- [ ] **Step 9: Task review and main-only commit**

The task agent writes its report without staging or committing. The main orchestrator obtains an independent spec/quality review of the working diff, then commits only Task 1 files with:

```text
feat(frontend): share the public lab world routes
```

---

### Task 2: Anchor the accessible dialog to the character

**Files:**
- Create: `frontend/src/features/public-labs/dialog-position.ts`
- Create: `frontend/src/features/public-labs/dialog-position.test.ts`
- Modify: `frontend/src/features/public-labs/AgentCharacter.tsx`
- Modify: `frontend/src/features/public-labs/AgentCharacter.test.tsx`

**Interfaces:**
- Produces: `RectLike`, `Size`, `DialogPlacement`, and `calculateDialogPlacement(anchor, dialog, viewport)`
- Produces: CSS custom properties `--dialog-left`, `--dialog-top`, `--dialog-tail-offset`
- Consumes: the unchanged `PublicLab` manager content and CTA

- [ ] **Step 1: Add failing pure geometry tests**

Use hand-derived rectangles to cover each meaningful branch:

```ts
expect(calculateDialogPlacement(
  { left: 100, top: 200, right: 260, bottom: 460, width: 160, height: 260 },
  { width: 320, height: 240 },
  { width: 1200, height: 800 },
)).toMatchObject({ side: "right", left: 284 });

expect(calculateDialogPlacement(
  { left: 980, top: 200, right: 1140, bottom: 460, width: 160, height: 260 },
  { width: 320, height: 240 },
  { width: 1200, height: 800 },
)).toMatchObject({ side: "left", left: 636 });
```

Add a narrow-space case that chooses `above` and cases that clamp left, top, and tail offset within a `20px` viewport margin. The production mutations caught are wrong side selection, missing flip, and viewport overflow.

- [ ] **Step 2: Run geometry tests and verify RED**

```text
pnpm exec vitest run src/features/public-labs/dialog-position.test.ts
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the pure placement function**

Use constants `VIEWPORT_MARGIN = 20` and `DIALOG_GAP = 24`. Prefer right, flip left, otherwise place above or below while clamping both axes. Return:

```ts
interface DialogPlacement {
  side: "right" | "left" | "above" | "below";
  left: number;
  top: number;
  tailOffset: number;
}
```

The tail offset is relative to the dialog edge and must remain between `24` and the corresponding dialog dimension minus `24`.

- [ ] **Step 4: Verify geometry tests GREEN**

Run the Step 2 command. Expected: all geometry tests PASS.

- [ ] **Step 5: Add failing character behavior tests**

Extend the real component tests to verify:

- the dialog remains under `document.body`, not inside the animated article
- opening sets `document.body.style.overflow` to `hidden`
- closing restores the exact previous body overflow value
- a measured trigger/dialog produces `data-placement="right"` and pixel CSS variables
- dispatching `resize` recomputes placement from changed rectangles
- dispatching `orientationchange` and capture-phase `scroll` each recomputes placement
- unmounting cancels a queued animation frame and removes all three event listeners
- close-button initial focus, Tab containment, Escape close, and trigger focus restoration still pass

Stub only browser geometry (`getBoundingClientRect`) and `requestAnimationFrame`; do not mock the component or catalog.

- [ ] **Step 6: Run character tests and verify RED**

```text
pnpm exec vitest run src/features/public-labs/AgentCharacter.test.tsx
```

Expected: FAIL on missing placement data/CSS variables and missing body scroll lock.

- [ ] **Step 7: Implement measured dialog behavior**

In `AgentCharacter`:

- keep stable `triggerRef`, add `dialogRef`, and store `DialogPlacement | null`
- calculate after open in `useLayoutEffect`
- recalculate on `resize`, `orientationchange`, and capture-phase `scroll`
- cancel the scheduled animation frame and remove all listeners on cleanup
- save the previous `document.body.style.overflow`, set `hidden`, and restore the exact saved value
- keep the body portal, modal semantics, focus trap, Escape behavior, and focus restoration
- put `variant` animation on a new inner visual wrapper rather than the article or trigger
- expose placement through `data-placement` and typed CSS custom properties

If measurement produces a zero-size dialog, render the safe centered fallback class without blocking content or controls.

- [ ] **Step 8: Verify Task 2 GREEN and regression scope**

Run:

```text
pnpm exec vitest run src/features/public-labs/dialog-position.test.ts src/features/public-labs/AgentCharacter.test.tsx
```

Expected: all listed tests PASS with no React act warnings.

- [ ] **Step 9: Task review and main-only commit**

After independent review, the main orchestrator commits only Task 2 files with:

```text
feat(frontend): anchor the lab manager dialog
```

---

### Task 3: Build the full-viewport RAG laboratory scene

**Files:**
- Modify: `frontend/src/features/public-labs/LabWorldPage.tsx`
- Modify: `frontend/src/features/public-labs/LabWorldPage.test.tsx`
- Modify: `frontend/src/features/public-labs/AgentCharacter.tsx`
- Modify: `frontend/src/features/public-labs/PublicLabScene.module.css`
- Modify if required for normal-flow HUD spacing: `frontend/src/features/navigation/PublicNavigation.module.css`

**Interfaces:**
- Consumes: Task 1 world states and Task 2 placement custom properties/data attribute
- Produces: semantic RAG room equipment decorations and responsive visual layers
- Preserves: public catalog content and existing `/labs/rag` CTA

- [ ] **Step 1: Add failing semantic scene tests**

Assert user-visible and accessibility behavior rather than CSS source text:

```ts
const room = screen.getByRole("region", { name: "RAG 기술 연구실" });
expect(within(room).getByText("문서 수집 라인")).toBeVisible();
expect(within(room).getByText("검색 코어")).toBeVisible();
expect(within(room).getByText("근거 검증 모니터")).toBeVisible();
expect(within(room).getAllByRole("button")).toHaveLength(1);
```

This catches missing room context and decorative equipment accidentally becoming fake controls. Also verify the single button is the RAG manager trigger.

- [ ] **Step 2: Run the scene test and verify RED**

```text
pnpm exec vitest run src/features/public-labs/LabWorldPage.test.tsx
```

Expected: FAIL because the named laboratory equipment is not rendered.

- [ ] **Step 3: Implement semantic room structure**

Add non-interactive equipment groups around the manager:

- `문서 수집 라인`
- `검색 코어`
- `근거 검증 모니터`

Use headings or labelled groups appropriate to the room hierarchy. Decorative lights, cables, grid lines, and screens use `aria-hidden="true"`; do not add buttons, links, inputs, fake toggles, or hardcoded model data.

- [ ] **Step 4: Implement the CSS world and responsive contract**

Replace the `76rem` card shell with:

- `.page`: `min-height: 100vh; min-height: 100dvh; overflow-x: clip;`
- normal-flow HUD navigation and world intro
- `.scene`/room grid spanning the available viewport width without a max-width card wrapper
- background, wall, floor, room boundaries, equipment layers, and z-index tokens local to the module
- a stable character anchor and inner transform/opacity animation only
- desktop/tablet dialog positioning from Task 2 custom properties and placement-specific speech-bubble tails
- below `48rem`, a fixed bottom dialog panel using `env(safe-area-inset-bottom)`, bounded height, and internal scrolling
- below `64rem` and below `40rem` viewport height, reduced decoration density and spacing
- reduced-motion rules that remove all nonessential animations

Do not add a permanent global stylesheet restriction to `body` overflow or add a dependency/image
asset. Keep Task 2's temporary inline body scroll lock while the modal dialog is open.

- [ ] **Step 5: Verify Task 3 component tests GREEN**

Run:

```text
pnpm exec vitest run src/features/public-labs/LabWorldPage.test.tsx src/features/public-labs/AgentCharacter.test.tsx src/app/page.test.tsx "src/app/(public)/labs/page.test.tsx"
```

Expected: all listed tests PASS.

- [ ] **Step 6: Run static frontend verification**

Run sequentially from `frontend/`:

```text
pnpm test -- --run
pnpm run typecheck
pnpm run lint
pnpm run build
```

Expected: every command exits `0`; no test failures, type errors, ESLint warnings, or build errors.

- [ ] **Step 7: Task review and main-only commit**

After independent review, the main orchestrator commits only Task 3 files with:

```text
feat(frontend): build the full-screen RAG lab room
```

---

### Task 4: Verify the browser contract and close the implementation record

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-full-screen-ai-lab-world-design.md`
- Modify: `docs/decisions/0005-public-ai-lab-world.md`
- Modify: `WORKBOARD.md`
- Create only if material evidence exceeds WORKBOARD scope: `docs/worklogs/2026-09-04-full-screen-ai-lab-world-verification.md`

**Interfaces:**
- Consumes: completed Task 1–3 implementation and test evidence
- Produces: approved/implemented design status, exact verification record, and next task ordering

- [ ] **Step 1: Start or reuse the local non-Docker frontend**

Use the existing host Next.js process if it serves the current source. Otherwise restart only the host frontend with `pnpm run dev`; do not recreate Docker services for this UI-only task.

- [ ] **Step 2: Verify public routes and interaction in a real browser**

Check `/` and `/labs` at:

- `1440×900`
- `1024×768`
- `768×1024`
- `390×844`
- `320×568`
- `844×390`

At minimum record:

- both routes render the same RAG room without authentication or redirect
- every viewport records `document.documentElement.scrollWidth <= document.documentElement.clientWidth`, and a deliberately short viewport confirms `scrollHeight > clientHeight` with vertical scrolling still possible
- desktop/tablet records trigger and dialog `getBoundingClientRect()` values, verifies every dialog edge is within `[0, innerWidth/innerHeight]`, and verifies the placement tail points toward a point inside the trigger rectangle
- mobile records dialog, close, and CTA rectangles; all edges must stay inside the viewport and the computed dialog bottom padding must include `env(safe-area-inset-bottom)` fallback spacing
- initial close-button focus, Tab cycle, Escape, and trigger focus restoration
- while the dialog is open, attempt to activate a background navigation link and verify location and focus do not change; after close, verify `window.scrollY` equals the value captured before open
- `/labs/rag` CTA navigation
- at `200%` browser zoom, repeat horizontal overflow and dialog/control rectangle measurements
- launch a separate headless Chromium verification session with `--force-prefers-reduced-motion=reduce` and use the DevTools protocol to assert `matchMedia("(prefers-reduced-motion: reduce)").matches === true` plus computed `animation-name: none` for the character visual and status light

If the reduced-motion session cannot be launched or any numeric measurement cannot be collected, Task 4 remains incomplete; record the blocker but do not mark the design implemented.

- [ ] **Step 3: Run final automated verification fresh**

From `frontend/` run sequentially:

```text
pnpm test -- --run
pnpm run typecheck
pnpm run lint
pnpm run build
```

From repository root run:

```text
backend/.venv/Scripts/python.exe scripts/verify_project_agent_contracts.py validate --root .
git diff --check
```

- [ ] **Step 4: Obtain broad independent review**

The reviewer checks the entire implementation diff against all 15 spec acceptance criteria, verifies no backend/DB/catalog content/schema changes, and reports Critical/Important/Minor findings with file and line evidence. Any Critical or Important finding is fixed by an implementation agent and independently re-reviewed before completion.

- [ ] **Step 5: Update implementation records**

Only after fresh verification:

- mark the design `구현됨` and ADR `승인됨`
- update `WORKBOARD.md` current state, exact test counts, browser results, limitations, blockers, and next tasks
- keep recent completed work at five items
- do not claim reduced-motion browser validation if it was not actually emulated

- [ ] **Step 6: Main-only final commit**

The main orchestrator stages only in-scope documentation and review-driven fixes, verifies the staged diff, and commits with:

```text
docs: record full-screen lab world verification
```

Do not push, merge, publish, or delete unrelated temporary paths without separate user authorization.
