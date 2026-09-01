# Project Development Agent Organization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 도구 독립 역할 계약, 필수 역할 선택 규칙, 공통·RAG 역할 카탈로그, Codex 오케스트레이션 어댑터와 검증 도구를 구현한다.

**Architecture:** `docs/project-agents/`를 도구 독립 정본으로 사용하고 YAML frontmatter와 Markdown 본문을 Python 검증기가 검사한다. 메인 Codex는 얇은 어댑터 지침을 통해 정본을 읽고 필수 역할을 선택하며, 다중 역할 작업의 임시 기록은 Git에서 제외된 `.local-data/project-agent-work/`에서 성공 시 정리한다.

**Tech Stack:** Markdown, YAML frontmatter, Python 3.13, PyYAML, pytest, Ruff, mypy, Git/Codex repository instructions

**Spec:** `docs/superpowers/specs/2026-09-02-project-development-agent-organization-design.md`

## Global Constraints

- 역할 계약은 도구 독립 정본과 Codex 어댑터를 분리한다.
- 메인 Codex만 프로젝트 오케스트레이터로서 실제 역할 호출과 최종 통합을 결정한다.
- 작업별 필요한 역할만 선택하고 참여·제외 이유를 사용자에게 먼저 고지한다.
- 구현 역할과 독립 검증·리뷰 역할을 같은 작업 책임으로 합치지 않는다.
- 하드코딩 방지는 프론트엔드, 백엔드, DB, 인프라, AI와 미래 Labs 전체에 적용한다.
- 아직 시작하지 않은 AI 도메인의 빈 역할·소스 폴더와 가짜 메뉴를 만들지 않는다.
- 임시 에이전트 기록은 `.local-data/project-agent-work/<task-id>/` 밖에 만들지 않고 Git에 추가하지 않는다.
- 성공한 임시 기록만 정리하며 실패·차단 상태의 최소 진단 기록은 유지한다.
- 루트 `AGENTS.md`는 공백 포함 200줄 이하, `WORKBOARD.md` 최근 완료는 5개 이하로 유지한다.
- 새 Python 의존성을 추가하지 않고 이미 고정된 PyYAML, pytest, Ruff와 mypy를 사용한다.
- 역할 메타데이터는 각 역할 파일 frontmatter 하나만 정본으로 사용한다.

## File Map

### Validation tooling

- Create `scripts/project_agents/__init__.py`: 검증기 공개 타입과 함수를 노출한다.
- Create `scripts/project_agents/contracts.py`: 역할·activation·workflow 문서를 파싱하고 구조를 검증한다.
- Create `scripts/project_agents/selection.py`: activation signal에서 필수 역할 ID를 합성한다.
- Create `scripts/verify_project_agent_contracts.py`: 저장소 전체 검증과 역할 선택 CLI를 제공한다.
- Create `scripts/tests/test_project_agent_contracts.py`: parser, validator, selector와 저장소 통합 회귀 테스트를 둔다.

### Tool-independent governance

- Create `docs/project-agents/README.md`: 정본 진입점과 필요한 문서만 읽는 순서를 정의한다.
- Create `docs/project-agents/governance/role-contract.md`: 역할 파일 schema와 필수 절을 정의한다.
- Create `docs/project-agents/governance/orchestration.md`: 선택, 고지, 배정, 통합과 권한을 정의한다.
- Create `docs/project-agents/governance/activation-rules.md`: machine-readable rule frontmatter와 설명을 둔다.
- Create `docs/project-agents/governance/hardcoding-policy.md`: 프로젝트 공통·기술별·도메인별 하드코딩 규칙을 둔다.
- Create `docs/project-agents/governance/temporary-work-lifecycle.md`: 임시 기록 상태와 정리 게이트를 둔다.
- Create four files under `docs/project-agents/workflows/`: 반복 작업 흐름과 최소 signal을 정의한다.

### Role contracts

- Create 14 common role files under `docs/project-agents/roles/`.
- Create `docs/project-agents/domains/rag/rag-lead.md` and eight RAG specialist role files.

### Repository adapters and policies

