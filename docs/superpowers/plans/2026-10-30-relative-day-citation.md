# Relative-day Citation Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the implementation with independent verification. Repository/user instructions govern preservation and approval; no commit or cleanup requested.

**Goal:** Accept source-defined business-day paraphrases while rejecting unsupported combinations.

**Architecture:** Keep schema1/2 lexical validation; add a pure relation helper only for missing business-day values. Reuse GroundingEvidence provenance and PDF positions without provider/model-specific rules.

**Tech Stack:** Python, pytest, Ruff, Mypy, existing activated Conda.

**Spec:** [approved task boundary and implementation design](../specs/2026-10-30-relative-day-citation-design.md).

## Global constraints

- Preserve settings, stored results, schema3, exact_values and current authorization.
- Model calls and external data transfer: 0. Replay saved public outputs only.
- Current checkout has substantial prior work; use current checkout with before hashes, do not reset, stage, commit, or remove caches.
- Root: integration, docs/WORKBOARD, existing-environment rollout and issue history. Implementer: validator/helper/unit regressions. Independent verifier: isolated verification artifacts and read-only code review.

## Review focus

- Uncited definitions or a different source identity must never supply values.
- Adjacent lines must not join across missing, reordered or overlapping ranges.
- A different product column or row must not supply the claimed period.
- Negated/conflicting definitions or changed anchor/sign/unit/start point must fail closed.
- New replay acceptance must not rewrite historical validation or imply general semantic correctness.

## Task 1: Restrictive relation support

Files: `backend/src/ai_workshop/labs/rag/generation/citation_validation.py`, a focused helper in the same module, `backend/tests/unit/labs/rag/generation/test_relative_day_citations.py`.

- [x] Reproduce the missing `(영업일,2)` from both saved Terra outputs; write positive and adversarial source/claim tests and observe RED.
- [x] Implement pure support helper receiving claim text and cited `GroundingEvidence`; only union proved missing business-day values before existing subset check.
- [x] Run new tests plus existing generation unit tests, strict Mypy and Ruff using activated approved interpreter. Preserve exact_values bytes.
- [x] Independent adversarial verification and code review; fix supported findings with regression evidence.

## Task 2: Replay, original runtime and records

- [x] Replay original 2 Terra + 2 Gemma output files without network/model calls; record exact text/ID equality and before/after validation separately from semantic verdict.
- [x] Confirm settings and original artifacts unchanged by SHA; update ADR0035 and RAG design describing the constrained relationship contract.
- [x] Check original API/process and active jobs before bounded restart if needed; use existing runbook, current DB and account. Verify health/ready and deployed code without generation.
- [x] Record result and limitations in worklog and authenticated ISSUE45 history; finish WORKBOARD with recent-complete list at most five.
