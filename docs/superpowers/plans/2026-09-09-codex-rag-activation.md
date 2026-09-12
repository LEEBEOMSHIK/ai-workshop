# Codex RAG application activation implementation plan

> Agentic workers: use superpowers:subagent-driven-development, TDD, and task-scoped independent review.

**Goal:** Let the owner configure Codex in the administrator UI and test actual grounded conversational RAG in the existing domain conversation.
**Architecture:** Reuse the reviewed request executor and SQL approval/slot adapters. Registration is not readiness. Explicit exact-configuration synthetic verification writes body-free proof; passive readiness and per-call authorization gate all subsequent generation.
**Tech Stack:** Existing Next.js/React/TypeScript and FastAPI/Python/PostgreSQL. No new package.
**Spec:** `docs/superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md`; prerequisite `2026-09-09-codex-request-runtime.md` Tasks1/2.

## Global constraints

- Existing dirty main only; preserve user changes, no worktrees/staging/commit/push.
- No automatic real model requests; health/GET/page mount are passive. Only main performs approved synthetic live verification.
- Owner/development only, explicit public/synthetic input attestation, exact revision preapproval and current installation/workspace/configuration approval.
- Requested model and observed model are separate. Codex unknown is allowed only under the approved exception; known mismatch and other providers remain strict.
- No fake endpoint, API key requirement for Codex, runtime model fallback, evaluated/pass/default fabrication, or automatic private-data approval.
- No request/body/draft/event/reasoning/auth/host path logs. SQL tests use guarded disposable databases and `--tb=no`.
- Implementers cannot spawn reviewers or other subagents. Main owns integration, user DB setup, WORKBOARD and final testing notice.

## Task 1: Explicit connection verification, passive readiness and stage audit

Files (generation = `backend/src/ai_workshop/labs/rag/generation/`):
create `generation/codex_verification.py`, `generation/codex_verification_repository.py`,
`generation/codex_verification_models.py`, `generation/codex_composition.py`, `generation/codex_admin_api.py`;
modify `generation/codex_execution.py` only for injected body-free stage audit and `generation/readiness.py` for Codex passive proof branch;
modify `generation/domain.py`, `deployments/service.py`, `deployments/schemas.py`, `deployments/api.py`,
`configurations/schemas.py`, `configurations/domain.py`, `configurations/service.py`, `models/domain.py` only where exact new disclosure/model contracts require;
`configurations/api.py` only for authenticated actor dependency propagation into passive readiness;
`backend/src/ai_workshop/config.py` and `backend/tests/unit/test_config.py` for typed Codex mutation allowed origins, without coupling to Publishing settings;
register new model/router in `shared/model_registry.py`, `main.py`, `alembic/env.py`;
`generation/codex_approval_repository.py`, `generation/codex_slot_repository.py` and
`generation/codex_verification_repository.py` safe decorators: annotation/import-only
correction to expose their actual async Coroutine return rather than widen to Awaitable;
do not bypass adapter/Protocol validation with whole-object casts or change runtime behavior.
create migration `backend/alembic/versions/0029_codex_verification.py` down_revision0028.
Tests: new unit `test_codex_verification.py`, `test_codex_admin_api.py`, integration `test_codex_verification_storage.py`;
update affected existing deployment/configuration/generation/model tests and contract OpenAPI.

