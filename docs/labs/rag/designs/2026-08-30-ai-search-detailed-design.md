# 자산운용 문서 RAG AI 검색 상세 설계

- 상태: 사용자 검토 대기
- 기준일: 2026-08-30
- 상위 설계: [자산운용 문서 RAG AI 검색 설계](../design.md)
- 관련 결정: [ADR-0002 로컬 우선 데이터 경계](../../../decisions/0002-local-first-data-boundary.md), [ADR-0003 Hybrid retrieval 기준선](../../../decisions/0003-hybrid-retrieval-baseline.md)

## 1. 목표

첫 구현은 자산운용 전문 문서에서 사용자의 권한 범위 안에 있는 정확한 근거를 찾고, 원문 위치와 의미 하이라이트를 함께 보여주는 AI 검색이다.

성공한 검색은 다음 질문에 답할 수 있어야 한다.

1. 어떤 문서와 불변 버전에서 찾았는가?
2. 어느 페이지, 문단, 목록 항목 또는 표 셀인가?
3. 정확한 문자열 일치인가, 의미상 관련된 구간인가?
4. 어떤 파서, 청커, 임베딩과 검색 구성으로 결과를 만들었는가?
5. 같은 문서 스냅샷과 구성으로 결과를 재현할 수 있는가?

첫 버전은 자동 투자 판단, 투자 추천, 자동매매, 자율 에이전트 리서치와 LLM 생성 답변을 포함하지 않는다.

## 2. 확정 용어

### 검색 엔진과 검색 구성요소

- **Elasticsearch**: 문서와 벡터 검색을 실행하는 검색 엔진이다.
- **BM25**: Elasticsearch가 실행하는 sparse 검색 및 점수 계산 방식이다. 학습 모델이 아니다.
- **Bi-encoder**: 문서와 질의를 벡터로 변환하는 임베딩 모델이다.
- **Dense Retriever**: bi-encoder 벡터를 이용해 의미상 가까운 청크를 찾는 검색 구성요소다.
- **Hybrid Retriever**: BM25 Retriever와 Dense Retriever의 결과를 애플리케이션에서 RRF로 결합한 검색 구성이다.
- **Reranker**: 후보 검색 결과를 다시 정렬하는 선택 구성요소다. 첫 기준선에는 포함하지 않는다.
- **LLM**: 근거를 바탕으로 생성 답변을 작성할 수 있는 모델이다. 첫 검색 순위와 첫 답변에는 사용하지 않는다.

### 모델, 원자 프로파일과 저장된 RAG 구성

    Model Definition
      ├─ embedding
      ├─ reranker
      └─ llm

    Atomic Profile
      ├─ Indexing Profile
      ├─ Retrieval Profile
      └─ Generation Profile

    Saved RAG Configuration
      └─ 위 프로파일의 불변 버전을 조합한 사용자 저장 구성

- **Model Definition**은 개별 학습 모델의 저장소, 리비전, 차원, 토큰 한도, 실행 위치와 데이터 정책을 기록한다.
- **Indexing Profile**은 파서, 청커, 임베딩 모델과 색인 파라미터를 묶는다.
- **Retrieval Profile**은 BM25, dense 후보 수, RRF와 선택적 리랭커를 묶고 호환되는 Indexing Profile을 참조한다.
- **Generation Profile**은 LLM, 프롬프트와 근거 정책을 묶는다. 첫 버전에서는 사용하지 않는다.
- **Saved RAG Configuration**은 사용자가 이름을 붙여 저장하고 비교하는 최상위 구성이다. 모델 자체가 아니다.

저장된 구성을 수정하면 기존 버전을 덮어쓰지 않고 새 버전을 만든다. 검색 실행과 평가 실행은 항상 정확한 구성 버전을 참조한다.

## 3. 범위와 형식 확장 순서

첫 수직 슬라이스는 업로드부터 원문 하이라이트까지 전체 흐름을 다음 형식으로 완성한다.

1. Markdown
2. TXT
3. 텍스트가 포함된 PDF

이후 같은 공통 문서 모델과 검색 계약을 유지하며 다음 순서로 확장한다.

1. DOCX
2. 스캔 PDF와 OCR
3. PPTX, XLSX, HTML과 HWPX

형식 수를 먼저 늘리지 않는다. 첫 세 형식에서 provenance, 권한 필터, 검색 정확도와 하이라이트를 끝까지 검증한 뒤 파서 어댑터를 추가한다.

