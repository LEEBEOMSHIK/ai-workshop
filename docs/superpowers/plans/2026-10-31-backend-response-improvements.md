# Backend Response Improvements Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans within the explicit file ownership below. User approved implementation; no additional plan approval required.

**Goal:** 무결성·권한·답변 품질 조건을 유지하면서 다른 HTTP 요청의 정체, DB 연결 재생성, 구성 N+1 조회를 줄인다.

**Architecture:** 제한된 offload로 동기 검사를 분리하고 HTTP engine은 앱 lifespan에서 소유한다. 구성 repository는 현재 권한으로 집합 조회하며 실행·저장 업무 규칙은 유지한다.

**Tech Stack:** FastAPI, asyncio/AnyIO, SQLAlchemy async, PostgreSQL, pytest, Mypy, Ruff.

**Spec:** [ADR-0054](../../decisions/0054-request-response-lifetimes.md)

## Global Constraints

- 기존 설정·DB·계정·모델·프롬프트·근거·인용 품질 게이트를 보존한다. 신규 모델 호출0.
- 현재 dirty checkout의 관련 없는 변경을 보존한다. commit/push/캐시 삭제0.
- 원래 환경 실측과 offline 검증을 분리하고 본문/비밀/SQL 매개변수를 기록하지 않는다.

## Review Focus

- offload 요청 취소가 진행 중 검사의 제한 슬롯을 조기 반환하지 않아야 한다.
- 재사용 DB 세션이 다른 요청의 transaction/현재 권한을 공유하지 않아야 한다.
- 앱 종료·재기동과 복수 앱/이벤트 루프가 다른 engine을 소유해야 한다.
- 구성별 최신 버전·정렬·빈 관계·권한 취소 결과가 일괄 조회 전과 같아야 한다.
- 상태 조회 최적화가 무결성 검사나 현재 정책 승인 검사를 생략하지 않아야 한다.

## Task 1: 무결성 offload (backend agent)

Files: generation/codex_verification.py, 전용 offload helper 필요 시 추가, 해당 unit tests. readiness.py/shared/db.py/main.py는 다른 담당 소유.

- [x] 기존 코드에서 event-loop 응답성/취소 슬롯/검사 실패 회귀를 RED로 확인한다.
- [x] 전체 검사를 제한된 worker에서 await하고 실제 검사 종료까지 동시성 제한을 보존한다.
- [x] 기존 runner/verification 테스트와 범위 Mypy/Ruff를 실행한다.

## Task 2: 구성 조회 일괄화 (DB/backend agent)

Files: configurations/repository.py, service.py, generation/readiness.py, 필요 repository의 batch read API와 해당 테스트. Codex verifier/shared/db/main은 수정하지 않는다.

- [x] 권한/최신 버전/정렬/누락/쿼리 증가 경계 테스트를 RED로 확인한다.
- [x] list_visible과 준비 상태용 반복 조회를 집합화하되 현재 승인·검사 의미를 유지한다.
- [x] 관련 구성/준비/권한 테스트 및 범위 Mypy/Ruff를 실행한다.

## Task 3: HTTP engine lifespan (root)

Files: shared/db.py, main.py, tests/unit/shared/test_db_lifetime.py, 설계·WORKBOARD.

- [x] 두 요청의 engine 재사용과 서로 다른 세션, 실패 rollback, 앱 종료/복수 앱 격리 테스트를 RED로 확인한다.
- [x] app lifespan의 engine과 factory를 request.app에서 주입하고 request transaction 경계를 유지한다.
- [x] worker의 create_engine 사용은 유지하고 lifespan 없는 test transport 경계를 확인한다.

## Task 4: 독립 검증과 실제 비교 (reviewer/root)

- [x] reviewer가 제품 변경을 하지 않고 보안·transaction·권한·종료를 독립 검토/검증한다.
- [x] 수정 전 원래 서비스 상태를 측정·보존하고 같은 본래 DB 결과와 SQL 횟수를 전후 비교한다.
- [x] 관련 회귀·타입·린트 통과 뒤 원래 API만 재시작하고 health/ready 및 관리자 갱신 중 health 지연을 확인한다.
- [x] ISSUE48·worklog·WORKBOARD에 수치, 호출0, 보존 조건, 호스트 한계를 기록한다.

실행 근거: [구현·검증·본래 실측](../../worklogs/2026-10-31-backend-response-improvements.md). commit/push 미요청으로 미실행.
