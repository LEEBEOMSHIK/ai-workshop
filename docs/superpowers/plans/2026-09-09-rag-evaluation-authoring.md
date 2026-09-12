# RAG evaluation authoring implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Execute one implementation task at a time with independent specification and quality review.

**Goal:** Make initial evaluation authoring usable in administrator UI and accept real passing evidence without replacing the global default.

**Architecture:** Extend existing RAG services and immutable evaluation execution. A bounded owner-scoped authoring context supplies actual evidence; server-side fixture construction revalidates that context. Separate exact-version evaluation acceptance from default promotion.

**Tech Stack:** Existing FastAPI/Python/SQLAlchemy/PostgreSQL, Next.js/React/TypeScript. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-09-rag-evaluation-authoring-design.md`

## Global constraints

- Existing dirty main only, preserve unrelated work. No worktree/staging/commit/push.
- All task artifacts under `.local-data/project-agent-work/rag-evaluation-authoring/` per AGENTS, not the skill's default scratch directory.
- Main owns integration, WORKBOARD, live browser/data setup and real model calls. Implementers never spawn agents.
- No user DB mutation, auth extraction, external transfer, automatic model execution or policy weakening in code verification.
- Owner and current workspace/configuration authorization precede body access. Return narrow no-store DTOs, no internal execution snapshot/paths/secrets.
- Existing metric v1, actual frozen index checks, immutable policies and PromotionGate remain authoritative.
- First authoring supports one candidate plus automatic BM25 with the same document-processing/indexing pair and actual projection/build identity. Reject incompatible pairs explicitly.
- No new migration. Evaluation acceptance leaves every default flag unchanged, uses exact version and explicit completed run, and is not generative-answer readiness.
- Tests use synthetic data, fake external ports and guarded isolated SQL databases only. Reports distinguish mock, SQL and actual live results.

## Task 1: Exact-version evaluation acceptance without default mutation

**Files:** existing `backend/src/ai_workshop/labs/rag/configurations/{domain,service,repository,schemas,api}.py`; focused new unit `backend/tests/unit/labs/rag/configurations/test_evaluation_acceptance.py`; API and guarded SQL coverage under existing `backend/tests/integration/labs/rag/configurations/`. Reuse evaluation policy mapping rather than duplicate a second policy gate.

**Interface:**

```python
# Owner POST /api/v1/rag/configurations/{configuration_id}/versions/{version_id}/evaluation-acceptance
class EvaluationAcceptanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluation_run_id: UUID

# Response contains configuration: SavedRagConfigurationResponse,
# evaluation_run_id: UUID, evaluation_policy_version_id: UUID.
# Corresponding service/repository method:
async def accept_evaluation(
    self, configuration_id: UUID, version_id: UUID,
    evaluation_run_id: UUID, actor_id: UUID,
) -> EvaluationAcceptanceResult: ...
```

- [ ] Write RED domain/API/repository tests before production edits. A successful real policy-bound candidate produces PASSED but retains its previous is_default. Failure, missing policy, wrong actor/version/run, incomplete metrics, K/metric/dataset mismatch are rejected. No fallback to another run. Exact older version remains exact when identity has a newer version.

```python
accepted = configuration.with_passed_evaluation(policy=policy, evidence=evidence)
assert accepted.evaluation_state is EvaluationState.PASSED
assert accepted.is_default == configuration.is_default
assert accepted.version_id == configuration.version_id
# SQL: capture all default IDs before request and compare after success/failure/retry.
```

- [ ] Implement `with_passed_evaluation` using existing PromotionGate and exact evidence/version equality. Existing `as_default` calls the shared validation then explicitly changes only its own default result, preserving its API behavior.
- [ ] Repository checks identity owner, locks exact version, joins only the requested candidate/run/policy with ownership and dataset binding. Build the existing complete PromotionEvidence and EvaluationPolicy, validate, then update evaluation_state only. Return accepted run/policy identities. No global-default update statement in this path.
- [ ] Service commits once; endpoint retains owner dependency, adds current readiness DTO without invoking a model. No client-controlled evaluated flag. Repeat exact valid request is idempotent.
- [ ] Run scoped unit/API tests and guarded SQL tests, mypy and Ruff. Use existing isolated DB fixture and inspect it before running; do not point test database settings at development data. Record commands/results and baseline-delta frozen patch/manifest in task-1-report.md for independent review.

## Task 2: Bounded safe authoring context and genuine initial run

**Files:** create `backend/src/ai_workshop/labs/rag/evaluation/authoring.py`, `authoring_schemas.py`, `authoring_repository.py`, `authoring_api.py`; modify existing evaluation composition/repository only for safely shared snapshot helpers; register router in `backend/src/ai_workshop/main.py`; typed limits in `backend/src/ai_workshop/config.py`; new focused unit/API/guarded SQL tests under evaluation and existing config tests.

**Public contracts:**

```python
# POST /api/v1/rag/evaluation-authoring/documents (read-only metadata)
# configuration_version_id, workspace_ids, cursor optional UUID, limit 1..100 default50.
# Return paginated authorized active version metadata/status only, no body or digest.
# POST /api/v1/rag/evaluation-authoring/preview (read-only operation)
class AuthoringScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configuration_version_id: UUID
    workspace_ids: list[UUID]
    asset_version_ids: list[UUID]  # explicit nonempty selected versions