- Create `docs/guidelines/codex/project-agent-orchestration.md`: Codex sub-agent 호출과 인계 매핑만 정의한다.
- Modify `docs/guidelines/codex/README.md`: 새 Codex 참고 정본을 연결한다.
- Modify `AGENTS.md`: 오케스트레이터 의무와 정본 링크를 짧게 추가한다.
- Modify `CACHE_POLICY.md`: 프로젝트 에이전트 임시 기록의 보존·정리 경계를 추가한다.
- Verify `.gitignore`: 기존 `.local-data/` 제외가 새 임시 경로를 포함하는지 검사하고 중복 패턴은 추가하지 않는다.
- Modify `WORKBOARD.md`: 도입 상태, 검증 결과와 다음 DOCX 작업을 반영한다.

---

### Task 1: Role Contract Parser and Validator

**Files:**
- Create: `scripts/project_agents/__init__.py`
- Create: `scripts/project_agents/contracts.py`
- Create: `scripts/verify_project_agent_contracts.py`
- Create: `scripts/tests/test_project_agent_contracts.py`

**Interfaces:**
- Produces: `RoleContract`, `ValidationIssue`
- Produces: `load_role(path: Path) -> RoleContract`
- Produces: `validate_repository(root: Path) -> list[ValidationIssue]`
- Produces: `verify_project_agent_contracts.py validate --root PATH`
- Consumes: YAML frontmatter and Markdown role documents

- [ ] **Step 1: Write failing parser and validation tests**

Create temporary repositories in pytest fixtures. Test valid frontmatter, missing frontmatter, duplicate `role_id`, invalid enum values, missing required headings, unresolved `independent_from`, unresolved activation references, `AGENTS.md` over 200 lines, more than five recent completions and a tracked temporary work path.

```python
def test_duplicate_role_ids_are_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="duplicate")
    write_role(tmp_path, "roles/b.md", role_id="duplicate")

    issues = validate_repository(tmp_path)

    assert any(issue.code == "duplicate_role_id" for issue in issues)


def test_missing_required_heading_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    role = write_role(tmp_path, "roles/a.md", role_id="frontend-engineer")
    role.write_text(role.read_text(encoding="utf-8").replace("## 필수 검증\n", ""), encoding="utf-8")

    issues = validate_repository(tmp_path)

    assert any(issue.code == "missing_role_section" for issue in issues)
```

- [ ] **Step 2: Run the tests and verify RED**

Run from the repository root:

```powershell
$repositoryRoot = (Resolve-Path .).Path
docker run --rm --volume "${repositoryRoot}:/workspace" --workdir /workspace --entrypoint python ai-workshop-backend:local -m pytest -p no:cacheprovider --basetemp=/tmp/pytest scripts/tests/test_project_agent_contracts.py -q
```

Expected: collection or import failure because `scripts.project_agents.contracts` does not exist.

- [ ] **Step 3: Implement typed contracts and frontmatter parsing**

Use the already installed `yaml.safe_load`. Reject non-mapping frontmatter and empty values with bounded issue codes rather than raw parser traces.

```python
@dataclass(frozen=True)
class RoleContract:
    role_id: str
    name: str
    category: str
    scope: str
    activation: str
    independent_from: tuple[str, ...]
    path: Path


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: Path
    message: str
```

Use these exact allowed values:

```python
ALLOWED_CATEGORIES = frozenset({
    "leadership",
    "architecture",
    "engineering",
    "operations",
    "quality",
    "documentation",
    "domain-leadership",
    "domain-specialist",
})
ALLOWED_SCOPES = frozenset({"project", "rag"})
ALLOWED_ACTIVATIONS = frozenset({"always", "conditional"})
```

Require these exact headings in every role file:

```python
REQUIRED_ROLE_HEADINGS = (
    "## 목적",
    "## 담당 범위",
    "## 호출 조건",
    "## 비호출 조건",
    "## 작업 전 필수 문서",
    "## 필수 입력",
    "## 책임",
    "## 권한",
    "## 금지 사항",
    "## 산출물",
    "## 인계",
    "## 설정·하드코딩 점검",
    "## 필수 검증",
    "## 완료 조건",
    "## 중단·에스컬레이션",
)
```

`validate_repository` must also check unique IDs, referenced IDs, actual role files, placeholder text, `AGENTS.md` line count, `WORKBOARD.md` recent completion count and tracked paths under `.local-data/project-agent-work/` using `git ls-files` only when the root is a Git repository.

Add the initial `validate` CLI subcommand in `scripts/verify_project_agent_contracts.py`. It prints one bounded `path: code: message` line per issue and returns `1` when issues exist, otherwise `0`. Task 5 extends this existing CLI with `select`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Task 1 command again.

