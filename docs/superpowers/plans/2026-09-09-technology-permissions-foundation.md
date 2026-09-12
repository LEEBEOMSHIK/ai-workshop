# Technology Permissions Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Execute sequentially with independent review.

**Goal:** Master-only existing-user permission management with atomic last-master protection and a truthful management UI.
**Architecture:** Platform Identity owns general authorization state, grants and audit; composition registers RAG. This foundation does not open existing RAG/admin guards; delegated endpoint wiring is a separate next-stage plan under the same approved spec.
**Tech Stack:** Existing FastAPI/SQLAlchemy/PostgreSQL/Alembic, Next.js/React/TypeScript/CSS modules. No packages.
**Spec:** docs/superpowers/specs/2026-09-09-technology-permissions-design.md; ADR-0022.

## Global Constraints

Final status: foundation code accepted after independent final re-review; controller backend55/frontend65 tests, type/lint and API parity pass. Live migration/runtime/browser acceptance awaits explicit coordinated-cutover approval. Delegated RAG remains next stage.

- Main-only explicit user instruction; preserve dirty baseline. No commits/push/worktrees by agents.
- No live migration, user creation/grants/role changes, credential handling, external model calls or runtime restart.
- `owner` wire/storage stays; UI displays 마스터. Workspace owner terminology unchanged.
- Platform must not import Labs. Registered technology is only rag, with view/configure/execute.
- Configure/execute require view, never each other; no wildcard, groups or fake future Labs.
- Master bypass applies to technology capability only, not data/approval permissions.
- Artifact root .local-data/project-agent-work/technology-permissions-foundation; exact baseline patches, no cleanup.
- Tests are synthetic; SQL uses existing isolated_publishing_database harness, never shared/live DB writes.
- Stop before operational migration: explicit user approval is required and login/runtime readiness must not be claimed.

### Task 1: Authorization foundation and master API

Status: implemented and independently reviewed including fix1; main55-test rerun/type/lint/API parity passed.
Live migration/runtime verification remains unperformed and requires separate approval.

**Files:** platform/identity new authorization.py, authorization_models.py, authorization_repository.py,
authorization_service.py, authorization_api.py, authorization_schemas.py; identity repository/setup service minimal compatibility edits;
composition authorization_composition.py, main.py router registration; Alembic next revision after current head;
tests/unit/platform/identity/test_authorization.py, tests/integration/platform/identity/test_authorization.py and relevant setup tests.
**Interfaces:**

```python
class Capability(StrEnum):
    VIEW = "view"
    CONFIGURE = "configure"
    EXECUTE = "execute"
# Registry injected from composition, never imported from RAG by Platform.
# AuthorizationService.require_capability(actor_id: UUID, technology: str, capability: Capability) -> None
# raises AppError(403) for inactive/unauthorized, never mutates.
```

HTTP contracts (all under /api/v1; master APIs require fresh active owner inside transaction):

```text
GET /auth/access -> {is_master, revision, technologies:[{key,label,capabilities:[view|configure|execute],delegation_enabled:false}]}
GET /admin/access/technologies -> [{key:"rag",label:"RAG",delegation_enabled:false}]
GET /admin/access/users?cursor=<UUID>&limit=50 -> {items:[UserAuthority],next_cursor:UUID|null}
GET /admin/access/users/{id} -> UserAuthority
PUT /admin/access/users/{id}/technologies/{key} {expected_revision:int,capabilities:[...] } -> UserAuthority
PATCH /admin/access/users/{id}/status {expected_revision:int,is_active:bool} -> UserAuthority
PATCH /admin/access/users/{id}/role {expected_revision:int,role:"owner"|"member"} -> UserAuthority
GET /admin/access/users/{id}/audit?cursor=<positive sequence>&limit=50 -> {items:[Audit],next_cursor:int|null}
UserAuthority = {id,display_name,email,role,is_active,revision,is_last_active_master,technologies:[{key,label,capabilities,delegation_enabled:false}]}
Audit = {id:int,actor_id:UUID|null,target_user_id:UUID,event_type,technology_key:null|string,before:authority-values,after:authority-values,created_at}
```

Use extra=forbid request bodies, nonnegative required expected_revision, unique known capability values;
malformed/missing422, denied403, missing target404 after master check, revision/invariant conflict409.
Reads use limit1..200, UUID ascending user cursor and descending monotonic audit ID cursor; no unbounded hydration.
UserAuthority capabilities describe configured member grants/inherited owner capabilities even while inactive;
/auth/access describes effective active-only access. Audit records stored grants, including dormant assignments.
All authority fields identified by a revision must come from one coherent database snapshot.
No secret/password/token/config/body in audit; email only in master user directory. Cache-Control private,no-store.

