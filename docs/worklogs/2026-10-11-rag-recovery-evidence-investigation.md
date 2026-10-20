# RAG 별칭·과거 취소 복구 근거 조사

사용자의 기능 마감 후속 요청에 따라 두 차단을 원본 DB 메타데이터와 현재 코드에서 추적했다.
이번 작업은 조사와 문서화다. 새 제품 결함을 재현하거나 운영 복구를 완료하지 않았다.
앞선 [기능 확인](2026-10-11-rag-functional-closure-check.md)의 “기존 정식 복구”는
활성 대화의 과거 취소에 대해서는 정정한다. 현재 지원 API/CLI가 없다.

## 직접 확인한 원본 상태

원래 `.env`의 로컬 DB에 READ ONLY·5초 statement timeout·COMMIT 거부를 적용하고
SELECT 후 rollback했다. 질문·응답·문서 본문·비밀값은 조회하지 않았다.

- schema: `0063_rag_numeric_proof`. 저장소에 0064가 있어도 적용하지 않았다.
- 별칭 operation `f61a8fde-5a88-4690-be51-56e8f14ae696`: `open/legacy_unknown`,
  생성 시각 2026-09-20 14:27:26 UTC. gate는 frozen/revision1,
  request `09e0ee10-b5ac-4ace-a053-deafb20ec4ef`, receipt0.
  현재 operation snapshot SHA가 gate의 SHA와 일치했다. access epoch/execution 각0.
- 대화 `fea91839-4107-469d-9aef-7543b1f78d68`, revision3, 삭제되지 않음.
  첫 turn `bc10a519-62b6-4adf-8dac-de1a58011139`가 `cancelled`,
  `execution_terminated=false`, `conversation_cancelled`다.
  생성 2026-10-04 17:07:55 UTC, 마지막 변경 17:09:03 UTC.
- 연결 execution `146c3bc3-5567-4316-ad70-85b089667430`는 cancelled/complete=false.
  이 execution_id에 연결된 generation audit0, 당일 17:07~17:15 UTC Codex stage audit0,
  현재 Codex 실행 슬롯0이다. 좁은 시간대 조회는 모든 역사 감사의 부재를 증명하지 않는다.

## 별칭: 실제 지원 경로와 필요한 증거

| 경로 | 코드가 요구하는 것 | 현재 결론 |
| --- | --- | --- |
| reserved 복구 | dispatch 전 phase와 정확한 claim CAS | 실제 phase가 legacy_unknown이므로 부적합 |
| v1 통제 재시작 | 원본 이력·동일 배포·전체 client 부재, 동일 ES의 실제 stop/start·새 JVM, 재검증 | 구현돼 있으나 현재 preflight를 통과하지 못함 |
| v2 access epoch | 과거 control 정산, 소유권/보안 전환/새 권한 경계, 최종 native 검증 | 기반만 구현, 현재 즉시 실행 가능한 완성 경로가 아님 |

`alias_recovery_cli.py:296-310,367-391`의 recover는 v1 collector를 조립한다.
`preflight-access-epoch`는 읽기 진단일 뿐 v2 복구를 실행하지 않는다.
`AliasRecoveryService.recover_access_epoch()`는 존재하지만 외부에서 주입할 검증 port가 필요하다.
`access_epoch_control_native.py:152,955-969`가 요구하는
`access_epoch_verification_native.NativeFinalVerification` 모듈 파일은 없다.
따라서 “운영 승인만 받으면 v2 복구 가능”이라고 보고할 수 없다.

v1 이력은 `alias_recovery_local_native.py:58-62,1022-1062`의 고정 세 파일이다.
원래 cutover 백업의 `original.env`, `es-identities.json`, 2026-09-20 cutover worklog가
모두 코드의 SHA와 일치했다. 파일 내용/환경값은 출력하지 않았다.
이것은 과거 34개 요청의 source-map과 별개이며 v1을 source-map 부족으로 일괄 차단하면 안 된다.

v1 preflight와 v2 read-only preflight를 원본 snapshot으로 실행했다.
둘 다 `local_command_failed`; v2는 deployment_observed=false, termination_proven=false다.
Docker context 단독 읽기는 exit1/access_denied=true였다.
Windows CIM 프로세스 조회와 `.local-data/access-epoch/private` 열람도 접근 거부됐다.
권한/보호 설정 변경이나 제한 우회는 하지 않았다. 현재 배포 변경 여부·client 부재는 미확인이다.
이것은 이번 실행 환경의 관찰 제한이며 과거에 성공한 preflight를 소급 부정하지 않는다.

