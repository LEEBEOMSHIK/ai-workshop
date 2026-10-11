# RAG 별칭 복구의 서버 측 접근 epoch 전이

- 상태: 독립 보안·계약 검토 후 사용자 설계 승인(2026-10-01). 구현 계획 작성 중, 본래 배포 미승인.
- 날짜: 2026-10-01
- 문제: ISSUE-00013
- 선행: [ADR-0032](../../decisions/0032-rag-alias-recovery.md), [v1 복구 계약](2026-09-30-rag-alias-recovery-design.md)
- 결정 초안: [ADR-0033](../../decisions/0033-rag-access-epoch.md)

## 목적과 현재 상태

현재 개발 PC의 IDE·Codex·frontend build는 범용 실행기여서 v1의 전체 client 종료 계약에
들어오지 않는다. Node 실행 파일 상위 심볼릭 링크 거부도 확인됐지만, 링크 허용만으로
늦은 ES 쓰기가 불가능해지는 것은 아니다. 기존 개발 도구를 유지하면서 실제 미종료 별칭
요청의 재전송 능력을 끝내고, 현재 DB 기준 새 정상 parity를 실행하는 것이 목표다.

본래 operation은 legacy_unknown/open, 동일 claim은 frozen revision1, receipt0다.
진단 개선은 완료됐으며 이 설계만으로 서버·gate·operation을 바꾸지 않는다.
별도 애플리케이션 DB·계정·환경을 만들지 않고 기존 문서·원본·색인·활성 구성·큐를 보존한다.

## 대안과 선택

| 대안 | 의미와 제한 | 선택 |
| --- | --- | --- |
| IDE/Node/Codex 예외 확대 | 실행 파일 식별은 미래의 요청 불능을 증명하지 않는다 | 제외 |
| idle 유지보수 취소 | 해당 alias를 계속 막으면서 다른 alias를 열 수 있으나 기존 요청은 종료되지 않는다 | 별도 가용성 방향으로 보존 |
| 새 서버 접근 epoch | 이전 accepting JVM을 끝내고 새 서버가 과거 capability를 거부한다 | 이번 제안 |

접근 epoch는 서버의 인증·TLS·배포 경계와 새 application credential 세대를 묶는 식별자다.
과거 익명 HTTP 요청은 새 HTTPS 서버에서 인증받지 못한다. 기존 포트를 유지해도 capability가
같아지는 것은 아니다. 모든 host/guest/internal 경로가 같은 보호를 적용해야 한다.

이는 신뢰하는 로컬 운영자·Docker daemon 경계다. 악의적인 OS 관리자나 secret 탈취를
차단한다는 주장은 하지 않는다. 이미 실행한 정상 collector·복원·Compose 작업의 지연
실행과 application callback/큐의 credential 승격은 실제 지원 경로이므로 반드시 통제한다.

## 보존과 실제 배포 변경

기존 고정 ES 이미지 버전과 정확한 named data volume을 유지한다. 기존 보안 비활성
컨테이너의 종료를 확인하고 **그 컨테이너 메타데이터만 제거**한 다음, 동일 데이터 볼륨을
순차 사용하는 TLS·인증 컨테이너를 만든다. 이전 컨테이너 ID는 더 이상 START할 수 없다.
원본 볼륨 삭제·초기화·복사, 이미지 업그레이드, 새 Compose project, prune/down -v는 금지한다.
전이 전 live identity로 대상 ID·volume·daemon·network를 확정하며 운영값을 업무 코드에 박지 않는다.

동시에 두 live ES가 데이터 경로를 mount하지 않도록 inspect와 실행 상태를 대조한다.
이름이나 복제 cluster UUID만으로 보존을 주장하지 않는다. 같은 물리 volume·cluster UUID·
영속 node ID, 기존 physical index/문서 수·설정 지문·추적 정보와 원본 SHA를 확인한다.
새 security metadata 때문에 전체 volume의 byte hash가 같다고 주장하지 않는다.

