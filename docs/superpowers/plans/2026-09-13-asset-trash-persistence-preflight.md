# Asset Trash Persistence Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 휴지통 영속 기반을 만들기 전에 격리 DB 검증의 대상 안전성과 현재 SQL 삭제 권한을 실행 가능한 게이트로 만든다.

**Architecture:** 기존 Workspaces 권한을 정본으로 재사용하고 Assets에서 휴지통 행위와 결합한다. 먼저 통합 테스트의 DB 생성·제거 경계를 보강한다. 이 계획은 전체 영속 기반 중 2A이며 lifecycle migration·삭제 명령·worker·UI를 포함하지 않는다.

**Tech Stack:** 기존 Python 3.13, SQLAlchemy, psycopg, Alembic, pytest, mypy, Ruff. 새 패키지·가상환경·Docker 서비스 없음.

**Spec:** `docs/superpowers/specs/2026-09-13-asset-trash-purge-design.md`

## Global Constraints

- Platform에서 Labs 구현을 import하거나 문서 삭제에 LLM을 사용하지 않는다.
- 개인 파일함은 본인 생성 소유자와 기존 활성 접근 조건을 유지한다. 전역 마스터도 타인의 개인 공간을 우회하지 않는다.
- manage_members를 삭제 권한으로 재사용하지 않는다.
- 보관 기간은 관리자 UI에 양의 일수로 명시 저장하는 버전된 정책이다. 코드에 보관 기간을 고정하지 않는다.
- 기존 데이터의 연관 관계를 완전하게 증명할 수 없으면 inventory_incomplete로 차단한다.
- 상태 필터와 삭제 재생성 방지 검증 전에 UI를 활성화하지 않는다.
- 실사용 DB 적용·서버 재시작·실제 삭제는 별도 대상 확인 후 수행한다.
- main에서만 작업한다. 기존 미커밋 프론트 변경·WORKBOARD의 기존 이력·references를 보존한다.
- 회사 RESTORE는 이미 확정된 read+write+delete다. TEAM/TEMPORARY MEMBER의 기존 delete=False를 확대하지 않는다.

## 조사 결과와 분할 이유

1. `platform/jobs/models.py`의 일반 Job은 필수 asset_version_id와 CASCADE를 가진다. 폴더·배치 삭제 및 원본 삭제 후 남을 증명의 저장소로 재사용하지 않는다.
2. `assets/models.py`의 Folder.parent는 CASCADE, Document.folder는 SET NULL이다. 폴더 행 DELETE만으로 하위 문서 영구 삭제를 구현할 수 없다.
3. 기존 폴더 UNIQUE(workspace_id,parent_id,name)는 NULL root 중복을 막지 못한다. `repository.folder_name_exists()`는 SQL trim과 Python strip을 사용하므로 새 정규화/대소문자 정책을 조사 없이 발명하지 않는다.
4. `tests/integration/publishing_support.py`는 UUID DB 이름과 current_database 확인은 하지만 .env의 원격 PostgreSQL을 차단하지 않는다. 기존 ingestion 테스트의 local/test·loopback 검증을 참고하되 URL/환경의 우회 경로도 닫아야 한다.
5. Workspaces의 fresh capability 조회는 이미 존재한다. 새 권한 경로가 비회사 공간 전체에 delete를 주지 않도록 기존 OWNER/PERSONAL/COMPANY 규칙과 대조한다.

| 하위 단계 | 결과 | 다음 단계로 넘기는 조건 |
|---|---|---|
| 2A: 이 계획 | 격리 DB 대상 검증, 현재 SQL 삭제 predicate, 잠금 후 휴지통 권한 재검사 | 부정 입력·권한 철회·개인 격리 PG 검증 |
| 2B | additive lifecycle/generation·명시 정책 버전·배치·전용 purge job/outbox | 전이 미노출, upgrade/downgrade 거부 조건·기존 행 보존 검증 |
| 2C | typed provenance/manifest·최소 증명, 기존 데이터 dry-run inventory | 소유관계 미확정은 incomplete, 공유/무관 자원 보존 |
| 3 이후 | 목록/원문/검색/worker gate → 실제 명령 → 정리 참여자 → UI | 전체 설계 §5–11의 별도 구현 게이트 |

2B에서는 문서/폴더의 PURGED 행을 유지하지 않는다. PURGED는 전용 최소 삭제 증명의 결과다.
전용 purge 증명은 Document/AssetVersion의 CASCADE에 묶지 않는다. 기존 cascade를 무차별 제거하는 것도 이 계획에 포함하지 않는다.
활성 root/일반 폴더 고유 인덱스는 기존 이름 충돌을 먼저 읽기 전용 조사하고 충돌 시 migration을 중단한다. 자동 병합·이름 변경 없음.
원래 본문 행을 제거한 뒤에도 최소 증명은 남되, manifest locator/파일명/본문 hash는 정리 완료 시 제거하는 별도 수명주기를 갖는다.

