# RAG 숫자·날짜 근거 검증 수정 계획

계약: [ADR-0035](../../decisions/0035-rag-exact-value-canonicalization.md).
위험 중간. 루트는 RAG·요구·백엔드·테스트·문서 구현, 별도 담당은 독립 코드 리뷰와
본래 평가 검증을 맡는다. UI·DB 구조·모델·배포 설정 변경과 새 환경 생성은 제외한다.

- [x] 기존 문자열 비교의 동일 값 거절/다른 값 통과를 합성 테스트로 재현한다.
  변경 전 14 실패/12 통과; 날짜, 공백, 쉼표, 부호, 퍼센트포인트, 전체 숫자 사례.
- [x] 비교용 토큰 정규화를 구현하고 원문·권한·실패 계약을 보존한다.
- [x] 생성·검색·평가 회귀 158통과, 독립 173통과, Ruff/Mypy 및 독립 리뷰를 확인한다.
- [x] 기존75건(성공70/실패5)을 보존하고 수정 런타임의 본래 API/실모델 새 재시도5건 통과를 구분한다.
- [x] DB ISSUE-00021/23 verified·새 문서v1의4문제 추가 연결·WORKBOARD에 실제 검증과 미완료를 기록한다.

검증 명령은 backend cwd의 `.venv/Scripts/python.exe -m pytest`와
`.venv/Scripts/python.exe -m ruff check`, `.venv/Scripts/python.exe -m mypy`를 사용한다.
오프라인 단위 테스트에는 합성 SECRET_KEY만 설정한다. 원본 DB에서 글로벌 stale
복구나 평가를 중단시키는 테스트를 실행하지 않는다. commit/push는 이번 범위에 없다.