## 4. 모듈 경계

### Platform 책임

- platform/identity: 로그인 사용자와 역할
- platform/workspaces: 전사, 개인, 임시 지식 공간과 접근권한
- platform/assets: 원본 파일, 문서, 불변 버전과 활성 버전
- platform/jobs: 영속 작업 상태, 멱등 생성, 재시도와 실행 이력

Platform은 RAG 파서, 청커, 검색 모델과 Elasticsearch 색인 구조를 알지 않는다.

### Labs/RAG 책임

    labs/rag/
    ├─ documents       공통 문서 모델, 구조 요소와 provenance
    ├─ ingestion       RAG 처리 상태와 단계 오케스트레이션
    ├─ parsing         형식별 파서 어댑터
    ├─ chunking        검색 청크와 근거 단위 생성
    ├─ indexing        색인 버전, Elasticsearch projection과 활성화
    ├─ retrieval       BM25, dense, RRF와 중복 제거
    ├─ highlighting    정확 일치와 의미 하이라이트
    ├─ models          모델, 원자 프로파일과 저장된 RAG 구성
    ├─ experiments     구성 비교 실행과 재현 정보
    └─ evaluation      검색, 근거, 하이라이트와 접근권한 평가

generation과 실제 RAG 에이전트는 후속 단계에서 추가한다.

### 외부 구성요소

- **PostgreSQL**: 정본 메타데이터, provenance, 처리 상태, 구성 버전과 실행 이력
- **객체 저장소**: 원본, 파싱 결과, 페이지 이미지와 뷰어 자산
- **Elasticsearch**: BM25와 벡터 검색을 위한 재생성 가능한 projection
- **Redis**: Celery 작업 메시지를 전달하는 broker
- **Celery worker**: 파싱, 청킹, 임베딩, 색인과 일괄 평가 실행
- **로컬 모델 런타임**: 문서 및 질의 임베딩

PostgreSQL과 객체 저장소가 정본이다. Elasticsearch 색인은 정본 데이터와 프로파일에서 다시 만들 수 있어야 한다.

## 5. 문서 처리 상태와 비동기 실행

RAG 문서 버전은 Asset Version과 Indexing Profile Version의 조합으로 처리 상태를 가진다.

    PENDING
      -> PARSING
      -> CHUNKING
      -> EMBEDDING
      -> INDEXING
      -> READY

종료 예외 상태는 다음과 같다.

- FAILED: 일반 검색에 사용할 수 없다.
- PARTIAL_READY: 진단 또는 명시적 실험에서만 사용할 수 있다.

일반 검색은 READY인 문서 버전과 활성 색인 버전만 사용한다.

### 처리 흐름

    Asset Version 등록 및 무결성 확인
      -> RAG job 생성
      -> 원본 파싱
      -> 공통 구조와 provenance 저장
      -> 검색 청크와 근거 단위 생성
      -> 문서 임베딩 생성
      -> Elasticsearch projection 작성
      -> 청크 수, 벡터 수와 provenance 검증
      -> 색인 버전 원자적 활성화

Celery 메시지에는 원문 본문을 넣지 않고 job_id와 최소 라우팅 정보만 넣는다. 영속 상태와 오류는 PostgreSQL에 기록한다.

각 단계는 다음 멱등 키를 기준으로 중복 실행을 막는다.

    asset_version_id + indexing_profile_version_id + stage

재시도는 완성된 이전 단계를 재사용할 수 있지만, 파서나 모델을 조용히 다른 구현으로 바꾸지 않는다.

사용자 검색 요청은 Celery로 보내지 않고 동기 API 경로에서 처리한다.

## 6. 공통 문서 모델과 provenance

    Document
    └─ DocumentVersion
       └─ StructuralElement
          ├─ Heading
          ├─ Paragraph
          ├─ ListItem
          ├─ Table / Row / Cell
          ├─ Figure
          └─ TextSpan

모든 구조 요소는 가능한 범위에서 다음 정보를 가진다.

- Asset, Document와 Document Version 식별자
- Workspace와 Folder 식별자
- 페이지, 문단, 표, 행·열·셀 위치
- 정규화 전후 문자 시작 및 종료 위치
- PDF 원문 좌표
- 파서 또는 OCR 구현과 버전
- 파싱 또는 OCR 신뢰도
- 원본 콘텐츠 해시

