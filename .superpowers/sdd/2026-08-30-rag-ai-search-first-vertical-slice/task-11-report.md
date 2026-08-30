# Task 11 Report: Comparable RAG Configuration Evaluation

## Status

DONE

Base revision: `caaef5c42fb130e0f2a21bd3032a218eaa6c7fd8`

## Delivered

- Added immutable, owner-scoped Evaluation Dataset snapshots, versioned Evaluation
  Policies, comparable Evaluation Runs, ordered exact configuration-version candidates,
  per-case raw observations, unrounded aggregate metrics, and runtime/component snapshots.
- Added mathematically tested Recall@K, MRR, binary nDCG@K, supported precision,
  false-grounding rate, character-span and multi-box union IoU, linearly interpolated
  P50/P95 latency, access-leak counting, and repeated-output reproducibility.
- Added the frozen 12-case public fixture covering exact/semantic/numeric/table,
  insufficient/conflicting evidence, company/personal/temporary/inactive access, and
  semantic/keyword highlighting cases.
- Added migration `0010_rag_evaluation` with evaluation persistence, immutable-input
  triggers, finite/bounded candidate constraints, durable run dispatch, and a database
  trigger that refuses `passed`/default promotion without a completed qualifying exact
  configuration-version result under the matching immutable policy and dataset.
- Replaced the application fail-closed placeholder with a policy-backed promotion path;
  the application gate and database trigger independently validate the evidence.
- Added at-least-once, token-fenced run claims and dispatch reconciliation. Search/model/
  Elasticsearch work happens outside database transactions; stale runs resume stored raw
  cases and skip already terminal candidates.
- Added Evaluation Policy and Evaluation Run create/list/detail APIs, OpenAPI coverage, and
  generated TypeScript contracts. Only response serialization rounds floats.
- Added exact configuration-version search resolution without changing normal latest-version
  search behavior.
- Added fixed BGE-M3 technical model/indexing/retrieval profiles: pinned revision,
  dense-only 1024 output, explicit sparse/ColBERT disablement, RRF `k=60`, no reranker,
  and no seeded user-visible Saved Configuration.
- Added an opt-in BGE-M3 model smoke test guarded by `AI_WORKSHOP_MODEL_SMOKE=1`; default
  verification neither downloads nor loads E5/BGE weights.
- Added real PostgreSQL/Elasticsearch integration that creates the BM25, E5, and BGE-M3
  Saved Configurations through `RagConfigurationService`, builds 768/1024 indices from one
  synthetic snapshot, and compares all three exact saved versions in one durable run.
- Raw access observations persist opaque source IDs and surfaces only; source titles,
  excerpts, queries, exception messages, and private content are not copied into audit rows.

## TDD Evidence

- Metrics/promotion modules were introduced from failing imports, then reached 25 passing
  focused tests.
- Frozen-fixture loading/tamper validation was introduced RED, then reached 27 passing
  focused tests.
- Workflow orchestration was introduced RED, then reached 28 passing focused tests.
- `0010` migration, durable dispatch, and evaluation API each failed first for missing
  revision/modules/routes, then passed against real PostgreSQL or the API contract.
- Multi-box IoU, exact-version resolver, BGE dense-only flags, worker UUID-only payload,
  stale-run idempotence, and database rejection of non-finite candidate metrics each had a
  focused regression assertion before/with the corresponding implementation.

## Verification

- Baseline before Task 11: `364 passed, 3 skipped, 1 warning`.
- Final backend suite on a clean PostgreSQL database migrated through `0010`, with real
  Elasticsearch available: `406 passed, 4 skipped, 1 warning`.
- Focused final migrations/durable execution/dispatch/real-search suite: `10 passed`.
- Focused evaluation/worker/API hardening suite: `42 passed, 1 warning`.
- Real BM25/E5/BGE same-snapshot test alone: `1 passed`.
- BGE smoke default behavior: skipped as designed; no model download occurred.
- `python -m ruff check src tests alembic`: `All checks passed!`
- `python -m mypy src/ai_workshop`: `Success: no issues found in 125 source files`.
- `uv lock --check`: `Resolved 124 packages` with no lock change.
- Fresh `alembic upgrade head`: succeeded from `0001` through `0010`.
- Fresh `alembic check`: `No new upgrade operations detected.`
- Deterministic backend OpenAPI export plus `openapi-typescript --check`: passed.
- `pnpm --dir frontend lint`: passed.
- `pnpm --dir frontend test -- --run`: `7` files / `10` tests passed.
- `pnpm --dir frontend typecheck`: passed.
- `pnpm --dir frontend build`: passed.
- `docker compose -f infrastructure/compose/compose.yaml config --quiet`: passed.
- `git diff --check`: passed.

## Deviations and Concerns

- `WORKBOARD.md` was intentionally not modified because the Task 11 brief explicitly locks
  it out of this commit, despite the repository-wide default workflow rule.
- The four default skips are existing opt-in/e2e/model-smoke boundaries. In particular, the
  BGE-M3 smoke remains opt-in to honor the no-default-download requirement.
- The only recurring warning is Starlette's upstream `TestClient` deprecation notice for the
  installed HTTPX compatibility layer; it does not affect Task 11 behavior.
- No LLM generation, reranker, sparse BGE output, ColBERT output, or default model download
  was added.
