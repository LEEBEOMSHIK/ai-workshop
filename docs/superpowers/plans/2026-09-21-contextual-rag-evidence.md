# Contextual RAG Evidence and Search Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 일반 질문에서 문장과 문맥을 함께 비교해 필요한 원문 근거를 생성·인용에 연결하고, 테스트 요청에서 실제 검색 점수·선택 사유·시간을 확인한다.

**Architecture:** 기존 hybrid 검색과 권한 확인을 유지하고 생성 전 문맥 선택을 별도 서비스로 추가한다. 생성 어댑터들은 같은 근거 직렬화를 사용한다. 공개 응답에는 실제 전달 근거와 요청 시에만 진단을 추가하고 프론트가 이를 표시한다.

**Tech Stack:** Python 3.13, FastAPI/Pydantic, 기존 로컬 embedding adapter, Elasticsearch, Next.js/React/TypeScript, pytest/Vitest.

**Spec:** [승인된 설계](../specs/2026-09-21-contextual-rag-evidence-design.md). 2026-09-21 사용자가 테스트 유사도 표시까지 승인했다.

## Global Constraints

- 본래 checkout·환경·계정·자료를 사용한다. 새 worktree, 테스트 DB, 업로드 문서를 만들지 않는다.
- 기존 `references/`와 원본·sandbox 보존 자료는 수정하지 않는다.
- BM25 + dense + RRF 기준선, 권한 선필터와 생성 직전 현재 출처 재검증을 유지한다.
- 임베딩 모델·청킹 산출물·색인을 바꾸지 않는다. 새 프롬프트와 생성 profile 후보는 평가 후 적용한다.
- 초기 후보 예산: 8개 묶음, 32개 EvidenceUnit, 원문 합계 12,000문자. 버전된 generation profile JSON에 둔다.
- 근거를 잘라 인용하거나 keyword/BM25/RRF/cosine을 같은 척도로 합치지 않는다.
- 진단은 요청한 사용자에게 허용된 source만 반환한다. 비공개 질의·원문·벡터를 전역 캐시/로그에 남기지 않는다.
- 사용자 승인 없는 모델 전환·외부 전송 확대·평가 상태 직접 수정은 금지한다.
- 테스트 설계/구현은 메인, 독립 코드·권한/전송 검토는 별도 검토자. root만 staging/commit/push한다.
- 계획 상태: 사용자 검토 전. 아래 제품 변경은 아직 실행하지 않았다.

## Review Focus

1. 진단 on/off 때문에 다른 근거를 선택하거나 실패하는 경우: 같은 선택 결과를 Task 2/5에서 검증한다.
2. 다른 source가 같은 evidence ID를 제시하는 경우: 조용히 중복 제거하지 않고 Task 2에서 차단한다.
3. 문맥만 충분한데 추출형 status가 부족인 경우: Task 5에서 생성 실행과 별도 status를 검증한다.
4. budget으로 충돌 근거 한쪽만 사라지는 경우: Task 2/5에서 확정 답변을 차단한다.
5. provider가 인용한 새 근거가 화면에 없는 경우: Task 6에서 모든 인용 연결 또는 명시적 오류를 검증한다.

## 작업 공통 실행 규칙

각 Task는 실패 테스트 작성 → 실패 확인 → 최소 구현 → 테스트/타입/린트 확인 → 관련 파일만 커밋 순서다.
아래 Python 명령은 `backend`에서 `.venv/Scripts/python.exe -m ...`, 프론트 명령은 `frontend`에서 실행한다.
기존 unit fixture를 사용하되 운영 본문·ID를 복사하지 않는다. 가짜 모델 점수는 로직 검증일 뿐 실제 검색 품질 증거가 아니다.
새 파일 경로는 아래 Create 목록으로 제한하고, 기존 대형 service의 무관한 리팩터링은 하지 않는다.

### Task 1: 검색 원점수 보존과 요청 내 질의 벡터 재사용

**Files:**
- Modify: `backend/src/ai_workshop/labs/rag/retrieval/domain.py`, `retrieval/rrf.py` (동일 rag 루트).
- Create: `backend/src/ai_workshop/labs/rag/embeddings/request_cache.py`.
- Test: `backend/tests/unit/labs/rag/retrieval/test_rrf.py`.
- Create test: `backend/tests/unit/labs/rag/embeddings/test_request_cache.py`.

