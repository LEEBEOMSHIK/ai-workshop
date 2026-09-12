# Codex request workspace Implementation Plan

> Agentic workers: use superpowers:subagent-driven-development, TDD and independent security review.

**Goal:** Join the existing command assembler and stream adapter through an owned per-request directory with explicit cleanup evidence.
**Architecture:** A synchronous internal executor resolves a named runner, validates the command before writes, creates one random direct-child directory, writes only the trusted output schema, rechecks integrity, invokes an explicitly supplied stream adapter and cleans up only its known owned files. No application runtime activation or launch authorization is added.
**Tech Stack:** Python 3.13 stdlib pathlib/tempfile/os/stat/hashlib, existing RAG contracts, pytest; no new dependencies.
**Spec:** `docs/superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md` sections 3, 6, 9–11.

## Global Constraints

- main only; no worktree/staging/commit/push. Preserve unrelated dirty changes.
- No actual CLI/help/version/auth/model/network/user DB/.env/UI/server operations in implementation/tests.
- Tests use synthetic local files and an explicit fake stream dependency. No installed Codex path or private data.
- No actual runner setting or runtime readiness activation. Authorization/current settings evidence/concurrency are NOT provided by this internal adapter; it must eventually run inside that coordinator.
- A runner configuration fingerprint is an integrity comparison value, not proof it was approved. Do not bypass or alter CodexExecutionGate/approval storage or command/runtime resolvers.
- Only a newly created owned child and its fixed schema file can be removed. No recursive deletion, root removal, glob, user file cleanup or following reparse points. No request payload/developer text/raw events written to disk or safe errors.
- Unknown files, replacement/reparse identity, or unverified process termination cause cleanup failure with response discarded; retain the directory for scoped diagnosis. Do not claim every hostile race is eliminated.

## Task 1: Workspace execution lifecycle

Create only:
- `backend/src/ai_workshop/labs/rag/generation/codex_workspace.py`
- `backend/tests/unit/labs/rag/generation/test_codex_workspace.py`

Consume existing CodexRunnerRegistry.resolve, ResolvedCodexRunner, build_codex_command,
CodexCallIntent, CodexExecutionPayload, CodexStreamRunner.run, CodexStreamResult,
ProcessFailure, threading.Event. Do not edit those modules.

```python
class CodexWorkspaceStream(Protocol):
    def run(self, request: ProcessRequest, event_limits: CodexEventLimits,
            cancellation: threading.Event | None = None) -> CodexStreamResult: ...

@dataclass(frozen=True, slots=True)
class CodexWorkspaceResult:
    stream: CodexStreamResult | None = field(default=None, repr=False)
    failure: str | None = None  # fixed local codes only
    workspace_id: str | None = None  # generated random basename, no user path/input
    cleanup_verified: bool = True

class CodexWorkspaceExecutor:
    def __init__(self, *, registry: CodexRunnerRegistry,
                 stream_runner: CodexWorkspaceStream) -> None: ...
    def run(self, *, intent: CodexCallIntent, payload: CodexExecutionPayload,
            expected_configuration_sha256: str, timeout_seconds: float,
            cancellation: threading.Event | None = None) -> CodexWorkspaceResult: ...
```

No default live stream runner. Result repr must never include paths/payload/events. Pure configuration errors return stable bounded failure codes (no exception text/context). New module is internal primitive, not an authorized public API. Source comments must state this boundary prominently.

- [x] Step 1: Write a failing success-path test before implementation. Use a real registry with synthetic.exe bytes/hash, dedicated existing requests root and separate protected repo path. Use the actual trusted generation/contextualization schema constants serialized exactly as build_codex_prompt does. A fake stream inspects actual fixed schema bytes and cwd at invocation and returns a valid CodexStreamResult. Verify cwd direct-child/random, no payload/developer file, immutable original request bytes, callback once, root and sentinel sibling preserved, request directory gone before result returned.

```python
result = executor.run(intent=intent, payload=payload,
    expected_configuration_sha256=resolved.configuration_sha256, timeout_seconds=10.0)
assert result.failure is None
assert result.cleanup_verified
assert result.stream is successful_stream_result
assert not observed_cwd.exists()
assert sentinel.read_bytes() == b"synthetic sibling"
```

