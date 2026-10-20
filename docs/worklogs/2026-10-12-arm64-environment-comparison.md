# ARM64 environment comparison — 2026-10-12

> 현재 상태(2026-10-12): **AMD64 유지, ARM64 전환 취소 및 실험 환경 정리.**
> 사용자의 명시적 취소에 따라 아래 ARM64 전환·의존성 해결·OCR 분리 제안과 후속 검증은
> 종료된 조사 이력으로 보존하며 진행 중 계획이나 실행 승인 요청으로 취급하지 않는다.
> 기존 AMD64·Gemma 제품 코드·서비스는 유지한다. 정리 결과는 비교 작업 기록의 마지막 절을 따른다.

The user authorized a project-private ARM64 environment and removal of the old
AMD64 environment only if compatibility and transition were safe. This work does
not authorize model downloads/inference, DB/migrations, service changes, global
Python/PATH changes, policy changes, or permanent deletion. Existing RAG priorities
and operational blockers are unchanged.

## Installed comparison environment

- Base: `.local-data/runtimes/cpython-3.13.15-arm64-nuget/tools/python.exe`.
- Environment: `.local-data/venvs/ai-workshop-arm64/Scripts/python.exe`.
- Official CPython `pythonarm64` NuGet 3.13.15, PE machine `0xAA64`, valid Python
  Software Foundation Authenticode signature. Actual execution reports Python
  3.13.15, `ARM64`, `win-arm64`.
- NuGet archive SHA-256:
  `3c1b1fdf56adc14634165df922d447520aefdc4a8411a34c34d8a062a4edf494`.
- Official PyTorch CPU wheel: `torch-2.13.0+cpu-cp313-cp313-win_arm64.whl`, SHA-256
  `ac7aaf322be4777765a53bed7264a214dd81b3a1d276b93150515a3c5f75e4b0`.
- Official PyPI wheels: Transformers 5.16.1, bitsandbytes 0.50.2, accelerate 1.15.0,
  NumPy 2.3.5, SciPy 1.18.1, scikit-learn 1.9.0, plus their dependencies and scoped
  test/type/lint dependencies. Installed inventory contains 66 distributions.
- Locked PyYAML 6.0.2 had no matching ARM64 wheel and its source build failed because
  Microsoft C++ build tools were unavailable. **Only this comparison environment**
  uses PyYAML 6.0.3's official ARM64 wheel, within the project's `>=6,<7` requirement.
  This is an explicit lock deviation, independently reviewed; it is not a frozen
  lock reproduction. `pyproject.toml` and `uv.lock` were not changed.
- All installed distributions represented in the lock match locked versions except
  PyYAML. Additional packages absent from the lock are bitsandbytes, accelerate and
  pip 26.2.1. No compiler installation, forced package version or dependency hiding
  was used.

Initial network/CIM reads were denied in the default sandbox. Supported, narrowly
scoped tool escalation approved the official package downloads and PID/path-only
CIM read. No security policy or permissions were changed. Installation used no pip
download cache. The archive and project-owned environment remain available.

