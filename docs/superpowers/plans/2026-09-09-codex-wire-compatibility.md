# Codex wire compatibility implementation plan

> Agentic workers: use subagent-driven-development, TDD and independent security review.

**Goal:** Accept actual Codex output through a compatible versioned wire schema without weakening semantic RAG validation.
**Architecture:** New Codex-only object schema and answer prompt; normalize validated wire results into existing RAG v2. Explicit observed usage fields remain bounded. Request model identity remains unverified by design.
**Tech Stack:** Existing Python 3.13 adapters, JSON/pytest; no new dependency.
**Spec:** `docs/superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md`, especially updated §7.

## Global constraints

- main only; no commits/worktrees/push, preserve dirty work. No user DB/settings/auth/UI changes.
- Only main performs explicitly approved synthetic actual CLI calls. Implementer tests are offline.
- User approved Codex personal-development identity exception. Never copy requested model into observed model or weaken other providers.
- Original v2 semantic schema and published prompts remain immutable; add a versioned Codex wire shape and new prompt.
- No arbitrary extra JSON/event fields or tool events accepted. No raw output/body/reasoning logs.
- Stop only for genuine external authority; continue through review and handoff into runtime integration.

## Task 1: Versioned wire schema and measured usage compatibility

Files (generation/ means backend/src/ai_workshop/labs/rag/generation/):
- Create `generation/codex_wire.py`, `generation/prompts/codex-answer-v3.txt`.
- Modify `generation/codex_prompt.py`, `generation/prompts.py`, `generation/codex_workspace.py`.
- Modify `generation/codex_events.py` only after main supplies the exact observed extra usage field.
- Tests: new `backend/tests/unit/labs/rag/generation/test_codex_wire.py`; existing test_codex_prompt,
  test_codex_workspace, test_codex_events and test_prompts under the same test directory.
- No edits outside this list without returning the exact needed contract to main.

Interfaces:
```python
CODEX_GROUNDED_WIRE_SCHEMA_V1: dict[str, object]
def parse_codex_grounded_wire_v1(content: str, *, allowed_evidence_ids: Collection[UUID]) -> GroundedGenerationResultV2: ...
```
New prompt ref `rag-codex-answer-v3`, context ref remains `rag-codex-contextualize-v1`.
GenerationProfile.response_schema_version remains semantic version 2. Prompt envelope distinguishes
the new wire ref/version from legacy grounded-generation-v2. Legacy profiles/assets stay unchanged.

- [ ] Write RED tests for strict object shape, answered nonempty claims, insufficient empty claims,
  invalid statuses, duplicate keys/IDs, unknown evidence, bool/float schema_version, extra fields.
```python
parsed = parse_codex_grounded_wire_v1(
    '{"schema_version":2,"status":"insufficient_evidence","claims":[]}', allowed_evidence_ids=())
assert parsed.status is GenerationStatus.INSUFFICIENT_EVIDENCE
assert parsed.generation is None
```
- [ ] Implement a single root object with all three required fields and additionalProperties=false.
  Claims items require text/evidence_ids, additionalProperties=false. Use ordinary types/enums/arrays;
  do not use oneOf/anyOf/uniqueItems/minItems schema keywords for this compatibility wire contract.
  Enforce stronger status/nonempty/uniqueness semantics in parser. Decode strict JSON before normalization;
  only validated empty claims in insufficient status may be removed. Pass normalized canonical JSON to
  existing strict v2 parser; never discard caller's extra fields or mask answered invalid claims.
- [ ] Add v3 prompt via registry; retain original prompt bytes. Wire prompt explicitly requires empty
  claims for insufficient status. build_codex_prompt accepts exact legacy and new profile pairs,
  picks trusted schema/ref/version accordingly. Contextualization contract stays unchanged.
- [ ] Workspace only accepts canonical schema bytes from its fixed trusted stage list, including the
  new Codex wire schema for GENERATE. Arbitrary caller schema still fails before filesystem writes.
- [ ] After main provides exact new usage metadata evidence, add only that named field with strict
  type/range/consistency handling. Unknown fields still fail. Output/input token budgets stay enforced;
  observed_model stays None. Add RED tests reproducing actual metadata shape and malformed variants.
- [ ] Run scoped pytest/mypy/Ruff, self-review and freeze. Report TDD/results/files and actual-vs-fake
  boundaries to `.local-data/project-agent-work/codex-wire-compatibility/task-1-report.md`.

Main separately checks offline regression and safe synthetic actual calls for answered/insufficient/
contextualized output, then independent review. No user readiness change in this task alone.

## Continuous handoff

After this reviewed contract, implement request-scoped authorization/runtime composition, exact
approval fingerprint binding, cross-process concurrency and cancellation; then admin/UI contracts and
actual current-domain configuration/E2E. Each owns its own execution plan once preceding interfaces
are frozen; this is staged execution of the approved whole goal, not a user continuation prompt.
