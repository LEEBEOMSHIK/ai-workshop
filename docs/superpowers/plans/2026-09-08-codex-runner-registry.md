# Codex runner registry Implementation Plan

> Agentic workers: use superpowers:subagent-driven-development; TDD plus independent security review.

**Goal:** Resolve a named Codex runner from server-owned typed settings and validate its local executable/request-root integrity without starting any process.
**Architecture:** Add RAG-local frozen configuration DTOs and a read-only registry. Root Settings loads a default-empty reference map; explicit registry resolution validates environment, protected paths and executable SHA-256. It returns an immutable snapshot, not a runtime or readiness approval.
**Tech Stack:** Existing Pydantic, pathlib/hashlib, pytest. No new library.
**Spec:** `docs/superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md` §6–8, §11; ADR-0017.

## Global Constraints

- main-only, preserve dirty work, no staging/commit/push/worktree.
- No CLI/model/auth/version/help invocation, user DB/.env/credentials/server/UI changes or network calls from implementation/tests.
- No actual executable/request-root registration in user settings. Tests use synthetic files, not installed Codex or private paths.
- Registry resolution never executes a process, creates/deletes files, reads auth/config contents or changes permissions.
- No arbitrary command/argv/config-override/model/secret fields. Model remains in Deployment/Profile, not runner settings.
- Existing Codex runtime/registration/readiness blocks remain unchanged. Expected CLI version is an operator-declared expectation, not observed model/version proof.
- Environment values and filesystem paths are internal-only, excluded from repr and safe exception strings. Never dump settings to logs/API.
- Main owns docs/workboard and verification; implementation owns only Task1 files.

## Task 1: Typed settings and read-only reference resolution

Files:
- Create `backend/src/ai_workshop/labs/rag/generation/codex_runner_registry.py`.
- Modify `backend/src/ai_workshop/config.py` only for default-empty typed runner map and reference-key validation.
- Create `backend/tests/unit/labs/rag/generation/test_codex_runner_registry.py`.
- Modify `backend/tests/unit/test_config.py` for default-empty/env parsing and backward compatibility.

Interfaces (names are binding):

```python
class CodexRunnerLimits(BaseModel):
    # frozen, extra forbidden; no coercing bool/numeric strings into limits
    timeout_seconds: float = 60.0       # finite, >0, <=3600
    stdin_bytes: int = 1_048_576        # >=0, <=64*1024*1024
    stdout_bytes: int = 1_048_576       # >0, <=64*1024*1024
    stderr_bytes: int = 65_536         # >=0, <=64*1024*1024
    cleanup_seconds: float = 5.0       # finite, >0, <=3600
    max_line_bytes: int = 262_144      # >0, <=stdout_bytes
    max_events: int = 64               # >0
    max_input_tokens: int = 131_072    # >0
    max_output_tokens: int = 16_384    # >0
    max_concurrent_requests: int = 1   # >0; stored budget, NOT enforced by registry

class CodexRunnerSettings(BaseModel):
    # frozen, extra forbidden, hide_input_in_errors=True
    executable: Path                  # absolute local path, repr=False
    expected_cli_version: str          # strict numeric major.minor.patch, nonempty
    executable_sha256: str             # exactly64 lowercase hex
    request_root: Path                 # absolute local directory, repr=False
    environment: dict[str, str]        # explicit map, repr=False; default empty
    limits: CodexRunnerLimits          # default factory above

class CodexRunnerRegistry:
    def __init__(self, entries: Mapping[str, CodexRunnerSettings], *,
                 environment: str, protected_roots: tuple[Path, ...]) -> None: ...
    def resolve(self, reference: str) -> ResolvedCodexRunner: ...

@dataclass(frozen=True, repr=False)
class ResolvedCodexRunner:
    reference: str
    executable: Path
    expected_cli_version: str
    executable_sha256: str
    request_root: Path
    environment: Mapping[str, str]      # immutable copy, never os.environ merge
    process_limits: ProcessLimits
    event_limits: CodexEventLimits
    max_concurrent_requests: int
    configuration_sha256: str          # canonical config fingerprint, not approval

class CodexRunnerReferenceError(ValueError):
    code: str                         # named stable codes only; no raw cause/context

# Root Settings:
codex_runner_refs: dict[str, CodexRunnerSettings] = Field(default_factory=dict, repr=False)
```

- [x] Step 1 — Write RED tests for settings/default/env parsing and registry resolution before implementation. Use existing `Settings(..., _env_file=None)` with synthetic secret. Unknown fields/argv/model/secret, invalid reference, malformed version/hash, relative/UNC/device/drive-only paths, NUL and dot-dot paths, nonfinite/negative/coerced limits and duplicate-case environment keys must reject safely.

