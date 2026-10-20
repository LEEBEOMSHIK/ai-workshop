# 종료된 비교 이력: Windows ARM64 기능 동등성 검증표

> 현재 상태(2026-10-12): **AMD64 유지, ARM64 전환 취소 및 실험 환경 정리.**
> 사용자의 명시적 취소에 따라 아래 ARM64 전환·의존성 해결·OCR 분리 제안과 후속 검증은
> 종료된 조사 이력으로 보존하며 진행 중 계획이나 실행 승인 요청으로 취급하지 않는다.
> 기존 AMD64·Gemma 제품 코드·서비스는 유지한다. 정리 결과는 비교 작업 기록의 마지막 절을 따른다.

- 기준일: 2026-10-12
- 결론: **전체 동등성 미검증·전환 차단. 기존 AMD64 유지.**
- 범위: 현재 구현된 프론트, 비공개/공개 API, worker, 저장소 클라이언트와 전체 사용자 기능.
- 환경 구성·정확한 native 차단 증거: [ARM64 비교 작업 기록](../worklogs/2026-10-12-arm64-environment-comparison.md).
- 실행·migration 정본: [로컬 개발 실행서](local-development.md). 이 문서는 실행 절차를 대체하지 않는다.

## 판정 규칙과 비교 기준

같은 소스·패키지 계약·프로파일·공개 합성 입력을 기준으로 결과, 권한, 오류, 취소 후
종료·복구, 데이터 보존과 성능 예산을 비교한다. 기능을 제거하거나 AMD64 실행으로
대체한 결과는 전체 ARM64 성공으로 인정하지 않는다. 순수 JavaScript 코드라도 Node와
SWC/Oxc 등 native 의존성의 ARM64 실행을 별도로 확인한다.

| 표시 | 의미 |
| --- | --- |
| 단위 통과 | ARM64 인터프리터/Node에서 명시된 합성·모의 검사만 통과. API·브라우저·저장소 통합 증거가 아님 |
| 구성 확인 | 아키텍처·버전·파일/패키지 설치만 확인. 해당 기능의 실행 성공이 아님 |
| 차단 | 확인된 의존성·정책·선행 조건 때문에 해당 검증을 완료하지 못함 |
| 미검증 | 실제 실행하지 않았거나 결과를 확인하지 못함 |
| 기존 미완료 | AMD64에서도 작업 기록상 미완료. ARM64가 새로 발생시킨 회귀로 단정하지 않음 |

현재 AMD64 Node는 **24.18.0 x64**, backend는 Python 3.13.15 AMD64다. ARM64 비교용
Python은 `.local-data/venvs/ai-workshop-arm64`, 프론트는 같은 Node 버전의 공식 ARM64
ZIP과 기존 `pnpm@11.20.0`/lock을 사용한다. 프론트 소스 405개 파일을 별도 경로로
복사했으며 `.env`, 기존 `node_modules`, `.next`는 복사·수정하지 않았다. 사용자 데이터나
기존 계정을 복제한 환경이 아니다. 사본 성공만으로 본래 환경 전환을 완료 처리하지 않는다.

### AMD64에서 이미 남아 있던 작업

[2026-10-11 마감 점검](../worklogs/2026-10-11-rag-functional-closure-check.md)과
[복구 근거 조사](../worklogs/2026-10-11-rag-recovery-evidence-investigation.md)의
별칭 open/frozen·receipt 0, 개인 첨부 검색 READY, 과거 취소 요청 종료, native 복구
최종 조립·근거, 실제 첫 질문/권한 committed 경합/모델 취소 수용은 별도 미완료다.
이 수치는 **과거 조회 기록**이며 이번 작업에서 운영 DB를 재조회하지 않았다.
ISSUE-00013 open/r33 등도 과거 기록으로만 인용한다. Git 인계·mock 통과가 운영 복구
완료를 뜻하지 않는다. 학습 교재 생성과 84일 학습 진도는 기능 동등성 완료 근거가 아니다.

## 프론트·실행 기반

