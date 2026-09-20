# 원본 파일 추적 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 원본 파일을 생성하기 전에 정확한 소유권·경로를 영속 등록하고 성공·실패한 업로드 모두 목록에서 추적한다.

**Architecture:** Platform Assets의 독립 업로드 원장과 최종 source resource를 분리한다. 추적 파일 어댑터는 등록된 정확 경로에만 불변 게시하며, coordinator가 버전·job·관계·원장 확정을 하나의 transaction으로 연결한다.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, PostgreSQL/Alembic, 기존 로컬 파일 저장소, pytest/mypy/Ruff.

**Spec:** [원본 파일 소유권 상세안](../specs/2026-09-20-original-file-ownership-design.md).

## Global Constraints

- 사용자 2026-09-20 지시로 상세안의 원본 추적 코드 구현을 진행한다. 다시 승인된 범위를 묻지 않는다.
- 원본·임시 key는 bytes를 소비하기 전에 등록·commit한다. commit 불명은 자동 삭제 사유가 아니다.
- Platform은 Labs를 import하지 않는다. 실사용 migration/marker 생성/backfill/서버 재시작/자료 삭제는 제외한다.
- 현재 checkout 사용의 기존 인계 예외를 유지한다. 참고 자료 `references/`는 보존한다.
- 메인만 통합·WORKBOARD·staging·commit·push를 담당한다. 구현과 독립 검증을 분리한다.
- OCR/뷰어 임시물과 일반 jobs 참여자의 전체 추적은 별도 후속이다.

## Review Focus

- 예약 commit 응답 상실: 파일 스트림은 한 번도 소비되지 않아야 한다(Task 3).
- DB commit 성공 뒤 응답 상실: 연결된 canonical을 지우지 않아야 한다(Task 3).
- 문서 없는 업로드 실패: workspace 목록에 예약이 남아야 한다(Task 4).
- 동일 bytes지만 다른 문서: 기존 파일을 인수하거나 삭제하지 않아야 한다(Task 2/3).
- 목록 조회 중 새 예약/버전/관계 생성: complete 판정을 거부해야 한다(Task 4).

## 공용 인터페이스

새 `platform/assets/upload_contracts.py`:

```python
@dataclass(frozen=True)
class OriginalStoreBinding:
    store_id: str
    binding_id: UUID

@dataclass(frozen=True)
class UploadClaim:
    attempt_id: UUID
    source: SourceIdentity
    user_id: UUID
    folder_id: UUID | None
    new_document: bool
    binding: OriginalStoreBinding
    suffix: str
    generation: int | None = None
    # canonical_key: ws/doc/attempt.hex + suffix
    # temporary_key: ws/doc/.attempt.hex.upload.tmp

@dataclass(frozen=True)
class UploadAttempt:
    claim: UploadClaim
    state: str
    revision: int
    size: int | None
    sha256: str | None

@dataclass(frozen=True)
class OriginalFileObservation:
    canonical: StoredObject | None
    temporary_exists: bool
```

`UploadClaim` 입력과 반환은 불변이며 기존 문서의 generation은 reserve가 잠금 아래 채운다.
suffix는 기존 업로드 allowlist의 소문자 확장자만 허용한다. ID/type/bool/revision/key를 엄격하게 검증한다.
`UploadOwnershipError(code)`는 고정 안전 코드만 전달한다.

### Task 1: 영속 예약과 원본 자원

**Files:**
- Create: `backend/src/ai_workshop/platform/assets/upload_contracts.py`
- Create: `backend/src/ai_workshop/platform/assets/upload_models.py`
- Create: `backend/src/ai_workshop/platform/assets/upload_repository.py`
- Create: `backend/alembic/versions/0045_original_upload_ownership.py`
- Modify: `backend/alembic/env.py`
- Test: `backend/tests/unit/platform/assets/test_upload_contracts.py`
- Test: `backend/tests/integration/platform/assets/test_upload_repository.py`

**Interfaces:**

```python
class UploadJournal:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]): ...
    async def reserve(self, claim: UploadClaim) -> UploadClaim: ...
    async def published(self, claim: UploadClaim, stored: StoredObject) -> None: ...
    async def cleanup(self, claim: UploadClaim, *, expected_state: str,
                      discard: Callable[[], None],
                      observe: Callable[[], OriginalFileObservation]) -> None: ...
    async def prepare_attachment(self, session: AsyncSession, claim: UploadClaim) -> Document | None: ...
    async def attach(self, session: AsyncSession, claim: UploadClaim, stored: StoredObject) -> None: ...
```

