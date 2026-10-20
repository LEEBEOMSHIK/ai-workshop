# RAG HTTP 어댑터 취소 회귀 보강

2026-10-11. RAG 안정화의 모델 failure/timeout/cancel 하위 검증 한 건이다.
제품 기능 수정이나 실제 모델 종료 검증을 완료했다는 의미가 아니다.

## 최신 확인과 선정

- README·설계·WORKBOARD·관련 계획/작업 기록과 실제 두 HTTP 어댑터 및 기존 테스트를 대조했다.
  `.agents/skills`는 이 체크아웃에 없었다. 추적된 하위 AGENTS는 없었다.
- 기록상 최근 완료는 source 연결 조회·보호 파일·TLS 수명주기 일부다. ISSUE-00013은
  최신 저장소 기록에서 open/r33이고 native 조립·역사 종료·보안 전환·별칭 복구·첨부 READY는
  미완료다. 이번에는 운영 DB를 조회하지 않았으므로 현재 DB 상태를 재확인한 값은 아니다.
- 작업 상태 도구에서 같은 저장소의 `다음 작업 확인`은 커밋 검증 도중 interrupted/notLoaded,
  학습 구조 작업은 idle이었다. 다른 대화의 커밋 요청을 이번 작업의 승인으로 사용하지 않았다.
- 시작 시 main에 461개 변경 파일이 있었다. 임시 디렉터리에 파일별 SHA와 Git 상태,
  WORKBOARD 원본을 보관하고 쓰기 전 대조했다. 기존 제품·테스트 파일은 수정하지 않았다.
- 기존 timeout/HTTP 오류 테스트는 있었지만 요청·재시도 대기에서 task 취소를 검증하는
  사례는 두 HTTP 테스트 파일에 없었다. 운영 상태 변경 없이 추가 가능한 이 범위를 선택했다.
- 낮은 위험의 테스트 전용 변경이다. 메인이 테스트 설계·AI 런타임 계약 확인·통합을 맡고
  별도 독립 코드 리뷰어가 검토·재실행했다. UI·DB·배포·권한·공개 계약 변경 역할은 제외했다.

## 구현

`backend/tests/unit/labs/rag/generation/test_http_cancellation.py`를 추가했다.
두 HTTP 어댑터 × generate/contextualize × 요청 중/timeout 재시도 대기/429 재시도 대기의
12사례에서 CancelledError 전파, task 취소 상태, 요청 1회와 finally 실행을 확인한다.
Event로 진입 지점을 맞추고 최대 대기 검사 후 정리하므로 실시간 sleep에 의존하지 않는다.
MockTransport와 기존 합성 fixture만 사용하며 외부 모델·소켓·DB를 호출하지 않는다.

## 실행한 검증

backend 디렉터리의 기존 `.venv/Scripts/python.exe`를 사용했다.

- `-B -m pytest tests/unit/labs/rag/generation/test_http_cancellation.py tests/unit/labs/rag/generation/test_openai_compatible.py tests/unit/labs/rag/generation/test_openai_responses.py -q --tb=short`: 최종 **83 passed**, 0.84초.
- 새 파일 `ruff check`, `ruff format --check`: 통과.
- `MYPYPATH=backend/src`, `mypy --strict --explicit-package-bases --follow-imports=silent` 새 파일: **1 source file 통과**.
- 독립 리뷰: 차단 지적 없음. 최종 새 파일 독립 재실행 **12 passed**, 0.63초.
- 메모리 내 결함 주입: 두 어댑터의 요청 예외 처리를 BaseException으로 바꾸면 요청 취소
  4사례가 provider_invalid_response로 실패했다. backoff 취소를 삼키면 8사례가
  `Provider did not propagate cancellation`로 실패했다(16.61초). 소스 파일 변경은 없었다.
  이후 깨끗한 프로세스의 최종 83통과를 확인했다.
- 최초 새 테스트는 없는 contextualization 인자를 전달해 6실패/6통과였고 인자를 수정했다.
  첫 backoff 변이는 테스트 namespace에 CancelledError가 없어 8실패했으므로 유효한
  결함 탐지 증거로 세지 않았다. namespace 보존과 bounded wait 보강 후 위 8실패를 확인했다.
- 최종 파일 보존 검사에서 별도 동시 변경을 감지했다:
  `evaluation/test_generative_failure_metrics.py` 수정,
  `evaluation/test_generative_workflow.py`와 `executions/test_citation_failure_diagnostics.py` 추가
  (모두 `backend/tests/unit/labs/rag/` 아래). 이번 작업은 이 파일들을 수정하지 않았고
  검사·완료 범위에서 제외한다. 초기 461파일 중 WORKBOARD와 위 동시 수정1개를 제외한
  459파일은 SHA가 동일했다. 최신5개·UTF-8·로컬 문서 링크 검사는 통과했다.

## 미실행과 남은 경계

실제 provider 실패/timeout/cancel·원격 실행 종료, Codex 자식 프로세스 종료, DB 저장·복원,
첫 질문/권한 committed 경합, 웹 E2E, 전체 저장소 테스트는 실행하지 않았다.
새 제품 결함을 확인한 작업은 아니며 ISSUE-00005/18의 실제 실행 완료 조건은 유지한다.
DB 변경 금지 범위이므로 관리자 문제 이력 등록·상태 변경은 미수행이다.

커밋·푸시·마이그레이션·DB/ES/Docker·서버·보안 설정·학습 진도·알림 예약을 변경하지 않았다.
기존 ISSUE-00013 역사 source map/종료 증거와 전체 native 연결의 미완료 기록을 유지하며
새 승인이나 receipt가 있다고 가정하지 않는다. 다음 독립 후보는 기존 Codex 실행 경로의
취소·deadline mock 회귀 보강이다. 실제 RAG 마감 후 Agents SDK → 벡터 저장소 비교 →
로컬 LLM 파인튜닝 → Kubernetes 순서를 유지한다.

## 최근 완료 목록에서 이동한 기존 기록

5. Kubernetes 학습·실습 후속 등록(2026-10-08): 현재 앱에 적용할 배포·통신·설정·복구·확장·영속 저장소 및 Compose 비교·학습 기록/흐름도 단계를 정리했다. 본래 자료/계정 보존과 OS 의존성·자원·실제 검증·원복/산출물 기준을 포함했다. 계획 등록이며 설치·실습·운영 전환은 미착수다. [계획](../superpowers/plans/2026-10-08-kubernetes-learning.md).


## 2026-10-12 승인된 Ollama HTTP 어댑터·종료 상태 보완

이 절은 위 10/11 테스트 전용 작업 이후 별도로 승인된 제품·테스트 변경이다. 이전의
Codex 취소 후속 후보를 재개하지 않았다. 중간 위험의 RAG 생성/대화 계약 변경으로 분류하고,
메인이 설계·대화 상태·통합을, 별도 구현자가 HTTP 어댑터를, 독립 리뷰어가 검증을 맡았다.
UI·DB schema·설치/인프라·보안 변경은 제외했다. 기존 미커밋 Gemma/문서 작업을 보존하고
깨끗했던 대상 파일 및 기존 기록의 SHA를 쓰기 전에 확인했다. 새 작업 폴더나 문서는 만들지 않았다.

### 구현 결과

- `generation/openai_compatible.py`: schema2의 status/claims 일관성, 타입·UUID·중복/추가 필드,
  정상 assistant 종료와 잘린 출력 검증. 명시적 근거 부족 응답을 수용한다. schema1 호환,
  schema3 거부와 공통 인용 검증은 유지한다.
- `generation/execution.py`, `conversations/service.py`, `conversations/domain.py`:
  대화별 POST 시도를 추적한다. 취소·timeout·전송 실패 뒤 `execution_terminated=false`와
  `provider_termination_unconfirmed`를 보존하고 결과를 폐기한다. 재시도 성공으로 이전
  미확인을 덮지 않으며 다음 질문을 막는다. 삭제 tombstone도 종료 확인으로 바꾸지 않는다.
  기존 다른 provider와 과거 일반 failed/interrupted 동작은 유지한다.
- 기존 테스트4파일에 HTTP 출력/취소/재시도·동시 대화·삭제 경합·문맥화 및 검색/인용 경계를
  추가했다. 계약은 [ADR-0009](../decisions/0009-model-deployments-and-data-policy.md)에 먼저 명시했다.

### 실제 검증

기존 AMD64 `backend/.venv/Scripts/python.exe -B` 사용, backend 기준:

- 변경 전 종료 상태6사례가 모두 기존 `execution_terminated=True` 때문에 실패했다.
  어댑터 테스트는 구현자 보고 기준30실패를 확인한 뒤 수정했다. 새 검색 테스트의 최초3실패는
  fixture의 health GET 누락으로, 이를 보완한 결과이며 제품 결함 탐지 수치로 합치지 않는다.
- `-m pytest tests/unit/labs/rag/generation tests/unit/labs/rag/conversations tests/unit/labs/rag/search tests/unit/labs/rag/deployments tests/unit/labs/rag/policies -q --tb=short`:
  **1467 passed, 4 skipped, 1 warning, 40.70초**. warning은 기존 Starlette/httpx deprecation이다.
  건너뛴 검사는 통과로 세지 않는다. 합성 fixture/로컬 검증이며 유료·실모델 호출은 없다.
- `-m ruff check --no-cache` 제품4파일·테스트4파일: 통과. 최초 테스트 import/줄 길이5건을 수정했다.
- `-m mypy --strict --follow-imports=silent --no-incremental --cache-dir=nul`
  제품4파일: **Success: no issues found in 4 source files**.
- 독립 리뷰: 중대도 있는 결함 없음. 어댑터/대화 테스트3파일 **97 passed, 2.83초**,
  추가 HTTP→검색/인용 파일 **6 passed, 1.25초**. 전체 회귀 수치와 중복 합산하지 않는다.
- `git diff --check`: 통과. 기존 다른 미커밋 변경을 현재 작업의 성과로 계산하지 않는다.

### 미검증·다음 경계

실제 Ollama/Gemma 추론·취소/timeout 뒤 원격 종료, DB 영속화·migration/Deployment 등록,
브라우저·운영 활성화는 검증하지 않았다. 사용자의 수동 모델 응답 성공은 앱 RAG 통합 증거가 아니다.
완전한 HTTP 응답은 해당 요청의 통신 완료이며 프로세스 종료·모델 unload를 증명하지 않는다.
종료 미확인 상태의 정식 복구 API는 여전히 미구현이고 임의로 gate를 해제하지 않는다.
제품 결함과 수정은 이 절에 기록했으며 문제 DB 갱신은 DB 변경 금지에 따라 대기다.
다음 후보는 실제 Ollama 연결 전 기존 Deployment/Generation Profile 계약과 본래 환경의
DB 호환성·종료 검증 절차를 좁혀 확인하는 일이다. 등록·migration·실호출은 별도 승인 범위다.
설치·다운로드·서비스/보안 전환·commit/push·학습 진도·예약 변경은 수행하지 않았다.


## 2026-10-12 실제3회 실패 후 Ollama reasoning 호환 보완

### 선행 관찰과 승인 경계

코드/mock 검증 이후 별도 읽기 전용 승인을 받아 기존 DB의 read_only=on 세션에서0063과
local_model_ref 열 부재를 확인했다. 기존 대화 execution_terminated 열은 있다. 로컬 HTTP
Deployment는 없었고 루트 .env와 조사 프로세스에 provider endpoint 참조가 없었다. 활성
asset-management 연결v2·구성v4의 schema2/32근거는 유지되며 schema3/128후보와 다르다.
ISSUE-00013·별칭 gate는 재조회하지 않았다. Ollama 비추론 조회는0.40.3 및 정확 모델
`gemma4:e2b-it-q4_K_M`을 확인했다.

이후 승인된 합성 실제 요청은 기존 어댑터·동일 모델·120초/512토큰/temperature0/재시도0으로
순차3회만 실행했다. 아래는 수정 전 실패 기록이며 수정 후 성공으로 바꾸지 않는다.

| 시험 | 초 | 관측 결과 |
|---|---:|---|
| 정상 답변 | 44.285 | HTTP200, stop, content schema2/answered. message.reasoning 때문에 provider_invalid_response |
| 근거 부족 | 31.532 | HTTP200, stop, content schema2/insufficient_evidence. 같은 이유로 거부 |
| 문맥화 | 25.975 | HTTP200, length, completion512토큰, 유효 content JSON 미완성·reasoning 존재로 거부 |

모든 응답 model은 위 exact ID였다. reasoning 원문을 출력·보관하지 않았고 인용 UUID와 질의
변환은 어댑터 검증을 통과하지 못해 미검증이다. HTTP 응답3건은 수신했지만 서버 종료 증거가
아니다. DB/파일/서비스를 변경하지 않았고 호출 예산3회를 소진한 뒤 중지했다.

### 이번 코드 변경

사용자가 reasoning 처리·출력 길이의 코드/테스트 보완을 승인했다. 추가 실호출은 승인되지
않았다. 중간 위험의 어댑터 계약 보완으로, 메인이 구현/테스트·계약·기록을 맡고 독립 리뷰어가
검증했다. DB·UI·인프라·보안 역할은 범위 밖이다. 기존 파일 hash/작업 상태를 확인했다.

수정 제품은 `generation/openai_compatible.py` 하나다. `dialect="ollama"` + schema2에서만
공식 message.reasoning 문자열을 버리고 content를 엄격 검증한다. 비문자열 reasoning,
알 수 없는 message 필드, content 추가 필드·중복 키·status/claims·UUID·잘린 출력은 거부한다.
외부 envelope의 중복 키도 이 선택 경로에서 거부한다. 문맥화에만 reasoning_effort=none과
짧은 독립 검색 질의를 요구하며 기존 max_tokens를 유지한다. length 결과를 재시도하지 않는다.
생성의 thinking 설정·schema1·기본 openai dialect·기본 factory·다른 provider는 변경하지 않았다.
따라서 이번 완료는 **명시적 opt-in 어댑터 호환성**이며 앱 기본 연결의 활성화가 아니다.

근거는 [Ollama v0.40.3 변환 코드](https://github.com/ollama/ollama/blob/v0.40.3/openai/openai.go),
[동일 버전 Gemma4 renderer](https://github.com/ollama/ollama/blob/v0.40.3/model/renderers/gemma4.go),
[공식 호환 API](https://docs.ollama.com/api/openai-compatibility),
[Gemma thinking 계약](https://ai.google.dev/gemma/docs/capabilities/thinking)이다. none→think=false와
Gemma4의 thinking 토큰 조건부 추가를 확인했다. 설치된 사용자 GGUF에 실제 적용돼 출력이
짧아지는지까지 확인한 것은 아니다.

### 이번 실행한 검증

- 기존 `test_openai_compatible.py`에28사례 추가. 최초 새 인자 부재로24실패를 확인했고,
  인자 연결 후 핵심4사례가 기존 reasoning 거부에서 실패하는 것을 확인한 뒤 수정했다.
- adapter+HTTP취소+검색/인용 집중 회귀112통과/1.40초. 이 과정의4실패는 테스트 호출행에
  합성 canary literal을 넣어 traceback 소스행에서 검출한 문제였고 입력 준비 위치를 수정했다.
- `backend/.venv/Scripts/python.exe -B -m pytest tests/unit/labs/rag/generation tests/unit/labs/rag/conversations tests/unit/labs/rag/search -q -rs --tb=short`:
  **1373 passed, 4 skipped, 1 warning, 37.33초**. 4skip은 OS 권한상 합성 symlink 불가,
  warning은 기존 Starlette/httpx deprecation이다. 실모델/DB 호출 없는 회귀다.
- `ruff check --no-cache` 변경 제품/테스트2파일 통과. `mypy --strict --follow-imports=silent
  --no-incremental --cache-dir=nul` 변경 제품1파일 통과.
- 독립 리뷰에서 severity 있는 결함 없음. test_openai_compatible/test_terminal_cleanup_cancellation/
  test_provider_insufficient_evidence 3파일 최종
  **122 passed, 2.47초**. 처음에는 메인의 줄 정리와 실행이 겹쳐 traceback canary7실패가
  있었으나 수정 종료 뒤 독립 재실행은 통과했다. 결과를 중복 합산하지 않는다.
- diff 공백·기존 문서 링크/UTF-8·WORKBOARD 최근5개 검사 통과. 새 문서/작업 폴더 없음.

### 미검증과 다음 승인 대상

이번 추가 실모델 호출0, DB 조회/쓰기0, migration/설정/서비스/보안/설치/다운로드/commit/push0.
본래 embedding/OCR native 차단과 종료 미확인 대화의 정식 복구 API는 미해결이다.
다음 실시험은 별도 승인 후 같은 exact 모델·endpoint에 dialect=ollama/schema2를 명시하고,
합성 정상/근거부족/문맥화 최대3회·120초·512토큰·temperature0·재시도0으로 한정한다.
미확인 종료/서버 비가용이면 중지하고 reasoning 원문 대신 최종 검증 상태·UUID·지연만 기록한다.

새 DB가 필요한 것은 아니다. 기존 DB는 모델/Deployment/생성프로파일/구성 등록을 저장한다.
0063 대 현재 ORM의 local_model_ref 불일치는 이전 local_transformers 변경에서 왔고 Ollama
HTTP 자체는 이 열을 쓰지 않는다. 직접 adapter 시험은 DB 없이 가능하다. 앱 반영은0063 호환
코드 범위 분리 작업 또는 migration/롤백 검토를 별도로 승인해야 하며0064/0065 일괄 적용을
자동 전제로 삼지 않는다. 문제 DB 등록은 이번 쓰기 금지에 따라 대기다.


## 2026-10-12 승인된 endpoint dialect 연결

사용자가 기존 네 제품 파일의 Ollama 설정 전달과 mock 검증을 승인했다.
`config.py`에 `AI_WORKSHOP_PROVIDER_ENDPOINT_DIALECTS`를 추가하고 endpoint_ref별
`openai`/`ollama`만 허용한다. 기존 endpoint 참조에 없는 키는 거절하며 기본 map은 비어 있다.
factory는 map을 복사해 로컬 HTTP 어댑터에만 전달하고 기본 dialect는 openai를 유지한다.
검색 API와 Deployment health 서비스가 같은 설정을 전달한다. 주소·포트·모델명 추측,
기존 endpoint 목록 변경, 다른 provider 변경 또는 schema1 정책 변경은 하지 않았다.

수정 전 현재 포트18000의 PID29536·시작시각2026-10-08T09:46:23.984+09:00을 기존
`rag-codex161-rollout-20261008` 실행 기록·시작 스크립트·서버 로그와 대조했다.
동일 프로세스의 실행 명령에는 --reload가 없었다. 직접 CIM 명령줄 조회는 접근 거부였으며
그 접근을 우회하지 않았다. 수정 후에도 동일 PID·시작시각·포트와 .env SHA를 확인했다.

- 제품 수정4파일: config.py, generation/runtime_resolver.py, search/api.py, deployments/service.py.
- 관련 테스트2파일: tests/unit/test_config.py, generation/test_openai_compatible.py.
  신규30사례로 설정·키별 값 검증, factory/검색/health 조립의 실제 어댑터 mock 요청,
  명시 선택·기본값·schema1·다른 provider 보존을 확인했다.
- RED: 최초20실패/10통과 중1개는 외부 provider fixture 누락이었다. fixture를 보완한 뒤
  해당 사례가 새 factory 인자 미구현으로 실패함을 별도 확인했다. 구현 후193통과.
- 독립 설정·어댑터·resolver203통과, 차단 지적0. 제품4파일 strict Mypy 및 변경6파일 Ruff 통과.
  Mypy 기본 SQLite 캐시는 Windows NUL/3.13 내부 오류가 났고,
  `--no-incremental --no-sqlite-cache --no-fixed-format-cache --cache-dir NUL`로 통과했다.
- 전체 안전 단위 범위 `pytest tests/unit -q --tb=short`: **7059통과/63실패/6skip**,344.00초.
  실패: object_store/test_intake.py2, test_originals.py28, test_temporary.py19
  (store_unavailable 및 파일/관찰 불일치), indexing/test_alias_recovery_local_native.py13
  (helper CreateProcess WinError5), runtime_topology/test_compose_contract.py의
  test_cpu_ocr_extra_is_explicit_and_the_ambiguous_extra_is_absent1
  (기존 torch sources list와 dict 기대값 불일치). 실패별 이름·trace는
  `.local-data/test-results/ollama-dialect-unit-20261012.log`에 보존한다.
  저장소49실패의 정확한 native 원인은 이번 범위에서 확정하지 않았다.
  초기의 합성 키 조건 추정은 실제 실패 원인이 아니었다. 전체 녹색으로 보고하지 않는다.
  skip6·기존 Starlette/httpx deprecation warning1도 남아 있다.

접근 거부 우회나 범위 밖 제품/의존성 수정·설치로 실패를 숨기지 않았다.
실제 .env·DB 등록/health 기록·활성 구성·서비스·보안 권한·모델 호출·commit/push 변경은 없다.
운영 설정 등록·API 반영·실제 RAG 수용은 별도 대기다. 연결 코드/mock 완료가 앱 연결 완료를 뜻하지 않는다.
승인된 백업 한 파일의 휴지통 이동은 [기존 migration 기록](2026-10-11-local-transformers-generation.md#승인된-백업-휴지통-이동)에 별도로 남겼다.


## 2026-10-12 Torch 계약과 저장소 최소 진단

사용자 승인 범위는 오래된 Torch 계약 테스트 정합화와 저장소 실패 단계·오류 번호 진단,
임시 데이터 재현 및 독립 검토다. Python 백엔드 구현과 독립 코드 리뷰 역할을 분리했다.
DB·배포·UI·모델 동작 변경은 제외했다. `.agents/skills`는 현재 저장소에 없다.

- Torch: 이전 Transformers 작업에서 추가한 generation-cpu와 embedding-cpu의 두 명시적
  CPU 인덱스 연결을 계약 테스트가 검증하도록 수정했다. pyproject/lock/설치는 변경하지 않았다.
- 저장소: 공유 `_windows_fd`의 CreateFileW 실패 직후 GetLastError를 보존한다.
  상수 stage·대상 종류·delete 여부·정수 winerror만 경고에 기록하며 경로·식별자·OS 원문·
  traceback은 기록하지 않는다. 예외에는 비민감 고정 문구와 번호만 유지한다.
  접근/공유/reparse 플래그, 전체 부모 핀, 정체성 검증, cleanup과 상위 안전 오류는 유지했다.
- 새 mock10사례는 오류5/32·파일/디렉터리/루트·삭제 여부, 보호 플래그 유지,
  잘못된 핸들의 미채택 및 경로/traceback 비노출을 검사한다.
- RED: 새 진단10건은 winerror 소실, 기존 topology1건은 dict/list 불일치로 실패했다.
  합계11실패/4통과. 변경 후 관련 전체 명령은
  `pytest tests/unit/infrastructure/object_store tests/unit/platform/runtime_topology/test_compose_contract.py -q --tb=short`:
  **62통과/49실패/2skip**, 2.12초. 실패49개의 식별자는 직전 전체 로그의 저장소49개와 같다.
- 실패49개 각각에서 `stage=CreateFileW target_kind=directory delete=False winerror=5`를
  확인했다(진단 총50회). 이는 볼륨 루트가 아닌 디렉터리 보호 핸들 획득의 접근 거부다.
  정확한 디렉터리·ACL·보안 정책 원인은 확정하지 않았다. 경로를 로그에 추가하거나
  권한·보호 설정·대체 실행 경로를 변경하지 않았다. 저장소 동작 자체의 수정은 하지 않았다.
- Ruff 변경 Python3파일 통과. 제품 originals.py strict Mypy1파일 통과:
  `--follow-imports=silent --no-incremental --no-sqlite-cache --no-fixed-format-cache --cache-dir NUL`.
- 독립 읽기 리뷰 차단 지적0: 보호 플래그·핸들 소유권·상위 오류 변환과 비식별 로그를 확인했다.
  독립 별도 실행은 새 진단10+topology5 모두15통과(1.36초, exit0), 한 번 수행했다.

전체 단위 재실행, helper13건 실행, DB·실데이터·.env·서버·모델 호출·설치·commit/push는
미실행이다. 기존 전체7059통과/63실패/6skip을 현재 전체 녹색으로 바꾸지 않는다.
문제 이력 DB는 쓰기 승인 범위 밖이므로 갱신하지 않았다. uv 공식 lock 검증도 미완료다.
다음 후보는 승인된 동일 실행 환경에서 디렉터리 핸들 거부 원인을 읽기 전용으로 확인하는 것;
GENERIC_READ 약화·부모 핀 생략·skip 추가로 우회하지 않는다.
증거는 `.local-data/project-agent-work/storage-diagnostics-20261012/`의 baseline.json,
red.log, scoped.log에 보존한다. 기존 변경 및 학습 문서는 건드리지 않는다.


## 2026-10-12 HTTP 관리자 등록 폼

승인된 다음 개발 범위를 기존 owner API를 사용하는 관리자 폼으로 한정했다.
HTTP/Ollama 배포 폼은 모델·endpoint 참조·실행 환경·capability·재시도 값을,
일반 HTTP 생성 프로파일 폼은 exact 배포 버전·프롬프트 참조·생성 한도·선택적 근거 한도를 받는다.
URL 직접 입력을 차단하고 프로파일은 draft로 등록한다. 중복 제출, 입력 오류, 권한/서버 오류를
검사하며 실패 시 입력을 보존한다. 등록 자체로 health·추론·활성화·기본값 승격을 실행하지 않는다.
Codex 폼은 실행 환경 선택으로 분리하고 구성 스튜디오와 관리자 화면의 이동 링크를 연결했다.
서버 주소 관리 UI는 별도 설계 범위다. 신규 로컬 배포 폼은 secret_ref 없는 서버를 대상으로 한다.

수정 범위는 HttpDeploymentForm/HttpGenerationForm 및 각각의 테스트4파일,
ModelAdminWorkspace, models/api.ts와 api.test.ts, ModelLabPage.tabs.test.tsx,
ConfigurationStudioPage와 테스트의 합계 프론트엔드10파일이다. 기존 다른 변경은 보존했다.

- TDD: 신규 폼과 API/화면 연결의 기대 실패를 확인한 후 구현했다.
- 프론트엔드 관련12파일 **143 passed**(139.33초). 마지막 구성 화면 링크 추가는 해당 회귀를
  다시 실행해 **1 passed / 23 deselected**(7.92초)를 확인했다. 전체 저장소 통과 주장이 아니다.
- 독립 리뷰: 신규 폼46테스트 통과, 실제 백엔드 계약의 합성 입력 검증, 차단 지적 없음.
  마지막 이동 링크2파일도 별도 검토했으며 차단 지적 없음.
- 백엔드 기존 owner/참조/프로파일 계약 **49 passed**: 단위39, 메모리 프로파일 API7,
  메모리 배포 API3. 배포 API3의 초기 환경키 누락은 해당 테스트 프로세스에 합성 키를 넣어
  재실행했다. 실제 인증정보·DB·마이그레이션은 사용하지 않았다.
- TypeScript noEmit, 변경 프론트엔드10파일 ESLint 통과. 외부 LLM 호출과 실DB 통합 테스트는 미실행.

운영 범위는 별도 사용자 승인에 따라 진행했다. startup admission 읽기 전용 사전 검사 통과,
진행 중 실행/작업 여부 확인 후 .env 원문을 보존하며 endpoint 참조와 dialect 두 키만 추가했다.
`ollama-local`은 `http://127.0.0.1:11434`, dialect는 `ollama`다.
.env 변경 전 SHA256은 `2f760a3163f370b6ec6075b0ef2e61ae2489ef4810a0140cb6c8f25c50f3b2aa`,
변경 후는 `44fc0ddb25fc98bfde714b05687afc57fb4a460fb8c7603a375c9ed832bdcb33`다.

기존 API PID29536의 정확한 종료가 Windows 접근 거부로 실패했다. 다른 도구·권한 승격으로
우회하지 않았고 새 API도 시작하지 않았다. 기존 `/api/v1/health`와 `/api/v1/ready`는200이나
새 .env/코드는 실행 API에 미반영이다. 기존 API 터미널에서 Ctrl+C 후 기존
`.local-data/project-agent-work/rag-codex161-rollout-20261008/start_api.ps1`로 재시작이 필요하다.
브라우저는 로그인 화면이며 owner 인증 후 실제 관리자 UI 검증도 남아 있다.
로그인 경로는 `http://127.0.0.1:5173/login?next=%2Fadmin%2Frag%2Fmodels`다.

이번 실제 모델 호출 **0회**, 실제 모델/배포/프로파일/시험 구성 등록·health POST도0회다.
기존 활성 연결/기본값과 데이터를 보존했다. 다음 등록 전에 READY·job·dispatch를 다시 확인하고,
색인이 필요하면 중단한다. 정책 완화·DB 직접 쓰기·migration·설치·commit/push는 하지 않았다.
기존 별칭 복구·native 접근 거부·실모델 종료 증거와 RAG 전체 기능 마감은 별도 미완료다.

### 2026-10-13 기존 API 재시작

사용자 요청으로 포트18000의 기존 PID29536과 시작시각을 재확인하고 해당 PID만 종료했다.
첫 시작은 수동 `.env` 로더가 따옴표를 유지해 `codex_runner_refs` JSON 파싱에 실패했다.
`.env` 값은 수정하지 않고 기존 `start_api.ps1`을 숨김 실행해 재시작했다.
새 API PID116596, 시작시각2026-10-13T00:24:52+09:00, `/api/v1/health`와
`/api/v1/ready` HTTP200을 확인했다. 새 실행의 startup complete 로그도 확인했다.
관리자 등록·모델 health POST·추론 호출·RAG 질문은 실행하지 않았다.

### 재시작 후 읽기 전용 확인과 로그인 대기

사용자의 재시작 완료 통보 후 기존 PID29536 부재와 새 Python PID116596/145824,
시작시각2026-10-13T00:24:52+09:00를 확인했다. 포트18000의 health/ready는 모두200이다.
.env SHA는 위 기록과 같고 새 로컬 Settings 로더에서 ollama-local endpoint/dialect 값이
일치했다. 이는 로컬 설정 검사이며 실행 API의 관리자 조회·배포 health 검증은 아직 남아 있다.
기존 Chrome 탭에서 `/admin/rag/models` 진입 시 `/login?next=%2Fadmin%2Frag%2Fmodels`로
이동했다. owner 로그인 대기를 알렸고 인증정보 수집·우회 없이 중단했다.
이번 단계의 등록·health POST·실모델 호출은0회다. 로그인 후 등록 직전에
READY/job/dispatch 및 색인 필요 여부를 다시 확인한다. 다른 서비스와 기존 활성 설정은 건드리지 않았다.

### 2026-10-13 Chrome owner 등록 확인

지원되는 Chrome 확장 연결(browser1)의 기존 사용자 탭441323440에서 마스터 계정과
`/admin/rag/models` 실제 관리자 화면 접근을 확인했다. 쿠키/토큰/프로필DB를 추출하지 않았다.
등록 전에 읽기 전용 트랜잭션으로 합성 자료 현재4버전의 projection/index READY·active,
각 job succeeded/dispatch sent를 확인했다. 별도 개인 연구의 queued/pending1건은 보존했다.

실제 관리자 폼으로 다음 새 버전을 등록했다: Gemma 4 E2B Ollama 모델v1,
Gemma 4 E2B Ollama 로컬 배포v1, Gemma 4 E2B 로컬 시험 2026-10-13 생성 프로파일v1,
동명 비기본 시험 구성v1. 배포는 local_openai_compatible/local/development,
model=gemma4:e2b-it-q4_K_M, endpoint_ref=ollama-local, timeout120초/재시도0이다.
비추론 health POST는 정상·1076ms, UI 사용 가능을 확인했다.
생성은 draft/schema2/인용필수, rag-answer-v2·rag-contextualize-v1, 출력512토큰,
temperature0, 문맥 예산8그룹/32단위/12000자다.

시험 구성ID `428992ab-697d-4604-9f6f-7b64f063e71f`, 버전ID
`89351388-8ad6-4bd3-8ea3-c25244a24100`, 생성 프로파일ID
`a07c2838-49d8-4241-b56a-e5b2a0004748`다. 기존 legacy 처리v1/e5 색인v2/hybrid-rrf v2와
합성 참조 공간만 연결했으며 semantic0.9/keyword0.5, is_default=false/evaluation=pending이다.
저장 후 검색·답변 준비 완료를 확인했다. job16/dispatch8/projection8/index6의 개수와 상태는
전후 동일하며 새 색인이 생기지 않았다. 기존 도메인 연결v2/RAG-TEST v4는 수정하지 않았다.

이번 묶음의 실제 모델 호출은 여전히0회다. 정상/근거부족/취소 통합시험은 미실행이다.
현재 대화 라우트는 활성 도메인 선택 화면이므로 비기본 시험 구성을 직접 선택할 수 없다.
기존 Swagger UI의 검색 API 시험 입력 확인을 시작했으나 요청은 제출하지 않았다.
Chrome 로그인/등록 성공과 통합시험 완료를 구분한다. 제품 코드·인증·보안 설정은 변경하지 않았다.


### 2026-10-13 비기본 구성 실제 HTTP 시험3회

KST 2026-10-13(UTC 2026-10-12)에 기존 인증 Chrome의 Swagger UI로만 실행했다.
위 등록 기록의 시험 구성v1/version `89351388-8ad6-4bd3-8ea3-c25244a24100`과
기존 합성 자료 workspace를 지정하고 `experimental=true`, `history=[]`, retry=0을 유지했다.
쿠키·토큰 추출 없이 기존 UI/API를 사용했으며 요청을 3회 제출한 뒤 추가 호출을 중단했다.

| 시험 | 실제 관측 | 판정 |
|---|---|---|
| 정상 답변 | HTTP503 `codex_verification_unavailable`; correlation `66624c4a-4c0b-43ec-8044-aac6875ffa68` | 실패. 성공 생성 기록 없음, 원래 예외·단계·모델 도달 여부 미확정 |
| 근거 부족 | HTTP200 `insufficient_evidence`, `no_eligible_evidence`, text=null/citations=[], 생성 진단 null; correlation `175ee4ad-c27c-48ac-beb4-207c25056e35`; 총49.555초 | 검색 단계의 근거 부족 반환 확인. 모델 생성 호출0회이며 모델 자체 abstention 검증은 아님 |
| 취소 의도 | 15:50:22.699Z 요청 제출 후 페이지 이탈. 서버 접근 로그 HTTP200; correlation `8e238a2a-c8f0-4c87-ad6c-403744be7f90`, 15:50:56.843087Z allowed 감사 기록 | 응답 본문 미확인. 페이지 이탈 전에 완료됐을 가능성이 있어 취소 수용·추론 종료 미검증 |

HTTP 요청3회와 추론 호출 횟수를 구분한다. 실제 모델 추론을 확인한 건은0건이지만
실제 호출이0회라고 확정하지 않는다. 첫 요청과 세 번째는 각각 최대1회, 두 번째는0회로
보수적인 총 추론 상한은2회다. allowed 감사 상태·latency0·토큰null이나 현재 `/api/ps`의
빈 목록은 모델 진입/성공/원격 종료 증거가 아니다. 현재 미완료 요청은 확인되지 않는다.

독립 리뷰에서 `get_codex_services`의 yield를 감싼 일반 예외 처리 때문에 하위 검색 또는
정리 예외도 같은503 코드로 표현될 수 있음을 확인했다. Codex 장애·정책 차단·DLL 재발로
단정하지 않았다. `run_until_disconnect`의 코드상 취소/join 보장과 이번 요청에서 그 경로가
실행됐다는 증거도 구분한다. 직접 search API는 대화 cancelled terminal 저장 경로가 아니므로
대화 취소·다음 질문 수용 검증을 대신하지 않는다. 리뷰는 읽기 전용이며 추가 모델 호출은 없다.

운영 문제 이력 UI에 [ISSUE-00030](http://127.0.0.1:5173/admin/system/issues?issue=7a1607fd-9454-49ff-badd-266153293bd8)을
open으로 저장하고 상세 화면에서 확인했다. ISSUE-00018/00028과의 동일 원인 여부는 미확정이다.
다음 한정 후보는 원래 예외·실패 단계 식별 및 오류 분류 보존 회귀 검증이다.
정상 생성·인용/실모델 실패·timeout·cancel/대화 terminal·후속 질문 수용은 여전히 남았다.

시험 후 읽기 전용 DB 확인: 시험v1 is_default=false/evaluation=pending,
asset-management 활성 연결v2/RAG-TEST v4 유지, 기본 구성 없음,
job16(성공14/queued1/실패1), dispatch8(sent7/pending1), index6(모두ready)로 보존됐다.
projection 집계 재조회는 테이블명 불일치로 확인하지 못했으며 시험 전 READY 확인을 새 결과로
재사용하지 않는다. 새 색인·활성/기본값 전환·제품 코드 수정·서비스 재시작·설치·migration·
보안 변경·commit/push는 이 시험 단계에서 하지 않았다. 생성한 임시 파일은 없고 기존 로그·캐시는 보존했다.
문서는 기존 내용을 보존한 최소 갱신이며 UTF-8/WORKBOARD 줄 수와 git diff --check를 검증한다.


### 2026-10-13 ISSUE-00030 예외 경계 원인 추적과 최소 수정

사용자가 원인 추적 후 최소 제품 회귀 수정을 승인했다. 첫503의 원래 예외는 기존 stdout/stderr에
traceback·상관관계 상세가 없어 복구하지 못했다. 직접 search API에는 execution observer 설정이
없고 성공 감사2건의 execution_id도null이다. Ollama→Codex provider fallback은 없다.
search/api.py의 무조건 get_codex_services 의존성 → codex_admin_api.py의 try/async with/yield
경계가 하위 검색·정리의 일반 예외까지 Codex 초기화503으로 바꾸는 코드 결함은 확인했다.
기존 AppError는 그대로 통과하고 실제 Codex provider 선택은 별도 분기다.

추가 읽기 전용 감사 대조에서 #2/#3은 모두 allowed/evidence_ids=[]다. 현재 pipeline의 allowed
기록은 생성 전 빈 evidence 반환과 생성 후 비어 있지 않은 evidence 반환 두 곳뿐이다.
history=[]와 함께 두 요청 모두 생성 전 근거 부족 반환임을 뒷받침하며 독립 리뷰도 동의했다.
따라서 앞 기록의 보수적 상한2회를 **상한1회**로 정정한다. 실제 총0~1회 중 어느 것인지는
첫503 단계 미확정으로 알 수 없다. #3 HTTP200 본문 자체는 보존되지 않았으므로 status는
insufficient_evidence 경로로 추론하되 정확한 reason은 no_search_results/no_eligible_evidence 중
미확정이다. 서버 접근 로그는 응답 시작200 근거이며 원격 모델 취소·대화 terminal 증거가 아니다.
ISSUE-00030은 읽기 전용 DB에서 open/r1, UUID7a1607fd-9454-49ff-badd-266153293bd8로 재확인했다.

제품 변경은 codex_admin_api.py 한 곳: AsyncExitStack 진입만 초기화 오류 매핑 안에 두고
서비스 yield와 종료는 밖으로 옮겼다. 초기화의 기존 안전한503과 AppError·취소를 보존하고,
하위 일반 예외·정리 예외를 Codex 오류로 바꾸지 않는다. 원문/토큰/새 로그 필드를 추가하지 않았다.
일반 예외는 기존 FastAPI의 일반500 응답으로 전달된다. 이는 최초503의 근본 결함 해결이나
정상 모델 생성 완료 주장이 아니라 원인 관찰을 가리는 오류 경계의 수정이다.

신규 test_codex_service_dependency.py는 오류 identity·초기화 실패·취소·성공/실패 정리,
실제 create_app 합성 ASGI 요청의 일반500/private canary 비노출을 검증한다(lifespan 미실행).
첫 테스트 실행의 합성 Settings.secret_key 누락을 고친 후 수정 전2fail/3pass로 결함 재현,
수정 후 최종 신규9+기존관리자43+HTTP수명주기4=56passed(12.63초), Ruff 통과.
독립 리뷰는 ASGI 추가 전55passed(10.20초), 차단결함없음. 기존 Starlette/httpx deprecation1건.
Mypy는 대문자 cache-dir=NUL에서 Windows 경로 내부오류 후 소문자 nul로 수정하여
`--follow-imports=silent --no-incremental --cache-dir=nul` 대상1파일 통과했다.
전체 suite·실DB통합·실모델 재검증은 하지 않았다. API 재시작/추가 요청/설치/보안/기본값/색인/
commit/push 없음; 본래 실행 API에 이 코드가 반영됐다고 주장하지 않는다.

절차 점검: AGENTS.md는 사용자 제공 지침으로 처음부터 적용됐고 이번 점검에서 디스크 본문도
다시 확인했다. 수정 전 WORKBOARD·문제이력·project-agents 정본/activation/orchestration·
Python/독립리뷰 역할을 읽고 selector로 두 역할을 선택, 배정 전 중간 위험·참여/제외를 알렸다.
구현과 리뷰를 분리하고 TDD 실패→수정→검증을 수행했다. WORKBOARD 시작 갱신은 늦었고
별도 설계/계획 파일은 작성하지 않았다. 이번 변경은 기존 오류 경계 회귀 수정으로 처리했다.
개발 지침과 Codex 참고 README는 사용자 질문 후 재확인했으며 이를 작업 전 열람으로 소급하지 않는다.
현재 저장소 루트에 .agents/.codex는 없고 .agents/skills도 없다. docs/project-agents 역할 문서는
개발 지침이며, generation/prompts.py가 읽는 prompts/answer-v2.txt 등은 실제 앱 RAG 프롬프트다.

Ollama 경로는 파일시스템에서 재확인했고 Windows 서비스 이름 조회에 Ollama 항목은 없었다.
CIM의 현재 프로세스·부모 명령 조회는 접근 거부로 실패했고 우회하지 않았다. 서비스가 전혀 없거나
창 종료가 안전하다는 증거로 해석하지 않는다. WORKBOARD 실행 메모를 추가했으나 성능 환경변수4개
기존값은 아직 확인되지 않아 질문을 남겼고, 확정값 전 재실행을 막는 안내로 표시했다.
새 진단 파일은 만들지 않았으며 별도 설치·전역 환경/자동시작·실제 서버 시작/종료도 하지 않았다.

추가 ASGI 테스트도 독립 읽기 재리뷰에서 지적없음으로 확인했다(최종56pass는 메인, 독립실행은55pass). 신규 API 요청 금지에 따라 ISSUE-00030의 DB 상태는 open/r1로 유지하고 이번 수정 결과는 이 worklog에 기록했다.


### 2026-10-13 수정 반영 재확인과 정상1회 대기

사용자가 예외 경계 수정 반영을 위한 API 재시작 후 정상 답변1회(내부 추론 최대1회)를 추가 승인했다.
이전 종료 권한 거부를 재시도·도구 교체·승격으로 우회하지 않는 조건도 유지했다.
이번 작업 시작 시 AGENTS.md 디스크 본문, WORKBOARD 현재/다음 작업, Python 백엔드 역할,
Codex 프로젝트 에이전트 호출·인계 문서, 로컬 개발 안내의 호스트 API 실행 절을 다시 읽었다.
이는 이번 요청의 사전 확인이며 과거 누락을 소급 준수했다고 주장하지 않는다.

읽기 전용 Get-Process에서 기존 API PID116596와 venv launcher145824가 살아 있고 둘의 시작은
2026-10-13T00:24:52+09:00이었다. codex_admin_api.py 수정은2026-10-13T01:05:58+09:00
(UTC2026-10-12T16:05:58)로 더 늦다. 기존 start_api.ps1의 uvicorn 명령은 reload가 없고,
현재 작업에 연결된 app terminal도 없어 정상 종료를 전달할 제어 경로를 확보하지 못했다.
프로세스 종료/재시작을 시도하지 않았으며 수정 반영도 확인하지 못했다. 수동 재시작 필요를 즉시 보고했다.

추가 승인분의 HTTP 요청0회/추론0회다. 브라우저 인증/API를 새로 호출하지 않았으며 기존 요청의
결과를 이번 수정 후 검증으로 사용하지 않았다. 운영자가 기존 환경의 API를 정상 재시작한 뒤
새 PID·시작 시각·수정 반영과 기존 Chrome 인증을 확인하면 정상 요청1회 예산을 사용할 수 있다.
DB/색인/기본값/보안/서비스 상태 변경이나 종료 권한 거부 우회는 없다.

### 2026-10-13 01:32 API 재기동

사용자 요청에 따라 포트18000의 기존 Python PID116596(시작00:24:52)을 재확인한 후
해당 PID만 정상 종료하고 기존 `start_api.ps1`로 다시 실행했다. 새 PID39268의 시작은
01:32:01로 ISSUE-00030 수정 시각01:05:58보다 늦다. startup complete 로그와
`/api/v1/health`, `/api/v1/ready` HTTP200을 확인했다. 승인된 정상 요청1회와
추론 호출은 아직 실행하지 않았다.


### 2026-10-13 정상 요청1회 결과: 근거 단위 예산 초과

사용자의 재시작 완료 후 새 API PID39268(01:32:01 KST), 수정 파일 시각01:05:58,
기존 시작 스크립트의 저장소 경로·reload 없음, startup complete 및 health/ready200을
확인했다. 기존 Chrome owner 인증, 비기본 시험 구성v1/89351388-8ad6-4bd3-8ea3-c25244a24100,
Ollama Gemma 4 E2B 배포의 retry0과 기존 활성 연결v2/RAG-TEST v4 유지를 확인했다.
이번 수행자는 API·Ollama·DB·Docker를 재시작하거나 설정을 변경하지 않았다.

승인된 정상 요청을 2026-10-12T16:36:12.790Z(10/13 01:36:12 KST)에 딱 한 번
기존 인증 Chrome Swagger에서 제출했다. 질문은 합성 자료 AM-SYN-101의 환매 신청
마감 시각과 대금 지급 시점이며 기존 합성 workspace만 지정했다. 자동/수동 재시도 없음.
응답은 HTTP200, correlation `c3768a77-e5be-48e0-a0a0-8bc7b66978e5`,
`insufficient_evidence / no_eligible_evidence`였다. answer/text=null, citations=[],
선택 근거0이며 contextualization/generation 시간=null이다. 총53,656ms 중
retrieval32,277ms, selection20,092ms. 관련 합성 문서4개가 반환됐다.

이미 받은 diagnostics 278개를 집계하면 budget_exceeded2, below_threshold8,
not_transmitted268이다. 점수 기준을 통과한 eligible 후보2개가 있었으나 selected0이다.
각 후보는 incoming_units33/36으로 unit_limit32를 초과했다. incoming_characters712/683은
character_limit12000 이내이며 group_limit8, before_groups/units/characters 모두0,
violated=['units']였다. 따라서 이번 결과를 단순 점수 부족 또는 검색 결과 없음으로
설명하지 않는다. 임계값(semantic0.9/keyword0.5)이나 근거 한도를 변경하지 않았다.

읽기 전용 DB 감사는 같은 correlation의 allowed/evidence_ids=[], execution_id=null,
input/output_tokens=null, latency_ms0, safe_error_code=null,
created_at=2026-10-12T16:37:06.669505Z였다. 새 API stdout의 search POST200과 일치하며
새 stderr의 Traceback/ERROR 검색 결과는 없었다. 이는 생성 전 종료 근거다.
추가 승인 예산은 HTTP1회/생성0회로 종료했다. 앞선3회와 합치면 RAG HTTP4회이며
최초503의 추론 여부는 여전히 미상(전체 생성 추론0~1회)이다. 더 호출하지 않았다.

기존503은 재현되지 않아 최초 원본 오류·단계를 새로 복원하지 못했다. 오류 경계 수정의
기존 mock56pass/Ruff/Mypy/독립 리뷰 결과는 유지하되 이번200을 정상 생성·인용 성공이나
실제 취소 검증으로 보고하지 않는다. 이번에는 제품 코드를 추가 수정하지 않았고
WORKBOARD와 본 기록만 갱신했다. ISSUE-00030은 닫지 않는다.
다음 후보는 근거 단위 집계와 그룹 선택의 기대 동작을 기존 응답·코드·mock으로 확인하는
한정된 작업이다. 새 실모델 요청이나 한도 완화는 이번 결과 기록에 포함하지 않는다.


### 2026-10-13 근거 단위 집계와 그룹 선택 조사

범위: 기존 코드·설계·보관된 응답 메타데이터와 합성 unit으로33/36 대32를 재현한다.
중간 위험의 RAG 진단으로 selector가 Python backend/RAG lead/독립 리뷰를 선택했다.
메인이 근거 단위 전문 분석·테스트를 맡고 별도 budget_review는 읽기 전용 독립 검토했다.
DB·인프라·UI·모델 실행은 제외했다. 시작/종료 WORKBOARD 갱신, 쓰기 전 원본 바이트와
테스트 파일 SHA 확인으로 기존 변경을 보존했다. 실제 API/모델·DB 호출은0회다.

결론은 승인 설계상 안전거부이며 현재 PDF 문맥 그룹 크기와32단위 예산의 부적합이다.
09-21 문맥 근거 설계4절은 전체 그룹 수용/제외를 요구한다. 10-06 입력 예산 진단 설계의
‘확인한 경계’에는 이미33단위/712문자·36단위/683문자가 같은32한도로 제외된 사례가 있다.
context.py는 유효 원문 단위를 ID로 중복 제거한 뒤 그룹의 len(units)를 검사하고 초과 시
예산을 소비하지 않고 다음 후보를 검사한다. 기존 실제 응답의 두 그룹 단위 ID는 각각
33/36개 모두 고유하고 그룹 간 공통ID도0이다. 선택 경로의 중복 집계 증거는 없다.
PDF 파서는 text span별 bbox element를 만들며 chunker는 bbox 원문을 온전히 EvidenceUnit으로
보존하고 token 기준으로 chunk에 묶는다. 짧은712/683문자여도 단위33/36개일 수 있다.
같은 문자를 가진 별도ID나 현재 색인 원문의 완전성까지 이번 메타데이터 확인으로 증명하지 않는다.

질문 자체가 무관하거나 합성 자료에 답이 없다는 결론은 부적절하다. 기존 corpus 제작 코드의
환매 표에는 AM-SYN-101의15:00 마감/T+4 영업일 지급이 있고 기존 held-out-v2 H01에도
동일 목적의 질문/정답이 있다. 다만 현재 색인 원문을 새로 조회하거나 정상 생성은 검증하지 않았다.
따라서 이 질문/현재 PDF 그룹/32단위 구성의 조합은 정상 생성 양성 시험 조건에 맞지 않는다.
앞32개만 전달·한도 확대·그룹 재구성은 최소버그수정으로 처리하지 않고 별도 결정 대상으로 남긴다.

제품 버그가 확인되지 않아 제품 코드는 수정하지 않았다. 기존 test_pdf_context_budget.py에
characterization4건(진단on/off33/36거부, 동일ID/청크 중복과32경계, 초과그룹 뒤32그룹수용)을
추가했다. 기존동작검증이므로 최초부터 통과했으며 RED→GREEN 버그수정으로 보고하지 않는다.
합성36단위는 실제683문자 원문을 복제하지 않고 문자 한도 내임만 검증한다.
실행: pdf_context_budget/budget_trace/context3파일31passed(5.04초), Ruff 통과.
독립 검토는 변경 파일12passed(3.96초), 차단/중요지적0, 제품diff없음을 확인했다.
Mypy는 import internal 시 Windows 애플리케이션 제어 정책의 DLL 차단으로 실행 실패했다.
재시도·대체 로더·정책 우회 없이 중단했다. 전체 suite/실환경 API/모델/DB 통합은 미실행이다.
이 결과로 ISSUE-00030이나 정상 생성·인용/취소 검증을 완료 처리하지 않으며 문제 이력 DB도
API 재호출 금지로 갱신하지 않았다. 한도·활성 구성·색인·문서 데이터·서비스·commit/push 변경 없음.


### 2026-10-13 H07 실제 RAG 추가1회 결과

사용자 ‘진행해’ 승인으로 기존 비기본 Gemma v1의 H07 요청1회/내부 추론 최대1회만 수행했다.
AGENTS의 실행 검증·자료 보존·재시도 기록 규칙, WORKBOARD, 프로젝트 에이전트 호출 지침과
AI 역할을 재확인했다. selector ai-model-or-runtime/rag-behavior에 따른 AI/RAG 검증은 메인이
수행했으며 제품 구현·설정·DB·인프라 변경은 제외했다. 시작/종료 WORKBOARD를 갱신했다.
API PID39268/start01:32:01, health/ready200과 기존 Chrome 마스터 인증을 확인했다.
배포version1904891a-98ff-4824-8b28-4135bef105a4의 timeout120/retry0/backoff0,
구성version89351388-8ad6-4bd3-8ea3-c25244a24100(v1/defaultfalse)를 읽기 전용 확인했다.
배포version ID를 deployment_id 조건에 사용한 첫 메타데이터 조회는0행이어서 id로 정정했고
어떠한 설정도 바꾸지 않았다. 인증정보 추출/복사나 서비스 재시작은 없었다.

제출 시각2026-10-12T18:15:15.214Z(10/13 03:15:15 KST), 기존 Chrome Swagger의 Execute를
딱1회 눌렀다. 승인된 H07 문구, 기존 합성 workspace, top_k10, experimental/diagnostics=true,
history=[]로 요청했다. 재작성용 이력과 재시도는 없다. 응답은 HTTP502,
provider_invalid_response, correlation `115182e5-d55f-49fb-b601-5a02335ede55`로 완료됐다.
같은 요청이 진행 중일 때 중복 제출·탭 이동·취소하지 않고 완료 응답을 확인했다.

읽기 전용 감사 조회 결과failed, safe_error_code=provider_invalid_response,
provider=local_openai_compatible, provider_model_id=gemma4:e2b-it-q4_K_M,
latency_ms=52291, created_at=2026-10-12T18:16:45.576525Z다. 감사의19개evidence ID를
기존 원문 단위에 결합하면 전부 예정한chunk a6713e42-5d29-4a3c-ab27-a8ab238d75cf이며
합계691문자, PDF2–3쪽이다. ‘해소 완료 여부는 아직 확인되지 않았다’ 문장이 포함돼 있다.
선택된 근거와 예산은 확인했으나 실패 응답에는 후보별 순위/점수·전체 단계 진단이 없다.

감사 latency는 pipeline.py의 generation_runtime.generate 호출 직전부터 실패 처리까지의
52.291초이며 전체 검색시간으로 바꾸어 보고하지 않는다. 제출부터 감사failed시각까지
약90.36초이나 클라이언트 클릭시각 기반 근사이고 정확한 서버 total은 미기록이다.
input/output 및 provider-reported token은null, execution_id도null이다. HTTP 응답·감사failed는
확인했으나 모델 내부 추론 완료/정상 finish를 증명하는 provider 응답·서버 기록은 확보하지 못했다.
이번 모델 추론 예산은 보수적으로 최대1회 사용으로 취급하며, 실제 내부 추론수는0~1회 미확정이다.
답변·인용은 반환되지 않았고 정확성·정상 생성 성공으로 기록하지 않는다.

기존 API stdout에동일502가 있고 stderr의Traceback/ERROR/Exception 검색 결과는없었다.
기존 dev-logs 및 설치 경로에서 이 호출을 설명하는 Ollama 로그는 확보하지 못했다.
코드상 provider_invalid_response는 HTTP/JSON/envelope/finish/schema/identity 등 여러 경계의
공통 안전 코드이므로 어느 조건인지 추측하지 않는다. 최초codex503도이번502로소급확정하지 않는다.
추가 모델/API 검색 호출·코드수정·한도/활성연결/색인/자료/서비스/보안변경·commit/push 없음.
문서 UTF-8·줄수·diff 검증만 수행하며 기존 unit통과를 이번 실모델 통과로 대체하지 않는다.
다음 후보는 원문·비공개 내부 추론을 기록하지 않는 세부 응답 단계 진단 검토이며 재호출은별도승인이다.


### 2026-10-13 제공자 응답 거부의 안전한 단계 진단

승인 범위는 기존 provider_invalid_response 경계의 진단 보완이다. 중간 위험으로 Python/AI/RAG
구현은 메인, 독립 리뷰는 provider_diagnostic_review가 맡았다. 기존 미커밋 변경을 보존하고
쓰기 직전 파일 상태를 확인했다. DB·UI·배포 변경과 실제 API/모델 호출은 제외했다.

openai_compatible.py에 고정 enum 기반 stage/reason과 정규화 correlation UUID만 기록한다.
HTTP/transport, 응답 JSON/envelope, finish, 메시지 구조, 문맥 질의, 답변 JSON/schema/계약,
근거 UUID 형식과 claim 검증 실패를 구분한다. 임의 finish_reason, 원문·프롬프트·reasoning·
인증정보·예외 문자열/traceback은 남기지 않는다. 정상 답변/정상 근거 부족에는 오류 로그가 없다.
공개 오류 코드·재시도·schema1/2 수용·finish=stop·출력/근거 한도는 유지한다.
UUID 형식 진단은 공급 근거 포함 여부의 공통 인용 검증을 대신하지 않는다.

새 test_openai_compatible_diagnostics.py는 RED26실패/2통과 후28통과했다. 기존 두 테스트의
로그 없음 기대는 고정 분류만 허용하고 canary/예외 내용이 없음을 검사하도록 변경했다.
최종 pytest는 generation의 test_openai_compatible_diagnostics, test_openai_compatible,
test_http_cancellation, test_runtime_resolver, test_context_abstention 5파일169passed(2.99초),
변경 Python 3파일 Ruff 통과. 독립 리뷰는 차단/수정요청0, 두 어댑터 테스트 파일141passed(5.90초).
Mypy는 import internal의 Windows 애플리케이션 제어 DLL 차단으로 실행 실패했고 우회하지 않았다.
전체 suite·DB/서비스 통합·실모델 검증은 미실행이다. 문서 UTF-8/줄수와 diff 검사를 수행했다.

과거 H07 실제 실패 원인은 여전히 미확정이다. 실행 중 API에 코드를 반영하지 않았고 추가
API/모델 호출·재시작·설정/색인/활성값 변경·commit/push는 없었다. ISSUE-00030의 문제 DB도
갱신하지 않았으며 종료로 처리하지 않는다. 다음 검증 후보는 별도 승인 후 기존 API에 변경을
반영하고 동일 H07/기존 비기본 Gemma v1/top_k10/history=[]/diagnostics=true 요청을 최대1회,
retry0으로 실행하여 correlation별 고정 실패 분류 또는 정상 답변/인용을 확인하는 것이다.


### 2026-10-13 사용자 재시작 후 H07 재검증 사전 확인 — 로그인 차단

AGENTS/WORKBOARD, 프로젝트 에이전트 README·호출 지침과 AI/RAG 역할, 로컬 실행 지침을
재확인했다. selector(ai-model-or-runtime/rag-behavior)는 AI/RAG 역할을 선택했다.
중간 위험의 기존 환경 검증으로 메인이 수행했고 코드·DB·인프라 수정은 제외했다.
기존 변경 상태를 읽고 문서 쓰기 전 SHA/바이트를 재확인했다. Computer Use 지침으로
기존 Chrome 연결/탭을 사용했으며 프로젝트 .agents/skills는 없었다.

API PID130960의 시작은2026-10-13T23:03:28.2245224+09:00, 새230327 stderr의 startup
완료와 /api/v1/health·/api/v1/ready200을 확인했다. 최초 /health·/ready 조회404는
잘못된 경로였고 정본/코드 경로로 정정했다. 진단 소스는03:28:36에 수정되어 새 시작보다
앞서며 고정 분류 로그 코드가 존재한다. 다만 실제 요청에서 로그 발생 여부는 미검증이다.

기존 Chrome 작업소 탭은 로그인 화면이며 비공개 작업소 링크 접근 뒤에도 로그인 화면이다.
동시에 새 API stdout의 /api/v1/auth/me401을 확인했다. 인증정보 조회/복사·대체 인증·
보호 설정 변경 없이 중단했다. H07 요청은 발송하지 않았고 이번 검색 POST0회/모델0회다.
따라서 새 요청 식별자·HTTP 검색 결과·답변/인용·진단 분류·감사 대조 결과는 없다.
과거 H07 원인을 이번 사전 확인으로 특정하지 않는다. 코드/DB/설정/활성 도메인/색인/서버
상태 변경·재시작·commit/push 없음. 기존 Chrome에 사용자가 다시 로그인하면 동일 H07과
기존 비기본 Gemma 설정의 retry0을 확인해 이미 승인된 최대1회 검증을 이어갈 수 있다.


### 2026-10-13 로그인 후 H07 단일 검증 — 답변 스키마 거부 확인

사용자의 로그인 완료 통보 후 AGENTS의 실행/보존/기록 규칙, WORKBOARD, 에이전트 호출
지침·직전 AI/RAG 역할 및 로컬 실행 기록을 재확인했다. 중간 위험의 AI/RAG 실행 검증으로
메인이 수행하며 코드·DB·인프라 수정 역할은 제외했다. 최초 로그인 탭과 별개로 기존
Chrome441323440에 마스터 로그인 세션이 확인돼 같은 탭/쿠키의 Swagger를 사용했다.
추가 로그인·인증정보 추출/복사 없이 진행했다. PID130960은 그대로였고 진단 소스 SHA는
709b4c3caa8f85ba624668b5ed146764f5a581e094fd79c3ebb4ea059602b4d8로 확인했다.

읽기 전용 DB 트랜잭션에서 기존 비기본 구성v1(89351388-8ad6-4bd3-8ea3-c25244a24100),
생성프로파일a07c2838-49d8-4241-b56a-e5b2a0004748과 배포1904891a-98ff-4824-8b28-4135bef105a4
연결, local_openai_compatible/gemma4:e2b-it-q4_K_M, timeout120/retry0/backoff0/externalfalse를
확인했다. 생성 설정은 nested generation의 output512/temperature0/schema2다. 처음 top-level
키 조회의null은 저장 구조 차이였고 nested 키로 정정 확인했다. 설정 쓰기는 하지 않았다.

제출은2026-10-13T14:18:10.933Z(23:18:10 KST)에 기존 H07 문구·configuration_id
428992ab-697d-4604-9f6f-7b64f063e71f·기존 합성 workspace2292dfa0-3af8-4494-a8ce-da03ef2aa6ed,
folder_ids=[]/top_k10/experimental=true/include_diagnostics=true/history=[]로 Execute1회다.
진행 중 중복 제출·취소 없이 기다렸고 HTTP502 완료를 확인했다. 응답과 헤더의 요청ID는
c7bbe76b-4dc3-4cef-bfa7-8f231afc7bed, 공개 오류는provider_invalid_response이며 답변/인용은없다.

새230327 API stderr에는 동일ID의 고정 로그가 정확히 기록됐다:
`provider_response_rejected stage=answer_schema reason=invalid correlation_id=c7bbe76b-4dc3-4cef-bfa7-8f231afc7bed`.
stdout의 검색POST502와 DB 감사failed/safe_error_code도 일치한다. 감사created_at은
2026-10-13T14:20:02.131938Z, 생성 구간latency_ms60423이다. 클릭→감사 약111.20초는
클라이언트 기반 근사이며 정확한 서버 전체 시간이나 모델 토큰 속도로 해석하지 않는다.
선택근거는 이전과 같은chunk a6713e42-5d29-4a3c-ab27-a8ab238d75cf의19단위/691자/PDF2–3쪽이다.
입출력 및 provider-reported tokens와 execution_id는null이다. 원문/프롬프트/reasoning/
인증정보를 로그에 추가하거나 제공자 원문 응답을 수집하지 않았다.

이번 요청의 직접 거부 지점은 schema2 답변 스키마 검증이다. 코드 순서상 HTTP envelope,
finish=stop, 메시지 구조와 답변 JSON 해석 이후이며 timeout/finish.length 실패가 아니다.
다만 누락·잘못된 타입·추가 필드 중 무엇인지는 고정 분류만으로 구별할 수 없다. 이번 원인을
과거 H07/최초503에 소급 확정하지 않는다. 최소 후속 방향은 값 없는 고정 schema 오류
하위 분류를 mock으로 보완하고 확인된 계약 불일치만 수정하는 것이다. 스키마 완화·출력
예산 확대·임의 모델 전환은 제안된 최소 수정에 포함하지 않는다.

이번 검색POST는1회이며 history없음/retry0의 내부 생성 최대1회 예산으로 종료했다.
추가 실제 호출은없다. 코드·DB 수동쓰기·설정·활성 도메인·색인·서버상태·commit/push는
변경하지 않았다. 승인된 검색이 남긴 정상 감사 기록과 읽기 전용 대조를 DB 수정 작업과
구분한다. ISSUE-00030은 닫지 않았고 문제 DB도 편집하지 않았다. WORKBOARD와 본 기록만
최소 갱신하고 UTF-8/줄수/diff 검사를 수행했다. 새 unit/static 검사는 코드 불변으로 미실행이다.


### 2026-10-13 answer_schema 고정 하위 분류와 요청 계약 대조

승인된 최소 진단 범위로 TDD/systematic-debugging/완료 전 검증 지침을 적용했다.
selector의 Python/AI/RAG 구현은 메인, 독립 리뷰는 schema_diagnostic_review가 맡았다.
기존 source SHA709b4c3c…와 테스트 SHA를 확인해 이전 미커밋 변경을 보존했다.
openai_compatible.py에 ValidationError의 library type만 allowlist로 매핑하는 분류를 추가했다.
고정 reason은 missing/type/extra_fields/literal/constraint/mixed이며 알 수 없는 오류는invalid다.
여러 같은 유형은 같은 분류로, 서로 다른 유형은mixed로1회 기록한다. errors()에서 input/
context/url을 제외하고 loc/msg·자유 필드명·값을 로그로 전달하지 않는다. 기존 strict 모델,
finish=stop·상태/claim/UUID 검증·공개 오류·재시도·요청 본문·출력 예산은 변경하지 않았다.

진단 테스트에 root/nested 누락·타입·추가키·boolean·null·허용값·빈 인용배열·복합 오류17건,
알 수 없는 custom error의 코드/loc/msg/input/context canary 미노출1건, 요청 계약 대조2건을
추가했다. 최종 RED18실패/30통과(하위분류 미구현) 후 관련5파일189passed(5.35초)다.
5파일은 test_openai_compatible_diagnostics/test_openai_compatible/test_http_cancellation/
test_runtime_resolver/test_context_abstention이며 모두 mock/unit이다. 기존 로그 기대도
extra_fields로 좁혔다. Ruff3파일 통과, Mypy(--cache-dir=nul --follow-imports=silent
--no-incremental) 변경 소스1파일 통과. 이전 native DLL 차단은 이번 실행에서 재현되지
않았으며 정책·설치·로더 변경은 없었다. 독립 리뷰는 두 파일161passed(5.53초), 수정요청0.

요청/검증 대조: response_format은json_object만 전달하며 전체 JSON Schema는 보내지 않는다.
schema2 system JSON 예시의 schema_version/status/claims와text/evidence_ids, 정상/근거부족
조건·추가키 금지 안내는 로컬 검증과 일치한다. 허용된 두 상태를 mock에서 검증했고 스키마
위반은 성공 처리하지 않는다. 제공자의 JSON 객체 생성 요구와 로컬의 엄격한 스키마 검증
사이에 강제 수준 차이는 있지만, 모순된 스키마 전송이나 H07의 구체적 필드 오류를 증명한
것은 아니다. 기본 프롬프트의 evidence_id라는 개념 설명도 실제 단수 키 생성의 증거가 아니다.

H07 실제 하위원인은 여전히 미확정이고 이번 진단은 실행 중 API에 반영하지 않았다.
추가 API/모델·DB 호출0회, 설정/색인/서버/보안/commit/push 변경 없음. 코드 수정은 어댑터와
기존 테스트2파일뿐이며 기록은 WORKBOARD와 본 문서만 갱신했다. 문서 UTF-8/줄수/diff 검사
통과. 전체 suite·DB 통합·실모델 재검증은 미실행이다. 다음은 별도 승인 후 변경 반영과
한정 실제 검증 후보이며, 과거 호출 승인 예산을 재사용하지 않는다. ISSUE-00030은 유지한다.


### 2026-10-13 최신 진단 반영 후 H07 추가1회 — 복합 스키마 오류

이번 사용자 재시작/추가1회 승인에 따라 AGENTS·WORKBOARD·에이전트 호출·실행 지침을
재확인했다. selector AI/RAG 역할의 중간 위험 실행 검증으로 수행하며 구현·DB·인프라
변경은 제외했다. API PID101724 시작2026-10-13T23:40:14.3751359+09:00, startup완료와
health/ready200을 확인했다. 진단 소스는23:32:07에 저장됐고 SHA는
b420d93ae179d6de7b5347fb90cbffc39d8b33dbaaa6743cc02d9b558cbf8a66이다.
기존 Chrome의 오래된 로그인 화면을 보호된 작업소 URL로 새로 열어 기존 쿠키의 마스터
접근을 확인했다. 추가 로그인·인증정보 추출은 없었다. 읽기 전용 DB로 이전과 같은 비기본
Gemma v1/생성프로파일/배포와 timeout120/retry0/backoff0, output512/temperature0/schema2,
externalfalse를 확인했다. 기존 Swagger 폼의 동일 H07 문구·구성·공간·history=[]를 사용했다.

2026-10-13T14:47:20.484Z(23:47:20 KST) Execute를1회 눌렀으며 중복 제출·취소 없이
완료까지 기다렸다. 새 응답/헤더 요청ID는71f56230-8d67-41b2-b2ea-88109bc7cc0e,
HTTP502/provider_invalid_response다. 이전 화면의c7bbe76b…응답과 새 응답을 구분했다.
새234013 stderr의 동일ID 로그는 `stage=answer_schema reason=mixed`이며 stdout에는
검색POST502가1건 있다. 새 분류가 실제 API에서 작동함을 확인했다.

같은 요청의 DB 감사는failed/provider_invalid_response, 생성 구간latency_ms55103,
created_at2026-10-13T14:48:58.681759Z다. 클릭→감사 약98.20초는 근사이며 서버 전체
계측값이 아니다. 근거는 직전과 같은chunk a6713e42-5d29-4a3c-ab27-a8ab238d75cf의
19단위/691자/PDF2–3쪽이다. input/output/provider-reported tokens와execution_id는null,
답변·인용은 반환되지 않았다. 원문 응답·값·필드명·reasoning·인증정보는 추가 기록하지 않았다.

코드상 서로 다른 고정 schema 오류 분류가2종 이상이면mixed이므로 복합 오류까지 확인했다.
정확한 분류 조합과 필드 원인은 현재 로그에 없다. 이를 누락+추가키 등의 특정 조합으로
추정하거나 과거 실패 원인으로 소급 확정하지 않는다. 최소 후속 방향은 mixed로 합치기
전의 고정 enum 집합을 값/필드명 없이 한정 출력하도록 mock으로 보완하는 것이다.
엄격한 거부·스키마·예산은 유지하며, 이번에는 추가 제품 수정이나 실제 호출을 하지 않았다.

이번 새 승인 예산은 검색POST1회/history없음/retry0의 내부 생성 최대1회로 종료했다.
코드·설정·DB 수동쓰기·색인·활성 도메인·서버상태·재시작·commit/push 변경없음.
정상 검색 감사 쓰기와 읽기 전용 대조를 별도 DB 변경 작업과 구분한다. ISSUE-00030은
종료/편집하지 않았다. WORKBOARD와 본 기록만 쓰기 전 바이트 재확인 후 갱신했고
UTF-8/줄수/diff 검사를 수행했다. 코드 불변으로 unit/static 재실행은 하지 않았다.


### 2026-10-13 복합 스키마 진단 보완 및 structured outputs 최소 변경안

사용자 요청에 따라 추가 실제 API/모델 호출·재시작을 중단한 상태에서 진행했다. 마지막 H07의 `answer_schema.mixed`는 서로 다른 분류가 있다는 증거이며, 당시 정확한 조합/경로는 소급 식별할 수 없다. 기존 원문·계정·구성·DB·서비스·기본값과 미커밋 작업은 보존했다.

- 작업 등급: Python/AI 런타임의 한정된 진단 수정. 주요 위험은 로그의 비공개 값 유출 및 기존 거절 계약 변화다. Python backend·AI engineer·RAG lead 책임을 메인이 맡고 independent code reviewer를 별도 실행했다. UI/인프라 역할은 변경이 없어 제외했다.
- `openai_compatible.py`: 기존 stage/reason/request UUID를 유지하면서 schema2 검증 오류에만 `categories`와 `fields`를 추가했다. 분류6개(`constraint,extra_fields,invalid,literal,missing,type`)와 경로11개의 닫힌 enum에서 정렬·중복 제거한 전체 집합이다. 최대66쌍으로 입력 오류 수와 무관하게 제한되며 분류를 임의로 잘라내지 않는다. 호환용 `reason=mixed`에도 모든 분류가 함께 남는다.
- 고정 경로: `root`, `schema_version`, `status`, `claims`, `claims.item`, `claims.item.text`, `claims.item.evidence_ids`, `claims.item.evidence_ids.item`, `root.extra`, `claims.item.extra`, `unknown`. 알려진 전체 loc 구조만 대응시키고 숫자 인덱스/임의 키는 출력하지 않는다. 추가 키는 부모의 고정 extra 경로, 미지의 loc/코드는 unknown/invalid로만 기록한다. 원문·값·자유 필드명·reasoning·인증·ValidationError 텍스트/traceback은 기록하지 않는다.
- 합성 복합 예: `categories=extra_fields,missing fields=extra_fields:root.extra,missing:status`. 이는 mock 예시이며 H07의 실제 오류 조합을 뜻하지 않는다.
- 응답 수용, 공개 `provider_invalid_response`/retryable=false, 재시도, 종료 상태, 예산 및 실제 `response_format=json_object` 전송은 그대로다. 검증 기준을 완화하거나 자동 대체하지 않았다.

#### 설치 버전 및 공식 지원 조사 — 실제 요청 없음

`C:\AI\Ollama\ollama.exe`를 실행하지 않고 정적으로 읽었다. PE FileVersion/ProductVersion은 비어 있으나 내장 버전 문자열 `0.40.3`, Go build revision `eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21`, vcs.modified=false가 [공식 v0.40.3 릴리스](https://github.com/ollama/ollama/releases/tag/v0.40.3)의 revision과 일치한다. 설치 파일 SHA-256은 `539b92d2bfac33e553366e365110b7a9c69070ef5ec1703ea0e7789e2283d9d1`이다. 실행 중 서버의 버전/로드 모델은 이번에 API로 재조회하지 않았다.

[공식 structured outputs 문서](https://docs.ollama.com/capabilities/structured-outputs)는 native `format`의 JSON Schema와 OpenAI 호환 `response_format` 지원 및 Pydantic 스키마 생성을 안내한다. [v0.40.3 OpenAI 변환 소스](https://github.com/ollama/ollama/blob/v0.40.3/openai/openai.go#L728-L739)는 `json_object`를 일반 JSON 형식으로, `json_schema`의 `json_schema.schema`를 native Format으로 변환한다. 이 버전의 JsonSchema 구조체에는 schema만 있으므로 `strict:true`에 별도 강제 의미가 있다고 가정하지 않는다. [해당 runner 소스](https://github.com/ollama/ollama/blob/v0.40.3/llm/llama_server.go#L2255-L2280)는 스키마 객체를 runner에 전달하며 파일 서두는 grammar 기반 처리를 설명한다. 이 소스 경로 확인은 설치 GGUF의 모든 schema 키워드/추론 모드와 실제 성공을 검증한 결과는 아니다.

로컬 모델 정의의 `model_json_schema()`를 네트워크 없이 확인했다. `_AnswerV2`는 object/required/additionalProperties=false, status enum, claims array, `$defs`/`$ref`의 `_ClaimV2`, evidence_ids의 minItems=1을 내보낸다. `_QueryV2`는 required resolved_query string과 additionalProperties=false다. 현재 mock 전송 검증은 실제 adapter가 여전히 `json_object`를 보내는 차이를 확인한다. JSON Schema를 받는 실제 Ollama나 grammar 컴파일을 mock 통과로 대체해 주장하지 않는다.

#### 제안만 한 최소 변경 — 이번에는 제품 동작 미변경

기존 `_chat_completion`의 dialect/schema version/contextualize 분기에서 **Ollama + schema2에 한해** 다음 response_format을 선택한다. 새 provider/프로파일/설치/설정 없이 기존 모델 정의를 스키마 정본으로 사용한다.

```python
response_format = {
    "type": "json_schema",
    "json_schema": {
        "schema": (_QueryV2 if contextualize else _AnswerV2).model_json_schema(),
    },
}
```

OpenAI dialect와 schema1은 기존 형식을 유지한다. 한정된 분기 변경과 mock 요청/격리/거절 회귀가 최소 구현 범위다. 승인 후 구현할 때 해당 ADR의 wire 계약 설명도 함께 갱신해야 한다. 이번 수정 문서는 기존 WORKBOARD와 본 worklog뿐이다.

생성 스키마만으로 모든 업무 조건을 대체할 수 없다. 현재 schema_version은 integer이며 값2, status와 claims 유무의 관계, 공백 claim, 유효 UUID, 제공 근거 소속/권한/인용은 로컬 후검증으로 계속 강제한다. `$defs`/`$ref`와 각 키워드의 설치 runner 호환, reasoning과 grammar의 실제 상호작용, 512토큰에서 정상 종료 및 H07 품질은 아직 미확인이다. 지원 실패 시 json_object/다른 모델로 조용히 fallback하지 않는다. 구체 오류는 새 안전 진단으로 확인한다.

#### 검증 및 남은 조건

- TDD RED: 새 분류/경로 테스트13개를 먼저 추가한 진단 파일 실행 → **13 failed, 48 passed**. 실패는 진단 suffix 부재였다.
- GREEN: openai_compatible·diagnostics·http_cancellation·runtime_resolver·context_abstention 5파일 → **203 passed in 2.64s**(최종 타입 선언 반영 후 재실행). 1000개 반복 claim, 6000개 합성 오류/역순, 알려진 경로·미지 loc·복합 분류·비밀 canary·공개 오류 및 기존 wire 계약을 검사했다.
- Ruff 변경3파일 `--no-cache` 통과. Mypy 변경 source1개 `--cache-dir=nul --follow-imports=silent --no-incremental`는 첫 실행의 사전 키 타입 오류를 명시적 타입 선언으로 수정한 뒤 **통과**했다. 정책 변경/대체 로더 없이 실행했으며 이전 DLL 차단 이력은 보존한다.
- 독립 리뷰: 최초2파일174통과 후 최종 타입 선언/추가 상한 테스트까지 재검토, **175 passed in 2.96s**, severity 있는 결함 없음. 메인의 구현 책임과 분리했다.
- 실제 API/모델 호출, 브라우저 재시험, 서비스 재시작, 모델 설치, 설정/DB/마이그레이션/기본값 변경, commit/push는 **미실행**. 새 진단의 실행 API 반영은 미확인이다. 실제 H07 성공·RAG 마감 완료로 표시하지 않는다.

후속 실제 시험은 설계/최소 구현과 배포 반영이 별도 승인·검증된 뒤 **H07 한 번, retry0, history=[]**로 한정한다. 사전에는 로드 코드/SHA와 실행 버전, 실제 json_schema 분기, 기존 구성 `428992ab-697d-4604-9f6f-7b64f063e71f`·버전 `89351388-8ad6-4bd3-8ea3-c25244a24100`, generation profile `a07c2838-49d8-4241-b56a-e5b2a0004748`, deployment version `1904891a-98ff-4824-8b28-4135bef105a4` 및 timeout120/출력512/temperature0을 확인한다. 원래 H07 질문·workspace·top_k10과 근거 집합을 유지한다. 한 request UUID로 HTTP/finish/감사 terminal/latency·가용 token 계측을 맞추고 실패하면 전체 categories/fields를 수집한다. 성공하면 schema2·근거부족 상태의 적절성·인용/원문 위치를 확인한다. 근거가 달라지면 동등 비교로 판정하지 않고, 결과와 무관하게 자동 재시험 없이 멈춘다.


### 2026-10-13 승인된 Ollama schema2 JSON Schema 전달 구현

직전 최소 변경안을 검토한 사용자가 구현을 승인했다. 이번 문서 수정은 명시된 기존 WORKBOARD와 본 작업 기록에만 한정한다. 앞 절의 ADR 갱신 제안은 이후 사용자가 지정한 문서 범위에 따라 이번에 실행하지 않았다. 실제 API/모델 호출·재시작·설정/DB/색인/활성 도메인 변경·설치·권한 확대·commit/push는 하지 않았다. 기존 미커밋 파일을 기준으로 범위를 비교하고 쓰기 직전 해시를 재확인했다. 지원 도구에 다른 로컬 ai-workshop 작업은 notLoaded였으며 다른 작업 파일을 정리/이동하지 않았다.

- 범위/역할: Python/AI 런타임의 한정된 요청 형식 수정. dialect 격리 및 거절/정보 비노출 계약이 주요 위험이다. selector의 Python backend·AI engineer·RAG lead·test designer 책임은 메인, integration-e2e-verifier(허용된 mock 경계)·independent-code-reviewer는 별도 읽기 전용 에이전트로 분리했다. UI·DB·인프라는 변경이 없어 제외했다.
- 제품 변경은 `_chat_completion`의 **5줄**이다. 명시적 Ollama + schema2에서 생성은 `_AnswerV2`, 문맥화는 `_QueryV2`의 `model_json_schema()`를 `response_format={"type":"json_schema","json_schema":{"schema":...}}`에 넣는다. 기존 Pydantic 정의가 유일한 스키마 정본이며 복제 스키마/새 설정/프로파일은 없다.
- schema1과 openai dialect는 기존 json_object를 유지한다. 모델·temperature·출력 상한·문맥화 reasoning_effort·finish/엄격 JSON/버전2·status와 claims 관계·UUID·인용 및 전체 고정 오류 진단은 변경하지 않는다. provider가 스키마를 거절하면 기존 안전한 오류로 거부하며 json_object나 다른 모델로 fallback하지 않는다.
- 지원 근거는 위 정적 조사와 [Ollama v0.40.3 공식 변환 소스](https://github.com/ollama/ollama/blob/v0.40.3/openai/openai.go#L728-L739)다. 스키마를 native Format으로 전달하는 경로가 확인됐으며, 별도 strict 플래그는 덧붙이지 않았다. 설치 모델의 실제 grammar/keyword 지원·reasoning 상호작용·512토큰 정상 종료는 mock 검증 범위가 아니다.

검증은 실제 실행 결과만 아래에 기록한다.

- TDD RED: 제품 수정 전 신규 wire/실패 경계 테스트와 기존 wire 기대 갱신 → **6 failed, 179 passed**. 실패 이유는 json_object 전송으로 JSON Schema가 없다는 것이었다.
- GREEN: 해당 2파일 **185 passed**. 최종 관련 6파일(HTTP 어댑터·진단·HTTP 취소·runtime resolver·context abstention·citation validation) → **249 passed in 6.38s**. generate/contextualize × schema1/2 × openai/ollama 매트릭스, 정상/근거 부족, HTTP400 스키마 거부 시 max_retries2에서도 1회·fallback 없음·비밀 비노출, 복합 오류/로컬 후검증 및 인용 경계를 확인했다.
- Ruff 변경3파일은 첫 검사 E501 한 건을 테스트 줄바꿈으로 고친 뒤 **통과**. Mypy 제품1파일 **통과**. 제품 diff는 직전 작업 baseline 대비 위 분기5줄뿐임을 비교 확인했다. 전체 pytest는 실행하지 않았으며 로컬 runbook의 실사용 DB 격리 제한을 준수했다.

```powershell
backend/.venv/Scripts/python.exe -B -m pytest -c backend/pyproject.toml backend/tests/unit/labs/rag/generation/test_openai_compatible.py backend/tests/unit/labs/rag/generation/test_openai_compatible_diagnostics.py backend/tests/unit/labs/rag/generation/test_http_cancellation.py backend/tests/unit/labs/rag/generation/test_runtime_resolver.py backend/tests/unit/labs/rag/generation/test_context_abstention.py backend/tests/unit/labs/rag/generation/test_citation_validation.py -q --tb=short
backend/.venv/Scripts/python.exe -B -m ruff check --no-cache backend/src/ai_workshop/labs/rag/generation/openai_compatible.py backend/tests/unit/labs/rag/generation/test_openai_compatible.py backend/tests/unit/labs/rag/generation/test_openai_compatible_diagnostics.py
backend/.venv/Scripts/python.exe -B -m mypy --config-file backend/pyproject.toml --cache-dir=nul --follow-imports=silent --no-incremental backend/src/ai_workshop/labs/rag/generation/openai_compatible.py
```

변경 source SHA-256: `ca694770526fffcbda47d47d033484e024ffe72a08a5eb15867d0376152ecca1`. 실행 API가 이 코드를 로드했는지는 미확인이다. 실제 H07 한 번 시험은 **추가 승인과 재시작/로드 확인을 기다리며**, 바로 위 체크리스트의 동일 구성·retry0·history=[]·요청 UUID/감사/안전 진단 대조 조건을 유지한다. 이번 mock 성공을 H07 해결이나 RAG 운영 수용으로 표시하지 않는다.

독립 최종 리뷰: 지정 mock5파일 **213 passed in 6.22s**, 종료코드0, 차단·비차단 코드 결함 없음. 위 source SHA를 확인했고 실제 접근/수정 없이 구현 책임과 분리해 검토했다. 최종 Ruff·Mypy·diff 공백 검사와 WORKBOARD135줄/최근 완료5개 제한을 확인했다.


### 2026-10-14 JSON Schema 반영 재시작 후 H07 단1회 — 업무 계약 거부

사용자의 재시작 완료 통보와 동일 H07 최대1회 승인에 따라 본래 BOMI 환경을 확인했다. 중간 위험의 AI/RAG 실행 검증을 메인이 맡았으며 코드·DB·인프라 수정 역할은 제외했다. Computer Use로 기존 Chrome 로그인 세션/탭을 사용하고 새 로그인·credential 추출·권한 변경은 하지 않았다. 문서만 쓰기 전 현재 바이트/SHA와 대조했다.

API PID51504는 `C:\projects\ai-workshop`에서 기존 backend venv의 `-m uvicorn ai_workshop.main:app`로 실행 중이며 시작 시각은2026-10-14T00:24:44.4080342+09:00이다. 검증된 소스 SHA `ca694770526fffcbda47d47d033484e024ffe72a08a5eb15867d0376152ecca1`은 그대로이고 마지막 수정은 시작보다 앞선2026-10-13T15:17:48Z다. 새002443 stderr의 startup 완료·PID, health/ready 각200, Chrome 작업소 새로고침 후 기존 마스터 세션을 확인했다. 프로세스/소스 경로·수정시각으로 최신 코드 반영 조건을 확인했으며 provider 원문 wire를 별도 수집하지 않았다. TCP 소유 조회는 Windows 접근 거부였고 승격하지 않았다.

읽기 전용 DB 트랜잭션으로 기존 비기본 구성v1·생성 프로파일·배포 연결과 local_openai_compatible/gemma4:e2b-it-q4_K_M, 명시적 ollama dialect/loopback endpoint, schema2·출력512·temperature0·timeout120·retry0·backoff0·externalfalse를 재확인했다. 초기 async DB 조회는 Windows Proactor 호환 오류로 연결 전 실패하여 동일 설정의 동기 READ ONLY 조회로 확인했으며 DB/설정 쓰기는 없었다.

기존 Chrome Swagger에서2026-10-13T15:32:36.859Z(10/14 00:32:36 KST)에 기존 H07 문구·configuration_id `428992ab-697d-4604-9f6f-7b64f063e71f`·workspace `2292dfa0-3af8-4494-a8ce-da03ef2aa6ed`·folder_ids=[]·top_k10·experimental/include_diagnostics=true·history=[]로 Execute를 **한 번** 눌렀다. 중복 제출·취소·재시도 없이 완료를 기다렸다.

- HTTP **502 provider_invalid_response**. 본문/헤더 요청 UUID **`3a9683f5-5609-4f2d-9646-8e79d1d4acd5`**가 감사 failed/safe_error_code와 일치한다. 새002443 stdout의 검색 POST는1개이며502다.
- 같은 UUID의 안전 진단 전체는 `stage=answer_contract reason=invalid`이다. 이번 경로는 Pydantic ValidationError가 아니므로 schema 분류/경로 집합(categories/fields)은 발생하지 않았다. 원문·값·임의 필드명·reasoning·인증정보를 추가 수집하거나 로그하지 않았다.
- 감사 configuration version `89351388-8ad6-4bd3-8ea3-c25244a24100`, generation profile `a07c2838-49d8-4241-b56a-e5b2a0004748`, deployment version `1904891a-98ff-4824-8b28-4135bef105a4`가 사전 확인과 일치한다. 생성 구간 latency는 **56,196ms**, 감사 시각은2026-10-13T15:34:14.200394Z다. 클릭→감사 약97.34초는 클라이언트 기반 근사이며 정확한 서버 total/토큰 속도가 아니다. input/output/provider-reported token과 execution_id는null이다.
- 선택 근거는 이전 UUID `71f56230-8d67-41b2-b2ea-88109bc7cc0e`와 **ID 순서까지 동일한19단위·691자**다. chunk `a6713e42-5d29-4a3c-ab27-a8ab238d75cf`, PDF2–3쪽이다. 본문 대신 집계와 식별자만 조회했다.
- 응답에 답변·인용이 없어 유효성/정확성 통과로 판정할 수 없다. 고정 H07 정답은 **2026-09-03 발행 시점 해소 완료 여부 미확인**이며 결과는 기대 답변을 제공하지 못했다. 이 정답표는 모델 입력에 추가하지 않았다.

현재 schema2 코드 경로상 HTTP 응답/finish=stop/메시지/엄격 JSON/Pydantic 구조 검증 이후의 업무 불변식에서 거부됐다. 가능한 조건은 **schema_version 값이2가 아님** 또는 **status와 claims 유무 불일치**(둘 다일 가능성 포함)다. 현 고정 로그는 둘을 구별하지 않으므로 특정 값이나 한 조건을 원인으로 단정하지 않는다. 이전 answer_schema.mixed와 이번 answer_contract.invalid는 서로 다른 거부 단계이며, 과거 오류 조합을 소급 추정하거나 JSON Schema가 모든 업무 조건을 강제한다고 주장하지 않는다.

이번 승인 예산은 검색POST1회/history=[]/내부 retry0으로 종료했다. 새 코드·설정·DB 수동쓰기·색인·활성 도메인·서버 변경·추가 호출·commit/push 없음. 승인된 검색이 자동으로 남긴 감사 기록은 별도 DB 수정 작업이 아니다. 새 unit/static 검증은 코드 불변으로 실행하지 않았다. 기존 WORKBOARD와 본 기록의 UTF-8·공백·줄수 검사를 수행한다. ISSUE-00030은 닫거나 편집하지 않는다.

다음 최소 후보는 **실제 호출 없이** version/status-claims 두 불변식의 값 없는 고정 진단을 분리하는 mock 보완과, 같은 업무 조건을 전송 스키마에 표현할 최소 변경안 검토다. 로컬 거절·인용 검증은 유지하고 응답값을 추측해 보정하지 않는다. 이번에는 구현하지 않았으며 추가 실제 검증도 하지 않고 중단한다. RAG 전체 완료나 H07 해결로 일반화하지 않는다.


### 2026-10-14 답변 업무 계약의 전송 제약·진단 정합화 — mock 완료

추가 개발 요청에 따라 실제 호출 없이 기존 version2/status-claims 업무 계약을 전송 스키마·프롬프트와 맞췄다. 중간 위험의 Python/AI/RAG 기능 보완으로 메인이 구현·테스트 설계를 담당하고 독립 코드 리뷰·mock 검증을 분리했다. DB/인프라·프론트엔드·보안 역할은 범위 밖이라 제외했다. 시작본5파일/SHA를 `.local-data/project-agent-work/answer-v2-contract-20261014/`에 보존하고 쓰기 전 재대조했다. 다른 작업은 완료 상태였고 기존 미커밋 변경을 유지했다. 문서는 사용자 지정 기존 WORKBOARD와 본 worklog만 갱신했다.

기존 전송 스키마에는 schema_version의 integer 타입만 있고 값2 제약이 없었으며, 두 status와 claims 배열의 관계도 없었다. 로컬 검사에만 있던 다음 세 조건을 하나의 불변 규칙에서 전송 스키마·Ollama schema2 생성 프롬프트·로컬 검사로 적용한다.

| 계약 | 전송 JSON Schema | 고정 위반 코드 |
|---|---|---|
| schema_version은 정수2 | 각 객체의 schema_version에 type integer + const2 | schema_version |
| answered는 claim1개 이상 | status const answered + claims minItems1 | answered_without_claims |
| insufficient_evidence는 claim0개 | status const insufficient_evidence + claims minItems0/maxItems0 | insufficient_with_claims |

Pydantic의 기존 필드/$defs를 복제한 완전한 객체 두 가지를 root anyOf로 표현한다. required·extra forbid·evidence_ids 최소1개는 보존한다. 추가 안내는 명시적 Ollama+schema2의 generate에만 붙이며 generic OpenAI/schema1 요청·문맥화 계약은 그대로다. 로컬 strict 타입 검사 뒤 업무 조건을 검사하는 순서와 공개 provider_invalid_response/retryable=false를 유지한다. 로컬에서는 float2.0·bool·문자열2도 계속 거부한다. JSON Schema의 수학적 integer 의미가 Python strict int와 완전히 같다고 주장하지 않는다. 응답 보정·claim 생성·재시도·fallback은 추가하지 않았다.

`answer_contract.invalid`에 `violations=`의 정렬·중복 제거된 고정 코드 집합을 덧붙인다. 값2 위반과 상태 관계 위반이 함께 있으면 둘 다 남는다. 세 코드의 닫힌 집합이고 정상 구조에서는 최대2개가 동시에 발생한다. 원문/값/임의 필드명/reasoning/credential은 로그하지 않는다. 기존 schema 오류 categories/fields와 UUID 정규화도 보존한다. 이 새 진단은 과거 UUID의 실제 오류값을 소급 밝혀주지 않는다.

공식 근거와 확인 범위:
- [Ollama v0.40.3 runner](https://github.com/ollama/ollama/blob/v0.40.3/llm/llama_server.go)는 JSON Schema를 llama-server에 전달하는 경로를 설명한다. 설치 runner의 세부 revision/동작을 이 소스만으로 확정하지 않는다.
- [llama.cpp 공식 변환 문서](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md#json-schemas--gbnf)는 properties/anyOf를 같은 수준에 섞는 방식과 if/then/else의 제한, 스키마가 프롬프트에 주입되지 않는 점을 명시한다. 그래서 full-object anyOf와 명시적 프롬프트를 사용한다.
- [upstream 변환 코드](https://github.com/ggml-org/llama.cpp/blob/master/common/json-schema-to-grammar.cpp)의 ANY_OF/CONST/ARRAY와 max_items0 분기를 확인했다. 이는 조회 시점 master의 지원 근거이며 설치 바이너리의 grammar 실행 증거가 아니다. 실제 grammar 컴파일·모델 호출은 하지 않았다.
- [Pydantic json_schema_extra callable](https://docs.pydantic.dev/latest/concepts/json_schema/#using-json_schema_extra-with-a-callable)을 통해 구조 스키마에 업무 조건을 보완했다.

TDD: 제품 변경 전 **37 failed / 192 passed**로 스키마 제약·추가 프롬프트·복합 진단 누락을 재현했다. 첫 구현 편집에서 CRLF 문맥 치환 누락으로 실패127건이 발생해 수정했고, 이어 테스트의 근거부족 결과 기대값을 기존 generation=None 계약에 맞췄다. 최종 관련2파일 **229 passed in6.48s**. 위 이전 섹션과 동일한 명시적6파일 pytest 명령을 다시 실행해 **293 passed in5.60s**, Ruff3파일·Mypy1소스 모두 종료0이다. 전체 pytest/실사용 DB 통합 테스트는 실행하지 않았다.

별도 오프라인 검증: 이미 설치된 frontend AJV6.15.0을 사용해 생성 스키마를 compile하고 버전×상태×claim수 및 필드 위반 합성 **44개**를 모두 검증했다(coerceTypes=false/removeAdditional=false, 설치·네트워크 없음). 입력은 작업 증거 폴더의 schema-cases.json이다. 이는 JSON Schema 의미 검증이며 Ollama grammar 호환성 검증은 아니다.

독립 검토자는 지정 mock5파일 **257 passed in6.04s**, baseline/현재 `_safe_generation` 합성 **176조합**의 수용·거부/반환값 동일성, 내부 ref2개 해소 및 스키마 생성10회 동일성을 확인했다. 심각도 있는 결함 없음. 직접 API/DB/모델 접근이나 파일 수정 없이 검토했다. 검토·테스트한 source SHA-256: `5257cc6efb8e68f4ea66da9aaec7fd1a3ebb496c2dddbc70c36701a3ea48c485`.

실제 API/모델 호출·재시작·환경/DB/색인/활성 도메인 변경·설치·권한 변경·commit/push 없음. 현재 API의 새 코드 로드는 확인하지 않았다. 기존 실제 호출 예산은 소진됐으므로 다음 후보는 별도 승인 후 최신 코드 로드 확인 및 동일 H07 단1회 검증이다. ISSUE-00030/ISSUE-00013 및 전체 RAG 운영 수용을 완료 처리하지 않았다.


### 2026-10-14 계약 보완 반영 후 H07 단1회 — 정상 근거부족 응답

사용자의 백엔드 재시작 통보와 동일 H07 최대1회 추가 승인으로 본래 BOMI/기존 Chrome 세션에서 검증했다. 중간 위험의 RAG 실행 검증을 메인이 맡고 코드/DB/인프라/보안 수정 역할은 제외했다. WORKBOARD 시작 상태를 갱신하고 종료 쓰기 전 문서 바이트/SHA를 재확인했다.

API 서버 PID129484는 기존 backend venv로 `ai_workshop.main:app`, cwd `C:\projects\ai-workshop`, loopback18000에서 실행 중이다. 프로세스 시작은2026-10-13T15:54:29.765528Z(10/14 00:54:29 KST), 소스 수정은15:48:03.616488Z이며 검토된 SHA `5257cc6efb8e68f4ea66da9aaec7fd1a3ebb496c2dddbc70c36701a3ea48c485`가 그대로다. 새005429 stderr의 startup 완료를 확인했다. `/api/v1/health`·`/api/v1/ready`는 각200, Chrome 작업소 새로고침 후 기존 마스터 인증이 유지됐다. 초기 잘못된 `/health`·`/ready` 조회는404였고 정식 경로로 확인했다.

읽기 전용 DB 트랜잭션(`transaction_read_only=on`)에서 기존 비기본 구성v1, profile `a07c2838-49d8-4241-b56a-e5b2a0004748`와 deployment `1904891a-98ff-4824-8b28-4135bef105a4`의 연결, local_openai_compatible/gemma4:e2b-it-q4_K_M·local/externalfalse·timeout120·retry0/backoff0를 확인했다. 기존 endpoint의 명시적 ollama dialect와 schema2·max_output512·temperature0도 일치한다. 동일 소스가 생성하는 스키마의 version const2, answered minItems1, insufficient_evidence minItems0/maxItems0를 읽기 전용으로 재확인했다. 재시작 순서·실행 경로·설정과 코드 분기로 이번 요청의 전송 제약 적용 조건을 확인했으며 provider wire 원문이나 런타임 내부 grammar를 수집하지 않았다. 따라서 바이너리 내부의 각 grammar 제약 강제를 별도 증명했다고 주장하지 않는다.

기존 Swagger의 동일 질문·configuration_id `428992ab-697d-4604-9f6f-7b64f063e71f`·workspace `2292dfa0-3af8-4494-a8ce-da03ef2aa6ed`·folder_ids=[]·top_k10·experimental/include_diagnostics=true·history=[]를 확인하고 **2026-10-13T16:04:26.079Z(10/14 01:04:26 KST)에 Execute를 한 번만** 눌렀다. 처리 중 재제출·취소·새로고침하지 않았다. 큰 응답의 전체 DOM 읽기가 timeout되어 읽기 전용으로 서버 응답 영역만 제한해 확인했으며 검색 호출을 반복하지 않았다.

- **HTTP200**, 응답 헤더 요청 UUID **`acbfc893-4eeb-48cd-bb15-62dbdc29d625`**. 감사 같은UUID의 status=allowed, safe_error_code=null이다. configuration version `89351388-8ad6-4bd3-8ea3-c25244a24100` 및 profile/deployment가 사전 확인과 일치한다. 새005429 stdout 검색POST는1개/200이며 stderr에 provider_response_rejected 진단은 없다.
- 생성 latency **70,007ms**, 감사 시각2026-10-13T16:06:33.854506Z다. 클릭→감사 약127.78초는 클라이언트 기반 근사이며 정확한 서버 total/토큰 속도가 아니다. input/output/provider-reported token 및 execution_id는null이다.
- 응답은 status/generation.status **insufficient_evidence**, generation.reason_codes=`[evidence_content_insufficient]`, answer와generation.text는null, citations=[]이다. 버전·상태/claims·엄격 JSON 검증을 통과한 정상 근거부족 경로다. 이번1회에서 이전502/answer_contract.invalid는 재현되지 않았다.
- 감사 선택 근거는 이전UUID `3a9683f5-5609-4f2d-9646-8e79d1d4acd5`와 **ID 순서까지 동일한19단위·691자**, chunk `a6713e42-5d29-4a3c-ab27-a8ab238d75cf`, PDF2–3쪽이다. UI 응답 집계와 읽기 전용 DB 집계가 일치한다. 제공된 합성 근거의3쪽에는 발행일 표기와 발행 시점 해소 완료 여부 미확인 설명이 실제로 포함된다.
- 기대 결론은 **2026-09-03 발행 시점 해소 완료 여부 미확인**이다. 이번 출력은 완료 확정이라는 잘못된 단정을 하지 않았지만, 존재하는 근거로 미확인 결론을 설명하거나 인용하지도 않았다. 따라서 **형식/계약 수용은 확인, 근거를 인용한 H07 답변 품질은 미달**로 구분한다. 인용0이므로 인용 내용·위치 정확성의 성공 사례로 판정하지 않는다.

이번 승인 예산은 검색POST1회/history=[]/내부retry0으로 종료했다. 실제 호출에 따른 정상 자동 감사 기록 외 DB쓰기·추가 호출·재시작·코드/설정/색인/활성 도메인/권한 변경·commit/push 없음. provider 원문·reasoning·credential을 수집하거나 로그하지 않았고 문서는 기존 WORKBOARD와 본 worklog만 갱신했다. 제품 코드가 불변이므로 새 unit/static 검증은 하지 않고 문서 UTF-8·공백·링크·줄수와 소스 SHA를 확인한다.

다음 최소 후보는 **실제 호출 없이** 충분한 근거가 있는 부정/미확인 결론을 answered로 표현하는 경우와 진짜 insufficient_evidence의 구분을 프롬프트·mock 회귀로 점검하는 것이다. 답변 강제·claim 발명·로컬 검증 완화는 하지 않으며, 이번에는 후보만 기록하고 중단한다. 추가 실제 검증은 별도 승인이 필요하다. 이 단일 형식 수용을 전체 RAG 완료나 H07 최종 통과로 확대하지 않는다.


### 2026-10-14 기능 마감 우선 재점검 — 읽기 전용

사용자 우선순위에 따라 H07 부정/미확인 의미 이해·프롬프트 튜닝을 후순위로 돌렸다. 낮은 위험의 문서/읽기 전용 기능 조사이며 메인이 RAG 기준·검증 근거를 대조했다. 제품 구현·DB/서비스/보안 변경 역할은 제외했다. [설계 완료 기준](../labs/rag/design.md#12-첫-ai-검색-완료-기준), [기능 마감 기준](2026-10-11-rag-functional-closure-check.md), first-question/upload/monitoring 계획과 해당 검증 기록을 읽었다. 아래 실제 성공은 기록된 시점·경로의 증거이며 이번 재실행이 아니다.

| 기능 | 실제 확인 | mock/격리 검증 또는 남은 수용 경계 |
|---|---|---|
| 관리자 설정·연결 | 10/13 Chrome owner가 모델/배포/프로파일/비기본 구성 등록, health 사용 가능 확인. 10/14 실제 로컬 Gemma 응답 | 현재 Gemma 구성을 참조하는 활성 대화 도메인0개. 기존 asset-management 연결v2는 다른 configuration version을 사용한다. 미연결을 UI 폼 고장으로 오인하거나 자동 전환하지 않는다. |
| 정상 답변·인용·저장 복원 | [10/7 Codex 합성 Markdown 후속1회](2026-10-07-rag-generation-execution-path-verification.md)는 answered·claim1/근거2·인용 클릭·저장/새로고침 복원·단일 멀티턴 확인 | 현재 Gemma+PDF의 정상 answered·유효 인용 및 대화 UI 연결은 미검증. 과거 다른 경로의 성공을 없애거나 현재 수용으로 확대하지 않는다. |
| 근거부족 | 10/13 검색에서 no_eligible_evidence, 10/14 Gemma에서 evidence_content_insufficient·HTTP200·감사allowed 확인 | 정상 유보 기능 증거는 확보. H07에 명시 근거가 있는데 유보한 의미 품질은 별도 후순위이며 추가 튜닝/재시험하지 않는다. |
| 실패·취소·재요청·모니터링 | 10/5 tokenizer 실패 저장/새로고침과 검색 전 취소 terminal/다음 검색 확인. 이후 직접 검색502와 UUID별 안전 진단/감사 일치 | 실제 모델 실행 중 취소·timeout 뒤 종료 증거/terminal 저장/동일 대화 재요청/최신·누적 모니터링 일치는 남는다. [10/7 fault injection/rollback](2026-10-07-rag-functional-boundary-verification.md)과 HTTP mock은 이를 대체하지 않는다. 페이지 이탈 시험은 취소 성공으로 판정하지 않는다. |
| 첫 질문·권한 | 첫 질문 코드·후속 POST200 및 기존 권한 회귀/본래 rollback SQL 증거 | 최종 코드의 새 first POST201, 다중 연결 committed 권한/취소 경합은 미검증. 과거 cancelled/종료미확인1은 정식 복구도 남는다. |
| 첨부·업로드 실패 잔여물 | [10/8 개인 합성 PDF 저장/Asset READY](2026-10-08-rag-personal-attachment-verification.md), 현재 intake5개 모두 cleaned/attached | 개인 RAG pending/ingestion queued1·기존 failed projection1은 남음. [HTTP intake704/2skip](2026-09-20-http-upload-intake.md)은 격리 PG/native/ASGI 증거이며 본래 실패 업로드의 물리 잔여물 검증은 아님. 현재 새 미정리 intake 결함은 관측하지 않았다. 전체 영구 삭제 개발을 기존 READY 답변 시험의 선행 조건으로 삼지 않는다. |

이번 DB 조회는 기존 환경의 READ ONLY 트랜잭션·statement_timeout5초·rollback으로 수행했다. 별칭 open1/frozen1/receipt0, turns completed/종료확인17·failed/종료확인4·cancelled/종료확인1·cancelled/종료미확인1, projections ready6/pending1/failed1을 재확인했다. failed의 안전 코드 `chunk_tokenizer_unavailable`은 업로드 파일 누출 증거가 아니다. ISSUE-00013 open/r33·00018 implemented/r3·00029 open/r8 등 상태는 유지한다. 과거 비추적 임시물의 파일시스템 전수조사·종료 proof·receipt·gate 해제는 하지 않았다. 별칭 복구, DLL 재발 방지, main/원격/실행 인계는 기존 기능/운영 차단으로 남기되 H07 품질과 묶어 재구현하지 않는다.

**정상 답변 검증 후보(미제출):** “합성 월간 보고서 SYN-M01의 발행일은 언제인가요?” 기대값은 **2026-09-03**이다. document `415011bf-1720-449e-a2c9-28683c906e57`, active asset version `d7f4c78e-ed51-47b1-a8ef-46d4fc447cdc`의 lifecycle active/Asset READY·현재 구성과 일치하는 projection `f2569c4d-3394-4c40-9978-837fdfce9afc` READY·build READY/active를 DB로 확인했다. 근거 `f0348951-0d07-4285-a446-ce1fb8712ec1`, PDF3쪽 char1339–1398에 기준일과 구별된 발행일이 명시돼 있다. 해당 chunk는19단위·691자로 현재 max_groups8/max_units32/max_characters12000 안이다. 새 질의의 실제 검색 점수/선택은 아직 실행하지 않았으므로 근거 선택 성공을 보장하지 않는다. ES를 새로 조회하거나 색인을 변경하지 않았다.

**다음 최소 승인 묶음은 검색 POST1회, 실제 추론 최대1회다.** 기존 인증 Chrome Swagger와 configuration `428992ab-697d-4604-9f6f-7b64f063e71f`/version `89351388-8ad6-4bd3-8ea3-c25244a24100`, 기존 합성 workspace를 사용한다. `document_ids`를 위 문서1개로 한정하고 folder_ids=[]·top_k10·experimental/include_diagnostics=true·history=[]를 지정한다. 기존 schema2·출력512·temperature0·timeout120·retry0 및 필수 인용을 유지한다. 입력 history가 비어 문맥화 추가 호출을 만들지 않으며, 근거가 선택되지 않으면 생성0회로 끝낸다. 실패/유보여도 자동 재시도·다른 질문·추가 모델 호출 없이 중단한다. 실행 직전에 같은 구성/로드/권한 상태를 다시 확인해야 하며 이번 조사에서 런타임의 실제 입력 토큰 한도를 새로 측정하지 않았다.

수용 기준은 HTTP200/answered, 발행일과 기준일을 혼동하지 않은 한 문장, 공급된 원문 evidence UUID에 대한 유효 인용 및 PDF3쪽 위치 일치, 같은 UUID의 감사 성공·안전 진단 일치다. 부작용은 로컬 모델 CPU/RAM 사용·대기 시간과 정상 generation audit/필요한 인용 검증 영수증 등 서버 기록 생성이다. 별도 DB 수동쓰기·대화 생성·업로드·새 색인·프로파일/도메인 전환은 포함하지 않는다. 직접 검색1회는 대화 저장/취소/재요청이나 UI 인용 클릭까지의 수용을 닫지 않는다.

그 뒤의 모델 실행 중 취소→같은 대화 재요청은 별도 최소2질문/추론최대2회와 실제 취소 API·대화/turn/terminal 기록 쓰기가 필요한 검증이다. 현재 Gemma는 활성 도메인에 연결되지 않아 이 묶음을 지금 실행 가능한 승인안으로 제시하지 않는다. 정확한 기존 도메인 연결·보존/복구 범위를 별도 설계하고 승인받아야 하며 과거 미종료 turn을 이용하거나 강제 flag 변경하지 않는다. 실패 업로드 역시 파일/원장/작업을 생성할 수 있어 별도 한정 검증 대상이며 이번 모델 호출 묶음에 끼워 넣지 않는다.

이번 실제 API/모델 호출0회, 신규 테스트0회(제품 불변), 설치·재시작·코드/설정/DB/색인/권한/commit/push 변경0회다. 기존 WORKBOARD와 본 worklog만 최소 갱신했고 문서 UTF-8·공백·링크/줄수·최근 완료5개 보존을 검사한다. 현재 실제 호출 예산은0이고 위 묶음은 승인 요청용 제안일 뿐 실행하지 않았다. 전체 RAG 완료로 표시하지 않는다.


### 2026-10-14 SYN-M01 발행일 사실형 단1회 — 정상 답변·인용 미통과

직전 최소 검증 묶음에 대한 사용자의 “진행해봐” 승인으로 기존 BOMI/Chrome에서 검색 POST최대1회·추론최대1회를 수행했다. 중간 위험의 한정 실행 검증을 메인이 맡고 제품/운영 변경 역할은 제외했다. 기존 WORKBOARD 시작 상태와 문서 SHA를 보존·대조했다.

사전 확인: 기존 서버 PID129484·cwd/venv·시작15:54:29Z와 소스 SHA `5257cc6efb8e68f4ea66da9aaec7fd1a3ebb496c2dddbc70c36701a3ea48c485`가 그대로다. health/ready 각200, 기존 작업소 새로고침 후 마스터 인증 유지. READ ONLY DB 조회에서 비기본 configuration/version·generation profile·deployment 연결, loopback/명시적ollama/local/externalfalse, schema2/출력512/temperature0/timeout120/retry0를 재확인했다. 지정 문서의 같은 활성 Asset/Projection/build READY·active도 그대로다. 신규 로그인·health POST·서비스 재시작은 하지 않았다.

기존 Swagger에 질문 **“합성 월간 보고서 SYN-M01의 발행일은 언제인가요?”**, configuration `428992ab-697d-4604-9f6f-7b64f063e71f`, 합성 workspace `2292dfa0-3af8-4494-a8ce-da03ef2aa6ed`, document_ids=`[415011bf-1720-449e-a2c9-28683c906e57]`, folder_ids=[]·top_k10·experimental/include_diagnostics=true·history=[]를 입력했다. 입력 제어가 timeout됐지만 DOM의 실제 입력값이 정확히 반영됐음을 확인한 후 전송했다. **2026-10-13T16:23:46.262Z(10/14 01:23:46 KST)에 Execute 클릭을 한 번만 시도**했다. 클릭 제어도 timeout돼 다시 누르지 않았고 버튼 disabled, 이어 새 검색POST1개·감사1건·완료 응답으로 접수/종료를 확인했다. 클릭 시각은 서버 도착 시각이 아니며 응답 헤더 Date는16:24:43Z다. 브라우저 전체 응답 읽기가 지연돼 읽기 전용 DOM에서 핵심 필드만 추출했다.

- **HTTP200**, 헤더 UUID **`2d3966d7-c617-4e8c-89bc-c3f1ca8adbd2`**. 감사 같은UUID의 status=allowed/safe_error_code=null, configuration version `89351388-8ad6-4bd3-8ea3-c25244a24100`, profile `a07c2838-49d8-4241-b56a-e5b2a0004748`, deployment `1904891a-98ff-4824-8b28-4135bef105a4`가 사전값과 일치한다.
- 결과 status/generation.status=`insufficient_evidence`, reason_codes=`[evidence_content_insufficient]`, generation.text=null·citations=[]·turn_id/validation_token=null이다. 새005429 stderr에 provider_response_rejected 진단은 없다. 새005429 stdout의 검색POST 누적2개 중 첫째는 이전H07이고 이번 증분은1개/200이다. 이번 제출 시각 이후 해당 구성 감사도1건이다.
- 반환 resolved_query는 승인 질문과 일치하고 grounding_evidence의 document_id 집합은 지정 문서1개뿐이다. **19단위·691자**, 이전H07 UUID `acbfc893-4eeb-48cd-bb15-62dbdc29d625`와 감사 evidence ID 순서까지 동일하다. 발행일 근거 UUID `f0348951-0d07-4285-a446-ce1fb8712ec1`이 포함됐고 응답 근거의 PDF3쪽/char1339–1398에서 명시적인 발행일2026-09-03 포함을 확인했다. 예상 근거가 선택되지 않은 실패로 해석하지 않는다.
- 응답 진단: contextualization=null, retrieval23,280ms·selection6,300ms·generation88,167ms·total118,841ms. 감사 latency87,314ms, created_at2026-10-13T16:26:44.448307Z다. 서로 다른 측정 범위의 차이를 임의 원인에 배분하지 않는다. input/output/provider-reported token과 execution_id는null이며 실제 토큰 사용량은 미확인이다.
- **정상 답변·출처 인용 경계는 미통과.** 기대 날짜가 근거에 명시됐지만 날짜 답변·인용을 제공하지 않았다. HTTP·구조 계약 수용 및 정상 유보 반환을 answered 기능 수용과 구분한다. 인용0이라 인용 내용/원문 위치 정확성의 성공 사례로 판정하지 않는다. 왜 유보했는지 provider 원문/내부 reasoning 없이 단정하지 않는다.

예산은 검색POST1회·history=[]·내부retry0으로 종료했고 문맥화 추가 호출은 없다. provider 본문/원시 reasoning/credential·임의 오류값을 새 로그에 수집하지 않았다. 승인된 요청의 자동 감사 등 서버 기록 외 코드·설정·DB 수동쓰기·색인·도메인·서버·업로드·로그인·commit/push 변경은 없다. 기존 WORKBOARD/본 작업 기록만 갱신하며 제품 불변이므로 unit/static 검증은 새로 실행하지 않았다. 문서 UTF-8·공백·상대링크·줄수와 기존 최근완료5개·소스 SHA 불변을 검사한다.

다음 최소 후보는 **실제 호출 없이** 명시 사실에도 유보하는 현재 Gemma 요청 구성·정상 answered/유보 판정 경로를 코드/mock으로 조사하는 것이다. H07 의미 튜닝·추가 실제 호출·응답 강제 보정으로 우회하지 않는다. 현재 대화 도메인 연결, 모델 실행 중 취소/timeout/재요청, 첫 질문·권한 경합, 첨부 색인/별칭·과거 미종료 복구, DLL 재발 방지·인계는 기존 기능 검증으로 남는다. 이번에는 결과 기록 후 중단하며 전체 RAG 완료로 표시하지 않는다.
### 2026-10-14 발행일 유보 오프라인 조사

사용자 요청에 따라 systematic debugging으로 발행일 요청 `2d3966d7-c617-4e8c-89bc-c3f1ca8adbd2`의 검색→근거 선택→직렬화→유보 반환을 조사했다. 메인이 기존 감사/설정을 READ ONLY·statement timeout5초·rollback으로 조회하고, 독립 리뷰는 코드/명시적 mock 테스트만 검토했다. 기존 Chrome Swagger의 이미 표시된 응답을 DOM으로 읽어 같은 헤더 UUID임을 확인했으며 새 API 요청·새로고침·검색·실제 임베딩/모델 호출은 하지 않았다. 시작 문서 SHA와 쓰기 직전 상태를 대조했다.

**검색과 임베딩:** 구성 버전 `89351388-8ad6-4bd3-8ea3-c25244a24100`은 hybrid-rrf v2, BM25 top_k30·dense top_k30·RRF k60·reranker disabled다. 요청 top_k10은 융합 결과 상한이다. indexing e5-structure-aware v2의 embedding 바인딩은 intfloat/multilingual-e5-base, revision `d128750597153bb5987e10b1c3493a34e5a4502a`, 768차원·query/passage 접두사·정규화·CPU/float32·local_only다. 질의를 벡터화해 기존 문서 벡터를 검색하는 경로이며, 선택 단계도 질의/근거 임베딩으로 코사인을 계산한다. 이번 응답의 dense rank/score와 semantic score가 존재하여 BM25만 실행됐다고 볼 수 없다. 이는 현재 조사에서 모델을 새로 호출했다는 뜻이 아니다.

BM25는 text/title/section_path의 multi_match, dense는 embedding kNN(k/num_candidates30)이다. workspace/사용자 권한/READY 및 정확한 AssetVersion·Projection·build 식별자가 두 분기 검색 전에 필터링된다. 이번 selected_scope는 승인한 문서1개의 기존 활성 버전과 일치한다. 검색 요청에 별도 min_score/유사도 하한은 없으며, 후속 근거 선택 기준은 min_keyword_coverage0.5/min_semantic_score0.9다. RRF는 순위별 1/(60+rank)의 합이며 확률이나 코사인이 아니다. dense_score는 Elasticsearch가 반환한 _score다. 인덱스 프로파일의 similarity는 cosine이지만 이 _score를 원시 코사인으로 부르거나 선택 기준0.9와 직접 비교하지 않는다. 선택기의 semantic_score는 코드에서 직접 계산한 코사인이다. 실행 중 ES 매핑을 새로 조회하거나 점수를 재계산하지 않았다.

**이번 기존 응답의 그룹 진단(candidate_scope=returned_hits):**

| 융합 순위 | BM25 순위/점수 | dense 순위/점수 | RRF | keyword coverage | 선택 코사인 | 결과 |
|---|---|---|---|---|---|---|
| 1 | 1 / 1.2126852 | 1 / 0.92944425 | 0.03278688524590164 | 0.5714285714285714 | 0.8588884029765446 | selected, 19개/691자 |
| 2 | 2 / 1.1507163 | 3 / 0.9248461 | 0.03200204813108039 | 0.5714285714285714 | 0.8496921867931729 | budget_exceeded, incoming39개/667자 |
| 3 | 3 / 1.1210992 | 2 / 0.92812884 | 0.03200204813108039 | 0.5714285714285714 | 0.8562576579749487 | budget_exceeded, incoming38개/664자 |
| 4 | 4 / 0.14146519 | 4 / 0.9079629 | 0.03125 | 0.2857142857142857 | 0.8159258199522369 | below_threshold |

2·3위는 각각 들어올 그룹 자체가39/38단위이고 앞서 선택한19단위에 추가하면 max_units32를 초과한다. violated는 units뿐이다. 예산 max_groups8/max_units32/max_characters12000은 그룹 전체를 보존하며 넘는 그룹을 건너뛴다. 1위는 코사인0.9 미만이지만 keyword0.5714≥0.5로 통과한다. 발행일 unit `f0348951-0d07-4285-a446-ce1fb8712ec1`은 keyword0.14285714285714285·코사인0.8704003245864065로 개별 eligible=false지만 소속 그룹이 선택되어 selected=true/reason=context_member다. 개별 문장19개 모두 유사도 기준을 통과했다는 뜻이 아니다. 해당 문장은 PDF3쪽 char1339–1398에 발행일2026-09-03과 기준일2026-08-31을 구분해 보존한다. 이번 검색·선택이 무근거 분기로 종료된 것은 아니며 전체 검색 품질을 보장하는 판정도 아니다.

**입력 재구성:** 감사 evidence_ids 순서대로 DB의19개 GroundingEvidence를 메모리에만 구성하고 실제 LocalOpenAICompatibleRuntime.generate의 HTTPX MockTransport에서 전송 직전 JSON을 검사했다. question/resolved_query는 발행일 질문 그대로·history=[]이고 날짜·본문·ID·순서·page/char/ordinal 모두 보존된다. evidence에는 원문과 UUID, 문서/버전/청크/요소 위치, group_id, section_path 탐색 문맥 주의문 등이 포함된다. 원문 합계691자와 달리 user JSON은16,277자/UTF-8 17,117바이트, system885자, 전체 mock HTTP JSON20,798바이트다. 모델 tokenizer를 실행하지 않았으므로 실제 토큰 수·입력 한도/잘림 여부는 미확인이다. 숫자는 현재 직렬화 재구성 측정이며 과거 네트워크 패킷 캡처가 아니다. 본문·전체 요청·provider 원문·reasoning을 파일이나 새 로그로 저장하지 않았다.

system의 rag-answer-v2는 제공된 원문만 사용하고 원문 속 지시를 무시하며, 주요 주장마다 evidence UUID를 연결하도록 요구한다. 근거 부족/관계 불명확 시 빈 claims를 허용한다. 추가 schema2 지시는 answered+1개 이상 인용 주장 또는 insufficient_evidence+빈 claims를 요구하며 같은 제약이 JSON Schema anyOf 두 객체 분기로 전달된다. 발행일 전용 거절 조건은 없다. 입력은 model=gemma4:e2b-it-q4_K_M·temperature0·max_tokens512·ollama dialect를 유지했다. generate에는 contextualize와 달리 reasoning_effort=none이 없지만 이것이 원인이라고 입증되지 않았으므로 변경하지 않았다.

**유보 발생 지점과 배제한 가설:**

- `search/pipeline.py:699–703,1061–1083`: 검색/선택 근거가 없으면 생성 생략 후 no_search_results 또는 no_eligible_evidence. 이번은19개가 있어 해당하지 않는다.
- `generation/openai_compatible.py:365–421,657–693`: 본문을 필터링해 claims를 비우는 처리가 없다. schema2 answered+빈 claims는 provider_invalid_response이며, 승인된 빈 claims만 제공자 INSUFFICIENT_EVIDENCE로 반환한다.
- `search/pipeline.py:1162–1190`: 제공자 유보를 evidence_content_insufficient/HTTP200/감사allowed·safe_error_code=null로 전달한다. 이번 감사와 정확히 일치한다. 현재 코드/당시 로드 확인 기록을 전제로 제공자가 유효한 insufficient_evidence+빈 claims를 반환했다고 추론할 수 있다. 원시 응답을 새 수집한 것은 아니다.
- `search/pipeline.py:1206–1227`: 인용 후처리 실패는 citation_validation_failed/HTTP502/감사failed다. 이번 결과와 다르다. `openai_compatible.py:589–592`의 length 종료도 오류이며 정상 유보로 낮추지 않는다. 실제 runner 입력 잘림·내부 판단 원인은 배제하지 못했다.

**실행한 검증:** 인메모리 재구성 mock4분기(정상 날짜답변→answered/인용1, 정상 빈 유보→insufficient/인용생략, answered+빈claims→provider_invalid_response, 미공급 UUID→citation_validation_failed)를 모두 확인했다. 모델·네트워크 전송은0회다. 메인 `python -B -m pytest -q -p no:cacheprovider`의 retrieval/test_service.py·test_rrf.py, highlighting/test_context.py·test_evidence_selector.py, search/test_provider_insufficient_evidence.py에서77 passed/3.09s. 독립 리뷰는 search/test_provider_insufficient_evidence.py, generation/test_openai_compatible.py·test_citation_validation.py에서170 passed/7.39s이며 정상 answered를 유보로 바꾸는 결함 미발견·수정하지 않는 결론에 동의했다. 두 묶음은 중복이 있어 단순 합계를 고유 테스트 수로 보고하지 않는다.

재현 가능한 구현 결함이 없어 제품 코드/프롬프트/테스트 파일을 변경하지 않았다. 기존 WORKBOARD와 본 기록만 갱신했다. 코드 불변으로 Ruff/Mypy를 새 실행하지 않았으며 과거 통과를 이번 실행으로 표기하지 않는다. 완료 보고 전 문서 UTF-8/공백/상대 링크·보드200줄/최근완료5개·어댑터 SHA 불변을 확인한다. 실제 Gemma 정상 answered/인용, runner 입력 토큰·프롬프트/grammar/thinking 원인, 대화 UI/취소/timeout 등은 미검증으로 남는다.

다음 최소 후보는 동일 질문·동일 fact 근거를 유지한 채 전체 메타데이터와 최소 표현의 차이 또는 실행기 구조화 출력의 영향을 한 변수씩 비교하는 별도 승인 실험이다. 이번에는 실제 호출을 하지 않았고 원인으로 확정하지 않는다. 임계값/예산 확대·강제 답변·유보 제거·인용 완화·설치/재시작/설정·DB/색인/도메인/권한 변경·commit/push는 하지 않았다. 정상 답변 기능과 전체 RAG 마감을 완료로 표시하지 않는다.

### 2026-10-14 Ollama 컨텍스트·로그 읽기 전용 후속

사용자가 Ollama 현재 컨텍스트와 기존 입력 잘림 로그의 읽기 전용 조사를 승인했다. 대상은 같은 발행일 요청 `2d3966d7-c617-4e8c-89bc-c3f1ca8adbd2`이며 이전 검색·직렬화 결론을 보존한다. 메인이 비추론 상태/메타데이터와 관련 경로만 조회하고 독립 검토자는 결과 해석을 검토했다. 제품 코드·실행 상태를 변경하는 역할은 제외했다. 관찰은2026-10-13 17:01Z까지의 현재 상태이며 요청 당시16:24–16:26Z와 구분한다.

- **현재 상태:** loopback GET `/api/version`은0.40.3, GET `/api/ps`는models=[]다. 해당 모델의 POST `/api/show`는 비추론 메타데이터 조회이며200을 반환했다. 조회 뒤 GET `/api/ps`도models=[]여서 모델이 로드되지 않은 상태를 재확인했다. completion/generate/chat/embedding/search 요청은 하지 않았다.
- **현재 모델 정보:** gemma4:e2b-it-q4_K_M은 GGUF/Q4_K_M·family gemma4·runner llamacpp, `gemma4.context_length=131072`, `tokenizer.ggml.model=gemma4`다. 반환 parameters에는 top_k64/top_p0.95/draft_num_predict3/temperature1만 있고 num_ctx는 없다. 131072는 모델 메타데이터 한도이며 당시 실효 컨텍스트로 확정하지 않는다. 모델 기본 temperature1이 앱의 명시적temperature0을 무효화했다는 뜻도 아니다. 앱 요청 max_tokens512는 출력 예산이며 입력 컨텍스트 길이가 아니다.
- **환경/프로세스:** User/Machine 및 이번 검사 셸의 OLLAMA_CONTEXT_LENGTH는 미설정이다. 실행 중인 서버의 상속 환경은 확인하지 못했으므로 서버도 미설정이라고 추론하지 않는다. 기본 CIM 조회는 access denied였고, 같은 범위의 승인된 읽기 전용 승격 조회는 성공했다. Ollama PID167472·시작2026-10-12 15:10:18KST·부모PowerShell169100까지 확인했으나 두 프로세스의 executable/commandline은null로 반환됐다. 권한/보호 설정이나 프로세스 메모리를 변경·우회하지 않았다. 자동 승인 검토가 이 조회를 거절한 사건은 아니다.
- **로그 경계:** 사용자 LocalAppData/Ollama 표준 경로는 존재하지 않았다. 확인된 설치 C:/AI/Ollama는 exe/lib이며 하위에 log/ps1/cmd/bat 파일이 없었다. 프로젝트 dev-logs와 기존 Gemma/E2B 작업 디렉터리·관련 실행 문서/스크립트에서도 해당 서버 로그/시작 명령 위치를 확보하지 못했다. 프로젝트의 Ollama 이름 log는 단위 테스트 결과여서 실모델 로그로 사용하지 않았다. 당시 앱의 api-restart-20261014-005429 stdout/stderr에는 truncation/context-exceed 경고0건이고 stdout 검색POST2건은 이전H07+발행일이다. 이 앱 로그는 Ollama 서버 로그가 아니므로 경고 부재로 입력 잘림을 배제하지 않는다. 다른 사용자의 디렉터리·일반 셸 기록·자격 증명은 조사하지 않았다.
- **토큰 수:** 기존 같은 요청 감사의 input/output/provider-reported token은null이며 새 토큰 기록은 확보하지 못했다. 설치 모듈은tokenizers/transformers/sentencepiece가 있지만 matching Gemma 독립 tokenizer 파일은 확인한 프로젝트 모델 캐시(E5/OCR)와 기본 HF 캐시 경로에서 확보하지 못했다. gguf/llama_cpp 모듈도 없다. 라이브러리 설치 여부는 모델 vocabulary/chat template 호환성의 증거가 아니므로 다른 모델 tokenizer나 글자 수 비율로 대신 계산하지 않았다. GGUF 가중치를 실행기에 로드하거나 설치/다운로드하지 않았다. 이전 사용자JSON16,277자/본문691자는 여전히 문자 수이며 토큰 수가 아니다.

[공식 v0.40.3 환경 설정 소스](https://github.com/ollama/ollama/blob/v0.40.3/envconfig/config.go)는 OLLAMA_CONTEXT_LENGTH 기본값0 및 자원에 따른 기본 선택을 설명하므로 환경 미설정만으로4096을 단정하지 않는다. [같은 버전 runner 소스](https://github.com/ollama/ollama/blob/v0.40.3/llm/llama_server.go)의 completionPromptForRequest는 특정 조건에서 prompt를 tokenize하고 한도를 넘으면 오류 또는 truncating input prompt 경고와 길이 필드를 기록하는 경로를 갖는다. 이는 가능한 동작을 설명하는 정적 근거일 뿐 이번 요청의 실행 분기/실제 잘림 증거는 아니다.

**결론:** 당시 실효 num_ctx·서버 입력 토큰·잘림 경고는 미확인이다. 입력 잘림 가설은 입증도 배제도 하지 못했으며 현재 정보로 컨텍스트/프롬프트/코드를 바꿀 근거가 없다. 독립 검토도 메타데이터 한도/현재 상태/당시 실행을 구분한 결론에 동의했다. 다음 최소 조치는 기존 해당 서버 로그나 시작 명령의 정확한 위치가 확보될 때 해당 시각의 num_ctx·입력 토큰·잘림 경고만 대조하는 것이다. 위치가 없으면 실제 호출이 필요한 실험은 별도 승인 범위로 설계한다.

이번은 비추론 메타데이터/상태 조회4회(version1·ps2·show1), 실제 모델·임베딩·검색 호출0회, 모델 로드/언로드·설치·다운로드·재시작·코드/설정/DB/색인/권한·commit/push 변경0회다. 본문·원시 provider reasoning·credential을 새 기록하지 않았고 기존 WORKBOARD/본 worklog만 갱신했다. 제품 불변으로 신규 unit/Ruff/Mypy는 실행하지 않았으며 문서 UTF-8/공백/상대링크·보드200줄/최근완료5개·어댑터 SHA 불변만 검사한다. 현재 Gemma 정상 answered/인용과 전체 RAG 기능 마감은 미완료로 유지한다.
### 2026-10-14 Ollama 터미널 직접 열람 도구 차단

사용자가 로그를 찾기 어렵다며 직접 확인을 요청하여 이번에는 파일 로그 검색을 반복하지 않고 화면/창 제어 도구부터 조사했다. Windows Computer Use SKILL.md와 guidance/api/confirmations를 읽고 현재 callable 도구 목록을 확인했다. 스킬의 Windows 진입점은 node_repl에서 @oai/sky를 import하는 방식이나 이 작업에는 해당 node_repl/sky 실행 도구가 노출되지 않았다. 네이티브 화면 기능을 임의 helper/PowerShell UI Automation으로 우회하지 않았다.

실제로 `mcp__cua_repl.js`에서 `await cua.getState()`를 실행했으며 반환은 apps=[]와 Chrome browser1이었다. 이어 읽기 전용 `await cua.listWindows()`를 시도했으나 정확한 반환은 **cua.listWindows is not a function**이었다. 현재 CUA 도구 명세도 Native computer APIs are disabled라고 명시한다. 앱 목록이 비었다는 것을 사용자의 PowerShell 창이 닫혔다는 증거로 해석하지 않는다. 확인된 사실은 이 작업에 네이티브 Windows 창 목록/선택/화면/스크롤 도구가 제공되지 않는다는 것이다. Codex capture_screen_context는 활성 음성 채팅 및 Codex 내부 화면에만 한정되어 목적에 맞지 않아 호출하지 않았다.

따라서 **Ollama PowerShell/Windows Terminal 창과 스크롤 기록은 실제로 열람하지 못했다.** num_ctx/n_ctx·truncating input prompt·해당 요청 당시 토큰/시각에 관한 새 증거는 없으며 기록 소실 여부도 판단하지 않았다. 이는 사용자 승인 부족이나 이번 자동 승인 심사 거절이 아닌 도구 가용성 차단이다. 다음은 네이티브 Windows 화면 도구가 제공되는 작업 환경에서 이미 승인된 동일 읽기 전용 범위를 이어가는 것이다. 사용자에게 다시 로그 찾기를 넘기거나 추가 모델 호출로 대체하지 않았다.

명령 입력·Ctrl+C·창 닫기/재시작·모델/API/DB 조회·파일 로그 재검색·설치/권한/보호 설정 변경은0회다. 관련 없는 창의 본문/화면은 열람하지 않았다. 메인은 도구 가용성 확인과 기존 WORKBOARD/본 worklog 기록만 수행했고 별도 구현/모델/운영 역할은 배정하지 않았다. 제품 불변으로 unit/Ruff/Mypy는 미실행이며 문서 UTF-8·상대링크·공백·보드200줄/최근완료5개 보존을 검사했다.

### 2026-10-14 사용자 스크린샷으로 Ollama 입력 잘림 확인

사용자가 제공한 터미널 스크린샷(Library `libfile_2a223b6fe18081918c5ac848a647ce39`, 부모 작업 직접 열람·전사)을 기존 발행일 요청과 읽기 전용으로 대조했다. 이 작업의 Library 응답은 이미지 참조/메타데이터였으므로 여기서 픽셀을 직접 열람했다고 주장하지 않는다. 앞 절의 “잘림 미확인”은 당시 증거 범위이며 아래 새 증거가 이를 갱신한다. 코드/환경/서비스 변경 역할은 제외하고 독립 검토자는 계산·인과 해석·재검증 범위를 리뷰했다.

- **잘림 증거:** 2026-10-14 01:25:38.021+09:00 경고는 `truncating input prompt`, limit1,027/prompt11,017/keep5/new1,027이다. 이어 n_ctx_slot2,048/task.n_tokens1,027, prompt eval1,027/eval332/합계1,359가 기록됐다. 마지막 truncated=0은 앞 단계의 명시적 잘림을 취소하지 않는다. 생성332토큰 모두가 공개 답변 본문이라고 단정하지 않는다.
- **요청 대조:** 스크린샷 POST `/v1/chat/completions` HTTP200 완료01:26:44KST·약1분26초와 요청 `2d3966d7-c617-4e8c-89bc-c3f1ca8adbd2` 감사 생성2026-10-13 16:26:44.448307UTC·latency87,314ms가 맞는다. 해당 구성 버전/시간대 SELECT에서 한 건을 확인했고 statusallowed/error없음/input·output tokens null이었다. 읽기 전용 transaction 후 rollback했다. 로그에 UUID가 없으므로 시각·경로·소요 시간이 강하게 일치한다는 연결이지 직접 UUID 조인은 아니다.
- **소스/설정 대조:** 확인된 Ollama0.40.3의 [고정 커밋 runner 소스](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/llm/llama_server.go)에서 completionPromptForRequest/contextShiftPromptLimit을 확인했다. [기본 옵션](https://github.com/ollama/ollama/blob/v0.40.3/api/types.go)의 NumKeep4와 Gemma BOS 보정1은 경고keep5에 부합한다. 설치 exe SHA와 현재 adapter SHA는 앞 조사 값과 같지만 실행 프로세스 경로/상속 환경은 앞서 확인하지 못했다. slot2,048은 실행 로그의 사실이고 모델 메타데이터131,072와 구분한다. [스케줄러](https://github.com/ollama/ollama/blob/v0.40.3/server/sched.go)와 [환경 기본값](https://github.com/ollama/ollama/blob/v0.40.3/envconfig/config.go)만으로 이번에2,048이 선택된 설정 출처를 확정할 수 없다.

| 항목 | 확인한 계산과 한계 |
|---|---|
| 잘림 한도 | fullPromptLimit=2,047 초과 시 해당 context-shift 경로의 한도는 2,048−floor((2,048−5)/2)=1,027이다. 출력 상한512를 뺀 값1,536과 다르다. |
| 남는 입력 | 0부터 세는 토큰 구간 `[0:5]`와 `[9995:11017]`, 즉 앞5개와 뒤1,022개를 연결한다. 중간 `[5:9995]`의9,990개(약90.68%)가 제거된다. |
| 입력11,017의 의미 | runner 전처리/템플릿이 적용된 잘림 전 토큰 수다. 사용자 JSON 글자 수나 순수 근거 본문 토큰 수가 아니다. 질문·시스템·템플릿별 분량과 삭제된 원문은 재구성하지 않았다. JSON Schema의 별도 grammar 전달 전체를 prompt 토큰에 포함했다고 가정하지 않는다. |
| 출력/실제 평가 | max_tokens512는 출력 상한이며 이번 한도1,027을 직접 결정한 출력 예약량이 아니다. 로그의 prompt eval1,027은 실행기에 전달된 잘린 입력과 맞는다. |

앱 직렬화에 질문·발행일 근거가 있었다는 앞 mock 결과와 모델이 이를 전부 읽었다는 주장은 다르다. 입력 손실은 확인됐고 evidence_content_insufficient의 구체적인 원인 후보가 됐다. 다만 특정 발행일 문장/질문이 삭제됐다는 원문 단위 증명이나 유보의 유일 원인 확정은 아니며, 컨텍스트 확대만으로 정상 answered를 보장하지 않는다.

**최소 수정·재검증 제안(미실행):** 기존 Ollama 프로세스의 컨텍스트를16,384로 명시하는 방안을 우선 검토한다. 관측 입력11,017+출력 상한512=11,529에 대해4,855토큰 여유가 있다. 적용 수단 후보는 프로세스 범위 OLLAMA_CONTEXT_LENGTH=16384로 통제된 재시작하는 것이며, 공용 서버 기본값은 다른 호출에도 영향을 주므로 범위와 기존 값/미설정 상태 복구를 함께 승인받아야 한다. 현재 OpenAI 호환 어댑터는 num_ctx를 보내지 않으며 지원 여부 미확인 필드를 임의로 추가하지 않는다. 향후 입력 예산은 문자 수만이 아니라 전체 렌더링 토큰·출력 여유·초과 시 명시적 실패를 다루는 별도 코드 작업 후보로 남긴다.

슬롯 용량은2,048→16,384로8배지만 전체 RAM/VRAM이8배라는 뜻은 아니다. 모델 가중치는 그대로이며 KV cache·작업 버퍼 비용은 커질 수 있다. Gemma attention/sliding window, 캐시 자료형, 병렬도, draft 버퍼에 따라 실제 증가량이 달라 이번에는 측정하지 않았다. 적용/재시작/복구, 모델 로드와 자원 사용, 기존 질문의 검색 POST최대1회·추론최대1회(history=[],retry0)를 묶어 승인 범위를 정한다. 재검증에서는 실제 슬롯16,384, 입력 잘림 없음, 입력 토큰 수, 올바른 발행일 answered/유효 인용/감사 결과를 확인하고 실패 시 추가 재시도 없이 멈춘다. DB 수동 변경·색인 재생성·임계값/인용/모델 변경은 제안 범위에 없다.

**이번 실행/검증:** 기존 감사 SELECT, Library 참조/메타데이터 조회, 공식 소스 읽기, 잘림 한도·보존/제거 구간·16,384 여유의 산술 assertion4개 통과, 독립 리뷰 완료. 추가 검색/임베딩/실모델 호출·설치/다운로드·모델 로드·서비스/설정/DB 변경·commit/push는0회다. 기존77/170 mock 결과를 이번 신규 실행으로 재표기하지 않는다. 제품 코드 불변으로 unit/Ruff/Mypy는 재실행하지 않는다. WORKBOARD/본 worklog만 갱신하며 문서 diff 공백·UTF-8·상대 링크·WORKBOARD200줄/최근 완료5개·adapter SHA 불변을 검사한다. 정상 답변/인용과 전체 RAG 마감은 아직 미완료다.

### 2026-10-14 재시작 후 단일 검증 사전 점검—메모리로 보류

사용자가 컨텍스트16,384 안내 후 확인을 요청하여, 기존 비기본 Gemma 구성에서 동일 발행일 질문을 단1회(history=[],retry0) 검증하도록 승인했다. 단, 사전 메모리 부족이 명백하면 호출을 보류하라는 조건이 포함됐다. 메인은 비추론 사전 조회만 맡았고 코드/설정 변경과 구현 역할은 제외했다. 이번에는 아래 조건에서 멈춰 브라우저 질문 제출·응답 검증 단계에 진입하지 않았다.

- 2026-10-14 02:07:29UTC: 기존 loopback `/api/version` GET200/version0.40.3, `/api/ps` GET200/models=[] 확인. 실행 슬롯/컨텍스트가 반환될 로드 모델이 없어16,384 적용도 기존2,048 잔존도 확인하지 못했다.
- 같은 시각 psutil 물리 메모리: 총23.50GiB, 가용1.15GiB, 사용95.1%. 02:07:55UTC Windows GlobalMemoryStatusEx 재확인: 가용0.92GiB, 사용96%. 시스템 commit 한도82.93GiB/가용28.93GiB도 확인했으므로 commit 고갈이나 OOM 발생으로 단정하지 않는다. 그러나 모델 미적재 상태에서 물리 메모리가1GiB 안팎이고 계속 감소하여 새 모델/16,384 컨텍스트 로드의 페이징·응답 지연 위험이 크다고 판단, 사용자 지정 보류 조건을 적용했다. 실제 추가 메모리 요구량이나 GPU 오프로딩 여유를 측정한 결과는 아니다.
- **이번 검색 POST0회·임베딩0회·추론0회·모델 로드0회.** 입력 근거/답변/인용/검색 HTTP/감사 UUID/생성 소요시간/토큰/잘림 유무의 신규 검증 결과는 없다. 상태 API의200을 RAG 성공으로 표시하지 않는다. timeout/중단된 추론도 이번에는 발생시키지 않았다.
- 서버 재시작/종료·환경/DB구성·활성 도메인·제품 코드·다른 서비스·설치·commit/push 변경 없음. 메모리 확보를 위해 임의 프로세스 종료나 캐시 삭제를 하지 않았다. 승인된 한 번의 질문을 실패 후 재시도한 것이 아니라 제출 전에 보류한 상태다.

다음은 사용 가능 메모리가 확보된 후 사전 상태를 재확인하는 것이다. 이후에도 원래 단일 질문 범위만 유지하며 실제 슬롯16,384/입력 잘림 없음/정상 날짜 답변과 인용은 검증 전까지 미완료다. WORKBOARD와 본 작업 기록만 최소 갱신하며 UTF-8·상대 링크·diff 공백·WORKBOARD200줄/최근완료5개를 확인한다. 코드 불변이고 모델 호출 전 중단됐으므로 unit/Ruff/Mypy/실모델 테스트를 실행하거나 통과로 기록하지 않는다.

### 2026-10-14 재개 단일 요청—인증 거부로 종료

사용자가 메모리 보류 후 재개를 요청했다. 이전 보류는 검색POST0회였으므로 남은 단일 시험만 진행했다. 메인은 기존 Chrome/서버 사전 확인과1회 제출·추적을 맡았고 독립 검토자는 제공된 관측과 인증 단계 해석만 리뷰했다. 구현/설정/서비스 변경 역할과 추가 시험은 제외했다.

- **사전 조건:** 02:31:55UTC RAM23.50GiB 중 가용3.70GiB/사용84.2%, Ollama GETversion200/0.40.3·GETps200/models=[]를 확인했다. 모델 목록의 gemma4:e2b-it-q4_K_M 디스크 크기4.27GiB를 확인했으나 RAM 요구량과 동일시하지 않았다. 사전 보류 때의 가용0.92GiB보다는 개선됐으며, 준비 중 가용2.88GiB/87.7%, 클릭 직전 관찰2.13GiB/91.0%로 감소했다. 충분한 모델 메모리를 입증한 것은 아니며 제한된1회 동안 비추론 상태를 관찰하기로 했다. 메모리 변화가 아래401의 원인이라는 증거는 없다.
- 기존 API health/ready 각200, 어댑터 SHA `5257cc6efb8e68f4ea66da9aaec7fd1a3ebb496c2dddbc70c36701a3ea48c485` 불변을 확인했다. READ ONLY SELECT/rollback으로 기존 비기본 configuration/version428992ab/89351388, profilea07c2838→deployment1904891a 연결과 local/externalfalse/gemma4:e2b-it-q4_K_M/timeout120/retry0를 재확인했다. profile config는 generation 하위 schema2/출력512/temperature0이다. 최초 평탄 경로 조회의null은 중첩 구조 때문이었으며 실제 설정 누락으로 판단하지 않았다.
- **제출:** 기존 Chrome 작업소에는 마스터 로그인 표시가 있었고 Swagger에는 같은 질문·구성·합성 workspace/document·top_k10·experimental/include_diagnostics=true·history=[]가 그대로 남아 있었다. 토큰/쿠키를 조회하거나 수집하지 않았다. 2026-10-14T02:34:30.228UTC Execute를 정확히1회 클릭했다. CDP 입력 제어가 timeout됐지만 재클릭하지 않았고, 뒤이어 실제 응답·서버 로그로 접수를 확인했다. 이는 모델 timeout이 아니다.
- **완료 결과:** HTTP401, `not_authenticated`, 요청 UUID `c5b69ca0-2830-4fc3-9c5e-78086975a5be`. 응답 헤더 Date는02:34:40UTC이며 기존005429 stdout에도 새 검색POST1건/401이 확인됐다. 클릭 시각과 헤더 사이 약10초는 브라우저/서버 측정 경계가 달라 API 처리시간이나 생성시간으로 표시하지 않는다. 인증 만료는 가능한 설명이지만 구체적인 인증 실패 원인은 확정하지 않았다.
- **감사/모델:** READ ONLY 조회에서 해당 UUID의 rag_generation_execution_audits0건 및 제출 이후 해당 구성 버전 감사0건. search API의 get_current_user 의존성이 service.search 본문 전에 인증을 요구하므로 이번 요청은 검색 실행·임베딩·생성에 진입하지 않은 것으로 판단한다. 감사0건이나 ps 빈 목록만으로 이 결론을 내린 것은 아니다. 02:34:21–02:36:54UTC의 비추론 ps 관찰20회는 모두HTTP200/models=[]였고 실제 context_length/로드 크기/VRAM 값은 없었다. 이 관찰 구간 가용RAM은1.87–2.39GiB, 마지막2.11GiB였으며 관찰 프로세스는 정상 종료했다. 실행 중 모델이 없어16,384 적용·2,048 잔존 어느 쪽도 확인되지 않았다.
- **검증 한계:** 입력 근거를 새로 검색/선택하지 못했고 답변/인용·입출력 토큰·입력 잘림 여부·생성 소요시간은 이번 결과에 없다. 이전19단위/691자 근거와 과거 유보 응답을 새 검증 결과로 재사용하지 않는다. 모델 timeout/취소/종료 불명 사건으로 분류하지 않으며 과거 종료 불명 상태도 변경하지 않는다.

독립 리뷰는 인증 단계 실패와 CDP timeout/모델 timeout의 구분, 감사0건/ps 빈 목록의 증거 한계, 메모리 감소의 인과 미확정,16,384/답변/인용 미검증 및 재제출 금지 해석에 동의했다. 이번 검색 POST1회·추가 제출0회, 임베딩/추론 진입0회다. 인증 복구용 로그인·보호 설정 변경·서버 재시작·DB구성/활성 도메인/코드/다른 서비스/설치/commit/push 변경은 하지 않았다.

다음은 기존 사용자 인증 상태를 복구하고 메모리를 다시 확인한 뒤 새 단일 시험 범위를 승인받는 것이다. 인증 거부가 추가 제출 권한을 자동으로 만들지 않는다. 기존 WORKBOARD/본 작업 기록만 최소 갱신하고 쓰기 직전 SHA를 대조했다. 문서 UTF-8·상대 링크·diff 공백·WORKBOARD200줄/최근완료5개를 검사하며, 제품 불변으로 unit/Ruff/Mypy는 재실행하지 않는다. 전체 RAG 마감과 컨텍스트 확대 효과는 미검증으로 유지한다.

### 2026-10-14 재로그인 후 단일 시험—실제 컨텍스트2048·유보

사용자가 기존 계정 로그인 완료를 알려 같은 사실 질문을 한 번 더 검증하도록 승인했다. 앞401 요청과 구분되는 새 단일 시험이다. 메인은 기존 Chrome 세션·구성 확인/1회 제출/응답·감사·상태 관찰을 맡고 독립 검토자는 결과 해석을 리뷰한다. 제품 구현/설정/서비스 변경은 제외했다.

- **사전:** 02:42:09UTC Ollama version0.40.3/ps 각HTTP200·models=[]와 물리RAM23.50GiB/가용2.13GiB/사용90.9% 확인. 준비 중 가용2.27GiB/90.3%도 관찰했다. 작업소를 새로고침한 뒤 기존 마스터 세션을 확인했다. 사용자가 다른 화면으로 이동한 기존 탭에서 승인된 Swagger 검색 화면을 다시 열고 동일 입력을 설정했다. 토큰/쿠키는 수집하지 않았다.
- READ ONLY SELECT/rollback으로 기존 version89351388→profilea07c2838→deployment1904891a 연결, is_default=false/local/externalfalse/gemma4:e2b-it-q4_K_M, timeout120/retry0, generation schema2/output512/temperature0를 확인했다. 어댑터 SHA는 `5257cc6efb8e68f4ea66da9aaec7fd1a3ebb496c2dddbc70c36701a3ea48c485`로 불변이다.
- **제출1회:** 2026-10-14T02:44:28.937UTC Execute 클릭. “합성 월간 보고서 SYN-M01의 발행일은 언제인가요?”, configuration428992ab, workspace2292dfa0/document415011bf, folder_ids=[], top_k10, experimental/include_diagnostics=true, history=[]를 DOM에서 확인했다. 버튼 disabled/LOADING 이후 완료까지 추적했고 추가 클릭/재시도는 하지 않았다.
- **실제 컨텍스트:** 비추론 ps 관찰24회(02:44:18–02:47:22UTC)는 모두HTTP200이다. 처음미적재→02:45:14부터 해당 Gemma의 context_length=2,048을 확인했다. size220,662,333bytes/size_vram0도 API가 반환했으나 이 값을 전체 모델 상주메모리 실측으로 해석하지 않는다. **16,384 적용이 실제 실행에서 확인된 것이 아니라,2,048로 실행됐음이 확인됐다.** 서버가 해당 값을 선택한 원인과 사용자의 설정 여부를 이 값만으로 단정하지 않는다.2,048을 알게 된 시점은 이미 제출 후였으므로 추가 호출 없이 현재 요청만 추적했다.
- **자원:** 모니터 시작02:44:18 가용1.61GiB/93.2%,02:44:26 1.14GiB/95.1%였으며 이 두 번째 표본은 제출 후 도구 출력에서 확인했다.02:45:06 최저0.28GiB/98.8%까지 내려갔다가 관찰 중최대4.08GiB, 마지막1.93GiB로 변했다. 메모리 여유가 충분했다거나16,384로 확대해도 안전하다고 입증한 시험은 아니다. 임의 프로세스 종료/메모리 정리 없이1회 요청의 종결을 확인했다.

| 확인 항목 | 이번 결과 |
|---|---|
| HTTP/요청 | HTTP200, UUID `53a6eb61-b5e2-42b5-b3b8-cfd4e4cd0c73`, 헤더Date02:44:29UTC. 기존005429 stdout의 검색200 누적2→3으로 이번 증분1건 확인. |
| 답변/인용 | status 및 generation.status=insufficient_evidence, reason=evidence_content_insufficient, text=null, citations=[], turn_id/validation_token=null. 정상 날짜 답변/인용 수용은 미통과. |
| 입력 근거 | 새 응답의 grounding_evidence19단위/691자. 지정PDF3쪽/char1339–1398, evidence UUID f0348951-0d07-4285-a446-ce1fb8712ec1에 기준일2026-08-31과 발행일2026-09-03이 명시돼 있다. 과거 근거를 이번 확인으로 대체하지 않았다. |
| 소요 시간 | 응답 stages_ms: retrieval16,120/selection8,712/generation56,322/total82,107, contextualization=null. 클릭 시각·헤더Date는 이 측정과 구분한다. |
| 감사 | 동일UUID의 새 감사1건, statusallowed/safe_error_code=null/latency56,078ms/created_at02:45:52.282576UTC. 구성/프로파일/배포 버전은 사전값과 일치. |
| 토큰/잘림 | 감사 input_tokens/output_tokens=null. 현재 어댑터도 이 값을None으로 기록한다. 접근 가능한 설치/표준 로그 경로에는 이번 runner 로그가 없어 새 prompt 토큰/잘림 경고를 확보하지 못했다. 과거11,017→1,027 경고를 이번 호출 로그로 재사용하지 않는다. |

동일 질문/선택 근거와 실제2,048 컨텍스트는 과거 잘림 문제의 재발 가능성을 높이는 정황이지만, 이번 입력 잘림의 직접 증거나 유보의 유일 원인 증명은 아니다. 실제16,384에서 답변 품질을 비교한 결과도 아니다. HTTP200/allowed는 정상 answered/인용 성공을 뜻하지 않는다. 이번 요청은 최종 응답·감사로 완료됐으며 timeout/취소 사건은 아니다. ps는02:46:58 이후models=[]로 바뀌었지만 그 이유를 임의로 확정하거나 과거 종료 불명 상태의 복구 근거로 사용하지 않는다.

이번 검색POST1회·문맥화 추가호출0회·retry0, 추가 모델시험0회다. 자동 감사 외 DB수동쓰기·설정/활성 도메인/코드/서버/다른 서비스 변경·로그인 대행·설치·commit/push는 하지 않았다. 모니터는24회 관찰 후 정상 종료했다. 다음 최소 범위는 **추가 추론 없이 기존 시작 설정/실행 인스턴스를 확인해16,384 미적용 원인을 좁히는 것**이다. 설정 반영·재시작·새 시험은 별도 승인 범위로 두며, 메모리 자원 여유도 먼저 재평가한다.

기존 WORKBOARD/본 작업 기록만 갱신하고 쓰기 직전SHA를 대조했다. 제품 불변으로 unit/Ruff/Mypy는 실행하지 않았으며 문서 UTF-8·상대링크·diff 공백·WORKBOARD200줄/최근완료5개·어댑터SHA불변을 검사한다. 전체 RAG 마감은 미완료다.

독립 리뷰 완료: 생성 단계 유보와 검색 결과 없음의 구분, 실제2,048 관측/설정 출처 미확정, 이번 잘림 직접 증거 없음, 모델size·메모리 회복·마지막미적재의 해석 한계에 동의했다. 추가 호출·파일 수정 없이 리뷰했으며 차단 지적은 없다.

### 2026-10-14 사용자 컨텍스트16384 변경 후 단일 시험—적용 확인·timeout

사용자가 “다시 테스트 해봐. 16384로 다시 바꿨어”라고 승인한 뒤 기존 사실 질문 “합성 월간 보고서 SYN-M01의 발행일은 언제인가요?”를 한 번 제출했다. 기존 Chrome 인증을 파일함 새로고침으로 확인했고 health/ready/Ollama version·ps는200이었다. 사전 가용RAM은03:12:46UTC 3.69GiB, 제출 전03:13:46 2.96GiB였으며 모델은 미적재였다. 기존 local/external_transfer=false·retry0·timeout120초 배포와 원래 입력을 유지했다. 오프라인 직렬화 축소 후보는 적용하지 않았다.

- **요청:** Execute 동작 시각03:14:07.625UTC. 브라우저 클릭 도구는 입력 전달 응답 대기에서 timeout을 반환했지만 후속 화면의 Execute disabled/loading으로 접수를 확인했으며 재클릭하지 않았다. 새 correlation_id는 `ffef36a2-4a17-4765-b7aa-6000baf2588f`, 응답Date는03:14:18UTC다. configuration version `89351388-8ad6-4bd3-8ea3-c25244a24100`·문서/공간·top_k10·history=[]·experimental/include_diagnostics=true는 직전 시험과 같다.
- **결과:** HTTP504 `provider_timeout` / “생성 서비스 응답 시간이 초과되었습니다.”로 요청이 종료됐고 답변·인용은 반환되지 않았다. 읽기 전용 DB 대조에서 신규 감사는1개, 전체 해당 구성 감사는10→11이다. status=failed/safe_error_code=provider_timeout, latency_ms=121047, created_at=2026-10-14 03:16:50.228015UTC다. 근거19개 ID와 순서는 직전 요청 `53a6eb61-b5e2-42b5-b3b8-cfd4e4cd0c73`와 동일하다. input/output/provider-reported input/output token은 모두null이다. API stdout은 기존200 3개/401 1개에 새504 1개가 추가됐다.
- **실제 컨텍스트:** 8초 간격27회 관측(03:14:02–03:17:30UTC)에서 모델 적재 후03:15:06부터 마지막까지 `gemma4:e2b-it-q4_K_M`의 context_length=16384를 확인했다. size=276247346/size_vram=0은 Ollama 보고값이며 전체 프로세스 메모리로 해석하지 않는다. 이번에는16,384 적용을 확인했지만 실제 입력 토큰/잘림 로그는 없어 잘림 해소를 주장하지 않는다.
- **메모리:** 표본 최저 가용RAM은03:14:58 0.764GiB(사용96.8%)이고 다음 표본1.651GiB, 이후2.464–3.547GiB, 마지막2.466GiB였다. 표본 사이의 최저치는 미측정이다. llama-server PID117184의 관측 최대RSS 약3024.6MiB/private commit5973.1MiB다. RSS와 private commit은 합산하지 않는다. 마지막에도 모델/runner가 적재되어 있었지만 이는 추론 계속 또는 완전 종료 어느 쪽의 증거도 아니다. 실제 paging rate와 timeout 이후 실행 중단은 이번 검사에서 입증하지 못했다.

모니터는 정상 종료했다. 검색 제출1회·자동 재시도0·추가 모델시험0이다. 제품 어댑터 SHA-256 `5257cc6efb8e68f4ea66da9aaec7fd1a3ebb496c2dddbc70c36701a3ea48c485`는 불변이다. 설정·서비스 재시작·모델 설치·수동 DB쓰기·commit/push는 하지 않았다. 기존 WORKBOARD/본 기록만 쓰기 직전SHA를 재확인해 갱신한다. 제품 변경이 없어 unit/Ruff/Mypy는 재실행하지 않는다.

정상 답변/인용 및 RAG 기능 마감은 미완료다. 다음 후보는 추가 추론 없이 이번 요청에 대응하는 기존 runner 로그의 입력 처리·생성 소요와 timeout 후 종료/취소 증거를 좁혀 확인하는 것이다. 로그가 없으면 미확인으로 남기며 timeout 확대·직렬화 변경·추가 실모델 시험을 자동 진행하지 않는다.

독립 리뷰 완료: 16,384 적용/요청 timeout/모델 종료 미확인을 구분한 결론에 동의했다. 감사121,047ms는 순수 모델 추론 시간이나 전체 클릭 소요가 아니며, 메모리 수치만으로 timeout 원인을 확정하지 않는다. 추가 호출·수정 없이 리뷰했다.

### 2026-10-14 사용자 Ollama 화면 로그 대조—task2 입력 평가 timeout·취소 확인

추가 모델 호출 없이 사용자 첨부의 판독 내용과 기존 실패 감사를 대조했다. 원본 첨부 Library ID는 `libfile_3025030d7db881919783671cf4853077`, 사용자 메시지는 `Sentinel_9d96d4c355d88191aeea83ef3b91db9b`다. 부모 작업이 이미지를 직접 확인해 전달한 화면 판독을 사용했으며, 이 작업이 로컬 runner 로그 파일을 새로 확보한 것은 아니다. 화면 상단 task0은 별도 초기 이벤트로 제외하고 **task2**만 이번 요청과 대조한다.

| task2 화면 관측 | 값 |
|---|---|
| 입력/컨텍스트 | n_ctx_slot=16384, n_keep=4, task.n_tokens=11017, cached_n_tokens=0 |
| 입력 처리 진행1 | n_tokens=1024, progress=0.09, t=20.38s, 50.24tokens/s |
| 입력 처리 진행2 | n_tokens=2048, progress=0.19, t=41.48s, 49.37tokens/s |
| 입력 처리 진행3 | n_tokens=3072, progress=0.28, t=63.44s, 48.42tokens/s |
| 입력 처리 진행4 | n_tokens=4096, progress=0.37, t=86.48s, 47.36tokens/s |
| Ollama HTTP | 2026/10/14 12:16:50 KST, POST /v1/chat/completions, HTTP500, duration=2m0s |
| 취소/해제 | srv stop: cancel task, id_task=2; slot release task2 stop processing, n_tokens=5120, truncated=0 |
| 후속 상태 | srv update_slots: all slots are idle |

12:16:50KST는03:16:50UTC로, 요청 `ffef36a2-4a17-4765-b7aa-6000baf2588f`의 감사 created_at=03:16:50.228015UTC와 같은 초다. 읽기 전용 DB 재대조에서도 동일 구성·배포·모델, failed/provider_timeout, latency_ms=121047, 근거19개를 확인했다. 화면의 runner task ID와 앱 correlation ID는 같은 ID가 아니며, 단일 시험·모델/컨텍스트·입력 길이·시각을 대조해 연결한다. 앱 HTTP504와 Ollama HTTP500은 서로 다른 계층의 관측이다. Ollama500이 먼저 발생해 앱 timeout을 일으켰다는 역방향 인과관계는 주장하지 않는다.

**갱신된 진단:** 이번 요청은 입력 평가가 진행되는 동안120초 timeout에 도달했다. task2의 취소·slot 해제·전체 idle 전환을 보여 주는 직접 화면 증거가 추가됐으므로, 앞 절의 “timeout 이후 실행 중단 미입증”은 초기 관측의 한계로 남기고 이번 task에 대해서는 중단 확인으로 갱신한다. 4096까지의 진행 로그와 해제 시 n_tokens=5120을 구분하며, 후자만으로5120토큰 전부의 평가 완료를 추가 주장하지 않는다. 전체11017토큰 입력 평가나 답변 생성 완료는 확인되지 않았다. task2 해제 로그의 truncated=0과 새 입력11017 보존은 확인됐지만 다른 요청·모든 내부 단계의 무잘림으로 일반화하지 않는다. DB 토큰 필드는 여전히null이며, 화면 수치를 DB 관측값으로 대체하지 않는다. 이 결과는 과거 별도 종료미확인 실행이나 ISSUE-00013을 해결한 증거가 아니다.

취소·idle은 프로세스 종료와 구분한다. 앞선 후속 읽기 전용 관찰에서는03:21:51UTC /api/ps models=[], 03:22:54UTC에 당시 runner PID117184 미존재를 확인했지만 정확한 프로세스 종료 시각·사유는 확보하지 못했다. 이번 task 취소 확인에는 해당 사후 프로세스 관찰 대신 위 task2 로그를 사용한다. 관측 RAM 최저0.764GiB는 보존하며 메모리 부족을 timeout의 확정 원인으로 삼지 않는다.

**최소 변경 후보—아직 미적용:**

1. HTTP 제공자 전용 입력 직렬화에서 각 근거의 group_id는 그대로 두고 여기에 이미 포함된 document_id/asset_version_id/projection_id/chunk_id 4개 중복 필드를 생략한다. 반복 context_notice는 최상위1회로 옮기고 JSON 구분자 공백을 제거한다. 원문·evidence UUID·그룹 경계·순서·표/위치/출처 문맥과 서버의 원본 근거·인용 검증을 유지한다. 이전 메모리 내 비교에서 사용자JSON은16,277자/17,117바이트→10,056자/10,896바이트로, UTF-8 **36.34%** 감소했다. 전체 HTTP JSON은20,798→14,201바이트다. 역변환 동일성, 표/2그룹 합성 사례, 동일 mock 답변 인용 검증 및 잘못된 UUID/날짜 거부를 확인했으나 실제 모델 의미 이해·토큰/시간 절감은 미검증이다. 공유 serializer나 다른 제공자 계약까지 바꾸는 범위로 확대하지 않는다.
2. 별도 로컬 Gemma 배포 버전에서 timeout_seconds **120→360초**를 유한한 비교 후보로 검토하고 retry=0을 유지한다. 이번 입력11017을 관측47.36tokens/s로 나눈 약233초는 입력 평가만의 단순 산술 추정으로, 로딩·출력 생성·메모리 변동을 포함한 완료 예측이 아니다. 360초는 성공/메모리 안전성이 검증된 운영값이 아니다. 현재 HTTPX 설정은 연결/읽기/쓰기/pool 작업별 timeout이며 엄격한 전체 요청 deadline은 아니므로, 전체 경과 상한이 필요하면 별도 설계·검증 대상으로 명시한다. 짧은/외부 제공자에 전역 적용하거나 무제한 대기로 바꾸지 않는다.

공백만 제거한 후보의 사용자JSON 바이트 절감은4.38%였으므로 충분한 해결책으로 제시하지 않는다. 위 두 변경을 한 번에 적용하면 효과를 분리할 수 없으므로 각각 승인·검증 범위를 나눠야 한다. 현재 승인은 문서 진단 갱신과 제안까지이며 제품 코드·설정·서비스 변경·새 실모델 시험은 하지 않았다. 정상 답변·인용 및 RAG 기능 마감은 여전히 미완료다.

독립 리뷰는 입력 평가 timeout/취소·idle 결론,5120 해제 수치와 평가 완료의 구분,HTTP500/504 계층,36.34% 바이트 감소와 토큰/시간 절감의 구분,360초 후보의 미검증 한계에 동의했다.

### 2026-10-14 HTTP 전용 중복 메타데이터 축소 구현

사용자가 최소 입력 축소와 이후 로컬 시험 배포 timeout120→360초 분리 검증을 승인했다. 원문·인용 UUID·group_id·순서·표/출처 문맥·서버 검증은 유지한다. 기존 미커밋 변경을 보존하고 HTTP 어댑터 및 기존 테스트만 수정한다. 작업은 중간 위험의 기능 수정이며 요구/테스트 설계·RAG·AI·Python 역할과 독립 코드 리뷰/검증 역할을 분리한다. UI·DB 스키마·인프라·권한 변경은 제외한다.

구현 순서: HTTP 요청 경계의 보존/축소/기존 모드 테스트 RED → 전용 직렬화 구현 → 관련 unit·Ruff·Mypy → 독립 리뷰. 공유 serializer와 다른 제공자는 유지한다. 새 영구 계획 파일은 만들지 않는다. 백엔드는 자동 reload가 없어 코드 검증 후 사용자 재시작 인계가 필요하며, 첫 실모델 시험 전까지 timeout120/retry0을 유지한다. 두 번째 단계의360초는 정확한 시험 배포에만 적용할 후보이며 아직 설정을 바꾸지 않는다. 실모델은 단계당 동일 질문 최대1회/총2회, 매회 사전 자원 확인·메모리 감시·완료/취소 확인을 거친다. HTTP 작업별 timeout과 전체 관찰 경과 상한을 구분하고 무제한 기다리지 않는다.

**구현 결과:** `openai_compatible.py`의 HTTP contextual 생성 입력만 압축했다. 공유 `evidence_payload`가 만든 새 사본에서 group_id에 중복된4개 ID를 제거하고 context_notice를 최상위1회로 옮긴다. JSON 구분자만 줄이며 문자열 내부의 공백/개행은 보존한다. schema1/2·OpenAI/Ollama dialect에 적용하고 비문맥 입력의 기존 JSON 바이트 표현은 유지한다. CLI·Responses·Transformers 제공자와 서버 GroundingEvidence/CitationValidator는 변경하지 않았다. 변경 전 어댑터 SHA는 `5257cc6efb8e68f4ea66da9aaec7fd1a3ebb496c2dddbc70c36701a3ea48c485`, 변경 후는 `46da444733d7d5253f8e420088b3f7b35a5c5851158b63b48ac61f3011675eba`다.

| 실제 실행한 검증 | 결과 |
|---|---|
| 신규 테스트 RED: `pytest tests/unit/labs/rag/generation/test_openai_compatible.py -k "http_context_compaction or http_compaction" -q` | 최상위 context_notice 없음으로4실패·기존 비문맥2통과 |
| 같은 어댑터 파일 전체 pytest | 134통과 |
| `pytest tests/unit/labs/rag/generation tests/unit/labs/rag/search tests/unit/labs/rag/conversations -q` | 1523통과·4skip, 39.17초. Starlette/httpx 기존 deprecation warning1개 |
| 변경한 source/test2파일 `ruff check --no-cache` | 통과 |
| `mypy --no-incremental --cache-dir <Temp> src/ai_workshop` | 470파일 검사, 범위 밖 오류1개로 실패(아래 기록) |
| `mypy --cache-dir <Temp> src/ai_workshop/labs/rag/generation/openai_compatible.py` | 변경 source1파일 통과 |
| 독립 리뷰/검증 | 이번 변경 전 사본과 비교해 결함 없음. 어댑터134통과·빈근거/None provenance × schema1/2 × 두dialect 추가mock8통과 |
| `git diff --check`, 기존 두 문서 UTF-8·상대 파일 링크·WORKBOARD 최근 완료 개수 | 통과, 최근 완료5개 유지 |

검증은 기존 backend venv의 `python -B`로 수행했고 HTTPX MockTransport를 사용했다. 신규 영구 파일은 만들지 않았으며 비교용 사본·Mypy 캐시는 OS Temp에만 생성했다. 실모델 호출0회·DB/Elasticsearch/Docker 상태 변경0회·재시작0회·설치0회·commit/push0회다. 테스트는 원문/두그룹/순서/표셀/위치/출처/section_path의 역변환 동등성, 공유 serializer 비변이, 기존 질문·history 보존, 정상 날짜 인용 수용과 미허용UUID/잘못된 날짜 거부를 검증한다. 이전36.34%는 앞선 오프라인 표본의 바이트 감소이며 이번에 실모델 토큰·지연 개선을 측정한 값이 아니다.

**별도 발견/전역 검사 차단:** `evaluation/generative_workflow.py:156`은 `get_search_service(session, self.settings, resolver, codex)`를 호출하지만 현재 `search/api.py:79`에는 필수 `local_model_host`가 있다. 이번 수정 파일 밖의 기존 호출 불일치로 Mypy `[call-arg]`가 발생했으며 이 작업에서 고치지 않았다. 생성 평가의 직접 호출 경계 수정·회귀 검증을 별도 후보로 남긴다. 이 결함의 관리자 문제 DB 등록은 **미완료**이며 번호를 임의 발급하거나 과거 ISSUE-00013을 해결 처리하지 않았다.

**인계/미실행:** 기존 실행 기록의 API는 reload 없이 실행되므로 코드 반영을 위한 API 재시작이 필요하다. 최신 CIM 프로세스 조회는 접근 거부여서 재확인하지 못했고 승격·우회·강제 종료하지 않았다. 사용자가 기존 API 실행 창에서 정상 종료 후 [본래 실행 명령](../runbooks/local-development.md#3-호스트-애플리케이션-실행)으로 다시 시작한 뒤, 최신 코드·구성·모델·메모리를 확인하고 timeout120/retry0에서 발행일 질문1회만 시험한다. 종료/취소·idle을 확인한 이후에만 정확한 로컬 시험 배포의360초 단계를 분리한다. timeout 설정은 아직120 그대로이며 전체 경과 상한/메모리 중단 기준을 준비하기 전 실모델을 호출하지 않는다. 정상 answered/인용·실제 토큰/시간·메모리 안전성·360초 비교는 모두 미검증이다.


### 2026-10-14 입력 축소 반영 재시작 후 사전 검사—메모리로 제출 보류

사용자가 백엔드 재시작 완료를 알리고 승인된 두 단계 비교의 재개를 요청했다. 첫 단계120초/retry0에서 동일 사실 질문 최대1회, 처리 종료 확인 뒤 필요할 때만 정확한 로컬 시험 배포360초/retry0에서 최대1회이며, 메모리 위험 또는 진행 중 추론이 있으면 추가 시험하지 않는 조건이다. 이번 작업은 비추론 사전 확인과 독립 결과 검토로 제한됐고, 아래 자원 상태 때문에 질문 제출 전에 멈췄다.

- **코드/프로세스:** 어댑터 SHA `46da444733d7d5253f8e420088b3f7b35a5c5851158b63b48ac61f3011675eba` 불변, source mtime2026-10-14T04:42:30.109828UTC. psutil로 새 API PID148096의 시작04:53:14.718874UTC, cwd `C:\projects\ai-workshop`, `uvicorn ai_workshop.main:app`, reload없음을 확인했다. 이전 CIM 조회 거부와 별개로 이번 psutil 메타데이터 조회는 성공했다. 소스 수정 이후 본래 경로에서 새 프로세스가 시작된 반영 조건을 확인했으며 실제 제공자 wire 캡처나 실행 중 함수 introspection을 했다는 뜻은 아니다.
- **API/인증:** 코드에 정의된 `/api/v1/health`·`/api/v1/ready` 각HTTP200. 최초 루트 `/health`·`/ready` 요청의404는 잘못된 점검 경로였고 코드 확인 후 정정했다. 기존 Chrome 작업소 새로고침에서 인증된 마스터 세션을 확인했다. Swagger의 기존 동일 발행일 질문·configuration428992ab·합성 workspace2292dfa0/document415011bf·top_k10·experimental/include_diagnostics=true·history=[]를 확인했고 **Execute를 누르지 않았다**. 기존 표시504/correlationffef36a2는 이전03:14 시험 결과이며 신규 결과로 사용하지 않는다. 토큰/쿠키 조회 없음.
- **구성:** READ ONLY SELECT/rollback으로 version89351388→profilea07c2838→deployment1904891a, is_default=false/local/externalfalse/gemma4:e2b-it-q4_K_M/timeout120/retry0/schema2/output512/temperature0 확인. 해당 구성 감사 누적11건으로, 이번 실행 결과로 새 감사 레코드를 제시하지 않는다.

| UTC 사전 관측 | 가용 물리RAM | 사용률 | Ollama |
|---|---:|---:|---|
| 04:58:56 | 2.350GiB | 90.0% | version0.40.3, ps models=[] |
| 05:00:04 | 1.682GiB | 92.8% | 새 ps 조회 없이 RAM 측정 |
| 05:00:31 | 1.634GiB | 93.0% | ps models=[] |
| 05:00:42 | 1.630GiB | 93.1% | ps models=[] |

총 물리RAM은23.505GiB다. 모델 미적재 상태에서 가용량이2.35→1.63GiB로 감소했고, 이전16,384 시험에서는 시작3.69GiB 대비 최저0.764GiB를 관측했다. 이 과거 차이를 다음 시험의 확정 필요량으로 계산하지는 않지만, 현재 여유로 같은 적재·실행을 안전하게 감당한다는 근거가 없어 사용자의 메모리 위험 보류 조건을 적용했다. OOM 또는 commit 고갈을 진단한 것이 아니며, ps 빈 목록만으로 모든 원격 작업의 슬롯 idle을 증명했다고 주장하지 않는다.

**실행 수/남은 검증:** 검색POST0·임베딩0·추론0·모델로드0·360초변경0이다. 새 답변/인용/요청UUID/감사/입력길이/토큰/처리시간/입력잘림 결과는 없다. 로드 모델이 없어 실제 context16,384의 이번 실행 적용은 미검증이다. 승인된 두 번의 시험은 소비하지 않았으며 자동 재시도·자동 대기를 예약하지 않았다. HTTPX120초는 작업별 timeout이고 전체 경과 deadline이 아니라는 구분을 유지한다. 이번에는 제출 자체가 없어 요청 대기·취소 경로를 실행하지 않았다.

서비스 재시작·강제 종료·DB설정/활성기본값/보호설정 변경·설치·commit/push 없이 기존 WORKBOARD와 본 기록만 갱신한다. 제품 코드가 같고 실행 검증 전에 보류했으므로 pytest/Ruff/Mypy를 재실행하지 않았다. 전역 Mypy의 별도 평가 호출 인자 누락1건은 그대로 남는다. 다음은 사용자가 메모리 여유를 확보한 뒤 사전 상태를 다시 확인하고, 기존 승인 범위에서120초 단일 시험부터 재개하는 것이다. 360초 단계는 첫 결과·원격 종료 확인 및 자원 안전 조건을 충족할 때만 진행한다.

독립 검토는 전달된 사전 증거와 위험 시 보류 조건을 대조해 제출 전 중단 판단에 동의했다. 재시작/경로/해시는 코드 반영의 간접 근거이고 실모델 wire·성공 증거는 아니라는 한계를 확인했다. 검토자가 추가 조회·변경·모델 호출을 수행한 것은 아니다. 문서 UTF-8·상대 파일 링크·WORKBOARD 최근완료5개·diff 공백 검사 및 어댑터 SHA 불변을 확인한다.


### 2026-10-14 입력 축소120초·360초 분리 실모델 비교

사용자가 메모리 확보 후 재개를 요청했다. 기존 승인인 단계별1회/총2회만 진행하며 메인은 실행·추적, 독립 검토자는 관측 해석을 검토한다. 첫 성공이면360초를 생략하는 조건이었으나 첫 요청이 timeout이라 종료·메모리 조건을 확인한 뒤 두 번째 단계를 준비했다. 아래 시험 외 추가 추론은 금지한다.

**1단계 — 기존120초/retry0:** 코드SHA `46da444733d7d5253f8e420088b3f7b35a5c5851158b63b48ac61f3011675eba`, 새API PID148096·본래cwd·health/ready200, 기존 Chrome 인증과 동일 질문/합성 공간·문서/top_k10/history=[] 확인. 05:04:57UTC 가용RAM4.401GiB, 제출 준비05:06:16 4.010GiB, Ollama models=[]였다. 기존 config428992ab/version89351388/profilea07c2838/deployment1904891a 연결과 local/externalfalse/timeout120/retry0를 READ ONLY SELECT로 확인했다. 05:06:36.163UTC 검색 Execute를1회 클릭했고 loading/disabled를 확인했다.

- HTTP504/provider_timeout, correlation `49b5ef0c-c72b-41c9-a68b-25a54cb1da78`. 헤더Date05:06:37UTC. 감사1건 추가(11→12), failed/provider_timeout, latency121265ms, created_at05:09:28.443322UTC, execution_id=null, 입출력/제공자보고토큰4필드 모두null. 답변·인용은 반환되지 않았다. 감사latency는 전체 클릭부터 소요나 순수추론시간과 다르다.
- 6초 간격 비추론 모니터43표본(05:06:32–05:10:44): 실제Gemma context_length16384는05:07:44부터 관측했다. 최소 가용RAM0.675GiB/97.1%는05:07:38, 이후2–3GiB대로 회복했다. size276247346/size_vram0은 ps API값이며 전체상주메모리로 해석하지 않는다. 모니터의 runners 필드는 이 단계에서 ollama.exe만 수집했으므로 별도 llama-server의 메모리라고 표시하지 않는다.
- 별도05:08:14 psutil 관측: llama-server PID145812, 시작05:07:28.996767UTC, RSS3019.7MiB/private5972.8MiB. 05:10:32 ps models=[];05:10:56 PID145812 미존재/가용5.749GiB. 따라서 해당 실행 프로세스가 더는 남지 않음을 확인했다. 정확한 취소 사유·slot 해제 시점·완료 토큰의 runner 로그를 확보한 것은 아니다. 강제 종료/재시작하지 않았다. HTTP 요청은240초 전체관찰상한 전에 종결됐고 이후 유한한 상태 관찰을 마쳤다.
- 새 감사의 근거19개와 순서는 이전ffef36a2 시험과 같았다. 감사ID 순서대로 READ ONLY 원문·메타데이터를 읽고 현재 serializer로 재구성한 사용자JSON은16277자/17117UTF-8바이트→10056자/10896바이트(36.34% 감소), 근거691자/1그룹이었다. 실제 wire 캡처나 토큰 측정이 아니다. 최초 읽기 전용 보조조회에서 asset_id 열 이름을 잘못 사용해 실패했고, 정본 모델의 document_id로 정정해 성공했다. 제품 오류나 DB변경은 아니다.

**2단계 준비 — 정확한 로컬 시험 배포만360초/retry0:** 인증된 기존 Swagger API로 deploymentidentity `62523fae-9332-4ca4-8227-c34e13c95841`의 v2 `97327b16-30e3-41b4-88a3-9f64a55056db`를 등록했다. DB에서 v1/v2의 id/version/생성·갱신시각을 제외한 차이가 timeout_seconds120→360뿐임을 확인했다. v1은 보존했다. 연결검사는 비추론 모델 목록 조회로 ready/정확 모델ID를 확인했다.

- 같은 생성프로파일 이름의 v2 `c788a65e-c88c-45cd-8785-bbb500bf4ad3`를 등록했다. config는 timeout_seconds만360이고 prompt rag-answer-v2/context-v1, schema2/output512/temperature0, evidence8그룹/32단위/12000자, history4턴/1024토큰과 citation required를 그대로 유지한다. is_default=false. 생성직후 응답의 readiness=false는 등록응답 serializer의 기본 표현이며 이후 구성 readiness를 실제 확인했다.
- 비교config `54ef3fd7-6dae-4549-982d-813a3b16f63c`/version `f5b0cbe6-d656-4f1d-9620-dbce3c056360`를 비기본·비시스템·experimental/pending으로 저장했다. processing207/indexing201/retrievale07f88a6 및 기존 합성 공간을 유지한다. 답변정책 semantic0.9/keyword0.5/provenance필수/separate_sources 유지. search/answer/service_ready=true 확인. 기존120초 구성과 활성 도메인/전역기본값은 변경하지 않았다. 이는 별도 서버·DB·계정·색인을 만든 것이 아닌, 기존 환경의 불변 설정 버전을 연결한 비교 항목이다.
- 05:16:10UTC ps models=[]·이전PID미존재·가용RAM4.679GiB 확인, 기존검색UI에서 configuration_id만비교구성으로바꾸고 같은질문/범위를확인했다. 05:17:03.399UTC Execute를단1회클릭했다. 이로써총실모델제출2회가되어추가시험하지않는다. HTTP 작업별360초와전체관찰480초를구분하고, 위험표본이면정상요청취소를검토한다. UI취소만으로원격종료를단정하지않는다.

**2단계 결과 — 실패:** HTTP502/provider_invalid_response, correlation `f063f679-4795-4318-8165-d016c5551fee`. 헤더 Date05:17:06UTC, 감사 created_at05:21:16.904002UTC/latency224021ms, failed/provider_invalid_response, 해당 구성 감사1건이다. execution_id와 입출력/제공자보고토큰4필드는 null이며, 근거19개와 순서는 1단계와 같다. Execute가 다시 활성화된 것을05:22:07UTC 확인했다. 정상 답변·인용은 반환되지 않았다. 감사 지연은 전체 UI 소요나 순수 모델 추론시간이 아니다.

- 최신 API stderr `api-restart-20261014-135314.stderr.log`에서 같은 correlation의 `provider_response_rejected stage=finish reason=length`를 확인했다. 어댑터는 strict 응답의 finish_reason이 stop이 아닐 때 length를 해당 고정 분류로 기록하고 거부한다. 따라서 timeout 연장 후에도 제공자가 길이 제한 종료를 보고해 불완전 응답으로 거부됐다는 것까지 확인한다. output512 설정은 유지됐지만 실제 출력 토큰 수·부분 응답·reasoning 소비량은 확보하지 않았으므로 512토큰을 정확히 생성했다거나 JSON/인용 자체가 잘못됐다고 단정하지 않는다.
- 실제 context_length16384를05:17:47UTC부터 관측했다. 최소 가용RAM0.528GiB/사용97.8% 후 회복했다. 해당 llama-server PID83412의 관측 최대 RSS2836.1MiB/private6001.4MiB는 서로 더하는 값이 아니다. 05:22:18부터 ps models=[]와 runner 부재,05:22:54 별도 psutil에서 PID83412 미존재를 확인했다. 정확한 slot 해제 시점/취소 사유를 확보한 것은 아니다. 메모리 여유가 매우 적었던 표본이 있어 메모리 안전성이 검증됐다고 하지 않는다.
- 요청은 전체480초 관찰 상한 전에 종결됐고 수동 요청 취소·강제 종료·서비스 재시작은 하지 않았다. 읽기 전용 보조 모니터는 최대83회로 제한되어 종료코드0으로 끝났다. 종료 표시 파일은 이후 OS Temp에 기록됐으며 제품 프로세스를 종료시키지 않았다. 마지막 모니터 출력 일부가 도구 출력 제한으로 잘려 전체83개 원문을 보존했다고 주장하지 않는다. 최저 메모리·실제 컨텍스트·처리 종료의 앞선 표본은 별도로 확보했다.

**마감과 남은 범위:** 허용된 실제 질문은 정확히2회(120초1회/360초1회)이며 추가 추론·외부 LLM 호출은 하지 않았다. 두 요청 모두 실패했고 정상 answered/인용·실제 입력/출력 토큰·입력 잘림 여부·운영 수용은 미완료다. 실제 근거를 재구성한 입력 바이트 감소36.34%를 토큰 절감률 또는 성공/지연 개선으로 확대하지 않는다. 기존120초 설정은 보존됐고 비기본360초 배포 버전·draft 생성 프로파일·experimental 비교 구성만 기존 환경에 남긴다. 활성 도메인/전역 기본값 변경·승격·마이그레이션·Elasticsearch/Docker 변경·설치·commit/push는 하지 않았다.

이번 실모델 단계에서 제품 source/test는 수정하지 않았으므로 앞선 unit1523통과/4skip·Ruff·변경 파일 Mypy·독립 mock 리뷰 결과를 그대로 연결하며 재실행 결과로 표시하지 않는다. 전체 Mypy의 별도 평가 호출 누락1건과 관리자 문제 DB 등록 미완료는 유지한다. 다음 후보는 추가 실추론 없이 기존 로그와 출력 예산/종료 처리의 코드·mock 경계를 점검하는 것이며, timeout·output 상한의 자동 증액이나 새 실제 질문은 실행하지 않는다.


독립 검토자는 전달된 실행 증거를 대조해 두 시험 모두 정상 답변·인용에 도달하지 못했다는 마감과 timeout/length 구분에 동의했다. 입력 바이트 재구성을 토큰·속도 개선으로 확대하지 않고, 메모리 최저값을 OOM 또는 안전성 확보로 해석하지 않는 한계를 확인했다. 검토자는 추가 조회·변경·모델 호출을 수행하지 않았다. 다음 후보인 출력512 예산과 구조화 응답 계약 검토에서도 length 거절을 완화하거나 불완전 응답을 수용하지 않는다.

마감 검사: 두 문서 UTF-8 읽기·상대 파일 링크 존재, WORKBOARD 최근 완료5개, `git diff --check` 통과. source/test SHA는 앞선 구현 검증 이후 불변임을 확인했다. Git의 기존 LF→CRLF 안내는 공백 오류와 구분한다.


### 2026-10-14 출력512·종료 처리 코드/mock 진단

승인 범위는 제품 코드·배포 설정을 바꾸지 않고 최신 length 실패의 관측 한계, 최소 정상 답변과 프롬프트 요구를 조사하는 것이다. ai-model-or-runtime 역할 기준선을 확인하고 메인이 AI/백엔드 진단, 별도 리뷰어가 소스 해석을 담당했다. .agents/skills 경로는 현재 존재하지 않아 새로 만들지 않았다. 기존 dirty/untracked86개 상태를 정리하지 않았다.

**실제 증거:** READ ONLY SELECT/rollback으로 correlation `f063f679-4795-4318-8165-d016c5551fee` 감사1건의 failed/provider_invalid_response·224021ms·근거19개와 토큰4필드 null을 재확인했다. 같은 correlation의 최신 API 로그는 `stage=finish reason=length`다. 전체 응답 JSON은 읽혔지만 어댑터 `_message_content`는 message·reasoning·content 검사 전에 finish_reason을 거부한다. 따라서 실제 content의 존재/완결성, reasoning 필드 존재와 사용량 제공 여부는 이 로그로 확인할 수 없다. 원문 응답을 캡처한 증거도 없다. 확인한 dev-logs에는 Ollama/llama 이름의 로그가 없고 기본 Local/Ollama 로그 디렉터리도 없었다. 다른 경로의 로그 전체 부재를 주장하지 않는다.

**토큰 관측 공백:** `_chat_completion`은 profile.max_output_tokens512를 max_tokens로 전달한다. `_metadata`는 성공에서도 input_tokens/output_tokens를 None으로 고정하고 usage를 읽지 않는다. 실패 예외는 code/retryable만 갖고 사용량을 전달하지 않는다. 감사의 null은 제공자가 usage를 보내지 않았다는 증거가 아니다. 답변 generate에는 reasoning_effort가 없고 Ollama schema2 contextualize에만 none이 있다. 실제 reasoning 활성·소비량 또는 512토큰 전량 소모는 미확정이다.

**최소 정상 구조와 프롬프트:** 합성 발행일 근거와 실제 시험에서 사용한 UUID 형식의 단일 인용으로 `schema_version:2/status:answered/claims:[{text,evidence_ids}]`를 구성했다. text가 `발행일은 2026-09-03입니다.`인 compact JSON은138자/UTF-8 152바이트로 현행 어댑터와 CitationValidator를 통과했다. 이는 요구를 충족하는 단일 사실 표본이며 전역 최소 길이 증명이나 실모델 출력이 아니다. 프롬프트는 모든19개 근거의 인용, 여러 주장, 장문 해설을 필수로 요구하지 않는다. 실제 조립 규칙의 system prompt는885자/1349바이트, response_format JSON은1068바이트였다. 간결성 지시/주장 수 상한은 없지만 이것이 이번 length의 원인이라는 증거는 없다. JSON Schema는 출력 형식 제약이며 그1068바이트를 답변에 복제할 필요는 없다.

**토크나이저 한계:** transformers/tokenizers/sentencepiece 패키지는 설치돼 있지만 기본 Hugging Face cache, 프로젝트 모델 캐시, C:/AI/Ollama 및 OllamaModels에서 독립 Gemma tokenizer.json/model/config를 확인하지 못했다. 프로젝트의 E5 토크나이저를 대체 사용하지 않았다. GGUF 내장 토크나이저의 부재를 주장하지 않으며 현재 설치된 llama_cpp/gguf Python reader도 없다. 다운로드·설치·모델로드·토큰화 API 호출 없이 종료했고 문자/바이트를 토큰으로 환산하지 않았다. 따라서 512가 충분하거나 부족하다는 수치 결론은 내리지 않는다.

| 실제 실행한 로컬 검증 | 결과 |
|---|---|
| 기존 `test_openai_compatible.py`에서 `-k "requires_explicit_normal_completion or reasoning or answer_contract_prompt or wire_answer_schema"`, `python -B -m pytest -p no:cacheprovider` | 33통과/101선택제외,0.75초,exit0 |
| 메모리 내 HTTPX MockTransport7회, max_tokens512·합성usage123/456 부여 | stop 정상문장: answered·인용통과·토큰None. length 정상JSON/부분JSON: 둘 다 비재시도 오류. stop 부분JSON: 오류. 잘못된 날짜/UUID: 각 exact_value_not_supported/evidence_not_allowed. contextualize만 reasoning_effort=none. 각1요청 |
| reasoning 합성 canary 로그 확인 | 거부 로그에 원문 canary 없음 |
| 독립 소스 리뷰 | length 선행 거부·성공 usage 미수집·최소1주장 가능·reasoning 설정 범위에 동의. 리뷰어 추가 테스트/실추론/변경 없음 |

**최소 수정 후보만 제안:** (1) 제공자 응답의 유효한 정수 사용량 및 필요한 안전한 존재 여부만 본문 검증 실패 전후에 전달·감사할 수 있도록 진단 경계를 설계한다. 본문·비공개 reasoning·토큰 값 배열은 저장하지 않는다. (2) 질문에 필요한 주장만 간결히 작성하도록 prompt 후보를 만든다. (3) 답변 생성의 reasoning 비활성 요청은 지원·효과가 확인되지 않은 별도 후보로 두고 출력 예산 자동 증액과 묶지 않는다. 모두 미구현이다. length를 성공으로 바꾸거나 잘린JSON을 복구하고 스키마/인용 검증을 완화하지 않는다.

이번 단계는 실제 모델/임베딩 호출0·설정/서비스 변경0·새 영구파일0이다. 기존 WORKBOARD와 본 기록만 갱신한다. 제품 source/test SHA 불변, 문서 UTF-8·상대 파일 링크·최근 완료5개·diff 공백 검사로 마감한다. 제품 코드 미변경이므로 Ruff/Mypy/전체pytest는 재실행하지 않았고 기존 별도 Mypy 오류를 수정하지 않았다.


### 2026-10-14 HTTP 사용량·종료 사유 진단 보완 계획

사용자가 진단 보완과 기존 비기본360초/retry0 구성의 동일 사실 질문 추가1회를 승인했다. 재시작이 필요하면 mock/리뷰 후 인계하고 기다린다. 추가 시험은 아직0회다. 기존 미커밋 상태를 OS Temp에 사본/해시로 보존하고 각 쓰기 직전 확인한다.

- [x] 기존 어댑터 테스트에 성공/length/본문 오류의 usage 전달, 안전한 종료 사유·숫자 정규화, 잘못된usage/비공개canary/재시도 방지 RED를 추가한다.
- [x] openai_compatible.py에서 본문검증 전 safe diagnostics를 수집하고, execution.py의 선택적 실패 메타데이터로 기존 audit 입력/출력 토큰 전달 경로를 연결한다. finish_reason/추가 usage 수치는 고정형 진단 로그에만 기록하고 DB schema를 추가하지 않는다.
- [x] pipeline.py에서 exact provider/deployment에 결합된 실패 메타데이터만 감사에 전달한다. contextualize+generate 합산과 Integer overflow도 검증한다.
- [x] 관련 generation/search/conversation 회귀·Ruff·Mypy 및 독립 리뷰를 수행한다. unrelated Mypy 기존 오류는 분리한다.
- [x] 코드·검사 결과와 미실행 단일시험을 기록하고 API 재시작 인계에서 멈춘다.

검증 초점은 bool/float/음수/과대값·임의 finish 문자열·usage 누락·응답 파손·실패 원인 보존이다. 스키마/인용/length 거부·output512·reasoning·context16384·입력 직렬화는 그대로 둔다. 본문·비공개 reasoning·자격증명은 로깅하지 않는다.


### 2026-10-14 HTTP 사용량·종료 사유 진단 보완 결과

**변경 범위:** 기존 제품3파일(`generation/openai_compatible.py`, `generation/execution.py`, `search/pipeline.py`)과 기존 테스트2파일(`generation/test_openai_compatible.py`, `search/test_provider_insufficient_evidence.py`), WORKBOARD·본 기록만 수정했다. 각 경로의 backend/src 또는 backend/tests/unit/labs/rag 접두어는 기존 구조를 따른다. 추가 영구파일/DB schema/마이그레이션은 없다. 최초 사본은 OS Temp의 `ai-workshop-usage-diagnostics-k3nl6cqv`와 `ai-workshop-usage-audit-jrftso9s`에 보존했다. 관련 없는 변경은 정리하지 않았다.

- 응답 JSON을 읽은 뒤 본문·종료·스키마 검사 전에 허용된 finish_reason과 usage 수치를 안전한 진단 로그로 남긴다. 성공/length/본문 파싱·스키마 실패에서도 실행별 숫자를 잃지 않는다. input/output은 기존 감사4필드로 전달하고 total/reasoning **토큰 수**와 finish_reason은 correlation ID가 붙은 로그에만 남긴다. 실제 reasoning 내용은 읽거나 저장하지 않는다.
- 사용량은 bool을 제외한 정수0..2**31-1만 허용한다. 누락·잘못된 타입·음수·범위초과는 None이고 문자열 변환/추정은 하지 않는다. finish_reason은 stop/length/content_filter/tool_calls/function_call 또는 고정 missing/other다. 본문·reasoning 원문·자격증명·임의 제공자 문자열은 로그 인자에 넣지 않는다. 기존 서버 설정에서 관측되도록 분리된 response_diagnostics logger의 WARNING 레벨을 사용하므로 이 진단 이벤트 자체는 성공/실패 판정이 아니다.
- 선택적 GenerationProviderError.execution에 정규화 메타데이터만 연결한다. 메타데이터가 없는 기존 예외는 code/retryable 필드 계약을 유지한다. 실패 감사에는 현재 배포/provider/model과 일치하는 값만 전달하고 이전 contextualization 사용량을 보존·합산한다. 독립 리뷰가 발견한 공유 실패 경계의 bool/float/초과값 통과를 추가 정규화로 해결했다. 합계가 DB Integer 범위를 넘으면 None으로 처리한다.
- length·잘린 JSON·스키마/인용 오류는 계속 실패다. 재시도/프롬프트/입력 직렬화/max_tokens·reasoning 설정을 변경하지 않았다. HTTP transport/상태 오류 또는 응답 JSON 자체가 유효하지 않아 파싱되지 않으면 사용량을 복구·추정하지 않는다.

| 실제 실행 검증 | 결과 |
|---|---|
| 어댑터 신규25건 RED → GREEN | 성공 usage None 및 실패 execution 없음으로25실패 →25통과 |
| 실패 감사·합산 초기 RED | 초기15건 execution 미구현/overflow1건 실패. 필드 추가 후 Temp 원본 pipeline 메모리 로딩에서 실질 사용량누락3건/overflow1건 RED 재확인 |
| 독립 리뷰 지적 회귀 RED → GREEN | 잘못된 카운터 보존/합산23실패·19통과 → search 전체142통과 |
| 어댑터+진단 두 파일 | 260통과. 중간 caplog 기존 건수 기대13건은 새 안전 로그를 허용하도록 갱신했고 원문 비노출 검사는 유지 |
| `python -B -m pytest -p no:cacheprovider tests/unit/labs/rag/generation tests/unit/labs/rag/search tests/unit/labs/rag/conversations -q --tb=short` | 최종1595통과/4skip,39.77초, 기존 Starlette/httpx deprecation warning1개 |
| 변경 source/test5파일 `ruff check --no-cache` | 통과 |
| 변경 source3파일 `mypy --cache-dir <OS Temp> ...` | Success: no issues found in3source files |
| 독립 리뷰/재검증 | 어댑터+실패 감사 테스트212통과·비정상카운터6조합/legacy예외 계약 추가 메모리 검증 통과. P2해결, 추가 발견 없음 |

중간 구현 검사에서 line-length5건과 기존 예외 필드 검사1건도 확인해 해당 범위에서 해결했다. 관련 전체 회귀를 다시 실행한 최종 결과만 위에 통과로 표시한다. 전체 저장소/서비스 통합 검사는 실행하지 않았으며 이전 전체 Mypy의 평가 호출 인자 누락1건을 해결 처리하지 않는다. source 미반영 상태에서 실제 모델을 호출하지 않았다.

**인계/대기:** 기존 API는 reload 없이 실행되므로 정상 재시작이 필요하다. 이번 작업에서 서비스 종료/재시작·DB/Elasticsearch/Docker 변경·설치·커밋/푸시는0회다. 사용자의 추가 단일시험 승인은 유효하지만 사용 횟수는0회다. 부모에게 구현·검증 완료를 보고하고 재시작 완료를 기다린다. 이후 새 프로세스/해시·readiness·기존 비기본 config54ef3fd7/versionf5b0cbe6→profilec788a65e→deployment97327b16의360초/retry0·output512·동일 질문/합성 범위·메모리 및 진행 중 처리 부재를 확인한 뒤1회만 제출한다. context16384 관측과 안전한 진단 로그/감사, 정상 답변·인용 또는 기존 실패, 해당 처리 종료를 기록한다. 자동재시도·추가질문·설정증액은 승인하지 않았다.

반영 확인용 어댑터 SHA-256: `8be87006d11a08a19eb80d1c794d6c47b7aff735bf4de148bd394be4daa9234a`. 문서 UTF-8·상대 파일 링크·최근 완료5개·git diff 공백 검사로 마감한다.


### 2026-10-14 진단 보완 재기동 후 사전 검사—메모리로 제출 보류

사용자가 백엔드 재기동 완료를 알리고 승인된360초/retry0 동일 사실 질문 추가1회 재개를 요청했다. 위험하거나 필수 사전 조건이 불충족이면 제출 전에 멈추라는 조건에 따라 **이번 검색POST0회·추가 추론0회로 보류**했다. 승인된1회는 미사용이다.

- 진단 어댑터 SHA `8be87006d11a08a19eb80d1c794d6c47b7aff735bf4de148bd394be4daa9234a`와 source mtime05:42:33.551474UTC 확인. 새 API 서버 PID107440은05:50:23.140099UTC 시작, 본래 cwd, reload없음이다. 부모PID54936은 python launcher 관계이며 별도 API 두 개라고 판단하지 않는다. 새 stderr `api-restart-20261014-145022.stderr.log`의 Started server process107440·startup complete 및 health/ready각HTTP200을 확인했다. 이는 새 프로세스가 수정 이후 본래 경로에서 시작한 간접 반영 근거이며 함수 introspection/wire 또는 실모델 성공 검증이 아니다.
- 총 RAM23.505GiB에서05:52:28UTC 사전 검사 가용2.760GiB/사용88.3%,05:53:28UTC 재확인2.595GiB/89.0%였다. 두 번의 Ollama ps는 models=[]였고 첫 프로세스 검사에 llama-server는 없었다. 앞선 같은360초 시험은 시작4.679GiB에서도 최저0.528GiB까지 내려갔다. 이 과거 감소폭을 확정 필요량이나 OOM 진단으로 사용하지 않지만, 현재 더 작은 여유로 안전성을 입증할 수 없어 제출 전에 멈췄다.
- 기존 Chrome Swagger 탭의 존재만 확인했다. 메모리 조건에서 중단했으므로 새 로그인 유효성 확인·정확한 구성 DB 재조회·질문 입력/Execute는 하지 않았다. 과거 인증·설정 조회를 이번 확인으로 대체하지 않는다. 모델 미적재 상태라 실제 context16384의 이번 적용도 확인하지 못했다.
- 새 usage/finish_reason·감사·답변/인용·처리시간·신규 모델 종료 결과는 없다. 제품 코드·설정·서비스·DB·Elasticsearch/Docker·설치·commit/push를 변경하지 않았다. 재시작은 사용자가 완료한 선행 조치이며 이 사전 검사에서 실행한 것이 아니다. pytest/Ruff/Mypy는 제품 변경이 없어 재실행하지 않았다.

독립 검토자는 전달된 두 메모리 표본과 기존 관측, 사용자 중단 조건을 대조해 보류에 동의했다. 추가 조회·변경·모델 호출은 하지 않았다. 기존 WORKBOARD와 본 기록만 갱신하고 UTF-8·상대 파일 링크·최근 완료5개·diff 공백 검사를 수행한다. 다음은 메모리 여유가 안정적으로 확보된 후 인증·구성·처리 상태부터 다시 확인해 같은 승인 범위의1회를 재개하는 것이다. 자동 대기/재시도는 예약하지 않았다.

### 2026-10-14 사용량 진단 반영 후 승인 단일시험 결과

사용자가 메모리를 확보한 뒤 기존 조건의 동일 사실 질문 추가1회를 재개하도록 요청했다. 질문은 `합성 월간 보고서 SYN-M01의 발행일은 언제인가요?`이며 **06:03:08.098UTC Execute1회만 제출**했다. 승인된 추가 추론 예산은 소진했으며 자동 재시도·추가 질문은 없다. 이번 결과는 안전한 진단 수집 성공과 정상 생성 실패를 구분한다.

**사전 확인:** API PID107440·기존 어댑터 SHA·health/ready200을 확인했다. 새 프론트 탭에서 기존 master 세션을 확인하고 해당 보조 탭은 닫았다. 읽기 전용 SELECT/rollback으로 비기본 configuration54ef3fd7/versionf5b0cbe6→profilec788a65e→deployment97327b16, timeout360초/retry0, output512, 같은 합성 문서 범위와 빈 history를 확인했다. 입력 축소·reasoning 설정을 유지했다. Ollama PID113668은 기존 서버이며 모델 미적재·llama-server 없음이었다. 서버 환경변수 읽기는 AccessDenied여서 우회하지 않았고 context는 적재 후 관측했다. 초기05:59:53UTC 가용RAM4.905GiB에서06:02:06UTC4.033GiB, 제출 직전06:03:06UTC3.960GiB였다. 초기 수치를 제출 시 여유로 사용하지 않는다.

| 실제 확보 결과 | 관측 |
|---|---|
| 응답/진단 연결 | HTTP502, `provider_invalid_response`; correlation `3da1b4ca-f7be-479e-b66d-f0603177b44c` |
| 안전한 제공자 진단 | operation=generate, finish_reason=length, input_tokens=7119, output_tokens=512, total_tokens=7631, reasoning_tokens=None |
| 실패 감사 | status=failed, 같은 오류/correlation/구성·프로파일·배포; input/output 및 provider_reported_input/output 모두7119/512. 해당 구성 감사1→2건, execution_id=null |
| 감사 지연 | 199122ms. 감사 created_at06:07:12.645998UTC이며 UI 전체 대기 또는 순수 추론 시간과 동일시하지 않음 |
| 근거와 모델 | evidence19개·앞선360초 시험과 순서 동일, 적재 후 실제 context_length16384 확인 |
| 정상 답변/인용 | 반환되지 않음. 출력512와 length는 설정된 출력 예산 도달 근거이며 정상 JSON/인용 수용 근거가 아님 |
| 메모리 | 6초 간격62표본, 최저 가용0.337GiB/사용98.6%(06:04:07UTC), 512MiB 미만1표본. 다음 표본2.514GiB로 회복 |
| 모델 처리 프로세스 | llama-server PID114008, 최대 관측RSS4494.4MiB/private5994.8MiB. 두 값을 합산하지 않음 |
| 처리 종료 | 06:08:14UTC models=[]·runner없음,06:08:30UTC PID114008 부재 재확인. 마지막06:09:08UTC 가용6.584GiB·미적재/runner없음 |

새 `api-restart-20261014-145022.stderr.log`의 숫자 진단과 length 거절 및 같은 correlation의 감사가 일치했다. `reasoning_tokens=None`은 정규화된 유효 수치를 확보하지 못했다는 뜻으로0이나 reasoning 미사용을 뜻하지 않는다. 전체512 중 reasoning/최종 본문 비율은 알 수 없다. 제공자 입력7119는 실응답 보고치이며 과거 재구성 바이트 감소율과 연결해 토큰 감소율을 계산하지 않는다. 원문 응답·비공개 reasoning을 진단 기록에 추가하지 않았다.

회복 및 처리 종료와 별개로 **메모리 안전성은 통과하지 않았다**. 낮은RAM 표본만으로 OOM을 진단하거나 감소 전부를 모델에 귀속하지 않는다. 종료 관측을 정확한 slot-release 시각/취소 원인 증명으로 확장하지 않는다. 서비스 kill/재시작·설정 변경 없이 종료를 관측했으며 자체 읽기 전용 모니터만 stop marker로 끝내 exit0을 확인했다.

독립 리뷰는 전달된 증거를 검토해 사용량 수집/감사 확인과 정상 생성 실패의 분리, 출력 예산 도달 해석, reasoning 수치·메모리·지연의 한계 및 추가 호출 중단에 동의했다. 리뷰 과정의 추가 조회/변경/모델 호출은 없었다. 이번 실행 단계에서 변경한 저장소 파일은 WORKBOARD와 본 기록뿐이다. 제품3파일·관련 테스트2파일 해시 불변, 문서 UTF-8·상대 파일 링크·최근 완료5개·git diff 공백 검사를 확인한다. pytest/Ruff/Mypy는 제품 변경이 없어 재실행하지 않았으며 앞 절의 실제 실행 결과만 유지한다. 전체 Mypy의 기존 별도 오류와 관리자 문제 DB 등록은 미완료다.

**남은 경계/다음 후보:** 정상 answered/인용 성공과 메모리 안전성은 미완료다. 추가 추론 없이 출력 예산·reasoning 설정과 메모리 위험 완화 방안을 검토할 수 있다. 설정 증액·reasoning 변경·추가 실시험·기본값 승격은 하지 않았다. 이번 단계의 설치·마이그레이션·DB/Elasticsearch/Docker 관리 변경·commit/push·교재/예약 변경도 없다.

### 2026-10-14 시험용 answer thinking 설정의 수정 전 범위 확인

사용자가 현재 비기본 시험 구성 answer에만 reasoning_effort=none을 전달하는 최소수정·mock 검증을 승인했고, 스키마/DB마이그레이션이 필요하면 먼저 보고하도록 지정했다. 조사 결과 기존 설정만으로는 이를 적용할 수 없어 제품 수정 전에 범위를 보고했다.

- generation/domain.py의 GenerationProfile에는 answer reasoning 필드가 없고 generation/profile.py는 generation의 timeout/max_output_tokens/temperature/response_schema_version만 읽는다. JSON에 임의 키를 저장해도 요청에 전달되지 않는다.
- runtime_resolver.py의 기존 설정은 endpoint별 dialect이며 프로파일별 선택값이 아니다. openai_compatible.py의 rewrite 조건을 answer까지 넓히면 다른 Ollama schema2 프로파일도 바뀌므로 승인 범위에 맞지 않는다. UUID/모델명을 업무 코드에 고정하지 않는다.
- 최소 후보는 선택적 generation.answer_reasoning_effort 설정(미설정 또는 none)의 검증·프로파일 변환·로컬 Ollama schema2 answer 요청 매핑이다. 미설정은 기존 동작을 유지하고 비지원 조합은 명시적으로 거절한다. 이는 애플리케이션 설정 계약/도메인 필드 변경이다. rag_profiles.config는 JSON 컬럼이므로 DB DDL/마이그레이션은 필요하지 않다. 현재 시험 구성에 실제 적용하려면 별도 프로파일 버전/구성 연결 반영도 구분해야 한다.
- 독립 리뷰어가 기존 설정으로 불가·공유 dialect 영향·새 선택 설정 계약 필요·DDL 불필요 및 사전 보고 경계를 확인했다. 리뷰는 읽기 전용이며 추가 모델 호출/변경은 없다.

이번 단계는 제품/테스트/설정/DB 변경0회이며 TDD RED·mock·Ruff·Mypy를 실행하지 않았다. 기존 WORKBOARD와 본 기록만 갱신하고 UTF-8·상대 링크·최근 완료5개·git diff 공백 검사를 수행했다. 서비스 재시작·설치·실추론·commit/push도 없다. **지금은 재시작할 변경이 없다.** 선택 설정 계약 구현 후에는 reload 없는 API의 재시작이 필요하지만 이번 승인에는 포함되지 않는다. 출력512·입력·timeout360/retry0·rewrite·엄격 스키마/인용 검증은 그대로다. 사용자의 사전 보고 조건에 따라 코드 구현은 아직 미착수이며 기존 length 실패와 최저RAM0.337GiB의 미해결 상태를 유지한다.

### 2026-10-14 시험용 answer thinking opt-in 구현·검증

부모가 선택적 설정 계약이 이미 승인된 최소 수정 범위임을 명시해 구현을 계속했다. 추가 승인을 반복 요청하지 않았다. 기존 워킹트리는 보존했으며 변경 전11개 대상 파일과 status를 OS Temp `ai-workshop-answer-thinking-3b4qpifi`에 보관하고 쓰기 직전 원본/해시를 확인했다. 중간 위험의 요구/설계·Python/AI·RAG·테스트 설계는 메인이 맡았고 독립 리뷰/교차경계 mock 검증은 별도 담당이 수행했다. DB 컬럼·UI·인프라·권한 구현 역할은 범위 밖이다.

**구현 파일과 계약:**

- `backend/src/ai_workshop/labs/rag/models/domain.py`: 선택적 `generation.answer_reasoning_effort`의 키 생략 또는 정확한 문자열 `none`만 허용한다. null/bool/숫자/다른 문자열/배열/객체 및 schema2가 아닌 명시 설정은 거절한다.
- `backend/src/ai_workshop/labs/rag/generation/domain.py`: 선택 필드의 기본값은 None이다. 명시 설정은 local 위치의 local_openai_compatible Deployment·schema2만 허용한다. 기존 미설정 프로파일/다른 provider는 유지한다.
- `backend/src/ai_workshop/labs/rag/generation/profile.py`: 기존 JSON config에서 검증한 설정을 정확한 프로파일에 전달한다.
- `backend/src/ai_workshop/labs/rag/generation/openai_compatible.py`: 명시 opt-in에 대해 Ollama dialect를 요구하고 answer POST `/v1/chat/completions`에 `reasoning_effort="none"`을 추가한다. rewrite의 기존 none과 입력 직렬화·response_format·출력 상한·timeout/retry·엄격한 응답/인용 검증은 유지한다. 비지원 dialect는 HTTP 전 기존 안전 오류 generation_schema_not_supported로 거절한다.
- 테스트는 기존 `models/test_profiles.py`, `generation/test_profile_resolution.py`, `generation/test_openai_compatible.py` 세 파일에 추가했다. 모델명/UUID 고정 선택이나 전역 기본 변경은 없다.
- 문서는 본 기록·WORKBOARD 외 기존 RAG design과 ADR-0009에 선택 계약/수용 경계를 반영했다. 새로운 UI·DB열·마이그레이션은 없다.

| 실제 실행 검증 | 결과 |
|---|---|
| 신규 answer_reasoning 테스트 최초 RED | 34실패/1통과. 설정 미검증·전달 필드 부재·매핑 미구현을 확인했다. 일부 fixture 오류와 신규 import 누락은 뒤에서 수정했으며 이 오류 자체를 행동 회귀 증거로 쓰지 않는다. |
| 선택 계약 구현 후 신규 집중 검사 | 35통과/176deselected,0.99초 |
| `python -B -m pytest -p no:cacheprovider tests/unit/labs/rag/models tests/unit/labs/rag/generation tests/unit/labs/rag/search tests/unit/labs/rag/conversations -q --tb=short` | 1702통과/4skip,40.66초. 기존 Starlette/httpx deprecation warning1개 |
| 추가 opt-in 인용 조합 후 변경 테스트3파일 전체 | 212통과,2.40초. 허용 인용 성공·다른 근거 거절·틀린 날짜 거절을 기존 입력 보존 검사와 함께 확인 |
| Ruff 변경 소스4/테스트3파일 | 통과 |
| Mypy 변경 소스4파일, OS Temp cache | Success: no issues found in4source files |
| 독립 리뷰/검증 | 발견0. 당시 변경 테스트3파일211통과/2.60초, 별도 메모리 Profile JSON→resolver→HTTP MockTransport→CitationValidator6요청 통과. 이후 메인이 인용 조합1개를 추가했고 제품 코드는 동일 |

독립 mock에서 opt-in answer의 요청은 같은 baseline에 reasoning_effort=none만 추가됐다. rewrite는 동일하고 미설정 다른 synthetic model은 model 필드 외 요청이 같았다. 출력512·HTTP read timeout360·retry0, length/부분JSON/스키마 위반의 비재시도 실패를 확인했다. reasoning 원문을 수집하지 않았다. 전체 저장소 Mypy와 서비스/DB 통합·실모델은 실행하지 않았고 기존 전체 Mypy의 평가 호출 인자 누락을 해결 처리하지 않는다.

**반영 경계:** 등록된 실제 시험 프로파일/구성 DB 값은 바꾸지 않았다. opt-in을 사용할 버전의 generation JSON에 `"answer_reasoning_effort":"none"`을 명시하고 정확한 비기본 시험 구성에 연결하는 반영은 별도 인계다. 현재는 코드/mock 지원 완료이며 실응답의 thinking 비활성/정상 answer·인용/메모리 개선 완료가 아니다. reload 없는 API에 코드 반영하려면 재시작이 필요하지만 이번 단계에서는 하지 않았다. 어댑터 SHA-256: `6ed93bec5e9f6a43bae79c01c7a732f3d4147d5eda04488751c9a2a8e229ebc6`.

이번 실모델 호출0회·서비스 재시작/종료0회·실제 DB/설정/Elasticsearch/Docker 관리 변경0회·설치/commit/push0회다. 실추론 예산 소진과 최저RAM0.337GiB의 미해결 위험을 유지한다. 문서 UTF-8·상대 링크·최근 완료5개·git diff 공백을 검증하고 기존 우선순위를 보존한다.


### 2026-10-14 사용자 재시작 후 시험 설정 적용·메모리 보류

사용자의 백엔드 재시작 완료 및 기존 비기본 시험에만 thinking-off 적용/메모리 허용 시 동일 사실 질문1회 승인에 따라 진행했다. 이번 단계는 **시험 설정 적용 완료, 검색 질문 POST0회·실추론0회, 승인1회 미사용**이다. 자동 추가 호출을 예약하지 않았다.

- API PID104824는06:33:21.314127UTC 시작했으며 본래 cwd·reload 없음, 부모76784는 launcher다. 소스 수정 이후 시작 및 어댑터 SHA `6ed93bec5e9f6a43bae79c01c7a732f3d4147d5eda04488751c9a2a8e229ebc6`, health/ready200을 확인했다. 이는 프로세스/소스 기반 반영 근거이며 실모델 wire 검증은 아니다. 기존 인증으로 구성 GET200 및 아래 두 POST201을 확인했다.
- 가용RAM은06:44UTC3.215GiB→06:46UTC3.010GiB→07:06:19UTC2.344GiB(사용90.0%)였다. 기존 시험의 시작3.960GiB/최저0.337GiB 기록과 현재 여유로 안전성을 입증하지 못해 추론 전에 보류했다. 과거 감소폭은 확정 필요량이나 OOM 증거가 아니다. Ollama0.40.3 기존 서버의 최종 ps는 models=[]이며 이번 context16384 실적재 검증은 없다.
- 기존 사용자 탭 제어 연결 오류는 공식 브라우저 도구의 새 로컬 API 탭으로 복구했다. 자격증명 추출·새 계정·인증/보안 설정 변경은 없었다.
- 07:01:50UTC 관리자 프로파일 POST201: 같은 이름 `Gemma 4 E2B 로컬 시험 2026-10-13`의 v3 `c9e3bf96-9573-4173-b362-ef9ce8feff3c`. 기존 v2 `c788a65e-c88c-45cd-8785-bbb500bf4ad3`의 JSON과 비교해 **generation.answer_reasoning_effort=none 한 키만 추가**했다. deployment97327b16·output512·timeout360·schema2·입력 축소·문맥 정책·인용 설정은 동일하다. 등록 응답의 deployment_not_ready는 models/schemas.py의 초기 응답 값이며 구성 조회의 런타임 준비 상태와 구분한다.
- 07:05:30UTC 구성 POST201: 기존 config `54ef3fd7-6dae-4549-982d-813a3b16f63c`의 v2 `965a8d40-171e-4ca9-84cc-cfe8f03fd372`에 위 프로파일만 연결했다. 기존 문서처리207/색인201/검색e07f88a6·workspace2292dfa0·답변 정책은 동일하다. is_default=false, experimental=true, evaluation_state=pending, search_ready/answer_ready/service_ready=true, reasons=[]이며 local/external_transfer=false다. 준비 상태를 정상 생성 성공으로 보고하지 않는다.
- 구성 API의 ensure_indexed 부수효과를 독립 코드 리뷰로 확인했다. 쓰기 전 대상 active READY4개에 기존 processing207/index201 job·sent dispatch가 있고 handoff0건 및 활성 도메인 참조0건을 확인했다. 구성 저장 직전 같은 READY4개와 기존 테이블 해시를 재확인했다. 저장 후 읽기 전용 대조에서 기존 profiles20행/config versions12행 전부 보존+각1행 추가, configurations8/domains1/domain connections2/ingestion jobs8/dispatches8/handoff0의 전체 행 해시는 정확히 동일했다. 동시 변경의 원자적 배제를 주장하지 않는다. before/after 해시는 OS Temp ai-workshop-thinking-apply-cizeqii1에 보관했다.

새 usage/finish_reason·추론 감사·답변/인용·처리시간·신규 모델 종료 결과는 없다. 이전06:03 시험의 length/502 결과를 이번 thinking-off 시험 결과로 사용하지 않는다. 설정 적용 POST2회는 추론 호출이 아니다. 승인된 메타데이터 새 버전/정책/구독 저장 외 DB 직접쓰기·마이그레이션·서비스/Elasticsearch/Docker 변경·설치·commit/push는 없다. 제품 코드는 이번 단계에서 수정하지 않았고 pytest/Ruff/Mypy도 재실행하지 않았다. 기존1702통과/4skip 및212통과 기록을 이번 실행 결과로 중복 계산하지 않는다.

독립 검토는 설정 적용과 메모리 보류의 분리, 색인 dispatch/handoff의 저장 부수효과 및 최종 해시 대조 범위를 확인했다. WORKBOARD와 본 기록만 변경 전 사본/쓰기 직전 바이트를 확인해 갱신했다. 다음은 메모리 여유가 확보된 뒤 정확한 v2 구성·인증·진행 중 처리 부재를 다시 확인하고 승인된 동일 질문1회만 재개하는 것이다. 메모리 개선이나 정상 answer/인용 수용은 아직 미완료다.


### 2026-10-14 메모리 정리 후 재개 사전 검사—단일시험 미제출

사용자가 메모리 정리 안내 뒤 재개를 요청했다. 07:14:32UTC 가용4.897GiB/사용79.2%,07:15:01UTC4.884GiB를 관측했다. 앞선 같은 조건의 관측 감소3.623GiB(3.960→0.337) 및4.151GiB(4.679→0.528)를 단순 대입하면 약0.7~1.3GiB만 남을 수 있어 **질문 제출 전 보류, 실추론0회·승인된1회 미사용**으로 즉시 보고했다. 약6GiB는 추정 사전 여유 목표이며 고정된 필수량/안전 보장이 아니다. 감소 전부가 모델 때문이거나 이번에도 같다고 단정하지 않는다.

health/ready200, 기존 API PID104824/launcher76784와 Ollama113668의 시작 시각 유지, 위 어댑터 SHA 동일, Ollama ps models=[]를 확인했다. 읽기 전용 DB 재조회/rollback으로 최신 비기본 config54ef3fd7 v2/965a8d40→profilev3/c9e3bf96, answer_reasoning_effort=none·timeout360·output512·schema2·입력 축소 설정이 유지됨을 확인했다. 메모리 단계에서 보류했으므로 브라우저 인증을 새로 확인하거나 질문을 입력하지 않았다. context16384 실제 적재·retry0 실행 경로와 신규 답변/인용·usage/종료 사유·감사·처리시간·종료 결과도 이번에는 검증하지 않았다. 앞선 인증/설정/실시험 결과를 새 시험 결과로 대체하지 않는다.

추가 설정 변경·서비스 재시작/종료·추론 재시도·신규 파일 생성은 없다. WORKBOARD와 본 기존 기록만 변경 전 바이트를 확인해 최소 갱신했다. 제품 코드 변경이 없어 pytest/Ruff/Mypy는 재실행하지 않았고 문서 UTF-8·상대 링크·최근 완료5개·git diff 공백 검사를 수행했다. 남은1회는 메모리 여유 확보 후 사전 조건을 다시 확인할 때까지 사용하지 않는다.

### 2026-10-14 검색 요청 전용 CPU 임베딩의 생성 전 해제

사용자 승인 범위에서 로컬 코드와 mock 검증만 수행했다. 기존 RAG 기능 마감과 단일 thinking-none 실시험 보류를 유지하며, DB·설치·서비스·실모델 실행·commit/push는 변경하지 않았다. 작업은 중간 위험의 내부 수명주기 보완으로 분류했다. 요구·Python/AI·RAG 임베딩·테스트 설계와 내부 포트의 아키텍처 검토를 메인에서 맡고, 구현과 분리된 독립 리뷰/검증을 수행했다. UI·DB·인프라·권한 정책 역할은 실제 변경 범위가 없어 제외했다.

소유권 조사에서 검색 기본 resolver는 새 lazy 어댑터를 만들지만 주입 factory는 공유 객체일 수 있고, ingestion은 별도 공용 캐시를 사용함을 확인했다. execute/search_resolved는 동일 구성 재사용이 가능하며 FrozenGenerativeAdapter는 embedding을 frozen 평가 객체로 교체한다. 구성에 원본 어댑터의 close callback만 저장하는 방식은 동시 실행 및 평가 교체의 소유권에 맞지 않아, 기본 CPU 경로에만 실행별 신규 어댑터 factory를 제공했다. factory는 모델 설정·캐시 경로만 보유하며 DB session을 캡처하지 않는다.

- 제품 5파일: embeddings/sentence_transformers.py에 멱등적 terminal close와 재로드 금지, search/configuration_port.py에 선택적 요청 소유 factory 계약, configurations/repository.py에 기본 CPU 경로 연결, search/pipeline.py에 실행별 소유·선택 후 answer 생성 전 해제·finally 정리·원본 구성 반환, evaluation/generative_adapter.py에 frozen embedding 교체 시 factory 해제를 구현했다. custom factory·non-CPU·평가·ingestion의 borrowed 모델은 닫지 않는다. 모델명·프로파일·토크나이저·벡터·검색/인용 정책 변경이나 재색인은 없다.
- 테스트 4파일: 기존 test_sentence_transformer_adapter.py·test_configuration_processing_scope.py와 신규 test_request_embedding_lifetime.py·test_frozen_embedding_ownership.py. 어댑터 종료 미구현 및 pipeline 참조 유지, frozen 소유권 이전의 실패를 먼저 확인하고 수정했다. 작업 중 테스트 fixture/인자/진단 접근 오류는 별도 수정 후 재실행했다.
- 관련 회귀: `backend/.venv/Scripts/python.exe -m pytest`로 backend의 `tests/unit/labs/rag/{embeddings,search,configurations,generation,highlighting,evaluation,conversations,retrieval,ingestion}` 9개 디렉터리를 명시 실행해 **2137 passed, 4 skipped**(46.52초). 기존 Starlette/httpx deprecation warning 1건. 최종 추가 3경계 이후 변경 테스트 4파일을 다시 실행해 **49 passed**(2.17초).
- 최종 Ruff 대상은 제품5·테스트4파일이며 통과했다. 변경 제품5파일 Mypy(`--follow-imports=silent`, 별도 Temp cache)도 통과했다. 전체 backend Mypy·frontend 검사는 이번 범위에서 재실행하지 않았으며 과거 평가 호출 인자 오류의 해결을 주장하지 않는다.
- 독립 리뷰: 제품5파일 해시와 현재 diff 확인, 지정4파일 **46 passed**, observer 오류/생성 없는 검색의 owned·borrowed 추가4사례 통과. 마지막 hybrid 벡터/응답 진단 보존 및 빈 검색 생성 on/off 추가3건도 **3 passed**로 독립 확인했다. 차단·비차단 지적 없음. 이 수치는 주 실행과 독립 실행이며 합산한 서로 다른 사례 수가 아니다.

mock의 weak reference로 answer generation에 들어가기 전에 전용 모델 참조가 없어지고 오류·취소·순차·동시 요청에서 소유권이 분리됨을 검증했다. 검색 결과·근거·인용·history·hybrid 벡터/진단을 보존하며 종료 후 tokenizer/encode는 재로드 없이 실패한다. 원래 구성은 재사용 가능하게 반환한다. **이것은 실제 RSS/가용 RAM 감소나 즉시 OS 반환을 보장하지 않는다.** 모델 내부 참조·allocator·예외 traceback 등에 따른 회수 시점은 별개다. history token 계산 뒤 선행하는 contextualize 단계의 모델 중첩은 여전히 남는다.

최초 관련 파일 사본/해시와 git 상태는 OS Temp `ai-workshop-request-embedding-qw9srbxe`에 보존했고 각 쓰기 직전 바이트를 재확인했다. 현재 작업의 제품·테스트 delta와 해시를 별도 저장해 기존 미커밋 변경과 구분했다. 기존 WORKBOARD와 본 worklog만 최소 갱신했다. 실제 서비스는 자동 reload가 없으므로 **사용자의 백엔드 재시작 후에 반영 확인이 필요**하다. 이번 작업은 서버 재시작·실모델 로드/추론0회이며 승인된 동일 질문1회는 미사용이다. 다음은 재시작 후 메모리·인증·정확한 시험 구성·진행 중 처리 상태를 재확인하고 남은 단일시험의 실행 가능성을 판단하는 것이다. 정상 answer/인용·실제 메모리 수용과 전체 RAG 기능 마감은 미완료다.

### 2026-10-14 RAG Codex CLI 전용 UI와 현재 운영 안내 종료

사용자가 승인한 범위에서 전용 설정·동의·실행 진입점과 현재 운영 안내를 종료했다.
중간 위험의 프론트엔드 기능 변경으로 분류했고, 요구/범위·프론트·RAG·테스트 역할을 주 구현자와 실행 화면 구현자에게 분리했다.
별도 독립 리뷰어가 최종 변경을 검토했다. DB/백엔드/인프라·보안 설정은 범위 밖이다.
최소 계획은 기존 변경 보존 → 회귀 기대/최소 UI 수정 → 순차 검증/독립 리뷰/기존 기록 갱신이었다.
착수 당시 미커밋·미추적 변경을 Temp snapshot에 보존하고 각 최초 쓰기 직전에 원본 byte 일치를 확인했다.

**구현:** ModelAdminWorkspace에서 CodexSetup/CodexGenerationForm/CodexEvidenceApproval과 공급자 선택 진입점을 제거했다.
그 결과 CodexDeploymentForm도 제품 화면에서 더 이상 연결되지 않는다. SavedConfigurationList의 CodexVerificationPanel을 지원 종료·기록 조회 안내로 대체했다.
기존 Codex 정책 선택은 읽기 전용으로 표시하고 다른 공급자 변경 때 원래 값을 보존한다.
새 구성·도메인 연결·생성 평가의 알려진 Codex 후보 및 현재 Codex 구성 승격을 차단하고,
대화/검색의 Codex 전용 동의 입력을 제거하며 질문 전송을 차단했다. 기존 답변/모델 식별/감사 기록 표시는 유지한다.
기술 흐름 화면과 local-development 실행서도 신규 지원 종료 및 과거 호환 경로를 구분한다.
전용 컴포넌트 파일을 영구 삭제하지 않았고 API 타입·공통 codexError·요청 헤더·백엔드 lifecycle 및 개발 Codex 지침은 유지했다.

**정확한 경계:** 이것은 RAG 전용 UI 종료이며 Codex 백엔드의 모든 실행 경로 제거가 아니다.
기존 고급 YAML/API의 범용 계약은 보존한다. 구성 목록 API는 identity별 최신 버전만 반환하고 과거 연결/평가 기록에는 provider가 없으므로,
목록에 없는 옛 버전을 임의로 HTTP/Codex로 단정하지 않는다. 공급자를 확인할 수 없는 과거 버전의 공통 활성화·재시도·평가 반영은 기존 동작을 보존한다.
알려진 Codex의 새 UI 사용은 막지만 모든 과거 Codex 실행을 금지했다는 주장은 하지 않는다.
독립 리뷰에서 발견한 과거 HTTP 평가 재시도 회귀, 현재 Codex 기본값 승격 진입점, 사용 가능/지원 종료 표시 충돌을 수정하고 재승인받았다.

**실행 검증:** 모두 mock/로컬이며 한 번에 한 프로세스·Vitest worker 1개로 실행했다.
- RED에서 신규 종료 기대 실패를 확인했다. 초기 신규 테스트의 중복 text 질의/버튼 이름 오류와 act 대기 누락도 정정했으며 제품 결함으로 집계하지 않는다.
- 변경 관련 7파일(관리 탭·정책·구성 스튜디오·도메인·대화·검색·생성 평가): 최종 **138 passed**.
- HTTP 배포/생성 폼·배포 목록·로컬 배포·모델 페이지·모델 API 6파일: **61 passed**. 변경하지 않은 ModelLabPage.test.tsx에서 act 경고 2건 관측, 실패 없음.
- `node node_modules/typescript/bin/tsc --noEmit --incremental false --pretty false`: frontend 전체 타입 검사 통과, 출력/tsbuildinfo 생성 없음.
- 변경 TS/TSX 18파일 `node node_modules/eslint/bin/eslint.js … --max-warnings 0`: 통과.
- `pnpm --dir frontend exec vitest`는 기존 shim 경로에서 명령을 찾지 못했으므로 설치 없이 기존 `node node_modules/vitest/vitest.mjs run … --maxWorkers=1 --no-file-parallelism`으로 실행했다.
- 독립 리뷰는 코드/테스트 검토이며 별도 테스트 실행 통과로 합산하지 않는다.

**실모델 시험 별도 상태:** 사용자 재요청에 따라 UI 변경/테스트를 멈추고 연결을 확인했지만 이 도구에서 실제 요청은 **0회**다.
08:02:46UTC 가용RAM4.313GiB·Ollama models=[]였다. Swagger 탭 연결은 한 번 성공했지만 별도 `/api/v1/auth/me` 탐색은 Chrome `ERR_BLOCKED_BY_CLIENT`였다.
이후 사용자가 로그인된 기존 `/admin/rag/models` 탭을 유지했으나 해당 탭 바인딩은 `Debugger unattached`로 실패했다.
보호 설정을 변경하지 않았고 기존 탭/지원 DOM API로도 제어 연결을 확인하지 못했다.
08:09:55UTC 가용RAM3.199GiB, 정식 health/ready HTTP200, Ollama models=[]를 확인했다.
테스트 재개 전 읽기 전용 DB SELECT/rollback에서 대화/실행/평가 run/attempt의 running 각0을 확인했다.
시험 구성 “Gemma E2B 입력 축소 360초 비교 2026-10-14” v2(965a8d40)는 비기본/pending이고 활성 도메인 연결0이다.
정상 검색 route는 DomainPickerPage이므로 이 비기본 시험 구성을 현재 화면에서 직접 고를 수 있다고 안내하지 않았다.
부모에게 정확한 차단과 수동 Swagger 입력을 전달했으며, 사용자 직접 실행 여부는 이 기록에서 확인하지 않았다.
이번 도구 제출 기준 승인된1회는 미사용이다. 답변/출처/usage·context16384 실적재·실제 메모리 개선 수용은 미검증이다.

**변경 파일:** frontend RAG의 ModelAdminWorkspace, DataPolicyPanel, DeploymentRegistry, ConfigurationBuilder,
SavedConfigurationList, ComparisonPanel, GenerativeEvaluationPanel, DomainAdminPage, ConversationPage, SearchPage,
flows/architecture 및 관련 기존 테스트7파일; docs/runbooks/local-development.md, 이 worklog, WORKBOARD.md.
빌드·브라우저 E2E·모델 추론·외부 API·서비스 재시작/종료·설치·DB 쓰기/migration·커밋/푸시는 실행하지 않았다.
다음은 브라우저 제어 복구 또는 사용자 직접 실행의 정확한 단일 결과를 확인해 Gemma 정상 답변/인용 경계를 마무리하는 것이다.
RAG 안정화 → Agents SDK → 벡터 저장소 비교 → 파인튜닝 → Kubernetes 순서와 학습 문서/알림 예약은 유지한다.


### 2026-10-14 생성 답변·발췌 상태 분리와 대화 복원 회귀

**범위:** 일반 대화 구성 연결·생성 답변/출처·저장 후 재조회 우선 점검. 요구사항/프론트엔드/RAG/테스트 역할로 최소 수정하고 독립 코드 리뷰·backend mock 검증을 분리했다. 모델·권한·공개 API 계약·임계값·DB/배포 변경은 제외했다. 기존 변경을 작업 전 보존하고 각 쓰기 직전에 비교했다.

**앞선 실모델 시험 정정:** 사용자가 단일 요청을 직접 실행해 생성 answered와 PDF 3쪽 발행일 인용 일치를 확인했다. 승인1회는 사용자 실행으로 소진됐으며 아래 작업에서 추가 추론은 없다. 감사296f6849-b75b-43eb-b819-6c973c0cb5dc는 succeeded, 입력7117/출력81, 생성183.749초, external_transfer=false다. 사용자 진단 전체226.026초와는 측정 범위가 다르다. 프로파일 thinking none/schema2/출력512/timeout360을 읽기 전용 확인했다. 실제 thinking 비활성·모델 정체성·context 실적재·RAM 개선은 독립 입증하지 않았다. finish_reason은 직접 로그 확인이 아닌 엄격 파서 성공 조건으로 stop을 추론했다. 검증 토큰은 기록하지 않는다.

**원인과 수정:** 최상위 status/answer는 개별 발췌 판정이며 generation은 부모 청크 문맥을 이용하므로 insufficient_evidence와 answered가 공존하는 기존 계약이다. ConversationAnswer는 이미 grounding_evidence와 생성 상태를 사용한다. 관리자 검색 EvidenceAnswer만 문맥 근거를 인용 맵에서 누락하고 생성 성공 아래 일반적인 근거 부족 문구를 표시했다. 문맥 인용의 문서명·페이지·정확한 원문 버전/projection/context highlight 링크를 연결하고 발췌 판정 안내를 분리했다. 미지 인용 ID는 일반 대화처럼 본문을 숨기며 API/임계값은 유지했다.

**실행 검증:**
- 검색 회귀 신규2개가 수정 전 실패(기존8개 통과), 수정 후10개 통과했다.
- frontend 관련8파일(EvidenceAnswer, SearchPage, SourceViewer, ConversationAnswer, ConversationPage, ConversationSessions, DomainPickerPage, DomainAdminPage) **98 passed**. 기존 실제 컴포넌트와 mock transport로 검증했다.
- PDF context의 좌표·페이지·kind 보존 및 URL 본문 미포함 검사를 보강한 최종 변경2테스트파일 **18 passed**.
- ConversationSessions의 합성 표본은 POST/start 1회 → 화면 재마운트 → GET 복원 → 동일 근거의 실제 SourceViewer 컴포넌트 조회를 검증한다. 최초 테스트의 버전 문구 assertion만 정정했고 제품 결함으로 집계하지 않는다. 이는 실제 DB 영속 저장 검증이 아니다.
- frontend 전체 `node node_modules/typescript/bin/tsc --noEmit --incremental false --pretty false`, 변경3파일 ESLint `--max-warnings 0` 통과.
- 독립 검증자가 backend `test_context_generation.py`, `conversations/test_service.py`를 `pytest -q -p no:cacheprovider`로 실행: **11 passed**. 메모리 저장소/mock이며 실제 DB·모델 호출 없음.
- 독립 코드 리뷰 차단 지적 없음. 기존 buildSourceHref 사용과 세션 mock 범위 확인; 비차단 PDF highlight 테스트 권고도 반영했다.

**실제 화면·연결 경계:** 기존 Chrome 탭 제어는 이번에 성공했다. 일반 앱 `/workshop/rag/search` 진입은 `/login?next=...`로 이동하여 일반 대화 화면의 로그인 후 수용은 미실행이다. 로그인 토큰 추출/이동이나 보안 차단 우회는 하지 않았다. 읽기 전용 DB에서 시험 구성54ef3fd7-6dae-4549-982d-813a3b16f63c의 v2(965a8d40-171e-4ca9-84cc-cfe8f03fd372)는 pending/defaultfalse, 모든 도메인 연결0개, 허용 workspace2292dfa0-3af8-4494-a8ce-da03ef2aa6ed를 확인했다. 일반 화면은 구성 직접 선택 대신 도메인의 불변 연결 버전을 사용한다. 정식 평가 통과·서비스 준비 후 해당 구성 버전/허용 공간으로 연결을 만들고 활성화해야 한다. 기존 운영 도메인의 active_connection_version_id를 바꾸면 그 도메인의 후속 대화 구성이 바뀌므로 대상 승인 전 변경하지 않는다. 별도 도메인 생성 역시 DB 쓰기이므로 이번에는 실행하지 않았다.

**잔여:** 일반 앱 로그인, 정식 평가 및 승인된 도메인 연결, 이후 실제 질문1회와 저장/재조회/원문 열기의 본래 화면 수용. 이1회도 새 승인 전 실행하지 않으며 평가 게이트에 필요한 별도 실행을 대신하지 않는다. 검색 표시 결함의 관리자 문제 이력 DB 등록/갱신은 쓰기 제외 범위로 미완료이며 이 기록을 근거로 남긴다. 다른 RAG 기능 마감 조건과 우선순위는 그대로다. 전체 frontend suite/build·운영 DB 통합·실제 모델·서비스 재시작·설치·migration·commit/push는 실행하지 않았다.

**변경 파일:** frontend/src/features/rag/search/EvidenceAnswer.tsx, EvidenceAnswer.test.tsx, frontend/src/features/rag/conversation/ConversationSessions.test.tsx, WORKBOARD.md, 이 worklog.


### 2026-10-14 생성형 평가 워커 의존성과 자원 수명 수정

**범위와 원인:** 남은 RAG 기능 개발 승인에 따라 생성형 평가 워커의 필수 local_model_host 누락만 수정했다. 이전 전체 Mypy의 `generative_workflow.py:156 [call-arg]`와 같은 결함이며, 변경 전 전체470파일 검사에서 정확히 이 오류1건을 재현했다. FastAPI 직접 요청은 lifespan host를 주입하지만 Celery의 직접 factory 호출에는 주입이 없었다. Python backend·AI runtime 역할을 메인이 맡고 구현과 분리된 독립 리뷰를 수행했다. UI·DB·보안 정책 변경은 없다.

**구현:** 각 평가 attempt가 LocalModelHost를 만들고 검색 factory에 전달하며 aclosing으로 종료한다. HTTP/Ollama 경로에서는 이 호스트가 모델을 적재하지 않는다. local_transformers는 attempt 내에서만 캐시하고 끝날 때 해제하므로 다음 attempt의 재적재 비용은 남는다. get_search_service의 단일 yield 의존성은 asynccontextmanager로 감싸 정상·예외·취소 모두 Elasticsearch client를 즉시 닫는다. 기존 frozen.close(), Codex services 및 session 정리와 frozen 임베딩의 빌린 소유권, 일반 검색 CPU 임베딩 해제 경로는 유지했다. 재시도·평가 정책·공개 API 계약을 바꾸지 않았다.

**검증:**
- 새 회귀4케이스는 실제 get_search_service·GenerationRuntimeResolver·LocalModelHost를 조립하고 모델 loader/DB/검색 실행만 합성 대역으로 대체한다. 준비 실패·생성 실패·정상·취소 시 엔진 weakref 해제, 닫힌 호스트 사용 거부, ES/session/Codex/frozen 정리를 검사한다.
- 테스트 fixture의 합성 키 길이를 교정한 뒤 제품 수정 전 **4 failed / 9 passed**로 누락을 재현했다. 수정 후 단일 파일13통과. 첫 정리 방식의 AsyncIterator/aclosing 타입 불일치는 asynccontextmanager로 해결했다.
- 최종 `.venv/Scripts/python.exe -B -m pytest tests/unit/labs/rag/evaluation tests/unit/labs/rag/generation tests/unit/labs/rag/embeddings tests/unit/labs/rag/search tests/unit/labs/rag/conversations tests/unit/labs/rag/executions -q --tb=short`: **1890 passed, 4 skipped, 1 warning, 41.38초, exit0**. 경고는 기존 Starlette TestClient/httpx deprecation이다. frozen embedding ownership·request embedding lifetime·local host 취소/종료 회귀도 이 범위에 포함된다.
- 최종 `.venv/Scripts/python.exe -B -m mypy src/ai_workshop --no-incremental --cache-dir nul`: **Success: no issues found in470source files**, exit0. 이전 전역 인자 누락 오류는 해소됐다.
- 변경 제품/테스트2파일 `ruff check --no-cache`: 통과. 독립 리뷰자가 최종 테스트 파일을 별도 실행해 **13 passed, 3.56초, exit0**, 차단 지적 없이 승인했다.
- 새 workflow fixture는 attempt1개이고 취소는 fake host.run 완료 뒤 발생한다. 다중 attempt 격리·실모델 실행 중 취소·실제 RAM 감소를 이번 새 테스트의 직접 증거로 확대하지 않는다. 전체 pytest/운영 DB 통합·브라우저 E2E·실모델은 미실행이다.

**실행 반영 경계:** 코드상 Celery task `ai_workshop.rag.evaluate_generative_run` → generative_dispatch.execute_run → GenerativeWorkflow.run 경로다. 본래 호스트 worker 실행 정본은 [로컬 실행서](../runbooks/local-development.md#3-호스트-애플리케이션-실행)의 `backend\.venv\Scripts\python.exe -m celery -A ai_workshop.worker:celery_app worker --pool=solo --loglevel=INFO`이며 저장소 루트/PYTHONPATH 설정을 따른다. worker에는 자동 reload가 없다. 기존 모듈을 적재한 worker는 이 코드 반영을 위해 재시작해야 하며 API만 재시작해서는 반영되지 않는다. API/frontend/beat/Ollama 변경은 이번 수정에 필요하지 않다. Win32_Process의 명령줄/PID 관계 조회는 Windows 접근 거부였고 일반 Python 프로세스 목록만으로 worker를 식별하지 않았다. 실제 worker PID·현재 실행 여부·모듈 적재 여부는 미확정이므로 기존 실행 창과 작업 상태를 확인한 후 별도 승인으로 반영해야 한다. 권한 승격·정책 우회·서비스 재시작은 하지 않았다.

**보존과 잔여:** 최초4파일 사본·SHA·diff는 `.local-data/project-agent-work/generative-host-20261014/`에 보존했고 쓰기 직전 동시 변경을 확인했다. 다른 tracked diff는 최초와 동일하다. 변경 파일은 generative_workflow.py, 기존 test_generative_workflow.py, WORKBOARD.md, 본 기록4개다. 실제 모델/임베딩 호출0·DB쓰기0·평가 정책/기본값/도메인 연결 변경0·재시작0·설치/migration/commit/push0이다. 관리자 문제 DB 반영은 쓰기 제외로 미완료다. 다음은 실 워커 반영 확인 후 별도 승인된 정식 평가이며 기존 P95 120초 기준과 앞선 단일 요청226초의 성능 위험을 그대로 유지한다.


### 2026-10-14 정식 Gemma 평가 승인 후 사전 확인 대기

사용자는 시험 구성 v2(965a8d40-171e-4ca9-84cc-cfe8f03fd372), 평가 자료 bf846b4f-9d13-5f1b-88e6-576786f76b3b의 실제2사례×반복2로 로컬 Ollama gemma4:e2b-it-q4_K_M 평가 최대4회, 기존 정책 통과 시에만 평가 결과 반영·자산운용 연결 활성화·일반 대화1회를 승인했다. 총 생성 상한5회이며 자동 재시도/전역 기본값 변경은 제외한다. 평가 실패 시 연결/일반 대화 단계는 수행하지 않는다.

기존 Chrome 세션에는 Swagger 탭만 남아 있었으며 인증/응답 토큰을 읽지 않았다. 동일 Chrome에서 구성 스튜디오를 열자 `/login?next=%2Fadmin%2Frag%2Fconfigurations%3Ftab%3Dcomparison`으로 이동했다. 로그인 폼을 확인하고 입력 없이 handoff 탭을 유지했다. 새 로그인·비밀번호/쿠키/토큰 추출은 수행하지 않았다.

워커는 기존 설정으로 Celery의 정상 관리 `inspect(timeout=3).stats()`를1회 수행했고 응답은 None이었다. 평가 task 제출·shutdown·restart 제어는 보내지 않았다. 무응답은 worker 부재나 종료의 증거가 아니며 solo worker가 바쁜 경우 등도 구별하지 못한다. 앞선 Win32_Process 접근 거부를 우회하지 않았고 현재 PID/유휴/수정 모듈 적재 여부를 확인하지 못했다. 따라서 중복 기동하거나 임의 프로세스를 종료하지 않았다.

다음 사용자 조치는 일반 앱의 기존 owner 로그인과 기존 Celery worker 실행 창 확인이다. 실행 중 업무가 없는 정확한 worker를 확인한 뒤 해당 창에서 정상 종료/재시작하고 [로컬 실행서](../runbooks/local-development.md#3-호스트-애플리케이션-실행)의 저장소 루트·PYTHONPATH 및 `backend\.venv\Scripts\python.exe -m celery -A ai_workshop.worker:celery_app worker --pool=solo --loglevel=INFO` 명령을 따른다. API 재시작으로 대체하지 않는다. 워커 실행 창을 찾지 못한 상태에서 새 worker를 중복 시작하지 않는다.

이번 단계는 평가 제출0·실제 모델/임베딩 호출0(승인5회 전부 미사용)·DB 쓰기0·정책/연결/기본값 변경0·서비스 재시작0이다. 평가 실패/품질 미달로 판정한 것이 아니라 사전 조건 미충족이다. 제품 source SHA는 3b4444932bf85d9846539c468472064b3c56257130a8bcbf34738660d41fe783로 직전 검증과 같고 테스트/타입/린트를 재실행하지 않았다. 기존 WORKBOARD와 본 기록만 갱신하며 UTF-8·상대 링크·공백·최근 완료5개를 검사한다. 승인 범위와 사용량 상한은 보존하며 사용자 조치 뒤 같은 범위로 재개한다.


### 2026-10-14 로그인 완료 후 워커 재확인

사용자가 로그인 완료를 알린 뒤 동일 Chrome 탭에서 `/admin/rag/configurations?tab=comparison`의 관리자 구성 스튜디오와 시험 구성 v2를 확인했다. 로그인·인증 정보 추출 없이 기존 세션을 이용했고 탭은 handoff로 유지했다. 화면에 표시된 과거 RAG-TEST 평가 결과를 Gemma 신규 평가로 집계하지 않았다.

Celery 정상 관리 `inspect(timeout=3).stats()`를 새로1회 실행했지만 다시 None(응답 없음)이었다. 워커 종료/부재 또는 재시작 완료를 추정하지 않으며 수정 코드 적재도 미확정이다. 준비 조건을 충족하지 못해 평가를 제출하지 않았다. 현재 남은 선행 조치는 정확한 기존 worker 실행 창·유휴 상태와 수정 반영 확인이며 API 재시작으로 대신하지 않는다. 기존 실행서 명령과 중복 기동 금지 경계는 앞 절을 따른다.

신규 평가 제출0·실제 생성0/5·DB쓰기/연결변경0·재시작0이다. 승인된 평가4회와 통과 시 연결/대화1회 범위는 유지한다. 제품 변경과 추가 테스트 실행은 없으며 WORKBOARD/본 기록만 갱신하고 UTF-8·상대링크·공백·최근 완료5개를 검증했다.


### 2026-10-14 등록된 Celery Task.apply로 정식 Gemma 평가

상위 작업의 명시 승인에 따라 기존 owner UI로 run `7cb86b65-78d1-47d1-8b57-2ecc68ba295f` 한 건을 제출했다. 구성 v2 `965a8d40-171e-4ca9-84cc-cfe8f03fd372`, 기존 데이터셋 `bf846b4f-9d13-5f1b-88e6-576786f76b3b`의 2사례×2반복=4시도, 기존 정책 `3cb3fc16-98d7-4cd6-8f6c-4646fbff3256`(P95 120000ms), K10, 대화 이력 없음·기존 정답 문자열 규칙을 유지했다. 로컬 Gemma 모델·외부 전송 false·max_retries0·timeout360초를 대조했다. 시작 전 가용 RAM은 약2.61GiB였다.

UI 제출은 pending DB 저장이며 전달은 별도 reconciler가 담당한다. run/attempt 행 잠금과 상태·claim token 검사로 중복 전달의 재실행을 막고 stale 실행은 interrupted로 마감한다. 자동 replay는 없으며 정확히 한 번 완료를 보장한다는 뜻은 아니다. 관련 단위15개 통과(8.64초), memory broker의 Task.apply admission 거부 probe는 SystemExit 전파·작업 본문0회, 실제 verify_original_runtime(writer=True, non_es=False)도 통과했다. 등록된 `ai_workshop.rag.evaluate_generative_run`의 Task.apply(throw=True)를 위 run에1회 호출했으며 DB running·첫 시도 running을 확인했다. 일반 worker/beat·큐 삭제/소비/재배치·서비스 재시작·raw DB 쓰기는 하지 않았다.

최종 결과: 16:56:44 UTC에 run 및 4시도가 completed로 저장됐고 Task.apply는 SUCCESS/exit0으로 종료했다. 두 정답 시도는 검색 후보10개 모두 below_threshold, 선택 근거0, generation skipped/no_eligible_evidence로 insufficient_evidence가 되어 정답 실패다. 두 거절 시도는 선택 근거26개에서 실제 Gemma 생성 후 insufficient_evidence로 정상 거절했다. actual provider 호출은2회(각 입력9549/출력19, stop)이며 나머지2시도는 생성 미호출이다. audit4행을 모델 호출4회로 계산하지 않는다.

시도별 전체 지연은 정답18.572/10.994초, 거절267.134/16.574초다. 저장된4값에 정책과 같은 percentile_cont(0.95)를 적용한 P95는229849.529ms로 기존120000ms를 초과했다. 정답 사례의 문맥 충족0/2·정답0/2와 거절2/2를 구분한다. 생성 단계만의 실제 지연은235544/1779ms이며 가용 RAM/콜드 시작 등이 원인인지는 미확정이다. 시간 개선이나 thinking/context 적재 효과를 입증한 것으로 쓰지 않는다.

owner UI의 완료4·진행/대기/실패/중단0 및 정답 사례의 실패·근거 부족 표시를 확인했다. 실행 status completed는 품질 합격이 아니다. 평가 통과 반영0, 구성 pending/defaultfalse, 정책·서비스 연결·전역 기본값 변경0, 후속 일반 대화0이다. 총 생성2/5회이며 남은 상한을 추가 평가·재시도에 전용하지 않았다. 다음 후보는 저장된 진단에서 정답 근거의 검색 순위·선택 탈락과 첫 생성 지연을 조사하는 한정 작업이다. 관리자 문제 DB 갱신은 이번 승인된 평가 쓰기 범위 밖이므로 미반영으로 남기며 기존 문제 이력을 완료 처리하지 않는다.

독립 검증은 별도 읽기 전용 DB 조회로 동일4시도·실제 생성2회·P95 초과·acceptance0·Gemma 연결0과 기존 자산운용 활성 연결 보존을 확인했고 승격 중단 판정에 이견이 없었다. 파일/DB 쓰기와 모델/서비스/큐 제어 없이 수행했다. 문서 UTF-8·상대 링크·WORKBOARD200줄 이하/최근 완료5개·git diff --check를 최종 확인했다.


### 2026-10-14 오프라인 표 문맥 선택 개선

사용자는 기존 진단 기반의 제한된 문맥 선택 구현·오프라인 검증을 승인했다. requirements/rag-behavior/feature/significant 신호의 요구 설계·RAG·테스트 역할은 메인, 독립 통합 검증·코드 리뷰는 별도 검증자에 배정한다. UI·DB·인프라·모델 런타임 변경은 제외한다. 기존 미커밋 전체 diff와 대상 파일 바이트/SHA를 `.local-data/project-agent-work/table-context-20261014/`에 보존했고 쓰기 직전 재확인했다.

한정 설계: 기존 whole-chunk 및 임계값·검색 순위를 유지한다. 검색된 동일 원문 청크의 단일 페이지에 헤더와 반복 행의 열 좌표가 명확히 정렬된 표만 추가 경로로 인정한다. 질문은 유일한 대상 헤더와 대금 수령 시점 의도가 모두 명시된 경우에 한정하며 특정 상품·질문·정답 ID나 수치를 고정하지 않는다. 표의 모든 행 라벨·대상 열과 표 밖 원문 전체(제목·정의·조건·예외·부정문의 연속 줄)를 보존하고 다른 대상 열만 제외한다. 이는 이전 전체청크 정책에 대한 승인된 좁은 예외이며 원문을 자르거나 새 셀 관계·인용 ID를 저장하지 않는다. 헤더/열/행/대상/좌표가 모호하면 기존 경로로 돌아가며 필수 묶음이 예산을 넘으면 추가 절삭하지 않는다. 기존 추출형 적격/충돌 근거를 제거하지 않는다. 구조적 선택 사유는 별도로 표시하고 기존 cosine/keyword 점수를 조작하지 않는다.

계획: 신규 합성 표 fixture로 구어 질문·33→28단위·정확한 원문 ID/순서 보존 RED를 먼저 확인한다. highlighting의 순수 표 후보 helper와 context 통합을 분리한다. unrelated/unsupported/unknown/multiple target, 누락·중복 헤더/행/셀, 다른 열 혼입, 부정 조건 보존, 비정상 bbox, 예산 경계, 중복·순서·진단 on/off·기존 일반청크 회귀를 검증한다. 기존 모델 호출 수를 늘리지 않으며 테스트 embedding은 전부 fake다. 관련 RAG unit 전체·전체 backend Mypy·변경 Ruff·독립 리뷰 후 마감한다. 새 평가·실제 모델/임베딩·DB쓰기·도메인/기준/서비스 변경·commit/push는0으로 유지한다.

**구현 결과:** `highlighting/table_context.py`의 순수 선택 helper와 `context.py` 통합을 구현했다. 정규화한 헤더의 정확한 단일 대상과 제한된 한국어/영어 지급시점 의도만 추가 적격 경로로 인정한다. 단일 PDF 페이지의 유효 bbox·동일 행 높이·정확한 열 정렬·완전한 셀·유일한 지급일 행을 요구한다. 병합/기존 table_cell 메타데이터·누락·중복·여러 표 등은 이 좁은 경로에서 제외한다. 원문 unit 객체/ID/순서/위치와 모든 주변 설명을 유지하고 타상품 열만 제외한다. 기존 적격/충돌 근거가 제외될 경우에는 전체 청크를 유지한다. `structured_table_selected` 사유를 별도로 기록하고 cosine/keyword 점수와 임계값을 유지한다. 필수 묶음의 누적 그룹/단위/문자 예산을 검사하며 초과 시 추가 절삭하지 않는다. 진단은 실제 전송 ID만 selected로 표시한다.

**회귀와 독립 리뷰:** 최초 신규 테스트는 제품 수정 전 **7 failed / 22 passed**로 구어 질문과 예산 문제를 재현했다. 첫 구현 뒤29통과, 추가 보존 검증 뒤 highlighting112통과였다. 독립 리뷰가 발견한 타열 참조 셀(`다른 상품과 동일` 등)의 값 유실과 일부 부정/불능 질문의 잘못된 적격성을 신규16케이스 **16 failed / 37 passed**로 재현하고 수정했다. 유지할 원문에 동일/참조/ditto/좌우 등의 참조 표현이 있거나 대상 셀이 타열 헤더를 언급하면 축소하지 않는다. 부정 질문은 새 긍정 지급시점 경로에서 제외한다. 원래 임계값을 통과한 경우 전체33단위를 유지하는 회귀도 포함한다. 최종 신규 테스트는 selector53개와 mock SearchService2개이며, 합성 표33→28단위의 생성 요청·감사 기록·grounding·응답 인용 일치와 diagnostics on/off를 검증했다. 검색 회귀의 초기2실패는 응답 status가 문자열인데 `.value`를 기대한 테스트 오류였고 제품 수정 없이 바로잡았다. 독립 검증자가 최종 highlighting+신규 search를 별도 실행해 **130 passed, 4.19초**, 추가 차단 없음으로 승인했다.

**최종 실행 검증(모두 exit0):**
- backend에서 `.venv/Scripts/python.exe -B -m pytest tests/unit/labs/rag -q --tb=short`: **5991 passed, 17 skipped, 1 warning, 327.62초**. 경고는 기존 Starlette TestClient/httpx deprecation이다. skip17개는 통과로 집계하지 않는다.
- `.venv/Scripts/python.exe -B -m mypy src/ai_workshop --no-incremental --cache-dir nul`: **Success: no issues found in471source files**.
- `.venv/Scripts/python.exe -B -m ruff check --no-cache`로 변경 제품2파일·신규 테스트2파일 검사: **All checks passed**.
- WORKBOARD와 본 기록 UTF-8·상대 링크·최근 완료5개/200줄 제한·`git diff --check` 확인. 최초 diff와 비교해 범위 밖 tracked diff는 동일하고 기존 `test_pdf_context_budget.py` SHA도 그대로다.

**변경 및 잔여:** 변경은 제품 `highlighting/context.py`, 신규 `highlighting/table_context.py`, 신규 `tests/unit/labs/rag/highlighting/test_table_context.py`와 `tests/unit/labs/rag/search/test_table_context_generation.py`, WORKBOARD 및 본 기록6파일이다. 실제 모델/임베딩 호출·새 평가·DB쓰기·도메인 연결/정책/기본값 변경·서비스 재시작·migration·commit/push는 모두0이다. 전체 backend pytest/DB 통합·브라우저 E2E·실제 frozen 사례 재실행은 미실행이다. 엄격한 정규 표와 제한된 표현만 지원하며 일반 표 해석기로 확대하지 않는다. 기존 Gemma 평가의 정답 실패/P95 초과, 구성 pending/defaultfalse, 기존 연결 보존 상태를 바꾸지 않았다. 다음 후보는 별도 승인된 동일 평가 재검증 및 첫 생성 지연 원인 확인이며 실모델 정답률·지연 개선/운영 승격은 이번 mock 결과로 주장하지 않는다.

### 2026-10-14 표 문맥 수정 후 동일 Gemma 평가 재실행

사용자는 동일 구성v2·기존 평가셋/정책·2사례×2반복의 새 run1건, 최대4attempt/4생성 호출만 승인했다. 이전 예산 잔여와 합산하지 않으며 워밍업·시험 생성·자동재시도·추가 일반대화·승격·도메인 활성화는 제외한다. 메인은 정상 등록 task의 실행·진단, 독립 검증자는 최종 저장 결과의 읽기 전용 검증을 담당한다. UI/제품/보안/색인/서비스 변경 역할은 제외한다. 최초 diff/status와 기존 문서 사본을 `.local-data/project-agent-work/table-context-evaluation-20261014/`에 보존했다.

사전 확인: 기존 owner UI 로그인 유지, API health200, Ollama0.40.3의 모델 목록에 gemma4:e2b-it-q4_K_M 존재·`/api/ps` 적재 모델0, 가용 RAM4,559,851,520B, 진행 중 생성형 run0건이다. 구성v2/생성 프로파일v3의 기존 파라미터와 답변 임계값0.9/0.5·정책P95 120000ms·재시도0을 확인했다. 표 문맥 제품2파일 SHA는 최종 mock 검증과 같고 새 프로세스의 등록 Task.apply로 실행한다. 실제 `verify_original_runtime(writer=True, non_es=False)` 사전 admission을 통과했다. 공용 큐 소비/reconciler/서비스 재시작 없이 대상 run만 실행하며 DB0색인100건/DB3파일검증 대기는 조작하지 않는다.

**실행과 보존:** 기존 화면의 첫 제출은 같은 request_id로 이전 완료 run을 반환했으며 새 run/attempt/모델 호출은 없었다. 정상 새로고침 후 같은 자료·규칙·구성v2·정책·K10·빈 대화 이력·반복2를 입력해 새 run `e0331df7-9829-4f60-9af6-4fd9fc50db98`를 17:39:53 UTC에 생성했다. 이전 run `7cb86b65-78d1-47d1-8b57-2ecc68ba295f`와 snapshot 원본 bytes/digest 및 rules digest가 완전히 같다. 새 실행 프로세스 PID9888은 최신 표 선택 제품2파일 SHA와 현재 generation config·배포 timeout360/retry0·정확히4개의 pending attempt1을 검사한 뒤 등록된 `ai_workshop.rag.evaluate_generative_run`.apply(throw=True)를1회 호출했다. 17:40:15→17:45:26 UTC, SUCCESS/exit0이며 최종 DB와 owner UI 모두4completed/진행·대기·실패·중단0을 확인했다. 코드 변경·큐 소비·reconciler 실행·재시작 없이 정상 admission과 run/attempt 행잠금·claim token 검사를 유지했다.

**결과:** 실제 생성은 **2/4회**, 정답 시도2개는 `no_eligible_evidence`로 생성 미호출이다. 정답 근거는 두 번 모두 fused1/dense1/sparse4로 검색됐으나 선택·전송·인용0, 문맥 충족0/2·정답0/2였다. 거절 시도2개는 각각 선택/감사 전송 근거26개가 일치하고 실제 Gemma 호출 뒤 `insufficient_evidence`로 정상 거절했다. 각 provider 입력9549/출력19/total9568/finish_reason=stop, reasoning_tokens와 correlation_id는 unavailable이다. 권한 노출0, 인용은 생성된 답변이 없어 검증 대상 없음이다. UI/metric의 generation_completed는 최종 결과 상태이며 실제 provider 호출 횟수가 아니다.

실행 순서대로 기록한 단계별 시간(초; 기존 기록값 반올림):

| 시도 | 전체 | 요청 준비 | 검색 | 선택 | 생성 | 결과 저장 |
|---|---:|---:|---:|---:|---:|---:|
| 정답 2회차 | 18.056 | 0.521 | 10.224 | 7.213 | 생략 | 0.113 |
| 거절 1회차 | 263.564 | 0.851 | 2.845 | 7.014 | 252.707 | 0.085 |
| 정답 1회차 | 12.267 | 0.563 | 4.491 | 7.145 | 생략 | 0.037 |
| 거절 2회차 | 14.017 | 0.525 | 4.494 | 6.988 | 1.865 | 0.079 |

전체 observation 시간은 결과 저장 이전에 확정되므로 단계 합계와 정확히 같지 않다. 정책과 같은 SQL percentile_cont(0.95)는 **226738.120185ms**, 이전229849.529235ms와 모두120000ms 초과다. 실제 provider HTTP 지연은252699/1855ms이며 이전235544/1779ms보다 첫 생성은 더 길었다. 입력이 같아도 run 내부 attempt 순서는 UUID 정렬 영향으로 달랐으므로 이1회 비교를 성능 개선 증거로 보지 않는다.

**근거 탈락의 실제 원인:** 추가 모델/임베딩 없이 frozen source를 순수 객체로 재구성해 helper 반환 위치를 추적했다. 헤더·5개의3열 행은 정상 인식됐으나 마지막 원문 ordinal31(합성 자료 안내)과32(페이지 번호02/03)가 동일 y800.296~810.928의 두 셀 행으로 묶였다. `table_context.py:89`의 `ended=True` 이후 다중 셀 행 거부 조건에서 None을 반환했다. 일반 표 혼동 방지 조건이 표 밖 footer까지 거부한 것으로, 새 구조 경로는 실제 정답 청크에 적용되지 않았다. 합성 fixture의 한 줄씩 배치된 footer로는 잡지 못한 실제 레이아웃 차이다. 이번 평가·진단 승인에서는 제품을 수정하거나 평가를 다시 실행하지 않았다.

**지연 관측과 한계:** 실행 전 모델 미적재와 가용 RAM 약4.25GiB, 첫 생성 도중17:40:56 UTC에252,809,216B(약241MiB)/사용률98%, 17:42:26에는3,785,125,888B/85%를 관측했다. 후자의 `/api/ps`는 gemma4 적재·runner llamacpp·context_length16384·size_vram0을 보고했다. 모델 로드/초기 입력 처리/메모리 압박은 가능한 원인이지만 인과 및 각 기여 시간은 미확정이다. 기존 응답/저장 계약에는 입력·출력 토큰과 전체 provider 지연만 있고 load_duration/prompt_eval_duration/eval_duration 분리값은 확보하지 못했다. 확인한 기존 Ollama 로그 위치에도 사용 가능한 로그 파일이 없었다. 추가 워밍업·시험 생성·새 계측 소프트웨어·영구 설정은 사용하지 않았다.

**독립 검증과 인계:** 별도 검증자가 읽기 전용 DB로4completed/attempt1·동일 snapshot bytes/rules·실제생성2회·위 검색/선택/전송·P95·footer 반환 위치를 재확인했다. acceptance0, Gemma 구성 pending/defaultfalse, Gemma 도메인 연결0, 기존 활성 연결 `baa19d13-09e2-466b-a410-8a844d0a65a3` 유지도 확인했다. 이번 승인으로 평가 쓰기는 수행했지만 승격/도메인 활성화/추가 일반대화/재시도/서비스·큐·색인 변경/migration/commit/push는0이다. 제품과 기존 테스트는 변경하지 않아 이전5991unit·Mypy471·Ruff를 재실행하지 않았고, 최초 diff와 최종 검증 SHA 보존을 확인했다. 관리자 문제 DB 갱신은 승인 범위 밖이므로 미반영으로 남긴다. 다음 후보는 footer/주변 본문과 표 경계를 분리하는 한정 오프라인 수정·원문 보존 회귀이며, 추가 실모델 평가는 별도 승인이 필요하다. 상세 수치의 로컬 근거는 `.local-data/project-agent-work/table-context-evaluation-20261014/results.json`에 보존했다.


### 2026-10-14 실제 저장 PDF footer 회귀 보완

승인 범위는 직전 실평가의 실제 저장 원문을 사용한 오프라인 회귀와 최소 문맥 선택 수정이다. 이전4attempt 예산은 소진됐으며 새 모델/임베딩 호출·평가·DB쓰기·서비스/도메인 변경은 제외한다. 메인이 요구·RAG·구현·테스트를 담당하고 별도 검증자가 독립 리뷰를 수행했다. 초기 status/diff와 대상 파일 바이트/SHA를 `.local-data/project-agent-work/table-footer-20261014/`에 보존하고 쓰기 전 재확인했다.

**실제 실패 재현:** read-only DB 트랜잭션에서 run `e0331df7-9829-4f60-9af6-4fd9fc50db98`의 공개 합성 자료 `synthetic-product-prospectus.pdf` 청크 `d5f55bda-d34e-4dba-9ce7-04d96083e71d`를 읽었다. 전체 frozen source를 `backend/tests/fixtures/rag/stored_payment_table.json`에 그대로 보존했다. canonical JSON SHA는 `573df69f23f6cc7fc29dc2f3c2e453813ec97269de1db9a1a372e71b37903673`이며 원문33개 ID·순서·본문·bbox·문자 위치·조건·예외·footer가 저장 source와 완전히 같다. 테스트용 구성의 workspace scope를 원문에 맞춘 뒤, 제품 미수정 상태에서 **5 failed / 26 passed(3.45초)**: 정답 선택0과 mock 생성 미전달을 재현했다. 이전 임의 합성 표의 성공으로 이 원문 회귀를 대체하지 않았다. RED 출력은 위 로컬 증거 폴더의 `red.txt`에 남겼다.

**최소 수정:** 제품 변경은 `highlighting/table_context.py` 한 파일이다. 표 뒤 단일 본문 행 이후의 다열 행은 최종2셀인 경우에만 좁은 footer 판별을 적용한다. 오른쪽 전체 텍스트가 현재 페이지와 일치하는 유효한 `현재 / 전체`이고, 왼쪽 셀이 본문 왼쪽 여백과 같으며 표보다 왼쪽에 있고, 오른쪽 셀은 표 전체보다 오른쪽에 있어야 한다. 두 셀은 비중첩·같은 행 높이이며 표/본문보다 bbox 높이가 작고 마지막 본문과 충분히 떨어져야 한다. 절대 좌표·상품·안내 문구를 고정하지 않는다. 다른 후속 다열 행·여러 표·불완전 헤더·타열 참조는 기존 거부를 유지한다. footer도 삭제하지 않으며 기존 원문 객체 그대로 유지한다.

**보존과 전달:** 실제 원문33개에서 다른 상품 열의 ordinal8/11/14/17/20만 제외하여28개를 선택했다. 정답 `접수일 T+4 영업일`의 원래 ID `25b7b690-dd81-440e-9bd8-1e1020823e65`, 모든 표 밖 조건·예외·분리 부정문·계산 예시·달력 안내와 footer31/32를 보존했다. `test_stored_table_context.py`는 실제 fixture의 선택·오선택 방지·예산·좌표 이동/크기 변경·whole-chunk 복귀를 검사한다. 기존 `test_table_context_generation.py`를 실제 fixture로도 실행하여 원문 ID/본문28개가 mock 생성 요청·감사·grounding·응답 인용에 일치하고 diagnostics on/off에서 같음을 확인했다. 모든 embedding/runtime은 fake이며 실제 모델 호출이 아니다. 선택 상세는 로컬 `selection-proof.json`에 보존했다.

**검증:** 독립 검증자가 highlighting 전체+해당 search 회귀를 별도로 실행하여 **163 passed, 6.13초**, 추가 결함/차단 없음으로 리뷰했다. 실제 fixture+검색 회귀는 **35 passed, 3.64초**다. backend `.venv/Scripts/python.exe -B -m mypy src`는 **471source files 성공**, 변경 제품1·테스트2파일의 Ruff는 **All checks passed**다. 전체 RAG 단위 `.venv/Scripts/python.exe -B -m pytest tests/unit/labs/rag -q --tb=short`는 **6024 passed, 17 skipped, 1 warning, 340.75초**로 exit0이다. 경고는 기존 Starlette TestClient/httpx deprecation이며 skip은 통과로 집계하지 않는다.

**남은 범위:** 실제 모델·임베딩 호출/새 평가/DB쓰기/서비스 재시작/승격/도메인·기본값 변경/migration/commit/push는0이다. 전체 backend pytest·DB 통합·브라우저 E2E와 실모델 재평가는 미실행이다. 이 판별은 제한된 레이아웃만 지원하며 일반 PDF 표 해석 완료를 뜻하지 않는다. 직전 실평가의 정답0/2·P95226.74초 및 기능 마감/문제 DB 반영 잔여는 그대로다. 추가 실평가는 별도 승인이 필요하며 첫 생성 지연의 로드/입력/생성 분해는 여전히 미확인이다.


### 2026-10-14 승인 단일 정답 검색 실행 중단

사용자가 실패 정답 질문 `AM-SYN-101을 현금화하면 돈은 며칠 뒤 받을 수 있어?`의 로컬 Gemma 단일 요청1회/최대생성1회를 승인했다. 기존 구성v2·프로파일v3·동결 원문을 유지하고 추가 워밍업·자동재시도·전체4건 평가·도메인 활성화·기준 변경은 제외한다. 기존 owner UI 로그인과 현재 활성 owner 계정, 동일 snapshot/rules digest·프로파일 config·local/nonexternal Gemma timeout360/retry0을 읽기 전용으로 확인했다. 시작 전 가용 RAM4,902,105,088B, Ollama0.40.3의 적재 모델0이었다. 등록 Task는 전체 run만 실행하므로 기존 `FrozenGenerativeAdapter.prepare`·`get_search_service`·`pipeline.execute`를 새 독립 프로세스의 단일 검색으로 조립했다. 기존 평가 run/attempt를 생성·claim·재사용하지 않았고 현재 권한·정책·strict 응답/인용 경로를 보존하도록 준비했다. 제품 코드는 변경하지 않았다.

**실행 실패와 책임:** PID139512, 새 correlation `c1d0ec48-dc02-4b8e-9a08-ca1877f8bfa7`, 18:14:56.771933 UTC에 요청1회를 예약했다. 기존 `verify_original_runtime(writer=True, non_es=False)` admission을 통과하고18:14:57.316561 검색을 시작했으나18:14:57.351666에 `AssertionError`로 종료했다(exit1). 예약부터 실패까지579.733ms이며 모델 지연이 아니다. 메인이 작성한 한 번 실행용 `GuardedRuntime.health()`가 정상 파이프라인의 필수 비추론 `GET /v1/models`까지 워밍업으로 오분류해 차단했다. 사전 독립 리뷰도 이 필수 호출을 놓쳤다. 이는 실행 검증 도구의 오류이며 Gemma·footer 제품 수정의 실패 또는 보안/정책 차단으로 보고하지 않는다.

**진단·독립 확인:** 검색을 다시 실행하지 않고 현재 구성 resolver를 READ ONLY 트랜잭션으로 확인하여 provider/location/model/timeout/retry guard가 모두 충족됨을 검증했다. wrapper 클래스의 health 메서드만 offline fake로 호출하면 같은 AssertionError가 발생하고 위임0회임을 재현했다. 독립 검증자는 `pipeline.py:408`의 필수 health 호출과 실제 adapter의 비추론 GET 구현을 확인했다. 해당 correlation의 생성 audit0건이며 generation-started/input/provider-result/completion 파일도 없다. 이전 두 평가 run은 각각 completed4·attempt_number1·acceptance0을 유지한다. 실제 생성0회·새 평가0회·재실행0회이고 요청 예산1/1은 실패로 소진했다. 선택28개·정답 근거 ID의 실제 생성 입력 포함·답변·인용·Gemma 소요 시간은 이번 실행에서 미검증이다. 기존 offline6024통과 결과를 실제 생성 성공으로 확대하지 않는다.

**보존과 다음 경계:** API/Ollama 재시작, 인증정보 추출, 보호 설정·도메인·기본값 변경, migration, commit/push를 하지 않았다. 실행 스크립트와 예약 표시를 고치거나 삭제해 재시도하지 않는다. 다음 후보는 비추론 health를 정상 위임하는 실행 관찰 wrapper의 offline 계약 검증이며, 실제 재호출은 새 승인 없이는 하지 않는다. 초기 diff/status·문서 사본, preflight·request-started/error·diagnosis는 `.local-data/project-agent-work/table-footer-single-search-20261014/`에 보존했다. 제품/테스트 SHA가 직전 검증과 같으므로 전체 RAG/Mypy/Ruff는 반복하지 않았다. 기존 WORKBOARD와 본 기록만 최소 갱신한다.


### 2026-10-15 단일 검색 wrapper 오프라인 준비 검증 마감

PC 연결 복구 후 사용자가 승인한 범위는 이전 실행 준비 코드의 mock·정적 검사·보존 확인과 기존 문서 마감이다. 실제 모델·임베딩·검색/평가·DB 변경·예약 초기화·서비스 재시작·설치·commit/push는 포함하지 않았다. 메인은 검증·기록 통합, 독립 코드 리뷰어는 읽기 전용 재실행·검토를 맡았으며 UI·DB·배포·권한 변경 역할은 범위가 없어 제외했다. 재개 전 status/diff, 관련 파일과 미커밋/미추적 파일121개의 SHA를 `.local-data/project-agent-work/single-search-preparation-20261015/`에 보존했다. 이전 준비 시작 시점의 tracked diff와 비교하면 메인이 추가했던 WORKBOARD 준비 문장만 달랐다. 사용자 수정으로 추정되는 다른 내용을 되돌리거나 정리하지 않았다.

**구현과 범위:** 이전 작업에서 `GuardedRuntime.health()`가 실제 adapter의 비추론 `GET /v1/models`를 위임하도록 수정했다. `SingleGenerationTransport`는 정확한 로컬 origin·메서드·raw path만 허용하고 생성 POST 위임 전에 exclusive 파일로 예산을 예약한다. timeout·취소·실패 뒤에도 예약을 보존하며 동시/새 wrapper의 추가 POST를 차단한다. 정상 resolver가 반환한 실제 `LocalOpenAICompatibleRuntime`에 동일 guarded client를 주입하고 proxy·redirect·transport retry를 비활성화한다. 질문·프로파일·기존 정책 경로는 유지한다. 이번 재개에서는 `search_once.py`의 Ruff import 정렬만 보완했고, import 집합 및 나머지 AST가 이전과 같음을 확인했다. 제품 코드는 변경하지 않았다.

**환경 실패와 실제 통과를 구분:** 처음 명령은 기존 sandbox 임시 폴더 생성 실패로27개 setup errors였다. 기존 폴더/권한을 변경하지 않고 새 workspace basetemp를 사용했지만 첫 async fixture에서 정지했다. 저장소 `tests.conftest`의 Windows selector 설정을 명시해도 동일했다. 시간 제한 진단에서 `socket.accept → _fallback_socketpair → asyncio._make_self_pipe → pytest_asyncio fixture` 대기를 확인했다. 무응답 테스트 세션은 정확한 세션에 Ctrl-C를 보내 종료했고, 자체 생성한 진단 자식은35초 timeout으로 종료했다. API/Ollama/DB 서비스를 조작하지 않았다. 이후 승인 심사를 거친 동일 mock 명령은 **27 passed, 2.60초, exit0**였다. 보호 설정을 바꾸거나 실제 HTTP 차단 fixture를 제거하지 않았다. 독립 리뷰어도 같은 조건의 새 basetemp에서 **27 passed, 2.46초, exit0**를 확인했으며 추가 차단 결함이 없었다. 환경 실패 진단은 통과 기록과 함께 보존했다.

**검증 내용:** 실제 pipeline·adapter 코드가 모델 목록 GET → 권한 재확인 → 가짜 검색/원문 → 원래 근거28개 선택 → 생성 POST1회 → schema2 엄격 파싱 → 원문 인용 → 가짜 감사 저장까지 실행됐다. 근거 ID/본문28개와 `접수일 T+4 영업일`의 원래 ID `25b7b690-dd81-440e-9bd8-1e1020823e65`를 확인했다. 이는 canned mock 응답이며 실제 모델 정답이나 처리속도 증거가 아니다. 두 번째 생성/동시 POST/새 guard/취소 후 호출, 잘못된 retry2 설정에서도 wire POST1회, 외부 origin·경로·userinfo·query·fragment·redirect, health 실패, 잘못된 schema/인용, 진단 저장 실패 시 원래 오류·감사 보존을 검사했다. 모든 HTTP는 MockTransport이고 embedding·retrieval·audit는 fake다. `pipeline-proof.json`과 `pytest-approved.json`에 결과를 보존했다.

**실행한 검증 명령:** 아래 cwd는 `backend`다. 기록된 basetemp는 이번 실행 전 존재하지 않았으며, 후속 검증에서는 기존 경로를 재사용/삭제하지 말고 새로운 미존재 경로를 사용한다.

```powershell
.venv/Scripts/python.exe -B -m pytest -p tests.conftest -c pyproject.toml -o "pythonpath=. src ../.local-data/project-agent-work/table-footer-single-search-20261014" ../.local-data/project-agent-work/table-footer-single-search-20261014/test_preparation.py ../.local-data/project-agent-work/table-footer-single-search-20261014/test_flow.py --basetemp=../.local-data/project-agent-work/single-search-preparation-20261015/pytest-approved-1 -q --tb=short -rP
.venv/Scripts/python.exe -B -m mypy src
.venv/Scripts/python.exe -B -m mypy --strict --follow-imports=silent ../.local-data/project-agent-work/table-footer-single-search-20261014/single_search_guard.py
.venv/Scripts/python.exe -B -m ruff check ../.local-data/project-agent-work/table-footer-single-search-20261014/search_once.py ../.local-data/project-agent-work/table-footer-single-search-20261014/single_search_guard.py ../.local-data/project-agent-work/table-footer-single-search-20261014/test_preparation.py ../.local-data/project-agent-work/table-footer-single-search-20261014/test_flow.py
```

backend Mypy는 **471 source files**, 새 transport의 strict Mypy는 **1 source file**, Ruff는 위 **4파일 All checks passed**다. wrapper와 테스트를 strict 타입 검사했다고 확대하지 않는다. 4개 Python 파일의 compile-only 검사도 통과했으며 `main()`은 실행하지 않았다. 원래 실패·예약 증거8개, footer 제품/테스트/fixture4개, `context.py`1개의 SHA **13개 일치**를 `preservation-final.json`에 기록했다. 기존 request-started correlation과 소진1/1을 유지했고 실제 generation-started/generation-post-started 기록은 생성하지 않았다.

**준비 상태와 남은 검증:** 오프라인 코드 준비·27개 수용 검증은 완료했다. 기존 실행 스크립트는 이미 소진된 예약으로 직접 재실행이 차단된 상태다. 실제 재시도에는 새 명시 승인, 기존 증거를 유지하는 별도 실행 기록, 현재 원래 환경/구성/권한/메모리의 사전 확인이 필요하다. 추가 로그인·인증 추출·설치·재시작은 이번 오프라인 검증에 필요하지 않았다. 현재 서비스 readiness와 DB·모델 상태는 이번에 조회/검증하지 않았다. 실제 답변·인용·지연, 전체 RAG 재실행·DB 통합·브라우저 E2E·운영 수용은 미실행이다. 과거 정답0/2·P95226.74초·기능 마감 차단·학습 문서 및 예약 알림은 그대로 유지한다.


### 2026-10-15 재승인 단일 질문 — 생성 전 ImportError 종료

사용자가 이전 질문의 단일 로컬 Gemma 재시험을 새로 승인하고 안내받은 CMD 명령으로 Ollama를 직접 시작했다. 이번 승인은 질문1회·실제 생성 POST최대1회·자동 재시도0이며 전체 평가/도메인 활성화/서버 시작·종료/설치/DB 수동 수정/commit/push를 포함하지 않는다. 기존10/14 소진 예약과 실패 기록은 그대로 두고 `.local-data/project-agent-work/table-footer-single-search-20261015/`에 새 승인·사전 확인·예약·결과를 분리했다. `search_once.py`와 HTTP guard는 오프라인27개 및 독립27개를 통과한 코드와 바이트가 동일하다. 독립 리뷰어가 BASE의 새 경로, 기존 기록 보존과 호출 제한을 확인했다. 제품 코드는 변경하지 않았다.

**실제 사전 확인:** 사용자 Ollama0.40.3의 GET version/models/ps/tags가200이며 대상은 `gemma4:e2b-it-q4_K_M`, 로드 모델0개였다. `C:/AI/OllamaModels/manifests/registry.ollama.ai/library/gemma4/e2b-it-q4_K_M`은 API digest의 원본 manifest를 layer로 참조하는 포장 구조였다. 최초 체커는 파일 전체 SHA와 API digest를 바로 비교해 AssertionError를 냈고, 그 실패를 `preflight-attempt1.json`에 보존했다. 참조된 원본 blob1552bytes의 SHA `b37049369adfe3d2b653af0ab301a062ca5cbe96ace6aa0d3f2559ee9b563fc2`와 layer 크기/참조 일치를 확인해 경로·대상 파일 연결을 검증했다. 서버 프로세스의 실제 환경변수는 API로 노출되지 않아 `OLLAMA_MODELS`/context16384의 실제 적용값 자체를 확인했다고 확대하지 않는다.

기존 DB의 READ ONLY transaction에서 활성 owner, 원래 run completed·snapshot/rules digest, 비기본 구성v2·생성 프로파일v3와 local/nonexternal/Gemma/timeout360/retry0를 확인했다. 평가 진행0, 전체 run8·attempt527이었다. 가용 RAM은 최종 사전 검사7,717,797,888B였다. 정상 `verify_original_runtime(writer=True, non_es=False)` admission 및 Elasticsearch9.5.2 info 조회도 통과했다. API18000은 ConnectError였지만 검증된 wrapper는 같은 원래 설정·권한·정상 application service를 별도 프로세스에서 조립하므로 API 서버를 시작하거나 우회 경로로 대체하지 않았다. 사전 검사는 검색/추론을 실행하지 않았으며 native 임베딩 패키지 import 성공까지 확인한 것은 아니었다.

**실행과 종료:** 승인된 새 wrapper를1회만 실행했다. 새 correlation `ea4659b4-c442-4f2e-8cad-e4c8c394361c`, PID25832, 예약00:30:32.334908 UTC, admission00:30:32.450000, 검색 시작00:30:33.081024, 오류00:30:51.617234에 `ImportError`/exit1로 종료됐다. 예약부터 실패까지 **19,282.326ms**, 검색 시작부터 종료까지 **18,536.210ms**이며 생성 지연은 아니다. 실제 generation-started·generation-post-started·generation-input·provider-result·search-result·completion 파일은 모두 없다. 따라서 **요청1/1 소진, 실제 생성 POST0, 자동/수동 재실행0**이다. 실제 선택 근거·정답·인용·생성 시간은 미검증이며 PDF2쪽의 `접수일 T+4 영업일`은 기대 근거로만 유지한다.

**비추론 원인 진단:** 실패 후 질문·검색·모델 로드를 재실행하지 않고 `backend/.venv/Scripts/python.exe -B -X utf8 -c "import sentence_transformers; print('IMPORT_OK')"`만 실행했다. 이 독립 import는 sklearn → scipy.stats → scipy.optimize._direct에서 `ImportError: DLL load failed while importing _direct: 애플리케이션 제어 정책에서 이 파일을 차단했습니다.`로 종료됐다. 원래 실패 wrapper는 상세 stack을 보존하지 않아 그 실요청의 직접 발생 모듈까지 확정하지는 않는다. 다만 동일 임베딩 의존성의 native DLL 정책 차단은 별도 import에서 실제 재현됐다. 정책 완화, 파일 해제, 대체 로더, 재설치 또는 다른 모델 전환은 하지 않았다. 이것을 Ollama 생성 실패나 footer 정답 품질 실패로 해석하지 않는다.

**사후 확인과 한계:** READ ONLY 조회에서 해당 correlation의 생성 audit는 **0건**, 전체 run8·attempt527은 사전 값 그대로였다. Ollama GET ps도 여전히 로드 모델0개다. 독립 리뷰어가 예약·실패·파일 부재·저장된 사후 결과를 별도로 확인했다. 성공한 감사 저장이라고 보고하지 않으며, ImportError가 정상 오류/감사 처리 밖으로 빠져나온 지점은 후속 오프라인 검토 대상이다. `request-started/error.json`, `outcome.json`, `import-diagnosis.json`과 최초 diff/status·보존 SHA를 새 디렉터리에 유지했다. 기존10/14 기록은 변경하지 않았다.

**다음 경계:** 이번 단일 시험은 종료했으며 승인된 새 요청도 소진됐다. 다음 후보는 현재 정책 안에서 DLL 차단 원인·정상 승인 경로와 native import 사전 확인/오류 상태·감사 회귀를 조사하는 것이다. 실제 질문 추가 실행은 별도 승인 대상이다. 운영 문제 이력 DB는 수동 쓰기/관리자 변경 승인이 없어 갱신하지 않았고 DLL 재현·감사 누락의 관리자 이력 반영은 미완료로 남긴다. 기존 실평가 정답0/2·P95226.74초·별칭 복구/본래 UI 수용·학습/알림 예약은 변경하지 않았다.

### 2026-10-15 사용자 제공 CodeIntegrity 이벤트로 차단 정책 확인

사용자가 제공하고 상위 작업에서 전달한 이벤트에서 `scipy/optimize/_direct.cp313-win_amd64.pyd`의 차단 정책은 `VerifiedAndReputableDesktop`, PolicyGUID `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`, Status `0xc0e90002`로 확인됐다. 이벤트의 SHA256 Flat Hash `29c297b7561a0310de2d181b3b43cef7591e64b9927b10f71edeae3985f7e8b8`는 기존 조사 및 이번 파일 읽기의 SHA256과 일치한다. 따라서 별도 import에서 재현한 `_direct` 차단을 해당 정책과 연결할 수 있다. 이 정책은 기존 [10/6 조사](2026-10-06-rag-budget-runtime-diagnosis.md)와 [Microsoft 기본 정책 설명](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/inbox-appcontrol-policies)이 식별한 Smart App Control 정책이다. 에이전트의 직접 이벤트 로그 열람은 앞선 조사에서 권한 거절되어 중단했으며, 이번 확인 근거는 사용자가 제공한 이벤트다.

별도3033 이벤트는 `scipy/linalg/_internal_matfuncs.cp313-win_amd64.pyd`를 가리키며 기록 시각은 `2026-10-15 00:30:51 UTC`다. 이는 실제 단일 요청 실패 시각과 같은 초지만, 전달받은 정보에는 해당 이벤트의 PID/ActivityID 연결 및 실요청 상세 stack이 없으므로 실요청의 직접 실패 모듈을 확정하지 않는다. 현재 확인된 영향은 SciPy native 의존성을 사용하는 임베딩 준비 경로의 로드 차단이며, Gemma 생성 품질 실패나 저장 데이터 손상 증거가 아니다.

설치 파일을 실행하지 않고 읽은 결과 SciPy1.18.1의 `_direct`는70,656bytes, `_internal_matfuncs`는172,032bytes이며 두 파일 모두 설치 RECORD의 해시·크기와 일치했다. 후자 SHA256은 `ceb1ff22d068586d34e82fa0a713394457aec312d8bd013051bdc8b6987b91fa`다. `_direct`는 앞선 Authenticode 조사에서 NotSigned였으며, 이번에는 후자의 서명을 별도로 검사하지 않았다. RECORD 일치는 설치 메타데이터와의 일치이고, 이번 두 파일을 원격 공식 wheel과 대조하거나 전체 설치의 무결성을 검증했다는 뜻은 아니다. 과거 `_lsap`·`_duccfft` 차단 후 같은 환경에서 import가 통과한 이력만으로 현재 복구나 영구 해결을 주장하지 않는다. 이번에는 추가 import·검색·모델 호출·정책/예외 변경·재설치·서비스 조작을 하지 않았다. 복구 미완료와 단일 요청 승인 소진 상태는 유지한다.

### 2026-10-15 승인 Miniconda 독립 시험 — 다운로드 전 이름 해석 실패

사용자는 약관 안내 후 개인 프로젝트용 별도 Miniconda 설치·최소 수치 계산 시험 및 이번에 만든 불필요한 설치물 정리를 승인했다. 실행 호스트 `BOMI`와 작업 경로 `C:/projects/ai-workshop/.local-data/project-agent-work/miniconda-scipy-signed-20261015/`를 확인하고 최초 상태를 기록했다. 기존 uv 환경·lock·DB·모델·기본 Python·보안 정책을 바꾸지 않는 범위이며, RAG/임베딩/Gemma 실행은 승인 범위가 아니다.

[공식 Miniconda 인덱스](https://repo.anaconda.com/miniconda/) 웹 조회에서 `Miniconda3-py313_26.7.1-1-Windows-x86_64.exe`, 표시 크기124.5M, SHA256 `ff485c617e0e15addc111aa1caa206679e214d223624297bf8aa0bc726ed67bd`를 확인했다. 이는 인덱스 값 확인이며 실제 다운로드 파일의 해시 검증은 아니다. 설치 전 의존성·전체 용량 산정을 위해 BOMI에서 `https://repo.anaconda.com/pkgs/main/win-64/current_repodata.json`을 받는 첫 요청이 `urllib.error.URLError: <urlopen error [Errno 11001] getaddrinfo failed>`로 종료됐다. 이름 해석 실패이며 권한 거절·Smart App Control 차단·설치 아키텍처 오류로 확정하지 않는다. 권한 상승이나 대체 다운로드 경로를 시도하지 않았다. 별도 웹 도구의 SciPy 패키지/API 조회도 내용을 반환하지 않아 후보 메타데이터 재검증과 전체 다운로드·설치 용량 산정은 미완료다.

실제 설치 파일/패키지 다운로드0, 설치0, 새 native import/수치 계산0이다. 따라서 서명 유효성·Windows 실행·RAG 전환 가능성은 아직 검증하지 않았다. 생성한 빈 `metadata`·`downloads`·`tmp` 세 폴더만 정확한 절대경로·reparse point 부재·비어 있음 재확인 후 제거했다. 제거 파일 용량0bytes이며 최초 상태와 실패 결과3파일253,102bytes는 위 경로의 `evidence/`에 보존했다. 직후 C: 여유 공간136,353,669,120bytes는 관찰값이며 빈 폴더 정리의 회수 효과로 해석하지 않는다.

문서 반영 전에 추적 파일1,886개의 내용 해시, 원래 venv `python.exe` 해시, 검증 프로세스 PATH 및 `where python` 결과가 최초 값과 같음을 확인했다. 이는 venv 전체·시스템 전체 환경·모든 미추적 파일 검증을 뜻하지 않는다. 기존 환경 전환·DB/서비스 조작·보안 변경·실검색·모델 호출·commit/push는 하지 않았다. 다음 단계는 정상 다운로드가 가능한 실행 조건을 확인한 뒤 동일 격리 시험을 재개하는 것이며, 설치/계산 성공으로 보고하지 않는다.

**같은 공식 호스트 연결 재확인:** 상위 요청에 따라 설정·권한을 바꾸지 않고 `repo.anaconda.com`을 다시 진단했다. Python의 DNS 조회와 공식 Miniconda 인덱스 HTTPS HEAD 모두11001 이름 해석 실패였다. Windows `Resolve-DnsName -DnsOnly -QuickTimeout`은 오류5/액세스 거부(`5,Microsoft.DnsClient.Commands.ResolveDnsName`, Category `ResourceUnavailable`)를 반환했고, 같은 진단 명령의 `Invoke-WebRequest -Method Head`도 호스트를 찾지 못했다. 진단 스크립트의 중단 조건이 `PermissionDenied` 분류 또는 `UnauthorizedAccessException`만 검사해 `ResourceUnavailable`로 반환된 오류5를 즉시 감지하지 못했고, 같은 명령의 HTTPS HEAD까지 실행됐다. 반환된 접근 거부를 확인한 뒤 추가 네트워크 시도·권한 상승·미러/DNS/프록시 변경은 하지 않았다. 최초11001 자체를 정책 거절로 재해석하지 않으며, PC 전체 연결 문제인지 Codex 실행 환경의 접근 제한인지와 SciPy 차단과의 관련성은 미확정이다. 설치·다운로드·native 계산은 여전히0이다. 진단2파일을 기존 `evidence/`에 추가 보존했다. 최소 후속 확인은 사용자가 BOMI의 일반 PowerShell에서 같은 공식 호스트의 DNS와 HTTPS HEAD 결과를 확인하는 것이며 관리자 실행·보안 변경을 요구하지 않는다.

### 2026-10-15 사용자 다운로드 Miniconda 검증 — 설치 파일 실행 전 오류

사용자가 제공한 정확한 설치 파일 `Miniconda3-py313_26.7.1-1-Windows-x86_64.exe`를 읽었다. 크기는130,502,080bytes이고 SHA256 `ff485c617e0e15addc111aa1caa206679e214d223624297bf8aa0bc726ed67bd`가 공식 인덱스의 기존 후보와 일치했다. Windows `Get-AuthenticodeSignature`는 **Valid / Signature verified**, 서명자 **Anaconda, Inc.**, 지문 `A83A0F70E5AB4EC981F4362FCABC254CB8388184`, 타임스탬프 서명자 DigiCert SHA512 RSA4096 Timestamp Responder 2025 1을 반환했다. 설치 파일의 검증이며 Python/NumPy/SciPy 실행 성공을 의미하지 않는다.

기존 환경을 변경하지 않는 옵션을 확인하려 같은 서명 파일의 `/?` 도움말만 `Start-Process -WindowStyle Hidden`으로 실행했으나, Windows가 **잘못된 DLL 재할당 / 시스템 DLL이 메모리에 다시 할당됨** 오류를 반환했다. ErrorId는 `InvalidOperationException,Microsoft.PowerShell.Commands.StartProcessCommand`, Category는 `InvalidOperation`이며 숫자 Win32 원인은 수집되지 않았다. 도움말을 얻지 못했고 설치 명령·권한 상승·재실행·경고 우회를 하지 않았다. 앞선 SciPy Smart App Control 차단과 같은 원인 또는 설치 파일 손상이라고 단정하지 않는다.

승인된 테스트 경로의 `base`는 생성되지 않았고 해당 설치 파일 이름의 프로세스 조회는 `NoProcessFoundForGivenName`이었다. 설치0, SciPy/NumPy 의존성 다운로드0, import·linalg/optimize 시험0이다. 원본 설치 파일의 해시는 사후에도 같았으며 사용자가 받은 파일은 보존했다. 원래 uv lock·pyproject·venv 설정/launcher·문서2개의 해시와 검증 프로세스 PATH/where python은 이번 문서 반영 전 기준과 일치했다. DB·모델·서비스·보안 설정과 프로젝트 실행 환경을 변경하지 않았다.

이번에 만든 빈 `installer-tmp` 폴더와0bytes 도움말 stdout/stderr2파일만 정확한 경로·reparse point 부재·빈 상태 확인 후 제거했다. 이전 실패 기록과 이번 검증·실패 증거는 `.local-data/project-agent-work/miniconda-scipy-signed-20261015/evidence/`에 보존한다. 설치 직전 여유 공간은141,092,052,992bytes였으며 전체 의존성 다운로드/설치 용량은 아직 산정하지 못했다. 현 단계 차단은 검증된 설치 파일의 프로세스 시작 오류이며 별도 Windows 실행 환경 진단이 필요하다. 서명 검증 통과를 SciPy 복구나 프로젝트 전환 가능성 검증 완료로 보고하지 않는다.

### 2026-10-15 사용자 설치 Miniconda 확인 — 최소 환경 dry run 연결 실패

사용자가 Miniconda를 직접 설치했다고 알려 일반 설치 위치만 좁게 확인했다. 사용자 설치의 Python3.13.15는 `-I -B --version`을 정상 출력했다. 설치 등록 정보 HKCU Uninstall 조회는 접근 거부5로 종료하여 해당 조회를 재시도하지 않았다. `Scripts/conda.exe --version`은 Windows DLL 재할당 오류였으나, 설치된 `conda/__main__.py`가 제공하는 정상 모듈 진입점 `python -I -B -m conda --version`은 conda26.7.1을 정상 출력했다. 패키지 코드·로더 수정이나 보안 설정 변경은 없었다. Python 실행 파일·python313.dll·conda.exe 세 파일의 Authenticode는 모두 Anaconda, Inc.의 Valid였다. 서명 유효성과 각 진입점 실행 결과를 구분한다.

base를 수정하지 않도록 기존 시험 루트 아래 새 `trial-5`의 환경 prefix·패키지 캐시·임시 디렉터리·자식 프로세스 캐시 위치만 사용했다. 자동 base 갱신·환경 등록·기본 추가 패키지·자동 약관 수락을 끄고 공식 `https://repo.anaconda.com/pkgs/main`만 지정하여 `create --dry-run --json --no-default-packages --override-channels`로 Python3.13·NumPy·`scipy=1.18.1=py313hcca3590_0`·OpenBLAS의 의존성 계획을 요청했다. 약7.4249초 뒤 `CondaHTTPError HTTP 000 CONNECTION FAILED`로 exit1이었다. 실제 원인은 공식 호스트의 `NameResolutionError [Errno 11001] getaddrinfo failed`이며 Windows DNS 접근 거부 경로를 재시도하거나 미러/프록시/DNS/권한을 바꾸지 않았다. 새 약관 수락·실설치는 수행하지 않았다.

SciPy/NumPy 패키지 다운로드0·시험 환경 생성0·native import/linalg/optimize 시험0이다. 의존성 계획이 없어 전체 다운로드·디스크 요구량은 아직 미확정이다. 사용자 base의 conda-meta133파일 해시와 프로젝트6파일·프로세스 PATH·where python 결과는 문서 반영 전 기준과 일치했다. base 전체 파일을 전수 검증한 것은 아니다. `trial-5`의 파일5개388bytes는 목록·해시·절대경로·reparse point 부재와 dry run 종료를 확인한 뒤 제거했다. 사용자 Miniconda 본체·직접 다운로드한 설치 파일·이전 진단은 보존했다. `.local-data/project-agent-work/miniconda-scipy-signed-20261015/evidence/`의 `before-dryrun-5.json`, `dryrun-5.json`, `dryrun-result-5.json`, `cleanup-5.json`이 이번 증거다. 다음 필요한 조치는 사용자 일반 실행 환경에서 같은 공식 저장소의 연결 가능 여부를 확인하는 것이며, RAG/임베딩/Gemma 실행이나 프로젝트 전환은 아직 하지 않는다.


### 2026-10-15 사용자 설치 격리 SciPy — 서명·native 수치 검증 통과

사용자가 일반 PowerShell의 공식 저장소 HEAD 200 OK와 별도 환경 설치 완료 화면을 제공했다. 상위 작업이 확인한 다운로드 표시는58.3MB이며, 에이전트의 과거 DNS 실패와 구분한다. 실제 `C:/projects/ai-workshop-scipy-test/conda-meta`에는27패키지가 있고 모두 공식 `https://repo.anaconda.com/pkgs/main`의 win-64/noarch 채널이다. Python3.13.16, NumPy2.5.3, SciPy1.18.1 `py313hcca3590_0`, libopenblas0.3.31 및 BLAS openblas를 확인했다. SciPy 기록의 archive SHA256은 `6305ebbf3d716798e753b08e7a55fd7eb99e7fc30ba6de1f2cea7145859c7e2b`다. 이번 에이전트 작업에서는 다운로드·설치하지 않았다.

Windows Authenticode 읽기 검사는 SciPy pyd106개·NumPy pyd19개·Library/bin DLL70개·prefix 루트 DLL57개, 총252개 모두 **Valid**였다. 서명자는 Anaconda144개, Microsoft Corporation86개, Microsoft Windows Software Compatibility Publisher22개다. 기존 차단 대응 모듈 `_direct`, `_internal_matfuncs`, `_lsap`, `fft._duccfft.pyduccfft`와 `openblas.dll`도 Valid다. 검사 범위 밖 파일·전체 시스템의 서명 또는 향후 정책 판단을 보장하지 않는다.

첫 정상 `base python -I -B -m conda run --prefix <격리환경> --no-capture-output python ...`은 exit2이며, SciPy 실행 전 `The system cannot execute the specified program` / `conda activate ... exited with code 9020`으로 실패했다. 원인을 SciPy 차단·손상 또는 보안 정책으로 단정하지 않는다. 설치된 `conda/cli/main.py`의 main_sourced, `activate.py`의 PowerShellActivator 및 `shell/condabin/Conda.psm1:79/83`에서 지원 경로를 확인한 뒤, `base python -I -B -m conda shell.powershell activate <격리환경>`가 생성한 명령을 자식 PowerShell에서 실행했다. 생성/활성화와 수치 시험 모두 exit0이었다. 직접 DLL 경로 조작·대체 로더·실행 정책 변경·권한 상승 없이 Conda의 정상 PowerShell 활성화를 사용했으며, 첫 conda run 실패의 원인은 미확정으로 남긴다.

실행 Python·sys.prefix·CONDA_PREFIX와 로드한 NumPy/SciPy/네 native 모듈 경로가 모두 격리 환경임을 확인했다. 실제 통과한7개 계산은 `linalg.solve`의 `[2,3]`, `linalg.expm`의 diag(1,2), `optimize.minimize_scalar`의 x=3/success, `optimize.direct`의 x=[0,0]/fun=0/success, `linear_sum_assignment`의 열[1,0,2]/비용5, FFT([1,2,3,4])의 [10,-2+2j,-2,-2-2j], 정규분포CDF(0)=0.5다. 부동소수 검사는 예상값에 allclose 허용오차1e-12(스칼라 최적화1e-8)를 적용했다. 기존 차단 네 모듈도 직접 import에 성공했다.

시험 전후 base·시험환경 conda-meta와 선택된 프로젝트 uv.lock·pyproject·venv 설정/launcher 총166파일의 SHA가 일치했다. 첫 실행의 부모 PATH/where python도 같았고 두 번째 활성화는 도구 자식 PowerShell에만 적용했다. 이 제한된 검사로 base·venv 전체 파일 무변경을 주장하지 않는다. 처음 만든 임시 Python 시험 파일1개는 종료 후 제거했으며 성공 시험은 -c로 실행해 파일을 만들지 않았다. 성공 후보 환경은 **9,363파일 / 논리 크기317,369,597bytes(약302.67MiB)**로 전후 동일하며 후속 전환 결정 전 보존한다. 패키지 캐시나 사용자 Miniconda·원본 설치 파일은 삭제하지 않았다.

서명 개별 결과·첫 activation 실패·후속 실제 계산 출력·보존 결과는 `.local-data/project-agent-work/miniconda-scipy-signed-20261015/evidence/isolated-scipy-validation-6.json`에 보존한다. 독립 읽기 리뷰는 공식 패키지 메타데이터·네 모듈 존재·표준 PowerShell 활성화 경로를 확인했다. 이는 격리 SciPy의 제한된 성공이며, 기존 .venv 복구·프로젝트 의존성 호환성·임베딩/RAG/Gemma 검증이나 전환 완료가 아니다. 기존 정답0/2·P95·소진된 실질문 승인·DB/서비스·보안 설정·개발 우선순위는 그대로 유지한다.


### 2026-10-15 기존 Conda 환경 프로젝트 전환 준비 — 대상 쓰기 권한 차단

사용자는 검증된 `C:/projects/ai-workshop-scipy-test`를 재사용해 프로젝트에 적용하고 모든 필수 검증 성공 뒤 정확히 대체된 구 `.venv`만 복구 가능하게 정리하도록 승인했다. 새 Conda/venv/복제 환경 생성, DB·문서·모델·학습 기록 삭제/재생성, 보안 변경과 다른 서비스 종료는 제외한다. 새 로컬 E5/Gemma 단일 질문 승인은 이전 소진 승인과 별개이며 이번에는 **미사용0/1**이다. 설치·백엔드 전환과 필수 검증 완료 전 구 환경을 보존한다.

작업 등급은 기존 백엔드 실행 환경의 한정 전환, 위험은 native 패키지 소유권·OCR 호환성·기존 벡터 호환성이다. 메인이 백엔드/AI 런타임·로컬 실행 통합을 담당하고 별도 에이전트가 의존성 조사와 독립 읽기 리뷰를 수행했다. UI·DB 구조·인증 변경은 제외했다. 최초 dirty117개·추적1886파일 SHA와 base/대상 conda-meta162파일 SHA를 `.local-data/project-agent-work/conda-project-transition-20261015/initial-state.json`에 기록했다. `.agents/skills`는 발견되지 않았고 조회한 다른 동일 저장소 로컬 작업은 notLoaded였다. 새 브랜치/worktree와 실행 환경을 만들지 않았다.

독립 조사에서 기존 `.venv`의 dist-info150개 이름·버전은 uv.lock과 일치했다. Python3.13.16은 프로젝트 범위를 만족하지만, `paddlex==3.7.2`의 무조건 `numpy>=1.24,<2.4` 요구는 현재 Conda NumPy2.5.3과 충돌한다. OCR을 제외하거나 제약을 무시하지 않고 현재 lock의 NumPy2.3.5에 맞추는 공식 Conda OpenBLAS 후보를 기존 공식 repodata cache에서 확인했다: `numpy-2.3.5-py313h5f0191a_1.conda` SHA `7cf1227c3be20af390adc063bdf294f233a9c09e266c7dbdc4fd9a61f9424847`(10,653bytes), `numpy-base-2.3.5-py313had128fd_1.conda` SHA `8beb15bab391dd5519a5536997e04b455cfc79b9517b3974d84e00c6d05fd854`(9,758,440bytes). 두 archive 합계9,769,093bytes는 후보 파일의 합계이며 전체 solve/download 규모가 아니다. 새 후보의 실제 서명·수치 검증은 미실행이다.

base 패키지를 수정하지 않도록 공식 main win-64/noarch repodata 사본만 작업 cache에 두고 `python -I -B -m conda install --prefix <기존대상> --dry-run --json --offline --override-channels -c https://repo.anaconda.com/pkgs/main`으로 NumPy 두 build와 기존 Python/SciPy/OpenBLAS 조건의 계획을 요청했다. 약2.79초 뒤 exit1 / **EnvironmentNotWritableError: The current user does not have write permissions to the target environment**로 종료됐다. 설치 계획 계산 전 대상 권한 검사에서 중단했으며, 권한 상승·ACL 변경·검사 우회·다른 쓰기 경로·새 환경 생성은 시도하지 않았다. 네트워크 요청·실제 패키지 설치·서비스 전환은0이다. `conda-align-dryrun.json`에 정확한 명령과 오류를 보존했다.

독립적으로 가능한 준비만 진행했다. uv0.12.19의 정상 `export --frozen --offline --all-extras --all-groups --no-emit-project --no-emit-package numpy --no-emit-package scipy`로 기존 lock의 해시 포함 `project-requirements.txt`를 만들었다. Windows AMD64/Python3.13 활성149개 항목, CPU Torch2.13.0+cpu와 NumPy/SciPy/OpenBLAS 설치 항목 부재를 확인했다. 이 목록은 아직 설치 명령이 아니며, 수치 패키지 정렬 후 모든 활성 요구와 서명 파일 보존 검증을 결합해야 한다. `uv sync`로 대상 Conda prefix를 동기화하지 않는다. `transition-plan.json`에 lock·pyproject·목록 SHA와 남은 게이트를 기록했다. 문서 반영 직전 기존 추적1886파일 및 환경 메타데이터162파일의 SHA는 최초와 같았다.

실행 가능한 후속은 사용자 일반 PowerShell에서 **같은 기존 prefix**에 대한 공식 Conda NumPy2.3.5/OpenBLAS 정렬 dry run을 확인하는 것이다. 계획 통과 뒤 서명·native 수치 검증을 다시 하고, 나머지 잠금 의존성을 보호 패키지 제외·해시 확인으로 설치한 뒤 pip check, backend import/start/health, 관련 오프라인 회귀를 검증한다. 기존 E5 벡터는 공개 합성 `stored_payment_table.json`과 정확한 ES chunk의 저장 embedding을 읽기 비교해야 하며, 현재 로컬 evidence에는 벡터 배열이 없다. 단일 RAG는 새 승인/예약 경로·현재 공개 합성 source allowlist·기존 guard/admission/audit로 정확히1회만 실행한다. 이 작업에서는 ES/DB/모델 호출과 실제 질문을 하지 않았다.

따라서 런처·실행 정본을 새 환경 적용 완료로 변경하지 않았고 기존 `.venv`, 검증된 Conda 환경, 관리용 Miniconda base·설치 파일·모델 cache를 모두 보존했다. 구 환경 정리0이며 backend 시작/health·E5 호환·실질문 정확도/시간·프로젝트 전환은 미완료다. 전체 성공 전에 기존 환경을 제거하지 않는다.


### 2026-10-15 NumPy 정렬 확인과 Conda 전환 도구 준비

사용자가 기존 prefix의 NumPy 정렬을 실행했다고 알린 뒤 읽기 전용으로 재확인했다.
Python3.13.16, NumPy/numpy-base2.3.5, SciPy1.18.1, libopenblas0.3.31은 공식 main/win-64
record의 build·SHA와 일치했다. native 파일252개 Authenticode는 모두 Valid였고,
표준 Conda PowerShell 활성화에서 기존 차단 모듈4개 직접 import 및 수치 계산7개가 통과했다.
이는 수치 계층 확인이며 프로젝트 전체 의존성 설치나 RAG 성공을 의미하지 않는다.

`backend/conda-numeric-lock.json`에 정확한 수치 계층을 기록하고
`scripts/conda_backend_dependencies.py`와 `scripts/run_backend_conda.ps1`을 추가했다.
준비 도구는 기존 frozen export/uv.lock/pyproject SHA를 검사해 호환되는 공식 wheel149개와
Conda 소유 파일6121개의 SHA를 `.local-data/project-agent-work/conda-project-transition-20261015/install-plan/`
아래에 저장했다. 설치는 `--no-deps --no-index --require-hashes --only-binary=:all: --retries 0`로
명시적으로 분리했다. pip dry-run 보고서의 URL·버전·SHA, 설치 전후 보호 파일, 실제 설치 버전,
`pip check`를 검사한다. 설치 오류와 보호 파일 오류가 동시에 나도 둘 다 보존한다.
실행기는 표준 Conda PowerShell 활성화와 실제 앱 조건의 interpreter 확인을 수행하고,
PYTHONHOME을 프로세스에서 제거했다가 종료 시 환경·cwd와 함께 복원한다.

독립 리뷰의 P2 두 건(정상 실행 identity 누락, 설치 실패를 보호 검사 오류가 가리는 문제)을
회귀 테스트와 함께 수정했으며 재검토에서 추가 차단 사항은 발견되지 않았다.
실제 대상 prefix의 launcher `-CheckOnly`는 executable/prefix/CONDA_PREFIX 모두 예상 경로로 통과했다.
앞선 EnvironmentNotWritableError 이후 대상에 설치를 재시도하지 않았으며 사용자 일반
PowerShell에서 실행할 한 명령을 runbook에 준비했다. 새 환경0, 새 RAG0/1, 구환경 제거0이며,
backend import/start/health·E5 저장 벡터 비교·실제 RAG 결과·전체 전환은 계속 대기다.
기존 `.venv`·Miniconda base·모델·데이터·다른 미커밋 변경은 보존했다.

검증 명령은 기존 `.venv`에서 실행했다. 새 dependency/launcher 테스트와 기존 E5 adapter 회귀를 합쳐 **45개 통과(12.60초)**했다. 보호 파일·보고서·설치 실패의 mock 분기와 실제 모델 없는 adapter 회귀이며 새 Conda 전체 런타임 검증은 아니다. 잘못된 E5 테스트 경로로 한 차례 수집이 실행되지 않은 뒤 정본 경로로 수정해 위 결과를 얻었다.

최종 strict Mypy에서 테스트의 중첩 dict 타입과 monkeypatch 대상 표기를 보완한 뒤 **strict Mypy3파일·Ruff 통과**, 수정된 dependency 테스트 **17개 재실행 통과(0.11초)**를 확인했다. 전환 시작 snapshot의 추적 파일1886개 SHA와 비교해 변경된 기존 파일은 WORKBOARD·runbook·이 worklog 세 개뿐이었다. 새 코드/테스트/수치 manifest 다섯 파일은 이번 작업 산출물이며 커밋·푸시는 하지 않았다.


### 2026-10-15 Conda 설치 후 실제 import·오프라인 E5 검증과 소켓 차단

사용자의 일반 PowerShell 설치 결과를 부모 작업이 확인한 뒤 대상 Python으로 재검증했다.
잠금 wheel149개 설치 버전과 report URL/SHA, 보호 파일6121개 SHA, 수치 native252개
Authenticode Valid, `pip check`를 모두 확인했다. 표준 Conda PowerShell 활성화에서
기존 차단 모듈4개·Torch·Sentence Transformers·`ai_workshop.main` import가 성공했다.
기존 수치 파일이나 패키지를 다시 설치하지 않았다.

캐시 E5 revision `d128750597153bb5987e10b1c3493a34e5a4502a`를 CPU/float32,
local-files-only/HF offline 조건으로 로드했다. 공개 합성 fixture 본문 SHA를 확인한 뒤
문서와 기존 질문을 각각 encode해 768차원·정규화 조건을 통과했다(12.195초).
문서 norm1.0000000336, 질문 norm0.9999999859, query/document cosine0.8746329843이었다.
이는 로컬 임베딩 smoke이며 **기존 ES 저장 벡터 비교나 검색 정확도 검증은 아니다**.

기존 프로세스를 중지하지 않고 준비한 launcher를 Hidden PowerShell로 실행 요청했다.
PID10792가 반환됐으나 후속 조회에서는 찾을 수 없었고 stdout/stderr도 비어 있어
백엔드 기동 성공으로 판정하지 않았다. 최초 health GET은
`httpx.ConnectError: [WinError 10013]` 소켓 접근 거부로 실패했다.
다른 클라이언트·주소·포트·권한으로 우회하지 않았으며 DB/ES/Ollama 연결 검증은 진행하지 않았다.
이 오류만으로 제품·Gemma·Windows 앱 제어 정책 중 어느 계층이 원인인지 단정하지 않는다.

새 Conda에서 전체 RAG 단위 테스트는 초반21개 진행 표시 이후 정체해 해당 실행만 Ctrl+C로
중단했다. 전체 성공으로 계산하지 않는다. 관련45개 검증에서는36통과/9실패였으며,
실행기 mock 테스트9개의 PowerShell 한글 출력이 UTF-8 decode 중 실패하는 문제를 별도 조사했다.
기존 `.venv`에서의45통과 기록과 구분한다.

독립 실행 예산 리뷰는 기존 local wrapper가 evidence/응답 진단 저장 전에 공개 합성
source allowlist를 검사하지 않는 점을 확인했다. 다음 실행 전 DB의 frozen snapshot으로
허용 document/version/projection/build를 확인하고 prepared scope·생성 evidence를 검증해야 한다.
기존2026-10-14/15 예약·증거28개 SHA를 보존했다. 새 요청 예약·생성 POST는 모두0이며
새 예산0/1을 유지했다. 기존 `.venv`, 대상 Conda, Miniconda base와 모델/문서/DB는 보존했고
정리·영구 삭제·커밋·푸시는 하지 않았다. ISSUE-00013의 실제 답변 검증은 미완료이며,
관리 이력 DB는 이번 연결 차단 때문에 조회·갱신하지 않았다.

증거는 `.local-data/project-agent-work/conda-runtime-validation-20261015/`의
`embedding-offline.json`, `network-blocker.json`, `backend-process.json`,
`prior-search-evidence-sha.json`에 있다. 다음 단계는 정상 실행 경로에서 backend/health 확인,
읽기 전용 저장 E5 벡터 비교와 합성 source 검사, 승인된 단일 RAG 실행 순서다.

인코딩 원인은 PowerShell CP949 출력과 Python UTF-8 강제 모드의 불일치였다. `backend/tests/unit/test_conda_launcher.py`만 수정해 자식 PowerShell 출력·Python 디코딩을 명시적 UTF-8로 맞췄고, 한글 stdout/stderr와 실패 종료코드19를 보존하는 회귀를 추가했다. 담당 검증은 새 Conda의 PYTHONUTF8=0/1 양쪽에서 각10통과(11.90/11.95초), Ruff·strict Mypy1파일이었다. 독립 읽기 리뷰에서 출력 오류 은폐나 완료 과장은 발견하지 못했다. 메인의 새 Conda RAG Mypy312파일·Ruff도 통과했다.

메인이 표준 Conda 활성화·PYTHONUTF8=1 조건으로 관련 전체 검증을 다시 실행해 **46개 통과(14.15초)**를 확인했다. 최종 상태는 `runtime-result.json`에 기록했다. 실제 RAG 정확도와 생성/검색 시간은 미측정이며 위12.195초는 오프라인 E5 smoke 소요 시간만 뜻한다.


## 2026-10-15 Conda 수동 벡터·범위·단일요청 준비

사용자는 기존 `.venv` 기동 화면 이후 표준 `run_backend_conda.ps1` 재기동 안내에 따라
실행했고, 오류 없음·health `status ok`를 보고했다. 이는 사용자 보고이며 에이전트가
소켓10013 또는 CIM 거부를 다른 방법으로 재시도해 확인한 결과가 아니다.

`rag_stored_vector_check.py`는 고정 공개 합성 청크 한 개의 식별자·본문 SHA·E5 revision과
기존 ES mapping을 검증한 뒤 저장 벡터와 캐시 임베딩을 비교하도록 준비했다.
기존 admission·읽기 권한·CA 검증을 유지하고 정확한 mapping/document GET을 사용한다.
한 표본 통과를 전체 색인 호환·검색 품질로 확대하지 않는다.

새 로컬 묶음 `.local-data/project-agent-work/conda-rag-manual-20261015/`에는
manifest·preflight·scope guard·기존 transport를 유지한 단일 검색 wrapper와 수동 README를 두었다.
실제 공개 합성 PDF3개 SHA와 preview306근거의 식별자·본문 SHA·metadata를 결속했다.
정답지의 정답은 생성 입력에 포함하지 않는다. preflight는 read-only SELECT 후 rollback/close하고,
실제 scope·모델/프로파일·파일 해시·실제 Conda Python·15분 freshness를 확인한 후에만
새 요청을 예약한다. 기존 예약·증거는 보존하며 POST는 최대1회다.

TDD로 runtime/metadata/오류 기록 실패 경로를 먼저 실패시킨 뒤 수정했다.
최종 통합은 소켓 생성을 차단한 harness에서 **97통과(2.25초)**, strict Mypy4소스파일,
Ruff6파일이었다. 독립 개인정보·실행예산 리뷰와 코드 리뷰의 지적을 반영하고 재검토했다.
중간 pytest import 경로 오류와 Mypy import 추적 설정 오류는 검사 설정 수정 후 통과했다.
초기 wrapper async 테스트는 Windows event-loop 생성 단계에서 정체해 중단했고,
최종 검사는 event loop 없이 수행했다. 전체 RAG suite 성공으로 계산하지 않는다.

이번 준비에서 실제 서비스 HTTP·DB·ES·임베딩·RAG·서버 조작을 실행하지 않았다.
기존 증거28파일은 SHA를 보존했으며 새 vector/preflight/request 예약은 없다.
신규 RAG예산0/1·구환경 제거0이며 모델/DB/정책·권한·커밋·푸시를 변경하지 않았다.
실제 저장 벡터 비교 → 공개 합성 scope preflight → 결과 검토 → 승인된 단일 RAG 순서로
사용자 일반 PowerShell에서 진행한다. 자동 후속 POST를 묶지 않는다.
ISSUE-00013 관리 DB는 이번 준비에서 갱신하지 않았으며 실제 답변·인용·속도 검증이 남는다.


### 사용자 실행 저장 E5 벡터 비교 통과

2026-10-15 04:51:10 UTC 사용자 실행의 `vector-result.json`을 로컬에서 검증했다.
고정 공개 합성 청크1개·768차원, 저장 norm1.0000000311246602,
현재 norm1.0000000336402202, cosine0.9999999999999998,
최대 절대오차4.20650481114393e-09로 norm 오차≤1e-5·cosine≥0.99999·최대오차≤1e-5를 충족했다.
세션·manifest·fixture·모델 YAML·identity SHA·대상 prefix/cache가 일치하고 결속 파일16개도 무변경이다.
사용자 화면의 이름 변경 FutureWarning은 실패가 아니며 종료 결과는 passed다.
이는 해당 표본의 수치 호환성만 확인하며 전체 색인·답변 품질을 증명하지 않는다.

에이전트는 로컬 증거만 읽고 네트워크·모델 호출을 재실행하지 않았다.
preflight/request/generation 예약은 모두 없고 RAG예산0/1이다.
준비된 preflight 및 `search_once.py --check-ready`는 수정 없이 다음 단계에 적합하다.
벡터 freshness는 15분이므로 이 결과의 준비 검사 한계는 05:06:10 UTC다.
만료되면 기존 증거/예약을 삭제하거나 타임스탬프를 바꾸지 않고 중단한다.


### 사용자 preflight 통과와 만료 증거 갱신 절차 공백

2026-10-15 06:19:37 UTC의 실제 `preflight.json`은 ready=true이며 승인 합성3문서,
manifest·vector 결과 SHA·product hashes가 일치한다. 당시 run8/attempt527을 기록했다.
사용자 보고와 로컬 파일이 일치하지만 벡터 증거04:51:10 UTC는 이미15분을 초과했다.
06:21 UTC 이후 에이전트가 네트워크 없이 `search_once.py --check-ready`만 실행한 결과는
`READINESS_BLOCKED stale_or_future_preflight`(종료1)이다. 요청/생성 예약은 없고 예산0/1이다.

기존 vector CLI는 --session만 제공하고 결과/시작 파일을 exclusive 생성한다.
preflight도 기존 시작/결과 파일이 있으면 거부한다. 따라서 같은 세션의 만료 증거를
보존하며 갱신하는 지원 절차는 현재 없다. preflight 자체의 통과는 vector freshness까지
보증하지 않으며 최종 guard가 이를 차단한다. 현재 도구로 안전한 갱신 명령을 제시할 수 없다.
타임스탬프/유효시간/예약/결과/manifest는 수정하지 않았고 새 환경·세션도 만들지 않았다.
다음 후보는 같은 환경·동일 요청 예산 아래 이전 결과를 보존하는 읽기 전용 증거 갱신 기능의
최소 수정·오프라인 검증이다. 실제 RAG는 그 결과 확인 전 실행하지 않는다.


### 같은 세션의 읽기 전용 증거 갱신 구현

`refresh_readiness.py` 명령 하나가 기존 Conda에서 벡터 재관측→read-only preflight→
동일한 로컬 readiness 검사를 수행한다. 실제 POST는 별도 명령이다.
원래 manifest/vector/preflight5파일은 SHA로 보존했고 `readiness-manifest.json`은
원본 manifest SHA 및 운영도구4경로 변경만 허용한다. 질문·모델·원문·제품 해시는 유지한다.
새 관측은 동일 세션 내부 readiness-observations/000001...에 배타적으로 추가하며,
최신 실패/미완료를 과거 성공으로 대체하지 않는다.15분 제한을 유지하고 실제 만료 시각을 출력한다.

갱신과 실제 요청 예약은 같은 Windows byte lock 안에서 요청 marker를 확인한다.
잠금 파일과 기존 요청 예약은 삭제하지 않으며, 소비된 요청이 있으면 갱신을 거부한다.
독립 리뷰에서 두 성공 결과 저장 후 최종 검사 전 중단되는 경로를 발견했다.
실패 회귀2개를 확인한 뒤 결과 SHA에 결속된 completed.json을 최종 검증 후 저장하고,
완료 누락/변조 또는 error.json이 있으면 거부하도록 수정·재검토했다.

최종 검증은 소켓 생성을 차단한 harness에서 **115통과(2.92초)**,
strict Mypy 변경 소스3파일·Ruff5파일·전체 로컬 Python 문법 검사였다.
기존 증거5파일 및 결속17파일 SHA를 확인했고 실제 새 관측 폴더·잠금·요청 예약은 없다.
실제 HTTP·DB·ES·임베딩·RAG는 실행하지 않았다. 신규 RAG예산0/1이며 새 환경·세션 생성,
구환경 삭제·서버 재시작·모델 설치·보안 변경·커밋·푸시는 하지 않았다.
사용자는 같은 활성 Conda PowerShell에서 아래 한 명령을 실행하고 READINESS_OK를 전달한다.

```powershell
& 'C:/projects/ai-workshop-scipy-test/python.exe' -B 'C:/projects/ai-workshop/.local-data/project-agent-work/conda-rag-manual-20261015/refresh_readiness.py'
```

관리 ISSUE-00013 DB 갱신은 이 오프라인 작업 범위에서 실행하지 않았다.


### Conda 사용자 단일 RAG 결과: 런타임 통과, 직접 답변 품질 미충족

사용자가 관측000001의 READINESS_OK 후 실제 search_once.py를1회 실행했다.
correlation a0b79969-ef52-480c-9de4-e3a6c4e5ea28, PID28460,
예약06:48:46.388851 UTC, 생성POST06:49:04.658710 UTC,
결과06:53:31.522388 UTC다. 기존360초 제한 내 provider/search 모두 answered이며
검색 전체284.7148초, 생성266.7796초, 예약~결과285.1335초였다.
모델은 local_openai_compatible/gemma4:e2b-it-q4_K_M, 입력9992·출력169토큰이다.
새 평가 집계가 아니므로 과거 정답0/2·P95 기록은 변경하지 않는다.

생성 입력28근거의 공개 합성 allowlist·metadata·본문 및 직렬화 SHA를 확인했다.
답변은 “2026-09-07 월요일15:10 신청 시09-08 접수,09-10 기준가격,09-14 지급”이라는
문서 예시를 제시했고 두 인용ID는 합성 설명서2페이지의 해당 두 근거와 일치했다.
일반 질문 “현금화하면 돈은 며칠 뒤”에 필요한 “접수일 T+4 영업일” 근거도 입력에 있었지만
그 규칙을 직접 설명하지 않았다. 인용 추적과 실행 성공은 확인하되 완전한 정답 수용으로
판정하지 않는다. 다음 품질 후보는 질문의 일반 규칙을 먼저 답하고 날짜 예시를 구분하는 것이다.

전송 guard가127.0.0.1:11434의 GET /v1/models와 단일 POST /v1/chat/completions만 허용하고,
프로파일 external_transfer=false·재시도0·proxy/redirect 비활성을 유지했다.
결속17파일 SHA가 무변경이고 provider 실행도 local로 기록돼 애플리케이션 경로상 외부 전송은 없다.
독립 패킷 관측은 수행하지 않았다. 이번 실행은 검색 임베딩부터 생성까지 완료해 SciPy DLL 차단
재발이 관측되지 않았으며, provider/request error 파일은 없다. diagnostics에는 finish_reason=stop
토큰 통계 경고만 있다. 이를 장기 재발 방지나 전체 기능 마감으로 확대하지 않는다.

provider-result.json/search-result.json/completion.json은 결과 기록 증거다.
completion.json은 코드상 DB commit 전에 저장되므로 DB commit·프로세스 종료까지 증명하지 않는다.
에이전트는 로컬 결과·로그만 관찰했고 새 네트워크·모델 호출·프로세스 중지·예약 초기화·삭제는 없다.
현재 요청예산1/1·생성POST1회이며 추가 실행하지 않는다. 기존 환경도 보존한다.


### 같은 요청의 종료 증거와 답변 품질 진단

후속 로컬 파일·로그 확인에서도 commit 이후 또는 프로세스 종료를 기록한 파일은 없었다.
completion.json은 commit 전, diagnostics.log는 provider finish_reason=stop만 기록한다.
request-error.json 부재만으로 정상 종료를 단정하지 않는다. 코드상 SEARCH_END는
await session.commit() 다음에 출력되므로 같은 PowerShell의 SEARCH_END answered와
프롬프트 복귀가 남은 최소 확인이다. 이후 다른 native 명령을 실행하지 않았다면
$LASTEXITCODE=0도 정상 종료 증거가 된다. DB 소켓·CIM·프로세스 조회는 재시도하지 않았다.

저장된 serialized_user_content에 “접수일 T+4 영업일”이 실제 포함된 것을 확인했다.
모델은 그 근거25b7b690… 대신 날짜 예시2e8480e3…/af9d7189…만 인용한 두 주장을 반환했다.
따라서 이번 관측은 검색/입력 누락보다 생성의 일반 규칙 선택·질문 직접성 문제다.
현재 rag-answer-v2는 대상·속성·조건을 연결하고 근거를 인용하라고 지시하지만,
일반 규칙을 먼저 답하고 날짜 예시를 별도로 표시하라는 명시는 없다.
정확한 system 메시지 전체는 실행 파일에 저장되지 않았으므로 현재 프롬프트 정의와의 비교이며,
추론 내부 원인이나 다른 입력에서도 같은 문제가 생긴다고 단정하지 않는다.

환경 검증 통과: 앞선 잠금 의존성/서명·native import·수치·캐시 E5 smoke·오프라인 회귀,
사용자 Conda backend 기동/health 보고, 저장 E5 한 표본 호환, 공개 합성 scope 검사,
이번 실제 검색/로컬 생성/인용 추적과 SciPy 차단 미재발이다.
미확인/미충족: commit 이후 정상 종료 증거, 일반 T+4 답변 직접성, 장기 DLL 재발 방지와
전체 기능/브라우저 수용이다. 보수적으로 기존 .venv 제거 조건을 충족하지 않은 것으로 유지한다.
제품 동작·프롬프트·환경·예약은 변경하지 않았고 신규 요청은 없다(예산1/1).


### 사용자 종료 화면 확인 및 구 .venv 의존성 조사

부모가 확인한 동일 correlation a0b79969-ef52-480c-9de4-e3a6c4e5ea28/PID28460 화면에
GENERATION_END06:53:31.435931 UTC, SEARCH_END06:53:31.528090 UTC answered와
PS C:\projects\ai-workshop> 복귀가 있다. SEARCH_END는 await session.commit() 이후이므로
애플리케이션 commit 반환과 실행 종료를 사용자 화면으로 확인했다. 종료코드 숫자는 미관측이며,
DB 재조회나 프로세스/CIM 조회는 하지 않았다. 이전 종료 미확인 기록은 이 증거로 해소한다.
일상 API·검색·로컬 생성의 Conda 전환 검증은 통과했다. T+4 직접 답변 부족은 별도 생성 품질
항목이며 Python 환경 전환 실패나 구환경 보존의 직접 사유로 취급하지 않는다.

읽기 전용 조사에서 다음 활성 실행 코드6파일의 구환경 의존성을 확인했다.

- frontend/openapi-ts.config.mjs: api:check/api:generate용 Python 경로를 backend/.venv로 고정.
- scripts/prepare_rag_sandbox.ps1: 샌드박스 CLI와 api/worker/beat 실행 Python 고정.
- backend/src/ai_workshop/infrastructure/local/service_launcher.py: 등록 서비스 자식 Python 고정.
- backend/src/ai_workshop/labs/rag/indexing/access_epoch_original_apps.py: supervisor 실행문과 프로세스 경로 검증.
- backend/src/ai_workshop/labs/rag/indexing/access_epoch_route_commands.py: Python 바이너리 SHA 및 probe 실행 경로.
- backend/src/ai_workshop/labs/rag/indexing/alias_recovery_local_native.py: controller payload와 부모/자식 실행 파일 검증.

최소 후속 전환은 위 실행 경로를 승인된 기존 Conda Python·표준 활성화에 일관되게 연결하고,
관련 경로/해시/프로세스 검증 테스트를 함께 맞추는 것이다. 보안 역할·자격 증명·검증 강도는
완화하지 않는다. runbook의 worker/beat·운영 CLI·검증 명령, sandbox 안내와 corpus script의
사용 예도 갱신 대상이다. Dockerfile의 /app/.venv와 Docker backend-venv 볼륨은 별도 환경이므로
변경/제거 대상이 아니다. 과거 worklog/취소 ARM64/학습 검증 이력도 일괄치환하지 않는다.
.idea에는 Java SDK21만 확인했고 현재 조사 범위에 별도 Python IDE 고정은 발견하지 못했다.

정리 후보는 정확히 C:/projects/ai-workshop/backend/.venv 한 개다.
읽기 전용 합계46,725파일·1,701,291,709bytes(1.584GiB), 루트/하위 reparse0, 읽기 오류0이다.
이 수치는 논리 용량이며 현재 사용 프로세스 부재나 실제 디스크 회수량은 증명하지 않는다.
실행 참조 전환·관련 검증과 정리 직전 사용 여부를 확인하고 CACHE_POLICY에 구환경 분류를
명시한 뒤 정리한다. 복구 가능한 방법은 복사/새 환경 없이 같은 디렉터리 안에서
.venv.rollback-20261015로 임시 이름 변경해 참조 단절을 검증하고, 문제면 원래 이름으로
되돌리는 것이다. 이 후보 경로는 현재 없으며 이름 변경만으로 공간은 회수되지 않는다.
확인 후에만 정확한 보관 경로의 최종 제거를 별도 단계로 수행한다. 이번에는 이름 변경도 하지 않았다.

보존 대상은 기존 Conda prefix, Miniconda base, 모델/원문/DB/검색색인, 요청예산/관측 증거다.
현재 실행 참조 미전환과 프로세스 사용 미확인이 실제 정리 전 남은 조건이다.
새 환경/세션·소켓/CIM·모델 호출·서버 변경·삭제0이며 기존 요청예산1/1을 유지한다.


### 2026-10-15 고정 실행 경로의 Conda 전환 착수

승인 범위는 이미 검증된 기존 Conda로 로컬 실행 참조를 바꾸는 코드·오프라인 검증이다.
보호된 서비스에 자격증명이 전달되는 변경이므로 보안 영향이 있는 한정 작업으로 분류했다.
메인 Codex가 설계·통합·기록, Python 구현 담당이 공통 실행 검증과 보호된 경로,
도구 구현 담당이 OpenAPI·PowerShell 경로, 독립 검토자가 보안·코드 검증을 맡는다.
DB·Docker·UI·모델 동작 변경이 없어 해당 전문 구현 역할은 제외한다.

앞선 여섯 파일 분류를 정정한다. access_epoch_original_apps.py는 10월 8일 고정 PID·시각·
실행문·보고서 SHA를 검증하는 역사 증거이며 새로운 실행기가 아니다. 이 파일은 보존하고
나머지 다섯 활성 경로를 전환한다. 역사 receipt를 새 Conda 실행 증거로 재작성하지 않는다.

배포 설정 scripts/local_python_runtime.json에 승인된 prefix·python.exe SHA를 두고,
검증 코드가 설정 원문 SHA를 고정한다. 환경별 경로는 업무 코드에 흩어놓지 않는다.
설정만 바꾸거나 같은 Python을 다른 prefix에 복사해도 허용하지 않는다. 각 호출부는
활성 CONDA_PREFIX, Python 호출부의 sys.executable/sys.prefix, PYTHONHOME 부재,
실행 파일 SHA와 reparse 부재를 확인하며 실행 직전 재검증한다.
표준 Conda 활성화는 사용자가 먼저 수행한다. 자동 활성화·PATH 검색·대체 Python은 없다.
기존 admission·역할·access_epoch·PID/시각/부모/argv 검증은 유지한다.
이 설계는 독립 보안 검토를 받았으며 실제 구현 검토와 테스트 결과는 아래에 따로 기록한다.

Docker /app/.venv, 기존 run_backend_conda.ps1 및 요청 증거에 결속된 17개 파일은 변경하지 않는다.
새 앱 실행·소켓/CIM 재시도·외부/로컬 모델 요청·환경 설치·구 .venv 이동/제거는 하지 않는다.
기존 단일 RAG 요청예산1/1과 완료 증거를 보존한다.


### 2026-10-15 고정 Conda 실행 참조 전환 결과

활성 실행 경로5파일을 승인된 기존 Conda로 전환했다. 세 Python 호출부는 공통 typed
검증기를 통해 고정 descriptor 원문 SHA, 실행 파일 SHA, 활성 Conda와 현재 interpreter,
경로의 reparse 여부를 확인한다. 서비스 자격증명·admission·access_epoch·argv·PID/시각과
부모 관계의 기존 검증은 유지했다. 별칭 복구의 임의 base Python 허용은 제거했다.
Route는 명령 생성뿐 아니라 native 생성·resume·비밀 stdin 전달 전에 기존 assert 경로로
다시 검사한다. 환경변수 허용 목록과 자격증명 전달 범위는 확대하지 않았다.

OpenAPI는 Windows에서 같은 descriptor를 검증하고, POSIX의 backend/.venv/bin/python은
유지한다. PowerShell sandbox는 각 실행 직전에 재검증한다. 자동 Conda 활성화·다른 Python
fallback은 없다. 원문 SHA가 Git 줄바꿈 변환으로 달라지지 않도록 descriptor에 LF를 고정했다.
기존 API 실행기 run_backend_conda.ps1은 수정하지 않았다.

수정/추가 파일:
- 배포 설정: scripts/local_python_runtime.json, .gitattributes.
- Python: infrastructure/local/python_runtime.py·service_launcher.py,
  labs/rag/indexing/access_epoch_route_commands.py·alias_recovery_local_native.py.
- 도구: frontend/openapi-ts.config.mjs·local-python-runtime.mjs,
  scripts/prepare_rag_sandbox.ps1·local_python_runtime.ps1.
- 테스트: backend/tests/unit/infrastructure/local/test_python_runtime.py·test_service_launcher.py,
  backend/tests/unit/labs/rag/indexing/test_access_epoch_route_commands.py·test_alias_recovery_local_native.py,
  frontend/tests/local-python-runtime.test.mjs·openapi-runtime-selection.test.mjs,
  scripts/test-local-python-runtime.ps1.
- 안내: docs/runbooks/local-development.md·rag-sandbox.md, corpus script 사용 예,
  WORKBOARD와 이 작업 기록. 기존 미커밋 변경과 과거 실행 기록은 보존했다.

검증: 메인의 backend 전체 Mypy 472 source files 통과, 변경 Python/테스트/사용 예9파일
Ruff 통과. Node mock 테스트15/15, PowerShell 읽기 전용 경로·descriptor·실행 파일 해시·
활성 환경·PYTHONHOME·reparse 거부 및 구문 검사를 메인이 재실행해 통과했다.
메인이 신규 Python 검증기17개 테스트도 재실행해 통과했다. 변경 MJS4파일 ESLint와
지정 파일 git diff --check는 통과했다. Node의 experimental/deprecation 경고,
pytest-asyncio 비활성으로 발생한 asyncio_mode 설정 경고는 실패가 아니다.

독립 보안·코드 리뷰는 새 차단 결함을 발견하지 않았다. JS는 symlink/junction와 realpath
재지정을 검사하지만 Node가 모든 Windows reparse 태그를 노출하지 않아 전체 태그 거부를
보장하지 않는다. Python/PowerShell은 ReparsePoint 속성을 검사한다. 실행 파일 SHA는
Python DLL·패키지 전체 무결성을 증명하지 않는다.

실제 OpenAPI 생성, sandbox·등록 서비스·복구 probe 기동, socket/CIM 재시도, DB·ES·Docker,
모델 호출은 하지 않았다. 제한된 Route 환경에서 Conda DLL/SSL이 실제 적재되는지는 미검증이며,
실행 성공이나 확정 실패로 판정하지 않는다. 전체 테스트 suite와 실제 취소·timeout 타이밍 검증도
이번 실행 결과에 포함하지 않는다. 예산이 소진된 RAG 단일 요청은 반복하지 않았다.

보존 재검증: 요청에 결속된17파일 SHA 모두 일치, 원본 manifest·벡터·preflight와 readiness SHA
모두 일치, access_epoch_original_apps.py 원문 SHA 불변. 구 backend/.venv가 존재하고
.venv.rollback-20261015는 생성하지 않았다. 이동/삭제0, commit/push0이다.

다음 조건은 실제 변경된 도구·서비스 경로의 사용자 환경 검증과 구환경 사용 프로세스/IDE 확인이다.
기존 socket/CIM 차단을 우회하지 않는다. 이 조건과 CACHE_POLICY의 분류·승인 절차를 충족한 뒤에만
정확한 구 .venv를 복구 가능한 이름으로 이동하는 정리를 진행할 수 있다. 이름 변경 자체의 공간
회수량은0이며, 현재 보존한 구환경은 이전 읽기 전용 조사 기준1.584GiB이다.
RAG 답변의 일반 T+4 규칙 직접성은 별도 다음 개발 후보로 남긴다.


최종 Python 회귀는 메인이 4개 대상 파일 전체를 제외 없이 다시 실행해
208 passed, 13 skipped, 1 warning(38.41초, exit0)을 확인했다. 기존13skip은
고정 Windows PowerShell 실행 파일을 요구하는 synthetic_windows 조건이다.
테스트 harness는 socket/Popen/subprocess.run을 거부하고 coroutine을 직접 완료시켰다.
AMD64 관측은 mock이며 asyncio.to_thread는 동기 호출, timeout은 가상 context였다.
따라서 이는 경로·권한·상태 회귀의 오프라인 결과이며 실제 thread/시간/프로세스 검증은 아니다.
최초 harness의15failures/26errors는 event loop 부재로 발생했고 mock 처리를 갖춘
최종 전체 실행에서 해소됐다. 중간 실행에서 생략했던 느린 route 테스트도 최종 실행에 포함했다.

실행 명령 근거: backend에서 기존 Conda Python -I -B로 pytest.main을 호출하고
-p no:asyncio, 위4개 대상 파일, 새 --basetemp
.local-data/pytest-tmp/conda-runtime-root-final-full을 사용했다. 메인 재검증의
Mypy는 backend에서 python -I -B -m mypy src/ai_workshop,
Node는 node --experimental-test-module-mocks --test frontend/tests/local-python-runtime.test.mjs
frontend/tests/openapi-runtime-selection.test.mjs, PowerShell은
./scripts/test-local-python-runtime.ps1이다. 실제 앱 프로세스를 시작하는 명령은 실행하지 않았다.
