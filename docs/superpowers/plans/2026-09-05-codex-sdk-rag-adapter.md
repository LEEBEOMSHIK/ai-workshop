# 개발 전용 Codex SDK RAG Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 개발 환경에서 현재 OS 사용자의 Codex 로그인을 재사용하는 실제 `codex_sdk` 생성 Provider를 추가하고, RAG의 외부 전송 정책·정확한 Deployment·구조화 출력·인용 검증 계약 안에서 안전하게 실행한다.

**Architecture:** backend의 단일 Provider contract registry가 도메인 검증, 연결 해석, owner API와 frontend 입력을 구동한다. Codex 전용 SDK gateway는 호출마다 새 client·ephemeral thread·빈 임시 작업 공간을 만들고 모든 도구와 승인을 차단한 뒤 기존 `GenerationRuntimePort`로 결과를 정규화한다. SDK 공개 API가 지원하지 않는 샘플링·출력 한도는 Profile에 명시적으로 모델링하고 fail-closed 검증한다.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLAlchemy/Alembic, `openai-codex` Python SDK, pytest, Next.js 16, React 19, TypeScript, Vitest, Testing Library, OpenAPI-generated types.

**Spec:** `docs/superpowers/specs/2026-09-05-codex-sdk-rag-adapter-design.md`

## Global Constraints

- `main`에서만 작업하고 새 worktree를 만들지 않는다.
- 실제 SDK dependency를 설치한 뒤 pinned runtime의 공개 API와 설정 schema를 검증한다. 격리 강제를 증명하지 못하면 Task 1에서 중단하고 `codex_isolation_not_enforced` 증거만 기록한다.
- Codex 인증 파일, token, account ID, 이메일, thread ID, 질문·대화·Evidence 본문과 원본 SDK 오류를 DB·로그·Git에 저장하지 않는다.
- 자동 테스트는 fake SDK gateway를 사용하며 네트워크·실제 Codex 로그인·과금을 요구하지 않는다.
- `codex_sdk`는 `development` 전용, `external_transfer=true`, endpoint·secret 금지다. 정책·승인 실패 뒤에는 SDK client를 만들지 않는다.
- `contextualize()`와 `generate()` 및 각 retry는 서로 다른 client, ephemeral thread와 임시 디렉터리를 사용한다. Provider·모델 fallback은 없다.
- 공개 SDK가 지원하지 않는 `temperature`와 요청 시점 `max_output_tokens`를 조용히 무시하지 않는다. Codex Profile은 `sampling_mode=provider_default`, `temperature=null`이고 output usage를 사후 검증할 수 없거나 한도를 넘으면 결과를 폐기한다.
- 구현과 버그 수정은 RED 테스트를 먼저 작성하고 각 Task의 관련 테스트·타입·lint를 통과시킨 뒤 해당 Task 파일만 커밋한다.
- 실제 Codex smoke는 별도 사용자 승인과 비민감 합성 자료가 있을 때만 수행한다.
- 관련 없는 untracked cache와 `references/`는 수정·삭제·stage하지 않는다.

---

### Task 1: SDK dependency와 격리 가능성 fail-closed gate

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Create: `backend/src/ai_workshop/labs/rag/generation/codex_sdk_client.py`
- Create: `backend/tests/contract/test_codex_sdk_isolation.py`
- Create: `backend/tests/unit/labs/rag/generation/test_codex_sdk_client.py`
- Create: `docs/decisions/0010-development-codex-sdk-provider.md`
- Modify: `docs/labs/rag/design.md`

**Interfaces:**
- Produces: pinned SDK/runtime, 검증 가능한 `CodexIsolationContract`, 안전한 SDK gateway port
- Gate: 금지 도구가 하나라도 유효하거나 effective config를 확인할 수 없으면 이후 Task를 시작하지 않는다.

- [ ] **Step 1: SDK가 아직 없어 실패하는 contract test를 작성한다**

```python
def test_codex_isolation_contract_denies_all_tools() -> None:
    contract = codex_isolation_contract()
    assert contract.ephemeral is True
    assert contract.sandbox == "read-only"
    assert contract.approval_mode == "deny-all"
    assert contract.web_search == "disabled"
    assert contract.enabled_tools == ()
    assert contract.verified is True
```

fake effective-config probe가 shell, web, MCP, plugin, app, skill 또는 sub-agent 하나를 반환하면 `CodexIsolationError("codex_isolation_not_enforced")`가 발생하는 경우도 작성한다.

- [ ] **Step 2: RED를 확인한다**

Run: `cd backend; uv run pytest tests/contract/test_codex_sdk_isolation.py tests/unit/labs/rag/generation/test_codex_sdk_client.py -q --basetemp "$env:TEMP/ai-workshop-codex-gate-red"`

Expected: module/dependency가 없어 FAIL한다.

- [ ] **Step 3: 공식 Python SDK를 설치하고 lockfile에 실제 버전을 고정한다**

Run: `cd backend; uv add openai-codex`

Run: `cd backend; uv lock --check`

SDK 패키지가 요구하는 Python 범위, bundled Codex runtime 버전, `AsyncCodex`, `models()`, `thread_start`, `run`, `output_schema`, `ephemeral`, `Sandbox.read_only`, `ApprovalMode.deny_all`, timeout/interrupt API를 설치된 타입과 소스에서 확인한다. 별도 시스템 `codex` 실행 파일을 자동 탐색하는 코드는 만들지 않는다.