- [ ] Snapshot every existing file before edits and report it; new files recorded as absent.
- [ ] RED: no-grant member denied; configure without view rejected; unknown technology denied; master legacy role allowed.
```python
with pytest.raises(AppError) as exc:
    await service.require_capability(member.id, "rag", Capability.CONFIGURE)
assert exc.value.status_code == 403  # adapt to actual AppError status attribute
```
- [ ] Add singleton authorization_state(id=1,initialized), per-user revision state (unique user FK; keep existing UserResponse stable), grants unique(user_id,key) booleans with SQL view prerequisite, and append-only audit sequence table. Keep permissions out of JWT.
- [ ] Migration on empty DB seeds initialized=false. Existing valid owner(s) seed true and revision0 for users. Existing users with no active owner or invalid role state fail migration clearly without repair. Backfill no grants. Register metadata in Alembic env.
- [ ] All authority mutation and bootstrap acquire singleton FOR UPDATE first, then actor/target sorted, fresh scalar/current queries after locks. On setup completion atomically mark initialized and audit bootstrap; status stays closed after initialized even if users corrupted. Missing singleton fails closed (migration required), never recreates through public requests.
- [ ] Under lock recheck actor active owner, target revision and active-master count. Reject last active owner's demotion/deactivation. No hard delete endpoint. Role promotion clears explicit grants with audit; demotion starts empty; editing grants on a master is rejected. No-op same-value save returns unchanged revision, no fake audit.
- [ ] Commit mutation+revision+audit atomically via existing request transaction boundary. Authorization read uses fresh DB, no cached role/grants or ORM stale reuse. Master only inherited known capabilities, inactive receives none.
- [ ] API unit tests use real router/services with isolated dependencies; SQL tests use unique disposable DB: two-master concurrent demotion, grant vs actor demotion ordering, stale revision, audit rollback, promotion clear, empty/legacy migration, setup cannot reopen, pagination and unknown key.
```python
# Two independent sessions race demoting different masters; exactly one succeeds.
results = await asyncio.gather(demote(a), demote(b), return_exceptions=True)
assert sum(not isinstance(result, Exception) for result in results) == 1
assert await active_master_count() == 1
```
- [ ] Run backend/.venv/Scripts/python.exe -m pytest on named new unit/API/isolatedSQL plus existing identity/setup tests; mypy/Ruff touched modules. Freeze task-1/report.md, manifest.md and relative review.patch.

### Task 2: Master permission management UI

Status: implemented with two reviewed fix rounds; main62-test rerun/full tsc/scoped lint passed.
Whole-foundation final review and operational activation are separate remaining gates.

**Files:** new frontend features/identity/access/{api.ts,AccessManagementPage.tsx,AccessManagement.module.css,AccessManagementPage.test.tsx};
access-local AccessManagementSections.tsx for pure confirmation/audit/presentation, keeping request state in the page;
new app/(administration)/admin/system/access/page.tsx/test; shared routing routes.ts/test; navigation areaMenus.ts,AreaNavigation.tsx/test minimal master label/menu.
**Consumes:** exact Task1 HTTP types via generated schema (main regenerates before dispatch).
**Produces:** master-only /admin/system/access; no delegated route guard change yet.

- [ ] RED user list/detail, empty members, view prerequisite, no auto-save, save/cancel and successful actual refresh assertions.
```tsx
await user.click(screen.getByRole("button", {name: "권한 저장"}));
expect(await screen.findByRole("status")).toHaveTextContent("저장했습니다");
```
- [ ] Reuse requireOwner route guard, pass true server user. Master user list paginated50; select exact user, discard/abort stale requests; do not show another user's pending changes. Role displayed as 마스터 or 일반 사용자; wire owner unchanged.
- [ ] Capabilities edit explicit per technology checkboxes. Configure/execute auto-select view only as visible form interaction; removing prerequisite with dependents rejected/explained. Dirty changes require save/cancel, show before/after confirmation before submitting grants. Distinguish 저장됨 from 적용 준비 중 because delegation_enabled=false.
- [ ] UserAuthority capabilities are configured/inherited permissions; show that inactive accounts cannot use them, and show the dormant assignments before reactivation. Never treat that admin DTO as effective session access.
- [ ] Role and active changes each explicit separate confirm dialog with effect text and expected revision; last-master unsafe controls disabled with explanation, server409 still authoritative. Masters show inherited grants, no misleading editable boxes. No create-user/invite/password UI.
- [ ] GET failure/error/retry, mutation failure, stale409 re-fetch without silently resubmitting, submitting duplicate guard. Permission403 clears privileged detail and directs to workspace; don't assert success after failed POST/refresh. Audit paged and body-free.
- [ ] Add master-only nav item 권한 관리; use existing routes registry and style. Show 마스터 beside actual owner without changing membership labels. Preserve logout, existing admin master guard, existing RAG defaults.
- [ ] Vitest access/identity/navigation/routes/server-session plus typecheck and scoped lint. No live role/grant tests or screenshots with user emails beyond current UI. Freeze task-2 report/manifest/review.patch.

### Integration and next-stage handoff (main)

- [ ] Independent task review after each task; one final foundation security review across patches, fixes through implementer.
- [ ] Generate schema with existing frontend openapi command, check parity; fresh relevant tests/static checks and document check.
- [ ] Record implemented foundation vs NOT YET delegated RAG in WORKBOARD/worklog. Recent complete <=5. User approves live migration separately; no running backend restart on old schema.
- [ ] Next plan under same spec: complete route+method/alias inventory, safe view DTO, owned configure/execute service guards, /admin child guard decomposition, current actor/membership worker gates. Do not activate foundation grants on old RAG handlers.

Coverage boundary: spec data/master management is this plan; spec delegated RAG enforcement/async stop gate is
explicit next stage. Shared admin parent remains master-only until that stage passes. No whole-permission feature completion claim.
