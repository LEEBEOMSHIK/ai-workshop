# 저장된 모델 비교 연결 구현 계획

정본: [설계](../specs/2026-10-29-stored-model-comparisons-design.md), [ADR-0051](../../decisions/0051-stored-model-comparisons.md).

## 실행 경계

기존 checkout의2237파일 SHA를 `.local-data/project-agent-work/comparison-site-20261029/before-files.json`에 보존했다. 선행 작업이 미커밋이고 본래 서비스가 해당 코드에 의존하므로 현재 디렉터리에서 범위를 분리해 작업한다. 새 DB/계정/설치/추론/기본값 승격/commit/push/정리는 하지 않는다. 작업 중 서로 소유한 파일을 편집하지 않는다.

1. **설계/계약(root)**: 별도 저장·현재 source ACL·typed import/detail/summary·두 화면 진입을 고정한다. backend가 스키마를 먼저 만들고 frontend/reviewer에게 공유한다.
2. **Backend**: 새 comparisons 모듈과0067 migration·main/env 등록. 테스트를 먼저 작성해 필드 검증·멱등/충돌·현재 ACL·변조 거절 실패를 확인하고 구현한다. 기존 evaluation/executions/생성 코어는 보존한다. 본래 opt-in rollback 통합 시험을 준비한다.
3. **Frontend**: 새 comparison client/타입·목록/가져오기·공유 상세·CSS/테스트, 두 진입 컴포넌트·route helper·admin route. 로딩/빈/오류·null/Decimal표시·실답변/인용·선택/복귀를 검증한다. 기존 디자인 시스템을 사용한다.
4. **독립 검증**: 보안·변조·의미판정/비용표시 경계와 기존 흐름 회귀를 구현 책임과 분리해 검증한다. 새 테스트는 별도 review 디렉터리에 둔다. 문제가 있으면 구현 담당에게 되돌린다.
5. **통합(root)**: 승인 Conda pytest·Ruff·mypy, frontend Vitest/TypeScript/ESLint·OpenAPI 생성/일치. 본래 DB 사전 fingerprint/백업 후 additive migration, 원래 API 복구/반영·health/ready, 기존 자료 보존 검증.
6. **연결/실제 수용(root)**: 동결4회 자료의 허용 필드 import 파일 생성·독립 대조, 본래 관리자 업로드, 목록/상세/새로고침/원문·320/375px/키보드 확인. WORKBOARD·worklog·기존 ISSUE38에 실제 완료/한계를 기록한다.

## 검증 명령 원칙

Python은 `scripts/run_backend_conda.ps1`/승인된 Conda runtime 정본을 따른다. 단위 검사는 외부 네트워크와 모델0이며 고유 basetemp·cacheprovider off를 사용한다. `pnpm --dir frontend test --run <changed-scope>`, `typecheck`, 변경파일 ESLint, `api:generate`/`api:check`를 적용한다. 실제 DB 시험은 기존 opt-in rollback 패턴으로 합성행을 남기지 않는다. migration은 DB head를 먼저 확인하고 정확한0066→0067만 적용한다.
