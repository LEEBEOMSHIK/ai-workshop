# AI Workshop 1단계 작업소 기반 구현 계획

> **실행 지침:** 이 계획은 승인된 설계를 작은 테스트 우선 작업으로 나눈 실행 문서다. 각 작업은 실패하는 테스트 작성, 최소 구현, 전체 검증, 관련 파일만 커밋하는 순서로 수행한다.

**목표:** React와 FastAPI 기반의 로컬 우선 작업소를 만들고, 소유자 인증, 계층형 지식 공간, 폴더·문서·버전, 영속적인 비동기 작업 상태, 교체 가능한 RAG 모델 프로파일 등록 구조를 제공한다.

**범위:** 이번 단계는 플랫폼 기반과 RAG 설정 계약까지만 구현한다. 문서 파싱, 청킹, Elasticsearch 색인, BM25·bi-encoder·RRF 검색, 의미 하이라이트와 LLM 답변 생성은 후속 `RAG AI 검색` 구현 계획에서 다룬다.

**아키텍처:** 단일 저장소 안에 React SPA, FastAPI API, 같은 Python 패키지를 사용하는 Celery worker를 둔다. 업무 규칙은 애플리케이션·도메인 계층에, PostgreSQL·Redis·로컬 파일 저장소는 어댑터에 둔다. 브라우저는 같은 출처의 `/api/v1`만 호출하며 인증 토큰은 HttpOnly 쿠키로 전달한다. PostgreSQL의 `jobs`가 작업 상태 정본이고 Redis는 전달용 브로커로만 사용한다.

**기술 선택:** Node.js 22.12 이상 23 미만, pnpm 10, React, TypeScript, Vite, React Router Data Mode, Vitest, Testing Library, Python 3.13, uv, FastAPI, Pydantic Settings, SQLAlchemy 2 async, psycopg 3, Alembic, PyJWT, pwdlib Argon2, Celery 5.6, Redis, pytest, pytest-asyncio, httpx, Ruff, mypy를 사용한다. 버전은 생성 시점의 호환 버전을 lockfile에 고정한다.

**관련 설계:** `docs/architecture/system-design.md`, `docs/architecture/repository-structure.md`, `docs/labs/rag/design.md`, `docs/decisions/0001-modular-monolith.md`, `docs/decisions/0002-local-first-data-boundary.md`

---

## 공개 계약

### API 경로

| 기능 | 메서드와 경로 | 핵심 응답 |
|---|---|---|
| 상태 확인 | `GET /api/v1/health` | `{"status":"ok"}` |
| 로그인 | `POST /api/v1/auth/login` | HttpOnly 쿠키와 현재 사용자 |
| 현재 사용자 | `GET /api/v1/auth/me` | 사용자 ID, 이름, 이메일, 역할 |
| 로그아웃 | `POST /api/v1/auth/logout` | 쿠키 삭제, `204` |
| 지식 공간 | `GET/POST /api/v1/workspaces` | 허용된 지식 공간 목록·생성 |
| 폴더 | `GET/POST /api/v1/workspaces/{workspace_id}/folders` | 계층형 폴더 |
| 문서 | `GET/POST /api/v1/workspaces/{workspace_id}/documents` | 문서 메타데이터·업로드 |
| 문서 버전 | `GET/POST /api/v1/documents/{document_id}/versions` | 불변 버전과 처리 작업 |
| 작업 상태 | `GET /api/v1/jobs/{job_id}` | 상태, 단계, 오류 코드, 시각 |
| 모델 정의 | `GET/POST /api/v1/rag/models` | 임베딩·리랭커·LLM 모델 정의 |
| 프로파일 | `GET/POST /api/v1/rag/profiles/{kind}` | 색인·검색·생성 프로파일 버전 |

모든 ID는 UUID다. 시간은 UTC ISO 8601 문자열이다. 오류는 `{"error":{"code":"...","message":"...","correlation_id":"..."}}` 형태로 통일한다. 로그인과 상태 확인 외 API는 인증이 필요하다.

