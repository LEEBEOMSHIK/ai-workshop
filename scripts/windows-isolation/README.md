# Windows LPAC synthetic experiment

This is a **disabled native draft**, isolated from the application. It does not run
Codex, accept questions, read real documents, or change authentication settings.
The host supervisor and canary use installed .NET Framework and Win32 P/Invoke;
CLR startup under LPAC is itself unverified. Failure never grants CLR directory
access or switches to a less restrictive token.

## Current evidence

- Contract tests executed RED with 16 expected behavioral failures.
- Implemented contract tests and both binaries compile with warnings as errors.
- Windows Code Integrity blocked the implemented contract binary. GREEN and native
  execution are **BLOCKED**, not passed. Do not bypass that policy through alternate
  assembly loading, changes to signing policy, or new certificates.
- Independent review found that create-then-open gaps do not preserve continuous
  directory/file ownership: a regular replacement or hardlink could become an ACL
  target. That finding is unresolved. `run` now unconditionally fails with
  `native_run_disabled_ownership_lifecycle_unverified` before any profile, ACL,
  label, directory, fixture or listener mutation. No flag bypass exists.
- The complete synthetic matrix is not implemented: non-loopback controlled
  listeners and independent timeout/cancel/supervisor-death cleanup experiments are
  missing. Every `run` therefore exits nonzero and reports `cli_allowed=false`
  through its acceptance gate. There is no CLI launch mode.

## Build

Run from the repository root, with an unused build ID and the already discovered
compiler. The exact task artifact directory must already exist. Existing builds
are never overwritten or deleted.

```powershell
powershell -NoProfile -File scripts/windows-isolation/build.ps1 `
  -ArtifactRoot C:/projects/ai-workshop/.local-data/project-agent-work/codex-os-isolation-probe `
  -BuildId review01 `
  -Compiler C:/Windows/Microsoft.NET/FrameworkArm64/v4.0.30319/csc.exe
```

All source paths and output paths are explicitly passed to the installed compiler;
no SDK or package is installed. ContractTests.exe accepts the task artifact root
and writes one uniquely named synthetic fixture directory, which is preserved.
Do not retry blocked executables until the signing-policy authority is resolved.

## Reviewed execution interface

Supervisor.exe requires exactly five arguments: `preflight|run`, artifact root,
32 lowercase hexadecimal run ID, adjacent Canary.exe SHA-256, timeout milliseconds
(100–60000). No arguments produce a usage failure. `preflight` performs path/hash
validation and prints exact profile, task paths, noninheriting ACEs, and artifact
budget without creating the run directory or profile. Preflight paths are a local
mutation plan; runtime results contain only phase/status/safe codes.

`run` is disabled, even after the host execution policy is resolved. Enabling it
requires a code change establishing atomic create-to-handle ownership and reviewed
native lifecycle evidence. Do not remove the readiness guard merely to test startup.
`preflight` remains read-only and describes the proposed mutations below.

The retained disabled implementation would create a fresh run directory,
copies the pinned canary, creates two synthetic files, creates a fresh owned
AppContainer profile, and adds three exact noninheriting ACEs: run directory RX,
canary RX, and scratch file read/write. The scratch file also receives the exact low
mandatory label `S:(ML;;NW;;;LW)`, verified by read-back before launch and restored
during cleanup. Profile/ACE cleanup runs after process
termination verification and preserves artifact files. ACL cleanup removes only
the recorded ACE from the current ACL through the original pinned object handle;
changed same-SID ACEs or an altered scratch label block cleanup. A
cleanup failure preserves the profile for diagnosis instead of deleting it.

The retained launch code uses zero capabilities, ALL_APPLICATION_PACKAGES opt-out, child process
restriction, explicit NUL/protocol inherited handles, an empty environment, and
suspended creation. Job assignment and live AppContainer/package SID/LPAC/zero
capabilities/child-policy checks all precede resume. A kill-on-close Job allows
one active process and does not allow breakaway. Failed pre-resume validation
terminates the suspended process. Raw stderr goes to NUL.

The canary rejects standalone host invocation by checking its own AppContainer and
LPAC token flags before fixture IO. It accepts only the exact scratch.dat and
protected.dat siblings of a staged run-ID Canary.exe, plus the system cmd.exe path.
Its retained probes cover native scratch read/write, protected file access, suspended child
and shell creation, breakaway creation, privileged supervisor-handle access, and
IPv4/IPv6 loopback connections to host-owned listeners with positive controls.
Only actual access-denied codes pass: Win32 5 or Winsock 10013. Timeouts, refusal,
unavailable facilities, incomplete protocol and runtime startup failure cannot
pass. Every unexpectedly created child is requested suspended and terminated.
Reports are limited to 8192 bytes; host scratch contents are checked independently.

The disabled supervisor code contains Ctrl+C/timeout Job termination and bounded
exit verification. This is **not verified lifecycle evidence**. Abrupt supervisor death
has not been exercised; profile/ACE cleanup after an abrupt crash needs a reviewed
recovery procedure. Never sweep profiles or restore an old whole ACL.

## Limits needing independent review / future tests

- Native profile and ACE failure unwinding, exact native error codes, loaded CLR
  compatibility, handle inheritance and Job cleanup remain unexecuted.
- Contract tests exercise reverse-order rollback and resume state guards; they do
  not replace native fault injection or lifecycle integration tests.
- Path validation rejects reparse ancestors, traversal and alternate data streams.
  Ancestors and each target object are pinned without delete sharing, and path/file
  identities are checked before mutation. DACL and label reads/writes/rollback use
  pinned handles, but creation-to-open replacement gaps remain unresolved; therefore
  the native-run readiness guard is mandatory. This is not an approved security
  boundary and no native mutation is enabled.
- Managed canary initialization can fail before any positive scratch control.
- Current listener tests cover IPv4/IPv6 loopback only, not LAN/non-loopback egress.
- The printed artifact byte budget covers task files, not Windows-owned profile
  metadata; no broad runtime is staged. Artifact deletion needs a separate audit.

Microsoft API references: [AppContainer implementation](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer),
[creation attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute),
[token information](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ne-winnt-token_information_class),
[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
[Security information access rights](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-information)
documents READ_CONTROL for label queries and WRITE_OWNER for exact label changes.
