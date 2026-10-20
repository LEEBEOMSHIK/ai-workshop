# 2026-10-15 RAG 일반 규칙 답변·HTTP 입력 개선

## 범위와 상태

사용자 승인 후 새 `backend/.conda` 서버 health, 구 환경의 복구 가능한 정리, 저장된 단일 RAG 결과의 일반 규칙 누락과 지연을 확인했다. 중간 위험의 RAG 변경으로 요구·Python·AI·테스트 구현과 독립 RAG 원인 분석·코드 리뷰를 분리했다. UI·DB schema·배포·보안 역할은 이번 수정 대상이 아니다.

로컬 코드·오프라인 검증은 완료했으나 실제 품질·속도 수용은 미완료다. 실제 추론 예산은 **1/1 소진** 상태를 유지했고 추가 생성·임베딩·토크나이저 호출은 없다. 기존 작업 상태와 대상 파일을 `.local-data/project-agent-work/rag-direct-answer-20261015/before/` 및 상태·diff·SHA에 보존하고 쓰기 전 재확인했다.

## 확인한 원인과 구현

- 저장된 요청 `a0b79969-ef52-480c-9de4-e3a6c4e5ea28`의 생성 입력에는 일반 지급 규칙이 포함돼 있었다. 모델이 특정 날짜 예시만 반환했으며, 이번 누락은 검색에서 해당 근거가 빠지거나 후처리에서 일반 규칙이 삭제된 현상은 아니다.
- 입력은 근거 28개, 원문 659자이며 provider 사용량은 입력 9,992·출력 169 tokens, finish_reason은 stop이었다. 전체 284.7148초 중 생성 어댑터 구간은 266.7796초(약 93.7%)다. load/prefill/decode/GPU 단계별 관측이 없어 세부 지연 원인은 확정하지 않았다. 기존 none reasoning·512 output·재시도 0을 반복 설정하지 않았다.
- `rag-answer-v3`를 별도 등록했다. 일반 규칙·조건 우선, 예시와 구분, 근거 없는 날짜 추정 금지, 대상·항목·값 관계를 함께 인용하도록 명시한다. 특정 제품·정답을 하드코딩하지 않았다. 기존 v2 내용과 활성 프로파일은 유지하며 v3는 미활성이다.
- 로컬 HTTP 문맥형 입력의 동일 그룹 메타데이터를 한 번만 전송하도록 분리했다. 기존 v2에도 이 직렬화가 적용된다. 모든 원문·근거 UUID·element UUID·순서·좌표·표 셀·null/빈 값은 복원 가능하며, 서로 다른 그룹이나 대상의 사실을 병합하지 않는다. 비문맥 입력과 다른 provider의 공통 evidence 표현은 변경하지 않았다.
- 저장 입력을 오프라인 변환해 28개 근거의 정확한 복원을 확인했다. 14,331 → 8,326자(41.9% 감소), UTF-8 15,138 → 9,133bytes(39.7% 감소). 이는 입력 바이트 측정이며 실제 token 수·응답 시간 개선 실측이 아니다. `payload-metrics.json`에 결과를 보존했다.

## 실제 실행 검증

- RED: 신규 동기 테스트 5실패·1통과·1제외. 실패는 그룹 필드와 v3 등록·예산 계약 미구현 때문임을 확인한 후 구현했다.
- 최종 pytest: **116통과·1제외**, 2.10초. 그룹 무손실 복원·혼합 순서·스키마1/2·null/빈 값·비문맥 JSON 바이트·v3 예산·공통 evidence·인용·수치·구조 응답 계약을 검사했다. `pytest-final.xml` 보존.
- Mypy: 변경 소스4파일 통과. Ruff: 정본 backend 작업 위치에서 소스4·테스트3파일 통과.
- 독립 리뷰: 차단할 결함 없음. 독립 신규 동기6통과·1제외, 합성 혼합 그룹100건 복원 및 이전 비문맥 출력100건 바이트 일치, Ruff7파일 통과. 초기 root cwd/config 지정에 따른 Ruff import 분류 경고는 backend cwd에서 재확인해 해소했다.
- 기존 실행 증거32파일의 SHA 변경0개(`evidence-preservation.json`). answer-v2 원문도 변경하지 않았다.

