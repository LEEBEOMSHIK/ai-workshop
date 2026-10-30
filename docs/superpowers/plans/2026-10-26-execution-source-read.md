# 실행 목록 원문 권한 조회 개선 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development task-by-task; keep implementation and independent security verification separate.

**Goal:** 현재 권한·저장 답변·숫자 증명·전체 목록 응답을 보존하며 반복 원문 조회와 입증된 계산 비용을 줄인다.

**Architecture:** 기존 `visible_run`의 정확한 문서/버전/projection 조합을 최대64개씩 scalar 조회한다. 매 호출 snapshot 전체에서 source를 새로 추출하며 시작·끝 권한 확인을 유지한다. 계산 최적화는 읽기 전용 프로파일에서 비용을 확인한 뒤 별도 최소 변경으로 검토한다.

**Tech Stack:** 기존 Python/SQLAlchemy/PostgreSQL/Conda, pytest·Mypy·Ruff. 설치·migration·모델 호출 없음.

**Spec:** 사용자가 [직전 작업의 다음 개선](../../worklogs/2026-10-26-execution-validation-batch.md)을 진행하라고 승인했다. 아래는 그 범위의 내부 구현 설계이며 공개 계약이나 권한 정책 변경은 없다. 원문 근거·현재 권한 경계는 [ADR-0029](../../decisions/0029-rag-execution-monitoring.md)와 기존 RAG 설계를 유지한다.

## 설계와 대안

- 채택: 정확한 `(document_id, asset_version_id, projection_id)` tuple IN과 반환 tuple 집합의 완전 일치 검사. 기존 join·active/ready·workspace_read_allowed를 보존해 왕복만 줄인다.
- 제외: 문서 ID만 비교하거나 세 ID를 독립 IN으로 바꾸는 방식은 교차 조합을 잘못 허용한다. 저장 권한/요청 간 cache는 현재 권한 철회를 놓치므로 사용하지 않는다.
- 계산 후보: source 순회의 임시 set·불필요 scalar 호출 감소 또는 반복된 순수 계산 축소. 프로파일·동등성 증거가 없으면 제품 수정하지 않는다. 숫자 proof·판정을 생략하지 않는다.

계측 후 채택: `conversations/access.py::source_identities(value)`는 한 호출 안의 지역 accumulator와 재귀 collector를 사용한다. 현재 전체 dict/list 깊이우선 순회·부모 triple의 document→version→projection UUID 파싱·set dedup·입력 불변·호출별 새 결과를 유지하고 scalar마다 빈 set 생성/병합만 제거한다. 명시 stack으로 recursion 오류를 바꾸거나 visited 캐시를 만들지 않는다. cProfile에서574,157회/누적1.774초를 관측했다(프로파일러 포함 수치이므로 실제 개선율로 사용하지 않음). 판정 digest도 비용이 있으나 현재 품질 계약 보존을 위해 이번 제품 변경에서 제외한다.

## Global Constraints

- 기존 owner 차단, 빈 source SQL0, 중첩 dict/list 전체 source 추출·UUID 오류, 시작/끝 재추출과 fresh SQL을 유지한다.
- 현재 visible_run에 없는 active_version/index-build/외부전송 조건을 추가하지 않는다. 일반 대화·external 전송·numeric operand의 더 강한 검증과 혼합하지 않는다.
- batch64는 DB 왕복/매개변수의 내부 상한이며 업무·모델 정책값이 아니다. session 동시 execute·추가 worker를 도입하지 않는다.
- 목록 정렬·cursor·통계·리뷰 판정·답변/인용·실행 전체 실패 처리 동일. 모델·입력·검색·생성·UI 변경0.
- 원본 체크아웃2243파일/.env·DB/계정을 보존한다. 기존 환경의 읽기 전용 실측만 수행한다. commit/push·캐시 삭제 없음.

## Review Focus

