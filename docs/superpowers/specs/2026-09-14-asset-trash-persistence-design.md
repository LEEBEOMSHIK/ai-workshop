# 휴지통 영속 기반 2B 상세 설계

- 상태: 구현·통합 검증·최종 독립 검토 완료(2026-09-14). 실사용 DB 적용 전이다.
- 구현 결과: [2B 작업 기록](../../worklogs/2026-09-14-asset-trash-persistence.md).
- 상위 승인 설계: [휴지통·복원·영구 삭제](2026-09-13-asset-trash-purge-design.md).
- 선행 완료: [2A 권한·격리 검증](../../worklogs/2026-09-14-asset-trash-authorization.md).
- 범위: PostgreSQL에 상태·삭제 세대·배치·정책·전용 삭제 작업을 저장할 기반. API·자동 정리·실제 삭제·화면 활성화는 제외한다.

## 1. 채택 방향과 대안

기존 문서 행에 deleted_at만 추가하는 방식은 복원/삭제 경합과 오래된 worker의 재생성을 구별하기 어렵다.
일반 jobs 재사용은 asset_version_id가 필수이고 원본과 CASCADE로 연결되어 있어 폴더 배치와 삭제 후 이력을 보존할 수 없다.
따라서 Assets가 상태와 배치를 소유하고 전용 purge job/outbox를 분리하는 상위 승인안을 구체화한다.
Platform은 RAG 구현을 import하지 않는다. 본문 복제와 정리 참여자 목록은 후속 2C 계약이다.

## 2. 문서·폴더의 현재 상태

기존 documents/folders에 아래 필드를 추가한다. 기존 ID·이름·부모·버전·metadata_revision을 바꾸지 않는다.

| 필드 | 저장 규칙 |
|---|---|
| lifecycle | 기존 행과 신규 일반 생성의 기본값 active. active/trashed/purge_pending/purging/retry_wait/blocked만 허용 |
| lifecycle_generation | 양의 bigint, 시작값 1. 이후 휴지통 이동·복원·삭제 요청 때 증가 |
| trash_batch_id | active는 NULL, 비활성은 현재 삭제 배치 ID 필수 |
| trashed_at | timezone-aware 시각. active는 NULL, 비활성은 필수 |
| purge_after | timezone-aware 시각. active는 NULL, 비활성은 필수이며 trashed_at보다 뒤 |

정책 버전은 배치가 참조하는 불변 정책 행으로 추적한다. 문서별로 다른 정책을 중복 저장하지 않는다.
복원은 현재 삭제 필드를 NULL로 돌리되 generation과 metadata_revision을 증가시킨다.
generation은 작업 시도의 횟수가 아니다. 같은 삭제 작업의 재시도는 job.attempt_count만 증가시킨다.
PURGED는 원문 행의 영구 상태로 저장하지 않는다. 실제 정리 후 최소 삭제 증명만 남긴다.
2B는 이 필드를 저장할 뿐 실제 상태 전이를 호출하는 API나 worker는 추가하지 않는다.

## 3. 명시적 보관 정책

asset_retention_policies: id, workspace_id, version, days, created_by, created_at.
workspace_id/version은 UNIQUE, version과 days는 양수이며 days에는 기본값이 없다.
정책 수정은 기존 행 UPDATE가 아니라 새 버전 INSERT다. workspace 잠금 아래 다음 버전을 정한다.
DB trigger로 기존 정책의 UPDATE를 거부한다. 참조된 정책의 DELETE는 FK로 거부하며 미참조 정책을 제거해 이전 설정을 되살리는 서비스 동작은 제공하지 않는다.
기존 공간에는 정책을 자동 생성하지 않는다. 정책 미설정은 휴지통 기능 미준비이며 임의 보관 일수를 적용하지 않는다.
삭제 배치는 당시 정책을 참조하고 확정된 purge_after를 보존한다. 새 정책이 기존 기한을 자동 단축하지 않는다.
정책 저장의 OWNER 검사와 UI는 후속 명령 단계에서 연결한다. 2B의 DB 모델을 일반 API로 노출하지 않는다.

## 4. 삭제 배치와 공간 격리

asset_trash_batches: id, workspace_id, actor_id, policy_version_id, trashed_at, purge_after, created_at.
배치는 폴더 삭제 당시 포함된 활성 항목 집합의 식별자다. 이전에 독립적으로 삭제된 항목은 포함하지 않는다.
실제 항목 집합과 원래 위치·미리보기 digest의 저장은 후속 명령/manifest 계약에서 함께 구현한다.
2B 배치만으로 폴더 복원을 실행하거나 모든 자식이 같은 배치라고 추정하지 않는다.

