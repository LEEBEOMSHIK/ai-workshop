# RAG 과거 제어 명령의 종료 경계 조사

- 날짜: 2026-10-02
- 상태: 설계 조사 완료, 실제 전환을 허용할 종료 경계 미확정
- 문제: ISSUE-00013
- 승인 범위: 다음 설계 조사. 원래 환경 변경·재시작 승인 아님
- 기준 계약: [접근 epoch 설계](../superpowers/specs/2026-10-01-rag-access-epoch-design.md), [ADR-0033](../decisions/0033-rag-access-epoch.md)
- 선행: [부분 구현과 증빙 공백](2026-10-02-rag-access-epoch-implementation.md)

## 목표와 보존 조건

과거에 기록하지 않은 Docker 명령의 완료를 소급해서 만들어내지 않고, 그 명령이 앞으로 원래 ES를 변경할 수 없다는 실제 경계를 찾는다. 원래 DB·계정·문서·물리 색인·named volume·큐를 보존하며 별도 환경을 만들지 않는다. 승인된 설계의 IDE·Codex·frontend 실행 보존 조건도 기본값으로 유지한다.

이번 작업에서 원래 Docker·WSL·OS 프로세스 종료, daemon 설정 변경, 인증서·키 발급, migration, gate 해제는 실행하지 않았다. 소스·기존 기록·공식 문서만 읽었다. 기존 Docker 12개/프로젝트 label 밖9개·running0 관찰은 선행 작업의 값이며 이번 조사에서 재확인한 값으로 보고하지 않는다.

## 분리해야 하는 두 조건

| 조건 | 의미 | 단독으로 부족한 이유 |
| --- | --- | --- |
| 이전 accepting execution의 확정 종료 | 구 JVM 및 그 구간에 위임된 작업이 더 실행되지 않음 | Windows의 오래된 client·supervisor가 다시 명령을 제출할 수 있음 |
| 구 제어 capability의 재사용 차단 | 구 client의 stop/start/recreate/retry가 새 배포를 바꾸지 못함 | 이미 수락된 명령이나 기존 JVM의 작업을 소급해서 끝내지 않음 |

새 ES TLS/API key는 애플리케이션의 익명 요청을 거부한다. Docker Engine의 컨테이너 생성·시작 권한을 폐기하는 기능은 아니다. cluster UUID, daemon ID, 컨테이너 부재, TCP 부재 또는 시간 경과도 위 두 조건의 대체 증거가 아니다.

이미 제출된 정상 Compose/restore/client retry는 지원 계약 안에 있다. 미래의 임의 악성 OS 관리자 행위는 제외하지만, 운영자가 신뢰된다는 이유로 정상 작업의 지연 실행까지 제외하지 않는다.

## 소스로 확인한 범위

`alias_recovery_local_native.py`의 `command_argv()`는 구 변경 명령을 정확한 컨테이너 ID의 `stop/start`로 고정한다. old ID 제거 뒤 새 `start(old_id)`가 새 컨테이너를 찾아 시작한다고 해석하지 않는다. 다만 명령이 이미 daemon에 전달됐거나 별도의 Compose/restore가 새 컨테이너를 생성하는 경우는 다른 경계다.

현재 `NativeCommandExecutor.run()`에는 durable invocation submission/result journal이 없다. 고정 HISTORY_FILES는 배포 출처 자료이며, 과거 제어 명령 전체의 완료 이력이 아니다. Sep30 `cutover.ps1`는 등록 앱의 실제 프로세스 세대 종료/시작을 다루며 전체 Docker 위임 명령의 완료를 증명하지 않는다. 기록된 사전검사 거부는 그 시도의 ES stop/start 미실행을 뒷받침하지만 모든 과거 제어의 completeness로 확대하지 않는다.

`AliasJournal`의 frozen gate는 cluster 단위다. 구 alias만 영구 격리하고 다른 alias를 여는 방안은 현재 gate 해제가 아니라 별도 업무 계약·스키마·쓰기 경로 변경이다. 새 alias가 같은 physical index를 사용한다면 늦은 명령의 영향 범위까지 검증해야 한다. 현재 자료로 이 대안을 안전한 가용성 해결책이라고 확정하지 않는다.

## 후보와 판단

