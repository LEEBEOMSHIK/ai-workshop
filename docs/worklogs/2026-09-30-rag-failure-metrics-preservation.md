# RAG 실패 이전 측정값 보존 — 2026-09-30

ISSUE-00005의 후속 목록에서 **근거 선택 완료 후 생성·인용 실패 시 검색/문맥 측정값 보존**을 하나의 작업 단위로 구현·오프라인 검증했다. 직전 [인용 실패 세부 진단](2026-09-30-rag-citation-failure-diagnostics.md)과 기존 사용자 변경을 보존했다. 커밋·푸시·배포 및 실제 서버 재시작은 하지 않았다.

## 선택한 범위와 계약

직전 진단 보존 수정과 의존성이 연결되고 실제 외부 LLM 없이 재현 가능한 측정값 손실을 먼저 처리했다. 근거 부족·거절 상태와 필수 비교 결론 누락은 별도 후속으로 유지한다.

정상 응답과 동일한 전체 검색 근거 ID 및 실제 생성 문맥에 선택한 ID를 요청별 관측기에 보존한다. 수집 지점은 최종 근거 접근 권한 재검증 성공 직후이며 진단 저장 이전이다. 후보 진단의 200개 상한이나 후보의 선택 표시는 평가의 전체 집합을 대체하지 않는다. 본문·프롬프트·원문 예외는 추가 저장하지 않는다.

기존 `GenerativeObservation`의 `retrieved_evidence_ids`, `selected_evidence_ids`, `access_exposures` 필드를 사용한다. 공개 스키마·DB migration·result digest 구조·모델/프로파일·권한 정책은 변경하지 않았다. [ADR-0029](../decisions/0029-rag-execution-monitoring.md) 및 [ADR-0030](../decisions/0030-rag-generative-evaluation.md)의 관측·평가 경계를 따른다.

## 원인과 변경 파일

- `backend/src/ai_workshop/labs/rag/executions/observer.py`: 요청별 정확한 검색/선택 ID를 보존한다. 컨텍스트는 요청 종료 후 복원되며 별도 관측기와 섞이지 않는다. 관측 저장 오류와 독립적이다.
- `backend/src/ai_workshop/labs/rag/search/pipeline.py`: 전체 source의 evidence unit ID와 실제 generation answer의 evidence ID를 권한 재검증 후 확보한다. 거절된 권한의 ID는 이 체크포인트에 남기지 않는다.
- `backend/src/ai_workshop/labs/rag/evaluation/generative_workflow.py`: 예외 결과에도 보존한 ID를 직렬화한다. 정상 성공 경로와 같은 승인 ID 차집합으로 `access_exposures`를 계산해 실패 결과가 접근 노출을 조용히 0으로 처리하지 않는다. 실패 답변/인용 본문은 추가 보존하지 않는다.
- `backend/src/ai_workshop/labs/rag/evaluation/generative.py`: 실패(`failure_stage` 또는 `error_code`) 시 각 지표에 대응하는 ID가 없으면 `null`로 계산한다. 비어 있지 않은 ID의 실제 계산값 0%는 유지하며 정상 완료된 빈 검색은 기존의 0%를 유지한다.
- `frontend/src/features/rag/configurations/GenerativeEvaluationPanel.tsx`: 실패·중단 시 해당 근거 ID와 지표가 있는 검색/문맥 값만 개별 표시한다. 일부만 보존된 경우 나머지는 ‘확인 불가’로 유지하며 답변 정답·생성 성공으로 표시하지 않는다.
- 새 `backend/tests/unit/labs/rag/evaluation/test_generative_failure_metrics.py`: 14개 합성 회귀. 실패 신호 2종 × ID 조합 4종, 정상 빈 검색, 251개 정확한 ID와 요청 분리, workflow 직렬화/접근 노출 2종, 실제 pipeline 권한 재검증 실패 및 관측 저장 실패 경계.
- `backend/tests/unit/labs/rag/executions/test_citation_failure_diagnostics.py`: 직전 실제 인용 실패 4개 경로에 정확한 ID 보존 assertions를 추가했다.
- `frontend/src/features/rag/configurations/GenerativeEvaluation.test.tsx`: 기존 사용자 테스트를 보존하고 실패·중단 2종 및 검색만 보존된 경우 총 3개 회귀를 추가했다.
- `WORKBOARD.md` 및 이 날짜별 기록: 실제 구현·검증·남은 범위를 갱신한다.

## 실제 실행한 검증

가용 RAM 약 2.4GB에서 무거운 검사와 독립 테스트를 순서대로 실행했다. 기존 `.venv` 및 `node_modules`를 사용하며 설치·외부 LLM·실제 DB·새 인증·환경 설정 변경은 없었다. 테스트 프로세스에만 합성 secret을 지정했다.

