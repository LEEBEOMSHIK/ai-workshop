# RAG Selection Speed Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the bounded implementation tasks and independent review. User authorization preserves the current workspace, existing changes, and no commit/push.

**Goal:** 근거·인용을 보존하면서 중복 문자열 계산을 줄이고 저장된 단계에서 세부 비용을 구분한다.

**Architecture:** request-owned KeywordMatcher와 현재 ExecutionObserver를 사용한다. 새 모델·캐시 서비스·DB 테이블은 만들지 않는다.

**Tech Stack:** Python/FastAPI/Pydantic/pytest, 기존 OpenAPI TypeScript 생성기.

**Spec:** [설계](../specs/2026-10-25-rag-selection-speed-design.md), [ADR-0041](../../decisions/0041-rag-operation-timings.md).

## 실행 경계

기존 C:/projects/ai-workshop의 사용자 미커밋 변경192개를 SHA로 보존한다. 이 변경들이 실행 환경과 이번 수정의 기반이므로 현재 checkout에서 파일별 담당을 분리한다. 작업 증거는 `.local-data/project-agent-work/rag-selection-speed-20261025/`에 둔다. 새 환경·Git 변경·캐시 삭제·실제 모델 호출은 금지한다.

## Task 1: 결과가 동일한 요청 내부 문자열 재사용

소유: highlighting/service.py, highlighting/context.py 및 highlighting의 새 테스트. pipeline과 계측 파일은 수정하지 않는다.

인터페이스: service.KeywordMatcher(query), `.coverage(text)`, `.highlights(text, location, evidence_unit_id)`와 기존 find_keyword_highlights 호환. EvidenceSelector.select와 select_context에 선택적 `keywords` 추가. 객체는 하나의 query에만 쓰고 불일치는 검증한다. `.coverage`는 offset 함수를 호출하지 않는다.

- [x] RED: Unicode/빈 질의/중복·substring 의미, coverage의 offset 계산 부재, 재사용과 위치 검증 실패를 확인한다.
- [x] GREEN: 결과가 같은 빠른 정규화와 객체 수명 내부 재사용을 구현한다. 원문 offset 알고리즘은 보존한다.
- [x] 기존 highlighting 테스트와 새 회귀를 실행하고 변경 파일 Ruff/Mypy를 확인한다.
- [x] 계측 helper가 준비되면 normalize/offset 계산에만 고정 이름으로 시간·재사용 항목 수를 기록한다.

## Task 2: 단계별 연산 집계·보관·조회

소유: executions/operation_timings.py 신규, executions/domain.py·observer.py, embeddings/request_cache.py·sentence_transformers.py, retrieval/service.py·elasticsearch.py, search/pipeline.py 및 대응 새 테스트. highlighting 파일은 수정하지 않는다.

인터페이스: `measure_operation(name, *, items=0, reused_items=0)` context manager, `OperationTiming` 모델과 stage optional operations. observer가 없으면 no-op. 실행별 집계, 실패/취소 전파와 종료 뒤 변경 금지를 유지한다. pipeline에서 Task1의 KeywordMatcher를 한 번 만들고 두 선택에 전달한다.

- [x] RED: fake clock 집계·중첩/병렬 포함 의미·실패/취소·실행 격리·privacy/schema·old JSON 호환을 확인한다.
- [x] GREEN: closed-name 수치 집계와 기존 stage JSON 저장을 연결한다. 기존 DB 왕복에 합치고 새 쓰기는 추가하지 않는다.
- [x] 검색·선택·임베딩과 frozen 검색의 하위 연산을 계측하고 기존 오류/권한/소유권 경계를 보존한다.
- [x] 관련 observer/retrieval/embedding/search 테스트, 변경 Ruff/Mypy, 저장/조회 계약을 검증한다.

## Task 3: 독립 검증과 통합

소유: 독립 검증자는 독립 테스트와 리뷰만 작성한다. 메인은 OpenAPI 생성물·설계/runbook/WORKBOARD·작업 기록·합성 벤치마크·본래 환경 반영을 통합한다.

- [x] 정상 선택·충돌·budget·Unicode·권한/본문 비수집·동시성 회귀를 별도 확인한다.
- [x] 기존 DB rollback 검증에서 stage operations 저장→읽기와 이전 데이터 호환을 확인한다.
- [x] 최종 관련 RAG unit 범위·변경 타입/린트·OpenAPI 생성·frontend typecheck를 수행한다.
- [x] 같은 합성 입력의 전후 coverage 측정과 선택 결과를 비교하고 전체 RAG 성능 주장을 구분한다.
- [x] 기존 변경 SHA·문서 링크·본래 서비스 상태/적용·문제 이력을 확인하고 마감한다.

## Review Focus

결합 문자와 casefold 확장 위치, 공백 축약/substring 의미, 공유 캐시에서 이전 요청 본문 잔류, 중첩·병렬 시간을 전체로 오해하는 계약, 종료/취소 뒤 늦게 기록되는 계측을 집중 확인한다. 제품 테스트에 벽시계 시간 제한을 정답으로 넣지 않는다.
