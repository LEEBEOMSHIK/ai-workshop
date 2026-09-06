# Codex App Server 격리 feasibility gate 차단 기록

- 날짜: 2026-09-06
- 범위: 개발 전용 Codex App Server 후보의 content 전송 전 격리 가능성 확인
- 관련 결정: `docs/decisions/0011-development-codex-app-server-provider.md`
- 결과: 차단

## 실행한 진단과 결과

정확히 고정해 시험한 버전은 `codex-cli 0.151.0`이다. 다음은 의미 수준의 명령명만 기록한
진단 순서이며, 원시 protocol·호스트 경로·환경·계정·구성 값은 남기지 않는다.

1. `version`으로 설치된 CLI 버전을 확인했다.
2. `generate schema`로 비실험 App Server schema를 생성했다.
3. `no-content isolation gate`로 본문 없는 live 상태 검사를 실행했다.
4. `transport cleanup`으로 프로세스를 정리했다.

생성 schema에는 `config/read`, `configRequirements/read`, MCP·skill·hook·app·plugin 목록과
thread·turn 작업 등 안정적인 상태 메서드가 있다. 그러나 대상 thread의 effective per-thread
built-in tool inventory를 증명하는 안정 계약은 없다. 기능 플래그나 선언된 sandbox로 이
inventory를 추정하지 않으므로 schema gate는 fail closed 했다.

no-content live gate는 exit 1과 안전 코드 `codex_isolation_not_enforced`를 반환했다. runtime
state는 검증되지 않았으며 sanitized report의 안정 규칙 ID는 다음과 같다.

```text
config_state_unverified
requirements_state_unverified
tool_inventory_unverified
forbidden_builtin_tool
shell_enabled
web_enabled
apps_enabled
plugins_enabled
multi_agent_enabled
mcp_callable
app_callable
plugin_enabled
skill_enabled
hook_enabled
approval_policy_not_never
sandbox_not_read_only
```

관측 hash는
`37e116c961c281854b4d646edd753979c9f01915d7f6573223d216f2cf283a67`이다.

## 해석과 개인정보 경계

질문, 대화 이력, Evidence, `thread/start`, `turn/start`는 전송하지 않았다. Windows transport
cleanup은 unsanitized runtime warning을 냈지만 원시 출력은 이 worklog나 다른 추적 문서에
복사하지 않는다. 이 기록은 상태·안전 코드·규칙 ID·관측 hash만 보존한다.

App Server 후보는 승인된 Provider가 아니다. FAIL 뒤 후보 gate source·test·script entry를
제거했으며 Provider 등록, migration, DB, UI 또는 RAG 질문 실행은 수행하지 않았다.

## 검증

- 후보 CLI의 repository-root 권한 교정까지 포함한 격리 테스트는 제거 전에 `150 passed,
  6 skipped`였고 Ruff와 mypy가 통과했다.
- FAIL 경로로 후보 source·test·script entry를 제거한 뒤 backend unit은 `636 passed`, Ruff는
  통과, mypy는 `166 source files`에서 통과했다. backend source·test·project script에는 후보
  심볼 참조가 남지 않았다.
- 전체 backend 880건도 실행했으나 현재 로컬 통합 환경과 루트 `.env`의 영향을 받는 기존
  PostgreSQL·Elasticsearch·기본값 검증에서 `32 failed, 842 passed, 6 skipped`였다. 이를 전체
  회귀 통과로 기록하지 않는다. 후보 제거 범위와 직접 연결된 unit·정적 검사는 위와 같이
  통과했다.

## 정리 결정

단일 빈 진단 run directory는 `CACHE_POLICY.md`의 정확한 조사·승인·재검증 절차로 제거했다.
의미 있는 ignored 진단 산출물은 로컬·untracked 상태로 남겼으며, 이 문서는 그 내용을
복제하지 않는다.

Task 2 검증이 만든 다음 untracked pytest 임시 폴더는 현재 접근이 거부돼 제거하지 않았다.
제품 소스나 진단 보고서가 아니며 별도 cache-policy 승인 전에는 우회 삭제하지 않는다.

```text
.pytest-task2-round4-baseline
.pytest-task2-round4-final
.pytest-task2-round4-green-cli
.pytest-task2-round4-green-config
.pytest-task2-round4-green-config-invalid
.pytest-task2-round4-green-failure-version
.pytest-task2-round4-green-hooks
.pytest-task2-round4-green-initialize
.pytest-task2-round4-green-mcp
.pytest-task2-round4-green-probe
.pytest-task2-round4-green-requirements-params
.pytest-task2-round4-green-skills
.pytest-task2-round4-red-apps
.pytest-task2-round4-red-cli
.pytest-task2-round4-red-config
.pytest-task2-round4-red-failure-version
.pytest-task2-round4-red-hooks
.pytest-task2-round4-red-initialize
.pytest-task2-round4-red-mcp
.pytest-task2-round4-red-requirements-params
.pytest-task2-round4-red-skills
```

## 재개 조건

구현 또는 content-bearing 실행을 다시 검토하기 전에, 지원되는 안정 계약이 content 전송 전에
다음을 모두 증명해야 한다.

- effective per-thread built-in tool inventory
- config와 managed requirements 상태
- MCP, app, plugin, skill, hook, sub-agent 상태
- approval `never`와 read-only sandbox
- host-path 누출 없는 sanitized transport cleanup

이 조건이 충족되면 정확히 고정한 버전에서 no-content gate를 다시 실행한다. 그 성공 전에는
Provider, DB, UI 또는 본문을 포함하는 실행을 구현하지 않는다.
