# 비공개 Learning 1단계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로그인 사용자가 자유 메모와 구조화 실험을 저장·수정·분류·보관하고 허용된 RAG 평가 실행을 연결한다.

**Architecture:** Platform Learning은 기록·revision·일반 참조 계약을 소유한다. RAG 참조 해석은 조립부에서 주입하고 기존 identity·SQLAlchemy·OpenAPI·Next.js 작업소 패턴을 재사용한다. 공개 저장소와 학습 런타임은 생성하지 않는다.

**Tech Stack:** 기존 Python 3.13, FastAPI, SQLAlchemy/Alembic, PostgreSQL, Next.js/React, TypeScript, pytest/Vitest.

**Spec:** [승인된 상세 설계](../specs/2026-09-07-learning-service-link-design.md)

## Global Constraints

- 모든 작업 기록은 기본 비공개다.
- Platform은 RAG의 모델·실행 타입을 import하지 않는다.
- 주제 목록·라벨·관련 기능은 명시적 registry/저장 데이터로 관리한다. UI 분기와 모델명을 하드코딩하지 않는다.
- 연결 생성·조회·미리보기마다 대상 권한을 검증하며 비허용 대상의 제목·본문도 복제하거나 노출하지 않는다.
- 수정은 revision 충돌을 검출하고 조용히 덮어쓰지 않는다. 첫 버전은 보관/복원으로 관리한다.
- Codex 잔여 위험 수용, 외부 전송·학습 실행 승인은 이 문서 승인으로 대체하지 않는다.
- main에서만 작업한다. 기존 변경을 보존하며 새 worktree·Docker 변경·모델 다운로드는 하지 않는다.
- 실제 사용자 기록을 테스트에 사용하지 않는다. DB 검증은 정확히 식별한 전용 테스트 DB에서만 수행한다.
- 각 단계 RED→GREEN→관련 회귀 검증. 독립 리뷰 후 메인 담당만 staging/commit/push를 결정한다.

## 범위와 계약 결정

1단계는 note/experiment 두 종류다. 문제 해결 항목은 experiment의 선택적 구조 필드로 제공한다.
메모→실험 전환은 동일 record의 새 revision이며 이전 메모를 revision 이력에서 복구 가능하게 보존한다.
평가·학습 실행은 트리거하지 않는다. RAG 평가는 기존 실행 ID 참조이며 임의 URL·파일 경로는 참조로 받지 않는다.
첫 렌더러는 본문을 React 텍스트로 표시한다. Markdown 원문 입력은 가능하지만 HTML 실행·이미지 자동 로딩·원격 fetch는 없다.
phase 2의 풍부한 Markdown 렌더링, 공개 snapshot·캐릭터 링크·Publishing API는 별도 계획이다.

### API 계약

모든 경로는 `/api/v1/learning` 아래이며 `get_current_user`를 사용한다. owner도 타인 기록에 대한 우회 권한이 없다.

| 메서드·경로 | 계약 |
|---|---|
| GET `/topics` | 활성 topic `{key,label}` 목록. RAG·파인튜닝을 기술 주제로 제공 |
| POST `/records` | `LearningDraft` 입력, 서버가 actor/revision=1 부여, 201 |
| GET `/records` | actor 필터 선행, topic/kind/archived 필터와 limit/cursor, 본문 없는 목록 |
| GET `/records/{id}` | 현재 revision과 권한을 재확인한 참조 표시 |
| GET `/records/{id}/revisions/{revision}` | 동일 소유권 검사, 과거 원문과 참조 권한 재검증 |
| PUT `/records/{id}` | `expected_revision`+전체 draft, compare-and-swap, 200 또는 409 |
| POST `/records/{id}/archive` | `expected_revision`, 보관 및 revision 증가 |
| POST `/records/{id}/restore` | `expected_revision`, 복원 및 revision 증가 |

비로그인 401, 타인/없는 record 404, revision 충돌 409 `learning_revision_conflict`,
업무 규칙 입력 오류 422 `learning_invalid_input`, 공통 스키마 검증 오류 422 `validation_error`,
신규 비허용 참조 422 `learning_reference_unavailable`. 기존 공통 오류 handler는 변경하지 않는다.
과거 참조가 사라지면 record는 200, 참조는 `unavailable` 및 민감 정보 없는 표시로 반환한다.
편집용 draft에서도 비허용 참조와 중첩 dataset 참조를 제외하고 개수를 안내한다. 저장된 이력은 유지한다.
해당 draft를 저장할 때 UI는 접근 불가 연결이 제외됨을 명시 확인받는다.
보관된 기록 편집은 409 `learning_record_archived`; 먼저 복원해야 한다. 영구 DELETE는 없다.
페이지 cursor는 actor·filter에 귀속된 검증 가능한 형식이며 다른 사용자의 데이터 위치를 노출하지 않는다.