- [ ] **Step 4: 작은 SDK port와 격리 검증기를 구현한다**

```python
@dataclass(frozen=True, slots=True)
class CodexTurnRequest:
    model_id: str
    developer_instructions: str
    input_text: str
    output_schema: dict[str, object]
    timeout_seconds: float
    output_token_limit: int

@dataclass(frozen=True, slots=True)
class CodexTurnResult:
    final_response: str
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int
    observed_model_id: str | None

class CodexSdkClientPort(Protocol):
    async def account_ready(self) -> bool: ...
    async def model_ids(self) -> tuple[str, ...]: ...
    async def run_structured_turn(self, request: CodexTurnRequest) -> CodexTurnResult: ...
```

`codex_isolation_contract()`는 설치된 runtime이 실제로 인식하는 설정만 사용하고 effective tool inventory를 검증한다. 단순히 빈 `cwd`와 read-only sandbox만 보고 `verified=True`로 두지 않는다.

- [ ] **Step 5: contract gate를 통과시키거나 안전하게 중단한다**

Run: `cd backend; uv run pytest tests/contract/test_codex_sdk_isolation.py tests/unit/labs/rag/generation/test_codex_sdk_client.py -q --basetemp "$env:TEMP/ai-workshop-codex-gate-green"`

Expected: 모든 격리 조건을 실제 pinned runtime이 증명해 PASS한다. 증명할 API가 없으면 test를 완화하지 않고 ADR에 blocker를 기록한 뒤 구현을 중단한다.

- [ ] **Step 6: ADR과 RAG 정본에 확인된 SDK 계약을 기록한다**

ADR에는 로컬 SDK 프로세스와 OpenAI 외부 추론 구분, 인증 재사용·비저장, 호출별 격리, 도구 금지, Provider-managed sampling, output usage fail-closed와 비채택 대안을 기록한다. `docs/labs/rag/design.md`에는 실제 구현 경계만 반영한다.

- [ ] **Step 7: Task 1 변경만 커밋한다**

```bash
git add backend/pyproject.toml backend/uv.lock backend/src/ai_workshop/labs/rag/generation/codex_sdk_client.py backend/tests/contract/test_codex_sdk_isolation.py backend/tests/unit/labs/rag/generation/test_codex_sdk_client.py docs/decisions/0010-development-codex-sdk-provider.md docs/labs/rag/design.md
git commit -m "build(rag): pin isolated Codex SDK runtime"
```

---

### Task 2: Provider contract registry와 Codex 도메인 계약

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/deployments/providers.py`
- Modify: `backend/src/ai_workshop/labs/rag/deployments/domain.py`
- Modify: `backend/src/ai_workshop/labs/rag/deployments/schemas.py`
- Modify: `backend/src/ai_workshop/labs/rag/deployments/service.py`
- Modify: `backend/tests/unit/labs/rag/deployments/test_domain.py`
- Create: `backend/tests/unit/labs/rag/deployments/test_provider_contracts.py`

**Interfaces:**
- Produces: `ProviderKind.CODEX_SDK`, `ProviderContract`, provider별 endpoint·secret·환경·위치 검증과 안전 UI metadata

- [ ] **Step 1: Provider별 규칙과 registry 완전성 RED 테스트를 작성한다**

```python
def test_every_provider_has_an_implemented_contract() -> None:
    assert set(PROVIDER_CONTRACTS) == set(ProviderKind)
    assert all(contract.implemented for contract in PROVIDER_CONTRACTS.values())

def test_codex_requires_external_development_without_refs() -> None:
    deployment = codex_deployment(endpoint_ref=None, secret_ref=None)
    assert deployment.provider is ProviderKind.CODEX_SDK
    assert deployment.allowed_environments == (DeploymentEnvironment.DEVELOPMENT,)
```

Codex endpoint/secret 존재, local endpoint 누락, Responses endpoint/secret 누락, Codex production/staging, external false가 각각 실패하는 테스트를 추가한다.

- [ ] **Step 2: RED를 확인한다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/deployments/test_domain.py tests/unit/labs/rag/deployments/test_provider_contracts.py -q --basetemp "$env:TEMP/ai-workshop-codex-provider-red"`

Expected: registry와 Codex enum이 없어 FAIL한다.

- [ ] **Step 3: 단일 Provider contract registry를 구현한다**

```python
@dataclass(frozen=True, slots=True)
class ProviderContract:
    kind: ProviderKind
    display_name: str
    implemented: bool
    endpoint_mode: Literal["required", "optional", "forbidden"]
    secret_mode: Literal["required", "optional", "forbidden"]
    allowed_locations: frozenset[ExecutionLocation]
    allowed_environments: frozenset[DeploymentEnvironment]
    development_only: bool
    external_transfer: bool
    auth_strategy: Literal["endpoint_secret", "optional_secret", "codex_login"]
    response_model_observable: bool
    safe_description: str
```

`ModelDeploymentVersion.endpoint_ref`와 create/schema 입력을 `str | None`으로 바꾸고 `__post_init__`은 registry 한 곳에서 규칙을 적용한다. 기존 enum import 경로는 깨지지 않게 유지한다.

