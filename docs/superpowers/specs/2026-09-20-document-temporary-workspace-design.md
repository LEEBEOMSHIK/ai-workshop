# 문서 전용 임시 작업공간 추적

작성일: 2026-09-20. 상태: 사용자 바로 구현 승인에 따라 구현·독립 검토 완료. 실사용 적용 전.

## 1. 목적과 이번 범위

사용자는 원본 파일 추적 이후의 다음 작업 진행을 요청했다. 원본 파일 추적은
`21af8b8`에 반영됐다. 이번 상세안은 파싱·DOCX 이미지 추출·PDF OCR·PDF preview가
만드는 문서 전용 임시 파일을 생성 전에 문서에 연결하고, 실제 작성 종료와 파일 부재를
확인하기 전에는 정리 완료로 기록하지 않는 계약을 정한다.

상위 근거는 [원본 소유권 설계](2026-09-20-original-file-ownership-design.md)와
[삭제 출처 설계](2026-09-14-asset-purge-provenance-design.md)다.
Platform은 임시 작업공간의 예약·수명주기·목록을 소유하며 RAG 구현에 의존하지 않는다.

이번 구현 단위는 **문서 전용 임시 작업공간**이다. 다음 두 단위는 별도로 이어진다.

1. HTTP multipart spool: 본문 파싱 전 예약과 신규 문서의 예정 소유권 연결.
2. 일반 Job 메타데이터: revision, 현재 출처 관계, dispatch의 직접 상태 변경 연결.

현재/과거 미추적 임시 파일 및 외부 런타임의 미검증 쓰기는 전체 삭제 검증의 차단 사유다.
이번 단위 완료를 모든 문서 복제본의 추적 완료나 영구 삭제 활성화로 보고하지 않는다.
기존 OS temp를 이름/prefix/나이로 발견해 자동 인수하거나 삭제하지 않는다.

## 2. 선택한 방법과 대안

**선택: 실행마다 하나의 예약된 작업공간과 그 아래의 하위 파일.** async 진입점에서
DB 예약을 확정하고 동기 parser에는 작업공간 capability만 전달한다. 중첩 parser마다
별도 DB 예약을 하지 않으므로 잠금과 동기/비동기 결합을 줄일 수 있다.

파일마다 별도 원장을 만드는 방법은 내부 라이브러리 파일을 모두 사전에 알 수 없고
동기 OCR 경로의 DB 결합이 커진다. 기존 OS temp를 사후 스캔하는 방법은 생성 전
소유권과 다른 실행의 파일 구분을 보장하지 못한다. 두 방법은 채택하지 않는다.

작업공간 추적은 OS sandbox를 대신하지 않는다. 런타임 외부 쓰기 보장은 별도
검증 결과로 관리하며, 미검증 런타임은 목록에 차단 사유를 남긴다.

## 3. 소유권과 저장 계약

Platform Assets 아래에 임시 작업공간 계약·원장·읽기 목록을 두고, 실제 파일 조작은
infrastructure 어댑터로 분리한다. 공유 모델 다운로드/모델 캐시는 소유 대상이 아니다.
문서 bytes가 포함될 수 있는 cache/log는 공유 모델 캐시로 간주해 제외하면 안 된다.

원장 필수 값:

| 값 | 조건 |
| --- | --- |
| id / workspace token | 실행마다 새 UUID, 재사용 금지 |
| workspace/document/version | 실제 source의 복합 FK RESTRICT, 생성 후 불변 |
| job_id | preview는 NULL 가능, 있으면 jobs RESTRICT 및 source 소속 검증 |
| purpose | parsing 또는 pdf_preview의 제한된 값 |
| store_id / binding_id | 전용 저장소 marker와 일치, 생성 후 불변 |
| document generation | 예약 당시 쓰기 차단 세대, source와 재검증 |
| state / revision | 아래 전이만 CAS, revision은 성공한 전이마다 증가 |
| coverage | 확인한 실행 경계 및 미확인 runtime 쓰기의 고정 코드 |
| created_at / updated_at / error_code | 진단용, 종료 증명으로 사용하지 않음 |

