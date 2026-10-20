# v5 실제 평가: 브라우저 연결 복구·최종 입력 검증·품질 미통과

- 요청: 사용자가 v5 입력 개선 결과를 확인한 뒤 “평가 진행해”라고 승인했다. 동일 정상/근거 부족2사례×2회, 최대4회 로컬 생성·필요 임베딩·retry0을 범위로 준비했다. 이전 v4의 소진4회와 별도다.
- 역할: 메인 RAG·AI·backend 실행 준비, 독립 담당은 정상 등록/실행 경계와 입력 수집을 읽기 전용 검토. UI·스키마·배포 변경은 제외한다.
- 현재 결과: **v5 실제 생성4/4·retry0 완료, 품질·지연 기준 미통과**다. 브라우저 연결 복구 후 본래 로그인 UI에서 평가를 등록하고 해당 run만 처리했다. 최종 어댑터 입력4건을 수집해 선택 원문의 전달을 확인했고 정상2회 답변은 v4와 동일했다. correctness0.5·context1·refusal1·ACL누출0·P95 141.570초다. 산출물 검사61개와 독립 재계산54개·추가 출처/블록 검토를 마쳤다. 승인된4회는 소진됐고 도메인/기본값 승격이나 추가 생성은 없다. 아래 시간순 기록의 대기·0회 표시는 각 당시 상태다.

## 15:36 KST 읽기 전용 확인

- 기존 실행10개 중 pending/running은0이다. 최근 v4 실행 `1c75a9ed-8af6-4ef6-8b34-bdb70e9969f5`는 completed이며 generation 감사4건이다. 취소된 `b91990da-ef3e-4ce3-b8f7-e94db6ff5f21`도 cancelled 그대로다.
- 저장 dataset은 기존 `bf846b4f-9d13-5f1b-88e6-576786f76b3b`, 실제2사례다. 기존 v4 profile config와 평가 동결값은 같다.
- backend health ok, frontend HTTP200, Ollama0.40.3 응답을 확인했다. 로드된 모델 목록은 비어 있었으며 워커 프로세스 상태는 이번 조회에서 별도로 확인하지 않았다.
- `rag-answer-v5`로 등록된 profile은0이다. v5 코드 존재만으로 실행 가능한 저장 구성이 등록됐다고 보지 않는다.

## 차단과 준비 자료

브라우저 도구를 두 번 초기화했으나 두 번째 결과에서 `codex-windows-sandbox-setup.exe` 누락으로 kernel이 종료됐음을 확인했다. 이는 프로젝트 API 오류나 자동 승인 검토 거절이 아니다. 다른 앱의 쿠키/자격을 추출하거나 인증된 POST를 DB/service 직접 호출로 우회하지 않았다.

기존 v4 설정을 읽기 전용으로 복사해 `prompt_ref`만 v5로 바꾼 **draft 프로파일 YAML**을 준비했다. YAML 파서와 Profile 도메인 검증은 통과했으며 아직 등록하지 않았다.

