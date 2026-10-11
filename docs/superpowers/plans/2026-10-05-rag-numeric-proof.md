# 원문 기반 계산 근거 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자기 인용한 원문 숫자로 계산 결과를 재검증하고, 검증된 출처를 저장·조회·평가하는 schema3 생성 계약을 구현한다.

**Architecture:** Labs/RAG 안에 versioned 숫자 정책·서버 토큰 목록·결정론적 검증 코어를 분리한다. 기존 schema1/2·profile·JSON/digest·권한·서명은 유지하고, schema3 결과만 서버 audit에 연결한 검증 receipt와 provenance를 갖는다. 기존 주장 검토에 접힌 계산 설명을 추가한다.

**Tech Stack:** 기존 Python3.13/FastAPI/SQLAlchemy/PostgreSQL, Decimal, Codex CLI wire, Pydantic, Next.js/React/TypeScript, pytest/Vitest. 새 패키지를 설치하지 않는다.

**Spec:** [사용자 승인 명세](../specs/2026-10-05-rag-numeric-proof-design.md), [ADR-0036](../../decisions/0036-rag-source-backed-calculation.md).

**Status:** 명세·작성된 구현 계획 사용자 승인(2026-10-05), 현재 세션 직접 구현+독립 리뷰. Task1–6 코드·관련 검증 완료. 2026-10-06 승인된 Task7 본래0062→0063/API·새75회 평가 종료(64정상/11검증거절·의미63통과/1실패), 승격409·후보대기유지. 본래 브라우저는로그인·제어중단으로미검증이며 Task7 전체완료는아니다. [본래 반영·평가](../../worklogs/2026-10-06-rag-numeric-proof-rollout.md), [구현과 실행 판정](../../worklogs/2026-10-05-rag-numeric-proof-implementation.md).

## Global Constraints

- 정책 `source-numeric-proof-v1`: claim32개, claim당 계산32개, 출력당128개, 목록512토큰, 숫자30자리(소수 포함), 독립 Decimal precision64.
- `percentage_point_difference`: 명시 `%` 두 개의 왼쪽−오른쪽 → `%p`; `convert_krw_unit`: 원/만원/억원의 승수1/10^4/10^8 정확 환산만 허용.
- schema3 `text == text.strip()`, Unicode code point 반열림 span, 완전한 숫자+단위 토큰. Inexact/Rounded/Overflow는 거절한다.
- 반올림·환율·연산 사슬·연도/영업일 추론·맨 숫자의 헤더 상속·질문별 예외·모델 대체를 추가하지 않는다.
- 현재 허용된 선택 원문의 자기 인용만 사용한다. 계산 검증은 상품/기간/관계의 의미 평가를 대체하지 않는다.
- schema1/2 bytes/digest·과거 판정·프롬프트·활성 연결·후보 pending/defaultfalse·엄격한 정책과 별칭 open/frozen/receipt 경계를 보존한다.
- 원래 환경·DB·계정·자료와 현재 worktree에서 준비한다. 새 환경/DB/계정/worktree·정리·전체 integration 실행·미승인 migration/server 재시작·commit/push는 하지 않는다.
- 실패 초안·숫자·원문/답변·provider payload·비밀을 로그/문제 이력/산출물에 넣지 않는다. 단위 fixture는 새 합성 문자열과 제어된 ID만 사용한다.

## Review Focus

1. 같은 숫자와 같은 correlation이 반복돼도 요청 nonce·원문/주장 occurrence가 다르면 proof를 재사용하지 못한다(Task1/3).
2. emoji·줄바꿈·반복 값에서 Python code point와 JS UTF-16 offset이 섞여 다른 결과를 표시하지 않는다(Task2/5).
3. schema3 직접 값/근거부족에서 계산 목록 또는 envelope를 지워 schema1/2 승인으로 내려가지 않는다(Task4/5).
4. audit commit 뒤 권한이 철회되거나 취소돼도 답변·proof가 새 정상 결과로 저장/복원되지 않는다(Task3/4/6).
5. 아직0061인 본래 DB의 legacy 읽기를 새 ORM SELECT/자동 migration이 깨뜨리지 않는다(Task4/6).

## 공통 인터페이스와 파일 책임

아래 신규 파일/타입은 이 계획에서 정의할 대상이다. 기존 파일은 각 Task에 명시한다.

