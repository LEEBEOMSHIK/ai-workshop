# RAG Alias Write Fence Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

**Goal:** 공유 별칭의 미확인 writer를 영속 추적하고 차단 문서가 다시 색인·활성화되지 않도록 한다.
**Architecture:** RAG 내부 요청 원장·문서 fence를 기존 source/profile 잠금 및 inventory에 연결한다.
**Tech Stack:** Python, SQLAlchemy, PostgreSQL, Elasticsearch, pytest, mypy, Ruff.
**Spec:** [구현 계약](../specs/2026-09-20-rag-alias-write-fence-design.md).

## Global Constraints

- 사용자 진행 승인에 따라 구현·검증까지 수행한다. 실사용 데이터·서버·삭제 기능은 변경하지 않는다.
- 이전 worktree 권한 실패의 현재 checkout fallback을 유지하고 기존 변경을 보존한다.
- 메인만 통합·WORKBOARD·Git을 맡는다. DBA 구현과 독립 리뷰는 분리한다.

## Review Focus

- 별도 journal 연결이 source/profile FK로 자신을 기다리지 않아야 한다(Task 1).
- exact membership no-op가 선행 open 요청을 우회하지 않아야 한다(Task 1–2).
- fence는 모든 require_active=False 경로와 삭제 문서의 parity 재활성화를 막아야 한다(Task 3).
- 업무 commit 실패와 ES timeout의 종료 여부를 구분해야 한다(Task 2).
- generation·alias open 상태가 관찰 중 바뀌면 inventory 완료 판정을 거절해야 한다(Task 3).

### Task 1: 별칭 원장

Files: `backend/src/ai_workshop/labs/rag/indexing/alias_models.py`, `alias_journal.py`,
`backend/alembic/versions/0043_rag_alias_operations.py`, metadata 등록 및 `tests/integration/labs/rag/indexing/test_alias_journal.py`.
Interface: `AliasJournal(sessions).reserve(binding, alias, indexing_profile_id, processing_profile_id, targets) -> UUID`;
`finish(operation_id)`는 exact open 소유 요청만 닫는다. `AliasOperationRecord`를 소비자가 조회한다.

- [x] RED: `assert await other_session.get(AliasOperationRecord, operation_id)`; 경쟁 reserve는 안전 busy, rollback 후 open 보존.
- [x] GREEN: immutable identity·partial unique·거부형 downgrade 및 별도 세션 commit 구현.
- [x] pytest·mypy·Ruff 후 메인 인계.

### Task 2: 별칭 실행 연결

Files: `indexing/alias_service.py`, `indexing/elasticsearch.py`, `ingestion/stages.py`, `indexing/recovery.py`와 관련 unit/integration tests.
Interface: 서비스는 원장 예약 후 전달된 alias mutation/observation을 실행하고 확인된 성공만 닫는다.

- [x] RED: timeout 후 두 번째 실행에서 `assert mutation_calls == 1`; 정상 응답/DB rollback 경계·취소·no-op 검증.
- [x] GREEN: 실제 cluster 확인·mutation retry 0·activation/parity 공통 원장 연결·safe 오류.
- [x] 기존 tracked·legacy alias 통합 회귀와 정적 검사.

### Task 3: 문서 fence와 종료 관찰

Files: `indexing/write_fence.py`, `indexing/fence_models.py`, `0044_rag_index_write_fences.py`,
`ingestion/locking.py`, activation/parity target query, `indexing/resource_inventory.py`, 관련 단위/통합 tests.
Interface: 내부 `block_index_writes(sessions, workspace_id, document_id, generation)`와 읽기 종료 결과.

- [x] RED: stale generation 거부·block 반복 멱등·source 입장 거부·다른 문서 target 보존·open 작업의 not drained.
- [x] GREEN: Document→정렬 profile 잠금, fence RESTRICT, lifecycle/fence 공통 gate와 inventory snapshot.
- [x] 전용 PG/ES로 통합 검증, 독립 리뷰 결함 수정 및 runbook·작업보드 마감.

## 검증

backend `.venv/Scripts/python.exe -B -m pytest <각 task 테스트> -q --tb=short -p no:cacheprovider --basetemp=<작업별 경로>`.
동일 python으로 `-m mypy <변경 제품 파일>`, `-m ruff check <변경 Python 파일>`을 실행한다.
합성 DB helper와 전용 ES 외에는 연결하지 않으며 실행 결과는 별도 작업 기록에 남긴다.
