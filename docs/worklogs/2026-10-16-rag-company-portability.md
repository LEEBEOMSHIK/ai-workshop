# 업체 변경 시 RAG 적용 범위 오프라인 감사 — 2026-10-16

## 결론과 승인 범위

업체 A/B가 같은 상품명을 사용하면서 지급일·마감 시각을 다르게 정한 합성 문서를 동일 질문·동일 공통 프롬프트로 전달할 수 있다. 특정 업체·상품의 정답을 제품에 주입하는 상수는 이번 조사에서 발견하지 않았다. 그러나 **환매 표 선택은 업무·표현·레이아웃에 특화되어 있으며, 제품 전체의 업체 독립성이나 다중 tenant 격리, 실제 답변 품질이 입증된 것은 아니다.**

변경은 신규 오프라인 테스트와 이 문서·WORKBOARD뿐이다. 제품 코드·공통 프롬프트·활성 프로파일은 그대로다. 실모델 추가 호출 0회이며 이전 2/2 호출 예산은 소진 상태로 유지한다. DB/ES/Docker 변경, 설치·재시작·환경 삭제, 보안 설정 변경, commit/push를 하지 않았다. 학습 문서와 예약도 변경하지 않았다.

작업은 중간 위험의 RAG 호환성 감사로 분류했다. 메인이 RAG 분석·테스트 설계를 맡고 독립 검토자 `company_scope_review`가 보안·권한 경로, 오프라인 검증, 새 테스트 코드를 검토했다. 인프라·배포·DB 구현은 범위에서 제외했다. 작업 상태 도구에서 별도 로컬 ai-workshop 작업은 notLoaded였고, 같은 작업 제목의 durable 작업은 active였다. 전체 활동 부재를 가정하지 않고 새 파일을 사용했으며 WORKBOARD 쓰기 직전 SHA를 확인했다.

## 제품 분기와 fixture 구분

| 확인 대상 | 실제 코드·의미 | 판단 |
|---|---|---|
| 공통 답변 프롬프트 | `generation/prompts/answer-v1.txt`~`answer-v4.txt`, Codex 프롬프트들을 직접 읽음 | 대상·규칙·조건·예시를 구별하라는 지침이며 업체 정답표는 없음. v4는 명시 선택형이고 활성화하지 않음 |
| 원문 연결 | `generation/source_reading.py::build_source_reading`, `_adjacent`, `_scope` | 텍스트·질문 의미를 분류하지 않고 문서/버전/투영/청크/위치 연속성으로 ID 목록만 추가. 의미 관계·권한을 판정하지 않음 |
| 생성 입력 | `generation/openai_compatible.py::_generation_user_content` | 제공된 근거를 직렬화하고 v4에서만 연결 힌트 추가. 업체를 식별하거나 업체별 문서를 필터하지 않음 |
| 표 특수 선택 | `highlighting/table_context.py::payment_table_units`, `highlighting/context.py::select_context` | 환매/현금화/인출+시간+대금 수령 표현, 지급일 행 이름, PDF 단일 페이지·정렬된 열 구조에 의존. 상품 이름은 헤더에서 동적으로 가져오며 수치는 원문 셀을 사용 |
| 충돌/수치 휴리스틱 | `highlighting/service.py::_single_numeric_claim`, `_explicit_polarity`; `generation/exact_values.py::exact_values` | 지원 단위·한국어 접미사·긍정/부정 표현·날짜 형식이 한정됨. 모든 업체 언어/단위에 대한 의미 검증기가 아님 |
| 수치 증명 선택 기능 | `generation/numeric_proof_types.py::CalculationOperation`, `prompts/codex-answer-v6.txt` | 퍼센트포인트 차이와 원/만원/억원 변환으로 연산 범위가 한정됨. 변환 계수는 단위 계약이며 업체의 정답 상수가 아님 |
| 기존 평가 fixture | `tests/fixtures/rag/offline_payment_rubric.json`, `source_reading_cases.json`, `stored_payment_table.json` | 특정 공개/합성 사례와 기대 조건은 테스트 데이터. `evaluation/offline_rubric.py`의 사용자 지정 literal rubric은 오프라인 탐지용이며 제품 답변 정답표가 아님 |

