# RAG Index Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** 생성 전 등록된 build별 ES 대상과 prepare 시도를 실제 색인·출처 목록에 연결한다.

**Architecture:** RAG 소유 원장과 추적 ES 어댑터를 추가한다. 기존 ingestion·activation·parity를 이 원장과 연결하고 공통 ParticipantInventory로 읽기 결과를 반환한다. Platform의 RAG 의존은 만들지 않는다.

**Tech Stack:** Python 3.13, SQLAlchemy/PostgreSQL, Alembic, Elasticsearch 9.5 Python client, pytest, mypy, Ruff.

**Spec:** [승인된 상세안](../specs/2026-09-20-rag-index-provenance-design.md).

## Global Constraints

- 사용자 2026-09-20 지시: 상세안 이후 바로 구현. 계획 재승인 질문 없이 구현·독립 검증까지 진행한다.
- 기존 backend/.venv를 사용하며 패키지 설치·실사용 DB/ES 변경·migration·backfill·서버 재시작·삭제 활성화·push는 하지 않는다.
- 단위 테스트는 네트워크 없이 실행한다. DB 검증은 기존 안전 검사 helper가 생성한 UUID 전용 합성 DB만 사용한다.
- 모델·검색 순위·UI 변경 없음. 기존 무관한 프론트 및 설계 변경을 보존한다.
- 미확인 prepare writer는 자동 인계하지 않는다. alias writer 종료 증명·실제 purge는 이번 완료 조건이 아니다.
- 구현 책임과 독립 검증/리뷰 책임은 분리한다. 메인만 WORKBOARD·통합·Git 조작을 담당한다.

## Review Focus

- 같은 이름의 다른 ES UUID 및 잘못된 cluster: 첫 bulk 전에 차단(Task2).
- timeout 뒤 숨은 SDK retry/worker 재전달: 추가 mutation 없이 open 보존(Task2/3).
- 기존 legacy와 새 tracked build 혼합 alias: 다른 문서 target 보존(Task3).
- count가 같은 다른 chunk 또는 부분 shard 결과: inventory 성공으로 판정하지 않음(Task2/4).
- activation/parity의 여러 build 변경과 DB rollback: 모든 해당 revision 원자성(Task1/3).

## 실행 환경과 역할

Git worktree를 `.worktrees/rag-index-provenance`에 생성하려 했으나 `.git/refs` 쓰기 권한 제한으로 실패했다.
using-git-worktrees의 sandbox fallback에 따라 현재 checkout에서 정확한 파일 범위만 변경한다. 별도 worktree는 생성되지 않았다.
메인은 요구/시스템/RAG·색인/테스트 설계·통합을 맡는다. DB 구현과 추적 ES 구현은 별도 담당, 통합 검증·프라이버시·코드 리뷰는 구현과 독립된 담당에게 배정한다.
이번 계획의 실행 기록은 `docs/worklogs/2026-09-20-rag-index-provenance.md`에 유지한다. 중간 임시 기록이 필요하면 프로젝트 규칙의 `.local-data/project-agent-work/rag-index-provenance/`만 사용한다.

## 공유 인터페이스

Task1이 `indexing/tracking_contracts.py`의 frozen dataclass와 안전 오류를 소유한다.
다음 타입은 Task2/3/4의 공통 계약이며 명칭 변경 시 소비자와 동시에 조정한다.

```python
@dataclass(frozen=True)
class IndexBinding:
    store_id: str
    cluster_uuid: str

@dataclass(frozen=True)
class IndexResource:
    build_id: UUID
    projection_id: UUID
    job_id: UUID
    workspace_id: UUID
    document_id: UUID
    asset_version_id: UUID
    document_processing_profile_id: UUID
    indexing_profile_id: UUID
    revision: int
    binding: IndexBinding
    index_name: str
    alias: str
    mapping_version: int
    vector_dimension: int
    similarity: str
    index_uuid: str | None
    input_fingerprint: str | None
    chunk_ids_sha256: str | None = None

@dataclass(frozen=True)
class IndexClaim:
    resource: IndexResource
    attempt_id: UUID

class IndexTrackingError(RuntimeError):
    code: str  # allowlisted machine code; no raw exception payload
```