관리자 응답의 인증 표시는 `secret_configured: bool`만으로 판단하지 않는다.
`credential_state: "not_applicable" | "configured" | "missing"`를 추가해 Codex의 OS 로그인과
endpoint-secret Provider를 구분한다.

- [ ] **Step 4: profile 파라미터 모드의 도메인 RED 테스트를 작성한다**

```python
assert resolve_generation_profile(codex_profile(), codex_deployment(), llm).sampling_mode == "provider_default"
with pytest.raises(ValueError, match="temperature"):
    resolve_generation_profile(codex_profile(temperature=0.0), codex_deployment(), llm)
```

기존 local/Responses Profile은 `sampling_mode`가 생략돼도 migration 호환 기본값 `explicit`으로 읽히고 숫자 temperature가 계속 필요함을 검증한다.

- [ ] **Step 5: `SamplingMode`와 nullable temperature를 구현한다**

`GenerationProfile.temperature`를 `float | None`, `sampling_mode`를 `SamplingMode`로 바꾼다. Codex는 `provider_default + None`, HTTP Provider는 `explicit + number`만 허용한다. 기존 저장 Profile은 `sampling_mode` 미존재 시 `explicit`으로 해석한다.

- [ ] **Step 6: unit regression을 통과시킨다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/deployments tests/unit/labs/rag/generation/test_profile.py tests/unit/labs/rag/generation/test_profile_resolution.py -q --basetemp "$env:TEMP/ai-workshop-codex-provider-green"`

Expected: registry 완전성, Provider별 규칙, 기존 HTTP Profile 호환, Codex parameter 계약이 PASS한다.

- [ ] **Step 7: Task 2 변경만 커밋한다**

```bash
git add backend/src/ai_workshop/labs/rag/deployments backend/src/ai_workshop/labs/rag/generation/domain.py backend/src/ai_workshop/labs/rag/generation/profile.py backend/tests/unit/labs/rag/deployments backend/tests/unit/labs/rag/generation/test_profile.py backend/tests/unit/labs/rag/generation/test_profile_resolution.py
git commit -m "feat(rag): define Codex provider contract"
```

---

### Task 3: nullable endpoint migration과 저장소·API 계약

**Files:**
- Create: `backend/alembic/versions/0017_codex_sdk_provider.py`
- Modify: `backend/src/ai_workshop/labs/rag/deployments/models.py`
- Modify: `backend/src/ai_workshop/labs/rag/deployments/repository.py`
- Modify: `backend/src/ai_workshop/labs/rag/deployments/api.py`
- Modify: `backend/tests/integration/labs/rag/deployments/test_repository.py`
- Modify: `backend/tests/integration/labs/rag/deployments/test_api.py`
- Create: `backend/tests/integration/test_migration_0017_codex_sdk_provider.py`

**Interfaces:**
- Consumes: Task 2 Provider contract
- Produces: 기존 row 무변경 nullable endpoint migration과 owner-only Codex Deployment 저장 API

- [ ] **Step 1: migration·repository·API RED 테스트를 작성한다**

```python
saved = await repository.create_version(codex_deployment(endpoint_ref=None))
assert saved.endpoint_ref is None

response = await owner_client.post("/api/v1/admin/rag/deployments", json=codex_payload())
assert response.status_code == 201
assert response.json()["provider"] == "codex_sdk"
```

운영 환경, endpoint/secret 입력, 비-owner 요청이 거부되는지와 API response에 endpoint·secret·인증 식별자가 없는지 검증한다.

- [ ] **Step 2: RED를 확인한다**

Run: `cd backend; uv run pytest tests/integration/labs/rag/deployments/test_repository.py tests/integration/labs/rag/deployments/test_api.py tests/integration/test_migration_0017_codex_sdk_provider.py -q --basetemp "$env:TEMP/ai-workshop-codex-storage-red"`

Expected: non-null DB column과 schema 때문에 FAIL한다.

- [ ] **Step 3: 0017 migration과 mapping을 구현한다**

upgrade는 `model_deployment_versions.endpoint_ref`만 nullable로 만들고 기존 값을 update하지 않는다. downgrade는 null row가 있으면 명시적 오류로 중단해 데이터 손실을 피하고, null row가 없을 때만 NOT NULL을 복원한다.

- [ ] **Step 4: API는 registry 검증을 사용한다**

Codex payload는 endpoint·secret을 받지 않으며 server가 development-only, external transfer, required capabilities와 data categories를 검증한다. 임의 클라이언트 값으로 registry 안전 조건을 약화할 수 없게 한다.

- [ ] **Step 5: migration과 저장소 검증을 통과시킨다**

Run: `cd backend; uv run pytest tests/integration/labs/rag/deployments/test_repository.py tests/integration/labs/rag/deployments/test_api.py tests/integration/test_migration_0017_codex_sdk_provider.py -q --basetemp "$env:TEMP/ai-workshop-codex-storage-green"`

Expected: fresh/0016 upgrade, 기존 row 동일성, Codex nullable 저장, 안전 downgrade와 API privacy가 PASS한다.

- [ ] **Step 6: Task 3 변경만 커밋한다**

```bash
git add backend/alembic/versions/0017_codex_sdk_provider.py backend/src/ai_workshop/labs/rag/deployments backend/tests/integration/labs/rag/deployments backend/tests/integration/test_migration_0017_codex_sdk_provider.py
git commit -m "feat(rag): persist Codex deployments without endpoint"
```

---

### Task 4: 호출별 격리 SDK gateway와 안전 오류 정규화

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/generation/codex_sdk_client.py`
- Modify: `backend/tests/unit/labs/rag/generation/test_codex_sdk_client.py`
- Modify: `backend/tests/contract/test_codex_sdk_isolation.py`

