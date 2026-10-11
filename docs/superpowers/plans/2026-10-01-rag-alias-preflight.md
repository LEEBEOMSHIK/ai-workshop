# RAG alias preflight implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Check supported recovery prerequisites before new maintenance acquisition, without mutation, and reduce repeated executable checks within each fresh HOST observation.

**Architecture:** Keep the existing v1 termination proof and repository CAS unchanged. Native preflight uses a positive read-only command capability; the CLI invokes it before genuinely new open legacy/dispatching freezes. Each HOST invocation holds file handles and shares binary observations only within that invocation.

**Tech Stack:** Python 3.13, argparse, existing recovery service, fixed Windows PowerShell 7.6.6, pytest/Ruff/mypy.

**Spec:** [2026-10-01-rag-alias-preflight-design.md](../specs/2026-10-01-rag-alias-preflight-design.md), independently approved in the task's ignored `spec-review.md`.

## Global constraints

- Work in the existing user-authorized workspace; preserve all prior uncommitted changes. No additional application environment, account, DB or worktree.
- Product scope is exactly the native module, CLI and their two unit test files. No DB schema, core service, proof v1, permissions, model or frontend changes.
- `preflight=ready|blocked|not_required`, `termination_proven=false`, `parity=not_run`; blocked returns a nonzero CLI status and safe diagnostic only.
- Fixed original settings, active-owner, binding, snapshot, controller, endpoint, unknown-runtime/WSL/TCP guards remain.
- Preflight never STOP/START/freeze/close/release/alias/parity. It is advisory, not an atomic OS snapshot or proof.
- Call-local dedup only; handle deny-write/delete protection, no cache across observations, no relaxed allowlist, 45-second HOST timeout unchanged.
- Root alone original runtime observations, documentation, integration and Git decisions. No commit/push, source cleanup or cache deletion in this task.
- Preserve current exact open/frozen revision 1 and receipt count 0. No actual server drain/recovery/release/parity for this task.

## Review focus

1. Unknown commit/readback and foreign claim must stop acquisition before OS work, never invent authority.
2. Exact historical receipt is not current frozen ownership; replay bypass must retain repository semantics.
3. Running original app writers can legitimately block preflight; no exception introduced to obtain ready.
4. Reparse/path substitution, share-lock failure or signature/hash failure cannot yield an unlocked or mixed binary observation.
5. Every process retains its own lifetime/modules, every new HOST checks fresh, and all handles close on error.

## Task 1: Native observation and CLI preflight (one coupled deliverable)

**Modify:**

- `backend/src/ai_workshop/labs/rag/indexing/alias_recovery_local_native.py`: read-only capability, native preflight and HOST binary collection.
- `backend/src/ai_workshop/labs/rag/indexing/alias_recovery_cli.py`: parser/output and new-freeze prerequisite orchestration.
- `backend/tests/unit/labs/rag/indexing/test_alias_recovery_local_native.py`: capability and actual helper behavior with public synthetic fixtures.
- `backend/tests/unit/labs/rag/indexing/test_alias_recovery_cli.py`: CLI failure/replay/race scenarios.

**Interfaces:**

- Produce `async OriginalWindowsBackend.preflight(snapshot: AliasOperationSnapshot) -> None`, matching the existing async native adapter and command executor.
- CLI consumes a typed preflight port through injection; missing prerequisite capability must fail closed for new legacy/dispatching acquisitions. Production `_run` wires the canonical backend. Existing service/proof contracts unchanged.
- `execute` preserves existing two-argument usage for commands that require no native check; any optional injection must not permit required new-freeze checks to be omitted.
- `preflight --operation UUID --actor UUID` needs no request. Reserved snapshot reports `not_required` with no HOST. Other snapshots pass through the read-only backend.
- New freeze previews and checks given digest, reads back exact owner/snapshot/current gate before native I/O. Required preflight runs outside the repository transaction; definitive existing freeze CAS still arbitrates changes afterward.
- Reserved, closed, exact frozen and exact receipt replays require no HOST; foreign claims/digests and uncertain reads remain errors. `recover` still collects independently.

- [x] Write named failing tests for blocked/ready/non-required CLI output (`termination_proven is False`, `parity == 'not_run'`) and mutation count zero; native executor rejects STOP, START and unknown command before delegation.
- [x] Write failing freeze tests: blocked preflight means freeze count zero; successful preflight followed by changed snapshot is rejected by existing CAS; exact replay/reserved/closed avoids native work; digest/claim/readback failures stop before native work. Assert actual returned statuses and errors, not only mock call counts.
- [x] Write helper behavior tests using synthetic executable files and stub process/network observations: shared path checks once, separate paths independently, next invocation checks again; error cleanup; writes/replacements and ambiguous paths fail safely. Execute the helper logic rather than testing script tokens. No actual host enumeration/network in unit tests.
- [x] Run each RED group before product changes; record expected missing behavior/failure counts in `implementation-report.md` under the new task directory.
- [x] Implement minimal native/CLI behavior; retain existing safety checks and cleanup through `finally`. Bind signature/hash to the protected file identity. No broad restructuring.
- [x] Run both unit files and indexing unit suite using a fresh task-local basetemp. Run Ruff on four files and mypy on two source modules (`--cache-dir=nul`). Record commands/results and file hashes. Report any inherited warning/failure explicitly.
- [x] Self-review scope against spec and hand off four before/after diffs, SHA manifest, RED/GREEN evidence, limitations and immutable baseline to independent reviewer. Do not stage/commit.

## Task 2: Independent review, original read-only verification and records

**Root-owned documents:** this plan/spec, `WORKBOARD.md`, focused worklog and ISSUE-00013 exact DB document versions/history.

- [x] Independent task reviewer checks Task 1 spec and quality, especially the five focus cases. Owner fixes only actionable findings; scoped re-review after any fix.
- [x] Root reruns required fresh checks and obtains one final independent integration review of this four-file delta. Prior alias package is a preserved baseline, not another implementation task.
- [x] Capture before-state original gate/request/operation/receipt, ES generation, protected data and both health endpoints to exclusive artifacts. Execute only original `preflight` under the fixed supported PowerShell shell, with no concurrent local commands during HOST observation.
- [x] Capture after-state and compare; `blocked` is a truthful valid outcome, never recovery success. Independent verifier inspects state and freshly verifies health/protection without modifying the implementation.
- [x] Record implemented behavior, test counts, actual safe blocker, zero state changes and remaining real termination boundary in worklog/WORKBOARD. Keep ISSUE-00013 open; add exact new spec/worklog versions and dated history through existing admin UI. Verify saved DB body/source/links and screenshot.
- [x] Mark task complete only for preflight/dedup feature. Report existing legacy recovery remains blocked and servers/data preserved. No merge/commit/push or cleanup.

## Root self-review

| Item | Check |
|---|---|
| Task 1 self-consistency | Four owned files; typed native interface matches CLI wiring; failure tests enforce read-only capability and freshness. |
| Task 2 self-consistency | No code ownership; actual preflight only and truthful blocked outcome; original state preserved. |
| Task 1 → Task 2 | CLI safe metadata and reviewed helpers feed original observation; preflight is never supplied as proof. |
| Spec coverage | CLI, replay, CAS, fresh handles, safety checks, tests and original issue records covered; cancellation and endpoint/auth migration expressly excluded. |

Ruling: reuse the established implementation owner and independent reviewers for this single coupled change, in the existing ignored project task directory. This follows project AGENTS ownership/preservation requirements and avoids duplicate environments or redispatching the completed alias package.