# Response: scope_sha256, selected exact configuration/baseline metadata,
# documents[{document_id, asset_version_id, title, number, sha256}],
# evidence[{id, asset_version_id, projection_id, index_build_id,
#           text, element_id, page, start_char, end_char, bounding_boxes}],
# counts and complete=True. Actual identifiers only, no physical index name.

# POST /api/v1/rag/evaluation-authoring/runs -> existing EvaluationRunResponse (202)
# Input extends AuthoringScope with scope_sha256, draft_id (fresh client draft UUID),
# dataset_name, cases[{id,query,expected_answer_status,
#                     expected_evidence_ids, expected_highlight}],
# retrieval_k (1..50), repetition_count (2..5), retention_confirmed=True.
# IDs for new dataset/cases are draft idempotency identities only, never resource authority.
```

- [ ] RED tests cover member/anonymous, unowned config, unauthorized workspace, forged asset/evidence, nonactive/nonREADY source, profile mismatch, stale scope/build/permission, duplicate IDs, size cap, no side effects on preview, sanitized response and no-store.
- [ ] Add typed settings `evaluation_authoring_max_documents=20`, `evaluation_authoring_max_evidence_units=1000`, `evaluation_authoring_max_response_bytes=2097152`, `evaluation_authoring_max_cases=50`. Validate positive bounded limits. Reject oversize before returning any partial context; query count/limit before loading unbounded bodies.
- [ ] Build a dedicated adapter that validates selected ownership/access/subscriptions before reading text. Metadata list first allows selection even if other documents exceed cap or are not READY. Preview requires explicit selected active versions; scope must be exhaustive within the chosen frozen document corpus, not predicted retrieval. Lock/consistent-read the needed source/config rows in the existing source lifecycle order. Check processing/index pair AND exact actual READY build/projection matches for candidate and baseline, including the final persisted run snapshot rather than preview alone.
- [ ] Canonicalize context using actor/scope/config/baseline, immutable asset hash and active state, exact builds/projections/evidence text and positions. Exclude volatile current time from digest. Return allowed fields only. No raw internal `_execution_snapshot` response.
- [ ] On authored run, re-resolve same source scope and compare digest, validate all manual labels/locations and Unicode code-point spans. Expected evidence is a subset of the full scope; insufficient has no expected evidence/highlight. Build dataset schema1 on server with fresh/draft IDs, SHA256 query, complete source universe, actual document snapshot, actor caller and current as_of. Preserve draft identity across retry; resolve exact immutable existing dataset only if payload matches, never overwrite different labels.
- [ ] Retry contract: draft/case UUIDs are stable across network retries. Derive actual dataset/case UUIDs server-side using a named stable UUID5 namespace and authenticated actor+draft/case identity; client IDs cannot collide with another owner's real records. For an existing owner-bound dataset ID, reuse its original as_of and compare reconstructed canonical fixture bytes; reject changed name/labels/scope under the same ID. New datasets use name version1; same owner/name/version with different content returns safe409 requiring another name. Serialize same owner/draft creation with transaction-scoped locking and reuse original as_of after lock acquisition. Repeated explicit execution can create another run, but never another dataset for an identical draft. No exactly-once model/execution claim.
- [ ] Call existing `EvaluationApplicationService.start_run` with fixture and policy None in the same safe transaction. Reuse actual physical index validation and worker dispatch. Current authorization and scope snapshot must not race source supersession between preview revalidation and frozen run creation. Reject and roll back on drift.

```python
context = await repository.resolve_scope(actor_id, request.scope)
if context.scope_sha256 != request.scope_sha256:
    raise AppError("evaluation_authoring_stale", "Reload the evaluation sources.", 409)
