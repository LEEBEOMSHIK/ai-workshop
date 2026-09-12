# Codex 승인 저장소 Implementation Plan

**Goal:** 기존 CodexExecutionGate를 실제 PostgreSQL 승인·현재 상태 조회·독립 영속 소비에 연결한다.
**Architecture:** RAG generation 내부에 승인 ORM/codec/source를 추가한다. API·실제 CLI 연결은 차단 유지.
**Tech Stack:** SQLAlchemy async, PostgreSQL, Alembic, pytest. 새 라이브러리 없음.
**Spec:** `docs/superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md` §4·6·10·11.

## Global Constraints

- main-only. 기존 dirty 변경 보존. commit/push/worktree 생성 금지.
- 실제 사용자 DB migration·승인 등록·문서·정책 변경, CLI/모델/인증 호출 금지.
- 테스트는 기존 `tests/integration/publishing_support.py::isolated_publishing_database`의
  이름/current_database 검증을 사용한다. 메인이 새 테스트를 읽은 뒤 실행한다.
- 질문·본문·이력·생성 초안·비밀값은 DB에 저장하지 않는다. digest와 최소 식별자만 저장한다.
- 클라이언트 snapshot은 신뢰하지 않는다. 현재 상태를 실제 테이블/신뢰 지침 registry에서 재조회한다.
- 기존 Codex 등록/runtime/readiness 차단 유지. 이 단계는 서버 내부 저장소이며 신규 UI/API 없음.

## Task 1: PostgreSQL source + migration + tests

Create:
- `backend/src/ai_workshop/labs/rag/generation/codex_approval_models.py`
- `backend/src/ai_workshop/labs/rag/generation/codex_approval_codec.py`
- `backend/src/ai_workshop/labs/rag/generation/codex_approval_repository.py`
- `backend/alembic/versions/0027_codex_call_approvals.py`
- `backend/tests/unit/labs/rag/generation/test_codex_approval_codec.py`
- `backend/tests/integration/test_codex_approval_storage.py`
Modify only `backend/alembic/env.py` to import new metadata (preserve existing dirty file).
Existing `codex_authorization.py` gate is consumed unchanged unless a concrete incompatibility is reported first.

### Schema

1. `rag_codex_call_approvals`: id UUID PK; actor_id/approved_by FK users; request_id UUID;
   configuration_version_id/deployment_version_id/generation_profile_id FKs;
   operation/stage closed CHECK; binding JSONB (strict codec for all CodexCallIntent fields);
   approved_payload_sha256 lowercase64hex; issued_at/expires_at timestamptz expires>issued;
   input_classification public/synthetic CHECK (explicit issuer attestation of entire payload, not inferred);
   consented default false; revoked_at nullable. Binding+identity+digest immutable after insert;
   revocation monotonic, no unrevoking. Header/JSON duplicates must agree on repository read/write.
2. `rag_codex_evidence_approvals`: revision_id PK FK asset_versions RESTRICT; content_sha256 lowerhex;
   classification public/synthetic CHECK only; approved_by FK users; approved_at; revoked_at.
   Approval fields immutable, revoke monotonic. No raw source content or original filenames.
   This minimal stage does not provide reapproval UI or overwrite revoked classification.
3. `rag_codex_call_consumptions`: approval_id PK UUID WITHOUT FK; request_id/stage/consumed_at.
   Append-only with UPDATE/DELETE rejection. Independent transaction must never access locked parents.
   No FK is deliberate: snapshot holds parent lock while separate consume transaction commits.

Migration down_revision0026_codex_runner_reference. Only new tables/triggers/constraints; existing data untouched.
Downgrade refuses while ANY of these tables has rows, instead of deleting approvals or replay protection.
ORM and migration constraints match; import new metadata in env.py.

### Codec

Use strict Pydantic DTO or explicit typed parser, extra fields forbidden, closed enums, UUID,
SHA256 shape, safe runner name, nonempty model/disclosure, duplicate scope/revisions rejected.
Explicit JSON version field to reject unsupported encoding. Serializes intent only; not arbitrary dictionaries.
Arrays normalized to a documented canonical UUID ordering, used consistently on issue/load/current reconstruction.
Tests mutate nested binding fields, unknown fields, incorrect types, bool/int coercion, duplicate IDs and assert rejection.

### Trusted internal issuance / revocation

