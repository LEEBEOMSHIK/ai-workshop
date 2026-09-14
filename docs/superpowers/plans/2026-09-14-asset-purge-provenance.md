# 휴지통 2C 출처·목록·증명 저장 기반 구현 계획

> 실행: subagent-driven-development. main에서만 작업하며 구현자와 독립 검토자를 분리한다.

**Goal:** 삭제 출처와 버전된 대상 목록, 실행에 결합된 검증 결과 및 본문 없는 최소 증명을 저장한다. 실제 삭제 완료 명령은 활성화하지 않는다.
**Architecture:** Platform Assets의 순수 계약 → SQLAlchemy 저장 모델/저장소. 소유 모듈이 자원 ID를 해석하며 Platform은 Labs를 참조하지 않는다.
**Tech Stack:** 기존 Python 3.13, SQLAlchemy, Alembic, PostgreSQL, pytest. 추가 패키지 없음.
**Spec:** `docs/superpowers/specs/2026-09-14-asset-purge-provenance-design.md` (사용자 승인).

## Global Constraints

- 실제 삭제 API·worker·UI·서버 재시작·실사용 DB migration·push는 제외한다. 기존 UI 미커밋 변경을 보존한다.
- 기존 backend/.venv와 UUID 격리 DB helper만 사용한다. pytest는 `-B -p no:cacheprovider --tb=short`, Ruff는 `--no-cache`로 실행한다.
- 출처는 workspace/document/asset version UUID 조합이다. 공통 추적/증명에는 본문·질의·파일명·경로·원본 SHA-256을 넣지 않는다.
- 원문 복제(source_copy), 파생물(derived_artifact), 독립 작성 참조(authored_reference)를 구별한다. 공유라는 이유만으로 대상 소유 본문 잔존을 허용하지 않는다.
- 참여자 집합은 호출자가 응답에서 추론하지 않고 신뢰된 조립 설정에서 공급한다. 기존 자료/페이지 소진/미지원 여부 불확실은 fail closed다.
- 목록은 job/workspace/version, 명시적 문서·폴더 대상 집합, 모든 asset version 및 lifecycle generation, 참여자 계약 버전, 자원 revision에 결합된다.
- 증명은 온라인 검증 결과와 백업/외부 확인 대기를 구별한다. 외부 권위 원장·복구 게이트는 후속이며 단일 DB 저장은 전체 삭제 증명이 아니다.
- 저장소는 호출자의 트랜잭션을 사용하고 commit하지 않는다. 이번 코드에서 job을 purged로 바꾸는 운영 명령은 만들지 않는다.
- 아래 원자성 검사는 합성 DB에서 미래 완료 명령의 트랜잭션을 직접 구성하여 증명 저장/상세 정리/job 갱신의 rollback을 검증한다. 테스트 전용 완료 함수를 업무 코드에 넣지 않는다.

## Task 1: 순수 식별·목록·receipt 결합 계약

Files:
- Create `backend/src/ai_workshop/platform/assets/provenance_contracts.py`
- Create `backend/src/ai_workshop/platform/assets/purge_inventory_contracts.py`
- Create `backend/tests/unit/platform/assets/test_provenance_contracts.py`
- Create `backend/tests/unit/platform/assets/test_purge_inventory_contracts.py`
- Existing `purge_contracts.py`의 `assess_purge`는 유지한다.

