# HTTP upload intake implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development with TDD and independent review. Main alone stages/commits/pushes.

**Goal:** Authenticate and reserve ownership before multipart bytes can reach disk, then link intake and original atomically.

**Architecture:** Request-only endpoints delegate to a tracked intake service. A bounded low-level multipart adapter writes a single preallocated payload; a separate journal commits ownership before allocation. Existing original upload coordination reuses planned source IDs and attaches intake provenance in its final transaction.

**Tech Stack:** Python/FastAPI, python-multipart, SQLAlchemy/PostgreSQL, Windows handle allocation, pytest/mypy/Ruff.

**Spec:** [Reviewed HTTP intake design](../specs/2026-09-20-http-upload-intake-design.md).

## Global constraints

- User explicitly requested implementation; save plan and execute without another approval pause.
- Preserve current checkout exception, unrelated `references/`, and endpoint addresses/201 schemas/conditional dispatch.
- No real DB migration, service restart, user upload, model call or old cache cleanup.
- No File/Form/request.form/high-level spool in these routes. Actual byte count and terminal suffix required.
- Workspace→membership→folder/document→intake→original locks; never wait independent transaction while holding those locks.
- Windows native identity/manifest deletion only; no path-recursive deletion/adoption/restart recovery.
- Unknown commit or writer state preserves original and intake. Cleanup failure after successful commit cannot change success response.
- Tests use explicit synthetic loopback DB with UUID isolation and short ignored basetemp `.local-data/pytest-tmp/hi-*`.

## Interfaces

DB-owned `intake_contracts.py` supplies frozen `UploadIntakeClaim(id, source, user_id, new_document, binding, generation=None, revision=1, state='open', original_attempt_id=None, attached=False)`.
`source: SourceIdentity` is planned identity until attachment, `binding: TemporaryBinding`. Claim validates all values and state combinations.

`UploadIntakeJournal(sessions)`:
```python
async def reserve(*, user_id: UUID, workspace_id: UUID | None,
                  document_id: UUID | None, binding: TemporaryBinding) -> UploadIntakeClaim: ...
async def reserve_original(intake: UploadIntakeClaim, original: UploadClaim) -> UploadIntakeClaim: ...
async def prepare_attachment(session: AsyncSession, intake: UploadIntakeClaim,
                             original: UploadClaim) -> None: ...
async def attach(session: AsyncSession, intake: UploadIntakeClaim,
                 original: UploadClaim) -> UploadIntakeClaim: ...
async def transition(intake: UploadIntakeClaim, *, expected_state: str) -> UploadIntakeClaim: ...
```
`reserve_original` commits original reservation + intake link, returns revision2. `prepare_attachment` precedes original journal prepare to retain lock order. `attach` follows original attach in SAME transaction; result revision3 is acknowledged to live lease only AFTER final commit. Failed/unknown commit never refreshes a lease by requery.

`TrackedIntakeStore(root, binding)` exposes `.binding`, `.create(claim)->TemporaryWorkspace`, `.observe(claim)->bool`. Existing workspace `.root/create_file/discard/close` remains. Extract physical `(token,binding)` allocation without faking a TemporaryClaim.

Parser adapter:
```python
async def parse_upload(stream: AsyncIterator[bytes], content_type: str,
                       destination: BinaryIO, *, allow_folder: bool,
                       policy: UploadMultipartPolicy = DEFAULT_POLICY) -> ParsedUpload: ...
# ParsedUpload: filename:str, media_type:str, folder_id:UUID|None, size:int
```
`upload_policy.py` owns default 50MiB payload plus64KiB envelope,64KiB slices,256 boundary,8 headers/4224bytes,128bytes folder field.

Main's `UploadIntakeLease` holds mutable latest acknowledged `.claim`, `.workspace`, `.journal` and uncertainty flag. Its `reserve_original/prepare_attachment/attach` methods delegate journal contracts; `acknowledge(claim)` runs after final commit. `finish()` closes only confirmed local reader/writer after journal closed→cleaning→physical absent→cleaned, retains safe failure and releases handles. It never overwrites primary upload success/failure.

## Review focus

- Same-slice and split-slice epilogue cannot hide after on_end (Task2).
- Auth rejection and commit uncertainty consume zero request body (Tasks1/4).
- Concurrent/replayed intake cannot publish a second original or steal source IDs (Task1).
- Cancellation cannot delete an active local writer/reader; no detached thread writers (Task4).
- Successful original commit plus cleanup failure still dispatches exactly once and returns201 (Task4).

