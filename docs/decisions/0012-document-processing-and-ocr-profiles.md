# ADR-0012: Parser와 OCR을 독립 문서 처리 프로파일로 관리한다

- 상태: 승인됨
- 결정일: 2026-09-06

## 배경

현재 RAG ingestion은 문서 MIME 형식으로 parser를 선택하고 실제 parser identity는 문서 처리
산출물에만 기록한다. DOCX 구조 파싱과 내장 이미지 OCR을 추가하면 parser와 OCR 결과가 검색
대상 텍스트, 청크와 색인에 직접 영향을 준다. 저장된 RAG 구성과 관리자 화면이 이 구성을
고정하지 않으면 실행을 재현하거나 모델 조합을 비교할 수 없다.

PP-StructureV3는 단일 OCR 모델이 아니라 문서 분석 파이프라인이다. 따라서 pipeline과 텍스트
검출, 한국어·영어 인식 및 표 구조 모델을 하나의 모델명으로 숨기지 않아야 한다.

## 결정

- `document_processing` 불변 Profile Kind를 색인·검색·생성과 독립적으로 추가한다.
- Saved RAG Configuration은 정확한 Document Processing Profile Version을 참조한다.
- 프로파일은 형식별 parser adapter와 선택적 OCR pipeline 및 모델 binding을 고정한다. OCR
  프로파일은 별도의 최상위 Profile Kind가 아니라 Document Processing Profile의 typed immutable
  구성이다.
- 첫 OCR 조합은 PP-StructureV3의 실제 의존 그래프를 그대로 고정한다. 레이아웃 검출,
  텍스트 검출·인식, 표 분류, 유선·무선 표 구조, 유선·무선 표 셀 검출과 표 방향 분류를
  서로 다른 모델 역할로 등록한다. 표 하위 OCR이 요구하는 텍스트 줄 방향 모델도 포함한다.
- 첫 모델은 `PP-DocLayout_plus-L`, `PP-OCRv5_server_det`,
  `korean_PP-OCRv5_mobile_rec`, `PP-LCNet_x1_0_textline_ori`,
  `PP-LCNet_x1_0_table_cls`,
  `SLANeXt_wired`, `SLANet_plus`, `RT-DETR-L_wired_table_cell_det`,
  `RT-DETR-L_wireless_table_cell_det`, `PP-LCNet_x1_0_doc_ori`다.
- 수식, 인장, 차트와 region detection은 첫 프로파일에서 명시적으로 끈다. 일반 OCR의
  최상위 text-line orientation은 끄지만 표 하위 OCR이 실제로 초기화하는 전용 방향 모델은
  고정해 사용한다. 그 밖의 비활성 모듈 모델은 등록하거나 내려받지 않는다.
- Windows 로컬과 Linux 운영은 같은 모델 artifact, revision, SHA-256과 의미 설정을 사용한다.
  실제 OS와 CPU/GPU는 실행 snapshot과 환경별 평가에 기록한다.
- Parser 또는 OCR 구성이 바뀌면 새 문서 처리 프로파일과 호환되는 새 파싱·청킹·색인을 만든다.
- OCR 대상이 있는데 구성한 모델을 실행할 수 없으면 다른 OCR로 자동 전환하지 않는다.
- 낮은 confidence OCR은 일반 근거로 조용히 색인하지 않고 원본 좌표와 검토 상태를 보존한다.
- 관리자 화면은 pipeline과 하위 모델, 설정·artifact·평가 상태를 계층적으로 보여준다.
- 일반 사용자와 공개 AI Lab은 승인된 사용자용 이름·버전만 읽을 수 있다. 내부 UUID, artifact
  path, endpoint와 secret은 노출하지 않는다.
- 기존 저장 구성은 OCR이 없는 시스템 문서 처리 프로파일로 의미를 보존해 이관한다.
- 이미 적용된 v1의 모듈 플래그가 표 하위 방향 모델을 전역 비활성으로 잘못 표현한 경우 해당
  버전을 수정하지 않고 평가 실패로 남긴 뒤, 같은 10개 모델을 정확한 플래그로 결합한 v2를
  새 불변 버전으로 발행한다.

## 결과

### 장점

- 어떤 문서 해석 결과로 색인이 생성됐는지 정확히 재현할 수 있다.
- Parser/OCR과 청킹·임베딩을 독립적으로 평가하고 변경할 수 있다.
- DOCX 내장 이미지와 향후 스캔 PDF가 같은 OCR adapter와 provenance schema를 재사용한다.
- 관리자가 PP-StructureV3를 단일 OCR 모델로 오인하지 않고 전체 구성을 확인한다.

### 비용

- profile/model kind, 저장 구성, ingestion/build identity와 Source Location migration이 필요하다.
- 기존 구성과 Build에 문서 처리 identity를 안전하게 backfill해야 한다.
- Windows CPU와 Linux CPU/GPU 환경을 각각 평가·승인해야 한다.
- 기존 세 모델 가정보다 모델 저장 공간과 CPU 처리 시간이 증가한다.

## 비채택 대안

- Indexing Profile에 Parser/OCR을 포함: 문서 해석과 청킹·임베딩의 책임이 결합돼 채택하지 않는다.
- 최신 OCR 서비스를 실행 시점에 선택: 저장 구성과 색인의 재현성을 깨뜨려 채택하지 않는다.
- Tesseract 자동 fallback: 구성한 모델의 장애를 숨기고 결과 의미를 바꾸므로 채택하지 않는다.