### 핵심 타입

```python
class WorkspaceKind(StrEnum):
    COMPANY = "company"
    TEAM = "team"
    PERSONAL = "personal"
    TEMPORARY = "temporary"

class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

class ModelKind(StrEnum):
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    LLM = "llm"

class ProfileKind(StrEnum):
    INDEXING = "indexing"
    RETRIEVAL = "retrieval"
    GENERATION = "generation"
```

- `company`는 전사 등록 문서, `personal`은 본인 문서, `temporary`는 만료 가능한 임시 파일 영역이다.
- `team`은 스키마와 API 검증에는 포함하지만 이번 단계 UI의 생성 선택지에는 노출하지 않는다.
- 문서 권한은 우선 지식 공간 멤버십을 상속한다. 문서별 예외 권한은 실제 요구가 생길 때 별도 ADR로 추가한다.
- `AssetVersion`은 체크섬과 저장소 키가 불변이며 새 버전 처리 성공 후에만 `Document.active_version_id`를 원자적으로 바꾼다.
- 프로파일은 생성 후 불변이다. 변경은 새 버전을 만들며, `is_default` 승격은 이번 단계에서 평가 완료 상태인 프로파일에만 허용한다.

---

## Task 1: 저장소 도구 체인과 실행 골격

**Files:**

- Create: `.editorconfig`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/router.tsx`
- Create: `frontend/src/app/App.test.tsx`
- Create: `frontend/src/test/setup.ts`
- Create: `backend/pyproject.toml`
- Create: `backend/src/ai_workshop/__init__.py`
- Create: `backend/src/ai_workshop/main.py`
- Create: `backend/tests/test_health.py`
- Create: `infrastructure/compose/compose.yaml`
- Modify: `README.md`

- [ ] **1.1 프론트엔드 실패 테스트를 작성한다.**

```tsx
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "./router";

it("renders the workshop shell", async () => {
  const router = createMemoryRouter(routes, { initialEntries: ["/"] });
  render(<RouterProvider router={router} />);
  expect(await screen.findByRole("heading", { name: "AI Workshop" })).toBeVisible();
});
```

- [ ] **1.2 `pnpm --dir frontend test --run`을 실행해 앱 파일 부재로 실패하는지 확인한다.**
- [ ] **1.3 React Router 기반 최소 앱 셸과 테스트 설정을 구현한다.**
- [ ] **1.4 백엔드 실패 테스트를 작성한다.**

```python
from fastapi.testclient import TestClient
from ai_workshop.main import app

def test_health() -> None:
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **1.5 `uv run pytest tests/test_health.py -q`를 `backend/`에서 실행해 엔드포인트 부재로 실패하는지 확인한다.**
- [ ] **1.6 `create_app()` 팩터리, `/api/v1/health`, 앱 버전과 개발 CORS 설정을 구현한다.**
- [ ] **1.7 PostgreSQL 17과 Redis 8 서비스, healthcheck, 명명된 로컬 볼륨을 `infrastructure/compose/compose.yaml`에 정의한다. Elasticsearch와 모델 런타임은 넣지 않는다.**
- [ ] **1.8 `.local-data/`, `.env`, `node_modules`, Python 캐시, 생성 OpenAPI 파일을 `.gitignore`에 추가하고 `.idea/`는 수정하거나 추적하지 않는다.**
- [ ] **1.9 `corepack enable`, `pnpm install`, `uv sync --all-groups`, 두 테스트를 실행해 통과를 확인한다.**
- [ ] **1.10 `git add`에 Task 1 파일만 지정하고 `git commit -m "build:scaffold-workshop-apps"`로 커밋한다.**

## Task 2: 백엔드 설정, 데이터베이스와 공통 오류 계약

**Files:**

- Create: `backend/src/ai_workshop/config.py`
- Create: `backend/src/ai_workshop/shared/db.py`
- Create: `backend/src/ai_workshop/shared/errors.py`
- Create: `backend/src/ai_workshop/shared/models.py`
- Create: `backend/src/ai_workshop/shared/request_context.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/tests/unit/test_config.py`
- Create: `backend/tests/api/test_errors.py`
- Modify: `backend/src/ai_workshop/main.py`

