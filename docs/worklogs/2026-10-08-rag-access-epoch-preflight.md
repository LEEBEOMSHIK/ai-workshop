# 서버 접근 전환의 읽기 전용 사전검사 구현

2026-10-08 KST, ISSUE-00013. 기존 개인 첨부의 색인 예약을 진행하기 위해 별칭 복구 경계를 재개했다. 메인은 본래 환경 진단·구현·운영 확인, 독립 담당은 설계/보안/코드 리뷰와 자료 보존을 맡았다. 기존 승인된 [접근 epoch 설계](../superpowers/specs/2026-10-01-rag-access-epoch-design.md)와 [구현 계획 Task4](../superpowers/plans/2026-10-01-rag-access-epoch.md)를 기준으로, 실제 변이 작업을 포함하지 않는 사전 관찰 부분을 구현했다.

## 이번에 구현한 기능

`access_epoch_native.py`의 OriginalAccessEpochPreflight와 기존 로컬 CLI의 `preflight-access-epoch` 명령을 추가했다. 기존 OWNER의 operation preview 권한을 확인한 뒤 고정 Docker context/daemon/container 읽기3회, 로컬 ES 정보/health/node 상태 GET3회로 원래 배포를 관찰한다. 기존 이미지와 named volume의 식별 기준은 [원래 실측 기록](2026-10-02-rag-access-epoch-implementation.md)이다.

v1 `preflight`와 복구·claim·receipt·해제 계약은 유지했다. v1의 전체 client 종료 검사나 daemon 전체 running container 배제를 v2에 재사용하지 않았다. IDE·Codex·frontend를 종료하지 않고, 별도 DB·계정·환경도 만들지 않았다.

관찰이 정상이어도 결과는 항상 blocked·termination_proven=false·historical_control_settlement=unknown·route_verification=not_performed·parity=not_run이다. 이는 원래 이미지/저장 mount/실제 단일 ES 노드의 제한된 현재 관찰이다. 독점 volume 사용, 전체 ingress, 과거 제어 명령의 완료, 실행 가능한 native cutover를 증명하지 않는다. 새 proof·epoch·credential 생성이나 acquire/recover/release·Docker STOP/START는 호출하지 않는다.

## 오류 경계와 검증

신규 기능 테스트의 RED는 모듈/명령 미구현으로10실패·기존45통과였고 구현 뒤55통과였다. 독립 리뷰에서 observer dict 전체 병합이 원래 operation/snapshot을 덮어쓰거나 임의 필드를 출력할 수 있음을 확인했다. 재현1실패를 확인한 뒤 허용된 진단과 엄격한 boolean만 받아들이고 권한·snapshot·차단 상태는 CLI에서 고정하도록 수정했다.

주입 포트의 일반 예외/LocalRecoveryRefusal이 raw 진단으로 새는 방어 경계도2실패로 재현한 뒤 안전한 고정 진단으로 정규화했다. OWNER의 preview 권한 거부는 이 catch 밖에서 유지한다. 원문·Config.Env·secret marker·원시 오류는 결과에 포함하지 않는다.

최종 관련4개 파일 회귀는 **193통과**(32.56초), scoped Ruff 및 제품2파일 Mypy가 통과했다. 독립2개 단위 파일은 **58통과**(6.82초), 최종 읽기 전용 구현에 차단 지적이 없다. 단위 테스트는 합성 설정·fake DB/native/ES 경계이며 본래 DB 전환 성공으로 확대하지 않는다. 전체 저장소 회귀를 재실행한 결과도 아니다.

## 본래 환경 관찰

2026-10-08 02:14:39 UTC(11:14:39 KST)에 기존 frozen claim의 정상 preview·새 사전검사·status 경로를 실행했다. 파일·계정·설정·서버를 바꾸지 않았다.

