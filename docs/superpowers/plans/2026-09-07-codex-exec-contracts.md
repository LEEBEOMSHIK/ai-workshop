# Codex exec 입력·출력 계약 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 승인된 개인용 Codex RAG 설계의 버전된 내부 지침, 비신뢰 입력 직렬화와 엄격한 답변 v2 계약을 구현한다.

**Architecture:** 기존 generation 모듈에 순수 입력·출력 경계를 추가한다. 기존 v1 Provider 동작은 유지하며 새 계약을 런타임이나 DB에 자동 등록하지 않는다. 실제 CLI 모델 identity·수명주기를 검증한 뒤 Provider/DB/UI 연결을 별도 실행 단계로 이어간다.

**Tech Stack:** Python 3.13, dataclasses, JSON, pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md` (2026-09-07 상세 문서 사용자 승인)

## Global Constraints

- main에서만 작업하며 기존 OCR·Learning·도메인 변경을 보존한다. 자동 commit/push와 worktree 생성은 하지 않는다.
- 기존 SDK/App Server/LPAC 차단은 유지한다. 실제 모델 호출·인증 읽기·DB 변경·서버 재시작은 이 계약 구현에 포함하지 않는다.
- 질문·이력·근거는 비신뢰 데이터다. 신뢰된 지침은 registry에서만 읽고 입력에서 config·역할·경로를 만들지 않는다.
- 프롬프트는 보안 보장이 아니다. 실제 실행에는 현재 권한·모든 입력 전송 승인과 요청별 프로세스 회수가 별도로 필요하다.
- v1은 보존한다. v2 answered는 nonempty claims, insufficient_evidence는 schema_version/status 두 필드만 허용한다.
- 모델명·환경 경로·가변 제한은 코드에 고정하지 않는다. 프로토콜 버전·오류 코드는 명명된 불변식이다.
- 테스트는 합성 데이터로 오프라인 실행한다. 임시 인계는 `.local-data/project-agent-work/codex-exec-contracts/`에만 둔다.

## 범위와 후속 연결 게이트

이 계획은 상세 설계 §3·§5의 독립 실행 가능한 순수 코드와 §10.1·§10.4 검증을 담당한다.
전체 서비스 완료를 의미하지 않는다. §6~§8 실행기·DB·UI 구현은 CLI의 실제 모델 증거와 지침/schema
지원 계약 확인을 먼저 거친다. 모르는 이벤트나 실제 모델 이름을 추정해 구현하지 않는다.
후속 순서는 CLI 사전 검증 → 요청별 실행기/권한 허가 → DBA migration/정확한 runner 참조 →
관리자 등록·연결 검사 → Hybrid/도메인 구성 → 실제 대화·인용·후속 질문 검증이다.
계정 사용량이 발생하는 검사는 입력·수신자·사용량을 고지하고 명시 실행 승인 후 수행한다.

## Task 1: 엄격한 grounded output v2

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/generation/structured_output_v2.py`
- Test: `backend/tests/unit/labs/rag/generation/test_structured_output_v2.py`
- Read only: `generation/domain.py`, `generation/structured_output.py`, `generation/citation_validation.py`

**Interfaces:**
- Consumes: 기존 `GeneratedClaim`, `StructuredGeneration`, `GenerationStatus`, `StructuredOutputValidationError`.
- Produces: `parse_grounded_generation_v2(content: str, *, allowed_evidence_ids: Collection[UUID]) -> GroundedGenerationResultV2`.
- `GroundedGenerationResultV2`는 frozen dataclass이며 `status: GenerationStatus`, `generation: StructuredGeneration | None`을 갖는다.
- answered에는 schema_version=2의 nonempty StructuredGeneration, insufficient에는 None만 허용한다. 생성자도 상충 상태를 거부한다.
- `GROUNDED_GENERATION_SCHEMA_V2`는 두 정확한 object branch의 JSON Schema union이다. CLI 지원을 검증했다고 표시하지 않는다.

- [x] RED: 아래 수용 테스트와 거절 행렬을 먼저 작성한다.

```python
def test_insufficient_has_no_claims():
    result = parse_grounded_generation_v2(
        '{"schema_version":2,"status":"insufficient_evidence"}',
        allowed_evidence_ids=(),
    )
    assert result.status is GenerationStatus.INSUFFICIENT_EVIDENCE
    assert result.generation is None
```

거절 행렬: v1 payload, bool/float schema version, extra keys, insufficient의 claims/설명,
빈 answered claims/text/IDs, 중복·미허용·비UUID IDs, 중복 JSON key(중첩 포함), nonobject,
잘린 JSON, 여러 JSON, NaN/Infinity. 정상 answered의 text와 IDs가 그대로 해석되는지 확인한다.
오류 메시지와 exception chain에 입력 본문을 노출하지 않는다.

- [x] 실행: `backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/unit/labs/rag/generation/test_structured_output_v2.py -q`; 미구현 실패 확인.
- [x] GREEN: 중복 key 거부 object_pairs_hook, parse_constant 거부, exact field/type 검사와 claim 검증을 구현한다.

