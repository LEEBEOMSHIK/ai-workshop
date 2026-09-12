# Codex command assembly Implementation Plan

> Agentic workers: use superpowers:subagent-driven-development; TDD and independent security/quality review.

**Goal:** Assemble a deterministic, non-executing Codex request from the existing runner, call intent and exact authorized payload contracts.
**Architecture:** A pure RAG-local assembler joins named runner settings, model selection and payload hashes into an immutable command plan. It does not create files or launch processes. The plan carries schema bytes and configuration/payload fingerprints for the subsequent request-workspace and authorization coordinator.
**Tech Stack:** Python stdlib dataclasses/hashlib/json/tomllib tests; existing domain contracts, pytest. No dependencies.
**Spec:** `docs/superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md` sections 3, 6–11.

## Global Constraints

- main only; preserve dirty work; no worktree, staging, commit or push.
- No CLI/model/auth/network/DB/user .env/credential/UI changes by implementation/tests.
- The main agent has separately observed CLI version 0.153.4 and exec --help on 2026-09-09. Help support is not proof of effective tool isolation, settings applicability or model identity.
- No runtime registration/health/readiness activation. No process start, file creation, deletion or auth/config reading in this assembler.
- No arbitrary argv/config/endpoint/secret overrides. Model comes from CodexCallIntent.provider_model_id, never a production model literal/default.
- Question/history/evidence only in exact stdin bytes. Only trusted developer instructions may enter the developer_instructions config value. Never log plan/request/payload contents or include them in repr/errors.
- Preserve upper policy/rules; never add ignore-rules, full-access, approval/sandbox bypass, hook-trust bypass, resume/fork, image, output-last-message or user profile flags.
- Literal CLI keys and safety values are a named protocol contract, not user-changeable settings. Unknown CLI contract versions reject; updating support requires a reviewed versioned contract.

## Task 1: Pure invocation assembly and intent binding

Create only:
- `backend/src/ai_workshop/labs/rag/generation/codex_command.py`
- `backend/tests/unit/labs/rag/generation/test_codex_command.py`

Inputs: existing CodexCallIntent, CodexExecutionPayload, ResolvedCodexRunner and ProcessRequest/ProcessLimits. Inspect their definitions; do not modify them.

```python
@dataclass(frozen=True, slots=True, repr=False)
class CodexCommandPlan:
    process_request: ProcessRequest
    output_schema_path: Path
    output_schema: bytes
    runner_configuration_sha256: str
    payload_sha256: str
    cli_contract_version: str

class CodexCommandError(ValueError):
    code: str  # fixed safe codes only; never raw input/cause/context

def build_codex_command(*, runner: ResolvedCodexRunner, intent: CodexCallIntent,
                       payload: CodexExecutionPayload, request_directory: Path,
                       timeout_seconds: float) -> CodexCommandPlan: ...
```

This is a command plan, NOT launch approval. Required request_directory is a trusted coordinator input; assembler validates lexical containment but does not attest filesystem identity or create the directory/schema. The later coordinator must create an owned directory, write these exact schema bytes, check real paths/reparse points, re-resolve runner, compare fingerprints, bind current approval and only then launch. Missing that coordinator keeps runtime blocked.

- [x] Step 1: Add tests first and run RED (module absent). Build synthetic existing DTOs; use temp_path syntax only, never installed executable. Test an actual build_codex_prompt envelope converted to CodexExecutionPayload and matching intent digest to verify unchanged prompt adapter compatibility.

```python
plan = build_codex_command(runner=runner, intent=intent, payload=payload,
                          request_directory=runner.request_root / "request-synthetic",
                          timeout_seconds=30.0)
assert plan.process_request.stdin == payload.stdin
assert plan.output_schema == payload.output_schema
assert plan.payload_sha256 == payload.digest()
assert plan.runner_configuration_sha256 == runner.configuration_sha256
assert plan.process_request.limits.timeout_seconds == min(30.0, runner.process_limits.timeout_seconds)
assert not hasattr(plan, "ready")
```

- [x] Step 2: Implement validation and exact byte binding. Reject runner ref mismatch, malformed fingerprint/digest, developer/schema hash mismatch, empty/non-UTF8/NUL/unpaired-surrogate developer instructions, invalid UTF8/JSON/non-object stdin/schema, duplicate JSON keys or NaN/Infinity, input above stdin budget; finite positive timeout <=3600 with bool/string rejected. Do not reserialize approved stdin/schema. Validate provider model as nonempty trimmed ASCII identifier `[A-Za-z0-9][A-Za-z0-9._:-]{0,199}` (no leading option, whitespace, shell metacharacters, controls). Do not require one particular model. Hashes are 64 lowercase hex. Intent stage/operation must be actual enum values. Wrong DTO types yield safe errors, not raw AttributeError/TypeError.

