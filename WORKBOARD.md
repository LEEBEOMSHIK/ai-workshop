# Workboard

> 완료(2026-11-06): [학습 카드 전체 이동](docs/worklogs/2026-11-06-learning-card-navigation.md). 카드 전체 상세 링크·hover·키보드 포커스와 메모/실험 용도 안내를 적용했다. 회귀35건·독립31건·타입·린트 및 본래 비제목 클릭·Tab/Enter·두테마·375/320px·두 작성폼 확인 완료. 저장/API/모델 변경 없음. 사용자가 2026-11-06 다른 세션 작업까지 포함한 커밋·push를 재승인해 Rust 검토 문서와 함께 인계한다.

> Git 인계 검증 완료(2026-11-05): 공통 UI·테마·RAG 대화·학습 기록과 공개 합성 실험 자료를 선별했다. 프론트엔드 195개 파일의 1,477개 테스트, Node 17개, 학습 백엔드 84개·DB 통합 7개와 0069 migration 검증, 타입·린트·독립 리뷰 및 프로덕션 빌드를 통과했다. 빌드에서 확인한 두 페이지의 Next props 선언도 수정했다. 별도 Rust 조사와 사용자 참고 이미지는 로컬 보존하며 `.env`·DB·모델·캐시는 제외한다.

> 완료(2026-11-05): [학습 목록 페이지당 표시](docs/worklogs/2026-11-05-learning-page-size.md). 5·10·20개 선택과 기본5개를 적용했다. 개수 변경 시 첫 페이지로 돌아가며 다른 필터·정렬은 유지한다. 관련30건·독립9건·타입·린트, 본래 선택·필터 유지·두 테마·375/320px 확인 및 ISSUE-00051 이력 저장 완료.

> 완료(2026-11-05): [학습 목록 기술 주제 표시](docs/worklogs/2026-11-05-learning-category.md). 제목 아래 공통 분류 배지·라벨을 배치하고 디자인 시스템 예시를 추가했다. 관련 19건·타입·린트·독립 10건, 본래 두 테마·375/320px 검증 완료. 한 열·페이지 기본20개·현재4개와 정렬·학습 데이터 유지. ISSUE-00051 진행 이력 저장 확인.

> 완료(2026-11-05): [학습 출발점·개선 결과와 최신순](docs/worklogs/2026-11-05-learning-lineage.md). 원본→1차→2차→3차 어댑터 계승 근거와 차수별 목표·결과·남은 문제를 저장하고 최신 3차부터 표시했다. 기존 본문·평가 보존, 백엔드 84+2건·프론트80건·타입·린트·독립 검토와 본래 화면 재조회·모바일·테마·키보드 확인 완료. 재학습 없음.

> 완료(2026-11-05): [학습 실행 순서 표시](docs/worklogs/2026-11-05-learning-sequence.md). 실제 실행 3건의 1·2·3차와 실행일을 목록·상세에 표시하고 후속 계획을 미실행으로 분리했다. 본래 환경 저장·재조회, 정렬·필터, 두 테마·375/320px·키보드를 확인했다. 백엔드 73건·프론트엔드 47건·타입·린트와 독립 검토 통과. 재학습은 수행하지 않았다.

> 완료(2026-11-05): [실패 사례 추가 학습](docs/worklogs/2026-11-05-gemma-failure-driven-training.md). 번호·인용 지시가 있어도 실패한 4개 중 고정 정책으로 3개를 골라 12회 학습했다. 학습 문항 개선 1/3, 미사용 질문 의미·완전성 개선 0/7, 기존 회귀 정답 유지 2/2이며 미사용 한 답변의 [e4] 번호가 소실됐다. 독립 검증과 기존 환경 학습 기록 저장·새로고침 확인 완료. 서비스 모델·검색 색인·DB 구조는 변경하지 않았다.


> 2026-11-04 [백엔드 Rust 이식 비용·실부하 메모리 계측](docs/worklogs/2026-11-04-rust-backend-feasibility.md). 공개 TXT 8/32청크 처리의 워커 최고 상주량은 1,301/1,309 MiB로, 증가는 E5 준비·연산에 집중됐다. 본래 동시 대화와 별도로 측정한 결과이며 색인 쓰기 동결은 유지했다. ES 컨테이너 1.523 GiB에는 1 GiB 고정 JVM 힙 설정이 포함된다. Rust 전환·DB 교체는 미적용이다.

