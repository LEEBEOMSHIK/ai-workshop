# Document Transfer Reapproval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkboxes for tracking.

**Goal:** 동일 문서의 승인·취소·재승인과 권한 없는 사용자의 요청을 이력 보존 방식으로 제공한다.
**Architecture:** 기존 immutable 승인 행은 이관 원본으로 보존하고 현재 상태/append-only 이벤트를 분리한다. 호출 binding은 승인 세대를 포함해 취소 전 호출을 거절한다. DTO와 UI는 문서 버전과 승인 상태를 구분한다.
**Tech Stack:** FastAPI, SQLAlchemy/PostgreSQL/Alembic, Next.js React TypeScript, pytest/Vitest.
**Spec:** `docs/superpowers/specs/2026-09-10-document-transfer-reapproval.md`

## Global Constraints

- main에서만 작업한다. 기존 dirty worktree 보존, staging/commit/push는 메인만 결정하며 이번에는 수행하지 않는다.
- 코드 검증과 실제 DB 이관/서비스 재시작/문서 승인은 별도다. 실제 문서 승인과 모델 호출은 하지 않는다.
- Codex owner-only, 공간 권한/정책, READY/활성 실행, 평가 gate를 유지한다.
- 승인 변경으로 문서/해시/색인/임베딩을 재생성하지 않는다.
- 권한 없는 사용자의 요청은 실행이나 승인이 아니다. 기술 configure는 전송 승인 권한이 아니다.
- 새 binding만 발급하며 기존 v2 호출은 거절한다. 구세대 호출을 새 세대로 소급 보정하지 않는다.
- 임시 보고서/기준 스냅샷은 `.local-data/project-agent-work/document-transfer-reapproval/`에 한정한다.

## Task 1: 관리자 승인 저장·보안·API 수직 단위

**Files:**
- Create `backend/alembic/versions/0031_evidence_reapproval.py`.
- Create `backend/src/ai_workshop/labs/rag/generation/evidence_approval_lifecycle.py` (현재 상태/이벤트 mutation 책임).
- Modify generation `codex_approval_models.py`, `codex_approval_repository.py`, `codex_approval_codec.py`, `codex_authorization.py`, `codex_composition.py`, `codex_admin_api.py`.
- Test `backend/tests/integration/test_codex_approval_storage.py`, generation unit codec/authorization/API tests and new `backend/tests/unit/labs/rag/generation/test_evidence_approval_lifecycle.py`.

**Interfaces:** 기존 approve/revoke 경로를 유지하되 `expected_generation:int`, `request_id:UUID`를 필수 입력으로 사용한다. 목록 DTO는 `approval_generation`, `provider`, `approval_history`를 추가한다. 이력은 action, generation, actor_id(nullable for legacy revoke), occurred_at, classification을 제공한다. 문서 revision ID는 변경하지 않는다.

- [ ] RED: 순수 수명주기 테스트와 저장소 테스트를 먼저 추가한다. 승인(0→1), 취소(1→2), 재승인(2→3), 동일 요청 replay, 같은 request ID 다른 payload409, stale generation409, 동일 해시/asset 유지, 과거 호출 거절을 검증한다.

```python
def test_reapproval_does_not_revive_old_generation():
    # Pure lifecycle helper receives current state and expected_generation.
    assert next_generation(2, expected_generation=2) == 3
    with pytest.raises(ApprovalConflict):
        next_generation(3, expected_generation=1)
```