repository는 전달된 session을 사용하고 commit하지 않는다.
`SqlAlchemyRagIndexRepository(session)`은 `get(build_id)`, `register(build_id, binding, descriptor, index_name, alias)`,
`reserve(build_id, input_fingerprint, *, chunk_ids_sha256)`, `observe_uuid(claim, index_uuid)`, `finish(claim, result_code)`, `advance(build_ids)`를 제공한다.
contracts의 `index_chunk_ids_fingerprint(ids)`로 정렬된 입력 집합 digest를 고정한다. 이후 SQL·ES 집합 대조에 사용한다.
register는 실제 build/projection/ingestion/source를 조회해 원장을 생성한다. reserve/observe/finish/advance는 revision과 정확한 현재 관계를 원자적으로 갱신한다.
`observe_uuid`는 새 revision을 담은 IndexClaim을 반환한다. `finish` 결과 코드는 명명된 allowlist만 허용한다.
Task2는 `TrackedElasticsearchIndex`와 `index_input_fingerprint(documents)`를 제공한다.
추적 어댑터는 `prepare(resource, documents, on_identity)`에서 정확한 identity 확인 직후 async callback으로 UUID를 영속화하고 쓰기를 진행한다.
`observe(resource, expected_chunk_ids)`는 identity·mapping·전체 소유 레코드·chunk ID·alias를 검사하고 본문 없는 typed 관찰 결과를 반환한다.
Task3는 prepare/activation orchestration, Task4는 전체 상태 DB snapshot과 이 관찰 결과를 조합한다.

### Task 1: 원장·제약·migration과 repository

**Files:** Create `backend/src/ai_workshop/labs/rag/indexing/tracking_contracts.py`, `resource_models.py`, `resource_repository.py`;
create `backend/alembic/versions/0042_rag_index_resources.py`(실제 migration 경로/head 확인);
modify metadata 등록 모듈; create `backend/tests/unit/labs/rag/indexing/test_tracking_contracts.py`,
`backend/tests/integration/labs/rag/indexing/test_resource_repository.py`, `test_resource_migration.py`.

**Interfaces:** 위 IndexBinding/Resource/Claim/Error와 repository를 생산한다. 기존 ProvenanceRepository와 build/projection/job/source를 소비한다.

- [x] RED: 잘못된 binding·revision 거부, cross-source/profile/job FK, RESTRICT, open UNIQUE, 현재 관계 CAS·rollback 테스트 작성/실행.
  핵심 검증: `with pytest.raises(IndexTrackingError): await repository.reserve(build_id, changed_fingerprint)`;
  `assert (await repository.get(build_id)).revision == previous_revision` after rollback.
- [x] GREEN: 원장/시도와 복합 FK, additive migration·거부형 downgrade 구현. 같은 값의 재확인은 revision 유지.
- [x] 기존 합성 DB fixture를 사용해 등록→시도→UUID 확인→종료·재시도 및 source 삭제 거부를 실제 검증.
- [x] 관련 pytest·mypy·Ruff 통과 후 변경 목록과 RED/GREEN 증거를 메인에게 인계. 독립 검토 후 수정한다.

### Task 2: ES 소유권 검사·추적 prepare

**Files:** Create `backend/src/ai_workshop/labs/rag/indexing/tracked_elasticsearch.py`,
`backend/tests/unit/labs/rag/indexing/test_tracked_elasticsearch.py`.

**Interfaces:** Task1 타입을 소비한다. prepare/observe·typed observation·canonical fingerprint를 생산한다.

- [x] RED: fake client에서 cluster/UUID 충돌, legacy metadata, alias/data stream, 다른 소유 레코드, 같은 count 다른 chunk, shard failure 테스트.
  핵심 검증: `assert fake.bulk_calls == 0` after identity rejection; timeout test keeps callback/claim unresolved.
- [x] GREEN: 단일 concrete target, sibling `_meta.rag_index_resource`, UUID callback, `_meta.rag` 호환, 정확한 전체 집합 검사 구현.
- [x] 자동 retry를 끈 mutation client 사용·호출 횟수 및 원시 bulk 오류 비노출 검증. 실제 ES client signature는 설치된 패키지로 확인.
- [x] 기존 frozen inspector/기존 indexing 단위 회귀·mypy·Ruff 실행 후 독립 리뷰 인계.

