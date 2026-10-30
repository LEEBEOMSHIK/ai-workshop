# ADR-0041: 본문 없는 RAG 세부 연산 시간

- 상태: 승인된 속도 개선 범위의 구현 결정 (2026-10-25)
- 관련: [설계](../superpowers/specs/2026-10-25-rag-selection-speed-design.md), [조사](../worklogs/2026-10-25-rag-latency-audit.md)

기존 단계 시간은 검색·근거 선택 내부 비용과 모델/문자열 초기화 비용을 구분하지 못한다. 기존 실행 레코드의 stage JSON과 현재 권한을 확인하는 상세 API에 선택적 `operations`를 추가한다. DB migration·새 저장소·새 권한 경로는 없다.

각 항목은 닫힌 enum `name`, 유한한 비음수 `duration_ms`, 양의 `calls`, 비음수 `failures`, `items`, `reused_items`만 담는다. `failures <= calls`, `reused_items <= items`를 검증하고 임의 필드·본문은 거절한다. 단계당 최대16종, 각 이름당 누적1항목으로 저장한다. 값이 없던 과거 기록은 필드 생략/None으로 읽고 실제 관측한 빈 목록과 구분한다.

시간은 자식 연산과 대기를 포함한 inclusive 누적값이다. 중첩 연산·병렬 검색이 있어 각 값을 더한 결과를 전체 응답 시간이나 순수 CPU 시간으로 취급하지 않는다. 모델 HTTP span과도 의미가 다르다. 새 모델 내부 지표나 미관측 시간을 추정하지 않는다.

현재 task-local observer에 귀속하며 stage 종료와 함께 기존 recorder에서 저장한다. 개인정보·원문·질문·모델 비공개 추론은 수집하지 않는다. 계측 오류가 검색 결과를 바꾸지 않으며 기존 observation incomplete 의미를 따른다. 외부 전송은 없다. 기존 UI의 stage 표시와 생성 프로파일은 유지하고 API 타입만 갱신한다.