정책과 배치에 UNIQUE(workspace_id,id)를 두고, 배치→정책 및 문서/폴더→배치는 workspace_id를 포함한 복합 FK로 묶는다.
다른 공간의 정책 또는 배치 ID를 넣으면 DB가 거부한다. 문서/폴더가 참조 중인 배치는 RESTRICT다.
배치의 actor_id는 최소 감사용 불투명 ID이며 사용자 행 삭제와 CASCADE로 묶지 않는다.
배치/정책의 workspace 참조는 RESTRICT로 두어 공간 삭제가 삭제 작업 이력까지 조용히 지우지 않게 한다.
공간 자체의 삭제 기능을 새로 추가하거나 현재 권한을 확대하지 않는다.

## 5. 전용 삭제 작업과 전달 대기열

asset_purge_jobs: id, workspace_id, trash_batch_id, request_key, status, attempt_count,
available_at, error_code, finished_at, created_at, updated_at.
status는 purge_pending/purging/retry_wait/blocked/purged만 허용하고 attempt_count는 0 이상이다.
purged일 때만 finished_at을 필수로 저장하고 그 전에는 NULL이다. updated_at을 완료 시각으로 대신하지 않는다.
작업 상태는 job이 실행 정본이며 해당 원문 상태는 같은 트랜잭션에서 동기화한다. 교차 테이블 상태 일치는 단일 CHECK로 보장했다고 주장하지 않는다.
UNIQUE(workspace_id,request_key)로 동일 요청을 식별한다. 동일 키에 다른 배치를 전달한 충돌은 후속 명령에서 409로 거부한다.
UNIQUE(trash_batch_id)로 배치의 중복 삭제 작업을 막는다. 차단·실패 재시도는 새 job을 만드는 대신 같은 job을 사용한다.
배치와 공간은 복합 RESTRICT FK다. Document/AssetVersion에는 CASCADE FK를 두지 않는다.
파일명·경로·본문·예외 원문·전체 manifest는 job에 넣지 않는다. error_code는 명명된 안전 코드만 저장한다.

asset_purge_dispatches: id, job_id, status, attempt_count, available_at, claim_token, claimed_at, sent_at, created_at, updated_at.
job_id는 UNIQUE이며 RESTRICT 참조다. attempt_count는 0 이상이다.
status는 pending/claimed/sent를 사용한다. pending은 claim_token/claimed_at/sent_at 모두 NULL, claimed는 claim_token/claimed_at만 필수, sent는 sent_at만 필수다.
위 상태 조합은 CHECK로 강제하고 (status,available_at) 인덱스를 둔다. sent는 broker 전송 사실이며 작업 실행 완료가 아니다.
전송 대기열에는 job_id만 저장하고 원본·모델 입력 payload를 복사하지 않는다.
후속 삭제 요청은 purge_pending 변경과 job/dispatch를 동일 트랜잭션으로 저장한다.
Celery 전송기·재전송·claim/lease·실제 실행기는 이번 단계에 포함하지 않는다.
DB에 purged 문자열을 쓸 수 있다는 것만으로 정리 완료가 증명되지는 않는다. 후속 완료 명령은 2C의 최소 증명과 assess_purge를 필수로 사용한다.

## 6. 활성 폴더명 고유성과 선행 점검

현재 UNIQUE(workspace_id,parent_id,name)는 parent_id=NULL인 root 중복을 막지 못한다.
repository는 SQL trim(name), 이동은 Python strip()을 사용하므로 탭·유니코드 공백의 비교도 일치하지 않을 수 있다.
문서명 고유 제약은 0014에서 제거됐다. 문서에 파일명 고유 제약을 다시 만들지 않고 SHA-256 중복 계약을 유지한다.

폴더는 표시 이름을 바꾸지 않고 현재 Python strip() 의미의 비교 키를 정본으로 통일하는 것을 제안한다.
Python 런타임 변경으로 비교가 바뀌지 않도록 현재 공백 문자 집합을 명시적 상수로 고정하고 Python strip(문자집합)과 PostgreSQL btrim(name,문자집합)이 같은 값을 사용한다.
대소문자 접기와 Unicode NFC/NFKC 변환은 추가하지 않는다. DB 표현식과 Python 비교의 공백 집합 동등성을 테스트한다.
active root용 (workspace_id,비교키), active 일반 폴더용 (workspace_id,parent_id,비교키) 부분 UNIQUE 인덱스를 분리한다.
trashed 등 비활성 항목은 활성 이름 예약에서 제외한다. 복원 충돌은 자동 병합이나 덮어쓰기로 해소하지 않는다.
기존 전체 행 UNIQUE는 부분 인덱스로 교체한다. 그대로 남겨 비활성 폴더의 이름까지 예약하지 않는다.