- [ ] **2.1 환경 변수 접두사, 비밀값 검증, 로컬 객체 저장 경로를 검증하는 실패 테스트를 작성한다.**

```python
def test_settings_use_ai_workshop_prefix(monkeypatch) -> None:
    monkeypatch.setenv("AI_WORKSHOP_ENVIRONMENT", "test")
    monkeypatch.setenv("AI_WORKSHOP_SECRET_KEY", "x" * 32)
    settings = Settings()
    assert settings.environment == "test"
    assert settings.object_store_root.name == "objects"
```

- [ ] **2.2 `uv run pytest tests/unit/test_config.py -q`의 실패를 확인한 뒤 `Settings`와 테스트 전용 설정 오버라이드를 구현한다.**
- [ ] **2.3 `Base`, `TimestampMixin`, async engine·세션 팩터리와 요청 단위 세션 의존성을 구현한다. `AsyncSession`을 동시 태스크 사이에서 공유하지 않는다.**
- [ ] **2.4 공통 오류 응답 실패 테스트를 작성한다. 존재하지 않는 경로는 `error.code=not_found`와 응답 헤더·본문의 동일한 correlation ID를 반환해야 한다.**
- [ ] **2.5 correlation ID 미들웨어, `AppError`, 예외 핸들러와 구조화 로그 필터를 구현한다. 본문·쿠키·비밀값은 로그에 넣지 않는다.**
- [ ] **2.6 Alembic async 환경을 구성하고 `uv run alembic check`가 메타데이터 연결을 읽는지 확인한다.**
- [ ] **2.7 `uv run pytest -q`, `uv run ruff check .`, `uv run mypy src`를 통과시킨다.**
- [ ] **2.8 `git commit -m "feat:establish-backend-foundation"`으로 Task 2 파일만 커밋한다.**

## Task 3: 소유자 인증과 브라우저 세션

**Files:**

- Create: `backend/src/ai_workshop/platform/identity/domain.py`
- Create: `backend/src/ai_workshop/platform/identity/models.py`
- Create: `backend/src/ai_workshop/platform/identity/schemas.py`
- Create: `backend/src/ai_workshop/platform/identity/repository.py`
- Create: `backend/src/ai_workshop/platform/identity/service.py`
- Create: `backend/src/ai_workshop/platform/identity/api.py`
- Create: `backend/src/ai_workshop/platform/identity/cli.py`
- Create: `backend/alembic/versions/0001_identity.py`
- Create: `backend/tests/unit/platform/identity/test_passwords.py`
- Create: `backend/tests/integration/platform/identity/test_auth_api.py`
- Create: `frontend/src/platform/identity/api.ts`
- Create: `frontend/src/platform/identity/LoginPage.tsx`
- Create: `frontend/src/platform/identity/LoginPage.test.tsx`
- Create: `frontend/src/platform/identity/session.ts`
- Modify: `backend/src/ai_workshop/main.py`
- Modify: `frontend/src/app/router.tsx`