> 2026-11-04 Git 인계 범위는 벡터 저장소 오프라인 비교 도구, 공개 합성 입력, 회귀 테스트와 후보 조사 문서 등 23개 파일이다. 회귀 테스트 109개와 Ruff 검사, 문서 9개의 로컬 링크 188개를 확인했다. 실제 엔진 비교는 후속 작업이다.

> 비교 조사 완료(2026-11-01): **Qdrant·Milvus·Weaviate·Chroma의 프로젝트 적합성**을 공식 문서/고정 버전 소스와 기존 환경 관측으로 비교했다. 현재 ES 유지, 전용 DB 첫 실측 Qdrant·다음 Weaviate 권고이며 품질·속도·RAM 우열은 미측정이다. Chroma local은 후속 ANN, Milvus Standalone은 현 자원 제약에서 후순위로 판단하고 Lite를 구분했다. 독립 검토 차단0·문서3개/로컬 링크102개·최근 완료5개·보존17파일 검사 통과. 설치·적용·설정 변경·엔진/모델 호출0. [비교 보고서](docs/worklogs/2026-11-01-vector-store-candidate-comparison.md).

> 오프라인 준비 완료(2026-11-01): **ES·pgvector·Qdrant 비교 기준/도구**. 본래 메타데이터 읽기 조사, 후보 선정, 공개 합성 snapshot·exact 요청·반복 계획·검색 품질/시간/자원 관측 분석 CLI를 구현했다. 회귀109·독립91·strict Mypy7소스·Ruff·CLI 왕복·문서 검증 통과. 기존 `.env`/Compose/런타임 설정 해시 보존·제품 DB/ES쓰기0·모델0·설치0. 실제 세 엔진 비교/원래 자료 export/응답 변환·자원 자동 수집은 미실행·미구현이다. 다음은 메모리/아키텍처/pgvector 배포·승인 자료·실행기 계획 확정이다. [결과와 한계](docs/worklogs/2026-11-01-vector-store-comparison-preparation.md), [사용 방법](docs/runbooks/vector-store-comparison.md). 장시간 색인·복구 검증은 보류 유지.

> 정리 완료(2026-11-01): 사용자 요청에 따라 중단한 색인·복구 안전장치 회귀 검사를 **보류·자동 재개 안 함**으로 분리했다. 원래 계획과 최신 SDK 기록을 대조한 다음 작업은 **벡터 저장소 비교 준비**다. 추가 조회 최적화를 다음 필수 작업으로 올리지 않는다. 문서 독립 검토·링크/공백·최근 완료5개 검사를 확인했으며, 이번 범위는 문서 상태 정리뿐이다. 코드·서비스·DB 변경과 모델/장시간 검사·벡터 비교 실행은 없다.

> 인계 완료(2026-10-31): **누적 변경538개 커밋·푸시 완료(`b70869b`)**. 백엔드 회귀1843·strict타입527소스, 프론트1415개/188파일·Node17개·타입/린트·OpenAPI와 독립 검토를 확인했다. Node 수집 오류와 타입 변수 충돌을 수정했고, 장시간 색인 묶음은 미완료로 구분했다. 승인 캐시4곳166파일(논리386.60MiB) 삭제, 새 검증 캐시 압축·원문해시 보존. 사용자 이미지·환경/DB/모델·미해결 진단·ASA 유지, 모델0. `b70869b`의 본래 main·원격 origin/main SHA 일치를 10/31 최종 확인했다. [범위·검증·한계](docs/worklogs/2026-10-31-git-handoff.md).

> 진단·기록 완료 / 개선 미해결(2026-10-31): **ISSUE49 Windows 메모리 점유**. nonpaged pool 약11.84GiB 중 VAD3태그 약9.76GiB 확인, 관리자538개 프로세스 조회·25.45초 커널 추적/손실0·독립 decoder13개 검증. 전체 누적 원인·단일 드라이버는 미확정. 별도20초 관측에서 ASA PostgreSQL 자식102개와 두 작업 프로세스의 새 DB 연결 반복 코드를 확인했다. **사용자 지시: ASA는 유지하고 조사 결과만 기록**. ASA/Windows/제품 동작 변경0, 원래 API/프론트 유지·제품1013소스/.env 불변·모델0. 조치 전 준비6.004/5.652초·health100/100/최대39.57ms를 보존했으며 메모리 감소 조치·개선 후 비교는 미실행이다. [상세·한계·다음 조건](docs/worklogs/2026-10-31-windows-memory-investigation.md).