- [x] 예약 전 FK 없는 예정 ID·정확 key·상태·revision 제약과 실제 source resource의 복합 RESTRICT를 실패 테스트로 작성한다.
  `assert await independent_session.get(UploadAttemptRecord, attempt_id)`를 요청 rollback 이후에도 검사한다.
- [x] reserve는 workspace→membership→folder/Document 잠금과 active/generation 검증 후 독립 commit한다.
  prepare_attachment는 같은 잠금 순서로 최신 권한·generation과 폴더를 검증하고 기존 Document의 fresh 버전을 반환한다.
- [x] `published`는 open/1→published/2, `attach`는 published/2→attached/3을 expected state+identity로 갱신한다.
  attach에서 같은 transaction의 준비 증명과 version의 source/key/hash/size를 재검사하고 revision 1의 resource 및 `platform_originals/original/source_copy` 관계를 함께 flush한다.
- [x] `cleanup`은 원장을 잠그고 published/2→discarding/3을 먼저 commit한 뒤 물리 callback과 정확 부재 확인을 거쳐 abandoned/4로 전이한다. open/1의 미게시 정리는 abandoned/2다. attached 정리는 callback 전에 거절한다.
- [x] migration up/down과 source/resource/attempt 삭제 RESTRICT, 버전 경쟁·권한 철회·generation 변경을 격리 PG에서 검사한다.
  Run: `.venv/Scripts/python.exe -m pytest tests/unit/platform/assets/test_upload_contracts.py tests/integration/platform/assets/test_upload_repository.py -q` (`backend`).

### Task 2: 등록된 원본의 파일 게시

**Files:**
- Create: `backend/src/ai_workshop/infrastructure/object_store/originals.py`
- Test: `backend/tests/unit/infrastructure/object_store/test_originals.py`

**Interfaces:**

```python
class TrackedOriginalStore:
    def __init__(self, root: Path, binding: OriginalStoreBinding): ...
    async def publish(self, claim: UploadClaim, source: AsyncIterator[bytes]) -> StoredObject: ...
    def observe(self, claim: UploadClaim) -> OriginalFileObservation: ...
    def discard(self, claim: UploadClaim, expected: StoredObject) -> None: ...
```

- [x] marker 부재·binding 불일치·canonical 충돌에서 bytes를 소비하지 않는 실패 테스트를 작성한다.
- [x] root의 `.ai-workshop-original-store.json`를 제한 길이·schema 1·store_id/binding_id로 검증한다. 자동 생성하지 않는다.
- [x] 경로·reparse·symlink·case alias·hardlink 이상을 거절하고 임시 파일 xb→flush/fsync→overwrite 없는 게시→자기 임시 파일 해제로 구현한다. Windows 디렉터리·marker·파일 핸들 고정으로 생성/게시/삭제 경쟁을 차단한다. 비Windows mutation은 거절하고 observe는 유지한다.
  `with pytest.raises(UploadOwnershipError): await store.publish(claim, content())`; `assert original.read_bytes() == before`를 충돌에서 검사한다.
- [x] 실패/취소에서 열린 핸들이 닫힌 뒤 이번 호출이 만든 임시 파일만 정리한다. canonical은 성공적으로 관찰되지 않았더라도 함부로 제거하지 않는다.
- [x] observe는 두 exact 경로만 읽고 mismatch를 빈 결과로 바꾸지 않는다. discard는 exact binding/key/hash/size/파일 식별자를 검증한 뒤에만 canonical을 지운다.
- [x] Run: `.venv/Scripts/python.exe -m pytest tests/unit/infrastructure/object_store/test_originals.py -q`.

### Task 3: 운영 업로드 연결

**Files:**
- Create: `backend/src/ai_workshop/platform/assets/tracked_uploads.py`
- Modify: `backend/src/ai_workshop/platform/assets/service.py`
- Modify: `backend/src/ai_workshop/platform/assets/domain.py`
- Modify: `backend/src/ai_workshop/config.py`
- Test: `backend/tests/unit/platform/assets/test_tracked_uploads.py`
- Test: `backend/tests/integration/platform/assets/test_tracked_uploads.py`

**Interfaces:** `TrackedAssetUploadCoordinator`는 기존 coordinator와 동일한 upload/upload_version 입력·응답을 제공한다.
생성자에 assets/jobs, 현재 session, journal, tracked store를 전달한다. 기존 untracked coordinator는 운영 DI에서 선택하지 않는다.

