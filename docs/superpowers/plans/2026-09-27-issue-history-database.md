# Issue History Database Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

**Goal:** 카테고리·문제·진행 기록·불변 문서를 기존 PostgreSQL에 보존하고 관리자에서 관리한다.
**Architecture:** Platform Issue History의 service/repository/API, 기존 인증·CSRF·DB 기반을 재사용한다. 최초 이관 후 DB가 운영 정본이다.
**Tech Stack:** FastAPI, SQLAlchemy/PostgreSQL, Next.js/React, pytest/Vitest.
**Spec:** [승인 설계](../specs/2026-09-27-issue-history-database-design.md).

## Global Constraints

- 본래 체크아웃·DB·계정 유지. 추가 환경·더미 영속 데이터 없음.
- 마스터 전용, public 앱 미등록, 본문 로그 금지. 문제 연결은 정확한 문서 버전 FK.
- 문서 512KiB/제목200자/장문20000자/배열100개·항목2000자.
- 쓰기 request_id 멱등성과 expected_revision 충돌 처리. 기존 기록 삭제 없음.

## Review Focus

- 재전송·동시 등록: 한 요청은 한 결과와 사건만 남긴다.
- 변경된 이관 입력: 기존 DB 기록을 덮어쓰지 않는다.
- 비활성 카테고리: 기존 문제 수정은 가능하지만 신규 배정은 거부한다.
- 과거 본문 재등록: 현재 버전을 과거로 되돌리지 않는다.
- 연결 제거·교체: 과거 사건과 문서 본문이 유지된다.

## Task 1 — Backend contract and persistence

Files: `backend/src/ai_workshop/platform/issue_history/{schemas,models,repository,service,api}.py`, additive Alembic revision, main/alembic imports, scoped backend tests.

- [x] 실패하는 스키마·서비스·권한 테스트 작성 및 실행.
- [x] 카테고리/문제/사건/문서/버전/링크/명령/이관 테이블과 FK 구현.
- [x] `/api/v1/admin/issue-history` categories/issues/documents GET·POST·PUT 및 events/links/version 쓰기 API. DTO를 프론트 담당에게 먼저 전달.
- [x] 잠금·멱등성·충돌·원자 감사와 목록20/최대100, 상태 집계·검색 구현.
- [x] scoped pytest, ruff, mypy. 명령은 backend cwd에서 `.venv/Scripts/python.exe -m pytest tests/unit/platform/issue_history -q`, ruff/mypy는 변경 모듈 경로.

## Task 2 — Frontend management

Files: `frontend/src/features/issue-history/*`, `app/(administration)/admin/system/issues/*`, generated API types.

- [x] 한글 카테고리·서버 검색/페이지·문서 버전·수정 충돌 테스트 작성/실패 확인.
- [x] 기존 파일 로더 대신 인증 서버 API를 사용하고 목록·상세·문서 관리 UI 연결.
- [x] 카테고리 관리, 문제 등록/편집·사건 추가, 문서 등록/새 버전·정확한 버전 연결/해제 제공.
- [x] `pnpm typecheck`, targeted ESLint와 Vitest 실행.

## Task 3 — Import and original environment

Files: `backend/src/ai_workshop/platform/issue_history/importer.py`, CLI script, importer tests, worklog/runbook.

- [x] 원본 누락·경로·크기·UTF8·중복 및 manifest 안정성 테스트 후 구현.
- [x] 전체 파일 사전 검증, 동일 입력 재실행 무변경, 상이한 입력 충돌. 모든 관계 단일 트랜잭션.
- [x] 본래 DB 백업·head·기존 수량 확인 → 가산 migration → dry-run/수입 → ID/본문해시/관계/사건수 대조.
- [ ] 원래 API 재시작·health와 실제 관리자 메뉴 조회 검증. 실제 사용자 자료는 변경하지 않는다.

## Task 4 — Independent review and handoff

- [x] 구현 담당과 분리된 보안·동시성·통합 검토 후 수정.
- [x] schema 생성/check, 필요한 회귀 테스트·타입·린트·문서 링크 검증.
- [x] DB 정본 규칙·WORKBOARD·작업 기록 갱신, 이번 파일만 commit/push.

사용자가 상세 설계 후 명시적으로 구현을 요청했다. 위 계획을 같은 세션에서 수행한다.
