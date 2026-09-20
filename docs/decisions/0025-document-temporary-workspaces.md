# ADR-0025: 문서 전용 임시 작업공간의 생성 전 소유권

- 날짜: 2026-09-20
- 상태: 승인됨·구현 및 독립 검토 완료 (실사용 적용 전)

## 배경

파서·OCR·PDF preview가 OS 임시 디렉터리를 만들 때 source/job과 연결되지 않았다.
부모 작업의 취소나 DB job 완료만으로 외부 writer 종료를 증명할 수 없다.

## 결정

Platform Assets가 실제 source와 선택 job에 RESTRICT로 연결된 영속 예약을 소유한다.
독립 예약 commit 이후 infrastructure 어댑터가 전용 binding 저장소에 UUID 작업공간을
배타 생성한다. parser/renderer port에는 권한 확인된 source 문맥을 명시 전달한다.
동기 parser는 DB 세션을 소유하지 않는다.

상태는 open→closed→cleaning→cleaned이며 각각 현재 출처 revision과 함께 확정한다.
알려진 writer 종료와 cleaning commit 확인 전에는 파일을 정리하지 않는다.
Windows에서 상위 경로·marker·소유 파일 identity를 핸들로 고정하고 정확한 핸들에만
삭제를 요청한다. 미등록 파일/교체/미확인 writer는 보존하며 자동 복구하지 않는다.

## 영향

전용 root·store ID·binding과 migration이 준비되지 않은 파싱/PDF preview는 명시 실패한다.
일반 원문 읽기는 계속 가능하다. 초기 mutation 지원은 Windows다.
불투명 OCR 런타임은 종료 확인이 없어 open을 남길 수 있고 별도 복구가 필요하다.
HTTP multipart spool, 일반 Jobs 출처, 외부 runtime 쓰기 검증과 실제 purge 활성화는 후속이다.

세부 계약의 정본은 [상세 설계](../superpowers/specs/2026-09-20-document-temporary-workspace-design.md)다.
