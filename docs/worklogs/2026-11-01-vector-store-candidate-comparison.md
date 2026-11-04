# Qdrant·Milvus·Weaviate·Chroma 프로젝트 적합성 비교

- 조사일: 2026-11-01. 공식 문서·고정 버전 소스와 같은 날의 기존 환경 조사에 근거한다.
- 범위: 후보 비교·판단·문서 기록. 설치, 제품 설정/코드 변경, 컨테이너·DB·색인 생성, 모델 호출과 실제 성능시험은 하지 않았다.
- 선행: [비교 준비 결과](2026-11-01-vector-store-comparison-preparation.md), [ADR-0055](../decisions/0055-vector-store-comparison-preparation.md), [오프라인 비교 사용법](../runbooks/vector-store-comparison.md).
- 검토 상태: 제품별 조사·통합 문서 독립 검토 완료, 차단 결함0. 문구 권고2개 반영, 문서3개·로컬 링크102개·최근 완료5개·보존17파일·diff 공백 검사 통과.

## 판단

**현재 운영은 Elasticsearch를 유지한다. 전용 벡터 DB의 첫 실측 후보는 Qdrant, 다음 비교 후보는 Weaviate로 권고한다.** 이는 품질·속도·RAM 우열의 실측 결론이 아니라 현재 RAG 계약과 준비된 비교 도구에 대한 적합성 판단이다.

Qdrant는 필요한 범위인 외부 벡터·권한 prefilter·exact/ANN·단일 서버·스냅샷에 맞고, 이미 오프라인 exact 요청 준비가 되어 있어 다음 검증의 추가 비용이 작다. Weaviate도 exact·prefilter·인증·백업을 갖춘 유효한 서버 후보다. Qdrant의 우선순위에 기존 준비 비용이 반영됐음을 명시하며, Qdrant가 본질적으로 더 가볍거나 더 빠르다는 뜻으로 확대하지 않는다.

Chroma는 편리한 내장/단일 서버와 현재 Rust 구현을 갖춘 후보이며 소규모 실험용으로만 제한된 제품이라고 평가하지 않는다. 다만 확인한 local 공개 API에는 강제 exact 검색 경로가 없고, 인증·일관 백업 통합이 추가로 필요하여 이번 exact 1단계보다 후속 ANN 비교에 적합하다. Milvus Standalone은 현재 데이터·호스트 여유에 비해 운영 부담이 크다. Milvus Lite는 별도 경량 선택지이며 Standalone의 자원 요구량을 적용하면 안 된다.

## 이 프로젝트의 비교 조건

| 확인된 조건 | 판단에 미치는 영향 |
|---|---|
| 기존 검색은 ES의 BM25 + dense + RRF, 후보 수 각각30·RRF k60 | 전용 DB 후보는 dense 영역만 비교한다. ES의 BM25와 PG의 권한·원문 정본은 남으므로 새 저장소는 추가 운영 비용이다. |
| 활성 문서6개·청크/벡터22개, E5-base 768차원 float32 정규화 벡터 | 현재 규모는 거리·필터·원문 추적 정합성 확인용이다. 전체22개보다 top-k30이 커서 recall@30은 허용 집합 전체 회수 여부에 가까우며 ANN 품질 차이를 판별하지 못한다. |
| 원문 identity는 `chunk_id, workspace_id, document_id, asset_version_id, projection_id, index_build_id` | 모든 엔진에서 허용 청크와 정확한 튜플 조합을 검색 후보 생성 전에 제한해야 한다. 각 필드의 허용 ID를 독립 집합으로 섞으면 잘못된 원문 버전 조합이 허용될 수 있다. |
| 현재 ES는 cosine BBQ-HNSW, m16·ef_construction100·rescore oversample3 | 기존 압축 ANN 결과를 exact 정답으로 쓰지 않는다. 비압축 exact 동등성과 ANN/양자화의 비용·재현율을 분리한다. |
| 기존 평가6개 묶음·38문항은 근거 단위 평가이며 명시적 forbidden-source 사례가 없음 | 청크 정답·권한 부정 사례를 보강해야 한다. 기존 점수를 그대로 새 chunk recall 또는 권한 안전성 증거로 바꾸지 않는다. |
| 이전 읽기 조사: Windows ARM64, RAM23.50GiB·가용 약1.5~1.9GiB·nonpaged 약12.18GiB; Docker Linux ARM64·VM11.40GiB | 같은 날 관측된 상태이며 현재 가용량의 보장은 아니다. VM 할당량 전체를 새 DB 예산으로 보지 않는다. 네 엔진을 동시에 올리는 비교는 적합하지 않다. |
| 저장소 방침은 AMD64 유지, 실제 Docker는 ARM64 | 후보의 정확한 이미지 태그·digest·명령집합·네이티브/에뮬레이션 조건을 맞춰야 한다. 공식 ARM 지원만으로 이 장치의 실행성·속도를 검증했다고 말하지 않는다. |

