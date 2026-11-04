# 벡터 저장소 비교 준비 명세

사용자 요청: Elasticsearch·pgvector·전용 후보1개를 같은 조건으로 검색 품질·속도·자원 사용량 비교할 수 있게 준비하고 기존 설정·데이터를 보존한다. [ADR-0055](../../decisions/0055-vector-store-comparison-preparation.md)를 따른다.

## 성공 기준과 범위

1. 네트워크·DB·임베딩/LLM 실행 없이 유효한 공개 합성 입력을 검사하고 세 엔진의 exact 요청과 실행 순서를 생성한다.
2. 임베딩 모델/revision·차원·float32·cosine·정규화, 청크/질문 벡터, 원문 identity, 허용 범위, gold, 고정 BM25 순위를 하나의 SHA-256로 봉인한다. 비정상 벡터·중복 ID·혼합 provenance·허용 밖 gold/BM25를 거절한다.
3. 동일 snapshot·candidate K·출력 K·RRF k, concurrency1, 교차 순서·warmup·반복 수로 계획한다. 첫 관측을 cold start로 이름 붙이지 않는다.
4. 엔진별 수입 결과를 plan digest/attempt ID에 연결하고 범위 밖/잘못된 원문/중복 결과는 실패로 판정한다. 실패를 걸러 정상인 것처럼 채점하지 않는다.
5. dense와 동일 BM25+RRF의 청크 Recall@K/MRR/nDCG, BM25 기준선, tie-aware exact-neighbor recall, 첫 관측과 반복 p50/p95·성공/실패/누락 수를 구분한다. 미판정 gold/미측정 자원은 null. CPU 시간·RSS·컨테이너 메모리·저장 크기는 측정 범위/방법을 포함한다.
6. 합성 CLI 왕복·오류/권한 경계·정적 검증·독립 검토를 통과한다. 실제 서버 비교나 답변 품질 향상으로 보고하지 않는다.

이번 CLI는 공개 합성 입력만 받는다. 원래 자료를 임의 export하지 않는다. private 자료용 export·현재 권한 재검사·본문/원문 위치 연결·실제 엔진 실행기는 후속 작업이다. 저장소 전체 실제 qrel은 근거 단위이므로 청크 gold로 임의 변환하지 않는다.

## 입력과 요청

Frozen Pydantic 계약은 알 수 없는 필드를 거절한다. UUID 청크 식별자와 `(workspace_id, document_id, asset_version_id, projection_id, index_build_id)`를 보존한다. query마다 명시적 허용 청크를 받아 exact tuple들의 OR로 필터를 만든다. 빈 허용 범위는 요청을 생성하지 않는다. 스냅샷의 권한 버전은 과거 관측이며 현재 권한의 대체물이 아니다.

공통 float32 변환 후 차원·유한값·L2 정규화(허용오차1e-5)를 검사한다. 원문 identity/permission revision/profile 내용과 질문 벡터가 바뀌면 plan digest도 바뀐다. 후보 저장소는 snapshot 전체를 동일 payload로 materialize하고 동일 벡터 해시를 검증해야 한다. 준비 CLI는 이를 실행하지 않는다.

입력 차원은 공통 ES 한도4096까지다. RRF k와 후보 수는 세 군에 공통으로 기록하며 현 기준선은30/60이다. 다른 프로파일 값을 시험할 때 새 plan으로 구분한다. snapshot 해시는 벡터·identity·프로파일·권한 fixture를 봉인하고, 실제 원문/source hash·질문 text와 gold 검토의 연결은 후속 exporter에서 준비한다. 현재 CLI를 원문 검증 완료로 표현하지 않는다.

| 엔진 | exact 요청 | 필터와 점수 |
| --- | --- | --- |
| Elasticsearch | filtered `script_score` | 후보 생성 전 정확한 identity, cosine+1, 원 벡터 사용 |
| pgvector | `MATERIALIZED` 허용 subset 후 `<=>` | 허용 tuple을 먼저 확정, cosine distance, 매개변수 SQL |
| Qdrant | points/query `exact=true`, `quantization.ignore=true` | 정확한 identity payload filter, cosine score |

오프라인 요청은 후보의 단일 봉인 corpus 이름을 대상으로 한다. 본래 alias나 제품 물리 색인 이름을 자동 추정하지 않는다. 실제 실행 전에 payload/schema·READ ONLY·timeout·현재 권한·불변 generation·image digest를 검증한다. ANN·insert/update/delete·복원 측정은 별도 fixture 프로토콜로 준비한다.

## 공정성과 관측 한계

- exact oracle은 허용 subset의 cosine을 직접 계산한다. cutoff 동점은 허용오차1e-6으로 동등하게 인정한다. relevance 순위와 동점 판정은 분리한다.
- BM25 입력은 모든 엔진에 동일하게 고정하고 기존 RRF 합산/동점 규칙을 재사용한다. 선택 reranker와 생성 모델은 호출하지 않는다.
- 반복 수 기본20, warmup1, 첫 관측1. 실행 순서는 case·engine을 seed로 재현 가능하게 교차한다. engine별 성공 표본 수·오류율·누락을 함께 표시한다. 샘플이 적으면 p95의 대표성을 주장하지 않는다.
- 네트워크 왕복을 포함한 동일 클라이언트 관측 시간을 받는다. 서버 내부 처리 시간과 섞지 않는다. snapshot은 작은 합성 자료이며 실서비스 규모 추정치가 아니다.
- 자원 값은 외부 측정자가 공급한 관측이다. 같은 방법/범위/기간의 baseline·peak·증가분이 있어야 비교 가능하다. Docker 메모리, RSS, 호스트 메모리는 다른 값이다. 준비 도구는 측정 자체를 수행하지 않는다.
- 유효한 수입 파일도 실제 실행 증명을 의미하지 않는다. `synthetic`와 `imported_unverified`를 모든 보고서에 명시하며 자동 승격하지 않는다.

## 실제 실행 전 조건

환경·인프라 승인 목록은 후속 runbook에 명시한다: 충분한 여유 메모리, AMD64 정책/현재 ARM64 차이, 후보 이미지 digest와 pgvector 배포 호환성, 정확한 신규 파일/볼륨/테이블 소유·보존, ISSUE13 쓰기 게이트, 승인 corpus·질문 벡터·chunk gold, 현재 ACL 검증, 원문 추적, baseline 자원 측정. 이번 변경은 설치·기존 재시작·확장 생성·데이터 이관·모델 호출을 하지 않는다.
