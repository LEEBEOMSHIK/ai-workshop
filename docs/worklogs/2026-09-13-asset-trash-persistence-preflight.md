# 휴지통 영속 기반 사전 검사

- 상태: Task1 오프라인 안전 검사 구현·독립 검토 완료. SQL 권한과 영속 모델은 미구현.
- 계획: [2A 사전 검사](../superpowers/plans/2026-09-13-asset-trash-persistence-preflight.md)
- 정본: [휴지통·복원·영구 삭제](../superpowers/specs/2026-09-13-asset-trash-purge-design.md)

## 조사와 결정

- DBA와 보안·프라이버시 담당이 소스만 조사했다. 실사용 DB·서버·자료는 변경하지 않았다.
- 일반 Job은 원본 버전에 CASCADE로 연결되므로 영구 삭제의 최종 증명을 저장하는 용도로 재사용하지 않는다.
- 기존 폴더 고유 제약은 NULL root 중복을 막지 못한다. 향후 migration 전에 기존 이름 정책과 중복을 확인하며 자동 병합하지 않는다.
- 기존 격리 DB helper는 이름과 current_database 검증은 있지만 원격 접속 설정의 차단이 없다. SQL 검증 전에 이 경계를 보강한다.
- 권한 등가식 검토에서 비회사 공간 전체에 delete를 허용하는 제안은 배제했다. 현행 OWNER 또는 개인 생성자 또는 회사 can_delete만 유지한다.
- RESTORE는 이미 승인된 read+write+delete이며 새로운 권한 선택을 요구하지 않는다.

## 문서 정정

작업 시작 안내에서 과거 RAG 활성화를 잘못 언급했으나 코드·설정을 변경하기 전에 최신 휴지통 작업으로 정정했다.
계획서 초안에 섞인 일본어와 잘못된 띄어쓰기를 한국어로 수정했다. 해당 계획의 일본어 문자 검색 결과는 0건이다.
WORKBOARD 상단 현재 단계도 실제 진행 중인 휴지통 기반 작업으로 수정했다.

## 실행 범위

- 변경: tests/integration/publishing_support.py와 tests/unit/test_publishing_database_safety.py.
- 기존 Python 환경만 사용하며 새 패키지·가상환경·Docker 서비스를 만들지 않는다.
- 실제 DB 생성·삭제, 원본/색인 삭제, 서비스 재시작, 원격 push는 실행하지 않는다.
- PostgreSQL 통합 검증은 별도이며 오프라인 단위 테스트로 실행된 것으로 대체하지 않는다.

## 검증

- 구현: trash_db_guard_impl. 독립 보안·명세·품질 검토: trash_db_guard_review.
- 최초 함수 존재 여부에 대한 RED는 유효한 행동 검증이 아니므로 철회했다. 직접 import와 무동작 validator로 실제 잘못된 대상 거부 실패를 확인했다: 15 failed, 8 passed.
- 최소 구현 후 23건 통과. 독립 검토가 지적한 복수 호스트와 CREATE 실패/DROP 경계 테스트를 추가해 26건 통과했다. 추가 테스트는 기존 구현에서 즉시 통과했으며 새 RED를 주장하지 않는다.
- 메인 최종 명령(backend): `.venv/Scripts/python.exe -B -m pytest tests/unit/platform/assets tests/unit/test_publishing_database_safety.py -q -p no:cacheprovider`.
- 결과: 225 passed, 1 warning in 8.18s, exit0. 경고는 기존 Starlette/httpx deprecation이며 새 실패가 아니다.
- `.venv/Scripts/python.exe -B -m ruff check --no-cache tests/integration/publishing_support.py tests/unit/test_publishing_database_safety.py`: 통과.
- 프로세스 MYPYPATH=src로 `.venv/Scripts/python.exe -B -m mypy tests/integration/publishing_support.py`: 1파일 통과.
- 독립 재검토: 누락된 2개 검증 사항 해소, 새 지적 없음, 승인.
- 로컬 main 커밋: d6e8bdd. 원격 push 없음.
- 일본어 문자 검사: 해당 계획서 0건. WORKBOARD의 현재 단계와 다음 작업을 수정했다.

## 다음 작업

계획 Task2의 현재 SQL 삭제 권한과 Task3의 잠금 후 휴지통 권한 재검사가 남았다.
격리 PostgreSQL 검증은 접속 대상·생성/정리 경계 확인 후 수행하며 이번 오프라인 검증으로 대체하지 않는다.
아직 lifecycle migration, 실제 삭제 명령, 자동 정리나 휴지통 UI를 구현한 것은 아니다.
# 후속 완료 연결

2026-09-14 Task2–3 현재 SQL/행위별 권한 연결과 통합 265건 및 최종 독립 리뷰를 완료했다. 상세 결과와 다음 경계는 [서버 권한 작업 기록](2026-09-14-asset-trash-authorization.md)을 따른다.
