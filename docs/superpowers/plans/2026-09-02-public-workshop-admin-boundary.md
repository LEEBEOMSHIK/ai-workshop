# Public, Workshop, and Administration Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the login-free character-based public AI Lab, move private user features to `/workshop/*`, and isolate RAG configuration editing under owner-only `/admin/*` routes.

**Architecture:** Keep the current RAG search data contracts and implementation unchanged while enforcing owner permission on configuration and evaluation mutation endpoints. Introduce one typed frontend route contract, migrate Next.js route ownership without duplicating business pages, and build a public presentation layer from a validated content manifest so character copy is not embedded in UI components. This plan implements only phase 1 of the approved spec; dynamic RAG domains, public releases, public search, LLM generation, uploads, feedback, and training remain later plans.

**Tech Stack:** Next.js 16.3.4 App Router, React 19.2.8, TypeScript 5.9.3, CSS Modules, Vitest 4.1.11, Testing Library, FastAPI, Pytest

**Spec:** `docs/superpowers/specs/2026-09-02-public-ai-lab-rag-service-design.md`

## Global Constraints

- Work directly on `main`; do not create a Git worktree or feature branch.
- Public routes `/`, `/labs`, and `/labs/rag` never call authentication guards.
- Private documents and RAG search remain behind `/workshop/*`; RAG configuration editing is owner-only under `/admin/*`.
- Preserve former `/app/*`, `/workspaces`, and `/rag/*` URLs as permanent redirects to the new canonical locations.
- Do not add a public search endpoint, public release persistence, domain persistence, LLM generation, feedback persistence, or model training in this plan.
- Do not call a completed public feature a `demo`; use the feature name or an honest `연구 중` status.
- Put route strings in one typed route module and public presentation copy in one validated manifest boundary instead of scattering literals through components.
- Add no dependency and do not change PostgreSQL, Elasticsearch, Redis, Celery, or Docker configuration.
- Respect `prefers-reduced-motion`, keyboard focus, dialog semantics, and the existing Korean interface language.
- Commit only files named by the current task; do not touch `backend/.pytest-nextjs-final-contract/` or `references/`.

---

### Task 1: Canonical frontend route contract and legacy redirects

**Files:**
- Create: `frontend/src/shared/routing/routes.ts`
- Create: `frontend/src/shared/routing/routes.test.ts`
- Modify: `frontend/src/shared/routing/legacy-redirects.ts`
- Modify: `frontend/src/shared/routing/legacy-redirects.test.ts`
- Modify: `frontend/src/shared/auth/access.ts`
- Modify: `frontend/src/shared/auth/access.test.ts`
- Modify: `frontend/src/proxy.ts`
- Create: `frontend/src/proxy.test.ts`

**Interfaces:**
- Produces: `routes`, `workspaceDocumentPath(workspaceId)`, `ragSourcePath(assetVersionId)`, and `loginPath(nextPath)`.
- Consumes: no application module; this is the canonical URL dependency for all later tasks.

- [ ] **Step 1: Write failing route-contract tests**

```ts
import {
  loginPath,
  ragSourcePath,
  routes,
  workspaceDocumentPath,
} from "./routes";

describe("canonical frontend routes", () => {
  it("separates public, workshop, and administration URLs", () => {
    expect(routes).toMatchObject({
      home: "/",
      labs: "/labs",
      ragLab: "/labs/rag",
      workshopHome: "/workshop/workspaces",
      workshopRagSearch: "/workshop/rag/search",
      adminRagConfigurations: "/admin/rag/configurations",
      adminRagModels: "/admin/rag/models",
    });
  });

  it("encodes dynamic path segments and login return paths", () => {
    expect(workspaceDocumentPath("space/id")).toBe(
      "/workshop/workspaces/space%2Fid/documents",
    );
    expect(ragSourcePath("asset/id")).toBe(
      "/workshop/rag/sources/asset%2Fid",
    );
    expect(loginPath(routes.workshopRagSearch)).toBe(
      "/login?next=%2Fworkshop%2Frag%2Fsearch",
    );
  });
});
```

In `proxy.test.ts`, lock the protected matcher to the new boundaries:

