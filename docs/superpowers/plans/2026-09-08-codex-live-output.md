# Codex 실시간 출력 검사 Implementation Plan

> Agentic workers: use superpowers:subagent-driven-development; TDD and independent review required.

**Goal:** Connect the existing bounded Windows process lifecycle to incremental Codex JSONL validation, stopping an invalid stream before normal process completion.
**Architecture:** The generic process primitive accepts a trusted synchronous stdout observer and optional non-retention. A RAG-local stream adapter owns a fresh receiver per call and returns validated events only after process exit and verified cleanup.
**Tech Stack:** Existing Python/ctypes/threading/pytest; no new library.
**Spec:** `docs/superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md` §6, §9, §10.

## Global Constraints

- main-only as explicitly requested; preserve all unrelated dirty changes. No commits, pushes, worktrees.
- No actual CLI/model/auth calls, user DB changes, server restart, external transfer or UI changes.
- Existing Codex registration/runtime/readiness blocks and model identity requirement remain unchanged.
- Synthetic local Python children only; use existing pytest tmp_path, exact request-owned cleanup. Do not delete other processes/files/caches.
- Raw stdout/stderr, final draft and exception details must not appear in adapter failure results, repr or logs.
- Event detection cannot reverse already executed tool effects; this is not an OS sandbox or authorization substitute.
- Main owns docs/WORKBOARD and independent verification; implementer owns only the files in Task 1.

## Task 1: Incremental process observer and Codex stream adapter

Files:
- Modify `backend/src/ai_workshop/labs/rag/generation/windows_process.py`.
- Create `backend/src/ai_workshop/labs/rag/generation/codex_stream.py`.
- Modify `backend/tests/unit/labs/rag/generation/test_windows_process.py`.
- Create `backend/tests/unit/labs/rag/generation/test_codex_stream.py`.
- Existing `codex_events.py` and native Win32 lifecycle stay unchanged unless a concrete incompatibility is reported first.

Interfaces:

```python
class WindowsProcessRunner:
    def run(self, request: ProcessRequest,
            cancellation: threading.Event | None = None, *,
            stdout_observer: Callable[[bytes], bool] | None = None,
            capture_output: bool = True) -> ProcessResult: ...
# ProcessFailure.OUTPUT_REJECTED = "output_rejected"

@dataclass(frozen=True)
class CodexStreamResult:
    events: CodexEventResult | None = field(default=None, repr=False)
    process_failure: ProcessFailure | None = None
    event_failure: str | None = None  # only receiver's own bounded stable error codes
    cleanup_verified: bool = True
    active_processes_after_cleanup: int | None = None

class CodexStreamRunner:
    def __init__(self, process_runner: WindowsProcessRunner | None = None) -> None: ...
    def run(self, request: ProcessRequest, event_limits: CodexEventLimits,
            cancellation: threading.Event | None = None) -> CodexStreamResult: ...
```

- [x] Step 1 — Add RED real-process tests for observer rejection/exception and non-retention before editing production.

```python
# Existing synthetic request builder: sys.executable -I -c; tmp_path; explicit environment.
seen = []
def reject(chunk: bytes) -> bool:
    seen.append(chunk)
    return False
result = WindowsProcessRunner().run(request, stdout_observer=reject, capture_output=False)
assert result.failure is ProcessFailure.OUTPUT_REJECTED
assert result.stdout == result.stderr == b""
assert result.cleanup_verified and result.active_processes_after_cleanup == 0
assert seen
```

Use a child that prints/flushes then sleeps longer than its configured timeout; rejection must win over TIMEOUT. Add descendant ownership check using existing Job Object count, not blanket process killing. Observer exception, invalid return and capture_output=False stdout/stderr overflow must fail safely; existing capture defaults stay backward compatible.

- [x] Step 2 — Implement the generic observer at each bounded stdout read, including post-exit draining. Only bytes under the existing stdout cap reach the observer. Track byte counts independently of captured buffers so disabling retention cannot bypass caps. Once any failure is detected, do not invoke observers again. False/non-bool/Exception rejects stream, discards callback exception details, stops normal loop and runs existing job cleanup. Observer is trusted bounded in-process synchronous validation, not arbitrary user callback. No extra thread or background task. Validate new arguments before launch; invalid callable/capture flag never starts a process. Preserve cleanup failure precedence and all existing limits.

- [x] Step 3 — Add adapter RED tests using real receiver plus synthetic process protocol. Construct a fresh receiver for every run; stdout_observer calls feed and catches CodexEventError to a safe code. Call process with capture_output=False. No events on process failure, invalid/missing final event, cleanup failure, unknown/tool events, overflow, cancellation, timeout or nonzero exit—even if final text was seen. Only call finish after successful exit and verified cleanup. Keep observed_model=None, no conversion into a GenerationRuntime or ready status.

```python
result = CodexStreamRunner().run(request, CodexEventLimits())
assert result.events is not None
assert result.events.final_text == '{"synthetic":true}'
assert result.events.observed_model is None
assert result.process_failure is None and result.event_failure is None
# Invalid-event child sleeps after emitting a forbidden event:
assert rejected.events is None
assert rejected.event_failure == "invalid_event"
assert rejected.cleanup_verified and rejected.active_processes_after_cleanup == 0
```

Cover fragmented UTF-8/CRLF, success followed by nonzero/extra event, truncated final line, line/event/token cap failure, separate sequential calls with no receiver state reuse, malformed sensitive-looking error text not leaked. Generic runner protocol doubles may cover non-Windows adapter branches, but early termination and descendants must be exercised with real Windows synthetic children.

- [x] Step 4 — Implement minimal adapter and run scoped suite. Use safe status mapping, no raw ProcessResult payload in public result, no logging/reasoning persistence. Unexpected runner error maps to safe failure with cleanup unverified rather than claiming success. Do not invoke model/auth/version commands. Existing actual model identity gap remains explicit.

- [x] Step 5 — Self-review, scoped mypy/Ruff and report to main; no commit. Main independently runs Windows tests and full unit/contract.

Commands from `backend`:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/generation/test_windows_process.py tests/unit/labs/rag/generation/test_codex_stream.py tests/unit/labs/rag/generation/test_codex_events.py -q --tb=short
.venv/Scripts/python.exe -m mypy src/ai_workshop/labs/rag/generation/windows_process.py src/ai_workshop/labs/rag/generation/codex_stream.py
.venv/Scripts/python.exe -m ruff check src/ai_workshop/labs/rag/generation/windows_process.py src/ai_workshop/labs/rag/generation/codex_stream.py tests/unit/labs/rag/generation/test_windows_process.py tests/unit/labs/rag/generation/test_codex_stream.py
```

## Main verification / remaining integration

Independent review checks both spec and code quality; full unit/contract, mypy and scoped Ruff must pass. Record actual synthetic process cleanup evidence. Update WORKBOARD and worklog; no full RAG readiness claim. Runner registry, verified CLI flag/config assembly, authorization-to-runtime/API wiring, actual model identity and user-facing domain activation remain separately tracked integration work.
