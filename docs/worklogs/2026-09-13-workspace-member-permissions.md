# 전사 공간 구성원 권한 — 서버 구현

## 승인 범위

[설계](../superpowers/specs/2026-09-13-workspace-member-permissions-design.md)와
[구현 계획](../superpowers/plans/2026-09-13-workspace-member-permissions.md)을 따른다.
시스템 마스터와 공간 OWNER는 별도다. 신규 구성원은 읽기 기본이며, 이후 신규/기존 구분 없이
공간 소유자가 부여한 현재 read/write/delete가 정본이다. 기존 company MEMBER의 읽기/쓰기는 migration에서 보존한다.

## 구현

- Workspaces: 명시 grant·permission_revision·불변 감사 기록, 공간 소유자 전용 구성원 조회/권한 저장.
- API: 현재 capability GET, 페이지 단위 members GET, expected_revision을 받는 member PUT.
  전역 마스터만으로 다른 공간을 관리할 수 없고, 소유권 이전/OWNER 수정/시스템 계정 생성은 제공하지 않는다.
- Assets: 쓰기 선검사 및 업로드 후 commit 전 workspace→membership 잠금·현재 권한 재검사.
  철회된 업로드는 문서/버전/Job을 남기지 않고 새 객체를 정리한다.
- Platform/RAG: 파일함·원문·Job·도메인·구성·사용자 평가/승인 경로에 공통 현재 read 조건을 적용한다.
  평가 worker의 불변 스냅샷 재현성 계약은 유지한다.
- 검색: 문맥 해석 전, 검색 범위 확정, 질의 임베딩 후 후보 검색 직전, 최종 생성 전에 현재 접근을 확인한다.
- migration `0033_workspace_permissions`: 기존 grant 보존, 신규 기본값, personal 소유자 불일치 사전 중단,
  감사 이력이 생긴 뒤 downgrade 차단. 실사용 DB에는 아직 적용하지 않았다.
- frontend는 OpenAPI 타입 생성물만 갱신했다. 화면에 가짜 권한 저장 버튼을 노출하지 않는다.

## 검증 증거

구현과 독립 보안/코드 리뷰를 분리했다. 1차 리뷰의 Important 1건은 임베딩 계산 중 read 철회가
후보 조회 전에 감지되지 않는 경합이었다. 실패 테스트 후 계산 직후 재검사를 추가하고 재리뷰에서 해결을 확인했다.
최종 서버 사양·품질 리뷰에 새 Critical/Important는 없다. UI/배포 검증을 뜻하지 않는다.

- 구현 담당 전체 단위: 2,035 passed / 4 skipped, 116.17초, 기존 Starlette/httpx 경고 1건.
  main이 JUnit 원문 tests=2039/failures=0/errors=0/skipped=4를 확인했다.
- 구현 담당 격리 회귀: 35 passed, 69.78초. permission6·migration2와 기존 파일함/원문/개인/승인 요청 회귀를 포함한다.
- main 검색 경계 단위 재실행: 2 passed, 2.42초.
- main 권한/migration 격리 재실행: 8 passed, 19.22초.
- 구현 담당 기존 Codex 승인 저장소 격리: 43 passed, 92.10초. 앞선35건과 합쳐 서로 다른 격리 회귀78건이다.
- main frontend api:generate, api:check, typecheck: exit0.
- 구현 담당 strict mypy: 267개 소스 파일 통과. 변경 Python37파일 대상 Ruff 통과.
- 최종 formatting 후 관련 단위55건 통과(2.35초), 대상 git diff 공백 검사 exit0.

검증 한계: RAG 원문/source·viewer 및 평가 전체 경로의 권한 철회 실DB 행렬을 모두 개별 실행한 것은 아니다.
해당 경로는 공통 SQL 조건·단위 테스트·독립 코드 리뷰로 확인했다. UI 및 실제 배포 후 수용 검증은 남아 있다.

main 재검증 명령:

```powershell
backend/.venv/Scripts/python.exe -B -m pytest -c backend/pyproject.toml backend/tests/unit/platform/workspaces/test_permission_search_boundary.py -q --tb=short
backend/.venv/Scripts/python.exe -B -m pytest -c backend/pyproject.toml backend/tests/integration/platform/workspaces/test_member_permissions.py backend/tests/integration/platform/workspaces/test_member_permissions_migration.py -q --tb=short --basetemp=C:/projects/ai-workshop/.local-data/pytest-tmp/wmp/main-1
pnpm --dir frontend api:check
pnpm --dir frontend typecheck
```

검증에는 기존 backend/.venv와 UUID 격리 DB fixture만 사용했다. 새 환경·의존성·모델 호출은 없다.
전체 단위 첫 실행은 extended Windows 경로와 Codex/SQLite 경로 계약이 충돌했고, 테스트 double 보완이 필요한
2건도 있었다(167 failed / 1853 passed / 4 skipped). 다음 짧은 경로 실행은 부모 경로 누락으로 setup 오류가 났다.
부모 생성 및 대표 Codex/SQLite/Asset 검사 후 `.local-data/pytest-tmp/wmp/u3`의 일반 경로로 최종 전체 통과를 확인했다.
초기 실패를 기능 통과로 계산하지 않았으며, 경로 문제를 우회하려고 제품의 경로 보안 정책을 완화하지 않았다.

## 데이터 및 실행 경계

main이 작업 전후 users/workspaces/workspace_memberships/documents/asset_versions/승인 상태/승인 이벤트
7개 테이블의 건수·행 지문 및 alembic revision을 읽기 전용으로 대조해 동일함을 확인했다.
실사용 DB는 `0032_evidence_approval_requests`이며 자동 migration이나 API/worker 재시작을 하지 않았다.
기존 API18000 및 frontend5173 health200만 확인했다. 신규 API가 실행 중 서버에 반영됐다는 뜻은 아니다.
테스트 임시물의 정확한 후보는 작업 기록에 분리하며 CACHE_POLICY 승인 없이 광역 정리하지 않는다.

## 다음 단계

공간 소유자가 해당 파일함에서 구성원별 권한을 조회·저장하는 작업소 UI를 연결한다.
전역 마스터 전용 시스템 계정 관리는 기존 관리자 영역에 유지한다. UI 연결 후 승인된 유지보수 순서로
백업·복원 검증 및 실사용 migration/API·worker 적용을 수행한다. 사용자가 CLI로 권한을 대신 등록하게 하지 않는다.
파일 이름 변경·이동·휴지통·복원, 실제 PDF/OCR·LLM 대화 수용은 별도 단계다.