| 후보 | 해결하는 부분 | 남는 부분 | 판단 |
| --- | --- | --- | --- |
| 기존 authoritative invocation 이력 복구 | exact submission·종료·위임 완료가 모두 있으면 현재 계약 유지 가능 | 그런 complete source가 아직 없음 | 자료가 실제 발견될 때만 채택 가능 |
| 구 컨테이너 ID 제거와 ES TLS/auth 전이 | old-ID START 및 익명 애플리케이션 callback 차단 | 이전 위임 작업, 새 auth-off recreate | 원래 전이의 일부이며 단독 해법 아님 |
| Docker Desktop 또는 Docker WSL 실행 종료 | 정확한 runtime 종료를 관찰하면 guest execution 종료 후보 | Windows retry/supervisor, 영속 재실행, 다른 자원 중단 | 단순 restart 명령 성공을 proof로 쓰지 않음 |
| 새 daemon 제어 capability·정책 | 구 client의 새로운 변이 요청 거부 후보 | 모든 endpoint·gRPC·upgrade·설정 복원 및 이미 수락한 작업 | 전체 경로를 통제하는 구현·실환경 검증 없이 채택하지 않음 |
| 전체 PC의 검증된 full boot 경계 | 이전 Windows/guest 메모리 실행을 함께 끝내는 후보 | 저장된 자동 실행·큐·복원 의도는 남음, 기존 도구 실행 유지 조건 변경 | 사용자가 설계 범위를 바꿀 경우의 추가 설계 후보. 재시작만으로 종료 확정 아님 |
| 구 alias 영구 격리와 새 alias 운영 | 과거 요청을 종료했다고 기록하지 않는 가용성 대안 | cluster gate 변경, captured 요청의 정확한 영향 범위, 공유 index 보호 | 별도 요구 승인 전 현재 작업에 혼합하지 않음 |

기존 도구 실행·현재 제어 endpoint를 그대로 유지하면서 과거 제어의 completeness 없이 두 조건을 모두 충족하는 방식은 이번 조사에서 입증되지 않았다. 이는 모든 가능한 해법이 불가능하다는 주장이 아니다. 실행 가능한 증빙 경계를 발견하지 못했다는 결과다.

## 공식 문서로 확인한 제한

