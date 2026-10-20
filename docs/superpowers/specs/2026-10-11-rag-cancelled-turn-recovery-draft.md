# 취소된 대화의 종료 확인 복구 계약 초안

- 상태: **미승인 설계 초안 / 구현 안 됨 / 운영 적용 안 됨**
- 기준일: 2026-10-11
- 작성 범위: 기존 권한 안에서 복구 요청·증거 검증·상태 저장 계약 제안
- 결정권자: 사용자. 문서 검토는 구현·migration·운영 실행 승인이 아니다.
- 정본 관계: 현행 [RAG 설계](../../labs/rag/design.md)를 대체하지 않는다.
  승인 시 필요한 ADR·RAG 설계·API 계약 변경을 먼저 확정한다.

## 1. 목표와 현재 근거

취소 상태는 저장됐지만 실행 task의 종료 확인 저장이 누락된 대화는 다음 질문이 계속 차단된다.
목표는 **정확한 대상의 종료 또는 미기동이 검증된 경우에만 다음 질문을 다시 허용**하는 것이다.
취소를 답변 성공으로 바꾸거나 누락된 관측을 추정해 채우는 기능이 아니다.

| 현행 근거 | 설계에 미치는 영향 |
| --- | --- |
| `conversations/domain.py`의 reserve_turn은 cancelled/종료미확인을 busy로 판정 | 상태 해제에는 실제 종료 근거가 필요 |
| 같은 파일 recover는 오래된 running만 interrupted로 변경 | 시간 만료·재취소는 과거 취소의 복구 수단이 아님 |
| `conversations/service.py`의 finalize는 executor task join 뒤 종료 플래그 저장 | task 완료와 저장 완료가 분리되며 DB 상태만으로 task 종료를 단정할 수 없음 |
| `conversations/repository.py`의 record_termination은 삭제 tombstone 전용 | 활성 대화 복구에 재사용하면 안 됨 |
| `executions/models.py`는 turn_id당 execution 하나를 강제 | 실제 FK와 actor를 검사하여 결합, 시간·correlation만으로 결합하지 않음 |
| `executions/repository.py`의 finish_execution은 단계별 기록을 확인해 complete 판정 | 종료 복구가 complete를 강제로 true로 만들면 안 됨 |

코드 경로는 모두 `backend/src/ai_workshop/labs/rag/` 기준이다.
[원인 조사](../../worklogs/2026-10-11-rag-recovery-evidence-investigation.md)와
[기존 결함·실제 관측](../../worklogs/2026-10-05-rag-browser-closure.md)을 함께 읽는다.
과거 문제 건은 retrieval running·일부 미기록이었다. 모델이 실행됐다고 가정하지 않는다.
현재 자료만으로 이 건을 복구할 수 있다고 보장하지 않는다.

## 2. 범위와 선택지

| 선택지 | 장점 | 한계 / 제안 |
| --- | --- | --- |
| 소유자의 명시적 복구 요청 + 서버 증거 검증 | 기존 인증·대화 소유권 재사용, 멱등 응답 가능 | **추천.** 신뢰 가능한 증거 생산 경로는 별도 확정 필요 |
| 같은 소유자 권한의 유지보수 CLI | UI 추가 없이 운영자가 요청 가능 | 현재 API 인증과 동일한 신원·권한 확인 방식 설계가 더 필요; 원시 DB 접근으로 대체 금지 |
| 자동 복구 작업 | 사용자 조작 감소 | 증거 생산·수명주기·재시도 범위가 커짐. 첫 범위에서 제외 |

첫 범위는 삭제되지 않은 자기 대화의 `cancelled + execution_terminated=false`만이다.
running/interrupted/삭제 대화/평가 실행, 슬롯 일괄 삭제, 첨부 정리, 별칭 gate,
인증 변경·새 운영 권한·자동 스케줄·프로세스 종료·모델 호출은 제외한다.
다른 busy turn이나 권한 제한이 남으면 복구 하나가 성공해도 다음 질문은 여전히 거부될 수 있다.

## 3. 권한과 모듈 책임

