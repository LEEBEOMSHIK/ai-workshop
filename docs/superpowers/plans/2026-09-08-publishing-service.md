# Publishing 서비스 구현 계획

승인 정본: `../specs/2026-09-07-public-study-management-design.md`.
기존 package/domain/projection 계약을 보존한다. main에서 진행하며 커밋·push하지 않는다.

## 공통 제약과 성공 기준

관리자가 공개 편집본을 저장·미리보기·게시·철회하고 방문자는 게시본만 읽는다.
게시 중 편집은 현재 공개본을 바꾸지 않는다. 충돌과 적용 실패는 완료로 가장하지 않는다.
공개 plain-text snapshot에는 비공개 원본·계정·경로·로그를 포함하지 않는다.
독립 공개 reader는 private Settings/DB/Identity를 가져오지 않는다.
같은 Windows 사용자 로컬 기능 검증과 OS 접근권한 격리 검증은 구별한다.
새 모델·외부 API·Docker 서비스·라이브러리는 추가하지 않는다.

## 저장과 실행

비공개 PostgreSQL에 불변 revision·승인·명령 outbox를 동일 트랜잭션으로 저장한다.
별도 SQLite 공개 파일에는 snapshot/tombstone과 본문 없는 멱등 fingerprint만 저장한다.
로컬 private applicator만 쓰고 public reader는 mode=ro로 읽는다. 운영은 수동 전달/receipt다.
적용 확인 전에는 대기 상태이며 공개 mutation HTTP를 만들지 않는다.
관리자 변경에는 기존 owner 인증과 별도 Origin/JSON/custom header 검사를 적용한다.
기존 구현에는 명시적인 CSRF 검사가 없어 단순 재사용으로 기록하지 않는다.

## Task 1: 영속 공개 projection

신규 Publishing `public_store.py`, `test_public_store.py`.
SqlitePublicStudyWriter(path).initialize()/apply(command),
SqlitePublicStudyReader(path).get(slug)/list_published(topic_key=None).
불변 receipt는 slug/sequence/request_id/action이다. 실제 임시 SQLite로 재시작,
원자성, 멱등 키 충돌, sequence 역전, 철회 후 재시도, digest 손상, 읽기 전용을 TDD 검증한다.

## Task 2: 비공개 저장·서비스·API와 독립 공개 API

Publishing models/repository/service/api/settings, 0025 migration, public_app 추가.
main에는 owner router만 등록한다. revision lock/outbox 원자성과 재시도/receipt를 검증한다.
독립 공개 app은 SQLite 조회만 제공하며 응답은 no-store다.
미게시·철회·미존재는 동일한 404. 실제 PostgreSQL은 격리 테스트 DB에서 검증한다.

## Task 3: 관리자/공개 UI와 연구실 연결

Publishing feature, `/admin/publishing`, `/labs/rag/studies`, `/studies/[publicSlug]`,
공통 plain-text renderer와 공개 API client, 관리자 메뉴·RAG NPC 링크를 연결한다.
미리 본 revision/hash 게시, 편집 보존, 409, 적용 대기/철회를 UI 테스트한다.
공개 client는 private API fallback을 금지한다. 공개 실행 모드는 루트 env를 읽지 않는다.
현재 통합 로컬 실행은 개발용이며 OS 격리된 운영 배포가 아니다.
Vitest/TypeScript/ESLint/Next build를 검증한다.

## Task 4: 후보 편집본과 실제 실행 검증

worklogs/Learning 후보를 검토하고 각 처리 상태를 기록한다. 원본 전체를 게시하지 않는다.
DB migration/서버 상태를 확인한 후 host 로컬 실행을 유지한다.
owner 저장→미리보기→공개→익명 목록/상세/NPC→철회→동일 URL 404→재공개를 검증한다.
실제 격리 적용은 별도 권한 확인과 검증이 필요하다. 합성 자료 정리는 CACHE_POLICY를 따른다.
독립 최종 리뷰 후 WORKBOARD 최근 완료 최대 5개를 유지하며 사용자 테스트를 요청한다.

## 검증

backend: `.venv/Scripts/python.exe -m pytest tests/unit/platform/publishing -q`,
`.venv/Scripts/python.exe -m ruff check src/ai_workshop/platform/publishing`,
`.venv/Scripts/python.exe -m mypy src/ai_workshop/platform/publishing`.
통합 시 전체 unit/contract, 새 PostgreSQL integration과 frontend 기존 명령을 실행한다.
오프라인 테스트 SECRET_KEY는 합성 process 환경값만 사용한다.
