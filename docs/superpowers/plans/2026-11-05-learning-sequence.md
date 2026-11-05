# 학습 실행 순서 구현 계획

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. 저장소 역할 계약에 따라 구현과 독립 검증을 분리한다.

**Goal:** 계획과 실제 학습 차수·실행일을 구분하고 수정 후에도 실행 순서를 보존한다.

**Architecture:** Platform Learning의 기존 experiment JSON에 선택 정보를 추가한다. 목록 조회가 상태·순서와 전체 정렬을 소유하며 React는 저장된 정보만 표현한다.

**Tech Stack:** 기존 FastAPI/Pydantic/SQLAlchemy, Next.js/React/TypeScript/CSS 토큰.

**Spec:** [설계·수용 기준](../../worklogs/2026-11-05-learning-sequence.md), [ADR 0016](../../decisions/0016-private-learning-records.md).

## 공통 제약

- 모델·가중치·실제 학습·검색·권한 범위는 바꾸지 않는다.
- 기존 본문·참조·다른 작업의 미커밋 변경을 보존한다. 커밋·푸시는 요청 범위 밖이다.
- 실제 기록 ID·제목·모델명을 제품 코드나 테스트에 고정하지 않는다.

## 작업

- [x] 백엔드: `platform/learning/{schemas,repository,service}`와 API route에 선택 `learning_sequence`, 상태 요약, 정렬별 커서를 추가한다. 먼저 계획/미입력/소유권/여러 페이지/잘못된 커서 회귀를 작성해 실패를 확인한 뒤 구현한다. 관련 pytest·Ruff·Mypy와 OpenAPI 갱신을 확인한다.
- [x] 프론트엔드: learning 목록·편집·읽기와 CSS에서 상태·차수·날짜·흐름 이름을 재사용한다. 먼저 정렬 요청·필터 리셋·상태·입력 보존 회귀를 작성한다. 기존 기록의 정보 부재를 허위 차수로 대체하지 않는다. 관련 Vitest·TypeScript·대상 ESLint를 확인한다.
- [x] 독립 리뷰: 잘못된 계획 번호, 다른 흐름/같은 차수, 필터/페이지 전환, 미입력 과거 기록, 한국어 긴 제목·좁은 화면을 검토한다. 명시 데이터와 자동 추론의 경계를 확인한다.
- [x] 본래 환경: 코드 반영 후 기존 로그인 UI에서 기존 실행 3개와 계획 1개의 흐름을 입력한다. 저장·재조회, 학습순/수정순 전환, 상세·모바일·테마·키보드 동작을 확인하고 이슈 이력을 추가한다.
- [x] 완료: 실행 증거·한계를 작업 기록과 WORKBOARD에 남기고 사용자에게 실제 화면 링크를 전달한다.