경로는 저장소의 UUID token으로만 결정한다. 사용자 파일명·본문·원본 locator·hash를
공통 출처 관계나 공개 오류에 복제하지 않는다. source relation의 resource는 opaque
workspace ID이며 내용 revision과 현재 관계 교체는 원장 전이와 같은 트랜잭션이다.
source/job/목적/binding/token을 호출자 입력만으로 확정하지 않는다.

새 전용 root와 marker가 준비되지 않았거나 추적 mutation이 지원되지 않는 OS에서는
파일 생성 전에 명시적으로 거절한다. 초기 구현의 mutation 지원은 Windows로 한정한다.
실사용 marker 생성·migration 적용·서버 재시작은 이번 구현 작업에 포함하지 않는다.

## 4. 생성·종료·정리 상태

| 상태 | 의미와 허용 전이 |
| --- | --- |
| open, revision 1 | 영속 예약됨. 파일 생성·writer가 있을 수 있음 |
| closed | 해당 실행의 모든 알려진 writer 종료가 확인됨, 파일은 남을 수 있음 |
| cleaning | closed에서 정리 권한을 영속 확정함. 새 writer/재실행 금지 |
| cleaned | 정확한 작업공간 부재를 확인한 뒤 기록됨 |

정상 경로는 reserve commit → 디렉터리 생성 → 작업 → writer 종료 → closed commit
→ cleaning commit → 안전한 파일 정리 → 부재 확인 → cleaned commit이다.
각 전이는 이전 revision, claim, binding을 검증한다. cleaning commit 결과가 불명이면
파일 정리를 시작하지 않는다. cleaned 기록 실패는 cleaning을 남기며 성공으로 표시하지 않는다.

예약 직후 예외라도 동일 실행이 파일/worker를 만들지 않았음을 알고 있을 때만 closed로
전이한다. 부모 crash, DB 결과 불명, process reap 실패, 식별 불가능한 자손/백그라운드
writer가 있으면 open을 유지한다. 시각·lease·job terminal·PID 존재 여부만으로 닫지 않는다.
재시도는 새 token이며 이전 open 작업공간을 인수하거나 새 쓰기에 재사용하지 않는다.
재시작 후 자동 회수는 이 단위에서 지원하지 않으며 잔존 차단으로 보고한다.

물리 정리는 살아 있는 실행이 보유한 capability와 종료 증거에만 허용한다.
UUID 디렉터리는 exclusive 생성하며 이미 존재하면 인수하지 않는다. capability가 하위
파일/디렉터리의 생성 전에 메모리 manifest에 할당을 등록하고 생성한 identity를 보관한다.
worker 산출물도 부모가 exclusive 생성해 identity를 등록한 파일에만 쓰도록 전달한다.
자식이 path를 교체하면 원래 identity와 달라지므로 정리를 거절한다. DB 원장은 실행 root
단위로 유지하며 메모리 manifest가 사라진 재시작 후에는 자동 정리를 하지 않는다.
marker·상위
경로·작업공간을 Windows 핸들로 고정하고, 경로로 재귀 삭제하지 않는다. 하위 디렉터리와
파일도 핸들로 열어 reparse/교체/경로 이탈/예상 밖 hardlink를 거부한다. 삭제 전 전체
트리를 manifest와 대조하고 각 항목의 identity를 검증한 뒤 열린 핸들에 삭제를 요청한다.
라이브러리가 만든 미등록 scratch 항목은 root 안에 있어도 삭제 소유권을 추정하지 않고
전체 정리 시작 전에 차단한다. 검증 중 새 항목 또는
변경이 발견되면 정리를 중단해 cleaning과 차단 사유를 보존한다. 일부 정리가 성공한 뒤
실패해도 cleaned로 전이하지 않는다. 임의 파일을 삭제할 권한으로 root 소유권을 확대하지 않는다.

