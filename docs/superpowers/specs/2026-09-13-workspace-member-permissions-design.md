# 전사 공간 구성원 권한

- 상태: 2026-09-13 사용자 승인. 신규/기존 구성원 모두 소유자가 부여한 현재 권한을 사용한다.
- 상위 계약: [통합 파일함](2026-09-13-unified-cabinet-design.md) §4–6.
- 이번 구현은 서버 권한 관리와 파일 작업 선검사다. 소유권 이전·폴더 이동·휴지통·관리 UI는 다음 수직 슬라이스다.

## 소유자와 사용자

시스템 마스터는 전역 사용자 계정과 기술 권한을 관리한다. 전사 공간 소유자는 해당 공간의 OWNER membership으로
판정하며 로그인 사용자와 공간을 서버에서 확인한다. 전역 마스터 역할만으로 다른 공간 소유자가 되지 않는다.
공간 생성 시 생성자를 OWNER로 등록하는 기존 절차를 유지한다. created_by는 생성 이력이며 임의로 수정하지 않는다.
공간 소유자 변경은 이 API에서 허용하지 않는다. 개인 공간은 생성자 본인만 접근하는 기존 정책을 유지한다.

## 명시 권한과 전환

회사 membership에 read/write/delete를 명시 저장한다. read가 없으면 write/delete도 없어야 한다.
OWNER는 전체 권한 및 구성원 권한 관리 권한을 갖는다. MEMBER는 현재 저장된 부여값만 따른다.
기존 company MEMBER는 read/write 유지, delete 미부여로 migration한다. 새 MEMBER 기본값은 read만이다.
TEAM/TEMPORARY의 기존 동작은 이 단계에서 제한하지 않는다. 새로운 멤버십에 기존 부여값이 자동 복원되지 않는다.
membership을 물리 삭제하지 않고 권한을 빈 집합으로 철회할 수 있다. 권한 revision은 행에서 단조 증가한다.
OWNER의 권한 수정 및 역할 변경은 이 API에서 거부한다. owner 역할/권한 불일치는 전환 전에 검사한다.

## API와 감사

인증된 사용자는 GET /api/v1/workspaces/{workspace_id}/capabilities로 자신의 유효 권한을 읽는다.
응답은 read/write/delete/manage_members boolean이며 개인/전사 소유자와 일반 구성원을 구분한다.
전사 OWNER만 GET /api/v1/workspaces/{workspace_id}/members로 페이지 단위 구성원 목록을 조회한다.
표시는 사용자 ID·표시명·역할·활성 상태·부여값·permission_revision만 포함하며 암호/계정 권한 내부값은 제외한다.
PUT /api/v1/workspaces/{workspace_id}/members/{user_id}는 기존 등록 사용자에 대한 권한 부여/변경이다.
요청은 read/write/delete와 expected_revision(신규0, 기존현재값)을 필수로 받는다. bool이나 음수 revision은 거부한다.
신규 추가는 이미 존재하는 활성 계정에 한정한다. 시스템 계정 생성 및 전체 사용자 검색은 포함하지 않는다.
소유자 UI가 없으므로 이번 API를 사용자에게 CLI로 대신 실행하도록 요구하지 않는다.
후속 공간 구성원 UI는 로그인 작업소의 해당 파일함에서 manage_members로 진입을 제어한다.
전역 마스터 전용 /admin/system/access는 시스템 계정/기술 권한 관리로 유지하며 공간 OWNER에게 전체 관리자 접근을 부여하지 않는다.
멤버십 생성/권한 변경은 actor·target·workspace·이전/이후 권한·revision·시각의 감사 레코드와 원자적으로 저장한다.
대상 비접근/비소유자/비활성 계정은 404. 접근 가능한 대상의 stale revision은 409이며 자동 덮어쓰지 않는다.

## 읽기 및 쓰기 적용

새 read=false가 Platform 목록/문서/원문/Job 또는 RAG 검색·뷰어·도메인·평가·승인 경로를 우회하지 않도록
명명된 공통 SQL 조건을 기존 membership·active·personal 조건과 함께 적용한다. Platform은 RAG를 import하지 않는다.
ES의 membership ACL은 최종 권한 정본이 아니며 BM25/dense 후보 전에 DB read allowlist를 적용한다.
검색 준비 중 read 상태가 바뀌면 검색/외부 전송 전 최신 권한 검증으로 중단한다. 이미 전송된 답변의 회수는 보장하지 않는다.
upload/create_folder/upload_version은 write가 필요하다. capability 응답과 화면의 체크박스는 서버 검사를 대체하지 않는다.
스트리밍 전에 검사하고, 저장/Job commit 전에도 현재 write를 재검사하여 변경과 동일한 잠금으로 직렬화한다.
권한 잠금 순서는 workspace → membership이며 기존 승인 경로와 충돌하지 않게 유지한다.
이미 허용된 commit 뒤 철회가 발생한 순서는 정상이다. 철회 commit 뒤 시작된 저장은 거부한다.
권한이 없으면 영속 문서/Job을 남기지 않으며 새로 받은 임시 객체는 기존 실패 정리로 처리한다.
파일 삭제 권한 저장은 삭제 기능의 구현 완료를 뜻하지 않는다. 소유권/전송 승인/원본 버전은 변경하지 않는다.

## 검증과 적용

기존 backend/.venv 및 UUID 격리 PostgreSQL fixture만 사용한다. 실사용 DB migration과 서버 재시작은
별도 검증 후 적용 단계로 분리하고 이번 코드 작성 중에는 실행하지 않는다. 의존성·Docker·모델 호출은 추가하지 않는다.
TDD로 owner/member/master 다른 공간/개인/만료/read-only/write/권한 철회/stale CAS 행렬을 검증한다.
migration 전 기존 member 권한 보존, migration 후 신규 기본값, 감사 원자성, 동시 저장1건 성공/1건409를 확인한다.
기존 단위·격리 회귀, strict mypy·Ruff·OpenAPI 생성 및 독립 보안/코드 리뷰 후 수락한다.

권한 운영 이후 구 schema로 되돌리면 철회한 read가 구 membership 검사에서 다시 허용될 수 있다.
따라서 rollback은 단순 downgrade를 운영 복구로 안내하지 않는다. 권한 변경 이력이 생긴 DB는
정확한 사전 백업 복원과 API/worker 버전 조합을 별도 검토하며, 이번 자동 테스트는 격리 DB에서만 적용/복구를 다룬다.
