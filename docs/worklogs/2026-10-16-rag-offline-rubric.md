# 2026-10-16 일반 규칙·조건 인용의 오프라인 평가 보강

## 범위와 판정

사용자가 저장된 v3 실패 사례의 검증 기준 보강을 승인했다. 일반 규칙 누락과 조건이 빠진 예시가 자동 인용 검사 통과만으로 의미상 정답 처리되지 않게 하는 평가용 보조 검사를 추가했다. **실패 탐지 보강 완료이며 모델 답변 품질 개선은 입증하지 않았다.**

중간 위험의 한정된 평가 변경이다. 메인 Codex가 요구·RAG 경계·테스트 설계·구현을 맡고 별도 검토자가 독립 코드 리뷰와 오프라인 재현을 수행했다. DB·인프라·보안·모델 런타임 변경이 없어 해당 역할은 제외했다. 상태 도구에서 다른 로컬 AI Workshop 작업은 notLoaded였으며 새 파일 중심으로 작업했다. 기존 미커밋 diff/status와 WORKBOARD 시작본은 별도 작업 디렉터리에 보존했고 WORKBOARD 쓰기 직전에 SHA를 대조했다.

## 최소 설계와 검증 기준

기존 `CitationValidator`는 인용 ID·provenance·정확 값의 존재를 확인한다. 질문에 필요한 일반 규칙을 답했는지, 예시의 조건이 유지됐는지를 일반적으로 증명하지 않는다. `judge_propositions` 역시 정규화된 문구 일치 범위를 명시하고 있다. 이 기존 동작·DB 판정 계약을 바꾸지 않고 순수 함수 `evaluation.offline_rubric.assess`를 추가했다. 라이브 생성/API/평가 worker에는 연결하지 않았다.

평가 기준은 검토자가 작성한 공개 합성 fixture에서 주입한다. 제품명·T+4·날짜를 검사 코드에 고정하지 않는다. 다른 상품·T+7로 기준과 근거를 함께 바꾼 테스트도 통과했다.

| 기준 | 검사 방식 | 이번 사례 |
| --- | --- | --- |
| 일반 규칙 | 한 claim에서 필요한 개념 그룹의 대안 표현을 모두 만족하고 필수 근거 묶음 전체를 인용 | 상품·접수일·상대 영업일·지급, 원문 ordinal4·5·7·18·19 |
| 예시 적용 | 해당 예시 근거를 인용하거나 지정된 예시 표현 그룹을 만족할 때만 조건 검사 | ordinal27 인용 또는 지급 날짜 표현 |
| 예시 조건 | 같은 claim에 조건 표현과 조건/결과의 근거 묶음을 요구 | 휴일 없음, ordinal26·27 모두 |
| 입력 동일성 | 기준에 결속된 원문 exact text, 고유 ID, 실제 존재하는 인용, 답변과 claim 결합문 일치 | 다른 claim의 조건/근거를 합쳐 통과시키지 않음 |

출력 `status`는 **이 rubric 검사**의 `failed`·`unreviewed`·`invalid_input`이다. `semantic_correctness`는 항상 `unreviewed`, `semantic_review_required`는 항상 true다. 모든 기준 일치도 자동 의미 정답 통과가 아니다. 원문 누락/변조·중복/없는 ID·답변/claim 불일치는 모델 오답과 구분하는 입력 오류다. 실행 오류도 정답/거절 성공으로 바꾸지 않는다. 이 모듈은 일반 규칙을 요구하는 positive rubric용이며 근거 없는 질문의 일반 평가를 대체하지 않는다.

문자열 검사의 한계는 의도적으로 남겼다. 알려지지 않은 바꿔쓰기, 부정문, 의미 반전, 키워드 나열, 문장 사이의 조건 연결을 일반적으로 판정하지 못한다. 동일 claim 요구는 의미상 맞는 여러 문장의 답도 rubric 미충족으로 표시할 수 있다. 예시 trigger는 지정한 ID·표현에 한정되므로 모든 날짜 예시의 조건 누락 탐지로 일반화하지 않는다. `failed`는 기준 미충족이며 의미상 거짓 확정이 아니다. 검토자는 rubric의 근거 연결 자체와 이 미탐/과탐을 검토해야 한다. 이 결과는 DB 승격 증거나 기존 의미 검토를 대체하지 않는다.

## 구현 파일

- `backend/src/ai_workshop/labs/rag/evaluation/offline_rubric.py`: typed 입력·기준·결과, 순수 오프라인 검사와 입력/기준 digest.
- `backend/tests/fixtures/rag/offline_payment_rubric.json`: 이번 공개 합성 저장 입력28개·답변·claim, 원본 입력/결과 SHA와 검토된 rule/example/condition 기준. 계정·runtime 메타데이터는 복사하지 않았다.
- `backend/tests/unit/labs/rag/evaluation/test_offline_rubric.py`: 저장 실패 재현, 현행 인용 검사와의 비교, 일반 규칙의 표현 변형·잘못된 값/상품/기산점/단위, 예시 조건·근거 연결, 입력 오류·한계 회귀.
- `WORKBOARD.md`, 이 작업 기록: 실제 결과와 잔여 범위.

