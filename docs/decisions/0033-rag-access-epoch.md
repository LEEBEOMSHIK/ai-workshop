# ADR-0033: RAG 서버 측 접근 epoch로 늦은 별칭 쓰기 차단

- 상태: 사용자 설계 승인(2026-10-01), 구현 계획 작성 중·본래 배포 미승인
- 날짜: 2026-10-01
- 문제: ISSUE-00013
- 계약 초안: [상세 설계](../superpowers/specs/2026-10-01-rag-access-epoch-design.md)

본래 개발 도구는 v1의 전체 client 종료 지원 경계 밖이다. 범용 tool 예외 또는 현재
TCP 부재를 종료 증거로 쓰지 않는다. 기존 named ES 데이터 볼륨을 유지하면서 이전 accepting
JVM을 끝내고, 새 TLS·인증 서버가 이전 익명 capability를 거부하는 접근 epoch 전이를 제안한다.

fresh ES service credential은 새 application 세대에만 주며 root .env/hot refresh/proxy로
과거 callback을 승격하지 않는다. 프로젝트 전용 CA만 사용하고 OS 전역 신뢰를 바꾸지 않는다.
기존 ES 컨테이너 메타데이터의 정확한 제거와 secured 재생성은 별도 구체적 배포 승인 대상이다.
원본 볼륨·DB·계정·문서·색인·큐와 IDE·Codex·frontend는 보존한다.

v2 proof·영속 epoch/floor·외부 execution 소유권과 schema 제약을 함께 도입한다.
v1 proof와 receipt 의미는 유지한다. unknown 외부 결과는 frozen이며 closure/release를 금지한다.
종료 뒤 auth-off rollback은 금지하고 secured forward repair만 지원한다.
본래 종료·receipt·gate release·현재 DB truth parity는 별도 검증하며 아직 실행하지 않았다.

## 2026-10-08 읽기 전용 사전검사 구현 범위

승인 계획 Task4의 native 사전 관찰을 `preflight-access-epoch`로 먼저 제공한다.
이 명령은 기존 소유자의 operation preview 권한을 확인하고 원래 고정 Docker context/daemon/container,
기존 named volume·이미지 및 실제 단일 ES 노드만 읽는다. 원래 volume/image 식별자는
[실측 기록](../worklogs/2026-10-02-rag-access-epoch-implementation.md)의 원래 배포를 기준으로 한다.
v1 `preflight`의 전체 client 종료 검사·전역 running container 제외는 v2에 재사용하지 않는다.

관찰이 정상이어도 과거 제어 명령의 definitive settlement는 `unknown`으로 분리하고 결과는
항상 `blocked`, `termination_proven=false`, `parity=not_run`이다. 전체 ingress와 독점 volume 사용,
실제 native controller·secured forward repair 준비를 증명하지 않는다. raw inspect/env/키/오류를
출력하지 않으며 새 epoch/claim/proof/credential 생성, 제어 명령, 복구·해제는 호출하지 않는다.
이 명령의 정상 관찰은 실제 cutover 승인이거나 실행 가능한 복구 완료가 아니다.

## 2026-10-08 제어 소유권 계약 보완

승인 계획 Task4의 소유권은 execution UUID만으로 인정하지 않는다. 기존 execution의
영속 `executor_generation`을 readback으로 읽고, typed `ControlOwnership`의 execution·generation·
control-port UUID를 현재 포트와 정확히 대조한다. 포트의 `assert_owned`는 이전 executor·자식·
daemon 작업의 종료 증거와 직렬 소유권 유지 여부를 확인해야 하며 TTL이나 관찰 부재로 대체하지 않는다.
포트의 acquire·expected·execute·reconcile은 동일 소유권을 명시적으로 전달받는다.

controller는 예약·실행·재조정·정산 및 최종 관찰·anchor·verified 저장 경계마다 소유권을 재검사한다.
예약 뒤 제어권을 잃으면 pending을 그대로 두고 재발행하지 않는다. 기존 action의 execution·generation도
대조하며 acquire·assert_owned 오류 본문은 고정 오류로 제한한다. fresh readback이 이미 verified 또는
receipted이면 제어·관찰·anchor 호출을 반복하지 않고 반환한다. check와 실제 submission 사이의 경쟁은 native 포트가
동일한 직렬 소유권 아래 직접 막아야 한다. 이 generic 검증은 실제 OS mutex나 과거 종료 증거를
구현한 것으로 간주하지 않으며, 기존 DB 스키마·v1 proof·실제 frozen gate 상태를 바꾸지 않는다.

소유권을 획득한 현재 controller의 완료 반환에도 동일한 경계를 적용한다. mark_verified 뒤와
마지막 readback 뒤에 소유권 및 영속 execution·generation을 재검사한다. active 호출의 fresh
completed 반환도 검사를 거친다. 실패하면 해당 호출은 새 proof를 반환·등록하지 않는다.
이미 정당하게 저장된 verified/floor는 되돌리지 않으며 별도의 정확한 readback/재접수로 처리한다.
소유권 획득 전 확인한 기존 verified/receipted의 읽기 전용 재접수는 기존 계약을 유지한다.

## 2026-10-08 Windows 잠금 보유 구현 범위

Task4의 OS 잠금은 Infrastructure의 동기·thread-affine primitive로 먼저 구현한다.
검증된 daemon identity SHA와 Compose project에서 고정 Global namespace 이름을 도출하고,
CreateMutexW(initial_owner=false) 뒤 WaitForSingleObject(timeout=0)를 한 번만 호출한다.
같은 스레드·같은 이름의 다른 인스턴스도 재귀 획득하지 못하도록 프로세스 내 등록을 유지한다.
소유 스레드 객체·native thread ID와 exact execution/generation/session token을 고정하고,
assertion은 재wait 없이 검사한다. 획득·검사·해제는 같은 스레드에서 수행한다.
향후 async 포트는 한 owner thread에 이 호출들을 배치해야 하며 호출마다 threadpool로 보내지 않는다.

WAIT_ABANDONED는 실제 획득된 잠금을 같은 스레드에서 해제·close한 뒤 거부한다.
busy/실패/잘못된 token·thread는 고정 오류를 반환하고, cleanup이 미확정이면 세션과 동일
스레드의 이름 등록을 재사용하지 않는다. 정상 close도 해당 인스턴스를 재획득하지 않는다.
이 잠금의 clean acquisition은 durable execution takeover나 과거 command settlement 증거가 아니다.
Global namespace는 협조하는 Windows 세션 간 직렬화 범위이며 DACL 기반의 보안 fence,
악성 동일 사용자/관리자 차단, daemon endpoint 폐기를 의미하지 않는다.

primitive에는 caller callback·shell·Docker submission·proof 발급 기능을 두지 않는다.
실제 CutoverControlPort 연결은 durable 소유권·과거 자식/daemon 작업 종료·동일 잠금 아래
고정 command submission과 journal을 함께 구현할 때만 가능하다. 이번 구현은 서비스에
자동 조립하지 않으며 실제 별칭 복구·gate 해제·색인 완료 계약을 바꾸지 않는다.

## 2026-10-08 제출 이력 기록 경계

RAG의 보호 journal은 실제 launcher를 조립하기 전에 recording-only 계약으로 제공한다.
잠금의 readonly scope digest와 execution/generation/session, action/순서/kind/expected digest를
대조한다. fresh ticket의 내부 nonce는 새 expected payload에 포함되며 발급 객체 자체를
한 번만 소비한다. 기존 pending action에 새 ticket을 붙이거나 파일 부재만으로 새 제출을
허용하지 않는다. begin 시도는 보호 파일 쓰기 전에 ticket을 소비하고 exact readback을
요구하며, 응답 유실이나 오류 후 같은 ticket으로 다시 쓰거나 제출하지 않는다.

intent → process_created → process_finished 또는 unknown을 기록하고 PID+creation time+Job
식별자가 다른 종료 결과는 거부한다. unknown은 terminal이다. caller가 읽은 과거 record로
append하지 않으며 새 세션에서는 읽기만 한다. 레코드는 비밀/argv/output 없이 typed 관찰만
담는다. process_finished는 local child 관찰이며 daemon 작업의 definitive settlement가 아니다.

기존 Infrastructure DPAPI/owner ACL 파일 포트를 사용하고 RAG 업무 타입은 Infrastructure로
옮기지 않는다. begin은 실제 DB reservation commit 검증이나 command submission 증거가 아니다.
파일의 fsync/replace/ACL 검사는 namespace commit의 crash durability나 anti-rollback을
입증하지 않는다. 원래 환경에서의 이 경계와 durable DB/journal reconciliation, suspended
child/Job 등록·동일 잠금 아래 resume·daemon 결과 연결이 준비되기 전 실제 native 포트에
조립하지 않는다. 이번 기록 API에는 launcher/callback/shell/proof 발급 기능이 없다.

## 2026-10-08 실제 자식 실행 연결 범위

Task4의 Windows 자식은 CreateProcessW의 suspended·hidden 상태로 만들고
PROC_THREAD_ATTRIBUTE_JOB_LIST로 생성 시점부터 별도 Job에 넣는다. 생성 후 assign 사이의
crash 공백을 피하며 Job은 unnamed/noninheritable·KILL_ON_JOB_CLOSE, breakaway 불허다.
선택한 표준 입출력 handle만 상속하고 출력은 제한된 private capture로 처리한다.
실제 process handle에서 PID/creation을 관찰하고 exact issued token의 같은 스레드에서
resume 한 번만 허용한다. process signal과 Job active count 0을 함께 확인해야 local 종료다.
자기 Job cleanup이나 local exit는 daemon 위임 작업의 종료 증거가 아니다.

