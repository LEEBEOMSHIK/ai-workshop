# RAG Context Budget Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 원문과 관련성 기준을 보존하면서32→128 raw 단위 상한의 효과만 분리하고, 제한된 정상 후보 실행의 답변을 검토한다.

**Architecture:** 제품 선택 알고리즘은 변경하지 않는다. task-local helper가 기존 검색·근거 선택을 한 번 실행하고 요청별 embedding cache를 공유한 두 예산을 비교한다. 입력 비교를 통과한 경우에만 정상 관리 API와 기존 생성 평가 workflow로 새 pending 후보를 검증한다.

**Tech Stack:** 기존 Python3.13.15 venv, pytest, Ruff, mypy, SQLAlchemy AsyncSession, Elasticsearch, RequestScopedEmbedding, httpx, 정상 FastAPI 관리 API.

**Spec:** [승인된 원문 문맥·예산 분리 설계](../specs/2026-10-07-rag-context-budget-isolation-design.md)

상태: 사용자 승인 구현·제한 평가·정상 문제 이력 등록과 독립 최종 보존 검증 완료(2026-10-07). 회귀47+11·타입/린트와 입력32/128 근거 복구는 통과했지만 실제 평가12개는 양성 유보4·생성 요청 실패8로 불통과했다. 활성32를 유지하고 승격하지 않는다. [실행 보고서](../../worklogs/2026-10-07-rag-context-budget-isolation-execution.md) exact DBv1·ISSUE-00005 openr58·기존55테이블 원래 행/9턴/동결10보고서 보존을 확인했다. 체크는 계획 실행의 완료이며 실제 답변 통과 또는 RAG 전체 완료를 뜻하지 않는다.

## Global Constraints

- 본래 루트·`.env`·DB·계정·기존3합성 PDF만 사용한다. 새 환경/DB/계정/문서/대화 세션을 만들지 않는다.
- baseline은8그룹·32원문 단위·12000자, candidate는8·128·12000이며 budget version1이다. `max_units`는 실제 전달 원본 EvidenceUnit 수다.
- generation v4/schema2의 모델/deployment·prompt·temperature·timeout·numeric policy, 처리/색인/검색 profile, answer policy의 모든 업무 필드를 고정한다. 이름·ID·버전 외 허용 차이는 `context_evidence.max_units`뿐이다.
- 이미 비교한 pure-v4/128 generation profile은 재확인 후 재사용한다. 기존128 configuration은 semantic 임계값이 달라 재사용하지 않는다. 다른 업무 차이 발견 시 중단하고 재설계한다.
- 원문 ID/text/순서/location/projection/asset version을 보존한다. 자르기·병합·중복 제거·bbox로 표 관계 추정·가짜 citation ID·provider wire 변경을 하지 않는다.
- 활성32 구성·도메인 연결·옛 pending 후보/평가/판정/승인·동결 보고서·기존 세션·frozen gate1/receipt0을 보존한다. accept/promote/default 변경·새75회·재색인·서버/worker/beat 재시작·Git staging/commit/push·삭제는 범위 밖이다.
- helper 로그/결과/Git에는 질문·정답·원문·벡터·원문 ID 목록·비밀·실패 초안·비공개 추론을 기록하지 않는다. 정상 비공개 평가 DB의 승인된 입력/근거 기록과 counter-only helper 기록을 구분한다.
- 외부 전송은 새 configuration 생성 승인, exact 후보 synthetic 연결 검증 동의, 평가 입력 동의를 정상 API에서 각각 결속한다. 기존 승인 복사/직접 DB 쓰기는 금지한다.
- 생성 사례는 아래6개×최소 반복2회=12회이며 연결 검증 contextualization1+generation1을 포함해 실제 provider 호출 최대14회다. 평가 history는 `{}`이고 자동/수동 재시도·다른 모델 대체·추가 연결 검증은0회다.
- 이번 결과는 제한된 예산 실험이다. 성공해도 자동 승격·전체 품질/기능 마감으로 보고하지 않는다. SDK→벡터 저장소 비교→로컬 LLM 학습의 후속 순서는 유지한다.

## Review Focus