최종 테스트 명령(저장소 루트, 설치된 `.conda` 사용):

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
backend/.conda/python.exe -X utf8 -B -m pytest -c backend/pyproject.toml -p pytest_asyncio.plugin backend/tests/unit/labs/rag/generation/test_http_evidence_groups.py backend/tests/unit/labs/rag/generation/test_direct_answer_prompt.py backend/tests/unit/labs/rag/generation/test_context_profile.py backend/tests/unit/labs/rag/generation/test_evidence_payload.py backend/tests/unit/labs/rag/generation/test_citation_validation.py backend/tests/unit/labs/rag/generation/test_numeric_validation.py backend/tests/unit/labs/rag/generation/test_structured_output_v2.py backend/tests/unit/labs/rag/generation/test_structured_output_v3.py -k 'not http_request' -q --basetemp=.local-data/project-agent-work/rag-direct-answer-20261015/pytest-final --junitxml=.local-data/project-agent-work/rag-direct-answer-20261015/pytest-final.xml
```

## 차단·미실행과 다음 단계

- `GET http://127.0.0.1:18000/api/v1/health`는 에이전트의 소켓 접근 거부로 실패했다. 사용자 확인 기동 이력을 서버 장애나 health 성공으로 바꾸지 않았다. 권한·정책·보호 설정을 바꾸거나 다른 경로로 우회하지 않았다.
- `backend/.venv`와 외부 `C:/projects/ai-workshop-scipy-test`는 모두 보존했다. 정리 전 health·프로세스/IDE 참조·reparse/current-size 검증이 미완료다. 외부 Conda 경로는 현재 CACHE_POLICY의 정확한 프로젝트 정리 대상에 포함되지 않아 후속 조사와 분류 기록도 필요하다. 휴지통·이동·영구삭제 재시도0.
- mock HTTP 비동기 테스트도 이벤트 루프 생성 시 socketpair accept에서 정지했다. 15초 faulthandler로 테스트 본문 이전임을 확인해 해당 실행을 중단했다. 이벤트 루프·소켓 구현을 바꾸지 않았다. 해당 새 테스트1개 및 기존 HTTP 비동기 회귀 전체는 통과로 집계하지 않았다.
- 실제 T+4 답변·인용 수용·지연 단축, 전체 backend/통합 테스트, 프론트 검증은 미실행. 기존 입력·실행 예산과 본래 데이터/모델을 유지하며 활성 프로파일 변경·재색인·서버 재시작은 하지 않았다.
- 문제 이력 운영 DB 반영은 미완료다. 연결된 ISSUE-00013의 최신 revision을 조회/수정하지 않았으며 옛 open/r33을 현재 상태로 단정하지 않는다. 이 기록은 운영 DB 갱신을 대신하지 않는다.
- 다음 후보는 정상 사용자 환경에서 health와 비동기 mock 회귀를 확인한 뒤, 별도로 수량·자원을 정한 승인 예산으로 v3와 그룹화 입력의 실제 품질·지연을 재평가하는 것이다. 기존 환경 정리는 필요한 관측을 충족한 뒤 복구 가능한 방식으로 마감한다. RAG 안정화 → Agents SDK → 벡터 저장소 비교 → 로컬 LLM 파인튜닝 → Kubernetes 순서는 유지한다.
- 커밋·푸시·마이그레이션·DB/ES/Docker 상태 변경, 다운로드, 예약·학습 진도 변경은 없다.

## 후속 health·mock 확인과 실평가 계획

사용자의 후속 진행 요청에 따라 차단을 재시도하지 않고 실행 경로와 남은 검증만 확인했다. 이 작업에는 앱 터미널이 연결돼 있지 않았고 사용자의 새 health 응답도 없다. 자동 실행 경로의 제한이 해제됐다는 증거는 없으므로 에이전트 health·비동기 실행 재시도0을 유지한다. 직전 변경11파일 SHA 무변경, 지정 비동기 mock 테스트 **8개 collect-only 성공(2.88초)**을 확인했다. 수집은 테스트 통과가 아니다. 기존 116개 테스트는 반복하지 않았다.