## 실행·역할

- 메인: 요구/시스템 설계·테스트 설계·통합 및 문서, 계획 자가 검토.
- Task1: Python/DB 테스트 기반 구현; 별도 DBA·보안 검토.
- Task2–3: Python 구현; 별도 보안·권한 및 통합 검증.
- UI·AI 모델·Docker 구현은 제외한다. 구현 담당은 독립 승인에 참여하지 않는다.
- 기존 backend/.venv를 사용한다. `-B`, pytest `-p no:cacheprovider`, Ruff `--no-cache`.
- 단위 테스트는 Settings(_env_file=None, ...)에 합성 입력을 명시하며 실제 .env나 연결을 사용하지 않는다.
- 통합 테스트는 Task1 검증 후에만 실행한다. 실제 실행 전 loopback PostgreSQL 접속 대상·생성 이름·정리 경계를 보고하고 승인된 환경에서만 실행한다.
- 새 루트 테스트 디렉터리·공용 DB 초기화·광범위 캐시 정리·원격 push를 하지 않는다.

### Task 1: 격리 PostgreSQL 대상 사전 검사

**Files:**
- Modify: `backend/tests/integration/publishing_support.py`
- Create: `backend/tests/unit/test_publishing_database_safety.py`

**Interfaces:**
- 추가 `validate_disposable_database_target(settings: Settings, database: str) -> None`.
- 기존 `_require_exact_database_name`, `_assert_current_database`, `IsolatedPublishingDatabase`, `isolated_publishing_database(monkeypatch)` 계약은 유지한다.
- 잘못된 대상은 `ValueError("unsafe_disposable_database_target")`, 연결 정보/비밀번호는 오류에 넣지 않는다.

- [x] 행동 테스트를 먼저 작성한다. 잘못된 URL/환경/이름은 생성 전에 거부되고 유효한 합성 local/test loopback PostgreSQL만 통과한다.

```python
@pytest.mark.parametrize("environment", ["local", "test"])
def test_local_disposable_target_allowed(environment):
    settings = Settings(
        _env_file=None, environment=environment,
        secret_key="offline-test-secret-not-a-credential",
        database_url="postgresql+psycopg://test:test@127.0.0.1:5432/source",
    )
    validate_disposable_database_target(settings, "ai_workshop_publishing_" + "a" * 32)

@pytest.mark.parametrize("url", [
    "postgresql+psycopg://test:test@db.example.test/source",
    "postgresql+psycopg://test:test@127.0.0.1/source?host=db.example.test",
    "postgresql+psycopg://test:test@127.0.0.1/source?hostaddr=192.0.2.1",
    "postgresql+psycopg://test:test@127.0.0.1/source?service=external",
    "sqlite:///local.db",
])
def test_remote_or_overridden_connection_is_rejected(url):
    settings = Settings(_env_file=None, database_url=url,
                        secret_key="offline-test-secret-not-a-credential")
    with pytest.raises(ValueError, match="^unsafe_disposable_database_target$"):
        validate_disposable_database_target(settings, "ai_workshop_publishing_" + "a" * 32)
```

- [x] 추가 사례: production 환경, 빈 호스트, 복수 호스트, UUID 규칙을 벗어난 이름과 원본 DB 이름, 값이 설정된 PGHOSTADDR/PGSERVICE/PGSERVICEFILE을 거부한다. localhost와 IPv6 loopback은 허용한다. 테스트 환경에는 monkeypatch로 합성 값만 설정한다.
- [x] RED: `.venv/Scripts/python.exe -B -m pytest tests/unit/test_publishing_database_safety.py -q -p no:cacheprovider`. 선언 부재 오류로 끝내지 않고, 최소 선언 후 예상한 동작 assertion이 실패하는지 확인한다.
- [x] 아래 검사를 첫 연결 전과 삭제 직전에 호출한다. URL 해석 실패도 같은 안전 오류로 변환한다.

```python
url = make_url(settings.database_url)
host = url.host
try:
    loopback = host == "localhost" or (host is not None and ip_address(host).is_loopback)
except ValueError:
    loopback = False
safe = (
    settings.environment in {"local", "test"}
    and url.get_backend_name() == "postgresql"
    and loopback
    and _DATABASE_NAME.fullmatch(database) is not None
    and set(url.query) <= {"connect_timeout"}
    and not any(os.environ.get(key) for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"))
)
if not safe:
    raise ValueError("unsafe_disposable_database_target")
```