**Interfaces:** `FusedHit` 뒤에 optional `sparse_score: float | None = None`, `dense_score: float | None = None` 추가.
`RequestScopedEmbedding(delegate: EmbeddingPort)`는 EmbeddingPort를 구현하며 동일 query의 encode만 재사용한다.
문서 embedding은 캐시하지 않는다. wrapper는 검색 요청마다 새로 생성한다.

- [ ] 기존 합성 chunk fixture로 sparse score 8.2, dense score 0.77을 넣고 아래 회귀를 추가한다.

```python
fused = rrf_fuse((SparseHit(chunk, 2, 8.2),), (DenseHit(chunk, 1, 0.77),))
assert fused[0].sparse_score == 8.2
assert fused[0].dense_score == 0.77
assert fused[0].score == 1 / 62 + 1 / 61
assert rrf_fuse((RankedHit(chunk.chunk_id, 1),), ())[0].sparse_score is None
```

- [ ] `-m pytest tests/unit/labs/rag/retrieval/test_rrf.py tests/unit/labs/rag/embeddings/test_request_cache.py -q` 실행, 새 필드/클래스 부재로 실패 확인.
- [ ] 원점수는 각 branch의 best rank에 해당하는 hit에서 가져온다. 동순위는 입력 첫 hit를 유지하고 provenance 충돌 검사와 RRF 순서는 유지한다.
- [ ] wrapper는 query→tuple 벡터를 요청 내 저장하고 반환할 때 list 복사. 실패는 저장하지 않는다. count 메서드는 delegate로 전달한다.

```python
first = cached.encode_query("합성 질문")
first[0] = 100
assert cached.encode_query("합성 질문") == original_vector
assert delegate.query_calls == 1
assert RequestScopedEmbedding(delegate).encode_query("합성 질문") == original_vector
assert delegate.query_calls == 2
```

- [ ] count 불일치·비유한 score·빈 branch·BM25-only·실패 후 재시도 회귀를 통과시키고 커밋한다.

### Task 2: 문맥 후보 선택, 예산, 진단의 순수 계약

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/highlighting/context.py`.
- Modify: `backend/src/ai_workshop/labs/rag/highlighting/service.py` (기존 검증/점수 함수 공유만).
- Create test: `backend/tests/unit/labs/rag/highlighting/test_context.py`.

**Interfaces:** 다음 타입을 `context.py`가 소유한다. 다른 Task는 이를 재정의하지 않는다.

```python
@dataclass(frozen=True, slots=True)
class EvidenceBudget:
    max_groups: int
    max_units: int
    max_characters: int

@dataclass(frozen=True, slots=True)
class ContextGroup:
    source: EvidenceSource
    units: tuple[EvidenceUnit, ...]
    keyword_coverage: float
    semantic_score: float | None

@dataclass(frozen=True, slots=True)
class CandidateDiagnostic:
    chunk_id: UUID
    evidence_id: UUID | None  # None이면 문맥 후보
    keyword_coverage: float | None
    semantic_score: float | None
    eligible: bool
    selected: bool
    reason: str

@dataclass(frozen=True, slots=True)
class ContextSelection:
    groups: tuple[ContextGroup, ...]
    diagnostics: tuple[CandidateDiagnostic, ...]
    blocked_reason: str | None

def select_context(*, query: str, sources: tuple[EvidenceSource, ...],
                   extractive: EvidenceSelection, policy: AnswerPolicy,
                   budget: EvidenceBudget, embedding: EmbeddingPort,
                   include_diagnostics: bool) -> ContextSelection:
    ...
