# RAG Lab Agent Workroom Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the public RAG chief enter `/labs/rag` directly and turn that page into an accessible workroom containing the chief and six current RAG worker characters.

**Architecture:** Keep public Lab discovery in the existing catalog and add a separate validated RAG worker registry for worker-specific copy. Extract the existing dialog mechanics into a generic character component, retain `AgentCharacter` as the Lab-manager adapter, and compose the RAG page from semantic workstations backed by the registry.

**Tech Stack:** Next.js 16, React 19, TypeScript 5.9, CSS Modules, Vitest, Testing Library

**Spec:** `docs/superpowers/specs/2026-09-04-rag-lab-agent-workroom-design.md`

## Global Constraints

- Work only on `main` because the user explicitly required main-only development.
- Display only the six currently implemented RAG responsibilities; do not add Generation or Reranker placeholders.
- Keep the public catalog, backend API, database, model runtime and authentication boundaries unchanged.
- Store worker copy in a validated registry, not in the page component.
- Preserve the existing modal-dialog accessibility, viewport placement, mobile bottom sheet and reduced-motion behavior.

---

### Task 1: Direct RAG chief entry

**Files:**
- Modify: `frontend/src/features/public-labs/LabEntrancePage.tsx`
- Modify: `frontend/src/app/page.test.tsx`

**Interfaces:**
- Consumes: `PublicLab.href`, `PublicLabManager.ctaLabel`, `routes.labs`
- Produces: RAG manager dialog action to `/labs/rag` while the independent overview link remains `/labs`

- [x] **Step 1: Write the failing route test**

Change the home route interaction assertion to require `RAG 연구실 들어가기` with literal href
`/labs/rag`, while separately asserting `연구실 전체 보기` has href `/labs`.

- [x] **Step 2: Run the focused test and verify RED**

Run: `pnpm test --run src/app/page.test.tsx`
Expected: FAIL because the character currently renders `AI Labs 살펴보기` to `/labs`.

- [x] **Step 3: Remove the entrance dialog override**

Render `<AgentCharacter lab={lab} variant="roaming" />` so the validated catalog supplies the character
CTA. Keep the surrounding `연구실 전체 보기` link unchanged.

- [x] **Step 4: Run the focused test and verify GREEN**

Run: `pnpm test --run src/app/page.test.tsx`
Expected: PASS.

### Task 2: Validated RAG worker registry

**Files:**
- Create: `frontend/src/content/rag-lab-agents.json`
- Create: `frontend/src/features/public-labs/rag-lab-agents.ts`
- Create: `frontend/src/features/public-labs/rag-lab-agents.test.ts`

**Interfaces:**
- Produces: `RagLabAgent`, `parseRagLabAgents(input)`, `listRagLabAgents()`
- `RagLabAgent` fields: `slug`, `name`, `role`, `statusLabel`, `eyebrow`, `intro`, `currentWork`, `inputOutput`, `handoff`

- [x] **Step 1: Write registry contract tests**

Assert six literal unique slugs in pipeline order, exact current-role names, required nonblank strings,
duplicate rejection and extra-key rejection. Assert the list excludes names containing `생성`, `LLM`, or
`리랭커`.

- [x] **Step 2: Run the registry test and verify RED**

Run: `pnpm test --run src/features/public-labs/rag-lab-agents.test.ts`
Expected: FAIL because the registry module does not exist.

- [x] **Step 3: Implement the strict parser and content manifest**

Implement exact-key object validation, kebab-case slug validation, duplicate detection and defensive copies.
Populate the six approved workers with present-tense descriptions tied to current implemented behavior.

- [x] **Step 4: Run the registry test and verify GREEN**

Run: `pnpm test --run src/features/public-labs/rag-lab-agents.test.ts`
Expected: PASS.

### Task 3: Reusable worker character dialog

**Files:**
- Create: `frontend/src/features/public-labs/InteractiveAgentCharacter.tsx`
- Modify: `frontend/src/features/public-labs/AgentCharacter.tsx`
- Create: `frontend/src/features/public-labs/RagWorkerCharacter.tsx`
- Create: `frontend/src/features/public-labs/RagWorkerCharacter.test.tsx`
- Modify: `frontend/src/features/public-labs/AgentCharacter.test.tsx`

**Interfaces:**
- Produces: `InteractiveAgentProfile` and `InteractiveAgentCharacter({ profile, variant, action? })`
- `AgentCharacter` maps a `PublicLab` manager to the generic profile without changing its public behavior.
- `RagWorkerCharacter({ agent })` maps registry fields and renders no fabricated detail CTA.