DDL 적용 전 읽기 전용 dry-run은 동일한 비교 키로 root/일반 중복, 비정규 저장 이름, 잘못된 공간-부모 연결, 순환을 검사한다.
비정규 이름은 name != name.strip()인 기존 저장값이다. 해당 값도 자동 변경하지 않고 적용을 중단한다.
출력은 issue code·건수·불투명 ID만 포함하고 폴더명·경로·본문을 출력하지 않는다.
일관된 읽기 snapshot에서 검사하며 검사 실패/미지원 DB/불완전 결과는 성공으로 표시하지 않는다.
충돌이 있으면 migration을 중단한다. 실사용 데이터를 자동 rename/merge/delete하지 않는다.
dry-run 통과와 DDL 사이 변경을 막기 위해 실제 migration도 쓰기 차단 잠금 아래 같은 검사를 다시 수행한다.
실사용 dry-run 실행 대상과 허용 범위는 별도 확인하며, 이번 설계에서 DB에 접속하지 않았다.
folder.parent뿐 아니라 document.folder의 다른 공간 연결도 검사한다. 기존 parent CASCADE/folder SET NULL FK는 이번 작업에서 임의로 교체하지 않는다.
복합 FK의 ON DELETE SET NULL이 workspace_id까지 NULL로 만들 수 있으므로 해당 계층 FK 변경은 별도 계약 없이는 수행하지 않는다.

## 7. 파일 경계와 구현 순서

1. `backend/src/ai_workshop/platform/assets/trash_models.py`: 정책·배치 모델. `assets/models.py`: 현재 상태/세대/배치 참조.
2. `backend/src/ai_workshop/platform/assets/purge_models.py`: 전용 job/dispatch 모델. 기존 `platform/jobs/models.py`는 변경하지 않는다.
3. `backend/alembic/env.py`와 `backend/src/ai_workshop/shared/model_registry.py`: 새 모델 metadata 등록. `backend/alembic/versions/`에는 현행 0034 다음의 명명된 migration을 순차 추가한다.
4. `backend/src/ai_workshop/platform/assets/folder_names.py`: 비교 키 정본. repository/movement가 같은 의미를 소비하게 한다.
5. `backend/src/ai_workshop/platform/assets/trash_migration_preflight.py`: 읽기 전용 검사와 구조화된 결과. 자동 데이터 수정 없음.
6. `backend/tests/integration/platform/assets/test_trash_persistence.py`: 정책/배치/공간/상태 제약 검증.
7. `backend/tests/integration/platform/assets/test_purge_persistence.py`: 작업/dispatch 멱등 식별·FK 보존·rollback 검증.
8. `backend/tests/integration/platform/assets/test_trash_migration.py`: 기존 0034 합성 데이터의 upgrade/downgrade·충돌/보존 검증.

구현 계획에서는 정책/배치/현재 상태, 전용 작업, 이름 비교/dry-run을 각각 테스트와 리뷰 가능한 Task로 나눈다.
새 테이블을 사용하는 모델 배포는 해당 migration 이후다. 실제 운영 적용은 후속 runbook에 따른다.

## 8. 검증과 되돌리기

- 기존 backend/.venv와 2A의 hardened 격리 DB helper만 사용한다. 새 venv·pytest 캐시·컨테이너를 만들지 않는다.
- 실제 PostgreSQL에서 0034 합성 데이터 → 새 revision으로 업그레이드하여 기존 ID/이름/부모/버전/본문 hash가 보존됨을 비교한다.
- 기존 모든 문서/폴더는 active/generation=1, 정책·배치·삭제 job은 0건이어야 한다.
- 다른 공간 배치·정책, 비활성 필드 누락, purged 원문 행, 음수 재시도·잘못된 기한·중복 키는 DB에서 거부해야 한다.
- 트랜잭션 rollback 시 job/dispatch가 함께 사라지는지 검사한다. 아직 외부 broker 전달을 검증했다고 보고하지 않는다.
- 신규 필드를 사용하지 않은 깨끗한 업그레이드만 downgrade를 허용한다.
- 정책/배치/job/dispatch 데이터가 있거나 generation이 1을 넘거나 비활성 원문이 있으면 downgrade를 DDL 전에 거부한다.
- 기존 고유 제약을 복원할 수 없는 데이터가 있으면 downgrade를 거부한다. 데이터를 지워 rollback을 성립시키지 않는다.
- Alembic revision과 스키마가 거부 전후 동일한지 검사하고 기존 권한·파일함 회귀와 mypy/Ruff를 수행한다.
- 실사용 DB migration·삭제·서버 재시작·푸시는 별도 대상 확인 전에는 수행하지 않는다.

## 9. 완료 경계

2B 완료는 저장 제약과 마이그레이션의 합성 검증 완료다. 사용자가 파일을 삭제할 수 있게 되는 시점이 아니다.
2C의 provenance/최소 증명, 일반 조회·검색·worker 차단, 휴지통/복원 명령, 정리 참여자와 공통 UI 게이트를 이어간다.
필터가 없는 현재 API에 비활성 데이터를 생성해 테스트하지 않는다. 합성 비활성 사례는 격리 DB에서만 만든다.

DBA 정적 조사에서 모델 registry 등록·기존 전체 고유 제약 제거·outbox claim/전송 상태·완료 시각 보완을 반영했다. 실사용 데이터에 충돌이 실제 존재한다고 확인한 것은 아니다.
