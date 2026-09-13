# Asset Trash Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 휴지통·복원·영구 삭제의 상태/권한/보관 기한/완료 판정을 외부 의존성 없는 실행 가능한 Python 계약으로 만든다.

**Architecture:** Platform Assets가 순수 정책을 소유한다. 기존 VersionStatus, Document/Folder 저장 모델은 이번 단계에서 바꾸지 않는다. 이후 DB·worker·API가 이 계약을 소비하며, 지금은 사용자 삭제 기능을 노출하지 않는다.

**Tech Stack:** 기존 Python 3.13, dataclasses, StrEnum, pytest, mypy, Ruff. 새 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-09-13-asset-trash-purge-design.md`

## Global Constraints

- Platform에서 Labs 구현을 import하거나 문서 삭제에 LLM을 사용하지 않는다.
- purge_pending 이후에는 일반 사용·복원을 허용하지 않는다.
- 보관 기간은 관리자 UI에 양의 일수로 명시 저장하는 버전된 정책이다. 코드에 보관 기간을 고정하지 않는다.
- 정책 변경은 새 휴지통 항목부터 적용한다.
- 문서 전용 자산만 삭제한다.
- 기존 데이터의 연관 관계를 완전하게 증명할 수 없으면 inventory_incomplete로 차단한다.
- 같은 bytes라도 독립적으로 소유한 다른 문서 원본은 대상 문서의 파생물이 아니다.
- 최종 manifest는 정리가 끝나면 경로·파일명·본문 hash 등 불필요한 값을 제거하고 건수·단계별 결과만 남긴다.
- main에서만 작업한다. 실사용 DB·서버·자료·캐시를 변경하거나 외부 모델을 호출하지 않는다.
- 기존 프론트 미커밋 변경·references와 새 작업의 변경을 섞어 커밋하지 않는다.

## 전체 설계의 단계별 범위

이 문서는 **1단계만 실행 가능한 계획**이다. 전체 삭제 기능 완료 계획으로 해석하지 않는다.
상호 의존하는 데이터 삭제를 한 번에 구현하지 않도록 후속 단계는 앞 단계의 검증된 인터페이스를 입력으로 별도 상세 계획을 작성한다.

| 단계 | 독립 검증 산출물 | 설계 연결 |
|---|---|---|
| 1: 이 계획 | 순수 전이·기한·권한·완료 판정과 단위 회귀 | §2–4, §6, §8–9 |
| 2: 영속 기반 | lifecycle/generation·정책·배치·outbox·소유 provenance 모델, migration/backfill dry-run, 현재 SQL 권한 | §2–4, §6 |
| 3: 사용 차단 | 목록/원문/승인/검색·생성/worker/alias의 상태 검사, writer fencing과 종료 확인 | §5 |
| 4: 휴지통·복원 명령 | 원자적 하위 트리 배치, 충돌·revision·멱등·동일 SHA 안내, 만료/복원 경합 | §2–4, §10 |
| 5: 연관 데이터 삭제 | 정확한 정리 참여자, 불변 trigger 제한 예외, 공유 snapshot 승인, 잔존 검증·실패 재시도 | §6–8 |
| 6: 보관 정책·자동 실행·복구 | 명시 설정·기한 단축 확인, beat 멱등 실행, 백업 목록/삭제 증명 재적용·외부 확인 | §4, §9 |
| 7: 공통 화면·전체 게이트 | 휴지통/미리보기/복원/영구 삭제 진행 UI, 형식별 격리 E2E·잔존/무관자료 보존 | §10–11 |

후속 핵심 기존 파일: Assets의 `models.py`, `repository.py`, `library_repository.py`, `originals.py`, `movement.py`, `tasks.py`, `dispatch.py`;
Workspaces의 `permissions.py`, `member_repository.py`; RAG의 `retrieval/scope.py`, `documents/models.py`, `evaluation/models.py`,
`generation/audit_models.py`, `generation/codex_approval_models.py`; Platform Learning/Publishing의 `models.py`.
이 목록은 이번 단계의 수정 허용 목록이 아니다. 기존 writer/trigger/provenance 조사 결과 없이 후속 migration·삭제 SQL을 만들지 않는다.

## 파일·역할 배정

- 생성 `backend/src/ai_workshop/platform/assets/lifecycle.py`: 사용 상태/명령 전이만 담당.
- 생성 `backend/src/ai_workshop/platform/assets/trash_policy.py`: 보관 정책·서버에서 해석된 capability의 행위 판정.
- 생성 `backend/src/ai_workshop/platform/assets/purge_contracts.py`: 참여자 정리 영수증과 완료/차단 사유 판정. 파일 삭제·DB·ES 접근 없음.
- 생성 `backend/tests/unit/platform/assets/test_asset_lifecycle.py`, `test_trash_policy.py`, `test_purge_contracts.py`: 공개 합성 값만 사용하는 단위 테스트.
- 생성 `docs/worklogs/2026-09-13-asset-trash-contracts.md`: 실행 증거와 실제 미구현 경계. WORKBOARD 마감은 메인만 수행.

구현 전 역할 selector로 requirements-or-behavior, python-api-or-worker, authentication-permission-or-exposure,
privacy-or-external-transfer, feature-implementation 신호를 평가한다. Python 구현/테스트 설계와 독립 통합·보안·privacy 검증을 분리한다.
이번에는 UI, SQL migration, 모델 runtime, Docker 실행 담당을 배정하지 않는다. 범위가 늘어나면 중단·재분류한다.

## 실행 환경과 검증 규칙

명령의 작업 디렉터리는 `backend`다. 이미 있는 `.venv/Scripts/python.exe`를 사용한다.
단위 테스트는 실제 `.env`를 읽지 않으며 필요한 경우 터미널 프로세스에만 합성 `AI_WORKSHOP_SECRET_KEY`를 지정한다.
`-B`와 `-p no:cacheprovider`로 새 pyc/pytest 캐시를 만들지 않는다. 루트 테스트 폴더·별도 venv를 만들지 않는다.
각 Task는 테스트 작성 → 기대 RED 확인 → 최소 구현 → GREEN → 독립 검토 → 메인의 정확 파일 커밋 순서다.
새 함수가 없어서 import 실패하면 테스트 수집이 되는 최소 선언을 먼저 제공하고, 행동 assertion의 RED를 확인한 후 본문을 작성한다.

### Task 1: 사용 상태와 합법 전이

**Files:** 생성 `lifecycle.py`, `test_asset_lifecycle.py`(위 절의 전체 경로).

**Interfaces:**
- `AssetLifecycle(StrEnum)`: ACTIVE, TRASHED, PURGE_PENDING, PURGING, RETRY_WAIT, BLOCKED, PURGED(값은 소문자).
- `LifecycleAction(StrEnum)`: TRASH, RESTORE, REQUEST_PURGE, START_PURGE, RETRY_LATER, BLOCK, RETRY, COMPLETE.
- `transition(current: AssetLifecycle, action: LifecycleAction) -> AssetLifecycle`; 금지 전이는 `ValueError("invalid_lifecycle_transition")`.
- `allows_normal_use(state: AssetLifecycle) -> bool`; ACTIVE만 True. PURGED는 삭제 작업 결과용이며 DB 문서 행 잔존을 뜻하지 않는다.

- [x] 다음 핵심 실패 테스트와 전체 허용/거부 행렬 테스트를 작성한다.

```python
import pytest
from ai_workshop.platform.assets.lifecycle import (
    AssetLifecycle as S, LifecycleAction as A, allows_normal_use, transition,
)

