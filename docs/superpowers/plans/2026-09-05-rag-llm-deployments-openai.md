# RAG LLM Deployments and OpenAI Responses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RAG 생성 모델의 정체성과 실행 위치를 분리하고, 회사·지식 공간 데이터 정책과 관리자 승인을 거친 기존 로컬 런타임 또는 OpenAI Responses API의 정확한 Deployment Version으로 근거 제한 답변을 실행한다.

**Architecture:** 불변 Model Deployment Version과 Data Policy Version을 RAG 모델 레지스트리에 추가하고 Generation Profile은 정확한 Deployment Version에 결합한다. 검색 애플리케이션은 사용자 권한 확인 직후 정책·환경·승인 교집합을 판정한 다음 단일 Provider adapter를 선택하며, 구조화 출력과 인용 hard gate를 통과한 결과만 실행 메타데이터와 함께 반환한다. 첫 전달에서는 기존 local OpenAI-compatible adapter와 OpenAI Responses API만 실제로 지원하고 Codex SDK 및 다른 외부 Provider는 선택지에 노출하지 않는다.

**Tech Stack:** Python 3.13, FastAPI, Pydantic Settings, SQLAlchemy 2 async, Alembic, PostgreSQL, httpx, pytest, Next.js 16, React 19, TypeScript 5.9, Vitest, OpenAPI TypeScript

**Spec:** `docs/superpowers/specs/2026-09-05-multi-environment-llm-deployment-design.md`

## Global Constraints

- 작업은 `main`에서만 수행하고 별도 worktree를 만들지 않는다.
- 이번 전달의 실행 Provider는 `local_openai_compatible`과 `openai_responses`뿐이다.
- OpenAI Responses API를 먼저 완성하며 Codex SDK는 이 계획 완료 뒤 별도 계획으로 구현한다.
- Model Definition, Model Deployment identity, Model Deployment Version을 분리한다.
- Deployment Version, Generation Profile, Saved RAG Configuration Version과 Data Policy Version은 생성 뒤 수정하지 않는다.
- Generation Profile은 정확한 Deployment Version ID 하나를 참조하며 Deployment 변경은 검색 색인을 재구축하지 않는다.
- 외부 전송 판정은 `Deployment 환경 허용 ∩ Installation 정책 ∩ 모든 선택 Workspace 정책 ∩ 구성 승인`이다.
- 선택 Workspace 하나라도 외부 전송을 금지하면 질문·대화·Evidence를 외부 adapter에 전달하지 않는다.
- 첫 migration의 Installation 외부 전송 정책은 `deny`다.
- 실제 endpoint와 API key는 환경변수 또는 Secret Manager에만 두고 DB에는 allowlist된 reference만 저장한다.
- Provider 실패 시 다른 Deployment 또는 모델로 자동 fallback하지 않는다.
- 안전 오류 계약은 `deployment_not_allowed_in_environment`,
  `workspace_external_transfer_denied`, `provider_not_allowed`, `deployment_not_ready`,
  `provider_authentication_failed`, `provider_rate_limited`, `provider_timeout`,
  `provider_invalid_response`, `structured_output_invalid`, `citation_validation_failed`를
  Provider와 UI 전반에서 동일하게 사용한다.
- Provider 응답은 공통 `StructuredGeneration`으로 정규화하고 기존 인용 hard gate를 그대로 통과한다.
- 일반 로그와 감사 레코드에는 질문, 대화 본문, 문서 본문, prompt 본문, 생성 초안과 secret을 저장하지 않는다.
- 외부 전송 구성은 owner의 명시 승인 없이는 저장하지 않는다.
- 로그인 사용자는 질문 전 상시 disclosure와 답변 후 실제 실행 Provider·모델·위치·외부 전송 여부를 확인한다.
- 기존 model-bound Generation Profile과 Saved Configuration은 수정하지 않고 legacy read-only·`deployment_not_ready`로 유지한다.
- `references/`와 ACL 잠금 테스트 임시 폴더는 수정·stage·삭제하지 않는다.

---

### Task 0: 대화형 생성 RAG V2 기준선 고정

**Files:**
- Verify: `docs/superpowers/plans/2026-09-04-conversational-generative-rag-v2.md`
- Verify: `docs/worklogs/2026-09-04-conversational-generative-rag-v2.md`
- Modify: `WORKBOARD.md`

**Interfaces:**
- Consumes: 현재 작업 트리의 Generation Profile, 대화 문맥, local OpenAI-compatible adapter, migration `0015_rag_generation_v2` 구현
- Produces: 새 Deployment 작업이 의존할 수 있는 독립적인 V2 기준 커밋

- [ ] **Step 1: 현재 변경을 V2 범위와 사용자 소유 파일로 분류한다**

Run: `git status --short`

Expected: V2 구현 파일과 `references/`가 함께 보이며 `references/`는 이후 staging 목록에서 제외된다.

- [ ] **Step 2: V2 회귀 검증을 다시 실행한다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/generation tests/unit/labs/rag/configurations tests/integration/labs/rag/configurations tests/integration/labs/rag/search/test_search_api.py -q --basetemp "$env:TEMP/ai-workshop-v2-baseline"`

Expected: 모든 선택 테스트 PASS. ACL 잠금 저장소 내부 basetemp는 사용하지 않는다.

Run: `cd frontend; pnpm test --run; pnpm typecheck; pnpm lint; pnpm build; pnpm api:check`

Expected: Vitest, TypeScript, ESLint, Next build, OpenAPI drift check가 모두 exit code 0이다.

- [ ] **Step 3: V2 파일만 stage하고 범위를 확인한다**

```powershell
git add .env.example WORKBOARD.md backend/pyproject.toml backend/uv.lock backend/alembic/versions/0015_rag_generation_v2.py backend/src/ai_workshop/config.py backend/src/ai_workshop/labs/rag/configurations backend/src/ai_workshop/labs/rag/generation backend/src/ai_workshop/labs/rag/models/domain.py backend/src/ai_workshop/labs/rag/search backend/tests/integration/labs/rag/configurations backend/tests/integration/labs/rag/search/test_search_api.py backend/tests/unit/labs/rag/configurations backend/tests/unit/labs/rag/generation backend/tests/unit/labs/rag/models/test_profiles.py docs/decisions/0008-required-generation-optional-reranker.md docs/labs/rag/design.md docs/runbooks/local-development.md docs/superpowers/specs/2026-09-04-conversational-generative-rag-v2-design.md docs/superpowers/plans/2026-09-04-conversational-generative-rag-v2.md docs/worklogs/2026-09-04-conversational-generative-rag-v2.md frontend/src/app/styles.css frontend/src/features/rag/configurations frontend/src/features/rag/search frontend/src/shared/api/schema.d.ts model-profiles/rag/generation/local-baseline.yaml
git diff --cached --stat
git status --short
```

Expected: `references/`와 `backend/.pytest-nextjs-final-contract/`는 staged 목록에 없다.

- [ ] **Step 4: 기준선을 커밋한다**

Run: `git commit -m "feat(rag): add contextual grounded generation v2"`

Expected: V2 구현이 단일 커밋으로 남고 새 Deployment 작업은 깨끗한 기준선 위에서 시작한다.

---

### Task 1: Deployment와 Data Policy 도메인 계약

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/deployments/__init__.py`
- Create: `backend/src/ai_workshop/labs/rag/deployments/domain.py`
- Create: `backend/src/ai_workshop/labs/rag/policies/__init__.py`
- Create: `backend/src/ai_workshop/labs/rag/policies/domain.py`
- Test: `backend/tests/unit/labs/rag/deployments/test_domain.py`
- Test: `backend/tests/unit/labs/rag/policies/test_policy_resolution.py`
- Create: `docs/decisions/0009-model-deployments-and-data-policy.md`
- Modify: `docs/superpowers/specs/2026-09-05-multi-environment-llm-deployment-design.md`