추적/미추적 파일을 포함한 `backend/src`의 `.py`·`.txt` 487개를 조사하고 SHA를 보존했다. `AM-SYN`, `ORCHID-71`, `CEDAR-82`, `T+4`, `09-14`, `200시간`, `37일` 검색 결과는 0건이었다. `company_id/tenant_id/organization_id`도 없었다. 이는 지정 문자열 검사 결과이며 모든 숨은 의존성이 없다는 증명은 아니다. 프롬프트와 선택·생성·권한 경로를 별도로 읽어 판단을 보완했다. 제품명 AI Workshop, provider 계약, 단위·형식 상수는 업체별 업무 정답과 구분한다.

## 동일 질문 A/B와 실패 경계

신규 `backend/tests/unit/labs/rag/generation/test_company_portability.py` 20개:

- `test_same_question_and_prompt_transmit_each_company_rule_and_conditions`: 같은 `COMMON-17을 현금화하면 돈은 며칠 뒤 받을 수 있어?`로 A는 T+2·10시, B는 T+11·16시를 전달한다. A/B의 합성 workspace/문서/asset/projection/chunk/build/evidence/element ID도 구별한다. `select_context → _grounding_evidence → LocalOpenAICompatibleRuntime.generate`의 실제 직렬화·파싱 경로를 실행하고 I/O 경계만 mock으로 바꾼다. v3/v4 각각 시스템 프롬프트가 A/B에서 동일하고 원문·식별자·부정 조건이 보존됨을 확인한다. 다른 상품 열 5개는 기존 설계대로 제외되며 전체 문서가 무손실이라는 주장은 하지 않는다.
- `test_table_numeric_substitution_uses_source_value_without_answer_constants`: 1/4/23/108로 바꿔도 해당 원문 객체·수치가 선택된다.
- `test_table_selection_preserves_prose_or_declines_reference_wording`: 상충하는 T+12 본문과 다른 상품 날짜 예시는 실제 표 선택·생성 입력을 거쳐 그대로 남는다. **“같은 조건”** 표현은 `_REFERENCE`의 `같[음은다]`에 걸려 특수 선택이 거절된다. mock 의미 점수 0.87가 기준 0.9보다 낮아 일반 청크도 선택되지 않는다. 유효 규칙이 있어도 입력이 비게 될 수 있는 어휘 의존 한계이며 충돌 해결 성공이 아니다.
- 규칙 없음/상충/다른 숫자+무관 예시/예시만 있는 사례 4개 × v3/v4: 직렬화 단계에서 원문 그대로이고 합성 답을 추가하지 않음을 확인한다. 이 8개 자체는 검색·문맥 선택·모델 유보 판단 검증이 아니다.
- 혼합 문서 사례: 연결 힌트는 A/B 문서 사이를 잇지 않지만 두 문서를 모두 입력에 남긴다. 연결 힌트는 ACL 필터가 아니다.
- 지급 행 누락/미지원 `지급 일정` 표현: 낮은 점수에서는 특수 경로로 승격되지 않는다. 일반 검색 점수가 충분할 때까지 거절된다는 의미는 아니다.

mock 응답은 작성된 빈 claims를 돌려준다. 그 통과는 입력 계약 호환성만 보여 주며 A/B에 대해 모델이 서로 다른 정답을 생성했다는 뜻이 아니다. 조건 적용·상충 해석·예시 오용·환각·유보 적절성은 실제 모델 없이 판정할 수 없다.

## 실제 검색·출처 권한 경계

| 경로 | 확인한 동작 |
|---|---|
| `platform/workspaces/permissions.py:18 workspace_read_allowed` | 활성 사용자, 멤버십, 개인 소유자, 임시 공간 만료, COMPANY 공간의 owner/read 권한 |
| `retrieval/scope.py:216 SearchScopeResolver.resolve` | 요청 workspace 권한, 폴더·문서 소속, READY/활성 asset→projection→build tuple 확정 |
| `retrieval/elasticsearch.py:195 build_scope_filter` | workspace, allowed_user_ids, READY, 정확한 lifecycle tuple을 BM25 bool.filter와 kNN.filter 양쪽에 검색 전에 적용 |
| `search/pipeline.py` | 구성 workspace 제한, 범위 확정과 응답 시점 현재 권한 재확인 |
| `search/repository.py:54 SqlAlchemySearchSourceResolver.resolve` | DB workspace 권한·수명주기와 ES 결과 식별자 대조 |
| `search/viewer_repository.py:24`, `search/viewer.py:184 _authorize` | 현재 권한 후 원본/파싱 파일 접근, 부적격 요청 일반 404 |
| `domains/service.py:232 resolve_allowed_workspaces` | 도메인 연결 ∩ 구성 ∩ 사용자 workspace. 업체 자동 식별 아님 |