def test_pending_purge_cannot_be_restored():
    with pytest.raises(ValueError, match="invalid_lifecycle_transition"):
        transition(S.PURGE_PENDING, A.RESTORE)

def test_trash_restore_is_distinct_from_version_readiness():
    assert transition(S.ACTIVE, A.TRASH) is S.TRASHED
    assert not allows_normal_use(S.TRASHED)
    assert transition(S.TRASHED, A.RESTORE) is S.ACTIVE
```

- [x] RED: `.venv/Scripts/python.exe -B -m pytest tests/unit/platform/assets/test_asset_lifecycle.py -q -p no:cacheprovider`。
- [x] 다음 표의 전이만 허용하는 데이터 기반 순수 함수로 구현한다.

```python
TRANSITIONS = {
    (S.ACTIVE, A.TRASH): S.TRASHED,
    (S.TRASHED, A.RESTORE): S.ACTIVE,
    (S.TRASHED, A.REQUEST_PURGE): S.PURGE_PENDING,
    (S.PURGE_PENDING, A.START_PURGE): S.PURGING,
    (S.PURGING, A.RETRY_LATER): S.RETRY_WAIT,
    (S.PURGING, A.BLOCK): S.BLOCKED,
    (S.RETRY_WAIT, A.RETRY): S.PURGING,
    (S.BLOCKED, A.RETRY): S.PURGING,
    (S.PURGING, A.COMPLETE): S.PURGED,
}
# production에서는 S/A 별칭 대신 위 enum 이름을 사용한다.
def transition(current, action):
    try:
        return TRANSITIONS[(current, action)]
    except KeyError:
        raise ValueError("invalid_lifecycle_transition") from None
