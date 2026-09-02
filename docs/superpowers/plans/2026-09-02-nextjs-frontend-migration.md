# Next.js Frontend Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vite·React Router 프론트엔드를 Next.js App Router로 완전히 전환하고 사용자 작업소와 owner 전용 관리자 영역을 FastAPI 권한 계약에 맞춰 분리한다.

**Architecture:** FastAPI가 세션, 권한, RAG와 데이터의 유일한 정본으로 남고 Next.js는 Server Component 기반 초기 렌더링과 same-origin API rewrite를 담당한다. 브라우저 상호작용은 작은 Client Component에 한정하며, FastAPI의 읽기 RAG registry API는 인증 사용자에게 유지하고 변경 API는 owner 전용 관리자 namespace로 제공한다.

**Tech Stack:** Next.js 16.3.4, React 19.2.8, TypeScript 5.9, Vitest 4, Testing Library, FastAPI, Pydantic, pytest, Ruff, mypy, OpenAPI TypeScript

**Spec:** `docs/superpowers/specs/2026-09-02-nextjs-frontend-migration-design.md`

## Global Constraints

- `main`에서만 작업하고 별도 branch 또는 worktree를 만들지 않는다.
- 로컬 프론트 주소는 `http://127.0.0.1:5173`으로 유지한다.
- 루트 `.env`의 `API_PORT`만 FastAPI target 설정의 정본으로 사용한다.
- Next.js는 JWT를 해석하거나 세션을 발급하지 않는다.
- 사용자별 server fetch는 요청 cookie를 전달하고 `cache: "no-store"`를 사용한다.
- FastAPI endpoint가 최종 인증·권한 경계이며 관리자 변경 명령은 `owner`만 허용한다.
- Vite와 React Router는 완료 상태에서 의존성·설정·진입점까지 제거한다.
- 프론트 의존성은 `frontend/node_modules`와 `frontend/pnpm-lock.yaml`에만 둔다.
- PostgreSQL, Redis와 Elasticsearch만 Docker로 실행하며 Next.js와 FastAPI는 host에서 실행한다.
- 기능 변경은 실패 테스트를 먼저 확인하고 최소 구현 후 관련 검증을 통과시킨다.

---

### Task 1: 역할과 owner 권한 계약

**Files:**
- Modify: `backend/src/ai_workshop/platform/identity/domain.py`
- Modify: `backend/src/ai_workshop/platform/identity/api.py`
- Modify: `backend/src/ai_workshop/shared/errors.py`
- Create: `backend/tests/api/test_owner_authorization.py`
- Create: `backend/tests/unit/platform/identity/test_domain.py`

**Interfaces:**
- Produces: `UserRole.MEMBER = "member"`
- Produces: `async def require_owner(user: Annotated[User, Depends(get_current_user)]) -> User`
- Raises: owner가 아니면 `AppError(code="owner_required", message="Owner access is required.", status_code=403)`

- [ ] **Step 1: 일반 사용자 역할과 owner guard 실패 테스트 작성**

```python
def member() -> User:
    return User(id=uuid4(), display_name="Member", email="member@example.com",
                normalized_email="member@example.com", password_hash="hash",
                role=UserRole.MEMBER)

def test_member_role_is_part_of_the_public_contract() -> None:
    assert UserRole.MEMBER.value == "member"

async def test_owner_guard_rejects_member() -> None:
    with pytest.raises(AppError) as raised:
        await require_owner(member())
    assert raised.value.status_code == 403
    assert raised.value.code == "owner_required"
```

