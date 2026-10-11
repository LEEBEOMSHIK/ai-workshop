# RAG 접근 전환 제어 소유권 검증 보완

- 날짜: 2026-10-08
- 관련 문제: ISSUE-00013
- 범위: 승인된 [접근 전환 계획](../superpowers/plans/2026-10-01-rag-access-epoch.md) Task4의 generic ownership 계약 보완
- 결과: 코드·오프라인 회귀·독립 리뷰 완료. 실제 별칭 복구·전환·색인은 미실행

## 문제와 변경

기존 controller는 acquire 결과의 execution UUID만 확인했다. 독립 fake 반례에서도 같은
execution을 가진 잘못된 generation·control port가 stop 동작을 진행했고, repository가 현재
DB generation을 action에 붙이므로 executor가 이를 그대로 복사하면 정산 검사를 통과할 수 있었다.

기존 execution의 영속 executor_generation을 readback에 노출했다. 새 DB 구조나 generation을
만들지 않는다. ControlOwnership은 execution UUID·canonical UUID generation·control-port UUID를
가지며 controller 생성 때 포트 UUID를 고정한다. acquire에 기존 execution·generation을 전달하고,
typed token·fresh readback·기존/신규 action의 execution·generation을 정확히 대조한다.

포트는 assert_owned를 제공하고 expected·execute·reconcile에 동일한 token을 전달받는다.
assert 전후와 expected 이후, 예약 이후/실행 이전, execute·reconcile 이후/정산 이전,
최종 관찰 이후/anchor 이전, anchor 이후/verified 저장 이전에 소유권을 검사한다.
예약 뒤 소유권 상실은 pending으로 남고 uncertain action은 재실행하지 않는다.
acquire·assert_owned의 원시 오류 본문은 고정 rag_alias_proof_invalid로 제한한다.
그 밖의 포트·backend 예외 처리까지 변경한 것은 아니다.

독립 리뷰에서 acquire 대기 중 다른 실행이 완료하면 관찰·anchor를 반복할 수 있는 경계도 발견했다.
validated fresh readback이 verified 또는 receipted이면 즉시 반환하도록 보완했다.
실제 repository와 fake SQL transport를 사용해 action이 없는 경우와 모두 settled인 경우를 검증했다.

## 검증 근거

모든 단위 실행은 기존 공식 backend .venv, backend 작업 디렉터리에서 수행했다. AI_WORKSHOP 설정은
테스트 자식에서만 제거하고 외부 DB·Docker·네트워크·모델 대신 기존 fake port를 사용했다.
별도 애플리케이션 환경·DB·계정은 만들지 않았다.

| 검사 | 실제 결과 |
| --- | --- |
| 최초 ownership/readback RED | 6 failed, 3 passed, 3.99초. 누락 generation/잘못된 port 허용 및 readback 누락 재현 |
| acquire 중 port 변경 RED | 1 failed, 1 passed, 2.64초 |
| 예약 후 assert 중 port 변경 RED | 1 failed, 2.44초. pending인데 동작이 제출되는 결함 재현 |
| 완료 경합 RED | verified/receipted 2 failed, 3.35초 |
| 최종 전체 indexing 단위 회귀 | 465 passed, 1 warning, 59.62초, exit0 |
| 수정한 source 2개·test 1개 Ruff | All checks passed, exit0 |
| source 2개 Mypy | Success: no issues found in 2 source files, exit0 |
| 독립 local/repository 회귀 | 26 passed, 10.63초, exit0 |
| 독립 설계·보안·코드 리뷰 | generic ownership 범위의 남은 차단 finding 없음 |

독립 26건은 최종 제품 코드에서 실행했으며 이후 추가한 settled 완료·foreign reservation·invalid
generation 테스트는 메인의 전체 indexing 465건 실행에 포함됐다. 독립 검증 건수를 확대하지 않는다.
경고 1건은 기존 FastAPI TestClient의 httpx 지원 중단 예정 경고다. 의존성은 변경하지 않았다.
전체 저장소 테스트·실제 committed 경합·실제 native 제어 증빙으로 확대하지 않는다.

## 본래 환경 보존과 이력

정상 이력 기록 전 독립 fresh baseline으로 현재 보호83테이블 전체 행 수·compact SHA를 확보했다.
이전 마감의 filtered digest와 이번 현재 전체 digest를 구분해 대조했고, 기존17개 동결 보고서의
exact v1 및 원문 바이트·SHA를 확인했다. 큰 row multiset이나 원문 본문·계정 목록은 저장하지 않았다.

ISSUE-00013 open revision16과 기존 업무 필드·다른 문제 행, 별칭 open1/frozen1 revision1/receipt0,
접근 전환4테이블0, 개인 Asset ready·RAG 색인 queued1, active32/pending128,
5대화23턴/선택4턴, 환경·runner·기존 API/frontend 프로세스·원본 및 개인 파일 보존을 확인했다.
baseline 자체의 DB/API 쓰기·모델 호출·서버 변경은 0이다.

이 보고서는 기존 owner의 정상 관리 API로 새 exact v1 문서와 ISSUE-00013 진행 사건·링크만
등록한다. 기존 업무/status/remaining과 사건·문서 버전은 덮어쓰지 않는다. 등록 후 독립 마감의
문서 ID·revision·보존 비교·health 결과는 WORKBOARD에 기록하며 이 동결 본문은 수정하지 않는다.

제품 변경은 access_epoch_local.py와 access_epoch_repository.py, 테스트는 test_access_epoch_local.py다.
ADR-0033·승인 계획·WORKBOARD 및 본 기록을 함께 갱신했다. 제품 파일 수정과 실행 환경 무변경을
혼동하지 않는다. staging·commit·push, migration, credential/TLS 생성, Docker/서버 제어, gate/proof
변경, 실제 파싱·임베딩·색인과 provider 호출은 수행하지 않았다.

## 남은 기능 경계

이 변경은 소유권을 요구하고 검사하는 generic 계약이다. 실제 Windows mutex·자식/daemon 작업
기록·단일 held control session을 구현하거나 과거 종료를 입증한 것이 아니다. assert 직전 검사만으로
check와 실제 submission 사이의 경쟁을 막을 수 없으므로 native 포트가 같은 held ownership 안에서
직접 검사·제출·재조정을 직렬화해야 한다. backend 관찰·anchor도 그 제어 세션을 보존해야 한다.

과거 uninstrumented 제어 명령의 definitive settlement 증거가 없어 실제 복구는 계속 차단돼 있다.
다음은 기존 IDE·Codex·프론트를 보존하는 native 제어 절차와 과거 제어 fencing/종료 경계,
secured forward repair 계약을 구체화하는 작업이다. 실제 전환을 위한 자료 보존·복구 절차를
검토하기 전에는 gate를 SQL로 해제하거나 원래 ES/PC/Docker를 재시작하지 않는다.
실제 receipt·release·fresh parity·예약 색인 READY 및 다른 남은 기능 검증은 완료되지 않았고,
아직 품질 개선만 남은 상태가 아니다.
