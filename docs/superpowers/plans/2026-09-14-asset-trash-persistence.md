# 휴지통 영속 기반 2B 구현 계획

> 필수 실행 스킬: superpowers:subagent-driven-development. 각 Task의 체크리스트를 순차 실행한다.

**Goal:** 승인된 휴지통 상태·정책·배치·삭제 작업과 활성 폴더 고유성을 DB에 저장하고 합성 migration 검증으로 보호한다.

**Architecture:** Assets 전용 모델과 additive migrations를 사용한다. 이름 사전검사→상태→작업→고유성 순서이며 API/UI 활성화는 없다.

**Tech Stack:** 기존 Python 3.13, SQLAlchemy, PostgreSQL, Alembic, pytest, mypy, Ruff.

**Spec:** docs/superpowers/specs/2026-09-14-asset-trash-persistence-design.md

## 공통 제약
- 사용자 승인 상세안: docs/superpowers/specs/2026-09-14-asset-trash-persistence-design.md.
- main에서만 작업. 기존 UI/WORKBOARD/references 수정 금지. 구현자는 Git staging/commit/push 및 하위 에이전트 호출 금지.
- 기존 backend/.venv, Python -B, pytest -p no:cacheprovider, Ruff --no-cache. 새 패키지/가상환경/컨테이너 없음.
- 실사용 DB/문서/서버 변경 금지. 127.0.0.1:15432의 hardened tests.integration.publishing_support.isolated_publishing_database가 만든 ai_workshop_publishing_<32hex>만 생성/합성 seed/migrate/drop. 전체 URL/비밀값 출력 금지. 정확 이름 current_database 확인은 기존 helper 사용.
- API, UI, worker 실행기, 실제 삭제를 추가하지 않는다. Platform→Labs 의존 금지. 문서명 고유 제약 부활 금지.
- TDD는 import 실패가 아닌 행동 실패를 확인. no-op 검사/빠진 제약이 잘못 허용하는 실패를 먼저 기록.
- 상세 보고는 지정 task 보고서에 한국어로 기록: RED/GREEN 명령·결과, 변경 파일, 정리된 격리 DB, 타입/린트, 남은 위험. 응답은 15줄 이내.

### Task 1: 고정 폴더 비교 키와 읽기 전용 사전 검사
**파일**
- 생성 backend/src/ai_workshop/platform/assets/folder_names.py
- 생성 backend/src/ai_workshop/platform/assets/trash_migration_preflight.py
- 생성 backend/tests/unit/platform/assets/test_folder_names.py
- 생성 backend/tests/integration/platform/assets/test_trash_preflight.py

**인터페이스**
- FOLDER_NAME_WHITESPACE_V1: str = "\u0009\u000a\u000b\u000c\u000d\u001c\u001d\u001e\u001f\u0020\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000" (실제 Python escape 리터럴 사용).
- folder_name_key(name: str) -> str: name.strip(FOLDER_NAME_WHITESPACE_V1); 대소문자/NFC 변경 없음.
- PreflightIssue(code: str, entity_ids: tuple[UUID,...]); PreflightReport(issues: tuple[PreflightIssue,...]), ready bool 속성.
- inspect_trash_migration(connection: sqlalchemy.engine.Connection) -> PreflightReport: 읽기 SELECT만. caller가 REPEATABLE READ READ ONLY transaction 또는 migration 쓰기차단 lock을 소유.
- assert_trash_migration_ready(connection) -> None: issues 있으면 RuntimeError("asset_trash_preflight_failed"), 원문/이름/경로 SQL오류 출력 금지.
- 0034에는 lifecycle 없으므로 inspector로 열 존재 확인 후 active로 간주. 열이 있으면 실제 active만 이름 충돌 검사. 전체 계층의 공간 불일치/순환은 상태 무관 검사.

