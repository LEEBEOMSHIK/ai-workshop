# 학습 출발점과 결과 요약 구현 계획

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans. 구현과 독립 검증을 분리한다.

**Goal:** 최신 학습부터 출발점·개선 목표·실제 결과·남은 문제를 표시한다.
**Architecture:** 기존 LearningSequence JSON 선택 메타데이터와 서버 정렬을 확장하고 공통 목록/상세 표시로 읽는다.
**Tech Stack:** 기존 FastAPI, Pydantic, SQLAlchemy, React, TypeScript, CSS 토큰.
**Spec:** [설계](../../worklogs/2026-11-05-learning-lineage.md).

## 작업

- [x] 백엔드 `platform/learning/{schemas,service,repository,api}.py`: 명시 메타데이터·길이/일관성 검증, `learning_latest` 전체 정렬과 커서. 먼저 구형/미평가/계획·내림차순 페이지 회귀를 추가하고 pytest·Mypy·Ruff 및 OpenAPI 생성 확인.
- [x] 프론트엔드 `features/learning/{LearningSequence,LearningEditor,LearningListPage,api}`와 관련 CSS/테스트: 출발점·목표·결과·남은 문제 표시와 편집, 미확인 처리, 최신순 기본값. 기존 내용 보존 회귀·Vitest·타입·린트 확인.
- [x] 독립 검증: 계승·성과 하드코딩 없음, 서버 정렬·커서, 미평가·계획 처리, 입력 왕복과 관련 테스트를 읽기 전용으로 검토하고 실행.
- [x] 통합: 원본 산출물 계승 확인 후 실제 세 기록 저장·재조회, 최신순과 상세, 모바일·두 테마·키보드 확인. 기존 본문 보존·문제 이력 추가.
- [x] 문서: 설계/ADR/UI 지침·WORKBOARD 마감, 실행한 검증과 한계 보고. 커밋·푸시 없음.
