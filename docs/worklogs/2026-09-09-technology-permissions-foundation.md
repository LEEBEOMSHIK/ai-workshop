# 기술별 권한 기반·마스터 관리 화면

- 상태: 코드 검증·로컬 전환·로그인 후 관리 화면 표시 확인. 기존 합성 계정 정리 조사 필요, 사용자 권한 변경 없음.
- 설계: [권한 계약](../superpowers/specs/2026-09-09-technology-permissions-design.md)
- 결정: [ADR-0022](../decisions/0022-technology-permissions.md)
- 계획: [1단계 구현 계획](../superpowers/plans/2026-09-09-technology-permissions-foundation.md)

## 범위와 이유

기존 owner의 표시명을 마스터로 사용하며, 마스터만 기존 사용자의 역할·활성 상태와
기술별 조회/설정/실행 권한을 관리한다. 설정/실행은 조회를 요구하지만 서로 포함하지 않는다.
권한 저장 기반과 관리 화면을 먼저 검증하고 기존 RAG 경로 개방은 후속으로 분리한다.
기존 API의 owner 검사를 일괄 제거하면 민감 설정과 외부 전송 권한이 함께 노출될 수 있기 때문이다.

## 보존할 경계

- main의 기존 변경을 보존한다. 별도 worktree, 커밋, push는 수행하지 않는다.
- 기술 권한은 사용자 공간·문서·외부 전송 승인 권한을 확대하지 않는다.
- 준비 중인 Lab과 사용자 가입/초대 기능은 만들지 않는다.
- 실제 DB migration·서버 재시작은 검증 후 사용자 별도 승인으로 수행했다. 계정 변경은 제외한다.
- 합성 통합 테스트는 전용 격리 DB에서만 수행한다.

## 검증과 인계

이 절은 실제 전환 전 코드 검증 시점의 기록이다. 최신 활성화 결과는 마지막 절을 따른다.

백엔드/API·DB와 프론트 관리 UI 구현 및 작업별 독립 보완 재검토를 완료했다.
전체 변경의 최종 독립 재검토도 통과했으며 실사용 활성화는 별도다.
첫 서버 구현은 메인 재실행 50건·타입·린트 및 API 타입 일치 검사를 통과했다.
기존 Starlette TestClient/httpx 경고 1건을 유지한다. 독립 검토에서 아래 두 사항을 발견해
보완했다. 첫 50건만으로 서버 단계 완료로 처리하지 않고 추가 회귀·재검토를 거쳤다.

- READ COMMITTED에서 역할/상태·revision·grant를 서로 다른 시점에 읽어 오래된 값에
  새 revision이 붙을 수 있었다. 단일 SQL과 페이지 CTE로 revision에 속한 표현을 같은 snapshot에서 읽는다.
- 비활성 사용자의 유효 권한은 비어 있으므로 이를 감사에 사용하면 저장된 grant 변경이
  기록에서 사라졌다. 감사는 실제 저장값을 기록하고 관리 조회의 저장값과 유효 접근을 구분했다.

보완 후 메인 재실행: 관련 55건(26.39초, 기존 경고 1건), 수정 모듈 mypy·Ruff 통과.
API 타입 생성·일치 검사 통과. 독립 재검토에서 두 항목 모두 해결·새 필수 수정 없음으로 승인됐다.
새 migration은 `0030_technology_permissions`이며 이전 revision은 `0029_codex_verification`이다.
검증은 전용 격리 DB에서만 수행했고, 실사용 DB는 아직 변경하지 않았다.

프론트 첫 구현은 메인 회귀 58건·타입·린트를 통과했다. 독립 리뷰에서 재조회 실패 후
오래된 revision으로 계속 저장 가능한 상태와 이에 대한 실패/중복 제출 테스트 누락,
확인창의 키보드 격리·초점 복귀 누락을 발견했다. 편집 잠금/명시적 재조회와 접근성을 보완했다.
추가 재검토에서 저장 성공 후 opener가 비활성화되면 초점이 body로 빠지는 사례를 확인했고,
dialog 수명 동안 opener를 유지하며 부적합하면 상세 제목으로 복귀하도록 수정했다.
이 경로도 RED로 재현한 뒤 GREEN과 독립 재검토를 통과했다.
최종 보완에서 사용자 전환 시 이전 메시지와 늦은 실패 응답을 격리하고 초기화 감사 제목을 수정했다.
구 API writer 중지 → migration → 같은 버전 서버 시작 순서도 명시했다.
메인 최종 재실행: 백엔드55건(27.17초, 기존 경고1건), 프론트65건/12파일(49.28초).
전체 프론트 타입·변경 TSX 린트, 백엔드 변경10모듈 mypy·관련 Ruff와 API 타입 일치 검사를 통과했다.
최종 독립 재검토에서 선택한 지적은 모두 해결됐고 새 Critical/Important 문제는 없었다.
실제 DB 반영과 브라우저 검증은 수행하지 않았다.

아직 권한 관리 화면의 실제 사용이나 전체 RAG 위임 기능 완료를 의미하지 않는다.
실행 추적: `.local-data/project-agent-work/technology-permissions-foundation/progress.md`.

## 실제 반영 승인 후 확인 순서

아래 항목은 운영 승인 요청에 포함할 순서이며 이 구현 작업에서 실행하지 않았다.

1. 정확한 대상 DB, 백업 산출물·복원 대상, 중단 시간과 함께 배포할 backend/frontend 버전을 승인받는다.
2. 신규 setup/identity 쓰기를 차단하고 구 API의 진행 중 쓰기를 drain한다. 구 API와 구 버전
   `bootstrap-owner`·CLI·자동화 writer를 모두 중지하며, 구·신 backend writer를 병행하지 않는다.