Support only named CLI contract `0.153.4` at this stage: runner.expected_cli_version must match. This is supported syntax, not an observed-version assertion. No actual model observation field.

- [x] Step 3: Assemble exact argv tuple in a stable order:

```python
argv = ("exec", "--strict-config", "--ignore-user-config", "--ephemeral", "--json",
        "--sandbox", "read-only", "--skip-git-repo-check", "--color", "never",
        "--model", intent.provider_model_id, "--cd", str(request_directory),
        "--output-schema", str(request_directory / "output-schema.json"),
        "-c", 'approval_policy="never"',
        "-c", 'web_search="disabled"',
        "-c", "project_doc_max_bytes=0",
        "-c", "features.shell_tool=false",
        "-c", "features.multi_agent=false",
        "-c", "features.apps=false",
        "-c", "features.hooks=false",
        "-c", "developer_instructions=" + toml_string(developer_text), "-")
```

Use TOML-compatible string encoding, not shell quoting; json.dumps(ensure_ascii=False) is suitable for valid Unicode basic strings, but test roundtrips using tomllib with Korean, emoji, quotes, backslashes, newline, control escapes and injection-shaped text. Never interpolate config keys or concatenate a shell command. Unknown plugin/skills/MCP blanket switches are not invented; actual effective settings/tool restrictions remain a separate verification gate. Absence of those in this contract is not a claim they are disabled.

Validate request_directory absolute/local/non-root/no traversal/NUL/UNC/device/reparse aliases lexically; it must be a STRICT direct child of runner.request_root, not the root itself. No filesystem access or symlink resolution here. Reuse public existing validators if suitable, otherwise a small private syntax helper; do not expose/modify registry internals. Reject Windows alias-dangerous segments (trailing dot/space, ADS/reserved device names, control/metacharacters). Validate schema path is exactly its fixed child. Ensure full Windows list2cmdline UTF-16 length including executable stays <32767; oversized developer instructions fail safely rather than truncate. Copy environment into MappingProxyType, preserve immutable process limits except min timeout. Validate runner process limits with the existing strict CodexRunnerLimits DTO fields where useful; no bool/numeric-string budget bypass.

- [x] Step 4: Add negative and determinism tests: payload tampering after matching intent setup, wrong runner/model/version, invalid paths, nested/root/outside cwd, malformed JSON/duplicate keys/nonfinite, UTF8/TOML injection and Win32 command cap, exact-byte whitespace preservation, no input leak in argv/repr/errors, safe __cause__/__context__, immutable environment, no inherited environment, no filesystem/process side effects. Explicitly assert prohibited flags and arbitrary data do not enter argv. Confirm schema bytes are not written by builder.

- [x] Step 5: Scoped pytest/mypy/Ruff, self-review, freeze/report; main independent full unit/contract and security review. No edits beyond two owned files. Write detailed RED/GREEN/report at `.local-data/project-agent-work/codex-command-assembly/task-1-report.md`.

```powershell
# from backend
.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/generation/test_codex_command.py -q --tb=short
.venv/Scripts/python.exe -m mypy src/ai_workshop/labs/rag/generation/codex_command.py
.venv/Scripts/python.exe -m ruff check src/ai_workshop/labs/rag/generation/codex_command.py tests/unit/labs/rag/generation/test_codex_command.py
```

## Verification sources and next boundary

### Review-driven path correction (same roles, scoped expansion)

Independent review reproduced accepted Windows reserved aliases COM\u00b9, LPT\u00b2.txt and CON .txt.
Use Python 3.13 ntpath.isreserved for Windows reserved-name semantics (pure syntax, no filesystem call),
retaining all existing local/containment/UNC/traversal checks. Add public-builder and registry-settings
regression tests for the aliases, superscript 1/2/3, base whitespace before extension and valid near names.
The same incomplete regex exists in the prior registry, so this corrective pass additionally owns only:
`backend/src/ai_workshop/labs/rag/generation/codex_runner_registry.py` and
`backend/tests/unit/labs/rag/generation/test_codex_runner_registry.py`, solely path-rule correction/tests.
Clarify command module/function docstrings: command planning grants no launch authority; current approval,
payload/configuration fingerprint comparison, real request ownership, executable identity and concurrency
belong to the coordinator. No new coordinator or runtime activation is added in this correction.
Run RED before correction, scoped command+registry tests, mypy on both sources and Ruff on all four files.
Main re-runs full unit/contract after the independent scoped fix review.

Official fetched 2026-09-09: https://learn.chatgpt.com/docs/non-interactive-mode and https://learn.chatgpt.com/docs/config-file/config-reference.
Installed --help and --version confirmed supported flag spelling and 0.153.4 only. Config overrides are not an effective configuration attestation.
Next: owned request-directory lifecycle, durable authorization fingerprint binding, current-version settings verification/concurrency, runtime/API wiring, actual model identity and domain activation.