## 파일 지도

- 새 backend `platform/learning/{__init__,domain,schemas,repository,models,service,api,references}.py`:
  순서대로 모듈, 불변 계약, HTTP 검증, 저장 포트/SQL 구현, DB, 업무 흐름, 얇은 API, 참조 포트.
- 새 `backend/src/ai_workshop/learning_composition.py`: RAG/record/service 참조 해석기와 DI.
- 새 `backend/src/ai_workshop/platform/learning/topics.json`: 기술 주제 registry. 모델·실행 성공 예시는 넣지 않는다.
- 수정 `backend/src/ai_workshop/{main.py,shared/model_registry.py,config.py}`: router, 모델 등록, 입력/페이지 한계 typed settings.
- 새 `backend/alembic/versions/0024_learning_records.py`: 현재 head=0023_rag_domains 이후 additive migration.
  실행 전 head를 재확인하고 충돌 시 번호를 재조정한다. 실행 중인 개발 DB에는 임의 적용하지 않는다.
- 새 frontend `src/features/learning/{api.ts,LearningListPage.tsx,LearningDetailPage.tsx,LearningEditor.tsx,RecordBody.tsx}`.
- 새 `frontend/src/app/(workspace)/workshop/learning/page.tsx` 및 `[recordId]/page.tsx`.
- 수정 `frontend/src/shared/{routing/routes.ts,api/schema.d.ts}`. 생성 경로는 기존 openapi-ts.config.mjs에서 확인했다.
  생성 파일은 수동 편집하지 않는다. 수정 `frontend/src/features/navigation/WorkspaceNavigation.tsx`.

## Task 1: 기록·주제·revision 도메인

**Files:** 새 domain.py, schemas.py, topics.json, `backend/tests/unit/platform/learning/test_domain.py`.

**Interfaces:** `RecordKind(note, experiment)`, `ExperimentStatus(planned, running, completed, failed, cancelled)`.
`LearningDraft`: title/body/kind/topic_keys/domain_labels/experiment/references.
`ExperimentFields`: purpose/hypothesis/dataset_snapshot/configurations/environment/procedure/observations/metrics/limitations/conclusion/next_steps/status,
troubleshooting의 symptom/reproduction/facts/hypotheses/confirmed_cause/change/verification/unresolved.
문자열·목록은 typed schema, metrics는 이름/값/단위 레코드다. 임의 실행 payload dict를 저장하지 않는다.
`LearningRecord.create(owner_id: UUID, draft: LearningDraft) -> LearningRecord`;
`record.revise(draft: LearningDraft, expected_revision: int) -> LearningRecord`.

- [x] RED: 제목·본문만으로 메모 생성, 빈 실험 초안 허용, note→experiment 시 이전 revision 보존, 잘못된 상태 거부를 작성한다.

```python
def test_note_needs_no_experiment_fields():
    draft = LearningDraft(title="청킹 메모", body="경계를 비교한다", kind="note")
    record = LearningRecord.create(owner_id=uuid4(), draft=draft)
    assert record.revision == 1
    assert record.draft.experiment is None
```

- [x] `backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/unit/platform/learning/test_domain.py -q` 실행: 신규 모듈 부재 RED 확인.
- [x] 도메인과 검증 구현. revision 증가는 입력값이 아닌 서버 동작이다.

```python
if expected_revision != self.revision:
    raise AppError("learning_revision_conflict", "기록이 변경되었습니다.", 409)
return replace(self, draft=draft, revision=self.revision + 1)
```

- [x] 같은 명령 GREEN. 모델·프롬프트·환경값을 본문 예제로 강제하지 않는지 리뷰하고 변경 파일만 인계한다.

## Task 2: 영속 저장·원자적 수정·보관

**Files:** models.py, repository.py, migration, model_registry.py,
`backend/tests/integration/test_learning_persistence.py`.
**Interfaces:** `LearningRepository.create(record)`, `get_owned(record_id, actor_id)`,
`save_revision(record, expected_revision)`, `list_owned(actor_id, filters, cursor, limit)` async 포트.
없는/타인 결과는 `None`; CAS 실패는 409. 서비스는 저장 트랜잭션 커밋 이후 성공을 반환한다.

- [x] RED: 두 사용자, 동시 revision=1 수정 두 개 중 하나만 성공, revision history 불변, 보관·복원, 목록 필터를 작성한다.