- [x] **Step 1: Write the failing worker interaction tests**

Render a real registry worker, click its unique `에게 말 걸기` button, and assert its dialog exposes the
literal current-work, input/output and handoff descriptions. Verify close-button focus, Escape close and
trigger focus restoration. Verify no link is rendered when the worker has no approved destination.

- [x] **Step 2: Run focused character tests and verify RED**

Run: `pnpm test --run src/features/public-labs/RagWorkerCharacter.test.tsx`
Expected: FAIL because the worker component does not exist.

- [x] **Step 3: Extract shared mechanics and add the worker adapter**

Move portal, focus trap, scroll lock and placement behavior unchanged into the generic component. Map Lab
manager invitation into the generic body and keep optional actions. Map worker fields into labeled paragraphs.

- [x] **Step 4: Run all character tests and verify GREEN**

Run: `pnpm test --run src/features/public-labs/AgentCharacter.test.tsx src/features/public-labs/RagWorkerCharacter.test.tsx`
Expected: PASS.

### Task 4: RAG workroom composition and responsive styling

**Files:**
- Modify: `frontend/src/features/public-labs/RagLabOverviewPage.tsx`
- Modify: `frontend/src/features/public-labs/RagLabOverviewPage.test.tsx`
- Modify: `frontend/src/app/(public)/labs/rag/page.test.tsx`
- Modify: `frontend/src/features/public-labs/PublicLabScene.module.css`

**Interfaces:**
- Consumes: `listPublicLabs()` for the chief and `listRagLabAgents()` for worker stations
- Produces: semantic `RAG 작업 파이프라인` region with one chief station and six ordered worker stations

- [x] **Step 1: Write failing workroom acceptance tests**

Assert the chief and all six worker trigger names, the pipeline region, login search CTA, and absence of
Generation/Reranker worker triggers. Click at least two nonadjacent workers and verify their different dialog
descriptions.

- [x] **Step 2: Run focused page tests and verify RED**

Run: `pnpm test --run src/features/public-labs/RagLabOverviewPage.test.tsx src/app/(public)/labs/rag/page.test.tsx`
Expected: FAIL because the static overview has no worker triggers or workroom region.

- [x] **Step 3: Build the semantic workroom**

Keep the public navigation, title and authenticated search CTA. Add a chief command station and map the
validated workers into ordered sections. Use decorative, aria-hidden workstation visuals and CSS grid flow.

- [x] **Step 4: Add responsive and reduced-motion styles**

Use existing color and breakpoint tokens: wide pipeline grid, two columns below `64rem`, one column below
`48rem`, and animation removal within the existing reduced-motion rule.

- [x] **Step 5: Run focused tests and verify GREEN**

Run: `pnpm test --run src/features/public-labs/RagLabOverviewPage.test.tsx src/app/(public)/labs/rag/page.test.tsx`
Expected: PASS.

### Task 5: Documentation, regression verification and independent review

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-full-screen-ai-lab-world-design.md`
- Modify: `docs/superpowers/specs/2026-09-02-public-ai-lab-rag-service-design.md`
- Modify: `WORKBOARD.md`
- Create: `docs/worklogs/2026-09-04-rag-lab-agent-workroom-verification.md`

**Interfaces:**
- Produces: canonical docs aligned with the new direct-entry and internal-worker contract

- [x] **Step 1: Update superseded public flow text**

Record that `/` has both the `/labs` overview link and per-manager direct Lab CTA. Link the RAG workroom
spec and ADR from the broader public RAG design.

- [x] **Step 2: Run full automated frontend verification**

Run from `frontend/`: `pnpm test --run`, `pnpm typecheck`, `pnpm lint`, `pnpm build`.
Expected: every command exits 0 with no test failures or lint warnings.

- [x] **Step 3: Run repository contract and diff checks**

Run: `backend/.venv/Scripts/python.exe scripts/verify_project_agent_contracts.py validate --root .`
Run: `git diff --check`
Expected: both exit 0.

- [x] **Step 4: Verify the actual browser flow**

At desktop and mobile widths, open `/`, verify the RAG chief CTA reaches `/labs/rag`, select the first and
last workers, and verify dialog containment, keyboard close and no horizontal overflow.

- [x] **Step 5: Request an independent read-only review**

Provide the reviewer the approved spec, changed files, test evidence and known unrelated untracked/ACL
paths. Resolve Critical and Important findings and rerun affected checks.

- [x] **Step 6: Finalize workboard and commit only scoped files**

Keep no more than five recent-completion entries, record exact verification evidence, preserve unrelated
`references/` and inaccessible pytest paths, and do not push without a separate user request.
