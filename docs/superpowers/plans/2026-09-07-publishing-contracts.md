# Publishing Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공개 편집본 승인과 공개 저장소 적용의 순수 계약을 실제 테스트 가능한 Python 코드로 만든다.

**Architecture:** Platform Publishing에서 canonical snapshot과 private 승인 상태를 분리한다. 공개 projection은 private DB를 읽지 않고 신뢰된 전달 경계가 검증한 명령만 적용한다. 이 첫 계획은 저장 어댑터·API·UI를 포함하지 않는 기반 구현 단위다.

**Tech Stack:** 기존 Python 3.13, Pydantic 2, pytest, Ruff, mypy. 추가 dependency 없음.

**Spec:** `docs/superpowers/specs/2026-09-07-public-study-management-design.md`

## Global Constraints

- main의 기존 변경을 보존하고 자동 커밋·push는 수행하지 않는다.
- 새 기록과 이후 수정본의 기본값은 비공개로 유지한다.
- 원본 ID·사용자 ID·호스트 경로·endpoint·인증 정보·개인정보·비공개 문서·raw log·모델 내부 추론은 export에서 제외한다.
- 공개 조회 프로세스에는 비공개 DB 자격 증명과 파일 접근권한을 주지 않는다.
- 임시 산출물은 `.local-data/project-agent-work/publishing-contracts/`만 사용한다.
- 본 계획은 package/domain/projection의 순수 계약만 구현한다. 실제 게시와 관리자 전환 완료로 보고하지 않는다.
- 본문은 첫 버전에서 plain text다. HTML/Markdown 파싱, 자동 링크화, 이미지 로딩은 하지 않는다.
- 자동 민감정보 탐지를 완전한 비식별화 검토로 간주하지 않는다. 공개 내용의 수동 검토는 별도 게이트다.

## 후속 작업 경계

이 계획의 계약을 검증한 뒤 별도 구현 계획에서 private revision/outbox 영속화, 공개 전용 저장
어댑터, owner API, 공개 read-only 서버, 관리자/방문자 UI, 초기 inventory·편집본 게시를 연결한다.
구체적 OS 권한·전달 인증·운영 적용 확인이 없는 상태에서 공개 서버를 활성화하지 않는다.
승인 digest는 무결성 검증이지 명령 발신자의 인증이 아니다. 공개 projection은 trusted importer
뒤에서만 사용한다. 사용자 입력 명령을 직접 projection에 연결하는 endpoint를 만들지 않는다.

### Task 1: 불변 공개 package와 승인·철회 순서 계약

**Files:**
- Create: `backend/src/ai_workshop/platform/publishing/__init__.py`
- Create: `backend/src/ai_workshop/platform/publishing/package.py`
- Create: `backend/src/ai_workshop/platform/publishing/domain.py`
- Create: `backend/src/ai_workshop/platform/publishing/projection.py`
- Test: `backend/tests/unit/platform/publishing/test_package.py`
- Test: `backend/tests/unit/platform/publishing/test_domain.py`
- Test: `backend/tests/unit/platform/publishing/test_projection.py`

**Interfaces:**
- Consumes: 기존 `ai_workshop.shared.errors.AppError`의 code/message/status_code 계약만 재사용한다.
- Produces: 아래 immutable 타입과 함수. persistence/clock/UUID 생성/network 의존성을 추가하지 않는다.

```python
# package.py — frozen Pydantic models, extra='forbid', strict numeric fields
class PublicPersona(BaseModel):
    slug: str
    label: str

class StudyContent(BaseModel):
    slug: str
    title: str
    summary: str
    topic_keys: tuple[str, ...]
    body: str
    verification: str
    limitations: str
    persona: PublicPersona | None = None

class StudySnapshot(BaseModel):
    schema_version: Literal[1] = 1
    revision: int
    content: StudyContent

def canonical_bytes(snapshot: StudySnapshot) -> bytes: ...
def snapshot_digest(snapshot: StudySnapshot) -> str: ...
def decode_snapshot(payload: bytes, *, expected_digest: str) -> StudySnapshot: ...
```

모든 공개 문자열은 strip 후 빈 문자열을 거부하고 CRLF/CR을 LF로 통일하며 Unicode NFC로
정규화한다. slug/topic/persona slug는 `^[a-z0-9]+(?:-[a-z0-9]+)*$` fullmatch를 사용한다.
topic은 비어 있거나 중복될 수 없다. revision은 strict positive int이며 bool은 거부한다.
persona의 존재 자체는 수동 승인의 증명이 아니며 후속 서비스가 승인된 registry와 대조한다.
운영별 크기 상한은 typed settings에서 처리하며 이 단위에서 임의의 운영 한계를 만들지 않는다.

Canonical encoding uses `model_dump(mode='json')`, `json.dumps(ensure_ascii=False,
sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')`.
Null persona is included. Hash is lowercase SHA-256 hex. Decode verifies raw payload hash against
expected digest, validates schema, then rejects bytes differing from canonical re-encoding. This
rejects duplicate keys, alternate whitespace, unknown fields, wrong schema and changed content.
Malformed input returns safe `publishing_package_invalid` 422 without echoing raw bytes.