**Interfaces:**
- Consumes: `ModelDefinition.id`, 현재 `Settings.environment`, 선택된 workspace ID 집합
- Produces: `ModelDeploymentVersion`, `ProviderKind`, `ExecutionLocation`, `DeploymentEnvironment`, `DeploymentCapability`, `InstallationDataPolicyVersion`, `WorkspaceDataPolicyVersion`, `PolicyDecision`, `resolve_external_transfer_policy(...)`

- [ ] **Step 1: 불변 Deployment 검증의 실패 테스트를 작성한다**

```python
def test_external_deployment_requires_external_transfer_contract() -> None:
    with pytest.raises(DeploymentValidationError, match="notice"):
        ModelDeploymentVersion.create(
            deployment_id=uuid4(), version=1, display_name="OpenAI 금융 답변",
            description="승인된 외부 생성", model_definition_id=uuid4(),
            provider=ProviderKind.OPENAI_RESPONSES,
            location=ExecutionLocation.EXTERNAL,
            allowed_environments=(DeploymentEnvironment.PRODUCTION,),
            provider_model_id="gpt-5-mini-2025-08-07",
            endpoint_ref="openai-responses", secret_ref="openai-primary",
            capabilities=frozenset({DeploymentCapability.STRUCTURED_OUTPUT}),
            external_transfer=True,
            transmitted_data_categories=("question", "bounded_history", "evidence"),
            data_processing_notice_ref=None,
            timeout_seconds=30.0, max_retries=1, retry_backoff_seconds=0.5,
            healthcheck_enabled=True, development_only=False, created_by=uuid4(),
        )
```

- [ ] **Step 2: Workspace 정책이 Installation 정책을 완화하지 못하는 실패 테스트를 작성한다**

```python
def test_workspace_policy_cannot_widen_installation_policy() -> None:
    installation = installation_policy(mode=OutboundMode.DENY)
    workspace = workspace_policy(
        mode=WorkspaceOutboundMode.APPROVED_PROVIDERS,
        providers=frozenset({ProviderKind.OPENAI_RESPONSES}),
    )
    with pytest.raises(DataPolicyValidationError, match="cannot widen"):
        resolve_external_transfer_policy(
            provider=ProviderKind.OPENAI_RESPONSES,
            installation=installation,
            workspaces=(workspace,),
        )
```

- [ ] **Step 3: 도메인 테스트가 아직 실패하는지 확인한다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/deployments/test_domain.py tests/unit/labs/rag/policies/test_policy_resolution.py -q --basetemp "$env:TEMP/ai-workshop-deployment-domain-red"`

Expected: 새 모듈 또는 타입을 찾지 못해 FAIL한다.

- [ ] **Step 4: 명시적 enum과 불변 도메인 타입을 구현한다**

```python
class ProviderKind(StrEnum):
    LOCAL_OPENAI_COMPATIBLE = "local_openai_compatible"
    OPENAI_RESPONSES = "openai_responses"

class ExecutionLocation(StrEnum):
    LOCAL = "local"
    ON_PREMISE = "on_premise"
    EXTERNAL = "external"

class DeploymentEnvironment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason_code: str | None
    installation_policy_version_id: UUID
    workspace_policy_version_ids: tuple[UUID, ...]
```

`ModelDeploymentVersion.create()`는 빈 이름, 0 이하 version/timeout, capability 누락, 외부 위치와 `external_transfer` 불일치, 외부 전송 범주·notice 누락, local Provider의 external 위치를 각각 거부한다. `resolve_external_transfer_policy()`는 Installation `deny`, Provider 미승인, Workspace `deny`, Workspace Provider 부분집합 위반을 구분된 reason code로 반환한다.

- [ ] **Step 5: ADR에 경계와 비목표를 기록하고 설계 상태를 승인 완료로 바꾼다**

```markdown
# ADR-0009: 모델 정체성과 실행 Deployment 및 데이터 정책을 분리한다

- 상태: 승인
- 결정: Generation Profile은 불변 Deployment Version을 참조한다.
- 결과: Provider 변경은 새 Deployment/Profile/Configuration version을 만들며 검색 색인을 재구축하지 않는다.
- 제외: Codex SDK와 타사 Provider adapter는 OpenAI 첫 전달이 검증된 뒤 별도 변경으로 추가한다.
```

- [ ] **Step 6: 도메인 테스트를 통과시킨다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/deployments/test_domain.py tests/unit/labs/rag/policies/test_policy_resolution.py -q --basetemp "$env:TEMP/ai-workshop-deployment-domain-green"`

Expected: PASS.

- [ ] **Step 7: 커밋한다**

```bash
git add backend/src/ai_workshop/labs/rag/deployments backend/src/ai_workshop/labs/rag/policies backend/tests/unit/labs/rag/deployments backend/tests/unit/labs/rag/policies docs/decisions/0009-model-deployments-and-data-policy.md docs/superpowers/specs/2026-09-05-multi-environment-llm-deployment-design.md
git commit -m "feat(rag): define llm deployment and data policy contracts"
```

---

### Task 2: Deployment·정책·승인·감사 영속성과 migration 0016

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/deployments/models.py`
- Create: `backend/src/ai_workshop/labs/rag/deployments/repository.py`
- Create: `backend/src/ai_workshop/labs/rag/policies/models.py`
- Create: `backend/src/ai_workshop/labs/rag/policies/repository.py`
- Create: `backend/src/ai_workshop/labs/rag/generation/audit_models.py`
- Create: `backend/src/ai_workshop/labs/rag/generation/audit.py`
- Modify: `backend/src/ai_workshop/labs/rag/models/models.py`
- Modify: `backend/src/ai_workshop/labs/rag/configurations/models.py`
- Modify: `backend/alembic/env.py`
- Create: `backend/alembic/versions/0016_rag_llm_deployments.py`
- Test: `backend/tests/integration/test_migration_0016_rag_llm_deployments.py`
- Test: `backend/tests/integration/labs/rag/deployments/test_repository.py`
- Test: `backend/tests/integration/labs/rag/policies/test_repository.py`

**Interfaces:**
- Consumes: Task 1 도메인 타입과 기존 `rag_model_definitions`, `rag_profiles`, `rag_configuration_versions`
- Produces: `SqlAlchemyDeploymentRepository`, `SqlAlchemyDataPolicyRepository`, `SqlAlchemyGenerationAuditRepository`, `ProfileDeploymentBindingRecord`, 외부 승인 snapshot 레코드

- [ ] **Step 1: migration 보존·기본 거부·legacy 변환 테스트를 작성한다**

```python
def test_upgrade_creates_deny_policy_and_preserves_legacy_bindings(connection) -> None:
    before = snapshot_generation_references(connection)
    upgrade_to(connection, "0016_rag_llm_deployments")
    policy = connection.execute(text(
        "select version, outbound_mode from rag_installation_data_policy_versions"
    )).one()
    after = snapshot_generation_references(connection)
    assert policy == (1, "deny")
    assert after.legacy_profile_bindings == before.legacy_profile_bindings
    assert after.legacy_configuration_bindings == before.legacy_configuration_bindings
    assert after.converted_deployments == before.convertible_local_llms