## Task1 — DB ownership and inventory

Files: new `platform/assets/intake_{contracts,models,repository,inventory}.py`, migration0047, Alembic env; focused unit/integration tests. Any necessary original reservation unique-constraint/model changes remain DBA-owned.

- [x] Run failing contract tests, then implement immutable planned source/snapshot validation.
- [x] Independent reserve authorizes exact user/workspace/document and records existing-document RESTRICT pin without FK to planned version.
- [x] Reserve original + intake link/CAS atomically; named composite source FK and unique original attempt; actual source pins and attachment/provenance in final transaction.
- [x] Transition increments snapshot/current relation together. Stale snapshot, wrong source/user/generation and changed transaction capability reject.
- [x] Inventory includes all document claims and authorized unattached workspace claims, relations/originals/actual pins, snapshot changes, physical presence and legacy blockers without locators.
- [x] Run guarded isolated PG migration/CAS/RESTRICT/concurrency/commit rollback tests, mypy/Ruff; independent review.

Test invariant:
```python
linked = await journal.reserve_original(intake, original)
assert linked.source == original.source and linked.revision == 2
```

## Task2 — bounded multipart adapter

Files: new `infrastructure/document_formats/upload_multipart.py`, `platform/assets/upload_policy.py`, corresponding unit tests.

- [x] Red tests for both field orders, byte-by-byte splits, duplicate parts, missing/truncated EOF and same/split epilogue.
- [x] Low-level callbacks only; fixed payload destination supplied by caller; external counters and bounded header/field accumulation, no tempfile allocation.
- [x] Validate metadata safely, reject unknown encodings/dispositions/headers, allow normal final CRLF only; enforce actual stream EOF and exactly one nonempty file.
- [x] Verify all configured boundaries and that secrets/file names/body never appear in exceptions; run unit/mypy/Ruff and independent review.

Expected invariant:
```python
with pytest.raises(AppError):
    await parse_upload(stream_with_extra_bytes, content_type, sink, allow_folder=True)
```

## Task3 — shared native allocation

Files: `infrastructure/object_store/temporary.py`, new `intake.py`, shared physical allocation contract if needed; native store tests.

- [x] Red tests for intake planned source allocation without actual source fake and wrong binding/stale snapshot.
- [x] Extract UUID+binding physical allocator while preserving TemporaryClaim wrapper checks and pins.
- [x] Add tracked intake wrapper, exact manifest/identity cleanup and observation. No path/rmtree cleanup.
- [x] Run temporary/original/intake native tests, mypy/Ruff and independent review before final integration.

## Task4 — HTTP lifecycle/coordinator/API integration (main)

Files: new `platform/assets/intake_service.py`; `tracked_uploads.py`, `api.py`, `service.py`; route/coordinator/lifecycle tests; docs/ADR/runbook.

- [x] Test reserve-before-stream/create and unknown commits, then implement lease/service with safe fixed failure codes.
- [x] Coordinator `upload_intake` consumes trusted live intake and parsed metadata; original reservation reuses source/generation, prepares intake before original and acknowledges attachment only after commit.
- [x] Replace File/Form with Request; keep dependencies and explicit multipart OpenAPI; callbacks use existing result and conditional background dispatch.
- [x] Test unauthenticated body untouched, forbidden workspace, folder-after-file, malformed/truncated body, unknown commit preservation, cleanup failure retains201/dispatch and old original coordinator behavior.
- [x] Real Windows+isolated PG+ASGI/pipeline tests; combine relevant unit regression, type/lint; independent whole-change review.

## Task5 — verification and handoff

- [x] Record exact counts/limitations in worklog; mark WORKBOARD and maintain recent5.
- [x] Keep RAG readiness limitations explicit; no claim of real search/generation smoke or full purge completion.
- [x] Check task fixture DB absence and stop only its exact container; preserve other services.
- [x] Hand verified task files to main for commit/push and remote parity check under existing user authorization.

Commands: backend `.venv/Scripts/python.exe -m pytest <owned tests> -q --basetemp=C:/projects/ai-workshop/.local-data/pytest-tmp/hi-<unique>`; `-m mypy <changed sources>`; `-m ruff check <changed Python>`.

Execution evidence: [implementation worklog](../../worklogs/2026-09-20-http-upload-intake.md). All code tasks and independent review complete. Main performs the authorized Git handoff and verifies remote parity.