Expected: all parser and negative validation tests pass.

- [ ] **Step 5: Run static checks**

```powershell
$repositoryRoot = (Resolve-Path .).Path
docker run --rm --volume "${repositoryRoot}:/workspace" --workdir /workspace --entrypoint /bin/sh ai-workshop-backend:local -c "ruff check --no-cache scripts/project_agents scripts/tests && mypy --strict --cache-dir=/tmp/mypy-cache scripts/project_agents scripts/tests"
```

Expected: Ruff reports `All checks passed!`; mypy reports no issues.

- [ ] **Step 6: Commit Task 1**

```powershell
git add scripts/project_agents scripts/verify_project_agent_contracts.py scripts/tests/test_project_agent_contracts.py
git commit -m "add project agent contract validator"
```

### Task 2: Machine-Readable Activation Rules and Mandatory Role Selector

**Files:**
- Create: `scripts/project_agents/selection.py`
- Create: `docs/project-agents/governance/activation-rules.md`
- Modify: `scripts/project_agents/contracts.py`
- Modify: `scripts/project_agents/__init__.py`
- Modify: `scripts/tests/test_project_agent_contracts.py`

**Interfaces:**
- Produces: `ActivationRule(signal: str, required_roles: tuple[str, ...])`
- Consumes: `ActivationRule(signal: str, required_roles: tuple[str, ...])`
- Produces: `load_activation_rules(path: Path) -> tuple[ActivationRule, ...]`
- Produces: `select_required_roles(signals: Iterable[str], rules: Iterable[ActivationRule]) -> tuple[str, ...]`
- Selection output is sorted and duplicate-free; it is a mandatory baseline, not the complete contextual roster.

- [ ] **Step 1: Write failing activation tests**

```python
def test_selector_unions_mandatory_roles_without_duplicates() -> None:
    rules = (
        ActivationRule("react-ui", ("frontend-engineer", "integration-e2e-verifier")),
        ActivationRule("feature-implementation", ("test-designer", "integration-e2e-verifier")),
    )

    selected = select_required_roles({"react-ui", "feature-implementation"}, rules)

    assert selected == (
        "frontend-engineer",
        "integration-e2e-verifier",
        "test-designer",
    )


def test_unknown_signal_is_reported() -> None:
    with pytest.raises(UnknownActivationSignalError, match="unknown-signal"):
        select_required_roles({"unknown-signal"}, ())
```

- [ ] **Step 2: Run focused tests and verify RED**

Run the Task 1 pytest command.

Expected: import failure for `scripts.project_agents.selection` or failing selector assertions.

- [ ] **Step 3: Implement activation parsing and deterministic selection**

The activation document frontmatter must use this structure:

```yaml
---
schema_version: 1
rules:
  - signal: requirements-or-behavior
    required_roles: [requirements-implementation-designer]
  - signal: cross-module-or-public-contract
    required_roles: [system-architect]
  - signal: react-ui
    required_roles: [frontend-engineer]
  - signal: python-api-or-worker
    required_roles: [python-backend-engineer]
  - signal: ai-model-or-runtime
    required_roles: [ai-engineer]
  - signal: database-or-migration
    required_roles: [database-administrator]
  - signal: docker-compose-or-deployment
    required_roles: [infrastructure-docker-engineer]
  - signal: authentication-permission-or-exposure
    required_roles: [security-permission-verifier]
  - signal: privacy-or-external-transfer
    required_roles: [data-privacy-verifier]
  - signal: rag-behavior
    required_roles: [rag-lead]
  - signal: feature-implementation
    required_roles: [test-designer, integration-e2e-verifier]
  - signal: significant-change-or-merge
    required_roles: [independent-code-reviewer]
  - signal: design-adr-or-document-structure
    required_roles: [design-adr-documentation-manager]
---
```

The body explains that the selector returns minimum mandatory roles. The orchestrator adds domain specialists based on actual scope and records both selected and excluded roles.

- [ ] **Step 4: Run tests and repository validation**

The unit fixture must supply referenced role files, so the temporary test repository passes after the selector is correct. Full repository validation is expected to report missing role contracts until Tasks 3 and 4.

- [ ] **Step 5: Run Ruff and mypy**

Run the Task 1 static-check command.

Expected: all checks pass.

- [ ] **Step 6: Commit Task 2**