파서 출력은 형식별 객체를 직접 검색 계층에 넘기지 않고 공통 문서 모델로 변환한다.

## 7. 검색 청크와 근거 단위

검색과 사용자 근거 표시에 서로 다른 크기의 단위를 사용한다.

### Retrieval Chunk

- BM25와 dense retrieval의 색인 및 순위 단위다.
- 제목, 절 경로와 주변 문맥을 포함한다.
- 문장이나 표 셀의 경계를 깨지 않는 구조 기반 청킹을 우선한다.
- 초기 E5 기준 목표 크기는 약 380 tokens이며 실제 값은 평가로 조정한다.

### Evidence Unit

- 사용자에게 인용하고 하이라이트하는 최소 의미 단위다.
- 문장, 목록 항목, 표 셀 또는 짧은 문단이 될 수 있다.
- 부모 Retrieval Chunk와 원문 구조 요소를 모두 참조한다.

청크만 저장하고 나중에 원문 위치를 추측하지 않는다. 청크와 Evidence Unit을 만들 때 원문 범위와 좌표를 함께 확정한다.

## 8. 색인 버전과 Elasticsearch projection

Indexing Profile Version이 달라지면 별도 Index Build를 만든다.

다음 변경은 새 색인 버전을 요구한다.

- 파서의 검색에 영향을 주는 변경
- 청킹 방식, 크기 또는 겹침 변경
- 임베딩 모델 또는 고정 리비전 변경
- 벡터 차원, pooling 또는 normalization 변경
- Elasticsearch mapping의 호환되지 않는 변경

LLM, 프롬프트, RRF k와 후보 수 변경은 문서 재색인을 요구하지 않는다.

Elasticsearch 문서에는 최소한 다음 검색 필드를 둔다.

- BM25 대상 원문과 제목·절 경로
- dense vector
- Document, Version, Chunk와 Evidence Unit 식별자
- Workspace, Folder와 접근권한 필터 키
- Index Build와 Profile Version 식별자
- 활성 및 처리 상태
- 페이지와 구조 위치

하나의 불변 물리 색인은 하나의 문서 projection과 Index Build만 포함한다. 반면
Indexing Profile의 활성 읽기 alias는 단일 물리 색인이 아니라 현재 검색 가능한
projection 전체를 나타내며, 서로 다른 문서의 여러 정확한 물리 색인을 동시에 가리킬
수 있다. alias 교체 대상은 해당 프로파일에서 `READY`이고 소유 Document의 현재 활성
Asset Version에 속한 build 전체와, 검증을 마치고 지금 활성화하는 prepared build다.

활성화는 프로파일 행 잠금을 직렬화 경계로 사용한다. 잠금 안에서 정본 PostgreSQL
상태로 전체 대상 집합을 계산하고 Elasticsearch alias를 그 집합으로 원자적으로
교체한 뒤, alias가 정확히 같은 물리 색인 집합을 가리키는지 확인하고 DB의
`is_active` 플래그를 같은 집합과 일치시킨다. 새 문서 버전이 활성화되면 이전 버전의
물리 색인은 alias와 활성 플래그에서 제거하되 다른 문서의 활성 물리 색인은 유지한다.
Elasticsearch 교체 뒤 DB commit이 실패한 재시도도 같은 정본 집합으로 수렴하며,
단일 projection용 편의 색인 경로의 기존 대상 합치기는 이 교체 판단에 사용하지 않는다.

다중 활성 build를 허용하는 스키마에서 이전 단일 활성 제약으로 downgrade할 때는
프로파일별 `updated_at DESC, created_at DESC, id DESC` 순서의 첫 build만 활성으로
남기고 나머지를 명시적으로 비활성화한 뒤 제약을 복원한다. 이 downgrade는 검색 집합을
축소하므로 운영 전 별도 확인이 필요한 호환성 동작이다. migration은 Elasticsearch에
접근하지 않으므로 downgrade 직후에는 프로파일별 alias도 DB에 남은 단일 활성 build로
원자적으로 재조정하고 정확한 대상을 확인해야 한다. 이 재조정이 끝나기 전에는 단일
활성 build를 가정하는 이전 애플리케이션 버전을 시작하지 않는다.

BM25와 dense 검색에는 동일한 Workspace, Folder, 권한, 활성 버전과 상태 필터를 검색 전에 적용한다.

## 9. Hybrid 검색 흐름