환경 수치는 선행 기록과 로컬 증거 `vector-store-preparation-20261101/environment-audit.md`에 기반한다. 이번에는 운영 DB나 서비스를 다시 조회하지 않았다. 기존 ISSUE-00013 쓰기 게이트, 보류한 장시간 색인·복구 검증, ASA 유지 방침도 변경하지 않았다.

## 네 후보 비교

아래 속도·자원 항목은 공식 기능과 구조에 따른 예상 평가 항목이다. **동일 조건의 검색 품질·ms·QPS·프로세스 RAM 실측값은 네 제품 모두 아직 없다.**

| 후보 / 비교 모드 | 검색 품질과 필터 | 속도에 영향을 주는 구조 | 자원 사용과 운영 복잡도 | 프로젝트 적합성 |
|---|---|---|---|---|
| **Qdrant / 단일 서버** | 외부 벡터, cosine, 복합 payload prefilter, `exact=true` 전수 검색. HNSW의 탐색 폭과 양자화는 별도 실험 | 필터 인덱스·허용 집합 크기·HNSW 설정·캐시가 영향. cold 저장은 첫 접근 I/O와 교환 | 한 서버와 볼륨으로 시작 가능. 벡터/그래프 메모리 계층 조절, API key·TLS·스냅샷 제공. payload index와 캐시도 자원 소모 | **첫 실측 후보.** 현재 exact 요청 준비 재사용과 필요한 운영 기능의 범위가 맞음. 최저 RAM·최고 속도 판정은 아님 |
| **Weaviate / 단일 서버** | 외부 벡터, 비압축 flat exact, inverted-index allow-list 기반 prefilter. HNSW·ACORN 등 선택 | flat/HNSW·필터 전략·벡터 캐시가 영향. 작은 허용 집합은 HNSW 설정에서도 flat으로 전환할 수 있어 실제 경로 기록 필요 | 서버 하나로 시작 가능. 인증·RBAC·백업 모듈 제공. 스키마·벡터화/모듈·캐시 설정 항목을 명시해야 함. 디스크 중심 HFresh도 별도 선택지 | **다음 비교 후보.** 기능적으로 충분하며 Qdrant보다 품질·속도가 낮다고 결론낼 근거 없음 |
| **Chroma / local 또는 단일 서버** | 외부 벡터·cosine·ids/metadata prefilter 지원. 확인한1.5.9 local query는 HNSW이고 강제 exact 옵션 없음 | HNSW 탐색 설정과 RAM 상주가 영향. embedded와 HTTP 서버의 호출 비용은 서로 다른 측정 경계 | 내장 모드는 시작이 간단. 서버 운영에는 별도 인증/TLS 경계와 SQLite·HNSW 전체의 일관 백업 필요. HNSW 메모리·paging 주의 | **후속 ANN 후보.** 개발 API 편의성이 장점. native exact 1단계와 운영 통합에서는 추가 작업 |
| **Milvus / Standalone** | FLAT exact, HNSW/IVF 계열 등 다수 인덱스. 표준 필터는 검색 전 제한; iterative 필터는 별도 방식 | 인덱스 선택·필터 선택도·로드/캐시·스토리지 영향. 큰 규모의 선택 폭은 장점이나 현재22개에서는 이득 미입증 | 공식 Standalone RAM 최소8GB·권장16GB. 단일 Docker 또는 Milvus+etcd+MinIO Compose 가능. 스토리지·메타데이터·백업/복구 경계를 함께 관리 | **현재 우선순위 낮음.** 큰 규모·분산 운영 요구가 실제로 생겼을 때 재평가. 아래 Lite와 구분 |