```powershell
git add scripts/project_agents scripts/tests/test_project_agent_contracts.py docs/project-agents/governance/activation-rules.md
git commit -m "define project agent activation rules"
```

### Task 3: Governance Documents and Common Role Contracts

**Files:**
- Create: `docs/project-agents/README.md`
- Create: `docs/project-agents/governance/role-contract.md`
- Create: `docs/project-agents/governance/orchestration.md`
- Create: `docs/project-agents/governance/hardcoding-policy.md`
- Create: 14 common role files listed below
- Modify: `scripts/tests/test_project_agent_contracts.py`

**Interfaces:**
- Consumes: exact role schema and activation references from Tasks 1 and 2
- Produces: all project-scope role IDs required by activation rules
- Produces: one tool-independent entry point at `docs/project-agents/README.md`

- [ ] **Step 1: Write the failing common-catalog integration test**

```python
EXPECTED_PROJECT_ROLE_IDS = {
    "project-orchestrator",
    "requirements-implementation-designer",
    "system-architect",
    "frontend-engineer",
    "python-backend-engineer",
    "ai-engineer",
    "database-administrator",
    "infrastructure-docker-engineer",
    "test-designer",
    "integration-e2e-verifier",
    "security-permission-verifier",
    "data-privacy-verifier",
    "independent-code-reviewer",
    "design-adr-documentation-manager",
}


def test_repository_contains_exact_initial_project_roles(repository_root: Path) -> None:
    roles = load_repository_roles(repository_root)
    project_ids = {role.role_id for role in roles if role.scope == "project"}
    assert project_ids == EXPECTED_PROJECT_ROLE_IDS
```

- [ ] **Step 2: Run the integration test and verify RED**

Run the Task 1 pytest command.

Expected: the expected project role IDs are missing.

- [ ] **Step 3: Write governance documents**

`README.md` links only the governance documents, role categories, current RAG domain and Codex adapter. `role-contract.md` defines the exact frontmatter enums and 15 required headings. `orchestration.md` defines classification, notification, non-overlapping assignments, implementation/verification separation, scope recalculation and orchestrator-only integration.

`hardcoding-policy.md` must contain these project-wide sections:

- forbidden mutable literals and sensitive values
- allowed protocol and domain invariants
- frontend feature/Lab registry and design tokens
- backend typed settings, enums and domain policies
- DB named identity and repository lookup
- infrastructure environment and validated deployment settings
- AI model registry and versioned indexing/retrieval/generation profiles
- public synthetic test fixtures
- mandatory implementation handoff checklist

- [ ] **Step 4: Create all common role contracts from one exact template**

Use this body structure in every file and fill each section with role-specific content; empty sections and generic `프로젝트 규칙을 따른다` placeholders are invalid.

```markdown
---
role_id: <exact-id-from-table>
name: <Korean role name>
category: <exact category>
scope: project
activation: <always only for orchestrator, otherwise conditional>
independent_from: [<exact role IDs>]
---

# <Korean role name>

## 목적
## 담당 범위
## 호출 조건
## 비호출 조건
## 작업 전 필수 문서
## 필수 입력
## 책임
## 권한
## 금지 사항
## 산출물
## 인계
## 설정·하드코딩 점검
## 필수 검증
## 완료 조건
## 중단·에스컬레이션
```

Create these exact files and responsibilities:

| Path | Role ID | Category | Primary responsibility |
|---|---|---|---|
| `roles/leadership/project-orchestrator.md` | `project-orchestrator` | leadership | classification, roster, scope, integration, commit/push |
| `roles/architecture/requirements-implementation-designer.md` | `requirements-implementation-designer` | architecture | success criteria and implementable contract |
| `roles/architecture/system-architect.md` | `system-architect` | architecture | module/public interface boundaries |
| `roles/engineering/frontend-engineer.md` | `frontend-engineer` | engineering | React UI, route, registry and accessibility |
| `roles/engineering/python-backend-engineer.md` | `python-backend-engineer` | engineering | FastAPI, application and worker code |
| `roles/engineering/ai-engineer.md` | `ai-engineer` | engineering | model runtime, provider policy and reproducibility |
| `roles/operations/database-administrator.md` | `database-administrator` | operations | schema, query, migration and data safety |
| `roles/operations/infrastructure-docker-engineer.md` | `infrastructure-docker-engineer` | operations | Docker, Compose, runtime resources and recovery |
| `roles/quality/test-designer.md` | `test-designer` | quality | failing acceptance and edge-case tests before implementation |
| `roles/quality/integration-e2e-verifier.md` | `integration-e2e-verifier` | quality | independent cross-boundary verification |
| `roles/quality/security-permission-verifier.md` | `security-permission-verifier` | quality | authentication, authorization and exposure review |
| `roles/quality/data-privacy-verifier.md` | `data-privacy-verifier` | quality | sensitive data, logging and external transfer review |
| `roles/quality/independent-code-reviewer.md` | `independent-code-reviewer` | quality | read-only spec, quality and regression review |
| `roles/documentation/design-adr-documentation-manager.md` | `design-adr-documentation-manager` | documentation | official document boundaries and canonical links |