| 파일 | 책임·인터페이스 |
| --- | --- |
| `models/numeric_proof_policy.py` | `NumericProofPolicy` 불변 정책과 `resolve_numeric_proof_policy(config: Mapping[str, object]) -> NumericProofPolicy | None`. generation 설정의 `numeric_proof_policy_ref`로 정확한 정책을 선택한다. |
| `generation/numeric_proof_types.py` | stdlib와 정책에만 의존하는 `CalculationProposal`, `VerifiedOperand`, `VerifiedCalculation`, `SourceValueToken`, `SourceValueCatalogue`, `ValidatedNumericClaim`, `ValidatedGenerationPayload`, `NumericValidationBinding`, `ExpectedNumericContext`. domain/search/evaluation을 import하지 않는다. |
| `generation/numeric_catalogue.py` | `build_source_value_catalogue(evidence: tuple[GroundingEvidence, ...], *, request_id: UUID, configuration_version_id: UUID, profile: GenerationProfile) -> SourceValueCatalogue`. |
| `generation/structured_output_v3.py` | `parse_grounded_generation_v3(content: str, *, allowed_evidence_ids: Collection[UUID], policy: NumericProofPolicy) -> GroundedGenerationResultV3`. status/generation 구조는 v2처럼 구분한다. |
| `generation/codex_wire_v2.py` | `CODEX_GROUNDED_WIRE_SCHEMA_V2`, `parse_codex_grounded_wire_v2(content: str, *, allowed_evidence_ids: Collection[UUID], policy: NumericProofPolicy) -> GroundedGenerationResultV3`. wire2는 response schema3이며 기존 wire1을 수정하지 않는다. |
| `generation/numeric_validation.py` | `NumericProofValidator.validate(draft: StructuredGeneration, *, evidence: tuple[GroundingEvidence, ...], catalogue: SourceValueCatalogue, profile: GenerationProfile, request_id: UUID, configuration_version_id: UUID) -> ValidatedNumericGeneration`; wrapper의 payload는 성공만 존재하며 실패는 None이다. |
| `generation/numeric_proof_serialization.py` | `canonical_numeric_payload(payload: ValidatedGenerationPayload) -> bytes`, `numeric_payload_digest(payload: ValidatedGenerationPayload) -> str`, `rebuild_validated_numeric_payload(*, status: str, answer: str | None, claims: tuple[ValidatedNumericClaim, ...], binding: NumericValidationBinding) -> ValidatedGenerationPayload`. 순수 타입만 소비하며 search/evaluation을 import하지 않는다. 각 저장형의 DTO→순수 타입 변환은 그 저장형을 소유하는 모듈에서 한다. |
| `generation/numeric_proof_schemas.py` | frozen/closed `VerifiedOperandView`, `VerifiedCalculationView`, `NumericValidationBindingView`; domain 타입→DTO 변환. 검색과 평가가 같은 DTO를 사용한다. |
| `generation/numeric_validation_models.py` / `numeric_validation_repository.py` | 별도 immutable `rag_generation_numeric_validations` receipt, 원자적 audit+receipt 저장 및 현재 권한 아래 payload digest 대조. |

`CalculationProposal`의 필드는 operation/operand_token_ids/result_start/result_end다.
`VerifiedOperand`는 evidence/document/asset/projection/chunk/element ID, 원문 내 token_start/end,
원문 위치 char_start/end·page 및 명시 unit을 갖는다. 원문 숫자/문장을 audit에 복제하지 않는다.
`VerifiedCalculation`은 operation/result_start/end/ordered operands/policy_ref를 갖는다.

`SourceValueCatalogue`는 새 UUID nonce, config/profile ID, policy ref/digest, evidence/catalogue digest와
서버 토큰 tuple을 묶는다. token ID는 이 nonce와 exact evidence ID/span에 결속한다.
`ValidatedGenerationPayload`는 status/answer/exact claims+evidence IDs+verified calculations와
schema3/request/config/profile/policy/catalogue identity를 함께 canonical화한다. source metadata에
없는 상품 관계를 새 필드로 발명하지 않는다.

canonical payload의 identity 필드는 schema_version/request_id/configuration_version_id/
generation_profile_id/policy_ref/policy_digest/catalogue_digest로 고정한다. payload_digest 자체와
검증 이후 생성되는 validation_id/audit_id는 payload에 넣지 않는다. 따라서 audit 전 검증형과
저장 후 복원형이 동일한 bytes를 만들며 자기 해시를 포함하는 순환 정의가 생기지 않는다.

`NumericValidationBinding`은 validation_id/audit_id/request_id/configuration_version_id/
generation_profile_id/schema_version/policy_ref/policy_digest/catalogue_digest/payload_digest를 갖는다.
정상 schema3 answered와 insufficient 모두 binding을 보존하되, insufficient payload는 answer=null,
claims=[]이며 계산 검증 성공으로 표시하지 않는다. 기존 schema1/2는 새 필드를 None으로 생략한다.

`ExpectedNumericContext`는 actor/execution/request/config/profile/schema/policy와 현재 허용 원문
identity 집합을 갖는다. 복원 대상 turn/attempt/monitoring record의 신뢰된 execution ID로 audit와
서버 receipt·동결 프로파일을 먼저 조회해 만든다. 응답 JSON의 binding에서 역산하지 않는다.
execution 없는 일회성 검색 응답은 즉시 반환할 수 있지만 영속 대화/평가 복원의 기대 문맥으로 쓰지 않는다.

## 실행 명령의 기준

- 파일 경로의 `generation/`, `models/`, `search/`, `evaluation/`, `conversations/`, `executions/`는 모두 `backend/src/ai_workshop/labs/rag/` 기준이다. `main.py`는 `backend/src/ai_workshop/main.py`다. Task2에서 접두사 없는 Python 파일은 `generation/`, Task5의 `generative_*.py`는 `evaluation/` 기준이다. Task1/2의 접두사 없는 test 파일은 `backend/tests/unit/labs/rag/generation/` 기준이다.
- Python unit/정적 검사 cwd는 `backend`, 실행 파일은 `.venv/Scripts/python.exe`다. `.env`를 unit에 로드하지 않는다.
- 프론트 cwd는 `frontend`, 기존 `pnpm`과 `package.json` 명령을 사용한다.
- 단계별 RED/GREEN은 신규 test 파일을 작성한 뒤 실행한다. 지금은 계획이며 아직 존재하지 않는 테스트를 통과했다고 보고하지 않는다.
- 각 Task의 기존 회귀와 새 테스트를 통과하면 독립 검토 후 다음 Task로 간다. commit은 관련 파일만 root가 최종 인계 범위에 따라 결정한다.

### Task1: 불변 정책·원문 occurrence·요청별 토큰 목록