- [ ] **Step 2: 테스트가 `MEMBER` 또는 `require_owner` 부재로 실패하는지 확인**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\api\test_owner_authorization.py backend\tests\unit\platform\identity\test_domain.py -q`

- [ ] **Step 3: 역할 enum과 재사용 가능한 owner 의존성 구현**

`UserRole`에 `MEMBER`를 추가하고 `require_owner`는 `get_current_user` 결과를 그대로 반환하되 role이 `OWNER`가 아니면 `AppError` 403을 발생시킨다. `COMMON_ERROR_RESPONSES`에도 403 envelope 설명을 추가한다. DB 컬럼은 `String(32)`이므로 스키마 변경을 만들지 않는다.

- [ ] **Step 4: 역할·권한 테스트와 Alembic 상태 통과 확인**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\api\test_owner_authorization.py backend\tests\unit\platform\identity\test_domain.py -q`

Run: `backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini check`

- [ ] **Step 5: 역할 계약 커밋**

```powershell
git add backend/src/ai_workshop/platform/identity backend/tests/api/test_owner_authorization.py backend/tests/unit/platform/identity/test_domain.py
git commit -m "feat:add-owner-authorization-contract"
```

### Task 2: RAG 모델 관리자 API 분리

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/models/api.py`
- Create: `backend/src/ai_workshop/labs/rag/models/admin_api.py`
- Modify: `backend/src/ai_workshop/main.py`
- Modify: `backend/tests/integration/labs/rag/models/test_profile_api.py`

**Interfaces:**
- Keeps: `GET /api/v1/rag/models`, `GET /api/v1/rag/profiles/{kind}` with `get_current_user`
- Produces: owner-only POST endpoints under `/api/v1/admin/rag`
- Keeps: legacy POST endpoints under `/api/v1/rag`, marked `deprecated=True` and owner-only
- Consumes: `require_owner`, `RagModelRegistryService`

- [ ] **Step 1: canonical 관리자 endpoint와 member 거절 테스트 작성**

```python
with TestClient(app) as client:
    created = client.post("/api/v1/admin/rag/models", json=model_request)
assert created.status_code == 201

app.dependency_overrides[get_current_user] = member
with TestClient(app) as client:
    denied = client.post("/api/v1/admin/rag/models", json=model_request)
    readable = client.get("/api/v1/rag/models")
assert denied.status_code == 403
assert denied.json()["error"]["code"] == "owner_required"
assert readable.status_code == 200
```

같은 방식으로 profile JSON, YAML과 default 승격 canonical 경로를 검증하고 legacy POST가 owner에게 동작하면서 OpenAPI operation에 `deprecated: true`가 있는지 검증한다.

- [ ] **Step 2: 새 관리자 경로가 404이고 legacy POST가 member에게 열려 있어 실패하는지 확인**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\labs\rag\models\test_profile_api.py -q`

- [ ] **Step 3: 관리자 router와 legacy 호환 endpoint 구현**

`admin_api.py`에 `APIRouter(prefix="/api/v1/admin/rag", tags=["admin-rag-models"])`를 만들고 네 POST 명령을 구현한다. 기존 `api.py`의 GET은 유지하며 POST에는 `Depends(require_owner)`와 `deprecated=True`를 적용한다. 양쪽 endpoint는 동일 `RagModelRegistryService` 메서드를 직접 호출해 업무 로직을 복제하지 않는다.

- [ ] **Step 4: app에 관리자 router 등록 후 API 테스트 통과 확인**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\labs\rag\models\test_profile_api.py backend\tests\api\test_owner_authorization.py -q`

- [ ] **Step 5: 관리자 API 경계 커밋**

```powershell
git add backend/src/ai_workshop/labs/rag/models backend/src/ai_workshop/main.py backend/tests/integration/labs/rag/models/test_profile_api.py
git commit -m "feat:separate-rag-admin-commands"
```

### Task 3: Next.js 도구 체인과 API transport 기반

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml`
- Modify: `frontend/tsconfig.json`
- Delete: `frontend/tsconfig.app.json`
- Delete: `frontend/tsconfig.node.json`
- Create: `frontend/next.config.ts`
- Create: `frontend/next-env.d.ts`
- Create: `frontend/vitest.config.ts`
- Modify: `frontend/eslint.config.js`
- Modify: `.gitignore`
- Move: `frontend/src/app/apiTarget.ts` to `frontend/src/shared/config/api-target.ts`
- Move: `frontend/src/app/apiTarget.test.ts` to `frontend/src/shared/config/api-target.test.ts`
- Modify: `frontend/src/shared/api/client.ts`
- Create: `frontend/src/shared/api/server-client.ts`
- Create: `frontend/src/shared/api/server-client.test.ts`

