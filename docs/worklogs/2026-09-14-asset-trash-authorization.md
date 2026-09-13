# 휴지통 서버 측 권한 연결

- 상태: 2A Task1–3 구현·개별 독립 검토·최종 전체 리뷰 완료.
- 계획: [영속 기반 사전 검사 Task2–3](../superpowers/plans/2026-09-13-asset-trash-persistence-preflight.md)
- 설계: [휴지통·복원·영구 삭제](../superpowers/specs/2026-09-13-asset-trash-purge-design.md)

## 범위와 역할

기존 read/write 권한을 변경하지 않고 현재 SQL 삭제 조건과 휴지통 행위의 재검사를 연결한다.
메인은 요구·테스트 설계/통합, Python 담당은 구현, 별도 담당은 독립 보안·통합 검증을 맡는다.
조회·삭제·영구 삭제는 read+delete, 복원은 read+write+delete다. 개인 생성자 격리와 현재 사용자 활성/공간 만료를 유지한다.
TEAM/TEMPORARY MEMBER에게 기존에 없던 삭제 권한을 부여하지 않는다.

## 검증 환경 경계

- main에서 기존 backend 가상환경을 사용한다. 새 패키지·서버·컨테이너는 만들지 않는다.
- 설정의 비밀값을 출력하지 않고 local/127.0.0.1:15432/PostgreSQL과 대상 안전 검사 통과만 확인했다.
- 기존 hardened helper가 생성한 UUID 일회용 DB에 합성 자료만 넣어 검증한다. 기존 앱 DB의 테이블·자료는 수정하지 않는다.
- 일회용 DB는 정확한 이름과 current_database를 검사한 뒤 해당 fixture가 정리한다.
- 원본 문서·파일/색인 삭제·서비스 재시작·외부 모델·원격 push는 범위 밖이다.
- API/UI나 영구 삭제 실행기가 완성된 것으로 보고하지 않는다.

## 결과

Task2 구현: trash_sql_delete_impl. 독립 보안·명세·품질 검토: trash_sql_authorization_review.

- 최초 행동 RED: 허용해야 할 조건을 always-deny 구현으로 검사해 7 failed, 8 passed. 정상 구현 후 15 passed.
- 기존 읽기·쓰기 PostgreSQL 회귀: 6 passed. production mypy와 변경 파일 Ruff 통과.
- 독립 리뷰에서 잠금 전 statement의 현재 시각이 재사용되는 문제를 발견했다. 잠금 대기 중 임시 공간이 만료되면 과거 기준으로 승인될 수 있었다.
- 실제 PostgreSQL 행 잠금과 pg_blocking_pids로 대기를 확인하는 회귀 추가: 수정 전 1 failed(error is None), 수정 후 1 passed.
- 사전 조회·잠금 후 조회에서 predicate와 select를 각각 새로 구성하도록 수정했다. 전체 삭제 권한 16 passed, 메인 재실행도 16 passed in 9.10s.
- 독립 재검토 승인, 로컬 커밋 a78ae1f. 기존 read/write 본문은 변경하지 않았다.
- 지정 테스트 파일까지 mypy에 포함하면 import된 기존 test_asset_originals.py의 generator fixture 반환 annotation과 RaceObjectStore protocol 오류 2건이 남는다. 범위 밖 코드를 수정하거나 오류를 숨기지 않았다. production 타입 검사 통과와 구분한다.

Task3 구현: trash_action_auth_impl. 독립 검토: trash_sql_authorization_review. 지적 사항 없이 승인됐다.

- LIST는 최신 권한 조회만, TRASH/RESTORE/PURGE는 잠금 후 최신 권한 재조회까지 수행한다.
- 행동 RED 9 failed/9 passed → GREEN 18 passed. 로컬 커밋 `805baf5`.
- 메인 통합 검증: Assets 단위·DB 안전·삭제/휴지통/기존 구성원 권한을 함께 실행하여 **265 passed, 1 warning in 35.25s**(exit 0).
- 경고는 기존 Starlette/httpx TestClient 사용 중단 예고 1건이다.
- production 2파일과 DB helper를 함께 지정한 mypy 3파일 통과. 변경 6파일 Ruff 통과.
- helper만 단독 mypy 실행하면 소스 패키지 탐색 문제(import-untyped/unused-ignore)가 발생했다. production 파일과 함께 지정한 명령으로 소스 경로를 정상 해석하여 통과했으며 코드나 ignore를 추가하지 않았다.
- 합성 격리 DB만 사용하고 fixture가 정리했다. 실사용 자료·스키마·서버와 기존 UI 변경은 보존했다.
- 실제 휴지통 이동/복원/영구 삭제는 아직 사용자 테스트 대상이 아니다. 다음은 영속 모델·상태 필터·삭제 작업 연결 단계다.

후속 명령은 같은 트랜잭션에서 문서/배치 소유 범위, 상태·revision, 보관 기한과 삭제 증명을 추가 검사해야 한다. 이번 권한 helper만으로 삭제를 승인해서는 안 된다.

최종 전체 변경 검토: `trash_preflight_final_review` 승인, 수정 필요 코드 지적 없음. 실사용 자료 변경과 푸시는 하지 않았다.