1. 다른 owner·빈 source는 SQL0, 부분 source 키는 자식 순회를 막지 않으며 완전한 잘못된 UUID는 기존처럼 실패.
2. 교차 조합·누락 tuple·문서 비활성·버전/처리본 nonready·현재 membership/active user·개인/임시/회사 권한 거절.
3. 같은 문서의 여러 버전/처리본·중복 source·다중 chunk·DB 결과 중복에서 완전 집합 비교.
4. 두 번째 checkpoint의 원문 추가/권한 철회와 SQL 오류·취소는 기존 실패/전파 유지.
5. 계산 경로는 반환 값·UUID 파싱 순서/예외와 기존 입력 종류·리뷰 digest를 보존하고 호출 밖에 결과를 캐시하지 않음.

## Tasks

- [x] 새 파일/.env 기준선과 변경 전5모듈 복사본 확보. 기존 DB의 동일 응답 해시와 CPU/SQL 비용을 읽기 전용 계측.
- [x] 백엔드 담당: `evaluation/generative_read.py`의 `visible_run(session, actor_id, run) -> bool`만 우선 변경. `tests/unit/labs/rag/evaluation/test_source_visibility_batch.py`에64/65/129개 조회 수·정확 tuple·실패/취소·빈/owner/중첩 경계 RED를 확인하고 최소 구현. 기존 `test_generative_trace_authority.py` fake는 필요한 계약만 갱신.
- [x] 계산 구현 담당: `conversations/access.py::source_identities(value: object) -> set[tuple[UUID, UUID, UUID]]`의 지역 accumulator 재귀로 임시 할당 제거. 신규 `tests/unit/labs/rag/conversations/test_source_identities_cost.py`에서 다중/nested/중복/부분키/완전부모자식/UUID 오류·파싱 순서/tuple 무시/입력 불변·호출 간 변경/cycle 경계를 기존과 대조하고 scalar 빈set·함수 호출 수 비용 회귀를 검증한다. SQL과 `ConversationAccess.visible/identity`는 수정하지 않는다.
- [x] 독립 QA: 관련 executions/evaluation/conversations/numeric 회귀·별도 보안 테스트, 범위 Mypy/Ruff 및 기존 데이터 해시를 확인. 테스트는 명시 task-local basetemp와 승인 Conda 사용.
- [x] 메인: profiler 없는 전후2쌍의 전체508건 해시·시간·SQL을 비교. 새 기준선만 사용하고 CPU 계측 수치와 섞지 않음.
- [x] 유휴 작업0·정확 API 신원 확인 후 본래 동일 환경 반영. health/ready와 로그인 목록/필터/상세,25표/.env 보존·ISSUE42·WORKBOARD·worklog 마감.

마지막 단계 완료: 본래 API 반영·health/ready/API 계약·25표2560행/.env 보존을 확인했다. 세션 만료로 잠시 남았던 상세/필터 검증은 사용자 재로그인 후 전체508건·대화25건·저장 답변/인용2개/근거28개 확인으로 마감했다. ISSUE42 수정·진행 이력을 저장·재조회했고 마지막 계측13~15초 지연과 기존 정답0/2 한계는 후속으로 남겼다.

테스트 명령은 기존 승인 Conda에서 `python -B -m pytest tests/unit/labs/rag/evaluation/test_source_visibility_batch.py tests/unit/labs/rag/executions -q --basetemp=<taskroot>/pytest-temp-1`을 시작으로 영향 경계에 맞춰 실행한다. 독립 검증은 구현 결과와 중복 합산하지 않고 JUnit 고유 사례를 집계한다.

## 역할

위험 높음: 현재 원문 권한 조회. 메인은 요구/설계/실측/통합/문서, 백엔드·DB 담당은 제품과 RED/GREEN, 독립 담당은 security/test/integration/review, 읽기분석 담당은 계산 병목 설계를 맡는다. UI/AI-runtime/배포 구조 변경 역할은 실제 변경 범위에 없어 제외한다.
