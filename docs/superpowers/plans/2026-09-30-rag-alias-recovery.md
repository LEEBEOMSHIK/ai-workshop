# RAG 별칭 정상 복구 구현 계획

> REQUIRED: superpowers:subagent-driven-development. 승인된 기존 workspace에서 실행하며 새 DB·계정·worktree를 만들지 않는다.

목표: [복구 설계](../specs/2026-09-30-rag-alias-recovery-design.md)에 따라 exact 요청의 전송 차단·종료 근거·불변 receipt를 구현하고 ISSUE-00013을 본래 환경에서 검증한다.

기준 HEAD: `f8e85656b1b633929c3489ed65166ecfb5e52b67`. 앞선 첫 질문/진단 미커밋 변경은 보존한다.

실행 상태(2026-10-01): Task1·Task2 구현과 독립 검토 승인, 전체 offline3,161건 및 후속 좁은 회귀 완료.
Task3의 본래0061·SAVEPOINT3건·자료 보존·서버 복원 완료. 실제 호스트의 Node/tool/IDE/build
지원 경계와45초 HOST 관찰 제한 때문에 종료 proof·receipt·해제·새 정상 parity는 미완료다.
원래 요청은 open/frozen revision1, ISSUE-00013은 open으로 보존한다. 다음 진행은 호스트
지원 경계·freeze 전 사전 검사 재설계이며 [실행 기록](../../worklogs/2026-09-30-rag-alias-recovery.md)을 따른다.

## Global Constraints

- original `.env`, DB `ai_workshop_local_clean`와 자료·계정·구성·ES volume 유지. root만 실환경 변이·문서 통합·staging/commit/push.
- 기존 open 행은 `legacy_unknown`; 신규 `reserved -> dispatching` CAS가 성공한 뒤에만 mutate. reserve와 dispatch 모두 cluster gate를 잠그며 absent gate도 동시 초기화 안전해야 한다.
- source → profile → build → 별도 journal 순서 유지. source/profile FK나 외부 I/O 동안 journal lock을 추가하지 않는다.
- `confirmed`, `not_dispatched`, `recovered_terminated`는 서로 다른 결과다. 복구 receipt와 exact closure는 원자적이며 증거/닫힌 행은 불변이다.
- local만 허용·기존 active owner 재검증. 임의 JSON/force flag/task 부재/현재 alias 일치는 종료 증거가 아니다. 과거 결과를 성공으로 바꾸거나 bulk close하지 않는다.
- 신뢰하는 로컬 운영 경계 밖의 client/history/topology가 미확정이면 open/frozen을 보존한다. 실제 종료 proof와 fake 테스트는 구분한다.
- gate는 request/actor/snapshot에 귀속하며 자동 만료·takeover 없다. 같은 정확한 request만 replay/readback. 불명확 commit 뒤 새 request·network mutation·release/parity 금지.
- 테스트는 외부 모델/네트워크 없이 unit을 먼저 실행. 실제 DB는 root migration 뒤 opt-in outer rollback harness만 사용하며 기존 provisioning fixture를 호출하지 않는다.
- backend/.venv의 기존 패키지 사용. 환경·의존성·모델·queue·cache·index 삭제/새 생성 금지.

### Task 1: 원장 phase·cluster gate·atomic recovery 계약

소유 범위: `backend/src/ai_workshop/labs/rag/indexing/alias_{models,journal,service}.py`, 새 `alias_recovery.py`, `alias_recovery_repository.py`, 필요하면 `alias_recovery_types.py`; `backend/alembic/versions/0061_alias_recovery.py`; 관련 `backend/tests/unit/labs/rag/indexing/`와 opt-in `backend/tests/integration/labs/rag/domains/test_original_alias_recovery.py`. 문서·config·conversations·기존 runtime 수정 금지.

