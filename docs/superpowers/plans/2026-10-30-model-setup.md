# Model setup Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independent implementation and review. Main owns integration and WORKBOARD.

**Goal:** 관리자 모델 등록·변경과 RAG 후보 구성·검증·적용을 한 화면에서 처리한다.
**Architecture:** 기존 등록/프로파일/구성/평가/도메인 API를 조합하는 관리 화면, owner 전용 안전한 연결 옵션 조회만 추가.
**Tech Stack:** Next/React/TypeScript, FastAPI/Pydantic, 기존 Vitest/Pytest.
**Spec:** [승인 범위](../specs/2026-10-30-model-setup-design.md)
**Decision:** [ADR-0052](../../decisions/0052-admin-model-setup.md)

## Global Constraints

- 기존 `.env`·기본 연결·모델/프롬프트·원문/인용·평가 게이트 보존. 모델 자동 호출0.
- 기존 checkout 재사용, 관련 없는 미커밋 변경 보존. 패키지 설치/commit/push/캐시 삭제 없음.
- 모든 성공/실패·부분 저장을 명시하고 데이터 정책을 완화하지 않는다.
- 모델 연결 → 기존 RAG 복제 → 연결 상태·답변 평가 → 도메인 명시적 적용 순서를 유지한다. 고급 화면 링크는 보존하고 전역 기본값은 변경하지 않는다.
- 아래 체크리스트는 구현·검증 대상이며 실제 환경 수용 결과는 메인의 작업 기록에서 별도로 확인한다.

## Review Focus

- owner 외 연결/인증 참조 접근, 비밀값/URL 노출을 거절한다.
- 공급자/기반 구성/범위 변경 후 오래된 승인·비동기 응답이 재사용되지 않는다.
- 중간 모델/배포/프로파일 저장 성공 뒤 실패를 중복 생성으로 복구하지 않는다.
- 복사한 config·답변 정책·색인/검색/권한 범위를 임의 기본값으로 치환하지 않는다.
- 추출식 기반의 LLM 생성 답변 전환은 별도 체크박스로 확인하고, 기존 프로파일의 비호환 필드는 조용히 변환하지 않는다.
- `canApplyCandidate`만으로 적용하지 않는다. 정확한 후보 버전의 `acceptGenerativeRun` 수용 응답과 새로 조회한 준비 상태가 모두 필요하다. 검색 평가의 `passed`를 답변 평가 수용으로 재사용하지 않는다.
- 새로고침 뒤 기존 완료 답변 평가의 통과 반영으로 수용 응답을 복구하는 동작은 새 모델 호출 없이 수행한다.
- 평가 미통과·준비 미완료·이전 연결 변경 상태에서 활성화하지 않는다. 응답 유실은 저장 여부를 대조하고, 대조 불가 상태에서 중복 쓰기를 계속하지 않는다.

### Task 1: 안전한 연결 옵션

- Files: deployments/setup_options.py, schemas.py/api.py, 해당 unit/API tests; generated OpenAPI는 메인 통합.
- Contract: GET `/api/v1/admin/rag/deployment-setup-options`, owner only, `Cache-Control: no-store`. `endpoints:[{reference,dialect}]`, `secret_references:string[]`, `environment`, `generation_presets:[{id,name,description,supported_providers,config}]`. 옵션 조회는 외부 호출/DB쓰기 없음. 키/URL 값 반환 금지.
- Presets: 기존 추론 계약을 유지해 OpenAI Responses용 `rag-answer-v1`/schema1과 로컬 HTTP용 `rag-answer-v3`/schema2를 구분한다. UI에서 `supported_providers`를 적용하며 기존 설정을 대체하지 않는다.
- [x] 계약 검증: 권한·비밀 미노출·빈 옵션·정규 환경·공급자별 프리셋 유효성·후보 상태.
- [x] 구현, 기존 배포 검사와 Ruff/Mypy 실행, 보고.

### Task 2: 모델 연결 패널

- Files: frontend/features/rag/setup/ModelConnectionPanel.tsx, setup-api.ts, setup.module.css, tests.
- Contract: props `models`, `deployments`, `selectedDeploymentId`, `onModelSaved`, `onDeploymentSaved`, `onSelectDeployment` (모델/배포 기존 타입 사용).
- [x] 계약 검증: 기존 선택, 공급자별 등록, model 성공/deployment 실패 복구, 응답 유실 후 결과 확인, 빈 서버 설정/오류/입력 보존/이중 제출.
- [x] 기존 model/deployment API와 새 옵션으로 구현, health는 부모에서 수행.

### Task 2 후속: 공개 모델 카탈로그와 탐색 구분

- [x] 공식 모델 문서·최초 공개일 확인, ADR0052·디자인 기준에 공개 카탈로그/계정 권한/실제 품질 수용 경계 명시.
- [x] OpenAI native select·공개일 최신순·빈 초기값·고급 직접 입력·공급자/방식/모델 변경 초기화 구현과 회귀.
- [x] 기존 고급 메뉴 이름 구분·상위 관리자 진입을 통합 설정에 연결, 기존 URL 보존.
- [x] 독립 검토·프론트 회귀/타입/린트·본래 desktop/320/375px/키보드 확인·ISSUE46 후속과 WORKBOARD 마감.

### Task 3: RAG 구성·검증·적용과 진입점

- Files: 새 setup 기능 내부 candidate/apply/hub, app/admin/rag/setup/page.tsx, routes/areaMenus, 기존 models/configurations 진입 링크.
- [x] 계약 검증: profile/config 전체 복사 보존·공급자 호환성·추출식 전환 확인·외부 승인 초기화·부분 저장/응답 유실 복구.
- [x] 계약 검증: 검색 평가만 통과한 후보·다른 버전 수용 응답·수용 뒤 준비 상태 변경·확인 후 도메인 연결 변경의 적용 차단.
- [x] 계약 검증: 새로고침 후 기존 완료 평가의 통과 반영으로 정확한 후보 수용 응답 복구, 새 모델 호출0.
- [x] 한 화면에서 기존 배포 health/평가 컴포넌트·도메인 API 연결. 기존 RAG 고급 Builder는 보존하고 쉬운 구성 흐름을 안내한다.
- [x] 다크·청록 토큰, 단계별 상태/오류/부분 성공, 44px 조작 영역·키보드 초점·320/375px 줄바꿈/넘침·고급 화면 링크 확인.
- [x] 타입·린트·관련회귀·독립검토, 본래 UI/DB 읽기 확인과 합성 화면 검증을 구분해 기록하고 디자인 정본/문제 기록/WORKBOARD 마감. UI·mock 검증을 새 모델 품질 수용으로 보고하지 않는다.

검증 범위와 실제 운영 미실행 경계는 [작업 기록](../../worklogs/2026-10-30-admin-model-setup.md)을 따른다.
