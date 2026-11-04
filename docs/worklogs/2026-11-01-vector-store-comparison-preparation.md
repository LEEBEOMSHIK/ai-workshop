# 2026-11-01 벡터 저장소 비교 준비

## 요청과 결과 범위

사용자 요청은 Elasticsearch·pgvector·전용 후보1개를 동일 조건으로 검색 품질·속도·자원을 비교할 준비이며 기존 설정/데이터 보존이 조건이다. 전용 후보는 **Qdrant**로 선정했다. 공개 합성 snapshot과 네트워크 없는 요청 생성/분석 CLI를 구현했다. **실제 세 엔진 비교·설치·제품 검색 전환은 미실행**이다. [실행 안내와 미완료 조건](../runbooks/vector-store-comparison.md), [ADR-0055](../decisions/0055-vector-store-comparison-preparation.md), [명세](../superpowers/specs/2026-11-01-vector-store-comparison-design.md), [계획](../superpowers/plans/2026-11-01-vector-store-comparison.md).

중간 위험으로 분류하고 메인이 계약/CLI/통합, 별도 담당이 환경·후보 조사/세 엔진 요청/결과 분석, 독립 담당이 보안·공정성 검토를 맡았다. UI·LLM 생성·학습 역할은 범위 밖이다. 제품의 기본 연결·응답 경로·권한 resolver·모델·청킹/임베딩 설정은 수정하지 않았다.

## 본래 환경에서 확인한 사실

읽기 전용 PostgreSQL 트랜잭션3개에서31개 SELECT 결과 그룹, 기존 ES 물리 색인6개 GET, 호스트/Docker 메타데이터만 조사했다. DB는 repeatable read/read only/statement timeout5초 및 최종 rollback이다. 문서 본문·질문·벡터 값·비밀은 내보내지 않았다.

| 항목 | 관측 |
| --- | --- |
| PostgreSQL | 17.11 Alpine/aarch64, schema0068, pgvector installed0/available0 |
| Elasticsearch | 9.5.2/Lucene10.5.1, 6개 활성 빌드, 22개 벡터 |
| 벡터/검색 | E5 768차원/float32/정규화, BM25·dense K30/RRF60, reranker 미사용 |
| 실제 ES ANN | cosine, BBQ-HNSW m16/ef100/rescore oversample3 |
| 평가 자료 | 6세트38사례, forbidden_source_ids 사례0; evidence gold를 chunk gold로 자동 전환하지 않음 |
| 호스트 자원 | Windows ARM64, RAM23.5GiB, 관측 가용1.5~1.9GiB/nonpaged12.18GiB; 순간값이며 benchmark 아님 |
| 실행 보호 | ISSUE13 frozen gate1/open alias operation1, 기존 장시간 검증 보류 유지 |

Qdrant1.20.0/pgvector0.8.7은 공식 자료 조사 후 고정한 **설치 전 후보 버전**이다. Qdrant의 단일 노드 구조·exact·필터 표현을 선정 근거로 삼았으며 속도·메모리 우위는 미측정이다. 기존 이미지는 실제 ARM64로 프로젝트 AMD64 방침과 차이가 있다. 후보 아키텍처를 강제하거나 PG 이미지/볼륨을 교체하지 않았다. 공식 근거는 runbook에 연결했다.

## 구현

- Frozen 계약: 청크/질의 float32 canonicalization·차원≤4096·정규화1e-5, UUID와 원문 부모 관계, 명시적 allowlist/gold/BM25, profile/revision/permission snapshot digest. 공개 합성만 지원한다.
- Exact 요청: ES filtered script_score, pgvector materialized 허용 subset, Qdrant exact+quantization ignore. 허용 chunk ID를 포함한 전체 identity 튜플로 사전 제한하고 빈 범위는 요청을 만들지 않는다. SQL 매개변수와 후보 식별자 제한을 적용했다.
- 공통 계획: candidate K/결과 K/RRF k·seed·concurrency1 고정, 엔진 순서 회전, 첫 관측/warmup/반복 구분. 계획/요청을 재생성해 변조를 검사한다.
- 분석: dense와 동일 BM25/RRF의 청크 Recall/MRR/nDCG, tie-aware exact-neighbor recall, 첫 관측/반복 p50·p95/표본수, 실패·누락·불법 결과, 미측정 자원 null, 측정 범위/방법 보존. 수입 관측은 `execution_verified=false`다.
- CLI: `validate`, `prepare`, `score`; 기존 출력 파일 덮어쓰기 방지, 원문/벡터/예기치 않은 비밀값을 오류 로그로 출력하지 않음. 제품 서버·DB에 연결하지 않는다.