```python
if status == "insufficient_evidence":
    if set(parsed) != {"schema_version", "status"}:
        raise StructuredOutputValidationError("Invalid grounded generation output.")
    return GroundedGenerationResultV2(GenerationStatus.INSUFFICIENT_EVIDENCE, None)
```

claims 검증은 기존 v1 parser의 검증을 재사용할 수 있지만 원본 v1 parser나 스키마를 변경하지 않는다.
재사용 전 strict JSON을 해석하고 스키마 버전을 명시 변환한다. 새 결과만 schema_version=2로 만든다.
- [x] GREEN/회귀: 새 테스트와 기존 generation 단위 테스트 실행. ruff 및 mypy 검증.
- [x] 담당 보고서에 RED/GREEN 명령·출력·수정 파일·제약·diff 기준을 남기고 독립 리뷰에 인계한다. commit하지 않는다.

## Task 2: 버전된 내부 지침과 canonical stdin envelope

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/generation/prompts.py`
- Create: `backend/src/ai_workshop/labs/rag/generation/prompts/codex-control-v1.txt`
- Create: `backend/src/ai_workshop/labs/rag/generation/prompts/codex-answer-v2.txt`
- Create: `backend/src/ai_workshop/labs/rag/generation/prompts/codex-contextualize-v1.txt`
- Create: `backend/src/ai_workshop/labs/rag/generation/codex_prompt.py`
- Test: `backend/tests/unit/labs/rag/generation/test_codex_prompt.py`

**Interfaces:**
- Consumes: Task 1 schema, `ContextualizationRequest`, `GenerationRequest`, existing closed prompt registry.
- Produces: `build_codex_prompt(request: ContextualizationRequest | GenerationRequest) -> CodexPromptEnvelope`.
- frozen envelope fields: `developer_instructions: str`, `stdin_json: str`, `output_schema_json: str`,
  `control_ref: str`, `control_version: int`, `control_sha256: str`, `task_ref: str`, `task_version: int`,
  `task_sha256: str`, `schema_ref: str`, `schema_version: int`, `schema_sha256: str`.
- Envelope repr excludes instructions/input; metadata contains no body. No log or disk writes.
- Registry refs: `rag-codex-control-v1`, `rag-codex-answer-v2`, `rag-codex-contextualize-v1`.
- Profile must select the exact answer/context refs and response schema version 2. Unsupported combinations fail safely.

- [ ] RED: use existing generation test builders to form requests. Assert canonical stdin round-trips malicious-looking question/history/evidence unchanged but developer instructions and schema/digests are unchanged when those inputs change.

```python
payload = json.loads(envelope.stdin_json)
assert payload["question"] == request.question
assert envelope.control_ref == "rag-codex-control-v1"
assert len(envelope.control_sha256) == 64
assert request.question not in envelope.developer_instructions
```

Use distinct synthetic injected strings (role tags, quote/newline, command text, file-like paths) rather than normal words shared with instructions.
Test both contextualize and answer, unknown/path-like refs, mismatched profile/schema, exact keys,
no model/account/path attributes in payload, output schema mutation isolation and unchanged existing prompt behavior.
- [ ] Run focused pytest before production edits and record RED.
- [ ] GREEN: put §3 approved Korean control text verbatim in trusted asset. Answer task states exact v2 output; contextualization keeps exact resolved_query v1 output. Registry alone loads the assets.

```python
stdin_json = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":"), allow_nan=False)
digest = hashlib.sha256(trusted_text.encode("utf-8")).hexdigest()
```

Payload exact keys: question/history/evidence, plus resolved_query only for generation.
history objects contain role/content only, evidence objects contain evidence_id/text only; no source host paths or model/config data.
Keep existing bounded-history selection upstream; this builder does not claim permission checks or start a process.
Assemble developer instructions from registry control+task+canonical schema, never from input fields.
Return copied/serialized schema so callers cannot mutate the shared registry through envelope.
- [ ] Run focused test, full generation unit directory, ruff and mypy; report RED/GREEN and independent review.

## Task 3: 독립 통합 검증과 다음 실행 계약 확인

**Files:**
- Create: `docs/worklogs/2026-09-07-codex-exec-contracts.md`
- Modify: `WORKBOARD.md`, approved spec/ADR status only.
- Read only: installed CLI help and official non-interactive/config docs. No account/session/auth files.

**Interfaces:** Task 1 parser and Task 2 envelope; downstream Provider must still enforce §4/§6/§7.

- [ ] Independently review both task diffs and tests for spec compliance and code quality.
- [ ] Run combined regression and static checks:

```powershell
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/unit/labs/rag/generation -q
backend/.venv/Scripts/python.exe -m ruff check backend/src/ai_workshop/labs/rag/generation backend/tests/unit/labs/rag/generation
backend/.venv/Scripts/python.exe -m mypy --config-file backend/pyproject.toml backend/src
```

- [x] Verify CLI documented event/schema/instruction contracts without model calls; separate documented fields from measured identity evidence.
- [ ] Record exact passing checks, unmet runtime gates, follow-on roles and next action in worklog/WORKBOARD; recent completed remains max 5.
- [ ] Before live verification, present synthetic input scope and account usage. Do not claim prompt implementation makes actual RAG answers ready.