```python
# domain.py — frozen dataclasses; no private fields in package
class PublicationAction(StrEnum):
    PUBLISH = 'publish'
    WITHDRAW = 'withdraw'

@dataclass(frozen=True)
class PublicationCommand:
    slug: str
    sequence: int
    request_id: str
    action: PublicationAction
    snapshot: StudySnapshot | None
    digest: str | None

@dataclass(frozen=True)
class PublicationDraft:
    snapshot: StudySnapshot
    approved_digest: str | None = None
    sequence: int = 0

    def revise(self, content: StudyContent, *, expected_revision: int) -> PublicationDraft: ...
    def approve(self, *, expected_revision: int, expected_digest: str) -> PublicationDraft: ...
    def publish(self, *, request_id: str) -> tuple[PublicationDraft, PublicationCommand]: ...
    def withdraw(self, *, request_id: str) -> tuple[PublicationDraft, PublicationCommand]: ...
```

revise checks current revision, forbids slug rename, increments revision and clears approval without
changing command sequence. approve validates exact revision/digest. publish requires matching approval,
increments sequence, produces matching snapshot/digest. withdraw increments sequence, clears approval,
emits no body/digest. No method claims a command was delivered. Wrong revisions/digests/states are
safe AppError 409. Re-publication after withdraw requires approve again; repeat publish commands
are valid new sequences when explicitly requested. Commands have nonblank request_id, strict positive
sequence; publish payload slug and digest must match; withdraw payload must be absent.

```python
# projection.py — immutable public serving state, caller persists transactionally later
@dataclass(frozen=True)
class PublicStudyProjection:
    slug: str
    sequence: int = 0
    last_command: PublicationCommand | None = None
    snapshot: StudySnapshot | None = None

    def apply(self, command: PublicationCommand) -> PublicStudyProjection: ...
    def read(self) -> StudySnapshot: ...
```

apply rejects wrong slug and malformed command; newer sequence atomically replaces state in returned
object; lower sequence fails 409 without resurrecting data. Same sequence and exact same command is
idempotent; same sequence with different action/request_id/content fails 409. Reusing the last request_id
with different command also fails. Persistent outbox will enforce historical request_id uniqueness later.
Gaps in sequence allowed so later withdrawal can supersede undelivered publish. Withdrawal stores a
tombstone (sequence + safe last command), no snapshot. read returns a revalidated approved snapshot or
uniform `not_found` 404 for empty/withdrawn state. Never retain old public body after withdrawal.

- [x] **Step 1: Add first failing behavior test**, e.g.:

```python
def test_withdrawal_prevents_late_publish_resurrection():
    draft = PublicationDraft(snapshot=synthetic_snapshot())
    draft = draft.approve(expected_revision=1, expected_digest=snapshot_digest(draft.snapshot))
    draft, publish = draft.publish(request_id='publish-request')
    draft, withdraw = draft.withdraw(request_id='withdraw-request')
    public = PublicStudyProjection(slug='example-study').apply(withdraw)
    with pytest.raises(AppError) as failure:
        public.apply(publish)
    assert failure.value.status_code == 409
    with pytest.raises(AppError) as hidden:
        public.read()
    assert hidden.value.code == 'not_found'
```

`synthetic_snapshot()` is a test-only helper constructing revision 1, slug `example-study`, topic
`rag`, synthetic Korean plain-text title/summary/body/verification/limitations, no real source data.
First test must fail by an assertion about missing functionality: import inside the test with a clear
assertion if module missing, rather than treating an unexplained collection error as behavioral RED.

- [x] **Step 2: Run RED**, cwd `backend`: `.venv/Scripts/python.exe -m pytest tests/unit/platform/publishing -q`.
  Record actual assertion failure and missing behavior before production code.
- [x] **Step 3: Implement minimal behavior in small RED/GREEN cycles.** Exact contract above is binding.
  Cover literal canonical byte order, Korean NFC/line endings, digest tampering, duplicate JSON keys,
  unknown private fields, schema/revision bool/negative, slug traversal/blank fields/topic duplicates;
  wrong approval digest, stale revision, edit clearing approval, private edit preserving previously
  returned public state, withdrawal/reapproval, stale/same-sequence conflicting commands and absent body.
- [x] **Step 4: Verify tests and static checks**, cwd `backend`:
  `.venv/Scripts/python.exe -m pytest tests/unit/platform/publishing tests/unit/platform/learning -q`
  `.venv/Scripts/python.exe -m ruff check src/ai_workshop/platform/publishing tests/unit/platform/publishing`
  `.venv/Scripts/python.exe -m mypy src/ai_workshop/platform/publishing`
  Tests must exercise real objects, not mock-only forwarding; no model/network/DB access.
- [x] **Step 5: Self-review and hand off.** Report RED/GREEN, files, limits and commands to
  `.local-data/project-agent-work/publishing-contracts/task-1-report.md`. No staging or commit.
  Controller supplies independent task review and final integration review; fixes return to implementer.

## Completion / next work

Only the above pure contract is complete when tests and independent review pass. Next work is durable
private draft/outbox and public-store application, then API/UI. No candidate source material is loaded,
no app database is migrated, no public content is posted by this foundation plan.