Official references: [CPython Windows NuGet distribution](https://docs.python.org/3.13/using/windows.html#the-nuget-org-packages),
[pythonarm64 3.13.15](https://www.nuget.org/packages/pythonarm64/3.13.15),
[PyYAML 6.0.3 metadata](https://pypi.org/pypi/PyYAML/6.0.3/json).

## Executed checks

All native probes used offline Hugging Face settings, tiny synthetic tensors and
two CPU threads. No model/tokenizer was constructed and no weights were fetched.

- `pip check`: passed after ML install and after scoped test dependencies.
- PyYAML safe dump/load round trip: passed.
- Native BF16 CPU 16×16 matmul against FP32 reference: passed (43.744 seconds,
  including import; this is not a model performance benchmark).
- bitsandbytes NF4 CPU 64×64 quantization/dequantization and 1×64 matmul against
  dequantized reference: passed (6.678 seconds, including import). This does not
  validate loading or running a 4-bit Gemma model.
- First SciPy/scikit-learn and Gemma4 class probes each exceeded 60 seconds. They
  were recorded as timeouts, not policy errors or successful imports.
- Root six-file mock run stopped at collection with two missing-`pwdlib` errors in
  runtime-resolution and pipeline tests. No tests from that run are claimed passed.
- Independent ARM64 run of `test_local_transformers.py`, `test_local_gemma4.py`,
  `test_local_model_host.py`, `test_local_error_contract.py`: **57 passed, 1.25s**.
- ARM64 Mypy with `--follow-imports=silent`: both `local_model_host.py` and
  `local_transformers.py` passed under project strict settings. Ruff passed those
  files and `test_local_gemma4.py`.

The follow-up import diagnostic uses unbuffered stage markers, periodic stack dumps
and an in-process 150-second watchdog. A fresh PID/path-only CIM read before that
diagnostic confirmed no remaining ARM64 Python processes from the first probes.
Follow-up result: `scipy` imported in 0.078s and
`scipy.optimize._group_columns` in 71.833s. The next
`sklearn.metrics.roc_curve` import remained incomplete when the 150-second watchdog
exited the diagnostic (command returned failure). This run never reached its
Transformers/Gemma4 stages. The last stack passes from scikit-learn into SciPy stats
and ndimage's native extension loading;
no Python exception or application-control denial was returned in this ARM64 run.
The precise reason for the delay is unknown. The earlier AMD64 policy error does
not establish the cause of this ARM64 timeout. No package removal, dependency
hiding, policy change, DLL replacement or alternate-privilege import retry was used.

## Why AMD64 is preserved

- The backend base-dependency binary-only dry run failed: locked cryptography 50.0.1
  has no compatible official Windows ARM64 wheel. No source toolchain was added.
- Locked PaddlePaddle 3.2.2 has no official Windows ARM64 wheel or source distribution;
  the existing OCR environment cannot be replaced with the approved package set.
- The project correctly omits `psycopg-binary` on Windows ARM64, but compatible libpq
  availability remains unverified. Full backend, API export, PDF/DOCX/OCR and DB
  compatibility have not been established.
- Existing service launcher, OpenAPI wrapper and sandbox preparation paths still
  reference `backend/.venv`; no execution path was switched.
- A fresh CIM read found three old-environment Python launchers and their three
  shared AMD64 base-interpreter children. These processes were not stopped. Final
  PID/path verification showed the same six processes and no ARM64 Python remnants.
- Old environment: `backend/.venv`. Its base interpreter is the shared per-user
  `C:/Users/bumci/AppData/Local/Programs/Python/Python313/python.exe`, which is outside
  project cleanup scope.

**No AMD64 directory was renamed, quarantined, or removed.** Its 150-package metadata
inventory is unchanged (independent before/after comparison); its `pyvenv.cfg`,
`pyproject.toml`, `uv.lock` and `.gitignore` hashes match the initial baseline. This
is configuration/package metadata preservation evidence, not a full binary audit.
No recovery from deletion is necessary. The user’s condition for removal is unmet.

## Evidence and remaining work

Local ignored evidence is under
`.local-data/project-agent-work/arm64-env-20261012/`: baseline hashes/status,
official archive, lock/probe constraints, pip install reports with URLs/hashes,
both package inventories, native probe results, staged import log/results and
preservation checks. Comparison scripts are confined to this directory.

Only this worklog and the current WORKBOARD entry are documentation changes in this
environment task. Existing uncommitted implementation changes were preserved. No
staging, commit, push, migration, service restart or cleanup was performed. Existing
user/service processes were not terminated; only this task's diagnostic processes
ended under bounded timeout/watchdog. Full project tests/API/UV lock validation and real model inference are
not reported as passed. Operational issue DB updates remain outside authorization.

Next work is to diagnose the bounded scikit-learn/Gemma import delay within existing
policy, then decide a supported ARM64 backend/OCR dependency and execution layout
before considering transition. The environment is retained for comparison, not
promoted to the application runtime. Model download/load remains a separate step
requiring its approved manifest and memory limits.

## Follow-up: exact import blocker and dependency boundaries

The user authorized continued diagnosis and compatible official packages inside the
same ARM64 environment, preserving AMD64 and all services, shared Python/PATH,
policy, DB and model state. No compatible package correction was established in
this follow-up, so no package was changed.

### Native import evidence

A 300-second bounded diagnostic observed `ExtensionFileLoader.create_module`
start/end/error boundaries while delegating unchanged to the real loader. It did
not replace modules, suppress dependencies or change import resolution. Offline
settings, immediate output, stack dumps and an owned-process watchdog were retained.

- SciPy optimize stage passed in 0.899s; the formerly slow
  `scipy.optimize._lsq.givens_elimination` load took 0.002s in this run.
- `sklearn.metrics.roc_curve` entered at 0.902s.
- `sklearn.utils._isfinite` loaded in 2.895s.
- `sklearn._cyutility` entered at 4.360s and failed at 6.105s with
  `ImportError: DLL load failed while importing _cyutility: 애플리케이션 제어 정책에서 이 파일을 차단했습니다.`
- The affected file is
  `.local-data/venvs/ai-workshop-arm64/Lib/site-packages/sklearn/_cyutility.cp313-win_arm64.pyd`.
- Read-only Code Integrity events **3033 and 3077** for that exact Python/file path
  at `2026-10-12T10:47:36+09:00` independently report unmet Enterprise signing-level
  requirements / code-integrity policy. This establishes a current ARM64 policy
  failure; it does not retroactively prove the cause of every earlier timeout.
- The file is PE ARM64 (`0xAA64`); SHA-256
  `18d7249b42a8649322cfe5c733ca57495b5ffea941756d1bd3a5cbc3a574c44b`
  matches its installed wheel RECORD. Official scikit-learn 1.9.0 ARM64 wheel SHA-256:
  `d77f54c017633791bc0225a43e2f8d03745fdcfe4880268fcc4df15f505dec2e`.
  A matching package hash does not grant policy trust.

Gemma4's stage was not executed after this error. Static installed-source evidence
connects Gemma4 `modeling_gemma4.py:35` to `GenerationMixin`, then
`generation/utils.py:54` to `candidate_generator.py:30-31`, which imports
`sklearn.metrics.roc_curve` when scikit-learn is installed. Thus the installed
configuration has an affected import dependency; actual Gemma4 import remains
unverified. No downgrade/replacement, dependency removal/hiding, elevated import,
DLL alteration or policy change was attempted after the policy denial.

### Required paths versus optional execution

| Dependency | Code boundary | Official package finding |
| --- | --- | --- |
| cryptography | Required by API/worker import, not merely optional startup checks | Locked 50.0.1 and compatible 50.0.2 have no Windows ARM64 wheel |
| PaddlePaddle | Native engine required when configured OCR runs | Locked 3.2.2 has no Windows ARM64 wheel or sdist; newer 3.3.1 also lacks a Windows ARM64 wheel and is outside the exact pin |
| PaddleOCR / PaddleX | Lazy OCR runtime factory | 3.7.0 / 3.7.2 offer generic Python wheels; these do not supply a compatible native Paddle engine |

Required cryptography chain:
[main.py:33](../../backend/src/ai_workshop/main.py) imports
[assets/api.py:28](../../backend/src/ai_workshop/platform/assets/api.py), which imports
[worker.py](../../backend/src/ai_workshop/worker.py). Its line 381 constructs Celery;
line 375 imports `access_epoch_worker`, which imports
[access_epoch_runtime.py:12-13](../../backend/src/ai_workshop/labs/rag/indexing/access_epoch_runtime.py)
and eagerly imports cryptography X.509 and hashes. Skipping cryptography therefore
cannot establish normal API import/OpenAPI/worker compatibility.

OCR selection is conditional in
[ingestion/tasks.py:590-603](../../backend/src/ai_workshop/labs/rag/ingestion/tasks.py).
The [Paddle adapter](../../backend/src/ai_workshop/labs/rag/ocr/paddle_structure.py)
constructor does not import Paddle; `recognize` invokes its factory, whose line 167
loads `paddleocr.PPStructureV3`. Ordinary startup and OCR execution are distinct, but
omitting this engine loses configured OCR capability and is not full replacement.

Official package evidence:
[cryptography 50.0.1](https://pypi.org/pypi/cryptography/50.0.1/json),
[50.0.2](https://pypi.org/pypi/cryptography/50.0.2/json),
[PaddlePaddle 3.2.2](https://pypi.org/pypi/paddlepaddle/3.2.2/json),
[3.3.1](https://pypi.org/pypi/paddlepaddle/3.3.1/json),
[PaddleOCR 3.7.0](https://pypi.org/pypi/paddleocr/3.7.0/json),
[PaddleX 3.7.2](https://pypi.org/pypi/paddlex/3.7.2/json).
The [official cryptography Windows build instructions](https://cryptography.io/en/latest/installation/#building-cryptography-on-windows)
require C/VC tools, Rust and suitable OpenSSL. `cargo`, `rustc` and `cl` were not
discoverable on this task's PATH; the prior source-build probe also lacked MSVC.
This does not prove those tools are absent everywhere. No source toolchain or
cryptography source build was installed/attempted in this follow-up.

### Verification and minimum next actions

Independent review checked dependency boundaries and official versions. Final
inventory comparison preserves all **150 AMD64 / 66 ARM64** distributions; project
lock/settings and old `pyvenv.cfg` are unchanged. Native import returned failure;
full backend/API/model tests are not claimed passed. Earlier 57 mock passes remain
historical evidence and were not rerun after a production change (there was none).

1. Have the responsible policy owner assess the exact official wheel/file hashes
   and signing failure through the normal trust process. No policy exemption or
   altered import path is part of this task.
2. Obtain a trusted Windows ARM64 cryptography build, or separately plan and approve
   a reproducible ARM64 source toolchain/build. Merely upgrading to 50.0.2 does not
   close the binary distribution gap.
3. Preserve the working AMD64 OCR/runtime until a supported replacement or explicitly
   designed mixed-runtime arrangement proves feature parity. No such split was
   implemented here. libpq, full API/parser checks and executable-path transition
   also remain prerequisites.

Follow-up evidence is in
`.local-data/project-agent-work/arm64-followup-20261012/`: fresh baseline, native
boundary trace/summary, filtered Code Integrity events, blocked DLL provenance,
package preservation and before/after Python process snapshots. Diagnostics stopped
at the policy error, and no existing process or environment was changed.

## Whole-application parity inventory and isolated frontend checks

The user's acceptance criterion is functional parity for frontend, backend and all
implemented features, preserving AMD64 until the complete transition is proven.
The [38-row parity matrix](../runbooks/arm64-feature-parity.md) now separates actual
ARM64 results, unit/mock evidence, blocked/unrun integrations and pre-existing
AMD64 RAG closure work. Independent review found no blocking scope omission.

New checks (not replacements for earlier integration gaps):

- ARM64 Python: 11 selected pure/parser/mock test files, **126 passed in 1.55s**;
  independent JUnit inspection confirmed 0 failed/error/skipped. This includes the
  earlier 57 local mock cases; counts overlap and must not be added.
- Official Node24.18.0 Windows ARM64 ZIP SHA-256 and OpenJS signature verified.
  Existing Node is x64; it was not used to claim frontend ARM64 success. A 405-file
  source copy matched the original before build. Private `.env`/data and existing
  `.next`/node_modules were not copied or modified.
- Isolated pnpm11.20.0 frozen lock installed 469 packages. Its 574-entry policy check
  concerns dependency/install policy, not Windows DLL trust. Seven selected native
  binding distributions have ARM64 PE files; this alone is not runtime parity.
- ARM64 frontend **144 files / 968 tests passed**, 0 failure/pending, Vitest exit0;
  JSON result window ~645.95s. TypeScript and ESLint both exited0. These use JSDOM and
  mocks, not a live ARM64 API or browser acceptance run.
- Default Next16.3.4 Turbopack production build ran once in an isolated Windows Job
  with 768MiB job memory / 512MiB V8 old-space / 300s bounds because free RAM was only
  about1.54GiB. It entered compile then failed OOM in26.543s, exit2147483651. Peak
  job memory reported917,667,840bytes. This is a resource-limited failed build, not
  evidence of an ARM64-only regression. Its owned processes ended; no existing
  process was stopped. No increased-limit retry or start/server/API test followed.

Source/package contracts, existing Python environments, services, DB and policy
remain unchanged. Runtime/migration/model tests were not performed. Exact commands,
JUnit/JSON reports, build log/resource result, source comparison, native package
inventory and preservation evidence are retained in
`.local-data/project-agent-work/arm64-parity-20261012/`. The matrix defines the
remaining safe sequence; **whole-application parity is not established**.


## Dependency resolution research and resource gate

The [resolution and approval plan](../runbooks/arm64-dependency-resolution.md)
records official package/source support, Windows policy evidence and one proposed
path: preserve Windows ARM64 protection boundaries, prefer a future official cryptography51 wheel qualification, and investigate a local Linux ARM64 OCR adapter. This is a
proposal, not an approved architecture or an implemented runtime split.

Fresh official PyPI JSON reads confirmed no win_arm64 wheels for cryptography
50.0.1/50.0.2 or Paddle3.2.2/3.3.1. Paddle3.2.2 does offer the CPython3.13
manylinux2014_aarch64 wheel (88,143,036 bytes); no Linux installation/runtime or
PPStructureV3 compatibility test was performed. Upstream cryptography PR14216
withdrew Windows ARM64 support on 2026-01-27. Independent review found the later PR15350 (merged2026-09-02) restoring support for51. A fresh PyPI latest query returned50.0.2, no51 releases and no latest win_arm64 wheel. The recommendation therefore prioritizes released official51 qualification over installing a source toolchain now; changing the current <51 constraint requires separate compatibility review. A50.x source build remains a separately approved fallback with maintenance responsibility. Generic source-build instructions
must not be represented as a maintained Windows ARM64 release guarantee.

Existing Code Integrity3033/3077 evidence identifies enforced App Control with
Policy ID0283ac0f-fff1-49ae-ada1-8a933130cad6. A read-only3099 query found no matching
events, so specific product/deployment ownership remains unresolved. No denied
native import, substitute package/environment, trust rule or security setting was
attempted. Policy-owner review must precede affected execution.

Fresh memory was1,715,524KiB free physical (~1.64GiB), total24,646,392KiB,
free virtual6,666,648KiB. Current IDE/ChatGPT/Codex/Unity/WSL processes are concurrent
load, not retrospective proof of which caused the earlier OOM. Previous Vitest
had finished before the build. No frontend retry was justified under this headroom;
no user process was stopped. The plan states proposed resource gates and separates
estimated disk/RAM budgets from measured package sizes.

Execution in this follow-up: official metadata reads, saved-log inspection,
RAM/working-set/disk reads and documentation checks only. Narrow read-only network
and CIM calls succeeded after sandbox restriction; a role-selector call under the
global Python lacked PyYAML and passed under the existing private ARM64 environment.
No packages or build tools were installed, no model/test/integration/build was run,
and no product source/lock/service/DB/WSL/Docker/policy/Git publication was changed.
Evidence: `.local-data/project-agent-work/arm64-resolution-20261012/`.

Independent read-only review completed with no blocking document findings after
the cryptography51 support-restoration correction. Relative-link checks (11) and
scoped git diff --check passed; backend/frontend dependency files and locks matched
the start-of-follow-up hashes. No new product tests are claimed.


## Local ARM64 OCR design only

The user authorized the design stage only. The canonical
[local OCR boundary draft](../superpowers/specs/2026-10-12-local-arm64-ocr-design.md)
now defines the local container/pipe contract, private raster handling, no network
or source/DB mounts, ten-model semantic parity, current permission recheck, bounded
resources, cancellation/termination evidence, retries, cleanup and rollback.
Architecture, RAG and dependency-resolution documents reference the same draft;
existing linux/amd64 deployment remains the approved operational baseline.

Read-only Docker context/version inspection returned the Windows ARM64 client
29.5.3 but denied access to Docker config and the daemon pipe (Server:null, exit1).
No escalation, alternate context, WSL path or environment access retry was attempted.
Actual Linux engine/distribution/resources therefore remain unidentified. Existing
cryptography, Windows DLL policy, libpq, frontend memory and full-service blockers
remain independent; no source/model/DB/engine/service/security setting changed.

Independent review found and closed two protocol issues: keep control stdin open
after the complete image frame until terminal/exit, distinguishing normal completion
from parent-loss EOF; persist create intent before container creation and bind its
unique exact identity before start. Final read-only review found no blocking design
findings. This is not runtime isolation or feature-equivalence verification.

Executed checks: role selector passed; 62 relative links and placeholder scan passed;
scoped git diff --check passed (existing Git LF/CRLF normalization warnings noted).
Backend dependency manifest/lock matched the task baseline. Product tests, package
installation, downloads, model inference, DB/WSL/Docker mutations, service stops and
Git commit/push: zero. Evidence is in
`.local-data/project-agent-work/ocr-arm64-design-20261012/`.

One next approval unit is a single official Paddle3.2.2 CPython3.13 Linux ARM64
wheel download (88,143,036 bytes), SHA/ZIP/METADATA/ELF static inspection only, with
256MiB proposed disk headroom. No site-packages/OS/container installation or native
execution is part of that unit. Full image/dependency footprint remains unmeasured.


## Official Paddle wheel static preflight

The user clarified that downloading and statically inspecting the one public wheel
is within the existing compatibility-investigation scope; no new installation
approval was needed. The official PyPI JSON matched the expected filename, size,
SHA256 and non-yanked status. A single files.pythonhosted.org HTTPS download saved
88,143,036 bytes in2.828s, SHA256
`b03569ba151ac50aa730955c65dfa571fe7ae71f94574c94e8bfe5e0913a7d9c`.

A task-local stdlib inspector opened the ZIP without extracting/importing/executing
its code. Path/duplicate/symlink/encryption/size checks passed for3315 entries. WHEEL,
METADATA, RECORD paths and13 ELF headers/dynamic dependency/version sections were
read. The first inspector run stopped at its own8MiB whole-string-table bound;
reading only requested names fixed that diagnostic limitation. The next ARM-only
assertion detected real mixed-architecture contents. The final50.078s run recorded
all machine types instead of assuming ARM and exited0. No additional download or
package mutation was used to address either finding.

Confirmed findings:

- Filename advertises cp313-cp313-manylinux2014_aarch64; internal WHEEL says
  cp313-cp313-linux_aarch64. Requires-Python is absent. This is not an abi3 wheel.
- Nine ELF64 little-endian objects are AArch64, four are x86_64:
  libblas.so.3, libgfortran.so.3, liblapack.so.3 and libquadmath.so.0.
- libpaddle's bundled DT_NEEDED closure has five ARM64 libraries and none of those
  four foreign objects. This does not establish that dlopen/preload never uses them.
- ARM64 libphi_core/warp libraries require GLIBC_2.27; observed C++ symbol needs
  include GLIBCXX_3.4.22 and CXXABI_1.3.11. These exceed the manylinux2014 symbol
  baseline; the filename alone is not compatibility evidence.
- ARM64 libopenblas requires libgfortran.so.4/GFORTRAN_7, not included in the wheel.
  The bundled x86_64 libgfortran.so.3 cannot substitute for it. Other external names
  include libc/libm/libpthread/librt, libgcc_s/libstdc++/libgomp and the AArch64 loader.
- Declared uncompressed size334,392,098bytes (~318.90MiB) was not extracted. The
  inspection directory remained about84.1MiB, below the256MiB cap.

The [design](../superpowers/specs/2026-10-12-local-arm64-ocr-design.md) section10
contains the detailed facts, eight direct Python dependencies and qualifications.
Full archive SHA was checked; per-member RECORD hashes/full CRC, dlopen/transitive
host resolution, actual CPU features, Linux import, PaddleOCR/PaddleX closure and
OCR inference were not checked. Independent review separately read five ZIP ELF
headers and computed the bundled dependency closure, finding no blocking report
errors. It agreed that runtime qualification must remain withheld.

No extraction, pip/uv installation, package/native execution, model operation,
Docker/WSL access retry, policy/service/DB change or commit/push occurred. Existing
AMD64 remains untouched. Mixed binaries were not removed or replaced. The artifact
packaging issue is recorded here; operational issue-history DB registration is
pending under the explicit no-DB-change constraint, with no invented ISSUE ID.

Evidence directory:
`.local-data/project-agent-work/ocr-arm64-wheel-preflight-20261012/` contains the
wheel, source/download receipts, inspector, ELF headers, static report and findings.
The next investigation must establish an official compatible dependency/loader
path before this wheel can be qualified; environment installation and actual
execution remain separately scoped. cryptography, Windows DLL policy, libpq,
frontend resources and full application integration are independent open gates.


## Official Paddle support-path investigation

Read-only follow-up on2026-10-12 kept Python3.13/Paddle3.2.2/PaddleOCR3.7.0/
PaddleX3.7.2 fixed. No concrete officially supported general-CPU Linux ARM64
configuration matching those pins was established. This is not a runtime failure
or a universal claim that Paddle cannot run on ARM64.

The [design section11](../superpowers/specs/2026-10-12-local-arm64-ocr-design.md)
records official release/3.2 installation/source-build docs, stable CPU index and
HEAD metadata, Docker Hub metadata, v3.2.2 source paths, issue78118 and merged
PR79516/79518. Six3.2.2 image tags are all linux/amd64; documentation says Python3.10.
LAPACK is loaded on relevant operation calls, so the mixed libraries are not proven
unused. Upstream fixed ARM LAPACK packaging in develop/release3.4, while inspected
v3.2.2/release3.2 source retains the old path. A newer-source fix is neither a fix
for our pinned archive nor proof that Fortran/glibc issues are all resolved.

Official CDN HEAD matched the existing archive's size88,143,036bytes but provided
no SHA256: byte identity was not claimed. The libgfortran.so.4/GFORTRAN_7 plus
observed glibc/C++ symbol combination has no confirmed official recipe for these
pins. No package installation approval is requested without a qualified target.
Next scope is upstream clarification/fixed release metadata or an explicitly
approved version-change investigation, followed by exact digest/closure/budget
before any bounded import/synthetic check. Original RAG and Windows policy gates
remain open; issue-history DB registration remains pending under no-DB-write scope.

Evidence: `.local-data/project-agent-work/ocr-arm64-official-support-20261012/`.
The first sandboxed public-HTTPS request returned WinError10013; the same harmless
metadata read succeeded through the tool's approved escalation. No Docker/WSL
access retry or application-control bypass occurred. Website timeout/404 attempts
were resolved with official repository text; they are not runtime test failures.
No new wheel/image layers, installation, extraction, model/native execution,
product test, environment/service/DB/policy change, commit or push occurred.

Independent source/evidence/document review found no blocking factual findings.
Its wording correction (structural candidate, installation recommendation withheld)
and additional CBLAS/setup source links were applied. Fifteen relative links,
merged-PR/base-branch checks, six-tag architecture metadata, unchanged manifest/lock
and scoped diff checks passed. The first verification helper hit Windows cp949
JSON decoding; explicitly reading UTF-8 corrected it and the rerun exited0. This
was a diagnostic-helper issue, not a product/runtime test failure.


## ARM64 transition cancelled and reversible cleanup

Current decision2026-10-12: the user explicitly cancelled ARM64 migration, retained
AMD64 and authorized reversible removal of experiment-only installations. The ARM
comparison/dependency/OCR separation proposals above are archived investigations,
not ongoing plans or pending installation requests. Existing Gemma product code is
not rolled back. No further ARM migration work is scheduled by this record.

Ownership was checked against the installation/parity/static-preflight records and
actual pyvenv.cfg. The separate NuGet Python belongs only to the project experiment;
it is distinct from the pre-existing shared Python3.11 ARM64 installation, which
was preserved. Eleven candidate inventories totalled2,713,956,065bytes. Fresh
process executable/command-line checks found no candidate in use. All1,453 internal
reparse targets stayed within the candidate set; roots were not reparse points.
The two failed-build diagnostics inside the copied frontend were copied and hash
checked into this cleanup evidence folder before any operation.

| Exact target relative to C:/projects/ai-workshop | Logical bytes | Actual result |
| --- | ---: | --- |
| `.local-data/venvs/ai-workshop-arm64` | 906,793,483 | Recycled; original path absent |
| `.local-data/runtimes/cpython-3.13.15-arm64-nuget` | 45,980,720 | Recycled; original path absent |
| `.local-data/project-agent-work/arm64-env-20261012/mypy-cache` | 10,502,404 | Recycled; original path absent |
| `.local-data/project-agent-work/arm64-env-20261012/pythonarm64.3.13.15.nupkg` | 13,762,836 | Recycled; original path absent |
| `.local-data/project-agent-work/arm64-parity-20261012/corepack` | 36,725,865 | Recycled; original path absent |
| `.local-data/project-agent-work/arm64-parity-20261012/frontend` | 618,828,142 | Preserved: Shell recycle E_ABORT |
| `.local-data/project-agent-work/arm64-parity-20261012/node-runtime` | 94,262,724 | Recycled; original path absent |
| `.local-data/project-agent-work/arm64-parity-20261012/node-v24.18.0-win-arm64.zip` | 33,361,856 | Recycled; original path absent |
| `.local-data/project-agent-work/arm64-parity-20261012/pnpm-cache` | 255,207,461 | Recycled; original path absent |
| `.local-data/project-agent-work/arm64-parity-20261012/pnpm-store` | 610,387,538 | Recycled; original path absent |
| `.local-data/project-agent-work/ocr-arm64-wheel-preflight-20261012/paddlepaddle-3.2.2-cp313-cp313-manylinux2014_aarch64.whl` | 88,143,036 | Recycled; original path absent |

Ten targets totalling **2,095,127,923bytes (~1.95GiB)** were moved to Windows Recycle
Bin. The **618,828,142byte (~590.16MiB)** frontend inspection copy remains in its
original location: Shell returned E_ABORT(0x80004004). No permanent-delete fallback
or unsafe retry was used. A new scan confirmed all30,819 regular files,1,452 links
and aggregate bytes remained equal to the pre-operation inventory. The exact reason
for the Shell abort is unconfirmed; it is not reported as a policy verdict or as
permission to bypass safeguards. This is the sole cleanup blocker.

The task-local IFileOperation helper used RECYCLEONDELETE/ADDUNDORECORD plus a
PreDeleteItem callback rejecting non-recycle and unexpected-path operations. A
small task-created canary first verified the mechanism. Its sandbox attempt aborted;
the supported approval flow allowed the recycle-only operation. Current-volume
Recycle Bin settings were read, not modified: NukeOnDelete0, MaxCapacity26,389MiB,
and only the46byte canary was present before removing experiment targets. The
operation checked spare capacity and preserved pre-existing recycle entries.
No Recycle Bin emptying or permanent deletion occurred.

Recovery: open Windows Recycle Bin, select the experiment items by the original
locations in the table, and choose Restore. Restore related runtime/venv or Node
items together to recover their original dependency paths. The ten exact original
and `$Recycle.Bin` paths are in `recycled-items.json`; `preservation-after.json`
confirmed each source absent, recycled item present and a matching Shell entry.
The blocked frontend copy needs no restoration because it never left its location.
Recycling does not reclaim these bytes permanently. Observed host free space changed
by -48,381,952bytes during the task, which includes concurrent activity and is not
attributed to cleanup. No disk-space recovery is claimed.

Preservation checks: existing backend interpreter still reports Python3.13.15/AMD64
and150 distributions. Hashes of the AMD64 venv interpreter, AMD64 base interpreter
and pre-existing shared ARM64 Python3.11 matched. All15 baseline Python/Docker
processes remained at the same PID/executable path (six project Python processes,
nine Docker processes); none was terminated or restarted. All1,442 tracked product
source hashes matched. This verifies process/file preservation, not application
readiness, DB/ES health or full RAG acceptance. No model/import integration/health
endpoint test, install, service/DB/Docker/PATH/policy change, commit or push ran.

Documents and all diagnosis logs/JSON/reports/scripts were preserved. The new
cleanup evidence is `.local-data/project-agent-work/arm64-cleanup-20261012/`.
Temporary inspection failures (legacy path-length scan, JSON serialization) were
corrected without altering targets; the broad scan was stopped as our own tool
process. Independent read-only review confirmed candidate ownership/boundaries and
identified the two diagnostics to preserve. Product tests run0.

Final independent evidence/document review found no blocking errors. Seven-document
relative-link checks259 and scoped diff checks passed; Git status path/status set
remained unchanged. Actual Restore execution and service-functional readiness were
not tested; the recovery claim is based on verified Recycle Bin entries.


### Approved frontend-copy retry: preserved, not recycled

The user reauthorized retrying only
`C:/projects/ai-workshop/.local-data/project-agent-work/arm64-parity-20261012/frontend`.
The actual product `C:/projects/ai-workshop/frontend` was never an operation target.
Fresh inventory matched30,819 regular files,618,828,142bytes and1,452 reparse links;
all links resolved inside the inspection copy. No process executable/command line
referenced the exact target immediately before the API invocation. This check does
not exhaustively inspect open file handles. The original existed, with no matching
Recycle Bin item. CACHE_POLICY.md was unchanged.

Earlier diagnostic tracing identified the immediate E_ABORT: after root status
0x00270003(COPYENGINE_S_NOT_HANDLED), Shell requested a child-file delete with flags2,
without the recycle flag0x80. The safety callback rejected that request. Adding
FOF_WANTNUKEWARNING previously returned0x80270000(COPYENGINE_E_USER_CANCELLED).
Neither result establishes the underlying reason Shell could not recycle the root.
The612 long paths are a possible contributor, not a confirmed cause. No access-denied
or path-too-long HRESULT was observed; no permanent-delete consent was given.

This newly authorized attempt reused the same strict IFileOperation helper, with
RECYCLEONDELETE/ADDUNDORECORD/WANTNUKEWARNING and exact-root/recycle-only callbacks
unchanged. Its call did not return a result. The agent interrupted only its own
pending command via Ctrl+C(exit1); no attempt.json or new HRESULT was produced.
No dialog contents were observed and no UI approval was supplied. A subsequent
CIM query confirmed no process command line for the retry script remained. The
first post-query matched its own diagnostic process; a second query excluding
itself and assembling the search string separately returned no matches.
No user/service process was killed and no alternate deletion method was attempted.

Post-verification: original copy still present; regular-file count, link count and
aggregate bytes match the preflight exactly; matching Recycle Bin items0. Product
SHA-256 checks matched all1,442 baseline files, including404 actual frontend files.
These hashes cover the recorded product files, not every dependency/generated file.
Three preserved Python interpreter hashes matched and all15 recorded Python/Docker
processes retained their PID/executable path. The previous ten recycled items remain
in the Recycle Bin, with their original paths absent. No item was restored or moved
again. No additional logical bytes were recycled and no host free-space gain is
claimed. The remaining copy is still590.16MiB; its content was checked by counts and
aggregate size, not a full per-file content hash.

Next action, if the user wishes to investigate further: in Windows Explorer, select
only the exact inspection-copy path above and use ordinary Delete. If Windows says
it cannot recycle or requests permanent deletion, cancel and retain the copy; report
the displayed reason. Do not use Shift+Delete or empty the Recycle Bin. The existing
ten items can be restored through Recycle Bin > Restore using their recorded original
locations; the frontend copy needs no restoration because it remains in place.

Evidence: `frontend-followup/` retains earlier callback traces and
`frontend-approved-retry/` contains fresh preflight, exact retry script and final
file/recycle/process verification under the cleanup evidence directory above.
Product tests, application readiness, DB/ES health and actual Restore execution were
not run for this cleanup-only retry. Installation, policy, service, DB, product-code,
commit and push changes0. WORKBOARD and this log were the only tracked edits in this
retry; previously existing changes were preserved.


### User-reported copy removal confirmed

The user subsequently reported deleting the test frontend copy. A fresh read-only
check confirmed that
`C:/projects/ai-workshop/.local-data/project-agent-work/arm64-parity-20261012/frontend`
is absent. This supersedes the earlier preserved-copy status. No matching Recycle
Bin root item or item whose original location is within that copy was found; the
removal method and recovery availability are unconfirmed, not assumed permanent.
The agent performed no additional move, delete, restore or service/settings change.
The prior ten recycled items remain present, with their original paths absent.

All1,442 recorded product-file hashes, including404 actual frontend files, matched.
The AMD64 venv/base interpreter and pre-existing shared ARM64 Python3.11 hashes also
matched. The eight experiment task directories now contain only128 records/scripts
(8,264,780bytes, approximately7.88MiB); experiment venv/runtime parent directories
are empty. These records remain preserved. This is a residual-file inventory and
hash check, not a fresh application/service health test.