**Interfaces:**
- Produces: `resolveApiTarget(port: string | undefined): string`
- Produces: `apiRequest<T>(path, options)` for browser same-origin calls
- Produces: `serverApiRequest<T>(path, options, cookieHeader?): Promise<T>` for direct FastAPI calls
- Produces: `next.config.ts` rewrites `/api/:path*` to `${apiTarget}/api/:path*`

- [ ] **Step 1: server API client와 target validation 실패 테스트 작성**

```ts
it("forwards cookies and disables caching", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ id: "owner" })));
  await serverApiRequest("/api/v1/auth/me", {}, "ai_workshop_session=token");
  expect(fetch).toHaveBeenCalledWith(
    "http://127.0.0.1:8000/api/v1/auth/me",
    expect.objectContaining({ cache: "no-store", headers: expect.any(Headers) }),
  );
  expect((fetch as Mock).mock.calls[0][1].headers.get("cookie"))
    .toBe("ai_workshop_session=token");
});
```

기존 target 테스트에는 빈 값 기본 `8000`, 범위 밖 숫자와 비숫자 거절을 유지한다.

- [ ] **Step 2: server client 테스트가 파일 부재로 실패하는지 확인**

Run: `pnpm --dir frontend test --run src/shared/config/api-target.test.ts src/shared/api/server-client.test.ts`

- [ ] **Step 3: 의존성과 Next/Vitest/TypeScript/ESLint 설정 구현**

`next`와 `@next/env`를 정확히 `16.3.4`로 추가하고 `@vitejs/plugin-react`, `vite`, `react-router-dom`, `eslint-plugin-react-refresh`를 제거한다. scripts는 `dev: next dev --hostname 127.0.0.1 --port 5173`, `build: next build`, `start: next start --hostname 127.0.0.1 --port 5173`, `typecheck: tsc --noEmit`, 기존 test/lint/api scripts로 구성한다. `vitest.config.ts`는 jsdom, globals, setup file과 `@` alias를 설정한다. `.gitignore`에 `frontend/.next/`를 추가하고 `frontend/dist/`를 제거한다.

- [ ] **Step 4: root `.env` 로드 rewrite와 두 API client 구현**

`next.config.ts`에서 `loadEnvConfig(path.resolve(process.cwd(), ".."))` 후 `resolveApiTarget(process.env.API_PORT)`를 호출한다. `serverApiRequest`는 주어진 cookie를 `Headers`에 넣고 direct target URL로 요청하며 `cache: "no-store"`를 강제한다. 오류 envelope decoding은 브라우저 client와 공유 함수로 분리해 401/403/404 및 correlation ID를 보존한다.

- [ ] **Step 5: 기반 테스트, 타입 검사와 dependency 위치 확인**

Run: `pnpm --dir frontend install --frozen-lockfile=false`

Run: `pnpm --dir frontend test --run src/shared/config/api-target.test.ts src/shared/api/client.test.ts src/shared/api/server-client.test.ts`

Run: `pnpm --dir frontend typecheck`

Run: `if exist node_modules exit /b 1`

- [ ] **Step 6: Next 도구 체인 커밋**

```powershell
git add .gitignore frontend
git commit -m "build:migrate-frontend-toolchain-to-nextjs"
```

### Task 4: App Router 접근 정책과 layout