1. 호출 사용자와 검색 범위 확정
2. 허용 Workspace, Folder와 문서 버전 필터 생성
3. 질의 정규화
4. 선택 구성에 필요한 경우 질의 임베딩 생성
5. Elasticsearch에서 BM25와 dense 검색 병렬 실행
6. Python 애플리케이션 계층에서 RRF 결합
7. 비활성 버전과 중복 청크 제거
8. 상위 청크 안에서 Evidence Unit 선택
9. 근거 충분성 판정
10. 최상위 근거와 관련 문서 목록 반환

첫 기준선의 RRF 점수는 각 검색 경로의 순위에 기반한다.

    RRF score(item) = Σ 1 / (k + rank)

초기 프로파일은 k=60을 사용하고 평가 결과에 따라 새 Retrieval Profile Version으로 조정한다.

Elasticsearch의 유료 내장 RRF 기능에 의존하지 않는다. BM25와 벡터 검색 결과를 애플리케이션이 결합해 로컬 개발과 배포 라이선스의 예측 가능성을 유지한다.

일반 hybrid 검색에서 한 검색 경로가 실패하면 다른 경로로 조용히 축소하지 않는다. 검색 실패를 명시적으로 반환한다. BM25-only 실행은 별도 저장 구성으로 선택한다.

## 10. 근거 우선 응답 계약

첫 버전은 LLM 생성 답변이 아니라 검색된 원문의 발췌 근거를 최상단 답변으로 사용한다.

응답 판정은 두 상태다.

- SUPPORTED: 질의에 직접 답하는 근거 단위가 있고 원문 위치를 확인할 수 있다.
- INSUFFICIENT_EVIDENCE: 관련 문서는 찾았지만 직접 답할 근거가 부족하거나 provenance 신뢰도가 기준을 충족하지 못한다.

SUPPORTED 결과는 다음을 포함한다.

- 정확한 원문 인용
- 문서명과 불변 버전
- Workspace와 Folder 영역
- 페이지, 절, 문단 또는 표 셀 위치
- 하이라이트 범위 또는 좌표
- 사용한 Saved RAG Configuration Version
- 관련 문서 목록

관련 문서 목록이 존재한다는 이유만으로 SUPPORTED로 판정하지 않는다.

서로 충돌하는 근거는 하나의 결론으로 합성하지 않는다. 출처별 근거를 분리해 표시하고 충돌 상태를 알린다.

## 11. 의미 하이라이트

BM25의 정확한 문자열 일치와 의미 하이라이트를 데이터와 UI에서 구분한다.

- keyword: 질의 토큰 또는 정규화된 정확 일치 범위
- semantic: 상위 Retrieval Chunk 안에서 질의와 의미상 가장 관련된 Evidence Unit

벡터 필드 자체에 대한 Elasticsearch 하이라이트에 의존하지 않는다. 애플리케이션은 Evidence Unit 점수와 저장된 provenance를 이용해 하이라이트 범위를 만든다.

PDF는 원본 페이지 좌표를 사용한다. Markdown, TXT와 DOCX는 통합 뷰어의 구조 요소 및 문자 범위를 사용한다.

낮은 파싱 신뢰도, OCR 신뢰도 또는 불완전한 좌표는 경고와 함께 반환하고 정상 좌표처럼 표시하지 않는다.

## 12. 초기 모델 비교

### Model A: multilingual-e5-base

- 첫 dense 기준선
- 다국어 문서와 질의 지원
- 최대 입력 512 tokens
- 초기 Retrieval Chunk 목표 약 380 tokens
- 모델 등록 시 저장소와 리비전, pooling, normalization, query/document prefix, device와 dtype을 고정

현재 저장소의 baseline Indexing Profile Version 1에 있는 600-token 설정은 1단계 기반 예시다. 첫 AI 검색 구현은 이를 수정하지 않고 약 380-token 목표를 가진 새 Indexing Profile Version을 만든다.

### Model B: BAAI/bge-m3

- 두 번째 dense 비교 모델
- 최대 입력 8192 tokens
- 첫 비교에서는 dense output만 사용
- sparse와 ColBERT 기능은 BM25 기준선과 원인 분리를 위해 사용하지 않음
- 모델 등록 시 저장소와 리비전, 차원, 최대 토큰, pooling, normalization, device와 dtype을 고정

첫 비교 대상은 다음 세 가지다.

    BM25 기준선
    BM25 + multilingual-e5-base + RRF
    BM25 + BAAI/bge-m3 dense + RRF