- [x] CREATE 성공 전에는 DROP하지 않는다. 기존 current_database 및 정확한 이름 검증을 유지한다. 실패 시에도 이번 호출에서 생성한 해당 DB만 finally에서 정리한다.
- [x] 실행 흐름 단위 테스트에서 잘못된 대상이 연결 전에 거부되는지 확인한다. DB 없이 수행한 검사를 실제 CREATE/DROP 성공 증거로 보고하지 않는다.
- [x] GREEN, helper의 mypy, 변경 2개 파일의 Ruff와 독립 검토를 수행한다. 메인만 해당 파일을 커밋한다.

### Task 2: 현재 삭제 권한을 SQL 조건으로 공유

**Files:**
- Modify: `backend/src/ai_workshop/platform/workspaces/permissions.py`
- Create: `backend/tests/integration/platform/workspaces/test_delete_permissions.py`

**Interfaces:**
- `workspace_delete_allowed(actor_id: UUID) -> ColumnElement[bool]`
- `require_workspace_delete(session: AsyncSession, actor_id: UUID, workspace_id: UUID, *, lock: bool = False) -> None`
- 기존 `workspace_read_allowed`, `lock_workspace_memberships`, `not_found()`을 사용한다.

- [x] Task1 검증을 통과한 isolated_publishing_database로 생성한 DB에만 head migration을 적용한다. seed_original의 합성 사용자·공간만 사용한다.
- [x] 독립 기대표로 COMPANY의 read/write/delete 조합과 OWNER, PERSONAL 생성자·위조 membership, TEAM/TEMPORARY의 OWNER/MEMBER, 만료·비활성 상태를 검증한다.

```python
@pytest.mark.asyncio
async def test_team_member_write_does_not_imply_delete(database):
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as session:
            await session.execute(update(WorkspaceRecord).where(
                WorkspaceRecord.id == seed.workspace_id
            ).values(kind=WorkspaceKind.TEAM, expires_at=None))
            with pytest.raises(AppError) as denied:
                await require_workspace_delete(session, seed.user.id, seed.workspace_id)
            assert denied.value.code == "not_found" and denied.value.status_code == 404
    finally:
        await engine.dispose()
```

- [x] RED: `.venv/Scripts/python.exe -B -m pytest tests/integration/platform/workspaces/test_delete_permissions.py -q -p no:cacheprovider`. 격리 환경을 사용할 수 없으면 미검증으로 기록한다. SQLite나 SQL 문자열 검사만으로 PostgreSQL 검증 통과를 주장하지 않는다.
- [x] 아래 등가식을 구현한다. delete 조건에 `kind != COMPANY`를 사용하지 않는다.

```python
member = aliased(WorkspaceMembershipRecord)
return and_(
    workspace_read_allowed(actor_id),
    select(member.id).where(
        member.workspace_id == WorkspaceRecord.id,
        member.user_id == actor_id,
        or_(
            member.role == MembershipRole.OWNER,
            WorkspaceRecord.kind == WorkspaceKind.PERSONAL,
            and_(WorkspaceRecord.kind == WorkspaceKind.COMPANY, member.can_delete.is_(True)),
        ),
    ).correlate(WorkspaceRecord).exists(),
)
```

- [x] require 함수는 선택한 공간의 ID를 SQL로 조회하고 없으면 not_found()를 반환한다. lock=True이면 사전 조회 → workspace/membership 잠금 → 같은 조건 재조회 순서를 지킨다. ORM에 저장된 grant로 대체하지 않는다.
  여기서 같은 조건은 같은 권한 규칙이라는 뜻이다. 현재 시각이 포함된 statement를 재사용하지 않고 매 조회마다 predicate와 select를 새로 구성한다. 잠금 대기 중 임시 공간이 만료되면 최종 조회가 거부해야 한다.
- [x] 두 세션으로 과거 membership을 미리 읽은 상태와 권한 철회를 조합해 최신 SQL이 거부하는지 검사한다. 잠금 보유 중 철회가 기다리는 경로는 Event로 순서를 정하고 제한 시간이 있는 wait_for로 교착을 검사한다.
- [x] GREEN·mypy·Ruff와 독립 보안 검사 후 메인이 정확한 파일만 커밋한다. 기존 read/write 권한을 수정하지 않는다.

### Task 3: 휴지통 행위의 잠금 후 현재 권한 재검사

**Files:**
- Create: `backend/src/ai_workshop/platform/assets/trash_authorization.py`
- Create: `backend/tests/integration/platform/assets/test_asset_trash_permissions.py`

