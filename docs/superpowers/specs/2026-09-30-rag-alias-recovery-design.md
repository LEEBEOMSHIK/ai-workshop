# RAG 미종료 별칭 요청의 정상 복구

- 상태: 구현·독립 검토 완료, 본래0061·SAVEPOINT 검증 반영. 실제 호스트 지원 경계 미충족으로 legacy 종료·해제·새 정상 parity는 미완료(2026-10-01).
- 날짜: 2026-09-30
- 문제: ISSUE-00013
- 선행: [별칭 원장·쓰기 차단](2026-09-20-rag-alias-write-fence-design.md)
- 결정: [ADR-0032](../../decisions/0032-rag-alias-recovery.md)

## 본래 반영 상태 — 2026-10-01

원장·gate·receipt와 local collector/CLI는 구현·독립 승인했고 본래0061 migration과
외부 COMMIT 없는 SAVEPOINT3건을 검증했다. 실제 HOST 관찰은45초 제한을 초과했으며,
현재 IDE/Codex 도구·frontend build child·Docker build process는 아래 exact 지원 범위에
포함되지 않는다. 이름·서명·부모·현재 연결 부재만으로 일괄 허용하지 않는다.
호스트 지원 경계와 freeze 전 사전 검사 재설계가 필요하다.

기존 요청은 `legacy_unknown/open`, 같은 request의 frozen revision1·receipt0을 유지한다.
ES stop/start·종료·해제·새 정상 parity는 실행하지 않았다. gate는 **같은 클러스터의 모든
새 별칭 예약·전송**을 차단한다. 원래 API·worker·beat와 frontend의 기동/health는 정상이나
별칭 정합성 복구 또는 새 모델 답변의 검증 완료가 아니다. 계정·자료·활성 구성은 보존했다.
실행 근거와 남은 순서는 [작업 기록](../../worklogs/2026-09-30-rag-alias-recovery.md)을 따른다.

## 목적과 성공 기준

종료 근거가 없는 요청을 열린 상태로 보존하는 기존 원칙을 유지하면서, 종료를 실제로 입증한
정확한 요청만 복구한다. 기존 계정·자료·색인·구성·첫 질문 기능을 보존한다. 복구 후 일반
profile parity가 현재 DB 기준으로 성공하고, 본래 환경에서 반복 busy가 해소돼야 완료다.
품질 튜닝·모델 변경·삭제 API/UI·fence 해제·색인/큐/파일 삭제는 이 작업에 포함하지 않는다.

현재 원장은 예약 commit 뒤 전송 전 관찰 실패와 전송 후 timeout을 구분하지 못한다.
과거 open 요청의 실제 실패 시점은 미확인이다. 현재 target 일치, 빈 task, 시간 경과,
worker 재시작 또는 terminal Job은 종료 증거가 아니다. Elasticsearch timeout 뒤에도 metadata
갱신이 적용될 수 있다([공식 설명](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/indices-aliases.html)).

## 대안과 경계

1. 현재 alias가 같으면 원장을 해제: 늦은 writer를 배제하지 못하므로 거부.
2. 별도 종료 증거와 정확한 원장 전이를 갖춘 내부 운영 CLI: 채택.
3. 공개 복구 API·관리자 버튼: 지원할 원격 종료 collector가 없고 노출을 늘리므로 후속.

업무 정책은 Labs/RAG Indexing의 서비스·repository에 두고 OS/Docker/ES 수집은 어댑터로
분리한다. Platform은 RAG에 의존하지 않는다. 기존 `ai_workshop.cli` 또는 전용 모듈 CLI로
진입하며 public app에는 등록하지 않는다. local 환경의 기존 활성 owner와 호스트 운영 권한을
함께 요구한다. OS 운영자는 DB/Docker 접근 권한을 가진 신뢰 주체이며 owner UUID 자체가
일반 웹 인증을 대신하는 계약은 아니다. owner 부재·비활성·member는 조회/변이를 거부한다.

## 요청 단계와 클러스터 유지보수

신규 원장은 `reserved → dispatching`을 단방향 CAS로 기록한다. 기존 행은
`legacy_unknown`으로 보존하며 전송되지 않았다고 backfill하지 않는다. 전송 진입은 현재
cluster gate와 exact operation을 같은 짧은 거래에서 확인한다. gate가 frozen이거나 요청이
닫혔으면 실제 mutate callback을 실행하지 않는다. dispatch commit의 결과가 불명확하면
SDK 전송도 하지 않는다. 현재 callback 안의 읽기/무변경 경로는 보수적으로 dispatching에
포함한다. 이를 실제 HTTP 전송 시각이라고 표시하지 않는다.

