# RAG 접근 epoch 구현 및 기존 제어 이력의 증빙 공백

- 날짜: 2026-10-02
- 상태: 부분 구현·오프라인 검증 중. 원래 환경 배포·종료·해제 미실행
- 문제: ISSUE-00013
- 설계: [접근 epoch 계약](../superpowers/specs/2026-10-01-rag-access-epoch-design.md)
- 계획: [6개 작업](../superpowers/plans/2026-10-01-rag-access-epoch.md)
- 결정: [ADR-0033](../decisions/0033-rag-access-epoch.md)

사용자가 계획과 현재 세션 직접 구현을 승인했다. 기존 main 작업 공간에서 이전 변경을 보존하면서 구현했다. 별도 앱 환경·DB·계정·worktree를 만들지 않았다. 실제 migration·인증서·비밀번호·키 생성·컨테이너 전환·gate 변경은 승인하거나 실행하지 않았다. 이번 기록은 전체 기능 완료나 배포 준비 완료를 뜻하지 않는다.

## 구현한 범위

- 엄격한 v2 proof, 원래 v1 receipt와의 합집합 디코더, 정확한 claim·epoch·execution·manifest 연결을 추가했다. 숫자와 bool, UUID·UTC 표기, 저장소 ID 문법을 구분한다.
- 영속 epoch·execution·append-only action event·floor 모델과 저장소 및0062 migration 초안을 추가했다. 외부 명령은 먼저 예약을 commit해야 하며 pending/unknown을 재발행하지 않는다. verified 상태 문자열만으로 종료를 확정하지 않고 고정 명령 전체와 실제 종료·퇴역 manifest를 대조한다.
- v2 receipt·작업 폐쇄·epoch receipted 전이를 같은 DB 트랜잭션에서 처리하는 서비스 경로와 정확한 재조회/재호출을 추가했다. release·새 parity는 자동 실행하지 않는다.
- 공개 HTTPS/CA/epoch 설정과 실제 ES client capability를 분리했다. 키 없는 DB-only 설정은 허용하지만 ES client 생성은 거부한다. 실제 client는 명시적 프로젝트 CA, IP SAN을 포함한 hostname 검증, immutable startup key를 사용한다.
- CurrentUser DPAPI·owner/SYSTEM 보호 파일과 단조 floor anchor, 등록 서비스 실행기를 추가했다. 새 자식만 시작 환경에 키를 받으며 부모 환경을 수정하지 않는다. venv redirector와 실제 자식의 PID·생성 시각을 구분한 Hello→보호된 허가→인증→ACK 경로를 작성했다. 이 native 경로의 실제 프로세스 실행은 검증하지 않았다.
- API lifespan/별도 readiness, Celery worker/beat 및 RAG task admission을 연결했다. floor·anchor 불일치를 차단한다. 기존 health는 liveness이며 색인 정상성을 뜻하지 않는다.
- 고정 controller/collector의 도메인 조정, namespace별 권한, 경로·색인 보존 관찰 검증을 추가했다. 실제 Docker cutover adapter·secured Compose·완성된 CLI 연결은 구현 완료하지 않았다.

등록 앱 시작은 accepting-JVM 종료 명령 목록에서 제외하고 보호된 anchor와 verified DB floor가 모두 확정된 뒤 별도로 처리한다. 이를 앞서 실행하면 startup admission 자체와 충돌한다. action reservation 순번과 실제 settlement append 순번도 구분한다.

## 독립 검토와 수정

메인 구현과 별도 보안/DB 검토자가 전체 WIP 범위를 읽었다. 최종 기능 승인은 아니다. 다음 실제 결함을 수정했다.

1. `_security/_authenticate`의 `api_key`에는 임의 key metadata가 없다. 보호된 launch record의 key ID와 실제 인증 유형을 비교하도록 수정했다. epoch/role/key ID 연결은 보호된 실행 기록과 linked credential manifest로 확인한다. [공식 응답 스키마](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-security-authenticate)에 맞춘 회귀 테스트가 수정 전 실패하고 수정 후 통과했다. 앱 키에 보안 관리 권한을 추가하지 않았다.
2. nullable `receipted_at`의 SQL 비교가 UNKNOWN으로 빠지는 문제를 명시적 NULL 거부와 `IS DISTINCT FROM`으로 수정했다.
3. verified floor의 stable node 일치 검사를 추가했다.
4. ORM의 v1-only receipt 제약과 누락된 epoch/execution linkage를 migration과 맞췄다. 새 nullable linkage는 deferred/server-default NULL/eager-defaults disabled로 기존 v1 조회·삽입의0061 경로를 유지한다. 실제 원래 SQL 확인은 아직 하지 않았다.

proof/서비스/저장소/권한/관찰/launch/startup 테스트는 실제 클래스와 SQL·OS·ES·crypto 경계 fake를 사용한다. native ACL 구조 검증은 추가 characterization이며 실제 host ACL 변경이나 DPAPI 실행 성공으로 보고하지 않는다. Celery test 모드의 epoch 없는 eager 단위 실행은 원래 deployment가 없으므로 live DB admission을 하지 않는다. epoch를 설정한 테스트와 local 실행은 검증 경계를 유지한다.

## 기존 제어 이력의 설계 차단 요소

승인된 계약은 이전 v1 collector·restore·Compose 명령과 자식 및 daemon delegation이 모두 확정적으로 종료/완료됐다는 증빙을 요구한다. 현재 고정 역사 자료는 그 조건을 충족하지 않는다.