Implementation roles must declare independence from `integration-e2e-verifier` and `independent-code-reviewer`. The two independent roles must prohibit implementing the same change they approve.

- [ ] **Step 5: Run common-catalog tests and validator**

Run the Task 1 pytest command, then:

```powershell
$repositoryRoot = (Resolve-Path .).Path
docker run --rm --volume "${repositoryRoot}:/workspace" --workdir /workspace --entrypoint python ai-workshop-backend:local scripts/verify_project_agent_contracts.py validate --root /workspace
```

Expected: unit tests pass. Repository validation may still report only missing RAG roles and workflow documents that Task 4 creates; it must not report common role schema errors.

- [ ] **Step 6: Commit Task 3**

```powershell
git add docs/project-agents scripts/tests/test_project_agent_contracts.py
git commit -m "add common project agent contracts"
```

### Task 4: RAG Hierarchy and Workflow Contracts

**Files:**
- Create: `docs/project-agents/domains/rag/rag-lead.md`
- Create: eight files under `docs/project-agents/domains/rag/roles/`
- Create: four files under `docs/project-agents/workflows/`
- Modify: `scripts/project_agents/contracts.py`
- Modify: `scripts/tests/test_project_agent_contracts.py`

**Interfaces:**
- Produces: exact RAG role IDs and `scope: rag`
- Produces: `WorkflowContract(workflow_id: str, default_signals: tuple[str, ...], path: Path)`
- Produces: `load_workflow(path: Path) -> WorkflowContract`
- Produces: workflow frontmatter with `workflow_id` and `default_signals`
- Consumes: Task 2 activation signals and Task 3 common verification roles

- [ ] **Step 1: Write failing RAG catalog and workflow tests**

```python
EXPECTED_RAG_ROLE_IDS = {
    "rag-lead",
    "document-structure-parser",
    "chunking-evidence-unit-specialist",
    "embedding-model-specialist",
    "indexing-specialist",
    "retrieval-fusion-specialist",
    "evidence-highlight-viewer-specialist",
    "generation-llm-specialist",
    "rag-evaluation-specialist",
}

EXPECTED_WORKFLOW_IDS = {
    "feature-development",
    "bug-fix",
    "architecture-change",
    "destructive-operation",
}
```

Assert exact IDs, no extra future-domain roles, valid references and that each workflow's signals exist in activation rules.

- [ ] **Step 2: Run tests and verify RED**

Run the Task 1 pytest command.

Expected: RAG roles and workflows are missing.

- [ ] **Step 3: Create the RAG role hierarchy**

Use the Task 3 role template with `scope: rag`. Create these exact files:

| Path | Role ID | Primary responsibility |
|---|---|---|
| `domains/rag/rag-lead.md` | `rag-lead` | RAG scope, specialist requests and end-to-end quality |
| `domains/rag/roles/document-structure-parser.md` | `document-structure-parser` | format parsing and source location fidelity |
| `domains/rag/roles/chunking-evidence-unit-specialist.md` | `chunking-evidence-unit-specialist` | Evidence Unit and chunk boundaries |
| `domains/rag/roles/embedding-model-specialist.md` | `embedding-model-specialist` | embedding compatibility and tokenizer limits |
| `domains/rag/roles/indexing-specialist.md` | `indexing-specialist` | physical index version, mapping and activation |
| `domains/rag/roles/retrieval-fusion-specialist.md` | `retrieval-fusion-specialist` | BM25, dense retrieval, RRF and reranking |
| `domains/rag/roles/evidence-highlight-viewer-specialist.md` | `evidence-highlight-viewer-specialist` | provenance, semantic highlight and viewer contract |
| `domains/rag/roles/generation-llm-specialist.md` | `generation-llm-specialist` | grounded generation after retrieval quality gate |
| `domains/rag/roles/rag-evaluation-specialist.md` | `rag-evaluation-specialist` | frozen datasets, metrics and promotion evidence |

