# 공개 개발·실험 기록 — Publishing 기반 계약

- 상태: 기반 계약 구현·자동 검증·독립 최종 재검토 완료
- 설계: [공개 관리](../superpowers/specs/2026-09-07-public-study-management-design.md)
- 계획: [순수 계약 구현](../superpowers/plans/2026-09-07-publishing-contracts.md)
- 결정: [ADR 0019](../decisions/0019-public-study-snapshots.md)

## 구현 범위

`platform/publishing/package.py`는 공개용 필드만 받는 불변 snapshot과 canonical UTF-8 JSON,
SHA-256 검증을 제공한다. Unicode NFC·LF·공백 정규화, schema/revision·slug 검증과 알 수 없는
필드 거부를 적용한다. 전달된 원본 bytes와 canonical 재직렬화가 다르면 안전한 오류로 거부한다.

`domain.py`는 편집본 revision·정확한 본문 승인·게시/철회 명령을 관리한다. 본문 수정은 기존
승인을 해제하고 철회 뒤 재공개도 다시 승인받는다. 명령 생성은 실제 배포 성공을 의미하지 않는다.

`projection.py`는 공개 측 적용 상태를 관리한다. 더 오래된 sequence의 게시를 차단하고,
동일 명령은 멱등 처리하며 충돌은 거부한다. 철회는 본문 없는 tombstone으로 남고 조회는 404다.
승인된 본문 hash와 상태를 읽을 때도 재검증한다. DB·파일 저장·네트워크 처리는 포함하지 않는다.

## 검증

- 구현자 TDD: missing-module assertion RED → 최소 철회 시나리오 GREEN,
  package·domain·projection별 경계 RED/GREEN. 합성 데이터만 사용했다.
- 메인 재실행: Publishing 78개 + Learning 47개 = 125 passed in 1.92s.
- 메인 Ruff: All checks passed. mypy: 4 source files, no issues.
- 별도 메인 실행: package encode/decode → 승인 → 게시 → 철회 404 → 재승인/재게시.
  비공개 config·DB·main 모듈을 import하지 않음을 같은 프로세스에서 확인했다.
- 전체 백엔드 unit/contract: 합성 테스트 키를 프로세스 환경에 지정한 뒤 963 passed,
  기존 Starlette/httpx deprecation warning 1개, 26.65s. 아래 최종 수정 후 다시 검증했다.

작업 단위 독립 리뷰는 명세·품질·보안·privacy를 승인했다. 최종 통합 리뷰에서 lone surrogate를
담은 JSON의 canonical UTF-8 재인코딩 예외가 안전 오류 경계 밖으로 나오는 문제를 발견했다.
정규화 시 UTF-8 표현 가능성을 검증하고 decode의 오류 경계에 재인코딩을 포함하도록 수정했다.
high/low surrogate 거부와 정상 non-BMP 문자의 왕복을 검증했다(RED 4 failed → package 42 passed).
최종 Publishing 83개, 전체 백엔드 unit/contract 968 passed, 기존 경고 1개, 26.60s이며
Ruff와 mypy 4개 파일도 재통과했다. 독립 재검토는 수정 완료·새 결함 없음으로 승인했다.
기반 계약만 완료됐으며 전체 공개 서비스 완료로 판정하지 않는다.

처음 전체 실행에서는 기존 Learning 익명 API 검사가 backend 작업 디렉터리에서 필수
secret_key를 찾지 못해 실패했다(962 passed, 1 failed). 인증 dependency가 Settings를 먼저
구성하는 경로이며 Publishing은 관여하지 않았다. 실제 키를 읽는 대신 해당 테스트 프로세스에만
합성 키를 제공해 단일 재현과 전체 재실행을 통과했다. 인증 코드나 환경 파일은 수정하지 않았다.

## 아직 제공하지 않는 기능

- 관리자 `/admin/publishing` 화면과 owner 관리 API
- 영속 draft/outbox·공개 저장소, 전달자 인증·프로세스 접근권한 분리
- 공개 목록·상세·NPC 링크와 cache 철회 적용 확인
- 기존 RAG 기록 inventory·민감정보 검토·공개 편집본 게시

따라서 사용자가 현재 브라우저에서 공개·비공개 전환을 검증할 단계는 아니다. 실제 원문이나
학습 기록을 읽거나 게시하지 않았고 DB migration·모델 실행·Docker 변경도 수행하지 않았다.
SHA-256은 본문 무결성 검증이지 발신자 인증이 아니다. persona 승인과 과거 request_id 전체
중복 검증은 후속 registry/outbox에서 구현해야 한다. 본문은 plain text로 렌더링해야 한다.

## 인계

다음은 영속 저장과 API 연결이다. 기존 `main.py`는 비공개 DB router들을 조립하므로 공개
reader entry point로 재사용하지 않는다. Next의 기존 root 환경 로딩과 private API rewrite도
공개 배포 프로필에서 분리해야 한다. Learning 0024의 실제 활성화는 이번에 확인하지 않았다.
main에서만 작업했으며 커밋·push하지 않았다. 임시 리뷰 자료는 정확한 task 경계에 유지하고
CACHE_POLICY의 승인 없는 삭제는 하지 않는다.
