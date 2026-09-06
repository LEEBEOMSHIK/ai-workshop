# RAG 문서 처리·OCR 프로파일 설계

- 상태: 승인됨
- 기준일: 2026-09-06
- 범위: DOCX 구조 파싱과 내장 이미지 OCR부터 관리자 전체 구성 표시까지
- 관련 결정: `docs/decisions/0012-document-processing-and-ocr-profiles.md`
- 관련 기준선: `docs/labs/rag/design.md`

## 1. 배경과 목표

현재 RAG ingestion은 MIME 형식에 따라 TXT, Markdown과 텍스트 PDF parser를 선택한다.
실제 parser 이름과 버전은 문서 처리 기록에 남지만 Saved RAG Configuration은 parser를
고정하지 않는다. 관리자 구성 화면도 Parser를 `형식별 자동 선택`으로만 표시한다.

DOCX를 구조적으로 처리하고 내장 이미지와 향후 스캔 PDF에 OCR을 적용하려면 어떤 parser와
OCR 모델 조합이 어떤 검색 색인을 만들었는지 재현할 수 있어야 한다. 이 설계의 목표는 다음과
같다.

- Parser와 OCR을 하나의 불변 문서 처리 프로파일로 관리한다.
- OCR을 단일 모델로 오인하지 않고 파이프라인과 하위 모델을 각각 기록한다.
- Windows 로컬과 Linux 운영에서 같은 모델 artifact와 의미 설정을 사용한다.
- 문서 처리 구성이 바뀌면 새 파싱·청킹·색인 버전을 만들고 기존 결과와 섞지 않는다.
- 관리자는 전체 구성을 확인하되 일반 사용자와 공개 화면에는 안전한 표시 정보만 제공한다.
- OCR 근거를 DOCX 내장 이미지 또는 스캔 PDF 페이지의 실제 좌표로 추적한다.

## 2. 채택 방식과 대안

### 채택: 독립 문서 처리 프로파일

`document_processing` Profile Kind를 추가한다. Saved RAG Configuration은 정확한 문서 처리,
색인, 검색, 선택적 생성 프로파일 버전을 조합한다. 문서 처리 프로파일은 형식별 parser 정책과
선택적 OCR 프로파일을 포함한다.

여기서 OCR 프로파일은 별도의 최상위 Profile Kind가 아니라 Document Processing Profile 안의
typed immutable 구성이다. 관리자는 Document Processing Profile 하나를 선택하고 그 안에 고정된
OCR pipeline과 모델 binding을 전체 상세로 확인한다.

이 방식은 parser/OCR 변경이 색인 호환성에 미치는 영향을 명시하면서도 청킹·임베딩과 문서
해석 책임을 분리한다.

### 비채택: 색인 프로파일 안에 OCR 포함

구현은 단순하지만 parser, OCR, 청킹과 임베딩의 독립 평가가 어려워지고 한 구성요소의 변경이
전체 프로파일을 불필요하게 복제한다.

### 비채택: OCR 서비스만 별도 등록

실행 환경은 유연하지만 Saved RAG Configuration과 색인 Build가 정확한 OCR 결과를 고정하지
못한다. 실행 시점의 최신 OCR 모델을 암묵적으로 사용하게 될 위험이 있어 채택하지 않는다.

## 3. 구성 계층

```text
Saved RAG Configuration Version
├─ Document Processing Profile Version
│  ├─ Parser Policy
│  │  ├─ Markdown Parser
│  │  ├─ TXT Parser
│  │  ├─ PDF Text Parser
│  │  └─ DOCX Structure Parser
│  └─ OCR Profile
│     ├─ Pipeline: PP-StructureV3
│     ├─ Text Detection: PP-OCRv5_server_det
│     ├─ Text Recognition: korean_PP-OCRv5_mobile_rec
│     ├─ Table Structure: SLANet_plus
│     ├─ Language, preprocessing and confidence policy
│     └─ Runtime compatibility and artifact manifest
├─ Indexing Profile Version
│  ├─ Chunker
│  └─ Embedding Model
├─ Retrieval Profile Version
└─ Optional Generation Profile Version
```

PP-StructureV3는 단일 OCR 모델이 아니라 문서 분석 파이프라인이다. 관리자와 실행 기록은
파이프라인 이름과 검출·인식·표 구조 모델을 분리해 표시한다.

## 4. 불변 프로파일 계약

### Document Processing Profile

프로파일은 다음 의미 설정을 고정한다.