- [ ] **3.1 Argon2 해시가 원문과 다르고 올바른 비밀번호만 검증하는 실패 테스트를 작성한다.**
- [ ] **3.2 `PasswordHasher` 포트와 pwdlib 어댑터를 구현한다.**
- [ ] **3.3 인증 통합 테스트를 작성한다. 로그인 전 `/auth/me`는 `401`, 올바른 로그인은 `HttpOnly; SameSite=Lax` 쿠키를 설정하고, 이후 `/auth/me`는 소유자를 반환하며 로그아웃은 쿠키를 지운다.**
- [ ] **3.4 `User`, `UserRole.OWNER`, 사용자 테이블과 고유 이메일 마이그레이션을 구현한다. 이메일은 비교용 정규화 값을 별도로 저장한다.**
- [ ] **3.5 JWT의 `sub`, `iat`, `exp`, `jti`를 검증하고 환경별 `Secure` 쿠키 설정을 적용한다. 토큰이나 비밀번호는 응답·로그에 노출하지 않는다.**
- [ ] **3.6 `uv run ai-workshop bootstrap-owner --name "Workshop Owner" --email "owner@example.test"` 명령을 구현한다. 비밀번호는 터미널에서 숨김 입력하고 기존 소유자가 있으면 갱신하지 않고 명시적으로 실패한다.**
- [ ] **3.7 로그인 UI 실패 테스트를 작성한다. 폼 제출 후 사용자 이름이 보이고 잘못된 자격 증명은 일반화된 오류를 표시해야 한다.**
- [ ] **3.8 `credentials: "include"`를 사용하는 인증 API, 로그인 페이지, 세션 loader와 보호 route를 구현한다.**
- [ ] **3.9 백엔드 전체 테스트·린트·타입 검사와 프론트엔드 테스트·타입 검사를 실행한다.**
- [ ] **3.10 `git commit -m "feat:add-owner-authentication"`으로 Task 3 파일만 커밋한다.**

## Task 4: 계층형 지식 공간과 멤버십

**Files:**

- Create: `backend/src/ai_workshop/platform/workspaces/domain.py`
- Create: `backend/src/ai_workshop/platform/workspaces/models.py`
- Create: `backend/src/ai_workshop/platform/workspaces/schemas.py`
- Create: `backend/src/ai_workshop/platform/workspaces/repository.py`
- Create: `backend/src/ai_workshop/platform/workspaces/service.py`
- Create: `backend/src/ai_workshop/platform/workspaces/api.py`
- Create: `backend/alembic/versions/0002_workspaces.py`
- Create: `backend/tests/unit/platform/workspaces/test_workspace_rules.py`
- Create: `backend/tests/integration/platform/workspaces/test_workspace_api.py`
- Create: `frontend/src/platform/workspaces/api.ts`
- Create: `frontend/src/platform/workspaces/WorkspacePage.tsx`
- Create: `frontend/src/platform/workspaces/WorkspacePage.test.tsx`
- Modify: `frontend/src/app/router.tsx`

- [ ] **4.1 `WorkspaceKind`과 생성 규칙 실패 테스트를 작성한다. 개인 공간은 사용자당 하나, 임시 공간은 `expires_at` 필수, 전사 공간 생성은 소유자만 가능해야 한다.**
- [ ] **4.2 `Workspace`, `WorkspaceMembership`, 역할과 저장소 포트를 구현하고 마이그레이션에 고유 제약을 둔다.**
- [ ] **4.3 목록 API가 멤버십 없는 공간을 반환하지 않는 통합 테스트를 먼저 작성한다. 회사·개인·임시 공간은 반환하고 만료된 임시 공간은 기본 목록에서 제외한다.**
- [ ] **4.4 서비스에서 사용자 범위를 강제한 뒤 CRUD API를 구현한다. 저장소 필터 누락이 있어도 서비스에서 접근을 재검증한다.**
- [ ] **4.5 workspace 목록 UI 테스트를 작성한다. 회사·개인·임시 배지를 표시하고 생성 폼에는 팀 공간을 노출하지 않아야 한다.**
- [ ] **4.6 지식 공간 선택·생성 UI와 `/workspaces/:workspaceId` route를 구현한다.**
- [ ] **4.7 관련 백엔드·프론트엔드 테스트, 타입 검사와 린트를 통과시킨다.**
- [ ] **4.8 `git commit -m "feat:add-knowledge-workspaces"`로 Task 4 파일만 커밋한다.**

## Task 5: 폴더, 문서와 불변 파일 버전

**Files:**