계약:
- frozen `SourceIdentity(workspace_id: UUID, document_id: UUID, asset_version_id: UUID)`.
- frozen `ResourceIdentity(participant: str, kind: str, resource_id: UUID, revision: int)`와 `SourceRelation(source, resource, relation_kind)`; 키는 제한된 기계 식별자, revision 양수, bool 거부.
- frozen `DocumentTarget(document_id, generation: int, asset_version_ids: tuple[UUID,...])`, `FolderTarget(folder_id, generation: int)`; 중복/빈 버전 집합 거부. 빈 문서 목록은 폴더만 있는 배치를 표현할 수 있으나 전체 대상이 비면 완료 불가.
- frozen `ParticipantInventory(participant, contract_version: int, resources: tuple[ResourceIdentity,...], exhausted: bool, supported: bool, legacy_resolved: bool)`; 모두 확인되어야 완전하다. resources가 빈 경우에도 명시적인 exhausted 확인이 필요하다.
- frozen `PurgeInventory(workspace_id, job_id, version: int, documents, folders, participants)`.
- `inventory_binding(inventory) -> str`: 정렬한 UUID/기계 식별자/정수/검사 플래그의 canonical JSON SHA-256. 입력 순서는 무관하며 대상·generation·계약·revision 변경 시 달라진다. 문서 내용 해시가 아니다.
- frozen `BoundCleanupReceipt(job_id, inventory_version, inventory_binding, participant_contract_version, attempt: int, checked_at: datetime, receipt: CleanupReceipt)`; UTC 인식 시각, 양수 버전/시도, 실제 bool 검증.
- `assess_bound_purge(*, inventory, required_participants: frozenset[str], receipts: tuple[BoundCleanupReceipt,...], attempt: int, writers_stopped: bool = False, references_cleared: bool = False) -> PurgeDecision`: 정확한 결합·누락·중복·완전성 검사 후 기존 assess_purge 활용. 이 함수는 순수 판정이며 권한/서버 증거의 인증 수단이 아니다. 기본값으로 완료 불가, API에 연결하지 않는다.
- `proof_binding(*, inventory, receipts, required_participants: frozenset[str]) -> str`: 신뢰된 필수 참여자와 목록/receipt의 exact-match를 먼저 확인한다. 대상/계약과 정렬된 검증 결과·시도·시각까지 결합, 임의 payload 금지.

- [x] RED: 다른 job/version/generation/revision/계약/시도, 중복/누락, 미완성 페이지, legacy 미확정, mixed residual+retained_shared의 실패 테스트를 먼저 실행한다.
- [x] GREEN: 최소 구현. 모든 버전과 여러 출처의 동일 resource 연결, 독립 동일 바이트 문서는 서로 다른 식별자인 점을 검증한다.
- [x] canonical 순서 안정성과 결합 변경, naive datetime·bool 정수·잘못된 키 거부를 검증한다.
- [x] 관련 단위 테스트, mypy, Ruff 후 구현 보고서와 독립 리뷰.

## Task 2: 출처 관계 SQL 저장 기반

Files:
- Create `backend/src/ai_workshop/platform/assets/provenance_models.py`
- Create `backend/src/ai_workshop/platform/assets/provenance_repository.py`
- Modify `backend/src/ai_workshop/platform/assets/models.py` (복합 참조 UNIQUE만)
- Modify 모델 registry 및 `backend/alembic/env.py` (현행 등록 방식 사용)
- Create `backend/alembic/versions/0038_asset_provenance.py`
- Create `backend/tests/integration/platform/assets/test_provenance_persistence.py`

스키마:
- documents `(workspace_id,id)` UNIQUE, asset_versions `(document_id,id)` UNIQUE.
- `asset_source_relations`: UUID PK, workspace/document/asset_version UUID, participant/kind 제한 식별자 VARCHAR(80), resource UUID, resource_revision BIGINT >0, relation_kind VARCHAR(32) CHECK, created_at timezone.
- 두 복합 FK로 정확한 source 조합 확인, ON DELETE RESTRICT (검증 전 추적 유실 방지).
- `(workspace,document,asset_version,participant,kind,resource,resource_revision,relation_kind)` UNIQUE. resource 중심 조회 INDEX.
- `ProvenanceRepository(session: AsyncSession).register(relation: SourceRelation) -> None`, `list_for_source(source) -> tuple[SourceRelation,...]`, `list_for_resource(workspace_id,resource) -> tuple[SourceRelation,...]`. flush만 수행, commit하지 않으며 중복 등록은 멱등적이다. 공유 참조는 유지한다.
- migration은 additive, downgrade는 관계 행이 있으면 안전 코드로 거부하고 비어 있을 때만 제거한다. 기존 행 backfill/추적완료 표시는 하지 않는다.

- [x] RED: 교차 공간/다른 문서 버전 등록 거부, 중복 멱등성, 동일 resource의 여러 출처 조회, 트랜잭션 rollback, source 삭제 RESTRICT를 합성 DB에서 검증한다.
- [x] GREEN: 모델/저장소/0038과 metadata 등록 구현.
- [x] 0037→0038 이전 자료 보존, 비어 있는 downgrade 성공·비어 있지 않으면 거부, ORM/SQL 제약 일치 검증.
- [x] 타입·린트·관련 통합 테스트 및 독립 리뷰.