HTTP와 transport에 서로 다른 새 프로젝트 전용 CA·TLS 인증서를 적용하고 익명 권한은 비활성화한다.
transport는 client_authentication=required, 단일 node의 검증된 인증서만 사용하며 9300을
host에 publish하지 않는다. guest의 transport 접근도 client 인증 없이는 거부되어야 한다.
host publish는 기존 loopback 범위, 내부 service DNS/direct IP도 보호된 서버로만 연결한다.
추가 HTTP profile·transport·remote cluster·credential 삽입 relay는 manifest에서 제외를
증명하거나 보호를 확인한다. 미확인 ingress·인증 이전 키/권한은 전이를 차단한다.
security=false였다는 이유로 과거 .security 상태가 없다고 가정하지 않는다. 기존 hidden
security-state metadata 부재를 확인하거나 secure 시작 뒤 bootstrap port로 과거 principal/key
write capability를 명확히 식별해 승인된 대상만 폐기한다. 미확인 상태는 proof를 거부하며
security index·user·key 일괄 삭제 또는 암호 일괄 재설정으로 대체하지 않는다.
과거 key가 폐기 전 새 bootstrap JVM에 요청을 제출했을 가능성이 있으면 key 폐기만으로
그 이미 수락된 작업을 종료했다고 보지 않는다. 접근 통제된 bootstrap으로 수락을 방지하거나,
폐기 후 해당 accepting JVM의 definitively settled 종료와 최종 secured 새 실행을 추가 확인한다.
그 제어 단계·JVM 세대도 execution 이력과 control settlement manifest에 포함한다.
CA는 application client에만 지정하며 OS 전역 신뢰 저장소를 변경하지 않는다.
certificate/hostname 검증 실패 때 인증서 검증을 끄거나 HTTP로 fallback하지 않는다.

실제 전환에서는 등록된 기존 API·worker·beat만 정상 종료하고 새 세대로 다시 실행한다.
IDE·Codex·frontend와 관계없는 프로세스는 유지한다. ES/백엔드 재시작 동안 RAG 검색·답변에
일시 중단이 있으며, health와 생성 연결·검색을 재검증한 뒤 사용할 수 있다고 알린다.
중단 시간은 실제 실행에서 측정하며 아직 검증하지 않은 분 단위 보장을 하지 않는다.

## Credential 배포와 과거 callback

새 ES API key는 현재 prefix의 필요한 index/alias 작업과 관찰 권한으로 제한하고,
보안 변경·키 생성·node join 권한을 주지 않는다. alias/index 관리에 필요한 ES index manage
권한은 삭제도 포함하므로 alias 전용 권한이라고 표현하지 않는다. 허용 범위는 검증된 현재
namespace로 제한하고 이 잔여 권한 폭을 permission manifest에 기록한다. reader/writer/collector의 권한 명세와
실제 호출 목록을 대조한다. ES service key이며 새로운 AI Workshop 사용자 계정이 아니다.
bootstrap 관리자 credential은 cutover controller에만 있고 API/worker 설정에 전달하지 않는다.

beat에는 실제 호출상 필요한 경우만 key를 주며 frontend에는 주지 않는다.
key 발급 응답이 유실되면 exact epoch/role/issuance의 key ID를 bootstrap metadata로 대조하고
그 inaccessible 발급 건만 폐기한 뒤 교체한다. 결과 미확정 상태에서 key를 반복 발급하지 않는다.

새 key는 private owner-controlled store에 보관하고, 고정 launcher가 현재 epoch와 역할·module을
검증한 뒤 **새 process의 환경에만** 전달한다. launcher의 부모/shell 환경은 변경하지 않는다.
root `.env`에는 HTTPS endpoint·공개 CA·epoch 참조만 저장하며 key·비밀번호는 넣지 않는다.
Settings/client는 시작 시 credential을 고정해 사용하고 secret 파일을 자동 검색하거나
매 요청 reload하지 않는다. 구 callback이 새 key를 받는 일반 broker·proxy는 제공하지 않는다.

