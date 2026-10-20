# 2026-10-16 선택형 v4 답변 구성과 원문 읽기 안내

## 목적과 현재 결과

사용자는 일반 규칙·적용 조건·예시를 근거와 연결하는 답변 구성 개선과 상세 설명을 요청했다. 이어서 질문별 정답이나 특정 용어를 제품 분기에 넣는 방식인지 명확히 설명하도록 요청했다. 구현은 **질문별 정답 주입 없이 범용 작성 지침과 파서 원문 순서 안내를 제공하는 opt-in v4**로 한정했다. 활성 설정은 변경하지 않았으며 실제 모델의 답변 품질·속도 개선은 미검증이다.

중간 위험의 생성 입력 변경이다. 메인 Codex가 요구·RAG·AI 구현·테스트 설계를 맡고, 별도 검토자가 읽기 전용 설계·코드 리뷰와 모의 실행을 맡았다. DB·배포·보안 변경이 없어 해당 역할은 제외했다. 시작 시 상태 도구, git status/diff, 작업 보드와 관련 코드·지침을 확인했고 기존 미커밋 변경을 보존했다. 원래 수정된 파일3개는 작업 직전 SHA를 확인하고 필요한 줄만 추가했다. 새 브랜치·worktree로 전환하지 않았다.

## 세 종류의 변경을 구분한다

### 1. 프롬프트: 범용 작성 절차

`generation/prompts/answer-v4.txt`는 다음을 요구한다.

- 질문 대상·속성과 일반 기준 질문/특정 사례 질문을 구분한다.
- 일반 규칙 질문에는 원문이 실제로 정한 규칙과 단위·기준 시점을 먼저 답한다.
- 그 규칙에 적용된다는 관계가 원문에서 확인되는 조건·제한·예외만 함께 설명한다. 조건이 결과를 제한하면 같은 주장에 담고 관계를 지지하는 조각을 함께 인용한다.
- 예시는 필요한 경우에만 구별해서 사용한다. 예시만 있는 자료에서 일반 규칙을 만들어내지 않는다.
- 관계가 없거나 불명확하면 추정하지 않고 기존 빈 claims 거절 계약을 사용한다.

이것은 질문별 정답표가 아닌 범용 지침이다. 상품명·특정 기간·특정 날짜는 포함하지 않는다. 규칙/조건/예시의 **의미 구분은 여전히 모델의 해석에 의존**한다. 이 프롬프트를 추가했다는 사실만으로 정확도 개선을 주장하지 않는다.

### 2. 입력 데이터 구조: 위치 기반 읽기 안내

변경 전 `openai_compatible._generation_user_content()`는 원문과 출처 메타데이터를 묶어 전달했다. v4는 이 자료를 그대로 두고 `source_reading` 필드를 하나 추가한다.

```text
기존: 질문 + evidence 원문/ID + evidence_groups 출처 메타데이터
v4:  기존 입력 그대로 + source_reading(파서 순서가 연속인 ID 목록)
출력: 기존 schema_version/status/claims/evidence_ids 계약 그대로
```

새 `source_reading.build_source_reading()`은 원문의 단어·질문·상품·날짜·숫자 값을 읽어서 분류하지 않는다. `_adjacent()`는 document/version/projection/chunk, page, source_kind/source_part, table_cell, section_path 경계를 비교하고 ordinal이 바로 다음이며 앞 char_end와 뒤 char_start가 같은지 확인한다. 현재 선택 순서를 바꾸지 않고 길이2 이상인 연속 구간의 ID만 제공한다. 누락 구간·역순·출처 혼합·잘못된 좌표는 연결하지 않으며 중복 evidence ID가 있으면 안내 목록을 만들지 않는다.

PDF 파서는 문서 전체 char_offset을 누적하므로 서로 다른 element_id도 파서 순서상 연속일 수 있다. element_id와 각 위치는 원래 evidence에 그대로 보존하고, ID를 합친 새 인용이나 합성 본문을 만들지 않는다. 실제 저장 입력의 ordinal26/27처럼 분절된 조건 문장을 함께 읽을 수 있도록 돕지만, 이는 **문장/대상/조건의 의미 관계를 증명하지 않는다**. 다단 PDF나 표에서는 인접 조각의 주제가 다를 수 있다.

출력 안내는 `basis: parser_source_order_only`, `semantic_roles: not_assigned`를 명시한다. 처음 검토했던 키워드 기반 rule/condition/example 후보 분류는 사용자 clarification 이후 구현 전에 제외했다. `T+숫자`, “예시” 등의 표현만으로 의미 역할을 추측하지 않는다. section_path는 보수적인 경계 비교에만 사용하며 내용의 사실 근거로 사용하지 않는다.

