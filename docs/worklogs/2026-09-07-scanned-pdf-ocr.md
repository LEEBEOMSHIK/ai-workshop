# Windows 스캔 PDF OCR 구현 검증

- 결정: [ADR 0014](../decisions/0014-scanned-pdf-ocr.md).
- 별도 Linux 서버 없이 Windows 호스트에서 진행했다. native Linux 검증은 운영 준비 시 재개한다.
- 새 `pymupdf-ocr` v1 route와 불변 `pp-structure-v3-pdf-docx` v1 프로파일을 추가했다.
  기존 프로파일·저장 구성·기본값은 보존한다.
- 페이지 raster 상한, 회전·CropBox 좌표, 표 셀·confidence provenance, 낮은 confidence의
  근거 제외, 실패 코드와 임시 PNG 정리를 구현했다. 관리자에는 저장된 설정을 표시한다.

## 검증 결과

- backend unit: 718 passed.
- 합성 PDF parser→chunker→semantic highlight→권한 검사 원문 뷰어: 4 passed.
- 실제 Windows PP-StructureV3: 합성 한국어 텍스트·표 PDF 2페이지 추출, bbox 범위 검사
  1 passed in 121.70s. 고정 10개 모델 무결성 확인. 외부 모델 API 호출 없음.
- 격리 PostgreSQL: migration upgrade/rollback·기존 프로파일 보존·10개 binding 1 passed.
  검증 DB는 테스트 종료 후 정리했다.
- frontend: 46 files, 207 tests passed. TypeScript·ESLint 통과.
- backend Ruff 통과, mypy 178 source files 통과.
- 독립 리뷰 지적을 수정하고 최종 읽기 전용 리뷰에서 추가 차단 결함 없음.
- 로컬 앱 DB에 0020→0021 migration을 적용했다. 기존 구성·기본값은 바꾸지 않았다.

## 선별 이슈와 해결

1. PDF 텍스트 판정 시 이미지 바이트가 자원 검사 전에 추출될 수 있었다.
   `TEXT_PRESERVE_IMAGES`를 끄고 렌더 전 상한 검사를 유지했으며 회귀 테스트를 추가했다.
2. worker가 OCR 오류를 일반 ingestion 오류로 축약했다.
   원문 메시지는 노출하지 않고 안전한 OCR 오류 코드만 보존하도록 수정했다.
3. DB 검증 당시 기존 인프라가 중지돼 기존 PostgreSQL·Redis·Elasticsearch만 재시작했다.
   Docker 이미지 빌드나 volume 삭제는 수행하지 않았다.

## 다음 확인과 한계

- 실제 사용자 문서의 업로드→Elasticsearch 색인→검색→원문 이동 전체 흐름은 다음 작업이다.
  합성 데이터 통과를 실제 문서 정확도나 운영 품질 보증으로 해석하지 않는다.
- 텍스트와 그림이 같은 페이지에 있을 때 그림 추가 OCR은 미지원이다.
- Linux native·GPU 추론 및 실제 외부 LLM API 답변 검증은 포함하지 않았다.
- 새 프로파일은 평가 전 draft이며 관리자가 새 저장 구성에서 명시 선택해야 한다.
