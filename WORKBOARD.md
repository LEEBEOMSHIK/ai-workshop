# Workboard

> 인계(2026-10-20): 사용자 요청에 따라 누적 구현·테스트·변경 이력을 커밋·푸시 대상으로 정리했다. 사용자 참고 이미지 1개는 보존·제외한다. 종료 로그·정적 검사 캐시를 원문 보존 압축해 기존 점유 공간 약729MiB를 줄였고 이번 임시 빌드 약101MiB를 제거했다. 검증 통과·실패·미완료와 Git 반영은 [인계 기록](docs/worklogs/2026-10-20-rag-git-handoff.md)을 따른다. 새 모델 호출·운영 데이터 변경은 없다. 아래 과거 작업의 commit/push 제외 조건은 이번 인계 요청에 적용하지 않는다.

> 최신 RAG 결과: A/D 실제 생성 8/8회 완료. D는 예시 휴일 조건·관련 인용을 보완했지만 일반 지급 규칙 누락이 남아 정상 품질 A·D 각각 0/2, 적절한 거절 각각 2/2다. 전체 RAG 수용·운영 승격은 미완료다. [실제 결과](docs/worklogs/2026-10-19-rag-relation-improvement.md#2026-10-20-실제-ad-비교-검증)

## 프론트·백엔드 수동 기동

Docker Desktop과 기존 PostgreSQL·Redis·Elasticsearch 컨테이너가 실행된 상태에서, **새 PowerShell 창 2개**를 열어 각각 실행한다. 아래는 본래 환경의 포트 기준이다. 상세 절차는 [로컬 실행 안내](docs/runbooks/local-development.md#3-호스트-애플리케이션-실행)를 따른다.

**백엔드 — 첫 번째 창**

사용자 선호에 따라 `.ps1` 실행기 대신 **환경 준비 후 Python으로 직접 실행**한다. 새 PowerShell 창에서 먼저 아래 블록으로 저장소 루트로 이동하고 Conda DLL·인증서 경로, 앱 소스 경로와 UTF-8을 준비한다.

```powershell
Set-Location C:/projects/ai-workshop
C:/Users/bumci/miniconda3/python.exe -I -B -m conda shell.powershell activate C:/projects/ai-workshop/backend/.conda | Out-String | Invoke-Expression
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
Set-Item Env:PYTHONPATH C:/projects/ai-workshop/backend/src
Set-Item Env:PYTHONUTF8 1
```

위 단계가 오류 없이 끝나면 **같은 창에서** 서버를 실행한다.

```powershell
C:/projects/ai-workshop/backend/.conda/python.exe -B -m uvicorn ai_workshop.main:app --loop ai_workshop.shared.asyncio_policy:create_selector_event_loop --host 127.0.0.1 --port 18000
```

실행 파일은 `C:/projects/ai-workshop/backend/.conda/python.exe`이며, Windows Selector 이벤트 루프로 Uvicorn을 실행한다. 주소는 `http://127.0.0.1:18000`이다. 환경 설정은 현재 PowerShell 창에만 적용되며 서버 종료 후에도 그 창에는 남는다. `python.exe`만 실행하면 Python 대화창(REPL)이 열리므로 서버 실행에는 위 Uvicorn 명령과 준비된 환경이 필요하다.

위 명령은 설치·다운로드나 다른 서버의 시작을 수행하지 않는다. 백엔드 자체의 시작 검사는 기존 DB를 읽고, 보안 전환 상태에 따라 Elasticsearch·Docker 상태를 조회할 수 있다. 상세 환경 설명은 [로컬 실행 안내](docs/runbooks/local-development.md#windows-도구용-표준-활성화)를 따른다.

**프론트엔드 — 두 번째 창**

```powershell
Set-Location C:\projects\ai-workshop
pnpm --dir frontend dev
```

두 앱은 루트 `.env`를 직접 읽는다. JSON 설정의 따옴표가 유지되는 단순 PowerShell `.env` 복사 블록은 실행하지 않는다. 백엔드는 루트 디렉터리에서 실행하며, 위 명령은 자동 reload가 없으므로 코드 수정 후 재시작한다.

- 접속: [프론트엔드](http://127.0.0.1:5173), [API 문서](http://127.0.0.1:18000/api/docs)
- 정상 시작 확인: 백엔드 창의 `Application startup complete.`와 `Uvicorn running on http://127.0.0.1:18000`을 확인한다. 이번 새 환경의 기동은 사용자 확인 완료이며, 아래 health 응답 확인과는 구분한다.
- 상태 확인: 다른 PowerShell 창에서 `Invoke-RestMethod 'http://127.0.0.1:18000/api/v1/health'`를 실행해 `status`가 `ok`인지 확인하거나 [health](http://127.0.0.1:18000/api/v1/health)를 브라우저에서 열어 `{"status":"ok"}`를 확인한다. [ready](http://127.0.0.1:18000/api/v1/ready)는 별도의 시작 조건 확인용이다. 이번 기동 후 health는 2026-10-16 사용자 보고로 확인했다. 전체 검색 RAG 재시험은 미실행이며, 저장 입력 생성2회 결과는 최상단 기록을 따른다. health 성공만으로 RAG·모델 품질 검증이 완료되지는 않는다.
- 종료·재시작: 실행한 창에서 `Ctrl+C`로 종료한다. 같은 창에서는 Python/Uvicorn 실행 줄을 다시 실행하고, 새 창에서는 환경 준비부터 반복한다. 이미 서버가 실행 중이면 먼저 기존 서버를 종료한다.

## 현재 상태

- 마지막 갱신일: 2026-10-20
- 현재 결정: **AMD64 유지. RAG 기능 마감을 우선한다. ARM64 전환과 로컬 Linux ARM64 OCR 분리 제안은 취소된 조사 이력이다.**
- 이전 환경 복구·검증 이력: 실제 PDF footer 회귀의 오프라인 수정·검증(RAG6024통과/17skip·Mypy471·Ruff·독립163통과)은 완료했다. 후속 승인 단일 정답 검색1회는 실행 wrapper가 필수 비추론 health 확인을 잘못 차단하여 생성 전에 중단됐다. 요청1/1 소진·실제생성0·재실행0이며 정답·인용·속도는 미검증이다. Gemma/제품/정책의 실패로 해석하지 않는다. 직전 실평가 정답0/2·P95226.74초는 그대로다. [최신 기록](docs/worklogs/2026-10-11-rag-http-cancellation-regression.md#2026-10-14-승인-단일-정답-검색-실행-중단). 실행 wrapper의 오프라인 준비 검증은 2026-10-15 완료했다: mock27·독립27통과, backend Mypy471·guard strict Mypy1·Ruff4·보존 SHA13개 일치. [준비 결과](docs/worklogs/2026-10-11-rag-http-cancellation-regression.md#2026-10-15-단일-검색-wrapper-오프라인-준비-검증-마감). 사용자 재승인 단일 질문도 2026-10-15 ImportError로 생성 전 종료됐다(새 요청1/1 소진·생성 POST0·감사0). 별도 임베딩 라이브러리 import에서 SciPy `_direct` DLL의 Windows 애플리케이션 제어 정책 차단을 재현했다. Ollama·모델·원래 DB/구성·admission·ES는 확인했으나 정답·인용·생성 시간은 미검증이다. 정책 우회·재실행 없이 기록을 보존했다. [최신 실행](docs/worklogs/2026-10-11-rag-http-cancellation-regression.md#2026-10-15-재승인-단일-질문--생성-전-importerror-종료). 승인된 독립 Miniconda 시험은 공식 메타데이터 다운로드의 DNS11001 오류로 설치 전 중단됐으며, 같은 호스트 재진단에서 Windows DNS 오류5(액세스 거부)도 확인했다(설치/시험0). 빈 준비 폴더만 정리하고 실패 증거를 보존했다. 후속 사용자 다운로드 설치 파일은 공식 SHA·Authenticode Valid를 확인했으나 도움말 실행부터 Windows DLL 재할당 오류로 실패해 설치/시험0을 유지한다. 원본 설치 파일과 진단은 보존하고 빈 임시물만 정리했다. 사용자 직접 설치 후 Python3.13.15·conda26.7.1 모듈 진입점은 실행됐으나 최소 환경 dry run이 공식 저장소 DNS11001로 실패했다. 패키지 다운로드/시험 환경 생성0이며 임시388bytes만 정리하고 사용자 base를 보존했다. 이후 사용자가 설치한 별도 `ai-workshop-scipy-test`는 SciPy/NumPy 확장·DLL252개 서명 Valid와 표준 Conda PowerShell 활성화 후 기존 차단 모듈4개 import·수치7개 검증을 통과했다. `conda run` 활성화9020 오류는 별도로 남으며, 성공 후보 환경317,369,597bytes는 보존했다. 기존 프로젝트 전환·RAG 검증은 미실행이다. 후속 전환·성공 뒤 구환경 복구가능 정리가 승인됐으나, PaddleX의 NumPy<2.4 제약과 대상 prefix의 EnvironmentNotWritableError로 설치 전 중단했다. 사용자 NumPy2.3.5 정렬 뒤 서명252개·기존 차단 모듈4개 import·수치7개는 통과했다. 사용자 일반 PowerShell 설치 후 공식 wheel149개 버전·Conda 보호 파일6121개·서명252개·pip check를 재확인했다. 새 환경의 Torch/Sentence Transformers/backend import와 캐시 E5 문서·질문 임베딩(768차원,12.20초)은 통과했다. 다만 health GET이 WinError10013 소켓 접근 거부로 차단돼 backend 기동·저장 E5 벡터 호환·실제 RAG는 미검증이다. 새 환경0·새 RAG0/1·구환경 제거0을 유지하며 정책·권한 우회 없이 중단했다. 사용자는 Conda 실행기 재기동 뒤 오류 없음·health status ok를 보고했다(에이전트 직접 재확인 아님). 사용자 정상 PowerShell용 저장 벡터 비교·공개 합성 범위 검사·신규 단일 요청 도구 준비는97개 오프라인 검사·strict Mypy4파일·Ruff·독립 리뷰로 마쳤다. 사용자 실행 저장 벡터 비교는 고정 합성 청크1개에서 통과했다(768차원·cosine0.9999999999999998·최대오차4.21e-9, 로컬 결과/세션/16파일 SHA 확인). 사용자 preflight는06:19:37 UTC에 공개 합성3문서 범위로 통과했다. 다만 벡터 증거가 만료되어 로컬 --check-ready가 stale_or_future_preflight로 차단했다. 같은 세션에 읽기 전용 관측을 누적하는 갱신 명령을 추가했고 오프라인115검사·strict Mypy3·Ruff·독립 재검토를 마쳤다. 원래 증거·예약과15분 제한을 보존하며 새 실제 관측은 아직 미실행이다. 사용자 실행 단일 RAG는06:53:31 UTC에 answered 결과를 기록했다(전체284.71초·생성266.78초·인용2개 근거일치·이번 SciPy 차단 재발 없음). 답변은 특정 날짜 예시만 제시해 일반 T+4 영업일 설명이 부족하며 완전한 정답 수용으로 판정하지 않는다. 예산1/1·생성POST1회다. 같은 요청의 사용자 화면에서 commit 이후 SEARCH_END answered(06:53:31.528090 UTC)와 PowerShell 복귀를 확인했다(종료코드 숫자는 미관측). 일상 API·검색·생성의 Conda 실행 검증은 통과했고 답변 직접성은 별도 품질 항목이다. 구 .venv 참조6파일 중 활성 실행5파일의 고정 Conda 전환과 실행 안내 갱신을 완료했다. 역사 증거1파일은 보존했다. 오프라인 Python208통과/13skip·Node15통과·PS 검증·Mypy472·Ruff·독립 보안 리뷰를 마쳤고 권한·epoch·프로세스 검증을 유지한다. 새 경로의 실제 서비스/Route DLL·SSL 기동과 구환경 사용 여부 확인은 미실행이다. 요청 증거17파일 SHA와 예산1/1을 보존했으며 구환경1.584GiB는 이동/삭제하지 않았다. [전환 결과](docs/worklogs/2026-10-11-rag-http-cancellation-regression.md#2026-10-15-고정-conda-실행-참조-전환-결과). [수동 확인 준비](docs/worklogs/2026-10-11-rag-http-cancellation-regression.md#2026-10-15-conda-수동-벡터범위단일요청-준비). 개발 우선순위는 유지한다.
- 현재 범위: Markdown/TXT/PDF/DOCX·OCR ingestion, 검색·뷰어·근거 제한 답변·인용 및 관리 기능의 코드가 있다. 코드 존재·mock 통과·본래 환경 수용·운영 활성화는 구분한다.
- 아직 **품질 개선만 남은 상태가 아니다**. 아래 기능 마감 조건을 실제로 충족하면 사용자에게 그 상태를 별도로 알린다.

## 현재 기능 마감: 상위 5묶음

상위①을 a/b/c로 나눈 세부 7개와 상위 5개는 같은 범위다. 추가 작업으로 중복 집계하지 않는다.

| 묶음 | 남은 결과와 검증 | 근거 |
|---|---|---|
| ① 별칭 복구·개인 첨부 색인 | a. 실제 native 제출·이력 및 observer/backend/factory 조립 → b. 과거 실행 종료·쓰기 차단/보안 전환 → c. 정확한 receipt·release·fresh parity와 기존 queued 색인 READY. generic 계약·recording 구현만으로 완료하지 않는다. | [native 경계](docs/worklogs/2026-10-08-rag-control-native.md), [복구 조사](docs/worklogs/2026-10-11-rag-recovery-evidence-investigation.md) |
| ② 첫 질문·권한·취소 경합 | 현재 Gemma 정상 답변/인용·대화 UI 연결, 실제 first POST·committed 권한 철회/첫 질문 경합·취소 terminal 저장·다음 질문 및 본래 브라우저 수용. 합성/rollback 회귀와 구분한다. | [기능 마감 기준](docs/worklogs/2026-10-11-rag-functional-closure-check.md), [경계 검증](docs/worklogs/2026-10-07-rag-functional-boundary-verification.md) |
| ③ 실모델 failure/timeout/cancel | 실제 worker/원격 실행의 종료, terminal 결과 저장과 이후 질문 수용. 신규 실패 진단·실패 전 측정값이 최신/누적 모니터링·비교 화면·새로고침 뒤에도 일치해야 한다. HTTP mock 회귀가 실모델 종료를 대신하지 않는다. | [HTTP 회귀](docs/worklogs/2026-10-11-rag-http-cancellation-regression.md), [브라우저 경계](docs/worklogs/2026-10-05-rag-browser-closure.md) |
| ④ Windows DLL 재발 방지 | 기존 환경·애플리케이션 제어 정책 안에서 SciPy 등 native import 차단의 원인과 재발 방지를 검증한다. 정책 완화·대체 로더 우회는 하지 않는다. | [본래 환경 진단](docs/worklogs/2026-10-06-rag-numeric-proof-browser.md), [Gemma 사전 검사](docs/worklogs/2026-10-12-gemma4-e2b-preflight.md) |
| ⑤ main·원격·실행 인계 | 이번 사용자 요청은 누적 변경의 commit/push를 포함한다. Git 반영과 본래 실행 환경의 실제 반영·수용을 각각 확인하며, 누적 회귀·인계 검증을 운영 전환 완료로 확대하지 않는다. | [최신 인계](docs/worklogs/2026-10-20-rag-git-handoff.md), [이전 검증](docs/worklogs/2026-10-12-rag-git-handoff.md) |

### 관찰된 상태와 복구 차단

- **2026-10-14 읽기 전용 재확인:** 별칭 open1/frozen1/receipt0, ISSUE-00013 open/r33, 과거 cancelled/종료미확인1. Projection ready6/pending1/failed1(기존 chunk_tokenizer_unavailable), 개인 첨부 ingestion queued1. HTTP intake5개는 모두 cleaned/attached이며 새 잔여 결함은 관측하지 않았지만 과거 비추적 파일·물리 잔여물 전체 부재는 미검증이다. DB0065 적용·보존 검증은10/12 기존 기록을 유지한다. [기능 재점검](docs/worklogs/2026-10-11-rag-http-cancellation-regression.md#2026-10-14-기능-마감-우선-재점검--읽기-전용).
- 과거 `execution_terminated=false` 대화의 정식 복구 API는 미구현이다. 소유권·실행 결합·종료 증거·CAS/멱등성·감사를 다룬 [취소 복구 설계](docs/superpowers/specs/2026-10-11-rag-cancelled-turn-recovery-draft.md)는 **미승인 초안**이다.
- 34개 요청/67개 코드 의존성 source-map 진단은 당시 v2 검증 경계다. v1 역사 자료와 구분하며 파일 유실이나 모든 복구 경로의 보편 차단으로 단정하지 않는다. [정정된 조사](docs/worklogs/2026-10-11-rag-recovery-evidence-investigation.md).
- 현재 PID/TCP/UUID·새 journal·PC 재시작만으로 과거 실행 종료 proof를 만들어내지 않는다. 실제 실행/위임 종료·fencing과 자료·큐 보존을 충족해야 한다. [제어 범위](docs/worklogs/2026-10-02-rag-control-boundary-assessment.md), [소유권](docs/worklogs/2026-10-08-rag-access-epoch-ownership.md), [제출 이력](docs/worklogs/2026-10-08-rag-control-submission.md).
- 개인 첨부의 파일/Asset READY와 RAG Projection/색인 READY는 다르다. 10/8 파일 검증과 당시 개인 색인 예약 대기를 전체 검색 가능 상태로 확대하지 않는다. 개인 자료 외부전송 deny를 유지한다. [첨부 검증](docs/worklogs/2026-10-08-rag-personal-attachment-verification.md).
- 활성32·pending128/defaultfalse·기존 frozen gate 및 과거 평가 결과는 마지막 관찰 기준 보존 대상이다. 새 평가 반복·후보 승격·SQL gate 해제를 기능 마감의 대체로 하지 않는다.

## Gemma·실행 환경

- `local_transformers` 배포 참조, 단일 모델 호스트, 취소/timeout·schema2·인용·토큰 기록은 코드와 mock 검증이 있다. [ADR-0037](docs/decisions/0037-local-transformers-generation.md), [구현 계획](docs/superpowers/plans/2026-10-11-local-transformers-generation.md), [구현·검증 기록](docs/worklogs/2026-10-11-local-transformers-generation.md).
- 실제 모델 선택·고정 revision/라이선스·native 호환성, uv 공식 lock 일치 검증, Transformers 모델 다운로드·실추론 및 운영 활성화는 완료하지 않았다. 0064→0065 영향 검토·기존 DB 적용과 보존 검증은2026-10-12 승인 범위에서 완료했다. E2B 사전 검사의 import 차단과 BF16/mock 결과를 실모델 수용으로 확대하지 않는다. [사전 검사](docs/worklogs/2026-10-12-gemma4-e2b-preflight.md).
- AMD64 기존 실행 환경을 유지한다. ARM64 실험 설치물·검사 사본은 원래 경로에서 제거됐고 실험 기록은 보존한다. 이전10개는 휴지통에서 확인했으며 사용자 삭제 검사 사본의 복구 가능성은 미확정이다. [정리 결과](docs/worklogs/2026-10-12-arm64-environment-comparison.md#user-reported-copy-removal-confirmed).
- 취소된 [ARM64 의존성 조사](docs/runbooks/arm64-dependency-resolution.md), [기능 비교](docs/runbooks/arm64-feature-parity.md), [ARM64 OCR 설계](docs/superpowers/specs/2026-10-12-local-arm64-ocr-design.md)는 재개 대기 실행서가 아니다. Gemma 제품 코드나 기존 OCR 기능의 취소를 뜻하지 않는다.
- 본래 환경 실행·migration·owner bootstrap·smoke 명령의 유일한 정본은 [로컬 개발 실행서](docs/runbooks/local-development.md)다. 오래된 PID·health·실행 명령을 이 보드에 복제하지 않는다.

## Ollama 로컬 서버 실행 메모

기존 설치 `C:\AI\Ollama\ollama.exe`와 모델 저장소 `C:\AI\OllamaModels`의 존재를 2026-10-13 확인했다. 아래 명령은 문서이며 이번 작업에서 실행하지 않았다. 기존 모델을 사용하며 설치·pull·전역 환경변수·자동시작 서비스는 추가하지 않는다.

- 먼저 별도 PowerShell에서 `Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction Stop`으로 확인한다. listener가 있으면 기존 서버를 사용하고 중복 실행하지 않는다. 접근 거부는 빈 포트라는 뜻이 아니다.
- 새 시작은 기존 서버가 종료됐고 포트가 비었음을 확인한 뒤에만 한다. 현재 부모 프로세스 조회는 Windows 접근 거부로 미확인이다.
- 아래 4개 성능 변수의 기존 값은 아직 확보하지 못했다. **기존 실행값을 확인해 같은 PowerShell 세션에 설정하기 전에는 재시작하지 않는다:** `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_NUM_PARALLEL`, `OLLAMA_MAX_LOADED_MODELS`, `OLLAMA_KEEP_ALIVE`. 임의 기본값을 현재 실행값으로 기록하지 않는다.

```powershell
# 서버용 PowerShell: 확인한 기존 4개 성능 변수를 먼저 이 세션에 설정한다.
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = 'C:\AI\OllamaModels'
$env:OLLAMA_NO_CLOUD = '1'
$ollamaRequired = @('OLLAMA_CONTEXT_LENGTH', 'OLLAMA_NUM_PARALLEL', 'OLLAMA_MAX_LOADED_MODELS', 'OLLAMA_KEEP_ALIVE')
foreach ($ollamaName in $ollamaRequired) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($ollamaName, 'Process'))) {
        throw "기존 실행값 확인 후 $ollamaName 을 현재 세션에 설정하세요."
    }
}
& 'C:\AI\Ollama\ollama.exe' serve
```

별도 PowerShell에서 비추론 확인: `Invoke-RestMethod 'http://127.0.0.1:11434/api/version'`, `Invoke-RestMethod 'http://127.0.0.1:11434/v1/models'`. 응답/설치 모델 조회 성공은 RAG 생성 성공을 뜻하지 않는다. 전경 `serve` 창을 닫거나 Ctrl+C로 종료하면 해당 서버를 쓰는 로컬 RAG 호출은 불가능해진다. RAG 사용 중에는 창을 유지한다. 일반 앱 실행 정본은 [로컬 개발 안내](docs/runbooks/local-development.md)다.

## 다음 작업 순서

1. 실제 PDF footer 보완의 오프라인 검증은 완료했지만 승인 단일 검색은 실행 wrapper의 health 오분류로 생성 전 중단됐다. 비추론 health 위임·단일 POST 제한의 offline 계약 검증은27개 및 독립27개 통과로 마감했다. 10/15 재승인 실행은 ImportError로 생성 전 종료됐고 단독 import에서 SciPy `_direct`의 애플리케이션 제어 정책 차단이 재현됐다. 다음 후보는 정책을 유지한 DLL 차단 원인·정상 승인 경로 조사와 native import 사전 검사/오류 상태·감사 누락의 오프라인 회귀 검토다. 이 차단이 해소되기 전 실제 질문을 반복하지 않는다. 기존 예약 기록을 초기화하거나 기존 스크립트를 그대로 재실행하지 않는다. 10/14·10/15의 각 요청1회는 각각 소진됐고 실제 재호출은 새 승인 대상이다. 직전4attempt 실평가의 정답0/2·P95226.74초는 미통과 상태다. 첫 생성 지연의 로드·입력 처리·생성 시간 분해도 미확인이다. 기준 완화·자동 재평가·추가 대화·승격/도메인 활성화는 하지 않는다. 별칭 복구·본래 환경 수용·관리자 문제 DB 반영은 계속 남는다.
2. 별칭 복구의 a→b→c 선행 관계를 지키며, 독립 가능한 첫 질문/권한·취소·실패 흐름 검증을 진행한다. 실제 종료 증거·운영 범위가 없으면 임의 전환하지 않는다. H07의 부정·미확인 의미 이해/프롬프트 튜닝은 기능 수용 뒤 품질 과제로 보류한다.
3. **RAG 기능 마감 → Agents SDK → 벡터 저장소 비교 → 로컬 LLM 파인튜닝 비교 → Kubernetes** 순서를 유지한다. 지속 품질 개선의 완결을 후속 학습의 무기한 선행 조건으로 삼지 않는다.

| 후속 | 승인된 준비 범위와 다음 경계 |
|---|---|
| Agents SDK | Python/Provider 호환성·계약/ADR → SDK 어댑터 → 세션/권한 → 필요한 전문 역할 → 모니터링 → 동일 조건·본래 환경 검증. 개발 Codex 협업 도구와 서비스 에이전트를 구분한다. 설치·런타임 전환 미착수. [계획](docs/superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md) |
| 벡터 저장소 | Elasticsearch·전용 벡터 DB 후보1개·PostgreSQL/pgvector를 동일 청크/벡터·권한·BM25/RRF 조건으로 비교. 임의 이관하지 않는다. [비교 범위](docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md) |
| 로컬 LLM 파인튜닝 | 장치·라이선스·검토 데이터셋 준비 후 학습 전후를 같은 근거로 비교. 저장소 비교와 독립 실험이며 SDK/기존 복구 완료를 대체하지 않는다. 설치·학습 미착수. [계획](docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md) |
| Kubernetes | 현재 장치·Docker·OS·자원·본래 자료 연결 조사 후 배포/통신→설정/권한→복구→확장/업데이트→영속 저장소→Compose 비교. 순서는 프로젝트 우선순위이며 기술적 필수 의존성은 아니다. 개념/흐름도 준비는 병행 가능, 설치·새 DB/계정·이관·서버 전환 미착수. [계획](docs/superpowers/plans/2026-10-08-kubernetes-learning.md) |
| 84일 학습 | [학습 문서8개](docs/learning/2026-10-12-ai-engineering-84-days/README.md)는 준비 산출물이다. 실제 진도는 해당 기록 기준이며 개발 작업으로 자동 완료하지 않는다. 교재·사용량 알림 예약은 이번 작업에서 변경하지 않는다. |

## 승인과 보존 경계

- 2026-10-14 후속 승인: 시험 구성 v2·기존 합성 평가2사례×2반복으로 로컬 Ollama Gemma 평가 최대4회, 기존 P95 120초 등 기준 통과 시에만 평가 결과 반영·자산운용 연결 활성화·일반 대화1회. 총 생성 최대5회/자동 재시도 없음. 전역 기본값·외부 모델·새 로그인/인증 추출·권한 확대·임의 프로세스 종료는 제외한다. 현재 로그인 완료·워커 반영 확인 대기이며 신규 호출0/5.

- 2026-10-12 후속 승인: before.dump 한 파일의 복구 가능한 휴지통 이동 및 제품4파일 dialect 연결·mock 검증. 이동·동일 SHA 검증 완료, 다른 백업/증거/실데이터 보존. 실제.env·DB쓰기·서비스·모델 호출은 제외한다. [이동 기록](docs/worklogs/2026-10-11-local-transformers-generation.md#승인된-백업-휴지통-이동).

- 2026-10-12 추가 승인: 기존 `ai_workshop_local_clean`에 데이터 삭제·재입력 없이 정확한0064·0065 적용, 로컬 백업·비파괴 보존 검증과 최소 기록 갱신. 서비스 재시작·모델 등록·활성 설정·실모델 호출·보안 권한 변경은 제외한다.

- 현재 개발·운영 승인: HTTP/Ollama 배포·일반 생성 프로파일 관리자 폼, 기존 owner API 사용, endpoint 참조·dialect 설정, 유휴 기존 API 재시작, 비기본 시험 구성 및 로컬 Gemma 최대3회 정상/근거부족/취소 검증. 서버 주소 관리 UI·인증 우회·보안 권한 확대·설치·commit/push는 제외하며 기존 활성 연결과 기본값을 보존한다. 재시작 권한 거부 이후 우회·승격하지 않는다.

- 이전 정리 승인: 현행 문서·깨진 링크 정합화, 미완료·승인·이력 보존을 전제로 WORKBOARD 축약, 종료·점유·재생성 가능성을 확인한 정확한 Mypy 캐시의 복구 가능한 휴지통 이동. 범위 밖에서 생성한 테스트·개발 worklog2개와 그 Mypy 캐시의 복구 가능한 정리도 별도로 승인됐다.
- 이전 정리 제외: commit/push, 제품 동작·로그 회전 설정, migration, DB/Elasticsearch/Docker/서비스 상태 변경, 인증·보안 권한 확대, UV 캐시, 실행 중일 수 있는 `.next`, dev-logs/복구 입력, 미해결 native 복구 작업의 Mypy 약313MiB, 접근 거부 영역, 영구 삭제·휴지통 비우기.
- 기존 사용자 계정·자료·원문·업로드·모델·대화·구성·문제/평가 이력과 IDE/Codex/frontend 실행을 보존한다. 사용자 검증용 새 환경·DB·계정을 임의로 만들지 않는다. 별도 환경 성공을 본래 환경 완료로 보고하지 않는다.
- 개인 Codex owner-only 제한 실행 및 관측 모델 unknown 예외는 이미 승인된 계약이다. 이를 취소/미승인으로 되돌리지 않는다. 모델 identity 외 검증은 그대로 필요하다. [ADR-0017](docs/decisions/0017-personal-codex-exec-provider.md).
- 합성 참조 자료와 평가·승인 이력의 로컬 보관은 승인됐다. 공개 게시·학습 사용 승인을 뜻하지 않으며 완전 삭제 UI 부재 고지를 보존한다. [활성화 기록](docs/worklogs/2026-09-09-codex-rag-activation.md).
- 실제 외부 API smoke는 해당 입력 전송·비용·안전한 credential·exact Deployment/Generation Profile/구성 승인 조건을 따른다. 이전 특정 호출 승인을 새 대상의 포괄 승인으로 확대하지 않는다.
- 보안 정책 해제·전역 인증서 추가·대체 로더 우회·유료 서명 신청·임의 다른 모델 전환은 승인 범위가 아니다. 기존 App Server 격리 차단을 지우거나 개인 Codex 계약과 혼동하지 않는다.
- 문제 DB의 정확한 문서 버전·SHA·사건 연결을 보존한다. 등록 대기 초안이나 새 문서의 DB 반영을 임의 완료 처리하지 않는다. 운영 문제 정본과 문서 보존 기준은 [문제 이력 규칙](docs/issues/README.md)을 따른다.

## 별도 보류·장기 후속

아래는 이전 인계에서 남은 경계다. 재개할 때 최신 코드·후속 기록과 대조하며 오래된 미완료 문구만으로 재구현하지 않는다.

| 분야 | 보존할 후속과 근거 |
|---|---|
| 삭제·휴지통 수명주기 | 전체 participant inventory, 구 writer/파일 writer 종료, 잠금 순서·잔존 재검증·OCR writer·legacy/backfill·비Windows native 및 실제 삭제 API/UI 통합. 기반 구현과 운영 활성화는 구분한다. [임시 작업/삭제 경계](docs/worklogs/2026-09-20-jobs-and-rag-sandbox.md), [provenance](docs/worklogs/2026-09-14-asset-purge-provenance.md) |
| 파일함·실제 화면 | 이름 변경/휴지통·복원, PDF/중첩 폴더/다중 버전의 실제 사용자 흐름과 뷰어 닫기 초점 Minor. 기존 이동·권한 구현을 반복하지 않는다. [서버](docs/worklogs/2026-09-13-explorer-movement-server.md), [UI](docs/worklogs/2026-09-13-explorer-movement-ui.md) |
| 기술별 권한 | 공통 권한 기반과 기존 RAG 기술별 위임 개방은 구분한다. [기반 기록](docs/worklogs/2026-09-09-technology-permissions-foundation.md) |
| Learning 제품 | 로그인 브라우저 확인·모델 비교/학습 실행은 별도 후속이며 84일 학습 문서 준비와 다르다. [기록](docs/worklogs/2026-09-07-private-learning.md) |
| 공개 화면·게임 | 공개 기록/관리 미리보기·SQLite 동시 조회/실패 경로, 사용자 이동감/NPC/그래픽 확인 후 공간 확장. 기존 열린 공개 본문의 소급 회수를 약속하지 않는다. 전체 연구실·실제 AI 실행을 자동 확장하지 않는다. [월드 검증](docs/worklogs/2026-09-04-full-screen-ai-lab-world-verification.md), [사장실 MVP](docs/worklogs/2026-09-07-game-office-mvp.md) |
| 과거 격리 경로 | App Server 도구 목록 기반 후보와 OS 격리 합성·인증/통신 경계는 차단/미검증 이력으로 보존한다. 해당 경로를 다시 선택할 때만 절차를 재개한다. [OS 격리](docs/worklogs/2026-09-07-codex-os-isolation-probe.md), [CLI 사전 검사](docs/worklogs/2026-09-07-codex-01534-isolation-preflight.md) |
| OCR 이식 | 기존 Linux x86_64/GPU 운영 검증 보류는 취소된 ARM64 전환과 별개다. 동일10모델 매니페스트 package build·품질·처리시간 검증 전 기본값으로 승격하지 않는다. [재개 조건](docs/worklogs/2026-09-07-linux-ocr-native-preflight.md) |
| 품질·성능 | Q08 표 provenance/계산 위치·Q09 비교 결론, 원문 위치/선택·기록 표시, 불필요 거절·문맥 선택·새 문서 일반화·속도, 32/128 후보·목록/readiness N+1 측정. 특정 질문 예외·평가/인용 기준 완화·무한 재시도로 통과시키지 않는다. [수치/화면](docs/worklogs/2026-10-06-rag-numeric-proof-browser.md), [문맥 실험](docs/worklogs/2026-10-07-rag-context-budget-isolation-execution.md), [거절 후보](docs/worklogs/2026-09-30-rag-abstention-prompt-v5.md) |
| 관리자 이력 등록 | 원문 접근 검증 뒤 문제 등록 초안과 정확 문서 버전 연결은 당시 로그인 대기였다. 후속 DB 등록 증거 없이 완료 처리하지 않는다. [준비 자료](docs/worklogs/2026-10-04-rag-monitoring-source-access.md) |
| 과거 정리 후보 | sandbox·복구 임시물14개·Publishing 빌드3개·E5 불필요 모델 형식·기타 pytest/BuildKit 후보는 최신 소유·점유·보존 상태와 정확 승인을 재확인한다. 이번 Mypy 승인으로 합치지 않는다. [캐시 정책](CACHE_POLICY.md), [기존 정리 기록](docs/worklogs/2026-09-06-test-artifact-cleanup-audit.md) |

## 최근 완료 작업

아래는 구현·검증 완료 기록이며 전체 운영 수용을 뜻하지 않는다. 이전 누적 요약은 [보존 이력](docs/worklogs/2026-10-20-workboard-history.md)을 따른다.

1. A/D 실제 생성 비교(2026-10-20): 8회 완료·재시도0. D의 예시 조건은 부분 개선, 핵심 규칙 누락으로 정상 품질 미통과. [결과](docs/worklogs/2026-10-19-rag-relation-improvement.md#2026-10-20-실제-ad-비교-검증).
2. 인용 값 검사·배열 후보 구현(2026-10-19): 관련1,665통과/4skip·독립234통과. 서버 반영은 별도이며 실제 D 비교는 위 결과를 따른다. [구현](docs/worklogs/2026-10-19-rag-relation-improvement.md).
3. 최종 입력/답변 진단·A/B/C 비교(2026-10-19): 실제12회 모두 완료, 정상 품질0/2씩·거절2/2씩. [결과](docs/worklogs/2026-10-19-rag-v5-evaluation-preparation.md).
4. 평가 준비 모드·UI 기준(2026-10-19): 모드별 입력 보존, 공통 토큰/ChoiceGroup, 연결형 버튼과 관련156·독립13검사 통과. [모드](docs/worklogs/2026-10-19-rag-evaluation-preparation-modes.md), [스타일](docs/worklogs/2026-10-19-ui-style-foundation.md), [버튼](docs/worklogs/2026-10-19-preparation-segmented-control.md).
5. 미시작 평가 취소(2026-10-18): 소유자 pending 전용 취소·동시성 방어, 관련 backend185/UI134/PG12와 독립 검사 통과. [결과](docs/worklogs/2026-10-18-rag-pending-evaluation-cancel.md).

## 이력 보존과 정본

- 상세 구현·검증은 위 주제별 기존 worklog/spec/plan에 둔다. 새 요약을 과거 실행 증거로 바꾸지 않는다.
- 축약 전 **2,147줄 원문**은 [WORKBOARD 보존본](.local-data/project-agent-work/documentation-cleanup-20261012/WORKBOARD.before.md)에 바이트 그대로 보존했다. SHA-256: `76e32ee05bfaf1eeb4b4daacff9cdb11b659fd1f1dfb4cdf372e42e2edfb5e3d`.
- 다른 Markdown에서 못 찾은 보고서/문제 UUID7개와 일부 고유 관찰이 있어, 모든 과거 근거가 이미 worklogs로 이관됐다고 주장하지 않는다. 현재 미완료·승인 조건은 이 보드에 남기고, 나머지 고유 이력은 보존본에서 주제별 인계가 확인될 때까지 유지한다. Git에 현재 미커밋 원문이 모두 있다는 가정도 하지 않는다.
- **`documentation-cleanup-20261012`는 원문 이력·정리 복구 영수증을 포함한 보존 예외다. 작업 검증 완료만으로 전체를 자동 정리하지 않는다.** 독립된 이력 이관·복구 보존 판단이 필요하다. 이번 정리는 과거 이력의 영구 보관 체계 확정까지 완료한 것이 아니다.
- 고정 경로/SHA·역사 patch 검증 입력인 [9/20 원래 환경 인계](docs/worklogs/2026-09-20-original-environment-rag-cutover.md), [10/8 실행 복원](docs/worklogs/2026-10-08-rag-codex161-runtime-restoration.md), [9/30 별칭 복구](docs/worklogs/2026-09-30-rag-alias-recovery.md)는 원위치·원문을 보존한다.
- 프로젝트 목적·모듈 경계·실행 명령·캐시 정책은 [문서 정본 안내](docs/guidelines/codex/README.md)를 따른다. 사용자 `.idea`와 관련 없는 미커밋/미추적 변경은 정리 대상이 아니다.

## 갱신 규칙

- 시작·종료 시 현재 작업·미완료·차단·다음 작업을 갱신한다. 과거 날짜의 “현재/다음” 문단을 계속 덧붙이지 않는다.
- 최근 완료는 최대5개이며 상세는 기존 해당 주제 기록으로 연결한다. 관계없는 worklog로 옮기지 않는다.
- 코드 구현·mock/자동 검사·본래 환경 관찰·운영 활성화를 구분하고, 관찰 날짜와 미실행 검증을 명시한다.
- 링크를 옮길 때 상대 경로를 다시 검증하고, 코드/복구가 고정한 경로·바이트 계약을 먼저 확인한다.
- 새 미완료 항목은 기존 상위 범위와 중복 여부·선행 조건을 밝힌다. 승인 범위를 추측해서 확대하거나 이미 받은 승인을 취소하지 않는다.