```

- [x] 명시 타입을 적용하고 같은 명령으로 GREEN을 확인한다. 모든 enum 조합에서 표 밖 전이 거부, PURGED의 terminal 성질을 검사한다.
- [x] 독립 검토 후 메인이 이 두 파일만 커밋한다. 이 전이 함수는 권한·revision·완료 증거 검사를 대신하지 않는다.

### Task 2: 보관 기한을 확정하는 정책

**Files:** 생성 `trash_policy.py`, `test_trash_policy.py`.

**Interfaces:** frozen `RetentionPolicy(version: int, days: int)`; `purge_deadline(trashed_at: datetime, policy: RetentionPolicy) -> datetime`.
version/days는 bool을 제외한 양의 int, 시각은 timezone-aware를 요구한다. 결과는 UTC이며 overflow는 `ValueError("invalid_retention_deadline")`다.
policy 미설정은 호출 전에 차단한다. 무기한/임의 기본 기간을 이 함수에서 만들지 않는다.

- [x] 다음 실패 테스트와 bool/0/음수/naive datetime/overflow 사례를 작성한다.

```python
from datetime import UTC, datetime
from ai_workshop.platform.assets.trash_policy import RetentionPolicy, purge_deadline

def test_deadline_uses_explicit_policy_and_remains_a_saved_value():
    deleted = datetime(2026, 1, 1, tzinfo=UTC)
    saved = purge_deadline(deleted, RetentionPolicy(version=1, days=7))
    assert saved == datetime(2026, 1, 8, tzinfo=UTC)
    changed = purge_deadline(deleted, RetentionPolicy(version=2, days=2))
    assert changed == datetime(2026, 1, 3, tzinfo=UTC)
    assert saved == datetime(2026, 1, 8, tzinfo=UTC)
```

- [x] RED: `.venv/Scripts/python.exe -B -m pytest tests/unit/platform/assets/test_trash_policy.py -q -p no:cacheprovider`。
- [x] dataclass `__post_init__`에서 `type(value) is int and value > 0`을 검사한다. 함수는 다음 계산을 수행하고 위 입력/overflow 오류를 명시적으로 변환한다.

```python
from datetime import UTC, timedelta
deadline = trashed_at.astimezone(UTC) + timedelta(days=policy.days)
```

- [x] 같은 명령으로 GREEN. UTC offset 입력이 같은 순간의 UTC 만료일을 반환하는지 검사한다.
- [x] 독립 검토 후 메인이 두 파일만 커밋한다. 정책 변경의 저장·기존 항목 기한 단축은 6단계의 별도 승인 명령이다.

### Task 3: 현재 capability로 휴지통 행위 판정

**Files:** 수정 `trash_policy.py`, `test_trash_policy.py`.

**Interfaces:** `TrashAction(StrEnum)` = LIST, TRASH, RESTORE, PURGE; `allows_trash_action(capabilities: WorkspaceCapabilities, action: TrashAction) -> bool`.
기존 `platform.workspaces.domain.WorkspaceCapabilities`를 재사용한다. 이는 서버가 현재 DB에서 해석한 권한을 소비하는 내부 정책이며, 사용자 JSON이나 UI capability를 신뢰하는 인증 API가 아니다.
개인 생성자·만료·회원 활성·OWNER 판정과 행 잠금은 2단계 SQL 권한에서 수행한다. 본 함수가 그 격리를 검증했다는 주장을 하지 않는다.

- [x] 쓰기만 있는 구성원의 복원 거부, delete-only의 삭제 허용/복원 거부, manage_members만 있는 입력 거부 테스트를 추가한다.

```python
from ai_workshop.platform.workspaces.domain import WorkspaceCapabilities
from ai_workshop.platform.assets.trash_policy import TrashAction, allows_trash_action

