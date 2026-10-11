# RAG 별칭 복구 사전 검사와 호스트 관찰

- 상태: 사용자 후속 작업 범위의 구현 계약. 기존 종료 증거 계약을 유지하는 읽기 전용 개선이며 독립 검토 후 구현한다.
- 날짜: 2026-10-01
- 문제: ISSUE-00013
- 선행: [정상 복구 설계](2026-09-30-rag-alias-recovery-design.md), [ADR-0032](../../decisions/0032-rag-alias-recovery.md)

## 목표와 완료 기준

본래 개발 PC에는 IDE·Codex·frontend build·Docker build가 함께 실행된다. 기존 HOST 관찰은
같은 실행 파일의 서명·해시를 반복 조회해45초 제한을 넘었다. 이 비용을 줄여 차단 조건을
관찰하고, 앞으로 새 유지보수를 시작하기 전에 지원 여부를 확인한다. 기존 도구·자료·계정·
DB·색인·서버를 보존한다. 이번 변경은 미종료 요청을 실제로 닫는 작업과 구분한다.

성공 기준은 읽기 전용 사전 검사의 지원/차단 결과가 본래 환경에서 반환되고, 사전 검사
실패 때 새 gate·receipt·alias 변이·서버 중지가0인 것이다. 현재 exact frozen revision1은
변경하지 않는다. 사전 검사 통과는 종료 proof·복구 성공이나 새 parity 성공을 뜻하지 않는다.

## 비교한 대안과 선택

1. 정확한 모듈·서명·부모에 IDE/Codex/build 예외 추가: 관련 도구 식별에는 도움이 되지만
   범용 실행기의 지연 ES 쓰기 불능을 보장하지 않는다. v1 proof 기준을 바꾸지 않는다.
2. 기존 endpoint 또는 인증 권한 폐기: 늦은 client를 서버 측에서 거절할 수 있는 별도
   방향이다. Docker publish는 container 생성 시 정하고 현재 어댑터에는 ES 인증 설정이
   없어 배포·credential·proof·migration 계약이 확장된다. 이번 읽기 전용 변경에 섞지 않는다.
3. 사전 검사와 호출 내 관찰 중복 제거: 채택. 지원 범위를 넓히지 않고 현재 차단을 더
   빨리, 유지보수 전에 확인한다. 실제 종료에는 여전히 기존 controlled restart 증거가 필요하다.

취소만으로 현재 cluster gate를 해제하는 대안도 제외한다. 0061은 open 요청의 release를
금지하며, DB CAS만으로 잠금 밖에서 실행 중인 collector의 stop/start를 취소할 수 없다.
취소를 지원하려면 별도 실행 소유권·외부 변이 장벽·불변 취소 이력 계약이 먼저 필요하다.

## CLI와 어댑터 경계

`preflight --operation UUID --actor UUID`를 기존 privileged local CLI에 추가한다. 설정은
원래 고정 `.env`, local/owner/binding/canonical snapshot 검증을 유지한다. 호출자가 proof,
허용 프로세스, 환경 파일이나 성공 flag를 넘길 수 없다. public API·UI는 추가하지 않는다.

`OriginalWindowsBackend.preflight(snapshot) -> None`는 기존 identity·history·host 검사를
재사용한다. 이 경로의 command executor는 고정 읽기 명령만 허용하고 STOP/START는 실행
전에 거부한다. `LocalTerminationCollector`, closure, release 또는 parity를 호출하지 않는다.
reserved 요청은 기존 CAS 경로라 종료 collector 사전 검사가 필요 없다는 결과를 표시한다.

결과는 `preflight=ready|blocked|not_required`, `termination_proven=false`,
`parity=not_run` 및 안전한 진단 코드다. blocked는 비정상 종료 코드로 반환한다. command
line·실행 파일 경로·source body·credential·원시 OS/Docker 오류는 출력하거나 기록하지 않는다.