- v1 `HISTORY_FILES`는 과거 원래 환경 출처, ES identity와 배포 작업 기록이다. 이후의 모든 명령 submission/child/daemon 결과를 열거하지 않는다.
- `NativeCommandExecutor.run`은 timeout을 가진 `subprocess.run`이며 각 호출의 durable submission/result를 남기지 않는다.
- 앱 PID/생성 시각 registry는 앱 실행 이력이고 Docker 위임 명령 전체의 완료 이력이 아니다.
- 기존 `local-history-assessment.md`도 배포 출처와 per-invocation 증빙을 구분한다.

새 journal은 앞으로의 명령만 기록할 수 있다. 과거에 없던 완료 증빙을 만들어낼 수 없으며, 현재 PID/TCP/컨테이너 부재나 과거 자료 재해시로 이를 대신하지 않는다. 이 문제 때문에 실제 native 전환을 실행 가능한 것으로 표시하거나 CLI에 연결하지 않았다. 종료 계약을 완화하거나 SQL로 gate를 풀지 않았다.

후속은 **계측되지 않은 과거 구간을 끝내는 검증 가능한 제어 경계 설계**다. Docker daemon/실행 VM의 실제 종료 경계를 포함하는 방안을 검토할 수 있지만, 정확한 retry 가능한 client/supervisor·위임 작업 종료, VM/daemon 새 실행 식별, 원래 데이터·큐 보존과 재기동 순서를 먼저 설계해야 한다. 단순 Docker 재시작 성공이나 operator 확인 boolean은 proof가 아니다. 이 후속은 승인된 계약을 실제로 구현하기 위한 추가 결정이며 현재 확정·승인된 실행 절차가 아니다.

## 실제 읽기 전용 조사

코드/검토만으로 원래 환경 완료를 보고하지 않기 위해 Docker에서 다음 비밀 없는 값만 재조회했다. 비밀번호·환경 전체·문서 본문·키·명령 secret output을 조회/출력하지 않았다.

| 항목 | 관찰 |
| --- | --- |
| 원래 ES ID | `c890380a5e6f21beb7692c78594fac5aeb84baee22cb0f6e8ba421442b5e58d6` |
| 원래 이미지 ID | `sha256:80d3ab189f131fca45c958c281975078ac88d8b133200fbae33d70baa40f4654` |
| 실제 named volume | `ai-workshop_elasticsearch-data` |
| 실행 상태 | running, StartedAt `2026-09-29T01:02:21.718672132Z` |
| 같은 daemon 컨테이너 | 총12개, 원래 Compose project label 3개 |
| project label 밖 컨테이너 | 9개, 현재 모두 정지, restart policy `no`/`unless-stopped` |

첫 조사에서는 이름 prefix로 범위 밖6개를 셌고, 추가 `Config.Labels` 조사에서 project label 밖9개·running0으로 정정했다. label이 다른 경우와 없는 경우를 원래 프로젝트 자원으로 추정하지 않는다. 현재 정지된 자원도 daemon/VM 재시작의 자동 시작·정지 상태 보존 대상이다. 전역 재시작은 원래 ES만의 재시작으로 볼 수 없으며 새 환경을 만들거나 다른 자원을 정리하지 않는다. 프로젝트 Redis 선언은 AOF+named volume이지만, 실제 durability·미완료 flush·큐 보존을 확인하지 않았으므로 선언만으로 재시작 시 큐 보존을 단정하지 않는다.

## 검증과 남은 작업

최종 전체 단위 **3,369 통과·6 skip**, Mypy **397 source 파일 통과**, 전체 Ruff 통과. 기존 Starlette/httpx deprecation warning 1개는 유지하며 의존성을 임의 업그레이드하지 않았다. backend cwd의 새 Python 자식에서 상속 AI_WORKSHOP 설정을 제거하고 합성 secret·UTF-8·새 프로젝트 내부 짧은 test temp 경로를 사용했다. 실제 원래 `.env`/DB/ES는 단위 검증에 사용하지 않았다.

첫 전체 실행은 합성 secret 설정 누락 및 Windows Temp ACL로 실패했다. 두 대표 실패는 새 프로젝트 내부 경로를 사용한 unsandboxed 단위 검증에서 통과했다. 이후 깊은 임시 경로 때문에 Windows 경로 길이 문제가 발생했고, 실제 worker eager 테스트에 잘못 들어간 live admission도 수정했다. 테스트의 원래 `.env` 로딩·실제 DB 연결로 이 문제를 우회하지 않았다. 새 test temp는 이 작업의 진단 산출물이며 다른 프로젝트의 캐시·Docker 산출물을 제거하지 않았다.

[inline 실행 규칙](C:/Users/bumci/.codex/plugins/cache/openai-curated-remote/superpowers/6.4.2/skills/executing-plans/SKILL.md)은 “a plan so broken that every path forward is a guess”를 중단 조건으로 둔다. 여기서는 필수 historical settlement의 실제 증빙 원천이 없다는 독립 검토 결과에 적용했다. 이는 그 규칙의 적용 판단이며 사용자 데이터 보존·새 환경 금지·실제 전환 별도 승인 조건을 바꾸는 승인이 아니다. 계약에 없는 완료 추정이나 전역 Docker 재시작을 구현·실행하는 대신 증빙 경계의 추가 결정을 남긴다.

원래0062 적용/SQL 제약·경합/실제 native launch/제어 종료/인증서·키/전체 ingress/색인 및 자료·큐 보존/실제 v2 receipt/해제/현재 DB 기준 새 parity는 **미실행·미검증**이다. 신규 실패 실제 저장, 원래 첨부·모바일 흐름, 문제 DB의 exact 문서 연결과 main/원격 인계도 남아 있다. 관리자 재로그인 전에는 문서 링크가 DB에 저장됐다고 보고하지 않는다. 아직 품질 개선만 남은 상태가 아니다.