독립 검토에서 발견한 준비 코드의 원문 부모 관계 충돌, bool→측정 수치 변환, JSON bool/숫자 동등 비교의 요청 변조 누락, 모든 범위가 빈 경우의 complete 표기를 수정했다. 더 강한 이웃을 누락한 동점 결과는 감점한다. JSON 과도한 중첩도 traceback 대신 입력 거절로 처리했다. RRF k를 설정 가능하게 둔 것은 의도된 결정이며 세 군에 공통으로 봉인한다. 현 기준선60과 다른 실험은 새 plan으로 구분한다.

## 검증

검증 범위는 신규4개 모듈 테스트와 기존 RRF/평가 지표 회귀이며 보류한 native 색인 묶음은 실행하지 않았다.

- 개발 중 contracts 최초 red(ModuleNotFoundError), 분석 최초 red(NotImplementedError) 확인 후 구현했다.
- 최초 CLI 테스트의 기본 Windows sandbox 임시 디렉터리 접근 실패는 새 task 전용 basetemp로 해결했다. 제품의 실패로 해석하지 않는다.
- 최종 통합 **109개 통과/2.82초**(신규91 + 기존18), 실패/skip0. JUnit은 `integrated-final-tests.xml`이다. 단위 검사 숫자가 실제 DB 검색 횟수를 뜻하지 않는다.
- strict Mypy **7개 소스** 통과(`--follow-imports silent` 범위 지정), 신규 소스/검사 **11개 파일 Ruff** 통과. 전체 backend 타입/장시간 회귀를 다시 실행한 것은 아니다.
- 독립 담당 최종 신규4파일 **91개 통과/3.14초**, 코드/설계 검토 미해결 차단0. 실제 엔진/스키마/권한 동작을 검증한 결과로 확대하지 않는다.
- 별도 CLI 프로세스로 합성 snapshot4벡터/3질의를 validate→prepare→score했다. 준비 일정132회이며 **실제 검색 요청0회**다. 관측0 입력은 partial·미측정 null로 남겨 임의 성능 수치를 만들지 않았다.
- CLI 종료 후 `.env`/Compose/승인 Python descriptor의 최초 SHA 일치를 다시 확인했다. 문서 로컬 링크·최근 완료5개·diff 공백도 검사했다.

로컬 증거 디렉터리: `.local-data/project-agent-work/vector-store-preparation-20261101/`. `environment-audit.json/md`, 후보/계약 조사 보고서, pytest JUnit, `cli-smoke-plan/observations/report.json`을 보존한다. Git에는 수제 합성 fixture만 포함 대상이며 실제 환경 메타데이터/관측은 제외한다.

## 보존과 다음 작업

환경 조사 전후 `.env`/Compose/승인 Python descriptor SHA 일치, 기존 컨테이너 ID·이미지·볼륨·시작시각/RestartCount0 보존을 확인했다. 실행 중인 다른 앱의 동시 쓰기까지 멈추거나 전체 DB/볼륨의 byte 불변을 주장하지 않는다. 이번 작업의 제품 DB/ES쓰기·새 환경/DB/계정·설치·서비스 변경·임베딩/LLM 호출은0이다. 모델 답변 품질을 새로 측정하지 않았으며 기존 답변 경로를 변경하지 않았다.

다음은 **실측용 배포·자료 계획 확정과 실제 실행기 준비**다. 메모리·아키텍처/pgvector 호환성, 신규 산출물의 정확한 소유/위치/보존, 현재 권한과 승인 corpus·원문/질문 벡터·chunk gold, ISSUE13 쓰기 조건을 먼저 정한다. 현재 CLI는 서버 응답 변환·자원 자동 수집·원래 자료 export·UI 조회 기능이 없으므로 실제 비교를 바로 실행할 수 있는 상태로 보고하지 않는다. 후보 설치·실측 이후에만 품질/속도/자원 우위를 판단한다.