Repository methods may register a server-owned exact `CodexCallIntent`, payload digest and TTL/consent;
they must not be exposed as unchecked API. On issuance verify current active owner and exact technical/policy/space/revision
state with the same loader used on execution. Evidence classification approval is a distinct explicit owner operation;
validate current owner, exact READY AssetVersion SHA256 and document workspace membership before insert.
No method automatically labels arbitrary documents public/synthetic. Registration requires explicit classification.
Revoke only matching owner or validated current owner, without deleting rows or consumed ledger.
Issuance checks must not consume approval. Errors stable/safe, no raw SQL/parameters in returned errors.

### Source contract

`SqlAlchemyCodexAuthorizationSource` implements existing locked_snapshot/consume.
Fresh snapshot session per context, ContextVar/per-call state (no shared mutable active-session slot).
Dedicated consumption session factory/engine pool distinct from snapshot pool to avoid pool-exhaustion deadlock;
validate factory bind identity or make independent consumption engine explicit. No new engine per consume.
Both snapshot and consume transactions enforce READ COMMITTED with driver autocommit disabled before their
first SQL, regardless of caller engine defaults; policy snapshots must not remain stale and locks must persist.

Locks: Installation singleton FOR SHARE via existing repository; actor row FOR SHARE; sorted selected Workspace
and membership rows FOR SHARE; call approval FOR UPDATE; evidence approvals/AssetVersion then owning Document
rows FOR SHARE in consistent UUID order. Exact asset→document order follows existing project rule.
Hold all through gate callback. Revocation update waits for existing locks or is seen before execution.
Avoid policy/actor writes from callback; deployment technical values remain immutable.

Load approval by intent.approval_id; decode stored binding independently, compare relational columns and stored binding.
Independently read current actor (not password_hash), configuration visibility and configured spaces, generation profile
and binding, deployment kind/development flags/runner/model and current prompt/schema digests, exact external config approval,
current Installation+every selected Workspace policy, membership/temporary expiry, evidence revision→document→workspace,
READY, matching nonrevoked explicit public/synthetic approval/hash. SEARCH evidence requires active version;
EVALUATION may bind an explicitly approved historical READY revision. Do not confuse Asset with RAG Projection state.
Reconstruct current_intent from stored request/stage/operation identifiers and fresh technical/policy values.
Stored binding must equal reconstructed values AND requested intent. Never silently replace stale approval values.
Current config scope must include all selected spaces; parent external configuration approval and current outbound policies
cover full configured scope as existing search does. Return selected-subset policy snapshots to gate without dropping forbidden
configured spaces. Personal spaces also require created_by==actor, even when membership exists.
Clamp effective snapshot.expires_at to earliest selected temporary workspace expiry so clock passage cannot bypass it.
Owner never bypasses workspace membership. Missing/forbidden/mixed spaces fail whole request.
Current instruction digests come from existing build_codex_prompt/resolve_generation_profile on trusted empty synthetic request,
not by copying request hashes. No embeddings/model runtime loaded for this lookup.

`consume` only inside active locked context for exact approval/request/stage. Separate pool transaction INSERT
ON CONFLICT(approval_id) DO NOTHING RETURNING id, commit before True. Consumed ledger remains after callback error/cancel.
Same approval across instances/concurrent sessions runs callback at most once. No nonpersistent fallback.
Use bounded lock timeout from constructor/settings parameter; no indefinite test waits.

### TDD and integration proof

- [x] Codec behavior tests RED→GREEN; test application checks rather than framework existence.
- [x] Migration0026→0027 preserves old rows; downgrade empty succeeds; nonempty refuses without loss.
- [x] Seed synthetic owner, workspaces/membership, model+Codex deployment+profile/config and exact policies/approvals.
  Reuse existing fixture builders where appropriate. Never real user records.
- [x] Real source+gate success; another source instance/restart cannot replay. Concurrent separate connections one callback.
- [x] Callback failure/cancel leaves consumed row committed. Source context rollback cannot erase ledger.
- [x] Missing/malformed approval, member/inactive actor, denied policy, wrong/stale config/model/digests,
  revoked/expired approval, removed membership, forbidden mixed space, inactive revision/hash mismatch/private approval deny before callback.
- [x] Revocation vs execution serialization test with bounded async events; prove no deadlock for separate consume.
- [x] Main runs isolated DB tests after inspection. Implementer runs codec unit/mypy/scopedRuff, no realDB calls.

## Task 2: Main verification and handoff

Independent security/DB review of Task1, fixes and scoped re-review. Main runs full unit/contract and type/lint.
Record tested DB names and exact helper cleanup, no user DB application. Update WORKBOARD/worklog with actual readiness.
Next: runner registry/real-time event cancellation and search/evaluation/explicit connection request wiring; actual model identity
still required before declaring full RAG user testing available.