- [ ] `backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/labs/rag/generation -q`로 실패를 확인한다. helper 실제 이름은 이 task의 모듈에서 정의하고 테스트/소비자를 일치시킨다.
- [ ] 현재 상태(revision/provider key, generation, classification/status)와 append-only 이벤트(request identity/digest, action/actor/time) 테이블을 구현한다. 기존 승인/취소는 시각 보존해 세대1/2로 이관한다. revoke actor 미기록은 null이다. 구 승인 테이블의 불변 트리거를 우회하지 않는다.
- [ ] 정책→사용자/공간→asset→document→승인 상태 잠금 순서를 기존 호출 경로와 맞춘다. CAS와 멱등 이벤트는 한 트랜잭션이다. 첫 상태 생성의 경합도 직렬화한다.
- [ ] EvidenceRevision/EvidenceApproval에 승인 세대를 전달하고 codec 새 version으로 정확히 encode/decode한다. consume 직전 snapshot에 현재 세대를 재구성한다. legacy binding 거절 테스트를 넣는다.
- [ ] 관리 API의 body/DTO를 확장한다. owner/현재 문서 접근을 유지하고 오류409를 안전한 code로 응답한다. 목록은 승인된/취소된 상태와 이력을 반환한다.
- [ ] generation unit + 승인 저장 통합 테스트, mypy/ruff를 실행한다. 실제 DB 대신 기존 격리 PG fixture/runbook을 사용하며 환경 미준비면 명확히 보고한다.
- [ ] report에 migration의 cutover/rollback 위험, 파일 목록, RED/GREEN 및 정확한 API shape를 기록하고 독립 리뷰를 받는다.

## Task 2: 관리자 재승인·이력 UI

**Files:** `frontend/src/features/rag/models/CodexEvidenceApproval.tsx`, `api.ts`, `CodexSetup.test.tsx`; API 생성 산출물 `frontend/src/shared/api/schema.d.ts` 및 `backend/build/openapi.json`.
**Consumes:** Task1 DTO/body generation+request identity.
**Produces:** 동일 문서에서 새로 승인할 수 있는 명시적 UI, 접힌 식별자/이력 표시.

Task1 wire contract: POST 기존 approval 경로 body `{classification,content_sha256,expected_generation,request_id}`;
DELETE 동일 경로 body `{expected_generation,request_id}`. 응답은 둘 다204.
GET의 추가 필드는 `approval_generation:number`, `provider:'development_codex_exec'`,
`approval_history:[{action:'approve'|'revoke',generation,actor_id:null|string,occurred_at,classification}]`이다.
새 미승인 세대는0, 충돌은 `codex_evidence_approval_conflict`/409다. 공급자는 서버 소유이며 요청 body로 바꾸지 않는다.

- [ ] RED: 취소된 카드에서 다시 승인 가능, 새 동의/자료분류/대상공급자 표시, exact generation 요청, 취소 후 이력 보존, stale409 재조회와 재동의, POST성공 GET실패 구분을 테스트한다.
```tsx
expect(screen.getByRole('button', {name: '다시 승인'})).toBeDisabled();
// After explicit classification and consent, dispatch once with the loaded generation.
```
- [ ] 서버 계약으로 OpenAPI/TS 타입을 생성한다. 기존 `api:generate` 정의를 확인해 사용하고 API snapshot을 수동 조작하지 않는다.
- [ ] 승인/철회 handler는 안정된 request ID를 사용한다. 재전송은 동일 payload/ID, 새로운 행위에는 새 ID다. SHA/UUID는 details, 문서명·버전·공급자·상태는 기본 표시한다.
- [ ] 승인 응답 성공 후 목록조회 실패는 승인 실패로 바꾸지 않고 재조회 안내한다. 자동 재승인/모델 실행은 하지 않는다.
- [ ] `pnpm --dir frontend test run src/features/rag/models`, typecheck와 대상 lint 실행 후 독립 리뷰.

## Task 3: 일반 사용자 요청 저장소·API

**Files:** new generation `evidence_approval_requests.py`, `evidence_approval_request_api.py`, `backend/alembic/versions/0032_evidence_approval_requests.py`; app router registration 및 API permission inventory; unit/integration request tests.
**Consumes:** Task1 lifecycle/generation/status; 기존 문서 접근 서비스.
**Produces:** 인증 사용자 문서별 요청 생성/자기 상태 조회와 owner 처리함. 새 request는 승인과 독립 상태다.