- 형식별 parser adapter 이름과 버전
- OCR을 적용할 MIME 형식과 문서 요소 종류
- OCR pipeline 이름과 package/runtime 버전
- OCR 모델 binding과 정확한 artifact revision·SHA-256
- 인식 언어와 순서
- 방향 보정, 회전, 이미지 크기와 같은 결정적 전처리 설정
- 텍스트·표 confidence 기준과 낮은 신뢰도 처리
- 표 구조 모듈 사용 조건
- OCR 출력 schema와 provenance schema 버전

비밀값, 로컬 파일 절대 경로, endpoint와 인증정보는 프로파일에 저장하지 않는다. 실행 가능한
모델 위치는 환경 설정 또는 승인된 내부 runtime registry에서 해석하고 실행 snapshot에는
안전한 deployment 표시명만 남긴다.

### Model Definition

모델 registry는 최소한 다음 OCR 역할을 구분한다.

- `ocr_text_detection`
- `ocr_text_recognition`
- `ocr_table_structure`

향후 실제 요구가 생기면 문서 layout 모델 역할을 additive하게 추가할 수 있다. 현재 DOCX 내장
이미지 처리에 사용하지 않는 수식, 인장과 차트 모델은 미리 등록하거나 화면에 노출하지 않는다.

### 기존 구성 이관

기존 저장 구성은 현재 TXT·Markdown·텍스트 PDF 동작을 표현하는 시스템 불변
`legacy-text-document-processing-v1`로 이관한다. 이 프로파일은 OCR을 사용하지 않는다.
마이그레이션은 기존 구성 의미나 기본값을 바꾸지 않고 새 참조를 채운다.

## 5. 처리와 데이터 흐름

1. Platform Asset이 파일 검증과 저장을 완료한다.
2. RAG ingestion은 저장 구성의 정확한 Document Processing Profile을 해석한다.
3. MIME 형식에 해당하는 parser adapter를 선택한다.
4. DOCX parser는 문단, 제목, 목록, 표와 내장 이미지를 문서 순서대로 추출한다.
5. 결정적 eligibility 규칙을 통과한 이미지만 OCR adapter에 전달하고 제외 사유를 기록한다.
6. OCR adapter는 선택된 pipeline과 하위 모델을 실행한다.
7. 텍스트, 표 셀, 읽기 순서, confidence와 이미지 좌표를 정규화한다.
8. parser 본문과 OCR 요소를 원래 문서 순서에 맞춘 Parsed Document로 결합한다.
9. 청커는 정상 근거로 승인된 구조 요소만 Evidence Unit과 Chunk로 만든다.
10. Index Build는 Document Processing Profile과 Indexing Profile의 정확한 버전을 모두
    fingerprint에 포함한다.
11. 검색 결과는 Asset Version, 문서 요소, 내장 이미지 또는 PDF 페이지 좌표로 왕복한다.

동일 Asset Version 안에서 원본 이미지 SHA-256과 OCR Profile Version이 같으면 OCR 산출물을
재사용할 수 있다. 다른 프로파일의 결과나 다른 Asset Version의 결과를 암묵적으로 섞지 않는다.

## 6. DOCX와 향후 스캔 PDF 경계

DOCX parser가 문단·목록·표를 직접 구조화하며 OCR이 DOCX parser를 대체하지 않는다. 내장
이미지는 package relationship과 문서 요소 순서를 보존해 추출한다. OCR provenance에는 다음을
포함한다.

- Asset Version과 DOCX element identity
- package image part identity의 안전한 내부 표현
- 원본 이미지 크기와 이미지 SHA-256
- OCR line/word 또는 table-cell 좌표와 confidence
- Document Processing/OCR Profile Version과 실행 snapshot

스캔 PDF는 후속 작업에서 페이지 rasterizer를 앞단에 추가하고 같은 OCR adapter와 정규화
schema를 재사용한다. 텍스트 layer가 있는 PDF는 기존 PDF text parser가 우선하며 자동 OCR
대체 여부를 현재 작업에서 도입하지 않는다.

## 7. 로컬·운영 공통 실행

개발 Windows와 운영 Linux는 동일한 다음 항목을 사용한다.

- PaddleOCR/PaddlePaddle의 검증·고정 버전
- PP-StructureV3 pipeline 설정
- `PP-OCRv5_server_det`
- `korean_PP-OCRv5_mobile_rec`
- `SLANet_plus`
- 모델 artifact revision과 SHA-256
- 전처리, 언어, confidence와 출력 schema

로컬은 FastAPI 요청 프로세스와 분리된 로컬 Python OCR worker를 기본 CPU로 실행한다. 로컬
개발 전체를 Docker로 강제하지 않는다. 운영은 같은 고정 dependency와 모델 manifest를 사용한
내부 Linux worker 또는 container로 실행할 수 있다. 실제 장치, OS, package build와 처리 시간은
실행 snapshot에 기록한다.

