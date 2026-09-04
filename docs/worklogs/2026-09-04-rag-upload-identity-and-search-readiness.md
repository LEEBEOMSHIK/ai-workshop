# RAG 업로드 동일성·검색 준비 상태 검증

- 날짜: 2026-09-04
- 브랜치: `main`
- 상태: 구현 및 자동 검증 완료

## 확정 계약

- 파일명은 표시 메타데이터이며 문서 동일성 기준이 아니다.
- 같은 지식 공간 안에서 원본 바이트 SHA-256이 기존 어느 문서 버전과든 같으면 신규 문서와
  새 버전 업로드를 모두 `duplicate_document_content` 409로 거절한다.
- 같은 파일명이더라도 원본 바이트가 다르면 별도 문서로 허용한다.
- 다른 지식 공간의 같은 해시는 중복으로 취급하지 않고 존재 여부도 노출하지 않는다.
- 기존 문서 계보에는 해당 행의 `새 버전 올리기`를 사용한 경우에만 추가한다.
- 파싱 후 정규화 본문 해시는 형식 간 본문 유사성 분석용 후속 ingestion 산출물로 분리한다.
- 저장 구성은 호환되는 활성 READY 색인의 존재를 `search_ready`로 제공한다. 준비 전 구성은
  선택할 수 있지만 검색 제출은 막고 사용자 조치 안내를 표시한다.
- 구성·버전·지식 공간·폴더 UUID는 API와 원문 링크 내부에서만 사용하고 결과 설명에는
  노출하지 않는다.

## 구현 결과

- Platform Asset 저장소가 같은 지식 공간의 SHA-256 조회 전에 트랜잭션 advisory lock을
  획득해 동시 업로드도 같은 판정 순서로 직렬화한다.
- 문서 파일명 unique constraint를 제거하고 workspace 및 SHA-256 조회 인덱스를 추가하는
  `0014_asset_content_identity` 마이그레이션을 작성했다.
- 문서 목록 각 행에 접근 가능한 `새 버전 올리기` 입력을 추가하고 성공 시 기존 행을 최신
  버전 응답으로 교체한다.
- 완전 중복 오류는 서버 상세를 그대로 표시하지 않고 안전한 한국어 안내로 변환한다.
- RAG 구성 목록은 활성 READY build의 벡터 차원이 모두 존재하고 하나로 일치할 때만
  `search_ready=true`를 반환한다.
- 검색 화면은 준비 전 라벨과 상태 안내를 표시하고 제출 버튼을 비활성화한다.

## TDD와 검증 증거

- RED: 완전 중복이 거절되지 않음, 새 버전 파일 입력이 없음, 결과 UUID가 노출됨,
  `search_ready` 계약과 준비 전 안내가 없음.
- Backend 단위·계약·구성 API 회귀: 최종 `438 passed`.
- PostgreSQL 통합: 실제 저장 구성 준비 상태 `false → true → false`와 0014
  upgrade/downgrade/upgrade 왕복 `2 passed`.
- Frontend 전체: `41 files, 171 passed`.
- Python: Ruff 전체 통과, mypy `136 source files` 통과.
- Frontend: TypeScript, ESLint, OpenAPI 생성물 check 통과.
- Next.js 16.3.4 production build: 11개 route 생성 통과.
- 프로젝트 에이전트 계약 검증과 `git diff --check` 통과.
- 로컬 개발 DB를 `0014_asset_content_identity`로 적용했고 FastAPI health 200 및 제공
  OpenAPI의 `search_ready` 포함을 확인했다.

## 남은 범위

- 마이그레이션 이전에 이미 만들어진 별도 중복 문서는 자동 병합하거나 삭제하지 않는다.
- 정규화 본문 해시와 유사 문서 후보 표시는 파서별 정규화 계약을 먼저 설계한 뒤 추가한다.
- 브라우저의 기존 인증 세션이 만료되어 보호 화면 수동 smoke는 로그인 뒤 재확인해야 한다.