Public contracts:
```python
# generation/domain.py: existing external-generation-v1 kept, Codex receives distinct version
CODEX_GENERATION_DISCLOSURE_VERSION = 'codex-external-generation-v1'

class CodexInputApprovalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    classification: Literal['public', 'synthetic']
    consented: StrictBool
    disclosure_version: str = Field(min_length=1, max_length=120)

# GET /api/v1/admin/rag/codex-runners: safe metadata only, no execution
# [{runner_ref, cli_version, local_preflight_passed, safe_error_code,
#   limits:{timeout_seconds,max_output_tokens,max_concurrent},
#   prompt_options:[{answer_ref,context_ref,response_schema_version,
#      control_ref,control_text,answer_text,context_text}]}]

# POST /api/v1/admin/rag/configuration-versions/{version_id}/codex-verify
# body: {consented:true, disclosure_version:'codex-external-generation-v1'}
# response: {ready,safe_error_code,requested_provider_model_id,
#   observed_provider_model_id,model_identity_status,checked_at}

# GET same .../{version_id}/codex-status: same proof/status, no model request
# POST /api/v1/admin/rag/codex-evidence/{revision_id}/approval
# body: {classification:'public'|'synthetic', content_sha256:<displayed current revision hash>}
# DELETE same approval: explicit revocation through existing source method
# GET /api/v1/admin/rag/codex-evidence?workspace_id=UUID
# revision metadata+current approval only, authorized scope, no body or host storage path
```

- [ ] RED: absent/stale/failed/mismatch proof not ready; exact successful proof+observedNone ready only Codex/development; altered CLI/config/model/prompt/schema invalidates proof; GET/health makes zero executor calls. Two configurations sharing one profile must not share verification: verifying A leaves B unready. Correct Codex/HTTP disclosure saves and each cross-provider wrong version rejects before persistence.
```python
assert not await verification.is_ready(context, profile)
await verification.verify(context, profile)  # fake executor, exact source/gate used
assert await verification.is_ready(context, profile)
assert executor.calls == ['contextualize', 'generate']
await verification.status(context, profile)
assert executor.calls == ['contextualize', 'generate']
```
- [ ] Implement verification on an already saved exact configuration with current external approval. Use server-owned synthetic question/bounded synthetic history and EMPTY evidence. Call coordinator directly with CONNECTION_CHECK context for each stage, parse respective schema and require complete strict stream/usage/termination/workspace cleanup. Generate must be insufficient with no evidence. Do not fabricate DB evidence revisions. This proves connectivity/schema, not grounded answered correctness.
- [ ] Store append-only verification attempts tied to exact profile/config/deployment, runner ref/fingerprint, CLI version/executable digest, requested/observed model, both control/task/schema metadata signatures, success/failure safe code/time and usage presence. Latest relevant failure invalidates prior ready. No raw body. Add durable body-free stage audit with context request/actor/config IDs, stage, prompt refs/versions/digests, CLI/settings/model metadata, outcome, latency, usage, safe workspace basename. Audit persistence failure fails execution rather than silently losing required records. Keep this logic behind a RAG repository, not API handler.
- [ ] Add passive `CodexPassiveReadiness.health` implementation backed by that exact proof plus current registry. Missing source/proof fails closed. General SqlAlchemyGenerationReadiness uses this branch only for Codex; HTTP logic unchanged. Extend ConfigurationService's GenerationReadinessPort and its callsite with exact configuration_version_id (and adapt test doubles), because profile_id alone cannot distinguish two configurations sharing a generation profile. Missing exact configuration must never reuse another configuration's Codex proof.
- [ ] Allow configured Codex registration only after typed registry read-only preflight and development environment. Preserve healthcheck_enabled=False, official CLI auth and no secret/endpoint. Existing health-check endpoint stays non-model for Codex and reads proof/status, never repurposes as paid verification. Admin/options readiness must use server proof, not `observed==requested` client reconstruction.
- [ ] Publish Codex-specific disclosure text covering OpenAI processing, question/history/evidence/service instructions, account usage, owner-only limited isolation; propagate its exact version into saved external approval and previews (no hardcoded old external version). ExternalTransferApprovalConfirmation must accept only named supported versions; save-time service must compare the submitted version with the resolved deployment's exact generation_disclosure version. Cross-provider disclosure substitution must fail. No readiness is granted by accepting disclosure alone.
- [ ] Add optional `requested_provider_model_id`, `observed_provider_model_id`, `model_identity_status` (`unknown|verified|mismatch`) fields to execution snapshot/preview for Codex, plus disclosure_version transport. Existing non-Codex fields/labels stay unchanged and new identity fields may remain None. Support LLM ModelDefinition config `{'model_identifier': <nonempty model identity string>}` as provider-independent identity for deployment-bound profiles; execution provider/data policy belongs to Deployment, not a fabricated local-only config. Preserve existing valid legacy local definitions. ModelLab supported-model filter/details must understand both shapes.
- [ ] Add safe runner/evidence/verify/status owner endpoints with authorized scope lookup. Existing origin guard is Publishing-specific, not shared: new Codex mutations require exact Origin in typed codex_allowed_admin_origins, x-codex-request:1, and application/json (including DELETE). Validate named origin settings strictly, retain local defaults consistent with the existing app, and leave Publishing/CORS behavior unchanged. Test missing/wrong origin, header and media type. Evidence approval accepts exact shown hash for stale detection, then source independently verifies current asset/hash/permission. Do not auto-approve documents when listing/uploading/asking.
- [ ] Run scoped unit/contract/type/lint and guarded SQL migration upgrade/downgrade tests; report/freeze for independent review.