CPU와 GPU는 같은 모델 프로파일을 사용할 수 있지만 같은 품질을 가정하지 않는다. Windows CPU,
Linux CPU와 Linux GPU는 각각 승인 평가를 통과해야 한다. 승인되지 않은 장치 조합을 일반 처리
기본값으로 사용하지 않는다.

모델은 승인된 준비 단계에서만 내려받고 runtime에는 로컬 model directory를 명시한다. 운영
추론 중 인터넷 다운로드와 외부 Hosted OCR API를 허용하지 않는다.

## 8. 오류와 부분 처리

다음 상태를 구분한다.

- `document_format_unsupported`
- `document_encrypted`
- `document_corrupt`
- `embedded_image_corrupt`
- `ocr_runtime_unavailable`
- `ocr_model_artifact_missing`
- `ocr_output_invalid`
- `ocr_confidence_below_threshold`
- `ocr_table_structure_unreliable`

OCR 대상 이미지가 존재하는데 구성한 runtime이나 모델을 실행할 수 없으면 해당 문서 처리를
실패시킨다. Tesseract나 다른 모델로 조용히 전환하지 않는다.

낮은 confidence 결과는 원본 좌표와 안전한 상태를 보존하되 일반 검색 근거로 승인하지 않는다.
모든 eligible 이미지가 구성한 OCR로 실행을 완료했다면 낮은 confidence 단위가 존재해도 문서
처리는 완료될 수 있다. 이 경우 해당 단위를 색인에서 제외하고 문서·작업 상태에 경고를 남긴다.
runtime·model·출력 schema 장애로 eligible 이미지 처리를 끝내지 못한 경우에는 문서를 READY로
만들지 않는다. 관리자는 제외된 이미지와 사유를 확인할 수 있어야 하며, 제외 사실을 숨긴 채
완전한 문서처럼 표시하지 않는다.

오류 응답과 로그에는 원문, 이미지 바이트, 로컬 경로와 모델 다운로드 URL의 인증정보를 남기지
않는다. 모델이나 runtime 실패는 safe code, profile version, 단계, 대상 요소 identity와 소요
시간만 기록한다.

## 9. 관리자 화면

`/admin/rag/configurations`의 구성 순서를 다음처럼 바꾼다.

1. 문서 처리 구성
2. 색인 구성
3. 검색 구성
4. 답변 구성
5. 저장 정보

문서 처리 영역은 이해 가능한 프로파일 이름·버전, 지원 형식, Parser 요약, OCR 사용 여부와
평가 상태를 먼저 보여준다. `전체 OCR 구성 보기`를 펼치면 다음을 계층적으로 표시한다.

- pipeline 이름과 버전
- 텍스트 검출, 텍스트 인식과 표 구조 모델 이름·버전
- 한국어·영어와 언어 순서
- 전처리와 confidence 정책
- 실행 위치, 장치와 readiness
- model source, revision, SHA-256과 license 검토 상태
- 최근 평가 snapshot과 승인 상태
- 선택한 색인 프로파일과의 호환성

일반 선택 목록에는 UUID, 해시와 raw JSON을 넣지 않는다. 기술 artifact 정보는 owner 전용 상세
영역에서만 제공한다. 상세 영역도 secret reference, endpoint와 로컬 절대 경로는 반환하지 않는다.

`/admin/rag/models`에는 OCR 모델 역할과 Document Processing Profile을 등록·조회하는 영역을
추가한다. 화면이 특정 모델명을 하드코딩하지 않으며 API가 제공한 typed display metadata를
렌더링한다. 프로파일 저장은 새 불변 버전을 만들고 평가나 운영 기본값을 자동 변경하지 않는다.

## 10. 사용자와 공개 표시 경계

로그인 사용자에게는 검색 결과를 만든 Document Processing Profile의 사용자용 이름·버전,
Parser와 OCR 사용 여부, OCR 근거의 confidence 경고를 읽기 전용으로 제공한다.

공개 AI Lab에는 승인된 현재 구성의 pipeline과 OCR 모델 표시명·버전만 보여줄 수 있다. 다음은
owner 전용이다.

- 내부 UUID
- artifact SHA-256과 저장 위치
- runtime endpoint와 secret reference
- 원시 오류 진단과 내부 health identity
- 평가용 비공개 문서와 원문

공개 화면은 비공개 작업소의 실제 문서 저장소나 OCR 산출물을 직접 조회하지 않는다.

