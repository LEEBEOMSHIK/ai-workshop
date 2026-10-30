# 고정 평가 임베딩 계산 재사용 구현 계획

**목표:** 현재 답변 품질·선택 결과와 생성 전 모델 해제를 유지하면서 같은 평가 반복의 준비·계산을 줄인다.
**설계:** [ADR-0045](../../decisions/0045-frozen-evaluation-embedding-reuse.md). 기존242개 작업 파일과 본래 환경을 보존하고 새 실제 모델 호출 없이 구현한다.

## 1. 계산 저장소 — AI 구현 담당

소유 파일: 새 evaluation/embedding_reuse.py, 새 unit evaluation/test_embedding_reuse.py.

- [x] RED: exact 네 연산·batch 순서·반환 복사·불량 출력·상한·닫힘·miss 실패·delegate lazy/close를 검증한다.
- [x] `FrozenEmbeddingResults(max_bytes=...)`에 bound(namespace: str, factory: Callable[[], OwnedEmbeddingPort], dimension: int) → OwnedEmbeddingPort와 close()를 구현한다. bound는 새 실행 wrapper이며 namespace/정확한 메서드 입력별 완료값만 공유한다.
- [x] 캐시는 complete normalized float tuple과 scalar int만 보관한다. 상한 초과는 admission 생략이며 전체 원래 호출을 그대로 유지한다.
- [x] hit만 `embedding.result_reuse`로 계측하고 실제 모델·DB 없이 전용 테스트·Ruff·범위 타입을 검증한다.

## 2. 평가 연결 — 백엔드 구현 담당

소유 파일: generative_adapter.py, generative_workflow.py와 새 unit evaluation/test_frozen_embedding_reuse_wiring.py.

- [x] RED: 동일 반복의 lazy factory/encode 생략, namespace 격리, borrowed/CPU 경계, 기본 비활성·finally 정리를 검증한다.
- [x] adapter에 선택적 embedding_results를 받아 정확한 namespace와 기존 frozen owned factory로 실행용 wrapper를 만든다. 기존 권한/검색 경로를 건너뛰지 않는다.
- [x] workflow의 기존 `_execute_claimed` 호출 계약을 유지하며 claim-local 생성/정리를 감싼다. enabled일 때만 adapter에 주입해 기존 fake/기본 경로를 보존한다.
- [x] worker_runtime에 scope/version/max_bytes/enabled를 기록한다. 실행당 모델/도구 예산·종료·재시도 정책은 변경하지 않는다.

## 3. 설정·관측·통합 — 메인

소유: config.py, executions/domain.py, 해당 새 설정/관측 테스트, 생성 OpenAPI/프론트 타입과 문서.

- [x] 실패 테스트 뒤 기본0/엄격정수/최대64MiB 설정과 새 고정 operation 이름1개를 추가한다.
- [x] 최종 관련 단위·범위 strict Mypy/Ruff·OpenAPI/TypeScript를 확인한다.
- [x] WORKBOARD/문제 이력에 구현과 실제 품질·성능 수용을 구분한다. commit/push·설치·캐시 삭제·새 환경/DB/계정을 만들지 않는다.

## 4. 독립 수용

- [x] 별도 담당이 namespace·warm 권한 철회·batch 수치 동일·오류와 보관 경계·기존 결과 동일성을 검증한다.
- [x] 필요한 기존 DB 검증은 opt-in rollback만 사용하고 실제 모델 호출을 포함하지 않는다.
- [x] 구현 중 호출0회 이후 사용자 새 승인4/4회·retry0의 실제 비교를 완료했다. 두 입력/답변/인용 동일, 반복46.797→16.810초·첫210.948초/정답0/2를 구분했다. 완료 화면 및 이슈의 실제 결과 갱신은 브라우저 URL 식별 실패로 미완료이며 [보고서](../../worklogs/2026-10-26-frozen-embedding-reuse.md)에 기록한다.