## Task 2: Search and domain API composition

Files: `generation/codex_composition.py`, `generation/codex_admin_api.py` from Task1;
`generation/execution.py` only for an optional trailing observed_provider_model_id
on ProviderExecutionMetadata, preserving existing positional calls and HTTP checks;
`deployments/schemas.py` only for an optional safe runner_ref on owner admin/options
responses, linking saved Codex deployment versions to the existing passive runner catalog;
`generation/codex_runtime.py` for preserving reviewed new audit/verification safe error codes through its existing whitelist,
and annotation-only correction of its async safe decorator return for GenerationRuntimePort conformance;
`generation/codex_execution.py`, `generation/codex_verification.py` and its repository only for optional audit-only public correlation linkage (existing JSONB, no new migration);
`search/service.py`, `search/api.py`, `search/schemas.py`, `domains/api.py`, `domains/schemas.py`,
`domains/repository.py` for authenticated actor propagation into its configuration-readiness adapter;
create `generation/codex_http_lifecycle.py` for disconnect-cancellation helper if existing transport lacks one.
Tests: new `backend/tests/unit/labs/rag/search/test_codex_search.py`,
`backend/tests/unit/labs/rag/generation/test_codex_http_lifecycle.py`, guarded integration
`backend/tests/integration/labs/rag/domains/test_codex_conversation.py`; affected existing search/domain tests.

Interfaces:
```python
# SearchRequest AND DomainSearchRequest
codex_input_approval: CodexInputApprovalRequest | None = None

class CodexSearchRuntimeFactory(Protocol):
    def create(self, *, context: CodexRequestContext,
        profile: GenerationProfile) -> GenerationRuntimePort: ...
```