cluster UUID로 admission gate를 저장한다. 초기 released/admitted 상태와 frozen 상태,
유지보수 request UUID·owner·revision을 기록한다. reserve와 dispatch 둘 다 gate와 직렬화한다.
유지보수는 정확한 operation snapshot을 묶어 acquire하고, 같은 request/payload만 재접수한다.
다른 owner/request나 오래된 revision은 충돌이다. 시간 기반 takeover·자동 만료 해제는 없다.
중단되면 frozen을 유지하고 같은 요청으로 상태를 조회/이어간다. 다른 scope에 열린 요청이
있다고 bulk close하지 않는다. release도 exact owner/claim/revision과 목표 요청의 종료 상태를
확인하며, 미종료 요청을 우회하는 범용 unlock 명령을 제공하지 않는다.

source → profile → build → 독립 journal 거래의 기존 순서를 유지한다. gate/원장은
caller가 잠근 source/profile/build에 FK를 추가하지 않는다. gate 거래나 journal 행 잠금 중에
프로세스 종료·ES 재시작·네트워크 호출을 수행하지 않는다. drain은 거래 밖에서 수행한다.

## 두 가지 종료 경로

### 전송 전 예약

exact reserved 요청을 CAS로 `closed / not_dispatched` 전이하고 불변 복구 receipt를 같은
거래에 저장한다. 예약 폐쇄와 dispatch CAS는 한 요청에서 하나만 이긴다. 폐쇄를 놓친 늦은
caller는 dispatch 실패 뒤 mutate를 호출할 수 없다. legacy_unknown/dispatching에는 이
경로를 적용하지 않는다. 현재 alias 관찰은 이 판단에 필요하지 않다.

### 전송 후/과거 미확인 요청

`closed / recovered_terminated`는 원래 요청의 성공을 뜻하지 않는다. 원래 결과가 미확인인
채로 더 이상 쓸 수 없다는 증거다. `confirmed`는 기존 invocation의 정확한 ack/target 관찰 의미를
유지한다. 복구 서비스는 정상 finish를 강제 종료로 재사용하거나 이전 target을 재전송하지 않는다.

처음 지원하는 collector는 **신뢰하는 운영자가 관리하는 Windows local·직접 loopback·기존
Docker single-node Elasticsearch**로 한정한다. 원격/프록시/터널/WSL writer·multi-node·미확인
client나 endpoint 이력이 있으면 이 collector로 복구할 수 없다. host/Docker의 구성되지 않은
외부 관리자 또는 공격자를 이 방식이 격리했다고 주장하지 않는다. 로컬 통제 경계는 runbook에
명시하고 진단에서 관찰된 미확인 프로세스·연결·네트워크 peer는 거부한다.

현재 본래 호스트의 관찰 helper와 controller는 이미 설치된 공식 Microsoft PowerShell7.6.6
ARM64 패키지의 정확한 실행 경로·SHA256에 고정한다. 서명 확인은 반영 전에 운영자가 검증하고,
실행 직전 경로·파일·해시를 재확인한다. WindowsApps 버전 wildcard, PATH 탐색이나 실패 후 다른
PowerShell로 자동 전환하지 않는다. Windows PowerShell5.1의 서명 모듈 로드 실패는 기록하되
보안 정책이나 설치 환경을 변경하지 않는다. 이 고정값의 변경은 새 배포 검증을 요구한다.

legacy 요청의 배포 provenance는 collector가 고정된 원래 배포 기록을 직접 읽어 검사한다.
요청 예약 전부터 보존된 original 환경 백업의 local/direct endpoint·관찰된 cluster UUID,
현재 같은 immutable container의 생성·설정·mount identity를 함께 검증하고 안전한 source digest를
증거에 묶는다. 임의 입력 파일/JSON 또는 `history_verified=true` 인자를 받지 않는다. 이 기록은
원래 배포를 뒷받침하며 개별 과거 invocation의 환경을 사후 암호학적으로 증명하지는 않는다.
미신고 endpoint override·복제 cluster·수동 writer 또는 privileged 기록 변조가 없다는 신뢰하는
운영 경계가 필요하다. 이를 전제로 둘 수 없거나 기록이 부족하면 복구를 거부한다. Docker Desktop의
검증된 인프라 WSL만 허용할 수 있으며 사용자 distro/writer·미확인 tunnel은 지원하지 않는다.

검증 순서는 다음과 같다.

1. exact 원장·binding·canonical profile/processing alias·target fingerprint를 preview한다.
   cluster gate를 frozen으로 commit한다. schema/계정/구성이 바뀌면 이후 apply를 거부한다.
2. API/worker/beat와 이전 코드/CLI sender 및 재시작 supervisor를 종료·확인한다. 큐는 보존한다.
   trusted OS inventory에서 command line 미확인 Python, 다른 project writer, unknown 연결/peer를
   배제한다. collector 자신의 정확한 PID·생성 시각·실행 모듈과 venv launcher만 허용한다.
