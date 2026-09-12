# Domain-first RAG Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. No subagent commits; main-only work is explicitly authorized.

**Goal:** 관리자 동적 도메인 연결과 로그인 사용자 도메인 선택→대화→범위 조정 흐름을 구현한다.
**Architecture:** RAG domain repository/service가 버전과 권한 교집합을 해석하고 기존 search/generation을 재사용한다. UI는 도메인 진입·관리와 대화·근거 패널을 분리한다.
**Tech Stack:** Existing FastAPI/SQLAlchemy/PostgreSQL, Next.js/React/TypeScript, pytest/Vitest.
**Spec:** `docs/superpowers/specs/2026-09-07-domain-first-rag-conversation-design.md`

## Global Constraints

- main에서 작업하며 기존 OCR 변경과 사용자 references를 보존한다.
- 도메인은 새 권한을 부여하지 않는다. 범위는 도메인 허용 공간 ∩ 구성 허용 공간 ∩ 현재 사용자 권한이다.
- 도메인 목록·모델·프로파일을 하드코딩하지 않는다. 기존 문서 자동 재분류와 설정 자동 승격은 없다.
- 공개 검색·인라인 첨부·피드백 저장은 이번 범위가 아니다. 작동하지 않는 버튼은 추가하지 않는다.
- 모델·Docker 변경과 외부 모델 호출은 없다. 테스트는 외부 모델 없이, 통합 DB는 사용자 DB와 격리한다.
- 도메인 경로는 generative/evaluated/ready 구성을 요구하며 조용한 extractive fallback은 없다.
- 범위 변경 시 이전 메시지는 보존하고 다음 LLM history는 새 문맥 구간만 사용한다.
- 임시 기록은 `.local-data/project-agent-work/domain-conversation/`에만 둔다.
- 각 task는 RED→GREEN 증거와 독립 리뷰를 갖는다. commit/push는 메인만 결정한다.

## Task 1: Domain backend and scope-bound conversation contract

**Files:** Create `backend/src/ai_workshop/labs/rag/domains/{models,schemas,repository,service,api}.py`, `backend/alembic/versions/0023_rag_domains.py`, tests under `backend/tests/unit/labs/rag/domains/` and `backend/tests/integration/labs/rag/domains/`. Modify model registration/router registration and minimally extend generation integrity/search API integration as needed. Do not alter unrelated OCR logic.

**Consumes:** existing saved configuration version resolver/readiness, workspace permissions, folder scope resolver, SearchApplicationService and ConversationTurnSigner.
**Produces:** owner CRUD/connection activation plus authenticated domain listing/detail/search; frontend contract recorded in task report and generated OpenAPI. Prefix `/api/v1/rag/domains`; owner management `/api/v1/admin/rag/domains` (follow existing owner API conventions if prefix conflicts; report exact routes before frontend).

- [x] Write failing unit tests: domain version cannot permit a workspace outside configuration/current-user intersection; inactive/stale connection refused; empty request scope rejected; scope signer rejects other domain/version/folder/actor and legacy token replay.
  Example behavior assertion:
  ```python
  assert resolve_allowed_workspaces(domain=(a, b), configuration=(b, c), actor=(a, b)) == (b,)
  ```
  Use repository fakes only for external DB access; exercise real service and signer.
- [x] Run focused pytest, record RED, implement typed entities and services. Domain slug immutable/unique, display name/description editable; immutable connection versions bind exact config version/workspaces; explicit active pointer and deactivation. Owner activation checks current readiness, evaluated generative config. No seeded domain rows.
- [x] Add isolated migration/API tests: owner vs member vs anonymous, immutable connections, invalid foreign workspace, stale version, inaccessible names not exposed, authorized detail/search, nonready generation. Use temporary database only; migration head0022 is predecessor. Constraints/triggers follow existing immutable version patterns.
- [x] Reuse existing search core with a dedicated domain entry that resolves server-side config and validates scope before retrieval. Bind assistant signatures to actor/config/domain connection/sorted unique workspace+folder scope. Preserve legacy search signature contract separately. External transfer policy still runs in existing search service. Exact pinned version must not silently resolve latest; revoked/changed domain connection fails explicitly.
- [x] API response includes domain slug/name/description, connection version identity, readiness and only allowed workspace options, plus safe generation execution preview needed for user notice. Search input includes pinned connection version, query, workspace_ids, folder_ids and history (no request approval field; stored configuration approval remains authoritative); no arbitrary configuration override. Return existing SearchResponse shape where possible. Report exact schema for Task2.
- [x] Run focused tests, Ruff and mypy; record GREEN. Do not apply migration to user DB. Prepare report and diff for independent review.