새 `freeze`는 현재 snapshot/owner와 제공한 digest를 먼저 확인하고 readback한다. open
legacy_unknown/dispatching의 **새 claim 획득 전** 사전 검사가 필요하다. 실패하면 freeze를
호출하지 않는다. reserved, 이미 closed인 요청, 동일 frozen claim 또는 terminal receipt의
정확한 재접수에는 종료 관찰을 반복하지 않는다. 다른 actor/request·snapshot·현재 gate 충돌과
불명확 readback은 기존 오류 계약대로 중단하며 OS 변이로 추측하지 않는다.

사전 검사와 gate 획득 사이의 상태 변화는 기존 freeze CAS가 검증한다. recover의 실제
clients_absent와 controlled stop/start·재검사는 그대로 필수다. 사전 검사 결과를 저장해
나중의 client 부재 증거로 쓰거나 freeze/recover에서 재사용하지 않는다.

## 호출 내 실행 파일 관찰

HOST의 한 번의 fresh inventory에서만 정규화한 정확한 executable path별 서명·SHA256을
공유한다. 파일의 OS 읽기 handle을 유지하고 write/delete sharing을 금지한 상태에서
서명·해시를 확인한다. handle은 inventory 완료/오류 시 finally에서 모두 닫는다. 경로가
모호하거나 잠금/관찰이 실패하면 거부하고 이전값·다른 binary로 대체하지 않는다.

각 process의 PID·부모·생성 시각·module은 계속 개별 관찰한다. 서로 다른 executable은
합치지 않는다. 별도 HOST 호출은 다시 조회하며 global cache·TTL·기존 증거 재사용은 없다.
45초 timeout, 고정 PowerShell 파일/해시, WSL/직접 endpoint/unknown process/TCP/peer 검사는
유지한다. 중복 제거를 위해 서명 검사나 현재 허용 범위 밖 process를 생략하지 않는다.

## 변경 범위와 검증

수정은 native collector helper·CLI와 각각의 단위 테스트다. 원장 업무 서비스·DB schema·
TerminationProof v1·권한·모델·frontend는 바꾸지 않는다. 기존 첫 질문 미커밋 변경은 보존한다.
실제 fixture는 본래 원문 대신 합성 입력이며 새 작업 임시 경로를 재사용/삭제하지 않는다.

검증 시나리오:

- 사전 검사에서 gate/receipt/STOP/START/alias/parity 호출0, blocked·ready 모두 proof=false.
- 새 freeze의 사전 검사 실패는 freeze0, 성공 뒤 snapshot 변경은 기존 CAS 실패.
- reserved/closed/exact frozen/terminal receipt 재접수는 불필요한 HOST0, 타 claim·digest 오류 차단.
- 같은 binary 여러 process는 서명/해시1회, 다른 binary는 각각, 두 호출은 다시 조회.
- 잠금 유지 중 교체/쓰기 시도 실패, 오류 시 모든 handle 해제·실패 전파, 해시/서명 오류 거부.
- 기존 unknown runtime·WSL/Docker build·TCP·controller·원본 설정 거부 검사는 유지.

관련 pytest·Ruff·mypy와 독립 spec/quality 검토 후 root만 본래 preflight를 읽기 전용 실행한다.
그 전후 exact gate/request/operation·receipt 수와 ES generation, 앱 health·보호 자료를
비교한다. 별도 DB·계정·환경·컨테이너 생성 또는 기존 서버 중지는 하지 않는다.
ISSUE-00013 DB에 실제 차단 코드·검증 범위·정확한 문서 버전을 누적 기록한다.

## 후속 종료 경계

현재 PC에서 v1의 전체 client 통제를 충족하지 못하면 open/frozen을 유지한다. 실제 복구는
별도 검토한 서버 측 접근 폐기 또는 충분한 client 통제 계약이 필요하며, 해당 설계가 v1과
다르면 새 proof kind/schema·DB 제약·배포 계약으로 명시한다. v1 영수증으로 위장하지 않는다.

근거: [Docker port publishing](https://docs.docker.com/get-started/docker-concepts/running-containers/publishing-ports/),
[Elasticsearch minimal security](https://www.elastic.co/docs/deploy-manage/security/set-up-minimal-security).
