# HTTP 업로드 선행 예약 구현 및 검증

- 날짜: 2026-09-20
- 상태: 구현·독립 검토 완료, 실사용 적용 전
- 기준 커밋: `313ec4b`; 현재 main checkout 예외를 유지했다. 새 worktree/branch는 만들지 않았다.
- 사용자 구현 지시에 따라 [승인 설계](../superpowers/specs/2026-09-20-http-upload-intake-design.md)와
  [실행 계획](../superpowers/plans/2026-09-20-http-upload-intake.md)을 적용했다.

## 결과

두 업로드 route의 File/Form을 Request stream으로 바꿔 인증·권한·독립 예약 commit 전에
본문을 읽거나 spool을 만들지 않는다. 신규 문서는 예정 문서/버전 ID를, 새 버전은 기존 문서
RESTRICT pin과 세대를 예약한다. 실제 source pin은 원본·버전·job·출처 확정 transaction에서 붙인다.

multipart는 등록된 payload 하나에 증분 기록한다. 50MiB payload, 64KiB envelope,
256-byte boundary, 8개/4224-byte header와 128-byte field 한도를 실제 바이트로 검증한다.
파일 1개와 신규 문서의 선택 folder_id만 허용하며 두 필드 순서, 기존 201 응답과 조건부 job 전달을 유지한다.
잘린 종료 경계·추가 epilogue·중복/미지정 필드·금지 metadata는 안전한 오류로 거절한다.

임시 할당은 기존 Windows 핸들 기반 구현을 UUID+binding으로 공유하며 실제 source를 위조하지 않는다.
본문 writer와 원본 reader 종료, closed/cleaning commit과 정확한 부재를 확인한 뒤 cleaned를 확정한다.
최종 commit 응답 유실, 원본 정리 commit 불확실, 파일 close 실패는 intake를 보존한다.
업로드가 확정된 뒤 정리만 실패하면 성공 응답과 job을 유지한다.

독립 검토에서 새 정리 기록만으로 과거 HTTP spool 부재를 선언할 수 없음을 지적했다.
이를 반영해 inventory의 `legacy_untracked` 차단을 항상 유지한다. 실제 purge는 활성화하지 않았다.

## 역할과 범위

높은 위험의 API/DB/저장소 작업이다. 메인이 요구·설계·Python API/coordinator/native 통합과 문서를,
DB 담당이 원장·migration·목록 및 실제 PG/native pipeline 검증을,
multipart 담당이 제한 parser와 ASGI 검증을 맡았다. 구현에 참여하지 않은 검토자가
보안·프라이버시·실패 보존·정적 검사와 재실행을 독립 확인했다.
프론트 UX와 RAG 알고리즘/모델은 바꾸지 않아 별도 구현 역할을 추가하지 않았다.

## 검증

- 최종 관련 단위/ASGI/기존 API 회귀: **678 passed, 2 skipped**.
  Assets, Jobs, object store, document formats, RAG temporary parsing, 설정과 API를 포함한다.
- 최종 격리 PostgreSQL/native 통합: **26 passed**.
  intake 원장6 + 실제 HTTP/native pipeline7 + 원본/임시 저장 기존 회귀13.
- 합계 **704 passed, 2 skipped**. skip은 Windows symlink 권한 제한이다.
  기존 FastAPI TestClient의 Starlette deprecation warning 1개를 기록한다.
- mypy: 변경된 제품 source **12파일 통과**. Ruff: 작업 Python **25파일 통과**.
- 변경 문서6파일 링크·최근 완료5개 제한·diff 및 프로젝트 에이전트 계약 검사를 통과했다.
- 독립 검토의 최종 통합 재실행 **47 passed**, 별도 DB6 통과. 최종 차단 사항 없음.
- TDD: 계약/adapter/module 미존재, File/Form body_field, intake coordinator 미구현의 실패를 먼저 관찰했다.
  종료 문자열·metadata 경계 실패를 보완한 뒤 위 최종 집합을 통과했다.
- migration0047 upgrade/downgrade/upgrade, 동시 연결 CAS, composite FK/unique/RESTRICT,
  권한/세대 변경, root/nested transaction capability와 commit 응답 유실을 검증했다.
- ASGI는 인증/예약 실패 시 receive 0회, spool 금지, 취소 시 writer/reader 종료 후 정리,
  정리 실패 뒤 201/dispatch 보존을 확인했다. 실제 native pipeline은 원장·원본·job·출처를 대조했다.

실행 명령은 backend venv의 `python -m pytest <관련 경로> -q`와 짧은 별도 basetemp를 사용했다.
주요 통합 경로는 `tests/integration/platform/assets/test_{intake_repository,http_intake_pipeline,
http_intake_api,upload_repository,upload_inventory,tracked_uploads,temporary_repository,temporary_pipeline}.py`다.

## 환경과 인계

실사용 `.env`를 DB 대상으로 사용하지 않았다. 명시적인 test 환경과 loopback55034의
작업 전용 postgres:17-alpine/tmpfs 컨테이너, UUID 격리 DB와 합성 파일만 사용했다.
검증 후 기본 postgres 외 DB가 없음을 확인하고 정확한 컨테이너 `b8088b560f27`만 종료했다.
기존 `tpmp-db-local`(55432)은 정상 유지했고 기존 중지된 프로젝트 컨테이너도 변경하지 않았다.
사용자 `references/`, 기존 캐시·실사용 파일·DB schema·marker·서버는 보존했다.
커밋/푸시는 기존 사용자 승인 범위에서 작업 파일만 대상으로 한다. 별도 worktree 정리 대상은 없다.

## 남은 경계와 RAG 테스트

일반 Jobs 출처/정리 계약, 미확인 OCR writer 잔존 복구, 전체 삭제 참여자 조립과 역순 잠금 해소,
비Windows 쓰기 구현과 실제 purge API/UI는 남는다. 기존 ingestion 통합 fixture의
`artifact_binding_missing` 8실패/5통과 기록은 이번 작업에서 해결하지 않았으며 ES/RAG 전체 통합은 실행하지 않았다.

RAG 사용 테스트는 영구 삭제 개발 완료를 기다릴 필요가 없다. 다만 이전
[readiness 확인](2026-09-20-http-intake-and-rag-readiness.md)에서 API/frontend/PG/Redis/ES가
준비되지 않았고 추적 저장소 binding/marker와 DB/model readiness가 미확인이다.
이번에는 코드와 격리 검증만 완료했다. 승인된 적용 절차로 환경·migration0047·저장소를 준비한 뒤
합성 TXT 업로드→검색→답변/인용→OCR 순서로 검증한다. 날짜를 확정할 실행 증거는 아직 없다.
운영 절차는 [로컬 실행 runbook](../runbooks/local-development.md)이 정본이다.