## 실제 재평가 결과

기존 원본 `rag-v3-two-calls-20261016/case-1-input.json`과 `case-1-result.json`을 읽어 fixture와 동일한 근거28개·답변·claim임을 확인한 뒤 직접 재평가했다. 모델 재호출은 없었다.

- `required_rule_missing`: 날짜 예시만 답하고 T+4 영업일 일반 규칙 누락.
- `example_condition_missing`: 두 번째 claim에서 휴일 없음 조건 누락.
- `example_support_incomplete`: 두 번째 claim이 ordinal27만 인용하여 조건·상품·접수일 연결을 담은 ordinal26이 빠짐.

최종 `status: failed`, `semantic_correctness: unreviewed`. 기존 독립 의미 검토의 일반 규칙 답변 실패 판정은 별도 기록으로 유지한다. 실제 `CitationValidator`가 동일 답변에 `answered`를 반환하는 비교 테스트를 실행해 자동 인용 검사 통과와 이번 보조 검사 결과를 구분했다. [원래 2회 실행 결과](2026-10-16-rag-v3-two-calls.md)는 수정하지 않았다.

## 실행한 검증

- 핵심 동작 구현 전 stub에서 **15 failed, 7 passed**를 확인했다. 저장 실패·조건·근거 결속·입력 오류·digest 검사 RED를 보존했다. 구현 후22통과, 실제 인용 검사 비교 추가 후 신규23검사를 검증했다.
- 최종 동기 회귀: **85 passed, 11 deselected in 5.68s**, exit0. 신규 테스트와 기존 citation/metrics/failure-metrics/claim-trace를 함께 실행했다.
- 독립 검증: 신규 **23 passed in 0.85s**, exit0. 저장 원본 SHA·fixture28근거·답변·claim 일치 확인, 중복 인용 ID·빈 answered·규칙 근거1개 누락의 추가3경계 assert 통과. 차단 결함/필수 수정 요청 없음.
- 최종 Mypy strict **2개 파일 통과**(의존성 import 생략 옵션 없이 실행), Ruff2파일 통과. 초기 `--follow-imports=skip`은 Pydantic/pytest를 Any로 처리해5오류를 냈다. 일반 import 검사에서 발견한 이종 tuple 추론6오류는 `Rule | Example` 명시 타입으로 수정한 뒤 통과했다.
- 확장 회귀의 첫 실행은 비동기 구간에서 진행이 정지해 중단했다. 그 실행은 통과로 집계하지 않는다. 이후 `-m 'not asyncio'`로 동기 회귀만 완료했고 제외11개는 검증하지 않았다. 전체 제품 테스트/전체 제품 타입 검사·검색 E2E·실모델 검증은 수행하지 않았다.
- 독립 추가 경계의 최초 standalone 실행은 src import 경로 미설정으로 실패했다. 프로세스 내부 import 경로를 지정한 재실행에서 성공했다. 설치나 시스템 환경 변경은 없었다.

재현 명령(저장소의 `backend` 디렉터리, 기존 환경 사용):

```powershell
.conda/python.exe -X utf8 -B -m pytest tests/unit/labs/rag/evaluation/test_offline_rubric.py tests/unit/labs/rag/generation/test_citation_validation.py tests/unit/labs/rag/evaluation/test_metrics.py tests/unit/labs/rag/evaluation/test_generative_failure_metrics.py tests/unit/labs/rag/evaluation/test_claim_citation_trace.py -m 'not asyncio' -q
.conda/python.exe -X utf8 -B -m mypy --strict src/ai_workshop/labs/rag/evaluation/offline_rubric.py tests/unit/labs/rag/evaluation/test_offline_rubric.py
.conda/python.exe -X utf8 -B -m ruff check src/ai_workshop/labs/rag/evaluation/offline_rubric.py tests/unit/labs/rag/evaluation/test_offline_rubric.py
```

## 보존과 남은 작업

기존 두 실행 디렉터리의 **144파일 SHA 변경0**을 확인했다. 기존 소진 예산1/1·새 소진 예산2/2·예약·manifest·원시 결과를 그대로 보존했다. 추가 모델 호출0, 활성 모델/프롬프트 설정·설치·OS 설정·권한·환경 삭제·DB/ES/Docker 상태 변경·커밋·푸시 없음. 로컬 증거는 `.local-data/project-agent-work/rag-offline-rubric-20261016/`의 초기 diff/status, RED/GREEN·최종 회귀 XML, `saved-answer-replay.json`, `preservation-check.json`이다.

문제 이력 DB 갱신은 이번 승인 범위에 없어 미반영이며 이슈를 닫지 않았다. 일반 규칙 답변 실패 자체는 남아 있다. 다음 후보는 이 평가 기준을 활용한 답변 구성의 오프라인 개선 설계다. 실제 생성 품질·속도의 재검증은 추가 모델 호출 승인 후 별도 작업이며, 이번 보강으로 완료 처리하지 않는다.