이전 진행 요약은 [2026-10-31 보존 기록](docs/worklogs/2026-10-31-workboard-history.md)에 두며, 최근 완료는 아래 5개 항목으로 관리한다.

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

- 디자인 시스템의 공간 유형 예시는 미선택으로 시작하고 선택한 행만 강조한다. 공통 펼침과 사용 코드는 회전 화살표를, PDF·공개 연구 목록의 페이지 이동은 이전·다음 아이콘을 사용한다. 기존 Chrome에서 선택 후 다시 열기, 키보드 펼침과 다음 이동을 확인했다. 관련 회귀 36건과 타입 검사 통과(카탈로그 4건 단독 재실행).

- SelectField 팝업을 남색 표면과 보라색 선택 행으로 통일하고 150ms 열림·닫힘 전환과 화살표 회전을 적용했다. 기존 Chrome에서 열림 시 180도, Esc 취소 및 Enter 선택 후 닫힘과 값 처리를 확인했다.

- 공통 SelectField의 단일 선택 목록에 아이콘과 연보라색 선택 행을 적용했다. 기존 Chrome의 디자인 시스템 화면에서 선택 행의 배경과 아이콘, 방향키·Enter로 값 변경을 확인했다.

- 디자인 시스템을 4개 분류·10종 공통 컴포넌트 카탈로그로 개편했다. 각 카드에 실제 미리보기·사용처·import 경로·JSX를 제공한다. 공간/기록 폼, 문제 이력·실행 모니터링, PDF 뷰어·공개 연구 관리에 적용했다. 카탈로그 4건 및 실사용처 회귀, 타입 검사·린트 통과. 기존 Chrome에서 사용 코드와 Enter로 상세 열기를 확인했다.

- 작업소 사이드바·모바일 메뉴에서 중복된 ‘비공개 작업소’ 펼침 단계를 제거했다. 브랜드 다음 Tab으로 파일함에 도달하는 키보드 검사 포함 탐색 회귀 69건 통과.

- 현재 메뉴는 8px 시안색 점과 강조 텍스트로 표시한다. 데스크톱·320px 모바일에서 다른 항목으로 포커스를 옮겨도 표시가 유지되는지 검사했고, 기존 RAG 대화의 접힌 메뉴에서도 점을 확인했다.

- 공통 메뉴의 현재 위치를 밝은 굵은 글자로 표시하고 링크 화살표를 제거했다. 기존 로컬 앱의 Chrome에서 평상시 투명 배경·그림자 없음·굵기 700, 마우스 오버의 배경, 키보드 포커스의 외곽선을 확인했다.

- 메뉴 로고를 28px에서 40px로 확대했다. 로컬 Chrome에서 320px 화면의 닫기 버튼과 겹치지 않고 192px 사이드바에서도 브랜드가 들어가는 것을 확인했다.

- 파비콘만 원본 심볼 외곽에 맞춰 잘랐다. 16px 축소 시 불투명도 50% 이상인 영역의 너비·높이가 14×13px에서 16×16px로 늘어난 것을 확인했다.

- 2026-11-04: 제공받은 PNG를 공통 메뉴의 브랜드 심볼과 48px 파비콘에 적용했다. 기존 로컬 앱에서 두 이미지 응답(200, image/png)과 페이지의 파비콘 연결을 확인했다.

- 마지막 갱신일: 2026-10-26
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

**2026-11-04 현재 우선순위는 로컬 Gemma 파인튜닝 준비다.** 백엔드 Rust 이식과 벡터 DB 교체·후보 엔진 실측은 보류한다. 준비 도구와 기존 측정 기록은 보존하고 재개는 별도 결정한다. [학습 장치 확인](docs/worklogs/2026-11-04-gemma-local-training.md) · [Rust 실측](docs/worklogs/2026-11-04-rust-backend-feasibility.md).