v1 종료 proof는 사용자가 작성하는 JSON이 아니다. collector가 claim 재확인 → 원본 이력 →
client 부재 → ES stop 확인 → 동일 배포 start/새 JVM 확인 → 이력/client 재확인 후 생성한다
(`alias_recovery_local.py:92-159`). gate/DB 상태 불명확 시 멈추며 서버가 멈춘 채 남을 수 있다.
단순 재시작 시각·빈 task 목록·현재 별칭 일치만으로 대체할 수 없다.
원본 이력·mount/config/cluster/stable node는 유지돼야 하고 JVM incarnation은 달라야 한다.
v1 host 검사는 미등록 Python/Node 등 client 가능 프로세스를 거부한다
(`alias_recovery_local_native.py:779-788`). 다른 Codex/IDE를 강제 종료해서 통과시키지 않는다.

DB receipt는 위 검증에 성공한 repository가 operation 종결과 함께 발급하는 불변 결과다.
receipt를 미리 수기로 만들거나 gate만 admitted로 바꾸는 복구는 지원하지 않는다.
release는 정확한 receipt readback 뒤 별도 단계이며 실제 alias parity는 그 다음 별도 작업이다.

## source-map: 유실과 미분류의 구분

기존 비공개 작업 자료의 `history-y1-y4-dependency-availability-01-report.md`와
`history-y1-y4-unmapped-dependency-next-plan.md`를 읽었다. 34개 호출/67개 import edge의
`no_approved_source_map`은 진단 도구가 허용한 `ai_workshop.<module>` 매핑에 후보가 없었다는 뜻이다.
실제 reconstruct 호출0, no_add_baseline0이며 원본 파일의 부재/영구 유실을 발견한 결과가 아니다.
호출의 실제 cwd/shell/import resolution도 미확정이다. 현재 설치된 모듈로 채우면 안 된다.

생성 절차는 다음처럼 분리된다.

1. 보호된 `history-recipe.dpapi`는 원본 Codex 세션 prefix의 locator/길이/SHA와
   call_id/shell_indices/supports를 선택한다. reader가 DPAPI를 풀고 원본 prefix를 다시 검증한다
   (`access_epoch_history.py:2827-2910,3493-3535`). recipe 자체가 종료 증거는 아니다.
2. 당시 실행 파일 후보는 해당 호출 이전의 검증된 Add/Update와 성공 ACK·연결된 child 기록으로
   재구성해야 한다. 당시 import 경로와 baseline을 연결할 수 없으면 미확정으로 남긴다.
3. 도구 결과·poll/session chain의 terminal exit와 실제 target support를 연결하고 누락 호출을
   검사한다. 그 결과를 OriginalHistoryGate가 현재 epoch/claim/lock에 묶어 보호 패킷으로 남긴다.
   이 패킷도 자체로 native 실행 권한이나 별칭 recovery receipt가 되지 않는다.

현재 수집 가능한 것은 기존 진단의 정확한 의미·지원 코드·원본 DB 상태·v1 이력 해시다.
보호 recipe/참조 prefix의 존재·복호화·당시 source 결손은 이번 권한으로 확인하지 못했다.
따라서 “영구히 없는 자료”는 아직 확정0이다. 권한 있는 원래 환경에서 실제 결손을 확인한 뒤에도
당시 baseline/실행 문맥/종료 결과가 없다면 그 역사적 사실은 현재 상태로 재생성할 수 없다.
그 경우 proof를 꾸미지 않고 다른 복구 설계를 검토해야 한다.

## 과거 취소: 원인 범위와 복구 최소 단위

`conversations/domain.py:94-98`은 cancelled/종료미확인 turn을 busy로 유지한다.
15분 recover는 running만, cancel API도 running만 처리한다. 재조회·재취소·대기로 풀리지 않는다.
정상 경로는 실행 task join 후 종료 표시/대화 revision을 저장한다(`service.py:404-442`).
`repository.py:232-262`의 record_termination은 삭제 tombstone 전용이다.

2026-10-05 terminal cancellation 수정 기록은 unshielded cleanup/finalization으로
종료 저장이 누락될 수 있던 결함을 재현·수정했고 과거 turn은 backfill하지 않았다고 명시한다.
이번 원본 건의 정확한 당시 중단 지점을 입증한 것은 아니지만 현재 고립 상태와 양립한다.
기존 회귀에서 새 제품 결함은 발견되지 않았다.

정본 [10월 5일 기록](2026-10-05-rag-browser-closure.md)은 바로 이 execution이
retrieval running·일부 미기록이었다고 명시한다. 생성 프로세스가 반드시 시작됐다고 가정하지 않는다.
필요한 증거의 출발점은 이 대화 실행을 소유했던 API/search task와 실제 생성된 자식의
종료 또는 미기동이다. 모델이 실행된 경우에만 아래 Codex 연결도 적용한다.