**Interfaces:**
- Consumes: pinned `openai-codex`, `CodexTurnRequest`
- Produces: 호출마다 독립된 `CodexTurnResult`, 안전한 account/model 상태와 Codex 전용 오류

- [ ] **Step 1: 호출 생명주기 RED 테스트를 작성한다**

```python
result = await gateway.run_structured_turn(request)
assert fake.clients_created == 1
assert fake.thread_starts[0].ephemeral is True
assert fake.thread_starts[0].cwd == fake.empty_temp_directories[0]
assert fake.thread_starts[0].model == request.model_id
assert fake.turn_runs[0].model == request.model_id
assert fake.turn_runs[0].output_schema == request.output_schema
assert fake.closed_clients == 1
assert fake.remaining_temp_directories == []
```

read-only, deny-all, effective tool inventory empty, context와 generation 연속 호출 시 client/thread/cwd가 다름, retry 시 새 자원, timeout interrupt·close·cleanup 순서도 검증한다.

- [ ] **Step 2: 인증·모델·오류 privacy RED 테스트를 작성한다**

인증 없음은 `codex_not_authenticated`, 모델 없음은 `codex_model_unavailable`, package/runtime 오류는 `codex_sdk_unavailable`, timeout은 `codex_timeout`, transient overload만 retryable로 매핑한다. 원본 exception, 로컬 경로, 입력 본문, 계정 정보가 exception·log record에 없는지 `caplog`로 검증한다.

- [ ] **Step 3: RED를 확인한다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/generation/test_codex_sdk_client.py tests/contract/test_codex_sdk_isolation.py -q --basetemp "$env:TEMP/ai-workshop-codex-client-red"`

Expected: 실제 lifecycle 구현이 없어 FAIL한다.

- [ ] **Step 4: gateway를 구현한다**

각 `run_structured_turn` 내부에서 빈 OS temp directory와 새 `AsyncCodex` context를 만들고 account/model preflight 뒤 새 ephemeral thread를 시작한다. `developer_instructions`와 `input_text`만 전달하고 이미지·파일·mention·skill 입력 타입은 받지 않는다. timeout/cancel 시 public interrupt API가 있으면 호출하고 항상 client 종료 후 temp directory를 제거한다.

- [ ] **Step 5: 응답 identity·usage를 정규화한다**

`final_response`, input/output usage, duration, SDK가 실제 제공한 경우에만 observed model ID를 반환한다. observed ID를 제공하지 않으면 `None`을 유지하고 추측하지 않는다. output usage가 없으면 상위 runtime이 fail closed할 수 있게 `None`을 보존한다.

- [ ] **Step 6: SDK gateway tests를 통과시킨다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/generation/test_codex_sdk_client.py tests/contract/test_codex_sdk_isolation.py -q --basetemp "$env:TEMP/ai-workshop-codex-client-green"`

Expected: lifecycle, isolation, identity, usage, retry resource separation, cleanup와 privacy가 PASS한다.

- [ ] **Step 7: Task 4 변경만 커밋한다**

```bash
git add backend/src/ai_workshop/labs/rag/generation/codex_sdk_client.py backend/tests/unit/labs/rag/generation/test_codex_sdk_client.py backend/tests/contract/test_codex_sdk_isolation.py
git commit -m "feat(rag): isolate Codex SDK turns"
```

---

### Task 5: Codex `GenerationRuntimePort` adapter

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/generation/codex_sdk.py`
- Modify: `backend/src/ai_workshop/labs/rag/generation/structured_output.py`
- Create: `backend/tests/unit/labs/rag/generation/test_codex_sdk.py`

**Interfaces:**
- Consumes: 기존 prompt/schema, exact Deployment-bound `GenerationProfile`, `CodexSdkClientPort`
- Produces: 기존 `ProviderHealthResult`, `ProviderContextualizationResult`, `ProviderGenerationResult`

- [ ] **Step 1: health·문맥화·생성 RED 테스트를 작성한다**

```python
context = await runtime.contextualize(context_request)
assert context.resolved_query == "독립 검색 질의"
assert gateway.requests[0].model_id == deployment.provider_model_id

answer = await runtime.generate(generation_request)
assert answer.generation.claims[0].evidence_ids == (evidence_id,)
assert gateway.requests[1].output_schema == GROUNDED_GENERATION_SCHEMA_V1
```

각 호출이 새 gateway lifecycle을 사용하고 exact model, bounded history, 허용 Evidence ID·최소 텍스트만 전송하는지 검증한다.

- [ ] **Step 2: 파라미터·응답 fail-closed RED 테스트를 작성한다**

`sampling_mode != provider_default`, non-null temperature, output usage 없음, usage 초과, malformed structured output, schema version mismatch, observed model mismatch가 모두 결과 폐기와 안전 오류로 이어지는지 검증한다.

- [ ] **Step 3: RED를 확인한다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/generation/test_codex_sdk.py -q --basetemp "$env:TEMP/ai-workshop-codex-runtime-red"`

