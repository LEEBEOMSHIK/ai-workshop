# Local Transformers Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task.

**Goal:** Add a directly loaded local generation provider compatible with the RAG conversation pipeline.

**Architecture:** Typed local model references resolve to a reusable process-owned worker. Deployment contracts distinguish local inference from HTTP and Codex execution.

**Tech Stack:** Python 3.13, Transformers/PyTorch (lazy imports), asyncio, pytest, SQLAlchemy.

**Spec:** [ADR-0037](../../decisions/0037-local-transformers-generation.md).

## Global Constraints

- No commit/push, applied migrations, DB/service/security changes or external inference.
- No model download/install/license acceptance/real inference without separate approval.
- Preserve pre-existing changes and verify file hashes before writing.
- No fake endpoint, implicit fallback, sensitive test fixtures or hardcoded model ID.

## Review Focus

- Repeated cancellation must not release a worker still executing native code.
- Failed loading/inference must permit a subsequent clean request.
- Resolver recreation must reuse the same process-owned model.
- Unsupported schema or oversized prompts must fail explicitly.
- Local configuration must not permit network model loading or remote custom code.

### Task 1: Deployment contracts

Files: deployment domain/API/repository/models, provider catalogue/policy, migration,
generated frontend contracts and focused tests.

Interfaces: `ProviderKind.LOCAL_TRANSFORMERS`; nullable `local_model_ref: str | None`.
Local deployments require the reference and prohibit endpoint/runner/secret/external transfer/retries.

- [x] Write and run failing contract tests.
- [x] Implement domain/storage/API contracts and an unapplied migration.
- [x] Run focused tests, static checks and offline migration validation.

### Task 2: Local worker and generation adapter

Files: `generation/local_transformers.py`, `generation/local_model_host.py`, focused unit tests.

Interfaces: `LocalModelSpec` typed configuration; `LocalModelHost` owns one loaded model;
`LocalTransformersRuntime(deployment, spec, host)` implements `GenerationRuntimePort`.

- [x] Write failing tests for reuse, concurrent admission, cancellation/deadline and failure recovery.
- [x] Implement an injectable synchronous engine and local-files-only Transformers backend.
- [x] Test schema v2 parsing, contextualization, token accounting and unsupported schema.
- [x] Run unit tests, Ruff and strict typing with mocks only.

### Task 3: Integration and independent verification

Files: settings, runtime resolver, API dependency/lifespan, tests, worklog and WORKBOARD.

- [x] Test named reference resolution and shared host reuse before implementation.
- [x] Integrate local reference settings, resolver and host shutdown.
- [x] Run relevant generation/conversation/contracts tests and independent review.
- [x] Record actual checks, unrun operational checks, model candidate and approval boundaries.

Results and remaining operational/uv validation blockers:
[worklog](../../worklogs/2026-10-11-local-transformers-generation.md).

Commits are omitted because the user explicitly prohibited them.
