# ADR 0019: 개발·실험 기록은 승인된 공개 snapshot으로 전달한다

- 상태: 상세 설계 승인 / 기반 계약 구현·검증 완료, 저장·API·UI 후속
- 정본: [공개 관리 설계](../superpowers/specs/2026-09-07-public-study-management-design.md)
- 첫 실행 계획: [Publishing 계약](../superpowers/plans/2026-09-07-publishing-contracts.md)

## 결정

Platform Publishing의 편집본·승인과 공개 저장소의 제공 상태를 분리한다. Learning 원본의
공개 플래그로 익명 조회하지 않는다. 관리자에게 공개/비공개 행동을 제공하되 적용 확인 전에는
완료로 표시하지 않는다. 초기 기존 RAG 기록의 공개 준비는 승인됐고 이후 기록은 비공개다.

승인은 canonical UTF-8 JSON package의 SHA-256에 귀속한다. 본문은 첫 버전에서 plain text로
표시하고 HTML/Markdown 실행·이미지 요청·자동 링크화를 하지 않는다. digest는 발신자 인증이
아니므로 실제 importer와 저장 어댑터를 연결할 때 별도 신뢰·권한 경계를 검증한다.

철회는 증가하는 sequence를 가진 body 없는 tombstone이다. 뒤늦은 낮은 sequence의 게시가
철회를 되돌리지 못한다. 재공개는 재승인과 새 sequence로 수행한다. 상세한 상태·데이터 계약은
정본 설계와 첫 실행 계획을 따른다.

## 구현 단계

먼저 불변 package·승인·명령·공개 projection의 순수 계약을 단위 검증한다. 이 단계는 영속 저장,
API 인증, 실제 배포 철회, 관리자 UI 또는 공개 게시를 구현한 것으로 간주하지 않는다.
로컬 및 운영 공개 저장 어댑터는 후속 단계에서 분리 실행·접근권한·원자성 검증을 거쳐 연결한다.

## 저장·실행 구체화 (2026-09-08)

비공개 PostgreSQL revision/outbox와 별도 SQLite 공개 projection을 사용한다.
공개 reader는 private 설정·DB를 import하지 않고 읽기 전용으로 연결한다.
실행 계획: [Publishing 서비스](../superpowers/plans/2026-09-08-publishing-service.md).
같은 Windows 사용자 로컬 실행은 OS 파일 접근 격리의 증거가 아니다.
운영 격리 완료 판정 전에는 계정/ACL 등 실행 경계의 별도 검증이 필요하다.
기존 인증에 명시적인 CSRF 검사가 없어 Publishing 변경 API에 이를 보완한다.

## 대기 요청의 관리자 복구 정보

현재 편집본과 적용 대기 명령이 참조하는 버전은 다를 수 있다. 따라서 현재 편집본의
revision/digest로 과거 요청을 추정해 재시도하지 않는다. owner 전용 관리 응답에
`pending_command: {action, expected_revision, expected_digest, request_id} | null`을 포함한다.
이는 최신 미적용 명령의 불변 정보이며 실제 저장된 outbox에서만 가져온다. 적용 완료 시 null이다.
공개 snapshot/API에는 포함하지 않는다. 새로고침·재선택 후에도 동일 요청을 복구하고,
오래된 요청의 응답은 요청 당시 의도가 아닌 서버가 반환한 현재 적용 상태로 안내한다.

## 공개 목록 페이지 조회 (2026-09-08)

목록 화면은 공개 projection만 사용하는 서버 필터·페이지 조회를 제공한다.
기존 담당자 관련 기록 조회 계약은 보존하고 별도 study-catalog endpoint를 추가한다.
기술 주제 facet과 총 건수는 공개 상태만 세며 같은 읽기 트랜잭션에서 페이지를 선택한다.
선택 페이지의 무결성 오류는 서비스 오류로 드러낸다. 탐색 상태는 검증된 page/topic URL로
보존하며 외부 return URL은 허용하지 않는다. [조회 계약·검증](../worklogs/2026-09-08-study-pagination.md) 참조.
