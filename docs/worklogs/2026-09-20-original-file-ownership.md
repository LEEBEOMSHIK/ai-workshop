# 원본 파일 추적 구현과 검증

- 사용자 지시: 원본 추적 코드가 다음 작업임을 확인한 뒤 구현 진행.
- 상세안: [원본 소유권](../superpowers/specs/2026-09-20-original-file-ownership-design.md).
- 계획: [구현 순서](../superpowers/plans/2026-09-20-original-file-ownership.md).
- 상태: 구현·최종 자동 검증·독립 검토 완료. 실사용 적용은 별도다.

## 구현

원본 bytes를 소비하기 전에 planned document/version ID·정확 파일 key·binding을 독립 원장에 등록한다.
최종 transaction은 현재 권한·lifecycle generation과 최신 버전 번호를 확인하고 원본 버전·검증 job·resource·source relation을 함께 확정한다.
최종 commit의 성공 여부가 불명확하면 파일을 보존한다.

확실한 rollback 이후 파일 정리를 할 때도 원장 상태를 먼저 확인한다.
게시된 파일은 `discarding/3`을 독립 commit한 뒤에만 정리 callback을 실행하고, 정확한 부재 확인 뒤 `abandoned/4`로 닫는다.
삭제 후 DB commit 실패가 발생해도 discarding 상태가 남아 같은 claim의 재첨부를 차단한다.
미게시 실패는 파일 부재를 확인하고 `abandoned/2`로 닫는다.

읽기 inventory는 모든 버전·예약·자원·현재 관계와 실제 파일을 대조하며 전후 DB snapshot을 비교한다.
원본 문서 행이 없는 실패 예약은 권한이 확인된 workspace 기준 미확정 목록에서 발견한다.
출력은 불투명 ID·revision·상태·안전 차단 코드만 포함하고 경로·해시·본문은 포함하지 않는다.

## 역할과 검토 보완

높은 위험의 파일/DB 수명주기 작업으로 분류했다. 메인은 요구사항·설계·업로드 연결·테스트 설계·문서·통합을 맡았다.
DBA는 계약/원장/migration, 저장소 담당은 Windows 파일 게시, 별도 담당은 inventory를 구현했다.
독립 reviewer는 구현과 분리해 코드·프라이버시·권한·통합 검증을 수행한다.
실제 RAG 동작·모델·UI·배포는 바꾸지 않으므로 해당 역할은 제외했다.

독립 검토에서 다음 문제를 발견하고 회귀 테스트와 함께 보완했다.

- 파일 확인 후 경로 unlink 사이 교체: Windows 파일 핸들에 삭제를 결합하고 전체 부모·marker를 고정한다.
- 파일 생성·게시 전후 경로 교체: 파일 쓰기와 canonical 게시 전체에 같은 고정을 적용한다.
- 원장 확인 전 정리 및 정리 commit 불명: discarding 선행 commit과 재첨부 거부를 추가한다.
- prepare 우회: 정확한 claim과 같은 root/nested transaction의 증명을 attach에서 검증·소진한다.

## 검증 기록

- 메인 최종 Assets·Jobs·설정·object store 단위 **516 passed, 2 skipped**, 실제 DB·FS·coordinator 및 원장/inventory 통합 **10 passed**. 합계 **526 passed**, 두 skip은 Windows symlink 생성 권한이다.
- 기존 Starlette TestClient 경고 1개는 이번 변경과 별개다. 최종 commit 성공 뒤 응답 상실, 실패 cleanup, 권한/generation 경합, 동시 새 버전, migration 왕복을 합성 검증했다.
- 독립 최종 단위 **83 passed, 1 skipped**, 합성 PG **10 passed**, 핵심 타입5파일·소스/migration 린트10파일 통과. 메인 실행과 중복되므로 합산하지 않는다.
- 메인 타입 **9 source files**, 관련 source/tests/migration 린트 **20 files** 통과. 최종 독립 검토 잔여 major/차단 없음.
- DB 검증은 전용 loopback tmpfs 컨테이너와 UUID 합성 DB만 사용했다. 잔여 UUID DB가 없음을 확인하고 정확 컨테이너 ID만 종료했다. 기존 다른 프로젝트 DB는 유지했다.
- 실사용 migration과 marker 설정은 하지 않았다.

독립 검증 첫 실행에서 환경변수 접두사 누락으로 기본 loopback DB 연결 시도가 있었으나 timeout으로 끝나 DB 작업은 수행되지 않았다.
정확한 합성 환경변수로 재실행했고, 새 통합 fixture 세 곳에 명시 DB URL과 test 환경 없이는 helper 호출 전 거절하는 guard를 추가했다.
연결 설정·비밀값은 이 기록에 포함하지 않는다.

## 운영 및 인계 경계

- 현재 파일 변경은 Windows만 지원한다. 비Windows publish/discard는 안전 구현 전까지 거절하며 observe와 기존 원본 읽기는 유지한다.
- 운영 설정/migration/marker 절차는 [로컬 개발 정본](../runbooks/local-development.md#원본-업로드-추적-활성화-전제)을 따른다.
- 실사용 DB·서버·원본·캐시·참고 이미지 변경이나 실제 영구 삭제는 하지 않았다.
- OCR/뷰어 임시물, HTTP multipart spool, 일반 작업 기록의 전체 추적은 후속이다.
- 생성한 테스트 임시물 20개 디렉터리는 정확 경로·파일 크기·reparse 부재를 확인한 뒤
  `.local-data/project-agent-work/original-upload-20260920/test-artifacts/`로 이동해 보존했다. 삭제하지 않았다.
- 현재 checkout 예외를 유지했으며 별도 worktree는 없다. staging/commit/push는 메인만 결정한다.

## 실행 명령

기존 `backend/.venv`에서 관련 단위 경로와 새 통합 세 파일만 명시해 실행했다.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/platform/assets tests/unit/platform/jobs tests/unit/test_config.py tests/unit/infrastructure/object_store -q --basetemp=C:/projects/ai-workshop/.local-data/pytest-tmp/or-final-unit
.venv/Scripts/python.exe -m pytest tests/integration/platform/assets/test_upload_repository.py tests/integration/platform/assets/test_tracked_uploads.py tests/integration/platform/assets/test_upload_inventory.py -q --basetemp=C:/projects/ai-workshop/.local-data/pytest-tmp/or-final-pg --tb=short
```

통합 명령은 새로 만든 전용 loopback DB URL과 `AI_WORKSHOP_ENVIRONMENT=test`를 명시한 실행에만 해당한다.
실사용 `.env`를 그대로 사용해 재실행하는 명령이 아니다. 누락은 fixture guard에서 연결 전에 거절한다.
