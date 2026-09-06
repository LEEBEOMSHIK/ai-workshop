# Linux OCR Runtime and Admin Topology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Linux CPU용 PP-StructureV3 worker를 core backend image와 분리하고, owner가 안전한 Docker 논리 구성을 관리자 화면에서 확인하게 한다.

**Architecture:** Dockerfile은 공유 application stage에서 `runtime-core`와 `runtime-ocr-cpu`를 만든다. Compose가 실행 정본이고 Platform package의 typed YAML은 관리자 표시 정본이며, 자동 drift contract가 둘을 동기화한다. Docker socket 없이 API process만 `responding`, 나머지는 `not_observed`로 표시한다.

**Tech Stack:** Docker BuildKit, Docker Compose, Python 3.13, FastAPI, Pydantic, PyYAML, pytest, Next.js 16, React 19, TypeScript, Vitest

**Spec:** `docs/superpowers/specs/2026-09-06-linux-ocr-runtime-admin-topology-design.md`

## Global Constraints

- 사용자가 승인한 대로 현재 `main`에서만 작업하고 별도 worktree를 만들지 않는다.
- Docker socket, raw Compose, 환경변수, secret, endpoint, host port와 절대 경로를 API에 노출하지 않는다.
- Linux GPU image와 actual GPU inference는 구현하지 않고 `미구현/미검증`으로 표시한다.
- Docker cache와 image 삭제는 `CACHE_POLICY.md`의 별도 조사·승인 없이 수행하지 않는다.
- 모든 production behavior는 실패하는 테스트를 먼저 확인한 뒤 최소 구현한다.

---

### Task 1: Typed safe topology contract

**Files:**
- Create: `backend/tests/unit/platform/runtime_topology/test_manifest.py`
- Create: `backend/src/ai_workshop/platform/runtime_topology/__init__.py`
- Create: `backend/src/ai_workshop/platform/runtime_topology/domain.py`
- Create: `backend/src/ai_workshop/platform/runtime_topology/service.py`
- Create: `backend/src/ai_workshop/platform/runtime_topology/runtime-topology-v1.yaml`

**Interfaces:**
- Produces: `RuntimeTopologyService.load() -> RuntimeTopology`
- Produces: immutable `RuntimeNode`, `RuntimeStorage`, `CompatibilityLane`, `RuntimeTopology`
- Rejects: unknown YAML fields, duplicate IDs, missing dependency/storage references, forbidden endpoint/path-like fields

- [x] **Step 1: Write failing manifest behavior tests**

```python
def test_loads_safe_runtime_topology_and_marks_only_api_as_responding() -> None:
    topology = RuntimeTopologyService().load()
    assert topology.node("api").observation == RuntimeObservation.RESPONDING
    assert topology.node("worker").observation == RuntimeObservation.NOT_OBSERVED
    assert topology.compatibility("linux-gpu").verification_state == "unverified"

def test_rejects_unknown_or_dangling_manifest_fields(tmp_path: Path) -> None:
    manifest = tmp_path / "runtime.yaml"
    manifest.write_text("schema_version: 1\nsecret: exposed\n", encoding="utf-8")
    with pytest.raises(RuntimeTopologyManifestError):
        RuntimeTopologyService(manifest_path=manifest).load()
```

- [x] **Step 2: Verify RED**

Run: `backend\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp=.local-data/pytest-runtime-topology-red backend/tests/unit/platform/runtime_topology/test_manifest.py -q`

Expected: collection fails because `ai_workshop.platform.runtime_topology` does not exist.

- [x] **Step 3: Implement minimal immutable domain, strict YAML parser and manifest**

Use Pydantic models with `ConfigDict(extra="forbid", frozen=True)`. Resolve the default manifest through `importlib.resources.files("ai_workshop.platform.runtime_topology")`. Validate all node dependency/storage references and keep compatibility lanes outside Compose nodes.

- [x] **Step 4: Verify GREEN**

Run the Step 2 command with basetemp `.local-data/pytest-runtime-topology-green`.

Expected: all manifest tests pass.

### Task 2: Compose drift and image-target contract

**Files:**
- Create: `backend/tests/unit/platform/runtime_topology/test_compose_contract.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Modify: `backend/Dockerfile`
- Modify: `infrastructure/compose/compose.yaml`
- Modify: `scripts/verify-backend-image-footprint.ps1`

**Interfaces:**
- Compose targets: `runtime-core`, `runtime-ocr-cpu`
- Optional dependency: `ocr-cpu = [paddleocr==3.7.0, paddlepaddle==3.2.2, paddlex[ocr]==3.7.2]`
- Verification script parameter: `-ExpectedOcrRuntime absent|cpu`

- [x] **Step 1: Write failing parsed-Compose contract tests**

```python
def test_compose_matches_safe_topology_manifest() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    topology = RuntimeTopologyService().load()
    assert project_compose_contract(compose) == topology.compose_contract()