1. 비교 중 현재 권한/READY 버전/alias가 바뀌면 자료를 대체하지 않고 중단한다(Task2).
2. 두 번째 예산 검사에서 cache miss나 점수/적격 순서가 다르면 예산 효과를 주장하지 않는다(Task1·2).
3. 원문 글꼴 조각·같은 텍스트의 다른 ID·충돌 쌍을 임의로 줄이지 않는다(Task1).
4. 생성 POST의 모호한 timeout과 새 snapshot case UUID를 처리할 때 중복 후보/시도·옛 판정 복사를 만들지 않는다(Task3).
5. 허용된 숫자라도 다른 대상·기간·조건을 차용하면 독립 의미 판정을 실패로 남긴다(Task4).

## 파일 지도와 공통 검증

향후 helper 루트 `H=.local-data/project-agent-work/rag-context-budget-isolation-implementation-20261007` 아래에만 실행 코드를 둔다. 아래 `H/…`는 이 정확한 경로의 약기다.

| 파일 | 책임 |
| --- | --- |
| `H/compare_budget.py`, `H/test_compare_budget.py` | 기존 selector의 동일 입력 예산 비교·회귀 |
| `H/compare_original.py`, `H/test_compare_original.py` | 본래 읽기 전용 조합·drift/ACL 검사 |
| `H/prepare_candidate.py`, `H/run_limited.py`, `H/test_limited_contracts.py` | 정상 후보/6문항 snapshot·최대14회 실행 결속 |
| `H/review_results.py`, `H/test_review_results.py` | 안전한 집계·exact 결과 수동 판정 결속 |
| `docs/worklogs/2026-10-07-rag-context-budget-isolation-execution.md` | 실제 관측·실패·한계 보고서; 완료 후 DB에 exact v1 동결 |
| `WORKBOARD.md`, `docs/labs/rag/design.md` | 시작/종료 상태·최근 완료 최대5개·다음 순서 |

각 task의 테스트는 합성 입력과 fake ports만 사용하며 네트워크/실모델/실DB 쓰기는 금지한다. 루트에서 `backend/.venv/Scripts/python.exe -m pytest H/test_<해당파일>.py -q`를 RED→GREEN으로 실행한다. 실제 명령에서는 H를 위 경로로 치환한다. 각 task 뒤 같은 Python으로 `-m ruff check H`와 `-m mypy --follow-imports=silent H`를 실행해 exit0을 확인한다. 기존 관련 회귀는 마지막에 한 번 실행한다.

## Task 1: 동일 입력 비교기

**Interfaces:** `compare_context_budgets(*, query: str, sources: tuple[EvidenceSource, ...], extractive: EvidenceSelection, policy: AnswerPolicy, baseline: EvidenceBudget, candidate: EvidenceBudget, embedding: RequestScopedEmbedding, required_evidence_groups: tuple[tuple[UUID, ...], ...]) -> BudgetComparison`. `CountingEmbeddingPort(delegate: EmbeddingPort)`는 dimension/count_tokens/count_query_tokens/encode_query/encode_documents의 기존 계약을 그대로 위임하며 encode_calls/encode_items 정수만 누적한다. 입력 cache의 delegate로 이 wrapper를 사용한다. `BudgetTotals(groups: int, units: int, characters: int)`와 `BudgetComparison(baseline: BudgetTotals, candidate: BudgetTotals, second_delegate_calls: int, second_delegate_items: int, integrity_verified: bool, budget_only_rescue: bool)`는 frozen dataclass이며 본문/ID 목록을 포함하지 않는다. 실패는 body-free `ComparisonInvariantError`로 중단한다.