## 5. 예약 트랜잭션과 호출 경계

독립 session factory로 예약을 commit하고 나서 파일을 만든다. 호출 session이 source/job
FOR UPDATE를 보유한 채 독립 예약을 기다리면 FK 검사부터 자기 대기가 생길 수 있다.
따라서 lifecycle transaction 종료 → 불변 실행 문맥 추출 → 예약의 순서를 지킨다.
미커밋 source/job을 대상으로 예약하지 않는다. timeout으로 이 문제를 우회하지 않는다.

다른 worker와의 순환 대기도 피해야 한다. 예약의 잠금 순서는 기존 RAG와 맞춰
job → asset_version → document → 임시 원장으로 고정한다. job 없는 preview는 첫 단계를
생략한다. document gate를 먼저 잠근 뒤 job/version FK를 검사하지 않는다. 문서 gate만
보유하는 경로는 뒤에서 job/version 잠금을 추가하지 않아야 하며, 구현 전에 해당 경로도
검사한다. 서로 다른 session의 예약/worker/gate 경쟁을 통합 테스트에 포함한다.

구현 검토에서 아직 제품 호출이 없는 `PurgeInventoryRepository._require_exact_batch_targets`의
document→version 역순 잠금을 확인했다. 해당 purge 저장 경로의 활성화는 순서 통합과 추가
경쟁 검증 전까지 금지한다. 이번 구현은 기존 미활성 purge 경로까지 교착 방지를 완성한 것이 아니다.

예약은 exact source/job 소속, 현재 generation과 쓰기 허용 상태를 검증하고 삭제 gate와
직렬화한다. 허용 상태는 기존 문서 쓰기 gate와 일치시키며 trash/purging 또는 세대 변경 시
새 예약을 거절한다. 이후 purge는 open/closed/cleaning 원장을 무시하고 진행할 수 없다.
gate 경쟁에서 예약이 먼저면 정리 차단 자원이 남고, gate가 먼저면 물리 파일 생성이 없다.

RAG `lifecycle.begin` 반환 이후 `ParsingService` 진입 전은 예약에 적합하다.
`_load`, artifact finalize, readiness 활성화 transaction 안에서는 예약하지 않는다.
preview는 권한 확인된 resource로 문맥을 만들고, 공유 renderer에 request session을
보관하지 않는다. 파일 읽기/응답의 기존 최종 권한 재확인은 유지한다.

## 6. 파서와 preview 연결

- `IngestionExecution`과 `ParsingPort`는 exact SourceIdentity와 job_id를 전달한다.
  `tasks.py`가 로드한 document.workspace_id에서 문맥을 구성한다.
- `ParsingService`는 예약된 root에 검증된 suffix의 고정 파일명을 사용한다.
  `ParseRequest`에 작업공간을 전달하고 parser 인스턴스의 가변 필드에 저장하지 않는다.
- DOCX 이미지와 PDF OCR page/region 임시 파일은 같은 작업공간 아래 생성한다.
  각 parser의 OS TemporaryDirectory와 독립적인 path cleanup을 제거하고 소유 어댑터가
  하위 할당·정리를 담당한다. 동기 parser는 DB session을 소유하지 않는다.
- 현재 parser/OCR은 동일 이벤트루프에서 동기 실행한다. 이번 작업에서 무심코 to_thread로
  옮기지 않는다. 예외/취소를 받았다는 사실만으로 native/background writer 종료를 보장하지 않는다.
  실행 종료를 확인할 수 없는 런타임은 open 및 coverage 차단을 남긴다.
- `PdfRenderer.inspect/render_page`는 bytes 외에 권한 확인된 source 문맥을 받는다.
  semaphore 획득 → 예약 commit → 입력 생성 → spawn 순서를 지킨다.
