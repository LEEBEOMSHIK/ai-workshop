# Conversational Generative RAG V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** 로그인 사용자의 현재 브라우저 대화 문맥을 반영해 질문을 독립 검색 질의로 확정하고, 허용된 Hybrid 검색 근거만 사용하는 로컬 LLM 답변을 인용 검증 후 제공한다.

**Architecture:** 기존 모듈형 모놀리스에 `generation` 도메인 포트와 로컬 OpenAI-compatible 어댑터를 추가한다. 저장 구성은 V1 추출식과 V2 생성식을 모두 표현하되 V2는 generation profile과 생성 정책을 필수로 한다. 검색 서비스는 문맥화, 검색, 선택적 리랭킹 경계, 근거 선별, 생성, 인용 검증을 고정 순서로 실행하며 미구성 리랭커는 정상 생략한다. 서버는 대화 전문을 영속 저장하지 않는다.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLAlchemy, Alembic, httpx, PostgreSQL, Elasticsearch, Next.js 16, React 19, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-04-conversational-generative-rag-v2-design.md`, `docs/decisions/0008-required-generation-optional-reranker.md`

**Global Constraints:** `main`에서만 작업한다는 사용자 지시를 따른다. 외부 모델 API와 실제 문서를 사용하지 않는다. 모델명·endpoint·prompt 전문을 업무 코드나 로그에 고정하지 않는다. 리랭커 실행 구현, 서버 대화 영속화, 실제 모델 다운로드는 제외한다. 기존 `SearchResponse.answer` 의미는 바꾸지 않고 생성 결과를 additive 필드로 추가한다.

## File map

- 생성 도메인과 런타임: `backend/src/ai_workshop/labs/rag/generation/{domain,contracts,prompts,openai_compatible}.py`
- 프롬프트 자산: `backend/src/ai_workshop/labs/rag/generation/prompts/{contextualize-v1,answer-v1}.txt`
- 검색 연결: `backend/src/ai_workshop/labs/rag/search/{configuration_port,service,schemas,api}.py`
- 저장 구성과 준비 상태: `backend/src/ai_workshop/labs/rag/configurations/{domain,models,repository,schemas,service}.py`
- 런타임 설정: `backend/src/ai_workshop/config.py`, `.env.example`, `backend/pyproject.toml`, `backend/uv.lock`
- DB 계약: `backend/alembic/versions/0015_rag_generation_v2.py`
- 백엔드 테스트: `backend/tests/unit/labs/rag/generation/`, `backend/tests/unit/labs/rag/configurations/test_configuration.py`, `backend/tests/integration/labs/rag/{configurations,search}/`
- 관리자 UI: `frontend/src/features/rag/configurations/{ConfigurationBuilder,ConfigurationStudioPage,packageSummary}.tsx`
- 대화형 검색 UI: `frontend/src/features/rag/search/{api,SearchPage,EvidenceAnswer}.tsx`
- 프론트 테스트: 같은 기능 폴더의 `*.test.tsx` 및 `*.test.ts`
- 생성 API 타입: `frontend/src/shared/api/generated/schema.ts`
- 운영 문서: `docs/runbooks/local-development.md`, `docs/labs/rag/design.md`, `WORKBOARD.md`

## Task 1: 생성 도메인과 문맥 정책

1. `backend/tests/unit/labs/rag/generation/test_context_policy.py`에 첫 질문은 그대로 유지되고, 후속 질문은 허용된 user·검증된 assistant turn만 제한된 순서로 전달되며, 제한 초과·비정상 역할을 거부하는 테스트를 작성한다.
2. `backend/.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/generation/test_context_policy.py -q --basetemp=<fresh path>`를 `backend/`에서 실행해 모듈 부재로 RED를 확인한다.
3. `generation/domain.py`와 `generation/contracts.py`에 `ConversationTurn`, `ContextPolicy`, `GenerationProfile`, `GenerationRuntimePort`, 문맥화·생성 입출력 타입과 명시적 runtime 예외를 최소 구현한다.
4. 같은 테스트를 다시 실행해 GREEN을 확인한다.
5. `backend/tests/unit/labs/rag/generation/test_profile.py`에 prompt 참조, context budget, timeout, 출력 한도와 단일 LLM binding 검증을 추가하고 RED→GREEN으로 구현한다.

## Task 2: 구조화 생성과 인용 검증

1. `backend/tests/unit/labs/rag/generation/test_citation_validation.py`에 모든 주장 인용, 검색되지 않은 evidence ID, 수치·날짜 불일치, 원문 위치 불완전, 유효 출력의 `answered` 변환을 각각 테스트한다.
2. 테스트를 실행해 validator 부재로 RED를 확인한다.
3. `generation/domain.py`에 versioned structured claim/output, generation status/outcome을 추가하고 `generation/citation_validation.py`에 결정적 hard gate를 구현한다.
4. 검증 실패가 생성 초안을 결과·예외 문자열에 포함하지 않는 테스트를 추가한 뒤 GREEN을 확인한다.

## Task 3: 로컬 OpenAI-compatible 어댑터

1. `backend/tests/unit/labs/rag/generation/test_openai_compatible.py`에 loopback endpoint 허용, 비로컬 endpoint 거부, exact model 전달, timeout/연결 실패의 안전한 예외, 문맥화·생성 JSON schema 파싱을 `httpx.MockTransport`로 테스트한다.
2. RED를 확인한 뒤 `httpx`를 runtime dependency로 이동하고 `generation/prompts.py`, 두 prompt 파일, `generation/openai_compatible.py`를 구현한다.
3. `config.py`와 `.env.example`에 선택적 base URL과 비밀 환경 변수 참조, timeout을 추가한다. endpoint 미설정은 `answer_ready=false`이지 임의 기본 모델 선택이 아니다.
4. 어댑터 단위 테스트와 `ruff check`, `mypy` 대상 검사를 실행해 GREEN을 확인한다.

## Task 4: V2 저장 구성과 migration

1. `backend/tests/unit/labs/rag/configurations/test_configuration.py`에 extractive는 generation 금지, generative는 generation 필수, 미구성 reranker 허용, 구성된 reranker는 현 구현에서 명시적 unsupported인 계약을 추가하고 RED를 확인한다.
2. `configurations/domain.py`와 `models/domain.py`의 생성 profile shape를 확장하고 Answer Policy mode를 `extractive | generative`로 만든다.
3. `backend/tests/integration/labs/rag/configurations/test_configuration_api.py`와 resolver 테스트에 generation profile/LLM/model 해석, `search_ready`, `answer_ready`, `service_ready` 원인 반환을 추가해 RED를 확인한다.
4. `configurations/{schemas,service,repository,models}.py`와 `search/configuration_port.py`를 구현한다. 준비 상태 계산은 exact immutable version과 runtime health를 사용한다.
5. `0015_rag_generation_v2.py`로 V1 전용 mode·generation DB check와 validation trigger를 V2 불변 규칙으로 교체한다. downgrade는 V2 행이 존재하면 안전하게 거부한다.
6. 대상 단위·통합 테스트와 Alembic upgrade/downgrade 격리 검증을 실행한다.

## Task 5: 검색 파이프라인 연결

1. `backend/tests/unit/labs/rag/search/test_generation_pipeline.py`에 첫 질문 raw query, 후속질문 contextualized query, 근거 부족 시 generation 미호출, 유효 답변, 인용 실패 draft 비노출, contextualizer/LLM 장애 503을 작성한다.
2. RED를 확인한 뒤 `SearchApplicationService`에 generation runtime과 citation validator를 주입하고 고정 실행 순서를 구현한다.
3. 요청 schema에 bounded history를, 응답 schema에 `resolved_query`와 additive `generation` 객체를 추가한다. V1은 `not_requested`를 반환한다.
4. `search/api.py`에서 typed settings와 resolved profile로 runtime을 조립하되 요청마다 다른 모델로 silent fallback하지 않는다.
5. `backend/tests/integration/labs/rag/search/test_search_api.py`에 실제 API schema, 권한 재검사, 후속질문, 근거 부족, runtime 장애를 추가해 GREEN을 확인한다.

## Task 6: 관리자 생성 구성 UI

1. `ConfigurationStudioPage.test.tsx`, `packageSummary.test.ts`, 필요 시 `ConfigurationBuilder` 테스트에 generation profile 선택, LLM 이름·버전, 세 readiness와 원인, 미구성 reranker 정상 상태를 추가해 RED를 확인한다.
2. `ConfigurationBuilder.tsx`, `ConfigurationStudioPage.tsx`, `packageSummary.ts`, API mapping을 최소 구현해 GREEN을 확인한다.
3. UUID를 기본 표시하지 않고 내부 ID는 제출 값으로만 유지한다. 준비되지 않은 구성은 관리자에게 조치 원인을 표시한다.

## Task 7: 사용자 대화형 검색 UI

1. `SearchPage.test.tsx`에 여러 turn 렌더링, 직전 bounded history 전송, 새 대화 초기화, 원 질문·확정 검색 질의 구분, 검증된 생성 답변·문장별 인용, 근거 부족/검증 실패/503 상태를 테스트하고 RED를 확인한다.
2. `search/api.ts`, `SearchPage.tsx`, `EvidenceAnswer.tsx`를 구현한다. assistant history에는 `answered`와 인용 검증을 통과한 텍스트만 포함한다.
3. `service_ready=false`이면 제출을 막고 search/answer 준비 원인을 나눠 보여준다. 새로고침 후 대화가 사라짐을 UI에 짧게 알린다.
4. 대상 Vitest를 실행해 GREEN을 확인한다.

## Task 8: 계약 생성, 회귀 검증과 문서 마감

1. 백엔드 OpenAPI를 생성하고 `frontend/src/shared/api/generated/schema.ts`를 공식 생성 절차로 갱신한다.
2. 백엔드 대상 테스트, 전체 unit, Ruff, mypy와 migration 검증을 실행한다.
3. 프론트 대상 테스트, 전체 Vitest, TypeScript, ESLint, production build, OpenAPI check를 실행한다.
4. 로컬 fake/MockTransport로 후속질문→확정 질의→검색→생성→인용 응답 계약을 smoke한다. 실제 모델이 없으므로 라이브 모델 성공을 주장하지 않는다.
5. `docs/runbooks/local-development.md`에 local runtime 설정과 데이터 경계를, `docs/labs/rag/design.md`에 구현 상태를 반영한다.
6. `WORKBOARD.md`의 현재 상태·다음 작업·차단 요소를 갱신하고 최근 완료 작업은 최대 5개로 유지한다.
7. `git diff --check`, 프로젝트 에이전트 계약 검증, 관련 파일 diff를 검토한다. 사용자 파일 `references/`와 ACL 잠금 테스트 폴더를 변경·스테이징하지 않는다.

## Plan self-review

- 승인 설계의 문맥 기반 후속질문, 필수 LLM, 선택적 리랭커, 인용 hard gate, 비영속 대화, 준비 상태와 명시적 실패를 모두 작업에 매핑했다.
- 실제 모델명·endpoint·비밀값·평가 수치를 placeholder나 업무 코드 상수로 만들지 않는다.
- 기존 추출 답변 타입과 생성 답변 타입을 분리하고 응답은 additive하게 유지한다.
- 리랭커 미구성은 정상 동작하지만 리랭커 실행 구현은 이번 범위에 포함하지 않는다는 경계를 테스트와 UI에 함께 고정한다.
- 각 production 변경은 먼저 실패하는 소비자 관점 테스트를 가진다.