Expected: adapter가 없어 FAIL한다.

- [ ] **Step 4: Codex runtime을 구현한다**

```python
class CodexSdkGenerationRuntime(GenerationRuntimePort):
    def __init__(self, deployment: ModelDeploymentVersion, client: CodexSdkClientPort) -> None: ...
    async def health(self) -> ProviderHealthResult: ...
    async def contextualize(self, request: ContextualizationRequest) -> ProviderContextualizationResult: ...
    async def generate(self, request: GenerationRequest) -> ProviderGenerationResult: ...
```

기존 `CONTEXTUALIZATION_SCHEMA_V1`, `GROUNDED_GENERATION_SCHEMA_V1`과 parser를 재사용한다. Provider가 반환한 final response가 schema와 profile response version을 통과한 뒤에만 domain result를 만든다.

- [ ] **Step 5: output acceptance limit와 오류를 적용한다**

SDK output token usage가 `None`이거나 `profile.max_output_tokens`보다 크면 `codex_output_limit_unverified`로 폐기한다. 이 값이 Provider 요청 한도로 전달된 것처럼 감사/UI에 기록하지 않는다. timeout·overload retry는 Deployment 한도만 사용하고 각 attempt는 gateway의 새 client/thread/cwd를 사용한다.

- [ ] **Step 6: runtime unit tests를 통과시킨다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/generation/test_codex_sdk.py tests/unit/labs/rag/generation/test_context_policy.py tests/unit/labs/rag/generation/test_citation_validation.py -q --basetemp "$env:TEMP/ai-workshop-codex-runtime-green"`

Expected: 구조화 출력, 출력 한도, no fallback, 기존 context/citation 계약이 PASS한다.

- [ ] **Step 7: Task 5 변경만 커밋한다**

```bash
git add backend/src/ai_workshop/labs/rag/generation/codex_sdk.py backend/src/ai_workshop/labs/rag/generation/structured_output.py backend/tests/unit/labs/rag/generation/test_codex_sdk.py
git commit -m "feat(rag): add Codex generation runtime"
```

---

### Task 6: resolver·readiness·정책·감사 통합

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/generation/runtime_resolver.py`
- Modify: `backend/src/ai_workshop/labs/rag/generation/readiness.py`
- Modify: `backend/src/ai_workshop/labs/rag/deployments/service.py`
- Modify: `backend/src/ai_workshop/labs/rag/search/service.py`
- Modify: `backend/src/ai_workshop/labs/rag/generation/audit.py`
- Modify: `backend/tests/unit/labs/rag/generation/test_runtime_resolver.py`
- Modify: `backend/tests/unit/labs/rag/generation/test_readiness.py`
- Modify: `backend/tests/unit/labs/rag/search/test_generation_policy_gate.py`
- Create: `backend/tests/integration/labs/rag/generation/test_codex_policy_flow.py`

**Interfaces:**
- Consumes: Provider registry, exact Deployment, current environment와 정책 결정
- Produces: endpoint 없는 Codex runtime 해석, 질문 전 readiness, metadata-only audit

- [ ] **Step 1: connection object와 resolver RED 테스트를 작성한다**

```python
resolved = resolver.resolve(codex_deployment(), allowed_policy())
assert resolved.deployment.provider is ProviderKind.CODEX_SDK
assert codex_factory.connections == [
    ResolvedProviderConnection(endpoint=None, secret=None)
]
```

Codex가 production이거나 refs가 있으면 factory 0회, missing factory는 `deployment_not_ready`, 다른 Provider 기존 해석은 동일함을 검증한다.

- [ ] **Step 2: 정책 선차단·no fallback RED 테스트를 작성한다**

Installation deny, 한 Workspace deny, stale approval, insufficient Evidence 각각에서 Codex client 생성 0회인지 검증한다. Codex failure 뒤 Responses/local factory 호출 0회인지 검증한다.

- [ ] **Step 3: RED를 확인한다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/generation/test_runtime_resolver.py tests/unit/labs/rag/generation/test_readiness.py tests/unit/labs/rag/search/test_generation_policy_gate.py tests/integration/labs/rag/generation/test_codex_policy_flow.py -q --basetemp "$env:TEMP/ai-workshop-codex-integration-red"`

Expected: resolver positional endpoint 계약과 Codex factory 부재로 FAIL한다.

- [ ] **Step 4: provider-neutral connection과 factory 등록을 구현한다**

```python
@dataclass(frozen=True, slots=True)
class ResolvedProviderConnection:
    endpoint: str | None
    secret: str | None

