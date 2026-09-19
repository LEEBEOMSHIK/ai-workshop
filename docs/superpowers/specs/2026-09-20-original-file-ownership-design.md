# 원본 파일 생성 전 소유권 등록

- 상태: 상세 설계와 독립 검토 완료. 사용자 상세안 확인 전이며 구현·실사용 적용은 하지 않았다.
- 검증 및 인계: [작업 기록](../../worklogs/2026-09-20-original-file-ownership-design.md).
- 사용자 목적: 문서를 영구 삭제할 때 원본과 실패한 업로드의 파일 위치를 잃지 않고, 다른 문서의 파일을 잘못 지우지 않는다.
- 상위 계약: [삭제 대상 추적과 최소 증명](2026-09-14-asset-purge-provenance-design.md).
- 선행 구현: [RAG 별칭 종료와 쓰기 차단](2026-09-20-rag-alias-write-fence-design.md).
- 이번 경계: 신규 원본 및 새 버전 업로드의 예약·게시·확정·목록 계약. 실제 영구 삭제 실행은 포함하지 않는다.

## 1. 현재 경로와 문제

`platform/assets/service.py`는 파일을 저장한 뒤 Document/AssetVersion을 저장한다.
새 문서 ID는 쓰기 전에 있지만 버전 ID는 쓰기 뒤에 만들어진다.
`LocalObjectStore.put`은 내부에서 무작위 임시 이름을 만든 뒤 목적 파일을 교체한다.
정상 예외에서는 파일을 지우지만 프로세스 종료, 취소, DB commit 결과 불명까지 보장하지 못한다.
특히 업로드 coordinator의 최종 commit은 기존 파일 정리 try 블록 밖에 있다.

공통 source relation은 실제 문서·버전의 RESTRICT FK를 요구하므로 아직 없는 원본을 등록하는 용도로 사용할 수 없다.
원본 행을 먼저 확정하면 현재 문서 목록과 작업 생성의 원자성을 바꾸게 된다.
따라서 **미확정 업로드 예약과 확정 원본 관계를 분리**한다.

## 2. 대안과 선택

| 방식 | 장점 | 문제 / 결정 |
|---|---|---|
| 원본 행을 먼저 commit | 기존 source FK 사용 | 실패한 빈 문서 노출·작업 없는 버전·기존 API 의미 변경. 채택하지 않는다 |
| 파일 저장 뒤 관계 등록 | 작은 변경 | 파일 저장 중 종료하면 위치를 잃는다. 채택하지 않는다 |
| 예정 ID를 가진 독립 예약 후 원자적 확정 | 파일 쓰기 전 locator 확보, 기존 성공 응답 유지 | 예약과 확정의 두 트랜잭션 및 불명 상태가 필요. 채택한다 |

원본 바이트에 대한 동일 해시는 소유권이 아니다. 기존 workspace 내 중복 콘텐츠 거부 정책은 유지하며,
다른 문서나 공간의 동일 bytes를 하나의 파일로 합치지 않는다.

## 3. 소유 모듈과 계약

Platform Assets가 업로드 예약과 원본 자원 목록을 소유한다.
파일시스템 구현은 `infrastructure/object_store`에 둔다. Platform은 RAG artifact 계약을 import하지 않는다.
기존 RAG 추적 저장소는 별도 자원이며 이번에 재구현하거나 그 대장에 원본을 섞지 않는다.

업로드 예약은 다음 정보를 가진다.

- 불투명 attempt ID, 예정 workspace/document/asset-version ID, 생성 사용자 ID.
- 신규 문서 또는 기존 문서 새 버전 구분, 신규 문서의 예정 folder ID. 기존 문서는 예약 시 lifecycle generation을 고정한다.
- 저장소 ID 및 binding ID, 정확한 canonical key와 임시 key, 계약 버전.
- 단조 증가 revision, 상태, 예약 시각, 안전 오류 코드.
- 게시 관찰 뒤에만 size와 SHA-256. 본문·원래 파일명·요청 내용·임의 오류 문자열은 저장하지 않는다.