**Interfaces:**
- `require_trash_action(session: AsyncSession, actor_id: UUID, workspace_id: UUID, action: TrashAction) -> WorkspaceCapabilities`
- 기존 `SqlAlchemyWorkspaceMemberRepository.capabilities`, `allows_trash_action`과 잠금 helper를 사용한다.
- 조회 LIST는 최신 SQL 검사만 수행한다. 변경 TRASH/RESTORE/PURGE는 사전 검사 후 잠금과 재검사를 필수 수행한다. 호출자가 lock=False로 변경 잠금을 끄는 옵션은 제공하지 않는다.

- [x] COMPANY의 read+delete만 있고 write가 없는 사용자는 TRASH/PURGE 허용·RESTORE 거부, write만 있는 사용자는 모두 거부, 전체 권한을 가진 사용자는 허용하는 PostgreSQL 회귀 테스트를 먼저 작성한다.

```python
caps = await require_trash_action(session, actor_id, workspace_id, TrashAction.TRASH)
assert caps.read and caps.delete and not caps.write
with pytest.raises(AppError) as denied:
    await require_trash_action(session, actor_id, workspace_id, TrashAction.RESTORE)
assert denied.value.status_code == 404
```

- [x] RED 명령: `.venv/Scripts/python.exe -B -m pytest tests/integration/platform/assets/test_asset_trash_permissions.py -q -p no:cacheprovider`.
- [x] 다음 최소 흐름을 구현한다. actor_id는 인증 계층이 결정한 값이며 UI capability는 입력받지 않는다.

```python
repository = SqlAlchemyWorkspaceMemberRepository(session)
capabilities = await repository.capabilities(actor_id, workspace_id)
if not allows_trash_action(capabilities, action):
    raise not_found()
if action is not TrashAction.LIST:
    await lock_workspace_memberships(session, workspace_id, (actor_id,))
    capabilities = await repository.capabilities(actor_id, workspace_id)
    if not allows_trash_action(capabilities, action):
        raise not_found()
return capabilities
```

- [x] Task2의 삭제 SQL 조건과 capabilities가 같은 결과를 내는지 동일한 PostgreSQL 기대표로 검사한다. 권한 철회·비활성·개인 생성자 불일치·만료·미등록 행위는 404로 거부한다.
- [x] 이 함수는 문서·배치의 소유 범위, lifecycle/revision, 보관 기한, 실제 삭제 증명을 검사하지 않는다. 후속 명령이 같은 트랜잭션에서 검사해야 하며 AssetVersion → Document 잠금 순서를 역전시키지 않는다.
- [x] GREEN·mypy·Ruff와 독립 보안·통합 검증 후 메인이 해당 2개 파일을 커밋한다. API는 아직 등록하지 않는다.

## 최종 검증과 다음 단계 진입 조건

- [x] 기존 Assets 199건과 새 단위 테스트, 관련 Workspaces/Assets PostgreSQL 테스트를 실행한다. 건수·종료 코드·경고·격리 DB 생성 및 종료 확인을 기록한다.
- [x] 변경 코드 3개와 테스트 3개 파일의 Ruff, 애플리케이션 코드 2개와 helper 1개의 mypy를 실행한다. 승인 전에 실제 DB 접속 명령을 자동 실행하지 않는다.
- [x] DB0034와 실사용 자료를 유지하고 실사용 DB migration 파일 생성·적용이 없음을 확인한다. head migration은 fixture 전용 UUID DB에만 적용했다.
- 후속 2B 착수 조건: 역참조·FK·폴더 이름 중복 dry-run의 입출력과 실행 권한을 확정한다.
- [x] `docs/worklogs/2026-09-13-asset-trash-persistence-preflight.md`와 WORKBOARD를 갱신한다. 최근 완료 작업은 최대 5개다.
- [x] 실제 삭제·휴지통 테스트는 아직 불가능하다고 명시한다. 권한·테스트 기반 완료를 영속 모델 완료로 표시하지 않는다.

## 메인 자가 검토

- 설계 §2의 확정 권한·개인 격리와 §3의 상위 잠금을 Task2–3에 연결했다. 본문 행 상태와 provenance 저장은 2B/2C로 분리했다.
- Task1은 스키마 검증의 안전 선행 조건이다. 원격 환경에서 기존 helper를 그대로 실행하지 않는다.
- Task2와 Task3는 같은 권한 정책을 SQL 필터와 명령 검사에 제공하며 통합 테스트로 동일성을 확인한다.
- 테스트의 실제 DB 조작은 승인된 일회용 DB로 제한한다. 단위 테스트는 실제 자격 정보나 DB에 의존하지 않는다.
- 함수를 선언하는 Task와 사용하는 Task의 이름·반환형을 대조했다. 이 문서는 전체 휴지통 완료 계획이 아니라 2A의 독립 실행 계획이다.