- [x] `test_compare_budget.py`에33단위/712자와36단위/683자의 두 적격 그룹을 만들고32에서는 `(0,0,0)`,128에서는 `(2,69,1395)`를 assert한다. 별도 미달38단위 그룹은128에서도 제외하고 source text/location/IDs 원본 불변을 assert한다.
- [x] 같은 테스트에 누적128초과·8그룹·12000자 제한, 충돌 쌍의 한쪽만 수용 시 전체 차단, 동일 문자열/다른 ID 보존, 진단 on/off의 선택 동일을 추가한다. max_units 이외 예산/업무 필드 차이와 cache miss·embedding 실패를 raise로 고정한다. RED를 확인한다.
- [x] `compare_budget.py`에서 기존 `select_context`를 두 번 호출한다. 동일 source/query/extractive를 메모리 digest로 검사하고 diagnostics의 적격·순서·점수를 비교한다. selected/reason/budget_trace만 허용 차이이며 두 번째 delegate 추가 call/item0을 검사한다. 진단 경고는 중단한다. required_evidence_groups의innerOR/outerAND를128에서모두충족하고32에서는unit-budget만때문에누락된경우에만 budget_only_rescue=true로 계산한다. empty groups/총량만증가/미달/충돌에는false다. 이 flag는 Task2의 원문 의미 검토를 대체하지 않는다. 원문/벡터 cache는 요청 종료 시 폐기한다.
- [x] GREEN·Ruff·mypy를 확인한다. cache 재사용의 시간 차이를 서비스 응답 속도 비교로 집계하지 않는다.

## Task 2: 본래 환경의 읽기 전용 입력 비교

**Interfaces:** `async compare_original_cases(*, settings: Settings, actor_id: UUID, configuration_version_id: UUID, case_codes: tuple[str, ...]) -> tuple[BudgetComparison, ...]`. case codes는 아래6개만 허용하며 query는 기존 로컬 정답표에서 메모리로 읽는다. actor/version은 본래 활성 연결에서 읽고 이름으로 선택하지 않는다.

- [x] 실제 조회 시작 전 독립 담당이 기존 보호55테이블의 기존행 manifest/SHA·대화/9턴·동결9보고서·옛 run/judgment/profile/config/승인·활성 연결·gate/receipt·환경/프로세스의 정확한 기준선을 읽기 전용으로 고정한다. 목록/비밀/본문은 출력하지 않는다. 보존용 REPEATABLE READ READ ONLY 기준선과 실제 current ACL용 READ COMMITTED 세션은 분리한다. 새configuration POST 직전 같은 baseline을 다시 확인한다.
- [x] `test_compare_original.py`에서 권한 취소·READY/원문 버전·processing profile·alias target UUID/build drift 각각 중단, COMMIT/INSERT/UPDATE 금지, generation/runtime/audit 호출0, retrieval 사례당1회, fresh 재검사 실행을 assert하고 RED를 확인한다.
- [x] `compare_original.py`를 READ COMMITTED READ ONLY 세션으로 구성한다. engine echo를 끄고 hide_parameters를 사용하며 무조건 rollback/close한다. 원본3 PDF의 기존 manifest SHA, active profile/binding/model/answer policy, alias/build를 전후 비교한다. 권한 재확인은 fresh session으로 수행한다.
- [x] `SqlAlchemySearchConfigurationResolver.resolve_version`→`SearchScopeResolver(SqlAlchemySearchScopeRepository)`→기존 ES sparse/dense + `HybridRetrievalService.search`→`SqlAlchemySearchSourceResolver.resolve`→`EvidenceSelector.select`를 조합한다. 기존 workspace subset/document IDs/processing exact 범위를 전달하고 hits와 resolved sources의 chunk 집합 일치를 검사한다. 선택 여부와 무관하게 검색 반환 모든 source의 원본4-tuple identities를 selection 전후 fresh scope에 대해 `require_authorized_identities`로 재검사한다. 전체 SearchApplicationService·RuntimeFactory·codex_services·ExecutionObserver·authoring preview는 생성하지 않는다.
- [x] 사례마다 단일 RequestScopedEmbedding을 Task1에 전달한다. 자료/설정/질문/추출/모델 digest는 메모리에서만 비교하고 scalar count/time/검증 flags만 `H/input-comparison.json`에 기록한다. 기존33/36 관측을 실제 새 결과에 강제하지 않는다. 기존 authoritative rule의 original required_evidence_groups와 query SHA를 메모리로 재결속한다. 각 inner group은대안OR, outer groups는모두AND이며128이모두충족·32의누락은unit-budget만원인·선택fullchunk의원본units전체보존·원문대상/조건/예외검토까지확인한 경우에만 budget_only_rescue=true로 반환한다. 이런 사례가 최소1건이고 모든 무결성 검사가 통과한 경우만 Task3으로 진행한다. 미달 사례의 임계값을 낮추지 않는다.
- [x] `test_compare_original.py`에 totals만증가/다른필요근거의 rescue=false, 각 OR대안중하나/모든outer충족의true, querySHA/rule/source version 불일치의중단, threshold미달/conflict취소의false, SYN-Q15의근거부재·생성전유보유지 검사를 추가한다. 입력비교에서는 유보할 수 있음을 확인하며 실제 음성답변은 Task4에서 별도 검증한다.
- [x] fake tests GREEN·Ruff·mypy 후 실제 본래6사례의 로컬 비교를 실행한다. provider 호출0·후보/평가 DB append0을 독립 확인한다. 실패하면 생성 준비를 하지 않고 원인과 열린 조건을 기록한다.