def test_worker_alone_uses_cpu_ocr_target() -> None:
    compose = load_compose()
    assert compose["services"]["worker"]["build"]["target"] == "runtime-ocr-cpu"
    assert compose["services"]["api"]["build"]["target"] == "runtime-core"
    assert compose["services"]["beat"]["build"]["target"] == "runtime-core"
```

- [x] **Step 2: Verify RED**

Run: `backend\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp=.local-data/pytest-compose-contract-red backend/tests/unit/platform/runtime_topology/test_compose_contract.py -q`

Expected: targets and manifest contract differ from the current single-image Compose.

- [x] **Step 3: Implement multi-target images and Compose selection**

Rename the optional extra to `ocr-cpu`, refresh `uv.lock`, add a shared application stage, install the extra only in `runtime-ocr-cpu`, and make `runtime-core` the last stage. Give the worker image `ai-workshop-backend-ocr-cpu:local`; keep API, beat and tools on `ai-workshop-backend:local` with explicit targets.

- [x] **Step 4: Extend image verification behavior**

`-ExpectedOcrRuntime absent` must fail if `paddle`, `paddleocr` or `paddlex` imports. `cpu` must require all three imports and exact versions. Both modes retain uv-cache, non-root import and `/data/objects` ownership checks.

- [x] **Step 5: Verify GREEN and Compose validity**

Run the Step 2 test with basetemp `.local-data/pytest-compose-contract-green`.

Run: `docker compose -f infrastructure/compose/compose.yaml config --quiet`

Expected: tests pass and Compose config exits 0.

### Task 3: Owner-only runtime topology API

**Files:**
- Create: `backend/tests/api/test_runtime_topology.py`
- Create: `backend/src/ai_workshop/platform/runtime_topology/schemas.py`
- Create: `backend/src/ai_workshop/platform/runtime_topology/api.py`
- Modify: `backend/src/ai_workshop/main.py`
- Modify: `backend/tests/contract/test_openapi.py`

**Interfaces:**
- Route: `GET /api/v1/admin/system/runtime-topology`
- Response: `RuntimeTopologyResponse`
- Authorization: `Depends(require_owner)`

- [x] **Step 1: Write failing authorization and safe-response tests**

```python
def test_owner_reads_safe_runtime_topology(owner_client: TestClient) -> None:
    response = owner_client.get("/api/v1/admin/system/runtime-topology")
    assert response.status_code == 200
    assert response.json()["nodes"][0].keys() >= {"id", "display_name", "observation"}
    assert not forbidden_keys(response.json())

def test_member_cannot_read_runtime_topology(member_client: TestClient) -> None:
    response = member_client.get("/api/v1/admin/system/runtime-topology")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "owner_required"