fixture = build_fixture(context, request)
result = await evaluation.start_run(
    actor_id=actor_id, dataset_fixture=fixture, dataset_snapshot_id=None,
    evaluation_policy_version_id=None,
    configuration_version_ids=(request.configuration_version_id,),
    metric_definition_version=1, retrieval_k=request.retrieval_k,
    repetition_count=request.repetition_count,
)
```

- [ ] Existing fixture API remains compatible. No model or label inference. Run scoped tests/guarded SQL/mypy/Ruff, freeze task-2 report/patch. Main exports OpenAPI types with existing local `node openapi-ts.config.mjs` only after independent backend approval.

## Task 3: Guided administrator authoring and separate result actions

**Files:** create `frontend/src/features/rag/configurations/EvaluationAuthoringPanel.tsx`, `EvaluationCaseEditor.tsx`, `EvaluationPolicyForm.tsx`, scoped CSS and co-located tests; modify `ComparisonPanel.tsx`, `ConfigurationStudioPage.tsx`, `api.ts` and related tests; generated `frontend/src/shared/api/schema.d.ts` main-owned export.

**Interfaces:** consume generated DTOs/endpoints from Tasks1/2, existing create policy and run/poll APIs. Expose wrapper functions `previewEvaluationSources`, `startAuthoredEvaluation`, `createEvaluationPolicy`, `acceptConfigurationEvaluation`. Do not hand-maintain DTO copies or guess identifiers.

- [ ] RED tests render actual components with API fakes: no mount writes, context loading only on explicit button, late source responses ignored, source/config changes invalidate labels and run state, manual evidence selection, insufficient case rules, input retention, draft retention across studio tabs, sequential explicit initial-run/policy/policy-run actions, accept-only exactrun and no promote call.

```tsx
expect(previewEvaluationSources).not.toHaveBeenCalled();
expect(startAuthoredEvaluation).not.toHaveBeenCalled();
await user.click(screen.getByRole('button', { name: '근거 불러오기' }));
// Pick authoritative source evidence, never predicted search output.
// After mocked server acceptance:
expect(acceptConfigurationEvaluation).toHaveBeenCalledWith(config.id, config.version_id, run.id);
expect(promoteConfigurationDefault).not.toHaveBeenCalled();
```

- [ ] Build numbered sections inside existing comparison area. Show exact names/versions and fixed BM25 comparison, hide UUIDs in technical details. Pass existing workspace list and preserve authoring draft across tabs. Source preview supports local paging and accessible manual text-span selection, with code-point conversion and server validation. Unsupported coordinate authoring is explicit rather than fabricated.
- [ ] Label thresholds with range/unit explanations; require user-entered finite values, fixed leak0/reproducibility1 visible. Keep thresholds chosen before policy-bound run; no copy-from-observed metric button. Store returned snapshot/policy/run identities in state and reuse existing comparison polling/status UI.
- [ ] Distinct `이 버전의 평가 통과 반영` and `전체 기본값으로 지정` actions, exact version/run context, explicit pending/error/success. Only server successful response updates state. Refresh readiness; do not infer service ready from PASS. Existing default button behavior retained and not called by acceptance.
- [ ] Run relevant Vitest, tsc and ESLint. Main independently tests final frozen code and actual logged-in UI, with no security/privacy setting changes. Independent task and final cross-task reviews precede live testing claim.

## Main actual gate

- [ ] Confirm uploaded synthetic reference exists and has actual compatible READY indexes; never create fake completed rows. User has been asked to select the prepared local file in the existing upload UI.
- [ ] Use implemented owner UI with retained synthetic corpus, human-authored expected facts, explicit thresholds and real repeated evaluations. Keep policies and any external-transfer approval user-controlled.
- [ ] Accept passing exact evaluation without global default change, complete exact Codex verification and existing asset-management domain activation only after all gates.
- [ ] Verify real answer, citation/source highlight, signed follow-up, insufficient case and cancel/recovery. Record actual versus mocked evidence and notify user only when their test path works.