Routes: `POST/GET /api/v1/rag/evidence-approval-requests`,
`GET /api/v1/admin/rag/evidence-approval-requests`,
`POST /api/v1/admin/rag/evidence-approval-requests/{id}/decision`.
Create body `{request_id,revision_id,provider,expected_approval_generation}`.
Decision body `{request_id,expected_state_revision,decision:'approve'|'reject',expected_approval_generation,classification?,content_sha256?}`.
Approve decision reuses Task1 session helper and records approved request atomically; reject does not change approval.
If another request or direct administration already approved the same document, resolve against that current grant only when expected generation, exact hash and explicit classification match. Do not create another approval generation/event; stale or mismatched input conflicts. Each request decision still has its own durable idempotency receipt.
Self DTO: `id,revision_id,provider,status:'pending'|'approved'|'rejected',state_revision,created_at,resolved_at`;
current approval state/generation is separate. Omit other actors' identities from self DTO.
Admin adds document/workspace names, revision number and requester display name for authorized rows only.
Self GET accepts an optional revision_id filter. When present, authorize that revision independently of whether requests exist and return a separate evidence context `{revision_id,provider,approval_status:'unapproved'|'approved'|'revoked',approval_generation}` alongside `{items,next_cursor}`. Without the filter, context is null. This supports the initial request UI without exposing admin hashes or requiring a prior request. Bind the filter into the cursor. Read context and request state consistently.
Use `get_current_user` vs `require_owner`; derive asset→document→workspace server-side and call current access guard.
Both requester and owner require current membership, personal ownership, temporary-space nonexpiry.
Cursor-based lists use signed cursor bound to actor/view/filters and deterministic created_at+id order;
default/max sizes come from existing typed library pagination settings, not new magic limits.
Register router in `backend/src/ai_workshop/main.py` and permission path contract in `backend/tests/contract/test_openapi.py`.

- [ ] RED: 자기 접근 문서만 요청, 타인 요청 미노출, 개인공간 owner 우회 금지, 중복 pending 방지, 취소/재승인과 요청 처리 CAS 경합 테스트.
- [ ] 요청자/revision/provider pending unique와 멱등 request ID로 생성한다. body에는 문서 본문이나 자유 prompt를 저장하지 않는다. 사용자 조회는 자기 요청만, 관리자는 현재 접근 가능한 문서 요청만 조회한다.
- [ ] 관리자는 Task1 명시 승인 뒤 요청을 처리 완료로 연결하거나 거절한다. 요청 처리/이벤트/상태는 원자적으로 처리한다. 권한 변동 시 재검사한다.
- [ ] Codex 요청은 자료 검토일 뿐 member 실행 권한이 없음을 DTO/문구에 명시한다. 공급자는 서버 registry의 지원 목록으로 제한한다.
- [ ] focused pytest + 통합 PG + mypy/ruff, API permission manifest 검사 후 독립 리뷰.

## Task 4: 요청 UI·통합·운영 인계

**Files:** new `frontend/src/features/rag/models/DocumentTransferApproval.tsx` 및 test, 관리자 모델 승인 처리함; `frontend/src/features/assets/DocumentBrowser.tsx`에는 선택적 ReactNode renderer slot만 추가한다. 상위 app/composition에서 RAG UI를 주입해 assets→Labs 직접 의존을 금지한다. client APIs/schema; `docs/runbooks/local-development.md`, 작업 log/WORKBOARD.
**Consumes:** Task3 API, Task1/2 관리 흐름.

- [ ] RED: 접근 가능한 문서에서 승인 필요/요청 중/거절/승인됨 표시, 중복 클릭 방지, 비로그인 차단, 개인 Codex 실행 제한 안내, stale응답 폐기 테스트.
- [ ] 기존 문서 상세 및 관리자 패널을 연결한다. 원문/폴더 탐색과 스타일을 유지하고 요청자에게 남의 감사 주체/이력을 노출하지 않는다.
- [ ] 전체 변경 영역 단위/통합/타입/린트/API 검사와 최종 독립 리뷰를 수행한다. 실제 외부 호출 대신 mock runtime을 사용한다.
- [ ] cutover 절차(서비스 writer 중지→백업확인→migration→새코드→health/저장상태 조회)를 runbook에 작성한다. 실제 적용은 사용자에게 별도 고지한다.
- [ ] WORKBOARD와 worklog에 완료와 실제 적용 여부를 분리 기록한다. 마지막 검증 전에는 RAG 준비 완료라 주장하지 않는다.