**Files:** 위 policy/types/catalogue 신규 파일; Modify `generation/domain.py`, `generation/profile.py`, `models/domain.py`, `models/context_evidence.py`.
**Tests:** Create `tests/unit/labs/rag/generation/numeric_proof_fixtures.py`, `test_numeric_catalogue.py`; Modify 기존 `test_profile_resolution.py`, `test_context_profile.py`.
**Interfaces:** 공통 표의 policy/catalogue/types를 생산한다. `GenerationProfile.numeric_proof_policy=None`, `GenerationRequest.numeric_catalogue=None`, `GeneratedClaim.calculations=()`, `GeneratedCitation.calculations=None`, `GenerationOutcome.numeric_validation=None`을 추가한다.

- [x] **RED:** `test_nonce_and_occurrence_bindings`, `test_bare_cell_invalid_literal_and_unknown_policy_rejected`, `test_catalogue_and_digit_limits`를 작성한다. fixture의 `NumericFixture`는 profile/evidence/catalogue를 가지며 `numeric_fixture(source_texts: tuple[str, ...], *, request_id: UUID | None = None) -> NumericFixture`가 합성 evidence와 profile을 만든다.
  ```python
  first = numeric_fixture(("rate 0.90%", "rate 0.90%"))
  second = numeric_fixture(("rate 0.90%", "rate 0.90%"))
  assert first.catalogue.tokens[0].token_id != first.catalogue.tokens[1].token_id
  assert first.catalogue.tokens[0].token_id != second.catalogue.tokens[0].token_id
  policy = first.profile.numeric_proof_policy
  assert policy is not None
  assert (policy.max_claims, policy.max_tokens, policy.max_digits, policy.precision) == (32, 512, 30, 64)
  ```
- [x] **RED 확인:** `.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/generation/test_numeric_catalogue.py -q`; 아직 미구현 함수/정책으로 FAIL한다. test import 오류만으로 실제 경계 재현을 대신하지 않는다.
- [x] **구현:** 정확한 policy ref/digest를 resolve하고 v3+policy/v6+evidence budget 조합을 검사한다. `models/context_evidence.py`의 contextual prompt 목록에 v6를 추가한다. 기존 exact_values 자체는 바꾸지 않고 동일 토큰 문법을 occurrence scanner에서 재사용한다. 513번째 토큰/31자리 입력은 전체 거절한다. nonce는 correlation 문자열과 구분한 서버 UUID이며 선택 source revision/text digest에 묶는다.
- [x] **GREEN/회귀:** 새 파일과 `test_profile_resolution.py`, `test_context_profile.py`, `test_citation_validation.py`를 pytest로 함께 실행한다. bare 숫자/불량 쉼표/날짜는 계산 operand가 되지 않고 기존 직접 값 결과는 그대로여야 한다.
- [x] **검토/인계:** stdlib-only types 의존성·legacy defaults·JSON 생략·limits와 새 nonce의 생성 소유권을 독립 검토한다.

### Task2: 엄격한 schema3·Codex wire2·프롬프트·준비 검사

**Files:** Create `generation/structured_output_v3.py`, `codex_wire_v2.py`, `prompts/codex-answer-v6.txt`; Modify `prompts.py`, `codex_prompt.py`, `codex_runtime.py`, `codex_execution.py`, `codex_workspace.py`, `codex_verification.py`, `codex_request.py`, `readiness.py`, `openai_responses.py`, `openai_compatible.py`.
**Tests:** Create `test_structured_output_v3.py`, `test_codex_wire_v2.py`; extend 기존 `test_codex_prompt.py`, `test_codex_runtime.py`, `test_codex_execution.py`, `test_codex_workspace.py`, `test_codex_verification.py`, `test_readiness.py`, provider 테스트.
**Interfaces:** Task1의 정책·catalogue와 common parser/wire signature를 소비한다. runtime의 `ProviderGenerationResult`는 기존 타입을 유지하며 schema3 StructuredGeneration을 보존한다.

- [x] **RED:** `test_closed_schema3_and_wire2_roundtrip`, `test_boolean_span_duplicate_keys_unicode_and_unknown_fields`, `test_every_codex_contract_uses_wire2`, `test_unsupported_provider_refuses_before_http`를 작성한다. schema3 text 앞뒤 공백·NUL/유효하지 않은 Unicode·중복/초과 claims·임의 식/승수·bool offset·NaN/지수 offset을 거절하고 emoji 앞의 code point span을 그대로 보존한다.
  ```python
  parsed = parse_codex_grounded_wire_v2(wire_json, allowed_evidence_ids={evidence_id}, policy=policy)
  assert parsed.generation is not None
  assert parsed.generation.schema_version == 3
  assert parsed.generation.claims[0].calculations[0].operation == "percentage_point_difference"
  assert refused_http_client.calls == []
  ```
- [x] **RED 확인:** `.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/generation/test_structured_output_v3.py tests/unit/labs/rag/generation/test_codex_wire_v2.py -q`; 미구현 계약 때문에 FAIL해야 한다.
- [x] **구현:** answered의 정확한 keys와 claim/calculation keys를 검증한다. insufficient wire의 빈 claims만 제거한다. v6+schema3+policy+budget만 wire2로 라우팅하며 v2-v5/schema2는 기존 경로다. 서버 목록을 승인된 evidence payload와 함께 보내고 Codex request nonce·승인 payload hash에 결속한다. 기존 `PreparedGeneration`에 `_prepare_generation`이 생성한 `CodexRequestContext.request_id`를 보존한다. catalogue와 runtime은 이 UUID를 사용하고 validator의 기대 UUID는 별도로 PreparedGeneration에서 받는다. synthetic verification은 자체 UUID와 빈 catalogue를 만든다. sandbox의 schema byte allowlist, stage audit parser까지 대응한다. 기존 runtime의 출력 크기 제한을 유지하고 닫힌 스키마 밖 중첩 객체는 거절한다.
- [x] **provider 거절:** schema3는 첫 버전에서 Codex만 지원한다. 준비/실행의 미지원은 안전한 `generation_schema_not_supported`로 명시하고 기존 generic readiness/HTTP 오류 매핑으로 전달한다. model/schema fallback 또는 proof 필드 버림은 없다.
- [x] **GREEN/회귀:** 새 parser/wire 파일과 위 기존 Codex/provider 테스트를 실행한다. legacy prompt/schema SHA·wire 출력·disclosure/승인·requested/observed 모델 경계는 바뀌지 않아야 한다.
- [x] **검토/인계:** 모든 schema2 하드 경로의 명시 분기와 외부 전송 승인 결속을 독립 검토한다. 실제 모델 호출/runner 신뢰 등록 변경은 하지 않는다.