아래의 “근거”는 실제 구현·검사 위치다. 코드 존재만으로 통과를 뜻하지 않는다.

| ID | 구현 범위와 근거 | 현재 ARM64 증거/판정 | 완료에 필요한 검사 |
| --- | --- | --- | --- |
| F01 | Node·pnpm·Next/React 및 native 의존성 (`frontend/package.json`, lock) | Node24.18.0 `arm64`, 공식 SHA-256·OpenJS 서명 확인. lock 설치469개·pnpm 의존성/설치 정책 검사574항목 통과(Windows Code Integrity 판정 아님). **구성 확인** | Next/SWC/Oxc 실행, 기본 production build와 두 runtime 모드 |
| F02 | TS·린트·컴포넌트 (`frontend/src`, Vitest) | ARM64 TS·린트 및 144파일·968테스트 **단위 통과**, 실패/skip0 | 브라우저·실제 API 수용과 성능 비교는 별도 |
| F03 | production build, start, 라우팅·redirect·assets (`next.config.ts`, `src/app`) | 기본 ARM64 Turbopack build 시도 후 메모리 상한 아래 OOM: **자원 제한 실패**. 실서버 **미검증** | 자원 확보 후 기본 build→start→HTTP·브라우저 진입; combined/public 각각 |
| F04 | API rewrite, 오류·stream·proxy timeout, schema (`openapi-ts.config.mjs`, `shared/api`, `shared/config`) | **차단**. wrapper는 기존 `backend/.venv` 고정; ARM API 미가동 | ARM API로 export/schema 일치, 쿠키·CORS·stream·오류·취소 실제 왕복 |
| F05 | 로그인·setup·공간·파일함·관리자 탐색 (`features/identity`, `assets`, `navigation`) | **미검증** | 동일 권한의 실제 화면·폼·업로드·라우팅 수용 |
| F06 | 게임 입구·맵·캐릭터·흐름 안내 (`office-game`, `flowcharts`, `home`) | **미검증**. 별도 게임 backend router 없음 | ARM 브라우저 Phaser 렌더/입력/충돌·리사이즈·접근성·맵 상태 |
| F07 | RAG 검색·원문·대화·구성·평가·관리 화면 (`features/rag`) | 단위 결과와 통합은 분리. **실제 API 연결 미검증** | 결과·근거/원문·대화·관리 작업을 아래 backend 기능과 연결 |
| F08 | 공개 전시실·학습·문제·토폴로지·에이전트 안내 (`features` 해당 디렉터리) | **미검증** | 공개/비공개 접근 분리와 실제 UI/API 수용 |
| B01 | API import/lifespan, router, health/ready, middleware, OpenAPI (`main.py`) | **차단**: cryptography 필수 import 및 backend 의존성 미완비 | ARM API 기동·ready·전체 계약·인증/오류/audit middleware |
| B02 | Celery worker/beat·dispatch·reconcile·멱등성 (`worker.py`, `platform/jobs`) | **차단**. worker 기동·브로커 작업 미실행 | 승인된 격리 작업으로 enqueue→실행→중복/재시도/재시작 검증 |
| B03 | SQLAlchemy/psycopg/libpq·Windows event loop (`shared/db.py`, `asyncio_policy.py`) | **차단/미검증**: ARM libpq 미확인. DB 접근·migration 없음 | native client import와 승인된 DB 왕복·transaction·pool·async 정리 |
| B04 | Redis/Celery 클라이언트·ES async/TLS (`worker.py`, `indexing`, `retrieval`) | **미검증**. 실제 서버 연결 없음 | 버전·아키텍처, 접속/TLS·시간 제한·재시도·재연결·권한 처리 |
| B05 | Windows DPAPI/DACL·보호 읽기·mutex·Job·프로세스 종료 (`infrastructure/local`) | **미검증**. 기존 복구 미완료와 구분 | ARM native 호출·소유권·취소 후 실제 자식 종료, 보호 경계 유지 |
| B06 | cryptography X509·startup admission (`indexing/access_epoch_runtime.py`) | **차단**: 50.0.1/호환50.0.2 WindowsARM64 wheel 없음 | 신뢰 가능한 ARM 빌드와 X509·API/worker 경로 확인; 생략 금지 |