`rag-lead` may request specialists but cannot invoke them directly. Each specialist must identify when the common AI, backend, frontend, DB, security or data role is also mandatory.

- [ ] **Step 4: Create workflow contracts**

Each workflow frontmatter uses this exact schema:

```yaml
---
schema_version: 1
workflow_id: feature-development
default_signals:
  - requirements-or-behavior
  - feature-implementation
---
```

Use these defaults:

| Workflow | Default signals | Mandatory behavior |
|---|---|---|
| feature-development | requirements-or-behavior, feature-implementation | design before implementation and independent validation |
| bug-fix | feature-implementation | reproduce RED, fix, GREEN, regression review |
| architecture-change | requirements-or-behavior, cross-module-or-public-contract, significant-change-or-merge, design-adr-or-document-structure | approved design and independent review |
| destructive-operation | significant-change-or-merge | exact targets, policy precheck, user approval and post-verification |

The destructive workflow body must state that domain-specific policies such as `CACHE_POLICY.md` remain authoritative and workflow selection never grants destructive authority.

- [ ] **Step 5: Run all contract tests and repository validation**

Run both Task 3 validation commands.

Expected: all tests pass and repository validation reports no contract, role reference or workflow errors.

- [ ] **Step 6: Commit Task 4**

```powershell
git add docs/project-agents/domains docs/project-agents/workflows scripts/tests/test_project_agent_contracts.py
git commit -m "add RAG agent hierarchy and workflows"
```

### Task 5: CLI, Codex Adapter and Root Instructions

**Files:**
- Modify: `scripts/verify_project_agent_contracts.py`
- Create: `docs/guidelines/codex/project-agent-orchestration.md`
- Modify: `docs/guidelines/codex/README.md`
- Modify: `AGENTS.md`
- Modify: `scripts/tests/test_project_agent_contracts.py`

**Interfaces:**
- CLI: `verify_project_agent_contracts.py validate --root PATH`
- CLI: `verify_project_agent_contracts.py select --root PATH --signal SIGNAL [--signal SIGNAL ...]`
- Exit `0` on valid contracts, exit `1` with bounded `path: code: message` lines on validation failure, exit `2` on CLI usage error.

- [ ] **Step 1: Write failing CLI and adapter tests**

```python
def test_cli_validate_returns_zero_for_repository(repository_root: Path) -> None:
    result = run_cli("validate", "--root", str(repository_root))
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_select_prints_sorted_mandatory_roles(repository_root: Path) -> None:
    result = run_cli(
        "select",
        "--root",
        str(repository_root),
        "--signal",
        "react-ui",
        "--signal",
        "feature-implementation",
    )
    assert result.stdout.splitlines() == [
        "frontend-engineer",
        "integration-e2e-verifier",
        "test-designer",
    ]
```

Also assert `AGENTS.md` links both `docs/project-agents/README.md` and the Codex adapter and remains at most 200 lines.

- [ ] **Step 2: Run tests and verify RED**

Run the Task 1 pytest command.

Expected: CLI file and root instruction links are missing.

- [ ] **Step 3: Extend the thin CLI with mandatory-role selection**

```python
def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        issues = validate_repository(args.root)
        for issue in issues:
            print(f"{issue.path}: {issue.code}: {issue.message}")
        return 1 if issues else 0
    rules = load_activation_rules(args.root / ACTIVATION_RULES_PATH)
    for role_id in select_required_roles(args.signal, rules):
        print(role_id)
    return 0
```

Do not add task-specific role selection logic to the CLI. It returns mandatory rules only; the orchestrator retains contextual selection authority.

- [ ] **Step 4: Write the Codex adapter**

The adapter must instruct the main Codex to:

1. read the workboard and classify the task;
2. consult activation signals and only selected role files;
3. announce task class, risk, selected roles, reasons and meaningful exclusions;
4. use delegated agents only for concrete bounded scopes and never overlapping writes;
5. keep implementers separate from validators and reviewers;
6. require evidence-backed handoffs;
7. stop and recalculate the roster when scope expands;
8. keep temporary work local and clean it only after the verified gate;
9. let the main orchestrator own integration, Workboard finalization, staging, commit and push.

