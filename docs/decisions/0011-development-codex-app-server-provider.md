# ADR-0011: 개발용 Codex Provider는 전용 App Server 경계로 재설계한다

- 상태: 승인
- 결정일: 2026-09-06

## 배경

ADR-0010은 공개 Python SDK가 호출별 effective tool inventory를 증명하지 못해 Codex SDK
Provider 구현을 차단했다. 사용자는 안전 기준을 유지하면서 로컬 개발 환경의 현재 Codex
사용 권한을 RAG 생성에 연결하고, 폐기된 결과도 원인 분석과 테스트가 가능해야 한다고
결정했다.

## 결정

- Python high-level SDK adapter 대신 고정 버전 Codex App Server의 stdio JSON-RPC를 사용한다.
- 프로젝트 전용 `CODEX_HOME`, 별도 Codex 로그인과 관리형 requirements를 사용한다.
- App Server가 보고하는 config, requirements, MCP, skill, hook, app 상태와 대상 thread의
  effective built-in tool inventory를 질문 전 검증한다. 기능 플래그만으로 inventory를
  추정하지 않는다.
- 격리를 증명할 수 없으면 `codex_isolation_not_enforced`로 본문 전송 전에 실패한다.
- runtime 중 금지 이벤트는 답변 폐기, process quarantine과 안전 사건 기록을 발생시킨다.
- 일반 사건 기록은 metadata-only이며, 전체 protocol과 폐기 답변은 합성 데이터 전용 owner
  진단 모드에서만 Gitignored 로컬 저장소에 임시 보존한다.
- 구현과 UI는 우선 Labs/RAG 내부에 두고 두 번째 실제 사용처가 생길 때 공통화한다.
- `codex_app_server`는 development-only 외부 Provider이며 운영 Provider의 실행 경로와
  분리한다.

## 결과

안전 통제는 선언된 sandbox에만 의존하지 않고 실행 전 상태 증명과 실행 중 사건 탐지를 함께
사용한다. 답변을 폐기해도 trace ID, 실패 단계, 규칙, 버전, attestation과 event metadata로
재현 가능한 분석을 할 수 있다. 실제 비공개 본문과 폐기 초안은 일반 로그나 DB에 남지 않는다.

## 대체 관계

ADR-0010의 Python SDK 구현 차단 판단과 증거는 유효하다. 이 결정은 그 차단 기준을 완화하지
않고 다른 통합 경계인 App Server를 후속 후보로 채택한다. 상세 계약은
`docs/superpowers/specs/2026-09-06-codex-app-server-rag-adapter-design.md`를 따른다.