RAG 제출 연결은 fresh repository readback의 exact epoch/generation/open/frozen 상태와
committed pending action을 확인한 뒤 intent → suspended child 기록 → resume → local 결과를
연결한다. 원래 immutable container의 STOP/RETIRE만 고정 argv로 제공하며 rm에는 force/volume
옵션을 넣지 않는다. Docker는 원래 context의 검증된 named-pipe 주소를 argv에 직접 고정한다.
출력 bytes는 보호 파일에만 저장하고 오류/manifest에는 담지 않는다. ACK 유실/취소/실패는
재제출하지 않으며 자기 자식만 정리한다. fresh ticket과 missing journal은 과거 action의 재발행
권한이 아니다. 이 연결은 완성된 CutoverControlPort/CLI에 자동 조립하지 않는다.

실환경 사용에는 과거 제어의 확정 종료, durable DB/journal reconciliation 및 namespace
durability, daemon settlement, 보안 전환/관찰/anchor 경계가 여전히 필요하다. 과거 DPAPI
journal 자체를 유일한 증거로 요구하지는 않는다. 실제 과거 tool completion과 정확한
대상/daemon/terminal readback의 결합을 조사하되 앱 재시작을 Compose 재생성으로 확대하지 않는다.
공식 API 근거: [CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw),
[UpdateProcThreadAttribute](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute),
[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

## 2026-10-08 보안 시작 자산과 daemon 종료 관찰

bootstrap Compose는 기본 Compose와 합치지 않는 독립 파일로 제공한다. 원래 external data
volume만 사용하고 network none·restart no·pull never를 적용한다. HTTP/transport 각각의
node key·node certificate·public CA 여섯 파일만 readonly bind하며 CA signing key와 controller
credential 디렉터리는 mount하지 않는다. local config image ID와 registry manifest digest는
다른 식별자다. 고정 image inspect의 닫힌 projection에서 정확한 원래 config ID에 연결된
RepoDigest를 관찰한 뒤 사용한다. 문자열을 바꾸어 config ID를 manifest처럼 쓰지 않는다.
최종 secured Compose도 독립 파일이며 원래 external network와 loopback 9200만 사용한다.
9300은 publish하지 않는다. 원래 network ID/IPAM·사용 가능한 검증된 IPv4와 HTTP SAN을
대조한 controller만 필수 public 참조를 공급할 수 있다. 새 default network를 만들거나
보안 비활성 기본 Compose와 합쳐서 기존 노출을 물려받는 경로는 제공하지 않는다.

STOP/RETIRE의 settlement는 exact committed reservation·보호 journal의 동일 자식 완료와
동일 daemon readback을 결합한다. STOP은 exit0와 정확한 old ID의 nonrunning/nonrestarting,
원래 StartedAt 및 유효 FinishedAt을 함께 확인한다. RETIRE는 이전 settled STOP의 종료 시각과
exit0를 요구하고 성공한 전체 container ID 목록에서 old ID의 부재를 확인한다. inspect 실패,
timeout, 빈 오류 출력만으로 부재나 과거 종료 시각을 만들지 않는다. 이 관찰은 고정 old-ID
동기 명령의 완료에만 적용하며 Compose/create 등 다른 위임 작업에 확대하지 않는다.

private helper 입력은 argv/environment에 담지 않고 bounded 전용 stdin pipe로 전달한다.
기본 NUL 입력 계약은 유지하며 명시적 입력의 parent handle은 상속하지 않는다. child의
출력과 입력을 제한시간 안에서 함께 drain하고 EOF handle을 한 번만 소비한다. 입력 bytes와
그 hash는 journal·manifest·오류·로그에 넣지 않는다. 구현의 실제 Windows 검증과 독립 리뷰
전에는 원래 보안 helper에 연결하지 않는다.

## 2026-10-08 유한 과거 기록의 재검증

기록이 없는 모든 OS 작업을 추정해 영구 차단하지 않는다. 내부 reader가 고정된 본래
기록 범위에서 실제 제출 call·배치의 해당 명령·yield/poll terminal chain을 다시 검증한다.
review용 JSON의 settled label이나 caller path/boolean은 증거로 받지 않는다. 실패한 앱 종료는
성공한 종료가 아니며 collector exit1은 당시 refusal 단계와 동일 세대 사후 관찰을 함께
확인해야 pre-submission으로 분류한다. 실제 확인된 pending recreate는 계속 차단한다.
관찰한 기존 컨테이너 startup의 initiator가 미기록인 사실은 범위 제한으로 남긴다.

유한 prefix 안에서도 식별한 original control과 근거 call은 모두 닫힌 문법으로 검증한다.
누락된 original Docker/application/collector 호출과 해당 target의 argv·import alias·dataflow
미해결은 계속 거부한다. target 결속 증거가 없는 일반 helper의 미지원 문법은 범위 밖
미판정으로 보존하며 noncontrol/settled/coverage 성공에 넣지 않는다. 이 영수증은 prefix의
모든 OS 호출이나 미기록 startup initiator의 종료를 증명하지 않으며 최종 controller의
현행 native/daemon 종료·보안 전환 검사를 대신하지 않는다.

기존 security metadata가 없다는 bootstrap 경로는 caller boolean으로 승인하지 않는다.
내부 observer가 동일한 원래 deployment identity를 전후 확인하고 고정 원래 endpoint에서
hidden security index 목록의 실제 빈 응답을 확인한 발급 객체만 소비한다. timeout·권한 오류·
미지원 응답·빈 문자열은 부재가 아니다. 기존 security index가 하나라도 있으면 이 경로를
중지하며 임의 폐기하거나 새 관리 암호로 덮어쓰지 않는다.

Bootstrap 명령 조립은 이 observer의 exact 발급 객체와 deployment reader의 exact bootstrap
발급 객체를 함께 소비한다. 후자는 같은 epoch/execution의 START_BOOTSTRAP settled DB
manifest와 일치해야 하며, 현재 frozen/open claim·generation·Windows owner를 전후 검사한다.
복사 DTO나 caller의 security-absent boolean은 명령 조립 권한이 아니다. 조립 결과 또한
원래 project root의 보호 journal에 결속하며, 실제 실행은 별도 fresh 예약과 제출 검사를
필요로 한다. 조립만으로 암호·key 발급이나 종료 proof를 만들지 않는다.

관리 암호 reset의 local 종료와 bootstrap 보안 검증은 분리한다. 동일 발급 관리 credential로
reserved realm 인증·built-in user 목록·빈 API key 목록을 실제 조회하고, fresh bootstrap의
users/users_roles 두 고정 file-realm 파일에서 유효한 non-comment 행이 없음을 각각 확인한다.
조회 helper도 보호 journal/catalog에 기록하고 이전 local 상태가 미확정이면 다음 조회나
mutation을 제출하지 않는다. 응답 부재·비정상 종료·시간 초과는 빈 목록이 아니다.
원래 security metadata 부재 관찰과 함께 이 검증이 모두 성공해야 해당 bootstrap 보안
단계를 정산할 수 있다. 과거 principal을 임의 폐기하는 경로는 추가하지 않으며 실제
검증이 없으면 audit pending을 유지한다.

gate는 reader가 발급한 opaque facts만 받고 exact prepared epoch·DB generation·원래 identity와
같은 Windows owner/session을 전후 검사한다. private 출처/자료는 기존 DPAPI/ACL 포트로
보관·readback하고 공개 manifest에는 정제한 종류·상태·건수와 업무 binding만 담는다.
원문 session·환경·출력의 hash나 locator는 공개하지 않는다. opaque history ticket은 복사한
DTO로 대체할 수 없고 action 예약·native 실행·credential 발급·최종 proof를 허용하지 않는다.
fresh original identity는 읽기 전용 metadata에서 원래 container/image·named volume 생성/driver/
mountpoint·single-node stable/ephemeral ID·JVM 시작을 대조하여 만든다. secret 가능성이 있는
Config.Env 전체나 원시 Config/HostConfig를 hash하지 않는다. 승인된 공개 설정과 topology의
닫힌 projection만 config/deployment manifest에 담으며 비공개 환경 변수가 추가되어도 그
본문이나 hash가 proof로 이동하지 않는다. 이것은 종료 증명과 별개인 대상 binding이다.

PREPARE_TLS의 generic certificate adapter는 서로 다른 HTTP/transport CA와 해당 leaf를
만들고 issuer·key 일치·SAN·유효기간·용도를 검증한다. private key는 repr/오류/manifest/hash에
담지 않는다. CA signing key는 DPAPI store 안에만 두고 Docker에는 exact node key/cert/public
CA만 materialize한다. OS 전역 신뢰에는 등록하지 않는다. 합성 메모리 검증과 원래 환경의
프로젝트 key 생성·배포를 구분한다.

## 2026-10-08 역할별 key action group 보완

### 원래 Node 실행 별칭의 고정 파일 검증

현재 frontend의 `C:\nvm4w\nodejs`는 `v24.18.0`을 가리키는 NVM symbolic link이며 물리
Node의 등록 SHA·Authenticode가 원래 값과 일치한다. 사전검사의 일반 ancestor reparse
거부는 유지하되 이 exact alias만 별도 handle로 고정한다. alias directory는
OPEN_REPARSE_POINT·read sharing으로 열어 변경/삭제를 막고, 물리 디렉터리와 파일은 모두
일반 경로 검증으로 고정한다. alias를 통한 재열기와 물리 파일의 file identity·최종 경로를
대조한 뒤 서명과 기존 등록 해시를 검증한다. 다른 alias/target/version·추가 reparse·파일
교체는 거부한다. 이 예외는 frontend 유지 검사를 위한 파일 관찰이며 original 명령 제출,
과거 종료·daemon 정산·보안 전환 권한을 부여하지 않는다.

현재 ISSUE_ROLE_KEY 상위 단계는 유지하고 reader/writer/collector의 각 발급 및 필요한
폐기를 DB에 별도 선행 예약하는 append-only 하위 이력을 추가한다. 설치된 0062를 수정하지
않고 후속 migration으로 저장·guard를 확장한다. 한 event 뒤에 세 POST를 숨기거나 하나의
writer key를 모든 역할에 배포하는 것은 허용하지 않는다. 각 발급에는 새 issuance UUID와
exact epoch/role/name/permissions binding을 두고 I/O 전에 commit한다.

발급 ACK가 없으면 같은 issuance를 재POST하지 않는다. 정확한 server metadata lookup으로
생성 완료가 확인되고 secret이 없는 발급은 inaccessible로 정산한다. 그 exact key의 별도
폐기 예약·invalidated readback을 끝낸 뒤에만 새 UUID로 교체한다. lookup·발급·폐기 결과가
미확정이면 다른 발급도 멈춘다. 이미 secret을 정상 보관한 issued role은 교체하지 않는다.
상위 단계는 세 역할 모두 최신 issued·credential durable이고 하위 pending/unknown이 없을
때만 settled가 된다. 하위 이력에는 secret/Authorization/body/hash를 넣지 않는다.

역할 helper의 보호된 유한 catalog는 SQL child와 read-only lookup의 exact public submission
binding을 보관한다. 다음 mutation은 이전 helper journal의 실제 process_finished와 Job 종료
관찰이 모두 영속 확인된 경우에만 가능하다. key metadata GET이나 SQL issued 정산은
timeout·cancel·Job cleanup unknown을 종료 증거로 바꾸지 않는다. catalog/record가 없거나
intent/created/unknown이면 조회로 상태를 확인할 수 있지만 다음 mutation은 계속 차단한다.
정상 local 종료 후 credential 보관/SQL ACK가 유실된 경우의 조회 복구는 유지한다.

### 현재 원래 앱의 출처와 종료 대상

과거 PID가 남은 실행 registry를 현재 종료 권한으로 쓰지 않는다. 내부 observer가 고정된
동결 공개 실행 보고서의 승인된 SHA와 API/launcher 시작 초를 대조하고, 고정 HOST 관찰의
실제 포트·부모·원래 venv/module/argv 및 query-only kernel FILETIME을 전후 검증한다.
supervisor의 원래 workspace 소유 `-File` source는 환경 namespace 정리·고정 root/venv
uvicorn 실행·종료 코드 전달만 하는 닫힌 템플릿과 일치해야 한다. 일반 파일 삭제,
재시작 loop, 다른 모듈·포트·추가 명령은 거부한다. frontend는 보존하고 worker/beat는
실제 inventory에서 OFF인지 확인한다. 외부 PID 목록·source 경로·JSON 승인은 받지 않는다.

동일 owner/epoch/generation에서 observer가 발급한 exact 객체만 보호 source capsule로
기록·readback한 뒤 종료 allowlist를 발급한다. supervisor 종료 뒤에도 capsule의 원래
권한은 유지하되 개별 대상은 native가 같은 held handle의 PID/FILETIME/실행 파일로 검증한다.
종료 중 새 PID나 새 all-off 관찰로 기존 allowlist를 바꾸지 않는다. 이 출처 관찰은 과거
제어 이력의 미확정 상태나 최종 cutover·receipt 검사를 대신하지 않는다.
`..`·UNC/다른 drive·ADS·reparse source는 거부한다. 일반 source 파일은 bounded 반복 읽기와
동결 공개 SHA/닫힌 template로 검증하며 held-file lock을 증명하지 않는다. 기존 trusted
maintenance의 권한 있는 저장소·source 동시 편집 금지 조건을 유지한다. 현재 issuer의
fresh 발급과 같은 살아 있는 issuer의 capture 검증을 process-crash 복구와 구분한다.

### 기존 색인 형식과 비공개 보존 비교

원래 저장소의 보존 검사는 새 tracked mapping만 가정하지 않는다. 실제로 확인한
`rag`-only v1은 processing profile 없는 canonical profile/build 이름·mapping UUID/dimension·
기존 네 provenance keyword/integer 필드를 별도 `legacy_rag_v1` 계약으로 검증한다.
`rag_index_resource`의 명시적 부재일 때만 이 형식을 인정하며 null/불량 tracked 값을
legacy로 바꾸지 않는다. legacy에서 asset/workspace/resource provenance를 만들지 않는다.
RAG metadata 없는 자료는 이 예외에 포함하지 않으며 삭제·재색인·권한 확대하지 않는다.

전체 settings/defaults/mappings/aliases는 private canonical bytes로 전후 비교한다.
inline synonyms·임의 `_meta`·fingerprints·alias filters를 공개 hash preimage에 넣지 않는다.
공개 settings/provenance SHA는 버전이 지정된 닫힌 비밀 없는 projection만 표현하므로
공개 SHA 일치만으로 전체 보존을 인정하지 않는다. count는 해당 physical index의 선언된
logical shard 수와 두 응답의 전체 성공·문서/provenance 수를 각각 대조한다. decode된 DTO와
안정된 두 표본은 실제 source 권한이나 ES 원자적 snapshot·전체 완료를 증명하지 않는다.

### RAG 밖의 기존 색인과 기록된 관찰 출처

본래 16개 physical index 중 4개는 tracked, 7개는 legacy RAG 형식이며 5개는 RAG
metadata가 없는 기존 자료다. 마지막 5개를 RAG provenance로 재해석하거나 collector의
index 권한을 확대하지 않는다. 기존 cluster monitor로 cluster-state의 전체 index 이름·UUID·
settings/mappings/aliases와 routing, 단일 노드의 level=indices docs 통계를 함께 검사한다.
현재 본래 다섯 자료의 aliases는 모두 빈 list다. 빈 list는 alias 부재로만 인정하며 이름이
있는 list에서 filter/routing 정의를 만들지 않는다. 공개 cardinality에는 명시적으로
`lucene_live_docs` 종류를 붙여 RAG의 논리 문서 수와 혼동하지 않는다. 모든 primary의
STARTED·동일 원래 node·relocation 없음과 replica coverage를 검사하며 일부 shard 성공을
전체 보존으로 인정하지 않는다. 런타임 allocation/term/version은 immutable configuration
비교에서 제외하는 명시된 projection을 사용한다. 전체 settings/mappings/aliases의 private
bytes 비교와 UUID·동일 volume/image·실제 쓰기 종료 검증이 함께 필요하며 동일 count만으로
본문 불변을 주장하지 않는다.

현재 본래 다섯 자료의 자동 복제 설정 `0-1`은 별도 singleton 계약으로만 지원한다.
ALL-node 관찰의 total/successful=1·failed=0, 실제 effective replicas=0과 모든 선언된
shard의 primary-only STARTED 배치를 함께 요구한다. 노드 수 공식만으로 effective 수를
추정하지 않는다. 다른 활성 자동 복제 범위는 거부한다. issuer는 고정 all-node 통계와
master/node/ephemeral/JVM 구성의 관측 전후 결속을 별도로 검증해야 하며, pure decoder의
한 표본은 전 구간 단일 노드 또는 쓰기 종료를 보증하지 않는다.

native inventory의 출처 binding은 original의 STOP_OLD, bootstrap의 STOP_BOOTSTRAP,
final의 VERIFY_ACCESS exact pending/unknown parent로 제한한다. original은 동일 issuer의
과거 종료 prerequisite와 이전 앱 종료 관찰·정산이 필요하다. 보안 서버의 관찰은 동일
issuer가 발급한 실제 deployment, 완료 role-key ledger, 보호 credential와 실제 TLS 파일의
fresh 대조에서 collector credential만 얻는다. FinalAuthBinding을 bootstrap에 재사용하거나
관리자 credential로 부족한 index 권한을 우회하지 않는다. 단순 응답 DTO나 caller의
container/credential/완료 boolean은 이 binding을 발급할 수 없다. 이 binding 자체는 helper
실행·완전한 inventory·최종 proof·receipt를 완료하지 않는다.

원래 배포의 후속 조립에는 preflight가 실제 같은 관찰에서 계산한 daemon/volume/mount/
image/config/deployment의 닫힌 공개 packet과 원래 IPv4·bridge subnet/gateway가 필요하다.
후속 native factory가 이를 caller JSON이나 현재 다른 배포에서 재구성하지 않도록 exact
issuer 객체의 별도 observation으로 보유한다. topology는 고정 daemon/network ID의 실제
network inspect와 원래 container의 주소를 결속한다. 기존 identity-only 사전검사 계약을
유지하며 새 observation도 종료·변경 권한 또는 historical prerequisite가 아니다.
Config.Env/HostConfig 전체나 비밀 가능성이 있는 raw packet의 공개 hash는 추가하지 않는다.


## 2026-10-08 개인 첨부의 한 건 실행과 dispatch 정산

receipt·gate release·parity 뒤 기존 예약 한 건을 실행하기 위해 등록 서비스 `ingestion`을
writer 역할로 추가한다. 보호 birth capability에는 canonical job UUID 하나만 결속하며
고정 모듈의 `--job` grammar로 동일 원래 설정의 정상 ingestion workflow를 한 번 호출한다.
Celery eager 실행·전체 worker·별도 큐/DB/계정은 사용하지 않는다. runtime admission과
현재 PID/creation/epoch/role 대조를 완료하기 전에 job 또는 artifact에 접근하지 않는다.
일반 worker의 오류 분류를 공유하며 busy·writer-unconfirmed는 공유 작업을 실패로 만들지
않는다. retryable 결과는 자동 재실행 없이 실패/미확정으로 반환한다. 현재 job-wide owner lease가
없으므로 CLI의 상태/attempt 관찰만으로 workflow.fail을 호출하지 않는다. 정상 stage가
자체 정산한 상태 외에는 terminal 오류도 미정산으로 보존한다. 취소·자식 ACK·stdout의
성공 문구는 READY 또는 writer 종료 증거가 아니며 부모가 실제 자식 종료와 fresh 상태를
별도로 확인한다. 이 서비스의 추가는 실제 실행 승인이거나 현재 cutover 준비 완료가 아니다.

직접 workflow 실행이 기존 pending dispatch를 broker의 sent로 바꾸지는 않는다.
동일 job이 영속 succeeded이고 결속 projection이 READY인 경우에 한해 pending/unclaimed
전송 의무를 cancelled로 정산한다. 고정 사유는 `rag_ingestion_already_completed`이며
sent_at·claim_token·attempt_count를 위조하지 않는다. exact job/projection을 정상 잠금 순서로
확인하고 처리하며 claimed/sent·미완료·다른 job은 건드리지 않는다. ACK 유실은 fresh
readback으로 확인하고 입력 job을 다시 실행하지 않는다. 정상 batch dispatcher도 terminal
성공을 새 delivery로 내보내지 않으며, 잘못된 job/projection 상태는 조용히 완료로 인정하지
않는다. 성공 정산은 색인 provenance/원본·writer 종료 검증과 별개이며 다른 대기 예약을
소비하거나 정리하는 근거가 아니다.

## 2026-10-08 routing 응답의 typed 진단 확장

완전한 원래 routing 응답의 UNASSIGNED 비-primary copy에는 고정 recovery_source와
unassigned_info가 함께 올 수 있다. exact PEER recovery, UTC 시각·식별자·bool 타입을
검증해 private 비교에 포함한다. primary 배치·effective replica 수·전체 copy cardinality·
relocation 거부 기준은 유지하며 이 진단 필드를 primary 배치나 미확정 writer의 종료로
해석하지 않는다. 응답 decoder 통과와 실제 source binding·전후 보존 증거를 구분한다.


## 2026-10-08 실제 원래 namespace 권한의 발급 경계

전체 native 조립은 caller의 prefix/namespace tuple을 역할 key 발급 근거로 사용하지 않는다.
원래 설정·동일 원래 배포 observation에 결속된 한정 source producer가 complete cluster
metadata에서 canonical RAG 물리 이름과 profile/build/processing 관계를 검증하고, 같은
본래 DB의 실제 indexing/document_processing profile 종류와 대조해 존재하는 namespace만
산출한다. 원래 단일 JVM identity를 읽기 전후 대조하며 foreign/system/lookalike·알 수 없는
profile·불완전 목록·duplicate/임의 wildcard는 권한으로 편입하지 않는다. 임의 prefix 입력,
모든 profile의 Cartesian product, 관리자 fallback은 허용하지 않는다. 발급된 opaque object와
UUID/string scalar 서명을 보유하고 실제 issuer 확인 후에만 구조 Permissions를 내부 사용한다.
이 사전 읽기의 source capability는 이후 native 기록 inventory·쓰기 종료·최종 보존 증거를
대체하지 않으며 source pin은 실제 관찰 범위의 대조이지 디스크 전체 불변성 증명이 아니다.

## 2026-10-08 본래 scope 밖 색인의 보존과 과거 mixed poll

원래 설정의 prefix 밖 물리 색인이 RAG 형식의 metadata를 갖더라도 현재 namespace 권한으로
편입하지 않는다. 권한 producer는 설정된 prefix의 실제 namespace만 산출하고, scope 밖
색인의 metadata와 alias membership도 전체 목록의 전후 대조에 보존한다. scope 밖 색인이
현재 scope의 alias를 점유하면 거부한다. 원래 색인 삭제·이름 변경·writer 권한 확대는 이
호환성 처리에 포함되지 않는다. 후속 native 전체 보존은 scope 밖 원래 색인까지 별도 출처가
결속된 물리 inventory로 대조해야 하며, namespace 발급 성공만으로 이 보존을 주장하지 않는다.

과거 실제 numeric-array poll 뒤 `text((await tools.exec_command({...})).output)`가 붙은
닫힌 문법은 물리 Text emission 순서를 먼저 결속한다. 세 structured poll과 stdout-only
한 건을 구분하고, stdout-only는 JSON처럼 보여도 종료 메타데이터로 해석하지 않는다.
해당 shell의 명령은 discovery·omission 검사에 그대로 남기며 평가 대상으로 선택되면
종료 정보 부족으로 거부한다. 누락·추가·순서 변경된 emission, 임의 expression·추가 문장·
분기·식별자 변경은 거부한다. JS line comment는 LF/CR/LS/PS에서 종료하며 이후 호출을
숨기지 않는다. 한 chain의 파싱 성공은 전체 과거 control 수용이나 facts 발급이 아니다.

원래 canonical legacy 색인에서 indexing profile의 실제 DB 행이 없는 경우에는 별도
`OriginalUnmanagedPhysical` companion을 namespace와 원자적으로 발급할 수 있다. 두 번의
성공한 bounded SQL에서 같은 행의 부재를 확인하고 legacy processing profile은 정상이어야
한다. selected snapshot profile/target, tracked resource, wrong-kind 또는 processing profile
누락은 이 제외로 우회하지 않는다. 현재 허용 namespace/선택 alias와의 충돌도 거부한다.
companion은 exact 원래 name/UUID·명시적 사유·전체 private metadata·snapshot/deployment와
namespace nonce에 결속한다. source 밖 tuple·복사·변조는 권한이나 완료 근거가 아니다.

이는 원래 자료 보존을 위한 관리 범위 구분이다. orphan DB 행 생성·원본 삭제·권한 확대는
실행하지 않으며 해당 색인은 역할 key의 namespace에 포함하지 않는다. native collector는
동일 source의 companion을 complete 실제 physical map과 다시 결속하고 global metadata/
routing·node stats만으로 별도 `unmanaged_legacy_rag_v1` 보존을 확인한다. per-index 검색/
provenance count나 문서 본문 일치·DB 소유권을 주장하지 않는다. 원래 모든 물리 색인을
포함하는 O→B→F 보존과 exact security 생성 출처가 별도로 완성되기 전에는 전환을 허용하지
않는다. 확인된 8 managed/3 unmanaged/5 foreign 건수는 현재 관찰 결과이며 승인 상수가 아니다.

## 2026-10-08 일곱 route의 실제 발급 경계

`NativeRouteCommands`와 `RecordedNativeRoutes`는 같은 실제 native context의 final deployment,
인증/key ledger, TLS, 앱 종료 및 보호 journal에서만 고정 명령·route capability를 발급한다.
host의 공식 Python과 guest의 기존 image bundled JDK를 사용하고 별도 설치·이미지·인증서/
trust store를 만들지 않는다. endpoint/argv/credential/Java source·route 목록을 caller가
제공하지 않는다. source-launch private stdin은 고정 Java template와 RAM payload 하나이며
secret-bearing source/출력의 공개 hash는 만들지 않는다.

transport는 TLS1.2의 exact project CA/leaf·client cert handshake와 같은 endpoint에서
client cert 없는 요청의 검증된 peer fatal alert를 짝지어 required 설정과 결속한다. timeout,
EOF·임의 handshake failure는 enforcement 증거가 아니다. host/guest HTTP의 project-only
TLS와 현재 collector 인증, anonymous exact401, complete NodesInfo와 daemon/network/config
전후 관찰이 필요하다. remote server/client와 추가 profile/listener는 닫힌 실제 관찰로 제외한다.
relay 제외는 실제 앱 종료·배포 ingress의 승인된 유지보수 신뢰 경계까지만 주장한다.

이 capability는 exact pending/unknown VERIFY_ACCESS parent에 결속하며 고정 finite helper
catalog·보호 capture·실제 issued child/local-finish를 모두 검사한다. ACK 손실·취소·Job0·
missing capture로 새 helper를 재발행하거나 guest 종료·route 완료를 주장하지 않는다.
support 검사에는 준비 전 static/source 조건만 사용하고 final runtime cap는 명령/관찰 시점에
검증한다. factory는 support를 epoch DB 생성 전에 확인한다. 미구현 relay/security transition/
최종 verifier는 unsupported로 유지하며 부분 route 성공을 proof/receipt로 승격하지 않는다.

## 2026-10-08 닫힌 두 poll 및 structured tail

같은 승인 source 안의 정확한 두 literal session poll 뒤 `text(await tools.exec_command({cmd:<literal>,max_output_tokens:<literal>}));` 형식도 순서가 결속된 structured emission으로 읽는다. 기존 세 poll/stdout projection과 혼합하지 않으며 두 문법 각각의 exact wrapper·개수·닫힌 literal 필드를 검사한다. 원래 모든 Text element 타입과 값을 선검증한 후 정확한 슬롯을 유지한다. structured tail은 별도 exec session/terminal 결과이고 poll session으로 간주하지 않는다. 추가 문장·알 수 없는 출력·누락/추가/복사·잘못된 session 결속은 거부하며 discovery/omission은 tail을 유지한다. generic 결과 decoder·recipe admission·control target 판정 범위는 확대하지 않는다.

## 2026-10-08 아직 물리 색인이 없는 예약 namespace

현재 예약 snapshot의 indexing/processing pair는 아직 물리 색인이 없을 수 있다. 원래 physical namespace의 관찰 집합과 별도로 exact snapshot pair의 두 프로파일 종류를 같은 두 bounded SQL에서 확인하고 canonical alias와 결속하여 권한 집합에 포함한다. 프로파일 전체 곱이나 caller pair는 수용하지 않는다. selected profile 부재·wrong-kind·두 조회 불일치·alias 충돌은 거부한다. 물리 원본·unmanaged 분류와 전체 보존 집합은 그대로이며 snapshot의 빈 target이 새 색인 전 상태일 수 있다는 것만 반영한다.

## 2026-10-08 공개 software pin의 실제 descriptor source

보안 main descriptor는 본래 image의 고정5개 공개 class를 bundled javap로 읽어 출처를 발급한다. 임의 bytecode evaluator 대신 검토한 exact javap packet의 전체 UTF8 software fingerprint를 내장하여 비교한다(CRLF→LF만 정규화). unknown build/변경된 packet은 unsupported이고 caller hash·문자열 부분 일치로 수용하지 않는다. 실제 source-issued 원래 deployment/image/manifest와 전후 identity·완료된 owned read-only child를 결속한다. public software hash는 private 검증용이며 cutover manifest에 출력하지 않는다.

확인된 main은 `.security-7` / `.security`, index.format6, `_meta.security-version` 문자열8.14.0, `_meta.managed_index_mappings_version` 정수5다. core descriptor가 index.hidden을 true로 기본 적용하고 false이면 거부하는 공개 구현도 확인했다. runtime의 system boolean·hidden/open·alias/UUID 및 생성·전체 원본 보존 출처는 별도 실제 collector/transition에서 검증한다. descriptor source 하나의 성공을 security 생성·최종 proof로 보고하지 않는다.

## 2026-10-08 unmanaged legacy의 순수 물리 보존 decoder

`access_epoch_unmanaged_inventory.py`는 namespace companion의 typed entry와 실제 complete state/routing/node-stats packet을 구조적으로 교차 확인하는 순수 decoder다. 전체 물리 name/UUID 집합을 유지하고 해당 exact legacy name/profile/build/reason·private metadata 및 live-doc cardinality를 보존한다. 별도 per-index count/provenance API·DB 조회·권한을 만들지 않는다. 순수 결과 자체는 출처 권한이 아니며 native collector가 exact source companion과 capture lineage를 결속해야 한다. 원래 entry 보존 비교와 전체 O/B/F map 전이 비교를 구분하고 추가 security row 허용은 실제 transition issuer에만 둔다.

## 2026-10-08 unrelated literal poll의 한정 제외

현재 찾는 session이 포함되지 않은 정확한 `const result = await Promise.allSettled([3개 literal].map(session_id => tools.write_stdin({session_id,chars:"",yield_time_ms:<int>,max_output_tokens:<int>}))); result.forEach(text);` 문법은 그 session의 continuation 후보에서 제외한다. 전체 source 문법·닫힌 tool·literal 배열·binding·필드·단일 출력만 검증한 후 제외하며 unknown expression은 그대로 거부한다. 관련 session이 포함되면 이 제외를 적용하지 않고 기존 unsupported 종료 경계를 유지한다. Promise 결과를 종료 사실로 해석하거나 새 recipe/source/control 범위를 승인하지 않는다.

## 2026-10-08 main security 순수 decoder

`access_epoch_security_inventory.py`는 승인된 실제 descriptor의 닫힌 software 계약과 complete state/routing/node-stats 구조를 대조하는 순수 decoder다. exact .security-7 하나의 true system·hidden/open·alias·format·mapping marker·singleton routing/cardinality를 검사하고 전체 physical map/private metadata를 유지한다. restricted index API·권한을 추가하지 않는다. DTO를 생성할 수 있다는 것은 출처 권한이 아니며 실제 transition issuer가 descriptor source와 native capture/creation을 다시 검증해야 한다. 추가 system row·토큰/profile name·알 수 없는 버전은 허용하지 않는다.

## 2026-10-08 실제 physical capture와 category 완료 분리

원래 physical collector는 namespace source/companion과 실제 captured 전체 sample을 같은 snapshot/원래 deployment/permissions에 결속한다. 완전한 global metadata/routing/stats·세 listing·두 pass와 managed per-index capture를 `CapturedPhysicalInventory`로 발급한 후 category 완료를 별도로 수행한다. 미관리3개는 exact companion set만 global 경로로 대조하며 per-index 호출하지 않는다. 원래 완료는 system row 부재와 managed/unmanaged/foreign의 exhaustive 전체 map을 검사한다. 보안 완료는 실제 별도 transition issuer가 준비되어야 하며 일반 collect/fake callback으로 수용하지 않는다.

System boolean은 complete cluster-state projection에서 필수로 읽고 검증한다. 기존 pure listing DTO의 필드는 유지하며 global state와의 complete UUID/state/hidden 교차 검증을 사용한다. 기존 pure foreign 계약의4field 형식은 보존하되5field system 형식을 읽을 때 strictbool/selected non-system 조건을 추가하고 private packet 전체를 유지한다. generic whole-physical foreign equality와 O16→B17 직접 거부는 유지한다. 새 actual physical/source completion은 strict5field와 exact issuer가 필수여서 legacy pure 호환을 보안 관찰 fallback으로 사용하지 않는다.

### Complete physical-map main security transition comparison

The pure transition comparator enforces B = O union the exact decoded main security row and optional F = B using complete private metadata maps. Every original physical row remains byte-canonically equal; no category is dropped and the generic foreign full-map comparison is not relaxed. It verifies the main decoded DTO is consistent with its complete map, private row and strict live cardinality, while actual descriptor/capture/creation/quiescence source authority and per-category counts remain required in the composing native issuer. Pure success emits no capability or permission.

### Closed stored-result unrelated continuation

Approve the narrow same-sealed-source exclusion in history-next-poll-shape-03-plan.md: the exact preceding exec producer stores and emits its same result binding under the literal key loaded by the exact next dynamic poll. A single actual physically validated yielded result and a strict different session establish only nonmembership in the sought continuation. Any intervening exec, ambiguous key/binding/output, equal session or unknown grammar remains unsupported. No stored-value interpreter, receipt/result slot, terminal fact, source admission or omission-coverage change is introduced.

### Native preepoch source assembly

The exact context now owns a one-shot asynchronous read-only preparation of the pinned original security descriptor and bundled JDK route support before any epoch/native cutover acquisition. Both actual source objects and the same route commands support receipt remain retained and immutable; no caller approval boolean or source setter exists. Missing/failed preparation or missing mandatory final verifier denies cutover support before reservation. This preflight does not grant security creation or retire a server.

### Managed global/per-index metadata join

Native physical capture must join each managed per-index packet to its corresponding complete global metadata row in both passes: exact full settings, canonical mapping after the known sole _doc wrapper, and exact alias names. If the global wire supplies a dictionary of alias options, compare those options privately as well; a name-only list cannot prove options. Per-index defaults are retained privately but are not invented as global fields. Matching UUID alone is insufficient. This prevents an inconsistent two-source snapshot from being promoted as completed original inventory.

### Stored-result exclusion output and prefix uniqueness

The source-only stored-result nonmembership predicate admits only the closed typed yielded exec result envelope: output string, positive integer session, absent/null exit code and optional typed chunk/wall-time/token-count metadata. Unknown/error fields, nonfinite or boolean metadata values deny. Every prior outer call has exactly its own ordered output through the current poll boundary, including the producer-to-poll interval; a later contradictory or duplicate response cannot be ignored by slicing only before the producer. Actual formatted outer header/cell lifecycle support remains separately unimplemented.

### Closed outer-cell lifetime and non-store-writer exception

Approve the exact same-sealed-source outer protocol in history-next-poll-shape-05-plan.md: whole completed/failed/running headers with finite wall-time, whole raw header-only running strings, all physically validated Text content and the narrow validated input_image envelope. Uniquely bind ordered exec and literal wait responses; unknown/duplicate/late-contradictory/missing/overlapping/cross-source/colliding generation state denies. A failed isolate ends only its JavaScript lifetime, not a native helper. Cell IDs may be reused only after prior generation closure and a new actual exec-open event.

Two original generations lack closure at the producer cutoff. Their complete admitted script grammar consists exclusively of one or three text(await tools.exec_command({...})); statements. Request fields cmd/max_output_tokens are mandatory literals; optional workdir/justification are strings, yield_time_ms is a positive integer when present, and sandbox_permissions is the closed use_default/require_escalated mode. This is the exact observed six-key request grammar; no other option is admitted. Full token recognition, with no variables, unknown calls, dynamic fields/eval or further statements, proves these particular active isolates cannot write the stored JavaScript key. Allow only this narrow non-store-writer exception to the prior-writer absence check, never generic absence of the word store, and never infer their native command termination. All other active/unknown generations continue to deny. Recipe, source admission, selected terminal decoding and omission coverage remain unchanged.

### Native security inventory completion issuer

Approve NativeSecurityInventory(context).observe(parent, actual_collector, source_issued_physical) -> MainSecurityCompletion and assert_issued. The exact context owns original descriptor/JDK/namespace/absence/history/apps, actual recorded original inventory, settled bootstrap admin/audits/three-role key/TLS/deployment sources, and for final the settled bootstrap retirement plus actual current final authentication. Two complete native-captured private packet samples must satisfy the pure whole-map O→B→F equation and unchanged full managed/unmanaged/ordinary foreign category tuples/counts. Derive actual deployment preservation from these same packets before completion to avoid a circular current inventory getter. No helper reads or credential creation are added by completion. Original collector origin is checked against its settled historical row without re-running its now-inactive parent guard.

The collector remains the completed-inventory issuer: a subsequent complete_secure accepts only the exact actual native issuer/capability association with fresh reader/owner/DB/material checks, retaining that association transitively. A structural decoded DTO, reduced foreign object, callback, public bool or future getter placeholder cannot certify completion. Final publication failure/cancellation poisons its attempt. Native source/test pair implementation is assigned separately; root retains collector/context/port integration responsibility, and no live cutover is authorized by this class contract.

### 유한 mixed allSettled script의 continuation 후보 제외

동일 sealed source/selector의 다음99-token script는 literal write_stdin1개와 literal exec_command2개를 Promise.allSettled3배열에서 호출하고, zero-based index loop로 세 결과를 내보낸다. `.local-data/project-agent-work/rag-control-native-20261008/07-plan.md`의 전체 닫힌 token grammar만 승인한다. sole literal poll session이 sought와 다른 경우에만 continuation 후보 제외를 허용한다. 별도 결과 decoder나 slot, outer/helper 종료 사실, source admission, omission 면제를 만들지 않는다. 두 exec shell의 제어 의무는 기존 omission 검사에 남고, 같은 session 또는 unknown grammar는 거부한다. 출력이 없거나 위조돼도 이 predicate로 terminal을 공급할 수 없다. 후속 실제 결과와 전체 역사 coverage 완료는 별도 검증한다.

### apply_patch를 포함한 유한 continuation 후보의 판정 범위

동일 source/selector의 다음95-token script는 text(await tools.apply_patch(literal)) 뒤 fixed2 allSettled[exec,poll]와 coherent zero-index loop다. 공개 도구 계약의 apply_patch는 파일 편집이며 이 판정에서는 성공·안전성·제어 종료·전역 coverage를 판단하지 않는다. 기존 유한 계약은 identified original control invocation과 그 consumed support를 검증하므로, 정확히 다른 sole literal session을 poll하는 후보 제외를 위한 source nonmembership은 허용한다. 이것은 patch를 non_control/settled로 분류하거나 파일 변경의 후속 실행을 면제하는 근거가 아니다.

허용 구현은 이 whole95-token 닫힌 형태만 별도 predicate로 처리한다. contained exec의 기존 omission 의무, _patches discovery, 선택 helper의 실제 patch/output 출처 재구성, explicit _recorded_stage 검증과 historical_source_writes pin을 그대로 유지한다. selected mixed exec/patch/stage의 unsupported 결과는 계속 거부한다. patch가 synthetic sensitive target을 수정한 경우도 이 predicate로 성공·terminal/support 사실을 발급하지 않는다. equal/unknown session/callee·추가문장/동적 인자/다른 order/count는 거부한다. 전역 patch completeness나 harmlessness는 주장하지 않으며 facts/source admission/recipe 변경은 별도 검증 전0을 유지한다.

### 역사 coverage의 source 충돌 차단

독립 합성 재현에서 다른 source의 같은 call_id/shell_index를 이미 확인한 호출로 오인하여 미선택 application 제어가 통과했다. selected 및 omission coverage는 source/call/index 출처까지 결속해야 한다. 같은 source의 byte-identical fork call/output 중복은 기존 닫힌 dedup 계약을 유지한다. 서로 다른 source를 동등한 fork로 볼 경우에는 실제 전체 호출/결과와 정확한 출처의 동등성 검증이 별도로 필요하며 call_id만으로 cover하지 않는다. 다른 명령/결과·미선택 실제 제어·모호한 support binding은 거부하고 새로운 fact/recipe 변경 전 독립 재현을 통과해야 한다.


### Native final verifier support before reservation

The fixed final verifier must implement a synchronous zero-I/O assert_supported() returning exactly None. The actual control port calls it before publishing the retained verifier, rechecks source/context identity after publication, and calls it again on retained support checks. Class provenance and callable verify/assert_issued alone are insufficient to enable reservation. Any support or publication failure clears the candidate from both port and context and permanently poisons this port attempt; cancellation remains the primary exception. This contract does not publish a partial final verifier or authorize live cutover. The fixed final module stays absent until its complete actual-source lifecycle is tested.


### Closed unpatched poll/exec unrelated continuation

Approve the exact retained80-token source-only shape in H/09-diagnostic-proposal.md: Promise.allSettled has exactly literal empty write_stdin(session/yield/max) followed by literal exec_command(cmd/max), with the fixed zero-index ordered text loop and whole-token/binding validation. Permit exclusion only when the sole strict positive literal poll session differs from the sought strict positive session. Dispatch the three existing finite variants with a closed internal enum, never independent optional grammar flags. Contained shell discovery/omission coverage, cross-source identity checks and selected terminal/result-slot decoding remain unchanged. Forged/duplicate mixed outputs, equal/unknown session, selected mixed exec, arbitrary options/order/prefix/suffix and new patches remain unsupported; this predicate issues no terminal or support facts. Recipe, source admission and facts stay unchanged pending the separate complete historical judgment.


### Closed two-poll unrelated continuation

Approve the exact retained88-token two-poll source grammar in H/10-diagnostic-proposal.md after RAM confirms whole script, coherent zero-index loop and both distinct strict positive literal sessions differing from sought. A fourth closed internal poll_poll branch may consume exactly two fixed emptychars/session/yield/max polls; no optional count/order/callback/member/suffix grammar is admitted. This is only source nonmembership. It never infers poll/cell/native termination or emits receipt/result-slot/support authority. Equal/duplicate/dynamic session and altered loop/options/body refuse. Shell/patch discovery, all-source omission and source collision checks, physical result decoding, recipe and source admission remain unchanged. Implementation must retain all423 regressions and independent finite mutation/forged-output/omitted-control checks.


### Original configuration repeated parsing

Actual same-epoch source composition profiling found thousands of fresh Settings constructions, with .env/environment parsing dominating synchronous provenance validation. Cache only the validated configuration projection for exact private inputs: fixed path, freshly read identical bounded .env bytes, full current process environment snapshot and exact Settings loader identity. Every guard still checks source/capability identities, current Settings projection, endpoint and file kind, and freshly compares bytes/environment. Changed inputs always reparse; compare file/environment before and after parsing and refuse races. Failed parses do not update the cache. This is a private per-instance optimization, not a stale environment/configuration approval, no cap/assert/global memoization, no I/O removal and no persistence of private bytes or environment values.

Independent negative review reproduced private cache-slot substitution accepting unparsed changed inputs. Before reuse require an exact frozen eq=False validation token issued into this same source instance private registry, with strict primitive nonce/input/configuration signature. A raw input tuple, cloned token, mutated nested fields or another source token denies. Refresh clears the previous token registry and publishes only after matching parsed configuration and before/after source inputs. Keep the token and private input bytes/environment out of public DTOs, logs and persistent artifacts.

A second independent state-transfer probe requires explicit issuer identity in the frozen cache token and primitive signature: transferring both a foreign token and its registry still denies at current source identity. Registry membership alone is insufficient per-instance provenance.


### 2026-10-09: same sealed source finite batch continuation exclusion

같은 sealed source의 남은20호출을 RAM에서 전수 확인한15개 전체 문법만 source-only continuation 제외 대상으로 승인한다. P는 고정 빈chars poll(session/yield/max), Q는 session/chars/max/yield 순서 poll, E는 cmd/max exec, Y는 cmd/yield/max exec, F는 cmd/workdir/require_escalated/login:false/max exec, G는 F 뒤 yield, C는 clock__curr_time({}), A는 literal apply_patch다. N은 exact allSettled array→zero indexedloop→nested static result emission, S는 같은 loop의 exact bound result spread, T는 text(await atom) 전체 statement다.

승인된 whole-script forms는 N[P,P,P,E], T(E)+N[P,P,P], N[P,P,P], N[P,P,E], N[P,P,C], S[P,P], S[P,E], N[E,E,P], N[E,P], N[C,E,P], S[E,Q], N[Y,E]+T(P), exact two distinct literal for-of polls+T(Y), T(A)+T(F)+S[P,P], S[G,P]의15개로 닫힌다. 기존4문법은 유지한다. 내부 불변 descriptor만 사용하고 개수/순서/옵션/앞뒤 statement/spread를 독립적인 선택 사항으로 확장하지 않는다. 모든 literalpoll은 positive<2**31·상호distinct이며 실제 sought와 달라야 한다. 1MiB·safe coherent bindings·quoted/unquoted literalkeys·fixed semicolons·전체 consumption 검사는 유지한다.

이 승인은 해당 different-session poll을 현재 result chain에서 제외할 뿐이다. clock timestamp, spread resultfields, contained shell/patch/output은 해석하거나 실행하지 않는다. 기존 resultdecoder/terminal linkage/recipe/sourceadmission/prefix/cross-source conflict/omission/helper reconstruction/stage 판단은 변경하지 않는다. Group14의 미선택 potentialcontrol과 patch는 여전히 미판정이고 최종 omission 거부 의무가 남는다. Group15의 이미 선택된 호출은 자기 result/terminal 증거를 별도로 충족해야 한다. facts/recipe/admission0을 유지하며 실제 역사 종료를 주장하지 않는다. 15positive와 모든 poll membership/duplicate/동적/타입 오류, 비표 문법/extra statement/옵션·spread·clock 변경, terminal/omission integration 음성 회귀와 독립 검토를 구현 조건으로 둔다.


### 2026-10-09: synchronous security graph getter reuse

실제 클래스 합성 route 검증은 fake transport에서도 두 helper에360초가 걸렸고, 단일 profiled _runtime의 실제 출처 검사 DAG는2F+10B security traversals/1609 assert_sources를 수행했다. 일반 요청 시간으로 해석하지 않으며 profiler overhead를 포함한다. 같은 출처의 반복 조회만 줄이기 위해 NativeSecurityInventory._objects 안의 public getter를 각각 한 번 검증해 local에 보관한다. 동기 함수 안의 재사용만 허용하며 await 간·호출 간 cache나 검증된 bool flag는 만들지 않는다.

기존 explicit actual issuer assertions와 static/owned/source guards 및 source_origin.objects의 정확한 순서는 유지한다. 기존 getter가 수행하던 actual issuer validation도 생략하지 않는다. 반환 직전 raw context/collector/cap identity 및 각 mutable factory/admin/audit/auth/key/bootstrap 연결이 검증한 local과 같은지 확인한다. 복제 cap·issuer·nested source 교체나 파일/환경/credential drift를 승인으로 취급하지 않는다. _origin_seal과 closed _inventory_seal의 실제 발급 검사, complete_secure의 await 전후 검사는 이 변경에 포함하지 않는다. 실제 B/F 그래프에서 delegated getter 횟수와 late substitution 음성 회귀, 변경 없는 독립 재현 및 타입/린트 검증을 먼저 실행한다. 12→8 traversal은 구조상 예측일 뿐 성능 완료나27route 통과 주장으로 사용하지 않는다. 실제 전환/서버/계정/자료/권한 변경은 이 최적화 범위 밖이다.


### 2026-10-09: exact selected historical result-slot settlement

동일 sealed source의 실제 target shell0은 exact int exit0이고, 같은2-shell batch의 shell1만 종료가 확인되지 않음을 RAM13/14에서 확인했다. 외부 cell은 matching3wait로 완료됐고2결과의 전체 cardinality가 일치했다. 전체 batch의 모든 결과에 terminal을 먼저 요구하는 현재 _chain 때문에 대상 slot의 결과도 판단할 수 없었다. 이는 대상 애플리케이션의 자식 수락이나 전체 history 완료 증거가 아니며 실제 recipe 선택은 변경하지 않는다.

private _chain에 keyword-only required_shell_indices: tuple[int,...]|None을 추가한다. None은 기존 모든 슬롯 종료 검사를 유지한다. 명시 범위는 nonempty·중복 없는 exact int·전체 source/result 범위의 tuple만 허용하고 bool/subclass/음수/범위 초과/임의 iterable을 거부한다. 전체 producer identity, 지원되는 출력 문법/ordinal binding, physical result deduplication/cardinality, outer cell의 정확한 완료는 선택 범위와 무관하게 먼저 검증한다. 새 mixed result decoder를 만들거나 finite15 source-only 제외를 selected 결과 문법으로 승격하지 않는다. 기존 구조상 ordinal 결속을 증명할 수 없으면 여전히 거부한다.

반환값은 원래 순서의 전체 결과 vector를 유지한다. required yielded slot만 기존 exactsession/poll/unique terminal 계약으로 완료 결과를 연결한다. 비대상 yielded 결과는 그대로 남기며 exit/settled/noncontrol/receipt를 합성하지 않는다. read_original은 기존 recipe.shell_indices를 전체 source 범위에서 먼저 검증하고 immutable tuple로 전달한 뒤 기존 selected exact-int/category/support 판단을 유지한다. support/inspection callers의 defaultall은 변경하지 않는다.

누락 검사·cross-source conflict·source prefix/recipe admission·helper/source reconstruction·당시 refusal-stage 의무는 전체 source/allslots에 계속 적용한다. 비대상 knowncontrol의 누락이나 unknown potentialcontrol은 facts 발급을 거부한다. mixed selected shell 안의 미해석된 원래 대상 호출을 이 선택 범위로 숨길 수 없다. 실제74target 의무·3pytest purpose·기존43call catalog·recipe 재발급은 이 변경 범위 밖이다. synthetic selected0/1/multiple/default, invalid tuples, 전체 missing/extra/contradictory producer/output/cell, required forged/missing/invalid terminal, unsupportedmixed protocol, 비대상 control omission 및 기존sourcecollision 음성 회귀와 독립 검토를 완료하기 전 실제 facts를 발급하지 않는다.


### Secured read capture create-once boundary (2026-10-09)

The remaining native final-access package needs fresh post-settlement and post-receipt reads without a live mutation mutex or fabricated launch authority. The reviewed lifecycle design is retained in the current task handoff. Its first independent implementation boundary is a narrow method on the existing NativeWindowsPrivateState, with no change to existing credential, floor, launch, or generic write APIs.

Create/read capture selectors are exact nonzero UUID nonce, exact integer slot 0 through 4, and a closed phase set: intent, child, resume_intent, terminal, capture, cleanup. The adapter derives only private/read-checks/<nonce>/<slot>-<phase>.dpapi; callers cannot provide a path or generic command. Plain bytes are bounded and DPAPI-protected before persistence. Creation uses an exclusive protected temporary file, complete write/flush/fsync, regular-file/reparse/owner/DACL checks, and Windows atomic rename without replacement. Existing equal or different destination records deny creation; no retry, overwrite, credential mutation, key issuance or implicit recovery. Fresh readback decrypts only the exact fixed capture path after the same protection checks and validates byte bounds.

An uncertain create/readback/cleanup ACK remains denied. Temporary cleanup attempts preserve the primary BaseException and never delete the published capture or an unrelated file. This primitive only persists private observations; it does not issue a secured-read capability, prove child cleanup, activate support, or authorize an original cutover. Production source/factory integration and cancellation cleanup-barrier verification remain separately required. External-fake unit tests and independent review are required before integration; no original private capture, server, key, floor or gate write is authorized by this implementation step.


### Secured fixed-read child cleanup barrier (2026-10-09)

The secured phase reader will await one fixed Docker observation slot at a time, freshly guarding SQL, floor, credentials and local material before and after each await. Its private Labs worker derives only five fixed read commands and persists create-once intent/child/resume/terminal/cleanup/capture records through the native adapter. Each child uses one dedicated thread for the actual WindowsControlProcess lifecycle; no mutation owner, pending SQL or fabricated launch capability is supplied. Fixed2MiB output and10s native wait cannot be relaxed by callers.

Cancellation requests no further work, retains the original BaseException and awaits the shielded same-thread cleanup barrier despite repeated cancellation. Successful output is admitted only after terminal Job-empty and successful owned close. Timeout, active descendants, uncertain phase/close ACK or hanging native calls never imply verified cleanup; cross-thread close and unrelated process termination are forbidden. The helper grants no phase or operational authority and remains disconnected from live cutover until complete actual-source integration and independent verification.


Fixed read inputs retain immutable nonce and root primitive values across every external callback; mutable UUID objects are not attempt-registry keys. Private atomic-move flags follow [Microsoft MoveFileExW documentation](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw): WRITE_THROUGH only, without replacement, copy or restart scheduling. This API check does not substitute for actual syscall/crash-durability verification.


### Fixed original secured-read dependency assembly (2026-10-09)

The committed-read component verifies persisted consistency but does not establish the origin of an arbitrary repository, session maker or private-state port. Its next dependency adapter must construct its own original Settings, SQLAlchemy engine/session/repository and actual native private-state graph from the existing fixed root. The concrete implementation contract is `.local-data/project-agent-work/rag-control-native-20261008/secured-read-native-dependency-binding-plan.md`; caller roots, DSNs, adopted repositories, custom creators and approval booleans are not accepted. An opaque, retained association establishes only dependency provenance, never server observation, epoch verification, receipt or cutover support.

Retain exact constructor-issued objects and typed private seals for maker options, engine/URL/dialect/pool/creator arguments and native DLL/owner/root associations. Default SQLAlchemy first-connect listener lifecycle and learned connection state must be explicitly distinguished from replacement or added redirecting listeners; no successful assembly is published when the installed default behavior is unresolved. Keep URL credentials, original configuration and native private values out of public manifests, exceptions, logs and repr. Construction creates no database/account and opens no SQL connection; original configuration/SID reads are separately real I/O and must not be described as memory-only.

The implementation is limited initially to the new assembly source/test pair, offline actual SQLAlchemy plus actual NativeWindowsPrivateState over low external transport fixtures. No original native construction, SQL query, private directory/ACL/key/anchor/capture write or factory activation is authorized by those tests. Controller factory and committed source integration require separate independent review of the full graph. Production support remains unavailable until actual source assembly, live observations and the completed pending/all-settled/verified/receipted lifecycle are verified. Original cutover and historical recipe provisioning remain separate concrete operational gates.


### Pure historical recipe purpose validation (2026-10-09)

Approve only the first structural slice in `.local-data/project-agent-work/rag-control-native-20261008/history-recipe2-pure-validator-plan.md`: a separate pure source/test pair validates a supplied predecessor, candidate and ordinary reference. Preserve ordered43call/64shell inventory and source/support descriptors; require exactly three reference selectors to carry recorded_unadjudicated/historical_test_source_unqualified and every other selector adjudicate/null. Strict closed JSON, duplicate-key rejection, typed bounds, ordered bijection, canonical predecessor digest and revision increment are mandatory. These ordinary values authenticate neither the supplied reference nor the actual historical test triple. They cannot issue coverage, settlement, facts, omissions or activation.

Existing schema1 reader, public seven-key manifest and protected recipe bytes remain unchanged. Reader integration requires actual source-bound triple/invocation validation and complete original-target omission checks. Provisioning further requires reviewed protected versioned CAS, exact installed predecessor and independent historical rederivation; structural validator success is never CAS success. No fourth exemption, purpose inheritance, current-helper fallback or whole74-safe label is introduced.


### Active and committed native read lifecycle (2026-10-09)

The existing committed persisted-read binder cannot be invoked before mark_verified: repository.verified and store.load are not yet available. Allsettled maintenance reads instead require the exact real held context, prepared credentials and settled12 records. Preepoch zero-I/O support cannot demand runtime bind_context before owner/store/keys exist; it validates only the retained fixed complete implementation/dependency association. Neither boundary can manufacture a verified phase.

Committed startup and revalidation use a separately source-issued construction path without old original preflight/context/mutex/pending cap. Do not fabricate a launch or use registered OriginalRuntimeAdmission._probe as maintenance authority. Fresh live observations remain separate mandatory producers. DB previous_floor stays the durable predecessor; a matching candidate DPAPI anchor after lost write ACK is exact idempotent recovery, never a new predecessor or ordinal. Unknown, changed or foreign anchor denies. These requirements clarify the existing backend contract, not operational support or live-cutover authorization.

### Native private constructor origin before first binding (2026-10-09)

First binding cannot certify the current nested DLL graph when it was not retained at construction. NativeWindowsPrivateState records a source-owned, exact-instance memory snapshot only at successful constructor completion, with typed primitive root/owner and strong DLL/function/prototype references. Its weak registry must not retain the owner through values or bound methods. Copied objects, failed/repeated initialization, replacement or mutated native functions/prototypes deny; memory assertions never auto-enroll missing objects. Platform keeps this guard independent of Labs and existing native file/DPAPI/ACL I/O remains unchanged.

The secured-read assembly checks the exact class memory assertion before accepting its nested private-state seal. Construction provenance alone proves neither current Windows module integrity nor server/epoch/receipt readiness. Full held-context/factory/DAG and actual operational integration remain mandatory separate boundaries. Scope and seven independent RED cases are recorded in .local-data/project-agent-work/rag-control-native-20261008/native-private-construction-origin-plan.md.
### Phase-neutral TLS packet decoder (2026-10-09)

The new access_epoch_tls_packets component consumes only ordinary packet bytes and exact typed epoch/action/address data. It preserves the existing schema1 binding and two-layer/four-field wire layout, canonical UTF8 JSON/base64, closed journal expected identity, 131072-byte packet and 16384-byte decoded-field limits. Duplicate/nonfinite/coerced values, copied altered primitive types and extra timestamp/schema fields deny. Successful decoding returns ordinary ProjectTlsBundle data; it grants no authority and validates no certificate/key chain by itself.

The pure component performs no file, SQL, native, owner, DPAPI, generation or issuer calls. Existing active TLS guards remain intact, and committed reading still requires actual source-owned persisted/material checks and ProjectTlsBundles validation. Full final source/backend/factory and operational support remain unavailable. The fixed H prototype passed65 author plus6 independent boundary tests; product integration requires its own imports/types/independent checks before use.


### Distinct committed SELECT-only snapshot and protected handle read (2026-10-09)

Existing active acquire/readback/key mutation guards retain their gate upsert and row locks. Committed observations instead use a separate ordinary composite snapshot built from one actual source-owned AsyncSession transaction: REPEATABLE READ, READ ONLY before SELECTs, no_autoflush, no FOR UPDATE or DML. Existing owner/claim/canonical operation/snapshot/gate/receipt/epoch/execution/twelve-event/proof/floor/completed-key semantics remain mandatory; absent rows deny rather than initialize. Snapshot DTOs grant no issuer or source authority. The secured source must separately bind the actual fixed assembly and recheck retained dependencies around SQL awaits; fresh samples bracket external reads rather than claim unseen interval invariance.

Platform adds a phase-neutral read_protected(value, limit) primitive on the constructor-issued NativeWindowsPrivateState. It returns only ordinary repr-private bytes and file identity, never nonce/capture/TLS/epoch authority. Exact bounds (1..4MiB), typed path, protected owner/DACL and non-reparse ancestor checks precede one opened read handle. Correlate path stat with regular, nonzero device/inode identity from fstat before/read/after, exact bounded bytes/size and final checked path identity. Every failure or BaseException closes the handle; no write, ACL repair, mkdir, DPAPI decrypt or fallback is performed. Keep existing generic read/write/capture APIs unchanged. Equal-byte replacement and swap-and-restore races must deny through handle identity. Sequential reads establish sampled observations, not an atomic global filesystem snapshot. Full TLS material, committed source/factory and original operational acceptance remain separate gates.


### Exact committed source association and bound sampling (2026-10-09)

Only NativeSecuredReadSource._from_committed_dependencies accepts the actual fixed assembly's exact issued committed graph. Its weak association retains a weak reference to the exact source owner; the immutable input signature includes the source instance. Copying the source or moving its association record never grants native authority. Losing a native association denies rather than falling back to the legacy component path. Ordinary component construction retains its existing locked/upsert repository queries and supplies no READ ONLY or original-source claim.

A source-private bound sample returns ordinary evidence/state/material only after verifying an already issued SecuredReadBinding from that exact native source. The distinct composite query route retains the actual source and exact binding and calls the concrete issuer's retained checks before and after each SQL await. Two fresh samples must equal the binding's original evidence, twelve-action state and protected credential/floor material; only the same verified-to-receipted transition is allowed. No protocol issuer, caller callback, arbitrary DTO, selected path or boolean is adopted. SQL rollback/close completes through the shielded cleanup barrier before cancellation propagates.

Native construction seals retain exact FunctionType code identity plus typed immutable defaults/keyword defaults, including transitive guards. A caller uses the concrete class assert_origin before invoking a potentially altered native entrypoint; a replaced entrypoint cannot check its own replacement. This protects the retained constructor graph, not arbitrary mutation of the checker/module or live DLL integrity. Path/DACL sampling is not atomic handle-ACL or invisible interval proof. The committed TLS reader must still verify actual crypto, seven fixed protected-file identities and both committed public references. These components do not activate the final observer/backend/factory or authorize original cutover, receipt or ingestion READY.


### Private committed TLS component and permanent observations (2026-10-09)

The standalone committed TLS reader can be constructed only from the actual fixed native Source and its exact retained issued binding. It derives the epoch/PREPARE_TLS action/IP from fresh committed samples, checks the actual original deployment target/scope, decrypts only the fixed bundle and validates actual ProjectTlsBundles crypto/materialization against six fixed bind files. Both the TLS row/evidence public manifest and the whole START_SECURED row/evidence deployment packet must match. Retain opened-handle identity plus bytes for all seven files; repeated full file samples bracket actual source-bound SQL sampling. A same-byte file replacement or any observed mismatch denies. This is sampled correspondence, not atomic filesystem or invisible interval integrity, live HTTPS/server identity or complete final-factory support.

Private construction/observe rechecks full source/config/SQL/native/file freshness; assert_observed only checks memory-retained exact reader/source/binding/dependency/native origins and ordinary observation seals. It performs no config/file/SQL read and is not a fresh observation. Exact source object references, primitive root and protection ports must match constructor-issued dependencies. Once this reader observes receipted state it cannot return to verified. Every BaseException invalidates its issuance; close consumes the exact reader's observations even if its retained assertion fails. Copied readers cannot invalidate the original. A caller-owned assembly remains responsible for session/engine lifetime; every synchronous protected file handle closes before returning. No new mutex, launch/pending token, generated credentials/material, arbitrary source path or approval flag is adopted.

The synthetic actual-graph acceptance and independent failures are recorded under the current native task. Integrate the standalone component with persistent low-transport regressions before any complete controller/factory activation. Original historical source mapping/settlement, operational security cutover, receipt/release/parity and queued ingestion remain separate unsatisfied gates. Existing servers/settings/schema/keys/gate and user data are preserved.