v4 전용 분기는 HTTP 호환 생성 어댑터에만 연결했다. 다른 provider의 wire 경로를 이 작업에서 변경하거나 검증하지 않았다. 기존 검색·문맥 선택·순위·권한·숫자 인용 검사·응답 스키마는 변경하지 않았다. 따라서 이번 일반성 검증은 생성 입력 안내 범위이며 기존 검색 선택 규칙 전체의 도메인 독립성을 입증하지 않는다.

### 3. 평가 fixture: 실패와 변형을 고정한 테스트 데이터

`tests/fixtures/rag/source_reading_cases.json`은 공개 합성 저장 근거28개와 원본 입력 SHA, 변경 전 v1~v3 wire6개 SHA, 별도6개 합성 시나리오를 담는다. 지급 질문의 상품·기간·날짜는 테스트 데이터에만 남고 제품 분기에 들어가지 않는다.

| 시나리오 | 확인하는 것 |
| --- | --- |
| 기존 지급 실패 | 규칙 표 항목/값 및 분절 조건 원문의 ID가 연결되고, 원문28개는 무손실 |
| 프린터 필터 점검 | 지급과 무관한 기간·조건 입력도 동일 위치 알고리즘 적용 |
| 도서 대출 | 다른 도메인의 규칙·제한을 코드가 의미 분류하지 않음 |
| 로그 보관과 바뀐 수치/날짜 | 특정 숫자나 날짜와 무관하게 동작 |
| 예시만 있는 근거 | 일반 규칙을 코드가 새로 생성하지 않음 |
| 규칙 없는 근거·규칙 표제의 부정문 | 키워드만으로 규칙이라고 표시하지 않음 |

각 시나리오의 원문을 같은 길이의 무의미한 문자로 전부 바꿔도 위치/ID가 같으면 동일한 안내를 반환한다. 이는 **단어 기반 분류가 없다는 증거**이며 의미 이해 정확도 증거가 아니다.

## 구현 파일과 호환성

- 신규 `generation/source_reading.py`: 위치 비교와 ID-only 안내 생성.
- 신규 `generation/prompts/answer-v4.txt`: 범용 답변 구성 지침.
- 기존 `generation/prompts.py`: v4 파일·버전 등록2줄 추가.
- 기존 `generation/openai_compatible.py`: import와 v4 전용 입력 분기 추가. v4에 명시적 evidence budget이 없으면 거부.
- 기존 `models/context_evidence.py`: v4를 명시적 문맥 budget이 필요한 프롬프트 목록에 추가.
- 신규 테스트2개, fixture1개, WORKBOARD와 이 기록.

`rag-answer-v4`를 명시하고 기존 형식의 context_evidence budget을 지정한 새 구성에서만 사용한다. 저장된 프로파일을 새로 만들거나 변경하지 않았고 default를 v4로 바꾸지 않았다. v1~v3의 변경 전6개 payload SHA가 일치하며 v4에서 source_reading만 제거하면 같은 schema의 v3 입력 객체와 같다. 원문·ID·순서·출처 필드와 response schema1/2는 그대로다.

## 실제 검증과 한계

- 구현 전 핵심 RED: **10 failed, 16 passed**. 분리 원문 연결 부재·v4 입력/프롬프트 미등록을 확인했다. 구현 후 기본26통과, mock/legacy 경계 추가 후 신규41통과.
- 최종 관련 동기 회귀: **143 passed, 1 deselected in 4.94s**, exit0. 신규2파일과 HTTP metadata·v3 prompt·인용·프로파일·모델 설정·offline rubric 회귀를 포함한다. 제외1개는 기존 비동기 v3 HTTP mock이며 이번에는 실행하지 않았다.
- 독립 검증: **41 passed in 3.40s**, exit0. 추가 경계7개 assert 통과. 시작본 대비 변경 범위·원문 보존·의미 분류 부재 확인. 차단 결함/필수 수정 요청 없음.
- 새 모의 검사는 실제 `generate → _chat_completion`의 prompt/직렬화와 응답 파서를 실행하되 `_request_json` 경계를 authored 응답으로 대체한다. 이벤트 루프와 소켓을 열지 않고 즉시 완료되는 coroutine만 허용한다. 이는 네트워크 전송·서버·모델 실행 검증이 아니다.
- 스키마1/2에서 다른 도메인의 모의 답변·거절이 기존 형식으로 반환되는 것을 확인했다. 모의 응답은 사람이 작성했으므로 모델이 그 답을 생성하거나 지침을 지킨다는 증거가 아니다.
- 기존 오답을 모의 응답으로 넣으면 원래 답변/인용이 그대로 반환되고 `offline_rubric`의 **일반 규칙 누락·예시 조건 누락·예시 근거 불완전** 세 실패가 유지된다. 새 구성은 오답을 정답으로 보정하거나 기존 평가 판정을 바꾸지 않는다.
- Ruff6파일 통과. **strict Mypy 제품 소스4파일 통과**(일반 import 분석). 테스트까지 포함한 최초6파일 명령은 테스트 모듈 이름 중복으로 실패했다. 명시적 package base로 다시 실행한6파일 검사는 진척을 확인하지 못해 중단했으며 통과로 집계하지 않는다. 제품4파일 명령으로 범위를 한정해 완료했다. 프로세스 확인용 CIM 읽기도 권한 거부됐으며 권한 확대나 우회는 하지 않았다.