### Task3: 결정론적 계산 검증과 검색·대화 최종 권한

**Files:** Create `generation/numeric_validation.py`, `numeric_proof_serialization.py`; Modify `search/pipeline.py`, `generation/citation_validation.py`(schema3 직접 호출 거절), `generation/execution.py` 및 provider 안전 코드 목록.
**Tests:** Create `test_numeric_validation.py`; extend `tests/unit/labs/rag/search/test_context_generation.py`, `conversations/test_final_authority.py`, `generation/test_turn_integrity.py`.
**Interfaces:** Task1 catalogue·Task2 parsed draft를 소비한다. `ValidatedNumericGeneration(outcome: GenerationOutcome, payload: ValidatedGenerationPayload | None)`와 canonical digest를 생산한다. `validated_numeric_abstention(*, catalogue: SourceValueCatalogue, profile: GenerationProfile, request_id: UUID, configuration_version_id: UUID) -> ValidatedNumericGeneration`은 빈 answered proof 대신 insufficient 계약 payload를 만든다. Task4의 audit/receipt port는 여기서는 recording fake로 검증한다.

- [x] **RED:** `test_signed_percent_difference_and_exact_krw_conversion`, `test_proof_only_supports_its_claim_occurrence`, `test_wrong_sign_unit_result_self_citation_or_request_rejected`, `test_limits_rounding_and_global_decimal_context`, `test_final_authority_after_audit`를 작성한다.
  ```python
  assert valid.outcome.status is GenerationStatus.ANSWERED
  assert invalid.outcome.text is None and invalid.outcome.citations == ()
  assert invalid.outcome.reason_codes == ("calculation_result_mismatch",)
  assert global_decimal_context == before_context
  assert revoked_result_saved is False
  ```
- [x] **RED 확인:** `.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/generation/test_numeric_validation.py -q`; 계산 검증 미구현으로 FAIL한다.
- [x] **구현:** 독립 Decimal context와 고정 arity/단위 승수로 재계산한다. 모든 proof를 검사하고 같은 token 중복/결과 span overlap/부분 숫자·다른 claim·다른 요청 참조를 거절한다. 직접 지원 집합은 같은 claim의 자기 인용에서만 얻고 proof는 지정 occurrence만 지원한다. 모든 값 조합 탐색이나 연산 사슬을 하지 않는다.
- [x] **pipeline 연결:** 승인/선택 후 고유 catalogue를 한 번 만들고 provider·validator에 같은 객체를 전달한다. 기대 request/config/profile/policy/evidence context는 실제 pipeline 입력에서 얻어 catalogue와 대조하며 catalogue에서 역산하지 않는다. catalogue 실패는 provider 호출 전 안전한 단계 오류로 기록한다. v3 검증을 legacy CitationValidator로 우회하지 않는다. insufficient는 schema3 계약 payload만 만들어 실제 계산 성공 표시를 하지 않는다. 실패/취소는 기존 cleanup과 초안 비노출을 유지한다.
- [x] **GREEN/회귀:** 새 numeric 검증·기존 citation/검색/최종 권한/서명 테스트를 실행한다. 표 단위 상속·날짜 추론을 거절하고 legacy v3 turn token의 내용/actor/config/scope 검증을 유지한다.
- [x] **검토/인계:** 산술 성공과 의미 정답을 구분한다. Task4가 연결되기 전 fake audit 테스트를 실제 SQL 성공으로 보고하지 않는다.

### Task4: 원자적 서버 검증 기록·복원 검사·DB 승인 분기

**Files:** Create `generation/numeric_validation_models.py`, `numeric_validation_repository.py`, `numeric_validation_sql.py`, `backend/alembic/versions/0063_rag_numeric_proof.py`; Modify `generation/audit.py`, `search/pipeline.py`, `generation/readiness.py`, `main.py`(ORM 등록).
**Tests:** Create `tests/unit/labs/rag/generation/test_numeric_validation_repository.py`, `tests/unit/labs/rag/evaluation/test_numeric_proof_gate_contract.py`; 기존 audit unit·최종 권한 테스트 확장. Task6의 rollback SQL 시험이 실제 DB 검증을 맡는다.
**Interfaces:** async `SqlAlchemyGenerationAuditRepository.add_validated(audit: GenerationExecutionAudit, validated: ValidatedNumericGeneration) -> NumericValidationBinding`는 현재 session에 두 행을 추가·flush하되 commit하지 않는다. pipeline의 `_record_audit`가 한 번 commit한 뒤에만 binding을 outcome에 연결해 반환한다. `SqlAlchemyNumericValidationRepository(session: AsyncSession)`의 async `expected_context_for_execution(*, actor_id: UUID, execution_id: UUID) -> ExpectedNumericContext | None`과 async `verify_binding(binding: NumericValidationBinding, payload: ValidatedGenerationPayload, *, expected: ExpectedNumericContext) -> None`을 정의한다. 현재 원문 권한도 이 session에서 재확인한다. 실패는 기존 안전한 AppError 매핑을 사용한다.

