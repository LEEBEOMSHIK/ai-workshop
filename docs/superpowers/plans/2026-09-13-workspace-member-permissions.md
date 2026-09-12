# Workspace member permissions implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development with project-defined main-only, no-commit and temporary-artifact rules.

**Goal:** 전사 공간 소유자의 구성원 권한 관리 서버 계약과 실제 읽기/쓰기 enforcement를 함께 완성한다.
**Architecture:** Platform Workspaces가 권한 및 감사 저장을 소유한다. Assets와 RAG는 공통 권한 조건을 소비한다.
**Tech Stack:** 기존 FastAPI, SQLAlchemy, PostgreSQL, Python .venv. 새 의존성 없음.
**Spec:** docs/superpowers/specs/2026-09-13-workspace-member-permissions-design.md

## Global constraints

- main만 사용하고 기존 dirty 변경을 보존한다. commit/push/worktree 생성 없음.
- 실사용 DB·승인·모델·서버·Docker 변경 없음. migration 검증은 격리 fixture에서만 수행한다.
- 신규 MEMBER 읽기 기본, 기존 company MEMBER 읽기/쓰기 보존. 현재 소유자의 부여값을 정본으로 사용한다.
- UI와 소유권 이전, 휴지통은 다음 수직 슬라이스이며 이번 서버 완료와 구분한다.
- 작업 임시물은 .local-data/project-agent-work/workspace-member-permissions/ 안에 둔다.
- Windows MAX_PATH 영향을 피할 테스트 basetemp는 .local-data/pytest-tmp/wmp/ 아래의 명시한 실행별 경로도 허용한다.

## Task 1: 권한 저장·관리와 소비 경계

하나의 보안 기능 단위다. read 철회 API만 먼저 노출하지 않는다.
Files: platform/workspaces/{domain,models,repository,api,schemas}.py 및 책임 분리한 permissions 모듈,
backend/alembic/versions의 다음 연결 revision, platform/assets/{service,repository,library_repository,originals}.py,
platform/jobs/repository.py; labs/rag의 기존 membership 소비 지점. backend/tests/unit/platform/workspaces 및
격리 tests/integration/platform/workspaces/test_member_permissions.py. API 타입 생성물은 후속 검증 때 main이 갱신한다.

Interfaces: 현재 workspace 생성 계약 유지. spec의 capabilities/members GET 및 PUT 계약을 등록한다.
SQL 공통 read 조건은 actor UUID를 받아 기존 WorkspaceRecord 기준의 조건식을 생성한다.
쓰기 저장과 권한 변경은 같은 workspace→membership 잠금 순서와 트랜잭션을 사용한다.

- [x] 격리 테스트에서 owner/member/master 분리, readonly 쓰기거부, 신규기본/기존매핑, stale revision 실패를 먼저 작성·RED 확인.

```python
# 격리 실제 API/service 결과를 독립적으로 검증할 행렬
# owner가 member에게 read=True, write=False, delete=False 부여 후:
assert upload_response.status_code == 404
assert members_response.status_code == 200
# 같은 expected_revision으로 두 저장이 경쟁하면:
assert sorted(statuses) == [200, 409]
```

- [x] 명시 grant·revision·audit 모델 및 migration 구현. schema boolean strict validation, owner 변경금지.
- [x] capabilities 및 소유자 members 계약 구현. handler에 권한 정책을 넣지 않는다.
- [x] Platform/RAG read 소비와 Assets write commit 검사 구현. 권한 철회 경합을 실제 두 세션으로 검증.
- [x] 관련 기존 단위·격리 통합 테스트를 순차 실행하고 회귀 수정. 테스트 의미를 축소해 통과시키지 않는다.
- [x] backend cwd에서 Ruff 및 MYPYPATH=src strict mypy 실행. 실제 결과와 변경 파일을 보고서로 인계.

## Task 2: 독립 검증 및 인계

Files: WORKBOARD.md, 작업 기록, frontend API 생성물(계약 생성만; UI 아님).
- [x] 독립 리뷰어가 Task1 diff·spec·report를 검토하여 사양/품질 판정. 수정은 구현자에게 돌린다.
- [x] main은 새 권한 핵심 격리 검증 재실행, API 생성/check, 실제 DB 무변경과 적용 미실시를 기록한다.
- [x] WORKBOARD 최근 완료 최대5개를 유지하고 다음 관리 UI·실사용 migration 단계를 구분해 인계한다.

검증 명령: backend/.venv/Scripts/python.exe -B -m pytest -c backend/pyproject.toml 명시된_격리파일.
pytest cacheprovider는 기존 설정대로 비활성. Codex/SQLite 경로 계약을 위해 짧은 일반 Windows basetemp를 사용한다.
계획 self-review: Task1 모든 구현을 한 담당자가 소유하고 Task2는 생산 코드 수정 없이 독립 검증한다.
API 생성물은 Task1 계약이 확정된 뒤만 갱신한다. 테스트·문서가 런타임 적용을 주장하지 않도록 구분한다.