## Task 3: 버전된 목록·receipt·최소 증명 저장 기반

Files:
- Create `backend/src/ai_workshop/platform/assets/purge_inventory_models.py`
- Create `backend/src/ai_workshop/platform/assets/purge_inventory_repository.py`
- Create `backend/src/ai_workshop/platform/assets/purge_inventory_storage.py` (내부 SQL 행 재구성·삽입 매핑만, 공개 계약 없음)
- Create `backend/src/ai_workshop/platform/assets/purge_proof_models.py`
- Modify `backend/src/ai_workshop/platform/assets/purge_inventory_contracts.py` 및 해당 단위 테스트 (최소 증명 payload 정합성만)
- Modify `backend/src/ai_workshop/platform/assets/purge_models.py` (workspace/id UNIQUE만)
- Modify 기존 모델 registry 및 `backend/alembic/env.py`
- Create `backend/alembic/versions/0039_asset_purge_inventory.py`
- Create `backend/tests/integration/platform/assets/test_purge_inventory_persistence.py`
- Create `backend/tests/integration/platform/assets/test_purge_proof_persistence.py`
- Modify `backend/tests/integration/platform/assets/test_trash_migration.py` (head 왕복 검사의 과거 최신 버전 고정값 제거, 기존 보존/실패 검증 유지)

정규화 저장 (임의 본문 JSON payload 없음):
- `asset_purge_inventories`: UUID PK, workspace/job UUID 복합 FK RESTRICT, version>0, binding CHAR(64), created_at; UNIQUE(workspace,job,version)와 UNIQUE(workspace,id).
- `asset_purge_inventory_targets`: inventory 복합 FK RESTRICT, target_kind(document/folder), target UUID, generation>0, asset_version UUID nullable (folder일 때만 NULL); 대상·버전 중복 금지. 원본 FK 없음: 정확한 실재/공간/버전/generation 검사는 목록 저장 시 수행한다.
- `asset_purge_inventory_participants`: inventory 복합 FK, participant, contract_version>0, exhausted/supported/legacy_resolved bool; UNIQUE(inventory,participant).
- `asset_purge_inventory_resources`: participant 소속 복합 FK, kind/resource UUID/revision>0; 동일 inventory/participant/kind/resource/revision UNIQUE.
- `asset_purge_receipts`: inventory+participant 복합 FK, attempt>0, checked_at timezone, binding CHAR(64), contract_version>0, deleted/retained_shared/residual_owned >=0, verified bool; UNIQUE(inventory,participant,attempt).
- `asset_purge_proofs`: UUID PK, workspace/job UUID UNIQUE 및 job RESTRICT FK, inventory_version>0, inventory_binding CHAR(64), binding CHAR(64), actor UUID nullable, policy_version>0, finished_at timezone, backup_state('pending'), external_state('unverified'). 원본/상세 inventory FK 없음.
- `asset_purge_proof_targets`: proof FK RESTRICT, target_kind/target UUID/generation/asset_version (target 제약 동일).
- `asset_purge_proof_participants`: proof FK RESTRICT, participant/contract_version/attempt/checked_at/deleted/retained_shared/residual_owned/verified; UNIQUE(proof,participant), CHECK(verified AND residual_owned=0), 최소 성공 결과만.