- [x] 독립 예상값 테스트 작성:
```python
assert folder_name_key("\t 연구 \u3000") == "연구"
assert folder_name_key("A") != folder_name_key("a")
assert folder_name_key("\u200b연구\u200b") == "\u200b연구\u200b"
```
- [x] no-op key/빈 보고 스텁의 행동 RED 실행. 새 경계 함수 미정의 오류만으로 RED 인정하지 않는다.
- [x] 실제 PostgreSQL 0034 합성 자료에서 root/sibling 중복, 비정규 이름, 빈 이름, folder-parent 다른 공간, document-folder 다른 공간, self/다중 cycle을 검사. 정상 데이터 ready=True; 다른 공간의 같은 이름과 다른 부모의 같은 이름은 정상.
- [x] code는 folder_name_noncanonical/folder_name_empty/folder_root_name_conflict/folder_sibling_name_conflict/folder_parent_workspace_mismatch/document_folder_workspace_mismatch/folder_cycle. 정렬된 UUID 결과; 이름·경로 미포함. 유실 부모는 FK로 방지되지만 발견되면 folder_parent_missing/document_folder_missing으로 보고.
- [x] 구현: 동기 Connection SELECT로 구조화된 snapshot 조회, 폴더 ID map과 iterative 방문 집합으로 순환 탐지(깊은 트리 RecursionError 금지). 검사함수는 DDL/DML/commit/rollback 안함. 비PostgreSQL은 지원불가 안전 오류.
- [x] PostgreSQL btrim(:name,:chars)와 Python key가 공백 집합/일반/제로폭/한글/combining fixture에 대해 같은지 검증. 기존 데이터 전후 hash/건수 같고 실제 READ ONLY transaction에서 수행됨을 확인.
- [x] GREEN: .venv/Scripts/python.exe -B -m pytest tests/unit/platform/assets/test_folder_names.py tests/integration/platform/assets/test_trash_preflight.py -q -p no:cacheprovider
- [x] 관련 mypy/Ruff, 독립 Task 리뷰 후 메인이 지정 파일만 커밋. 현재 repository/movement는 Task4까지 변경하지 않는다.

### Task 2: 상태·정책·삭제 배치 저장 기반
**파일**
- 수정 backend/src/ai_workshop/platform/assets/models.py
- 생성 backend/src/ai_workshop/platform/assets/trash_models.py
- 수정 backend/alembic/env.py, backend/src/ai_workshop/shared/model_registry.py
- 생성 backend/alembic/versions/0035_asset_trash_state.py (revision=0035_asset_trash_state, down_revision=0034_asset_metadata_revision)
- 생성 backend/tests/integration/platform/assets/test_trash_persistence.py
- 추가 통합 검증 범위: backend/tests/integration/platform/assets/test_asset_api.py의 합성 인증 설정 격리와 기존 metadata_revision 응답 기대값 보완. API 업무 코드는 변경하지 않는다.

**인터페이스**
- Task1 assert_trash_migration_ready(Connection) 소비.
- AssetRetentionPolicyRecord, AssetTrashBatchRecord: 상세안 §3–4의 정확한 필드/타입/명명 UNIQUE/FK.
- FolderRecord/DocumentRecord에 lifecycle: str, lifecycle_generation:int(BigInteger), trash_batch_id:UUID|None, trashed_at/purge_after:datetime|None.
- active/default1/NULL 기본값. 상태 필드 SQL CHECK는 active iff 모든 trash 필드 NULL, 비활성 iff 모두 NOT NULL 및 purge_after>trashed_at, generation>=1, raw purged 금지.