1. 기존 alias unit/생산 writer 진입점과 0043 trigger, first-question original rollback harness를 읽는다. test 먼저 작성하고 실패 이유를 기록한다.
2. migration0061(head0060): 기존 row phase `legacy_unknown`, 신규 phase `reserved`, open dispatch CAS. gate cluster UUID primary key, frozen claim/request/actor/snapshot/revision. receipt request UUID 및 operation 각각 unique, exact immutable metadata. closed check 확장·복구 결과 receipt 요구·immutable phase/terminal trigger; immutable source identity/target 보존. 새 데이터/evidence/frozen gate 있으면 downgrade 거부.
3. journal에 `dispatch(operation_id: UUID) -> None`를 추가한다. gate 동시 초기화/upsert + FOR UPDATE → operation 순서로 예약/전송/복구 직렬화. 실패/불명확 commit은 fail closed. `run_alias_operation`은 reserve → dispatch → mutate → observation → finish로 연결한다. 기존 fake journals도 contract 업데이트한다. 실제 application writers가 이 경로를 사용하는지 report에 위치를 적는다.
4. recovery 업무 서비스를 typed port/repository로 분리한다. Task2에서 사용할 공개 facade는 기존 sessions/settings로 구성 가능하게 하고 `preview`, `freeze`, `readback`, `recover_not_dispatched`, `recover_terminated`, `release` 기능을 제공한다. 서명·타입·안전한 error code를 report에 명시한다. exact snapshot에는 ID/store/cluster/alias/profile/processing/targets/created/phase와 SHA256을 포함한다.
5. `TerminationProofPort`가 exact frozen claim에 맞는 allowlisted typed proof를 수집/검증하며 임의 JSON 입력을 서비스가 증거로 받지 않는다. reserved closure는 CAS만으로 가능, legacy/dispatching은 proof 필수. 서비스 자체 local 및 current active OWNER 검사, 최종 atomic transaction에서 재검사한다. 정상 finish 승리·ABA·receipt replay·다른 payload/owner/request 충돌·revocation·unknown commit/readback·gate release exactclaim을 처리한다.
6. proof의 안전한 typed 계약은 Task2 collector가 만들 수 있어야 한다: request/operation/snapshot/cluster/container identity, protected mount/config digest, stable node, old/new ephemeral/JVM incarnation, controlled stop/start UTC 순서, client inventory digest와 schema version. 시각/명칭만으로 충분하다고 검증하지 않으며 collector의 controlled workflow를 port 책임으로 정의한다.
7. unit 검증: gate가 frozen이면 reserve/dispatch에서 mutate0, 폐쇄 reserved 재개 dispatch0, legacy reservedshortcut거부, 정상 confirmed보존, actor오류/권한변경, 정확한 claim/snapshot·receipt불변/ABA/replay, rollback/commit응답유실. SQL unit은 실제 predicate/transaction 로직을 확인하고 fake 자체의 행동만 검사하지 않는다.
8. 본래 DB opt-in harness는0061 guard·기존 계정/행만 사용하고 outer COMMIT 거부+SAVEPOINT rollback. 제약/trigger/receipt원자성/phase 전이를 검증; 독립 committed race는 별도 한계로 기록한다. agent는 실행하지 않고 root가 migration 후 실행한다.
9. scoped pytest/Ruff 및 전체 src mypy 실행. TDD red/green·파일 목록·Task2 exact signatures·명시적 미검증 경계를 지정 report에 남긴다. staging/commit/subagent/runtime 작업 금지.

### Task 2: 신뢰하는 local collector·운영 CLI

소유 범위: 새 `backend/src/ai_workshop/labs/rag/indexing/alias_recovery_local.py`, `alias_recovery_cli.py`, 필요시 별도 collector helper module; 관련 unit tests. Task1 계약을 사용하고 DB 업무 규칙을 복제하지 않는다. 정확한 Task1 signatures는 Task1 report를 읽는다.