기대 문맥 조회의 None은 authoritative schema1/2에서만 반환한다. schema3의 누락/불일치 receipt는 오류로 거절한다. 먼저 기존 audit와 동결 프로파일을 읽어 분기하고 legacy에서는 새 테이블을 조회하지 않는다.

- [x] **RED:** `test_audit_and_numeric_receipt_are_atomic`, `test_failed_or_cancelled_before_commit_never_receipts`, `test_revoke_or_cancel_after_commit_preserves_audit_but_not_completed_result`, `test_changed_payload_actor_profile_or_policy_cannot_restore`, `test_whole_valid_receipt_from_other_execution_cannot_restore`, `test_schema3_cannot_downgrade_without_receipt`, `test_schema0061_legacy_queries_do_not_require_numeric_table`를 작성한다. SQL shape 검사는 실제 gate 통과를 대신하지 않는다.
  ```python
  assert binding.payload_digest == numeric_payload_digest(validated.payload)
  assert audit_commit_count == 1 and receipt_count == 1
  assert rolled_back_audit_count == rolled_back_receipt_count == 0
  assert legacy_numeric_table_queries == []
  ```
- [x] **RED 확인:** `.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/generation/test_numeric_validation_repository.py tests/unit/labs/rag/evaluation/test_numeric_proof_gate_contract.py -q`.
- [x] **구현:** audit와 receipt를 같은 session/transaction에서 저장하고 성공 commit 후에만 binding을 외부 결과에 반환한다. 기존 audit ORM에 새 SELECT 컬럼을 추가하지 않고 별도 table을 쓴다. receipt는 audit_id unique FK·request_id unique·execution_id nullable unique FK·schema3·정책/해시 형식·immutable update/delete trigger를 갖는다. audit의 actor/config/profile/execution과 exact payload SHA를 묶는다. 검증 실패/commit 전 취소·허용 불일치는 receipt0이며 commit 실패는 전체 rollback한다. commit 뒤 최종 권한 철회/취소는 이미 저장한 immutable 검증 기록을 보존하되 답변·proof를 정상 turn/result로 저장/반환하지 않는다. execution 실패/취소와 gate 거절을 유지한다.
- [x] **정상 결과 복원:** 복원 대상의 server-owned execution ID로 expected context를 먼저 조회한다. audit의 동결 프로파일이 schema3이면 JSON의 envelope/proof 삭제를 legacy로 취급하지 않는다. SearchResponse와 PrivateGenerativeResult에서 같은 canonical `ValidatedGenerationPayload`를 재구성해 expected context와 receipt의 payload digest를 대조한다. 숫자/문장을 receipt/audit에 중복 저장하지 않는다. digest는 기존 `rag_generative_canonical`과 JSON 표기 호환을 SQL 시험으로 확인한다. receipt UUID나 model의 validated=true만 확인하는 구현은 금지한다. 같은 actor/동일 answer라도 다른 execution의 정상 receipt/payload 전체 이식을 거절한다.
- [x] **migration/gate:** revision=`0063_rag_numeric_proof`, parent=`0062_rag_access_epoch`로 준비하며0059를 고치지 않는다. `rag_require_generative_numeric_candidate(run_uuid uuid, version_uuid uuid)`를 새로 정의하고 기존 `rag_verify_generative_candidate`에 unique anchor를 검증해 이 검사 호출만 추가한다. CREATE OR REPLACE로 기존 함수의 OID를 유지하며 rename/wrapper로 우회하지 않는다. authoritative 동결 generation profile/schema/policy로 분기를 선택한다. schema1/2는 새 receipt 테이블을 조회하기 전에 기존 경로로 반환한다. schema3는 정상 receipt·audit·source origin/span·self citation·payload/canonical SHA를 검사한다. policy digest는 등록된 불변 v1의 연산·승수·제한값을 canonical화한 정확한 SHA와 비교하며 임의의 SHA 형식만 받아들이지 않는다. answered는 succeeded audit, insufficient는 allowed audit이며 후자는 answer/null·claims/empty·계산0 계약이다. 기존 정답/권한/반복/latency 기준은 그대로다.
- [x] **배포 capability:** numeric table/function이 없는0061에서 schema3 readiness는 false/명시적 미지원으로 반환한다. legacy 준비/조회는 새 table을 질의하지 않는다. fixture나 요청이 migration을 실행하거나 alembic version을 stamp하지 않는다.
- [x] **GREEN/검토:** 새 unit과 기존 audit/평가 계약·최종 권한 unit을 통과하고 DBA·독립 reviewer가 SQL source를 검토한다. 실제0063 업그레이드나 SQL gate 통과는 Task6/7의 증거 전 주장하지 않는다.

### Task5: 비공개 결과·API·관리자 주장별 계산 근거

**Files:** Create `generation/numeric_proof_schemas.py`; Modify `search/schemas.py`, `evaluation/generative.py`, `generative_workflow.py`, `generative_read.py`, `generative_schemas.py`, `conversations/service.py`, `conversations/api.py`, `executions/read_repository.py`; Create `frontend/src/features/rag/configurations/CalculationProofReview.tsx`; Modify `frontend/src/features/rag/configurations/ClaimCitationReview.tsx`, `frontend/src/features/rag/configurations/GenerativeEvaluation.module.css`, `frontend/src/shared/api/schema.d.ts`, `frontend/src/features/rag/executions/ExecutionDetailPage.tsx`.
**Tests:** Create `tests/unit/labs/rag/evaluation/test_numeric_proof_trace.py`, `frontend/src/features/rag/configurations/CalculationProofReview.test.tsx`; 기존 claim trace/workflow/monitoring/conversation tests 확장.
**Interfaces:** Task3의 canonical payload·Task4 binding을 공통 DTO로 전달한다. `ClaimCitation/GeneratedCitationResponse.calculations`와 결과의 `numeric_validation`은 None이면 omit, schema3는 exact tuple/binding을 보존한다. React component는 claim text/계산 DTO/허용 source 목록만 받아 원문 링크를 표시한다.