- [x] 기존 0034 합성행을 만든 뒤 migration skeleton(no-op)에서 inspector가 lifecycle/정책테이블을 찾지 못하는 assertion RED 확인; 이어 필드만 있는 무제약 상태에서 잘못된 상태/다른 공간 배치가 허용되는 RED 확인.
- [x] 0034 seed는 당시 스키마에 맞는 raw SQL/기존 seed 경계를 사용한다. 아직 없는 lifecycle 열을 INSERT하는 최신 ORM으로 upgrade 전 seed를 만들지 않는다.
- [x] upgrade 첫 DDL 전 LOCK TABLE folders, documents IN SHARE ROW EXCLUSIVE MODE, Task1 사전 검사. 검사 실패 시 전체 migration rollback.
- [x] 정책은 UUID id/workspace_id/created_by, positive int version/days, timezone created_at. UNIQUE(workspace_id,id), UNIQUE(workspace_id,version). workspace RESTRICT, created_by 불투명 UUID(CASCADE 없음). UPDATE 거부 trigger 함수/이름을 migration에 명시.
- [x] 배치는 UUID id/workspace_id/actor_id/policy_version_id, timezone trashed_at/purge_after/created_at; deadline CHECK. UNIQUE(workspace_id,id), 복합 (workspace_id,policy_version_id) FK→정책(workspace_id,id) RESTRICT. workspace RESTRICT.
- [x] models.py는 기존 이름/계층/metadata_revision/READY 의미를 유지. 배치 복합 FK RESTRICT 추가. metadata 등록 두 위치 반영. SQLAlchemy defaults와 DB defaults 동일하게.
- [x] API는 shared.load_models를 호출하지 않으므로 assets/models.py에서 독립 trash_models를 명시 import하여 FK 대상 metadata를 등록한다. trash_models는 assets/models.py를 역import하지 않는다. 새 프로세스의 기존 API 생성/업로드 경로가 NoReferencedTableError 없이 실행되는 회귀를 검증한다.
- [x] downgrade 첫 DDL 전 관련 표 write lock, 정책/배치 1행 또는 비active/gen!=1/trash 필드 있으면 RuntimeError("asset_trash_downgrade_unsafe"). 무조건 DROP으로 설정 지우지 않음.
- [x] 0034→0035→0034 clean 왕복 ID/name/parent/version/hash/metadata_revision 보존, 정책0/배치0 검증. 정책만 저장한 경우도 downgrade 거부하고 revision/열/자료 유지.
- [x] 다른 공간 정책/배치·잘못된 status/NULL조합/deadline·policy UPDATE 거부를 savepoint로 검증. 생성자 삭제가 감사행을 CASCADE 삭제하지 않는지 확인.
- [x] GREEN: .venv/Scripts/python.exe -B -m pytest tests/integration/platform/assets/test_trash_persistence.py -q -p no:cacheprovider
- [x] mypy/Ruff 및 독립 리뷰 후 메인 지정 파일 커밋. 실제 서비스 DB에는 적용하지 않는다.

### Task 3: 전용 purge job과 outbox 저장
**파일**
- 생성 backend/src/ai_workshop/platform/assets/purge_models.py
- 수정 backend/alembic/env.py, backend/src/ai_workshop/shared/model_registry.py
- 생성 backend/alembic/versions/0036_asset_purge_jobs.py (revision=0036_asset_purge_jobs, down_revision=0035_asset_trash_state)
- 생성 backend/tests/integration/platform/assets/test_purge_persistence.py

**인터페이스**
- Task2 AssetTrashBatchRecord(workspace_id,id) 소비.
- AssetPurgeJobRecord/AssetPurgeDispatchRecord: 상세안 §5 필드. String 상태와 명명 SQL CHECK; job.id/workspace_id/batch UUID; request_key String255, error_code String100; timezone 시각; attempt_count Integer0.
- job UNIQUE(workspace_id,request_key), UNIQUE(trash_batch_id), 복합 workspace/batch RESTRICT. Document/Version/user CASCADE 없음.
- dispatch UUID id/job_id/claim_token, status pending 기본, attempt_count0, timezone available_at/claimed_at/sent_at/created_at/updated_at. job UNIQUE RESTRICT, (status,available_at) index.

- [x] no-op migration/제약 미구현 RED: 중복 job/다른 공간 배치/음수시도/잘못된 claim 조합을 허용하는 실패 확인.
- [x] upgrade Task1 사전검사 + 자산 write lock 후 표 생성. job status=purge_pending/purging/retry_wait/blocked/purged, finished_at은 purged일 때만 필수.
- [x] dispatch CHECK 구현:
```sql
(status='pending' AND claim_token IS NULL AND claimed_at IS NULL AND sent_at IS NULL)
OR (status='claimed' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL AND sent_at IS NULL)
OR (status='sent' AND claim_token IS NULL AND claimed_at IS NULL AND sent_at IS NOT NULL)
```
- [x] DDL 이전 downgrade 안전 검사: 정책/배치/job/dispatch 중 어떤 데이터라도 있거나 원문이 pristine 아니면 거부. 기존 기록을 삭제해 downgrade 허용 금지.
- [x] 테스트: 같은 transaction에 job+dispatch 저장 후 rollback 둘다0; raw 합성 원문/version 제거해도 job/batch 살아있음(휴지통 명령 아님); 참조 batch/workspace 삭제는 RESTRICT; finished_at/claim 상태 조합과 idem중복 검증.
- [x] clean 0035→0036→0035 왕복, nonempty 거부시 revision/schema변경0.
- [x] GREEN: .venv/Scripts/python.exe -B -m pytest tests/integration/platform/assets/test_purge_persistence.py -q -p no:cacheprovider
- [x] mypy/Ruff, 독립 리뷰 후 메인 커밋. 일반 jobs, Celery task, beat, API는 변경하지 않는다.