### Task 3: ingestion·activation·parity 연결

**Files:** Modify `backend/src/ai_workshop/config.py`, `labs/rag/ingestion/stages.py`,
`labs/rag/indexing/recovery.py`, 필요한 worker 안전 오류 분류; create `labs/rag/indexing/tracking_service.py`;
modify/create 관련 `backend/tests/unit/labs/rag/ingestion/`, `backend/tests/integration/labs/rag/indexing/` 테스트.

**Interfaces:** Task1 원장과 Task2 adapter 소비. 신규 build 예약·tracked prepare 및 build revision 변경 경계를 생산한다.

- [x] RED: 등록 실패면 ES 0건, UUID 저장 후 prepared 최종화 rollback, busy/미확인 요청이 기존 작업 실패로 전파되지 않는 테스트.
- [x] GREEN: 새 build에 exact name/binding/descriptor 예약; 기존 untracked build는 legacy 유지. typed settings에 store ID/cluster UUID 검증 추가.
- [x] prepare 예약 commit→외부 I/O→UUID 저장→prepared/attempt 종료의 순서를 서비스로 분리하고 raw ES 오류를 안전 코드로 변환.
- [x] profile 아래 모든 변경 build 정렬 잠금 및 resource revision/current relation 동시 갱신. 기존 no-op과 alias 잠금 직렬화 유지.
- [x] 기존 단위/격리 DB activation/parity 테스트와 회귀·정적 검사 후 독립 리뷰 인계.

### Task 4: 읽기 목록·최종 검증과 문서

**Files:** Create `backend/src/ai_workshop/labs/rag/indexing/resource_inventory.py`,
`backend/tests/integration/labs/rag/indexing/test_resource_inventory.py`; modify runbook·설계 상태·작업 기록·WORKBOARD.

**Interfaces:** Task1 원장과 Task2 observe를 소비해 공통 `ParticipantInventory`를 반환한다.

- [x] RED: 전체 version/generation·모든 build 상태·역방향 relation 불일치·legacy·open attempt·조회 중 변경·미생성 build 테스트.
  핵심 검증: `assert not result.exhausted` for open prepare; `assert not result.legacy_resolved` for missing tracked build.
- [x] GREEN: DB→ES→DB 관찰과 정확한 chunk 집합·alias 대조, 공통 DTO는 ID/revision/flags만 반환.
- [x] 기존 indexing/ingestion/artifact/SQL 출처 단위 및 검토된 격리 DB 통합 실행. 전체 앱 DB 통합을 임의 실행하지 않음.
- [x] 독립 통합·코드/프라이버시 검토의 결함 수정·재검증, 설정/legacy/미확인 writer 운영 조건 기록.
- [x] 메인이 최종 변경 범위·검증 결과·남은 실사용 적용 경계를 정리하고 WORKBOARD 최근 완료 최대 5개 유지.

## 검증 명령

backend 작업 디렉터리에서 기존 `.venv/Scripts/python.exe -B -m pytest <위에 명시한 테스트 파일> -q --tb=short -p no:cacheprovider`를 사용한다.
정적 검사는 `.venv/Scripts/python.exe -m mypy <변경 제품 모듈>`와 `.venv/Scripts/python.exe -m ruff check <변경 Python 파일>`이다.
새 테스트 파일은 각 Task의 RED 단계에서 실제 생성 후 실행하며 경로가 달라지면 계획과 검증 기록을 함께 갱신한다.
실제 ES 통합은 전용 자원 안전 경계가 검증된 경우에만 실행하고, 실행하지 못한 경우 fake 통과와 구분해 보고한다.

## 계획 자체 검토

Task1→2/3/4는 공통 타입·원장, Task2→3/4는 prepare/observe 인터페이스로 연결된다.
Task3과 Task4만 메인 통합 시 기존 코드/문서를 변경하며 Task1·2 구현 파일은 겹치지 않는다.
각 Task의 RED/GREEN은 해당 산출물을 검증한다. 상세안 §1–11은 Task1–4에, §12 수용 조건은 각 테스트 단계에 대응한다.
사용자의 바로 구현 지시를 실행 방식 선택으로 적용하고, 프로젝트의 역할 분리 지침에 따라 구현과 독립 검증을 분리한다.