근거: Qdrant [필터](https://qdrant.tech/documentation/search/filtering/)·[검색](https://qdrant.tech/documentation/search/), Weaviate [벡터 인덱스](https://docs.weaviate.io/weaviate/concepts/vector-index)·[prefilter](https://docs.weaviate.io/weaviate/concepts/filtering), Chroma [설정](https://docs.trychroma.com/docs/collections/configure)·[1.5.9 query API](https://github.com/chroma-core/chroma/blob/1.5.9/chromadb/api/models/Collection.py#L176)·[local executor](https://github.com/chroma-core/chroma/blob/1.5.9/rust/frontend/src/executor/local.rs#L133), Milvus [FLAT](https://milvus.io/docs/flat.md)·[표준/iterative 필터](https://milvus.io/docs/filtered-search.md)·[Standalone 요구 사항](https://milvus.io/docs/prerequisite-docker.md).

### 검색 품질

같은 벡터·cosine·권한 집합을 대상으로 비압축 exact 검색을 하면 부동소수 오차·동점 처리 범위 안에서 같은 이웃을 얻는 것이 기대값이다. DB 교체 자체가 E5의 한국어 의미 이해나 LLM의 추론 능력을 높이지 않는다. ANN·양자화에서는 이웃 누락이 달라져 최종 근거와 답변에 영향을 줄 수 있으므로 관련도와 함께 평가해야 한다.

구분할 지표는 (1) exact 이웃 대비 ANN 재현율, (2) 사람이 판정한 근거 관련도·Recall/MRR/nDCG, (3) 같은 BM25·RRF를 거친 최종 근거, (4) 같은 모델·프롬프트에서의 답변·인용 품질이다. (1)이 높다고 (2)~(4)가 자동으로 높아지는 것은 아니다. 이번 조사에서는 어느 후보의 답변 품질도 향상·유지됐다고 실측 판정하지 않았다.

Chroma도 공통 외부 exact 정답과 ANN을 비교할 수 있다. 다만 모든 벡터를 `get`으로 꺼내 애플리케이션에서 계산한 시간을 다른 엔진의 내부 exact 시간과 같은 항목으로 비교하면 안 된다. 높은 HNSW `ef` 또한 exact 보증이 아니다. [Chroma 고정 버전 실행 경로](https://github.com/chroma-core/chroma/blob/1.5.9/rust/frontend/src/executor/local.rs#L150)

### 속도와 메모리

- **Qdrant:** dense 벡터는 mmap 저장과 cold/cached 계층을 사용한다. cold는 사전 적재를 줄이지만 OS page cache·첫 조회 I/O가 남고, 필터 payload index·그래프·프로세스 비용도 있다. 메모리 추정 API는 allocator/라이브러리를 포함한 실제 프로세스 peak가 아니다. [저장](https://qdrant.tech/documentation/manage-data/storage/), [메모리 계층](https://qdrant.tech/documentation/ops-configuration/memory-tiers/), [추정 범위](https://qdrant.tech/documentation/ops-monitoring/memory-usage/)
- **Weaviate:** flat·HNSW의 메모리 구조가 다르며 vector cache·그래프·Go GC·mmap을 구분해야 한다. HFresh는1.38부터 GA인 디스크 중심 대안으로, centroid HNSW와 압축 posting을 사용한다. 필수 양자화가 있어 비압축 exact 기준과 섞지 않는다. HFresh의 구체적 사용 조건·이 장치 성능은 추가 확인 대상이다. [자원 계획](https://docs.weaviate.io/weaviate/concepts/resources), [1.38 GA](https://github.com/weaviate/weaviate/releases/tag/v1.38.0), [HFresh 설정](https://docs.weaviate.io/weaviate/config-refs/indexing/vector-index#hfresh-index)
- **Chroma:** single-node 성능 가이드는 HNSW RAM 상주와 paging 시 지연 증가, RAM2GB 미만 배포 비권장을 설명한다. 이는1.5.9의 이 장치 최소 사용량이나 벤치마크 결과가 아니다. 디스크에 영속화한다는 사실만으로 disk-native ANN이라고 해석하지 않는다. Cloud/distributed SPANN의 자원 특성도 local HNSW와 다르다. [단일 노드 성능 가이드](https://docs.trychroma.com/guides/performance/single-node), [분산 구조](https://docs.trychroma.com/reference/architecture/distributed)
- **Milvus:** Standalone의8/16GB는 배포 가이드 요구치이며 실제 RSS 실측값도, Lite 요구치도 아니다. mmap으로 일부 메모리 압력을 줄일 수 있지만 SSD I/O·로드/조회 지연과의 교환을 측정해야 한다. [요구 사항](https://milvus.io/docs/prerequisite-docker.md), [mmap](https://milvus.io/docs/mmap.md)

벡터 값만의 산술 하한은22×768×4=67,584bytes,10만개 약293MiB,100만개 약2.86GiB다. 이는 어떤 제품의 총 RAM/디스크 요구량도 아니다. 그래프·필터 인덱스·본문/메타데이터·WAL·백업·구축 peak·프로세스·OS 캐시가 더해진다. 현재 가용 RAM 관측치로는 후보의 안전한 추가 기동까지 보장할 수 없다.

기존 Gemma 비교의 첫 입력 처리133.632초는 LLM 실행 구간에서 관측됐다. [기존 실측과 한계](2026-10-29-openai-gemma-comparison.md). 벡터 DB 선택으로 검색 부분을 줄일 가능성은 있지만 그 시간을 직접 해결하지는 않는다. 전체 응답을 검색·fusion·LLM 입력 처리·출력 생성으로 나눠 판단해야 한다.

### 배포 방식과 운영 부담

- **Milvus Lite3.2.2**는 현재 Python/FAISS 기반이며 FLAT/BRUTE_FORCE뿐 아니라 HNSW/IVF 계열도 지원한다. 과거의 FLAT 전용 설명을 적용하지 않는다. 내장 방식은 서버 설치 부담을 줄이지만 인증·TLS·RBAC가 없고 같은 컬렉션의 동시 쓰기가 제한되므로 API/worker의 소유·직렬화 경계를 설계해야 한다. Windows ARM64 native 의존성 설치 가능성도 미검증이다. [3.2.2 README](https://github.com/milvus-io/milvus-lite/blob/v3.2.2/README.md), [인덱스 설계](https://github.com/milvus-io/milvus-lite/blob/v3.2.2/docs/index-design.md)
- **Milvus Standalone**은 단일 Docker 실행도 가능하다. 그 경우 etcd·local Woodpecker 등 내부 구성요소가 없어지는 것은 아니다. Compose 예제는 Milvus·etcd·MinIO의 세 상주 서비스이며 백업 가이드는 Compose 방식을 권한다.3.x snapshot은 원본 segment를 참조하는 동일 클러스터 복원 기능이므로 독립 백업과 구분한다. [Docker](https://milvus.io/docs/install_standalone-docker.md), [Compose](https://milvus.io/docs/install_standalone-docker-compose.md), [snapshot](https://milvus.io/docs/snapshots.md)
- **Qdrant**는 self-host 기본 무인증이므로 API key/TLS 등 서버 경계가 필요하다. snapshot도 원본 volume과 다른 장애 영역의 보관·복원 시험이 필요하다. Windows에서는 POSIX 파일시스템의 Linux volume을 우선 검토해야 한다. [보안](https://qdrant.tech/documentation/security/), [스냅샷](https://qdrant.tech/documentation/database-tutorials/create-snapshot/), [설치](https://qdrant.tech/documentation/installation/)
- **Weaviate**는 API key/OIDC/RBAC와 백업 모듈을 제공한다. anonymous·모델 통합·vectorizer·양자화 여부를 비교 조건에 명시해야 한다. 현재 문서의 양자화 기본값은 none이며 exact 기준도 비압축으로 고정한다.1.40에서는 컬렉션의 self-provided 벡터를 지정하며 폐기된 `DEFAULT_VECTORIZER_MODULE`에 의존하지 않는다. 일반 flat/HNSW/BYOV 비교에 enterprise Namespace는 필요 없다.1.40.3 라이선스는 `wl/` 외부 BSD와 enterprise 영역을 구분하므로 전체 기능을 일괄 무료라고 표현하지 않는다. [인증](https://docs.weaviate.io/deploy/configuration/authentication), [백업](https://docs.weaviate.io/deploy/configuration/backups), [환경변수](https://docs.weaviate.io/deploy/configuration/env-vars), [라이선스](https://github.com/weaviate/weaviate/blob/v1.40.3/LICENSE)
- **Chroma**는1.0부터 Rust 구현으로 바뀌면서 기존 내장 인증 구현을 제거했다. self-host 서버에는 앱의 문서 ACL과 별도로 인증/TLS proxy 또는 동등한 접근 경계가 필요하다. SQLite DB 파일 하나의 복사만으로 HNSW까지 일관되게 복구됐다고 볼 수 없다. 전체 persist 저장소의 일관 스냅샷/정지 백업과 복원 검증은 채택 시 설계할 항목이다. [마이그레이션](https://docs.trychroma.com/docs/overview/migration), [Docker 영속화](https://docs.trychroma.com/guides/deploy/docker)

모든 후보에 공통으로 앱 ACL, 원문 버전/빌드 활성 상태, 변경·삭제 동기화, 멱등 재시도, PG·ES와 같은 build 경계 복구, 원문 뷰어 역참조가 필요하다. DB의 인증·필터·백업 기능이 이 애플리케이션 책임을 대신하지 않는다. 관리형 Cloud의 기능·비용을 self-host와 혼합하지 않았으며 외부 자료 전송·계정 생성·과금은 없다.

## 실제 비교로 판단을 확정할 조건

다음은 후속 비교의 판단 기준이며 이번에 실행하거나 신규 어댑터를 구현한 내용이 아니다.

1. **입력과 환경 고정:** 승인 자료, 문서/질문 벡터·E5 revision·float32·정규화·cosine·정확 identity/ACL·반환 top-k·BM25·RRF를 동일하게 봉인한다. 비공개 자료의 외부 전송 없이 비교하고 native/에뮬레이션·CPU/RAM 한도·클라이언트 경계를 맞춘다.
2. **정합성 먼저:** 현재22개로 필터·거리·동점·누락 필드·권한 철회·잘못된 원문 버전·빈 허용 집합을 검사한다. Qdrant exact, Milvus FLAT, Weaviate 비압축 flat을 공통 exact 정답과 확인한다. Chroma local은 ANN으로 구분한다. Milvus iterative filtering은 strict prefilter 기준에 섞지 않는다.
3. **품질과 속도 함께:** top-k보다 충분히 큰 승인 자료와 다양한 질문·필터 선택도를 사용한다. 같은 `ef` 숫자가 아니라 **같은 목표 이웃 재현율**에서 p50/p95/p99·처리량·품질 곡선을 비교한다. 실제 탐색 경로·압축·캐시 상태를 기록하고 첫 요청/같은 질문 반복/다른 질문의 warm 요청을 구분한다. 충분한 반복 횟수와 불확실성을 보고한다.
4. **자원과 운영:** 한 후보씩 idle/구축/query peak RAM·CPU·page cache·디스크/WAL/백업 크기를 수집한다. HTTP 왕복과 embedded 내부시간은 별도 표기한다. update/delete·재시작·백업 복원에서 원문/권한/활성 build 정합성을 확인하고, 필요한 운영 구성요소와 작업을 함께 기록한다.
5. **답변 품질:** 검색 품질과 최종 답변/인용을 분리한다. 고정 모델·프롬프트의 생성 평가를 실행한다면 별도 입력·호출 범위를 정한다. 모델을 함께 바꿔 DB 성능과 추론 성능을 혼합하지 않는다. 유의미한 이익이 없으면 ES 유지가 합리적인 결과다.

Qdrant와 Weaviate 사이의 우선순위는 이 측정으로 바뀔 수 있다. Chroma의 간단한 내장 구조가 필요한 사용 방식이 되거나 Milvus의 대규모/분산 기능이 필요해지면 해당 후보의 가치도 달라진다. 지금 운영 채택을 확정할 근거는 없다.

## 출처의 버전과 확인 한계

2026-11-01 공식 GitHub latest가 가리킨 안정판은 Qdrant[1.20.0](https://github.com/qdrant/qdrant/releases/tag/v1.20.0), Milvus Server[3.0.5](https://github.com/milvus-io/milvus/releases/tag/v3.0.5), Milvus Lite[3.2.2](https://github.com/milvus-io/milvus-lite/releases/tag/v3.2.2), Weaviate[1.40.3](https://github.com/weaviate/weaviate/releases/tag/v1.40.3), Chroma[1.5.9](https://github.com/chroma-core/chroma/releases/tag/1.5.9)다. Milvus 최신 patch의 상세 노트와 일부 설치 예제 버전, Weaviate 릴리스 요약표는 latest와 일치하지 않았다. 이동형 문서의 기능 설명을 각 이미지의 실제 실행 검증으로 취급하지 않는다.

일반 ARM64 지원 또는 빌드 설정과 이 후보 태그의 manifest/digest·이 장치 실행성을 구분한다. 특히 Chroma1.5.9 배포 목록에는 Windows ARM64 native wheel을 확인하지 못했고, Milvus Lite의 FAISS/PyArrow 조합도 실제 설치하지 않았다. 공급자 EC2/Cloud 벤치마크의 ms·QPS를 우리 결과로 전재하지 않았다. 기능 지원은 공식 근거, 상대적 적합성은 추론, 품질·속도·자원 우열은 미측정이라는 경계를 유지한다.

## 작업·검증 기록

- 작업 등급: 읽기 중심 설계 조사. 제품별 조사 역할과 통합 판단·독립 검토 역할을 분리했다. UI·구현·배포·모델 실행 역할은 제외했다.
- 보존 검증: 시작/종료 `.env`·Compose·Python 런타임 선언·기존 오프라인 비교 도구/fixture/test17개 파일의 SHA-256 일치, 불일치0. 문서3개 로컬 링크102개·공백/충돌 표식·최근 완료5개 검사를 통과했다. 제품 코드 변경이 없어 애플리케이션 테스트·타입/린트는 다시 실행하지 않았고, 선행 준비 도구 검사 숫자를 이번 새 실측으로 사용하지 않는다.
- 로컬 조사 증거: `.local-data/project-agent-work/vector-four-candidates-20261101/`의 제품별 조사, 독립 검토와 보존/문서 검사 결과. 비공개 원문·벡터·키는 보고서에 포함하지 않았다.
- 장시간 색인/복구 검사는 보류 유지. 실제 엔진/모델 호출0, 설치0, 운영 DB쓰기0, 기존 설정 변경0.