Reference names follow current project safe named-reference pattern `[a-z][a-z0-9]*-[a-z0-9]+(?:-[a-z0-9]+)*`, maximum120, no `sk-`, `sess-`, `key-`, `token-`, `secret-` prefixes. Do not refactor other reference consumers.
Environment allowlist: `SystemRoot`, `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `TEMP`, `TMP`, `CODEX_HOME`. Match keys case-insensitively, reject duplicates, normalize canonical keys. Reject other variables (especially API keys, DB credentials, PATH, NODE_OPTIONS, PYTHONPATH, proxy/config variables). Values must be nonempty absolute local directory paths with no NUL; explicit paths only, no interpolation or auth-file read. CODEX_HOME names the official directory, not a copied credential. Settings parsing validates syntax only; it must not touch the filesystem.

- [x] Step 2 — Implement strict DTO parsing and default-empty Settings integration. Avoid circular imports: registry module may use existing ProcessLimits/CodexEventLimits but must not import root Settings. Frozen Pydantic is shallow: registry must defensively validate/copy nested mutable maps and resolved.environment must be immutable. Snapshot behavior survives caller map/settings.environment mutations. Do not trust model_construct/model_copy injected invalid values: revalidate plain DTO data at registry boundary without exposing failed input.

- [x] Step 3 — Add RED read-only filesystem resolution tests, then implement named lookup and integrity validation.

```python
entry = CodexRunnerSettings(executable=synthetic_exe,
    expected_cli_version="1.2.3", executable_sha256=known_digest,
    request_root=dedicated_root, environment={})
registry = CodexRunnerRegistry({"codex-test-v1": entry},
    environment="test", protected_roots=(synthetic_repo, synthetic_objects))
resolved = registry.resolve("codex-test-v1")
assert resolved.executable_sha256 == known_digest
assert resolved.process_limits.stdout_bytes == 1_048_576
assert resolved.event_limits.max_total_bytes == 1_048_576
assert resolved.expected_cli_version == "1.2.3"
assert not hasattr(resolved, "ready")
```

`resolve` allows `local`/`test` only; rejects production/unknown environment, unknown names or unavailable entries. Protected roots must be a nonempty set of explicit absolute trusted paths. Every existing path component for executable/request root/environment roots must reject symlinks, junctions and other reparse points before resolution/open; do not silently resolve a link and accept its target. Paths must be local, normalized, no drive root, UNC/device namespace, `..` or NUL. Request root must already exist as directory and must neither be inside nor contain any protected root. Executable must exist as regular `.exe` file; it may live outside project, but request root must not contain executable or its parent dependency installation path (no package-dir cwd). Reject executable located inside request root. This stage never creates a request cwd or cleanup target.

Check configured executable SHA-256 by bounded incremental reads (e.g.64KiB) over the file size measured before reading; reject changing size or file identity/stat metadata during inspection and do not read an endlessly growing file. Do not claim this closes all replacement races: execution must recheck and future launcher integration must manage that boundary. Tests mutate bytes after initial success and require next resolve to reject. Missing/unreadable/reparse/hash mismatch/path overlap errors must expose safe codes and no original path/cause/context, including OS errors.

Use deterministic sorted canonical serialization to compute configuration_sha256 from the validated complete runner config including normalized environment and all budgets. Reordered environment map yields same fingerprint; any executable digest/version/root/environment/budget change yields different fingerprint. This fingerprint is not per-call approval; downstream runtime must bind/compare it before activation. No silent fallback to another runner.

- [x] Step 4 — Verify real files remain untouched and global environment is not inherited. Test default empty lookup rejects; caller mutations do not change existing registry; resolved environment cannot be changed; reference errors do not leak submitted names/paths; process execution is never reached. Use real synthetic local files, and a narrowly scoped reparse simulation where Windows link creation permissions are unavailable. Record real vs simulated coverage accurately.

- [x] Step 5 — Scoped pytest/mypy/Ruff and self-review, report then freeze. Main independently runs full unit/contract and security review. Do not modify runtime resolver, approval schema/gate, deployment/DB/API/UI. No actual runner default is selected or activated.

```powershell
# from backend
.venv/Scripts/python.exe -m pytest tests/unit/test_config.py tests/unit/labs/rag/generation/test_codex_runner_registry.py -q --tb=short
.venv/Scripts/python.exe -m mypy src/ai_workshop/config.py src/ai_workshop/labs/rag/generation/codex_runner_registry.py
.venv/Scripts/python.exe -m ruff check src/ai_workshop/config.py src/ai_workshop/labs/rag/generation/codex_runner_registry.py tests/unit/test_config.py tests/unit/labs/rag/generation/test_codex_runner_registry.py
```

## Main handoff

This implements server-side registration/resolution only. CLI flag/config assembly and install-version validation, exact runtime fingerprint/approval binding, concurrency enforcement, request cwd lifecycle, admin/runtime/API wiring and actual model identity verification remain explicit next work. Never call the expected CLI version an observed version or enable readiness from file existence/hash alone.
