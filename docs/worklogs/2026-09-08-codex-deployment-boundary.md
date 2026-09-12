# Codex 실행 승인 선행 저장 경계

## 조사 결과와 순서 보정

기존 GenerationPolicyResolver는 Installation singleton의 FOR SHARE 잠금을 잡고,
정책 작성자는 같은 행을 FOR UPDATE로 잠근다. provider 호출과 감사 트랜잭션이 끝나기 전에
정책이 바뀌지 않도록 순서를 제어하므로 검색에 단순 재조회만 추가하지 않는다.
이번 조사에서 사용자에게 처음 설명한 '각 호출 직전 정책 재확인'은 이 기존 잠금과 구분한다.

현재 실제 Codex 실행에 필요한 정보는 별도로 부족하다.

- ProviderKind와 DB 제약이 HTTP 기반 두 provider만 허용한다.
- endpoint_ref 필수 구조에 CLI를 넣으면 가짜 endpoint를 만들게 된다.
- 실행 직전 최신 owner, 승인된 공개/합성 revision과 정확한 전송 payload 승인 기록이 없다.
- 현재 resolved 외부 승인에는 원본 승인 ID/approved_by/시각이 전달되지 않는다.

따라서 승인 설계 §11에 따라 Codex provider와 별도 runner_ref 저장 계약을 먼저 마련한다.
등록/실행/readiness는 승인 증거와 runner registry가 연결되기 전 차단한다.
계획: `docs/superpowers/plans/2026-09-08-codex-deployment-boundary.md`.

## 데이터 변경 경계

새 migration 파일을 작성하되 실제 사용자 DB에는 적용하지 않는다. 새 provider를 추가해도
기존 Installation/Workspace 승인 목록이나 도메인·프로파일을 자동 변경하지 않는다.
통합 검증은 current_database와 이름을 확인하는 기존 격리 DB helper를 이용한 합성 데이터만 사용한다.
검증을 위한 임시 DB만 정확한 이름으로 생성/회수하며 실제 문서나 계정은 테스트하지 않는다.
Codex CLI·모델 호출·인증 조회는 이번 단위에 없다.

## 구현·검증 결과

- `development_codex_exec`와 별도 `runner_ref`를 domain/API/ORM/repository에 반영했다.
  HTTP endpoint와 상호배타이며 개발 전용·외부 전송·재시도 없음·자동 health 호출 없음을 강제한다.
- 등록·runtime resolver·관리자 및 생성 readiness는 아직 Codex를 `deployment_not_ready`로 차단한다.
- migration 0026은 기존 HTTP 데이터·정책 승인을 보존한다. Codex 설정 또는 승인 기록이 있으면
  downgrade를 거절한다. 실제 사용자 DB는 0026을 적용하지 않았으므로 새 백엔드 재시작 전 적용 필요하다.
- 메인 검증: backend unit/contract **1,140 passed**, 기존 Starlette 경고 1개.
  runbook에 따른 합성 `AI_WORKSHOP_SECRET_KEY`를 테스트 프로세스에만 설정했다.
  격리 PostgreSQL migration **4 passed**, 생성한 합성 DB는 helper가 종료 시 삭제했다.
  frontend 관련 **43 passed**, TypeScript·OpenAPI 동기화·관련 ESLint 및 backend Ruff 통과.
  mypy **214개 소스 파일** 통과.
- 독립 보안/DB 리뷰: 실행 차단 결함 없음. Workspace downgrade 사례에 Installation 승인도 포함되어
  Workspace 검사만 단독 입증하지 못하는 검증 공백은 남아 있다. migration 자체는 양쪽을 검사한다.
- API enum 확장에 따른 기존 화면 세 곳의 Provider 표시명만 추가했다. 새 모델 선택 UI나 실제 호출은 없다.
  실제 Codex 답변·인용·후속 질문의 사용자 검증 완료를 의미하지 않는다.

## 후속

runner registry → 현재 actor/전체 공간/구성·Deployment·지침·입력 revision/전송 승인 결합 →
실제 spawn 직전 검증 → 출력/회수/identity 검증 순서다. `PolicyDecision.allowed` 하나를
Codex 전체 승인으로 취급하지 않는다. 기존 HTTP Provider의 health/identity 기준은 유지한다.