GenerationRuntimeFactory = Callable[
    [ModelDeploymentVersion, ResolvedProviderConnection], GenerationRuntimePort
]
```

registry가 endpoint/secret 필요 여부를 결정하고 Codex factory는 두 값이 모두 `None`일 때만 adapter를 만든다. health/readiness는 SDK availability, safe auth bool, exact model presence와 isolation verified만 사용한다.

기존 Provider는 health가 반환한 observed model ID의 exact match를 계속 요구한다. Codex는 SDK가
실제 turn model ID를 제공하지 않을 수 있으므로 registry의 `response_model_observable=false`를
따라 model 목록 사전 확인과 thread·turn exact model 지정으로 readiness를 계산하고, 반환되지
않은 observed ID를 채워 넣지 않는다.

- [ ] **Step 5: 정책·감사 통합을 구현한다**

기존 권한 → exact 구성 → 환경 → Installation/Workspace policy → approval → Evidence 순서를 유지한다. audit에는 `codex_sdk`, exact provider model ID, 정책/version, usage, duration, safe code만 저장하고 thread/account/path/body는 넣지 않는다.

- [ ] **Step 6: 통합 tests를 통과시킨다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/generation/test_runtime_resolver.py tests/unit/labs/rag/generation/test_readiness.py tests/unit/labs/rag/search/test_generation_policy_gate.py tests/integration/labs/rag/generation/test_codex_policy_flow.py -q --basetemp "$env:TEMP/ai-workshop-codex-integration-green"`

Expected: environment/policy 선차단, exact runtime, no fallback, readiness, output/citation failure 폐기와 audit privacy가 PASS한다.

- [ ] **Step 7: Task 6 변경만 커밋한다**

```bash
git add backend/src/ai_workshop/labs/rag/generation backend/src/ai_workshop/labs/rag/deployments/service.py backend/src/ai_workshop/labs/rag/search/service.py backend/tests/unit/labs/rag/generation backend/tests/unit/labs/rag/search/test_generation_policy_gate.py backend/tests/integration/labs/rag/generation/test_codex_policy_flow.py
git commit -m "feat(rag): resolve Codex through policy gates"
```

---

### Task 7: owner Provider metadata·Codex 모델 탐색 API

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/deployments/schemas.py`
- Modify: `backend/src/ai_workshop/labs/rag/deployments/service.py`
- Modify: `backend/src/ai_workshop/labs/rag/deployments/api.py`
- Create: `backend/tests/unit/labs/rag/deployments/test_provider_metadata.py`
- Create: `backend/tests/unit/labs/rag/deployments/test_codex_models_api.py`
- Modify: `backend/tests/contract/test_openapi.py`

**Interfaces:**
- Produces: 실제 구현 Provider의 안전 metadata와 development owner-only Codex model options/auth 상태

- [ ] **Step 1: metadata와 privacy RED 테스트를 작성한다**

```python
response = owner_client.get("/api/v1/admin/rag/providers")
codex = next(item for item in response.json() if item["kind"] == "codex_sdk")
assert codex["endpoint_mode"] == "forbidden"
assert codex["secret_mode"] == "forbidden"
assert codex["development_only"] is True
assert codex["external_transfer"] is True
```

provider metadata가 enum 전체와 일치하고 미구현 Provider가 없음을 검증한다. Codex models response에는 `authenticated`, safe status, model ID/display name, checked time만 있고 email/account/token/path/raw error가 없음을 검증한다.

- [ ] **Step 2: 권한·환경 RED 테스트를 작성한다**

일반 사용자 403, staging/production 403, 미인증 시 200 safe state + empty models, exact model 사라짐 시 readiness false, 모델 조회가 생성 turn을 만들지 않음을 검증한다.

- [ ] **Step 3: RED를 확인한다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/deployments/test_provider_metadata.py tests/unit/labs/rag/deployments/test_codex_models_api.py tests/contract/test_openapi.py -q --basetemp "$env:TEMP/ai-workshop-codex-api-red"`

Expected: endpoints/schema가 없어 FAIL한다.

- [ ] **Step 4: 안전 API를 구현한다**

`GET /api/v1/admin/rag/providers`는 registry의 표시 안전 필드만 반환한다. `GET /api/v1/admin/rag/providers/codex-sdk/models`는 development owner에게만 SDK/runtime availability, 인증 bool, model options와 safe reason code를 반환한다. 로그인·token 갱신 mutation endpoint는 만들지 않는다.

- [ ] **Step 5: OpenAPI와 API tests를 통과시킨다**

Run: `cd backend; uv run pytest tests/unit/labs/rag/deployments/test_provider_metadata.py tests/unit/labs/rag/deployments/test_codex_models_api.py tests/contract/test_openapi.py -q --basetemp "$env:TEMP/ai-workshop-codex-api-green"`

Expected: registry-driven fields, owner/environment restriction, model discovery와 privacy가 PASS한다.

- [ ] **Step 6: Task 7 변경만 커밋한다**

```bash
git add backend/src/ai_workshop/labs/rag/deployments backend/tests/unit/labs/rag/deployments/test_provider_metadata.py backend/tests/unit/labs/rag/deployments/test_codex_models_api.py backend/tests/contract/test_openapi.py
git commit -m "feat(rag): expose safe Codex provider metadata"
```

---

### Task 8: registry-driven 관리자 Deployment·정책 UI

