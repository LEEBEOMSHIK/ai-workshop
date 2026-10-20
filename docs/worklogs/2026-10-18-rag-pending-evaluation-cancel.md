# 미시작 생성형 평가 취소

- 날짜: 2026-10-18
- 결과: 구현·mock/PG 검증·독립 리뷰와 승인된 본래 DB/API 반영 완료. 실제 대상 실행의 로그인 UI 취소·정정 재제출은 미실행이다.
- 범위: owner 소유 pending 실행만 취소한다. 실행/시도 cancelled, 취소자·시각·고정 사유 user_requested, 멱등성, run→attempt 잠금, 늦은 claim 차단을 추가했다. running은409, 취소된 실행의 재시도·승격은 거절한다. 입력·규칙·해시·이력은 유지한다.
- 정본 계약: [ADR-0030](../decisions/0030-rag-generative-evaluation.md), [RAG 설계](../labs/rag/design.md).

## 승인·역할·보존

사용자의 후속 진행 승인에 따라 기능 구현 후 기존 DB/server 반영까지 수행했다. 실제 평가 취소·재제출, 일반 worker 시작, 모델·임베딩 호출, 계정·권한·보호 설정 변경, commit/push는 하지 않았다. 기존 RAG P0 순서와 모델 호출 예산을 보존한다.

메인은 요구·설계·backend·통합·반영·기록을 맡고, DB 담당과 frontend 담당은 파일 소유 범위를 분리했다. 별도 리뷰 담당이 코드·권한·경합 계약과 mock 테스트를 독립 확인했다. 별도 모델/개인정보 역할은 모델 입력·외부 전송 계약이 바뀌지 않아 추가하지 않았다.

작업 전 1,975개 파일 SHA-256과 수정 대상 원본을 `.local-data/project-agent-work/pending-evaluation-cancel-20261018/`에 보존했다. 쓰기 전 재확인했고, 종료 비교에서 달라진 기존 파일은 이번 범위11개뿐이다. 다른 미커밋·미추적 변경은 유지했다.

## 구현 파일

- backend: evaluation의 `generative_models.py`, `generative_repository.py`, `generative_schemas.py`, `generative_read.py`, `generative_api.py`.
- DB: `backend/alembic/versions/0066_generative_pending_cancel.py`.
- frontend: `GenerativeEvaluationPanel.tsx`, `generative-api.ts`, 자동 생성 `shared/api/schema.d.ts`.
- 검증: `test_pending_cancellation.py`, `test_pending_cancellation_api.py`, `test_pending_cancel_existing_db.py`, `GenerativeEvaluationCancel.test.tsx`.
- 문서: WORKBOARD, ADR-0030, RAG 설계, 이 작업 기록.

API는 `POST /api/v1/rag/generative-evaluations/{run_id}/cancel`, 본문은 `{"reason":"user_requested"}`다. 기존 owner 인증·실행 소유권·현재 원문 접근 검사를 유지한다. UI는 pending 선택 시에만 취소를 제공하고 중복 입력을 막는다.409에는 최신 상태를 조회하며, 조회까지 실패하면 확인되지 않은 취소 완료를 표시하지 않는다.

DB는 취소 시 모든 시도가 미시작이고 실행/생성 감사가 없어야 한다. 취소 감사와 terminal 불변, 모든 자식 취소를 commit 시 확인하는 제약을 포함한다. 취소 증거가 있으면 downgrade를 거절한다.

## 실행한 검증

- 신규 repository RED: 취소 메서드 부재14실패. UI 핵심 RED4실패 후 구현. 초기 API 테스트의 잘못된 enum은 수정했으며 해당 수집 오류를 기능 RED로 세지 않는다.
- backend 평가 단위 전체: **185 passed,14.26초**. backend 디렉터리에서 `python -m pytest tests/unit/labs/rag/evaluation -p pytest_asyncio.plugin --assert=plain -q`와 새 작업 전용 basetemp로 실행했다.
- frontend configurations: **14파일134 passed,135.85초**. 취소 전용10개를 포함한다.
- PostgreSQL: **12 passed,8.62초**. 기존 DB 내 task-only schema에서 실제 repository/두 연결로 취소 우선·claim 우선 경합, 멱등성·소유권, 입력/terminal 불변, 부분 취소 commit 거절, 늦은 claim·재시도·승격 차단을 검사했다.
- 독립 담당 직접 실행: backend 취소/API **24 passed,4.73초**, UI 관련3파일 **50 passed,34.31초**. 위 전체 결과와 중복되는 검사이므로 합산하지 않는다.
- Ruff 변경 backend9파일, strict Mypy 제품5파일 및 migration1파일, frontend 전체 TypeScript, frontend 소유3파일 ESLint 통과. OpenAPI 생성 완료.
- 리뷰에서 attempt error_code와 DB 제약 불일치 및 미시작 흔적의409 검사 누락을 수정 후 재검토했다. 미해결 코드 차단은 발견되지 않았다.

