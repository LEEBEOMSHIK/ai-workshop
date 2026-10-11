# RAG 접근 전환의 Windows 잠금 보유 구현

- 날짜: 2026-10-08
- 문제: ISSUE-00013 (실제 별칭 복구는 계속 open)
- 범위: 승인된 [접근 전환 계획 Task4](../superpowers/plans/2026-10-01-rag-access-epoch.md)의 OS 잠금 primitive
- 계약: [ADR-0033](../decisions/0033-rag-access-epoch.md#2026-10-08-windows-잠금-보유-구현-범위)
- 실행 환경: 본래 저장소와 기존 공식 Python 3.13 가상환경. 새 DB·계정·애플리케이션 환경 생성 없음

## 구현 결과

Infrastructure에 `cutover_control_windows.py`를 추가했다. 검증된 daemon identity SHA와
Compose project를 입력으로 고정 Global namespace의 잠금 이름을 도출한다. 호출자가 임의의
mutex 이름이나 raw handle을 주입하는 공개 인터페이스는 없다. 실제 배포 identity의 검증은
향후 고정 controller가 담당하며, 문자열 형식 검사 자체가 배포 검증을 대신하지 않는다.

획득·검사·해제를 같은 스레드에서 수행하고, execution UUID·canonical generation·새 session
token을 연결한다. token 값이 같은 복사본도 거부한다. Python Thread 객체와 native thread ID를
함께 고정하고, assertion 때 다시 wait하지 않는다. 새 인스턴스라도 같은 스레드·같은 이름을
재귀 획득할 수 없도록 등록을 유지한다. 최초 상태 claim과 등록은 한 guard 안에서 처리한다.

`CreateMutexW(initial_owner=false)`와 nonblocking `WaitForSingleObject(timeout=0)`를
한 번만 사용한다. clean acquisition만 성공하며 busy·알 수 없는 결과·잘못된 thread/token은
고정 오류로 거부한다. `WAIT_ABANDONED`가 현재 스레드에 부여한 소유권은 release와 close로
정리한 뒤 거부한다. 이를 과거 작업의 완료로 해석하지 않는다.

release가 실패하거나 중단되어도 close를 시도한다. 불명확한 정리를 성공으로 반환하지 않고
세션을 재사용하지 않는다. 인터럽트는 원래 중단으로 전파한다. 불명확한 wait/cleanup의
같은 스레드·이름 등록은 보존한다. 정상 close 뒤에도 해당 객체를 다시 획득하지 않는다.

## 발견한 결함과 검증

구현 전 테스트는 모듈 부재로 collection error 1건을 확인했다. 첫 구현에서 25개가 통과했다.
추가 검사에서는 native ID의 `True`와 정수 `1`이 같게 비교되는 사례를 재현해 정확한 정수
검사를 추가했다. 이 단계는 실패 1·통과 3에서 전체 29개 통과로 변경됐다.

독립 코드 리뷰에서 다음 두 결함을 발견했다. 결정적 실패 3건을 확인한 뒤 수정했다.

1. 두 스레드가 같은 객체의 최초 획득을 동시에 통과하면 공유 handle/owner 상태를 덮어썼다.
   최초 claim·소유 스레드·등록을 원자적으로 처리해 성공 소유자가 하나만 남도록 수정했다.
2. wait 또는 release 중 KeyboardInterrupt가 발생하면 cleanup을 건너뛰었다.
   BaseException 정리 경계를 추가해 close 시도와 미확정 등록을 보존하고 중단을 전파했다.

최종 검증은 다음과 같다. 전체 저장소 테스트 성공으로 확대하지 않는다.

| 검증 | 실행 결과 |
| --- | --- |
| Infrastructure local + RAG indexing 단위 회귀 | 522 passed, 기존 경고 1, 30.28초, exit 0 |
| Ruff, 새 source와 test | 2파일 통과 |
| Mypy, 새 source | 1파일 통과 |
| 독립 코드·보안 리뷰 | 차단 finding 없음, 독립 fake 단위 32 passed, 0.23초 |
| 독립 통합 담당의 최종 fake 단위 | 32 passed, 0.37초, exit 0 |
| 실제 Windows 합성 mutex 검사 | 5조건 통과, exit 0 |
| 프로젝트 역할 계약 검사 | exit 0 |

주 회귀 명령은 backend cwd의 기존 `.venv/Scripts/python.exe -B` child에서
`AI_WORKSHOP_*` 환경값만 제거한 뒤 `pytest -c pyproject.toml tests/unit/infrastructure/local
tests/unit/labs/rag/indexing -q --tb=short --basetemp <작업별 local-data 경로>`였다.
네트워크·모델 없이 fake 경계를 검증했으며 부모와 서비스 환경을 수정하지 않았다.
기존 경고는 Starlette TestClient의 httpx deprecation이다. 의존성 변경은 하지 않았다.

실제 커널 검사는 무작위 합성 daemon SHA와 `synthetic-review` project만 사용했다.
다른 스레드의 busy, 다른 프로세스의 busy, 정상 close 뒤 fresh instance 획득,
open handle을 유지한 채 소유 helper가 정상 종료했을 때 abandoned 거부,
그 거부 경로의 release/close 뒤 fresh 획득을 확인했다. 숨김 Python helper 2개는
정상 종료했고 잔존·강제 종료는 0이었다. 원래 daemon/project 잠금은 사용하지 않았다.
최종 source SHA는 `537144abfd8260a0c87e31321c414061a5ab12750e4d7a0f511547cd6d761848`이며
독립 실제 커널 검사 전후 동일했다. 합성 커널 자원 검사는 새 애플리케이션 환경이 아니다.

## 본래 환경과 기록

독립 담당은 정상 기록 추가 전에 보호 대상 83테이블의 새 compact count/digest 기준선을
확보하고 기존 19개 동결 보고서의 exact version을 확인했다. ISSUE-00013은 open revision 20이었다.
별칭 gate frozen revision 1·receipt 0, 접근 전환 4테이블 0, 개인 Asset READY·RAG 색인 queued 1,
active 32/pending 128, 대화 5개/23턴/선택 4턴과 기존 파일·환경·runner·서버 실행을 보존했다.

이 문서는 기존 owner의 정상 관리 API로 exact v1을 등록하고 진행 사건·문서 연결만 추가한다.
기존 status·remaining·업무필드·옛 사건·문서 버전은 변경하지 않는다. 등록 이후의 독립 보존
검증과 문서 ID·SHA는 WORKBOARD에 별도로 기록한다. 동결된 본문을 사후 수정하지 않는다.

이번 실행에는 원래 mutex·Docker/WSL/PC 제어, credential/TLS 발급, migration, gate 해제,
실제 파싱·임베딩·색인, 모델/provider 호출, 서버 재시작, staging/commit/push가 없다.
주 구현과 fake/native 합성 테스트, 정상 문제 이력 기록은 서로 구분한다.

## 구현 선택과 남은 작업

현재 primitive는 동기식으로 유지했다. 고정 command executor가 없는 단계에서 전용 actor와
작업 queue를 추가하지 않았다. 향후 async controller는 한 소유 스레드에 호출들을 배치해야
하며 호출마다 threadpool에 보내면 안 된다. 이 선택이 맞지 않으면 async adapter 연결 단계에서
owner actor를 추가해야 한다. primitive에는 일반 callback·shell·command submission을 넣지 않았다.

등록의 poison 범위는 `(이름, Thread)`다. 다른 스레드나 프로세스가 clean mutex를 얻더라도
이전 실행의 정상 종료나 durable takeover가 증명되는 것은 아니다. 프로세스 전체 poison을
추가하는 대신 미확정 execution/action/job의 재개 차단은 향후 durable journal에서 검증한다.
이 판단이 잘못된 채 연결되면 과거 미정산 실행을 재개할 수 있으므로, journal 없이 실제
CutoverControlPort에 연결하거나 획득 결과를 종료 증거로 쓰지 않는다.

Global namespace는 협조하는 Windows 세션 사이의 직렬화다. DACL 보안 fence나 악성 동일
사용자/관리자 차단을 제공했다고 주장하지 않는다. [Microsoft mutex 계약](https://learn.microsoft.com/en-us/windows/win32/sync/mutex-objects)에
따라 스레드 소유권과 재귀 획득을 처리했다.

아직 실제 CutoverControlPort를 조립하지 않았다. 동일 잠금 아래 고정 명령 제출·자식/Job/daemon
submission/result journal, 영속 execution 소유권, 과거 제어의 authoritative settlement 또는
실제 capability fencing, secured forward repair와 전체 route/volume 보존 검증이 남았다.
과거 이력 부재를 새 잠금이나 새 journal로 소급 채우지 않는다. 실제 receipt·exact release·
DB truth parity·queued 색인 READY도 미완료이며 **품질 개선만 남은 상태가 아니다**.
SDK·벡터 저장소 비교·로컬 LLM·Kubernetes 후속 순서는 유지한다.