| 항목 | 실제 결과 |
| --- | --- |
| 원래 이미지·named volume·실제 단일 ES 노드 관찰 | deployment_observed=true |
| 새 사전검사 | blocked / historical_control_settlement_unknown |
| 과거 제어 명령의 확정 종료 | unknown |
| 전체 ingress 검증 | 미수행 |
| 기존 operation / gate | legacy_unknown / open / frozen revision1 |
| 복구 receipt / 접근 epoch·execution·event·floor | 모두0 |
| 명시적 parity / 서버 재시작 / 모델 호출 / DB 변이 | 모두0 |

검사 전후 exact claim의 status는 같다. 앞선 v1 사전검사도 host_ancestor_reparse로 차단됐으며 그 검사로 Node 링크를 허용하거나 실제 종료를 주장하지 않았다. OS의 현재 boot 시각을 조회했지만 특정 과거 명령·guest/daemon 실행의 완료 proof로 사용하지 않았다.

첫 운영 도구의 테이블명 두 개가 실제 이름과 달라 존재 조회가NULL이었다. 실제 이름 `rag_access_epoch_executions/events`로 정정한 후 네 epoch 테이블 모두 존재/count0을 확인했다. NULL을 migration 미반영의 증거로 쓰지 않는다.

독립 compact 기준선은 기존83테이블 전체 행 SHA를 직전 최종 검증과 정확히 대조한 뒤 count/정렬 SHA aggregate만 저장했다. 큰 row multiset 복제 없이22KB다. 동결16보고서 exactv1, 기존5대화23턴·선택4턴, ISSUE2 implementedr6/3 implementedr4/5 openr69/13 openr14의 fresh 업무/status/remaining, 환경/Codex0.161.0·기존 API/frontend 시작/경로, active32/pending128·개인 파일ready/queued색인1과 실제 원본 바이트를 보존했다. 직접/프론트 경유 health·ready4GET200이며 독립 DB/API 쓰기·provider·프로세스 변경0이다.

새 보고서의 정상 이력 등록 후 compact 독립 최종 대조는 Workboard에 별도로 기록한다. 증거와 독립 리뷰는 `.local-data/project-agent-work/rag-alias-recovery-resumption-20261008/`에 있으며 비공개 원문·계정·비밀값은 이 보고서에 저장하지 않는다.

## 실제 복구에 남은 문제

과거 제어 명령의 complete settlement 자료는 발견되지 않았고, 지금 새 journal을 만드는 것으로 과거 unknown을 완료로 바꿀 수 없다. 현재 계약을 그대로 유지하면 이 증빙 공백이 실제 cutover를 차단한다. native controller의 executor generation/control-port 소유권 결속과, 최초 보안 전환 후 정상 secured 재시작의 forward repair도 아직 구현되지 않았다. 이번 사전검사 성공은 해당 계약·어댑터의 구현이나 실제 별칭 복구 완료가 아니다.

다음은 기존 도구 실행을 보존하는 제어 경계 설계와, PC/Docker 재시작 절차를 포함한 유지보수 설계 중 허용할 범위를 구체화하는 것이다. 사용자에게 설계 범위 선호를 확인 중이며 실제 재시작 절차를 승인받거나 실행한 것으로 간주하지 않는다. 답이 없으면 기존 IDE·Codex·frontend 보존 조건을 유지한다. 어떤 방안도 종료 proof·복구 receipt·exact release·새 정상 parity·원래 자료/큐 보존 검증을 대신하지 않는다.

개인 첨부는 Platform ready이며 RAG projection pending·job queued·dispatch pending 각1이다. 실제 파싱·임베딩·색인은 대기 상태를 유지한다. 실모델 실패/취소/timeout·committed 경합·DLL·Git 인계도 남아 **아직 품질 개선만 남은 상태가 아니다.** ISSUE-00013에 새 보고서 exact DBv1과 진행 사건을 연결하고 기존 status/remaining·업무 필드·사건/문서 연결을 보존한다. DB 등록 후 이 보고서는 동결한다.

제품2파일·테스트2파일·ADR·실행서·작업 기록은 이번 변경이며, API/worker/beat/ES 재시작·TLS/키 발급·schema·gate 변경·staging/commit/push0이다.