- Create: `backend/src/ai_workshop/platform/assets/domain.py`
- Create: `backend/src/ai_workshop/platform/assets/models.py`
- Create: `backend/src/ai_workshop/platform/assets/schemas.py`
- Create: `backend/src/ai_workshop/platform/assets/repository.py`
- Create: `backend/src/ai_workshop/platform/assets/service.py`
- Create: `backend/src/ai_workshop/platform/assets/api.py`
- Create: `backend/src/ai_workshop/platform/assets/storage.py`
- Create: `backend/src/ai_workshop/infrastructure/object_store/local.py`
- Create: `backend/alembic/versions/0003_assets.py`
- Create: `backend/tests/unit/platform/assets/test_versions.py`
- Create: `backend/tests/integration/platform/assets/test_asset_api.py`
- Create: `backend/tests/integration/infrastructure/test_local_object_store.py`
- Create: `frontend/src/platform/assets/api.ts`
- Create: `frontend/src/platform/assets/DocumentBrowser.tsx`
- Create: `frontend/src/platform/assets/DocumentBrowser.test.tsx`
- Create: `frontend/src/platform/assets/UploadDialog.tsx`
- Modify: `frontend/src/platform/workspaces/WorkspacePage.tsx`

- [ ] **5.1 `ObjectStore` Protocol을 다음 계약으로 테스트부터 작성한다.**

```python
class ObjectStore(Protocol):
    async def put(self, key: str, source: AsyncIterator[bytes]) -> StoredObject: ...
    async def open(self, key: str) -> AsyncIterator[bytes]: ...
    async def delete(self, key: str) -> None: ...
```

- [ ] **5.2 로컬 어댑터가 설정 루트 밖의 키를 거부하고 임시 파일에 쓴 뒤 원자적으로 이동하며 SHA-256과 크기를 반환하도록 구현한다.**
- [ ] **5.3 폴더 순환 방지, 동일 부모 내 이름 고유성, 버전 번호 단조 증가, 활성 버전 전환 규칙의 실패 테스트를 작성한다.**
- [ ] **5.4 `Folder`, `Document`, `AssetVersion`, `VersionStatus` 모델·마이그레이션과 서비스를 구현한다. 원본 파일명은 표시용으로만 사용하고 저장소 키에는 사용하지 않는다.**
- [ ] **5.5 허용 MIME과 확장자(`pdf`, `docx`, `pptx`, `xlsx`, `txt`, `md`, `html`)를 검증하는 업로드 API 통합 테스트를 작성한다. 1단계는 저장과 작업 생성까지만 하며 파싱 완료로 표시하지 않는다.**
- [ ] **5.6 스트리밍 업로드, 크기 제한, 중복 체크섬 기록과 새 버전 API를 구현한다. 다른 지식 공간의 문서 ID 접근은 존재 여부를 숨기기 위해 `404`를 반환한다.**
- [ ] **5.7 문서 브라우저 UI 테스트를 작성한다. 폴더 탐색, 버전 표시, 업로드 진행·오류 상태를 검증한다.**
- [ ] **5.8 문서 브라우저와 업로드 대화상자를 구현한다. 검색·미리보기 버튼은 후속 단계 전까지 렌더링하지 않는다.**
- [ ] **5.9 관련 전체 검증을 실행하고 `git commit -m "feat:add-versioned-document-storage"`로 커밋한다.**

## Task 6: 영속 작업 상태와 비동기 worker

**Files:**

- Create: `backend/src/ai_workshop/platform/jobs/domain.py`
- Create: `backend/src/ai_workshop/platform/jobs/models.py`
- Create: `backend/src/ai_workshop/platform/jobs/repository.py`
- Create: `backend/src/ai_workshop/platform/jobs/service.py`
- Create: `backend/src/ai_workshop/platform/jobs/api.py`
- Create: `backend/src/ai_workshop/worker.py`
- Create: `backend/src/ai_workshop/platform/assets/tasks.py`
- Create: `backend/alembic/versions/0004_jobs.py`
- Create: `backend/tests/unit/platform/jobs/test_job_state.py`
- Create: `backend/tests/integration/platform/jobs/test_jobs_api.py`
- Create: `backend/tests/integration/platform/assets/test_asset_task.py`
- Create: `frontend/src/platform/jobs/api.ts`
- Create: `frontend/src/platform/jobs/JobStatus.tsx`
- Create: `frontend/src/platform/jobs/JobStatus.test.tsx`
- Modify: `backend/src/ai_workshop/platform/assets/service.py`
- Modify: `infrastructure/compose/compose.yaml`

