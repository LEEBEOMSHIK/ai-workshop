# RAG 인용 검증 실패 세부 진단 — 2026-09-30

ISSUE-00005의 최우선 후속 목록에서 **인용 실패 세부 사유 보존**을 하나의 작업 단위로 구현했다. 기존 사용자 변경을 보존했고 커밋·푸시·배포는 하지 않았다.

## 범위와 성공 기준

기존 `CitationValidator`가 생성하는 안전한 사유 코드를 `citation_validation` 단계에 남긴다. 외부 HTTP 응답과 공급자 감사 오류는 기존 `citation_validation_failed`를 유지한다. 단계 기록을 먼저 종료해도 평가 결과의 `failure_stage`가 `request`로 바뀌지 않아야 한다. 관측 저장 실패는 본래 처리 오류를 대체하거나 생성 본문을 로그에 노출하지 않는다.

승인된 [ADR-0029](../decisions/0029-rag-execution-monitoring.md) 및 [모니터링·평가 설계](../superpowers/specs/2026-09-27-rag-execution-monitoring-and-evaluation-design.md)의 기존 단계·안전한 사유 코드 계약 안에서 수정했다. 공개 응답 스키마·DB migration·프로파일·모델·권한 정책은 변경하지 않았다.

## 원인과 구현

- `search/pipeline.py`: 인용 검증기가 만든 `exact_value_not_supported`, `evidence_not_allowed` 등 세부 사유가 일반 예외로 대체돼 외부 종결 처리에 넘어갔다. 실패 단계에 검증기 사유를 먼저 기록한 뒤 기존 감사와 HTTP 예외를 그대로 전달하도록 수정했다.
- `executions/observer.py`: 종료한 실패 단계를 `failed_stage`로 보존한다. 저장 시도 전에 설정하므로 관측 저장 실패에도 단계 식별을 유지한다. 이후 일반 오류 처리·미실행 단계 채우기·저장 단계가 이미 종료된 인용 사유를 덮어쓰지 않는다.
- `evaluation/generative_workflow.py`: 활성 단계가 없으면 보존된 실패 단계를 사용한다. 실제 workflow 오류 분기 및 결과 직렬화 경계에서 이를 검증했다.
- 새 `tests/unit/labs/rag/executions/test_citation_failure_diagnostics.py`: 실제 인용 검증기 두 실패 유형 × 진단 on/off, 종결 후 일반 오류 처리, 관측 저장 실패, 평가 실패 단계 직렬화 두 경로의 총 8개 사례를 추가했다. 합성 검색·생성·저장 경계만 사용하며 실제 DB·LLM·네트워크를 호출하지 않았다.

## 검증

검증은 순차 실행했다. 시작 당시 가용 RAM 약 2.3GB이며 다른 프로그램을 종료하거나 빌드·검사를 병렬 실행하지 않았다. 독립 검증 역할의 pytest도 메인 검사 종료 후 단일 프로세스로 실행했다. 테스트 터미널에만 합성 `AI_WORKSHOP_SECRET_KEY` 및 offline 플래그를 지정했다.

| 검사 | 결과 |
| --- | --- |
| 수정 전 새 회귀 8개 | 7 실패·1 통과. 세부 사유가 일반 코드로 바뀌는 4건, 실패 단계 추적 부재 2건, 평가 단계 `request` 오분류 1건을 재현 |
| 수정 후 새 회귀 | 8 통과, 2.24초 |
| 독립 관련 단위 재검증 | 8개 파일·49 통과, 5.72초, 종료 0·경고 없음 |
| Ruff | 소스 3개·신규 테스트 통과. 최초 신규 테스트 줄길이 1건은 해당 신규 파일만 포맷해 해소 |
| Mypy | 변경 소스 3개에서 오류 없음 |
| 백엔드 전체 단위 검사 첫 시도 | 2,324 통과·645 setup 오류·경고 1개, 63.33초. 공용 `pytest-of-<user>` 임시 경로 접근 거부(WinError 5) 확인 |
| 전체 단위 검사 재실행 | 2963 passed, 6 skipped, 1 warning in 80.39s (0:01:20) |
| 독립 소스 리뷰 | 차단·중요 결함 없음. 구현 담당과 분리된 읽기 전용 검토 |

전체 재실행의 6개 skipped는 통과 건수에 포함하지 않았다. 경고 1개는 기존 FastAPI/Starlette TestClient의 httpx 사용 중단 예정 경고이며 이 작업에서 의존성을 변경하지 않았다.

첫 전체 검사 환경 오류는 기존 임시 폴더·권한을 바꾸지 않고 이번 작업공간의 **존재하지 않는 새 basetemp**를 지정해 재검증했다. 테스트 산출물과 로그를 보존했다. 전체 검사 로그: `<verification-workspace>/citation-unit-suite.log`.

실행 명령(작업 디렉터리 `backend`, 기존 `.venv` 사용):

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/executions/test_citation_failure_diagnostics.py -q --tb=short
.venv/Scripts/python.exe -m ruff format tests/unit/labs/rag/executions/test_citation_failure_diagnostics.py
.venv/Scripts/python.exe -m ruff check src/ai_workshop/labs/rag/executions/observer.py src/ai_workshop/labs/rag/search/pipeline.py src/ai_workshop/labs/rag/evaluation/generative_workflow.py tests/unit/labs/rag/executions/test_citation_failure_diagnostics.py
.venv/Scripts/python.exe -m mypy src/ai_workshop/labs/rag/executions/observer.py src/ai_workshop/labs/rag/search/pipeline.py src/ai_workshop/labs/rag/evaluation/generative_workflow.py
.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short
.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short --basetemp <verification-workspace>/citation-unit-temp-20260930
```

독립 재검증 파일: `executions/test_citation_failure_diagnostics.py`, `executions/test_observer.py`, `executions/test_conversation_trace.py`, `search/test_context_generation.py`, `search/test_provider_insufficient_evidence.py`, `search/test_generation_policy_gate.py`, `generation/test_citation_validation.py`, `evaluation/test_generative_workflow.py` (모두 `tests/unit/labs/rag/` 아래).

공개 전 개인정보 최소화를 위해 로컬 계정명이 포함된 경로를 `<verification-workspace>`와 `<user>`로 일반화했다. 실제 실행 경로·원본 로그는 로컬에 보존하며 검증 결과는 변경하지 않았다.

## 남은 검증과 다음 작업

- 본래 API·worker에 코드 반영을 위한 재시작, 실제 DB의 단계 사유 저장 및 관리자/대화 화면 표시는 이번에 검증하지 않았다. 실제 외부 LLM 호출·추가 결제·인증 변경은 없었다.
- 본래 환경의 신규 인용 실패에서 안전한 단계 사유를 확인하고, 정상 관리자 경로로 이 문서를 버전 등록해 ISSUE-00005에 연결해야 한다. 운영 문제 이력 DB 등록·연결은 미완료이며 저장소 문서 작성만으로 DB 반영됐다고 보지 않는다.
- 기존 실패 기록은 backfill하지 않았다. 기존 실행 기록의 검색·생성 시간과 선택 정보 보존은 회귀 검증했지만, 실패한 `PrivateGenerativeResult` 자체의 검색·선택 측정값 복구는 별도 후속이다.
- 근거 부족·거절 상태 계약, 필수 비교 결론 누락, 지연 개선, 새 문서 일반화와 실제 대화·원문 인용 검증은 남아 있다. 기존 활성 구성을 승격하거나 ISSUE-00005를 종결하지 않았다.