- [x] **RED:** `test_numeric_proof_roundtrip_and_digest_binding`, `test_legacy_absent_fields_keep_exact_bytes`, `test_workflow_cannot_lose_binding`, `test_proof_revocation_or_tampering_hides_restored_turn`를 작성한다. proof/원문 span/연산/policy 변경은 신규 digest·판정 결속을 바꾸고 기존 schema1/2 canonical bytes와 digest는 동일해야 한다.
  ```python
  assert restored_payload == validated.payload
  assert old_result.model_dump(mode="json") == old_json
  assert old_result.digest() == old_digest
  assert changed_proof_result.digest() != original_proof_result.digest()
  ```
- [ ] **RED 실행:** `.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/evaluation/test_numeric_proof_trace.py -q`; frontend에서 `pnpm exec vitest run src/features/rag/configurations/CalculationProofReview.test.tsx`.
- [x] **서버 구현:** outcome→SearchResponse→대화 저장/복원과 outcome→PrivateGenerativeResult→평가 조회/정상 판정에서 계산·binding을 보존한다. 조회는 기존 현재 원문 권한과 Task4 digest 검사를 거친다. ConversationService 검증 의존성은 실제 생성 위치인 `conversations/api.py`에서 주입한다. turn.execution_id/attempt.execution_id/monitoring execution.id로 기대 문맥을 조회하고 JSON binding과 별도로 전달한다. evaluation에서는 authoritative attempt.configuration_version_id와 run의 동결 generation profile도 대조한다. `generative_read.run_detail`은 기존 session, monitoring repository는 조회 session에 결속한 numeric repository를 사용한다. 현재 signer v3는 content/actor/config/turn/scope만 보증한다. proof를 클라이언트 history의 권위로 받지 않고 저장된 서버 결과만 별도 검증한다. 기존 서명/토큰 length/과거 대화는 변경하지 않는다.
- [x] **UI 구현:** 기존 주장별 검토 안의 native details로 `계산 근거`를 접어 보여준다. 연산명은 `퍼센트포인트 차이`/`금액 단위 환산`, 결과는 `[...claimText].slice(start,end).join("")`로 표시한다. 원문은 현재 허용 sources와 `buildSourceHref(assetVersionId, projectionId, [], page)`로 연결한다. 접근 불가 원문은 링크를 만들지 않고 명시한다. 원문 근거 수나 산술 통과를 의미 정답/유사도 점수로 표시하지 않는다. 실행 상세의 안전한 새 실패 코드는 한글 설명으로 매핑한다.
- [x] **API 타입/검증:** frontend에서 `pnpm api:generate`, `pnpm api:check`, `pnpm typecheck`, 위 신규 UI와 기존 `GenerativeEvaluation.test.tsx`·`ExecutionMonitoring.test.tsx`를 Vitest로 실행한다. 키보드 펼침/닫힘·legacy 미기록·같은 값의 여러 span·emoji/줄바꿈·빈 sources/부분 접근을 확인한다.
- [x] **검토/인계:** 프론트엔드/백엔드 정적 검사와 독립 permission/privacy 검토 후 인계한다. 실제 브라우저/신규 모델 결과 확인은 Task7이며 fixture 화면을 본래 완료로 보고하지 않는다.

### Task6: 본래0061의 완전 rollback SQL trial과 관련 회귀

**Files:** Create `tests/integration/labs/rag/evaluation/test_original_numeric_proof.py`, `original_numeric_proof_support.py`; 기존 다른 integration fixture는 수정/실행하지 않는다. Modify `docs/runbooks/local-development.md`에 이 파일의 opt-in과 trial/실제 migration 구분을 기록한다.
**Interfaces:** Task4 `NUMERIC_PROOF_DDL: tuple[str, ...]`를 `numeric_validation_sql.py`에 정의한다. 신규 migration과 이 trial은 같은 DDL을 사용하되 trial은 하나의 bound connection 안에서만 실행한다.