3. writer 중지를 확인한 뒤 승인된 `0030` migration을 적용하고 DB revision이
   `0030_technology_permissions`인지 읽기 전용으로 확인한다. migration 뒤 구 bootstrap을 사용하지 않는다.
4. revision 확인 후 같은 릴리스의 새 backend와 frontend만 시작한다. 새 UI와 구 API의 조합은
   권한 route가 없어 사용할 수 없는 상태이며 활성화가 아니다.
5. health, setup 완료 상태, 기존 마스터 로그인 응답과 `/admin/system/access`의 사용자·마스터 표시·
   변경 이력을 읽기 전용으로 확인한다. 마스터 한 명이면 강등·비활성화 보호와 `적용 준비 중`인
   RAG 위임 표시를 확인하되 실사용 권한은 변경하지 않는다.
6. migration 또는 시작 실패 시 검토되지 않은 downgrade, 데이터 삭제, 사용자 수리나 호환되지 않는
   구 writer 재시작을 하지 않는다. 승인된 백업·복원 계획과 원인 검토 뒤 후속 조치를 다시 승인받는다.
7. 두 번째 기술을 등록하기 전에는 다중 기술 PUT의 부분 성공을 권위 상태로 재조회·설명하는 복구와
   첫 PUT 성공/둘째 PUT 실패 회귀를 먼저 구현한다. 현재는 가짜 Lab이나 두 번째 기술을 등록하지 않는다.
8. 사용자 추가/초대 및 실제 RAG 위임 경로 연결은 별도 후속으로 진행한다.

## 로컬 전환 결과 — 2026-09-09

- 사용자가 백업·DB 반영·호스트 프론트/백엔드 재시작을 승인했다.
- 대상은 기존 `ai-workshop-postgres-1`의 loopback15432 `ai_workshop_local_clean` DB 하나다.
  main HEAD `9082bb55d61665d4613c9ba9e91cb4d02cbfc9aa`와 검토된 미커밋 권한 변경을 사용했다.
  다른 DB, 볼륨, 원문 파일과 모델은 변경하지 않았다.
- 프론트22308/13572/12640과 구 API23936/23928을 중지하고 다른 프로젝트 writer 및
  대상 DB의 남은 연결0을 확인한 뒤 백업했다. 코드 변경이나 자동 bootstrap은 실행하지 않았다.
- 백업: `.local-data/backups/permission-cutover-20260909/database.dump`, 409,785 bytes.
  SHA-256: `6780a5a6af4525737aca695489a17640db17d53c9616bbb9036072fb8c42044a`.
  PostgreSQL custom archive의 목록 검사497줄과 컨테이너/호스트 해시 일치를 확인했다.
  실제 복원 시험은 하지 않았다. 백업에는 비공개 DB 자료가 포함되므로 Git 제외로 보존한다.
  컨테이너 `/tmp/ai-workshop-permission-cutover-20260909.dump` 복사본도 보존했다.
- 명시적 `0029_codex_verification` → `0030_technology_permissions` 적용 성공.
  singleton1/initialized=true, 사용자6/권한 revision행6/비영 revision0/grant0/audit0을 확인했다.
  기존 사용자 ID·역할·활성 상태의 집계 해시가 전후 동일하다. 계정 생성·권한 변경 없음.
- 호스트 API launcher4712와 frontend launcher5832를 숨김 실행했다. 앱 Docker 추가 없음.
  API health200, setup200/false, 프론트 login200 및 proxied setup200/false 확인.
  활성 로그는 `.local-data/project-agent-work/technology-permissions-foundation/*-cutover.*.log`에 보존한다.
- 현재 브라우저는 로그인 화면이다. 로그인 응답·마스터 상세 UI의 실계정 확인은 사용자 재로그인 후
  이어간다. 실제 권한 변경으로 테스트하지 않으며, RAG 일반 사용자 위임은 여전히 후속이다.
- 독립 검증의 credential 없는 GET11개도 통과했다. 권한 API는401/private no-store,
  관리 페이지는307/login 이동으로 비인증 접근을 차단한다. 백업 크기·SHA-256도 독립 확인했다.
- 복원 시 이 단일 DB 백업을 대상으로 별도 승인·원인 검토가 필요하다. 자동 downgrade/복원은 하지 않는다.

## 로그인 후 읽기 전용 확인

- 사용자 로그인 후 Chrome `/admin/system/access`에서 마스터 표시·로그아웃 버튼·사용자6명,
  선택된 마스터의 활성 상태/revision0, RAG 조회·설정·실행 상속과 `적용 준비 중`, 변경 이력 없음 표시 확인.
- 저장·비활성화·강등·로그아웃은 실행하지 않았다. 마지막 마스터 보호를 실계정으로 시험하지 않았다.
- 기존5개 계정이 Synthetic Supersession/Embedding/Alias Parity 이름이며 모두 활성 마스터다.
  해당 이름이 ingestion/indexing 통합 테스트 소스와 일치한다. 생성 시점·실행 경로 및 참조 데이터는
  아직 확정하지 않았으므로 임의 삭제/비활성화하지 않았다. 이 계정들은 0030 적용 전부터 존재했다.
- 따라서 현재는 활성 마스터가 여러 명이라 본인 강등/비활성화 버튼이 표시된다.
  개인 단일 마스터 운영을 위해 기존 합성 계정의 생성·잔존 원인과 안전한 정리 범위를 별도 조사해야 한다.
