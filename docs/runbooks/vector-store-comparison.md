# 벡터 저장소 비교 준비와 후속 실행 조건

현재 제공하는 기능은 **오프라인 준비/분석 CLI**다. 서버에 요청을 보내거나 DB/색인/컬렉션을 만들지 않는다. 비교군은 Elasticsearch, pgvector, Qdrant이며 실제 세 엔진의 속도·자원 사용량은 아직 측정하지 않았다. [설계](../superpowers/specs/2026-11-01-vector-store-comparison-design.md), [ADR-0055](../decisions/0055-vector-store-comparison-preparation.md)를 따른다.

## 준비 명령

저장소 루트에서 [기존 Windows Python 활성화](local-development.md#windows-도구용-표준-활성화)를 먼저 수행한다. 아래 입력은 Git에 넣어도 되는 수제 2차원 합성 벡터4개/질의3개다. 실제 E5·기존 문서·질문을 사용하거나 임베딩을 호출하지 않는다. 후보 이름은 예시이며 서버에 생성되어 있지 않다.

```powershell
$comparisonPython = 'C:/projects/ai-workshop/backend/.conda/python.exe'
$env:PYTHONPATH = 'C:/projects/ai-workshop/backend/src'
$comparisonFixture = 'C:/projects/ai-workshop/backend/tests/fixtures/rag/vector_comparison'
$comparisonOutput = 'C:/projects/ai-workshop/.local-data/vector-comparison-preparation'
New-Item -ItemType Directory -Force -Path $comparisonOutput | Out-Null

& $comparisonPython -B -m ai_workshop.labs.rag.evaluation.vector_comparison validate --snapshot "$comparisonFixture/snapshot.json"
& $comparisonPython -B -m ai_workshop.labs.rag.evaluation.vector_comparison prepare --snapshot "$comparisonFixture/snapshot.json" --settings "$comparisonFixture/settings.json" --targets "$comparisonFixture/targets.json" --output "$comparisonOutput/plan.json"
```

첫 명령은 구조/차원/정규화/권한 fixture/원문 identity와 digest를 검사한다. 두 번째 명령은 요청9개(빈 범위 skip3개 포함)와 **미실행 일정132회**를 기록한다: 허용 범위가 있는 질의2개 × 엔진3개 × (첫 관측1 + warmup1 + 반복20). 이 숫자는 실제 요청 횟수가 아니다. 출력 파일이 있으면 덮어쓰지 않고 종료코드2를 반환한다. 재작성할 때 새 출력 파일명을 선택한다.

CLI는 입력 파일당32MiB 이하의 `public_synthetic`만 허용한다. 사용자 문서의 분류 문자열만 바꾸어 사용하면 안 된다. 실제 자료용 export·현재 권한 확인·질문 벡터/정답의 원문 추적과 엔진 실행·응답 변환기는 아직 제공하지 않는다.

## 수입 관측 분석

외부 실행기가 만든 관측을 나중에 다음 형식으로 전달한다. 이번 도구의 계약은 [contracts.py](../../backend/src/ai_workshop/labs/rag/evaluation/vector_comparison/contracts.py)가 정본이다.

- `plan_digest`: 준비 결과의 정확한 SHA-256.
- `evidence_kind`: 자동 생성한 시험 데이터는 `synthetic`, 외부 관측은 `imported_unverified`.
- `records[]`: `attempt_id`, `status`(`ok/error/timeout/unavailable`), `elapsed_ms`, `hits[]`, 선택 `resources`.
- `hits[]`: 반환 순서대로 `chunk_id/workspace_id/document_id/asset_version_id/projection_id/index_build_id` UUID와 숫자 `score`. 입력 snapshot의 청크 identity와 정확히 일치해야 한다. 결과 본문은 넣지 않는다.
- `elapsed_ms`: 동일 클라이언트에서 요청 직전부터 완전한 응답 해석까지 측정한 밀리초. 성공은 값이 필수다. bool·문자열·음수·NaN은 거절한다. 서버 내부 시간과 합치지 않는다.
- `resources`: `method`, `scope`와 `cpu_process_ms`, `rss_peak_bytes`, `container_memory_peak_bytes`, `storage_bytes`의 측정된 값만 넣는다. 미측정은 null이다. CPU 시간은 해당 요청 관측 구간의 증가분이다. RSS/메모리 peak와 저장 크기는 측정 기간·범위를 method/scope에 명시한다.

`score`는 실행을 하지 않으며 수입 파일의 진위를 증명하지 않는다. 계획·생성 요청이 수정되었거나 모르는/중복 attempt ID가 있으면 분석을 거절한다. 범위 밖 청크/잘못된 identity/중복 hit/과다 hit는 해당 관측의 `invalid_result`로 남기고 성공 통계에서 제외한다. 원래 오류와 누락 수는 남긴다.

```powershell
& $comparisonPython -B -m ai_workshop.labs.rag.evaluation.vector_comparison score --snapshot "$comparisonFixture/snapshot.json" --plan "$comparisonOutput/plan.json" --observations "$comparisonOutput/observations.json" --output "$comparisonOutput/report.json"
```

보고서는 엔진별 첫 관측/반복 p50·p95·표본 수, 실패/누락, dense·고정 BM25/RRF의 **청크** Recall@K/MRR@K/nDCG@K, 동점 허용 exact-neighbor recall을 제공한다. `execution_verified=false`를 항상 남긴다. `complete`는 계획 관측의 파일상 충족만 뜻하며 서버/품질 수용 완료가 아니다. 모든 범위가 비어 실행 일정이 없으면 `no_attempts`다. `gold=null`은 미판정, `gold=[]`는 정답 없음으로 구분한다. 두 경우 관련도 지표는 null이다. warmup은 성능/품질 합산에서 제외한다.

서로 다른 scope/method의 자원 관측은 평균 내지 않고 그대로 나열한다. 실제 비교에서는 엔진별 idle baseline, 색인 완료 상태, 요청 구간 peak/CPU, 호스트 사용 가능 메모리와 디스크 증가분을 동일 방법으로 별도 기록해야 한다. 자원 자동 샘플러와 그래프 UI는 이번 범위에 없다.

## 후보 스키마와 공정 비교

준비 요청은 **동일한 봉인 corpus를 별도로 materialize한 후보 스키마**를 전제로 한다. 기존 ES에 없는 `document_id`를 요구하므로 현재 운영 색인에 그대로 실행할 수 없다. 기존 색인을 수정하거나 문서 필드를 자동 추가하지 않는다. 미래 exporter가 현재 DB의 원문 관계를 확인해 매핑하고, 승인된 후보에 동일한 내용/벡터가 적재되었는지 해시로 검증해야 한다.

- 공통 identity6개는 ES keyword/PG UUID/Qdrant UUID 문자열 payload다. 문서 튜플 전체와 허용 chunk ID를 함께 선필터한다. 같은 문서의 미허용 형제 청크를 포함하지 않는다.
- ES/PG 벡터 이름은 `embedding`, Qdrant는 이름 없는 dense vector다. ES·PG 원점수는 각각 `cosine+1`·`cosine distance`, Qdrant는 cosine이다. 보고서는 raw score 크기를 엔진 사이 직접 비교하지 않고 결과 순서를 평가한다.
- PG는 `WITH allowed AS MATERIALIZED` 결과를 exact distance 정렬한다. 실행 전에 read-only transaction과 statement timeout 및 `EXPLAIN`으로 허용 subset 뒤 정렬인지 확인한다.
- Qdrant는 `exact=true`와 `quantization.ignore=true`를 함께 사용한다. ES는 filtered script_score로 기존 ANN과 구분한다. 현재 ES BBQ-HNSW 결과는 나중의 ANN 실험으로 별도 기록한다.
- 공통 차원은1~4096, float32 유한/L2 정규화 오차1e-5다. cosine cutoff 동점 허용오차는1e-6이다. 동점 인정은 neighbor recall에만 적용하고 관측된 관련도 순위를 재정렬하지 않는다.
- `settings`는 비교군 전체에 하나만 적용한다. 실제 기준선은 현 프로파일의 candidate K30/RRF k60을 옮겨야 한다. 다른 값을 시험할 때도 세 군에 동일하게 적용하고 새 plan으로 기록한다. 합성 예시의 결과 K2는 실제 운영 K가 아니다.
- qrel은 사람이 검토한 **청크 gold**를 제공한다. 기존38개 평가의 evidence gold를 이름만 바꿔 사용하지 않는다. 외부 질문 원문·source hash와 qrel 검토 근거는 후속 snapshot exporter에서 연결한다.

## 실제 비교를 시작하기 전

1. **인프라 조건 확정:** 조사 당시 가용 RAM 약1.5~1.9GiB로 제한적이다. 후보별 메모리/CPU/디스크 예산과 종료 기준을 정한다. 기존 서비스·ASA를 임의 중지하지 않는다. 문서 AMD64 방침과 실제 ARM64 이미지의 차이를 해소하고 모든 군의 native/emulated 상태를 기록한다.
2. **배포안 확정:** Qdrant1.20.0, pgvector0.8.7은 조사 후보 버전이다. 플랫폼별 image digest를 검증한다. 현재 PG17.11 Alpine에는 vector extension이 없으므로 기존 볼륨을 다른 이미지로 즉시 바꾸지 않는다. 호환 배포·백업/복원·신규 객체 소유/보존 계획을 먼저 만든다.
3. **데이터/권한 확정:** 승인된 동일 corpus, 기존 벡터와 고정 질의 벡터의 전수 parity, 현재 ACL·READY·active build, 원문 위치, chunk gold와 권한 부정 사례를 준비한다. 기존22벡터는 정합성 점검 규모이며 대규모 성능 표본이 아니다.
4. **쓰기 조건:** ISSUE-00013의 ES 쓰기 게이트는 유지한다. 사용자 보류 장시간 색인 검사를 자동 재개하지 않는다. 새 후보 corpus 생성도 별도 구체적 실행 범위가 필요하다.
5. **실행기 검증:** 세 엔진 응답 변환·실제 필터 음성 사례·timeout/cancel·순차 스케줄·동일 클라이언트 시간·자원 샘플링을 통합 검증한다. 재시도/다른 엔진 fallback은 자동 적용하지 않는다.
6. exact 동등성 후 ANN을 recall 목표별로 비교한다. 수집·갱신·삭제·재시작/복원 비용은 기존 자료가 아닌 승인된 disposable fixture에서 별도 평가한다. 결과가 좋아도 기본 연결을 자동 변경하지 않는다.

## 공식 근거

2026-11-01 조회: [Qdrant v1.20.0](https://github.com/qdrant/qdrant/releases/tag/v1.20.0), [설치/아키텍처](https://qdrant.tech/documentation/installation/), [exact 검색](https://qdrant.tech/documentation/search/search/), [양자화 우회](https://qdrant.tech/documentation/manage-data/quantization/), [pgvector 0.8.7 검색/필터/설치](https://github.com/pgvector/pgvector/blob/v0.8.7/README.md), [PostgreSQL MATERIALIZED](https://www.postgresql.org/docs/17/queries-with.html#QUERIES-WITH-CTE-MATERIALIZATION), [ES script_score](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-script-score-query), [ES dense_vector/차원](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/dense-vector), [Docker stats의 메모리 정의](https://docs.docker.com/reference/cli/docker/container/stats/).