def test_writer_cannot_reverse_another_members_deletion():
    caps = WorkspaceCapabilities(read=True, write=True, delete=False, manage_members=False)
    assert not allows_trash_action(caps, TrashAction.RESTORE)

def test_delete_grant_does_not_require_member_management():
    caps = WorkspaceCapabilities(read=True, write=False, delete=True, manage_members=False)
    assert allows_trash_action(caps, TrashAction.TRASH)
    assert not allows_trash_action(caps, TrashAction.RESTORE)
```

- [x] Task2 명령으로 RED를 확인한다.
- [x] 모든 행위는 `capabilities.read and capabilities.delete`; RESTORE만 추가로 `capabilities.write`를 요구한다. 등록되지 않은 행위는 거부한다.

```python
allowed = capabilities.read and capabilities.delete
if action is TrashAction.RESTORE:
    return allowed and capabilities.write
return allowed and action in (TrashAction.LIST, TrashAction.TRASH, TrashAction.PURGE)
```

- [x] 16개 capability 조합×4개 행위의 기대 행렬을 독립적으로 작성해 GREEN을 확인한다. owner ID나 모델명을 소스에 넣지 않는다.
- [x] 독립 보안 검토 후 메인이 해당 두 파일만 커밋한다.

### Task 4: 잔존·누락·공유 자산이 있는 삭제는 완료 금지

**Files:** 생성 `purge_contracts.py`, `test_purge_contracts.py`.

**Interfaces:**
- frozen `CleanupReceipt(participant: str, deleted: int, retained_shared: int, residual_owned: int, verified: bool)`.
- frozen `PurgeDecision(online_complete: bool, reasons: tuple[str, ...])`.
- `assess_purge(*, required_participants: frozenset[str], receipts: tuple[CleanupReceipt, ...], inventory_complete: bool, writers_stopped: bool, references_cleared: bool) -> PurgeDecision`.
참여자 집합은 조립 계층에서 전달한다. Platform에 RAG 고유 참여자명을 고정하지 않는다. 빈 집합도 inventory_incomplete로 거부한다.
건수는 bool을 제외한 0 이상의 int다. 공백뿐인 참여자명은 거부하고 알 수 없거나 중복된 receipt는 성공으로 취급하지 않는다.

- [x] 다음 잔존 테스트와 receipt 누락·중복·미검증, 실행 중 writer, 참조 잔존, 불명확한 inventory 테스트를 먼저 작성한다.

```python
from ai_workshop.platform.assets.purge_contracts import CleanupReceipt, assess_purge

def test_zero_deleted_is_not_proof_of_absence():
    result = assess_purge(
        required_participants=frozenset({"objects"}),
        receipts=(CleanupReceipt("objects", 0, 0, 1, True),),
        inventory_complete=True, writers_stopped=True, references_cleared=True,
    )
    assert not result.online_complete
    assert "owned_residuals" in result.reasons

def test_verified_shared_objects_are_preserved_not_counted_as_residuals():
    result = assess_purge(
        required_participants=frozenset({"objects"}),
        receipts=(CleanupReceipt("objects", 2, 1, 0, True),),
        inventory_complete=True, writers_stopped=True, references_cleared=True,
    )
    assert result.online_complete