## 플랫폼·RAG 기능

| ID | 구현 범위와 근거 | 현재 ARM64 증거/판정 | 완료에 필요한 검사 |
| --- | --- | --- | --- |
| P01 | owner/setup·로그인·session·암호·권한 revision·마지막 master 보호 (`platform/setup`, `identity`) | **미검증** | native 암호 모듈과 API/DB·쿠키·역할·권한 철회 수용 |
| P02 | 공간 멤버십·소유권·접근 (`platform/workspaces`) | **미검증** | 조회/변경·교차 사용자 접근·현재 권한의 동등성 |
| P03 | 업로드/intake·버전·provenance·원본·폴더/이동/휴지통/purge (`platform/assets`) | **미검증** | 합성 업로드부터 검증 작업·원문 보기·권한·실패 복구까지 실제 왕복 |
| P04 | 작업 상태·정합·중복·부분 실패 (`platform/jobs`) | **미검증** | worker·저장소 연계와 취소/재시도/재시작 정합성 |
| P05 | 학습 기록 revision/archive/restore·문제 이력 (`platform/learning`, `issue_history`) | **미검증** | 승인된 데이터로 CRUD·이력·복구·접근 제어. 학습 진도 자동 완료 금지 |
| P06 | 공개 후보·검토·digest·publish/withdraw·공개 SQLite 분리 (`platform/publishing`, `public_app.py`) | **미검증** | 패키지 검증·공개 API와 private DB 미접속·철회·권한. 이번 SQLite/운영 DB 쓰기 없음 |
| P07 | 설정·runtime topology·프로젝트 에이전트 안내 (`config.py`, `platform/runtime_topology`, frontend) | **미검증** | 설정 오류·owner 접근·읽기 전용 Compose 계약·실행 주체 표시 |
| R01 | Markdown/TXT 인코딩·문단·heading·offset (`parsing/markdown.py`, `plain_text.py`) | **단위 통과**: 합성 파일 parser 검사 포함 | 업로드→worker→원문/검색 위치의 실제 왕복 |
| R02 | 텍스트 PDF·미리보기 자식 프로세스 (`parsing/pdf.py`, `infrastructure/document_formats/pdf_preview.py`) | **미검증** | ARM PyMuPDF·추출/렌더·격리 프로세스·뷰어 위치와 실패 처리 |
| R03 | DOCX 구조·이미지·뷰어 (`parsing/docx*`) | **미검증** | ARM lxml/python-docx·표/heading/이미지·원문 추적·프로파일 |
| R04 | 스캔/혼합 PDF·DOCX OCR·표/좌표/신뢰도·부분 실패 (`ocr/paddle_structure.py`, parsing) | **차단**: Paddle3.2.2 및 후보3.3.1 WindowsARM64 wheel 없음 | native 엔진과 실제 OCR 산출물·품질·오류. 선택 경로라도 기능 제외 불가 |
| R05 | 구조 청킹·문장·token budget (`chunking`) | **단위 통과**: 구조·문장 검사 포함 | 실제 tokenizer·다양한 형식·색인 버전/재처리와 연계 |
| R06 | 임베딩·cache·모델/프로파일·차원 (`embeddings`) | **차단/미검증**: sklearn 정책; 실제 모델 금지 | 승인된 모델·메모리·cache·실패·버전 호환; fake를 실모델로 인정하지 않음 |
| R07 | ingestion·handoff·projection/Asset READY·색인 버전 (`ingestion`, `indexing`) | **미검증 + 기존 미완료** | 실제 worker·ES·DB·파일 저장소의 멱등 처리와 활성화 수명주기 |
| R08 | BM25+dense+RRF·필터·선택 문서·PIT/snapshot (`retrieval`) | RRF **단위 통과**. 실제 BM25/dense 검색 **미검증** | 같은 권한·snapshot으로 순위/필터/원문·PIT/TLS 비교 |
| R09 | exact/semantic highlight·근거 예산·원문 viewer (`highlighting`, frontend sources) | highlight **단위 통과**. 화면/실검색 **미검증** | 원문 offset/bbox·권한·근거 선택·근거 부족 표시 |
| R10 | 생성 schema/인용/numeric proof·contextualization (`generation`, `search/pipeline.py`) | citation **단위 통과**. 실제 생성·numeric 연계 **미검증** | 근거 제한·잘못된 인용/수치 거부·진단·답변 품질 |
| R11 | HTTP·Codex·local providers, BF16/NF4·host (`generation`) | local mock **단위 통과**; 과거 tiny BF16/NF4 통과. Gemma native는 sklearn 정책 **차단** | provider별 실제 연결·비용/메모리·오류/timeout·출력 계약 |
| R12 | 대화·첫 질문·개인 첨부·실행 이력·취소 후 다음 질문 (`conversations`, `executions`) | **미검증 + 기존 미완료** | UI→API→실provider·worker·DB, 첫 질문/권한 경합·첨부 READY·이력 보존 |
| R13 | cancellation/timeout·부분 실패·프로세스 종료·재시도 (`generation`, `search`, indexing) | mock host 범위만 통과. **실종료/복구 미검증 + 기존 미완료** | 실제 요청·retry wait·native 작업 중 취소와 종료 증거·새 질문 |
| R14 | 별칭/access epoch·receipt/parity·native 복구 (`indexing/access_epoch*`, `alias_recovery*`) | **기존 미완료**, ARM64 **미검증** | 승인된 본래 환경의 전체 조립·서명/TLS·상태 전환·증거·복구 |
| R15 | 모델 catalog/deployment·secret·데이터 정책·프로파일/저장 구성 (`models`, `deployments`, `policies`, `configurations`) | **미검증** | 저장/검증·선택 provider 실패 시 무단 전환 없음·권한/외부 전송 제한 |
| R16 | 평가 authoring·고정 snapshot·비교·승격 (`evaluation`) | **미검증** | 동일 데이터·profile·실행환경의 측정/비교, 미평가 기본값 승격 금지 |
| R17 | 도메인·문서 연결·범위 (`domains`) | **미검증** | 연결/해제·공간/문서 이동·현재 권한·검색/대화 범위 동등성 |