인증 주체는 기존 `get_current_user`다. domain 접근은 현재 `DomainService.detail_for_actor`,
대화 접근은 기존 owner_id/domain_id/비삭제 조건을 적용한다. 서버가 owner_id를 결정한다.
운영자·마스터라는 이유로 타인 대화를 복구하는 우회 경로를 추가하지 않는다.
증거 발급 권한은 대화 소유자의 요청 권한과 다르다. 요청자가 증거를 직접 발급할 수 없다.

Conversations의 애플리케이션 서비스가 권한·상태 전이·CAS를 소유한다.
검증 port 뒤의 어댑터가 원래 실행 수명주기의 증거를 검증하고, repository가 결과·감사·소비를
한 트랜잭션에 저장하는 안을 제안한다. handler에 종료 판정 규칙을 두지 않는다.
기존 Generation의 모델 승인·슬롯, Executions의 단계 관측 책임을 침범하지 않는다.

권한은 사전 확인과 쓰기 직전 현재 상태에서 다시 확인한다. revoke 경합에 대한 기존 권한 조회의
보장 수준을 보존하며, 더 강한 원자적 revoke 보장이 필요하면 기존 권한 변경 경로와의 잠금 계약을
구현 계획에서 검토한다. 단순 재조회만으로 동시 권한 변경이 완전히 배제됐다고 주장하지 않는다.
거부는 기존 도메인/대화의 오류·존재 비공개 규칙을 재사용한다. 타인 대상의 증거 존재도 노출하지 않는다.
본문을 포함하는 응답을 선택하면 기존 source ACL/redaction을 그대로 거쳐야 한다.
첫 제안은 본문 없는 최소 receipt 응답이며 Cache-Control은 기존처럼 no-store다.

## 4. 실행 결합과 허용 증거 후보

검증 대상 결합은 다음 전부다. 값은 서버가 기존 레코드와 비교한다.

- 현재 actor/owner, domain_id, conversation_id, turn_id와 turn.request_id
- FK로 결합된 execution_id와 execution.actor_id, evaluation_attempt_id 없음
- conversation revision과 turn 상태/종료 플래그/변경시각의 snapshot
- 실제 실행을 소유한 API/search task의 attempt 또는 수명주기 식별자
- 생성된 자식이 있다면 각 child의 부모 결합과 종료 범위

마지막 두 항목은 현재 DB에 충분한 영속 결합이 있다고 가정하지 않는다. **자료가 없으면 거부한다.**
turn 요청 ID와 별도로 생성되는 Codex request_id는 같다고 가정하지 않는다.
공개 correlation ID, 비슷한 시각, runner 이름, PID 하나는 권한/정확한 결합 증거가 아니다.

| 증거 후보 | 반드시 입증할 내용 | 첫 계약의 미정점 |
| --- | --- | --- |
| 소유 실행의 terminal/join 확인 | 해당 attempt의 모든 실행·cleanup이 끝났고 이후 자식 생성/재개가 불가능함 | 이를 영속적으로 발급·검증할 생산자와 수명주기 ID |
| 미기동 확인 | 예약 이후 해당 attempt가 실행을 dispatch하지 않았으며 앞으로도 dispatch될 수 없는 종결 경계 | 현재 미기동 원장/차단 경계가 존재하는지; 없으면 새 설계 필요 |
| 과거 소유 프로세스 종료 기록 | 정확한 task→process 수명 결합, 실제 child 목록/종료 또는 미기동, 재개 불가 | 누가 어떤 기존 기록을 검증해 신뢰 가능한 terminal 사실로 만드는지 |

추천은 검증된 소유 실행의 종결 사실을 기본으로 삼고, 과거 기록은 **정확한 producer·자료 형식·
검증 규칙을 별도로 승인한 경우에만** 허용하는 것이다. 현재 새 서명키·보호 저장소·권한을 만들지 않는다.
프로세스가 없다는 현재 관찰, API 재시작, 슬롯0, 감사0, 오래된 시각, 운영자의 체크박스,
임의 JSON 또는 그 SHA는 허용 증거가 아니다. 자식 모델 종료만으로 API/search task 종료를 대체하지 않는다.

