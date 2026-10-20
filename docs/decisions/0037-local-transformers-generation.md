# ADR-0037: Local Transformers generation

- Date: 2026-10-11
- Status: implementation authorized; operational activation pending

## Decision

Add `local_transformers` as a distinct generation provider. A deployment uses
`local_model_ref` rather than an HTTP endpoint or Codex runner. The reference resolves
through typed server settings to a local snapshot directory, model ID, immutable
40-character revision, CPU execution with explicit float32 (default) or bfloat16 dtype and a configured input-token ceiling.
No model name or user path is built into business code. Loading is local-files-only,
with remote code disabled. Installation, downloads, license acceptance and real
inference require separate approval. Existing HTTP and Codex providers remain intact.

The process owns one reusable local model host and permits one inference at a time.
Blocking loading/tokenization/generation run outside the event loop. Cancellation and
deadline signal cooperative stopping and await actual worker completion, including
repeated cancellation. A native kernel cannot be forcibly interrupted by a Python
thread; completion may exceed the requested deadline. No next inference or successful
termination is reported before the worker exits. Load/inference failure discards the
cached model, allowing a later request to reload it. Shutdown drains owned work.

Schema v2 output is parsed strictly into existing claims and evidence IDs, followed
by the existing citation validator. Invalid/truncated JSON fails explicitly. Prompt
and output token counts are recorded. No alternative model or provider is selected
silently. Schema v3 numeric proofs are outside this slice.

## Boundaries and consequences

The new nullable deployment column and provider check constraints require a new
migration file; applying it or registering a live deployment is not authorized here.
Mock tests cover provider resolution, lifecycle, schema/citations, failure and
cancel-then-next-request. Real model quality, hardware compatibility and latency remain
unverified. Existing alias recovery, pending attachments and historical cancelled
turn recovery are separate blockers; changing the LLM does not resolve them.

## 2026-10-12 bounded compatibility amendment

The approved preflight adds explicit bfloat16 without automatic precision fallback.
The text context ceiling is read from the nested text configuration where present.
For Gemma 4 text requests, use separate system/user roles, disable thinking, and
parse the assistant final text through the tokenizer response template before the
existing strict JSON validation. Reasoning and tool responses are not persisted.
The Gemma 4 family is selected from model configuration, never a fixed model ID.
This does not add quantization, select an operational model, or authorize loading
weights. Native import checks and mock coverage cannot establish real inference
compatibility, memory consumption or quality.
