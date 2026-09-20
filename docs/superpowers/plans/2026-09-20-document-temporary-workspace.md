# Document temporary workspace implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for bounded implementation and independent review. Check off verified tasks only.

**Goal:** Reserve document-owned temporary workspaces before writes and retain unresolved writers/cleanup as explicit blockers.

**Architecture:** Platform Assets owns immutable claims, independent journal commits and inventory. A Windows file adapter owns exclusive allocation and handle-pinned cleanup. Parsing and preview carry exact source context and explicitly report writer completion.

**Tech Stack:** Python, SQLAlchemy async/PostgreSQL, Windows native handles, pytest, mypy, Ruff.

**Spec:** [Reviewed design](../specs/2026-09-20-document-temporary-workspace-design.md).

## Global constraints

- Windows mutation only; no automatic untracked fallback in production DI.
- Reserve commit before mkdir/write/spawn; no outer source/job locks during reservation.
- job → version → document → journal lock order; viewer omits job.
- No cleanup without confirmed writer completion and acknowledged cleaning commit.
- No path-recursive deletion, adoption of existing entries, automatic recovery, live DB changes or legacy temp cleanup.
- HTTP spool/general Job provenance remain separate followups and block whole-document completeness.
- Existing main checkout fallback from the preceding work is preserved; only task files are staged. User's explicit immediate implementation instruction supersedes another plan confirmation pause.
- Main integrates, updates WORKBOARD and commits; subagents never stage/commit/push. Temporary evidence under `.local-data/project-agent-work/temporary-workspace-20260920/`.

## Shared interfaces

`platform/assets/temporary_contracts.py` defines frozen `TemporaryBinding(store_id: str, binding_id: UUID)`,
`TemporaryContext(source: SourceIdentity, job_id: UUID | None = None)`,
`TemporaryClaim(id: UUID, context: TemporaryContext, purpose: str, binding: TemporaryBinding, generation: int, coverage: str)`.
Purposes: `parsing`, `pdf_preview`; coverage: `bounded`, `runtime_unverified`.
`TemporaryOwnershipError(code)` exposes fixed safe codes only.
States/revisions are `open/1`, `closed/2`, `cleaning/3`, `cleaned/4`.

Journal port:
```python
async def reserve(context: TemporaryContext, purpose: str,
                  binding: TemporaryBinding, *, coverage: str) -> TemporaryClaim: ...
async def transition(claim: TemporaryClaim, *, expected_state: str) -> None: ...
```

Store port:
```python
binding: TemporaryBinding
def create(claim: TemporaryClaim) -> TemporaryWorkspace: ...
def observe(claim: TemporaryClaim) -> bool: ...  # exact workspace exists
```

Workspace port has `root: Path`, `create_file(name: str) -> Path`, `discard() -> None`,
`close() -> None`. Exclusive flat file allocation with manifest identities is enough for current callers;
unregistered subdirectories/scratch block cleanup rather than being recursively adopted.
`TemporaryWorkspaceService.open(context, purpose, *, coverage) -> TemporaryLease` reserves then creates.
Lease exposes `workspace` and `finish(*, writer_confirmed: bool)`: false preserves open;
true performs three acknowledged transitions with discard/absence between cleaning/cleaned.
All exit paths release pins; journal/cleanup errors never imply success.

## Review focus

- Repeated cancellation during child termination must not release slot or delete live inputs (Task 3).
- Unexpected files or replacement between observation and delete remain untouched (Task 2).
- Concurrent source gate and worker reservations must not deadlock or admit forbidden writes (Task 1).
- Missing settings must fail before disk writes, while non-PDF original reads still work (Task 3).
- OCR opaque runtime failure/background writes must leave open rather than assume closure (Task 3).

## Task 1 — journal and inventory (DBA)

Files: new `platform/assets/temporary_{contracts,models,repository,inventory}.py`, migration `0046_document_temporary_workspaces.py`, Alembic env model import; corresponding unit and guarded integration tests under Platform Assets.

- [x] Add failing contract/state tests; demonstrate import failure before implementation.
- [x] Implement claim validation, actual source/job RESTRICT FKs, state constraints and independent reserve commit.
- [x] Register `platform_temporary / workspace / claim.id` source relation at revision 1; transitions replace current relation atomically, reject wrong state/claim.
- [x] Implement fresh repeatable-read snapshots before/after physical observation; include all versions, relation consistency, legacy/runtime coverage and changed inventory blockers.
- [x] Guard PG fixtures with explicit test environment/loopback synthetic database and test rollback/CAS/source mismatch/RESTRICT/gate races.
- [x] Run focused pytest, mypy and Ruff; hand exact evidence to main. Independent review before integration completion.

