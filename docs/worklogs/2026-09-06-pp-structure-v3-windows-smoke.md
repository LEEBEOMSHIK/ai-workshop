# PP-StructureV3 고정 모델·Windows CPU 검증

- 일자: 2026-09-06
- 범위: DOCX 내장 이미지용 PP-StructureV3 전체 모델 구성과 실제 로컬 추론
- 환경: Windows, Python 3.13, CPU

## 결론

PP-StructureV3 3.7.0의 표 인식을 실제로 초기화하면 처음 예상한 레이아웃·검출·인식 세 모델만으로
동작하지 않는다. 일반 OCR, 표 분류, 유선·무선 표 구조·셀 검출, 표 방향 및 표 하위 OCR의
text-line orientation까지 총 10개 고정 모델이 필요하다. 모든 모델을 공식 PaddlePaddle 저장소의
정확한 40자리 revision과 Apache-2.0 license로 고정하고, 실행 파일별 크기와 SHA-256을 하나의
매니페스트에 기록했다.

## 구현 계약

- 정본: `model-profiles/rag/ocr/pp-structure-v3-v1.json`
- 고정 런타임: `paddleocr==3.7.0`, `paddlepaddle==3.2.2`, `paddlex[ocr]==3.7.2`
- 전체 매니페스트 파일 크기: 886,506,913 bytes
- 설치 경로: `.local-data/models/ocr/<model-kind>/<inference-weight-sha256>`
- 실행 중 다운로드와 다른 OCR/Tesseract 자동 대체는 금지한다.
- 프로비저닝은 모든 source 파일을 먼저 검증한 뒤 원자적으로 설치하고, 기존 최종 경로도 다시
  검증한다. `artifact_sha256`은 `inference.pdiparams`의 SHA-256과 정확히 같아야 한다.
- OCR adapter는 문서 이미지마다 모델을 다시 초기화하지 않고 worker의 adapter 수명 동안 동일한
  고정 runtime을 재사용한다.

## 마이그레이션 정합성

`0019_pp_structure_v3`은 10개 모델과 10개 바인딩을 가진 비기본 초안 v1을 추가했다. 실제
초기화 과정에서 v1의 `disabled_modules`가 표 하위 방향 모델까지 비활성인 것처럼 표현하는 의미
오류를 발견했다. 적용된 v1을 수정하지 않고 `failed` 이력으로 보존했으며,
`0020_pp_structure_profile`에서 다음을 구분하는 비기본 초안 v2를 새로 추가했다.

- 활성: `table_ocr_textline_orientation`
- 비활성: `general_ocr_textline_orientation`

로컬 DB는 `0020_pp_structure_profile (head)`이며 v1·v2 모두 10개 바인딩, 상태는 각각
`failed`와 `draft`로 확인했다.

## TDD에서 발견한 실패와 해결

1. PaddleOCR 패키지만으로는 PP-Structure 파이프라인 의존성이 부족했다.
   `paddlex[ocr]==3.7.2`를 명시했다.
2. 표 하위 OCR이 `PP-LCNet_x1_0_textline_ori`를 별도로 초기화했다. 열 번째 모델 역할과 로컬
   디렉터리 인자를 추가했다.
3. 일반 텍스트 결과에는 `table_res_list` 키가 없을 수 있었다. 누락을 잘못된 출력으로 보지 않고
   빈 표 결과로 정규화했다.
4. 이미지마다 10개 모델을 다시 초기화했다. adapter runtime을 1회 초기화해 재사용하도록 했다.
5. 매니페스트의 최종 디렉터리 식별 SHA와 실제 weight SHA가 달라도 설치되던 경계를 회귀
   테스트로 차단했다.
6. 로컬 DB 증거를 확인해 v1의 실제 10개 바인딩을 보존하고, 의미 플래그 수정만 v2로 발행했다.

## 실제 추론 결과

매니페스트의 10개 모델을 로컬 불변 경로에서 모두 초기화했으며 네트워크 fallback은 없었다.

- 합성 한국어 이미지: `운용`, `7%` 인식과 정규화 bbox 확인
- 합성 표 이미지: `항목/비율`, `주식/7%`, `채권/20%`의 표 셀 텍스트와 정규화 bbox 확인
- 명령 결과: `3 passed, 1 warning in 78.11s`
- 경고: 선택적 컴파일 캐시 도구 `ccache` 미설치 안내이며 추론 결과에는 영향을 주지 않았다.

## 자동 검증

- OCR·프로파일·DOCX 집중 백엔드: 34 passed
- 전체 백엔드 unit: 661 passed
- 마이그레이션 0019/0020: 2 passed
- Ruff: 전체 backend 통과
- mypy: 172 source files 통과
- 프론트엔드: 43 files, 200 tests 통과
- TypeScript, ESLint, OpenAPI 동기화, Next.js production build 통과

첫 unit 실행의 1건 실패는 루트 `.env` 값이 기본값 검증에 주입된 실행 위치 문제였고, 정본
`backend` 작업 디렉터리 재실행에서는 기존 관리자 ACL의 `.pytest-tmp`가 59건의 fixture 오류를
냈다. 정책상 해당 경로를 삭제하지 않고 새 basetemp를 지정해 661건을 모두 통과시켰다.

## 보존과 후속 작업

최종 불변 OCR 경로는 실행 의존성이므로 보존한다. 준비용 `.local-data/models/p`와 과거 staging
경로는 최종 검증 후 정리 후보일 뿐이며, 이번 작업에서는 `CACHE_POLICY.md`의 정확한 용량 조사와
명시 승인 없이 삭제하지 않았다. 다음 형식 확장은 같은 OCR adapter를 사용하는 스캔 PDF이며,
그 전에 Linux CPU/GPU에서 동일 매니페스트 호환성을 별도 검증한다.