- [ ] **6.1 허용 상태 전이 `queued→running→succeeded|failed`와 종단 상태 변경 금지 테스트를 작성한다.**
- [ ] **6.2 `Job`에 `type`, `idempotency_key`, `status`, `stage`, `attempt`, `error_code`, `error_message`, 시작·종료 시각을 만들고 상태 전이 서비스를 구현한다.**
- [ ] **6.3 같은 사용자·문서 버전·작업 타입의 idempotency key가 중복 작업을 만들지 않는 통합 테스트를 작성한다.**
- [ ] **6.4 Celery 앱과 Redis 브로커를 구성한다. 결과 backend는 사용하지 않고 작업 시작·성공·실패를 각각 짧은 DB 트랜잭션으로 기록한다.**
- [ ] **6.5 첫 worker 작업은 업로드 객체의 존재·체크섬을 재검증하고 `stored` 단계로 끝낸다. 파싱을 흉내 내거나 성공으로 기록하지 않는다. 재시도 가능 오류와 영구 오류를 구분한다.**
- [ ] **6.6 작업 조회 API가 소유 지식 공간 작업만 반환하고 내부 예외 대신 안정된 오류 코드를 반환하는지 테스트하고 구현한다.**
- [ ] **6.7 업로드 후 상태 배지와 수동 새로고침을 제공하는 UI 테스트·컴포넌트를 구현한다. 실시간 전송은 후속 최적화로 남긴다.**
- [ ] **6.8 Compose worker 서비스를 추가하고 `api`, `worker`, `postgres`, `redis` health·dependency를 검증한다.**
- [ ] **6.9 eager 모드 통합 테스트와 전체 검증을 통과시킨 뒤 `git commit -m "feat:add-durable-background-jobs"`로 커밋한다.**

## Task 7: RAG 모델 정의와 버전 프로파일 등록

**Files:**

- Create: `backend/src/ai_workshop/labs/rag/models/domain.py`
- Create: `backend/src/ai_workshop/labs/rag/models/models.py`
- Create: `backend/src/ai_workshop/labs/rag/models/schemas.py`
- Create: `backend/src/ai_workshop/labs/rag/models/repository.py`
- Create: `backend/src/ai_workshop/labs/rag/models/service.py`
- Create: `backend/src/ai_workshop/labs/rag/models/api.py`
- Create: `backend/alembic/versions/0005_rag_profiles.py`
- Create: `backend/tests/unit/labs/rag/models/test_profiles.py`
- Create: `backend/tests/integration/labs/rag/models/test_profile_api.py`
- Create: `frontend/src/labs/rag/models/api.ts`
- Create: `frontend/src/labs/rag/models/ModelLabPage.tsx`
- Create: `frontend/src/labs/rag/models/ModelLabPage.test.tsx`
- Create: `model-profiles/rag/indexing/baseline.yaml`
- Create: `model-profiles/rag/retrieval/bm25.yaml`
- Create: `model-profiles/rag/retrieval/hybrid-rrf.yaml`
- Create: `model-profiles/rag/generation/local-baseline.yaml`
- Modify: `frontend/src/app/router.tsx`