신뢰 검증 결과는 서버 내부의 검증 객체/보호된 참조로 전달하는 안이다. 타입 검사나 해시만으로
발급자를 신뢰하지 않는다. 외부 요청의 `terminated=true`, proof 본문·파일 경로는 받지 않는다.
TTL은 종료의 대체 증거가 아니다. 불변 terminal 사실도 target/attempt 일치·소비·현재 상태를 재검증한다.
변경 가능한 관찰만 있는 자료는 복구 근거로 쓰지 않는다. 불명확한 영구 결손은 자동 성공시키지 않는다.

## 5. 제안 API 계약 — 아직 등록되지 않음

경로 후보: `POST /api/v1/rag/domains/{slug}/conversations/{conversation_id}/turns/{request_id}/termination-recoveries`.
경로의 request_id는 기존 turn 요청 ID다. body의 recovery_request_id는 별개의 멱등 키다.

| 입력 후보 | 의미 |
| --- | --- |
| recovery_request_id | 호출자가 재전송 때 유지할 UUID |
| expected_revision | 기존 대화 revision |
| expected_execution_id | 사용자가 본 실행과 서버 결합이 같은지 확인 |
| evidence_ref | 승인된 서버 검증 경로가 발급한 불투명 참조; 단독 bearer 권한 아님 |

turn_id는 경로 결합으로 서버가 해석한다. owner·종료 플래그·complete·원시 증거를 입력받지 않는다.
응답 후보는 recovery_id, turn_id, execution_id, 결과, before/after revision,
execution_terminated, observation_complete, recovered_at이다. 새로운 질문·답변·프로세스 정보는 반환하지 않는다.
복구 시각은 실제 실행 종료 시각과 구분한다. 증거의 종료 시각을 turn.updated_at으로 소급 기록하지 않는다.

성공은 200과 같은 저장 receipt를 반환하는 안이다. 409는 revision/대상 상태/멱등 키 충돌,
422는 허용되지 않는 증거나 결합 불일치, 503은 검증 자료 조회 불가 후보이며 정확한 코드명은
API 계약 승인 시 고정한다. 인증·권한 오류를 일반 증거 오류로 숨기거나 vice versa로 누출하지 않는다.
거부 응답은 고정 safe code만 제공한다. 사용자 입력·비밀 경로·원시 예외는 포함하지 않는다.
자동 DB 재시도나 다른 proof로 조용히 대체하지 않는다.

## 6. 상태 변경, CAS와 경합

| 항목 | 복구 성공 후 |
| --- | --- |
| turn.status / error_code / query / response | 기존 cancelled 및 내용 보존 |
| turn.execution_terminated | 검증 후 false → true |
| turn.updated_at / conversation.updated_at | 실제 복구 저장 시각 |
| conversation.revision | 정확히 한 번 증가 |
| execution.complete / stages / status / ended_at | 변경하지 않음 |
| Codex slot·승인, 첨부, 별칭, 외부 시스템 | 변경하지 않음 |

`execution_terminated`는 소유 실행 종료 확인이며, `execution.complete`는 단계 관측의 완결성이다.
`true/false` 조합은 허용한다. UI·모니터링에서 관측 누락을 지우거나 답변 성공으로 표시하지 않는다.
종료 복구와 관측 재구성은 별도 작업이다. 회복된 turn을 재실행하지 않으며 새 질문은 기존 submit을 사용한다.

제안 처리 순서:

1. 현재 권한·대상 소유권과 canonical 요청 digest를 확인하고 기존 recovery_request_id의
   receipt를 먼저 조회한다. 같은 payload이면 저장 receipt를 반환하고 다른 payload이면 충돌이다.
   성공 replay에는 과거 expected_revision·cancelled/false·미소비 증거 검사를 다시 적용하지 않는다.
   replay 결과와 현재 대화 상태는 구분한다. 권한이 회수되면 receipt도 반환하지 않는다.