- [x] fake journal/store/session으로 순서를 기록한다.
  `assert events.index('reserved') < events.index('first_byte') < events.index('attach') < events.index('commit')`.
  reserve 실패 시 `assert consumed == []`; commit 실패 시 `assert store.canonical_exists`.
- [x] UUID를 사전 생성하고 `Document.new_version(version_id=...)`로 유지한다. 버전 번호는 fresh 버전의 max+1이다.
- [x] 최종 prepare→중복 검사→version 저장→job 생성→attach→commit을 연결한다.
  최종 commit 이전 실패는 rollback 확인 후 exact discard 및 abandoned를 시도한다. cleanup 실패는 원장에 열린 상태를 보존한다.
  commit을 시도한 뒤의 어떤 오류/취소도 canonical 삭제를 시작하지 않는다.
- [x] config에 original_store_id/original_store_binding_id paired 설정을 추가한다. 운영 DI는 미설정/marker 불일치 시 안전한 503으로 중단하고 untracked 경로로 대체하지 않는다.
- [x] 신규/새 버전, 중복, 입력 크기, 취소, job 생성 실패, 권한 철회, commit 불명, 기존 원본 읽기 회귀를 검사한다.
  Run: `.venv/Scripts/python.exe -m pytest tests/unit/platform/assets/test_asset_service.py tests/unit/platform/assets/test_tracked_uploads.py tests/integration/platform/assets/test_tracked_uploads.py -q`.

### Task 4: 문서·미확정 업로드 목록

**Files:**
- Create: `backend/src/ai_workshop/platform/assets/upload_inventory.py`
- Test: `backend/tests/integration/platform/assets/test_upload_inventory.py`

**Interfaces:** SQL session과 tracked store를 받는 읽기 전용 participant. `collect(workspace_id, document_id)`는 불투명 자원·안전 차단 이유를 반환한다.
`list_unattached(user_id, workspace_id)`는 현재 workspace 권한 확인 후 실제 문서 없는 예약도 포함하며 locator/hash는 노출하지 않는다.

- [x] legacy version은 관계 누락으로 incomplete, open 예약은 writer 미종료로 차단하는 실패 테스트부터 작성한다.
- [x] 모든 버전/예약/자원/관계를 조회하고 revision·source·binding·실물과 대조한다. 누락·불명·오류는 완전한 빈 목록으로 바꾸지 않는다.
- [x] DB 조회 전후 snapshot과 파일 대조 전후 상태를 비교한다. 전체 조회이므로 continuation 없이 exhausted를 명시하며 변경 시 incomplete다.
- [x] 실패한 신규 예약은 document 없이 workspace 목록에서 발견되는지 검사한다.
  `assert orphan.attempt_id in {item.attempt_id for item in result.items}` 및 `assert 'object_key' not in serialized`.
- [x] Run: `.venv/Scripts/python.exe -m pytest tests/integration/platform/assets/test_upload_inventory.py -q`.

### Task 5: 통합·문서·독립 검증

- [x] 새/영향 테스트, mypy·Ruff 및 합성 PG migration을 실행하고 결과를 읽는다.
- [x] 독립 reviewer가 DB/FS/transaction 연결 및 프라이버시를 검사한다. 실제 DB와 사용자 파일에 접근하지 않는다.
- [x] 작업 기록·설계 구현 상태·운영 정본에 설정과 적용 전제 및 미완료 후속을 기록한다. WORKBOARD 최근 완료는 최대 5개다.
- [x] 합성 테스트 컨테이너만 정확 ID로 종료하고 실사용 서비스·자료·캐시는 보존한다.
- [x] commit/push는 사용자 승인 범위와 실제 검증 결과를 확인한 메인만 수행한다.

## 실행 판정 기록

- 사용자 직전 대화에서 다음 작업이 코드 구현임을 확인하고 진행을 지시했으므로 추가 계획 승인 질문 없이 구현한다.
- 예약 원장 revision과 확정 원본 자원 revision은 별개다. 자원/관계 revision 1, attached 원장 revision 3으로 검증한다.
- 독립 리뷰에서 cleanup 검사/삭제 경쟁과 삭제 후 DB 결과 불명을 확인해 discarding 영속 차단 및 Windows handle 기반 파일 보호를 추가했다.
- 비Windows 쓰기는 안전 보장 구현 전까지 fail closed다. 운영 정본에 지원 제한을 기록하고 기존 읽기를 유지한다.
- 신규 통합 fixture는 명시 AI_WORKSHOP_DATABASE_URL 및 AI_WORKSHOP_ENVIRONMENT=test 없이는 연결을 시도하지 않는다.