- [ ] **7.1 모델과 프로파일 불변성 테스트를 작성한다. 같은 종류·이름·버전은 중복 불가하고 생성된 설정을 수정할 수 없으며 새 버전만 추가할 수 있어야 한다.**
- [ ] **7.2 `ModelDefinition`, `Profile`, `ProfileModelBinding`, `EvaluationState` 모델과 마이그레이션을 구현한다. 설정은 검증된 JSON으로 DB에 보관하고 비밀값 대신 환경 변수 참조 키만 허용한다.**
- [ ] **7.3 종류별 검증 테스트를 작성한다. 색인은 chunker+embedding, 검색은 BM25/dense/RRF와 선택적 reranker, 생성은 LLM+prompt 참조를 받아야 한다. 검색 프로파일에 LLM을 직접 넣으면 거부한다.**
- [ ] **7.4 YAML을 Pydantic 스키마로 검증해 등록하는 서비스와 API를 구현한다. 평가 상태가 `passed`가 아니면 기본 프로파일로 승격하지 못하게 한다.**
- [ ] **7.5 기본 프로파일 파일에 다음 비교 축을 명시한다: BM25 단독, BM25+dense+RRF, 선택적 reranker. 임베딩과 LLM은 구체 공급자 이름을 업무 코드에 고정하지 않고 모델 정의 ID로 연결한다.**
- [ ] **7.6 Model Lab UI 테스트와 화면을 구현한다. 임베딩·리랭커·LLM 정의, 색인·검색·생성 프로파일을 별도 표로 표시하고 새 버전 등록 폼을 제공한다. 실제 모델 실행 버튼은 표시하지 않는다.**
- [ ] **7.7 전체 검증 후 `git commit -m "feat:add-rag-model-profile-registry"`로 Task 7 파일만 커밋한다.**

## Task 8: OpenAPI 계약과 생성 TypeScript 타입

**Files:**

- Create: `backend/tools/export_openapi.py`
- Create: `backend/tests/contract/test_openapi.py`
- Create: `frontend/openapi-ts.config.mjs`
- Create: `frontend/src/shared/api/schema.d.ts`
- Create: `frontend/src/shared/api/client.ts`
- Create: `frontend/src/shared/api/client.test.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/src/platform/identity/api.ts`
- Modify: `frontend/src/platform/workspaces/api.ts`
- Modify: `frontend/src/platform/assets/api.ts`
- Modify: `frontend/src/platform/jobs/api.ts`
- Modify: `frontend/src/labs/rag/models/api.ts`

- [ ] **8.1 OpenAPI에 모든 공개 경로, 공통 오류, 보안 스키마와 고유 `operationId`가 존재하는 계약 테스트를 작성한다.**
- [ ] **8.2 결정적인 키 순서와 마지막 개행을 사용하는 OpenAPI export 도구를 구현한다. 출력은 `backend/build/openapi.json`이며 Git에는 추가하지 않는다.**
- [ ] **8.3 `openapi-typescript`를 개발 의존성으로 추가하고 `pnpm api:generate`가 `frontend/src/shared/api/schema.d.ts`를 만드는 스크립트를 정의한다. 생성 파일은 검토 가능한 계약 산출물로 Git에 포함한다.**
- [ ] **8.4 공통 fetch client 실패 테스트를 작성한다. 쿠키 포함, JSON·multipart 처리, correlation ID가 포함된 typed error를 검증한다.**
- [ ] **8.5 각 기능 API 래퍼의 수동 응답 타입을 제거하고 생성 타입을 사용하도록 변경한다. 런타임 입력 검증은 백엔드 Pydantic이 담당한다.**
- [ ] **8.6 OpenAPI를 다시 생성했을 때 `git diff --exit-code frontend/src/shared/api/schema.d.ts`가 깨끗한지 확인하는 `pnpm api:check`를 추가한다.**
- [ ] **8.7 양쪽 전체 검증을 통과시킨 뒤 `git commit -m "build:enforce-openapi-contract"`로 커밋한다.**

## Task 9: 로컬 통합 실행, 접근 경계와 인계 문서

**Files:**

- Create: `backend/tests/e2e/test_foundation_flow.py`
- Create: `scripts/smoke.ps1`
- Create: `docs/runbooks/local-development.md`
- Modify: `infrastructure/compose/compose.yaml`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `WORKBOARD.md`