과거 배포의 alias entrypoint·captured client·Celery payload/재전달을 먼저 감사한다.
이미 dispatch한 operation ID/raw 요청을 새 worker가 다시 보낼 수 있으면 전이를 차단한다.
정상 큐 재전달은 기존 권한·멱등성·새 reserve/dispatch CAS를 거친다. 큐를 비우지 않는다.
기존 in-process callback은 익명 client만 보유하고, ordinary config reload로 새 권한을
얻지 못해야 한다. 새 보안 세대와 현재 DB truth로 만든 새 작업을 과거 요청 replay와 구분한다.

키·Authorization·관리 비밀번호·private key·secret-bearing 명령/환경/응답·그 해시는
로그·proof·이력·Git·테스트에 저장하지 않는다. 감사에는 epoch/key ID·공개 인증서 SHA·
nonsecret manifest digest만 사용한다. bootstrap 결과는 고정 private controller 내부에서
처리하고 원시 stdout/stderr를 사용자 도구 결과로 출력하지 않는다.

## DB 상태와 외부 실행 소유권

추가 migration으로 Labs/RAG에 access epoch와 cutover execution 기록을 도입한다.
기존 operation, gate claim/revision, v1 receipt와 reserved CAS 의미는 그대로 둔다.
epoch는 cluster/store·정확한 request/operation/actor/snapshot과 nonsecret 배포 identity에
묶이며 cluster별 미완료 cutover는 하나다. 명명된 unique/check/FK와 immutable event로 지킨다.

cutover 단계는 prepared → old_stopped → old_retired → secured_started → verified → receipted다.
각 외부 호출은 **호출 예약을 먼저 commit**하고 실행 ID·고정 명령 종류·expected identity·
outcome=pending/settled/unknown을 기록한다. owner → gate → operation → execution 순서로 짧게 잠그며
OS/Docker I/O 동안 DB row lock을 유지하지 않는다. TTL이나 process silence로 소유권을 회수하지 않는다.

새 recover 경로는 단일 durable execution 소유권을 얻은 뒤에만 외부 변이를 시작한다.
재접수는 같은 request/execution의 readback이다. 누가 executor인지 불명확하거나 control
호출이 unknown이면 frozen을 유지한다. DB CAS와 Docker 동작 사이의 간극을 lease로 숨기지 않는다.

배포 전 이전 v1 collector·restore·Compose command와 자식/daemon delegation이 모두 종료 또는
definitively settled인지 확인한다. 이미 시작한 old Compose up은 컨테이너 ID 제거로 막을 수
없으므로 unresolved이면 전환하지 않는다. 명령 이름/TCP 부재만으로 settled라고 쓰지 않는다.
전이 controller는 현재 고정 project/config만 사용하는 단일 직렬 실행 경로다.
중단된 controller의 재개는 exact readback·외부 상태 대조와 이전 executor 세대/자식/daemon
작업의 definitively settled 증명 후 단일 control port 소유권을 다시 얻은 경우만 가능하다.
현재 inspect만 보고 pending 작업을 재발행하거나 새 request로 추측하지 않는다.
old stop의 완료된 관찰과 시각은 retirement 전에 영속 저장한다. old ID가 없어진 뒤 시각을
역추정해 채우지 않는다. 각 다음 단계는 이전 action의 durable settled 결과를 요구한다.

verified epoch에는 인증 floor를 영속 저장한다. 이후 startup/recreate/recovery와 writer admission은
현재 secured identity/floor를 검증하며 auth-off 또는 과거 설정을 거부한다. 기본 Compose·
runbook·health check도 같은 계약을 따른다. 이미 실행 중인 과거 코드와 혼합 배포하지 않는다.

## 별도 v2 proof와 원자적 종료