**Files:**
- Create: `frontend/src/app/layout.tsx`
- Create: `frontend/src/app/page.tsx`
- Create: `frontend/src/app/(workspace)/app/layout.tsx`
- Create: `frontend/src/app/(administration)/admin/layout.tsx`
- Create: `frontend/src/app/(workspace)/app/error.tsx`
- Create: `frontend/src/app/(administration)/admin/error.tsx`
- Create: `frontend/src/features/navigation/WorkspaceNavigation.tsx`
- Create: `frontend/src/features/navigation/AdminNavigation.tsx`
- Create: `frontend/src/shared/auth/access.ts`
- Create: `frontend/src/shared/auth/access.test.ts`
- Create: `frontend/src/shared/auth/server-session.ts`
- Create: `frontend/src/shared/auth/server-session.test.ts`
- Modify: `frontend/src/app/styles.css`

**Interfaces:**
- Produces: `safeReturnPath(candidate: string | null): string`
- Produces: `unauthenticatedDestination(setupRequired: boolean, returnTo: string): string`
- Produces: `requireWorkspaceUser(returnTo: string): Promise<SessionUser>`
- Produces: `requireOwner(returnTo: string): Promise<SessionUser>`

- [ ] **Step 1: 접근 결정 순수 함수와 owner/member 분기 실패 테스트 작성**

```ts
expect(safeReturnPath("//evil.example")).toBe("/app/workspaces");
expect(unauthenticatedDestination(true, "/app/rag/search"))
  .toBe("/setup?next=%2Fapp%2Frag%2Fsearch");
expect(canAccessAdmin({ role: "member" })).toBe(false);
expect(canAccessAdmin({ role: "owner" })).toBe(true);
```

server-session 테스트는 `serverApiRequest`를 mock해 401 뒤 setup status에 따라 `redirect`가 호출되고 member owner guard는 `/app/workspaces?error=owner_required`로 이동하는지 검증한다.

- [ ] **Step 2: 접근 테스트가 모듈 부재로 실패하는지 확인**

Run: `pnpm --dir frontend test --run src/shared/auth/access.test.ts src/shared/auth/server-session.test.ts`

- [ ] **Step 3: 접근 함수와 서버 세션 guard 구현**

`server-session.ts`는 `cookies()`의 값을 header 문자열로 직렬화해 `/auth/me`에 전달한다. 401일 때만 `/setup/status`를 조회하며 backend 연결 실패는 redirect나 빈 사용자로 바꾸지 않는다. `/admin` guard는 받은 역할이 `owner`인지 검사한다.

- [ ] **Step 4: root, workspace와 admin layout 구현**

root layout은 metadata, `<html lang="ko">`, 전역 스타일만 제공한다. workspace/admin layout은 각각 guard를 호출한 뒤 서로 다른 navigation과 `<main>` content를 렌더링한다. error boundary는 Client Component로 오류 message를 노출하지 않고 correlation ID와 `reset()` 버튼을 표시한다.

- [ ] **Step 5: 접근·layout 관련 테스트와 타입 검사 통과 확인**

Run: `pnpm --dir frontend test --run src/shared/auth/access.test.ts src/shared/auth/server-session.test.ts`

Run: `pnpm --dir frontend typecheck`

- [ ] **Step 6: App Router 경계 커밋**

```powershell
git add frontend/src/app frontend/src/features/navigation frontend/src/shared/auth
git commit -m "feat:add-nextjs-access-layouts"
```

### Task 5: 공개 홈·로그인·최초 관리자 setup 이전

**Files:**
- Move: `frontend/src/app/App.tsx` to `frontend/src/features/home/HomePage.tsx`
- Move: `frontend/src/app/App.test.tsx` to `frontend/src/features/home/HomePage.test.tsx`
- Move: `frontend/src/platform/identity/*` to `frontend/src/features/identity/`
- Create: `frontend/src/app/(public)/login/page.tsx`
- Create: `frontend/src/app/(public)/setup/page.tsx`
- Modify: `frontend/src/app/page.tsx`

