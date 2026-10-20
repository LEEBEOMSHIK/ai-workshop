# 생성형 평가 실행 전 읽기 전용 점검

- 날짜: 2026-10-19
- 범위: 사용자 13:10 KST경 제출 보고의 실행 ID, 저장 조건, 중복, 기존 호출 수와 worker 상태 확인 및 단일 실행 경로 검토.
- 역할: 메인 RAG·Python backend·AI runtime 진단. UI·DB schema·배포 변경 역할은 실제 범위에 없어 제외한다. 제품 수정은 하지 않는다.
- 보존: 작업 전 Git 상태와 WORKBOARD 원문을 `.local-data/project-agent-work/rag-evaluation-inspection-20261019/`에 보존했다. 기존 미커밋·미추적 변경은 유지한다.
- 실행 경계: 총 최대4회 로컬 생성은 이미 발생한 호출을 포함한다. 이번 읽기 전용 점검 뒤 대상 ID·정확한 조건·기존 호출·남은 횟수를 보고하고 실제 생성 허용을 확인한다. 일반 큐 worker 시작, DB 직접 수정, 설치·모델 다운로드·재색인, 인증 우회·자격 추출, commit/push는 제외한다.

## 진행 상태

- 브라우저 목록 조회는 `Automatic approval review failed: Selected model is at capacity`로 실행 전에 차단됐다. 안전성 거절이나 프로젝트 오류로 해석하지 않는다.
- sandbox의 TCP listener 조회는 접근 거부였고, 공식 권한 요청도 동일한 승인 검토 서비스 용량 오류로 실행되지 않았다. 현재 worker 유무는 미확인이다.
- 코드의 `generative_dispatch.execute_run(settings, id)`는 하나의 실행 ID를 `GenerativeWorkflow.run`에 전달한다. `dispatch_pending`은 여러 대기 실행을 선택하므로 이번 대상만의 실행 경로로 사용하지 않는다. 실제 실행은 아직 하지 않았다.
- 최종 입력 확인은 ADR-0038의 요청 수명 범위이며 평가 이력만으로 실제 전송 메시지가 보존됐다고 판단하지 않는다.

## 실제 조회 결과

프로젝트 `backend/.conda/python.exe`를 표준 Conda 활성화와 기존 해시 검사 뒤 사용했다. 기존 앱 설정을 메모리에서 읽어 연결했으며 자격값·쿠키·환경변수를 출력하거나 추출하지 않았다. DB 조회는 `default_transaction_read_only=on`, `REPEATABLE READ READ ONLY`, statement timeout 10초와 종료 시 rollback으로 수행했다. 새 DB·계정·schema는 만들지 않았다.

14:03:37 KST DB 관찰:

- 새 실행: `1c75a9ed-8af6-4ef6-8b34-bdb70e9969f5`, 생성 시각 2026-10-19 13:09:53.232841 KST, 상태 pending.
- 해당 owner의 최근 실행은 10건이며 최신 30건 한도 안에 모두 포함됐다. 별도 전체 pending/running 조회에서도 대상 1건뿐이다. 같은 조건의 대기 중복은 발견하지 않았다.
- 시도 4개 모두 pending, claim 없음, 결과·오류·종료 시각 없음, attempt_number 1. 실행 자체의 claimed_at/dispatched_at/finished_at도 없다.
- 대상 실행의 `rag_executions` 0건, `rag_generation_execution_audits` 0건. 14:05~14:06 후속 조회에서 제출 이후 같은 owner/profile의 생성 감사도 0건이다.
- 정상 실행 경로는 run claim → attempt claim → execution observer → pipeline 순서이므로 해당 평가의 정상 경로가 시작됐다는 증거는 없다. 이 결과를 화면의 pending 숫자만으로 판단한 호출 0회와 구분한다. Ollama 전체 호출 이력이나 기록 외 직접 호출까지 0회라고 주장하지 않는다.
- 이전 실행 `b91990da-ef3e-4ce3-b8f7-e94db6ff5f21`은 cancelled, 취소 시각 2026-10-18 21:15:06.684565 KST, 사유 user_requested다. 이전 WORKBOARD와 10/18 기록의 pending은 그 당시 관찰이며 현재 상태로 사용하지 않는다.

## 조건 대조

| 항목 | 확인된 저장 값 |
|---|---|
| 평가 자료 | `bf846b4f-9d13-5f1b-88e6-576786f76b3b`, PDF 생성형 경로 점검 Q01-Q15 20260928 v1, 실제 2사례 |
| 정상 질문 | AM-SYN-101을 현금화하면 돈은 며칠 뒤 받을 수 있어? |
| 정상 규칙 | answered, required_propositions `["4","영업일"]`, 금지 내용 없음 |
| 근거 부족 질문 | AM-SYN-202의 다음 달 확정 수익률은 얼마야? |
| 근거 부족 규칙 | insufficient_evidence, 필수/금지 내용 모두 없음 |
| 이력 | case_histories가 빈 객체이므로 두 사례 모두 빈 이력 |
| 구성 | `f174e01e-a1f2-4007-9d6c-5aa02a600095`, Gemma E2B 범용 v4 비교 2026-10-17, v1 |
| 구성 버전 | `29e972cf-66ff-4a17-8b32-b3815fd54d98`, 비교 후보 1개 |
| 생성 프로필 | `79f608ee-68a9-4c4c-9234-a3aecf3e1a1c`, 동결 config와 현재 config 일치, prompt `rag-answer-v4` |
| 지식 공간 | `2292dfa0-3af8-4494-a8ce-da03ef2aa6ed`, RAG 합성 참조 자료 |
| 횟수 | K=10, 사례별 반복=2, 총 4시도 |
| 모델 | 로컬 `gemma4:e2b-it-q4_K_M`, 외부 전송 false |
| 배포 | `97327b16-30e3-41b4-88a3-9f64a55056db` v2, max_retries=0 |
| 생성 설정 | 출력 512, temperature=0, timeout 360초, schema=2, answer_reasoning_effort=none |
| 평가 기준 | PDF 생성형 검증 기준 20260928 v1, correctness/context coverage/abstention 각각 1, ACL 누출 0, 유효 인용 필수, P95≤120000ms |

