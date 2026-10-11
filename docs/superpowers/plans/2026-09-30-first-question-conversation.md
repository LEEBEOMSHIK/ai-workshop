# 첫 질문 접수·첨부 초안·의도 제목 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. 구현 담당은 작업별로 순차 배정하며 메인만 통합·staging·commit·push를 결정한다.

**Goal:** 질문 전에는 대화를 만들지 않고, 유효한 첫 질문과 첨부 결합을 원자적으로 접수하며 첫 질문의 대상·요청을 보존하는 제목을 제공한다.

**Architecture:** RAG에 owner 전용 첨부 초안과 첫 접수 원장을 추가한다. start UoW 이후 기존 생성 실행 코어를 재사용한다. Platform intake 예약 확장 지점은 RAG에 의존하지 않는다.

**Tech Stack:** FastAPI, SQLAlchemy/PostgreSQL, Alembic, Pydantic, Next.js/React, Vitest.

**Spec:** [첫 질문 설계](../specs/2026-09-27-first-question-conversation-design.md), [ADR-0031](../../decisions/0031-first-question-conversation-and-drafts.md).

## Global Constraints

- 기존 환경·DB·계정·자료를 보존한다. 별도 사용자 실행 환경·계정은 만들지 않는다.
- 외부 제목 모델 호출·generation prompt/schema·프로파일·활성 구성 변경은 없다.
- 같은 owner/domain/request_id와 같은 payload는 대화·첫 turn·외부 생성을 중복하지 않는다. 다른 payload는409, 삭제 후 replay는410이다.
- 검증 거부·업로드 종료 미확인·트랜잭션 실패는 빈 대화를 남기지 않는다.
- 현재 owner/domain/source 권한을 검사하며 첫 turn이 가려지면 목록·상세·replay 제목도 가린다.
- 첨부 취소·만료·legacy 이관은 원본 영구 삭제가 아니다.
- 수정 책임과 독립 리뷰 책임을 분리한다. 하위 에이전트는 추가 에이전트·실환경 migration·stage·commit·push를 실행하지 않는다.
- 로컬 진행 원장은 `.local-data/project-agent-work/first-question-20260930/progress.md`에 둔다.

## Review Focus

DB 원자성/멱등성, 업로드 잠금 순서·종료 확인, 권한 철회 시 제목 유출 방지, 기존 세션 보존, 구 API 차단, 새 화면에 늦은 응답이 덮어쓰지 않는지 확인한다.

### Task 1: 백엔드 start·draft·제목 계약 구현

**Files:** `backend/src/ai_workshop/labs/rag/conversations/{domain,models,repository,schemas,service,api,attachment_models,attachment_service,attachment_api,attachment_lifecycle,title_policy}.py`, 관련 Platform intake 어댑터·worker·typed config, `backend/alembic/versions/`의 다음 Alembic revision, `backend/tests/unit/labs/rag/conversations/`, 필요한 통합 테스트.

- [x] 실제 기존 경로·테스트 설정과 migration head를 먼저 확인한다.
- [x] 제목 보존·fallback·수동 변경, no-draft 중복 start/충돌/삭제 replay, draft owner/revision/업로드 busy/완료·실패, 취소/만료/legacy, 구 create 차단의 실패 테스트를 작성하고 실행한다.
- [x] `rag_conversation_starts`, `rag_attachment_drafts`, attachment 부모 XOR, 제목 provenance를 additive migration으로 구현한다. 새 draft/start 데이터가 있으면 downgrade를 선행 검사로 차단한다.
- [x] `POST /rag/domains/{slug}/conversations/start`는 기존 submit 필드에서 revision만 제외하고 request_id, 선택적 draft_id/draft_revision 쌍을 받는다. 응답은 기존 `ConversationDetail`이다. 같은 접수키 조회는 현재 owner/domain 검사 후 수행한다.
- [x] `GET /rag/domains/{slug}/conversations/starts/{request_id}`는 현재 ACL을 적용한 ConversationDetail을 반환한다.404는 접수 미확인, 삭제는410이며 no-store다. 첫 생성 대기 중 ID 복원 후 기존 cancel API를 재사용한다.
- [x] draft create는 request_id를 받고, GET/DELETE draft 및 draft attachments list/upload/exclude와 도메인 attachment options를 제공한다. 각 실제 경로·schema를 보고서에 명시해 프론트에 인계한다. 조회 응답은 no-store다.
- [x] 한 UoW가 ledger/conversation/first-turn/draft-bound/attachment FK를 commit한다. 기존 submit의 예약 후 실행 코어를 재사용한다. scope/classification/consent 결정적 거부는 commit 전에 검사한다.
- [x] Platform intake 예약과 RAG binding은 같은 transaction 확장 지점을 이용한다. 잠금은 workspace/source→intake→RAG parent→attachment 순서이며 start의 저장 권한 재검사도 역순을 만들지 않는다.
- [x] upload transport 종료 확인은 draft/legacy 부모도 지원한다. failed 종료 확인 첨부를 영구 busy로 만들지 않는다. TTL1440분·reconcile60초 설정과 취소/만료 inventory를 구현한다.
- [x] legacy 빈 대화는 질문 목록에서 제외하고 읽기 복원·이관을 제공한다. 활성 writer 종료 전 FK 이전과 구 경로의 신규 쓰기를 차단한다.
- [x] 로컬 제목은 첫 질문만 사용한다. 기본64자 설정(2~180), 일반 문법 정리, 불확실/장문 fallback `새 대화`, 제목 metadata, 첫 turn ACL 기반 서버 가림을 구현한다.
- [x] 관련 pytest, Ruff, mypy를 실행하고 실패/수정/통과 증거 및 공개 계약을 report에 기록한다. 실행 DB는 disposable 설정을 확인하기 전 통합 fixture를 사용하지 않는다.