### 사용자 정상 PowerShell 최소 확인

기존 서버는 그대로 두고 일반 사용자 PowerShell의 새 창에서 실행한다. 관리자 권한·새 설치·환경 추가는 필요하지 않다. 이미 동일 Conda 환경을 준비한 창이면 환경 준비5줄은 생략할 수 있다. health가 실패하면 그 오류를 전달하고 권한을 바꾸거나 반복하지 않는다.

```powershell
Set-Location C:/projects/ai-workshop
C:/Users/bumci/miniconda3/python.exe -I -B -m conda shell.powershell activate C:/projects/ai-workshop/backend/.conda | Out-String | Invoke-Expression
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
Set-Item Env:PYTHONPATH C:/projects/ai-workshop/backend/src
Set-Item Env:PYTHONUTF8 1
Invoke-RestMethod 'http://127.0.0.1:18000/api/v1/health' -TimeoutSec 10 -ErrorAction Stop
```

응답 `status: ok`를 확인한 뒤 같은 창에서 아래를 실행한다. 세 테스트 계열의 파라미터 조합까지 총8개이며 HTTP는 MockTransport를 사용한다. 실제 모델·DB·ES 호출은 없다.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
backend/.conda/python.exe -X utf8 -B -m pytest -c backend/pyproject.toml -p pytest_asyncio.plugin backend/tests/unit/labs/rag/generation/test_direct_answer_prompt.py::test_http_request_uses_selected_v3_without_changing_schema_or_citation_ids backend/tests/unit/labs/rag/generation/test_openai_compatible.py::test_http_context_compaction_preserves_evidence_and_citation_boundary backend/tests/unit/labs/rag/generation/test_openai_compatible.py::test_http_compaction_keeps_noncontextual_wire_unchanged -q -o faulthandler_timeout=15
$LASTEXITCODE
```

기대값은 8 passed와 exit0이다. 15초 진단은 자동 중단 타이머가 아니며, 60초 동안 완료되지 않으면 Ctrl+C로 해당 테스트만 중단하고 출력을 보존한다. 환경 변수는 이 창에만 적용된다. health/mock 성공은 구환경 미사용·실제 품질을 보장하지 않으므로 두 구환경은 계속 보존한다.

### 별도 새 실평가 범위 — 승인·runner 구현·실행 전

- **권장 최소 생성 POST2회**, 순차 실행: 같은 지급 질문의 일반 규칙 답변1회와 근거 없는 질문의 abstention1회. 기존 소진된 1/1 기록·잠금·manifest는 절대 재사용하거나 초기화하지 않는다. 이번 진행 요청은 범위 정리까지이며 새2회 실행 승인으로 간주하지 않는다.
- 기존 로컬 `gemma4:e2b-it-q4_K_M`와 승인된 공개 합성 문서에서 저장된 근거28개만 사용한다. 기존 사례와 비교하는 frozen-input 생성 평가이며 전체 검색 E2E가 아니다. 검색·임베딩·rewrite·모델 다운로드·외부 호출0이다. 부정 질문 후보는 해당 상품의 2030-01-01 실제 운용수익률이며, 저장 근거에 2030이 없음을 정적 확인했다. 실행 전 28개 전체에 답이 없음을 별도로 확정해야 한다.
- 사전 확인 최대60초: 현재 권한과 공개 범위·원본/근거 SHA·순서·서버 health·실제 모델 digest 일치. 태그만 같은 모델은 수용하지 않는다. 새 manifest에 두 질문, 입력/프롬프트/제품 코드 SHA, 모델 digest, 실행 환경·파라미터를 고정한다. 조건 불충족 시 생성0회로 중단한다.
- 요청별 메모리 복사에서만 `prompt_ref=rag-answer-v3`를 선택한다. 활성 DB 프로파일은 그대로 둔다. 기존 schema2·temperature0·max_output_tokens512·answer_reasoning_effort none·재시도0·timeout360초를 유지한다. 시험용 실제 파라미터와 원래 프로파일을 구분해 기록하며 기존 버전으로 위장하지 않는다. 영구 설정을 바꾸지 않아 종료 시 복사본 폐기로 복구한다. 기존 서버·모델을 재시작하지 않는다.
- 클라이언트 대기는 요청당 최대360초, 두 요청 최대720초와 사전 확인60초를 합해 **최대780초(13분)**로 제한한다. 이는 원격 모델 작업 종료 보장이 아니다. POST 전송 뒤 결과 불명도 예산을 소비하며, timeout·취소·응답/인용 검증 실패 등 불확실한 실패에서는 재시도나 두 번째 요청을 하지 않는다.
- 기존 증거 폴더와 다른 새 run ID 디렉터리에 manifest, 호출 전 예산 예약, 최종 직렬화 입력 SHA, 응답·finish reason·usage·소요 시간·검증 결과·중단 상태를 기록한다. 비공개 내부 추론은 저장하지 않는다. 서버가 보고하지 않은 load/prefill/decode 시간은 추정하지 않는다. runner는 아직 구현하지 않았으며 승인 범위가 정해지면 mock 검증 후 사용한다.
- 긍정 성공: 일반 T+4 규칙·영업일 단위·근거에 있는 접수 기준/조건을 구분해 설명하고 정확한 근거 UUID 인용 검증을 통과한다. 날짜 예시로 일반 규칙을 대체하거나 사용자 날짜를 추정하면 실패다. 부정 성공: 정상 완료·schema2의 insufficient_evidence와 빈 claims. length/파싱 실패/timeout/인용 실패는 abstention 성공이 아니다.
- 성능은 동일한 생성 어댑터 구간의 이전266.78초와 새 실측을 비교한다. 질문1회의 관측으로 P95·재현성·원인별 개선을 확정하지 않는다. 두 사례 통과도 기본 프로파일 자동 승격 근거로 사용하지 않는다.
- 독립 검토에서 새 예산 분리, 모델 digest 고정, 결과 불명의 예산 소비와 후속 중단, 클라이언트/원격 종료 구분을 확인했다. 실제 새 추론0회, health 성공·mock8통과·구환경 정리·운영 DB 갱신은 여전히 미확인/미완료다.

## 2026-10-16 사용자 실행 확인

- 사용자가 일반 PowerShell에서 새 환경 서버의 health 응답 `status: ok`를 보고했다. health 응답의 정확한 관측 시각은 전달되지 않았다.
- 부모 작업은 **2026-10-16 11:32 KST(02:32 UTC)** 스크린샷에서 위에 안내한 동일한 세 테스트 선택 명령이 `backend/.conda/python.exe`로 실행돼 **8 passed in 2.00s**로 완료됐고 PowerShell 프롬프트가 돌아온 것을 확인했다고 전달했다. 별도 종료 코드 숫자는 전달되지 않아 exit0 관측으로 추가 기록하지 않는다.
- 이는 사용자 정상 터미널 실행 증거다. 이 작업에서 health·pytest를 직접 재실행하거나 스크린샷 원본을 별도로 열람한 결과는 아니다. 앞선 에이전트 소켓 차단·이벤트 루프 정지 기록을 보존하며, 사용자 환경의 성공으로 에이전트 실행 제한 해제를 추정하지 않는다.
- 지정 mock8개의 실행 미확인 상태는 사용자 실행 통과로 갱신한다. 실제 모델 호출을 하지 않는 검증이므로 일반 T+4 답변 품질·지연 개선이나 전체 RAG 수용을 완료한 것으로 확대하지 않는다.
- 새 로컬 모델2회 재시험은 **승인 대기·실행0회**다. 기존 소진 예산1/1, 실행 증거와 활성 설정을 유지한다. 구 `.venv`·외부 Conda 삭제, 서비스·DB/ES/Docker 변경, 운영 문제 이력 DB 갱신은 하지 않았다.
- 이번 반영은 WORKBOARD와 이 작업 기록만 변경했다. 문서 공백·UTF-8과 증거 표현을 검사했으며 기존 테스트는 반복하지 않았다.