The adapter references the tool-independent documents instead of copying their role content.

- [ ] **Step 5: Add concise root instructions and Codex index link**

Add a `프로젝트 개발 에이전트` section to `AGENTS.md` with no more than eight bullets. Add one row to the Codex reference table. Do not repeat the role catalog in either file.

- [ ] **Step 6: Run CLI, tests and static checks**

Run the Task 1 pytest and static-check commands, then both CLI commands from the Interfaces block.

Expected: all exit `0`; selection output is exact and sorted; `AGENTS.md` remains at most 200 lines.

- [ ] **Step 7: Commit Task 5**

```powershell
git add AGENTS.md docs/guidelines/codex scripts/verify_project_agent_contracts.py scripts/tests/test_project_agent_contracts.py
git commit -m "connect Codex project agent orchestration"
```

### Task 6: Temporary Work Lifecycle and Repository Safety Gates

**Files:**
- Create: `docs/project-agents/governance/temporary-work-lifecycle.md`
- Modify: `CACHE_POLICY.md`
- Verify without modification unless needed: `.gitignore`
- Modify: `scripts/project_agents/contracts.py`
- Modify: `scripts/tests/test_project_agent_contracts.py`

**Interfaces:**
- Temporary root: `.local-data/project-agent-work/<task-id>/`
- Allowed states: `active`, `validating`, `failed`, `blocked`, `verified`
- Cleanup readiness is a documented gate; the validator proves Git exclusion and rejects tracked temporary paths.

- [ ] **Step 1: Write failing lifecycle safety tests**

```python
def test_repository_ignores_project_agent_temporary_root(repository_root: Path) -> None:
    result = subprocess.run(
        ["git", "check-ignore", ".local-data/project-agent-work/example/task-brief.md"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_cache_policy_classifies_agent_work_as_temporary(repository_root: Path) -> None:
    policy = (repository_root / "CACHE_POLICY.md").read_text(encoding="utf-8")
    assert ".local-data/project-agent-work" in policy
    assert "verified" in policy
```

Add fixture validation that a tracked path under the temporary root returns `tracked_temporary_agent_work`.

- [ ] **Step 2: Run tests and verify RED**

Run the Task 1 pytest command.

Expected: `CACHE_POLICY.md` classification assertion fails.

- [ ] **Step 3: Write the lifecycle contract**

Define exact state transitions and cleanup gates. `verified` requires implementation complete, relevant checks passing, independent review clear, no unresolved security/data/migration issue and canonical docs updated. `failed` and `blocked` preserve only diagnostic input, bounded result and unresolved issue; never preserve internal reasoning, secrets or source data.

Automatic cleanup means the orchestrator performs the exact task-directory cleanup as the final workflow step. It is not a broad prune and does not permit deletion outside `.local-data/project-agent-work/<task-id>/`. Any applicable cache safety instruction and exact-target check remains mandatory.

- [ ] **Step 4: Update cache policy without duplicating lifecycle detail**

Add one filesystem classification row and one lifecycle link. State that unresolved tasks are preserved, verified tasks are candidates for exact-path cleanup, and reparse points or paths outside the temporary root are blocked. Keep `destructive_approval: required` unchanged.

`.gitignore` already excludes `.local-data/`; do not add a redundant narrower rule when the test proves the existing rule works.

- [ ] **Step 5: Run lifecycle tests, full validator and static checks**

Run the Task 1 pytest/static commands and `validate` CLI.

Expected: all pass; `.gitignore` remains unchanged; no temporary work file is tracked.

- [ ] **Step 6: Commit Task 6**

```powershell
git add CACHE_POLICY.md docs/project-agents/governance/temporary-work-lifecycle.md scripts/project_agents/contracts.py scripts/tests/test_project_agent_contracts.py
git commit -m "define project agent temporary work lifecycle"
```

### Task 7: Scenario Verification, Documentation Finalization and Handoff

**Files:**
- Modify: `scripts/tests/test_project_agent_contracts.py`
- Modify: `docs/project-agents/README.md`
- Modify: `docs/superpowers/specs/2026-09-02-project-development-agent-organization-design.md`
- Modify: `WORKBOARD.md`

**Interfaces:**
- Consumes: all role IDs, activation rules, workflows, CLI and lifecycle policy
- Produces: verified repository state and next task `DOCX 구조 파서·원문 뷰어 계약 설계`

