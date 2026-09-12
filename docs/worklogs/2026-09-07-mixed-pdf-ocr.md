# 혼합 PDF 페이지 OCR 보완

## 요구와 변경

본문과 이미지가 같은 PDF 페이지에 있으면 v1이 이미지 OCR을 생략하는 누락을 보완한다.
사용자가 승인한 본문 직접 추출+이미지 영역 OCR을 `pymupdf-ocr` v2로 구현했다.
결정 정본은 [ADR 0014](../decisions/0014-scanned-pdf-ocr.md)다.

- 겹친 이미지 영역을 합쳐 제한된 크기로 렌더링한다. 원본 이미지 바이트의 선추출은 하지 않는다.
- 회전·CropBox·소수 좌표·실제 픽셀 원점을 원문 페이지 좌표로 변환한다.
- 낮은 confidence와 중복 OCR은 산출물·경고에 보존하지만 검색·LLM 근거에서는 제외한다.
- 정상적인 글자 없는 장식 이미지와 OCR 런타임 실패를 구분한다.
- 새 `pp-structure-v3-pdf-docx` v2는 draft·비기본이다. 기존 v1·저장 구성은 보존한다.
- 관리자 상세 화면은 선택된 버전의 실제 처리 범위를 표시한다.
- 로컬 앱 DB에 migration `0022_mixed_pdf_ocr_profile`을 적용했다.

## 검증

- backend unit 750건 + 합성 PDF 근거·권한 뷰어 연결 4건: 754 passed.
- frontend 46 files, 211 tests passed. TypeScript·ESLint 통과.
- backend Ruff 및 mypy 178 source files 통과.
- 독립 parser 재검증 38건, profile/resolver 38건 통과.
- 격리 PostgreSQL migration 0021·0022 upgrade/rollback 회귀 2건 통과.
  기존 프로파일·구성 보존과 신규 binding을 확인했다.
- 역할 계약 검사, AGENTS 123줄, diff 공백 검사 통과.

## 선별 문제 해결

독립 리뷰에서 native font bbox의 여백이 인접한 다른 행과 조금 겹칠 때 같은 문구를
중복으로 제외하는 결함을 재현했다. 정규화된 문자열 일치 외에 교차 면적이 작은 bbox의
50%를 초과해야 같은 위치로 판정하도록 보완했다. 인접 행 보존과 같은 위치 중복 제외를
RED→GREEN으로 확인하고 독립 재리뷰했다.

## 검증 경계

최종 실제 모델 검증은 `1 passed, 8 warnings in 109.27s`였다. 실제 owner setup·업로드·
checksum 검증·저장 구성 API·PP-StructureV3 10모델·E5·Elasticsearch READY를 통과했다.
BM25/Hybrid 각각 한국어 텍스트·표 키워드 4개와 Hybrid 의미 질문 1개를 검사했다.
반환된 근거가 실제 OCR 요소인지, 페이지·bbox와 semantic highlight가 일치하는지 확인했다.
부분 키워드에는 추측 bbox가 없고 표 셀 전체 일치에는 원본 bbox가 보존됐다.
PNG 원문 뷰어와 로그아웃 후 401도 확인했다. 종료 후 테스트 DB·색인 잔존은 각각 0개였다.
경고는 Starlette httpx 사용 중단 안내, Paddle ccache 부재와 E5 메서드명 변경 안내다.

순수 텍스트·스캔·혼합 페이지 분기는 합성 parser 회귀로 확인한다. 실제 모델 통합 검증은
`backend/tests/e2e/test_rag_mixed_pdf_actual.py`로 수행하며 별도 실행 결과를 기록한다.
이 테스트는 사용자 DB가 아닌 고유 임시 DB·색인과 합성 한국어 문서를 사용한다.
큐 전달은 실제 workflow 직접 실행으로 대체하므로 Redis 프로세스 간 전달·브라우저
상호작용·외부 LLM 답변까지 검증했다는 뜻은 아니다.

벡터 도형의 의미 이해·사진 설명 생성은 OCR과 별도다. 동일 위치 판정은 보수적인 정확
문자열 방식이며 인식 문자열이 다르면 임의로 병합하지 않는다. 실제 사용자 문서 품질과
운영 Linux·GPU 검증을 대신하지 않는다.

## 로컬 실행 인계

웹 5173·API 18000을 호스트에서 시작해 HTTP 200을 확인했고 worker ready·beat 시작도 확인했다.
기존 인프라만 사용하며 Docker image·volume을 새로 만들거나 삭제하지 않았다.
시작 중 기존 처리 프로파일 207의 READY build 한 건이 현재 canonical 색인명과 일치하지 않아
`alias_parity_invalid_build`가 발생했다. 기존 데이터·alias는 변경하지 않았으며 이 로컬 정합성
복구는 다음 작업이다. 이번 독립 v2 실제 모델 테스트에는 이 기존 데이터가 포함되지 않는다.
