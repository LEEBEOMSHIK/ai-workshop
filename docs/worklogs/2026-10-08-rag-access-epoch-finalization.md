# RAG 접근 전환 완료 반환 경계 보완

- 날짜: 2026-10-08
- 관련 문제: ISSUE-00013
- 범위: 승인된 [접근 전환 계획](../superpowers/plans/2026-10-01-rag-access-epoch.md) Task4의 소유권 획득 후 완료 반환
- 결과: generic 코드와 오프라인 검증 보완. 실제 native 제어·과거 종료·전환·별칭 복구·색인은 미실행

## 원인과 수정

직전 소유권 보완은 mark_verified 전까지 검사했지만, 저장 이후 최종 readback·완료 반환에는
같은 검사가 빠져 있었다. 실제 repository와 유효한 합성 v2 closure fixture로 실행하면
소유권을 잃어도 현재 controller가 verified를 반환하고 collector가 새 proof를 발급할 수 있었다.
마지막 readback의 execution/generation 불일치와 active acquire 후 completed 반환도 재현했다.

소유권을 획득한 controller의 모든 fresh readback을 _owned_readback으로 모았다.
이 helper는 정확한 prepared binding·영속 executor generation·기존 action을 대조한 뒤
현재 포트의 소유권을 await 검사하고 결과를 반환한다. mark_verified 뒤에도 먼저 소유권을
재검사하고 이 helper를 거친다. active 호출의 completed shortcut도 동일한 경계를 따른다.

실패한 현재 호출은 새 proof를 반환·등록하지 못한다. 이미 정당하게 저장된 verified/floor는
되돌리지 않고 operation open·gate frozen·receipt 없음이 유지된다. 재접수는 정확한 상태를
읽어 처리한다. 소유권 획득 전의 기존 verified/receipted 읽기 전용 재접수는 유지했다.
새 DB 구조·proof 형식·CLI·credential·runtime 설정은 바꾸지 않았다.

## 테스트와 한계

기존 공식 backend .venv, backend cwd, 자식에서만 AI_WORKSHOP 설정을 제거한 pytest를 사용했다.
repository와 collector/controller는 실제 제품 클래스이며 SQL·제어·backend port만 fake다.
이 테스트를 물리 DB commit 경합이나 실제 Windows/Docker 종료 증거로 확대하지 않는다.

| 검사 | 실제 결과 |
| --- | --- |
| 최초 mark/readback 소유권 상실 RED | controller/collector 4 failed, 28 deselected, 2.81초 |
| generation/binding/active completed 포함 RED | 10 failed, 28 deselected, 5.97초 |
| 구현 중 검사 helper 위치 오류 | 15 failed, 23 passed, 8.90초. 기존 assertion 본문 아래로 helper 위치 교정 |
| 위치 교정 후 local 회귀 | 38 passed, 8.28초 |
| 정상 proof 발급·읽기 전용 재접수 추가 후 전체 indexing 회귀 | 477 passed, 1 warning, 29.00초, exit0 |
| 수정 source/test Ruff | All checks passed, exit0 |
| 수정 source Mypy | Success: no issues found in 1 source file, exit0 |
| 독립 local/repository 회귀 | 46 passed, 10.92초, exit0 |

10개 음성 사례는 mark 직후·final readback 중 소유권 상실, final generation·binding 불일치,
active completed readback 중 소유권 상실을 controller와 collector 각각으로 검증했다.
정상 소유자 및 미리 verified된 읽기 전용 재접수 2개 양성 사례는 실제 proof 발급과 public
revalidate 성공을 확인한다. 실패 사례는 public revalidate 거부 및 durable verified 보존도 확인한다.

독립 보안·코드 리뷰는 같은 real repository/fake closure 반례로 새 proof 발급을 재현하고
수정·기존 계약을 별도로 검토했다. 최종 범위에 남은 차단 finding은 없으며 독립 회귀는
local/repository 46개, 10.92초, exit0이다. 실제 OS/DB 경합 증거로 확대하지 않는다.
경고 1건은 기존 FastAPI TestClient의 httpx 지원 중단 예정 경고이며 의존성을 변경하지 않았다.
전체 저장소 테스트나 실제 RAG 답변·속도·품질 검증은 수행하지 않았다.

## 본래 환경과 이력

정상 기록 전 독립 fresh baseline으로 현재 보호83테이블 전체 행 수·compact SHA,
18개 동결 보고서 exact v1, ISSUE-00013 open revision18 업무 필드·다른 문제 전체 행을 확인했다.
이전 마감의 filtered digest와 현재 전체 digest를 구분하며 큰 row multiset·본문·계정 목록을
복제하지 않았다. baseline 쓰기·provider/native/서버 변경은 0이다.

별칭 open1·frozen revision1·receipt0, 접근 전환4테이블0, 개인 Asset ready·색인 queued1,
활성32/pending128, 기존5대화23턴/선택4턴, 환경·runner·API/frontend 프로세스 시작·경로·
원본 및 개인 파일 보존을 확인했다. 이번 코드는 실제 native 복구 경로에 반영·실행한 것이 아니다.

새 exact v1 문서·진행 사건·링크만 정상 owner 관리 API로 등록하고, 기존 업무/status/remaining과
사건·문서 버전은 덮어쓰지 않는다. 등록 후 문서 ID·revision·최종 보존/health 검증은 WORKBOARD에
남기며 이 동결 본문은 수정하지 않는다. 제품1·test1·ADR·WORKBOARD·본 기록의 수정과
실행 환경 무변경을 구분한다. staging/commit/push, schema/gate/proof/credential 변경,
실제 모델 호출·파싱·임베딩·색인·서버/Docker 제어는 수행하지 않았다.

## 다음 작업

현재 검사는 generic 포트 계약이다. 실제 Windows held session과 실제 submission 직렬화,
과거 executor·child·daemon 명령의 definitive settlement 및 secured forward repair는
구현·입증하지 않았다. 과거 무계측 구간은 새 journal·현재 PID/TCP·token이나
단순 PC/Docker 재시작 성공으로 채우지 않는다. 기존 IDE·Codex·frontend 보존 조건을 유지한다.

실제 종료/fencing 경계와 자료·큐 보존/복구 절차를 구체화하고 native controller·secured
관찰·복구 CLI를 완성한 뒤, 실제 receipt·exact release·fresh parity·예약 색인 READY를
본래 환경에서 검증해야 한다. 현재 쓰기 차단과 queued 색인은 유지되고 품질 개선만 남은 상태가 아니다.
Kubernetes 학습·실습은 등록한 후속 범위로 유지하며 현재 복구 절차를 대체하지 않는다.
