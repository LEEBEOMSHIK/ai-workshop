# Windows OS isolation probe implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Track the checkboxes below.

**Goal:** Implement and exercise an auth-free, synthetic Windows LPAC runner; distinguish failed startup from successful denial.

**Architecture:** A trusted host supervisor creates a suspended LPAC process, verifies its token and child policy, assigns a kill-on-close Job, then resumes. The isolated canary reports only bounded synthetic outcomes. This is an experiment, not a production generation Provider.

**Tech Stack:** Windows Win32 APIs; installed .NET Framework C# compiler if suitable; PowerShell build entry point; Python pytest for executable contract tests where appropriate. No downloaded runtime.

**Spec:** `docs/superpowers/specs/2026-09-07-codex-os-isolation-design.md`

**Execution status:** Disabled draft only. Contract RED16 observed; implemented GREEN and all native execution blocked by Windows Code Integrity. Six additional regression tests were added but could not be executed (22 total). Independent review permits retention only: creation-to-handle ownership remains unresolved. `run` unconditionally fails before all mutations, without an override. No profile/ACL mutations or CLI/model calls. Full Phase 1 is not complete; evidence lives in `docs/worklogs/2026-09-07-codex-os-isolation-probe.md`.

## Global constraints

- main only; preserve unrelated changes; no commit, push or worktree.
- No actual documents, questions, authentication, Codex configuration changes or model requests.
- No network capabilities, firewall changes, loopback exemptions, new users, services, Docker or WSL changes.
- Only a uniquely owned experiment AppContainer profile and exact task-directory ACEs may change.
- Fail closed before resume on policy/token/hash/path failure. No weaker fallback.
- A timeout is not evidence of denied access; an allowed scratch operation must succeed.
- Artifacts only under `.local-data/project-agent-work/codex-os-isolation-probe/`; record size and precise cleanup scope. Do not delete old task artifacts.
- LPAC runtime incompatibility is a failed experiment, not authorization to grant broad runtime/user-home access.

## Task 1: Executable experiment and tests

Files: create `scripts/windows-isolation/` for focused supervisor, native declarations, synthetic canary and build/test entry points. Create tests alongside this experimental tool; do not couple it to application startup.

Interfaces: supervisor accepts explicit artifact root, run identity, executable SHA-256 and bounded timeout. It returns a safe phase/code/status result and a nonzero exit on any incomplete gate. Native canary accepts only synthetic fixture identifiers/paths, controlled listener ports and supervisor PID, never arbitrary question input.

- [ ] Write executable failing tests for hash mismatch, unsafe/reparse path, invalid timeout and incomplete/timeout canary rejection. Confirm RED against the missing behavior, not source-string assertions.
- [x] Implement configuration/path validation and bounded report parsing. Keep Win32 constants named; environmental paths come from arguments/discovery. Compiled; execution verification blocked.
- [ ] Implement fresh profile ownership and exact added-ACE lifecycle; reject pre-existing profiles/paths rather than adopting them. Do not restore entire ACLs over concurrent changes.
- [x] Implement `CreateProcessW` suspended with LPAC, zero network capabilities, explicit inherited handles and child restriction; Job assignment and token/policy verification precede resume. Compiled; native behavior remains unverified.
- [ ] Implement scratch positive control, protected synthetic file denials, process/handle denial, controlled IPv4/IPv6 loopback connection denials, timeout/cancellation cleanup. Report not-run separately for any unavailable check.
- [ ] Build and run contract tests using the discovered installed compiler. Record exact commands and results; C# compiler warnings are errors. No new SDK install.

## Task 2: Independent review and controlled host execution

Files: update this plan, the design status, `WORKBOARD.md`, and `docs/worklogs/2026-09-07-codex-os-isolation-probe.md`.

- [x] Independent reviewer reads source and test evidence, checks specification compliance and code quality, and reports unsafe gaps before host execution. Final verdict: disabled draft retention only; native execution blocked.
- [ ] Resolve the exact profile name, task paths, expected artifact size and permission additions. Execute only the approved profile/task ACL mutations.
- [ ] Run synthetic canaries with bounded time; record explicit Windows result codes and positive controls. Verify profile/ACE/Job ownership and cleanup.
- [ ] Only if every mandatory synthetic gate passes, run auth-free Codex executable compatibility under the identical boundary. Otherwise keep CLI unexecuted.
- [x] Publish the real evidence, residual risks and next task. Do not claim full Phase 1 or RAG readiness if any required gate is missing or fails.

## Preflight review

| Tasks | Shared contract | Finding |
|---|---|---|
| 1 | Test outcome → runner safe report | Native denial and startup failure are distinct outcomes. |
| 2 | Source/test evidence → authorized native probe | Review precedes host changes; partial implementation cannot pass acceptance. |
| 1 → 2 | Runner result → CLI compatibility gate | All mandatory canaries must pass, no success inference from exit code alone. |

User already approved implementation and the narrow OS-change scope; no repeated general approval checkpoint. Exact execution authority remains enforced by tool permissions.