### Task 2: 프론트 초안·첫 전송 상태 구현

**Files:** `frontend/src/features/rag/conversation/{ConversationPage,ConversationAttachments,types,sessions-api,api}` 및 관련 테스트. OpenAPI 생성 타입은 메인이 백엔드 계약 확정 후 재생성한다.

- [x] Task1의 실제 경로·schema를 보고서에서 읽고, 기존 API 테스트와 페이지/첨부 테스트에 실패 사례를 추가해 먼저 실행한다.
- [x] sessionId와 draftId를 분리한다. 방문/새 대화/문서 선택/옵션 조회는 생성 요청이0회이며 실제 파일 선택/드롭에서만 draft를 만든다.
- [x] 첫 질문은 start 한 번으로 제출한다. 재시도 payload와 request_id를 보존하며 성공 접수 후만 목록·URL을 갱신한다. 후속 turn과 기존 세션 이어가기·수동 제목 변경을 유지한다.
- [x] 첫 start 대기/응답유실은 request_id 기반 접수 조회로 복구한다. fetch abort나 조회404를 서버 취소 완료로 표시하지 않고 payload/key·취소 대기를 유지해 접수 후 기존 cancel을 수행한다.
- [x] draft upload/poll/exclude/포기/새로고침 복원·legacy 복원을 구현한다. 시작 중 파일 transport 완료를 기다리고 서버 busy/expired/권한 거부를 명확히 표시한다.
- [x] 다른 대화/새 초안 이동 후 늦은 시작 응답이 화면을 덮어쓰지 않도록 화면 세대와 요청 상태를 확인한다.
- [x] 관련 Vitest, TypeScript, ESLint를 실행하고 report에 결과를 남긴다.

### Task 2a: 본래 Codex 런타임 호환성 복구

첫 질문 실제 화면 검증을 준비하며 등록된 CLI0.158.0과 설치된 OpenAI 서명 CLI0.159.2의
불일치를 발견했다. registry의 해시 거부와 command builder의 정확한 버전 차단을 함께 처리한다.
프론트 구현·리뷰 이후 별도 순차 구현으로 수행하며 원래 모델·구성·계정·전송 정책은 유지한다.

**Files:** `backend/src/ai_workshop/labs/rag/generation/codex_command.py`, 관련 command 계약 테스트,
Git 제외 본래 `.env`의 해당 runner 버전·해시, 운영 기록.

- [x] 실제 서명·버전·해시와 공식 릴리스를 확인하고 독립 보안/운영 검토를 받는다.
- [x] 실제 CLI argv/event 지원을 확인한 정확한0.159.2만 허용한다. 인접·미검토 버전과 prerelease는 거부한다.
- [x] TDD·관련 command/event/verification 테스트, Ruff·mypy와 독립 리뷰를 수행한다.
- [x] 같은 경로·실행 제한을 보존하며 본래 `.env`의 버전·해시만 갱신한다. 기존 비밀 설정은 보존한다.
- [x] 같은 환경 API 재시작 후 활성 구성의 실제 합성 연결 검사를 다시 수행한다. 저장 증거를 수동 조작하지 않는다.

### Task 3: 독립 리뷰·본래 환경 반영·이력

**Files:** 원래 runtime의 migration/검증 증거, `WORKBOARD.md`, RAG 설계·runbook, DB ISSUE-00001 및 관련 문서 정확한 버전.

- [x] Task1/2 수정 diff와 report를 파일로 독립 리뷰에 제공한다. spec 충족과 코드 품질을 각각 판정하고 수정 후 covering tests·재리뷰를 수행한다.
- [x] 관련 회귀와 타입/린트, OpenAPI 타입 재생성·문서 검사 결과를 확인한다.
- [x] 기존 DB 백업·legacy/attachment/turn inventory 후 원래 API/worker/beat를 안전히 중지하고 migration을 적용한다. 원본·계정·활성 모델과 구성은 변경하지 않는다.
- [x] 실제 first/followup POST 최종 권한 재확인의 닫힌 트랜잭션 오류를 보완하고 독립 리뷰·관련 회귀·실제 HTTP 성공을 확인한다. 감사commit과 최종ACL은 유지한다.
- [x] 같은 환경을 재시작해 health·브라우저 방문/파일 초안/첫 제목/기존 대화/후속 POST200을 확인했다. 권한 가림·늦은 응답은 회귀·원래 SQL로 확인했으며 실제 브라우저 권한 철회·다중 연결 commit 경합·종료 뒤 복구는 작업 기록의 미검증 경계로 남겼다.
- [x] 이력 DB의 ISSUE-00001에 구현/검증/남은 범위를 저장하고 설계 exact v3·최종 검증 기록 exact v1을 연결했다. READ ONLY 조회로 본문·해시·출처 일치와 기존 설계 v1/v2 연결 보존을 확인했다. WORKBOARD 최근 완료5개·문서10개/링크65개 검사를 마감했다.

## Verification Commands

프로젝트 정본 `docs/runbooks/local-development.md`와 각 package 설정을 확인해 실행한다. 저장소 루트에서 `backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/unit/labs/rag/conversations -q`, backend 작업 디렉터리에서 `.venv/Scripts/python.exe -m ruff check`·`-m mypy`, 프론트 `pnpm --dir frontend test --run src/features/rag/conversation --maxWorkers=1`·`typecheck`·`lint`·`api:check`를 사용한다. 관련 검증을 먼저 실행하고 새 변경/실패/미해결 우려가 없으면 반복 확장하지 않는다.