2. 신규 요청에만 exact binding과 producer 증거를 검증한다. 검증은 긴 DB 잠금을 잡기 전에 수행한다.
   기존 규칙과 충돌하지 않는 잠금 순서로 대화→turn→execution→증거 소비/복구 요청을 잠근다.
   실제 기존 SQL lock 순서와의 합성 검증은 구현 전 필수다.
3. 잠금 후 현재 권한·소유권을 확인하고, 경합 중 생성됐을 수 있는 동일 키 receipt를 다시 조회한다.
   있으면 1번 replay/conflict 규칙을 적용한다. 여전히 신규인 요청에만
   비삭제·actor/FK·revision·cancelled/false·증거 미소비를 확인한다. 증거의 attempt/terminal 사실과
   현재 snapshot을 비교하며 재개/늦은 dispatch 가능성이 있으면 실패한다.
4. 신규 요청만 위 상태 변경·증거 소비·불변 감사 receipt를 원자 commit한다. 하나라도 실패하면 전부 rollback한다.

검증 뒤 삭제·재시도·정상 finalize가 먼저 완료하면 신규 복구는 conflict/no-op이며 “이번 복구 성공”
receipt를 발급하지 않는다. 정확한 재전송만 기존 receipt를 돌려준다. 정상 finalizer의 stale 객체 저장이
복구 결과를 덮어쓰지 않는지도 검증해야 한다. finalizer가 아직 살아 있다면 애초에 종료 증거가 성립하지 않는다.
connection loss로 commit 결과가 불명확하면 같은 멱등 키의 인증된 상태 조회/재전송으로 확인한다.
새 키 재시도·수동 flag 갱신·역갱신은 하지 않는다. 상태 조회 경로도 본문 없는 동일 소유권을 적용한다.

## 7. 영속성·감사와 재사용 방지 제안

메모리 소비 표시만으로 재사용을 막을 수 없다. RAG 소유의 영속 복구 원장과 소비 제약을 제안한다.
새 저장 구조/migration 필요 여부는 승인 뒤 구현 계획에서 확정하며 이번에는 만들거나 적용하지 않는다.

- 복구 요청의 유일 키: actor_id + recovery_request_id. 입력은 canonical digest로 고정한다.
- 성공 소비는 exact turn/execution/attempt와 원본 terminal event identity에 결합한다.
  동일 evidence_ref만 unique로 제한하면 참조를 재발급해 우회할 수 있으므로 producer의 안정적인
  terminal event identity까지 검사한다. 이 identity가 없으면 재사용 방지 계약은 미완성이다.
- 다른 사용자·대화·turn·execution·attempt에 재사용하면 거부한다. 같은 성공 요청의 replay만 허용한다.
- 원장은 actor/대상 ID, evidence 종류·producer/version·terminal event 참조·digest,
  전후 revision/종료 플래그, 처리 시각·결과, 검증 코드 버전을 보존한다.
  과거 query/answer/문서·credential·전체 프로세스 명령·세션 원문은 저장하지 않는다.
- 거부는 소비하지 않는다. 조회 시도/거부의 감사가 필요하면 기존 비공개 safe-code 로그에 한정하고
  타인 대상 ID를 새 영속 원장에 누적하는 방식은 별도 개인정보 검토 없이 추가하지 않는다.
- 증거 참조와 소비 tombstone은 적어도 복구 receipt가 유효한 동안 유지한다. 임의 TTL 만료로
  소비 제약을 제거하지 않는다. 기존 보존 정책과 삭제·권한 회수 처리는 구현 계획의 필수 검토다.

재사용 방지 DB 제약과 권한 검사가 모두 필요하며 어느 하나가 다른 하나를 대신하지 않는다.
복구 전 값을 남겨도 새 질문이 접수된 뒤 단순 false 역갱신은 안전한 rollback이 아니다.

## 8. 승인 전에 결정할 최소 사항

1. **첫 진입점:** 기존 소유자 인증을 사용하는 명시적 API를 우선할 것인가?
   추천은 위 API이며 자동 복구·타인 대화 관리 권한은 추가하지 않는다.