```

추가 테스트는 같은 deployment identity의 version 중복, workspace 정책 version 중복, secret literal 저장 방지 check, 새 Deployment를 참조할 때 downgrade 거부를 검증한다.

- [ ] **Step 2: migration 테스트를 실행해 실패를 확인한다**

Run: `cd backend; uv run pytest tests/integration/test_migration_0016_rag_llm_deployments.py -q --basetemp "$env:TEMP/ai-workshop-migration-0016-red"`

Expected: migration 파일이 없어 FAIL한다.

- [ ] **Step 3: SQLAlchemy 레코드와 관계를 구현한다**

```python
class ModelDeploymentVersionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_model_deployment_versions"
    __table_args__ = (UniqueConstraint("deployment_id", "version"),)
    deployment_id: Mapped[UUID] = mapped_column(ForeignKey("rag_model_deployments.id"))
    model_definition_id: Mapped[UUID] = mapped_column(ForeignKey("rag_model_definitions.id"))
    provider: Mapped[str] = mapped_column(String(48), nullable=False)
    location: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_model_id: Mapped[str] = mapped_column(String(180), nullable=False)
    endpoint_ref: Mapped[str | None] = mapped_column(String(120))
    secret_ref: Mapped[str | None] = mapped_column(String(120))

class ProfileDeploymentBindingRecord(Base):
    __tablename__ = "rag_generation_profile_deployments"
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("rag_profiles.id"), primary_key=True)
    deployment_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_model_deployment_versions.id", ondelete="RESTRICT"), nullable=False
    )
```

정책 version, 구성 승인, 승인-workspace snapshot, health check, 본문 없는 generation execution audit는 각각 별도 append-only table로 만든다. immutable trigger는 version row의 UPDATE/DELETE를 거부한다.

- [ ] **Step 4: migration에서 legacy를 제자리 수정하지 않고 새 version을 생성한다**

`provider=openai_compatible`, `data_policy=local_only`, 비어 있지 않은 `runtime_model`을 모두 가진 LLM마다 local Deployment Version을 만든다. 해당 모델에 결합된 Generation Profile마다 config를 복사한 다음 같은 이름의 `max(version)+1` Profile을 생성하고 새 deployment binding을 추가한다. 기존 profile-model binding과 saved configuration version은 그대로 둔다.

- [ ] **Step 5: repository round-trip 테스트를 작성하고 실행한다**

```python
saved = await repository.add_version(deployment)
loaded = await repository.get_version(saved.id)
assert loaded == saved
assert loaded.secret_ref == "openai-primary"
```

Run: `cd backend; uv run pytest tests/integration/labs/rag/deployments/test_repository.py tests/integration/labs/rag/policies/test_repository.py -q --basetemp "$env:TEMP/ai-workshop-deployment-repositories"`

Expected: PASS.

- [ ] **Step 6: 빈 PostgreSQL과 기존 0015 상태 모두에서 upgrade/downgrade 보호를 검증한다**

Run: `cd backend; uv run pytest tests/integration/test_migration_0016_rag_llm_deployments.py -q --basetemp "$env:TEMP/ai-workshop-migration-0016-green"`

Expected: 새 설치 upgrade PASS, legacy 참조 보존 PASS, 새 참조가 없는 downgrade PASS, 새 참조가 있을 때 안전 거부 PASS.

- [ ] **Step 7: 커밋한다**

```bash
git add backend/alembic backend/src/ai_workshop/labs/rag/deployments backend/src/ai_workshop/labs/rag/policies backend/src/ai_workshop/labs/rag/generation/audit.py backend/src/ai_workshop/labs/rag/generation/audit_models.py backend/src/ai_workshop/labs/rag/models/models.py backend/src/ai_workshop/labs/rag/configurations/models.py backend/tests/integration/test_migration_0016_rag_llm_deployments.py backend/tests/integration/labs/rag/deployments backend/tests/integration/labs/rag/policies
git commit -m "feat(rag): persist immutable llm deployments and policies"
```

---

### Task 3: Secret reference 해석과 Deployment 관리자 API

**Files:**
- Modify: `backend/src/ai_workshop/config.py`
- Modify: `.env.example`
- Create: `backend/src/ai_workshop/labs/rag/deployments/secrets.py`
- Create: `backend/src/ai_workshop/labs/rag/deployments/schemas.py`
- Create: `backend/src/ai_workshop/labs/rag/deployments/service.py`
- Create: `backend/src/ai_workshop/labs/rag/deployments/api.py`
- Modify: `backend/src/ai_workshop/main.py`
- Test: `backend/tests/unit/labs/rag/deployments/test_secret_resolver.py`
- Test: `backend/tests/integration/labs/rag/deployments/test_api.py`

**Interfaces:**
- Consumes: `SqlAlchemyDeploymentRepository`, owner authentication, settings maps
- Produces: `SecretReferenceResolver.resolve(ref) -> SecretStr`, Deployment 등록·조회 API,
  `/api/v1/rag/deployments/options`

- [ ] **Step 1: allowlist 밖 reference와 secret 응답 노출 방지 테스트를 작성한다**

```python
def test_secret_resolver_rejects_unknown_reference() -> None:
    resolver = SecretReferenceResolver({"openai-primary": SecretStr("secret")})
    with pytest.raises(SecretReferenceError, match="not configured"):
        resolver.resolve("request-controlled-name")