- [등록 YAML](../../.local-data/project-agent-work/rag-v5-evaluation-20261019/v5-generation-profile.yaml)
- 이름: `Gemma E2B 범용 v5 입력 비교 2026-10-19`, version1, 기존 deployment 유지, 출력512·temperature0·timeout360·schema2·reasoning none·문맥예산8/32/12000 유지.
- 본래 owner 로그인 화면의 [모델 관리](http://127.0.0.1:5173/admin/rag/models)에서 **처리·검색·답변 구성** → **고급 프로파일 YAML 등록** → 종류 generation으로 등록할 자료다. 기본 승격은 포함하지 않는다.

사용자에게 정상 관리자 등록 후 정식 평가를 이어갈지, 저장된 검색 근거만 사용한 생성4회 비교로 범위를 바꿀지 선택을 요청했다. 후자는 검색·전체 RAG P95 평가가 아니므로 답변 없이 임의로 대체 실행하지 않는다.

## 실행 전 남은 확인

1. 정상 인증 경로에서 v5 프로파일과 별도 시험 구성·새 pending 실행을 등록한다. 기존 구성과 취소/완료 실행은 변경하지 않는다.
2. 새 구성 저장도 `ensure_indexed`를 호출하므로 같은 processing/indexing 조합의 active asset별 기존 완료 job·dispatch·ready projection/index를 먼저 확인한다. 등록으로 새 색인 작업을 만들지 않는다.
3. 정확한 새 run ID·snapshot/rules digest·원래4시도·retry0·모델·K10·반복2를 확인한 뒤 정상 admission과 단일 실행 영수증으로 해당 run만 처리한다. 일반 큐 worker/beat는 시작하지 않는다.
4. 최종 입력을 수집할 runner 관찰 경계를 준비·검증한다. 평가의 `include_diagnostics=false`를 유지한다. true로 바꾸면 추가 임베딩이 발생해 지연 비교 조건이 달라진다. 기존 `_chat_completion` 안의 request-local capture와 최종 pipeline 권한 확인 성공을 조합해야 하며, 원문은 합성 평가 로컬 산출물에만 남긴다. 현재 이 관찰 wrapper는 검토 단계이며 실제 전송 증거를 수집하지 않았다.
5. 정상/거절 답변·근거·실제 메시지·인용·ACL·전체 P95를 검증하고 실제 결과만 설명 이미지로 만든다. 품질 기준과 도메인 비활성 상태는 유지한다.

증거는 `.local-data/project-agent-work/rag-v5-evaluation-20261019/`의 읽기 전용 DB/runtime 보고서와 등록 자료에 있다. 설치·모델 다운로드·재색인·서버 재시작·기준 완화·도메인 활성화·commit/push는 없다.

## 후속: v5 YAML 등록422와 서버 반영 누락 수정

사용자가 준비한 YAML을 등록했으나 `Context evidence requires a contextual prompt and structured limits.` 오류가 발생했다고 보고했다. API 로그에서도 인증된 `/api/v1/admin/rag/profiles/generation/yaml` POST의422를 확인했다.

원인은 API 프로세스에 새 코드가 반영되지 않은 상태였다. 정확한 API PID119884의 시작은14:14:32이고 `--reload`가 없었다. `context_evidence.py`·`prompts.py`의 v5 허용 코드 수정은15:16:23~24였다. 동일 YAML에서 v5 항목만 제외한 이전 허용 목록을 메모리 내에서 재현하자 사용자와 같은 오류가 발생했고, 현재 코드의 YAML/도메인 검증은 통과했다. 문맥 예산은8그룹·32단위·12,000자이며 삭제나 완화가 필요하지 않았다. 등록을 안내하기 전에 API 반영을 확인하지 않은 에이전트 작업 누락이다.

15:46에 재현·현재 코드 검증과 running execution0·active evaluation0·active turn0·running job0을 다시 확인했다. 정확한 PID·생성 시각·실행 경로·명령·18000 포트 소유가 모두 일치할 때만 기존 API를 종료했고, 같은 프로젝트 `.conda`·Selector loop·호스트·포트·루트 환경으로 API만 재시작했다. 새 PID는118988, 시작15:46:53이며 다른 worker/beat·frontend·Ollama는 시작하거나 종료하지 않았다. 원래 로그와 시작 영수증은 덮어쓰지 않았다.

- 새 API의 `Application startup complete.`, 15:47 `health: ok`와 `ready: ready` 확인.
- 최신 YAML 검증 및 관련3파일47검사 통과(exit0). 제품/YAML 수정은 없으므로 타입·린트를 새로 실행한 것으로 보고하지 않는다.
- 독립 검토가 오래된 프로세스 원인과 해당 API만 재시작하는 조치의 타당성을 확인했다.
- 이번 복구의 모델/임베딩 호출0회, DB 직접 쓰기0회. 기존 평가와 취소 상태를 보존한다.
- 사용자가 같은 YAML로 인증된 등록을 다시 시도하도록 안내했다. 실제 POST201·v5 profile 저장은 아직 확인 전이며 health만으로 등록 성공을 주장하지 않는다.
- 사용자 보고 결함은 이 기록에 누적했으며 인증된 관리자 문제 이력 DB 반영은 미완료다.

증거는 `.local-data/project-agent-work/rag-v5-registration-fix-20261019/`의 `registration-probe.json`, `before-process.json`, `api-restart.json`, `after-health.json`, `regression.xml`, 새 API 로그에 있다. 평가는 여전히 기존 승인된2×2 범위이며 프로파일/시험 구성 등록과 실행 전 확인을 이어간다.

## 후속: 15:50 KST 프로파일 등록 확인

사용자가 등록된 것으로 보인다고 알리고 YAML의 의미를 물었다. 읽기 전용 preflight에서 `Gemma E2B 범용 v5 입력 비교 2026-10-19` 생성 프로파일의 저장을 확인했다. ID는 `10bb5ed9-dc04-4b1b-bc29-4358c859c425`, version1, `is_default=false`, `evaluation_state=draft`다. 기존 로컬 Gemma deployment와 준비한 YAML의 v5 프롬프트·문맥 예산·출력512·temperature0·timeout360·schema2·reasoning none이 일치한다.

YAML은 기존 모델에 적용할 답변 생성 프로파일을 정의한다. 검색 근거 전달 형식과 답변 지침, 근거/대화 이력 예산, 인용과 생성 제한을 묶어 저장하며, 실제 평가에는 이 프로파일을 참조하는 시험 구성이 필요하다. 등록만으로 품질 통과나 기본 적용을 뜻하지 않는다.

같은 조회에서 pending/running 생성형 평가는0이고 기존 v4 완료·감사4건과 과거 취소 상태가 유지됐다. backend health ok·frontend200·Ollama 응답도 확인했다. 이번 v5 평가는 아직 실행되지 않았고 생성/임베딩 호출0회다. 사용자가 정상 등록 경로를 진행했으므로 저장 근거만 재생하는 대체 평가로 범위를 바꾸지 않는다. 최신 증거는 `.local-data/project-agent-work/rag-v5-evaluation-20261019/v5-profiles.json`과 DB/runtime 읽기 전용 보고서다.

## 후속: v5 연결 요청과 정상 관리자 저장 차단

사용자가 “연결해서 확인진행해”라고 요청했다. 기존 승인된2사례×2회 범위를 유지하며, 메인 RAG·AI·backend 준비와 독립 읽기 검증을 분리했다. 제품/UI·스키마·배포 변경이나 도메인 활성화는 포함하지 않는다.

16:00 읽기 전용 preflight에서 기존 완료/취소 상태, pending/running0, API health와 frontend200을 재확인했다. 브라우저 `cua.getState()`를 두 번 시도했지만 `codex-windows-sandbox-setup.exe` 누락으로 kernel이 시작되지 않았다. 프로젝트 오류나 승인 검토 거절이 아니며 설치·인증 우회를 시도하지 않았다. 구성 저장 API는 정상 owner 인증을 요구하며 독립 검토에서도 별도 인증 없는 정상 등록 경로는 확인되지 않았다.

16:03 및16:09 읽기 전용 확인에서 선택 workspace의 active READY asset4개 모두 동일 processing/indexing 조합의 succeeded job, sent dispatch, ready projection/active index build, 수량 일치, alias verified, 미해결 handoff 없음이 확인됐다. 따라서 조회 시점의 조합을 그대로 등록하면 기존 ingestion 작업을 재사용한다. 새 v5 구성은0이고 v5 생성 감사도0이다. 최초 검사 도구의 job 성공 문자열을 `completed`로 잘못 비교했으나 제품 enum 정본 `JobStatus.SUCCEEDED`로 바로잡았다. DB 상태를 변경한 것이 아니다.

정상 화면 입력값은 아래와 같다. 새 이름으로 저장해야 기존 v4의 새 버전을 만들지 않는다.

| 화면 항목 | 값 |
| --- | --- |
| 문서 처리 프로파일 | legacy-text-document-processing v1 |
| 색인 패키지 | 임베딩: multilingual-e5-base v1 · 청킹: structure-aware v2 / 목표380 / 중첩60 · 프로파일 v2 |
| Retrieval Profile | hybrid-rrf v2 |
| 답변 방식 | 근거 제한 LLM 생성 |
| 생성 구성 | Gemma E2B 범용 v5 입력 비교 2026-10-19 v1 |
| 최소 semantic score / keyword coverage | 0.9 / 0.5 |
| 구성 이름 | Gemma E2B 범용 v5 비교 2026-10-19 |
| 적용할 지식 공간 | RAG 합성 참조 자료 하나 |

색인 패키지의 내부 이름은 `e5-structure-aware`이며 실제 UI는 위와 같이 임베딩·청킹 정보를 표시한다. 사용자에게 정상 화면의 저장을 요청했고 답변은 아직 없다. `prepare_connection.py`는 read-only transaction에서 조건을 조사하고 `SavedRagConfigurationCreate`로 요청 preview를 검증할 뿐 POST나 DB 쓰기를 하지 않는다.

### 실제 입력 관찰 준비

임시 `capture_guard.py`는 단일 실행 프로세스 안에서 원래 pipeline/chat 함수를 정확히 한 번씩 호출하고 종료 시 원래 함수를 복원한다. 승인 attempt4개·actor·구성 버전·profile/deployment·질문·workspace·K10·빈 history·diagnostics false·retry0을 검사한다. contextualization과 중복 generation을 호출 전에 차단한다. 어댑터가 최종 schema/system 지침을 반영한 뒤 기록하는 기존 allowlist 입력만 메모리에 관찰하며, pipeline의 최종 원문 ACL 확인을 통과한 뒤에만 보존 후보로 넘긴다. 예외 시 미승인 입력을 폐기하고 원시 provider 응답·비공개 내부 추론은 수집하지 않는다.

- 네트워크/모델 없는 mock17검사 통과, `capture-final.xml`에17 tests/0 failures/0 errors.
- 임시 Python3파일 Ruff `--isolated --select E9,F` 통과. 제품 코드 변경이나 전체 타입/린트 검사 결과로 확대하지 않는다.
- 독립 담당은 파일/증거를 읽고 차단 결함 없음을 확인했다. 독립 재실행은 하지 않았다.
- 검토 도중 provider 오류를 pipeline이 정상 반환할 수 있다는 가정이 제기됐으나 실제 예외 전파 코드를 확인하고 철회했다. 그 가정의 mock 실패는 제품 결함이나 개선 결과로 보고하지 않는다. 실제 계약의 provider 오류 전파·입력 폐기 회귀1개를 추가했다.
- 이 도구의 `called/events`는 chat 진입 관측이다. 실제 HTTP 완료 횟수는 response_received·provider usage·감사와 함께 확인해야 한다.

실제 runner 결합과 실행은 아직 하지 않았다. 정상 구성·pending run 등록 이후 정확한 snapshot/rules digest,4 attempts와 execution 연결, 전체 frozen profile/모델/예산, normal admission, O_EXCL 실행 영수증을 확인하고 해당 run만 실행해야 한다. 사용자 실행 승인은 유지하며 다시 묻지 않는다. 지금은 사용자 정상 화면 저장 결과가 필요한 상태다. 기존 미커밋 변경·취소/완료 실행·기준을 보존했고 이번 설치·다운로드·재색인·DB 직접 변경·모델/임베딩 호출·commit/push는0이다.

## 후속: 사용자 구성 저장 확인과 평가 실행 등록 대기

사용자가 “저장했어”라고 알렸다.16:27~28 읽기 전용 확인에서 새 구성 `3d9953ea-cf57-40cc-8e90-871af09bb950`, version ID `4d603cb6-cd3f-40a5-8e91-974b5cf1f8fb`, version1이 확인됐다. 문서 처리207·색인201·hybrid-rrf v2·v5 생성 프로파일·답변 기준0.9/0.5·complete provenance·separate sources·합성 workspace 하나가 요청과 모두 일치한다. `evaluation_state=pending`은 구성의 평가 전 상태이며 새 생성형 run 등록을 뜻하지 않는다. `is_default=false`, v5 생성 감사0이다.

기존 평가10건의 완료/취소 상태와 pending/running0, 합성 자료4개의 기존 색인 재사용 조건을 다시 확인했다. 호스트 CIM에서 대상 API118988만 관측됐고 Python/Celery worker·beat는 없었다. ai-workshop Compose 컨테이너는 PostgreSQL·Redis·Elasticsearch3개만 실행 중이었다. 이를 원격/비관측 writer의 절대 부재 증명으로 확대하지 않는다.

브라우저 인증 화면 접근 차단이 계속돼 사용자에게 정상 평가 등록을 요청했다. 기존 dataset `bf846b4f-9d13-5f1b-88e6-576786f76b3b`, 정상 required `4`/`영업일` 별도 줄, 거절 required와 두 사례 forbidden/history 빈 값, 새 v5 구성 하나, 기존 policy `3cb3fc16-98d7-4cd6-8f6c-4646fbff3256`, K10·반복2다. 사용자 실행 승인을 다시 요구한 것이 아니며 인증 화면의 pending 등록만 필요하다.

실행 전 준비는 다음과 같다.

- `run_guard.py`: 읽기 전용으로 유일한 새 v5 run, 전체4시도/실행ID, 미실행·미선점, dataset/rules/policy, v4와 동일 frozen source/index/model/binding, v5의 정확한 profile, live config와 retry0을 검증한다. 성공 시 검토용 manifest/snapshot을 로컬에 한 번 저장한다. 조건 불일치나 중복이면 실제 실행을 차단한다.
- `execute_v5.py`: 검토 manifest와 현재값을 대조하고 정상 worker admission(`writer=True, non_es=False`)을 적용한 뒤 다시 대조한다. O_EXCL 영수증을 만든 뒤 정확한 run UUID로 기존 `execute_run`만1회 호출한다. 일반 queue worker나 beat는 시작하지 않는다. 종료 후 최종 ACL을 통과한 입력만 합성 로컬 산출물에 보존한다.
- `capture_guard.py`에 승인 attempt→execution ID 결합을 추가했다. 잘못된 실행ID로 원본에 진입하는 회귀를 실패로 확인하고 차단 후 통과했다.
- capture18 + runner mock5 =23통과(exit0), `runner-offline-final.xml`. 임시 Python6파일 Ruff E9/F 통과. 실제 DB run/worker 성공과 제품 전체 검증을 뜻하지 않는다.
- 독립 읽기 검토는 호출·admission·영수증·ACL 경계에 차단 결함 없음을 확인했다. 실제 run이 없으므로 inspector의 성공 경로는 아직 미검증이며, 등록 후 read-only manifest/snapshot 확인과 worker 상태 재확인이 필요하다.

마지막 read-only guard도 `expected_one_v5_run`으로 차단됐다. 승인 manifest·실제 invocation 영수증·실제 입력 산출물은 아직 생성되지 않았다. 정상 평가 등록 결과를 기다리며 기존 상태와 이번 실제 생성/임베딩0회를 유지한다. 검증 증거와 임시 도구는 기존 `.local-data/project-agent-work/rag-v5-evaluation-20261019/`에 보존했다.

## 후속: 브라우저 연결 복구와 v5 단일 실행 시작

사용자가 앱 재시작 안내 후 “브라우저 연결 다시 확인해”라고 요청했다. 이번 `cua.getState()`는 성공했고 Chrome의 기존 AI Workshop 탭, 로그인된 관리자 화면과 v5 구성을 읽었다. 앞선 `program not found`는 도구가 보조 프로그램을 찾지 못했다는 증거이며, 파일이 실제 삭제·누락됐다고 확정한 것은 아니다. 재연결 성공은 확인했지만 설치 경로 등 정확한 고장 원인을 확정하지 않는다.

16:50 읽기 전용 preflight에서 기존 실행10건·active0·취소 상태 보존·API health ok·frontend200·Ollama 응답을 확인했다. 호스트 CIM은 API118988만 Python 프로세스로 관측했으며 worker/beat는 없었다. 프로젝트 Compose도 PostgreSQL·Redis·Elasticsearch만 있었다. 정상 브라우저에서 저장 dataset을 불러오고 정상 required를 `4`와 `영업일` 두 줄로 입력했으며 나머지 규칙·history는 빈 값, v5 구성 하나·기존 policy·K10·반복2로 생성형 평가 실행을 한 번 눌렀다.

- 등록 run: `9f1df330-4d92-49bf-8186-eca8861b6160`, 등록 시각16:52:39 KST.
- UI는 이력11건·pending4를 표시했고 주소 run 매개변수와 DB ID가 일치했다. 고정 worker 성공 안내는 실제 워커 동작 증거로 사용하지 않았다. 질문 목록의 “진행 중”은 대기 상태에도 표시되는 기존 혼동이 재현됐다.
- `run_guard.py` exit0: 유일 pending·원래4시도/고유 execution·기존 생성0·전체 조건 일치. manifest/snapshot을 신규 로컬 파일로 고정했다.
- snapshot SHA `44f3ce894dab5392af230991d1129acf8e7055dd5ad138662b99ddbbb75212bf`, rules SHA `80b667f5e4c3523a104dc6fa316ac6396ef1fb039d0b6abff1762d085ba2d452`.
- 독립 담당이 실제 manifest/snapshot 해시·설정·질문/권한·2×2 연결을 재계산·확인했고 차단 결함은 없었다. dataset 대상은 기존3build·11chunk·306근거이며 workspace 전체4asset과 구별했다.
- 16:55:08 KST `execute_v5.py`의 정상 worker admission 전후 조건 검사가 통과했다. O_EXCL 실행 영수증을 남기고 기존 `execute_run`에 해당 run만 전달했다. 일반 큐 worker·beat는 시작하지 않았다.

등록 전후 DB/runtime 증거, `ui-pending.jpg`, 승인 manifest/snapshot과 invocation 영수증은 기존 v5 로컬 산출물 폴더에 있다. 아직 실행 완료나 품질 통과를 주장하지 않는다. 실제 입력은 최종 ACL 통과분만 실행 종료 후 저장한다.

## 최종: 실제 생성4회 완료와 입력·출력 검증

지정 run `9f1df330-4d92-49bf-8186-eca8861b6160`은 16:55:08~17:00:12 KST에 처리됐고 runner exit0·workflow 반환을 확인했다. 정상/근거 부족2사례×2회가 모두 completed이며 정확한4 attempt·execution·generation 감사·response_received 입력 수집이 연결된다. 일반 큐 워커를 시작하지 않았고 retry0을 유지했다. 실제 검색에 필요한 로컬 임베딩을 포함했으며 별도 진단용 검색·임베딩이나 추가 생성은 호출하지 않았다.

### 실제 입력과 실패 위치

- 정상 사례의 선택 원문28개와 근거 부족 사례26개 모두 최종 user 메시지에 전달됐다. 각 원문의 ID·본문·bbox·문자 범위·파서 순서와 출처 정보가 저장 결과와 일치한다. 정상은 출처1개/블록6개, 근거 부족은 출처3개/블록3개다.
- 정상 입력에는 일반 규칙 `접수일 T+4 영업일`, 마감15:00·다음 영업일 접수와 날짜 예시의 휴일 없음 조건이 있다. 실제 system에도 일반 규칙 우선·단위/조건 보존 지침이 있다.
- 그런데 정상2회 답변은 v4와 문자열까지 같으며 날짜 예시만 답했다. 일반 규칙과 예시의 휴일 조건이 빠졌다. 따라서 이번 실패는 해당 근거의 검색/전달 누락으로 설명되지 않는다. 모델의 근거 활용 또는 입력 관계 표현을 더 검증해야 하며 특정 내부 원인까지 확정하지 않는다.
- 근거 부족 입력에는 다음 달 확정 수익률이 문서에 없다는 원문이 있고 두 결과 모두 `insufficient_evidence`, `answer: null`이다. 실제로 생성되지 않은 거절 문장을 결과로 꾸미지 않았다.
- 정상의 `citation_valid=true`는 인용 ID 유효성이다. context coverage1과 함께 의미 정확성이나 필수 규칙/조건 반영의 성공을 뜻하지 않는다.

수집한 것은 모델 어댑터의 최종 허용 필드 요청(`messages`, 생성 제한 등)이다. 전체 HTTP 헤더/비밀값이나 내부 추론을 수집하지 않았고 공급자 내부 입력 절단 여부는 unknown이다. 두 정상 요청의 SHA는 `1f39175ae12233f63dcc0f37495fdb71e0f7863125e77f61fc3e3f5f41e40759`, 두 근거 부족 요청은 `dce17b9d2fe5f58361edce61d2a7ceff406cf085047b29e736ad2f418f12878d`로 각각 동일하다.

### 지표와 비교 한계

| 항목 | v4 | v5 | 판정 |
| --- | ---: | ---: | --- |
| correctness | 0.5 | 0.5 | 기준1 미통과 |
| context coverage | 1 | 1 | 근거 포함 기준 충족, 답변의 의미 정확성과 구별 |
| refusal accuracy | 1 | 1 | 근거 부족2/2 적절 |
| ACL 누출 | 0 | 0 | 관측 누출 없음 |
| 전체 RAG P95 | 209,433.563ms | 141,570.255ms | 기준120,000ms 초과 |
| 정상 입력 토큰/회 | 7,147 | 4,568 | 공급자 보고36.09% 감소 |
| 근거 부족 입력 토큰/회 | 7,119 | 4,496 | 공급자 보고36.85% 감소 |

v5 전체 시간은 정상 반복1 19,641.988ms·반복2 145,315.242ms, 근거 부족 반복1 120,348.664ms·반복2 12,396.075ms다. 반복 번호는 실제 실행 순서와 다르다. 실제 순서는 정상2→근거 부족1→정상1→근거 부족2이며 생성 단계는 각각 약113.631/109.811/8.375/1.411초다. 첫2개의 큰 지연은 생성 단계에서 관찰됐지만 캐시·초기 로드 영향을 분리하지 않았다. 관측 P95의32.40% 감소를 입력 형식만의 인과 효과로 주장하지 않는다. 프롬프트와 입력 형식도 함께 바뀌었고 표본은4개다.

읽기 전용 트랜잭션에서 기존 DB 수용 gate를 호출했으며 `generative acceptance policy failed`로 거절됐다. 지표 기준을 낮추거나 검증 상태를 DB에서 직접 바꾸지 않았다.

### 검증·보존·운영 화면

- `verify_actual.py`의 실제 산출물 검사61개 통과: frozen snapshot/rules 해시, 정확한 호출 연결, 전체 선택 근거와 최종 메시지, 기존10개 실행·dataset/cases/policy·취소 상태 보존.
- 독립 담당은 파일 읽기와 메모리 계산으로54개 검사 및 추가 ACL/source_ref·18개 블록 연속성 검증을 마쳤다. 결과4개·요청·snapshot/rules 해시와 P95 연속보간이 일치했고 승인 범위에 차단 결함은 없었다. 정상 의미 품질0/2 및 전체 정책 미통과 결론도 일치한다.
- 수집·모니터·검증·보고서 임시 Python4파일의 Ruff E9/F 통과. 제품 코드는 이번 실행에서 수정하지 않았으므로 제품 전체 테스트/타입 검사를 새로 통과한 것으로 보고하지 않는다. 이전 capture18+runner5 mock23개는 실행 전 준비 검증이다.
- 마감 문서2개의 로컬 링크101개 존재·공백 검사와 독립 HTML 보고서 파싱/외부 자원 없음 검사를 통과했다. WORKBOARD의 최근 완료5개를 유지했다.
- 검증 보조 도구의 메타데이터 필드 가정과 보고서의 상태 필드명을 실제 스키마에 맞춰 수정했다. 이는 실제 모델 호출 실패나 결과 정정이 아니다.
- 17:01 읽기 전용 확인에서 전체11실행 중 대상4/4 completed·active0, 기존10개 실행과 취소 상태가 보존됐다. backend health ok·frontend200·Ollama 응답을 확인했다.
- 본래 Chrome 관리자 화면에서 이력11건·실행 완료·전체4/완료4 및 정상 실패/근거 부족 결과를 확인하고 캡처했다. 이번 검증은 해당 데스크톱 평가 흐름이며 전체 로그인 업무나 모든 화면/모바일 E2E 완료로 확대하지 않는다.
- 인증된 문제 이력 UI로 기존 ISSUE-00005에 이번 실제 결과를 추가하고 저장 성공·새 이력 본문을 확인했다. 상태는 open이다. 첫 저장 시점에는 의미 검토 완료/수치 독립 검토 진행 중이었으며, 위 최종 검토는 이후 완료됐다. 이력 본문에 로컬 작업 기록 경로를 남겼고 별도 DB 문서 버전을 등록한 것은 아니다.

### 사용자 확인 산출물과 다음 범위

- [실제 질문·검색 근거·최종 system/user 전체·답변 보고서](../../.local-data/project-agent-work/rag-v5-evaluation-20261019/rag-v5-actual-input-output.html)
- [실제 입력·출력 흐름 이미지](../../.local-data/project-agent-work/rag-v5-evaluation-20261019/rag-v5-actual-flow.png)
- [실제 관리자 완료 화면: 정상 사례](../../.local-data/project-agent-work/rag-v5-evaluation-20261019/ui-completed-normal.jpg) · [근거 부족 사례](../../.local-data/project-agent-work/rag-v5-evaluation-20261019/ui-completed-refusal.jpg)
- 원자료: `actual-v5-inputs.json`, `evaluation-results.json`, `approved-v5-invocation.json`, `final-verification.json`, 등록 전/실행 전/후 읽기 전용 보고서. 모두 같은 Git 제외 로컬 폴더에 보존했다.

설명 이미지는 위 실제 자료로 그린 도식이며 제품 화면 캡처와 구별했다. 정상 일반 규칙·조건의 활용과 지연 원인 분리가 다음 과제다. 업체/질문별 정답 하드코딩, 재색인, 새 설치/다운로드, 도메인 활성화, 기본값 승격, 추가 생성, commit/push는 하지 않았다. 이번 승인4회는 소진됐으므로 후속 실제 생성은 별도 범위를 확인한 뒤 진행한다.

## 후속: 원인 확인 진단의 읽기 전용 설계

사용자가 답변 품질 실패와 LLM의 근거 활용 실패에 대한 설명 뒤 “확인할 수 있도록 만들 수 있어?”라고 요청했다. 기존 UI·ADR-0038·실제 캡처·오프라인 rubric을 읽었고 원인 구분과 원문 열람 중 우선 목표를 물었다. 답변 전에는 대화 맥락상 원인 구분을 우선하는 제한된 변경안을 제시하며, 미응답을 설계나 추가 실행 승인으로 취급하지 않는다.

메인이 요구사항·RAG·AI 역할을 맡고 기존 독립 검토자는 파일 읽기로 비교 조건을 검토했다. 작업 위험은 중간이다. 기존 로컬 HTML 보고서와 오프라인 검증 도구를 확장하는 범위이며 운영 UI·API·DB 영속 원문 저장·배포 변경은 제외한다. 기존 요청 내 입력 확인 화면은 v5의 구조를 별도 표로 해석하지 못하면 허용 필드 JSON 원문으로 표시하며, 평가 DB에 과거 최종 메시지를 임의 복원/삽입하지 않는다.

제시한 제한된 설계는 다음과 같다. 아직 구현하지 않았다.

1. 먼저 저장된 실제 질문 → 전달 근거 → 답변의 주장/인용 → 누락한 규칙/조건을 나란히 확인한다. 이번 날짜 예시가 거짓이라고 표시하지 않고 일반 규칙과 예시 조건 누락을 구분한다.
2. 비교 준비는 A 원본, B JSON의 동일 키·값·배열 순서를 보존한 들여쓰기/줄바꿈 변경, C user 문자열·형식 안내·출력 계약을 유지한 답변 지침 구간 변경으로 한정한다. B를 표 재구성이나 의미 관계 복원으로 부르지 않는다.
3. 원본/후보 해시, 출처 run/attempt/execution, 변환 버전·변경 구간·불변식 검사와 `not_run`을 표시한다. 준비 도구에는 전송 함수를 넣지 않는다. 실제 캡처에는 최종 wire/응답 계약 지침이 이미 있으므로 향후 실행 경계에서 이중 추가를 막아야 한다.
4. 정답·rubric·검토 강조는 후보 입력 생성과 분리한다. 기존 positive-only rubric을 음성 사례에 적용하지 않는다. 다른 업체의 규칙/자료 구조를 가진 합성 fixture로 하드코딩을 검사하고 실제 전송/실행 결과와 구분한다.
5. 후속 실제 비교는 동일 실험에서 A도 다시 실행하고 조건별 동등 반복·실행 순서 영향을 고려한다. 과거 A의 결과는 참고값이며 미래 B/C의 통제군을 대신하지 않는다. 세 조건만으로 표현/지침 상호작용이나 모델 자체의 한계를 확정하지 않는다. 생성 단계 실험을 전체 RAG P95 수용 평가와 혼동하지 않는다.

독립 검토는 위 불변식, 최종 지침 중복 위험, 채점 오염, 음성 판정 분리와 결론 한계를 지적했고 이를 설계에 반영했다. 공급자 내부 입력 절단·캐시·모델 내부 해석은 여전히 확인할 수 없다. `brainstorming`의 bounded 설계 확인 게이트에 따라 짧은 채팅 설계를 확인받은 뒤 구현한다. 이번 후속은 읽기 전용 조사와 작업 기록 갱신만 했으며 새 모델/임베딩 호출·제품 코드 변경·DB 변경·commit/push는0이다.

## 후속: 승인된 로컬 입력·답변 진단 구현과 검증

사용자가 위 설계에 “그래 진행해봐”라고 승인했다. 현재 작업 경로의 기존 변경을 보존하면서 메인이 요구·RAG·AI·테스트 설계를 맡고 독립 담당이 코드 검토와 실제 파일 통합 검증을 수행했다. 운영 UI/API·DB 스키마·활성 프로파일은 변경하지 않았다. 새 모델/임베딩 호출은0이며 기존 v5 승인4회는 소진 상태다.

### 구현과 사용 위치

- [입력·답변 비교 진단 보고서](../../.local-data/project-agent-work/rag-input-diagnosis-20261019/report-final/index.html): 실제4건의 질문 → 전달된 전체 근거 → 실제 system/user → 과거 답변과 주장별 인용 → 누락 검토를 연다. 정상2건은 일반 규칙·예시 조건 누락을, 근거 부족2건은 거절 반환 형식 일치를 표시한다. 반환 형식 일치만으로 의미상 거절 정확성을 새로 입증하지 않는다.
- [준비된 A/B/C 입력 JSON](../../.local-data/project-agent-work/rag-input-diagnosis-20261019/report-final/candidates.json): A 원본 바이트 그대로, B user JSON 문자열 밖 공백/줄바꿈만 변경, C 검토한 system 답변 지침 구간만 변경한다. B는 문자열의 escape 표기와 숫자 토큰도 보존한다. C는 user·생성 옵션·앞뒤 형식 안내/출력 계약을 보존한다. 실제4기록×3후보=12개 모두 `not_run`이며 새 답변은 없다.
- [검토 전용 기준](../../.local-data/project-agent-work/rag-input-diagnosis-20261019/report-final/review-only.json)은 후보 작성과 분리했다. 기존 합성 positive rubric을 재사용했고 거절 사례에는 적용하지 않는다. C의 제안 지침은 특정 업체/정답 수치를 넣지 않은 일반 규칙·조건·예시 구분 지침이며 현재 모델 프로파일에 적용된 것이 아니다.

새 파일은 `offline_input_diagnosis.py`(순수 후보 작성·불변식), `offline_input_artifacts.py`(저장 캡처/결과 결합), `offline_input_report.py`(정적 HTML·신규 산출물 저장), `scripts/prepare_rag_input_diagnosis.py`(CLI), 관련 단위 테스트2개다. 앞의3개 모듈은 `backend/src/ai_workshop/labs/rag/evaluation/`에 있다. 전송 함수를 추가하지 않았으며 CLI는 새 출력 폴더만 생성하고 기존 폴더·링크 경로를 거부한다. 보고서는 외부 자원·스크립트 없는 로컬 HTML이다.

입력은 기존 `actual-v5-inputs.json`, `evaluation-results.json`과 이번 `experiment.json`, `reviews.json`이다. 실제 로컬 provider/dialect·v5/schema2 계약, complete/response_received·해시·크기, run/attempt/execution 연결과 결과 digest, 전체 근거의 ID·본문·위치·출처를 대조한다. 이 일치는 저장 파일의 정합성 검사이며 서명된 전송 증명이나 현재 ACL 재검사가 아니다. 임의 공급자/입력 형식을 지원하는 것으로 확대하지 않는다.

### 검증과 수정 이력

- 프로젝트 `backend/.conda/python.exe`와 기존 런타임 준비 절차를 사용했다. 관련 `test_offline_input_diagnosis.py`, `test_offline_input_artifacts.py`, `test_offline_rubric.py` **65 passed**(`tests.xml`). 물류·장비·도서관 등 다른 합성 자료를 사용해 입력 보존, 조건별 단일 변경, 잘못된 출처/해시 거부, 판정 기준 격리, HTML escaping, 거절 분리와 덮어쓰기 방지를 검사했다. 다른 업체의 실제 생성 품질 검증은 아니다.
- 새 소스/CLI4파일 strict Mypy 통과, 새6파일 Ruff 통과. Ruff의 실행 위치에 따른 import 분류 차이는 `lint.isort.known-first-party=['ai_workshop']` override로 고정했다. 최초 PowerShell 인수의 따옴표 해석 오류는 정정 후 재실행했다. 프로젝트 전체 검사 통과를 주장하지 않는다.
- TDD에서 미구현 import 실패와 B의 Unicode escape/숫자 토큰 변경을 재현한 뒤 수정했다. 독립 검토가 발견한 C 한글 인코딩 손상, provider/dialect/prompt 및 필수 payload/schema 검증 누락도 실패 재현 후 보완했다. 인코딩 손상은 임시 PowerShell stdin 작성 과정에서 발생했으며 UTF-8 파일 읽기로 복원했다. 손상된 `experiment-encoding-failed.json`과 최초 `report/`는 실패 증거로 보존하고 최종 사용 대상에서 제외한다.
- 독립 검증64개 통과, 변조7종 거부 재확인, **socket 호출을 금지한 파일→CLI→HTML/JSON 통합** 성공. 실제4건·후보12개 미실행, A 바이트 일치/B 공백 외 토큰 일치/C user·옵션·앞뒤 구간 보존, 검토 기준을 제거해도 후보 동일, HTML ID 유일·인용 링크 목적지 존재를 확인했다. 최종 독립 생성물3파일이 메인 `report-final/`과 바이트 단위로 같다. 남은 차단 finding은 없다.
- 기존 v5 평가 산출물50개의 SHA-256이 모두 동일하다(`original-artifact-hashes.json`, `final-preservation.json`). 기존 결과를 새 후보 결과로 바꾸거나 평가 기준을 완화하지 않았다.

검증 명령의 대상 경로는 다음과 같다. 프로젝트 실행서에 따라 Conda 환경과 `PYTHONPATH=backend/src`를 먼저 준비한다.

```powershell
# 저장소 루트, 기존 출력 폴더는 거부하므로 새 경로를 지정한다.
$workshopPython = 'C:/projects/ai-workshop/backend/.conda/python.exe'
& $workshopPython -X utf8 -B scripts/prepare_rag_input_diagnosis.py --captures .local-data/project-agent-work/rag-v5-evaluation-20261019/actual-v5-inputs.json --results .local-data/project-agent-work/rag-v5-evaluation-20261019/evaluation-results.json --experiment .local-data/project-agent-work/rag-input-diagnosis-20261019/experiment.json --reviews .local-data/project-agent-work/rag-input-diagnosis-20261019/reviews.json --output .local-data/project-agent-work/rag-input-diagnosis-20261019/report-final
# backend 디렉터리에서 관련 검사
& $workshopPython -m pytest tests/unit/labs/rag/evaluation/test_offline_input_diagnosis.py tests/unit/labs/rag/evaluation/test_offline_input_artifacts.py tests/unit/labs/rag/evaluation/test_offline_rubric.py -q
```

### 남은 범위와 화면 검증 한계

브라우저 도구의 URL 보안 정책이 로컬 `file://` 보고서 열기를 거부했다. 이를 우회하지 않았으며 HTML 구조·텍스트·링크 검증만 수행했다. 보고서 실제 배치·320/375px·키보드 조작은 미검증이다. 사용자는 위 최종 HTML을 브라우저에서 직접 열 수 있다. 운영 페이지에 진단 메뉴를 추가한 작업은 아니다.

현재 확정할 수 있는 것은 필요한 원문이 전달됐지만 과거 정상 답변에서 규칙과 조건이 빠졌다는 사실이다. C의 효과, B의 줄배치 영향, 공급자 내부 절단/캐시·모델 자체 한계는 미확정이다. 후속 실험은 새 실행 범위를 정하고 같은 실험 안의 A 통제군과 동등 반복/순서를 준비해야 한다. 기존 품질·지연 미통과와 도메인 비활성 상태를 유지한다. 설치·다운로드·재색인·추가 생성·commit/push는 하지 않았다.

기존 관리자 UI에서 ISSUE-00005에 검증 이력을 저장하려 했지만 `Authentication is required.` 응답으로 거부됐다. 화면에 계정 표시가 남아 있어도 쓰기 인증 성공을 뜻하지 않는다. 새 이력 저장 완료는 확인되지 않았으며 DB 반영 미완료다. [미저장 초안](../../.local-data/project-agent-work/rag-input-diagnosis-20261019/issue-progress-draft.txt)과 [인증 필요 화면](../../.local-data/project-agent-work/rag-input-diagnosis-20261019/ui-issue-auth-required.jpg)을 보존했고 입력한 탭을 남겼다. 쿠키/자격 증명 추출이나 DB 직접 변경으로 우회하지 않았다.

## 후속: 승인된 A/B/C 실제 비교 실험

사용자가 제안된 3조건×2사례×2회=최대12회 로컬 생성·재시도0에 “그래 진행해”라고 승인했다. 기존 v5의4회와 별도 예산이며 기존 후보12개를 각각 한 번만 실행한다. 저장된 최종 입력을 재사용하므로 새 검색·임베딩·일반 큐 worker는 필요 없다. 생성 단계 비교이며 전체 RAG E2E나 수용 P95 평가를 대신하지 않는다.

메인이 요구사항·AI·RAG·테스트 설계를, 기존 별도 검토자가 독립 코드 리뷰·통합 검증을 담당한다. 위험은 중간이며 운영 UI/API·DB 스키마·배포 변경은 제외한다. `systematic-debugging`과 테스트 우선 절차로 준비한다. 현재 경로의 기존 미커밋 변경을 보존한다.

질문·원문·순서·스키마·출력512·temperature0·timeout360·retry0을 유지한다. A는 원본, B는 JSON 문자열 밖 줄배치만, C는 검토한 답변 지침 구간만 바꾼다. 최종 캡처에 이미 포함된 출력 계약을 다시 붙이지 않는다. 판정 기준은 전송과 분리한다. 모델/프로파일·현재 원문 접근·권한·정상 런타임 admission을 재확인하고 전송 직전 고유 슬롯을 예약해 실패/timeout도 소진으로 계산한다. 예열·보충 생성·자동 재실행은 금지한다.

사전 고정 순서는 정상A1→거절C1→정상B1→거절A1→정상C1→거절B1→정상C2→거절B2→정상B2→거절A2→정상A2→거절C2다. 모든 조건의 평균 실행 위치는6.5로 동일하지만 캐시·초기 로드나 소표본 한계를 제거하지 않는다. 실패 시 원인을 기록하고 자동으로 입력을 바꾸거나 예산을 늘리지 않는다. 결과에 따른 범용 개선 후보를 준비하되 실제 효과가 없는 변경을 성공으로 승격하지 않는다.

### 실제 12회 결과와 개선 판단

2026-10-19 20:44~20:59 KST에 승인12슬롯을 각각 한 번 전송해12/12 완료했다. HTTP 재시도0·추가 예열0·새 검색/임베딩0이다. 저장된 입력을 직접 비교한 로컬 생성 실험이며 DB에 새 평가 실행을 등록한 것은 아니다. 기존 v5 실행과 구분한다. 새 예산12회도 전부 소진됐다.

| 조건 | 정상 질문 품질 충족 | 근거 부족 질문의 적절한 거절 | 정상 생성 시간 1회 / 2회 | 거절 생성 시간 1회 / 2회 |
| --- | --- | --- | --- | --- |
| A 원본 | 0/2 | 2/2 | 118.111 / 7.552초 | 105.060 / 1.262초 |
| B JSON 문자열 밖 줄배치 | 0/2 | 2/2 | 151.068 / 7.697초 | 138.187 / 1.517초 |
| C 답변 지침 강화 | 0/2 | 2/2 | 109.778 / 7.069초 | 96.197 / 1.441초 |

실제 A 답변은 두 번 모두 다음과 같다. B는 두 번째 문장의 시작을 “그러므로”로 바꿨고, C는 같은 날짜 내용을 한 문장으로 합쳤다. 여섯 정상 답변 모두 일반 지급 규칙과 예시의 휴일 조건을 빠뜨렸다.

> AM-SYN-101을 2026-09-07 월요일 15:10에 신청하면 09-08 화요일이 접수일이다. 이 경우 기준가격 적용일은 09-10, 대금 지급일은 09-14이다.

전송한 정상 근거28개에는 `접수일 T+4 영업일`, T의 정의·마감 조건, 날짜 예시의 휴일 조건과 날짜가 모두 있었다. 근거 부족 사례는 전달26개에 확정 수익률이 없고 예측은 보장이 아니라는 내용이 있으며, 실제6답변이 모두 `insufficient_evidence`·빈 claims였다. 판정용 rubric은 입력에서 분리했고 원문을 정답 문장으로 바꿔 모델에 주입하지 않았다.

최종 출력12개는 모두 `finish_reason=stop`이며 사용량은19~172출력 토큰이다. 이번 관측에서 출력512 한도 도달이 원인이라는 증거는 없다. A/B는 각각 두 답변·주장·인용 배열까지 같았다. C의 답변 본문은 같았지만 첫 회는 앞 예시 조각 `2e8480e3…`만 인용했고, 두 번째는 뒤 조각 `af9d7189…`도 추가했다. 따라서 C의 출력127→162토큰 차이를 답변 내용 개선으로 해석하지 않는다.

기존 자동 인용 검사는 정상6건을 모두 통과시켰다. 그러나 C 첫 답변의 `09-10`, `09-14`는 인용하지 않은 뒤 조각에만 있다. [기존 수치 정규화 계약](../decisions/0035-rag-exact-value-canonicalization.md)과 `generation/exact_values.py`는 연도가 있는 날짜·일부 단위 수치만 인식하므로 짧은 날짜와 상대 영업일 규칙을 검증하지 않는다. 이는 새 회귀로 확정한 것이 아니라 현 검사의 범위 한계다. 날짜의 출처는 전체 전달 원문에 있으므로 숫자를 새로 지어냈다고 단정하지 않으며, 자동 인용 통과를 의미상 완전한 근거의 증명으로 사용하지 않는다. C 두 번째는 날짜 인용을 보완했지만 규칙·조건 누락은 해결하지 못했다.

첫6호출은96.20~151.07초, 이후6호출은1.26~7.70초였다. 처음 모델 조회는 비적재였고 첫 호출 중 관측된 context_length는16,384였다. 프로필·모델은 같았지만 로딩·캐시 등의 개별 기여는 측정되지 않았으므로 평균만으로 B/C의 속도 개선을 판단하지 않는다. 이 시간은 생성 단계 시간이며 전체 RAG P95 수용 평가를 대체하지 않는다. 이번 실험으로 모델의 비공개 내부 판단이나 입력 절단 여부가 밝혀진 것은 아니다.

**확정한 실패 지점은 필요한 원문이 최종 전송됐음에도 답변에서 규칙·조건을 사용하지 않았다는 점이다.** B 줄배치와 C 지침 강화는 이 표본에서 해결책이 아니었다. 품질 기준을 낮추거나 후보를 활성 설정으로 승격하지 않았다. 다음 개선은 다음 두 범위로 나눈다.

- 입력: 원문의 표에서 대상·항목·값 관계를 일반적인 구조 증거로 표현할 수 있는지 검증한다. 현 위치/블록 정보만으로 의미 관계가 증명됐다고 표시하지 않는다. 다른 업체·수치·일반 문서와 관계가 모호한 반례를 함께 검증하고 특정 질문의 정답을 넣지 않는다.
- 검사: 짧은 날짜·상대 규칙의 검사 범위와 실제 인용 조각의 지원 여부를 명확히 한다. 날짜처럼 보이는 제품 코드·범위와의 충돌을 다뤄야 하므로 정규식 확대만으로 의미 검증이 완성됐다고 주장하지 않는다. 공개 검사 계약 변경은 설계·회귀 검증 후 별도 반영한다.

이번 실제 비교와 원인 분리는 완료했지만 답변 품질 개선 자체는 미완료다. 추가 생성, 도메인 적용과 최종 입력 확인용1회는 실행하지 않았다.

### 실제 결과를 확인하는 산출물

- [실제 입력·출력 및 검토 보고서](../../.local-data/project-agent-work/rag-abc-experiment-20261019/reviewed-comparison.html):12개 질문, 실제 system/user, A 대비 변경, 전달 근거 ID/원문, 실제 답변/claims/출력 JSON, 기존 rubric 누락을 함께 표시한다.
- [실제 질문→근거→지침→답변 설명 이미지](../../.local-data/project-agent-work/rag-abc-experiment-20261019/actual-rag-flow.png): A 실제 입력·출력 발췌와 A/B/C 결과를 시각화했다. 예시 답변을 새로 작성한 이미지가 아니다.
- [원시12결과와 오프라인 검사](../../.local-data/project-agent-work/rag-abc-experiment-20261019/analysis.json), [완료·DB 보존 결과](../../.local-data/project-agent-work/rag-abc-experiment-20261019/completion.json), [입력·실행 파일 매니페스트](../../.local-data/project-agent-work/rag-abc-experiment-20261019/manifest.json).

원시 결과와 기존 미실행 후보 파일을 덮어쓰지 않았다. 실제 완료 기록은 별도 폴더에 두며 과거 후보 준비 시점의 상태를 소급 변경하지 않는다. PNG는 실제 데이터를 그린 독립 설명 자료이며 이미지를 직접 확인했다. HTML은 이전 브라우저 file URL 차단을 우회하지 않고 구조·문자열·링크만 검사하므로 실제 브라우저 배치·반응형·키보드 검증은 여전히 미완료다.

### 실행 보호와 보존 검증

기존 정상 런타임의 입장 조건, 현재 owner/원문 접근 권한, 정확한 프로필·모델·정책 및 대기 평가 부재를 읽기 전용으로 확인했다. 모델은 `gemma4:e2b-it-q4_K_M`, digest `b37049369adfe3d2b653af0ab301a062ca5cbe96ace6aa0d3f2559ee9b563fc2`, Ollama0.40.3이었다. 이전 실제 A와 현재 어댑터의 전송 payload4개를 모의 응답으로 대조해 중복 지침 추가 없이 일치함을 확인했다. 이 사전 비교는 실제 생성0회다.

매니페스트 SHA-256은 `e15288c5d9adb1128fa77eecfbb288dc4553de51ec0dd54424915678a2f6c563`이며98개 입력·코드 파일을 고정했다. 전송 직전 고유 슬롯을 배타적으로 기록하고 정확 body·로컬 endpoint만 허용했다. 중복 시작/순서/변경 body/다른 URL/timeout 재시도 금지를 다루는8개 보호 검사가 통과했고 별도 검토자가8개를 독립 실행했다. runner는 `--execute-approved-12`의 한 번 실행만 했으며 완료 상태에서 재실행하지 않는다.

실행 전후 기존6테이블의 행 수와 전체 해시가 같다: 평가 실행11, 시도539, 프로필23, 구성 버전15, 정책1, 생성 감사495. 새12개 결과는 이 DB의 평가/감사 행으로 삽입하지 않았다. 각 결과를 저장하기 전 현재 접근 권한과 보존 상태를 재검사했다. 이 확인은 새로운 검색 ACL 공격 테스트나 전체 도메인 수용을 대신하지 않는다.

별도 검토자가 모델·HTTP·DB 호출 없이 [독립 산출물225개 검사](../../.local-data/project-agent-work/rag-abc-experiment-20261019/independent/final-review.json)를 통과했다. 슬롯12개·전송 직렬화와 SHA·정확 승인 입력·HTTP200/stop·순차 시간·원문 위치·권한 scope·6테이블 전후 해시·rubric/집계가 일치했다. 최종 보고서의 실제 입출력/근거96블록도 원본과 같다. “조건·사례별2회, 조건당4회”와 “정상2+거절2 평균”을 명시해 분모 혼동을 보완했다.

최종 보존 검사에서 기존 v5 산출물50개와 고정98파일의 SHA가 일치했다. 작업 시작 기준2,009파일 중 변경된 것은 `WORKBOARD.md`와 이 worklog뿐이며 나머지 기존 변경을 보존했다. 새 실행기·검사·결과·이미지는 Git 제외된 로컬 산출물 폴더에 있다. 실행/분석 스크립트6개의 Ruff E9/F 검사와 두 문서의 상대 파일 링크·`git diff --check`를 통과했다. 제품 코드 변경이나 전체 타입/통합 테스트를 새로 수행한 작업은 아니다. 상세 수치는 [최종 보존 검사](../../.local-data/project-agent-work/rag-abc-experiment-20261019/final-preservation.json)를 따른다.

ISSUE-00005는 미해결 상태이며 이번 결과의 관리자 DB 이력 반영도 미완료다. 앞선 쓰기 인증 실패를 우회하지 않고 [추가 기록 초안](../../.local-data/project-agent-work/rag-abc-experiment-20261019/issue-progress-draft.txt)을 보존한다. 설치·다운로드·재색인·일반 worker 기동·활성 설정/도메인 변경·commit/push는 하지 않았다.