- [ ] RED first-question and signed follow-up tests with real SearchApplicationService, fake process and real isolated SQL authorization/slot repositories: no classification/consent, stale disclosure, member/production, mixed unapproved evidence and revoked policy result in zero CLI launches; valid contextualize and generate use independent consumed approvals.
- [ ] Inject optional Codex runtime factory into search service; only Codex uses it, never prebound generation_runtime shortcut. Construct server request context from authenticated actor, fresh correlation/request ID, resolved immutable config, selected spaces and validated request attestation. Preserve history signatures/folder scope and all configured-space policy checks. Non-Codex resolver/ports/signatures stay unchanged.
- [ ] Pass attestation unchanged through DomainSearchExecutor conversion. Codex health identity branch allows observedNone only for named provider through owner/development factory; known mismatch still errors. Keep retrieval, optional reranker, semantic v2 parsing, numeric/source citation validator and assistant signing unchanged.
- [ ] Both search POST handlers reuse the existing Codex Origin/header/JSON guard when codex_input_approval is present. No-attestation HTTP requests are unchanged; Codex without attestation still fails before launch in the service. Test both handlers for invalid/missing Origin, marker header and content type. This aligns explicit Codex mutation boundaries; current FastAPI strict-content-type already rejects missing-type JSON, so do not describe this as a demonstrated exploit.
- [ ] Compose dedicated snapshot/consumption/slot/audit pools with correct lifetime using request dependency; avoid user transaction locks leaking across cleanup or durable consumption rollback. No process singleton retains actor/context. Clear ownership: registry immutable server setting, runtime request-scoped, source current SQL sessions.
- [ ] Keep the fresh internal Codex request_id separate from the public correlation UUID, which middleware can accept from a client header. Capture normalized public correlation once in request composition and pass optional UUID audit-only metadata through executor/stage builder to CodexStageAudit; persist in existing details JSONB. Both stages share it; repeated headers still get distinct fresh internal IDs. It never influences permissions, consent, signatures, slots or actor. Non-HTTP context may use None; no per-stage fallback UUID. Any diagnostic lookup must restrict actor/config scope and disambiguate by internal request_id. Existing error/header contracts remain unchanged.
- [ ] Detect actual HTTP disconnect and cancel owned search task; await coordinator/gate/worker cleanup before releasing dependencies. Fake ASGI test proves browser disconnect requests exact worker cancellation, normal successful requests do not spuriously cancel, and repeated cancellation never returns capacity before cleanup.
- [ ] Preserve explicit safe Codex denial/full-capacity/timeout/event/schema/cleanup/audit error codes through runtime and search API whitelists for troubleshooting, no raw exception chains; do not collapse every issue to an indistinguishable generic error. Include the new codex_audit_required code: the Task2 substrate whitelist predates required audit. No model fallback or auto-retry.
- [ ] Return requested/observed metadata in Codex answer preview/snapshot, not a fabricated verified model. Never make anonymous/member execution possible merely because a domain preview is visible. Include safe owner-only applicability in preview; actual source remains authoritative.
- [ ] Expose only the validated logical Codex runner_ref on owner deployment admin/options responses, None for HTTP. This lets the UI match a saved deployment to current server runner preflight for draft setup. No physical path/secret/endpoint exposure, new DB field, inferred execution readiness or model call.
- [ ] Carry actual per-stage Codex event observed_model through the optional execution metadata field, validate bounded safe identity when present, and map the actual generation value to the response snapshot. Requested model or past verification proof must not fill a missing current-call observation. Existing provider metadata construction and strict HTTP identity remain compatible.
- [ ] Run scoped tests/type/lint/OpenAPI and independent review, then export frontend API types via existing project command.

## Task 3: Administrator and conversation controls

Files under `frontend/src/features/rag/`: models `api.ts`, `ModelLabPage.tsx`, `DeploymentRegistry.tsx`,
`DataPolicyPanel.tsx`; create `models/CodexDeploymentForm.tsx`, `models/CodexEvidenceApproval.tsx`;
configurations `ConfigurationBuilder.tsx`, `SavedConfigurationList.tsx`, `api.ts`;
small guided Codex generation-profile form and exact-configuration verification panel in existing features if needed;
conversation `ConversationPage.tsx`,
`ProcessingDisclosure.tsx`, `ConversationAnswer.tsx`, `api.ts`; search `SearchPage.tsx`, `api.ts` (conditional Codex marker header only);
generated `frontend/src/shared/api/schema.d.ts`, existing scoped styles only. Co-located tests for each changed behavior.
Shared `search/EvidenceAnswer.tsx` only if that existing renderer owns the promised identity display.
Also `frontend/src/app/page.test.tsx`: correct the independently diagnosed stale focus-recovery button assertion; preserve the approved automatic initial movement behavior, no home implementation change.
`frontend/src/features/rag/domains/DomainPickerPage.test.tsx`: update existing provider disclosure_version fixture fields required by the exported API contract; no domain-picker behavior change.