async def test_deployment_response_never_contains_secret(client, owner_headers) -> None:
    response = await client.post("/api/v1/admin/rag/deployments", headers=owner_headers, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["secret_configured"] is True
    assert "secret_ref" not in body
    assert "secret" not in response.text.casefold()
```

- [ ] **Step 2: 실패 테스트를 확인한다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/deployments/test_secret_resolver.py tests/integration/labs/rag/deployments/test_api.py -q --basetemp "$env:TEMP/ai-workshop-deployment-api-red"`

Expected: resolver와 route가 없어 FAIL한다.

- [ ] **Step 3: 환경변수 JSON map과 안전한 resolver를 구현한다**

```python
provider_endpoint_refs: dict[str, str] = Field(default_factory=dict)
provider_secret_refs: dict[str, SecretStr] = Field(default_factory=dict)

class SecretReferenceResolver:
    def resolve(self, reference: str) -> SecretStr:
        try:
            return self._allowlist[reference]
        except KeyError as exc:
            raise SecretReferenceError("The secret reference is not configured.") from exc
```

`.env.example`에는 실제 key 없이 `AI_WORKSHOP_PROVIDER_ENDPOINT_REFS={"openai-responses":"https://api.openai.com"}`와 빈 secret map 예시만 둔다. local legacy 설정은 migration 기간 동안 읽기 호환성을 유지한다.

- [ ] **Step 4: owner 전용 생성·version 추가 API와 사용자 안전 옵션 API를 구현한다**

```text
POST /api/v1/admin/rag/deployments
POST /api/v1/admin/rag/deployments/{deployment_id}/versions
GET  /api/v1/admin/rag/deployments
GET  /api/v1/rag/deployments/options
```

일반 옵션 응답은 표시 이름, 모델명·버전, Provider, 위치, 외부 전송, 허용 환경, capability, readiness와 안전한 reason code만 반환한다. endpoint reference와 secret reference는 owner 기술 상세에만 반환하되 secret 값은 어느 응답에도 반환하지 않는다.

- [ ] **Step 5: API 권한·불변 version·secret 위생 테스트를 통과시킨다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/deployments/test_secret_resolver.py tests/integration/labs/rag/deployments/test_api.py -q --basetemp "$env:TEMP/ai-workshop-deployment-api-green"`

Expected: owner 생성 201, 일반 사용자 생성 403, 조회 secret 비노출, 같은 identity/version 중복 409, unknown ref 422가 PASS한다.

- [ ] **Step 6: 커밋한다**

```bash
git add .env.example backend/src/ai_workshop/config.py backend/src/ai_workshop/main.py backend/src/ai_workshop/labs/rag/deployments backend/tests/unit/labs/rag/deployments backend/tests/integration/labs/rag/deployments
git commit -m "feat(rag): add secure deployment administration"
```

---

### Task 4: Installation·Workspace 데이터 정책 API와 실행 판정

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/policies/schemas.py`
- Create: `backend/src/ai_workshop/labs/rag/policies/service.py`
- Create: `backend/src/ai_workshop/labs/rag/policies/api.py`
- Modify: `backend/src/ai_workshop/main.py`
- Test: `backend/tests/integration/labs/rag/policies/test_api.py`
- Test: `backend/tests/unit/labs/rag/policies/test_execution_policy.py`

**Interfaces:**
- Consumes: Task 1 policy domain, Task 2 repository, owner authentication
- Produces: `GenerationPolicyResolver.resolve(deployment, workspace_ids) -> PolicyDecision`, Installation/Workspace 정책 version API

- [ ] **Step 1: 여러 Workspace의 가장 엄격한 정책과 정책 강화 즉시 반영 테스트를 작성한다**

```python
async def test_any_denied_workspace_blocks_external_provider_before_runtime() -> None:
    decision = await resolver.resolve(
        deployment=openai_deployment(),
        workspace_ids=(allowed_workspace_id, denied_workspace_id),
    )
    assert decision.allowed is False
    assert decision.reason_code == "workspace_external_transfer_denied"
```

API 테스트는 Installation이 `deny`인데 Workspace에서 `approved_providers`로 넓히는 요청 422, owner 아닌 정책 변경 403, 새 version 생성 뒤 이전 version 보존을 검증한다.

- [ ] **Step 2: 실패 테스트를 확인한다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/policies/test_execution_policy.py tests/integration/labs/rag/policies/test_api.py -q --basetemp "$env:TEMP/ai-workshop-policy-api-red"`

Expected: service와 route가 없어 FAIL한다.

- [ ] **Step 3: 현재 최신 version을 읽되 판정 결과에는 정확한 version ID를 고정하는 resolver를 구현한다**

```python
async def resolve(
    self,
    *,
    deployment: ModelDeploymentVersion,
    workspace_ids: tuple[UUID, ...],
) -> PolicyDecision:
    installation = await self.repository.latest_installation_policy()
    workspaces = await self.repository.latest_workspace_policies(workspace_ids)
    return resolve_external_transfer_policy(
        provider=deployment.provider,
        installation=installation,
        workspaces=workspaces,
    )
```

local/on-premise Deployment는 외부 Provider 승인 범위의 영향을 받지 않지만 policy version을 감사용으로 반환한다.

- [ ] **Step 4: 정책 관리 API를 구현한다**

```text
GET  /api/v1/admin/rag/data-policies/installation
POST /api/v1/admin/rag/data-policies/installation/versions
GET  /api/v1/admin/rag/data-policies/workspaces/{workspace_id}
POST /api/v1/admin/rag/data-policies/workspaces/{workspace_id}/versions
```

POST는 기존 row UPDATE가 아니라 `max(version)+1` insert만 수행하고 Workspace Provider 목록이 Installation Provider 목록의 부분집합인지 service와 DB trigger에서 모두 검사한다.

- [ ] **Step 5: 정책 단위·통합 테스트를 통과시킨다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/policies tests/integration/labs/rag/policies -q --basetemp "$env:TEMP/ai-workshop-policy-api-green"`

Expected: PASS.

- [ ] **Step 6: 커밋한다**

```bash
git add backend/src/ai_workshop/main.py backend/src/ai_workshop/labs/rag/policies backend/tests/unit/labs/rag/policies backend/tests/integration/labs/rag/policies
git commit -m "feat(rag): enforce versioned external data policies"
```

---

### Task 5: Generation Profile Deployment binding과 외부 구성 승인

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/models/domain.py`
- Modify: `backend/src/ai_workshop/labs/rag/models/schemas.py`
- Modify: `backend/src/ai_workshop/labs/rag/models/repository.py`
- Modify: `backend/src/ai_workshop/labs/rag/models/service.py`
- Modify: `backend/src/ai_workshop/labs/rag/generation/domain.py`
- Modify: `backend/src/ai_workshop/labs/rag/generation/profile.py`
- Modify: `backend/src/ai_workshop/labs/rag/configurations/domain.py`
- Modify: `backend/src/ai_workshop/labs/rag/configurations/schemas.py`
- Modify: `backend/src/ai_workshop/labs/rag/configurations/repository.py`
- Modify: `backend/src/ai_workshop/labs/rag/configurations/service.py`
- Test: `backend/tests/unit/labs/rag/models/test_profiles.py`
- Test: `backend/tests/unit/labs/rag/generation/test_profile_resolution.py`
- Test: `backend/tests/unit/labs/rag/configurations/test_configuration.py`
- Test: `backend/tests/integration/labs/rag/configurations/test_configuration_api.py`

**Interfaces:**
- Consumes: exact Deployment Version, current policies, owner actor, selected workspaces
- Produces: `Profile.deployment_version_id`, resolved `GenerationProfile.deployment`, `ExternalTransferApprovalInput`, immutable approval snapshot

- [ ] **Step 1: 새 generation profile이 Model binding 대신 Deployment binding을 요구하는 테스트를 작성한다**

```python
def test_generation_profile_requires_exact_deployment_version() -> None:
    profile = Profile.create(
        kind=ProfileKind.GENERATION,
        name="OpenAI grounded answer",
        version=1,
        config=generation_config(),
        bindings=(),
        deployment_version_id=deployment_version_id,
    )
    assert profile.deployment_version_id == deployment_version_id

def test_generation_profile_rejects_legacy_model_and_deployment_together() -> None:
    with pytest.raises(ProfileValidationError, match="exactly one deployment"):
        Profile.create(
            kind=ProfileKind.GENERATION, name="invalid", version=1,
            config=generation_config(), bindings=(llm_binding(),),
            deployment_version_id=deployment_version_id,
        )
```

- [ ] **Step 2: 외부 전송 승인 없는 구성 저장 거절과 stale 승인 테스트를 작성한다**

```python
async def test_external_configuration_requires_current_policy_approval(service) -> None:
    with pytest.raises(ConfigurationValidationError, match="approval"):
        await service.create(
            generation_profile_id=external_profile_id,
            workspace_ids=(workspace_id,),
            external_transfer_approval=None,
            **base_configuration_fields(),
        )
```

정책 version을 강화한 뒤 기존 configuration 응답의 `answer_ready`가 false이고 reason이 `provider_not_allowed` 또는 `workspace_external_transfer_denied`인지도 검증한다.

- [ ] **Step 3: 실패 테스트를 확인한다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/models/test_profiles.py tests/unit/labs/rag/generation/test_profile_resolution.py tests/unit/labs/rag/configurations/test_configuration.py tests/integration/labs/rag/configurations/test_configuration_api.py -q --basetemp "$env:TEMP/ai-workshop-deployment-binding-red"`

Expected: 새 binding과 approval 필드가 없어 FAIL한다.

- [ ] **Step 4: Profile 생성·조회 계약을 정확한 Deployment Version으로 바꾼다**

```python
@dataclass(frozen=True, slots=True)
class GenerationProfile:
    profile_id: UUID
    profile_name: str
    profile_version: int
    deployment: ModelDeploymentVersion
    model_name: str
    model_version: int
    prompt_ref: str
    context_prompt_ref: str
    context_policy: ContextPolicy
    timeout_seconds: float
    max_output_tokens: int
    temperature: float
    response_schema_version: int
```

legacy model-bound profile은 조회 응답에 `legacy=true`, `deployment_version_id=null`, `readiness.reason_codes=["deployment_not_ready"]`로 남긴다. 기존 row와 binding을 자동 변경하지 않는다.

- [ ] **Step 5: 외부 configuration 저장의 명시 승인 snapshot을 구현한다**

```python
class ExternalTransferApprovalInput(BaseModel):
    confirmed: Literal[True]
    disclosure_version: Literal["external-generation-v1"]

class SavedRagConfigurationCreate(BaseModel):
    # existing fields stay unchanged
    external_transfer_approval: ExternalTransferApprovalInput | None = None
```

service는 deployment가 external일 때 owner actor, current installation/workspace policy version, deployment version, disclosure version을 새 configuration version과 같은 transaction에서 저장한다. local/on-premise 구성에 approval을 보내면 422로 거부한다.

- [ ] **Step 6: Profile·구성 테스트를 통과시킨다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/models/test_profiles.py tests/unit/labs/rag/generation/test_profile_resolution.py tests/unit/labs/rag/configurations/test_configuration.py tests/integration/labs/rag/configurations/test_configuration_api.py -q --basetemp "$env:TEMP/ai-workshop-deployment-binding-green"`

Expected: PASS.

- [ ] **Step 7: 커밋한다**

```bash
git add backend/src/ai_workshop/labs/rag/models backend/src/ai_workshop/labs/rag/generation/domain.py backend/src/ai_workshop/labs/rag/generation/profile.py backend/src/ai_workshop/labs/rag/configurations backend/tests/unit/labs/rag/models backend/tests/unit/labs/rag/generation/test_profile_resolution.py backend/tests/unit/labs/rag/configurations backend/tests/integration/labs/rag/configurations/test_configuration_api.py
git commit -m "feat(rag): bind generation profiles to deployments"
```

---

### Task 6: 환경·정책 기반 단일 runtime resolver와 로컬 adapter 이전

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/generation/contracts.py`
- Create: `backend/src/ai_workshop/labs/rag/generation/execution.py`
- Create: `backend/src/ai_workshop/labs/rag/generation/runtime_resolver.py`
- Modify: `backend/src/ai_workshop/labs/rag/generation/openai_compatible.py`
- Modify: `backend/src/ai_workshop/labs/rag/generation/readiness.py`
- Modify: `backend/src/ai_workshop/labs/rag/deployments/api.py`
- Modify: `backend/src/ai_workshop/labs/rag/deployments/service.py`
- Modify: `backend/src/ai_workshop/labs/rag/search/configuration_port.py`
- Test: `backend/tests/unit/labs/rag/generation/test_runtime_resolver.py`
- Modify: `backend/tests/unit/labs/rag/generation/test_openai_compatible.py`
- Modify: `backend/tests/unit/labs/rag/generation/test_profile_resolution.py`

**Interfaces:**
- Consumes: resolved Generation Profile, current normalized environment, PolicyDecision, endpoint/secret resolver
- Produces: `GenerationRuntimeResolver.resolve(...) -> ResolvedGenerationRuntime`,
  `ProviderExecutionMetadata`, typed `GenerationProviderError`,
  `POST /api/v1/admin/rag/deployment-versions/{version_id}/health-check`

- [ ] **Step 1: 환경 금지와 fallback 금지 테스트를 작성한다**

```python
def test_resolver_rejects_deployment_outside_current_environment() -> None:
    with pytest.raises(GenerationProviderError) as caught:
        resolver(environment=DeploymentEnvironment.PRODUCTION).resolve(
            development_only_deployment(), allowed_policy_decision()
        )
    assert caught.value.code == "deployment_not_allowed_in_environment"

def test_resolver_does_not_try_second_provider_after_selected_provider_fails() -> None:
    runtime = resolver.resolve(selected_deployment(), allowed_policy_decision())
    assert runtime.adapter is selected_adapter
    assert fallback_adapter.calls == 0
```

- [ ] **Step 2: 공통 Provider 결과와 오류 계약의 실패 테스트를 실행한다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/generation/test_runtime_resolver.py tests/unit/labs/rag/generation/test_openai_compatible.py -q --basetemp "$env:TEMP/ai-workshop-runtime-resolver-red"`

Expected: resolver와 새 결과 타입이 없어 FAIL한다.

- [ ] **Step 3: 공통 실행 결과·usage·오류 타입을 구현한다**

```python
@dataclass(frozen=True, slots=True)
class ProviderExecutionMetadata:
    provider: ProviderKind
    provider_model_id: str
    deployment_version_id: UUID
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int

@dataclass(frozen=True, slots=True)
class ProviderGenerationResult:
    generation: StructuredGeneration
    execution: ProviderExecutionMetadata

class GenerationProviderError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
```

`GenerationRuntimePort.generate()`는 `ProviderGenerationResult`, `contextualize()`는 `ProviderContextualizationResult`를 반환하도록 바꾼다.

- [ ] **Step 4: resolver가 정확히 하나의 adapter만 선택하도록 구현한다**

```python
class GenerationRuntimeResolver:
    def resolve(
        self,
        deployment: ModelDeploymentVersion,
        policy: PolicyDecision,
    ) -> ResolvedGenerationRuntime:
        self._validate_environment(deployment)
        if not policy.allowed:
            raise GenerationProviderError(policy.reason_code or "provider_not_allowed", retryable=False)
        factory = self._factories.get(deployment.provider)
        if factory is None:
            raise GenerationProviderError("deployment_not_ready", retryable=False)
        return factory(deployment)
```

- [ ] **Step 5: local adapter가 Deployment의 endpoint/model identity를 사용하게 이전한다**

loopback `local`과 allowlist된 `on_premise` endpoint만 허용하고 `/v1/models`에서 exact `provider_model_id`를 확인한다. 기존 `AI_WORKSHOP_GENERATION_BASE_URL`은 legacy Deployment migration 입력에만 사용하고 새 실행은 `endpoint_ref` resolver를 사용한다.

owner health-check endpoint는 같은 resolver를 통해 선택된 정확한 adapter의 `health()`를 호출하고
본문 없는 append-only health check를 기록한다. Task 7에서 OpenAI adapter가 등록되면 같은
endpoint가 OpenAI Deployment도 검사하며, 등록되지 않은 Provider는 `deployment_not_ready`다.

- [ ] **Step 6: resolver·local 회귀 테스트를 통과시킨다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/generation/test_runtime_resolver.py tests/unit/labs/rag/generation/test_openai_compatible.py tests/unit/labs/rag/generation/test_profile_resolution.py -q --basetemp "$env:TEMP/ai-workshop-runtime-resolver-green"`

Expected: PASS.

- [ ] **Step 7: 커밋한다**

```bash
git add backend/src/ai_workshop/labs/rag/generation backend/src/ai_workshop/labs/rag/search/configuration_port.py backend/tests/unit/labs/rag/generation
git commit -m "refactor(rag): resolve one policy-approved generation runtime"
```

---

### Task 7: OpenAI Responses API adapter

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/generation/openai_responses.py`
- Create: `backend/src/ai_workshop/labs/rag/generation/structured_output.py`
- Modify: `backend/src/ai_workshop/labs/rag/generation/runtime_resolver.py`
- Test: `backend/tests/unit/labs/rag/generation/test_openai_responses.py`
- Test: `backend/tests/contract/test_openai_responses_adapter.py`

**Interfaces:**
- Consumes: OpenAI Responses endpoint/key refs, exact provider model ID, prompts, signed bounded history, selected Evidence
- Produces: `OpenAIResponsesRuntime`, normalized contextualization/generation result, common safe errors and token usage

- [ ] **Step 1: exact request schema와 비민감 응답 변환 테스트를 작성한다**

```python
async def test_generate_uses_strict_json_schema_and_exact_model(httpx_mock) -> None:
    httpx_mock.add_response(json=openai_response(model="gpt-5-mini-2025-08-07"))
    result = await runtime.generate(generation_request())
    request = httpx_mock.get_request()
    payload = json.loads(request.content)
    assert payload["model"] == "gpt-5-mini-2025-08-07"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert result.generation.claims[0].evidence_ids == (evidence_id,)
    assert result.execution.input_tokens == 120
```

contextualization 테스트는 앱이 전달한 bounded history만 request에 존재하고 `previous_response_id`와 provider conversation ID가 없음을 검증한다.

- [ ] **Step 2: Provider 오류 매핑 테스트를 작성한다**

```python
@pytest.mark.parametrize(("status", "code", "retryable"), [
    (401, "provider_authentication_failed", False),
    (429, "provider_rate_limited", True),
    (500, "provider_invalid_response", False),
])
async def test_maps_provider_errors(status: int, code: str, retryable: bool) -> None:
    runtime = runtime_with_status(status)
    with pytest.raises(GenerationProviderError) as caught:
        await runtime.generate(generation_request())
    assert (caught.value.code, caught.value.retryable) == (code, retryable)
```

timeout은 `provider_timeout`, JSON Schema를 벗어난 출력은
`structured_output_invalid`로 변환한다. malformed JSON, model mismatch, response에 secret이
포함돼도 로그로 전달하지 않는 경우도 별도 테스트한다.

- [ ] **Step 3: 실패 테스트를 확인한다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/generation/test_openai_responses.py tests/contract/test_openai_responses_adapter.py -q --basetemp "$env:TEMP/ai-workshop-openai-responses-red"`

Expected: adapter가 없어 FAIL한다.

- [ ] **Step 4: 두 JSON Schema를 한 곳에서 versioned constant로 구현한다**

```python
GROUNDED_GENERATION_SCHEMA_V1: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "claims"],
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "claims": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["text", "evidence_ids"],
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}
```

질의 문맥화 schema는 `resolved_query` 한 필드만 허용한다.

- [ ] **Step 5: Responses API 호출과 제한 재시도를 구현한다**

`POST {endpoint}/v1/responses`에 `Authorization: Bearer <resolved secret>`, exact model, instructions, explicit input, strict JSON schema를 보낸다. retry는 Deployment Version의 `max_retries` 범위에서 timeout·429만 대상으로 하고 인증, model mismatch, malformed output은 재시도하지 않는다. request/response body와 header는 예외 메시지에 포함하지 않는다.

- [ ] **Step 6: actual response model과 usage를 검증·정규화한다**

응답의 `model`이 Deployment의 exact `provider_model_id`와 다르면 `provider_invalid_response`로 폐기한다. `output_text` 또는 typed output item에서 JSON 문자열을 하나만 읽어 `StructuredGeneration`으로 만들고 schema version을 재검사한다.

- [ ] **Step 7: adapter 계약 테스트를 통과시킨다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/generation/test_openai_responses.py tests/contract/test_openai_responses_adapter.py -q --basetemp "$env:TEMP/ai-workshop-openai-responses-green"`

Expected: exact model, structured output, bounded history, usage, retry/error/secret 위생 테스트가 PASS한다.

- [ ] **Step 8: 커밋한다**

```bash
git add backend/src/ai_workshop/labs/rag/generation/openai_responses.py backend/src/ai_workshop/labs/rag/generation/structured_output.py backend/src/ai_workshop/labs/rag/generation/runtime_resolver.py backend/tests/unit/labs/rag/generation/test_openai_responses.py backend/tests/contract/test_openai_responses_adapter.py
git commit -m "feat(rag): add OpenAI Responses generation adapter"
```

---

### Task 8: 검색 전 정책 gate, 실행 감사와 응답 execution 계약

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/search/api.py`
- Modify: `backend/src/ai_workshop/labs/rag/search/service.py`
- Modify: `backend/src/ai_workshop/labs/rag/search/schemas.py`
- Modify: `backend/src/ai_workshop/labs/rag/search/configuration_port.py`
- Modify: `backend/src/ai_workshop/labs/rag/configurations/repository.py`
- Modify: `backend/src/ai_workshop/labs/rag/generation/domain.py`
- Test: `backend/tests/unit/labs/rag/search/test_generation_policy_gate.py`
- Modify: `backend/tests/integration/labs/rag/search/test_search_api.py`
- Modify: `backend/tests/e2e/test_rag_search_flow.py`

**Interfaces:**
- Consumes: actor-authorized scope, exact deployment/profile/config, current policy decision, resolved single runtime, audit repository
- Produces: `generation.execution` public contract and metadata-only audit event

- [ ] **Step 1: 외부 정책 거절이 contextualization과 generation보다 먼저 일어나는 테스트를 작성한다**

```python
async def test_denied_workspace_never_reaches_external_adapter() -> None:
    runtime = SpyGenerationRuntime()
    with pytest.raises(AppError) as caught:
        await service.search(actor_id=actor_id, request=external_search_request())
    assert caught.value.code == "workspace_external_transfer_denied"
    assert runtime.contextualize_calls == []
    assert runtime.generate_calls == []
```

두 Workspace 중 하나만 deny인 경우, Evidence 부족인 경우 Provider 미호출, selected Provider 실패 시 local adapter 미호출도 검증한다.

- [ ] **Step 2: 응답 실행 정보와 감사 본문 비저장 테스트를 작성한다**

```python
assert response.json()["generation"]["execution"] == {
    "provider": "openai_responses",
    "model_name": "OpenAI GPT-5 mini",
    "model_version": 1,
    "deployment_name": "OpenAI 금융 답변",
    "location": "external",
    "external_transfer": True,
    "disclosure": "OpenAI 외부 API로 현재 질문, 제한된 이전 대화와 선별된 문서 근거가 전송됩니다.",
}
audit = await load_last_audit()
assert audit.evidence_ids == expected_ids
assert not hasattr(audit, "question")
assert not hasattr(audit, "prompt")
assert not hasattr(audit, "document_text")
```

- [ ] **Step 3: 실패 테스트를 확인한다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/search/test_generation_policy_gate.py tests/integration/labs/rag/search/test_search_api.py -q --basetemp "$env:TEMP/ai-workshop-policy-gate-red"`

Expected: policy gate와 execution schema가 없어 FAIL한다.

- [ ] **Step 4: 권한 다음·첫 Provider 호출 전에 실행 계약을 확정한다**

```text
1. configuration/version resolve
2. requested workspace가 configuration subscription 안인지 확인
3. actor workspace/folder 권한 scope resolve
4. deployment environment + Installation + 모든 Workspace policy + approval 확인
5. server authoritative disclosure 생성
6. 필요할 때만 contextualize
7. retrieve/select evidence
8. Evidence가 충분할 때만 generate
9. citation hard gate
10. metadata-only audit와 응답 작성
```

- [ ] **Step 5: 안전 오류와 실행 정보 schema를 구현한다**

```python
class GenerationExecutionResponse(BaseModel):
    provider: ProviderKind
    model_name: str
    model_version: int
    deployment_name: str
    location: ExecutionLocation
    external_transfer: bool
    disclosure: str

class GenerationResponse(BaseModel):
    # existing fields remain
    execution: GenerationExecutionResponse | None
```

일반 응답에는 endpoint, secret ref, 내부 deployment UUID를 넣지 않는다. 정책·Provider 오류는
승인된 공통 코드와 한국어 사용자 메시지로 변환한다. Provider 구조는 유효하지만 인용 hard
gate가 실패하면 `citation_validation_failed`를 반환하며 다른 Provider를 호출하지 않는다.

- [ ] **Step 6: 성공·실패 audit를 같은 correlation ID로 기록한다**

actor, configuration/profile/deployment/policy/prompt reference/version, Evidence ID, token, latency, 비용 추정 기준/금액, 성공 또는 안전 오류 코드만 저장한다. 외부 호출이 시작되지 않은 정책 거절도 deployment와 policy 판정 metadata를 기록한다.

- [ ] **Step 7: 검색 단위·통합·E2E 테스트를 통과시킨다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/search/test_generation_policy_gate.py tests/integration/labs/rag/search/test_search_api.py tests/e2e/test_rag_search_flow.py -q --basetemp "$env:TEMP/ai-workshop-policy-gate-green"`

Expected: 정책 선차단, exact adapter, no fallback, execution 응답, citation gate, audit hygiene가 PASS한다.

- [ ] **Step 8: 커밋한다**

```bash
git add backend/src/ai_workshop/labs/rag/search backend/src/ai_workshop/labs/rag/configurations/repository.py backend/src/ai_workshop/labs/rag/generation backend/tests/unit/labs/rag/search/test_generation_policy_gate.py backend/tests/integration/labs/rag/search/test_search_api.py backend/tests/e2e/test_rag_search_flow.py
git commit -m "feat(rag): gate generation by policy and audit execution"
```

---

### Task 9: 관리자 Deployment·정책·외부 승인 UI

**Files:**
- Modify: `frontend/src/features/rag/models/api.ts`
- Modify: `frontend/src/features/rag/models/ModelLabPage.tsx`
- Create: `frontend/src/features/rag/models/DeploymentRegistry.tsx`
- Create: `frontend/src/features/rag/models/DataPolicyPanel.tsx`
- Modify: `frontend/src/features/rag/models/ModelLabPage.test.tsx`
- Create: `frontend/src/features/rag/models/DeploymentRegistry.test.tsx`
- Create: `frontend/src/features/rag/models/DataPolicyPanel.test.tsx`
- Modify: `frontend/src/features/rag/configurations/api.ts`
- Modify: `frontend/src/features/rag/configurations/ConfigurationBuilder.tsx`
- Modify: `frontend/src/features/rag/configurations/ConfigurationStudioPage.test.tsx`
- Modify: `frontend/src/features/rag/configurations/SavedConfigurationList.tsx`
- Modify: `frontend/src/app/styles.css`
- Modify: `frontend/src/shared/api/schema.d.ts`

**Interfaces:**
- Consumes: admin Deployment/health/policy API, safe options, Generation Profile deployment summary, configuration approval contract
- Produces: owner가 실행 위치와 정책을 인지하고 외부 구성을 명시 승인하는 관리 화면

- [ ] **Step 1: 실행 위치·준비 상태·secret 비노출 렌더링 테스트를 작성한다**

```tsx
render(<DeploymentRegistry deployments={[openAiDeployment]} />);
expect(screen.getByText("OpenAI 금융 답변")).toBeVisible();
expect(screen.getByText("외부 API")).toBeVisible();
expect(screen.getByText("gpt-5-mini-2025-08-07")).toBeVisible();
expect(screen.getByText("인증정보 구성됨")).toBeVisible();
expect(screen.queryByText("openai-primary")).not.toBeInTheDocument();
expect(screen.queryByText(/sk-/)).not.toBeInTheDocument();
```

- [ ] **Step 2: 비활성 사유와 외부 승인 테스트를 작성한다**

```tsx
expect(screen.getByRole("option", { name: /정책상 외부 전송 불가/ })).toBeDisabled();
await user.selectOptions(screen.getByLabelText("생성 구성"), externalProfileId);
expect(screen.getByRole("button", { name: "구성 저장" })).toBeDisabled();
await user.click(screen.getByRole("checkbox", { name: /질문.*이전 대화.*문서 근거/ }));
expect(screen.getByRole("button", { name: "구성 저장" })).toBeEnabled();
```

- [ ] **Step 3: UI 테스트 실패를 확인한다**

Run: `cd frontend; pnpm test --run src/features/rag/models src/features/rag/configurations`

Expected: 새 컴포넌트와 API 타입이 없어 FAIL한다.

- [ ] **Step 4: OpenAPI schema를 생성하고 typed API 함수를 구현한다**

Run: `cd frontend; pnpm api:generate`

```ts
export function loadDeployments(): Promise<DeploymentSummary[]> {
  return apiRequest("/api/v1/admin/rag/deployments");
}

export function createInstallationPolicy(
  request: InstallationDataPolicyCreate,
): Promise<InstallationDataPolicy> {
  return apiRequest("/api/v1/admin/rag/data-policies/installation/versions", {
    method: "POST", json: request,
  });
}
```

- [ ] **Step 5: 관리자 모델 화면에 실제 지원 Provider만 표시한다**

Model Definition과 Deployment를 구분하고 local/on-premise/external 배지, exact 모델 ID, 허용 환경, structured output capability, readiness reason, 마지막 health check를 표시한다. Codex, Anthropic, Gemini, Azure, Bedrock은 option이나 빈 카드로 만들지 않는다.

- [ ] **Step 6: RAG 구성에서 외부 전송을 명시적으로 재확인한다**

Generation Profile option은 `Deployment 이름 · Model Definition 이름/버전 · Provider model ID · 실행 위치`를 표시한다. 서버가 반환한 reason으로 비활성화하고 외부 항목 선택 시 Provider, 현재 질문, bounded history, 선별 Evidence, 선택 Workspace 목록과 disclosure version을 확인한 뒤에만 저장 요청을 보낸다.

- [ ] **Step 7: 관리자 UI 테스트와 정적 검사를 통과시킨다**

Run: `cd frontend; pnpm test --run src/features/rag/models src/features/rag/configurations; pnpm typecheck; pnpm lint; pnpm api:check`

Expected: 선택지 설명, 정책 비활성, 승인 payload, secret 비노출, 타입·lint·schema drift가 모두 PASS한다.

- [ ] **Step 8: 커밋한다**

```bash
git add frontend/src/features/rag/models frontend/src/features/rag/configurations frontend/src/app/styles.css frontend/src/shared/api/schema.d.ts
git commit -m "feat(rag): manage deployments and external approvals"
```

---

### Task 10: 사용자 대화 화면 상시 disclosure와 실제 실행 표시

**Files:**
- Modify: `frontend/src/features/rag/search/api.ts`
- Modify: `frontend/src/features/rag/search/SearchPage.tsx`
- Modify: `frontend/src/features/rag/search/SearchPage.test.tsx`
- Modify: `frontend/src/features/rag/search/EvidenceAnswer.tsx`
- Modify: `frontend/src/features/rag/search/EvidenceAnswer.test.tsx`
- Modify: `frontend/src/app/styles.css`

**Interfaces:**
- Consumes: configuration safe execution preview와 search response `generation.execution`
- Produces: 질문 전 서버 고지, 응답별 실제 Provider·모델·위치·외부 전송 표시

- [ ] **Step 1: 질문 전 상시 안내 테스트를 작성한다**

```tsx
render(<SearchPage initialOptions={externalOptions} />);
expect(screen.getByText(
  "OpenAI 외부 API로 현재 질문, 제한된 이전 대화와 선별된 문서 근거가 전송됩니다.",
)).toBeVisible();
expect(screen.getByRole("button", { name: "모델 및 처리 위치 상세" })).toBeVisible();
```

local 구성은 `사내 로컬 모델에서 처리됩니다.`를 표시하고 외부 전송 문구를 표시하지 않는지 검증한다.

- [ ] **Step 2: 답변별 실제 실행 표시 테스트를 작성한다**

```tsx
expect(screen.getByText("OpenAI GPT-5 mini v1")).toBeVisible();
expect(screen.getByText("OpenAI · 외부 API에서 처리")).toBeVisible();
expect(screen.getByText("외부 전송 있음")).toBeVisible();
```

실패 응답은 서버 reason code에 대응하는 안전한 한국어 문구를 표시하되 Provider 원문 오류, endpoint와 내부 UUID를 렌더링하지 않는다.

- [ ] **Step 3: UI 테스트 실패를 확인한다**

Run: `cd frontend; pnpm test --run src/features/rag/search/SearchPage.test.tsx src/features/rag/search/EvidenceAnswer.test.tsx`

Expected: execution UI가 없어 FAIL한다.

- [ ] **Step 4: config preview는 질문 전, actual execution은 답변 카드에 표시한다**

프론트가 Provider 이름으로 전송 위치를 추측하지 않고 서버 `location`, `external_transfer`, `disclosure`만 사용한다. 구성 선택이 바뀌면 입력창 위 안내도 즉시 바뀐다. 이전 답변 카드는 해당 응답 당시 execution snapshot을 유지한다.

- [ ] **Step 5: 대화 UI 테스트와 접근성 검사를 통과시킨다**

Run: `cd frontend; pnpm test --run src/features/rag/search; pnpm typecheck; pnpm lint`

Expected: local/external 안내, 응답 snapshot, 키보드 접근 가능한 상세, 안전 오류 표시가 PASS한다.

- [ ] **Step 6: 커밋한다**

```bash
git add frontend/src/features/rag/search frontend/src/app/styles.css
git commit -m "feat(rag): disclose actual generation execution"
```

---

### Task 11: 전체 계약·privacy·migration·실제 OpenAI smoke와 운영 문서

**Files:**
- Modify: `backend/tests/contract/test_openapi.py`
- Create: `backend/tests/integration/labs/rag/generation/test_openai_policy_flow.py`
- Modify: `docs/labs/rag/design.md`
- Modify: `docs/runbooks/local-development.md`
- Create: `docs/worklogs/2026-09-05-rag-openai-deployment-verification.md`
- Modify: `WORKBOARD.md`

**Interfaces:**
- Consumes: Tasks 1-10 전체 구현
- Produces: 재현 가능한 migration·테스트·비민감 smoke 증거와 다음 Codex SDK 구현 인계

- [ ] **Step 1: OpenAPI 안전 계약과 privacy 통합 테스트를 작성한다**

```python
def test_public_execution_schema_excludes_internal_references(openapi_schema) -> None:
    schema = openapi_schema["components"]["schemas"]["GenerationExecutionResponse"]
    assert "endpoint_ref" not in schema["properties"]
    assert "secret_ref" not in schema["properties"]
    assert "deployment_version_id" not in schema["properties"]
```

통합 테스트는 deny 정책에서 mock OpenAI 호출 0회, current approval에서 exact deployment 1회, 정책 강화 후 0회, audit 본문 필드 부재를 검증한다.

- [ ] **Step 2: backend 전체 검증을 실행한다**

Run: `cd backend; uv run pytest tests/unit -q --basetemp "$env:TEMP/ai-workshop-deployment-unit"`

Run: `cd backend; uv run pytest tests/contract tests/integration/labs/rag tests/e2e/test_rag_search_flow.py -q --basetemp "$env:TEMP/ai-workshop-deployment-integration"`

Run: `cd backend; uv run ruff check src tests; uv run mypy`

Expected: 모든 명령 exit code 0.

- [ ] **Step 3: frontend 전체 검증을 실행한다**

Run: `cd frontend; pnpm test --run; pnpm typecheck; pnpm lint; pnpm build; pnpm api:check`

Expected: 모든 명령 exit code 0이고 admin/workshop/public route build가 유지된다.

- [ ] **Step 4: migration을 격리 PostgreSQL에서 검증한다**

Run: `cd backend; uv run pytest tests/integration/test_migration_0016_rag_llm_deployments.py -q --basetemp "$env:TEMP/ai-workshop-migration-final"`

Expected: fresh upgrade, 0015 upgrade, 참조 보존, 안전 downgrade 조건이 모두 PASS한다.

- [ ] **Step 5: 실제 OpenAI smoke는 승인된 비민감 합성 문서로만 수행한다**

사전 조건은 owner가 Installation policy에 `openai_responses`를 승인하고 합성 전용 Workspace 정책, exact model Deployment, Deployment-bound Generation Profile, 외부 승인 Saved Configuration을 새 version으로 만든 상태다. 질문 전 disclosure, 두 turn 문맥화, exact deployment, 생성 답변, 문장별 인용, 원문 이동, 응답 execution, metadata-only audit를 브라우저와 DB에서 확인한다. API key와 request/response 본문은 캡처하지 않는다.

- [ ] **Step 6: 설계·runbook·worklog·WORKBOARD를 실제 결과로 갱신한다**

`docs/labs/rag/design.md`에는 새 경계와 오류 코드를, runbook에는 secret reference JSON 설정·정책 승인·health check·smoke·키 회전 절차를 기록한다. worklog에는 실제 명령, 통과 수, 발견·해결한 문제와 미완료 조건만 기록한다. WORKBOARD의 최근 완료 작업은 최대 5개를 유지하고 다음 작업을 Codex SDK 개발 전용 adapter 계획으로 바꾼다.

- [ ] **Step 7: 완료 전 diff와 secret 검사를 실행한다**

Run: `git diff --check`

Run: `rg -n "sk-[A-Za-z0-9_-]+|Bearer [A-Za-z0-9_-]{12,}" . --glob '!references/**' --glob '!.git/**'`

Expected: whitespace 오류 없음. 실제 credential match 없음. fixture의 명백한 가짜 값만 있으면 파일과 줄을 worklog에 설명한다.

- [ ] **Step 8: 최종 문서와 검증 증거를 커밋한다**

```bash
git add backend/tests/contract/test_openapi.py backend/tests/integration/labs/rag/generation/test_openai_policy_flow.py docs/labs/rag/design.md docs/runbooks/local-development.md docs/worklogs/2026-09-05-rag-openai-deployment-verification.md WORKBOARD.md
git commit -m "docs(rag): verify OpenAI deployment execution"
```
