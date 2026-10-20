# Gemma 4 E2B compatibility preflight

- Date: 2026-10-12
- Status: bounded code/mock verification complete; native import blocked; no operational activation
- Scope: existing-environment import diagnosis, explicit dtype, text context ceiling,
  final response parsing and synthetic tests. No installation, weight downloads,
  model loading/inference, database, service, security policy or Git publication changes.
- Roles: root owns requirements/RAG boundaries, diagnosis and documentation; adapter
  implementer owns Python/AI code and test design; independent reviewer owns review
  and cross-boundary mock verification. UI/DB/infrastructure/security policy changes
  are excluded. The role selector returned the eight corresponding mandatory roles.
- Existing uncommitted changes remain in place. Initial status, eight file hashes and
  pre-edit copies are retained under `.local-data/project-agent-work/e2b-preflight-20261012/`.

## Candidate evidence, not model selection

The user requested considering E2B first. The candidate is
`google/gemma-4-E2B-it`, BF16, Apache 2.0, with approximately 2.3B effective and 5.1B
total parameters including embeddings. The observed repository revision is
`3e22461f65e89153144f8adb70e3b8c2cc9845a7`.

- [Official model card](https://huggingface.co/google/gemma-4-E2B-it)
- [Observed revision](https://huggingface.co/google/gemma-4-E2B-it/commit/3e22461f65e89153144f8adb70e3b8c2cc9845a7)
- [Official configuration](https://huggingface.co/google/gemma-4-E2B-it/blob/main/config.json)
- [Weight pointer metadata](https://huggingface.co/google/gemma-4-E2B-it/raw/main/model.safetensors)

The pointer reports 10,246,621,918 bytes (9.5429 GiB), SHA-256
`2db5482b20d746879bb3ef79b5203e9075a2e2b98f54ec7c2f281c1477ddc550`.
Only public metadata was read; no weight bytes were downloaded. The repository file
listing displays approximately 10.3 GB including tokenizer and configuration files.
The exact-revision pointer URL was unavailable through the web tool; the byte count
and hash above came from the observed `main` pointer and must be bound to the pinned
revision again before any approved download.

## Memory calculation and limits

Previously approved hardware reads found Snapdragon X2 Plus / Windows ARM64,
23.5046 GiB physical RAM and 1.6091 GiB free at that observation. Free memory was not
remeasured in this step. Installed Python 3.13.15 and torch 2.13.0+cpu are AMD64;
Transformers is 5.16.1. This is not proof of ARM64-native execution or GPU/NPU support.

Using the BF16 file size, FP32 weight storage is approximately 20.4932 GB / 19.0858 GiB.
This is an estimate (the file includes a header), not measured process memory.
The configured token and per-layer embeddings contain
`262144 * (1536 + 35 * 256) = 2,751,463,424` parameters: exactly 5.125 GiB in BF16
or 10.25 GiB in FP32. Installed Transformers' bitsandbytes integration replaces
Linear modules, not these embedding modules.

Even assuming every remaining parameter could occupy just four bits, static weights
would be about 6.23 GiB with BF16 embeddings or 11.35 GiB with FP32 embeddings.
These optimistic estimates omit quantization metadata, other unquantized modules,
loading peaks, KV cache, activations and runtime overhead. They are not CPU memory
measurements or the Google GPU/TPU table. Last observed free RAM is insufficient.
No quantization support is added by this change.

## Existing-environment import diagnosis

A fresh, offline child process imported packages/classes only; it did not construct
a model. It used one compute thread, no bytecode writes, a 90-second watchdog and
20-second stack sampling. The directly launched process was also sampled for memory;
the Windows virtual-environment launcher reading is not aggregate interpreter memory
and is not used as a model-memory result.

| Stage | Observation |
| --- | --- |
| `import torch` | success, 3.003 seconds |
| `import transformers` | success, 3.907 seconds |
| `Gemma4ForConditionalGeneration` import | ImportError after 21.437 seconds |
| `AutoProcessor` import | not attempted after the error |
| Wrapper process | exited after 29.591 seconds; no watchdog kill |

The actual exception reports that application control policy blocked the DLL while
importing `_group_columns`. Static source identifies SciPy's
`_group_columns.cp313-win_amd64.pyd`; SciPy is 1.18.1 and scikit-learn is 1.9.0.
Transformers' candidate generator conditionally imports `sklearn.metrics.roc_curve`;
the stack sample shows the scikit-learn/SciPy dependency chain. The precise policy
rule and trust decision remain unknown. The earlier 30-second timeout alone did not
establish the cause; this fresh run establishes an actual import error.

No policy/ACL change, DLL replacement, package removal, optional-dependency hiding or
alternate privilege execution was attempted. Existing process/service state remains
untouched. The diagnostic wrapper's exit 0 only means it recorded the caught error.
Earlier 16x16 FP32/BF16 CPU matmul checks succeeded; they do not prove Gemma import or
inference compatibility.

## Implementation and validation

The bounded contract is recorded in [ADR-0037](../decisions/0037-local-transformers-generation.md).
`LocalModelSpec` accepts explicit `bfloat16` as well as the unchanged `float32`
default; loading uses the requested dtype without fallback. Context validation reads
`get_text_config()` / nested `text_config` and retains the configured input cap.
The official E2B configuration's `model_type=gemma4` selects separate system/user
messages and `enable_thinking=False`. Tokenizer `parse_response` receives unstripped
special tokens plus the rendered prompt prefix. Only final assistant text with empty
thinking/tool calls is accepted; unknown/malformed channels and parser errors become
`provider_invalid_response` without propagating generated text. The existing strict
schema/citation validation still runs. No model identifier is hardcoded.

Text-only requests keep AutoTokenizer/AutoModelForCausalLM: installed Transformers
maps `gemma4` to Gemma4ForConditionalGeneration, and ProcessorMixin.parse_response
itself delegates to tokenizer.parse_response. This avoids introducing multimodal
processor dependencies for the bounded text path. Actual pinned tokenizer parsing
and real loader compatibility remain untested.

Executed validation:

- New mock cases before implementation: 19 failed / 2 passed, reproducing missing
  dtype/context/role/response behavior.
- Implementer focused adapter, host and new Gemma 4 files: 55 passed.
- Root: `.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/generation
  tests/unit/labs/rag/deployments tests/unit/labs/rag/search/test_local_generation_pipeline.py -q`
  from `backend`: **1194 passed, 4 skipped, 1 existing Starlette deprecation warning**,
  36.60 seconds. This is a scoped regression run, not the whole repository suite.
- Root scoped strict Mypy: 2 production files passed. Ruff: 3 changed Python files
  passed. `git diff --check`: exit 0 (existing CRLF conversion warnings).
- Independent reviewer: 66 relevant adapter/host/resolver/error/pipeline mock tests
  passed, strict Mypy 2 production files and Ruff 4 files passed; no blocking finding
  for the official E2B `gemma4` configuration.
- Relative links in the three affected documents: 25 valid; AGENTS remains 126 lines.
- Eight-file baseline comparison: five intentionally edited files, three preserved;
  the new test and this worklog are the only new scoped deliverables. No unrelated
  cleanup, reset, branch switch, staging, commit or push was performed.

Counts overlap and must not be added. Full repository tests, real tokenizer/template
execution, model weights, inference, frontend, DB/service integration, ARM64-native
packages and measured model memory were not run. `gemma4_text` standalone extraction
and malformed third-party config getters are outside the official E2B path; review
noted these boundaries without extending this task.

## Remaining boundaries

The DLL policy block, native ARM64 compatibility, adequate free memory and real model
quality/latency remain unresolved. A permitted dependency-installation plan needs
explicit approval before changing Python/packages or creating an ARM64 environment;
installation approval does not authorize bypassing application control policy.
Weight download needs a verified revision/file manifest and approved cache location.
Actual loading/inference requires separate approval and bounded memory/context/output
limits. Existing alias/attachment/historical cancellation blockers are unchanged.
Per the issue-history rules, the DLL finding is retained here; no issue DB update was
performed because this task explicitly prohibits DB changes. Operational issue-history
reflection therefore remains pending.