**Interfaces:**
- Produces: `LoginForm({ nextPath, authenticate? })`
- Produces: `SetupForm({ createOwner? })`
- Redirects: 성공 시 `/app/workspaces`; setup 완료 시 `/login`; setup 미완료 로그인 시 `/setup`

- [ ] **Step 1: Next navigation과 canonical URL 기준으로 컴포넌트 테스트 변경**

`next/navigation`의 `useRouter().replace`를 mock하고 setup 성공이 `/app/workspaces`, 로그인 기본 성공이 `/app/workspaces`, 안전한 `next=/app/rag/search`가 해당 경로를 사용하는지 검증한다. Home 테스트는 링크가 `/app/rag/search`, `/app/rag/configurations`, `/admin/rag/models`인지 검증한다.

- [ ] **Step 2: 기존 컴포넌트가 React Router에 의존해 테스트가 실패하는지 확인**

Run: `pnpm --dir frontend test --run src/features/home/HomePage.test.tsx src/features/identity/LoginPage.test.tsx src/features/identity/SetupPage.test.tsx`

- [ ] **Step 3: 공개 Client Component와 server page 구현**

폼 파일에는 `"use client"`를 선언하고 `useRouter`만 사용한다. login/setup page는 setup status를 server fetch해 완료 여부에 따라 redirect하며 `searchParams.next`를 `safeReturnPath`에 통과시켜 폼 prop으로 전달한다. 홈은 `next/link`와 canonical URL만 사용한다.

- [ ] **Step 4: 공개 화면 테스트와 타입 검사 통과 확인**

Run: `pnpm --dir frontend test --run src/features/home/HomePage.test.tsx src/features/identity/LoginPage.test.tsx src/features/identity/SetupPage.test.tsx`

Run: `pnpm --dir frontend typecheck`

- [ ] **Step 5: 공개 화면 커밋**

```powershell
git add frontend/src/app frontend/src/features/home frontend/src/features/identity
git commit -m "feat:migrate-public-pages-to-nextjs"
```

### Task 6: 지식 공간과 문서 화면 이전

**Files:**
- Move: `frontend/src/platform/workspaces/*` to `frontend/src/features/workspaces/`
- Move: `frontend/src/platform/assets/*` to `frontend/src/features/assets/`
- Move: `frontend/src/platform/jobs/*` to `frontend/src/features/jobs/`
- Create: `frontend/src/app/(workspace)/app/workspaces/page.tsx`
- Create: `frontend/src/app/(workspace)/app/workspaces/[workspaceId]/documents/page.tsx`

**Interfaces:**
- Consumes: `serverApiRequest`, workspace layout authentication
- Produces: `WorkspacePage({ initialWorkspaces })` with canonical document links
- Produces: `DocumentPage({ workspaceId, initialDocuments })`

- [ ] **Step 1: router loader 없는 prop 기반 테스트와 canonical 링크 테스트 작성**

```tsx
render(<WorkspacePage initialWorkspaces={workspaces} />);
expect(screen.getByRole("link", { name: /전사 문서/ }))
  .toHaveAttribute("href", "/app/workspaces/1/documents");

render(<DocumentPage workspaceId="workspace-1" initialDocuments={documents} />);
expect(screen.getByRole("heading", { name: "문서" })).toBeVisible();
```

- [ ] **Step 2: React Router hook 제거 전 테스트가 실패하는지 확인**

Run: `pnpm --dir frontend test --run src/features/workspaces/WorkspacePage.test.tsx src/features/assets/DocumentBrowser.test.tsx`

- [ ] **Step 3: prop 기반 Client Component와 server page 구현**

workspace page는 server에서 `/api/v1/workspaces`, documents page는 `params.workspaceId`를 URL encode해 문서 목록을 조회한다. 업로드와 job polling 컴포넌트만 Client Component로 유지하며 초기 목록은 props로 전달한다.

