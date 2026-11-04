# 벡터 저장소 비교 준비 실행 계획

정본: [명세](../specs/2026-11-01-vector-store-comparison-design.md), [ADR](../../decisions/0055-vector-store-comparison-preparation.md).

## 배정과 경계

- 메인: 계약·실행 계획/CLI·통합·문서·WORKBOARD.
- 요청 구현 담당: 세 엔진 요청 생성과 해당 단위 검사만.
- 분석 구현 담당: 수입 결과 검증·검색/속도/자원 요약과 해당 단위 검사만.
- 독립 검토 담당: 보안·공정 비교 계약·통합 검증. 구현 책임과 분리.
- UI·모델 생성·학습·실제 인프라 변경은 제외한다.

현재 checkout을 재사용한다. 추가 환경·worktree·DB를 만들지 않는다. 기존 사용자 변경과 `.local-data` 조사 증거를 보존한다. 온라인 도구/제품 handler 대신 평가 모듈의 오프라인 CLI로 범위를 제한한다.

## 순서와 검증

1. 완료: 본래 DB/ES/호스트 메타데이터 읽기 전용 조사와 공식 후보 문서 조사. 현재 자료/설정 보존 해시 확인.
2. 완료: immutable 계약·계획 생성·CLI 작성. 벡터·scope 오류, plan 입력 변경, 파일 덮어쓰기 방지, synthetic 왕복 검사.
3. 완료: ES/pgvector/Qdrant exact 요청 생성과 injection/필터/빈 범위 검증. 결과 분석과 tie/실패/누락/자원 null/품질 지표 검증.
4. 완료: 신규91+기존18 회귀109, strict Mypy7소스/Ruff11파일, synthetic CLI prepare→score 실행, 독립91통과와 검토 수정.
5. 완료: 실행 방법·실제 준비 미완료 조건·검증 결과를 [worklog](../../worklogs/2026-11-01-vector-store-comparison-preparation.md)와 WORKBOARD에 기록. 최근 완료5개. 장시간 색인 검증 보류 유지.

이번 검증은 외부 모델/네트워크 없이 수행한다. 제품 서비스 재시작·실제 후보 benchmark·설치·운영 기본값 변경·자동 재시도는 없다. 실제 세 엔진의 쿼리 실행/권한/자원 검증은 후속 단계다.
