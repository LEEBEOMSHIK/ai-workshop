# ADR-0027: 일반 Jobs의 출처와 변경 버전 보존

- 날짜: 2026-09-20
- 상태: 구현·검증 완료

Jobs의 source와 변경 revision을 동일 transaction으로 기록한다. 신규 job은 별도 RESTRICT
소유권 pin으로 보호하며 legacy revision은 NULL로 남긴다. repository와 dispatch의 모든
persisted update는 현재 provenance revision을 함께 변경한다. 상태 종료는 writer 종료 증거가 아니다.
읽기 inventory는 별도 실행 종료 계약 없이 삭제를 승인하지 않는다.

CASCADE FK 전체 변경이나 추정 backfill 대신 신규 작업에 소유권 pin을 추가한다.
기존 NULL revision 작업에는 pin을 자동 추가하지 않으며 기존 보존 한계를 inventory에 표시한다.
세부 계약과 검증은 [설계](../superpowers/specs/2026-09-20-job-metadata-ownership-design.md)를 따른다.