경로의 `parsing`, `generation` 등 RAG 축약은 `backend/src/ai_workshop/labs/rag/`
하위, `platform`은 `backend/src/ai_workshop/platform/` 하위를 뜻한다. Agents SDK,
벡터 저장소 비교, 로컬 LLM 파인튜닝과 Kubernetes는 후속 개발이며 구현 완료 기능으로
행을 채우지 않는다. 현재 runtime registry/프로젝트 에이전트 안내 기능은 위 범위에 포함한다.

## 이번 실행 기록

- Python ARM64: 합성 Markdown/TXT, 문장·구조 청킹, RRF, 하이라이트, 인용 검증과
  local adapter/Gemma/host/error mock **126 passed, 1.55초**. 테스트 11개 파일,
  `backend-unit.xml` 보존. 실제 모델·네트워크·운영 DB를 사용하지 않았다.
- Node ARM64: 공식24.18.0 ZIP SHA-256
  `f274669adb93b1fd0fbf8f21fd078609e9dcc84333d4f2718d2dde3f9a161a01`,
  OpenJS Authenticode 유효. 기존과 같은 pnpm11.20.0 frozen-lock 설치 통과.
- 프론트 TypeScript `tsc --noEmit --pretty false --incremental false`: exit0.
- 프론트 ESLint `. --max-warnings 0`: exit0.
- 전체 Vitest: **144파일·968테스트 통과**, 실패/보류0, exit0. JSON의 219 suites는
  중첩 suite 집계이며 파일 수가 아니다. JSDOM·mock/API fake 기반으로 실제 브라우저와
  backend 연결 성공을 뜻하지 않는다. JSON 검사 구간은 약645.95초이며 전체 결과를 보존했다.