| 검사 | 결과 |
| --- | --- |
| 수정 전 백엔드 직접 회귀 | 11 실패·9 통과. 실패 빈 ID를 0%로 취급, 관측기 ID 추적 부재, workflow 실패 결과 ID 손실 재현 |
| 수정 전 화면 직접 회귀 | 3 실패·17 통과. 실패 결과의 실제 검색/문맥 지표까지 일괄 숨기는 동작 재현 |
| 수정 후 백엔드 직접 회귀 | 22 통과, 2.78초 (신규 14 + 직전 인용 회귀 8) |
| 수정 후 화면 직접 회귀 | 20 통과, 9.05초 (기존 17 + 신규 3) |
| Ruff | 소스 4개·테스트 2개 통과. 신규 파일 import/줄길이와 이번 pipeline 추가 줄만 정리 |
| Mypy | 변경 Python 소스 4개 오류 없음 |
| TypeScript / ESLint | `tsc --noEmit --pretty false` 및 변경 화면·테스트 2개 `--max-warnings 0` 통과 |
| 백엔드 전체 첫 시도 | 8 실패·2969 통과·6 skipped·경고 1개, 82.20초. 기존 asset_service 업로드 임시 파일 경로 264자에서 FileNotFoundError |
| 경로 원인 분리 | 제품 코드 수정 없이 짧은 새 basetemp `fmu1`에서 해당 파일 9 통과, 0.95초 |
| 백엔드 전체 단위 | 2977 passed, 6 skipped, 1 warning in 79.74s (0:01:19) |
| 프론트 관련 전체 회귀 | Test Files  13 passed (13); Tests  112 passed (112). configurations·executions, 단일 worker |
| 독립 소스 리뷰 | 차단·중요 결함 없음. 권한 재검증/관측 저장 실패 테스트 권고를 추가 후 재검토 |
| 독립 실행 재검증 | Independent review: no blocking or important findings; backend related unit tests: 16 files, 140 passed in 5.10s, exit 0, no warnings; offline synthetic inputs only, no DB/LLM/browser calls or source edits. |

전체 백엔드 skipped 6건은 통과에 포함하지 않았다. 경고 1개는 기존 FastAPI/Starlette TestClient의 httpx 사용 중단 예정 경고이다. 첫 전체 실행은 기존 업로드 테스트의 임시 파일 경로가 264자로 길어져 실패했다. 해당 파일을 짧은 경로에서 먼저 재검증하고 전체를 새 짧은 `fmu2`에서 다시 실행했다. 기존 임시 파일/ACL·Windows 장경로 설정·제품 코드는 바꾸지 않았다. 실패 로그도 `failure-metrics-unit-suite-longpath.log`로 보존했다.

실행 명령(각 backend/frontend 디렉터리, 무거운 작업 순차 실행):

```powershell
# backend
.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/evaluation/test_generative_failure_metrics.py tests/unit/labs/rag/executions/test_citation_failure_diagnostics.py -q --tb=short
.venv/Scripts/python.exe -m ruff check src/ai_workshop/labs/rag/executions/observer.py src/ai_workshop/labs/rag/search/pipeline.py src/ai_workshop/labs/rag/evaluation/generative_workflow.py src/ai_workshop/labs/rag/evaluation/generative.py tests/unit/labs/rag/evaluation/test_generative_failure_metrics.py tests/unit/labs/rag/executions/test_citation_failure_diagnostics.py
.venv/Scripts/python.exe -m mypy src/ai_workshop/labs/rag/executions/observer.py src/ai_workshop/labs/rag/search/pipeline.py src/ai_workshop/labs/rag/evaluation/generative_workflow.py src/ai_workshop/labs/rag/evaluation/generative.py
.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short --basetemp <verification-workspace>/failure-metrics-unit-temp-20260930
.venv/Scripts/python.exe -m pytest tests/unit/platform/assets/test_asset_service.py -q --tb=short --basetemp <verification-workspace>/fmu1
.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short --basetemp <verification-workspace>/fmu2
# frontend
node node_modules/vitest/vitest.mjs run src/features/rag/configurations/GenerativeEvaluation.test.tsx --pool=threads --maxWorkers=1 --reporter=dot
node node_modules/typescript/bin/tsc --noEmit --pretty false
node node_modules/eslint/bin/eslint.js src/features/rag/configurations/GenerativeEvaluationPanel.tsx src/features/rag/configurations/GenerativeEvaluation.test.tsx --max-warnings 0
node node_modules/vitest/vitest.mjs run src/features/rag/configurations src/features/rag/executions --pool=threads --maxWorkers=1 --reporter=dot
```

로그(저장소 밖 작업공간): `<verification-workspace>/failure-metrics-unit-suite.log`, `failure-metrics-frontend-suite.log`. 실제 실행 LLM 모델명은 런타임 메타데이터로 확인할 수 없어 기록하지 않는다. 기본 설정이나 RAG 모델을 실행 모델로 추정하지 않았다.

공개 전 개인정보 최소화를 위해 로컬 계정명이 포함된 경로를 `<verification-workspace>`와 `<user>`로 일반화했다. 실제 실행 경로·원본 로그는 로컬에 보존하며 검증 결과는 변경하지 않았다.

## 남은 항목·미검증 부분

- 실제 API·worker 재시작, 실제 DB 저장/조회 및 실제 브라우저의 관리자·대화·원문 인용 검증은 미실행이다. 인증된 정상 관리 경로의 이 문서 버전 등록·ISSUE-00005 DB 연결도 미완료이다.
- 기존 실패 기록은 backfill하지 않았다. 이번 보존은 근거 선택/권한 재검증이 끝난 뒤의 실패에 적용한다. 체크포인트 이전 검색·선택 실패의 측정값 복원은 범위 밖이며 실패 ID가 비어 있으면 실제 빈 검색/미기록을 구분할 수 없어 보수적으로 미확인 처리한다.
- 근거 부족·거절 상태 계약, 필수 비교 결론 누락, 새 문서 일반화, 생성 지연 및 최신/누적 이력 혼동은 남았다. 활성 구성 승격·문제 종결은 하지 않았다.
- 합성 pipeline/직렬화/UI 회귀 성공은 실제 DB/브라우저 및 외부 모델의 품질 검증을 대체하지 않는다.