- [ ] RED UI tests: no auto-verify on mount, no runner paths/auth input, model identifier editable and saves immutable new version, explicit verify sends consent/version and exact configuration, requested vs observed unknown displays separately, missing/private classification prevents send, per-question consent resets, reply failure preserves retry question without automatic resend.
```tsx
expect(screen.getByText('실제 모델: 미확인')).toBeVisible();
expect(verifyConnection).not.toHaveBeenCalled();
await user.click(screen.getByRole('button', {name:'합성 입력으로 연결 검사'}));
expect(verifyConnection).not.toHaveBeenCalled(); // explicit confirmation not supplied
```
- [ ] Implement Codex registration with server-listed runner refs/limits/prompt assets, existing LLM model definitions, editable requested model ID and display name; never hardcode user's selected model in business code. Registration/changes create immutable deployment/profile versions. Read-only control/answer/context prompts and limitations visible. Normal HTTP registration/status controls unchanged.
- [ ] Do not display unsupported CLI sampling parameters as applied. Current shared profile has a temperature field, but this Codex command does not transmit temperature; label it CLI-managed/not directly configurable for Codex. Timeout and output acceptance budget are enforced by the application; do not describe the latter as a guaranteed provider billing/token-generation ceiling.
- [ ] Permit Codex generation profile and configuration DRAFT save after local preflight even before live verification (break configuration→verify dependency cycle). Explain pending state; do not mark ready/pass/default. Explicit connection verification chooses a saved exact config and consent. Profile/runner/model changes require new proof. Provider selection in DataPolicyPanel must include Codex without replacing other approved providers silently.
- [ ] Expose exact document revision public/synthetic approval/revocation under admin with revision/hash/name context and warning; no auto-classification. Use authorized workspace selector. Keep user uploads private unless explicitly approved here.
- [ ] Explain the existing terminal revocation contract before the action: a revoked exact revision cannot be reapproved. Do not render it as a reversible switch or fabricate a new asset revision; retain existing backend authority.
- [ ] Conversation shows Codex disclosure and required public/synthetic selector covering current question and included history. Send `codex_input_approval` to server; reset consent after every send, scope/model/domain change and retry. No provider-specific form on non-Codex conversations. Cancellation continues AbortController and server disconnect cleanup.
- [ ] Codex-attested search API wrappers include x-codex-request:1 and JSON, matching the administrator mutation guard. Browser supplies Origin. Do not add this requirement to other providers or expose host settings in the browser.
- [ ] Display safe failure cause/correlation metadata and requested/observed model separately; no draft or raw model trace. Preserve existing citation/highlight panels, domain-first navigation, layout and public AI Lab behavior.
- [ ] Run relevant Vitest/TypeScript/ESLint and independent UI/API contract review.

## Main-owned user testing gate

- [ ] Confirm exact user DB migration version, apply only reviewed new migrations; preserve documents/indices/accounts, no reset.
- [ ] Configure physical CLI/approved dedicated request root through ignored local typed settings; no auth-file reading/copy. Restart only identified local app processes, not all Python/Node or infrastructure.
- [ ] Through normal owner service/UI create requested model/deployment/profile and saved compatible Hybrid configuration; current-policy approval explicit, no private document transmission. Bind existing asset-management domain only after real readiness/evaluation evidence.
- [ ] Before persistent test-data registration, obtain explicit retention approval: current evaluation snapshots retain text and immutable evidence approvals prevent ordinary deletion; document/workspace deletion UI is absent. A retained small synthetic reference corpus and required history must be explicitly approved, not treated as disposable temporary files. Otherwise stop user-DB fixture creation and use only separately authorized disposable E2E isolation, which does not prove user-DB readiness. Keep user uploads untouched.
- [ ] Run actual synthetic connection verification and actual document question→grounded answer→citation/highlight→signed follow-up→insufficient→cancel/failure E2E with approved material. Clean owned temporary runtime files under the project policy. Never force evaluation state to passed or claim historical PASS proves usable evidence after corpus removal.
- [ ] Verify administrator model-change flow remains available and actual model label unknown is clear. Update WORKBOARD/runbook with tested URL/sequence, known limits and final evidence. Only then ask user to test.
