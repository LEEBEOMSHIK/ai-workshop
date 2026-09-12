# Personal workspace isolation implementation plan

> **For agentic workers:** Use the approved project-agent implementation/review split and TDD. Work on main as explicitly requested; do not create a worktree or commit.

**Goal:** 통합 파일함 쓰기 확장 전에 개인 원문 접근을 소유자 본인으로 제한한다.
**Architecture:** Platform의 기존 SQL 접근 조건에 개인 생성 소유자 조건을 공통화한다. RAG는 Platform 정책을 소비할 수 있지만 Platform은 RAG에 의존하지 않는다.
**Tech Stack:** 기존 Python/FastAPI/SQLAlchemy/PostgreSQL 및 backend/.venv.
**Spec:** docs/superpowers/specs/2026-09-13-unified-cabinet-design.md §4와 docs/decisions/0023-domain-cabinet-conversation.md.

**Status:** Task 1·2 검증 완료. 승인 요청은 기존 가드가 충분하여 production 수정 없이 회귀를 확장했다.
main 격리27·단위86 통과, 대상 Ruff·전체 production strict mypy265·독립 리뷰 통과.
API18000 반영 및 health 확인 완료. 아래는 계획 당시 체크리스트이며 완료 증거와 한계는
[작업 기록](../../worklogs/2026-09-13-personal-workspace-isolation.md)을 따른다.

## Global constraints

- 사용자 문서·계정·권한·승인과 실행 DB를 변경하지 않는다. 모델 호출·새 의존성·UI 쓰기 버튼·migration을 추가하지 않는다.
- 기존 membership과 temporary 만료를 유지하면서 personal.created_by==actor를 추가한다. global 관리자 역할로 우회하지 않는다.
- 권한 없는 목록은 제외하고 정확한 원문/폴더/문서 요청은 기존 404 비노출 계약을 유지한다.
- 회사 read/write/delete 분리, capability, CAS와 휴지통은 후속 단계다. 현재 회사/team 동작을 임의로 축소하지 않는다.
- has_personal은 생성 중복 방지이므로 본인이 생성한 개인 공간 존재를 판단한다. 타인 공간 membership을 자기 공간으로 오인하지 않고, 본인 membership 누락을 새 공간 자동 생성으로 복구하지 않는다.
- 기존 .venv 및 격리 DB fixture를 재사용한다. 실사용 DB에 합성 계정을 넣거나 전체 통합 suite를 무차별 실행하지 않는다.

## Task 1: Platform 접근 경계

Files: platform/workspaces/repository.py, platform/assets/{repository,library_repository,originals}.py, platform/jobs/repository.py; 필요 시 Platform 내부 SQL 접근 helper. 기존 tests/integration/platform/assets/{test_asset_library,test_asset_originals}.py 및 연관 테스트.

- [ ] 합성 소유자 A, 타인 B, global 관리자 C를 만들고 A의 personal 공간에 B/C membership을 명시 부여한 격리 fixture로 RED를 확인한다.
- [ ] 목록/폴더/문서/버전/preview/PDF page/download와 업로드/새폴더/새버전 경로에서 B/C가 거부되는지 검증한다. A와 company/team 정상 경로는 유지한다.
- [ ] 사전 독립 검토에서 발견한 GET /api/v1/jobs/{job_id}의 개인 처리 상태·오류 metadata도 같은 조건으로 차단한다. 구현 역할·실사용 DB 구조는 바뀌지 않는다.
- [ ] 기존 workspace_is_active와 함께 적용할 명명된 SQL predicate를 사용한다.

```python
or_(WorkspaceRecord.kind != WorkspaceKind.PERSONAL,
    WorkspaceRecord.created_by == actor_id)
```

- [ ] has_personal의 존재 판정은 created_by==actor로 검사하고 본인 membership 누락/타인 membership 사례를 분리한다.
- [ ] 기존 단위 및 격리 integration 검증을 통과시키고 대상 ruff/mypy를 실행한다.

## Task 2: 간접 접근 및 독립 검증

Files: labs/rag/generation/evidence_approval_request_access.py, evidence_approval_requests.py와 관련 테스트(실제 접근 누락이 확인된 경우에만); RAG domain/retrieval은 일치/회귀를 검토한다.

- [ ] 사용자 문서 승인 요청 생성/목록/context에도 개인 소유자 조건이 적용되는지 확인한다. 명시적인 별도 관리자 검토 권한을 일반 파일함 우회와 혼동하지 않는다.
- [ ] 누락이 있으면 사용자 접근 경계만 같은 공통 predicate로 수정하고 합성 부정 권한 회귀로 검증한다. 외부 전송 승인 세대/상태를 바꾸지 않는다.
- [ ] 독립 보안 리뷰로 direct/indirect 경로와 Platform→Labs 의존 없음, RAG 선필터 유지, 회사/임시 회귀를 확인한다.
- [ ] main은 관련 검증 결과와 WORKBOARD를 갱신한다. 실제 서버 반영 여부와 남은 쓰기 권한/관리 기능을 구분한다.

## 검증 실행 원칙

`backend/.venv/Scripts/python.exe -B -m pytest -c backend/pyproject.toml <명시된 단위/격리 통합 파일>`을 순차 실행한다.
pytest cacheprovider는 기존 설정대로 끄며 새 테스트 환경을 만들지 않는다. 테스트 임시 파일은 작업 전용 경로에만 둔다.
`backend/.venv/Scripts/ruff.exe check --no-cache --config backend/pyproject.toml <변경 파일>`과 기존 strict mypy를 사용한다.
실사용 DB 및 승인 상태 불변을 확인한다. 실행 환경이 막히면 코드 검사 성공을 실제 통합 통과로 보고하지 않는다.