locator와 원본 해시는 Assets 전용 제한 저장소에만 두고 공통 출처/삭제 증명에는 복제하지 않는다.
canonical/임시 key는 UUID와 허용된 확장자에서 결정하고 쓰기 전에 모두 고정한다.
같은 attempt를 재사용해 내용을 다시 쓰지 않는다. 다시 업로드하면 새로운 attempt와 파일 이름을 사용한다.

상태는 `open`, `published`, `attached`, `abandoned`를 구분한다.

- `open`: 예약은 확정됐지만 파일 상태나 writer 종료가 확인되지 않았다.
- `published`: canonical 파일의 게시와 writer 종료를 관찰했다. 원본 DB commit은 아직 확정되지 않았다.
- `attached`: 문서·버전·검증 job·현재 source relation과 함께 확정됐다. 원본 파일은 계속 존재한다.
- `abandoned`: 원본에 연결되지 않았으며 writer 종료와 예약된 두 파일의 부재를 확인했다.

timeout, 취소, 오래된 시각, 일반 job의 terminal 상태만으로 상태를 전진시키지 않는다.
revision과 예상 상태를 대조해 갱신하고 다른 실행의 관찰 결과를 재사용하지 않는다.

## 4. 트랜잭션과 동시성

1. 읽기 전용 입력·권한 검증과 예정 ID 생성을 한다. 아직 업로드 bytes를 소비하거나 파일을 만들지 않는다.
2. 독립 예약 트랜잭션에서 현재 권한을 다시 확인하고 예약을 commit한다.
   기존 문서이면 문서 잠금 아래 active lifecycle과 generation을 확인한다.
   요청 트랜잭션이 같은 행을 잠근 채 독립 세션을 기다리게 만들지 않는다.
3. 예약 commit 성공을 확인한 경우에만 등록된 임시 key에 스트리밍한다.
   commit 응답이 불명확하면 파일을 생성하지 않는다. 조회로 예약을 확인하더라도 새 실행은 기존 writer를 인수하지 않는다.
4. 파일 핸들을 닫고 정확한 canonical 게시를 관찰한 뒤 예약을 `published`로 기록한다.
5. 최종 요청 트랜잭션에서 현재 권한·폴더 소속/상태·문서 lifecycle/generation을 다시 확인한다.
   기존 콘텐츠 중복 advisory lock을 유지한다. 기존 문서 버전 번호는 잠금 후 현재 DB 값에서 결정한다.
6. 문서/버전, 검증 job 및 기존 dispatch 상태, 원본 source relation, 예약의 `attached` 전이를 같은 트랜잭션에 둔다.
   버전 ID는 처음 예약한 ID를 사용한다. 이 전체 commit을 확인한 뒤 기존 성공 응답을 반환한다.

독립 예약은 요청 transaction rollback으로 사라지지 않아야 한다.
독립 예약의 ID는 예정 식별자이며 source/workspace/membership/folder FK를 두지 않는다.
이 방식은 아직 없는 source FK와 요청 세션의 잠금에 따른 FK 자기 교착을 피하고, source CASCADE 뒤에도 locator를 보존한다.
대신 예약 서비스가 현재 권한·소속을 검증하고, 확정 원본 resource에는 실제 source와 attempt의 RESTRICT FK를 둔다.
최종화 잠금 순서는 workspace → membership → 대상 folder/Document → 업로드 원장이다.
기존 AssetVersion을 Document 뒤에서 추가로 잠그지 않아 verification worker의 job → version → document 순서와 충돌하지 않게 한다.
stale domain 객체로 folder나 metadata revision을 덮어쓰지 않는다.
정확한 제약과 잠금 SQL은 구현 계획에서 고정하고 합성 PostgreSQL에서 교착과 경쟁을 검사한다.

후속 purge 명령은 같은 문서 잠금 아래 새로운 예약을 차단하고 기존 open/published 예약을 목록에 포함해야 한다.
예약이 있다는 사실은 writer 종료 증명이 아니다. 이번 원장만으로 전체 writer 차단 완료를 주장하지 않는다.

## 5. 파일 게시와 실패

새 원본 쓰기용 어댑터는 정확한 예약과 검증된 저장소 binding을 요구한다.
기존 `put`에 예약을 선택 사항으로 추가해 운영 경로가 추적을 우회하게 만들지 않는다.
프로덕션 업로드 조립은 추적 구현만 사용하고, 단위 테스트의 메모리 fake는 별도 명시 구현으로 둔다.