- [x] Step 2: Implement preparation. Resolve runner and compare supplied exact lowercase64 fingerprint; validate input/command using a random `request-` + uuid4().hex direct-child path BEFORE creating anything. Unsupported command/payload/model/timeout must not create a directory. Only accept output schema bytes exactly matching the existing canonical trusted schema for actual intent stage (CONTEXTUALIZATION_SCHEMA_V1 or GROUNDED_GENERATION_SCHEMA_V2); hash matching an arbitrary caller-supplied schema is insufficient for writing trusted schema. Do not write stdin or developer instructions.

Capture existing parent/ancestor identities and reject all symlink/junction/reparse components. Create child exclusively (`mkdir(exist_ok=False)`) and verify its parent/identity again; never reuse or remove a colliding existing child. Create fixed `output-schema.json` exclusively with binary `xb`, handle short/failed writes, close before running, verify regular/non-reparse identity and exact bounded bytes/hash. Parent must already exist and was validated by registry. No permission changes or schema copies elsewhere.

- [x] Step 3: Re-resolve the named registry immediately before invocation and require the same expected configuration fingerprint; this also rechecks executable bytes. Revalidate root/ancestors/child/schema ownership and schema bytes. Cancellation set before invocation returns a fixed cancellation failure without calling stream and cleans any owned allocation. Pass existing ProcessRequest, runner event limits and cancellation unchanged to the supplied stream dependency exactly once. Do not start threads/background tasks or apply retries/default runner/model. Current settings proof and durable authorization binding remain outside this primitive.

- [x] Step 4: Finalize all normal/failed outcomes. On a returned stream result, delete only after explicit `cleanup_verified is True` and actual integer `active_processes_after_cleanup == 0`; do not treat None/False-as-zero as proof. If stream raises or returns malformed/unknown termination evidence, preserve owned directory, discard stream/events, report fixed failure and cleanup_verified=False. Handle BaseException without deleting a directory potentially in use; propagate cancellation/control-flow exceptions after safe finalization of known pre-launch allocations. Ordinary error text must never escape.

When termination is proven, recheck full owned path/ancestor/identity chain and fixed schema identity/content before deleting. If content/identity changed, extra entry exists, schema disappeared, path is reparse, or any unlink/rmdir fails, return cleanup failure, no stream/events. Do NOT recurse into or delete unexpected content. Use bounded directory inspection (stop as soon as unexpected entry found; no unbounded recursive walk). For a write/preparation failure, remove only the exclusively created file whose ownership was established and the empty owned directory; if ownership uncertain, preserve and report cleanup failure. Verify final child absence and root/sibling preservation; failure must dominate a previously valid response.

Path checks plus before/after identity comparisons narrow races, not provide a race-free OS sandbox. Retention is a visible failure requiring exact-path review, not a successful cleanup. The parent adapter eventually owns approval/concurrency/thread cancellation integration and records only the random workspace_id plus safe failure for retention diagnosis.

- [x] Step 5: Add RED/green failure cases with real synthetic filesystem where possible: mismatched fingerprint/invalid command/untrusted schema => no writes/callback; registry changed between preparation and launch => no callback and own files removed; schema write error => safe cleanup or honest retained failure; process nonzero/timeout/cancel/event failure with terminated process => cleanup; unverified cleanup/raised stream => retained/no events; valid stream plus unknown file/schema change/directory replacement/reparse/delete failure => no response and no outside/sibling removal. Test concurrent calls have distinct children and one cleanup never removes the other's files. Test pre-cancelled and mid-call cooperative cancellation, safe repr/errors and no ambient changes. Simulated reparse/identity/delete errors must be labeled, not reported as actual Windows links. Keep tests bounded, no actual processes needed here; the stream layer's existing real Windows lifecycle tests remain regression coverage.

- [x] Step 6: Scoped tests/mypy/Ruff, self-review, freeze/report. Main runs full unit/contract and independent security review. Report TDD evidence, exact commands/results, real vs simulated checks, retained synthetic fixtures and remaining risks to `.local-data/project-agent-work/codex-request-workspace/task-1-report.md`.

```powershell
# from backend
.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/generation/test_codex_workspace.py -q --tb=short
.venv/Scripts/python.exe -m mypy src/ai_workshop/labs/rag/generation/codex_workspace.py
.venv/Scripts/python.exe -m ruff check src/ai_workshop/labs/rag/generation/codex_workspace.py tests/unit/labs/rag/generation/test_codex_workspace.py
```

## Handoff

Next is durable approval fingerprint binding, concurrency and actual runtime/API integration. This task performs no actual CLI/model call; successful synthetic execution does not establish effective CLI restrictions, model identity or full RAG readiness. Existing user data, services and cache/worktree artifacts remain untouched.