- production build·실 frontend runtime·API 통합: 성공 기록 없음. 실행 전 여유
  RAM은 1,821,272KiB(약1.74GiB); 전체 메모리 최소 요구치라는 뜻은 아니며 병행 빌드
  부하를 피하기 위해 검사 종료 후 재확인했다. 이후 여유 RAM 1,617,476KiB(약1.54GiB).
  기본 `next build`를 격리 ARM64 Node 프로세스 묶음에만 Windows Job 메모리768MiB,
  V8 old-space512MiB(`--max-old-space-size=512`)·시간300초를 설정해 1회 시도했다.
  old-space 값은 전체 Node 프로세스 메모리 상한이 아니다. 원본 Next 설정은 바꾸지 않았다.
  Next16.3.4 Turbopack이 config 로드 후 production compile에 진입했으나
  `Fatal process out of memory: Worklist::Segment::Create`로 **26.543초에 실패**했다.
  exit2147483651, Job 보고 peak917,667,840bytes. 설정 상한과 측정 peak는 구분한다.
  **자원 제한 하의 실패**이며 ARM64 고유 회귀나 충분한 자원에서의 실패로 단정하지 않는다.
  상한 증대 재시도·기존 서비스 종료는 하지 않았다. Job 종료로 이 빌드의 자식만 정리했다.
  build 산출물이 완성되지 않아 `next start`·HTTP·브라우저·API 왕복은 실행하지 않았다.
- backend 전체 startup/API export/worker/DB/Redis/ES/OCR/실모델/migration은 실행하지
  않았다. `api:check`의 기존 AMD64 Python 호출을 ARM64 검증으로 사용하지 않았다.

모든 새 산출물은 `.local-data/project-agent-work/arm64-parity-20261012/` 안에 있다.
원본 소스·lock·기존 `.next`/node_modules·공유 Python/Node·전역 PATH·서비스·DB는
변경하지 않았다. 설치 도구의 ARM64 선택을 위한 PATH 변경은 해당 자식 프로세스에만
적용했다. 새 소스 복사본은 검증 대상일 뿐 운영 전환이나 별도 계정/DB가 아니다.

## 안전한 진행 순서와 종료 조건

1. 기존 AMD64를 유지하고 현재 정책 차단 파일·공식 wheel 해시·Code Integrity 증거를
   정책 담당자의 정상 신뢰 판단 절차로 처리한다. 정책 우회·의존성 숨기기는 하지 않는다.
2. 신뢰 가능한 Windows ARM64 cryptography 빌드와 libpq/전체 backend 의존성을 확보한다.
   Paddle native OCR의 지원 경로도 해결한다. Windows ARM64 wheel이 없는 패키지는
   반복 설치로 해결하지 않는다. ARM/AMD 혼용을 설계하더라도 전체 ARM 전환과 구분한다.
3. 자원이 확보된 격리 환경에서 프론트 기본 build/start·공개/비공개 모드를 확인하고,
   ARM API export/schema·backend/worker startup 및 native Windows 제어를 검증한다.
4. 별도 승인과 보존 기준 아래 DB/Redis/ES·파일·실모델·브라우저 수용을 연결한다.
   같은 합성 입력으로 전체 표를 실행하고, 운영 기존 미완료와 이식 회귀를 따로 기록한다.
5. 전 행의 필수 동작·권한·오류·취소·복구와 성능 예산이 증명된 뒤에만 본래 실행 경로
   전환을 계획한다. 전환/rollback/데이터·프로세스 보존 확인 전 AMD64를 제거하지 않는다.

정상 전환 완료는 단위 통과율이 아니라 위 표의 통합 증거와 안전한 실행 인계로 판정한다.
운영 문제 이력 DB는 이번 권한 범위에서 갱신하지 않았으며 문서 기록만 완료한다.