- PDF preview의 terminate → 필요시 kill → wait/reap → 정리 → slot 반환 순서를 유지한다.
  반복 cancellation도 종료 대기를 끊지 않는다. 종료 실패 시 기존 TemporaryDirectory의
  finally 자동 삭제를 수행하지 않고 open을 보존한다.
- worker의 TEMP/TMP는 전용 root를 유지한다. 부모 process 환경을 전역 수정하지 않는다.
  자손 프로세스와 라이브러리 외부 쓰기는 현재 구현만으로 격리됐다고 주장하지 않는다.

## 7. 읽기 목록과 삭제 차단

모든 버전의 원장과 현재 출처 관계를 일관된 DB snapshot으로 읽고, 물리 관측 전후의
revision/관계/원장 집합을 대조한다. 새 예약·상태 변경·binding 불일치·열린 writer·잔존 파일·
미검증 coverage·legacy는 incomplete다. 목록이 비었다는 사실은 과거 임시 파일 부재의 증명이 아니다.
cleaned는 해당 token의 관측 시점 부재를 뜻하며 저장소 전체나 문서 전체 부재를 뜻하지 않는다.
공개 결과는 resource ID·revision·고정 차단 코드만 반환하고 경로·PID·원문을 노출하지 않는다.

상세 원장과 job/source는 잔존 검증 전 삭제하지 않는다. Job 삭제는 RAG ingestion/outbox를
CASCADE하므로 locator 검증보다 먼저 실행할 수 없다. 이번 단계는 RESTRICT pin을 추가하지만
모든 기존 삭제 경로의 보존을 완성했다고 주장하지 않는다. 실제 purge 실행은 계속 미활성이다.

## 8. 후속 경계

HTTP UploadFile은 route/coordinator보다 앞의 request.form에서 spool을 만든다.
따라서 기존 원본 예약이나 이번 parser 예약으로 HTTP spool이 추적되지는 않는다.
후속은 본문 파싱 전 인증·예정 source 예약, request 전용 spool factory, disconnect/실패 정리와
원본 예약 연결을 함께 설계한다. 전역 tempfile monkeypatch와 무제한 메모리 적재는 사용하지 않는다.

일반 Jobs는 별도 participant로 job 행만 소유한다. 신규 revision 1, legacy NULL과 현재 관계
교체가 필요하고 `assets/dispatch.py`의 직접 ORM 변경·bulk UPDATE까지 같은 transaction으로
연결해야 한다. RAG ingestion/handoff/outbox는 기존 RAG 소유로 남기며 jobs 목록으로 대체하지 않는다.

## 9. 구현 성공 기준과 검증

1. 예약/commit 실패나 불명 상태에서 mkdir/write/spawn이 0회다.
2. 다른 source/job/binding/generation을 거절하고 gate 경쟁·FK 보존을 격리 PG로 검증한다.
3. parser·DOCX·PDF OCR의 알려진 임시 경로가 예약 root 안에만 생성된다.
4. preview 정상/timeout/취소/반복 취소에서 reap 선행을 확인하고 종료 실패 시 root를 보존한다.
5. reparse·hardlink·경로 교체·새 항목·정리 도중 오류에 다른 파일을 지우지 않는다.
6. open/closed/cleaning/legacy/coverage 불명 및 수집 중 변경이 complete로 승격되지 않는다.
7. 원문 권한 재검사, parser 결과, OCR fake runtime, preview 실제 worker 회귀를 유지한다.

단위 테스트는 합성 파일/fake 모델과 네트워크 없이 실행한다. PG 테스트는 명시적인
test 환경 및 전용 loopback URL guard가 있는 격리 fixture만 사용한다. Python 타입/린트와
독립 DB·코드/프라이버시 검증을 포함한다. 실사용 DB, 기존 OS temp와 사용자 파일은 검증에 쓰지 않는다.

구현 역할은 DB 원장, 파일 어댑터, parser/preview 연결로 분리하고 독립 검토를 별도 배정한다.
구현 계획에서 테스트 명령과 파일 소유 범위를 확정한다.