**Files:**
- Modify: `frontend/src/features/rag/models/api.ts`
- Modify: `frontend/src/features/rag/models/ModelLabPage.tsx`
- Modify: `frontend/src/features/rag/models/ModelLabPage.test.tsx`
- Modify: `frontend/src/features/rag/models/DeploymentRegistry.tsx`
- Modify: `frontend/src/features/rag/models/DeploymentRegistry.test.tsx`
- Create: `frontend/src/features/rag/models/DeploymentEditor.tsx`
- Create: `frontend/src/features/rag/models/DeploymentEditor.test.tsx`
- Modify: `frontend/src/features/rag/models/DataPolicyPanel.tsx`
- Modify: `frontend/src/features/rag/models/DataPolicyPanel.test.tsx`
- Modify: `frontend/src/app/styles.css`
- Modify: `frontend/src/shared/api/schema.d.ts`

**Interfaces:**
- Consumes: owner Provider metadata, Codex model options/auth state, Deployment create/health와 policy API
- Produces: 실제 Provider만 표시하는 생성·조회·정책 UI와 Codex 안전 안내

- [ ] **Step 1: metadata-driven rendering RED 테스트를 작성한다**

```tsx
render(<DeploymentEditor providers={[codexProvider]} codexState={readyCodexState} />);
await user.selectOptions(screen.getByLabelText("공급자"), "codex_sdk");
expect(screen.queryByLabelText("Endpoint reference")).not.toBeInTheDocument();
expect(screen.queryByLabelText("Secret reference")).not.toBeInTheDocument();
expect(screen.getByText("Codex SDK · 개발 전용")).toBeVisible();
expect(screen.getByText(/질문·대화·근거는 OpenAI로 전송/)).toBeVisible();
```

Claude/Gemini/Azure/Bedrock option 부재, 모델 선택 없음·미인증·격리 실패·운영 환경에서 저장 차단, 현재 Codex 계정 사용량 소비 안내를 검증한다.

- [ ] **Step 2: 정책 UI hardcoding 제거 RED 테스트를 작성한다**

Provider metadata에서 `external_transfer=true`인 실제 Provider만 회사·Workspace 체크박스로 표시하고 Codex와 Responses를 독립 선택·저장하는지 검증한다. local Provider는 외부 정책 목록에서 제외한다.

- [ ] **Step 3: RED를 확인한다**

Run: `cd frontend; pnpm test --run src/features/rag/models`

Expected: metadata/model API 타입과 editor가 없어 FAIL한다.

- [ ] **Step 4: OpenAPI 타입과 API client를 갱신한다**

Run: `cd frontend; pnpm api:generate`

`loadModelAdministration()`은 deployments, provider metadata, Codex safe state, model definitions, Installation·Workspace policies를 조합한다. `createDeploymentVersion()`은 선택한 Provider contract에 허용된 필드만 보낸다.

- [ ] **Step 5: Deployment 생성·조회 UI를 구현한다**

Codex 선택 시 SDK model option에서 exact ID 하나를 고르고 endpoint/key 입력을 숨긴다. `샘플링: Codex에서 관리`, `출력 한도: 응답 후 검증`, `개발 환경 전용`, 외부 전송, 로컬 Codex 로그인 사용량 안내를 항상 표시한다. 성공 시 반환된 Deployment를 registry 목록에 추가하고 상태 확인을 제공한다.

Deployment 카드의 인증 행은 backend `credential_state`를 사용해 Codex에는 `로컬 Codex 로그인
재사용`, endpoint-secret Provider에는 `인증정보 구성됨/확인 필요`를 표시한다.

- [ ] **Step 6: Provider label·policy를 metadata 기반으로 바꾼다**

`supportedProviders`, `providerLabels`, 단일 `providerValue` 상수를 제거한다. backend가 반환한 registry만 source of truth로 사용하고 readiness reason의 한국어 표시만 frontend에 둔다.

- [ ] **Step 7: frontend focused 검증을 통과시킨다**

Run: `cd frontend; pnpm test --run src/features/rag/models; pnpm typecheck; pnpm lint; pnpm api:check`

Expected: Deployment 생성, safe auth/model 상태, endpoint/secret 숨김, 동적 정책, 미구현 Provider 부재와 정적 검사가 PASS한다.

- [ ] **Step 8: Task 8 변경만 커밋한다**

```bash
git add frontend/src/features/rag/models frontend/src/app/styles.css frontend/src/shared/api/schema.d.ts
git commit -m "feat(rag): manage Codex deployments in admin UI"
```

---

### Task 9: 저장 구성 선택·실행 안내·전체 회귀 검증

**Files:**
- Modify: `frontend/src/features/rag/configurations/ConfigurationBuilder.tsx`
- Modify: `frontend/src/features/rag/configurations/ConfigurationStudioPage.test.tsx`
- Modify: `frontend/src/features/rag/search/SearchPage.tsx`
- Modify: `frontend/src/features/rag/search/SearchPage.test.tsx`
- Modify: `backend/tests/e2e/test_rag_search_flow.py`
- Modify: `docs/runbooks/local-development.md`
- Create: `docs/worklogs/2026-09-05-rag-codex-sdk-verification.md`
- Modify: `WORKBOARD.md`

**Interfaces:**
- Consumes: Codex Deployment option/readiness, 기존 외부 승인 snapshot과 execution response
- Produces: Codex 선택 전 정확한 제한 안내, 응답별 실제 실행 표시, 재현 가능한 검증 기록

- [ ] **Step 1: 관리자 저장 구성 RED 테스트를 작성한다**