- [ ] **Step 1: Add representative selection scenario tests**

Assert these exact mandatory baselines:

```python
SCENARIOS = {
    frozenset({"react-ui", "feature-implementation"}): {
        "frontend-engineer",
        "test-designer",
        "integration-e2e-verifier",
    },
    frozenset({"python-api-or-worker", "database-or-migration", "feature-implementation"}): {
        "python-backend-engineer",
        "database-administrator",
        "test-designer",
        "integration-e2e-verifier",
    },
    frozenset({"ai-model-or-runtime", "rag-behavior", "feature-implementation"}): {
        "ai-engineer",
        "rag-lead",
        "test-designer",
        "integration-e2e-verifier",
    },
    frozenset({"authentication-permission-or-exposure", "privacy-or-external-transfer"}): {
        "security-permission-verifier",
        "data-privacy-verifier",
    },
}
```

Add a documentation-only scenario proving the orchestrator can work alone for a trivial typo and that workflow defaults do not force unneeded domain roles.

- [ ] **Step 2: Run scenario tests and fix only contract inconsistencies**

Run the Task 1 pytest command.

Expected: all scenarios pass. If a rule is inconsistent, update the canonical activation rule and its explanation together; do not special-case the test in Python.

- [ ] **Step 3: Update the entry point and approved spec status**

`docs/project-agents/README.md` must show:

1. read governance entry points;
2. classify signals;
3. select mandatory baseline;
4. add contextual specialists;
5. announce roster and exclusions;
6. execute with independent validation;
7. finalize canonical artifacts;
8. clean verified temporary records.

Update the design spec implementation status without changing approved decisions.

- [ ] **Step 4: Update WORKBOARD with at most five recent completions**

Set the next work to DOCX Evidence Unit and viewer contract design. Record the project agent organization as the newest completed item and remove the oldest completion so the list remains five.

- [ ] **Step 5: Run the full final verification suite**

```powershell
$repositoryRoot = (Resolve-Path .).Path
docker run --rm --volume "${repositoryRoot}:/workspace" --workdir /workspace --entrypoint python ai-workshop-backend:local -m pytest -p no:cacheprovider --basetemp=/tmp/pytest scripts/tests/test_project_agent_contracts.py -q
docker run --rm --volume "${repositoryRoot}:/workspace" --workdir /workspace --entrypoint /bin/sh ai-workshop-backend:local -c "ruff check --no-cache scripts/project_agents scripts/tests && mypy --strict --cache-dir=/tmp/mypy-cache scripts/project_agents scripts/tests"
docker run --rm --volume "${repositoryRoot}:/workspace" --workdir /workspace --entrypoint python ai-workshop-backend:local scripts/verify_project_agent_contracts.py validate --root /workspace
docker run --rm --volume "${repositoryRoot}:/workspace" --workdir /workspace --entrypoint python ai-workshop-backend:local scripts/verify_project_agent_contracts.py select --root /workspace --signal react-ui --signal feature-implementation
git diff --check
git status --short
```

Expected:

- all project-agent tests pass;
- Ruff and mypy report no issues;
- contract validation exits `0` with no issue lines;
- selector outputs `frontend-engineer`, `integration-e2e-verifier`, `test-designer` in sorted order;
- `git diff --check` exits `0`;
- only implementation-plan files are modified before the final commit;
- `AGENTS.md` has at most 200 lines and recent completions are at most five;
- no `.local-data/project-agent-work/` path is tracked.

- [ ] **Step 6: Perform an independent final review**

The reviewer reads the approved spec, all staged changes and actual verification output. It must confirm role completeness, tool-independent/Codex separation, no self-approval path, no RAG-only hardcoding policy, no future-domain placeholders and no cleanup path escaping the temporary root.

- [ ] **Step 7: Commit and push the completed organization**

```powershell
git add AGENTS.md CACHE_POLICY.md WORKBOARD.md docs/project-agents docs/guidelines/codex docs/superpowers/specs/2026-09-02-project-development-agent-organization-design.md scripts/project_agents scripts/tests/test_project_agent_contracts.py scripts/verify_project_agent_contracts.py
git commit -m "implement project development agent organization"
git push origin main
```

- [ ] **Step 8: Verify post-push state**

Confirm `git status --short` is empty and `git rev-parse HEAD` equals `git rev-parse origin/main`. Report the commit, exact validation commands and next work from `WORKBOARD.md`.
