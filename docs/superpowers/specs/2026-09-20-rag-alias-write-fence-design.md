# RAG 공유 별칭 요청 종료와 문서 쓰기 차단

- 상태: 사용자가 설명된 후속 작업 진행을 승인(2026-09-20). 구현·독립 검증 완료, 실사용 적용은 별도다.
- 선행: [색인 출처](2026-09-20-rag-index-provenance-design.md).
- 목적: 삭제 대상의 늦은 writer가 색인·공유 별칭을 재생성하지 못하도록 RAG 쓰기 진입과 종료 관찰을 연결한다.

## 범위와 선택

RAG 내부 별칭 요청 원장과 문서별 영속 차단을 구현한다. 실제 삭제 API/UI·물리 삭제·관리자 수동 복구는 제공하지 않는다.
단순 현재 alias 조회는 선행 timeout 요청의 종료 증명이 아니다. ES 비동기 task 조회만으로 동기 aliases 요청의
종료를 증명할 수도 없다. 따라서 먼저 영속 예약하고 정확한 성공 응답을 받은 요청만 종료하는 방식을 채택한다.
불확실한 요청은 자동 재전송·나이 기반 인계 없이 차단 상태를 유지한다. 운영 중 구 writer의 drain은 배포 전제다.

## 별칭 원장

`rag_alias_operations`는 요청 UUID, 논리 저장소·cluster UUID·alias, indexing/processing profile ID,
정렬한 의도 target, open/closed, 안전한 결과 코드와 시각만 저장한다. 본문·벡터·URL·원시 오류는 저장하지 않는다.
같은 `(cluster_uuid, alias)`에 open은 하나다. 논리 store 이름 변경으로 미확인 요청을 우회할 수 없다.
identity·입력은 불변, 종료 후 재개는 금지한다. 기록이 남은 downgrade를 거부한다.

기존 source → profile → build 잠금 트랜잭션은 유지한다. 별칭 원장은 별도 세션에서 ES 호출 전 commit한다.
이 원장은 잠긴 source/profile/build에 FK를 두지 않는다. 같은 프로세스의 별도 연결이 FK 검사를 위해
자신의 FOR UPDATE 잠금을 기다리는 교착을 피한다. profile ID는 요청의 불변 scope snapshot이다.
원장을 일반 source 삭제 CASCADE로 지우지 않는다. 최종 삭제 통합에서 별도 기록 수명주기를 연결해야 한다.

설정 binding 및 실제 cluster 확인 → open 예약 commit → alias 변경 → ack 및 exact target 확인 → 원장 종료 commit.
no-op도 open 검사·예약 뒤 현재 target을 확인한다. timeout·취소·미승인 응답·관찰/commit 실패는 open을 유지한다.
다른 요청이 open이면 호출 전에 차단한다. mutation SDK retry는 0이다. 원장 종료 후 업무 DB rollback이면
실행 중 ES 요청은 없으므로 다음 parity가 DB 진실에 맞춰 다시 수렴할 수 있다.

## 문서 차단과 잠금

`rag_index_write_fences`는 document/workspace 및 정확한 lifecycle generation을 묶는다. Document FK는 RESTRICT다.
내부 서비스의 block은 대상 Document를 잠그고 현재 workspace/generation을 검증한 뒤 관련 indexing profile을
ID 순서로 잠근다. Document 뒤에 Asset/Projection/Build 잠금을 얻지 않는다. 같은 generation의 반복은 멱등,
오래된 generation은 거부한다. 차단 해제 API는 제공하지 않는다.

공통 `lock_ingestion_source`는 require_active와 무관하게 lifecycle=active·fence 부재를 확인한다.
새 ingestion/파싱 게시/prepare/READY 진입을 차단하며, alias activation/parity는 비활성·차단 문서를 target에서 제외한다.
profile 잠금이 fence와 별칭 전송을 직렬화한다. 기존 다른 문서 target은 보존한다.
prepare가 이미 전송됐다면 열린 prepare 기록 때문에 종료 확인은 실패한다. fence만 저장됐다고 종료 완료로 보고하지 않는다.

종료 관찰은 fence의 exact generation, 해당 문서 전체 버전/build 등록, open prepare 및 관련 scope open alias를 검사한다.
legacy build·미확인 요청은 완료 아님이다. 이 결과는 RAG 색인/별칭 writer 범위이며 전체 파일 writer·구 프로세스·외부 관리자 종료 증명이 아니다.
읽기 inventory는 fence/lifecycle 및 관련 alias 원장 변화를 두 snapshot에서 대조하고 open alias 동안 exhausted=false다.

## 성공 기준과 적용

1. 별칭 mutation 전에 원장이 다른 연결에서 보인다. 경쟁 예약은 하나만 성공한다.
2. timeout·취소·불확실 ack·DB 실패 후 원장이 남고 추가 mutation은 0건이다. 정상 완료 후 재요청은 가능하다.
3. 차단된 source의 prepare/READY는 거절된다. parity는 차단 문서를 제거하면서 다른 문서를 유지한다.
4. block과 activation의 경합, stale generation, legacy/open prepare/open alias는 안전하게 차단한다.
5. migration 제약·rollback·downgrade 거부, 단위/격리 DB/ES·타입·린트 및 독립 검토를 통과한다.

기존 .venv와 합성 UUID DB/ES만 검증에 사용한다. 실사용 migration·서버 재시작·commit/push는 하지 않는다.
새 별칭 writer에도 이전 색인 작업의 store ID/cluster UUID 설정이 필요하다. 구 writer를 중지하지 않은 혼합 배포는 지원하지 않는다.