- [ ] **9.1 다음 전체 흐름의 실패하는 E2E 테스트를 작성한다: 소유자 로그인 → 개인 공간 확인 → 폴더 생성 → 문서 업로드 → worker 완료 → 새 버전 업로드 → 버전 목록 확인 → 모델·프로파일 등록.**
- [ ] **9.2 별도 사용자 fixture로 회사 공간 접근은 허용되고 다른 개인 공간·문서·작업 접근은 `404`인지 검증한다. 임시 공간 만료도 검증한다.**
- [ ] **9.3 Compose에서 API와 worker 이미지를 같은 backend 이미지로 빌드하고 마이그레이션은 명시적 one-shot 명령으로 실행한다. 여러 프로세스가 자동으로 동시에 마이그레이션하지 않게 한다.**
- [ ] **9.4 `scripts/smoke.ps1`에 환경 점검, Compose 기동, health 대기, 마이그레이션, E2E 테스트를 작성한다. 스크립트는 실패 시 non-zero를 반환하고 비밀값을 출력하지 않는다.**
- [ ] **9.5 로컬 개발 문서에 최초 설치, 환경 파일, 소유자 부트스트랩, API·frontend·worker 실행, DB 마이그레이션, 테스트와 문제 해결 명령을 기록한다.**
- [ ] **9.6 `AGENTS.md`의 현재 단계를 실제 구현 상태로 갱신하되 200줄 이하를 유지한다. 상세 실행법은 runbook 링크로만 연결한다.**
- [ ] **9.7 `WORKBOARD.md` 최근 완료를 최대 5개로 갱신하고 다음 작업을 `RAG AI 검색 구현 계획`으로 바꾼다.**
- [ ] **9.8 최종 검증 명령을 실행한다.**

```powershell
cd backend
uv lock --check
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run alembic check

cd ../frontend
pnpm test --run
pnpm typecheck
pnpm lint
pnpm build
pnpm api:check

cd ..
docker compose -f infrastructure/compose/compose.yaml config --quiet
./scripts/smoke.ps1
git diff --check
```

예상 결과는 모든 명령의 종료 코드가 0이고, E2E 테스트가 권한 경계와 전체 기반 흐름을 통과하며, `.idea/`와 로컬 데이터가 추적되지 않는 것이다.

- [ ] **9.9 `git status --short`에서 이번 작업 파일과 기존 사용자 소유 `.idea/`만 확인하고, Task 9 파일만 `git commit -m "docs:complete-workshop-foundation"`으로 커밋한다.**

---

## 완료 조건

- [ ] 브라우저에서 소유자 로그인 후 회사·개인·임시 지식 공간을 구분해 사용할 수 있다.
- [ ] 폴더와 여러 형식의 문서를 저장하고 불변 버전을 조회할 수 있다.
- [ ] 업로드 작업의 상태가 PostgreSQL에 남고 worker 재시도에도 중복 처리되지 않는다.
- [ ] 임베딩·리랭커·LLM 모델과 색인·검색·생성 프로파일을 독립적으로 버전 등록할 수 있다.
- [ ] 플랫폼 계층이 RAG 구현에 의존하지 않고, 모든 사용자 범위 조회에 접근 경계가 적용된다.
- [ ] OpenAPI와 TypeScript 타입이 같은 계약을 사용한다.
- [ ] 단위·통합·E2E 테스트, 정적 타입 검사, 린트와 빌드가 모두 통과한다.
- [ ] `AGENTS.md`는 200줄 이하이고 `WORKBOARD.md`의 최근 완료는 5개 이하다.
- [ ] 민감 정보, 원본 문서, 로컬 데이터, `.idea/`가 커밋되지 않는다.

## 후속 계획 경계

다음 계획은 저장된 `AssetVersion`을 입력으로 받아 파서 → 정규화 → 청킹 → 임베딩 → Elasticsearch 병렬 색인 → ACL 선필터 → BM25·dense → RRF → 의미 하이라이트까지 구현한다. LLM 답변 생성은 검색 근거와 하이라이트가 안정된 뒤 같은 RAG 검색 계획의 후반 작업으로 추가한다.