```python
assert await repository.get_owned(record.id, other_actor_id) is None
first = record.revise(updated_draft, expected_revision=1)
await repository.save_revision(first, expected_revision=1)
with pytest.raises(AppError, match="기록이 변경"):
    await repository.save_revision(first, expected_revision=1)
```

- [x] 테스트 fixture는 테스트 내 생성한 정확 UUID 명칭 DB를 확인하고 finally에서 그 DB만 회수한다.
  기존 migration_0023 테스트의 격리 패턴을 참조하되 개발 DB truncate/reset은 사용하지 않는다.
- [x] `learning_records`(id, owner FK, kind, current_revision, archived_at, timestamps),
  `learning_record_revisions`(record FK, revision, validated payload JSONB, created_at)을 생성한다.
  `(record_id, revision)` unique, `(owner_id, updated_at, id)` index. revision별 payload에 당시 보관 상태 포함.
- [x] UPDATE의 id+owner+revision 조건과 rowcount 검증, revision INSERT를 같은 트랜잭션에 둔다.

```python
result = await session.execute(
    update(LearningRecordModel)
    .where(LearningRecordModel.id == record.id,
           LearningRecordModel.owner_id == record.owner_id,
           LearningRecordModel.current_revision == expected_revision)
    .values(current_revision=record.revision)
)
```

- [x] 전용 DB가 준비된 경우만 `backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/integration/test_learning_persistence.py -q -m integration` 실행.
  migration upgrade/downgrade/upgrade와 기존 테이블 데이터 보존을 검증한다. 미실행은 통과로 기록하지 않는다.

## Task 3: 참조 권한·서비스·API 계약

**Files:** references.py, service.py, api.py, learning_composition.py, main.py,
`backend/tests/unit/platform/learning/test_service.py`, `backend/tests/contract/test_learning_api.py`.
**Interfaces:** `ReferenceKey(kind: str, target: str, version: str | None)`;
`ReferenceView(status, label: str | None, href: str | None)`;
`ReferenceResolver.resolve(actor_id: UUID, key: ReferenceKey) -> ReferenceView` async.
`LearningService.create(actor, draft)`, `detail(actor, id, revision=None)`, `update(actor,id,expected_revision,draft)`,
`archive(actor,id,expected_revision)`, `restore(actor,id,expected_revision)`, `list_for(actor,filters,cursor,limit)` async.

- [x] RED: 비로그인 401·타인 404·참조 권한 회수·revision 충돌을 각각 검증한다.
  `test_anonymous_request_is_401`, `test_other_owner_is_404`, `test_revoked_reference_hides_label`, `test_stale_revision_is_409`.

```python
response = await client.get(f"/api/v1/learning/records/{other_record.id}")
assert response.status_code == 404
assert other_record.draft.title not in response.text
```

- [x] Python unit/contract 신규 파일 실행 RED를 확인한다. client/actors는 테스트에서 합성 fixture로 만들고 auth dependency를 override한다.
- [x] `get_current_user`와 `AppError` 재사용. 요청에서 owner_id 금지, body·title·reference 수·페이지 한계를 config.py의 typed settings로 검증한다.
- [x] 조립부 resolver registry: `learning.record`는 소유권 확인, `service`는 허용 서비스 registry만,
  `rag.evaluation`은 기존 `EvaluationApplicationService.detail(run_id, actor_id)`를 호출한다.
  RAG evaluation의 읽기 권한이 변경되면 동일 정책이 적용된다. raw URL·SQL·경로는 입력 거부한다.
- [x] 순환 record 참조는 허용하되 중첩 확장하지 않는다. 표시용 label/href만 권한 확인 후 생성하고 원문은 복사하지 않는다.
- [x] 대상에 실제 상세 UI가 없으면 href는 null로 반환하고 검증된 요약만 표시한다. RAG 실행용 허구 경로를 생성하지 않는다.
- [x] 신규 unit/contract GREEN과 기존 권한 회귀 검증. `pnpm --dir frontend api:generate`로 계약 타입 생성 후 `api:check`.

## Task 4: 학습 목록·편집·전환·보관 UI

**Files:** 파일 지도 frontend 경로와 각 컴포넌트 `.test.tsx`, navigation/routes 테스트.
**Interfaces:** api.ts는 생성 schema의 `LearningDraft`, `LearningRecordResponse`, `LearningListResponse`, `LearningTopicResponse`를 사용한다.
`listRecords`, `getRecord`, `createRecord`, `updateRecord`, `archiveRecord`, `restoreRecord`, `listTopics`는 기존 apiRequest를 감싼다.

- [x] RED: 자유 메모 저장, 불완전 실험 저장, topic 필터, 실험 전환 확인, 409에도 입력 보존, 보관·복원, unavailable 참조 비활성화 테스트.