입력량도 증가한다. 같은 저장 근거28개와 합성 비교 질문을 사용한 provider user payload는 **8,280→9,503자(+1,223자)**, system prompt 원문은 **750→1,262자**다. 이는 문자 수이며 실제 토큰 수·지연 시간 측정이 아니다. 전체 원문을 중복하지는 않지만 추가 ID와 지침이 모델 비용/속도에 영향을 줄 수 있다. 정확도·속도 개선의 인과 효과, P95, 실제 질문 E2E는 미검증이다.

재현 명령(기존 `backend` 환경):

```powershell
.conda/python.exe -X utf8 -B -m pytest tests/unit/labs/rag/generation/test_source_reading.py tests/unit/labs/rag/generation/test_source_reading_mock.py tests/unit/labs/rag/generation/test_http_evidence_groups.py tests/unit/labs/rag/generation/test_direct_answer_prompt.py tests/unit/labs/rag/generation/test_citation_validation.py tests/unit/labs/rag/generation/test_profile_resolution.py tests/unit/labs/rag/models/test_profiles.py tests/unit/labs/rag/evaluation/test_offline_rubric.py -m 'not asyncio' -q
.conda/python.exe -X utf8 -B -m mypy --strict src/ai_workshop/labs/rag/generation/source_reading.py src/ai_workshop/labs/rag/generation/prompts.py src/ai_workshop/labs/rag/generation/openai_compatible.py src/ai_workshop/labs/rag/models/context_evidence.py
.conda/python.exe -X utf8 -B -m ruff check src/ai_workshop/labs/rag/generation/source_reading.py src/ai_workshop/labs/rag/generation/prompts.py src/ai_workshop/labs/rag/generation/openai_compatible.py src/ai_workshop/labs/rag/models/context_evidence.py tests/unit/labs/rag/generation/test_source_reading.py tests/unit/labs/rag/generation/test_source_reading_mock.py
```

## 보존과 다음 단계

기존 실행·오프라인 평가 증거 **157파일 SHA 변경0**, 작업 범위 밖 tracked diff 변경0을 확인했다. old1/1·new2/2 소진 예산과 원시 결과·manifest는 보존했다. 이번 소스 변경으로 과거 manifest에 결속했던 소스3개는 의도적으로 달라지지만 과거 실행 기록이나 승인을 갱신/재사용하지 않는다.

추가 모델 호출0, 외부 API 비용0, 활성 설정 변경0. 설치·재시작·DB/ES/Docker 상태 변경·환경 삭제·권한 확대·OS 보호 설정 변경·커밋·푸시 없음. 이슈 DB 반영은 승인 범위에 없어 수행하지 않았고 기존 답변 품질 결함을 닫지 않았다.

로컬 증거: `.local-data/project-agent-work/rag-answer-guide-20261016/`의 시작 diff/status·수정 직전 원본/해시·RED/GREEN/회귀 XML·`payload-comparison.json`·`preservation-check.json`. 원시 증거는 Git에 추가하지 않는다.

다음 판단은 v4를 실제 모델에 시험할지 여부다. 이 작업만으로 활성화하지 않는다. 추후 승인된 제한 평가에서는 일반 규칙 질문·특정 예시 질문·규칙 없는 질문을 구분하고, offline rubric과 독립 의미 검토로 누락/과잉 일반화·조건 관계·지연 시간을 함께 확인해야 한다. 현재 단계는 선택형 코드와 오프라인/모의 계약 검증 완료이며 실제 답변 품질은 미확인이다.