1. 실패 테스트 먼저: local외/owner오류/remote·proxy·WSL·unknownclient/history/topology, PIDreuse/emptycommand/enumerationerror, 바뀐container/mount/cluster/node, 동일ephemeral·JVM, stale start, unknowncommit에는 close/release/parity0.
2. 전용 module CLI로 preview/status/freeze/recover/release를 제공. 기존 `.env`를 명시적으로 읽고 local·binding·actor·exact operation/request를 검증한다. public API나 force/proofJSON 인자를 추가하지 않는다. output은 allowlisted safe metadata/error code만.
3. absolute executable와 fixed argument arrays로 OS/Docker 호출, shell=False. 신뢰하는 로컬 운영자/daemon·direct historical endpoint 경계를 명확히 진단한다. no-proxy/redirect 거부 ES transport, exact context/daemon/container immutable config·mount/port/cluster single-node/stable node 검증. known peer containers만 허용하며 arbitrary manual/hostile sender 배제를 자동으로 입증했다고 주장하지 않는다.
   최초 historical source는 저장소 root에서 고정된 `.local-data/backups/original-rag-cutover-20260920/original.env` 및 `es-identities.json`, 원래 cutover 실행 기록을 직접 검사하는 `trusted_operator_original_cutover_history_v1`이다. 요청 전의 local/direct endpoint·cluster 관찰과 현재 같은 pre-existing immutable single-node container/mount/port를 확인해 source digest를 묶는다. exact 과거 호출 환경의 사후 증명 또는 연속된 서명 이력이 있다고 주장하지 않는다. 신뢰하는 운영자가 보존한 원래 환경을 writer가 사용했고 endpoint override/cluster copy/manual writer/기록 변조가 없다는 명시적 지원 전제다. 미확정 기록·다른 환경·경로는 차단하며 caller-selected evidence 파일/true flag로 대신하지 않는다.
4. freeze 이후 API/worker/beat/old CLI와 supervisor 종료는 root가 정확한 process lifetime으로 수행. collector는 자신의 exact process/venv launcher/controller만 제외하며 관련 unknown 실행·WSL/터널·연결은 거부한다. 필요하다면 보수적으로 지원 범위를 더 제한하고 불충분한 historical evidence는 차단한다.
   DockerDesktop 자체의 검증된 `docker-desktop` WSL만 인프라로 구분한다. 원래 frontend node는 보존된 registry의 exact PID/생성 시각/module로만 허용한다. 검증용 PowerShell/CIM subprocess와 CLI/controller의 정확한 수집 경로를 명시적으로 분류하고 임의 descendants/다른 Python/Node/빈 command line을 일괄 제외하지 않는다. TCP TimeWait/PID0은 live writer로 오인하지 않되 미확인 live ES 연결·listener·peer·user WSL·portproxy/터널은 거부한다. 루프백 관찰에는 ambient proxy를 사용하지 않는다.
5. 신뢰하는 controlled workflow 안에서 clientabsence→samecontainer stop/실제stopped→samecontainer start→samecluster/stable node/newephemeral·JVM→client/gate재검사 순서의 typed evidence 생성. 각 외부 호출은 DB lock 밖, crash시frozen 유지. 별도 외부 evidence JSON 입력으로 대신하지 않는다. 중지 뒤 실패하면 동일 서버 복원 가능하나 closure 성공을 꾸미지 않는다.
6. receipt definitive readback후 exactrelease; current DB 기준 기존 scoped parity는 별도 결과로 표시, timeout새open 재귀복구 금지. runtime 기능은 root 실행 전 독립 review gate를 통과한다.
7. scoped pytest/Ruff/mypy, CLI help/unsupported-safechecks, 구현보고. commit/runtime/subagent금지.

### Task 3: 독립 검토·본래 반영·이력

root와 독립 verifier 책임. 두 구현 task별 spec+quality review 및 최종 전체 scoped review 후 수정영역 재검토. root는 본래0060 backup 검증, 현재 프로세스정확inventory/drain,0061migration, originalrollback검증을 진행한다. legacy 종료의 신뢰 전제가 실제로 확인되는 경우에만 controlled collector를 실행하고 oldrequest receipt+정상 새parity를 따로 확인한다. 부족하면 구현/검증된 부분과 runtime 차단을 명확히 남기며 위험한 해제는 수행하지 않는다. 기존 프로세스를 동일 `.env`로 복원, health와 자료·권한·활성구성 식별자 비교, ISSUE-00013 DB문서 정확버전연결/상태·worklog·WORKBOARD(max최근완료5)·docs link/diffcheck로 마감한다. 전체 unit 한번 및 src mypy/Ruff, 필요한 원래DB검증 수행. 첫질문 기존변경 보존.