3. 정확한 기존 container ID·immutable single-node 설정·생성 이력·volume/mount·publish endpoint와
   ES cluster/node/master의 일치를 검사한다. 과거 요청이 이 통제된 직접 endpoint에 속한다는
   조건이 성립하지 않으면 old JVM 시작 시각만으로 대체하지 않는다.
4. clients가 종료된 뒤 같은 ES container를 stop하고 실제 not-running/종료 시각을 확인한다.
   이어 동일 데이터/mount를 보존해 start한다. remove/recreate/volume prune은 사용하지 않는다.
5. 같은 cluster UUID·영속 node ID와 다른 ephemeral ID/새 JVM generation·정상 단일 노드 상태를
   확인한다. 서버가 예전에 재시작됐다는 사실만으로 적용하지 않는다. 기존 요청은 예약 이후
   늦게 전송됐을 수 있으므로 이번 client 종료 뒤 실제 server 교체를 증명한다.
6. gate 소유권·actor·정확한 snapshot·client 부재·container/ES identity를 다시 검사한다.
   trusted collector가 allowlist 사실만 담은 typed evidence를 만든다. 임의 JSON 증명/true flag,
   파일 해시 자체, task 없음은 proof port를 대신하지 못한다.
7. exact operation 행을 잠그고 snapshot CAS와 evidence/receipt 저장·terminal 전이를 한 거래로
   commit한다. 증거가 부족하거나 변하면 open/frozen을 유지하고 안전한 사유를 반환한다.

collector 실패 뒤 ES가 중지됐다면 동일 ID/volume으로 서버를 다시 켤 수 있지만 이를 복구 성공으로
표시하지 않는다. 원장은 open, gate는 frozen을 유지한다. 새로운 proof는 동일 유지보수 request의
현재 상태와 exact snapshot을 재검증한 뒤 얻는다. commit 응답 유실은 exact receipt 조회로 복구한다.

## 영속 계약과 멱등성

현재 head0060 뒤 additive revision을 추가한다. 원장에 phase를 추가하고 gate 및 불변 receipt를
저장한다. 원장 identity·targets·created_at과 closed 행의 변경 금지는 유지한다. result는
confirmed/not_dispatched/recovered_terminated만 허용하며 복구 결과에는 exact receipt가 필수다.
receipt는 operation당 하나, request UUID·actor·snapshot SHA256·proof 종류/버전·gate claim,
허용된 client/server incarnation 사실·proof digest·시각을 저장한다. 본문·파일명·credential·URL·
전체 command line·원시 오류는 저장하지 않는다. FK는 exact journal/owner 같은 짧은 거래 경계에만 둔다.

같은 request·actor·payload는 저장된 결과를 반환한다. 다른 payload/actor/evidence는 충돌이다.
정상 finish가 먼저 이기면 confirmed를 보존하며 복구 성공을 꾸미지 않는다. 이미 닫힌 요청의
재접수는 같은 alias의 이후 새 요청을 건드릴 수 없다. receipt와 closure의 rollback은 함께
적용되고 unknown commit은 새 request나 ES mutation으로 확인하지 않는다.

새 데이터/증거 또는 frozen gate가 있으면 downgrade를 거부한다. evidence를 지우거나
recovered_terminated를 confirmed로 변환해 downgrade하지 않는다. migration은 기존 문서·
작업·fence·active 구성·물리 색인을 변경하지 않는다. 구 writer와 새 writer의 혼합 배포는 지원하지 않는다.

## 수렴과 검증

원장의 종료와 parity 성공을 별도로 보고한다. gate의 controlled release 후 clients가 중지된 상태에서
기존 `run_once(profile_id=...)`를 한 번 호출한다. 현재 active READY 원문·Projection·Build·fence를
기준으로 새 operation을 만들고 정상 ack/target/Build flag를 확인한다. 실패하면 새 open을 보존하고
복구를 재귀 수행하지 않는다. 이후 동일 환경의 API/worker/beat를 재시작한다.

외부 모델 없는 단위 테스트로 actor/scope/phase/gate/증거 거부·rollback/unknown commit·재접수/ABA·
dispatch 경합을 검증한다. OS/Docker/ES는 fake port로 실패 경계를 시험하고 실제 proof와 구분한다.
본래 DB opt-in SAVEPOINT/outer COMMIT 차단/rollback으로 제약·trigger·receipt 원자성을 검증한다.
별도 DB/account/ES 자원을 만들거나 기존 provisioning fixture를 실행하지 않는다. 단일 연결 검증은
commit된 다중 연결 경합을 입증하지 않는다. 실제 원장 복구·scoped parity·프로세스/health·기존
자료/활성 연결 보존은 독립 본래 환경 검증의 완료 조건이다.