- marker의 store/binding과 설정을 일치시킨다. 기존 실제 root에 marker를 자동 생성하거나 과거 자료를 자동 인수하지 않는다.
- 절대 경로, `..`, 대소문자 별칭, symlink/reparse 경유, 다른 binding은 거부한다.
- 임시 파일은 배타적으로 생성하고 canonical은 기존 파일을 덮어쓰지 않는 방식으로 게시한다.
- 등록 이후 예상치 못한 경로/파일/하드링크 또는 내용 불일치를 발견하면 충돌로 남기고 자동 정리하지 않는다.
- 파일 게시 전 flush/fsync 및 지원 플랫폼의 게시 원자성을 검증한다. 전원 장애 후 존재를 추정하지 않고 재관찰한다.

파일 쓰기 실패나 크기 초과 때 현재 실행이 열었던 핸들이 닫히고 소유권이 확인된 임시 파일만 정리한다.
canonical 게시 뒤 DB 확정 실패는 **확실한 rollback**과 **commit 결과 불명**을 구분한다.
불명 상태에서는 canonical을 지우지 않는다. 새 DB 세션에서 exact version/attempt/관계를 확인할 수 있을 때만 연결 여부를 판정한다.
한 번의 version 부재 조회로 이전 commit의 실패를 단정하지 않는다. 이전 트랜잭션 종료와 최종 결과까지 확인해야 한다.
DB에 연결돼 있거나 판단 불가능하면 보존한다. 열린 세션의 미확정 결과를 바탕으로 삭제하지 않는다.
취소 처리에서도 writer 종료 및 파일 부재 확인을 완료하지 못하면 open/published 상태와 locator를 남긴다.
`Exception`을 잡는 것만으로 취소 안전성을 주장하지 않는다.

시작 시 임시 폴더 전체 스캔이나 prefix 기반 삭제는 하지 않는다.
프로세스 재시작 후 open 예약은 경과 시간만으로 정리하지 않고, 후속 복구 절차가 이전 writer의 종료를 증명해야 한다.
같은 파일을 재시도 writer가 다시 만들 수 있는 경로를 닫기 전에는 `abandoned`를 만들지 않는다.

## 6. 읽기 목록과 과거 자료

원본 참여자 `platform_originals`는 다음을 함께 대조한다.

1. 요청한 공간/문서의 모든 버전과 현재 source relation.
2. 예정 document ID로 연결되는 미확정 예약 및 확정 원본 자원 revision.
3. exact binding의 canonical/임시 파일과 관찰된 크기·해시·소유권.

새 버전 ID가 아직 없는 예약도 문서 수준 목록에서 빠뜨리지 않는다.
신규 업로드가 실패해 Document/AssetVersion 자체가 없는 예약은 기존 `DocumentTarget`에 억지로 넣지 않는다.
Assets 전용 workspace/attempt 기준 미확정 예약 조회를 별도로 제공해 이 항목도 발견한다.
서버 내부의 현재 workspace 권한 검사 뒤 불투명 attempt ID, 예정 source ID, 상태·revision·안전 차단 코드만 반환한다.
페이지 continuation을 끝까지 소진해야 하며 조회 중 예약 집합이나 revision이 바뀌면 incomplete로 반환한다.
예약 상세 locator는 제한된 저장소 실행 경계에서만 해석한다. 원본 없는 예약을 열거했다고 일반 문서 삭제 완료로 계산하지 않는다.
이 조회와 문서별 목록을 함께 제공하는 것이 이번 구현의 완료 조건이며, 미확정 예약 복구/삭제 실행은 후속이다.
목록 확인 중 예약·상태·버전 집합이 변하면 결과를 불완전으로 반환하고 새 목록을 만든다.
DB 상태가 일관돼도 파일 writer가 종료됐다는 증거가 없으면 정리 가능 판정은 하지 않는다.
파일 없음은 단독으로 성공이 아니며, binding 불일치/관계 누락/open writer/예상 밖 파일은 명명된 차단 사유다.