종료 근거는 turn → execution → generation audit → Codex stage/runner의 정확한 연결이 필요하다.
Codex request_id는 별도 생성되므로 turn.request_id와 같지 않다. correlation/시각만으로 확정하지 않는다.
DB 슬롯에는 PID/Job identity가 없고 Windows Job도 unnamed다. 빈 슬롯/현재 PID 부재는 당시
실행 task 종료나 모든 자식 종료의 증거가 아니다. 연결된 당시 감사 또는 소유 프로세스 수명·
자식 종료를 검증할 수 있는 원래 기록이 추가로 필요하다.

지원 복구 기능은 미구현이다. 근거가 확보되면 별도 최소 설계는 정확한 owner/domain/대화/turn 잠금,
revision3와 cancelled/false CAS, 종료 표시·시각·대화 revision 갱신 및 복구 감사 기록이다.
status/질문/응답은 보존한다. execution.complete=true나 슬롯 삭제를 함께 강제하지 않는다.
관측 완료는 별도 누락 진단이며 종료 표시만으로 모두 완료됐다고 할 수 없다.
복구 전 값을 보존해도 새 turn 접수 후에는 단순 역갱신이 안전한 rollback이 아니다.

## 다음에 필요한 한 묶음과 이후 승인 경계

**지금 필요한 것은 서비스 재시작 승인이 아니라 원래 로컬 실행 담당자가 제공하는 제한된 읽기 증거 묶음이다.**
기존 권한으로 다음을 검증하고 비밀값·원시 session/질문 본문 없이 결과를 전달한다.

- 같은 operation/request/revision/SHA의 현재 v1 preflight 결과와 거부 사유,
  원본 ES identity 및 정확한 등록 client/supervisor의 PID+생성시각·소유 관계.
- 보호 recipe가 원래 reader에서 읽히는지, 참조 prefix의 해시/길이 검증 결과,
  기존 34/67 범위의 당시 source/import 문맥을 연결할 자료가 있는지와 정확한 결손 분류.
  임의로 recipe를 만들거나 전체 세션을 공개할 필요는 없다.
- 위 취소 turn/execution에 정확히 결합되는 API/search task와 실제 생성된 자식의
  당시 종료 또는 미기동 기록. 모델 호출을 가정해 존재하지 않는 모델 종료 증명을 요구하지 않는다.
  없다면 “없음/결합불가”로 보고하고 current PID 목록으로 대체하지 않는다.

이번 조사에서 보호 설정을 풀거나 새 권한을 등록하지 않았다. 접근 거부를 실행 성공으로 바꾸어
표기하지 않았다. 자료 확보 뒤 코드 구현이 필요한 v2/과거 취소 복구는 운영 실행과 분리해 리뷰한다.

실제 운영 승인안은 그때 **정확한 대상과 전제가 검증된 경로 하나**로 좁혀야 한다.
v1이면 해당 등록 writer/supervisor만 drain/중지, 기존 ES container stop/start,
해당 operation+receipt DB 쓰기, exact readback/release, 대상 profile parity가 범위다.
원본 volume·문서·계정은 보존하지만 중단 시간과 stop 뒤 불확실성 시 중단 유지 위험이 있다.
v2면 미완성 최종 검증 조립을 먼저 구현·검증해야 하며 TLS/키/서비스 재기동·schema 필요성을
별도로 확정해야 한다. 승인만으로 missing module/source를 해결할 수 없다.
취소 복구의 DB 수정은 위 exact CAS와 감사 범위만 별도 명시한다.
개인 첨부 ingestion은 별칭 복구 후 target job을 한정해야 하며 worker 전체 기동을 묶지 않는다.

## 검증·보존

- 이번 회귀: alias recovery/service·local collector·conversation terminal cleanup 3파일,
  `64 passed in 6.93s`. 합성/단위 검증이며 원본 복구 성공 증거가 아니다.
- 독립 역할이 취소/슬롯/감사/API 및 v2 미구현 경로를 읽기 전용 검토했다.
  모델 실행을 가정하지 않도록 독립 지적을 반영했다. DB 접근은 메인만 수행했다.
- 원본 SELECT 세 차례 모두 rollback. 첫 시도는 잘못된 import로 DB 연결 전에 실패했고 수정 후 실행했다.
- 제품 코드/시험 파일 변경0, DB 쓰기/마이그레이션/모델 호출/서비스·보안 변경0.
  관리자 이력 DB 업데이트도 하지 않았으므로 이 문서가 DB 반영 완료를 뜻하지 않는다.
- 동시 작업이 WORKBOARD/Git 인계 기록을 갱신하고 별도 커밋한 것을 확인했다.
  최신 WORKBOARD를 다시 읽고 이 조사 단락만 추가했다. 본 작업은 staging/commit/push를 하지 않았다.
