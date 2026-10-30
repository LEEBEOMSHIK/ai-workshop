# SDK 대화 문맥 모니터링 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. 아래 체크리스트를 작업·독립 검증과 함께 갱신한다.

**Goal:** 같은 대화의 턴별 실행 연결과 실제 채택 메시지·질문 문맥화 관측을 제공한다.

**Architecture:** 기존 ConversationDetail 조회와 실행 stages JSON의 선택형 구조를 사용한다. 원 대화 출처는 private scope에서만 전달하며 관측은 업무 입력·출력을 바꾸지 않는다.

**Tech Stack:** 기존 FastAPI/Pydantic/SQLAlchemy, React/Next.js, pytest/Vitest. 설치 없음.

**Spec:** [ADR-0049](../../decisions/0049-conversation-context-observation.md)

## 범위·역할·제약

- 중간 위험: 비공개 관측 데이터의 API·저장 계약 및 UI. 메인: 요구/아키텍처/DB 경계/문서·통합. backend: Python·AI 어댑터 관측 및 테스트 설계. frontend: React·접근성 및 테스트 설계. 독립 검증자: 통합·코드 리뷰·보안·privacy.
- 활성화 selector의 requirements-or-behavior, cross-module-or-public-contract, react-ui, python-api-or-worker, ai-model-or-runtime, database-or-migration, authentication-permission-or-exposure, privacy-or-external-transfer, feature-implementation, significant-change-or-merge, design-adr-or-document-structure 기준을 적용한다.
- RAG 품질 튜닝·새 인프라/배포·색인·모델 실험은 변경하지 않아 전문 실행 역할에서 제외한다. 현재 API 반영은 기존 로컬 서비스만 다룬다.
- 관련 누적 변경이 현재 checkout에 있으므로 현재 폴더를 재사용하고2252개 시작 파일·.env 해시와 수정 전 파일을 보존한다. 무관 변경 정리·commit/push·캐시 삭제 없음.
- 모델0, 프로파일/연결 변경0, 새 DB/계정/환경0. 기존 DB rollback-only 검증과 본래 API 반영/읽기 수용을 구분한다.

## Review Focus

- 같은 텍스트의 다른 턴이 잘못 연결되지 않아야 한다.
- 부분 Q/A와 토큰 경계에서 실제 전송 메시지 순서가 바뀌지 않아야 한다.
- 진단 off 수집과 공개 응답 비노출이 함께 유지되어야 한다.
- 문맥화+SDK 합계 제한, 손상·추론 출력 및 과거 기록이 정직하게 표시되어야 한다.
- 화면 전환·늦은 응답·권한 실패 뒤 이전 질문/본문이 남지 않아야 한다.

## 작업

### 1. 백엔드 관측

대상: 기존 generation/domain 선택 동작 검증(제품 변경 없음) 및 HTTP 어댑터, conversations/service, search/pipeline, executions/domain·observer·repository·service와 새 전용 관측 모듈/테스트. 평가 저장/조회는 본문 중복 제거 경계를 함께 확인한다.

- [x] 선택/출처/진단 off/문맥화/상한/저장 경계 실패 테스트를 먼저 실행한다.
- [x] ADR의 optional history_selection·contextualization 계약을 구현한다. history_selection은 request 단계에 붙인다.
- [x] 기존 선택·HTTP 입력·답변·인용 동등성, 오류/취소와 legacy 회귀를 실행한다.
- [x] strict 범위 Mypy·Ruff 및 저장 경계 검사를 통과한다.

### 2. 화면

대상: frontend/src/features/rag/executions의 상세·새 턴 탐색·문맥 표시 컴포넌트/CSS/테스트. root가 frontend/src/shared/api/schema.d.ts를 기존 생성기로 갱신한다.

- [x] 턴 탐색의 경합·권한 실패·평가/legacy 제외·현재 선택 테스트를 먼저 실행한다.
- [x] 기존 authorized getConversation와 executionPath를 연결하고44px·키보드·긴 한국어를 지원한다.
- [x] 채택/제외 메시지와 한도·미기록·실제 문맥화 HTTP 본문을 표시한다.
- [x] Vitest·전체 TypeScript·변경 ESLint를 실행한다.

### 3. 독립 검증·본래 반영·기록

- [x] 독립 code/security/privacy review와 고유 회귀를 수행하고 발견 사항을 수정한다.
- [x] 기존 DB의 rollback 저장/조회와 원본 데이터·.env 보존을 확인한다.
- [x] 실행중 작업이 없음을 확인한 뒤 기존 API에 반영하고 health/ready/계약을 확인한다.
- [x] 본래 인증 화면의 턴 탐색/legacy 상태와 합성320/375px를 검증한다. 실제 모델 실행은 하지 않는다.
- [x] 관리자 문제 이력과 worklog·WORKBOARD를 갱신한다. 실제 멀티턴 품질 수용은 남은 범위로 명시한다.

## 검증 명령

기존 runbook의 Conda 활성화 및 Resolve-ApprovedLocalPython을 사용한다. `pytest -c backend/pyproject.toml`에 지정 unit/contract/rollback-only 파일만 전달하며 전체 실사용 DB 테스트를 실행하지 않는다. `python -m mypy`와 `python -m ruff check`는 변경 모듈/테스트를 대상으로 한다. frontend는 `pnpm exec vitest run <files>`, `pnpm typecheck`, `pnpm exec eslint <files> --max-warnings 0`, 기존 `api:generate`/`api:check`를 사용한다. 실제 명령·결과·고유 테스트 수는 worklog에 기록한다.