`WorkspaceRecord`와 RAG Domain 모델에는 별도 회사 FK/tenant entity 연결이 없다. `WorkspaceKind.COMPANY`는 공간 종류다. 두 workspace를 읽을 수 있는 사용자는 구성에서 허용하면 둘 다 검색할 수 있고, 같은 workspace에 A/B 문서가 있으면 문서 ID가 달라도 업체 경계가 자동 생기지 않는다. 현재의 **사용자·workspace ACL**과 별도 **업체 tenant 격리**를 혼동하지 않는다. 합성 A/B 전송 실험은 실제 DB의 서로 다른 업체 회원·ACL을 검증하지 않는다.

## 실행 검증과 보존

실행 환경은 기존 `backend/.conda/python.exe`, 외부 모델/네트워크 없는 검증이다. 결과 파일은 `.local-data/project-agent-work/rag-company-portability-20261016/`에 둔다.

- 신규 테스트: 20 passed / 5.65초 (`new-tests.xml`). 독립 재실행 20 passed / 5.49초, 차단할 테스트 결함 없음. 검토 SHA `9243ea2732691e3f4a866a9ac4ac67b817836887e0d62e2d36fb3817b821877c`.
- 최종 관련 회귀: 173 passed / 17.25초 (`regression.xml`). 신규 테스트, `test_source_reading.py`, `test_source_reading_mock.py`, `test_http_evidence_groups.py`, `highlighting/test_table_context.py`, `highlighting/test_stored_table_context.py`, `evaluation/test_offline_rubric.py`를 `pytest -q`로 함께 실행했다. 앞선 170통과는 표 본문 사례 3개 추가 전 결과다.
- 신규 파일 Ruff 통과. Mypy는 `MYPYPATH=src`, `--strict --follow-imports=silent --explicit-package-bases`로 신규 테스트 1파일 통과. 기존 untyped fixture 호출에만 `no-untyped-call` 예외를 명시한다. 프로젝트 전체 Mypy 통과로 확대하지 않는다.
- 독립 권한 pytest: `test_document_selection.py`와 `test_elasticsearch.py`의 `test_active_scope_without_authoritative_lifecycle_is_match_none`, `test_independent_asset_and_build_lists_do_not_authorize_live_search`: 12 passed / 3.00초.
- 독립 보충 검증: 기존 scope 무인자 async 17개와 BM25/dense 동일 ACL 1개를 즉시 완료 coroutine 직접 구동으로 확인. 이벤트 루프/실DB/실ES/pytest async 통과가 아닌 mock 경계 검증이다.
- 중간 실패도 구분: 최초 Mypy는 src 경로 누락과 untyped helper 오류, 다음에는 Any 반환 오류가 있었고 실행 경로·테스트 타입 선언을 고쳐 최종 통과했다. 표 본문의 “같은 조건”도 최초에는 선택을 기대해 1실패했으나 제품 참조어 분기를 확인해 거절 한계 테스트로 명시했다. 제품 동작을 바꿔 통과시키지 않았다.

작업 후 제품 코드·프롬프트 487파일 SHA가 모두 동일하고 WORKBOARD를 제외한 기존 tracked binary diff도 최초 스냅샷과 같음을 확인했다. 신규 테스트 검토 SHA도 최종 파일과 일치한다. 기존 untracked 전체의 무변경까지 SHA로 증명한 것은 아니며, 해당 파일에 쓰기 작업을 하지 않았다.

## 미실행·남은 작업

실제 모델 답변/속도, 실DB 멤버십·ES ACL 동기화, 실검색 E2E, 동시 권한 철회는 실행하지 않았다. 별도 tenant 격리 구현·업체 자동 식별·범용 표 해석은 이번 작업에서 추가하지 않았다. ISSUE-00013 및 운영 차단의 DB 정본을 수정/종결하지 않았으며 과거 open/r33 기록을 새 운영 조회 결과로 주장하지 않는다.

다음 후보는 기존 RAG P0 순서를 유지하면서 **일반적인 표 행·열 및 주변 조건 관계 선택 설계**를 검토하는 것이다. 특히 기존 환매 전용 경로와 참조어 보수적 거절의 범위를 대체/확장할지 성공 기준을 먼저 정해야 한다. 업체별 별도 정답표나 이름 분기를 추가하는 방식은 해결로 간주하지 않는다. 실모델 재평가·실환경 권한 검증·tenant 설계 확장은 별도 범위와 승인이 필요하다. Agents SDK 이후 단계나 학습 진도를 완료 처리하지 않는다.