## Task 3: 정상 pending 후보와 제한된 생성

**Interfaces:** `async prepare_candidate(*, client: httpx.AsyncClient, baseline_version_id: UUID, reused_generation_profile_id: UUID, input_comparisons: tuple[BudgetComparison, ...]) -> PreparedCandidate`; `PreparedCandidate(configuration_version_id: UUID, dataset_snapshot_id: UUID, case_id_map: dict[str, UUID], rules: dict[UUID, ExpectedAnswerRule])`는 task-private이며 출력하지 않는다. `async run_limited(*, client: httpx.AsyncClient, prepared: PreparedCandidate, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> UUID`는 run ID만 반환한다.

| 사례 | 검토 유형 | 기대 |
| --- | --- | --- |
| SYN-Q01 | 유사 표현·대상 구분 | 직접 원문 답변 |
| SYN-Q02 | 표·속성 구분 | 직접 원문 답변 |
| SYN-Q03 | 조건·예외 | 직접 원문 답변 |
| SYN-Q04 | 날짜 | 직접값 답변; schema2에서 미지원 계산을 성공 지표로 사용하지 않음 |
| SYN-Q13 | 다중 문서 | 필요한 문서별 원문 근거 |
| SYN-Q15 | 없는 속성 | 근거 부족·답변 유보 |

- [x] `test_limited_contracts.py`에 다른 업무 설정/동의 누락/입력 비교 실패의 생성0, ambiguous POST의 blind retry0, candidate1·case6·repetition2·history{}·rules exact newcase keys·12attempts·provider≤14를 assert한다. old UUID/rule 복사·retry/accept/default 호출은 실패하게 만들고 RED를 확인한다.
- [x] `prepare_candidate.py`에서 원래 owner 정상 로그인·mutation headers로 설정을 재확인한 뒤 현재 typed disclosure의 `external_transfer_approval`를 포함해 `POST /api/v1/rag/configurations`로 pending1개만 만든다. 활성 answer policy 업무 값은 복사하되 새 정책 ID는 정상 생성 계약을 따른다. 생성 전후 unique task 이름+exact 설정을 조회하고 모호한 timeout에는 재POST하지 않는다. 원본/옛 후보는 수정하지 않는다.
- [x] 새 exact configuration version의 정상 `codex-status`/`codex-verify`와 입력 동의를 사용한다. 연결 검증은2 provider 호출을 소비한다. 실패/timeout이면 중단하며 추가 검증으로 상한을 채우지 않는다. 정상 생성 승인·연결 proof·평가 approval은 다른 결속임을 receipt에 기록한다.
- [x] 정상 `evaluation-authoring/preview`에서 동일3 asset versions와 scope SHA를 검증하고 `/snapshots`로6개만 보관한다(`retention_confirmed=true`, retrieval_k10, repetition2). 기존25 snapshot은 변경하지 않는다. 양성은 authoritative expected IDs+기존 정확한 highlight, 음성은 IDs empty/highlight none이다. 반환 snapshot의 새 case UUID와 code·query UTF8 SHA·expected IDs·rule digest를 메모리에서 결속한다. 정답/rules는 생성 prompt에 전달하지 않는다.
- [x] `run_limited.py`에서 readiness 성공·정확6case/rules·12행 예상·14상한·단일 실행자 확인을 마친 후 정상 생성 평가 API에 request UUID·후보1·반복2·history{}·입력 동의로 한 번 제출한다. 기존 `GenerativeWorkflow(sessions, settings).run(run_id)`을 원래 루트/venv에서 한 번 실행하고 전역worker/beat는 시작하지 않는다. claim 충돌이나 불확실한 진행은 상태 조회로 확인하고 재제출/재시도하지 않는다.
- [x] GREEN·Ruff·mypy 후 정상 API 실행을 진행한다. stage audit에서 연결2회+평가 최대12회·actual provider 호출·실패/거절/미호출을 별도로 확인한다. counter/단계시간/serialized_bytes/보고된 사용량만 helper에 집계하며 requested 모델과 actual 미관측은 구별한다. 기존32 기록은 과거 기준선으로만 표시하고 새 E2E와 동일 반복의 속도 비교라고 하지 않는다.