리랭커와 LLM은 위 기준선 평가가 끝난 뒤 별도 실험으로 추가한다.

## 13. 저장된 RAG 구성

사용자는 다음 항목을 조합해 이름이 있는 Saved RAG Configuration을 만든다.

- Indexing Profile Version
- Retrieval Profile Version
- Answer Policy Version
- 선택적 Generation Profile Version

첫 버전에서 Generation Profile은 비어 있고 Answer Policy는 근거 발췌 방식으로 고정된다.

### 저장 규칙

- 시스템이 미리 제공하는 목록은 BM25 기준선 하나뿐이다.
- E5, BGE-M3와 이후 모델 조합은 사용자가 실제로 저장한 뒤 목록에 나타난다.
- 편집 중인 초안은 운영 검색과 평가에 사용하지 않는다.
- 저장은 불변 Configuration Version을 생성한다.
- 저장만으로 운영 기본값이 바뀌지 않는다.
- 비교 실행은 저장된 구성만 참조한다.
- 평가를 통과한 구성만 승인 절차를 거쳐 운영 기본값으로 승격할 수 있다.

기존 Indexing, Retrieval, Generation 원자 프로파일은 재현 가능한 기술 설정으로 유지한다. 사용자 화면의 Saved RAG Configuration은 이들을 조합하는 별도 애플리케이션 개념이다.

BM25 기준선도 파서와 청킹을 재현하기 위해 Indexing Profile Version을 참조하되 dense 결과는 사용하지 않는다. Retrieval 알고리즘만 비교할 때는 같은 Indexing Profile과 문서 스냅샷을 사용한다. 임베딩 또는 청킹까지 바꾸는 비교는 별도의 end-to-end 구성 비교로 기록한다.

## 14. 구성 스튜디오 화면

### RAG 구성 탭

- 왼쪽에는 BM25 기준선과 사용자가 저장한 구성만 표시한다.
- 새 조합 만들기는 운영 설정과 분리된 초안을 연다.
- 색인 구성은 Parser, Chunker와 Embedding Model을 선택한다.
- 검색 구성은 BM25, 연결된 Dense Retriever, RRF와 이후 Reranker를 선택한다.
- 답변 구성은 첫 버전의 근거 판정과 인용 정책을 보여준다.
- 임베딩 또는 청킹 변경 시 새 색인 버전이 필요함을 저장 전에 알린다.
- 구성 저장과 저장하고 비교에 추가를 구분한다.

### 비교 실험 탭

- BM25 기준선을 항상 비교 기준으로 포함한다.
- 동일 문서 스냅샷, 질의 세트와 호출 권한을 사용한다.
- 측정되지 않은 점수는 임의 값 대신 평가 전으로 표시한다.
- 평가 결과와 실패 사례를 구성 버전에 연결한다.
- 필수 평가를 통과하기 전에는 운영 승격 동작을 비활성화한다.

### 모델 레지스트리 탭

- embedding, reranker와 llm 같은 개별 학습 모델만 표시한다.
- BM25와 RRF는 검색 방식이므로 모델 목록에 표시하지 않는다.
- 저장소, 리비전, 실행 위치와 데이터 반출 정책을 확인할 수 있어야 한다.

## 15. 평가와 운영 승격

평가는 고정된 다음 입력을 기록한다.

- 문서와 활성 버전 스냅샷
- 질의와 정답 Evidence Unit
- 호출 사용자 또는 권한 시나리오
- Saved RAG Configuration Version
- 실행 환경과 모델 런타임

필수 지표는 다음과 같다.

- Recall@K
- MRR
- nDCG
- SUPPORTED 정밀도와 잘못된 근거 비율
- 의미 하이라이트 범위 정확도
- P50과 P95 검색 지연시간
- 접근권한 누출 건수
- 같은 입력과 구성의 재현 가능성

정량 임계값은 평가 데이터셋과 BM25 측정값 없이 임의로 정하지 않는다. 대신 버전이 있는 Evaluation Policy에 임계값을 기록하기 전에는 어떤 구성도 passed 또는 운영 기본값이 될 수 없다.

접근권한 누출은 허용치가 0건이다. 필수 평가 중 하나라도 실패하면 전체 승격을 막는다.

가장 높은 단일 검색 점수가 아니라 근거 정확도, 접근권한, 지연시간과 재현 조건을 모두 통과한 구성만 최적 후보로 취급한다.

