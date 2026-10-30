# 실행 목록 검증 조회 일괄화 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development task-by-task; implementation and independent security verification remain separate.

**Goal:** 기존 실행 목록의 응답·현재 권한·숫자 증명·legacy 호환을 유지하면서 반복 검증 SQL을 줄인다.

**Architecture:** 평가 목록의 `run_detail(list_only=True)` 안에 한정된 bounded context batch를 사용한다. 검증에 필요한 Audit/Profile 설정을 scalar projection으로 묶어 읽고 schema3에만 receipt를 읽는다. 기존 숫자 payload·fresh receipt/audit·현재 근거 ACL 검증은 그대로 호출하며 batch 이후 authority를 새로 읽어 비교한다. 일반 대화·상세·생성 경로는 변경하지 않는다.

**Tech Stack:** 기존 Python/FastAPI/SQLAlchemy/PostgreSQL, 기존 Conda와 pytest/Mypy/Ruff. 설치·migration 없음.

**Spec:** 이 문서의 요구·경계와 [ADR-0036](../../decisions/0036-rag-source-backed-calculation.md), 사용자 승인된 [선행 작업 후속](../../worklogs/2026-10-26-execution-list-mobile.md).

## 승인 범위와 근거

사용자가 제안받은 반복 검증 조회 일괄화를 진행하라고 승인했다. 기존 답변 품질·기능을 유지한다. 새로운 공개 API/DB 계약·정책 변경은 없으며 기존 어댑터 내부의 목록 전용 읽기다. 별도 ADR은 필요하지 않다.

이번 새 기준선: 기존DB508건/첫25건10.183초, 대화295 SQL/평가1,863 SQL. 앞선17초와 다른 측정 시점이므로 그 수치에 직접 개선율을 계산하지 않는다. Profile445회에 모델 bindings445회가 자동으로 추가 조회됐지만 숫자 context는 profile.config만 사용한다. 정확한 projection은 불필요 relationship 로딩을 제거한다.

## Global Constraints

- 기존 API·필터·정렬·cursor·전체통계·run 전체 fail-closed 유지.
- 현재 actor/execution/config/profile/receipt/request/status/evidence 순서·숫자 payload digest·재구성과 정확 위치/ready/index-build/ACL 검사 유지.
- schema1/2와 execution=None 무필드는 기존처럼 numeric 테이블 무조회. schema3 binding 누락은 거절.
- 요청간·worker간 cache 없음. 각 batch는 한 run의 독립 session에만 존재하며 마지막 권한/원문 재추출을 유지한다.
- 최대64개 execution의 SQL/메모리 경계를 사용한다. 모델·품질·업무 정책값이 아닌 내부 읽기 크기이며 추가 task/connection을 만들지 않는다.
- Audit execution_id 중복을 임의 dict 덮어쓰기로 선택하지 않는다. 중복 ID는 기존 단건 경로로 검사하여 기존 첫 행 선택 의미를 보존하고, 신규 모호성을 성공으로 축약하지 않는다.
- 원래 dirty checkout을 보존한다. 기존 업무 데이터/계정/프로파일을 변경하지 않고 읽기 전용 실측한다. 실모델0회.

## Review Focus

1. mixed legacy/schema3와 numeric 테이블 없는0061 조건: legacy는 receipt SQL 생성·조회0.
2. 없는 audit/profile, 다른 actor, 중복 audit, 숫자 필드 주입: 기존 fail-closed/단건 의미 보존.
3. batch 중 authority 변경/삭제/권한 철회: 새 후검증으로 거절. ORM identity-map을 새 조회로 오인하지 않음.
4. receipt 재조회·근거 ACL·operand 위치 등 기존 최종 검증: batch snapshot으로 치환하지 않음.
5. 빈 입력·64 경계·오류·취소·4-worker 독립 session: 무필터 SQL·무제한 task·정리 누락 없음.

## Tasks

- [x] 현재 소스/DB 쿼리 기준선·파일2239개/.env·변경 전 모듈 복사본을 확보한다.
- [x] 백엔드 담당: 새 `generation/numeric_validation_batch.py`와 필요한 목록 연결만 구현한다. 기존 generation verifier는 가급적 변경하지 않는다. `evaluation/generative_read.py`에서 완료 attempt chunk에만 연결하고 결과 순서/품질 계산을 보존한다.
- [x] 신규 단위 회귀에서 N에 비례한 context 쿼리·불필요 profile binding 읽기를 실패로 확인한 뒤 구현한다. 위5개 실패 경계를 함께 검증한다.
- [x] 독립 보안/코드 검토와 pytest·Mypy·Ruff를 실행한다. 기존 DB의 read-only 전후 응답 해시·SQL수·시간과 schema3 복원은 root가 확인한다.
- [x] 본래 API가 유휴임을 확인하고 동일 환경에 반영한 뒤 로그인 목록/필터/상세를 확인한다. 업무25표/.env 보존과 ISSUE-00042/WORKBOARD/작업 기록을 갱신한다.

## 역할과 변경 책임

위험 높음: 숫자 증명과 현재 권한 읽기. 메인은 요구·설계·실측·통합·문서 마감을 맡는다. 백엔드/DB 구현 담당과 독립 security/test/integration/code-review 담당을 분리한다. 추가 읽기 분석 담당은 exact source tuple 배치의 의미만 검토한다. UI/모델/프롬프트/검색 구현은 제외한다. 근거는 `.local-data/project-agent-work/execution-validation-batch-20261026/`에 본문 없는 건수·해시·시간으로 남긴다.