- [x] **RED/guard 작성:** 명시 opt-in `AI_WORKSHOP_VERIFY_ORIGINAL_NUMERIC_PROOF=1` 없으면 SKIP한다. inherited AI_WORKSHOP overrides를 제거하고 `load_original_settings`를 사용한다. COMMIT event deny·outer transaction·모든 session create_savepoint 결속·schema0061/기존 함수 digest/현재 owner 및 승인 합성 source 사전조건을 검사한다. trial engine의 `sync_engine.hide_parameters=True`, `echo=False`를 설정한다. `OriginalNumericProofTrialError`는 안전한 고정 코드만 갖는다. DB/API 예외는 statement/parameters 없이 해당 오류로 변환하고 `raise ... from None`으로 원 예외를 노출하지 않는다. 기존 source/result 본문은 repr/assert diff/log/receipt에 넣지 않는다. 새 DB/계정/환경/HTTP/model은 만들거나 호출하지 않는다.
- [x] **시험 작성:** `test_numeric_trial_roundtrip_and_gate`, `test_missing_forged_or_cross_bound_receipt_rejected`, `test_insufficient_and_legacy_gate_compatibility`, `test_trial_rollback_restores_schema_and_rows`를 만든다. 정확한 기존 합성 snapshot/source는 승인/permission/hash를 조회해 사용하고 본문을 출력하지 않는다. wrong actor/profile/policy/request/origin/span/result SHA·누락/변조 envelope·자기 인용 밖 operand·빈 receipt·허위 schema downgrade를 거절한다.
- [x] **guard 확인:** opt-in 없는 단일 파일 실행은 SKIP이며 DDL0/시험행0/환경 변경0이어야 한다. 격리되지 않은 기존 claim trace나 전체 integration을 대신 실행하지 않는다.
- [x] **승인된 원본 trial 실행:** root가 독립 검토한 helper를 기존 `.env`로 실행할 때만 아래 단일 파일을 opt-in한다. 이 명령은 앞으로 테스트가 작성·검토된 뒤 실행하며 지금은 실행하지 않는다.
  ```powershell
  $env:AI_WORKSHOP_VERIFY_ORIGINAL_NUMERIC_PROOF = '1'
  try { .venv/Scripts/python.exe -m pytest tests/integration/labs/rag/evaluation/test_original_numeric_proof.py -q --assert=plain --tb=short }
  finally { Remove-Item Env:AI_WORKSHOP_VERIFY_ORIGINAL_NUMERIC_PROOF -ErrorAction SilentlyContinue }
  ```
  예상: PASS, COMMIT0, outer rollback 후 새 table/function/합성행0, alembic_version은0061,
  기존 gate 함수 definition hash 복구와 이전 평가/문서/연결/별칭 정보의 보존 확인.
- [x] **SQL 원본 경계:** transaction-local DDL은 다른 API 연결에 보이지 않는다. 이 성공은 numeric SQL trial이며 실제0062→0063 migration·API 반영·HTTP 경쟁/모델 검증이 아니다. schema나 기존 helper가 조건을 만족하지 않으면 중단하고 원인만 기록한다.
- [x] **최종 관련 검사:** 아래 정확한 명령을 실행하고 실제 파일/수·exit와 실패를 기록한다. backend의 Ruff 대상 배열은 변경 계획에 포함된 범위다. 새 실패나 변경 없이 검사를 반복하지 않는다.
  ```powershell
  # cwd: backend
  .venv/Scripts/python.exe -m pytest tests/unit/labs/rag/generation tests/unit/labs/rag/search tests/unit/labs/rag/evaluation tests/unit/labs/rag/conversations -q
  .venv/Scripts/python.exe -m mypy -p ai_workshop
  $numericProofPaths = @('src/ai_workshop/labs/rag/generation', 'src/ai_workshop/labs/rag/models/numeric_proof_policy.py', 'src/ai_workshop/labs/rag/models/domain.py', 'src/ai_workshop/labs/rag/models/context_evidence.py', 'src/ai_workshop/labs/rag/search/pipeline.py', 'src/ai_workshop/labs/rag/search/schemas.py', 'src/ai_workshop/labs/rag/evaluation', 'src/ai_workshop/labs/rag/conversations/service.py', 'src/ai_workshop/labs/rag/conversations/api.py', 'src/ai_workshop/labs/rag/executions/read_repository.py', 'src/ai_workshop/main.py', 'alembic/versions/0063_rag_numeric_proof.py', 'tests/unit/labs/rag/generation', 'tests/unit/labs/rag/search', 'tests/unit/labs/rag/evaluation', 'tests/unit/labs/rag/conversations', 'tests/integration/labs/rag/evaluation/test_original_numeric_proof.py', 'tests/integration/labs/rag/evaluation/original_numeric_proof_support.py')
  .venv/Scripts/python.exe -m ruff check @numericProofPaths
  .venv/Scripts/python.exe -m ruff format --check @numericProofPaths
  # cwd: frontend
  pnpm api:check
  pnpm typecheck
  pnpm exec vitest run src/features/rag/configurations/CalculationProofReview.test.tsx src/features/rag/configurations/GenerativeEvaluation.test.tsx src/features/rag/executions/ExecutionMonitoring.test.tsx src/features/rag/conversation/ConversationPage.test.tsx
  pnpm exec eslint src/features/rag/configurations/CalculationProofReview.tsx src/features/rag/configurations/ClaimCitationReview.tsx src/features/rag/configurations/CalculationProofReview.test.tsx src/features/rag/configurations/GenerativeEvaluation.test.tsx src/features/rag/executions/ExecutionDetailPage.tsx src/features/rag/executions/ExecutionMonitoring.test.tsx src/features/rag/conversation/ConversationPage.test.tsx --max-warnings 0
  ```
- [x] **독립 검토:** 구현 담당과 분리한 reviewer/verifier가 source·RED/GREEN·rollback·legacy digest/권한 경계와 기존 결과 보존을 확인한다. 보존 감사에는 이전155/75판정, 첫75/68판정/새7, 동결 제품 코드7개 SHA·기존 정본/DB 보고서8개 SHA(설계 보고서79520c68-9349-4c19-93a2-9358e470c86a 정확한v1 포함), 기존 자료·세션/활성 연결·별칭 상태를 포함한다. 이번 구현의 의도된 코드 변경과 과거 동결 검증 스냅샷은 구분한다.

### Task7: 본래 반영·실모델 평가·문서/문제 DB 인계

**Files:** Update `WORKBOARD.md`, 승인 명세/ADR 상태, RAG 설계·runbook, 신규 `docs/worklogs/2026-10-05-rag-numeric-proof-implementation.md`(실제 구현한 날의 날짜를 사용). 기존 frozen 보고서/DB 문서 v1은 수정하지 않는다.
**Interfaces:** Task1-6의 실제 통과 증거와 body-free preflight/보존 기록을 소비한다. 관련 main/remote 반영이나 commit/push는 root가 별도 요청 범위에 맞춰 결정한다.