원래 등록 순서는 **Agents SDK → 벡터 저장소 비교 → 로컬 LLM 파인튜닝 → Kubernetes**다. [벡터 저장소·파인튜닝 계획](docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md#순서와-공통-경계), [Kubernetes 계획](docs/superpowers/plans/2026-10-08-kubernetes-learning.md#순서와-학습-방식)을 따른다. 프로젝트의 진행 순서이며 앞 단계의 모든 추가 품질 개선이 뒤 단계 준비의 기술적 선행 조건이라는 뜻은 아니다.

| 순서 | 작업과 현재 상태 |
|---|---|
| 1. Agents SDK | 실행·모니터링·문맥/턴 연결을 구현했고, 실제 근거 담당→답변 담당 단일 handoff를 두 반복에서 확인했다. 고정 평가의 history 생략·저장 완료·화면 복귀·원문 열기도 후속 실제 실행에서 확인했다. 기존 Gemma 의미 품질 문제, 검토 역할 방문·왕복 재위임 미관측, 후보 일반 기본값 비승격은 별도로 남는다. 전체 SDK 품질·운영 활성화 완료로 확대하지 않는다. [위임 검증](docs/worklogs/2026-10-27-delegation-rejection-verification.md#진행-기록), [관측 보완](docs/worklogs/2026-10-30-sdk-history-observation.md), [실제 생략·복귀 확인](docs/worklogs/2026-10-30-terra-gemma-new-question.md#이전-대화-단계와-화면-복귀) |
| **2. 벡터 저장소 비교·교체 — 보류** | Elasticsearch·pgvector·Qdrant 후보의 동일 입력/권한 fixture/BM25·RRF 계획과 exact 요청·검색 품질/시간/자원 분석을 구현했다. 회귀109·독립91·타입/린트 통과. 현재 PG에 vector 확장 없음, 여유 RAM1.5~1.9GiB, AMD64 방침/실제 ARM64 차이를 배포안에서 해소해야 한다. 설치·실제 corpus/질문 벡터 export·실행기/자원 수집·실평가는 남는다. [준비 결과](docs/worklogs/2026-11-01-vector-store-comparison-preparation.md), [실행 전 조건](docs/runbooks/vector-store-comparison.md#실제-비교를-시작하기-전) |
| 3. 로컬 Gemma 파인튜닝 준비 — 실제 CPU 1스텝 통과 | 공식 E2B-IT, 52토큰에서 rank 4 LoRA 35층 갱신·저장·재로딩 성공. 학습 670.20초, 최고 상주 5.09 GiB, 시스템 최소 가용 1.17 GiB. [학습 내용 v1 계획](http://127.0.0.1:5173/workshop/learning/7bbf3d1d-4c4f-42de-a840-a42f6bbd1550)을 등록했다. 다음은 학습용 문서군 2개·12문항의 정답·인용 검수이며 이후 미사용 평가 세트 고정과 장치 비교를 진행한다. [실측·판정](docs/worklogs/2026-11-04-gemma-local-training.md#실제-e2b-it-cpu-한-스텝) · [직접 질문·학습 실행](docs/worklogs/2026-11-04-gemma-local-training.md#이-pc에서-직접-실행) · [비공개 실험 기록](http://127.0.0.1:5173/workshop/learning/24d9b8f7-3b09-4e85-ba61-875a0b9684e7) |
| 4. Kubernetes | 현재 장치·Docker·OS·자원·본래 자료 연결을 확인한 뒤 배포/통신→설정/권한→복구→확장/업데이트→영속 저장소→Compose 비교를 진행한다. 개념 정리는 병행 가능하며 설치·새 DB/계정·이관·서버 전환은 미착수다. [계획](docs/superpowers/plans/2026-10-08-kubernetes-learning.md) |

벡터 저장소 비교를 다시 시작하기로 결정하면 아래 순서를 사용한다.

1. Qdrant·pgvector의 플랫폼별 digest/호환 배포·자원 예산·신규 산출물 위치/소유/보존과 복구안을 확정한다. 기존 PG 이미지/볼륨을 자동 교체하지 않는다.
2. 승인 corpus·기존 문서/질문 벡터 전수 parity·현재 ACL·원문 추적·청크 정답을 준비한다. 기존22벡터와38개 evidence 평가 사례를 대규모/권한 부정 검증 완료로 취급하지 않는다.
3. 실제 요청 실행/응답 변환·자원 수집을 준비하고 설치/쓰기가 필요한 구체적 범위를 확정한 뒤 exact 동등성→ANN 비교 순으로 실측한다. 현재 CLI는 오프라인 준비/수입 분석만 수행한다. [ADR-0055](docs/decisions/0055-vector-store-comparison-preparation.md).

**보존 경계:** 기존 DB·계정·문서·기본 모델·활성 검색 연결을 유지한다. 후보 평가만으로 운영 검색을 자동 전환하거나 저장 정본을 이관하거나 ES를 제거하지 않으며, 채택·전환은 별도 단계에서 판단한다. 새 ES 쓰기가 필요한 검증은 기존 **ISSUE-00013 종료 게이트**를 충족해야 한다. 이 쓰기 조건을 읽기 전용 조사·설계 전체의 차단 조건으로 확대하지 않으며, 장시간 회귀 검증 보류가 운영 보호 조건을 해제하지도 않는다.

### 완료된 최근 보완과 별도 후속

- Gemma 첫 실제 LLM 연결은 [사용자 완료 기준](docs/worklogs/2026-10-22-rag-first-llm-milestone.md)으로 마감했고, 일반 대화 연결4의 [백그라운드 처리·복귀 실제 수용](docs/worklogs/2026-10-26-conversation-live-connection.md)도 완료했다. 기존 답변 품질 한계는 유지한다. 과거 취소·색인 별칭·첨부·native 복구는 별도 보류 범위이며 자동 재개하거나 다음 계획의 필수 선행 조건으로 되돌리지 않는다.
- 백엔드 요청 차단 방지·DB 연결 재사용·조회 일괄화는 본래 전후 비교까지 완료했다. 남은 setup-options 중복 요청·준비 조회 비용은 추가 최적화 후보이며 현재 다음 필수 작업이 아니다. [ISSUE48 결과](docs/worklogs/2026-10-31-backend-response-improvements.md).
- 관리자 모델 연결·RAG 설정 통합과 Claude 연결 코드는 본래 반영했다. Claude 키/서버 참조·실제 평가·활성화, OpenAI 요청 파라미터 호환성 ISSUE47은 관련 공급자를 실제 적용할 때 확인할 별도 후속이다. [통합 설정](docs/worklogs/2026-10-30-admin-model-setup.md), [Claude](docs/worklogs/2026-10-31-claude-admin-workflows.md).
- Terra/Gemma 새 질문 비교와 history 생략 화면 확인은 2026-10-30에 완료했다. 원문 정의 기반 영업일 인용 보완도 별도로 완료했으며 Gemma 의미 오류까지 해결한 것은 아니다. 과거의 “비교 준비/호출0/첫 위임 실패” 메모로 완료한 검증을 자동 반복하지 않는다. [비교](docs/worklogs/2026-10-30-terra-gemma-new-question.md), [인용 보완](docs/worklogs/2026-10-30-relative-day-citation.md).
- 기존 OpenAI 비교의 실제 청구 집계 대조, 추가 로컬 런타임 속도 실험·품질 보강은 별도 후속으로 유지한다. 소진·종료된 모델 호출 범위를 재사용하지 않는다. [OpenAI 비교·비용](docs/worklogs/2026-10-29-openai-gemma-comparison.md), [로컬 진단](docs/worklogs/2026-10-29-gemma-timeout-observation.md).
- [84일 학습 문서8개](docs/learning/2026-10-12-ai-engineering-84-days/README.md)는 준비 산출물이며 실제 학습 진도와 다르다. 이번 정리에서 교재·사용량 알림 예약을 변경하지 않는다.

이 절의 정리 전 상태는 커밋 `b70869b`의 WORKBOARD와 각 주제의 worklog에 보존된다. 날짜별 과거 “다음” 표현을 현재 착수 지시로 취급하지 않는다.

## 승인과 보존 경계

- 2026-10-29 OpenAI 비교 범위 종료: 사용자 후속지시로 Pro API 혜택을 현재Personal조직에 연결해USD46.00을 확인하고, 공개합성질문/28근거의 OpenAI2+기존Gemma2회·retry0을 완료했다. 예상OpenAI총액USD0.000667/상한0.05, 미확인호출0·잔여금액자동사용0. 별도Git제외키/설정/ledger사용·기존.env/기본값/서비스/제품DB보존. 결제수단/자동충전변경0이며 실제차감은대시보드No data로미확인이다.

- 2026-10-29 새 단일진단 범위 종료: `gemma-timeout-observation-one-v1` 사용자명시승인1/사용1/잔여0·360초timeout·retry0·미채택. 새승인/78행ledger/종료기록을 보존한다. 후보회수·본래권한/28근거/입력/전체모델/.env/기존25파일보존 확인, DB쓰기0. 이전미사용3회와 이번범위를 재사용하지 않는다.

- 2026-10-28 서명 ARM 비교 범위 종료: 사용자 새승인 최대4회 중 후보1회가360초 시간초과, 기준0·잔여3미사용·재시도0. `approved-comparison.json`/실패ledger/`scope-closure.json`을 보존하며 범위를 재사용하지 않는다. 후보 회수·기존 환경 보존 확인, 제품/기본값/기존서비스/DB쓰기 변경0. 비교·품질은 미완료이며 후보는 미채택한다.

- 2026-10-28 장치·스레드 실측 범위 종료: 기존 설정2회+명시6스레드2회, 총4/4회·재시도0. 첫1회 계측 불완전 기록을 유지하고 기존 ledger SHA에 결합한 남은3회만 별도 실행했다. 유효3개 답변·인용 동일, 첫1개 품질 미확인. 추가 호출·기본 승격·DB쓰기·서비스재시작0이며 이번 호출 범위를 재사용하지 않는다.

- 2026-10-27 새 실측 범위 종료: 기존 후속 최대2회와 비기본 자율 후보 최대4회, 합계6회·retry0 승인. 실제 후속2+자율2=4회 사용·예정 두 반복 종료·잔여2미사용이며 자동 재시도하지 않는다. 실패 후 오프라인 보강/기존DB rollback/유휴 본래API 반영은 완료했고, 수정본 자율 경로의 실제 수용은 별도 후속이다.

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
| **보류: 색인·복구 안전장치 회귀 검증** | **2026-11-01 사용자 지시로 보류·자동 재개 안 함.** 10/31 커밋 검증 중 실행한 17파일 묶음으로, 697.45초 후 중단했다. 부분 출력800통과·13건너뜀·실패 표시0이며 최종 요약/JUnit이 없어 전체 통과가 아니다. 실제 재색인·모델 호출은 없었다. 현재 일반 대화·응답성 개선 완료나 다음 벡터 저장소 비교의 읽기·설계 준비를 막는 필수 작업으로 연결하지 않는다. 해당 native 색인·복구 경로 변경/운영 적용을 다시 검토할 때 검사 범위·장시간 원인을 확인하고 명시적으로 재개한다. 기존 운영 쓰기 게이트는 유지한다. [중단 범위·증거](docs/worklogs/2026-10-31-git-handoff.md#검증) |
| 추가 조회 최적화 | setup-options 중복 호출과 남은 준비 조회 비용은 측정 후보로만 보존한다. 이번 사용자 요청에서 원래 계획 작업보다 앞선 필수 보완으로 두지 않는다. [후보·한계](docs/worklogs/2026-10-31-backend-response-improvements.md#한계와-다음-순서) |
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

1. 2026-11-05 ISSUE-00040. 계정·테마 설정 통합 후 라이트 모드로 본래 앱 31개 경로를 점검했다. 공개 연구실 안내·원문 설명·비활성 버튼의 글자 대비와 대화/옵션 선택 표식을 보완했다. 공개 화면 37개 상태의 배경 표본 7,086개와 두 테마 토큰 대비, 버튼 브라우저 회귀가 통과했다. [측정 방법과 실화면 범위](docs/guidelines/design-system-coverage.md)

2. 2026-11-05 ISSUE-00051. 학습 기록 상세에서 실험 상태·목적·한계·기준 목록·예시를 구분했다. 기존 Chrome에서 데스크톱·375px 제목과 번호 정렬, 본문 보존을 확인했다. 후속 변경으로 열어 본 버전의 분류를 제목 아래로 옮기고 단일 항목은 문단, 복수 항목은 목록으로 표시했다. 실제 기록 상단 분류·단일 비교 구성·다음 작업 확인. 읽기·편집·버전 관련 테스트 24개, 타입 및 변경 코드 린트 통과.

   학습 흐름·차수·실행일을 선택 정보로 추가하고 서버 전체 정렬·페이지 커서를 연결했다. 실제 실행 1→2→3차와 미실행 후속 계획을 분리하고 저장 본문을 보존했다. 백엔드 73건·프론트엔드 47건·타입·린트·독립 검토, 본래 화면의 정렬·필터·모바일·테마·키보드 확인 완료. [구현과 검증](docs/worklogs/2026-11-05-learning-sequence.md).
   후속으로 원본 시작/이어 학습/미확인과 개선 목표·실제 결과·남은 문제를 명시하고 기본을 흐름별 최신순으로 바꿨다. 실제 어댑터 계승을 확인해 기존 기록에 저장했으며 성과를 과장하지 않았다. 백엔드84+2·프론트80·타입·린트·독립 검토, 본래 저장·재조회·375/320px·두 테마·키보드 펼침 통과. [계승과 결과 표시](docs/worklogs/2026-11-05-learning-lineage.md).

   2026-11-05 후속: 실패 3개로 12회 추가 학습한 실제 결과를 기존 학습 기록에 저장했다. 미사용 7문항의 의미·완전성 개선은 없었다. 실험에서 발견한 묶음 인용 표시 오류를 수정하고 관련 44건·타입·린트, 독립 16건과 저장된 실제 화면을 확인했다. 상세 결과·한계는 [실행 기록](docs/worklogs/2026-11-05-gemma-failure-driven-training.md)을 따른다.
   제목 아래 분류와 상태는 작은 보조 텍스트로 표시한다. 0069 이관으로 기존 학습 기록의 이전 본문 6건을 삭제하고 최신 2건의 내용과 메타데이터 해시 보존을 확인했다. 새 저장도 현재 본문만 보존한다. 1600px·375px 실제 상세에서 버전 선택·번호 제거와 가로 넘침 없음을 확인했다.
   읽기·편집 명칭을 ‘평가 범위와 한계’로 맞췄다. 실제 기록에서 실험 방법 직후에 일반 섹션으로 표시되며 경고 배경·아이콘이 없음을 확인했다.
   실제 수행 기록은 목적·학습 방법(입력, 정답, 어댑터 갱신)·동일 질문의 전후 답변 비교 순서다. 파일 식별값과 실행 환경은 하단에서 펼친다. 로그인한 본래 작업소에서 이관 후 현재 학습 방법과 비교표를 재확인했다. 프론트 학습 회귀 44개 및 타입·린트 통과.
   입력·정답·학습 라벨과 번호를 본문과 구분했다. 실제 기록에서 1600px 두 열·375px 한 열 정렬, 본문 렌더링 회귀 4개, 타입·린트 통과.
   단계가 확인되는 학습 본문은 입력 규정·질문, 기대 응답·근거, 학습 절차·대상을 세 카드에 표시한다. 1600px·853px 3열 및 375px 세로, 넘침 없음과 라이트·다크 테마, 키보드 원문 열기·닫기를 실제 기록에서 확인했다. 다른 규정과 인용, 반복 횟수 및 자유 본문을 포함한 관련 회귀 25개·타입·린트·운영 빌드 통과.
   학습 전후 답변의 변화 여부와 정답 기준 인용 누락을 비교표에 표시했다. 본래 기록의 ‘변화 없음’, ‘근거 인용 누락’, 전후 두 행의 ‘[e1] 누락’ 및 375px 가로 넘침 없음을 확인했다.
   전후 비교를 결과 요약·질문·기준/전/후 카드·변화 요약·실험 결론으로 구성했다. 명시적 의미 평가와 인용 번호 변화를 구분하고 평가 조건과 학습 설정을 실험 방법에 표시한다. 실제 기록의 2160px 2열·768/375px 세로, 두 테마, 가로 넘침 없음, 실행 환경 키보드 열기·닫기, 기본 운영 빌드를 확인했다.
   후속으로 변화 요약 패널과 중복 지표를 제거하고 전체 폭 답변 카드를 확인했다. 관련 테스트 32개와 타입·린트 통과. 공개 합성 2개 예제로 기존 어댑터에서 실제 4회 추가 학습하고 동일 입력의 전후 답변 3쌍을 확인했다. 기존 어댑터도 번호와 지시를 받으면 올바르게 답했고 추가 학습 이득은 관찰되지 않았다. [방법과 결과](docs/worklogs/2026-11-04-gemma-local-training.md#후속-비교-기준).

3. 2026-11-04 ISSUE-00050. RAG 대화 전용 전역 메뉴 축소, 세션 목록 토글, 세션 간 입력·읽기 위치 복원. 기존 작업소 Chrome에서 저장 대화 전환과 PDF 인용 원문 열기를 확인했다. 작성 아이콘이 있는 새 대화 버튼을 목록 상단에 고정하고 동명의 저장 세션을 구분했다. 목록 처음·끝에서 버튼의 상대 위치 12px, 목록 접기 후 헤더 버튼 표시를 확인했다. 11월 4일 후속으로 저장된 전역 메뉴 폭에 관계없이 대화에서는 64px 레일을 적용하고 본문 관리 행을 활성 세션 목록으로 옮겼다. 공통 사각 링크 장식을 정리하고 기존 Chrome에서 메뉴·근거 링크 44px를 확인했다. 최근 대화는 한 줄로 표시하고 떠 있는 관리 메뉴로 변경했다. 선택·상태 조회로 변경 시각이 그대로면 목록 순서를 보존한다. 새 대화 세 번·미전송 입력·새로고침 전후 목록 12개 유지, 관리 메뉴 전후 12개 행과 생성 버튼 좌표 동일, 백엔드 첫 질문 회귀 26건 통과. 실제 모델 신규 호출은 미실행.

4. [벡터 저장소 오프라인 비교 준비](docs/worklogs/2026-11-01-vector-store-comparison-preparation.md)(2026-11-01): ES·pgvector·Qdrant 선정/환경 조사·snapshot/exact 요청/일정/검색 품질·시간·자원 분석 CLI. 회귀109·독립91·strict7·린트·CLI 왕복 통과. 후속 [전용 네 후보 비교 조사](docs/worklogs/2026-11-01-vector-store-candidate-comparison.md)는 Qdrant 첫 실측·Weaviate 다음 후보를 권고하며 성능 우열은 미측정. 기존 설정/자료/모델 유지, 설치·실검색0. 실측용 배포·원래 자료·실행기·자원 수집은 후속.

5. [누적 변경 정리·Git 인계](docs/worklogs/2026-10-31-git-handoff.md)(2026-10-31): 538개 명시 선별, 회귀1843·타입527소스·프론트1415/Node17·OpenAPI와 독립 검토. 승인 캐시4곳166파일 삭제, 이력74개 보존 이관. 장시간 색인 전체 미완료·실모델/DB쓰기0·ASA 유지. main·origin/main의 `b70869b` 일치를 확인했다.

## 이력 보존과 정본

- [백엔드 응답성 개선](docs/worklogs/2026-10-31-backend-response-improvements.md)(2026-10-31): ISSUE48. 무결성 offload·HTTP DB풀·구성 일괄조회. 동일결과 SQL340→124, 준비9.2~9.4→5.7~5.8초, 본래동시health최대1.226→0.190초. 독립36·회귀/타입/린트·실제PG·124표162099행/.env/gate보존, 본래API반영·이력저장. 모델0, 호스트nonpaged원인별도.

- [Claude 연결·고급 관리 화면 정리](docs/worklogs/2026-10-31-claude-admin-workflows.md)(2026-10-31): ISSUE46 후속. native 공급자/정책·최신순 선택·작업별 관리/초안 보존. 서버558·독립189/62·프론트139/52·타입/린트, 본래320/375px와 migration0068/API 검증. 이력 전124표162091행·설정보존, 이력저장/재조회. 키/실제 Claude 답변평가·활성화 미실행, 모델0/추가 API비용0.

- [관리자 모델 연결·RAG 설정 통합](docs/worklogs/2026-10-30-admin-model-setup.md)(2026-10-30): ISSUE46. 안전한 연결 옵션·등록·기존 구성 복사·정확 평가 수용·도메인 적용. 후속 공개 최신모델5개 콤보·고급 메뉴 구분까지 완료. 후속86/66·독립108/최종25·TS/lint·본래320/375px 통과, 실모델0·기본연결 유지. 서버 참조/실제 새 모델 평가는 별도이며 runtime 파라미터 호환 확인은 ISSUE47로 등록.

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
