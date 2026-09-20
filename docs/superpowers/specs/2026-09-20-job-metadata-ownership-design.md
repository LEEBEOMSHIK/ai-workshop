# 일반 Jobs 메타데이터 소유권

- 날짜: 2026-09-20
- 범위: 사용자 다음 개발 지시에 따른 Jobs 출처·보존·revision과 읽기 inventory 구현.
- 제외: writer 종료 증명, 실제 job/문서 삭제, 큐 삭제, legacy 자동 backfill.

## 목적과 선택

Jobs의 현재 source와 메타데이터 변경을 같은 transaction에서 추적한다. 원본·RAG 작업에는
이미 각 소유자가 있으므로 Jobs는 자신의 row만 소유한다. 상태가 terminal이어도 OCR/indexwriter
종료를 추정하지 않는다. 기존 실행·재시도와 API schema를 유지한다.

대안은 jobs의 CASCADE FK를 전부 변경하거나 별도 소유권 pin을 두는 것이다. 후자를 선택한다.
legacy 동작을 무조건 중단하거나 과거 source를 추정해 backfill하는 대안은 사용하지 않는다.

## 데이터와 transaction

`jobs.revision`은 nullable positive bigint다. 기존 행은 NULL, 신규 repository.add는 1이다.
Platform Jobs 소유 `JobSourceRecord`는 job ID를 키로 정확한 workspace/document/version을 보존한다.
(job_id,workspace_id,asset_version_id)→jobs의 기존 composite unique에 RESTRICT,
(workspace_id,document_id)→documents와(document_id,asset_version_id)→asset_versions도 RESTRICT다.
이 row는 user/workspace/version CASCADE를 통한 추적 job 소실도 막는다. 기존 composite unique의
Python 모델 정의는 Platform Jobs로 옮긴다. migration0048은 legacy를 추정 등록하지 않는다.

add는 source를 읽어 workspace 일치를 검증하고 job/owner/현재 relation을 원자 기록한다.
participant=`platform_jobs`, kind=`job`, relation_kind=`derived_artifact`다.
update는 fresh job row→owner→현재 relation 순으로 검사하고 source 잠금을 새로 얻지 않는다.
user/workspace/version/type/idempotency identity 변경은 거절한다. 전달된 revision이 다르면
고정 코드 충돌을 반환한다. 새 revision과 relation 교체는 같은 transaction이다.
flush 성공 후 입력 domain Job의 revision도 갱신해 같은 transaction에서의 재사용을 지원한다.
rollback/commit 응답 유실 뒤에는 domain 객체를 재사용하지 않고 새 transaction에서 다시 조회한다.
legacy NULL update는 NULL로 유지하며 owner/relation 자동 생성은 금지한다.

revision은 실제 persisted update 호출마다 한 번 증가한다. domain 상태 method에서는 증가하지 않는다.
asset dispatch의 직접 ORM/벌크 CAS도 repository를 거치게 해 누락을 막는다. CAS조건 불일치는
revision과 relation을 바꾸지 않는다. dispatch 실패에는 고정 안전 메시지만 남긴다.

## 목록과 정리 경계

새 `JobMetadataInventory`는 문서의 모든 버전 job과 source owner, 현재 relation을 대조한다.
source에 연결된 job 외에 해당 source의 owner/relation으로 발견한 불일치 행도 검사한다.
두 개의 fresh READ ONLY/REPEATABLE READ snapshot fingerprint를 비교한다. 호출자 인증이 필요한
public wrapper는 workspace 접근을 먼저 확인한다. 반환은 opaque ID/revision과 고정 blocker뿐이다.
legacy NULL, 누락/추가/다른source 관계, owner 불일치, 관측 사이 변경은 불완전으로 표시한다.
metadata 완전성은 실행 종료와 별개다. writer 종료 확인은 이번 계약에서 제공하지 않으며,
미확인 writer blocker를 유지하고 cleanup receipt나 purge 실행기는 만들지 않는다.

## 검증과 운영

단위: legacy/불변 identity/CAS/dispatch stale claim/안전 오류와 inventory 대조.
격리 PG: migration up/down/up, 생성/갱신/rollback, 연속 update, 경쟁 CAS, provenance 불일치,
RESTRICT deletion 방어, dispatch claim/failure snapshot 갱신과 allversion inventory.
기존 원본 upload·verification·RAG ingestion 회귀를 실행한다. 실사용 DB는 변경하지 않는다.
RAG 테스트 준비는 별도 합성 sandbox에서 cached images와 pinned offline E5로 진행한다.

## RAG 실행 검증에서 확인한 보완

기존 ingestion 통합 fixture도 실제 artifact admission·추적 publisher 계약을 사용하도록 갱신한다.
게시 확정 전 실패는 파일을 인수하지 않고 예약과 원본 바이트를 보존하는 회귀로 검증한다.
저장 구성의 의미상 Document Processing Profile ID는 물리 alias 이름의 profile ID와 별도로
ResolvedSearchConfiguration에 전달한다. legacy alias와 고정 평가 target도 같은 의미상 ID로
선택 문서 범위·재검사·검색을 수행하며 실제 alias 이름은 변경하지 않는다.
이 보완은 실제 합성 TXT 선택 검색에서 재현된 409 오류의 수정이다.