최초 PG9통과/3실패는 fixture JSON 바인딩과 frozen profile 구성 문제를 고친 뒤12개 모두 재검증했다. 넓힌 단위 검사 최초180통과/1실패/4오류는 잘못된 작업 디렉터리와 기존 temp 경로 접근 문제였으며 backend/새 전용 temp로185개 통과했다. Windows sandbox의 asyncio socketpair 대기는 해당 테스트 세션만 종료하고 정상 승인 경로로 재검증했다. 보안 설정은 변경하지 않았다.

PG 시험 생성의 첫 자동 승인 검토는 위임 맥락의 승인 부족으로 거절됐으며 실행되지 않았다. 명시된 사용자 승인 범위를 붙여 정상 재요청한 뒤 수행했다. 남은 승인 차단은 없다. 시험 schema `cancel_test_5583e86baaf4487d9800bdf94c057af6`는 보존했으며 새 DB·계정은 만들지 않았다.

## 본래 환경 반영과 확인

- 본래 revision0065, 진행 중 평가/실행0을 확인했다. 기존 public123개 테이블의 원래 열 전체를 행 해시로 비교했다(alembic_version 제외).
- private pg_dump custom archive **29,085,849bytes**, SHA-256 `af12c5dda405f55c06d098d4f1ca03392ced652897a865c25c4986a205280063`. pg_restore 목록 확인 완료. **실제 백업 복원 시험은 수행하지 않았다.** 백업과 기준값은 위 ignored 작업 디렉터리에 있다.
- 본래 DB 트랜잭션에서0066 upgrade→downgrade 및 원래 데이터 해시 일치를 확인하고 전체 롤백했다.
- 정확한 **0065_local_transformers→0066_generative_pending_cancel**만 적용했다. 확인한 기존 API PID89576만 종료하고 같은 Conda/루트/127.0.0.1:18000에서 PID91712로 숨김 기동했다. frontend5173 기존 dev server를 유지했다. worker/beat·Docker·ES 실행 상태는 변경하지 않았다.
- 반영 후123테이블 원래 열 해시 전부 일치. API startup complete, health200/ok, ready200/ready, OpenAPI 취소 경로, 로그인 없는 가상 UUID 취소401, frontend 루트200 확인.
- 이 확인은 **로그인한 실제 UI E2E와 구분**한다. private 백업 복원·전체 RAG/실모델 검증은 수행하지 않았다.
- migration/새 시작 실패 시 강제 downgrade·stamp·보호 우회는 하지 않는 절차다. 취소 증거가 생긴 뒤에는 downgrade할 수 없고 별도 검토가 필요하다.

## 사용자 인계와 다음 후보

대상 `b91990da-ef3e-4ce3-b8f7-e94db6ff5f21`은 반영 후에도 pending,4시도 모두pending, claim/dispatched/finished 없음, execution/audit0이다. 잘못된 frozen 규칙과 이력을 직접 고치거나 취소하지 않았다. 이 작업의 모델/임베딩 호출은0이며 아직4시도가 대기 중이므로 예산 소진/회수를 단정하지 않는다.

기존 로그인 상태로 [비교 실험](http://127.0.0.1:5173/admin/rag/configurations) → **답변 품질 비교** → 실행 이력에서 **Gemma E2B 범용 v4 비교 2026-10-17 v1** 대상 실행을 선택 → **결과 새로고침** 옆 **시작 전 평가 취소**를 누른다. 취소 상태와 감사 정보를 확인한 뒤 승인된 규칙 `["4","영업일"]`로 새 평가를 제출하는 것이 다음 후보다. 기존 `["1018"]` 실행 이력은 보존한다. 모델 평가는 해당 승인 예산과 실행 전 점검을 다시 확인한 뒤 진행한다.

문제 이력 DB는 정상 로그인 세션 부재로 이번 결함/수정 기록을 갱신하지 못했다. 로그인 UI 취소·정정 제출과 함께 후속 갱신이 남는다. 학습 진도·교재·사용량 알림 예약은 변경하지 않았다.
