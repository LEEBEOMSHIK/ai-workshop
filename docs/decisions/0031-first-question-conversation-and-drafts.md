# ADR-0031: 첫 질문 접수·첨부 초안과 질문 제목

- 상태: 승인됨, 구현·본래 환경 반영 완료(2026-09-30)
- 기준일: 2026-09-30
- 범위: Labs/RAG Conversations와 기존 Platform Asset upload 경계
- 관련: ISSUE-00001, [설계](../superpowers/specs/2026-09-27-first-question-conversation-design.md), [ADR-0028](0028-issue-history-database.md)

## 문제

현재 create와 submit이 각각 commit돼 첫 질문 접수 실패 시 빈 대화가 남을 수 있다.
첨부 패널도 세션을 선행 생성한다. 날짜 제목은 질문 의도를 나타내지 않으며,
질문에서 제목을 만들면 현재 ACL이 철회된 뒤 목록/상세의 제목 노출까지 고려해야 한다.

## 결정

1. 질문 전 업로드는 owner/domain이 있는 attachment draft에 속한다. 원본 저장은 기존 Asset/intake 경계를 재사용한다.
2. 첫 질문 start는 독립 접수 원장과 conversation·첫 turn·draft 결합을 한 트랜잭션으로 저장한다.
   global owner/domain/request 멱등 키와 요청 digest가 replay를 보호한다. 삭제 뒤에도410 fence를 보존한다.
3. 기존 대화 후속 turn 실행 코어를 재사용한다. create 후 submit 조합과 새 모델 호출 코어 복제는 사용하지 않는다.
4. 첫 질문만으로 로컬 보수적 추출/문법 정리 제목을 한 번 만든다. 복합 요청·조건·부정을 보존하고
   불명확한 장문은 fallback으로 구분한다. 기존 생성 프로파일·모델·외부 호출은 바꾸지 않는다.
5. 제목의 first-turn provenance를 보존하며 현재 ACL로 해당 turn을 가리면 제목도 서버에서 가린다.
   수동 이름 변경·기존 legacy 제목도 동일한 보수적 가림을 적용한다.
6. 취소·만료는 신규 쓰기/결합을 막는 상태 전이다. 실제 writer 종료·참조 인벤토리 전에는 원본을 보존한다.
7. 기존 질문이 있는 세션과 기존 계정·파일·환경을 유지한다. 빈 legacy는 차단 확정 후 초안으로 이관하고 감사 ID를 보존한다.

## 대안과 영향

세션을 먼저 만들고 목록에서 숨기는 방식은 빈 DB행을 없애지 못한다.
브라우저 메모리 첨부만 사용하는 방식은 새로고침·처리 상태 복원을 보장하지 못한다.
별도 외부 제목 호출이나 기존 prompt/schema 변경은 현재 전송 승인·프로파일 불변성·지연 계약을 확대한다.
이번 로컬 정책은 임의 장문의 일반 의미 요약을 보장하지 않는 한계가 있다.

새 API·DB migration·UI 상태 전이·legacy 보존·원자성 통합 검증이 필요하다.
구 API POST create는 인증/owner 경계를 확인한 뒤410 안내로 막고 프론트와 서버를 함께 반영한다.
구현 계약은 아키텍처/DB·개인정보 역할의 독립 검토를 반영했다. [실행 계획](../superpowers/plans/2026-09-30-first-question-conversation.md)에 따라 구현·검증한다. 이 ADR 작성만으로 본래 환경 적용을 뜻하지 않는다.
