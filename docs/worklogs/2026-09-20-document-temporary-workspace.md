# 문서 전용 임시 작업공간 구현 기록

- 날짜: 2026-09-20
- 사용자 지시: 검토한 상세안을 바로 구현
- 상세안: [임시 작업공간](../superpowers/specs/2026-09-20-document-temporary-workspace-design.md)
- 계획: [구현 계획](../superpowers/plans/2026-09-20-document-temporary-workspace.md)
- 결정: [ADR-0025](../decisions/0025-document-temporary-workspaces.md)

## 구현

DB 담당은 immutable claim·원장·현재 provenance·목록·0046 migration을 구현했다.
별도 파일 담당은 Windows native 배타 생성, ancestor/marker pin, 생성 identity manifest와
핸들 삭제를 구현했다. RAG 담당은 ingestion source/job 전달과 parser/DOCX/PDF OCR 할당을
연결했다. 메인은 lease의 commit 경계·설정·원본 권한 문맥·PDF worker 종료·통합을 맡았다.
구현에 참여하지 않은 검토자가 각 단계와 전체 연결을 검증했다.

예약 commit 전에 파일을 만들지 않는다. closed/cleaning commit 응답이 불명이면 정리하지 않는다.
실제 worker reap 이후에만 정리하며 예상 밖 파일·hardlink·경로 교체는 삭제하지 않는다.
일반 parser와 preview의 알려진 파일은 정상 종료 뒤 제거된다. OCR 호출은 성공하더라도
native/background writer 종료를 증명하지 못하므로 open과 파일을 유지한다.
모든 production parser/renderer의 coverage는 runtime_unverified로 보수적으로 기록한다.

일반 사용자 응답·오류에는 원본/임시 경로나 raw DB 오류를 추가하지 않았다.
원본 최종 권한 재확인과 PDF worker의 반복 cancellation 대기는 유지했다.

## 실행 방식

사용자의 바로 구현 지시에 따라 계획 저장 후 추가 승인 질문 없이 실행했다.
이전 작업에서 기록한 현재 checkout 예외를 이어갔다. 새 worktree를 만들지 않았고
사용자 `references/`는 수정·stage하지 않는다. 프로젝트 지침에 따라 메인만 최종 인계한다.
DB/파일의 독립 구현은 공통 계약을 먼저 확정한 뒤 병렬로 수행했다.

## 검증

초기 missing module/port 및 source 문맥 누락 실패를 확인한 뒤 구현했다.
서비스 오류 정규화도 원시 예외 노출 실패를 먼저 확인한 뒤 고쳤다.

- 최종 단위: `tests/unit/platform/assets`, `platform/jobs`, `infrastructure/object_store`,
  `infrastructure/document_formats`, `labs/rag/parsing`, `labs/rag/ingestion`, `test_config.py`
  **699 passed, 2 skipped**. skip은 Windows symlink 권한 제한이다.
- 최종 격리 PG: `test_temporary_repository.py`, `test_temporary_pipeline.py`,
  `test_asset_originals.py` **7 passed**. 단위와 합계 **706 passed**.
- 새 pipeline은 실제 PG 원장·native 저장소·plain parser·실제 PDF worker를 연결해
  cleaned/4 및 현재 관계/4·물리 부재, opaque runtime open/1·입력 보존,
  예상 밖 항목 cleaning/3·양쪽 파일 보존을 검사했다.
- mypy 변경 소스 **18개 통과**, Ruff 변경 Python **39개 통과**.
- 독립 단계/연결 검증 **200 passed, 1 skipped**, DB·파일·연결 리뷰의 현재 실행 경로 차단 없음.
- 기존 Starlette/httpx deprecation 경고 1종은 이번 의존성 변경 대상이 아니다.

명령은 backend에서 `.venv/Scripts/python.exe -m pytest ... -q`를 사용했다.
메인 최종 basetemp는 `.local-data/pytest-tmp/tw-final-unit`, `tw-final-pg`다.
타입·린트는 `-m mypy <변경 source>` 및 `-m ruff check <변경 Python>`이다.

### 기존 통합 fixture 한계

추가로 실행한 `test_ingestion_task.py`는 **5 passed, 8 failed**였다.
8건 모두 변경하지 않은 기존 ArtifactAdmission의 `artifact_binding_missing`에서 파싱 전에
실패한다. 해당 fixture는 추적 산출물 binding/publisher/정리 제약을 아직 반영하지 않았다.
이를 새 임시 작업공간 성공으로 보고하지 않으며 전체 ingestion 통합 통과를 주장하지 않는다.
이번 exact source 전달과 신규 추적 경로는 별도 unit/실제 PG pipeline으로 검증했다.
`test_production_embedding_indexing.py`의 직접 parser 생성은 새 명시적 테스트 workspace에
맞췄지만 ES가 없어 해당 통합 모듈은 실행하지 않았다.

## 운영과 후속

합성 PG 컨테이너 `ai-workshop-temporary-test-20260920`, ID
`ba9a80d06bdf6cd4263d2f350f7447236d1276bcd281f2989a7e347fa3af9f45`는
tmpfs `/var/lib/postgresql/data`, loopback `127.0.0.1:55033`, 작업 라벨을 확인하고 사용했다.
테스트는 명시적인 `AI_WORKSHOP_ENVIRONMENT=test`와 synthetic URL을 사용했다.
격리 fixture가 생성한 UUID DB만 종료 시 제거한다. 기존 `tpmp-db-local`은 건드리지 않는다.
최종 UUID DB 잔존 0건 확인 후 정확한 컨테이너 ID로 종료했고 `--rm`에 따라 제거됐다.
기존 DB의 실행·포트 유지와 별도 worktree 없음도 확인했다.

실사용 migration·marker·서버 재시작·자료 삭제는 하지 않았다. 설정/적용의 정본은
[로컬 runbook](../runbooks/local-development.md#문서-전용-임시-작업공간-활성화-전제)이다.
현재 저장소 어댑터는 Windows만 지원한다. OCR 잔존 자동 회수, runtime 외부 쓰기 검증,
HTTP spool 선행 예약과 일반 Job provenance는 후속이다.

독립 검토에서 기존 미활성 `PurgeInventoryRepository._require_exact_batch_targets`의
document→version 잠금을 확인했다. 새 예약/worker의 version→document와 역순이므로
이 경로 활성화 전 순서 통합·경쟁 검증이 필요하다. 현재 제품 호출은 없고 purge는 비활성이다.
전체 inventory는 legacy/HTTP/jobs/runtime 차단을 유지한다.