```tsx
render(<RecordBody body={'<script>alert(1)</script> ![x](https://invalid.test/x)'} />);
expect(document.querySelector('script')).toBeNull();
expect(document.querySelector('img')).toBeNull();
```

- [x] `pnpm --dir frontend test --run src/features/learning` RED 확인.
- [x] 목록·상세는 기존 workspace layout의 로그인 보호를 사용한다. navigation에 “학습 기록”을 추가한다.
  제목·종류·주제·수정시각·상태를 표시하며 내부 UUID를 표시명으로 사용하지 않는다.
- [x] 초안 입력을 로컬스토리지에 저장하지 않는다. 409에서 입력을 보존하고 최신 revision 읽기와 재편집을 안내한다.
  자동 덮어쓰기/자동 재시도 금지. 전환·화면 이동 시 미저장 변경 확인, 저장 중 중복 제출 차단.
- [x] 안전한 첫 본문 컴포넌트와 구조화 필드 입력을 구현한다.

```tsx
export function RecordBody({ body }: { body: string }) {
  return <div className="learning-record-body">{body}</div>;
}
```

- [x] 줄바꿈은 CSS로 보존하고 dangerouslySetInnerHTML·임의 URL 링크·외부 이미지 로딩은 사용하지 않는다.
  각 실험 필드 label과 상태 선택지를 typed field registry로 관리한다. 테스트 GREEN, typecheck/lint 실행.

## Task 5: 통합 검증·인계

**Files:** `backend/tests/integration/test_learning_lifecycle.py`,
`frontend/src/features/learning/LearningLifecycle.test.tsx`, WORKBOARD.md, docs/runbooks/local-development.md.

- [x] 새 브라우저 mock 계약 테스트에서 메모 작성→새로고침 후 재조회→실험 전환→이력 확인→보관→복원 흐름을 작성한다.
  backend 통합 테스트는 같은 lifecycle을 실제 격리 DB에서 검증한다. 브라우저 mock 통과를 실제 E2E로 표현하지 않는다.
- [x] 참조 해석기 fake가 아닌 RAG 권한 경로와 접합하는 계약 테스트를 추가한다. 삭제/권한 회수/타인 실행 모두 label 누출 없이 실패해야 한다.
- [x] 아래 명령을 실행하고 결과를 기록한다. 코드 검증과 모델 검증을 구분한다.

```powershell
# 저장소 root
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/unit/platform/learning backend/tests/contract/test_learning_api.py -q
# backend 디렉터리
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/python.exe -m mypy src
# 저장소 root
pnpm --dir frontend test --run src/features/learning 'src/app/(workspace)/workshop/learning' src/features/navigation src/shared/routing/routes.test.ts --pool=threads --maxWorkers=1 --reporter=verbose
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend api:check
pnpm --dir frontend build
```

- [ ] 운영/개발 DB migration 적용은 별도 실행 단계로 고지한다. owner UI에서 비민감 테스트 기록의 저장·복원을 직접 확인하고 생성 기록을 인계한다.
- [x] 독립 보안·코드 리뷰 후 신규 산출물 목록을 CACHE_POLICY 절차로 조사한다. 실제 사용자 기록·기존 캐시를 삭제하지 않는다.
- [x] WORKBOARD 최근 완료는 최대 5개, 활성화 확인 이후 기능 작업은 Publishing 2단계로 명시한다. 공개 연결과 학습 실행은 아직 미구현이라고 표시한다.

## 자기 검토와 실행 인계

- spec 1~5의 비공개 범위는 Tasks 1~4, spec 6의 비공개 렌더링은 Task 4,
  spec 7의 실험 구조 기록은 Task 1, spec 8의 권한·revision·참조 검증은 Tasks 2~5로 대응한다.
- 공개 게시·학습 데이터 후보·실제 모델 비교/파인튜닝은 명시적으로 후속 계획이며 빈 모듈을 생성하지 않는다.
- 작업 역할: 아키텍처/문서, Python·DB, 프론트, 테스트 설계, 독립 보안·통합 검증.
  실행 전 selector로 최소 역할을 재계산하며 구현 담당과 독립 리뷰를 분리한다. AI 런타임·Docker 담당은 비활성이다.
- 계획 작성 단계에서는 테스트·migration·모델 호출을 실행하지 않았다. 위 명령은 구현 후 검증 명령이다.
- 참조 RAG 평가의 포트는 현재 `detail(run_id: UUID, actor_id: UUID) -> EvaluationRunView`로 확인했다.
  기존 구현의 `detail_visible`을 통해 권한 검사를 재사용하며 Platform 안에 SQL 접근을 복제하지 않는다.