- [ ] **Step 4: 공간·문서 테스트와 타입 검사 통과 확인**

Run: `pnpm --dir frontend test --run src/features/workspaces src/features/assets src/features/jobs`

Run: `pnpm --dir frontend typecheck`

- [ ] **Step 5: 공간·문서 화면 커밋**

```powershell
git add frontend/src/app frontend/src/features/workspaces frontend/src/features/assets frontend/src/features/jobs frontend/src/platform
git commit -m "feat:migrate-workspace-pages-to-nextjs"
```

### Task 7: RAG 사용자 화면과 관리자 모델 화면 이전

**Files:**
- Move: `frontend/src/labs/rag/*` to `frontend/src/features/rag/`
- Create: `frontend/src/app/(workspace)/app/rag/search/page.tsx`
- Create: `frontend/src/app/(workspace)/app/rag/configurations/page.tsx`
- Create: `frontend/src/app/(workspace)/app/rag/sources/[assetVersionId]/page.tsx`
- Create: `frontend/src/app/(administration)/admin/rag/models/page.tsx`
- Modify: `frontend/src/features/rag/models/api.ts`
- Modify: RAG component tests under `frontend/src/features/rag/`

**Interfaces:**
- Search page consumes: `loadSearchOptions()` server-side initial data
- Configuration page consumes: `loadConfigurationStudio()` server-side initial data
- Source viewer consumes: `assetVersionId`, `projectionId`, highlight query props
- Admin model mutations use: `/api/v1/admin/rag/models` and `/api/v1/admin/rag/profiles/{kind}/yaml`

- [ ] **Step 1: RAG 컴포넌트를 prop 기반·Next Link·관리자 API 기준으로 테스트 변경**

검색 테스트는 `initialOptions`, 구성 테스트는 `initialData`, 모델 테스트는 `initialData`를 직접 넘긴다. Evidence/related source 링크는 `/app/rag/sources/{id}`를 사용하고 query string을 보존한다. API 테스트는 등록 POST가 `/api/v1/admin/rag/...`로 향하는지 검증한다.

- [ ] **Step 2: 기존 React Router hook과 구 관리자 API 때문에 테스트가 실패하는지 확인**

Run: `pnpm --dir frontend test --run src/features/rag`

- [ ] **Step 3: 검색·구성 server page와 상호작용 Client Component 구현**

기존 `SearchPage`, `ConfigurationStudioPage`, `ModelLabPage`의 loader wrapper를 제거하고 초기 데이터 prop을 받게 한다. 각 Next page가 server client로 초기 데이터를 가져오며 이후 검색, 저장, 평가와 등록은 browser client를 사용한다.

- [ ] **Step 4: 원문 뷰어를 route prop 기반으로 변경**

Next source page가 `params.assetVersionId`와 `searchParams`를 검증해 `SourceViewer`에 전달한다. `SourceViewer`에서 `useLocation`, `useParams`, `useSearchParams`를 제거하고 keyword/semantic highlight query 값은 명시적 props로 받는다.

- [ ] **Step 5: admin model mutation 경로 변경과 전체 RAG 테스트 통과 확인**

Run: `pnpm --dir frontend test --run src/features/rag`

Run: `pnpm --dir frontend typecheck`

- [ ] **Step 6: RAG 화면 전환 커밋**

```powershell
git add frontend/src/app frontend/src/features/rag frontend/src/labs
git commit -m "feat:migrate-rag-pages-to-nextjs"
```

### Task 8: legacy 제거, 계약·문서 갱신과 전체 검증