```

- [x] RED: `.venv/Scripts/python.exe -B -m pytest tests/unit/platform/assets/test_purge_contracts.py -q -p no:cacheprovider`。
- [x] 입력을 검증하고 다음 순서로 안전 오류 코드를 누적한다. 성공은 모든 조건을 충족한 경우뿐이다.

```python
reasons: list[str] = []
if not inventory_complete or not required_participants:
    reasons.append("inventory_incomplete")
if not writers_stopped:
    reasons.append("writers_active")
if not references_cleared:
    reasons.append("references_remaining")
names = [receipt.participant for receipt in receipts]
if len(names) != len(set(names)) or set(names) != required_participants:
    reasons.append("participant_mismatch")
if any(not receipt.verified for receipt in receipts):
    reasons.append("cleanup_unverified")
if any(receipt.residual_owned for receipt in receipts):
    reasons.append("owned_residuals")
return PurgeDecision(not reasons, tuple(reasons))
```

- [x] 같은 명령으로 GREEN. 부재를 확인한 0건은 성공하고, 공유 보존 건수가 있더라도 해당 문서 전용 잔존이 0이면 성공하는지 확인한다.
- [x] 독립 프라이버시 검토 후 메인이 두 파일만 커밋한다. receipt는 신뢰한 어댑터의 결과이며 프론트 입력으로 발행하지 않는다.
이 함수는 실제 파일 잔존 검사를 수행하지 않으며 백업·외부 삭제 완료를 반환하지 않는다. 검증 방법과 durable receipt 저장은5단계에서 연결한다.

## 최종 검증·인계

- [x] 기존 환경에서 다음을 순차 실행하고 exit code·건수를 작업 기록에 남긴다.

```powershell
.venv/Scripts/python.exe -B -m pytest tests/unit/platform/assets -q -p no:cacheprovider
.venv/Scripts/python.exe -B -m mypy src/ai_workshop/platform/assets/lifecycle.py src/ai_workshop/platform/assets/trash_policy.py src/ai_workshop/platform/assets/purge_contracts.py
.venv/Scripts/python.exe -B -m ruff check --no-cache src/ai_workshop/platform/assets/lifecycle.py src/ai_workshop/platform/assets/trash_policy.py src/ai_workshop/platform/assets/purge_contracts.py tests/unit/platform/assets/test_asset_lifecycle.py tests/unit/platform/assets/test_trash_policy.py tests/unit/platform/assets/test_purge_contracts.py
```

- [x] 실패한 enum전이·미설정/잘못된 기한·권한 철회 입력·잔존/누락 증거가 완료로 바뀌지 않는지 독립 검토한다.
- [x] 메인이 실제 diff에서 API/schema/DB/프론트/실사용 데이터 변경이 없는지 확인하고 작업 기록·WORKBOARD를 마감한다. 최근 완료는5개 이내다.
- [x] 계약만 완료됐고 사용자 삭제 테스트는 아직 불가능함을 명시한다. 다음은 이 계약을 소비하는 영속 모델·SQL 권한·provenance 계획이다.
- [x] 원본/파생물/캐시를 실제로 삭제하거나 테스트 서버/DB를 생성하지 않았음을 기록한다. 기존 미커밋 UI 변경은 그대로 둔다.

## 메인 자가 검토

- 전체 설계 coverage는 위 단계 표로 구분했다. 이 계획의 범위는 §2–4/6/8–9의 순수 판단뿐이며 전체 삭제 완료 게이트는7단계다.
- Task2의 RetentionPolicy와 Task3의 TrashAction은 같은 정책 파일을 순차 수정한다. 병렬 파일 소유권을 배정하지 않는다.
- Task4의 온라인 완료 판정은 Task1 COMPLETE 호출의 필요조건이다. 실제 command service는 권한·revision과 영속 증거를 추가 검증해야 한다.
- 모든 테스트 입력의 날짜/기간/participant 이름은 합성 fixture이며 운영 기본값이 아니다.
