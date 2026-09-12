# RAG 합성 테스트 격리 보완

- 상태: 2026-09-10 구현·독립 검토·오프라인23건/격리 PostgreSQL13건 검증 완료. 기존 데이터 정리는 미실행.
- 승인 근거: [합성 계정 조사](2026-09-09-synthetic-account-audit.md) 후 사용자가 재발 방지 구현을 승인했다.
- 범위: Supersession reconciliation, production embedding indexing, alias parity recovery 통합 테스트3파일.
- 역할: Python/DB/테스트 설계 구현과 보안/독립 리뷰를 분리한다. main에서 작업하며 기존 변경을 보존한다.

## 성공 기준

- 해당 테스트는 테스트 함수마다 고유 disposable DB와 임시 object root, 고유 ES namespace만 사용한다.
  실패 잔여가 다음 테스트의 집계 결과에 영향을 주지 않도록 모듈 공유를 피한다.
- 일반 개발 DB는 테스트 seed 대상으로 연결하지 않는다. provisioning은 검증된 loopback
  PostgreSQL 관리 연결에서 정확히 소유한 고유 DB만 생성/해제한다.
- autouse legacy profile seed보다 격리가 먼저 적용되고 get_settings cache도 복원된다.
- 이를 위해 기존 ingestion/conftest.py의 선행 fixture 의존성을 대상3모듈에 한해 보완한다.
- fixture 생성 직후부터 실패를 보호하며 ES 정리 실패가 다른 자원 정리를 건너뛰지 않게 한다.
- cleanup 오류는 숨기지 않는다. 강제 종료로 남은 자원은 자동 광역 삭제하지 않는다.
- 연결 전 거절, fixture 순서, 실패 cleanup과 설정 복원은 네트워크 없는 테스트로 검증한다.
- 실제 SQL 검증은 검토된 harness의 고유 DB 수명주기만 대상으로 한다.

## 제외 및 현재 제약

- 기존 합성 계정5명과 관련121행, 사용자 원본·설정·프로파일·백업은 변경하지 않는다.
- 실제 복구 목록/dry-run은 격리 보완 검증 뒤 별도 준비하며 삭제는 최종 목록 승인 후 수행한다.
- 현재 실행 중인 PostgreSQL 외에 ES·Redis·모델 런타임을 자동 시작하거나 다운로드하지 않는다.
- 세 파일 검증은 전체 integration 테스트 격리 보증이 아니다. 다른 직접 앱DB 사용 테스트는 별도다.
- 실제 서비스 서버 재시작, 마이그레이션, 권한 부여, 패키지 설치, 커밋/push는 하지 않는다.

## 검증

### 구현 결과

- 공통 test-only `backend/tests/integration/rag_isolation_support.py`와
  `backend/tests/unit/test_rag_test_isolation.py`를 추가하고 대상3파일·ingestion/conftest.py를 연결했다.
- PostgreSQL provisioning은 local/test·loopback·정확한 UUID DB만 허용한다.
  URL query와 libpq 우회 환경 변수를 거절하며 runtime SQLAlchemy 연결도 활성 임시 DB로 제한한다.
- sync fixture barrier → 격리 DB migration → async legacy seed 순서를 명시했다.
- ES는 loopback·고유 namespace 아래만 허용하고, 목록의 소유권을 먼저 검증한 뒤 정확한 이름별로 삭제한다.
  ES 사용이 없는 테스트는 teardown에서도 ES에 연결하지 않는다.
- 전용 DB/객체/환경 복원은 개별 실패에도 계속 시도한다. 원래 실패와 cleanup 실패를 보존한다.
  reparse point가 있는 경로의 제거는 차단한다. 강제 종료 잔여를 광역 탐색·삭제하지 않는다.
- 실행서의 잘못된 기본 pytest 안내를 수정하고 빠른 검사를 `pytest tests/unit -q`로 한정했다.

### 실행 증거

- 단계별 TDD RED/GREEN을 수행했다. 독립 리뷰의 순서/원복 검증 누락을 보완하며
  환경 undo와 sync barrier 제거 mutation에서 두 회귀가 실패함을 확인한 뒤 원복했다.
- 메인 최종 offline: `pytest tests/unit/test_rag_test_isolation.py -q --tb=short`
  → **23 passed in 4.17s**. 독립 최종 재실행23건/4.39초 및 최종 승인.
- Ruff 변경6파일 통과. `MYPYPATH=src;.`와 `mypy --explicit-package-bases`로
  helper/새 unit/conftest3파일 통과.
- 실제 PostgreSQL: root에서 `backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml
  backend/tests/integration/labs/rag/ingestion/test_supersession_reconciliation.py -q --tb=short
  --basetemp=.local-data/project-agent-work/rag-test-isolation/pg-verification-20260910`
  → **13 passed in 24.75s**. 이 basetemp는 이번에 신규 생성한 경로이며 재실행 시 새 이름을 사용한다.
- 실사용 DB는 읽기 전용 집계만 수행했다. 전후65테이블/358행 및 전체 행 집계 SHA-256이 동일하다:
  `cffda1ce4da9e05d30d3737f93c795e5eae7df7cc41268f2fe41fa11b790beb0`.
- 전용 DB prefix의 잔존 수는 전후0, 이번 PG 검증 object 디렉터리 잔존0.
  테스트 자체 수명주기에서 생성한 자원만 회수했으며 기존 합성 데이터·캐시·백업은 삭제하지 않았다.

### 남은 범위

- 대상3모듈33개 수집 확인 중 실제 실행은 PG-only13개다. ES/모델이 필요한 나머지20개는
  실행하지 않았으므로 검색/임베딩 통합 완료를 주장하지 않는다.
- 다른 integration 모듈 전체 격리는 미검증이다. 전체 suite를 실사용 `.env`로 실행하지 않는다.
- 기존 계정5개와 연결 데이터 복구는 별도 dry-run·소유 참조 확인·최종 목록 승인 후 진행한다.
  실행 중인 앱과 사용자의 로그인 세션, 실제 DB 내용은 바꾸지 않았다.
