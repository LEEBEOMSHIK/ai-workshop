# ADR-0011: 개발용 Codex Provider의 App Server 경계 후보는 차단한다

- 상태: 차단
- 결정일: 2026-09-06

## 별도 개인용 경로

사용자는 이후 제한 실행의 잔여 위험을 수용하고 내부 통제 프롬프트를 요구했다.
[ADR-0017](0017-personal-codex-exec-provider.md)은 별도 개인용 `codex exec` 경로의 설계 결정이다.
이 ADR의 SDK/App Server 차단과 기존 LPAC 실행기 상태를 해제하거나 성공으로 바꾸지 않는다.
새 경로도 상세 설계·구현·실제 검증 전에는 사용할 수 있는 Provider가 아니다.

## 2026-09-07 재검증

사용자는 이후 OS 수준 격리 대안 방향을 승인했다. [대안 상세 설계](../superpowers/specs/2026-09-07-codex-os-isolation-design.md)는
전체 프로세스 접근 차단 실험을 제안하며 아직 실제 격리·통신 검증 또는 Provider 활성화 승인이 아니다.
새 증거와 승인된 대체 결정이 나오기 전까지 아래 기존 구현 경로의 차단 판정은 유지한다.

사용자 요청으로 설치된 `codex-cli 0.153.4`의 기본 비실험 스키마를 생성·검토했다.
thread별 effective built-in tool inventory의 사전 조회 계약은 확인되지 않았고 독립 검토도
BLOCK이다. live App Server·인증·본문 실행은 시작하지 않았다. 기존 차단 기준을 유지한다.
정확한 검증 범위와 스키마 hash는 [재검증 기록](../worklogs/2026-09-07-codex-01534-isolation-preflight.md)을 따른다.

## 배경

ADR-0010은 공개 Python SDK가 호출별 effective tool inventory를 증명하지 못해 Codex SDK
Provider 구현을 차단했다. 사용자는 안전 기준을 유지하면서 로컬 개발 환경의 현재 Codex
사용 권한을 RAG 생성에 연결하고, 폐기된 결과도 원인 분석과 테스트가 가능해야 한다고
결정했다.

## 측정 결과와 차단 결정

- 정확히 고정해 시험한 버전은 `codex-cli 0.151.0`이다.
- 생성한 비실험 schema에는 `config/read`, `configRequirements/read`, MCP·skill·hook·app·plugin
  목록과 thread·turn 작업처럼 안정적인 상태 메서드가 있다. 그러나 대상 thread의 effective
  built-in tool inventory를 증명하는 안정 계약은 없다.
- 따라서 schema gate가 fail closed 했고, 본문을 보내지 않는 live gate도
  `codex_isolation_not_enforced`로 exit 1 했다. runtime state는 검증되지 않았다.
- 질문, 대화 이력, Evidence, `thread/start`, `turn/start`는 전송하지 않았다. Windows transport
  cleanup은 host path를 포함한 unsanitized runtime warning을 냈지만 원시 출력은 추적 문서에
  복사하지 않는다.
- 이 후보는 승인된 Provider가 아니다. fail 결과 뒤 gate source·test·script entry 후보를
  제거했으며 Provider 등록, migration, DB, UI, RAG 질문 실행은 수행하지 않았다.
- 단일 빈 진단 run directory만 cache policy의 정확한 절차로 제거했다. 의미 있는 ignored
  진단 산출물은 로컬·untracked 상태로 유지한다.

## 결과

안정 지원 계약이 content 전송 전에 effective per-thread built-in tool inventory, config와
managed requirements, MCP·app·plugin·skill·hook·sub-agent 상태, approval `never`, read-only
sandbox와 host-path 누출 없는 sanitized transport cleanup을 모두 증명할 때만 재개한다. 그때
정확히 고정한 버전으로 no-content gate를 다시 실행한 뒤에만 Provider, DB, UI 또는 본문 전송
실행을 검토한다.

## 대체 관계

ADR-0010의 Python SDK 구현 차단 판단과 증거는 유효하다. 이 ADR은 그 기준을 완화하지 않은
App Server 후보의 측정 차단 결과를 기록한다. 재개 조건을 만족하기 전에는
`docs/superpowers/specs/2026-09-06-codex-app-server-rag-adapter-design.md`를 구현 승인으로
해석하지 않는다.