### Task 4: 활성 폴더 이름 고유성 및 전체 migration 회귀
**파일**
- 수정 backend/src/ai_workshop/platform/assets/models.py, repository.py, movement.py, domain.py, service.py (동일 assets 디렉터리)
- 생성 backend/alembic/versions/0037_active_folder_names.py (revision=0037_active_folder_names, down_revision=0036_asset_purge_jobs)
- 생성 backend/tests/integration/platform/assets/test_trash_migration.py
- 필요 시 기존 tests/unit/platform/assets의 생성/이동 회귀 파일 수정
- 기존 tests/integration/platform/assets/test_asset_library.py의 불법 동명 root fixture는 서로 다른 폴더명으로 수정한다. 페이지네이션·동시 생성 및 동명 문서 assertion은 유지한다.

**인터페이스**
- Task1 folder_name_key/FOLDER_NAME_WHITESPACE_V1 및 assert_trash_migration_ready 재사용.
- migration의 공백 상수는 명시적 v1 snapshot으로 고정; 역사 migration에서 변경 가능한 미래 정규화함수 참조 금지.
- repository.folder_name_exists의 이름부분을 func.btrim(FolderRecord.name, FOLDER_NAME_WHITESPACE_V1)==folder_name_key(name)로 통일. 생성/도메인/이동의 name.strip()도 같은 함수 소비.
- 폴더 이름 예약 여부 조회는 active로 제한해 부분 UNIQUE와 일치시킨다. 일반 목록·조회·검색의 lifecycle 차단 및 휴지통 UI 활성화는 후속이며 문서명 처리는 바꾸지 않는다.

- [x] 현재 head0036에서 active root 중복 INSERT가 성공하는 RED, 같은 비활성 sibling 이름은 기존 UNIQUE에 걸리는 RED 작성.
- [x] 첫 DDL 전 folders/documents 쓰기차단 lock + preflight. 기존 전체 UNIQUE folders_workspace_id_parent_id_name_key를 검증 후 제거.
- [x] root partial UNIQUE(workspace_id,btrim(name,chars)) WHERE lifecycle='active' AND parent_id IS NULL, sibling partial UNIQUE(workspace_id,parent_id,btrim(name,chars)) WHERE lifecycle='active' AND parent_id IS NOT NULL. 명명 ix_folders_active_root_name/ix_folders_active_sibling_name; ORM도 정확히 반영.
- [x] 같은공간 활성root/sibling 충돌거부, 비활성같은이름 허용, 다른공간/부모 허용, case구분/한글/zero width 비교 유지. 생성/이동에서 동일key충돌409, 표시이름 자동변경없음.
- [x] downgrade는 asset_retention_policies/asset_trash_batches/asset_purge_jobs/asset_purge_dispatches 중 행 있거나 raw lifecycle/generation/trash fields 사용흔적 있으면 거부. 이전 raw UNIQUE 복원 불가 검사도 lock 아래 선행. 안전한 경우에만 index제거와 이전 UNIQUE복구.
- [x] migration 회귀는 합성0034 seed후head upgrade, clean downgrade0034, 거부시revision+전체이전데이터동일 검사. 각 corrupt fixture는 정확code/id를 검증하고 원문비노출. 실패upgrade의 앞선revision 일부commit도 포함해 원래0034 유지되는지 검사.
- [x] GREEN: .venv/Scripts/python.exe -B -m pytest tests/integration/platform/assets/test_trash_migration.py tests/unit/platform/assets -q -p no:cacheprovider
- [x] 변경범위 mypy/Ruff·독립 Task리뷰 후 메인 커밋. 이후 전체4Task 최종리뷰/통합suite 실행, 문서/WORKBOARD 마감. 새삭제UI테스트가능 주장 금지.

## 마감
- [x] Assets 단위 + 신규 4 PG suite + 2A 권한/기존 구성원 권한을 실제 실행해 건수/경고 기록.
- [x] 전체 diff 최종 독립 리뷰, 관련 타입/린트/문서 링크 검증.
- [x] WORKBOARD 최근완료 최대5개. 실제DB/삭제/서버/원격 영향없음을 구분.

결과: 329 passed, 기존 경고 1건. mypy 14파일·Ruff 23파일·최종 전체 독립 검토 통과.
상세 결과와 후속 경계: `docs/worklogs/2026-09-14-asset-trash-persistence.md`.