## 16. 오류 처리

- 암호화, 손상, 미지원 형식과 파서 내부 오류를 구분한다.
- 자동 재시도 횟수와 마지막 오류를 영속 작업 이력에 남긴다.
- 프로파일 호환성 오류는 작업 시작 전에 거부한다.
- 벡터 차원과 Elasticsearch mapping이 다르면 색인 활성화를 막는다.
- 청크, 벡터와 provenance 개수 검증이 실패하면 READY로 전환하지 않는다.
- 일반 검색에서 권한 필터를 만들 수 없으면 검색을 실행하지 않는다.
- hybrid의 한 경로 실패를 정상 검색 결과처럼 반환하지 않는다.
- INSUFFICIENT_EVIDENCE는 시스템 오류가 아니라 정상적인 근거 부족 결과다.

## 17. 검증 전략

### 단위 테스트

- 공통 문서 모델과 provenance
- 구조 기반 청킹과 Evidence Unit 경계
- 프로파일 및 Saved RAG Configuration 호환성
- RRF 계산, 중복 제거와 근거 충분성 판정
- 정확 일치와 의미 하이라이트 구분

### 통합 테스트

- Asset Version에서 파싱 산출물과 색인 활성화까지
- PostgreSQL, 객체 저장소와 Elasticsearch projection 일치
- BM25와 dense에 동일한 권한 필터 적용
- Celery 재시도와 멱등성
- 색인 버전 교체 중 검색의 원자성

### End-to-end 테스트

- 전사, 개인과 임시 문서 검색 범위 분리
- 새 첨부 문서와 기존 문서 동시 검색
- 근거 선택에서 원문 위치 이동과 하이라이트
- Saved RAG Configuration 저장, 비교, 평가와 승격 차단
- 권한 밖 문서가 검색 후보, 관련 목록과 로그에 나타나지 않음

단위 테스트는 외부 네트워크와 실제 모델 다운로드 없이 실행한다. 실제 모델과 Elasticsearch를 사용하는 검증은 명시적 통합 또는 smoke 단계로 분리한다.

## 18. 구현 순서 제약

구현 계획은 다음 의존 순서를 따라야 한다.

1. 공통 문서 모델과 Markdown/TXT/텍스트 PDF 파서
2. Retrieval Chunk, Evidence Unit과 provenance
3. 색인 버전과 Elasticsearch BM25 projection
4. E5 임베딩과 dense projection
5. Python RRF와 검색 API
6. 근거 충분성, 의미 하이라이트와 검색 UI
7. Saved RAG Configuration과 비교 평가
8. DOCX
9. 스캔 PDF와 OCR

각 단계는 다음 단계 없이도 독립적으로 검증 가능한 수직 또는 기반 슬라이스로 나눈다.

## 19. 완료 기준

- 첫 세 형식에서 업로드부터 원문 하이라이트까지 provenance가 끊기지 않는다.
- BM25와 dense 검색 전에 동일한 권한 및 범위 필터가 적용된다.
- BM25 기준선과 두 dense 모델 구성을 동일 평가 입력에서 비교할 수 있다.
- 관련 문서가 있어도 직접 근거가 없으면 INSUFFICIENT_EVIDENCE를 반환한다.
- 임베딩 또는 청킹 변경이 기존 색인을 덮어쓰지 않는다.
- 사용자가 만든 RAG 구성만 저장 목록과 비교 대상에 추가된다.
- 평가되지 않은 구성은 운영 기본값으로 승격되지 않는다.
- 일반 검색에서 비공개 원문이 외부 모델 API로 전송되지 않는다.

## 20. 기술 참고

- [Elasticsearch hybrid search](https://www.elastic.co/docs/solutions/search/hybrid-search)
- [Elasticsearch RRF 문서](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/rrf.html)
- [Elasticsearch 라이선스 FAQ](https://www.elastic.co/pricing/faq)
- [Celery 소개](https://docs.celeryq.dev/en/main/getting-started/introduction.html)
- [Celery broker와 backend](https://docs.celeryq.dev/en/main/getting-started/backends-and-brokers/)
- [Redis job queue 사용 사례](https://redis.io/docs/latest/develop/use-cases/job-queue/)
- [multilingual-e5-base 모델 카드](https://huggingface.co/intfloat/multilingual-e5-base)
- [BAAI/bge-m3 모델 카드](https://huggingface.co/BAAI/bge-m3)