2. **첫 증거 범위:** 현재 검증 가능한 소유 실행의 terminal 사실만 지원하고,
   과거 기록의 producer/형식·검증 계약은 별도로 확정할 것인가?
   추천은 그렇게 분리하는 것이다. 근거가 없는 기존 문제 건은 계속 차단될 수 있음을 수용해야 한다.
   이를 실제로 풀려면 해당 API/search task의 결합·종료/미기동 자료가 먼저 필요하다.
3. **영속 원장:** 상태 변경과 증거 소비·감사를 원자 저장하는 구조를 설계 범위로 승인할 것인가?
   추천은 승인하되 migration 작성/실행과 운영 데이터 변경은 후속 명시 범위로 분리하는 것이다.

사용자가 producer의 세부 기술을 추측해 선택할 필요는 없다. 개발자가 기존 실행 소유권 자료와
결합 가능한 producer 후보·정확한 검증식을 제시하기 전에는 2번을 구현 준비 완료로 판정하지 않는다.
이번 초안은 새 runtime registry/서명 체계/권한을 승인된 사실로 가정하지 않는다.

## 9. 구현 후 검증할 수용 기준 — 이번 실행 결과 아님

| 검증 층 | 필수 사례 |
| --- | --- |
| 순수 계약/단위 | exact terminal 양성, exact 미기동 양성(해당 producer 지원 시), missing·unknown·위조·stale·다른 attempt·미종료 child 거부 |
| 권한/API | 비인증·다른 owner/domain·권한 회수·삭제 경합, receipt 존재 비노출, no-store, 원문·원시 예외 비노출 |
| 상태 | cancelled/false만 전이, complete=false 보존, status/본문 불변, 다른 busy turn은 계속 차단 |
| DB 통합 | revision CAS, 동일 키 replay 1건, 다른 본문 충돌, 다른 키·같은 증거 경합 1성공, 재발급 참조 재사용 거부 |
| 원자성 | 감사/소비 저장 실패 시 flag도 rollback, commit 응답 유실 후 같은 키 readback, 프로세스 재시작 후 재사용 차단 |
| 기존 동작 | finalize·submit·delete 경합, 잠금 순서, 같은 turn 요청 replay와 새 요청 구분, source ACL 보존 |
| 기능 마감 | 승인된 원본 자료로 exact 복구 후 새 요청 접수 가능, 관측 미완료 유지, 원본 이력·계정 보존 |

단위는 합성 UUID/증거 port와 mock으로 네트워크·모델 없이 작성한다. SQL·원본 통합은 별도 승인 범위다.
실제 종료 증거가 없으면 합성 양성 테스트만으로 원본 기능 마감이라고 보고하지 않는다.

## 10. 초안 작성 검증과 인계

이번 저장소 변경은 이 초안과 WORKBOARD의 미승인 참조뿐이다. 제품·테스트·ADR 정본·운영 상태는 변경하지 않는다.
문서의 상대 링크3·UTF-8·공백과 WORKBOARD diff 검사를 통과했다. 시작 상태 대비 기존 파일은
WORKBOARD만 변경됐고 기존 미추적 파일은 보존했다. 제품 테스트는 문서 전용 범위라 실행하지 않았다.
독립 검토에서 replay 이전에 신규 CAS를 적용하던 순서 모순을 지적받아 기존 receipt 우선 조회와
잠금 후 재조회로 수정했다. §6 재검토에서 해당 지적 해소·추가 차단 없음이 확인됐다.
독립 검토는 설계의 승인이나 구현/원본 검증을 대신하지 않는다.

작성 중 별도 사용자 승인이 도착해 Docker context와 같은 조건의 프로젝트 프로세스 읽기만
승인 심사의 require_escalated로 재실행했다. context exit0, CIM 성공/Python6개를 확인했다.
이전 제한 실행의 접근 거부와 달리 성공해 실행 제한과의 관련성을 확인했으나 정확한 OS 접근 검사
원인은 미확정이다. Docker daemon 상태·과거 실행 종료·전체 client 부재를 확인한 결과가 아니다.
private·credential·DB 조회/쓰기, ACL·설정·프로세스·서비스·예약 변경은 하지 않았다.
이 별도 진단은 본 설계의 승인 또는 evidence producer가 아니다.
