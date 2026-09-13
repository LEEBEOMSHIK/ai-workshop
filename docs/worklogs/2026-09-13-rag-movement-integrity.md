# RAG 이동 후 검색 정합성

- 상태: 구현·자동 검증·독립 소스 인계 검토 완료
- 승인 설계: [파일함 이동 계약](../superpowers/specs/2026-09-13-explorer-movement-design.md)
- 실행 계획: [RAG 이동 정합성](../superpowers/plans/2026-09-13-rag-movement-integrity.md)

## 문제와 변경 경계

문서 이동은 DB의 현재 폴더를 변경하지만 기존 검색 색인의 폴더 정보는 바꾸지 않는다.
그 정보를 실시간 검색 제한에 사용하면 새 폴더에서 문서가 누락되거나 준비 중인 검색에 이전 위치가 남는다.
현재 DB가 허용한 정확한 document/asset/projection/build 조합으로 두 검색 경로를 제한한다.
과거 평가의 물리 색인·폴더 snapshot은 보존한다.

생성 직전에 준비된 모든 반환 근거를 새 권한 목록과 비교한다. 관련 자료도 검사 대상이며,
필요한 근거가 범위를 벗어나면 안전한 범위 변경 오류로 중단한다. 위치만 바뀐 제한 없는 명시적 문서
선택은 유지한다. 이는 시점 검증이며 모델 네트워크 호출 동안의 원자적 잠금은 아니다.

## 검증 기록

- 구현자 RED: 필수 회귀에서 5 실패 / 87 통과. 누락된 정확 권한 전달, 독립 ID 집합 허용,
  변경된 준비 근거의 생성 호출을 실패 사례로 확인했다.
- 독립 사전 검토: 실시간/과거 평가 경계, 명시적 선택 의미, 현재 위치 조회와 외부 전송 전 검사를 확인했다.
- 메인 최종 단위 검사: retrieval/search/evaluation 및 workspace 권한 경계 **242 통과**(18.40초).
  기존 Starlette/httpx deprecation 경고 1건이며 새 의존성을 설치하지 않았다.
- 메인 격리 통합 검사: 문서/폴더 이동과 검색 범위 repository **5 통과**(14.89초).
  실제 PostgreSQL·Elasticsearch를 사용하고 임베딩은 합성 고정 벡터다. 실제 모델 호출은 아니다.
- 메인 mypy: 변경된 운영 코드 7파일 통과. 관련 운영 코드·테스트 Ruff 통과.
- 이동 전후 원본 바이트·해시·버전·파싱/색인 행, 기존 뷰어 권한 접근을 확인했다.
  ES 원문 폴더와 내부 버전은 그대로인데 실시간 검색·DB 표시만 새 위치를 사용한다.
  과거 물리 색인 검색은 이전 snapshot 의미를 유지한다.
- 생성 전 변경·잘못 조합된 근거·관련 문서 이탈은 생성 미호출로 검증했다.
  명시적 문서 위치만 변경되거나 무관한 자료가 이탈하는 최종 경계도 별도로 검사했다.
- 독립 구현 리뷰: 명세·품질 통과, 차단/경미 코드 지적 없음.
- 최종 교차 경계 리뷰: 코드 차단 없음. 정본의 진행 상태 문구 1건을 수정하고 독립 재검토까지 완료했다.
  실시간 exact-OR 쿼리는 문서 수에 비례해 커지므로 대규모 공간 성능은 별도 측정 대상이다.

명령은 기존 `backend/.venv`에서 `python -B -m pytest -p no:cacheprovider`로 실행했다.
단위 대상은 `tests/unit/labs/rag/{retrieval,search,evaluation}`과
`tests/unit/platform/workspaces/test_permission_search_boundary.py`다.
통합 대상은 `backend/tests/integration/labs/rag/retrieval/test_movement_integrity.py`와
`test_search_scope_repository.py`로 제한하고 저장소 루트에서 `-c backend/pyproject.toml`을 지정했다.
합성 테스트 키만 환경에 덮어썼으며 격리 helper가 정확한 임시 DB·ES namespace·원본 폴더를 생성·정리했다.
격리 helper를 쓰지 않는 기존 `test_hybrid_search.py`는 합성 권한 fixture만 갱신했고 실행하지 않았다.

## 적용 제한

기존 main 미커밋 변경과 실사용 자료를 보존한다. 이번 작업에는 실사용 DB migration, 서버 재시작,
실제 자료 이동, 외부 모델 호출, 커밋·푸시가 포함되지 않는다.
이동 메뉴·드래그앤드롭은 검색 정합성 검증 다음 단계다.