`LocalAccessEpochTerminationProof`, schema_version=2,
proof_kind=`local_single_node_access_epoch`를 추가한다. v1의 client inventory나
clients_terminated_at을 가짜로 채우지 않으며 기존 v1 타입·검증·receipt는 변경하지 않는다.

v2의 exact 필드 집합은 아래 표다. JSON 부가 필드·다른 타입·unknown version은 거부한다.
각 digest는 이름이 가리키는 allowlisted nonsecret 관찰 manifest의 canonical SHA256이다.

| 타입 | 정확한 필드 |
| --- | --- |
| UUID text | request_id, operation_id, actor_id, access_epoch_id, execution_id |
| 양의 integer (bool 제외) | gate_revision, minimum_access_epoch |
| 정확한 integer 2 | schema_version |
| 정확한 kind text | proof_kind |
| 기존 validated identifier text | store_id, cluster_uuid, stable_node_id, old_ephemeral_id, new_ephemeral_id |
| lowercase 64-hex | snapshot_sha256, old_container_id, new_container_id, daemon_identity_sha256, original_volume_identity_sha256, protected_mount_sha256, protected_image_sha256, old_config_sha256, new_config_sha256, old_deployment_sha256, new_deployment_sha256, route_policy_sha256, tls_public_ca_sha256, auth_policy_sha256, credential_deployment_sha256, deployment_history_sha256, control_settlement_sha256 |
| timezone-aware UTC text | old_jvm_start_at, old_server_stopped_at, old_container_retired_at, new_server_started_at, new_jvm_start_at, access_verified_at, verified_at |

old/new container와 ephemeral ID는 서로 달라야 하고 cluster/stable node/물리 volume/image는
보존되어야 한다. causal 순서는 old JVM 시작 ≤ old stop ≤ old retirement < secured start ≤
new JVM 시작 ≤ access verified ≤ verified이며 verified는 미래일 수 없다. 관찰의 시간 해상도 때문에 stop과
retirement가 같을 수 있어도 완료된 외부 실행 기록의 선후 관계가 별도로 필수다.
minimum_access_epoch는 exact verified epoch의 순번과 같고 이전 floor보다 높아야 한다.
request/operation/actor/gate revision/snapshot은 현재 claim과, 모든 deployment/route/auth
관찰은 linked epoch/execution의 immutable manifest와 같아야 한다.

실제 fixed collector만 live 관찰과 완료된 실행 기록으로 proof를 만든다. CLI에 caller JSON,
성공 flag, 허용 process/route 목록 또는 secret attestation 입력을 받지 않는다.
시각·digest는 관찰을 연결하며 관찰 자체를 대체하지 않는다.

service는 live 권한·snapshot·claim·protected identity·auth floor를 다시 확인한다.
최종 transaction은 verified exact epoch/execution, claim와 operation을 잠그고
recovered_terminated closure와 불변 v2 receipt·epoch receipted를 원자적으로 기록한다.
0061의 gate release·deferred receipt integrity는 유지하고 v2의 명명된 제약을 추가한다.
응답 유실은 동일 request readback으로 확인하며 새로운 cutover/키/alias 요청을 만들지 않는다.

과거 요청의 target을 확인했다고 기록하지 않는다. 결과는 과거 invocation의 늦은 적용 능력이
종료됐다는 의미다. exact release와 현재 DB truth로 만든 새 정상 parity는 별도로 검증한다.

## 실패·복원과 호환

| 상황 | 처리 |
| --- | --- |
| 외부 변이 전 preflight/감사 실패 | 원래 서버와 frozen claim 유지, 안전한 실패 코드 기록 |
| stop/remove/start 결과 유실 | pending/unknown과 frozen 유지, exact live readback으로 해결 |
| 새 TLS/auth 또는 원본 identity 불일치 | closure/release 금지, secured 환경에서 원인 수정 |
| receipt commit 응답 유실 | 동일 request로 atomic receipt readback, 외부 재실행 금지 |
| v2 종료 후 재시작 장애 | 같은 데이터·인증 floor의 forward repair, 익명 서버 rollback 금지 |

