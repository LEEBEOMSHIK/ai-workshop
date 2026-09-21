# RAG Conversation Sessions and Composer Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement the approved design continuously. User explicitly approved implementation; do not stop for another plan approval.

**Goal:** 서버에 대화를 보관하고 다시 이어가며 입력창에서 문서를 추가하고 근거·유사도를 바로 확인한다.
**Architecture:** RAG conversations 모듈이 소유자별 대화·turn·첨부 연결을 저장한다. 기존 도메인 검색 실행기와 Asset 업로드를 재사용한다.
**Tech Stack:** FastAPI, SQLAlchemy/Alembic/PostgreSQL, Next.js/React, pytest/Vitest.
**Spec:** `docs/superpowers/specs/2026-09-21-rag-conversation-sessions-ux-design.md`.

## Global Constraints

- 원본 main checkout과 기존 DB/계정/문서를 사용한다. 새 worktree·별도 DB·임의 테스트 계정을 만들지 않는다.
- 업무 코드에 실제 사용자/상품/환경 ID를 넣지 않는다. 외부 모델 입력은 기존 승인 합성 자료만 사용한다.
- root만 통합·운영 적용·WORKBOARD·commit/push를 담당한다. 담당자별 파일 소유권을 분리한다.
- 대화 삭제는 tombstone으로 즉시 조회/완료를 차단한다. 기존 원본과 audit는 삭제하지 않는다.
- 서버가 저장 history를 구성한다. 클라이언트 임의 응답 import와 자동 모델 재실행을 허용하지 않는다.
- 필요한 additive migration은 백업·기존 스키마/행수 보존 확인 후 본래 DB에 적용한다.

## Review Focus

1. 권한 철회된 저장 본문·출처·진단·history가 재노출되지 않는다.
2. 중복 요청·취소·삭제와 늦은 완료 경합에서 중복 모델 호출이나 대화 부활이 없다.
3. 새 대화/전환/새로고침은 이전 세션을 지우지 않고, 연결·문서 변경은 새 문맥 구간으로 분리한다.
4. 첨부 권한/도메인/분류 확인은 기존 문서 선택과 별개이며 파일 선택 해제가 원본을 지우지 않는다.
5. UI 준비 완료와 실제 활성 profile을 구분하고 모델 정답/인용을 실제 원본 환경에서 확인한다.

## Task 1: 서버 세션과 영속 turn

소유: backend 담당. 신규 `backend/src/ai_workshop/labs/rag/conversations/`의 domain/models/repository/service/schemas/api,
`backend/alembic/versions/0049_rag_conversations.py`, main router 등록과 migration model 등록, 관련 unit/contract tests.

- [x] owner/도메인 CRUD, revision/unique 요청/실패·취소 저장, 삭제 경합, 타 사용자 차단 회귀를 먼저 작성하고 실패를 확인한다.
- [x] 짧은 예약 commit → 기존 DomainSearchExecutor → 조건부 완료 commit. per-session 동시 실행은409, 재시도는 기존 요청 결과.
- [x] 저장 scope 및 현재 권한을 재검증해 서버 history를 조립한다. 연결/선택 identity 변경 시 새 segment; 과거 문맥을 숨겨 재사용하지 않는다.
- [x] 상세 조회 redaction과 no-store, stale running 상태 복구, 응답 snapshot 저장을 구현한다.
- [x] schema/API를 frontend 담당에게 전달하고 전체 관련 pytest, mypy, Ruff를 실행한다.

API 기준: `/api/v1/rag/domains/{slug}/conversations` GET/POST, `/{conversation_id}` GET/PATCH/DELETE,
`/{conversation_id}/turns` POST, `/{conversation_id}/turns/{request_id}/cancel` POST.
Turn 입력은 DomainSearchRequest에서 history를 제외한 값 + request_id + expected_revision.
Detail은 id/title/revision/created_at/updated_at와 turns를 반환한다. Turn은 id/request_id/status/query/response/요청 scope/segment/error_code/redacted를 포함한다.
계약 변경은 root·frontend에 즉시 알리고 문서에 기록한다.

## Task 2: 대화 목록과 입력창 +, 진단 표시

소유: frontend 담당. `frontend/src/features/rag/conversation/` 및 관련 app route, `frontend/src/app/styles.css`.

- [x] 세션 생성/목록/재개/새 대화 보존/제목 수정/삭제와 취소·실패/낡은 응답 회귀를 먼저 작성한다.
- [x] 서버 세션 목록과 URL 선택, turn 복원, 서버 응답 이후 갱신 및 요청 ID 재사용을 연결한다. localStorage에 본문을 저장하지 않는다.
- [x] 입력창 + 기존 문서 선택/PC 첨부, 파일 chips/제외, 검색 범위 보조 메뉴. 읽기 전용 선택 패널은 유지한다.
- [x] 테스트 진단 기본 수집과 응답 바로 아래 검색 문서 수·유사도 진입. 근거 부족 이유를 실제 reason code에 따라 표시한다.
- [x] 재로그인/전환/본문 redaction/기존 인용 원문·키보드 회귀를 Vitest로 검증하고 typecheck/ESLint를 실행한다.

## Task 3: 첨부와 실제 문맥 구성 적용

소유: root. 기존 Asset 업로드와 session association 계약을 확인한 후 backend 담당과 소유 파일을 분리한다.

- [x] 기존 비공개 공간의 사용자 소유/쓰기·도메인 허용 범위를 검사한 첨부 후보 및 대화 연결을 구현한다.
- [x] 업로드·처리 중/실패/ready 상태와 session 삭제·지연 완료를 기존 추적 계약에 연결한다. 공용 파일함 자동 게시 금지.
- [x] 실제 등록 모델/기존 승인 합성 자료로 새 문맥 profile/config 후보를 정상 서비스로 작성·검증한다.
- [x] 실제 양성/음성/다대상 질문 답변과 인용 검증, 성공한 후보만 연결 활성화. profile/정책 평가 SQL 조작 금지.

## Task 4: 본래 환경 마감 및 독립 검증

- [x] 원래 DB 백업·보존 확인 후 추가 migration 적용, 필요한 기존 서버만 현재 코드로 재시작.
- [x] OpenAPI 타입 생성, 전체 관련 backend/frontend 회귀·mypy/Ruff·TS/ESLint·diff check.
- [x] 독립 검토자가 Task별 계약과 최종 통합을 검토하며 중요 지적을 red→green으로 수정한다.
- [ ] 기존 마스터 화면에서 저장→새로고침→이어가기, +문서, 진단, 모든 인용, 실제 답변을 확인한다.
- [x] WORKBOARD/ADR/실행 기록을 실제 완료 상태로 갱신하고 해당 파일만 commit/push한다.

검증 명령: backend `.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/conversations tests/unit/labs/rag/domains tests/unit/labs/rag/search -q`,
`.venv/Scripts/python.exe -m mypy src/ai_workshop/labs/rag`, `.venv/Scripts/python.exe -m ruff check src/ai_workshop/labs/rag tests/unit/labs/rag`.
frontend `node node_modules/vitest/vitest.mjs run src/features/rag/conversation`, `pnpm typecheck`,
`node node_modules/eslint/bin/eslint.js src/features/rag/conversation --max-warnings 0`, `node openapi-ts.config.mjs --check`.
