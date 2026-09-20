# Jobs Metadata Ownership Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development and TDD. Main integrates and commits; independent reviewer writes no implementation.

**Goal:** Track Jobs metadata revisions and source retention while preparing a usable isolated RAG test environment.
**Architecture:** Transactional Jobs repository owns source pins/current relations. Dispatch delegates writes; inventory reads fresh snapshots without enabling deletion.
**Tech Stack:** Python/SQLAlchemy/PostgreSQL, FastAPI/Celery, Windows native stores, Elasticsearch and cached E5.
**Spec:** [Jobs metadata ownership](../specs/2026-09-20-job-metadata-ownership-design.md).

## Constraints

- User authorized next development and RAG preparation; retain current checkout exception and unrelated references.
- Existing DB/.env/files/services remain unchanged; new RAG sandbox has separate roots/ports/DB.
- No model download/external inference; use cached pinned model offline. No purge or legacy adoption.
- Existing ingestion/job/source lock order remains; no independent commit inside repository.

## Task1 — DBA: source retention and revision repository

Files: jobs/domain.py, models.py, repository.py; new ownership.py; migration0048; guarded unit/PG tests.
- [x] Write failing add/revision/legacy/stale/identity tests.
- [x] Add nullable revision and RESTRICT source owner. Move existing composite unique to Jobs model.
- [x] Atomically register/replace provenance; update input domain revision after flush.
- [x] Verify migration, rollback, repeated/stale/concurrent updates and RESTRICT in isolated DB.

## Task2 — main: dispatch and metadata inventory

Files: assets/dispatch.py; new jobs/inventory.py; focused unit and guarded PG integration tests.
- [x] Write failing dispatch revision and inventory mismatch tests.
- [x] Delegate successful dispatch mutations to Jobs repository; failed CAS changes nothing.
- [x] Include allversions and fresh snapshots, preserve legacy and writer-unconfirmed blockers.
- [x] Run existing Jobs/assets/RAG regression and independent review.

## Task3 — RAG/infra: runnable isolated sandbox

Files: new preparation script(s), targeted tests, docs/runbooks/rag-sandbox.md; ignored .local-data/rag-sandbox only.
- [x] Confirm existing images/model cache and exact free loopback ports before creating resources.
- [x] Create isolated PG/Redis/ES, dedicated marker/binding roots and ignored random credentials.
- [x] Apply current head to synthetic DB and start Windows API/worker/beat plus frontend without changing existing services.
- [x] Prepare synthetic owner/configuration/TXT and validate upload→BM25→cached E5 search if runtime permits.
- [x] Record exact ready/blocked boundaries, process/container IDs and user entry instructions; keep sandbox available.

## Task3b — RAG 실행 중 발견한 계약 누락 수정

- [x] ingestion fixture에 artifact admission/publisher를 연결하고 확정 전후 실패를 구분한다.
- [x] 저장 구성의 의미상 처리 프로파일을 물리 alias와 분리하여 선택 문서 검색에 전달한다.
- [x] legacy/frozen 대상 회귀와 실제 선택 문서 BM25/hybrid 검색을 검증한다.

## Task4 — independent verification and handoff

- [x] Independent code/security/DB review; relevant unit/integration, mypy, Ruff and docs checks.
- [x] Record actual RAG readiness, any legacy fixture failures, and remaining generation/OCR requirements.
- [x] Update WORKBOARD recent5 and task worklog; select only task files for handoff.

Final handoff: commit/push the verified task files and confirm remote parity; report the resulting hash in the user handoff.

Tests: backend venv python -m pytest <relatedpaths> -q --basetemp=.local-data/pytest-tmp/jobs-<unique>.
Static checks: backend venv python -m mypy <changedsources>; python -m ruff check <changedPython>.
PG tests require explicit test environment/loopback URL and per-test UUID DB; never load developer .env as target.
