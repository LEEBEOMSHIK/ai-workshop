# RAG DOCX OCR 구현·검증 기록

- 날짜: 2026-09-06
- 범위: DOCX 구조 파싱, 내장 이미지 OCR, 문서 처리 프로파일, provenance, 검색·원문 뷰어,
  관리자 전체 구성 표시
- 데이터: 비민감 합성 DOCX와 결정론적 fake OCR 결과만 사용

## 구현 결과

- Parser와 OCR을 별도 불변 `Document Processing Profile`로 저장하고 Saved RAG
  Configuration Version이 정확한 profile을 참조한다.
- 첫 OCR 구성은 PP-StructureV3 `3.7.0`, `PP-OCRv5_server_det`,
  `korean_PP-OCRv5_mobile_rec`, `SLANet_plus`다. Tesseract는 비교 평가 후보일 뿐 fallback이
  아니다.
- DOCX 문단·표·내장 이미지를 문서 순서로 파싱한다. 이미지 바이트 SHA-256, DOCX zip part,
  정규화 bbox, confidence와 검색 근거 사용 가능 여부를 Structural Element와 Evidence에
  유지한다.
- 같은 Asset Version 안의 동일 이미지 OCR 실행은 SHA-256으로 중복 제거하지만 원문 위치별
  요소는 유지한다. confidence 기준 미달 텍스트는 기록하되 chunk·검색·LLM 근거에서 제외한다.
- 허용된 사용자는 검색 근거가 가리키는 정확한 Asset Version·Projection·Element·이미지
  SHA-256 조합으로만 DOCX 이미지를 조회한다. 원문 zip 전체나 임의 part는 공개하지 않는다.
- 관리자는 문서 처리 구성의 parser route, OCR pipeline·하위 모델·언어·confidence·실행 위치·
  source/revision/license/SHA 등록 정보를 UUID와 로컬 경로 없이 확인한다.
- 사용자 원문 뷰어는 선택한 DOCX 이미지 근거의 bbox를 이미지 위에 표시한다.

## 구현 중 발견한 문제와 해결

1. Elasticsearch alias와 검색 준비 상태가 Indexing Profile 하나만 기준으로 계산돼 서로 다른
   Document Processing Profile이 같은 색인 공간을 공유할 수 있었다. 신규 index/alias identity를
   `(document processing profile, indexing profile)` 조합으로 분리하고, migration 이전 legacy
   index 이름은 혼합 없이 한 종류로만 존재할 때 읽도록 했다.
2. 사용자 뷰어가 결과 안의 첫 DOCX 이미지를 열어 선택한 근거와 다른 이미지를 표시할 수 있었다.
   선택한 evidence의 문자 범위를 포함하는 이미지 요소를 고르게 수정하고 회귀 테스트를 추가했다.
3. 전체 단위 테스트 재검증은 다른 pytest 실행과 공유하던 `backend/.pytest-tmp` 삭제가 Windows에서
   거부돼 601건 통과 뒤 52건이 fixture 준비 오류로 중단됐다. 고유 basetemp로 격리해 재실행하고
   653건 전부 통과를 확인했다. 통합 테스트는 저장소 루트에서 실행해 정본 `.env`를 로드했다.
4. 새 DOCX 이미지 endpoint가 OpenAPI 경로·binary media 계약에 빠져 있었다. 공개 경로 목록과
   PNG/JPEG 응답 스키마를 추가하고 생성 TypeScript schema를 갱신했다.

## 자동 검증

- Backend unit: `653 passed`
- DOCX OCR in-process E2E: `1 passed`
- OpenAPI contract, migration 0017/0018, exact resolver, serialization race, RAG ingestion·search와
  DOCX OCR E2E 집중 검증: `75 passed`
- Elasticsearch alias 복구와 Document Processing Profile별 색인 격리: `2 passed`
- Paddle package/import smoke: 위 집중 검증 75건 중 `2 passed`
- Backend mypy: `171 source files`, 오류 없음
- Frontend Vitest: `43 files, 200 tests passed`
- Frontend TypeScript, ESLint, OpenAPI schema 동기화, Next.js production build: 통과, `11 routes`

실제 과금 API나 외부 Provider는 호출하지 않았다. 실제 Paddle 추론도 승인된 모델 산출물
디렉터리가 아직 프로비저닝되지 않아 실행하지 않았다.

## 실제 OCR 실행 전 남은 게이트

1. 세 모델의 승인 source·정확 revision·license와 산출물 SHA-256 manifest를 확정한다.
2. `<model-cache>/ocr/<model-kind>/<artifact-sha256>` 세 경로에 산출물을 오프라인으로 배치한다.
3. 비민감 합성 DOCX로 Windows CPU 시간·메모리, 인식 텍스트, bbox 유효성과 낮은 confidence
   처리를 기록한다.
4. 같은 manifest로 Linux CPU/GPU smoke를 별도로 수행한다. Windows 결과로 Linux GPU 검증을
   대신하지 않는다.

산출물이 없거나 불일치하면 `ocr_model_artifact_missing` 또는 명시적 runtime 오류로 실패한다.
네트워크 다운로드나 다른 OCR 엔진으로 자동 전환하지 않는다.