**Files:**
- Delete: `frontend/src/main.tsx`
- Delete: `frontend/src/app/router.tsx`
- Delete: `frontend/src/app/router.test.tsx`
- Delete: `frontend/index.html`
- Delete: `frontend/vite.config.ts`
- Modify: `frontend/next.config.ts`
- Regenerate: `frontend/src/shared/api/schema.d.ts`
- Modify: `docs/runbooks/local-development.md`
- Modify: `docs/architecture/repository-structure.md`
- Modify: `CACHE_POLICY.md`
- Modify: `WORKBOARD.md`

**Interfaces:**
- Produces redirects: `/workspaces`, `/workspaces/:workspaceId/documents`, `/rag/search`, `/rag/configurations`, `/rag/sources/:assetVersionId`, `/rag/models`
- Produces production Next build with no Vite or React Router dependency

- [ ] **Step 1: redirect 설정 테스트와 dependency absence 검사를 작성**

`next.config.ts`의 redirect factory를 별도 export 가능한 `legacyRedirects()` 순수 함수로 두고 source/destination/permanent를 검증한다. 저장소 검사에서 `rg -n "react-router-dom|vite/client|@vitejs" frontend`가 소스·설정·manifest에 결과를 내지 않아야 한다.

- [ ] **Step 2: legacy 파일 제거 전 검사 실패 확인**

Run: `rg -n -e "react-router-dom" -e "vite/client" -e "@vitejs" frontend`

Expected: 기존 router, tests 또는 lockfile 위치가 출력됨.

- [ ] **Step 3: legacy 파일 제거와 permanent redirect 구현**

정적·동적 URL을 모두 `permanent: true`로 설정하고 source viewer query string은 Next redirect 기본 동작으로 보존한다. Vite entry/config/index와 router test를 삭제하고 남은 테스트는 Next page/feature 경계를 직접 검증한다.

- [ ] **Step 4: OpenAPI와 운영 문서 갱신**

Run: `pnpm --dir frontend api:generate`

로컬 실행서는 Next 명령, canonical URL, 관리자 URL과 FastAPI rewrite를 설명한다. 저장소 구조는 `src/app`, `src/features`, `src/shared` 실제 구조로 바꾼다. cache 정책은 `frontend/.next`를 재생성 가능한 보존 캐시로 분류하고 루트 `node_modules` 금지를 유지한다. WORKBOARD의 최근 완료는 최대 5개로 유지한다.

- [ ] **Step 5: 백엔드 전체 검증**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests -q`

Run: `backend\.venv\Scripts\python.exe -m ruff check backend`

Run: `backend\.venv\Scripts\python.exe -m mypy backend\src`

Run: `backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini check`

- [ ] **Step 6: 프론트 전체 검증**

Run: `pnpm --dir frontend test --run`

Run: `pnpm --dir frontend typecheck`

Run: `pnpm --dir frontend lint`

Run: `pnpm --dir frontend api:check`

Run: `pnpm --dir frontend build`

- [ ] **Step 7: host runtime smoke**

FastAPI를 root `.env`의 `API_PORT`에서 실행하고 Next dev server를 5173에서 실행한 뒤 다음을 확인한다.

```powershell
Invoke-WebRequest http://127.0.0.1:5173/ -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:5173/api/v1/health -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:5173/rag/search -MaximumRedirection 0 -SkipHttpErrorCheck
Invoke-WebRequest http://127.0.0.1:5173/app/workspaces -UseBasicParsing
```

기대 결과는 `/`와 health 200, legacy 검색 경로 308과 `/app/rag/search` Location, 인증 쿠키가 없을 때 `/app/workspaces`가 setup 완료 상태에 따라 `/login?next=...` 또는 `/setup?next=...`로 이동하는 것이다. 기존 사용자 cookie를 사용한 요청에서는 전사·개인 공간 텍스트가 응답에 포함되어야 한다.

- [ ] **Step 8: 최종 상태 커밋·푸시**

```powershell
git add frontend backend docs CACHE_POLICY.md WORKBOARD.md .gitignore
git commit -m "feat:complete-nextjs-frontend-migration"
git push origin main
```
