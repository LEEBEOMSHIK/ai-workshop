# Python 백엔드의 Rust 이식 비용과 메모리 효과

2026-11-04 기준 `f628bc7`에서 조사했다. **메모리 절약을 이유로 한 전면 이식은 현재 우선순위가 낮다.** Python 앱 조립 자체에 드는 메모리는 관측했으며, 같은 기능을 구현한 Rust 버전과의 차이는 아직 미측정이다. 초기 조사는 운영 소스·설정·DB·모델의 변경 없이 코드 집계, Windows 관측, 같은 Python 환경의 앱 import 비교만 수행했다. 후속 실제 부하 계측과 본래 계정의 대화 실행·결과 저장은 아래에 별도로 기록했다.

## 실제로 확인한 메모리

| 대상과 측정 시점 | 상주 메모리(working set) | 전용 커밋(private commit) |
|---|---:|---:|
| 11/04 새 Python 프로세스, 계측용 표준 라이브러리까지 | 27.57 / 27.62 MiB | 17.30 / 17.36 MiB |
| 같은 두 프로세스에서 FastAPI import 직후 | 55.32 / 55.02 MiB | 39.73 / 39.45 MiB |
| 같은 두 프로세스에서 `ai_workshop.main:app` import 직후 | 248.32 / 247.77 MiB | 227.83 / 227.46 MiB |
| 10/31 기존 운영 API 한 시점 | 16.10 MiB | 255.49 MiB |
| 10/28 별도 Gemma runner, 자동 설정 실행 중 관측 최대 | 3.62 GiB | 5.86 GiB |

11/04 17:09 KST에 포트 18000 리스너와 이 프로젝트의 실행 중인 API·워커를 식별하지 못했다. 호스트 가용 메모리는 약 6.12~6.20 GiB, 커널 비페이지 풀은 약 1.66 GiB였다. 이 초기 조사 시점에는 워커의 작업 중 최고 사용량을 확인하지 못했다. 위 첫 세 행은 기존 Conda 환경의 새 프로세스를 순차로 두 번 실행해 Windows `GetProcessMemoryInfo`로 읽은 값이다. 서버 수신·lifespan·DB·사용자 요청을 실행하지 않았으며, torch·paddle·sentence_transformers·transformers가 로드되지 않은 것도 확인했다. 진단의 최초 시도는 Python 표준 라이브러리의 Windows 버전 조회(`ver`)를 제약해 중단됐다. 최종 두 표본에서는 이 명령만 자식 프로세스로 허용했다. 측정 원본은 로컬 작업 기록 `rust-backend-feasibility-20261104/python-import-samples.json`에 있다.