Docker의 live restore는 daemon 종료 중에도 Linux 컨테이너 실행을 유지할 수 있다. 따라서 daemon 프로세스 종료만으로 구 JVM 종료를 주장할 수 없다. 실제 설정과 runtime 세대를 함께 확인해야 한다. [Docker live restore](https://docs.docker.com/engine/daemon/live-restore/).

Docker Desktop stop은 별도 CLI 동작이며 detach는 동기 완료를 기다리지 않는다. 그 완료가 프로젝트 Windows client의 종료를 뜻하지 않는다는 부분은 제어 경계에 대한 판단이다. [Desktop stop](https://docs.docker.com/reference/cli/docker/desktop/stop/).

`wsl --shutdown`은 모든 실행 배포판과 WSL2 utility VM을 종료한다. 특정 배포판 terminate와 범위가 다르다. Docker WSL 배포판 이름만으로 다른 실행 환경까지 중단할 권한을 얻지 않는다. [WSL 명령](https://learn.microsoft.com/en-us/windows/wsl/basic-commands#shutdown).

Docker authorization plugin은 Engine HTTP API를 대상으로 한다. 공식 문서가 native gRPC와 `POST /grpc`, 승인 후 upgrade stream을 적용 범위에서 구분한다. plugin 설치와 HTTP 성공 테스트만으로 전체 daemon capability 폐기를 증명할 수 없다. 이 문서는 Windows Docker Desktop의 새 plugin 지원·설치·전체 경로 통제가 검증됐다고 주장하지 않는다. [Docker authorization plugin](https://docs.docker.com/engine/extend/plugins_authorization/).

Windows의 full shutdown/boot는 사용자 세션을 다시 시작한다. sleep/hibernate/hybrid 경계와 같다고 보지 않는다. Docker Desktop에는 로그인 시 자동 시작 설정이 있으며 컨테이너 restart policy도 별개다. 따라서 새 boot 관찰 뒤 자동 실행·재전달 감사가 필요하다는 결론은 설계 판단이다. [Windows 전원 상태](https://learn.microsoft.com/en-us/windows/win32/power/system-power-states), [Docker Desktop 설정](https://docs.docker.com/desktop/settings-and-maintenance/settings/), [컨테이너 restart policy](https://docs.docker.com/engine/containers/start-containers-automatically/).

## full boot 후보를 검토하게 될 경우의 성공 기준

다음은 실행 절차나 승인된 새 proof 계약이 아니다. 전체 PC 재시작도 설계 범위에 포함한다는 답이 오면 작성할 계약의 필수 요구다.

1. 유지보수 전 원래 OS/VM/daemon/JVM 세대와 exact claim을 기록하고, 보호된 checkpoint와 DB의 execution 소유권을 연결한다. PID·daemon ID 단독을 실행 세대로 쓰지 않는다.
2. 원래 앱·worker·beat의 제출을 중단하고 broker의 ready/unacked/예약 작업을 삭제 없이 보존한다. 과거 operation ID/raw 요청의 재전달과 정상 새 command를 구분한다.
3. OS 로그인 자동 실행, 등록 서비스·작업·restore helper, Docker 자동 시작·restart policy 및 guest scheduler의 실제 재실행 경로를 조사한다. 확인되지 않은 경로가 있으면 차단한다. 동일 OS 사용자 권한의 임의 future control을 machine-fenced라고 표현하지 않는다.
4. 원래 PostgreSQL·Redis를 정상 종료·영속화하고 실제 설정·flush/종료 결과와 원래 volume을 기록한다. AOF 선언만으로 미완료 큐 보존을 단정하지 않는다. 외부 프로젝트 자원의 상태와 정책도 변경 없이 대조한다.
5. full boot 관찰이 checkpoint 이후의 실제 이전 kernel/guest 실행 종료 경계인지 검증한다. 화면 로그인, 새 PID, 명령 반환 또는 elapsed time만으로 대신하지 않는다. 관찰 SDK와 OS event의 실제 의미·권한·변조 신뢰 경계를 검증하기 전 구현 준비 완료로 표시하지 않는다.
6. 새 controller는 보호된 checkpoint와 실제 boot 경계를 확인한 뒤 exact 기존 execution을 이어받는다. 이전 외부 unknown action을 settled로 바꾸거나 재발행하지 않는다. boot로 종료된 실행과 정상 완료된 action은 구분한다.
7. 원래 이미지·물리 volume·cluster/stable node를 확인하고 기존 epoch 전이의 순차 stop/retire/bootstrap/final secured 흐름을 수행한다. boot 뒤 새로 시작된 구 컨테이너가 있다면 그 실제 JVM을 old baseline으로 재관찰하며 과거 stop 시각을 재사용하지 않는다.
8. 새 endpoint/floor가 과거 application capability를 거부하고, 재시작된 프로젝트 제어가 auth-off 배포를 복원할 수 없는 지원 경계를 검증한다. raw Docker/관리자 경로를 제외한다면 명시적 지원 범위 변경과 사용자 승인이 필요하다.
9. 실제 v2 계약으로 표현 가능한지 검토한다. 기존 proof 필드에 boot 관찰을 숨겨 넣거나 historical settlement digest를 성공 boolean으로 채우지 않는다. 계약 확장이 필요하면 설계·ADR·추가 migration 계획을 먼저 검토한다.
10. 실제 receipt·exact release·현재 DB 기준 새 parity·원문/계정/큐 보존을 각각 검증한다. PC 재시작 승인과 이러한 업무 완료는 별개다.

전체 PC 재시작은 실행 중 IDE·Codex·프론트를 끊으며 다른 앱·WSL 환경에도 영향을 줄 수 있다. 저장되지 않은 사용자 작업을 강제로 종료하는 `/f` 방식은 제안하지 않는다. [Windows shutdown 명령](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/shutdown)은 강제 종료 시 미저장 데이터 손실 위험을 명시한다.

## 다음 결정과 검증 상태

독립 보안 검토는 이 문서를 조사 결과로 수용했으며 사실·승인 경계의 차단 결함은 찾지 않았다. 실제 종료 방식, proof 설계, 구현 또는 배포를 승인한 결과는 아니다. 검토의 지원 범위 명확화 의견을 위 두 조건에 반영했다.

사용자에게 기존 도구 실행 보존을 유지할지, 전체 PC 재시작도 **설계 범위에만** 포함할지 물었다. 답이 없으면 기존 보존 조건을 유지한다. 실제 PC/Docker/WSL 재시작 승인을 요청하거나 받은 것은 아니다. 어느 선택이든 기존 v1/v2 의미와 historical unknown 상태를 조용히 완화하지 않는다.

전체 PC 범위를 포함한다는 선택이 오면 위 성공 기준을 구체적인 관찰·소유권·실패 계약으로 작성해 독립 검토 후 제시한다. 기존 도구 실행을 유지하면 authoritative historical source 또는 모든 제어 경로의 실제 capability fencing이 추가로 입증될 때까지 원래 cutover를 차단한다. 구 alias 격리라는 별도 가용성 방향은 종료 복구 완료로 보고하지 않는다.

이번 변경은 조사 문서와 WORKBOARD뿐이다. 이전 3,369개 단위 테스트 결과를 이번 조사에서 재실행한 결과로 표기하지 않는다. 제품 코드·schema·Compose와 원래 실행 환경은 변경하지 않았다. 아직 품질 개선만 남은 상태가 아니다. 문제 DB의 새 문서 연결은 인증된 관리자 경로로 반영하기 전 미완료다.
