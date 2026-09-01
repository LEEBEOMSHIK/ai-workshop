# RAG 검색 수직 슬라이스 통합 검증 기록

- 기록일: 2026-09-01
- 통합 커밋: `47cba3a`
- 원본 작업 보고서: RAG worktree의 무시된 Task 14 보고서
- 보존 범위: 최종 검증 증거와 재발 방지 가치가 있는 실패 기록

## 검증 범위

- Markdown, TXT와 텍스트 PDF 파싱·청킹·색인
- Elasticsearch BM25·dense 검색과 Python RRF
- keyword·semantic 하이라이트와 권한이 적용된 원문 근거
- 자산 READY 활성화, ingestion handoff, redelivery와 색인 alias 복구
- 저장 RAG 구성, 비교 평가와 기본 구성 승격 거절
- PostgreSQL migration, Redis 작업 전달과 Elasticsearch 실제 스택

## 선별 실패 기록

### 보존 볼륨에서 누락된 기준선 seed

초기 보호 smoke에서 revision 0012 상태의 불변 0009 seed가 과거 격리 reset으로 제거돼 0013 migration이 실패했다. 수정된 migration은 정확히 일치하는 seed가 완전히 없을 때만 복원하고 일부 또는 충돌 상태에서는 실패를 닫도록 했다. 실패 시 transaction rollback으로 revision 0012를 유지하며 구독 테이블이나 부분 프로파일을 남기지 않는다.

### ingestion 산출물과 실행 순서

초기 실제 스택 검증에서 TXT projection이 `embedding_artifact_missing`으로 실패했다. parsed, chunk와 embedding object key 및 worker 종료 순서를 비교해 비동기 실행·정리 경계를 보강했고, 이후 기존·신규 문서가 함께 READY projection과 활성 색인으로 연결되는 흐름을 재검증했다.

### 직렬화와 테스트 실행 환경

검색 payload의 UUID 구성 ID 직렬화 실패와 격리 테스트의 서비스·mount·환경값 누락을 각각 분리했다. 제품 직렬화는 API 계약에 맞게 수정했고, 실행 환경 실패는 코드 성공으로 오인하지 않고 정확한 서비스 연결과 쓰기 가능한 임시 경로로 재검증했다.

### Windows OpenAPI wrapper

공식 Windows wrapper는 worktree 로컬 Python 실행 파일이 없어 실패했다. 백엔드 이미지의 OpenAPI export와 고정된 `openapi-typescript` 검사를 대체 검증으로 실행해 스키마 일치를 확인했으며, 환경 실패와 계약 실패를 구분해 기록했다.

## 최종 증거

- 보호 실제 스택: foundation `2 passed`, RAG `17 passed in 110.70s`, beat-only liveness와 post-reset 통과
- 최종 백엔드: `574 passed, 6 skipped`, Ruff 통과, mypy 130개 소스 파일 통과
- 프론트엔드: 12개 파일의 58개 테스트, 타입 검사, 린트와 production build 통과
- migration: 0001부터 0013까지 신규 PostgreSQL에서 통과
- 격리 검증용 컨테이너와 네트워크는 제거하고 애플리케이션 데이터 볼륨은 보존

## 원본 작업 산출물 처리

이 문서는 worktree에만 있던 최종 증거와 선별 실패 기록의 공식 인계본이다. 중간 리뷰 diff, 반복 실행 로그, 가상환경, 테스트 캐시와 패키지 설치물은 재생성 가능 산출물이므로 worktree 정리 시 영구 보존하지 않는다.