약 248 MiB에는 라이브러리·애플리케이션·공유 페이지가 포함된다. 전용 커밋은 프로세스를 위해 OS가 확보한 가상 메모리이고 상주량은 측정 순간 RAM에 있는 페이지다. 메모리 압박이 컸던 10/31의 16 MiB와 새로 import한 11/04의 248 MiB는 각각 다른 상태를 보여준다. 차액은 Rust 절감량이 아니다. 10/31의 프로젝트 약 991 MiB 전용 커밋에는 프론트엔드도 포함됐다. 당시 Elasticsearch는 컨테이너 지표로 약 1.61 GiB였다. 날짜·측정 범위가 다른 값을 합산하지 않는다. [기존 호스트 조사](2026-10-31-windows-memory-investigation.md), [Gemma 실행 중 측정](2026-10-28-gemma-runtime-prefill-diagnosis.md), [Windows 상주량](https://learn.microsoft.com/en-us/windows/win32/memory/working-set), [전용 커밋](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex).

## 기대할 수 있는 변화

- Python 프로세스를 실제로 대체하면 인터프리터·로드된 Python 모듈과 객체의 고정 비용을 줄일 여지가 있다. Rust의 소유권과 빌린 참조를 활용해 큰 버퍼의 복제와 임시 객체 수를 줄이면 해당 작업의 최고 메모리와 CPU 시간도 줄 수 있다. 반대로 HTTP 앞단만 추가하고 기존 Python 업무 처리를 계속 띄우면 두 프로세스가 함께 상주한다. PyO3 확장 하나만 적용할 때도 Python의 기본 상주 비용은 남고 호출 경계에서 데이터를 복사하면 이익이 줄어든다. [Rust 소유권](https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html), [PyO3](https://pyo3.rs/main/).
- 입력 검증·직렬화 일부는 이미 Pydantic의 Rust 코어가 처리한다. 현재 앱은 DB 풀과 백그라운드 대화, 로컬 모델 호스트의 수명주기를 직접 관리한다. 같은 모델, 검색, DB 호출을 유지한 상태에서 HTTP 구현을 바꿔도 Ollama 가중치·Elasticsearch·PostgreSQL·Windows 커널의 메모리를 직접 회수할 수 없다. [앱 조립](../../backend/src/ai_workshop/main.py), [의존성](../../backend/pyproject.toml), [Pydantic 구조](https://pydantic.dev/docs/validation/latest/internals/architecture/).
- 관리 화면의 이전 지연은 SQL 일괄 조회·풀 재사용·무결성 검사 분리로 개선됐다. 같은 16개 구성에서 SQL 340→124회, 화면 갱신 중 health 최대 1,226→190ms였다. Gemma 첫 요청 중 모델 입력 처리 133.632초는 별도 모델 프로세스의 구간이었다. API 언어 변경에 이 개선치나 모델 시간을 귀속할 근거는 없다. [관리 화면 전후 측정](2026-10-31-backend-response-improvements.md), [Gemma 입력 처리](2026-10-29-openai-gemma-comparison.md).

## 기간 추정

양쪽 언어와 기존 도메인에 익숙한 개발자 1명 전담, 1주 5인일, 기존 HTTP 계약·DB·모델·권한·답변/인용 동등성 유지, 전환·복귀 검증 포함 가정이다. 아래는 대안별 총 기간이다. PoC와 부분 적용은 중복되고, 네 행을 더하지 않는다. 실제 이식 작업의 속도를 측정한 일정은 아니다.

| 범위 | 예상 공수 | 완료 기준 |
|---|---:|---|
| 병목 후보 한 곳의 Python/Rust 비교 시제품 | 3~7인일 | 같은 입력·동시성에서 메모리·지연과 결과 동등성 비교 |
| 확인된 처리 경로 한 곳 운영 적용 | 총 10~25인일(2~5주) | 비교, Windows 패키징, 오류/권한·취소 검사, 이전 경로 복귀 포함 |
| HTTP 계약 전체를 Rust로 옮기고 업무·AI는 Python에 위임 | 50~110인일(10~22주) | 170개 동작의 인증·검증·오류·스트림 동등성과 두 런타임 연결 |
| API·업무 로직·DB 접근·워커·복구까지 운영 동등성 이식 | 210~450인일(약 10~21개월) | 기존 검증된 AI/OCR 런타임을 활용하고 원문 추적·인용·재시도·취소·롤백 검증 |

HEAD의 Git 추적 Python 운영 소스는 534파일·120,423줄(공백/주석 포함)이며 RAG가 374파일·95,249줄이다. 현재 프론트의 생성된 OpenAPI 계약은 140경로·170메서드이며 공개 전시 앱을 포함한다. Celery 작업 9개, Alembic 마이그레이션 68개, `test_*.py` 604파일이다. 마이그레이션 수는 재작성할 파일 수가 아니라 호환할 데이터 이력의 규모를 나타낸다. 추적된 자체 Rust 크레이트는 없다. [HTTP 계약](../../frontend/src/shared/api/schema.d.ts), [워커](../../backend/src/ai_workshop/worker.py).

HTTP 계층 견적은 동작당 평균 0.2~0.4인일을 가정한 34~68인일에 공통 인증·오류·브리지·전환 16~42인일을 더했다. 전면 이식은 HTTP·기반 40~80, 도메인·저장 70~140, RAG·비동기·어댑터 60~150, 통합·품질·전환 40~80인일로 나눠 산정했다. 모두 개략 추정이다. 기존 Python Agents SDK·임베딩·OCR 런타임까지 제거해 **Python 의존성 0개**를 목표로 하면 대체 구현의 출력 동등성과 지원 플랫폼부터 확인해야 한다. 그 추가 기간은 위 견적에 포함하지 않았다.

## 다음 판단 기준

메모리 절약이 목적이라면 먼저 실제 문서 색인이나 동시 대화 중 **어느 프로세스에서 얼마나 증가하는지** 측정한다. Python 쪽 증가가 큰 경우 원문 위치를 보존하는 문서 분할처럼 입출력이 명확한 함수가 시제품 후보가 된다. 그 함수가 실제 병목인지는 아직 미측정이다. 같은 공개 문서·동시성·CPU·아키텍처에서 API와 워커의 전용 상주량·전용 커밋·처리 중 최고값을 각각 측정하고, 사용자가 기다리는 p95 시간과 오류·큐 누적을 함께 비교한다. 문서 분할 결과와 문자 단위 원문 위치(한국어·이모지 포함), 검색 근거·인용이 같아야 한다. 목표 절감량과 품질 기준을 먼저 정한 뒤 결과로 확대 여부를 판단할 수 있다.

## 11월 4일 실제 부하 계측

Windows working set(WS)은 당시 RAM에 올라온 페이지이고 private commit은 OS가 보장한 전용 가상 메모리다. 아래 단위는 MiB이며 합산하지 않는다.

| 공개 TXT 색인 단계 종료 | 8청크 WS | 8청크 private commit | 32청크 WS |
|---|---:|---:|---:|
| 워커 모듈 준비 | 175.68 | 156.03 | 175.30 |
| 본문 파싱 | 175.70 | 156.03 | 175.89 |
| 임베딩 런타임 import | 578.46 | 1,788.00 | 576.66 |
| 첫 토큰 수 계산: E5 가중치 로드 | 910.85 | 3,219.48 | 909.30 |
| 로드된 모델로 청크 분할 | 911.68 | 3,219.97 | 912.17 |
| E5 임베딩 계산 | 1,282.23 | 3,234.03 | 1,289.31 |
| 임베딩 결과 직렬화 | 1,282.25 | 3,234.03 | 1,290.82 |
| Elasticsearch 전송 본문 작성 | 1,282.29 | 3,234.03 | 미측정 |

본래 워커의 파서·청커·CPU float32 E5·배치 2와 실제 ES bulk 직렬화 코드를 별도 프로세스에서 계측했다. 10,966/44,166바이트의 공개 TXT에서 프로세스 평생 최고 WS는 각각 1,300.99/1,309.33 MiB, 최고 private commit은 3,946.66/3,945.99 MiB였다. 작은 표본 bulk 본문은 237,094바이트였다. 본래 DB의 색인 쓰기 차단(frozen)을 유지해 신규 문서 업로드, 큐 소비, ES 전송·저장·활성화는 측정하지 않았다. 큰 표본은 직렬화 후 종료 대기로 bulk 전 단계까지만 유효하다. OCR 또는 대형 PDF에 일반화할 수 없다.

별도의 대화 제어 실험에서는 실제 ASGI 접수·백그라운드 실행·근거 포장 코드를 사용하고 DB·검색·생성을 대역으로 바꿨다. 근거 28개/질문, 1→4→4→1건, 단계별 동시 도달을 확인했다. 1건 대비 유휴 WS 증가 약 0.37 MiB, 4건 1.61~1.64 MiB였다. 이 값은 실제 DB·모델 포함 API 메모리가 아니다.

Elasticsearch 재기동 후 컨테이너 1.523 GiB, JVM heap 사용 약 214.5 MiB, committed/max 각 1 GiB였다. 기존 설정은 Xms=Xmx=1g다. 과거 11/1 표본의 768차원 float32 벡터 22개를 펼친 값은 66 KiB이며 인덱스·캐시를 포함한 RAM 측정값이 아니다. BM25를 ES에 남기면 벡터만 옮겨도 기존 JVM이 남는다. Qdrant를 추가하면 별도 프로세스, pgvector라면 PostgreSQL 버퍼·벡터 인덱스가 필요하다. ES 전체를 종료할 수 있는 대안만 기존 프로세스 전체를 제거한다. 그때도 권한 필터·어휘 검색·융합을 포함한 대안 전체의 유휴/부하 메모리, 지연, 품질을 동일 조건으로 재야 순절감을 안다. [JVM 설정](https://www.elastic.co/docs/reference/elasticsearch/jvm-settings) · [ES 벡터 검색과 파일 캐시](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) · [Qdrant 저장 방식](https://qdrant.tech/documentation/manage-data/storage/).

### 본래 계정의 동시 대화

기존 API 하나와 실제 PostgreSQL·Elasticsearch·로컬 CPU Ollama를 사용했다. 기존 로그인에서 ‘회사 공간 · RAG 합성 참조 자료’로 제한한 새 대화 두 개씩을 동시에 시작했다. 대화 작업은 별도 Celery 워커가 아닌 API 프로세스 안에서 실행된다. Windows 프로세스 표본(약 0.5초)을 같은 UTC 기준의 저장된 실행 단계와 연결했다. 두 요청의 단계가 겹치므로 API 수치를 요청별 메모리로 나눌 수 없다.

1. 상품 식별자를 뺀 두 환매 질문: 34ms 차이로 접수, 각 52초 후 저장. 모두 insufficient_evidence로 생성 생략. API WS 305.8 → 최고 2,214.4 MiB, private commit 280.9 → 최고 4,929.6 MiB. 추론 러너 기동 전이고, 검색/근거 선택만으로도 큰 폭의 증가가 재현됐다. 종료 시점 WS 약 2,104 MiB는 메모리 누수를 증명하지 않는다.
2. 이전 평가에서 사용한 AM-SYN-101 지급일 질문 및 마감 전후 접수일·기준가격 질문: 127ms 차이로 접수되고 실제 생성 단계가 겹쳤다. [지급일 실행](http://127.0.0.1:5173/admin/rag/executions/95bdc255-cbdb-45c2-b7e8-d08ee54fbee1) · [마감 전후 실행](http://127.0.0.1:5173/admin/rag/executions/3eb7d895-3527-4f58-8631-063d5e9c8234). Ollama 0.40.3, 기존 모델 폴더, 루프백 전용. 과거 네 환경변수 값은 확인할 수 없었으며 이번에는 사용자 기동 지시에 따라 값을 임의로 설정하지 않았다. 이번 CPU 러너의 실제 실행 인자는 context 4096, parallel 1이었다. 두 대화가 API에서 겹쳐도 두 생성 모델 사본이 동시에 RAM에 뜬 것은 아니다.

두 쌍에 걸쳐 API 로그에서 가중치 로드 완료 4회를 관측했고 [검색 경로](../../backend/src/ai_workshop/labs/rag/search/pipeline.py)는 요청 소유 임베딩을 생성·해제할 수 있다. 각각의 할당 콜스택까지 측정한 것은 아니다. 메모리가 목표라면 동일 모델·버전·설정의 동시 로드 수명부터 비교할 가치가 있다. 공유 인스턴스 하나와 제한된 큐를 둔 후보가 현행보다 나은지는 유휴 상주량, 피크, 대기 지연, 취소와 검색 결과 동등성을 함께 재야 한다. 이번 조사에서는 적용하지 않았다. 이 표본에서 순수 Python 파싱·분할·직렬화 또는 HTTP를 Rust로 옮겨 확보할 메모리는 입증되지 않았다.

**실제 생성·저장 결과:** 추가 두 건의 API WS는 직전 2,105.3 MiB에서 최고 2,409.8 MiB, private commit은 4,784.2 → 6,156.6 MiB였다. 이번 최고값은 Gemma 러너가 뜨기 전, 두 대화의 접수·검색 구간이 겹칠 때였다. 두 건 종료 약 14초 뒤 API WS는 1,456 MiB, private commit은 약 4,891 MiB였다. 이때의 RAM 감소를 모델 전체 해제로 해석할 수 없다. 별도 llama-server 한 개의 Windows 평생 최고 WS 3,404.32 MiB, 최고 전용 커밋 5,804.60 MiB. 각 프로세스 최고값을 같은 시점의 총 RAM처럼 더하지 않는다.

실제 모델 HTTP 응답은 2건 모두 200. 지급일 질문은 총 192.30초 후 answered로 저장됐다. 마감 전후 질문은 총 327.81초 후 모델 생성은 완료했으나 citation_validation_failed로 실패 상태가 저장됐다. 인용 검증을 우회하거나 재시도하지 않았다. 모델 HTTP 경과 시간은 각각 약 140초와 279초로, 뒤 응답에는 단일 슬롯 대기가 포함된다. 이 2건을 품질 통과나 처리량 벤치마크로 일반화하지 않는다.

로컬 진단 원본은 Git 제외 경로 `.local-data/project-agent-work/`의 `index-stages-20261104/index-stages-{bulk,360}.json`, `chat-stage-memory-20261104/chat-*.json`, `live-memory-20261104/{concurrent.csv,runner.csv,stages.csv}`다. API와 Ollama 부모 965개 표본, 러너 427개 표본. 러너 샘플링은 이름/PID 식별 후 시작했고, 초기 피크는 Windows가 누적한 프로세스 생애 최고값으로 보완했다.