## 11. 저장과 마이그레이션 영향

구현 계획은 최소한 다음 영속 계약을 다룬다.

- Profile Kind에 `document_processing` 추가
- OCR Model Kind와 binding 역할 추가
- Saved RAG Configuration Version에 `document_processing_profile_id` 추가
- ingestion job, RAG Projection, Parsed Artifact와 Index Build에 정확한 문서 처리 프로파일
  identity 또는 동등한 immutable fingerprint 추가
- uniqueness와 재사용 key를 Asset Version, Document Processing Profile, Indexing Profile의
  정확한 조합으로 확장
- Source Location에 DOCX 내장 이미지와 OCR bbox/table-cell locator 추가
- 기존 구성과 빌드의 의미 보존 backfill

정확한 column과 constraint 변경은 현재 repository query, lock order와 supersession 계약을
확인한 구현 계획에서 결정한다. 기존 migration을 수정하지 않고 새 forward-only migration을
추가한다.

## 12. 평가와 승격 기준

공식 모델 benchmark를 프로젝트 품질 보증으로 사용하지 않는다. 비민감 고정 평가셋에서 다음을
프로파일·환경별로 기록한다.

- 한국어 CER, 영어 WER와 한·영 혼합 정확도
- 제목·문단·목록 읽기 순서
- 표 셀 텍스트와 행·열 구조 정확도
- OCR bbox와 원본 이미지 하이라이트 왕복 성공률
- eligibility와 낮은 confidence 판정의 정확성
- 문서·페이지 성공률
- 페이지·이미지별 P50/P95 처리 시간과 peak memory
- Windows CPU와 Linux CPU/GPU 결과 차이
- runtime 네트워크 차단과 artifact 무결성
- 모델·코드·artifact license와 NOTICE

Tesseract 5의 `kor+eng` 고정 구성은 오프라인 CPU 비교 기준선으로만 사용한다. 운영 자동
fallback으로 사용하지 않는다. 평가되지 않은 OCR 프로파일은 일반 처리 기본값으로 승격하지
않는다.

## 13. 수용 기준

1. 관리자가 문서 처리 프로파일을 색인 프로파일과 독립적으로 선택한다.
2. 저장 구성과 색인 Build가 정확한 Document Processing Profile Version을 재현한다.
3. 관리자 화면이 PP-StructureV3와 세 하위 모델을 서로 다른 역할로 표시한다.
4. DOCX 문단·표·내장 이미지의 원래 순서가 보존된다.
5. 정상 OCR 근거가 실제 내장 이미지 좌표로 이동하고 하이라이트된다.
6. OCR model/runtime 장애가 자동 fallback 없이 명시적으로 실패한다.
7. 낮은 confidence 결과가 정상 근거로 조용히 색인되지 않는다.
8. OCR 또는 Parser 변경이 새 파싱·청킹·색인을 만들고 기존 결과와 섞이지 않는다.
9. Windows 로컬과 Linux 운영이 같은 model artifact와 의미 프로파일을 사용한다.
10. 일반·공개 응답에 내부 UUID, artifact path, endpoint와 secret이 노출되지 않는다.
11. 기존 TXT·Markdown·텍스트 PDF 구성과 검색 결과가 이관 후에도 유지된다.
12. 단위 테스트는 실제 모델이나 네트워크 없이 실행되고 별도 smoke만 고정 모델을 사용한다.

## 14. 구현 순서

1. 정확한 PaddleOCR package/model artifact와 로컬·운영 feasibility gate
2. Profile/Model kind와 typed schema, migration 및 기존 구성 backfill
3. 문서 처리 프로파일 resolver와 ingestion/build identity 연결
4. DOCX 구조 parser와 embedded-image extraction
5. OCR runtime port, fake와 PP-StructureV3 adapter
6. OCR provenance·confidence·table-cell 정규화
7. DOCX 원문 viewer와 이미지 bbox highlight
8. 관리자 registry·구성 전체 상세 UI
9. 사용자용 안전 실행 metadata와 공개 표시 metadata
10. 단위·통합·migration·privacy·E2E 및 Windows/Linux smoke

## 15. 제외 범위

- 스캔 PDF 페이지 rasterizer의 실제 구현
- 외부 Hosted OCR API로 비공개 문서 전송
- Tesseract 자동 fallback
- 수식, 인장, 차트와 필기 인식 모델의 선제 등록
- 자동 모델 다운로드와 자동 기본 프로파일 승격
- OCR 결과를 이용한 자동 파인튜닝
- 일반 사용자의 OCR 모델·프로파일 변경