기존 AssetVersion의 object_key는 과거 원본 후보 위치를 알려주지만 임시 파일까지 추적했다는 뜻은 아니다.
이번 migration에서 모든 과거 자료를 자동 등록하거나 complete로 표시하지 않는다.
과거 버전, 미등록 임시 파일 또는 불명확한 binding은 별도 dry-run/backfill 절차 전까지 incomplete다.
일반 API에는 물리 경로·해시·내부 오류를 노출하지 않는다.

## 7. 임시물과 작업 기록의 후속 분리

이번 계약 다음에 다음 두 묶음을 구현한다. 이름만 있는 코드나 빈 폴더는 미리 만들지 않는다.

| 묶음 | 확인된 현재 경로 | 연결 방향 |
|---|---|---|
| 문서 전용 임시 작업 | ParsingService, DOCX 이미지, PDF OCR, PDF preview의 OS TemporaryDirectory | source/선택 job/binding/UUID 전용 디렉터리를 먼저 등록하고 내부 산출물을 그 아래로 제한 |
| 일반 작업 상세 기록 | Platform jobs의 asset-version CASCADE와 오류/idempotency 메타데이터 | 별도 Platform 참여자에서 현재 revision·실제 관련 기록을 대조하고 최종 검증 전 locator를 보존 |

파서는 workflow의 job 문맥을 전달받아 async 경계에서 예약하고 동기 parser가 DB 세션을 소유하지 않게 한다.
뷰어는 OriginalService가 이미 확인한 source를 PdfRenderer port로 전달한다.
PDF preview의 terminate→kill(필요 시)→wait/reap→temp 정리 순서를 유지한다.
부모 프로세스 crash 뒤 자식 종료를 확인하지 못하면 열린 작업으로 남긴다.
RAG 검색 뷰어의 현재 PDF/DOCX 메모리 처리에는 없는 디스크 산출물을 발명하지 않는다.
OCR 모델 provision 캐시는 문서 전용 임시물에서 제외한다.

이 두 묶음과 원본까지 연결한 뒤 전체 참여자 조립·writer 종료·잔존 확인·삭제 API/UI로 진행한다.
이번 설계만으로 사용자가 영구 삭제를 실행할 수 있게 된 것은 아니다.

## 8. 수용 기준과 검증

- 예약 저장 실패·commit 불명 때 bytes 미소비 및 파일 미생성을 검사한다.
- 신규/새 버전 업로드 모두 예정 ID가 relation·job·최종 버전까지 유지된다.
- 크기 초과, 스트림 예외, 취소, 게시 직후 종료, job 생성 실패, DB commit 불명을 주입해 locator 보존과 잘못된 삭제 방지를 확인한다.
- 동시 새 버전·동일 해시·권한 철회·폴더 이동/휴지통·문서 generation 변경과 예약/삭제 경쟁을 합성 PostgreSQL로 검사한다.
- canonical 충돌·다른 문서 동일 bytes·binding 바꿈·경로 탈출·reparse·예상 밖 파일을 거부한다.
- 원본/관계/예약 CASCADE 방지, rollback, revision 경쟁 및 목록 중 새 예약 출현을 검사한다.
- legacy가 빈 목록이나 complete로 바뀌지 않고 상세 경로·본문이 공개 결과에 포함되지 않는다.
- 기존 업로드 응답·중복 오류·원본 열람 및 검증 job 생성 회귀를 확인한다.

기존 시작점은 `tests/unit/platform/assets/test_asset_service.py`,
`tests/integration/infrastructure/test_local_object_store.py` 및 Platform Assets/Jobs 테스트다.
새 원장·목록·추적 어댑터 테스트와 migration 검증을 추가하고 Python 타입/린트를 실행한다.
실제 모델과 민감 문서 없이 fake 스트림·합성 파일·격리 DB로 검증한다.
독립 DB 검증과 프라이버시/코드 리뷰는 구현 담당과 분리한다.

## 9. 운영 경계

기존 실사용 object store marker 설정, backfill, DB migration 적용, 서버 재시작은 별도 적용 절차다.
추적 쓰기 준비가 안 된 환경에서 조용히 기존 untracked 업로드로 전환하지 않는다.
실패 원인과 준비 상태를 명시하며 배포 전에 root/binding·migration·업로드 smoke를 함께 점검한다.
실제 보관 자료·과거 OS temp·캐시·참고 이미지의 삭제는 이 설계의 실행 대상이 아니다.