```

- [x] **Step 2: Verify RED**

Run: `backend\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp=.local-data/pytest-runtime-api-red backend/tests/api/test_runtime_topology.py backend/tests/contract/test_openapi.py -q`

Expected: route is 404 and OpenAPI expected-path assertion fails.

- [x] **Step 3: Implement schemas, router and app registration**

Map domain objects to response models explicitly. Do not serialize YAML dictionaries directly. Return only the spec allowlist and register the new path in `EXPECTED_PATHS`.

- [x] **Step 4: Verify GREEN**

Run the Step 2 command with basetemp `.local-data/pytest-runtime-api-green`.

Expected: authorization, privacy and OpenAPI tests pass.

### Task 4: Admin runtime page

**Files:**
- Create: `frontend/src/features/runtime-topology/api.ts`
- Create: `frontend/src/features/runtime-topology/RuntimeTopologyPage.tsx`
- Create: `frontend/src/features/runtime-topology/RuntimeTopologyPage.test.tsx`
- Create: `frontend/src/app/(administration)/admin/system/runtime/page.tsx`
- Create: `frontend/src/app/(administration)/admin/system/runtime/page.test.tsx`
- Modify: `frontend/src/shared/routing/routes.ts`
- Modify: `frontend/src/shared/routing/routes.test.ts`
- Modify: `frontend/src/features/navigation/AdminNavigation.tsx`
- Modify: `frontend/src/features/navigation/AdminNavigation.test.tsx`
- Modify: `frontend/src/app/styles.css`
- Modify: `frontend/src/shared/api/schema.d.ts`

**Interfaces:**
- Route constant: `routes.adminSystemRuntime`
- Loader: `loadRuntimeTopology(cookieHeader?: string) -> Promise<RuntimeTopologyResponse>`
- Component: `RuntimeTopologyPage({ topology })`

- [x] **Step 1: Write failing route, navigation and rendering tests**

```tsx
it("renders service dependencies, storage and honest verification states", () => {
  render(<RuntimeTopologyPage topology={fixture} />);
  expect(screen.getByRole("heading", { name: "시스템 런타임" })).toBeInTheDocument();
  expect(screen.getByText("OCR 작업자")).toBeInTheDocument();
  expect(screen.getByText("별도 컨테이너가 아닌 영속 볼륨")).toBeInTheDocument();
  expect(screen.getByText("미구현/미검증")).toBeInTheDocument();
});
```

- [x] **Step 2: Verify RED**

Run: `pnpm --dir frontend test --run src/features/runtime-topology/RuntimeTopologyPage.test.tsx src/app/\(administration\)/admin/system/runtime/page.test.tsx src/features/navigation/AdminNavigation.test.tsx src/shared/routing/routes.test.ts`

Expected: modules and route constant do not exist.

- [x] **Step 3: Generate API types and implement server route/UI**

Run: `pnpm --dir frontend api:generate`

The server route must call `requireOwner(routes.adminSystemRuntime)`, forward the incoming cookie to `serverApiRequest`, and render `ServerRouteFailure` on failure. The component renders summary, service flow, image targets, storages, tools/verification and security boundary from API data without hardcoded service/model versions.

- [x] **Step 4: Verify GREEN**

Run the Step 2 command again.

Expected: all focused frontend tests pass.

### Task 5: Portable network-off Linux CPU OCR smoke

**Files:**
- Modify: `backend/tests/integration/labs/rag/ocr/test_paddle_structure_smoke.py`
- Modify: `infrastructure/compose/compose.yaml`
- Modify: `docs/runbooks/local-development.md`

**Interfaces:**
- Environment: `AI_WORKSHOP_OCR_SMOKE_MANIFEST_PATH`
- Environment: `AI_WORKSHOP_MODEL_CACHE_ROOT`
- Environment: `AI_WORKSHOP_OCR_SMOKE_DEVICE=cpu`
- Compose service: `ocr-linux-cpu-smoke`, profile `ocr-smoke`

- [x] **Step 1: Write failing portability tests**

Add unit-testable fixture/path helpers whose expected output does not contain `C:/Windows/Fonts` and whose cache/manifest paths come only from the three explicit environment settings.

- [x] **Step 2: Verify RED**

Run: `backend\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp=.local-data/pytest-ocr-portability-red backend/tests/integration/labs/rag/ocr/test_paddle_structure_smoke.py -q`

Expected: the Linux portability assertion fails against the current Windows-only fixture/path behavior while actual inference tests remain explicitly gated.

- [x] **Step 3: Implement portable synthetic fixture and Compose smoke service**

Generate English/numeric text and a table with Pillow's portable font path, retain the existing Windows Korean fixture as a separate case, mount exact model cache and profile directories read-only, set `network_mode: none`, run as uid 10001 and write pytest temp only under `/tmp`.

- [x] **Step 4: Verify helper GREEN**

Run the Step 2 command with basetemp `.local-data/pytest-ocr-portability-green` and the actual-smoke flag unset.

Expected: portable contract tests pass; actual inference cases skip with an explicit reason.

- [ ] **Step 5: Build and run actual Linux CPU smoke**

Run: `docker compose -f infrastructure/compose/compose.yaml build worker ocr-linux-cpu-smoke`

Run: `docker compose -f infrastructure/compose/compose.yaml run --rm ocr-linux-cpu-smoke`

Expected: exact model integrity, text, table and bbox actual inference tests pass with no network.

- [x] **Step 6: Verify both image boundaries**

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify-backend-image-footprint.ps1 -Image ai-workshop-backend:local -ExpectedOcrRuntime absent`

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify-backend-image-footprint.ps1 -Image ai-workshop-backend-ocr-cpu:local -ExpectedOcrRuntime cpu -MaximumImageBytes 20GB`

Expected: both scripts pass; the OCR ceiling is only a safety guard while actual size is recorded for a later evidence-based limit.

### Task 6: Full verification and documentation

**Files:**
- Modify: `docs/architecture/system-design.md`
- Modify: `docs/architecture/repository-structure.md`
- Modify: `docs/runbooks/local-development.md`
- Create: `docs/worklogs/2026-09-06-linux-ocr-runtime-admin-topology.md`
- Modify: `WORKBOARD.md`

**Interfaces:**
- Records: exact image IDs/sizes, Linux CPU smoke result, GPU unverified boundary, cache delta
- Keeps: recent completed work at maximum five entries

- [x] **Step 1: Run backend verification**

Run focused topology/API/Compose tests, full backend unit tests with a fresh `.local-data` basetemp, `ruff check backend/src backend/tests`, `mypy backend/src`, and OpenAPI contract.

- [x] **Step 2: Run frontend verification**

Run `pnpm --dir frontend test --run`, `pnpm --dir frontend typecheck`, `pnpm --dir frontend lint`, `pnpm --dir frontend api:check`, and `pnpm --dir frontend build` sequentially.

- [x] **Step 3: Inspect Docker/cache without deleting**

Run `docker image inspect` for the two exact project images and `docker system df -v`. Record only project-specific image sizes and the observed build-cache delta; do not prune.

- [x] **Step 4: Update canonical docs and worklog**

Document the runtime targets, owner route, network-off smoke command, honest live-observation boundary and GPU gate. Move this task into recent completions while retaining at most five entries.

- [x] **Step 5: Review staged scope and commit**

Stage only files from this plan, run `git diff --cached --check`, inspect `git diff --cached --name-status`, and commit the verified implementation without pushing unless the user asks.