```

- [ ] 합성 source는 기존 `test_evidence_selector.py`의 `_source` builder를 이 파일에 필요한 형태로 직접 정의한다.
  같은 chunk의 두 units를 `dataclasses.replace`로 조립하고 ordinal=0/1, 서로 다른 element ID로 둔다.
  문자열은 `실험 장치의 이름은 달빛입니다.`와 `보증 기간은 구매 후 18개월입니다.`를 사용한다.
  unit 벡터는 query에 미달, 문맥 벡터는 통과하도록 recording embedding을 구성한다.

```python
assert extractive.status is AnswerStatus.INSUFFICIENT_EVIDENCE
assert tuple(u.id for u in context.groups[0].units) == (name.id, warranty.id)
assert context.groups[0].units[1].text == warranty.text
assert context.groups[0].units[1].location == warranty.location
```

- [ ] `-m pytest tests/unit/labs/rag/highlighting/test_context.py -q`로 계약 부재 실패 확인.
- [ ] source의 유효 units만 원문 순서대로 조립한다. 같은 ID의 다른 원문/출처, 다른 chunk/projection,
  invalid offsets는 차단한다. invalid 항목의 본문을 진단에 담지 않는다.
- [ ] 의미 입력은 `section_path + 요소 경계와 원문 순서가 보존된 본문`이다. keyword coverage는 본문에 대해서만 계산한다.
  문맥 의미 비교는 후보들을 한 batch로 계산하고 query vector는 Task 1 wrapper를 재사용한다.
  기존 추출형 자격을 가진 unit이 있는 그룹 또는 문맥 자체가 정책을 통과한 그룹을 후보로 유지한다.
- [ ] 기존 정책의 keyword 자격 그룹을 coverage 내림차순, 나머지는 semantic 내림차순으로 정렬한다.
  동점은 source의 검색 순위와 chunk ID로 고정한다. 두 점수를 산술 혼합하지 않는다.
- [ ] 완전한 그룹 단위로 예산을 적용한다. primary/conflict 그룹 집합이 모두 들어가지 않으면
  `blocked_reason="conflict_context_budget_exceeded"`, groups=()로 반환한다.
  이유 enum은 `selected`, `below_threshold`, `budget_exceeded`, `provenance_invalid`, `duplicate`를 사용한다.
- [ ] 진단이 켜진 경우 모든 유효 unit의 실제 cosine을 batch 계산하되 선택 결과에는 추가 계산을 반영하지 않는다.
  진단이 꺼진 경우 이 추가 계산을 생략한다. 없는 값은 None이며 0.0으로 채우지 않는다.
- [ ] 다대상·다문서·다버전·표 관계 부족·동일 ID 충돌·budget·진단 on/off·모두 무관한 질문 회귀를 추가한다.

```python
assert select_context(**inputs, include_diagnostics=False).groups == select_context(
    **inputs, include_diagnostics=True
).groups
assert no_relevant_context.groups == ()
assert conflicting_over_budget.blocked_reason == "conflict_context_budget_exceeded"
```

- [ ] highlighting 전체 단위 테스트, ruff, mypy 통과 후 커밋한다.

### Task 3: 문맥 정책을 버전된 생성 profile에 연결

**Files:** Modify `backend/src/ai_workshop/labs/rag/generation/domain.py`, `generation/profile.py`,
`models/domain.py`, `backend/tests/unit/labs/rag/generation/test_profile.py`, `test_profile_resolution.py`.

**Interfaces:** `GenerationProfile.evidence_budget: EvidenceBudget | None = None`.
기존 profile에는 없으므로 기존 동작을 유지한다. 새 후보는 `context_evidence` JSON을 명시한다.

```json
{"context_evidence":{"version":1,"max_groups":8,"max_units":32,"max_characters":12000}}
```

- [ ] 기존 profile의 None, 후보 profile의 정확한 budget, bool/음수/0/알 수 없는 version 거부를 테스트한다.
- [ ] `-m pytest tests/unit/labs/rag/generation/test_profile.py tests/unit/labs/rag/generation/test_profile_resolution.py -q`로 실패 확인.
- [ ] 기존 immutable JSON 계약에 optional 키를 추가한다. 모두 양의 int이며 bool은 거부한다.
  `max_groups <= max_units`를 검증하고 새 prompt와 context policy가 함께 설정되는 것을 확인한다.
  기존 profile row 수정이나 migration은 하지 않는다.
- [ ] 기존 models profile validation과 generation profile 테스트·타입·린트를 통과시키고 커밋한다.

### Task 4: provider 공통 원문 문맥 입력과 새 프롬프트

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/generation/evidence_payload.py`.
- Modify: `generation/domain.py`, `generation/codex_prompt.py`, `generation/openai_responses.py`,
  `generation/openai_compatible.py`, `generation/prompts.py`, `generation/codex_runtime.py`.
- Create prompts: `generation/prompts/codex-answer-v4.txt`, `generation/prompts/answer-v2.txt`.
- Test: `backend/tests/unit/labs/rag/generation/test_codex_prompt.py`, `test_openai_responses.py`,
  `test_openai_compatible.py`, `test_codex_runtime.py`; Create `test_evidence_payload.py`.

**Interfaces:** `GroundingEvidence` 뒤에 `section_path: tuple[str, ...] = ()`,
`ordinal: int = 0` 추가. `serialize_evidence(evidence: tuple[GroundingEvidence, ...]) -> list[dict[str, object]]`.
기존 element/page/offset/문서·버전·projection·chunk 정보는 재사용한다.