컨테이너 제거 이후에는 security=false 원본 실행으로 되돌려 가용성을 복원하지 않는다.
새 secured 설정에서만 복원하며 current gate가 frozen일 때도 이 원칙을 지킨다.
v2 receipt/epoch가 있으면 migration downgrade를 거부한다. DB/config backup 복원도 floor를
낮추는 단순 rollback으로 취급하지 않는다. 호환되지 않는 구 writer/collector는 시작을 거부한다.

## 변경 책임과 검증 기준

Platform이 Labs/RAG를 참조하지 않도록 generic settings/ES client/secret-launch adapter와
RAG proof/service/repository/schema를 분리한다. UI·LLM·검색 순위·프로파일 승격은 변경하지 않는다.

영향 파일군: config.py와 infrastructure/search factory, 고정 local launcher/cutover adapter,
alias recovery types/service/repository/CLI와 models, 추가 alembic migration,
Compose와 실행서, 관련 unit/integration tests. 큰 native helper에 unrelated 정책을 계속 붙이지 않는다.

검증은 다음을 필수로 한다. offline success는 본래 cutover 성공으로 보고하지 않는다.

1. 늦은 anonymous callback/keepalive/reconnect/retry를 전이 전후 재개해 변이0, 새 정상 key 작업 성공.
2. host 및 guest/internal admitted route의 HTTPS/auth enforcement, anonymous·old capability·잘못된 CA 거부.
3. old config reload·stale queued ID는 fresh credential/dispatch를 얻지 못하고 정상 새 reserve는 가능.
4. old v1 START/Compose race·daemon 결과 유실·controller crash·동시 recover를 deterministic barrier로 검증.
5. singular original volume·정확한 identity, startup floor·auth 지속, backward config/unknown state 거부.
6. proof kind/schema·필드/권한/claim 불일치·forgery·close race·lost commit·exact replay·별도 release의 DB 제약 검증.
7. secret 출력0, app 최소 권한과 bootstrap 권한 분리, 기존 v1/reserved 회귀와 타입·린트 검사.
8. 승인된 본래 전환에서 계정·원문·색인·구성·큐 보존, old JVM 종료·v2 receipt·gate release·새 parity,
   검색/원문/생성 연결·실제 failure 기록/monitoring을 각 단계로 확인한다.

## 사용자 검토와 다음 승인 범위

이 초안을 승인하면 구현 계획을 작성해 역할별 코드·검증 순서와 exact 운영 대상·secret 보관·
중단/회복 절차를 확정한다. **초안 승인은 실제 컨테이너 제거나 credential 생성 승인과 다르다.**
오프라인 구현·독립 검증을 완료한 후 본래 cutover 직전에 구체적인 배포 변경 승인을 받는다.
현재 auth-off 원본 ES를 보존한 채 코드만 준비하며, 관리자 DB 문서 등록은 본래 로그인 후 진행한다.

품질만 남았다는 보고는 WORKBOARD의 기능 마감 기준을 모두 충족한 뒤 한다.
이 설계 작성이나 별칭 코드 테스트만으로 전체 RAG 기능 완료를 선언하지 않는다.

## 기본 문서 근거

기존 cluster의 보안은 수동으로 활성화하고 설정을 반영한 실행을 준비해야 한다.
[Elastic minimal security](https://www.elastic.co/docs/deploy-manage/security/set-up-minimal-security).
HTTP/transport 인증·TLS 설정은 별도다.
[Elastic security settings](https://www.elastic.co/docs/reference/elasticsearch/configuration-reference/security-settings).
Python client는 API key와 명시적 CA를 지원한다.
[Elastic Python connecting](https://www.elastic.co/docs/reference/elasticsearch/clients/python/connecting).
Compose recreate는 mounted volume을 보존하지만 이 운영의 정확한 동일 volume 확인은 별도 필수다.
[Docker compose up](https://docs.docker.com/reference/cli/docker/compose/up/).