Codex Generation Profile option이 `Codex SDK · 개발 전용 · exact model ID · 외부 전송`으로 표시되고, readiness false나 production이면 disabled인지 검증한다. 외부 승인 checkbox에는 현재 질문·bounded history·선별 Evidence가 OpenAI로 전송됨을 명시한다.

- [ ] **Step 2: 사용자 실행 안내 RED 테스트를 작성한다**

로그인 사용자의 검색 화면은 질문 전 Codex 외부 전송 안내를 표시하고, 응답 카드에는 server execution snapshot의 Provider·모델 정의/version·외부 위치를 표시한다. 공개 방문자에게 데이터 입력이나 Codex 실행 권한이 생기지 않음을 검증한다.

- [ ] **Step 3: RED를 확인한다**

Run: `cd frontend; pnpm test --run src/features/rag/configurations/ConfigurationStudioPage.test.tsx src/features/rag/search/SearchPage.test.tsx`

Expected: Codex-specific safe metadata가 반영되지 않아 FAIL한다.

- [ ] **Step 4: 구성·검색 UI를 구현한다**

Provider를 문자열로 추측하지 않고 backend의 `development_only`, `location`, `external_transfer`, `disclosure`, `readiness`를 사용한다. Codex SDK의 로컬 프로세스와 OpenAI 외부 추론을 함께 설명하고 답변별 execution snapshot은 해당 turn에 고정한다.

- [ ] **Step 5: backend 전체 검증을 실행한다**

Run: `cd backend; uv lock --check`

Run: `cd backend; uv run pytest tests/unit -q --basetemp "$env:TEMP/ai-workshop-codex-unit"`

Run: `cd backend; uv run pytest tests/contract tests/integration/labs/rag tests/e2e/test_rag_search_flow.py tests/integration/test_migration_0017_codex_sdk_provider.py -q --basetemp "$env:TEMP/ai-workshop-codex-integration"`

Run: `cd backend; uv run ruff check .; uv run mypy src; uv run alembic check`

Expected: 모든 명령 exit code 0이며 자동 테스트는 실제 Codex network/auth를 사용하지 않는다.

- [ ] **Step 6: frontend 전체 검증을 실행한다**

Run: `cd frontend; pnpm test --run; pnpm typecheck; pnpm lint; pnpm build; pnpm api:check`

Expected: 전체 UI tests, TypeScript, ESLint, Next.js production build와 OpenAPI drift 검사가 PASS한다.

- [ ] **Step 7: privacy·diff·프로젝트 계약을 검증한다**

Run: `git diff --check`

Run: `rg -n "auth\.json|sk-[A-Za-z0-9_-]+|Bearer [A-Za-z0-9_-]{12,}|account_id|thread_id" backend frontend docs --glob '!docs/superpowers/**'`

Run: `backend\.venv\Scripts\python.exe scripts\verify_project_agent_contracts.py validate --root .`

Expected: 실제 credential/account/thread 저장 없음, whitespace 오류 없음, 프로젝트 agent 계약 PASS. 명백한 schema/negative-test 문자열은 worklog에 파일과 이유를 기록한다.

- [ ] **Step 8: runbook·worklog·WORKBOARD를 실제 결과로 갱신한다**

runbook에는 SDK availability와 `codex login status` 확인, 개발 전용 Deployment 생성, 외부 정책·승인, 상태 확인과 안전 오류 해석을 기록한다. 인증 파일 경로나 token 복사 절차는 넣지 않는다. WORKBOARD 최근 완료는 최대 5개를 유지한다.

- [ ] **Step 9: 실제 Codex smoke 여부를 사용자에게 별도 승인받는다**

승인받은 경우에만 비민감 합성 질문·Evidence로 모델 목록, contextualize/generate 분리, 답변·인용, output usage, cleanup와 metadata-only audit를 확인한다. 승인하지 않으면 자동 검증 완료와 실제 smoke 미수행을 명확히 기록한다.

- [ ] **Step 10: 최종 구현·검증 문서를 커밋한다**

```bash
git add frontend/src/features/rag/configurations frontend/src/features/rag/search backend/tests/e2e/test_rag_search_flow.py docs/runbooks/local-development.md docs/worklogs/2026-09-05-rag-codex-sdk-verification.md WORKBOARD.md
git commit -m "docs(rag): verify Codex SDK provider"
```

---

## Completion Review

- [ ] 설계 수용 기준 14개가 최소 한 Task와 자동 test 또는 승인형 smoke에 연결됐는지 대조한다.
- [ ] 계획 전체를 검색해 미결정 표식과 미래 Provider 구현 지시가 없는지 확인한다. 테스트용 fake SDK gateway 표현만 허용한다.
- [ ] `ProviderKind`, Provider registry, Pydantic schema, SQLAlchemy column, Alembic migration, generated TypeScript type의 nullable endpoint와 enum이 일치하는지 확인한다.
- [ ] `GenerationProfile.temperature`, `SamplingMode`, YAML/profile parser, local/Responses/Codex runtime과 관리자 표시의 의미가 일치하는지 확인한다.
- [ ] 구현 역할과 독립 검증/리뷰 역할을 분리하고 메인 Codex만 통합, WORKBOARD, staging, commit과 push를 결정한다.