정상 사례의 기존 required_evidence_groups는 1개이며 변경하지 않았다. 모델 timeout 360초와 평가 P95 기준 120초는 서로 다른 설정으로 그대로 유지한다.

## 환경 확인과 남은 차단

14:06:17 KST 읽기 전용 비추론 GET 결과:

- frontend 5173 `/` HTTP 200.
- Ollama 11434 `/api/version` HTTP 200, version 0.40.3. `/api/ps` HTTP 200, 현재 loaded models 빈 목록. 과거 호출 0회의 증거로 사용하지 않는다.
- backend 18000 `/api/v1/health`는 `ConnectionRefusedError`, errno/winerror 10061. 두 관찰에서 실패했으며 프로젝트 코드 오류나 특정 프로세스의 종료 원인은 확정하지 않는다.
- OS listener/process 조회는 sandbox 접근 거부 뒤 공식 권한 요청이 자동 승인 검토 서비스의 모델 용량 오류로 실행되지 않았다. 브라우저 조회도 같은 서비스 오류로 실행되지 않았다. 거절을 우회하지 않았다.
- 기존 `.local-data/dev-logs`의 worker/beat 파일 목록 중 가장 최근 수정은 10/2였다. 이 위치의 옛 로그를 현재 worker 상태 증거로 쓰지 않는다.

## 단일 실행 경로와 다음 단계

기존 Celery task `ai_workshop.rag.evaluate_generative_run(run_id)`는 `generative_dispatch.execute_run(settings, UUID(run_id))`를 호출한다. 이 함수는 정확한 ID 하나의 `GenerativeWorkflow.run`을 실행하고 engine을 정리한다. claim은 해당 run 행을 잠그고 pending만 허용하며 attempt도 같은 run/token을 검사한다. `dispatch_pending`이나 일반 worker/beat를 켜지 않는 대상 지정 실행 후보다. 이번에 실행하지 않았으며 실제 runtime 성공을 보장하는 검증은 아니다.

1. 승인 검토 서비스 복구 또는 사용자 안내에 따라 원래 API/worker 상태를 확인하고 필요한 API 기동 범위를 확정한다. 일반 큐 worker는 시작하지 않는다.
2. 실행 직전 run·rules/snapshot digest·4시도·감사·profile/deployment를 재조회한다. 불일치·새 호출·추가 실행이 있으면 중단해 보고한다.
3. 대상 실행에만 정상/근거 부족 2사례 × 2회, 기존 호출 포함 최대 4회 로컬 생성과 필요한 임베딩, 재시도 0의 명시 허용을 받는다. 이번 작업에서 생성/임베딩 호출은 0회다.
4. 실제 실행 후 종결 상태·답변·검색/선택 근거·인용·정답/거절/coverage·ACL·P95를 확인한다. 완료와 품질 통과를 구분한다.
5. 평가 adapter의 SearchRequest는 include_diagnostics 기본 false를 사용하고 평가 PrivateGenerativeResult에 최종 messages를 저장하지 않는다. 따라서 이 4회의 평가 이력만으로 실제 최종 LLM 입력까지 확보한다고 약속하지 않는다. 통과 후 사용자가 정한 별도 추가 1회 입력 확인에서 현재 요청 캡처를 확보하고 설명·이미지를 만든다. 품질 미통과 시 READY/활성화하지 않는다.

DB 상태 수정·모델 실행·서버 기동/종료·설치·다운로드·재색인·commit/push는 수행하지 않았다. 제품 코드 변경은 없으며 WORKBOARD와 이 기록, Git 제외 점검 스크립트/보고서만 추가·갱신했다. 문제 이력 DB는 인증된 관리 경로 미확보 및 DB 쓰기 제외 범위로 반영하지 않았다.

증거: `.local-data/project-agent-work/rag-evaluation-inspection-20261019/database-readonly-report.json`, `runtime-readonly-report.json`, 두 읽기 전용 Python 스크립트와 고정 환경 진입용 `run-readonly.ps1`.

## 검증

`verify_reports.py`의 저장 증거 대조·문법·문서 보존 검사 21개와 `git diff --check`가 exit 0으로 통과했다. WORKBOARD는 이번 최신 관찰 문단을 제외하면 시작 시 원문과 일치한다. 이는 제품 테스트나 RAG 품질 검증이 아니다. 첫 stdin 검사에서는 PowerShell 파이프의 한글 인코딩 문제로 문단 탐색이 실패했으며, UTF-8 파일로 실행해 확인했다. 기존 제품 회귀를 새로 통과했다고 보고하지 않는다.