- [ ] 원문 두 units의 ID/text가 보존되고 서로 다른 doc/version/chunk가 구별되는 serialization 실패 테스트 작성.

```python
rows = serialize_evidence((first, second))
assert rows[0]["evidence_id"] == str(first.evidence_id)
assert rows[0]["text"] == first.text
assert rows[0]["document_id"] != rows[1]["document_id"]
assert rows[0]["char_start"] == first.char_start
```

- [ ] `-m pytest tests/unit/labs/rag/generation/test_evidence_payload.py tests/unit/labs/rag/generation/test_codex_prompt.py -q` 실패 확인.
- [ ] 새 prompt일 때만 공통 직렬화를 사용한다. 각 row에 source 메타데이터와 원문을 명시하고
  묶음 ID는 doc/version/projection/chunk 조합으로 결정한다. section_path는 보조 문맥임을 명시한다.
  기존 prompt의 payload와 hash는 유지한다.
- [ ] 새 prompt는 대상·속성·조건·예외를 원문으로 뒷받침하고, 다른 대상의 값을 연결하지 않으며,
  불명확하면 insufficient_evidence를 반환하도록 지시한다. 출력 schema와 현재 wire parser는 유지한다.
- [ ] Codex 허용 prompt 목록·runtime wire 분기를 v4에 확장한다. 세 provider에서 같은 payload,
  기존 prompt 호환, source 지시문을 데이터로 처리, 허용되지 않은 ID 응답 거부를 검증한다.
- [ ] generation 관련 테스트·정적 검사 후 커밋한다. 실제 모델 답변 품질은 Task 7에서 검증한다.