- [x] **반영 preflight:** 실제 현재0061과 미적용0062의 독립 WIP를 대조한다. `alembic upgrade head`로0062까지 묵시 적용하거나 stamp/별칭 해제하지 않는다.0062 구조 migration 자체의 호환성/보존/복구·정확한0063 적용 순서를 먼저 검토하고 concrete 반영 범위로 제시한다. 코드·SQL trial 완료와 실제 반영 승인을 구분한다.
- [x] **본래 반영:** 검토/승인된 정확한 migration 경로와 API 반영을 기존 환경에서만 실행한다. 필요한 API 재시작은 실제 진행 실행0과 exact 프로세스/설정/원본 캐시 경로 보존을 확인한 후 한다. worker/beat나 Docker/IDE는 임의 시작/재시작하지 않는다. 기존 DB/자료/활성 연결·receipt와0062/native 전환 경계를 보존한다. 2026-10-06 정확한0062→0063 적용과117테이블 보존·독립 legacy복원·API/proxy health를 확인했다.
- [x] **새 불변 후보:** 동일 모델/deployment·색인·검색·고정 snapshot/QA/rules/정책을 사용한 v6/schema3/policy 후보를 정상 API로 등록하고 새 합성 연결 검사를 수행한다. 기존 후보를 덮어쓰지 않는다. 모델 신뢰 등록/정책을 이 작업 때문에 바꾸지 않는다. 새 후보9c7c07e7-d128-4876-9411-aa7479eff3e1이며 승인 재파생의 누락을 수정한 뒤 정상 합성 연결ready=true를 확인했다. 실제 품질·승격은 별도다.
- [x] **실제 평가:** 새25×3은64정상/11검증거절로종료했고정상owner의독립의미판정63통과/1실패를64개등록했다. claim83·receipt64복원·%p proof10/통화환산0·요청audit75개gpt-5.5/관측unknown·단계별건수와p50/p95·실패firstsafe reason직접값8/계산위치3을기록했다. 메모리변조4종복원거절은실모델품질과구분했다. accept409로pending/defaultfalse·기존활성연결보존. 실패초안/정확한실패값/span/전체kindcount는미기록으로unknown이며Q08/Q12원인이해결됐다고보고하지않는다.
- [ ] **본래 브라우저:** 통과·승격 조건을 충족한 경우에만 검토된 도메인 연결을 적용하고 기존 세션/신규 질문/멀티턴·인용 원문·계산 설명 복원을 실제 Chrome에서 확인한다. 관리자 UI도 기존 결과/신규 proof·권한 철회/새로고침·1440/390px·키보드 펼침·선택/기록 개수 구분을 확인하고 실제 화면 증거를 보존한다.
  - 2026-10-06 후속: 기존 로그인 Chrome 관리자 계산·PDF·진단·새로고침·키보드·1440/390px 및 기존 세션을 확인했다. HTTP 세션 오류를 수정·본래 반영한 같은 질문은 정상 근거 부족으로 저장·복원됐다. v6 승격/유효 답변·성공한 멀티턴/실제 권한 철회는 미확인이므로 상위 브라우저 checkbox는 유지한다. [별도 동결 보고서](../../worklogs/2026-10-06-rag-numeric-proof-browser.md).
- [x] **문서/DB 마감:** ISSUE-00026·관련5에 이번 구현·실행·미검증 범위를 정상 관리자 API로 기록하고 신규 보고서의 exact DB 버전을 연결했다. 2026-10-06 새보고서6a6c12d1-a7f1-4e44-9b43-ac295bddaf85 v1을5/26/27에추가연결(5openr43/26openr13/27verifiedr3)하고기존필드·사건·연결·동결설계/계획/구현DBv1을보존했다. WORKBOARD 최근완료는5개다. 품질 개선만 남았다는 보고는 기존 별칭 종료/사용자 흐름/인계 기능 마감 조건까지 충족한 경우에만 한다.

## 실행·검토 인계

권고 실행 방법은 **현재 세션에서 메인 Codex가 Task별로 구현하고 독립 검증/리뷰를 별도로 받는 방식**이다.
nonce→wire→validator→receipt→digest가 서로 밀접하므로 공용 계약의 변경 소유자를 하나로 유지한다.
필요한 독립 UI 수정만 고정된 파일 범위로 배정하며, root가 task 통합과 staging/commit/push를 결정한다.

작성 당시에는 모든 구현 checkbox가 미착수였다. 사용자 승인 후 Task1–6 구현·관련 시험과 독립 리뷰를
수행했고 Task7의 사전검사와 현재 범위 문서/DB 이력을 완료했다. Task5 최초 UI RED의 미확인은
실행 판정에 기록했다. 2026-10-05에는 실제 migration·새 모델 평가·본래 브라우저 단계를 체크하지 않았다. 2026-10-06 사용자가 실제 반영과 새75회를 승인한 후 정확한0062→0063/API 및 합성 연결을 반영했다. 새 평가e20b73e8-2db4-423a-8d79-dfbc1f34999e는64정상/11검증거절·의미63통과/1실패로종료했고승격409·후보대기를확인해실제평가를체크했다. 앞선 반영 시점의 브라우저는 로그인·제어 중단으로 미체크였다. 이후 기존 로그인 화면과 HTTP 세션 수정을 실제 확인했으나 유효 답변·성공한 멀티턴/후보 승격·권한 철회는 남아 미체크를 유지한다. 자동 시험이나 rollback SQL 성공을 실모델 품질·제품 전체 완료로 해석하지 않는다.