Expected assertions include:
```python
assert events == ["reserve_committed", "create"]
assert inventory.complete is False  # open, legacy, or runtime_unverified
assert relation.resource.revision == 2  # same transaction as closed
```

## Task 2 — pinned temporary file adapter (file specialist)

Files: new `infrastructure/object_store/temporary.py`, `tests/unit/infrastructure/object_store/test_temporary.py`. Reuse original adapter native patterns without changing originals.

- [x] Add failing tests for marker mismatch, nonexclusive root/file, unknown entry and exact discard.
- [x] Implement dedicated `.ai-workshop-temporary-store.json` schema_version 1 marker, binding/root identity, exclusive UUID directory and flat file allocation.
- [x] Pin ancestors/root/marker before first mutation; keep owned file identities, deny reparse/hardlink/replacement. Windows handle deletion only.
- [x] Preflight the entire flat manifest before deleting any entry. Unknown subdirectory/file blocks all deletion. Empty root deletion also uses its owned handle.
- [x] Test stale/reused claims and reopened store cannot acquire cleanup authority; prove foreign file survives error.
- [x] Run Windows pytest/mypy/Ruff and independent review. No actual cache cleanup.

Expected assertion:
```python
with pytest.raises(TemporaryOwnershipError):
    workspace.discard()
assert foreign.read_bytes() == b"synthetic foreign fixture"
```

## Task 3 — lifecycle and parser/preview wiring (main with bounded RAG delegate)

Files: new `platform/assets/temporary_service.py` and DI factory; config; parsing service/contracts/docx/pdf_ocr; ingestion domain/service/tasks; originals/originals_api; pdf_preview; unit regression tests for those paths.

- [x] Test reservation failure causes zero store operations; closed/cleaning commit errors prevent discard; cleanup failure preserves cleaning.
- [x] Implement lease service and paired settings for dedicated root/binding. Production requires configured tracking; direct test adapters use explicit fakes.
- [x] Carry source context after lifecycle begin, allocate source and OCR images through workspace capability. Remove production OS TemporaryDirectory calls.
- [x] Keep unknown OCR writer termination open; no thread migration. Fake runtime tests demonstrate bounded known file paths and fail-safe unknown runtime handling.
- [x] Pass authorized source from OriginalService; cached renderer receives no request session. Instantiate per-engine tracking service while retaining shared concurrency limiter.
- [x] Preallocate preview input/output/metadata; preserve existing terminate/kill/reap repeated cancellation behavior. Only confirmed reap can close; always preserve open on termination failure.
- [x] Test exact source forwarding, missing config, worker real process, timeout/repeated cancellation, unsafe cleanup, and final authorization recheck.

Example service event order:
```python
await lease.finish(writer_confirmed=True)
assert events == ["closed", "cleaning", "discard", "absent", "cleaned", "release"]
```

## Task 4 — independent integration verification and handoff

- [x] Independent reviewer reads final diff/spec and runs targeted tests without modifying implementation.
- [x] Main resolves blockers and runs relevant combined unit suites, isolated PG tests, mypy on changed source and Ruff on all touched Python.
- [x] Document configuration/migration prerequisites in canonical local runbook; add architectural decision before public contract implementation is finalized.
- [x] Mark plan/worklog/WORKBOARD complete with actual counts and explicit runtime/HTTP/legacy limitations; keep recent completion list at most 5.
- [x] Hand verified task files to main for staging/commit/push under existing authorization; main verifies remote parity and preserves `references/`.

Test commands use `backend/.venv/Scripts/python.exe -m pytest` from backend, with unique short `--basetemp=C:/projects/ai-workshop/.local-data/pytest-tmp/tw-*`.
Static commands: `backend/.venv/Scripts/python.exe -m mypy <changed sources>` and `-m ruff check <changed Python>` (backend working directory with `.venv/Scripts/python.exe`).

## Verification outcome

699 unit tests and 7 focused PostgreSQL/pipeline tests passed; 2 Windows symlink permission skips. Mypy18/Ruff39 passed. Independent review200 passed/1skip, no current code blockers.

Legacy `test_ingestion_task.py` separately returned 5 passed/8 failed before parsing (`artifact_binding_missing`); its artifact fixture modernization is outside this plan. ES-dependent integration was not run. Full ingestion integration is not claimed green. See [worklog](../../worklogs/2026-09-20-document-temporary-workspace.md) for evidence and the dormant purge lock-order activation prerequisite.