## Task 4: 독립 의미 검증과 보존 확인

**Interfaces:** `AttemptReviewInput(state: str, observation: GenerativeObservation | None, judgment: Literal['passed', 'failed', 'unreviewed'] | None)`는 frozen dataclass다. `summarize_attempts(*, attempts: tuple[AttemptReviewInput, ...]) -> dict[str, int | float | None]`는 본문을 반환하지 않는다. `async record_review(*, client: httpx.AsyncClient, run_id: UUID, attempt_id: UUID, result_digest: str, status: Literal['passed', 'failed'], reason: str) -> None`는 독립 담당자가 원문과 대조해 결정한 새 판정만 정상 judgment API에 결속한다. reason에는 본문/비밀을 넣지 않는다.

- [x] `test_review_results.py`에서 completed≠passed, 검증거절/timeout은 별도 집계, 다른 대상/기간/조건의 허용값 차용은 failed, negative 허구 답변은 failed, result digest 불일치/옛 결과 판정 복사는 거절, summary 본문/ID 목록0을 assert하고 RED를 확인한다.
- [x] `review_results.py`를 구현해 새12시도의 정상 유효 결과마다 exact 원문 버전·대상·조건·예외·숫자/단위/기간·자기 인용 위치를 독립 검토한다. provider 실패/거절에 가짜 의미 판정을 만들지 않는다. 모든 새 판정은 exact run/attempt/result digest에 결속하고 accept/promote를 호출하지 않는다.
- [x] Task2의 사전 baseline과 비교한다. 허용 append whitelist는 새configuration1+정상policy/승인, 6case snapshot1, run1/attempt12, exact 연결proof/정상audit, 새judgments와 최종보고서/version/link/event 및 정상 로그인·로그아웃의 새 인증세션뿐이다. generation profile 신규0·원본문서/대화세션 신규0·이전평가/판정·불변cfg/profile payload 변경0이다. 정상 이력 추가에 따른 ISSUE-00005 revision/updated_at 변경은 명시적 예외이며 기존status/업무fields/event IDs/link rows는 보존한다. 활성 연결·원문/기존대화·동결9보고서·gate1/receipt0·환경/프로세스는 보존한다. 독립 담당은 구현을 하지 않고 원문/privacy/보존을 검증한다.
- [x] GREEN·Ruff·mypy 및 기존 `backend/tests/unit/labs/rag/highlighting/test_budget_trace.py`, `backend/tests/unit/labs/rag/search/test_context_generation.py`를 위 Python의 pytest로 실행해 실제 결과를 확인한다. 제품 코드 변경이 필요하면 이 계획을 확대하지 않고 재분류한다.
- [x] 실행 보고서에 합성 회귀·실제 입력 비교·정상 후보 E2E·의미 검토를 구별해 기록한다. WORKBOARD 최근 완료5개/다음 작업과 설계 상태를 갱신하고 링크/UTF8/공백을 검증한 뒤 정상 issue-history API로 ISSUE-00005에 exact 보고서 버전을 추가한다. 옛 보고서와 사건/상태는 유지한다. 유효 대화/멀티턴·별칭 종료·DLL 재발 방지·Git 인계 등 전체 기능 마감은 별도로 열린 상태임을 명시한다.

## Execution Handoff

이 계획을 사용자에게 링크하고 의도와 일치하는지 검토받은 뒤, 보존된 메인 직접 구현(`executing-plans`)·독립 검증 방식으로 Task1부터 진행한다. 이번 계획 작성 단계에서는 helper·새 후보/snapshot/run·실모델 호출을 시작하지 않는다.