## Task 2: Domain selection, administration and conversation UI

**Files:** Create `frontend/src/features/rag/domains/` and `frontend/src/features/rag/conversation/` focused API/components/styles/tests. Modify search route to domain picker; add chat route and admin domains route. Modify shared routing/navigation/schema and relevant route tests. Existing SearchPage can remain as compatibility implementation, but not render at user entry.
**Consumes:** Task1 OpenAPI endpoints; existing authenticated server fetch, user guards, folder API, source viewer/answer components.
**Produces:** `/workshop/rag/search`, `/workshop/rag/domains/[slug]/chat`, `/admin/rag/domains`.

- [x] Generate schema from local OpenAPI exporter using existing tooling, not handwritten duplication.
- [x] Write failing Vitest tests for dynamic domain list, no config/workspace chooser at entry, owner-only empty-state manage link, disabled unready domain, admin registration and immutable connection activation/deactivation. Implement minimal UI after RED.
- [x] Write conversation tests: sending a question renders user message and returned LLM answer; next question includes verified assistant history; selecting folder preserves old transcript but clears next request history; scopes are captured per answer; all spaces deselected blocks sending. Wrong response arriving after cancel/new conversation is ignored.
  ```ts
  expect(screen.getByRole('textbox', {name: '질문'})).toBeVisible();
  expect(screen.queryByLabelText('RAG 구성')).not.toBeInTheDocument();
  ```
  Assert request contract at API boundary for scope/history, not implementation internals.
- [x] Implement full-width chat layout, collapsible in-chat scopes, Enter/Shift+Enter/IME controls, new conversation and domain exit cancellation, immutable answer context, retry/error/insufficient-evidence states, generation-policy notice and consent. No placeholder attachments/feedback. Preserve browser-only memory notice.
- [x] Reuse source fetching/highlights in side panel with close/focus restoration, mobile full-width panel, keyboard Escape. Do not duplicate backend source parsing. Inline citations must open matching evidence; no external generation invocation from tests.
- [x] Run affected Vitest, TypeScript, ESLint, then report for independent review. Keep API user responses free of internal settings panels.

## Task 3: Integration verification and local handoff

**Files:** update `WORKBOARD.md`, RAG design/runbook and task worklog. Tests/bugfixes go back to original implementer with focused review.
**Consumes:** Task1+2 reviewed code; **Produces:** coherent frontend/backend contract and explicit handoff.

- [x] Run backend full unit tests, domain isolated integration/migration tests, Ruff/mypy, frontend full Vitest/tsc/eslint, OpenAPI check, production build where it does not disrupt live dev artifacts (stop/start dev only if required and report).
- [x] Verify local route guards and response health without reading user secrets or altering owner credentials. Apply reviewed additive migration through normal local runbook only after isolated upgrade/rollback passes. Do not create or activate a domain without user's actual mapping choice.
- [x] Final independent review for spec and quality, fix covered regressions, rerun affected checks.
- [x] Record exact passing/blocked checks, current no-domain/no-generation states and admin setup instructions. Do not claim live LLM or browser visuals verified if not exercised. Keep completed workboard entries <=5 and preserve pending cleanup approval separately.

## Verification handoff

구현·독립 리뷰와 검증 실행을 완료했다. 최종 전체 프론트 실행은 234 passed / 3 failed이며,
실패한 기존 두 파일은 코드·제한 시간 변경 없이 36 passed로 재검증했다. 단일 전체 실행 통과와
구분한다. 실제 로그인 화면·LLM 검증은 관리자 연결 후 진행한다. 명령·결과·제한은
[작업 기록](../../worklogs/2026-09-07-domain-first-rag-conversation.md)을 따른다.