### Task 5: 검색 API 통합, 실제 전달 근거, 요청별 진단

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/search/diagnostics.py`.
- Modify: `search/service.py`, `search/schemas.py`, `search/api.py`, `domains/schemas.py`, `domains/api.py`.
- Test: existing `backend/tests/unit/labs/rag/search/` and `domains/`.
- Create: `backend/tests/unit/labs/rag/search/test_context_generation.py`, `test_diagnostics.py`.

**Interfaces:** 두 SearchRequest에 `include_diagnostics: bool = False`.
SearchResult/SearchResponse에 `grounding_evidence` (기존 EvidenceAnswer 형식 목록), optional `diagnostics`.
diagnostics에는 `resolved_query`, `candidates`, `stages_ms`, `policy`, `candidate_scope="returned_hits"`를 둔다.
각 candidate는 Task 2 결과 및 Task 1 점수/순위, 권한 확인된 source reference를 가진다.
`stages_ms`: `retrieval`, `selection`, `contextualization`, `generation`, `total`의 float|None.

- [ ] 현재 검색 fake runtime에 문맥만 충분한 사례를 추가해 아래 실패를 확인한다.

```python
assert result.selection.status is AnswerStatus.INSUFFICIENT_EVIDENCE
assert runtime.generation_calls == 1
assert result.generation.status is GenerationStatus.ANSWERED
assert {x.evidence.id for x in result.grounding_evidence} == {
    x.evidence_id for x in runtime.last_request.evidence
}
```

- [ ] `-m pytest tests/unit/labs/rag/search/test_context_generation.py tests/unit/labs/rag/search/test_diagnostics.py -q` 실행.
- [ ] Task 1 wrapper 하나를 retrieval, extractive selector, context selector에 공유한다.
  profile budget이 None인 기존 구성은 기존 selection gate 유지, 후보 구성만 context gate 사용한다.
  `_generate`에는 실제 전달할 GroundingEvidence tuple을 명시적으로 전달해 두 곳에서 다르게 재계산하지 않는다.
  전송 목록과 API 목록·audit evidence ID는 같은 목록으로 만든다.
- [ ] diagnostics에는 원문 본문을 중복 저장하지 않고 권한 확인된 source+scores+reason을 담는다.
  원문 열기는 기존 source endpoint를 사용한다. profile/policy 버전을 반환해 점수 비교 기준을 식별한다.
- [ ] 단계별 perf_counter 경과를 재시도 포함 실제 측정한다. 미실행 단계는 None.
  오류는 기존 safe error 유지, 정상 진단 응답에 Cache-Control:no-store 적용.
- [ ] clock을 fake로 주입하는 테스트에서 실제0ms와 미실행None을 구분하고 total이 음수가 아닌지 확인한다.
  병렬 검색 branch 시간을 합산해 전체 검색 시간으로 오표시하지 않는다.
- [ ] 생성 전 권한/버전/전송 승인 재검증 유지. post-retrieval 접근 변경 시 diagnostics도 반환하지 않는다.
  conflict budget 차단은 provider0, 모든 후보 미달은 provider0, 생성하지 않았으면 grounding_evidence=[]로 반환한다.
- [ ] diagnostics on/off 동일 결과, 요청 내 query encode1회, missing score None, 비유한 값 거부,
  권한/승인 철회시 호출0, 전송 미승인 section_path, legacy API 응답 호환, source 링크 회귀를 검증한다.
- [ ] search/domains/generation/retrieval 관련 전체 단위·타입·린트 통과 후 커밋한다.

### Task 6: 모든 인용 연결과 테스트 진단 UI

**Files:**
- Generate: `frontend/src/shared/api/schema.d.ts` (수동 편집 금지).
- Create: `frontend/src/features/rag/conversation/SearchDiagnostics.tsx`, `SearchDiagnostics.test.tsx`.
- Modify: `ConversationAnswer.tsx`, `ConversationPage.tsx`, 관련 test 및 `api.ts`/`types.ts` 필요 범위.
  이 경로들은 모두 `frontend/src/features/rag/conversation/` 아래다.

**Interfaces:** `SearchDiagnostics({diagnostics}: {diagnostics: NonNullable<DomainSearchResult["diagnostics"]>})`.
`grounding_evidence`와 기존 answer/conflicts로 source map을 구성한다. 누락된 인용을 filter로 숨기지 않는다.

- [ ] `node openapi-ts.config.mjs`로 타입 생성하고 기존 conversation 테스트 fixture를 새 optional 필드에 맞춘다.
- [ ] 아래 UI 회귀를 작성한 뒤 기존 코드에서 실패를 확인한다.

```tsx
expect(screen.getByRole("checkbox", { name: "검색 진단 포함" })).not.toBeChecked();
expect(screen.getByText("문맥 코사인 유사도")).toBeVisible();
expect(screen.getByText("미계산")).toBeVisible();
expect(screen.queryByText(/정확도.*%/)).not.toBeInTheDocument();
```

- [ ] 질문 제출에 checkbox 값을 실어 보내고 응답별 접는 진단을 표시한다.
  열: 원문, BM25/순위, dense 원점수/순위, RRF/순위, 문장 cosine, 문맥 cosine,
  keyword coverage/임계값, semantic 임계값, 선택·제외 이유. 시간은 별도 표로 표시한다.
- [ ] null과 실제0을 구분하고 소수 표시만 반올림한다. 원본 값은 accessible 상세에 제공한다.
  진단 표시를 열고 닫는 행위로 재검색·모델 호출을 하지 않는다. 응답 순서별 snapshot 유지.
- [ ] 모든 citation ID는 grounding_evidence를 포함한 map으로 resolve하고 기존 원문 열기/초점 복원을 사용한다.
  알 수 없는 ID는 인용 확인 오류로 표시하고 검증된 답변처럼 조용히 통과시키지 않는다.
- [ ] 새 인용·근거 부족+진단·미실행 단계·복수 턴·키보드 접기/펼치기·문서 선택 관리기능 부재 회귀 실행.

```powershell
node node_modules/vitest/vitest.mjs run src/features/rag/conversation
pnpm typecheck
node node_modules/eslint/bin/eslint.js src/features/rag/conversation --max-warnings 0
node openapi-ts.config.mjs --check
```

- [ ] 통과 후 API와 UI 계약 변경을 함께 검토·커밋한다.

### Task 7: 다양한 질문의 회귀·본래 환경 품질/시간 비교·적용

**Files:**
- Create: `backend/tests/unit/labs/rag/highlighting/test_context_question_matrix.py`.
- Create: `docs/worklogs/2026-09-21-contextual-rag-evidence.md`.
- Modify: `docs/labs/rag/design.md`, `WORKBOARD.md` (완료 사실과 남은 제한만).

- [ ] 합성 fixture의 질문 matrix를 작성해 단위 테스트를 실행한다. 행은 기간/금액/절차/조건/예외/인명,
  한국어 조사·paraphrase, 다대상, 속성 없음, 원문 부정, 무관 질문, 표 메타데이터 부족을 포함한다.
  질문별 기대 evidence IDs, allowed abstention, 금지되는 다른 대상 ID를 명시한다.

```python
@pytest.mark.parametrize("case", question_matrix, ids=lambda case: case.name)
def test_context_selection_matrix(case):
    result = select_context(**case.inputs)
    ids = {unit.id for group in result.groups for unit in group.units}
    assert case.required_ids <= ids
    assert not (case.forbidden_source_ids & {g.source.document_id for g in result.groups})