```ts
import { config } from "./proxy";

describe("route proxy boundary", () => {
  it("captures return paths only for protected areas", () => {
    expect(config.matcher).toEqual(["/workshop/:path*", "/admin/:path*"]);
  });
});
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `pnpm test --run src/shared/routing/routes.test.ts src/shared/routing/legacy-redirects.test.ts src/shared/auth/access.test.ts src/proxy.test.ts`

Expected: FAIL because `routes.ts` does not exist and old expectations still point at `/app/*`.

- [ ] **Step 3: Add the typed route contract**

```ts
export const routes = {
  home: "/",
  labs: "/labs",
  ragLab: "/labs/rag",
  login: "/login",
  setup: "/setup",
  workshopHome: "/workshop/workspaces",
  workshopRagSearch: "/workshop/rag/search",
  adminRagConfigurations: "/admin/rag/configurations",
  adminRagModels: "/admin/rag/models",
} as const;

export function workspaceDocumentPath(workspaceId: string): string {
  return `/workshop/workspaces/${encodeURIComponent(workspaceId)}/documents`;
}

export function ragSourcePath(assetVersionId: string): string {
  return `/workshop/rag/sources/${encodeURIComponent(assetVersionId)}`;
}

export function loginPath(nextPath: string): string {
  return `${routes.login}?next=${encodeURIComponent(nextPath)}`;
}
```

- [ ] **Step 4: Replace legacy destinations and access fallbacks**

Make `legacyRedirects` contain exact permanent mappings for both the former SPA paths and the just-replaced `/app/*` paths:

```ts
export const legacyRedirects: LegacyRedirect[] = [
  { source: "/app", destination: routes.workshopHome, permanent: true },
  { source: "/app/workspaces", destination: routes.workshopHome, permanent: true },
  {
    source: "/app/workspaces/:workspaceId/documents",
    destination: "/workshop/workspaces/:workspaceId/documents",
    permanent: true,
  },
  { source: "/app/rag/search", destination: routes.workshopRagSearch, permanent: true },
  {
    source: "/app/rag/configurations",
    destination: routes.adminRagConfigurations,
    permanent: true,
  },
  {
    source: "/app/rag/sources/:assetVersionId",
    destination: "/workshop/rag/sources/:assetVersionId",
    permanent: true,
  },
  { source: "/workspaces", destination: routes.workshopHome, permanent: true },
  {
    source: "/workspaces/:workspaceId/documents",
    destination: "/workshop/workspaces/:workspaceId/documents",
    permanent: true,
  },
  { source: "/rag/search", destination: routes.workshopRagSearch, permanent: true },
  {
    source: "/rag/configurations",
    destination: routes.adminRagConfigurations,
    permanent: true,
  },
  {
    source: "/rag/sources/:assetVersionId",
    destination: "/workshop/rag/sources/:assetVersionId",
    permanent: true,
  },
  { source: "/rag/models", destination: routes.adminRagModels, permanent: true },
];
```

Change `safeReturnPath` fallback to `routes.workshopHome`. Update tests to use `/workshop/rag/search` and expect setup/login redirects with the encoded workshop path. Change the proxy matcher to:

```ts
export const config = {
  matcher: ["/workshop/:path*", "/admin/:path*"],
};
```

- [ ] **Step 5: Run focused tests**

Run: `pnpm test --run src/shared/routing/routes.test.ts src/shared/routing/legacy-redirects.test.ts src/shared/auth/access.test.ts src/proxy.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit the route contract**

```bash
git add frontend/src/shared/routing/routes.ts frontend/src/shared/routing/routes.test.ts frontend/src/shared/routing/legacy-redirects.ts frontend/src/shared/routing/legacy-redirects.test.ts frontend/src/shared/auth/access.ts frontend/src/shared/auth/access.test.ts frontend/src/proxy.ts frontend/src/proxy.test.ts
git commit -m "refactor: define public workshop admin routes"
```

### Task 2: Canonical private workshop routes and navigation

**Files:**
- Create: `frontend/src/app/(workspace)/workshop/layout.tsx`
- Create: `frontend/src/app/(workspace)/workshop/layout.test.tsx`
- Create: `frontend/src/app/(workspace)/workshop/workspaces/page.tsx`
- Create: `frontend/src/app/(workspace)/workshop/workspaces/[workspaceId]/documents/page.tsx`
- Create: `frontend/src/app/(workspace)/workshop/rag/search/page.tsx`
- Create: `frontend/src/app/(workspace)/workshop/rag/sources/[assetVersionId]/page.tsx`
- Delete: the corresponding files under `frontend/src/app/(workspace)/app/`, excluding the configuration page handled in Task 3
- Modify: `frontend/src/features/navigation/WorkspaceNavigation.tsx`
- Create: `frontend/src/features/navigation/WorkspaceNavigation.test.tsx`
- Modify: `frontend/src/features/workspaces/WorkspacePage.tsx`
- Modify: `frontend/src/features/workspaces/WorkspacePage.test.tsx`
- Modify: `frontend/src/features/rag/search/source-route-query.ts`
- Modify: `frontend/src/features/rag/search/source-route-query.test.ts`

**Interfaces:**
- Consumes: `routes`, `workspaceDocumentPath`, and `ragSourcePath` from Task 1.
- Produces: canonical protected pages at `/workshop/workspaces`, `/workshop/rag/search`, and `/workshop/rag/sources/{assetVersionId}`.

- [ ] **Step 1: Write failing navigation and layout expectations**

```tsx
render(<WorkspaceNavigation user={owner} />);
expect(screen.getByRole("navigation", { name: "비공개 작업소" })).toBeVisible();
expect(screen.getByRole("link", { name: "지식 공간" })).toHaveAttribute(
  "href",
  routes.workshopHome,
);
expect(screen.getByRole("link", { name: "RAG 검색" })).toHaveAttribute(
  "href",
  routes.workshopRagSearch,
);
expect(screen.queryByRole("link", { name: "RAG 구성" })).not.toBeInTheDocument();
expect(screen.getByRole("link", { name: "AI Lab" })).toHaveAttribute(
  "href",
  routes.labs,
);
```

In the relocated layout test, provide `x-ai-workshop-return-to: /workshop/rag/search?query=alpha` and expect `requireWorkspaceUser` to receive that exact value.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pnpm test --run src/features/navigation/WorkspaceNavigation.test.tsx "src/app/(workspace)/workshop/layout.test.tsx" src/features/workspaces/WorkspacePage.test.tsx src/features/rag/search/source-route-query.test.ts`

Expected: FAIL because the new route tree and navigation contract do not exist.

- [ ] **Step 3: Relocate the workspace layout and page adapters**

Create the `workshop` route tree using the existing page adapter bodies. Update imports for the new directory depth and replace guards with canonical route values. The search route must begin its server loader with:

```ts
await requireWorkspaceUser(routes.workshopRagSearch);
```

The layout fallback must be:

```ts
const returnTo =
  requestHeaders.get("x-ai-workshop-return-to") ?? routes.workshopHome;
```

Delete the old page files under `(workspace)/app` after their equivalents exist under `(workspace)/workshop`. Do not copy the configurations route in this task.

- [ ] **Step 4: Update private navigation and dynamic link builders**

Implement the navigation shape:

```tsx
<header className="area-navigation">
  <Link className="area-brand" href={routes.workshopHome}>AI Workshop</Link>
  <nav aria-label="비공개 작업소">
    <Link href={routes.workshopHome}>지식 공간</Link>
    <Link href={routes.workshopRagSearch}>RAG 검색</Link>
    <Link href={routes.labs}>AI Lab</Link>
    {user.role === "owner" ? <Link href={routes.adminRagModels}>관리</Link> : null}
  </nav>
  <span>{user.display_name}</span>
</header>
```

Use `workspaceDocumentPath(workspace.id)` in `WorkspacePage`. Use `ragSourcePath(assetVersionId)` as the base path in `buildSourceRoute`; keep the existing query serialization and the rule that private source text never enters the URL.

- [ ] **Step 5: Run focused tests**

Run: `pnpm test --run src/features/navigation/WorkspaceNavigation.test.tsx "src/app/(workspace)/workshop/layout.test.tsx" src/features/workspaces/WorkspacePage.test.tsx src/features/rag/search/source-route-query.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit the workshop migration**

```bash
git add "frontend/src/app/(workspace)" frontend/src/features/navigation/WorkspaceNavigation.tsx frontend/src/features/navigation/WorkspaceNavigation.test.tsx frontend/src/features/workspaces/WorkspacePage.tsx frontend/src/features/workspaces/WorkspacePage.test.tsx frontend/src/features/rag/search/source-route-query.ts frontend/src/features/rag/search/source-route-query.test.ts
git commit -m "refactor: move private features to workshop routes"
```

### Task 3: Owner-only RAG configuration administration

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/configurations/api.py`
- Modify: `backend/src/ai_workshop/labs/rag/evaluation/api.py`
- Modify: `backend/tests/integration/labs/rag/configurations/test_configuration_api.py`
- Modify: `backend/tests/integration/labs/rag/evaluation/test_evaluation_api.py`
- Create: `frontend/src/app/(administration)/admin/layout.test.tsx`
- Modify: `frontend/src/app/(administration)/admin/layout.tsx`
- Create: `frontend/src/app/(administration)/admin/rag/configurations/page.tsx`
- Create: `frontend/src/app/(administration)/admin/rag/configurations/page.test.tsx`
- Delete: `frontend/src/app/(workspace)/app/rag/configurations/page.tsx`
- Modify: `frontend/src/features/navigation/AdminNavigation.tsx`
- Create: `frontend/src/features/navigation/AdminNavigation.test.tsx`
- Modify: `frontend/src/shared/auth/server-session.ts`
- Modify: `frontend/src/shared/auth/server-session.test.ts`

**Interfaces:**
- Consumes: `routes.adminRagConfigurations`, `routes.adminRagModels`, and `routes.workshopHome` from Task 1.
- Produces: owner-only configuration and evaluation mutations plus the configuration studio at `/admin/rag/configurations` with exact return-path preservation.

- [ ] **Step 1: Write failing backend owner-boundary tests**

Add `MEMBER_ID = UUID("10000000-0000-0000-0000-000000000002")` and a `member()` fixture beside the existing `owner()` fixture in both API test files:

```py
def member() -> User:
    return User(
        id=MEMBER_ID,
        display_name="Member",
        email="member@example.test",
        normalized_email="member@example.test",
        password_hash="hash",
        role=UserRole.MEMBER,
    )
```

Create a client whose `get_current_user` override returns `member`. Assert that `POST /api/v1/rag/configurations`, `POST /api/v1/rag/configurations/{id}/default`, `POST /api/v1/rag/evaluation-policies`, and `POST /api/v1/rag/evaluation-runs` each return `403` with error code `owner_required`. Keep configuration, model, profile, and evaluation list reads authenticated so the existing private search and read-only summaries keep working.

- [ ] **Step 2: Run backend permission tests and verify failure**

Run from `backend/`:

```bash
uv run pytest tests/integration/labs/rag/configurations/test_configuration_api.py tests/integration/labs/rag/evaluation/test_evaluation_api.py -q
```

Expected: the new member mutation assertions FAIL with 201, 202, or the service-level response instead of 403.

- [ ] **Step 3: Enforce owner permission on mutation endpoints**

Import `require_owner` in both API modules. Change only the actor dependencies on mutation endpoints:

```py
user: Annotated[User, Depends(require_owner)]
```

Apply it to `create_configuration`, `promote_configuration_default`, `create_evaluation_policy`, and `start_evaluation_run`. Keep `list_configurations`, `configuration_detail`, `list_evaluation_runs`, and `evaluation_run_detail` on `get_current_user`.

- [ ] **Step 4: Run backend permission tests**

Run: `uv run pytest tests/integration/labs/rag/configurations/test_configuration_api.py tests/integration/labs/rag/evaluation/test_evaluation_api.py -q`

Expected: PASS, including the existing owner behavior.

- [ ] **Step 5: Write failing frontend owner-boundary tests**

The configuration route test must mock the server loader and assert:

```ts
expect(requireOwner).toHaveBeenCalledWith(routes.adminRagConfigurations);
expect(serverApiRequest).toHaveBeenCalledWith(
  "/api/v1/rag/configurations",
  {},
  "ai_workshop_session=token",
);
```

The admin layout test must provide the header `/admin/rag/configurations?tab=evaluation` and expect the same exact value to reach `requireOwner`. The navigation test must assert links named `RAG 구성`, `RAG 모델`, and `비공개 작업소`.

Update the member-denial expectation in `server-session.test.ts` so `requireOwner` redirects to:

```text
/workshop/workspaces?error=owner_required
```

- [ ] **Step 6: Run focused frontend tests and verify failure**

Run: `pnpm test --run "src/app/(administration)/admin/layout.test.tsx" "src/app/(administration)/admin/rag/configurations/page.test.tsx" src/features/navigation/AdminNavigation.test.tsx src/shared/auth/server-session.test.ts`

Expected: FAIL because the configuration route is still workspace-owned and the admin layout does not preserve the actual path.

- [ ] **Step 7: Move the configuration page adapter behind `requireOwner`**

Retain the existing `Promise.all` calls and `ConfigurationStudioData` construction, but change the route guard to:

```ts
await requireOwner(routes.adminRagConfigurations);
```

Create it under `(administration)/admin/rag/configurations/page.tsx` and delete the old workspace page.

- [ ] **Step 8: Preserve the requested admin URL and update navigation**

Use `headers()` in `AdminLayout` exactly as in the workshop layout:

```ts
const requestHeaders = await headers();
const returnTo =
  requestHeaders.get("x-ai-workshop-return-to") ?? routes.adminRagModels;
const session = await captureServerRoute(() => requireOwner(returnTo));
```

Render these admin links:

```tsx
<nav aria-label="관리자 운영">
  <Link href={routes.adminRagConfigurations}>RAG 구성</Link>
  <Link href={routes.adminRagModels}>RAG 모델</Link>
  <Link href={routes.workshopHome}>비공개 작업소</Link>
</nav>
```

Change `requireOwner` member denial to `${routes.workshopHome}?error=owner_required`.

- [ ] **Step 9: Run focused tests**

Run: `pnpm test --run "src/app/(administration)/admin/layout.test.tsx" "src/app/(administration)/admin/rag/configurations/page.test.tsx" src/features/navigation/AdminNavigation.test.tsx src/shared/auth/server-session.test.ts`

Expected: PASS.

- [ ] **Step 10: Commit the admin boundary**

```bash
git add backend/src/ai_workshop/labs/rag/configurations/api.py backend/src/ai_workshop/labs/rag/evaluation/api.py backend/tests/integration/labs/rag/configurations/test_configuration_api.py backend/tests/integration/labs/rag/evaluation/test_evaluation_api.py "frontend/src/app/(administration)" "frontend/src/app/(workspace)/app/rag/configurations/page.tsx" frontend/src/features/navigation/AdminNavigation.tsx frontend/src/features/navigation/AdminNavigation.test.tsx frontend/src/shared/auth/server-session.ts frontend/src/shared/auth/server-session.test.ts
git commit -m "feat: isolate RAG configuration administration"
```

### Task 4: Validated public Lab presentation catalog

**Files:**
- Create: `frontend/src/content/public-labs.json`
- Create: `frontend/src/features/public-labs/catalog.ts`
- Create: `frontend/src/features/public-labs/catalog.test.ts`
- Create: `frontend/src/features/navigation/PublicNavigation.tsx`
- Create: `frontend/src/features/navigation/PublicNavigation.module.css`
- Create: `frontend/src/features/navigation/PublicNavigation.test.tsx`

**Interfaces:**
- Produces: `PublicLab`, `PublicLabManager`, `parsePublicLabCatalog(input)`, and `listPublicLabs()`.
- Consumes: `routes` from Task 1; the presentation catalog is the replaceable boundary for the phase-2 public release API.

- [ ] **Step 1: Write failing catalog validation tests**

```ts
import { listPublicLabs, parsePublicLabCatalog } from "./catalog";

describe("public Lab catalog", () => {
  it("loads only the current RAG Lab without speculative empty Labs", () => {
    expect(listPublicLabs()).toEqual([
      expect.objectContaining({
        slug: "rag",
        href: "/labs/rag",
        manager: expect.objectContaining({ role: "RAG 기술 총괄" }),
      }),
    ]);
  });

  it("rejects duplicate slugs and non-local links", () => {
    expect(() => parsePublicLabCatalog({ labs: [validLab, validLab] })).toThrow(
      "public_lab_slug_duplicate",
    );
    expect(() =>
      parsePublicLabCatalog({
        labs: [{ ...validLab, href: "https://example.com" }],
      }),
    ).toThrow("public_lab_href_invalid");
  });
});
```

Define `validLab` in the test with every required string field and a nested manager object. Add a navigation test that expects `AI Workshop`, `AI Labs`, and `비공개 작업소 입장` links to `/`, `/labs`, and `/login?next=%2Fworkshop%2Fworkspaces`.

```ts
const validLab = {
  slug: "rag",
  name: "RAG 기술 연구실",
  eyebrow: "RETRIEVAL · EVIDENCE · GENERATION",
  description: "문서를 찾고 원문 근거와 함께 답하는 AI 검색 기술을 연구합니다.",
  status: "researching",
  statusLabel: "연구 중",
  href: "/labs/rag",
  manager: {
    name: "RAG 총괄",
    role: "RAG 기술 총괄",
    intro: "나는 문서 검색과 근거 기반 답변 기술을 관리하는 RAG 총괄 에이전트야.",
    invitation: "내가 관리하는 검색 기술과 해결 과정을 보러 갈래?",
    ctaLabel: "RAG 연구실 들어가기",
  },
};
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pnpm test --run src/features/public-labs/catalog.test.ts src/features/navigation/PublicNavigation.test.tsx`

Expected: FAIL because the catalog and public navigation do not exist.

- [ ] **Step 3: Add the first versioned presentation manifest**

```json
{
  "labs": [
    {
      "slug": "rag",
      "name": "RAG 기술 연구실",
      "eyebrow": "RETRIEVAL · EVIDENCE · GENERATION",
      "description": "문서를 찾고 원문 근거와 함께 답하는 AI 검색 기술을 연구합니다.",
      "status": "researching",
      "statusLabel": "연구 중",
      "href": "/labs/rag",
      "manager": {
        "name": "RAG 총괄",
        "role": "RAG 기술 총괄",
        "intro": "나는 문서 검색과 근거 기반 답변 기술을 관리하는 RAG 총괄 에이전트야.",
        "invitation": "내가 관리하는 검색 기술과 해결 과정을 보러 갈래?",
        "ctaLabel": "RAG 연구실 들어가기"
      }
    }
  ]
}
```

- [ ] **Step 4: Parse the manifest through a strict boundary**

Implement these exact public types:

```ts
export type PublicLabStatus = "researching" | "service";

export interface PublicLabManager {
  name: string;
  role: string;
  intro: string;
  invitation: string;
  ctaLabel: string;
}

export interface PublicLab {
  slug: string;
  name: string;
  eyebrow: string;
  description: string;
  status: PublicLabStatus;
  statusLabel: string;
  href: string;
  manager: PublicLabManager;
}
```

`parsePublicLabCatalog(input: unknown)` must reject a non-object root, a non-array `labs`, blank required strings, slugs outside `/^[a-z0-9]+(?:-[a-z0-9]+)*$/u`, duplicate slugs, non-local or mismatched `href`, and a status outside the two-value union. `listPublicLabs()` returns a new readonly array parsed from the JSON import so callers cannot mutate shared state.

- [ ] **Step 5: Implement public navigation with the route contract**

```tsx
<header className={styles.navigation}>
  <Link className={styles.brand} href={routes.home}>AI Workshop</Link>
  <nav className={styles.links} aria-label="공개 전시실">
    <Link href={routes.labs}>AI Labs</Link>
    <Link href={loginPath(routes.workshopHome)}>비공개 작업소 입장</Link>
  </nav>
</header>
```

Use `PublicNavigation.module.css` with `.navigation`, `.brand`, and `.links` classes. Keep the header responsive with wrapping links and visible `:focus-visible` outlines; do not add these styles to unrelated RAG search selectors.

- [ ] **Step 6: Run focused tests**

Run: `pnpm test --run src/features/public-labs/catalog.test.ts src/features/navigation/PublicNavigation.test.tsx`

Expected: PASS.

- [ ] **Step 7: Commit the public catalog boundary**

```bash
git add frontend/src/content/public-labs.json frontend/src/features/public-labs frontend/src/features/navigation/PublicNavigation.tsx frontend/src/features/navigation/PublicNavigation.module.css frontend/src/features/navigation/PublicNavigation.test.tsx
git commit -m "feat: add validated public Lab catalog"
```

### Task 5: Character-based public landing

**Files:**
- Create: `frontend/src/features/public-labs/AgentCharacter.tsx`
- Create: `frontend/src/features/public-labs/AgentCharacter.test.tsx`
- Create: `frontend/src/features/public-labs/PublicLabScene.module.css`
- Modify: `frontend/src/features/home/HomePage.tsx`
- Modify: `frontend/src/features/home/HomePage.test.tsx`

**Interfaces:**
- Consumes: `PublicLab`, `listPublicLabs()`, `routes`, and `PublicNavigation`.
- Produces: accessible moving manager characters and a login-free public landing at `/`.

- [ ] **Step 1: Write failing character interaction tests**

```tsx
const user = userEvent.setup();
render(<HomePage />);

expect(screen.getByRole("heading", { name: "AI 기술 관리자들이 일하는 작업소" })).toBeVisible();
expect(screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" })).toBeVisible();
expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

await user.click(screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }));

const dialog = screen.getByRole("dialog", { name: "RAG 총괄 소개" });
expect(dialog).toHaveTextContent("문서 검색과 근거 기반 답변 기술");
expect(within(dialog).getByRole("link", { name: "RAG 연구실 들어가기" })).toHaveAttribute(
  "href",
  routes.ragLab,
);

await user.keyboard("{Escape}");
expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
```

Add an `AgentCharacter` test for close-button focus return. The trigger must regain focus after the dialog closes.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pnpm test --run src/features/public-labs/AgentCharacter.test.tsx src/features/home/HomePage.test.tsx`

Expected: FAIL because the character scene and dialog do not exist.

- [ ] **Step 3: Implement the accessible character component**

`AgentCharacter` is a client component with this contract:

```ts
interface AgentCharacterProps {
  lab: PublicLab;
  variant: "roaming" | "working";
}
```

Render the character as a semantic button. Use CSS shapes for the avatar body and tools so no placeholder image asset is introduced. The dialog must use `role="dialog"`, `aria-modal="true"`, a labelled heading, an explicit close button, Escape handling, initial close-button focus, and focus return to the trigger. Prevent background click from being the only close mechanism.

- [ ] **Step 4: Replace the static card home with the public scene**

`HomePage` must load `listPublicLabs()` and render:

```tsx
<main className={styles.page}>
  <PublicNavigation />
  <section className={styles.hero} aria-labelledby="public-workshop-title">
    <p className={styles.eyebrow}>LEE BEOMSHIK&apos;S AI WORKSHOP</p>
    <h1 id="public-workshop-title">AI 기술 관리자들이 일하는 작업소</h1>
    <p>공부하고 실험한 AI 기술을 실제 기능과 해결 과정으로 연결합니다.</p>
    <Link href={routes.labs}>AI Lab 둘러보기</Link>
  </section>
  <section className={styles.scene} aria-label="기술 관리자 캐릭터">
    {labs.map((lab) => (
      <AgentCharacter key={lab.slug} lab={lab} variant="roaming" />
    ))}
  </section>
</main>
```

Remove public links that directly expose `/admin/*` or require login without explaining the boundary.

- [ ] **Step 5: Add responsive motion with a reduced-motion fallback**

In `PublicLabScene.module.css`, define separate decorative `transform` animations for roaming and working characters. Add:

```css
@media (prefers-reduced-motion: reduce) {
  .roaming,
  .working,
  .statusLight {
    animation: none;
  }
}
```

Keep character buttons in normal reading and tab order even when visual positions differ. At widths below `48rem`, use a single-column scene and disable path-like absolute positioning.

- [ ] **Step 6: Run focused tests**

Run: `pnpm test --run src/features/public-labs/AgentCharacter.test.tsx src/features/home/HomePage.test.tsx`

Expected: PASS.

- [ ] **Step 7: Commit the public landing**

```bash
git add frontend/src/features/public-labs frontend/src/features/home/HomePage.tsx frontend/src/features/home/HomePage.test.tsx
git commit -m "feat: build character based public landing"
```

### Task 6: Public AI Lab scene and RAG overview

**Files:**
- Create: `frontend/src/app/(public)/labs/page.tsx`
- Create: `frontend/src/app/(public)/labs/page.test.tsx`
- Create: `frontend/src/app/(public)/labs/rag/page.tsx`
- Create: `frontend/src/app/(public)/labs/rag/page.test.tsx`
- Create: `frontend/src/features/public-labs/LabWorldPage.tsx`
- Create: `frontend/src/features/public-labs/LabWorldPage.test.tsx`
- Create: `frontend/src/features/public-labs/RagLabOverviewPage.tsx`
- Create: `frontend/src/features/public-labs/RagLabOverviewPage.test.tsx`

**Interfaces:**
- Consumes: `listPublicLabs()`, `AgentCharacter`, `PublicNavigation`, `routes`, and `loginPath`.
- Produces: login-free `/labs` and `/labs/rag` pages without exposing unimplemented public search routes.

- [ ] **Step 1: Write failing public page tests**

```tsx
render(<LabWorldPage labs={listPublicLabs()} />);
expect(screen.getByRole("heading", { name: "AI Lab" })).toBeVisible();
expect(screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" })).toBeVisible();
expect(screen.getByText("RAG 기술 연구실")).toBeVisible();
```

```tsx
render(<RagLabOverviewPage />);
expect(screen.getByRole("heading", { name: "RAG 기술 연구실" })).toBeVisible();
expect(screen.getByText("BM25 + bi-encoder + RRF")).toBeVisible();
expect(screen.getByText("정확 일치와 의미 일치를 구분한 원문 하이라이트")).toBeVisible();
expect(screen.getByRole("link", { name: "로그인하고 현재 검색 기능 사용하기" })).toHaveAttribute(
  "href",
  loginPath(routes.workshopRagSearch),
);
expect(screen.queryByText(/데모/u)).not.toBeInTheDocument();
expect(screen.queryByRole("link", { name: /공개 AI 검색/u })).not.toBeInTheDocument();
```

Render both route functions directly in their colocated route tests without mocking cookies, session APIs, `requireWorkspaceUser`, or `requireOwner`. They must return the public page components synchronously.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pnpm test --run src/features/public-labs/LabWorldPage.test.tsx src/features/public-labs/RagLabOverviewPage.test.tsx "src/app/(public)/labs/page.test.tsx" "src/app/(public)/labs/rag/page.test.tsx"`

Expected: FAIL because these pages do not exist.

- [ ] **Step 3: Implement the public AI Lab scene**

`LabWorldPage` renders `PublicNavigation`, an `AI Lab` heading, one station per catalog entry, and `AgentCharacter` with `variant="working"`. Display the catalog status label. Do not render cards for insurance, finance, legal, HR, or any other future Lab before their real catalog entries exist.

Use this exact prop boundary:

```ts
interface LabWorldPageProps {
  labs: readonly PublicLab[];
}
```

- [ ] **Step 4: Implement the RAG overview from verified current capability**

Render four sections with fixed responsibility, not invented runtime data:

```text
담당 기술
- 문서 파싱과 구조 청킹
- BM25 + bi-encoder + RRF
- 정확 일치와 의미 일치를 구분한 원문 하이라이트

현재 사용할 수 있는 기능
- 로그인 작업소의 자산운용 문서 검색
- 전사·개인·임시 검색 범위
- 원문 근거 이동

공개 서비스 준비
- 다중 도메인과 불변 공개 릴리스
- 대화형 LLM 답변과 인용 검증

관리 경계
- 모델·색인·검색 구성은 시스템 관리자 영역에서만 변경
```

The only functional CTA in this phase is `로그인하고 현재 검색 기능 사용하기` pointing to `loginPath(routes.workshopRagSearch)`. Do not add `/labs/rag/domains/*` or public search links until their phase implements the required data contract.

- [ ] **Step 5: Wire the App Router pages without auth guards**

```tsx
export default function LabsRoute() {
  return <LabWorldPage labs={listPublicLabs()} />;
}
```

```tsx
export default function RagLabRoute() {
  return <RagLabOverviewPage />;
}
```

Neither file imports `requireWorkspaceUser`, `requireOwner`, cookies, or the private API client.

- [ ] **Step 6: Run focused tests**

Run: `pnpm test --run src/features/public-labs/LabWorldPage.test.tsx src/features/public-labs/RagLabOverviewPage.test.tsx "src/app/(public)/labs/page.test.tsx" "src/app/(public)/labs/rag/page.test.tsx"`

Expected: PASS.

- [ ] **Step 7: Commit the public Lab pages**

```bash
git add "frontend/src/app/(public)/labs" frontend/src/features/public-labs
git commit -m "feat: add public AI Lab experience"
```

### Task 7: Login, setup, metadata, and navigation consistency

**Files:**
- Modify: `frontend/src/features/identity/LoginPage.tsx`
- Modify: `frontend/src/features/identity/LoginPage.test.tsx`
- Modify: `frontend/src/features/identity/SetupPage.tsx`
- Modify: `frontend/src/features/identity/SetupPage.test.tsx`
- Modify: `frontend/src/app/(public)/login/page.tsx`
- Modify: `frontend/src/app/layout.tsx`

**Interfaces:**
- Consumes: `routes`, `safeReturnPath`, and `PublicNavigation`.
- Produces: consistent entry into `/workshop/*` while preserving login-free navigation back to `/labs`.

- [ ] **Step 1: Update tests first**

In `LoginPage.test.tsx`, use `nextPath={routes.workshopRagSearch}` and expect the router to replace that exact path after success. Assert a public link named `로그인 없이 AI Lab 둘러보기` points to `routes.labs`.

Assert the page also renders the shared public navigation with a `공개 전시실` navigation landmark.

In `SetupPage.test.tsx`, expect successful owner setup to replace `routes.workshopHome`.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pnpm test --run src/features/identity/LoginPage.test.tsx src/features/identity/SetupPage.test.tsx`

Expected: FAIL because the old defaults still use `/app/workspaces` and the public Lab link is absent.

- [ ] **Step 3: Update identity flows**

Set the `LoginPage` default `nextPath` to `routes.workshopHome`. After authentication, render `작업소 열기` linked to the safe resolved next path and a separate `AI Lab으로 돌아가기` link. Before authentication, include:

```tsx
<Link href={routes.labs}>로그인 없이 AI Lab 둘러보기</Link>
```

Render `PublicNavigation` above the authentication main region so the login page remains visibly part of the public area.

Change `SetupPage` success to `router.replace(routes.workshopHome)`. Keep setup owner-only copy because `/setup` provisions the actual system owner, not a technology manager character.

- [ ] **Step 4: Update root metadata**

```ts
export const metadata: Metadata = {
  title: "AI Workshop",
  description: "AI 기술 관리자와 실제 기능, 설계와 해결 과정을 탐색하는 AI 작업소",
};
```

- [ ] **Step 5: Run focused tests**

Run: `pnpm test --run src/features/identity/LoginPage.test.tsx src/features/identity/SetupPage.test.tsx src/shared/auth/access.test.ts src/shared/auth/server-session.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit entry-flow consistency**

```bash
git add frontend/src/features/identity "frontend/src/app/(public)/login/page.tsx" frontend/src/app/layout.tsx
git commit -m "refactor: align login with public and workshop areas"
```

### Task 8: Documentation, static checks, production build, and local route smoke

**Files:**
- Modify: `docs/architecture/system-design.md`
- Modify: `docs/architecture/repository-structure.md`
- Modify: `docs/runbooks/local-development.md`
- Modify: `docs/superpowers/specs/2026-09-02-public-ai-lab-rag-service-design.md`
- Modify: `WORKBOARD.md`

**Interfaces:**
- Consumes: all completed frontend routes and tests from Tasks 1–7.
- Produces: canonical documentation, verified production build, and a workboard handoff to phase 2.

- [ ] **Step 1: Search for stale canonical route and terminology references**

Run:

```bash
rg -n "/app/|/app\b|RAG 데모|공개 데모" frontend/src docs/architecture docs/runbooks docs/superpowers/specs/2026-09-02-public-ai-lab-rag-service-design.md
```

Expected: matches only in legacy redirect sources, migration history, or text explicitly explaining that the public UI does not use `데모`.

- [ ] **Step 2: Update canonical documents**

In `system-design.md`, make the three UI areas explicit:

```text
공개 전시실: /, /labs, /labs/* — 인증 없음, 승인된 공개 데이터만 사용
비공개 작업소: /workshop/* — 로그인 필요
시스템 관리: /admin/* — owner 필요
```

State that RAG is a cross-domain Lab whose first domain is asset management. Keep later public release, generation, feedback, and training work marked as later approved phases rather than implemented behavior.

In `repository-structure.md`, replace the canonical frontend `app` route branch with `workshop`, `admin`, and public `labs` branches. In `local-development.md`, update smoke URLs and explain that `/app/*` is compatibility-only.

Change the spec status from `사용자 검토 대기` to `승인됨` without changing its approved requirements.

- [ ] **Step 3: Run the full frontend verification in a resource-safe sequence**

Run from `frontend/`:

```bash
pnpm test --run
pnpm typecheck
pnpm lint
pnpm build
```

Expected: all tests pass, TypeScript exits 0, ESLint exits 0 with no warnings, and Next production build succeeds.

Run from `backend/`:

```bash
uv run pytest tests/integration/labs/rag/configurations/test_configuration_api.py tests/integration/labs/rag/evaluation/test_evaluation_api.py -q
uv run pytest tests/unit -q
uv run ruff check src tests/integration/labs/rag/configurations/test_configuration_api.py tests/integration/labs/rag/evaluation/test_evaluation_api.py
uv run mypy src
```

Expected: both focused API tests and the complete unit suite pass; Ruff and mypy exit 0.

- [ ] **Step 4: Start the local Next server and verify canonical route behavior**

Run `pnpm dev` using the existing local runtime procedure. Check:

```text
GET /                                      -> 200 without login
GET /labs                                  -> 200 without login
GET /labs/rag                              -> 200 without login
GET /workshop/workspaces                   -> 307 to /login or /setup when signed out
GET /admin/rag/configurations              -> 307 to /login or /setup when signed out
GET /app/rag/search                        -> 308 to /workshop/rag/search
GET /app/rag/configurations                -> 308 to /admin/rag/configurations
```

After signing in as the existing owner, verify `/workshop/rag/search` and `/admin/rag/configurations` render their existing data. Do not create a new owner or mutate document/model data for this smoke check.

Inspect `/` and `/labs` at a desktop viewport and a narrow mobile viewport. Verify the character does not cover navigation or copy, the introduction dialog stays inside the viewport, Escape and the close button restore focus, keyboard focus is visible, and reduced-motion mode removes decorative movement.

- [ ] **Step 5: Update the workboard**

Set the current stage to phase-1 completion, record the exact test/build/smoke results, keep recent completed work at no more than five entries, and set the next task to phase 2 `다중 도메인과 공개 릴리스 기반` detailed design.

- [ ] **Step 6: Commit documentation and verification evidence**

```bash
git add docs/architecture/system-design.md docs/architecture/repository-structure.md docs/runbooks/local-development.md docs/superpowers/specs/2026-09-02-public-ai-lab-rag-service-design.md WORKBOARD.md
git commit -m "docs: record public area boundary verification"
```