`PurgeInventoryRepository(session: AsyncSession)`:
- `save_inventory(inventory: PurgeInventory) -> None`: job→batch→대상 문서/폴더→기존 asset version 잠금을 트랜잭션 종료까지 유지하여 FK 기반 배치 유입과 버전 삭제 경합을 차단한다. workspace/batch의 명시적 대상 집합·모든 버전·현재 generation 대조. 복구 상태/다른 batch 대상 거부. 최초 version=1, 이후 max+1만 허용. 기존 목록 덮어쓰기 금지. 기존 목록·receipt는 재시도 상세 자료로 보존.
- `load_inventory(workspace_id,job_id,version) -> PurgeInventory | None`.
- 현재 SQL 재검증은 header/participant에도 적용한다. 이미 session에 존재하는 객체의 binding/contract_version을 재사용하지 않고 refresh 또는 column 조회로 대조한다.
- `save_receipt(workspace_id, receipt: BoundCleanupReceipt) -> None`: 현재 최신 목록/binding/계약/현재 job attempt 정확히 일치할 때만 저장. 중복은 거부, 완료 job 쓰기 거부. flush만.
- `store_proof(*, inventory, receipts, required_participants, actor_id, policy_version, finished_at, writers_stopped=False, references_cleared=False) -> UUID`: 내부 저장 어댑터이며 API/worker에는 미연결. job 잠금 후 저장된 최신 목록과 저장된 receipts를 다시 읽어 전달 후보와 대조, status=purging의 현재 attempt 및 순수 판정 통과만 허용. policy/actor는 batch 대조. 상세 정리나 job 완료를 자동 실행하지 않는다. caller boolean은 순수 계약 테스트용이며 현재 권한·writer 증거의 인증을 대체하지 못한다고 명시한다.
- 실제 완료 서비스는 후속에서 서버 증거·권한·writer gate를 먼저 확인하고 위 저장 어댑터 및 상세 정리를 하나의 트랜잭션에 연결해야 한다. 본 단계에는 활성화 경로가 없다.
- `proof_binding`의 canonical payload는 영구 보존하는 최소 필드만 사용한다: workspace/job/목록 version, inventory_binding, 문서·폴더·세대·버전 대상 집합, 참여자 계약과 결합 receipt 결과. 상세 resource 목록은 inventory_binding에 간접 결합하고 증명 payload에 다시 넣지 않는다. 상세 정리 후 남은 행만으로 증명 결합값을 재계산할 수 있게 한다.
- `retained_proof_binding(*, workspace_id: UUID, job_id: UUID, inventory_version: int, inventory_binding: str, documents: tuple[DocumentTarget,...], folders: tuple[FolderTarget,...], receipts: tuple[BoundCleanupReceipt,...], required_participants: frozenset[str]) -> str`를 같은 순수 계약 파일에 둔다. 보존 필드의 타입·중복·exact binding을 검증하는 최소 진입점이며 기존 `proof_binding`은 상세 목록 검증 후 이 함수에 위임한다. 해시는 발행자 인증이나 실제 삭제 증거를 대신하지 않는다.

- [x] RED: workspace/job/inventory 혼합 거부, 전체 버전 누락·generation 변경·폴더/문서 batch 불일치 거부, 순차 버전·stale receipt·중복·재시도 격리 테스트.
- [x] GREEN: SQL 모델/제약/저장소 및 0039 구현, 등록.
- [x] 합성 성공 후보에 대한 최소 증명 저장 후 같은 트랜잭션에서 상세 목록 제거와 job 완료 갱신을 테스트가 직접 실행한다. 중간 예외 rollback, 성공 commit, 원본 삭제 후 증명 존속을 검증한다. 운영 완료 메서드/테스트 전용 생산 코드는 만들지 않는다.
- [x] 증명에는 원본 body/path/hash가 없고 원본과 독립적으로 남으며 backup/external은 미확인 상태인 것을 검증한다.
- [x] 상세 목록 삭제 후 보존한 증명 행의 최소 필드만으로 canonical 결합값을 재계산하는 검사를 추가한다.
- [x] 0038→0039 기존 자료 보존, 상세/증명 존재 downgrade 거부·빈 테이블 downgrade 성공, SQL 제약·타입·린트·독립 리뷰.

## 통합 검증과 종료

- [x] Task 간 source/receipt/inventory 직렬화·타입·키 제약 결합을 검토한다.
- [x] 기존 Assets 단위 및 격리 DB 안전성·휴지통/권한/API 통합 회귀와 추가 테스트를 메인이 실행한다.
- [x] 최종 독립 전체 리뷰. 설계/구현 차이, 현재 미연결 상태, 실제 DB0034 유지 사실을 기록한다.
- [x] WORKBOARD 현재/다음 작업과 최근 완료 최대5개 갱신, 작업 기록 작성. 관련 파일만 main에서 커밋 가능, push하지 않는다.

계획 자체 검토: 승인안의 첫 공통 저장 범위만 포함한다. 실제 모듈별 등록/수집·worker gate·삭제 실행·UI와 백업 원장 구현은 후속이다. 논리 판정과 서버 증거 인증을 혼동하지 않는다.

독립 검토 보완: Task 1의 증명 결합 함수에도 신뢰된 필수 참여자 인자를 추가한다. 목록 자체의 참여자를 완전성 기준으로 재사용하는 것을 막기 위한 승인안 정합성 보완이며, 후속 저장소도 같은 인자를 전달한다.