```

- [ ] 같은 문단에 두 대상이 있는 경우 source를 통째로 금지하지 않고 **생성 답변이 다른 대상 값을 사용하지 않는지**
  실제 후보 모델 평가에서 확인한다. 위 selector 테스트만으로 의미 정확도 통과를 주장하지 않는다.
- [ ] 기존 본래 환경의 승인된 합성 문서와 로컬 모델로 기존 profile/BM25/후보를 같은 질문 집합으로 비교한다.
  새 영속 업로드 자료 없이 코드 fixture/기존 자료로 측정한다. 평가 기록은 기존 승인 범위 내에서 보존한다.
- [ ] 보고서에 코드 revision, 입력 snapshot, profile/정책/모델 버전, 실제 evidence recall,
  생성 입력 포함률, 정답/근거 부족/인용 정확도, 단계별 실제 시간, 실패 사례를 기록한다.
  첫 요청과 반복 요청 시간을 분리하고 원점수를 정확도 %로 바꾸지 않는다.
- [ ] 현재 0.9 등 임계값을 임의로 내리지 않는다. 문맥 평가 결과 필요하면 새 정책 후보를 만들고
  전체 양성·음성 질문을 재검증한다. 평가 결과 없는 기본값 승격은 하지 않는다.
- [ ] 독립 검토자가 code diff와 권한·전송·인용·진단 테스트 결과를 확인한다. 발견 blocker 수정 후 관련 검증만 재실행.
- [ ] 모든 게이트 통과 후 기존 관리 API로 후보 profile/구성을 검증·연결한다. SQL로 평가 상태를 변경하지 않는다.
  기존 서버를 현재 코드로 반영하고 본래 마스터 화면에서 질문→진단→모든 인용 원문을 확인한다.
  로그인 필요시 실제 사용자 세션을 사용하며 비밀번호 조회·인증 우회는 하지 않는다.
- [ ] 실모델 또는 로그인 확인이 막히면 코드 검증과 실사용 검증을 구분하고 차단 원인을 기록한다.
  기존 평가된 구성과 원본을 보존한 채 완료를 과장하지 않는다.
- [ ] WORKBOARD 최근 완료 최대5개 유지, 해당 파일만 커밋·push하고 HEAD/origin 상태 확인.

## 검증 명령과 최종 검토

```powershell
# backend 디렉터리
.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/highlighting tests/unit/labs/rag/retrieval tests/unit/labs/rag/search tests/unit/labs/rag/generation tests/unit/labs/rag/domains tests/unit/labs/rag/embeddings -q
.venv/Scripts/python.exe -m ruff check src/ai_workshop/labs/rag tests/unit/labs/rag
.venv/Scripts/python.exe -m mypy src/ai_workshop/labs/rag
```

기존 실패가 있으면 새 변경과 구분해 정확한 테스트명을 기록한다. 원래 환경 데이터를 변경하는
통합 fixture는 이 명령에 추가하지 않는다. 검색/권한 통합은 기존 본래 자료를 읽는 smoke와 fake-port 회귀로 확인한다.
실제 provider 결과와 브라우저 확인이 완료되기 전 본래 환경 적용 완료라고 보고하지 않는다.

## Self-review and execution handoff

- 설계 §1–4: Task 1–4, §5: Task 5–6, §6: Task 1/5/6, §7: Task 7, §8: 공통 규칙에 대응한다.
- 유사도 표시는 Task 1 원점수→Task 2 cosine→Task 5 응답→Task 6 표시로 연결된다.
- Review Focus 5항목은 각각 소유 Task에 회귀를 명시했다.
- 실행 권장: 메인이 순서대로 구현하고 마지막에 독립 검토. 동일 source/진단 계약을 공유하므로 구현자를
  Task마다 교체하는 방식보다 인계 부담이 적다. 구현자와 최종 검토자 책임은 분리한다.
- 사용자에게 이 계획을 전달해 검토받은 뒤 실행한다. 이번 문서 작성은 제품 구현 완료가 아니다.
