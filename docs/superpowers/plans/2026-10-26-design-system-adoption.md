# 디자인 시스템 체계화·적용 실행 계획

> **For agentic workers:** 기존 체크아웃의 변경을 보존하며 담당 범위별 구현과 독립 검증을 분리한다.

**Goal:** 미적용 업무 화면을 공통 디자인 규칙에 연결하고 사용성·시각 품질을 검증한다.

**Architecture:** 기존 CSS Modules/React, 의미별 토큰, 최소 공용 UI와 기능 소유 레이아웃을 사용한다.

**Tech Stack:** Next.js/React/TypeScript/CSS, 설치된 Vitest·브라우저 검증 도구.

**Spec:** [디자인과 수용 계약](../specs/2026-10-26-design-system-adoption-design.md).

## 범위와 검토 초점

기존 누적 파일을 보존하며 설치·본래 서비스 재시작·모델/업무 API 쓰기·commit/push는 수행하지 않는다. 저장소 지침에 따른 관리자 문제 이력 기록은 예외로 저장한다.
작업용 증거는 `.local-data/project-agent-work/design-system-20261026/`에 둔다.
320px 긴 한글, checkbox/radio, 조작 영역·focus, disabled/폼 제출, 대화 이탈·복귀를 우선 검증한다.

## 작업

- [x] route/CSS 적용 매트릭스와 변경 전 파일·시각·접근성 기준선을 기록한다.
- [x] `shared/ui/tokens.css`, `app/styles.css`, `navigation/ApplicationShell.module.css`의 표면·타이포·컨트롤 계약을 정리한다(메인).
- [x] shared Button과 실제 사용 화면을 구현하고 native 속성·폼 type·disabled·ref/aria 검증을 수행한다(공용 UI 담당).
- [x] RAG의 기능 CSS를 공통 의미 토큰에 연결하고 radio 유형·컨트롤·상태·줄바꿈을 보완한다(RAG 표현 담당).
- [x] 작업공간/파일함/학습/권한/문제이력/로그인/Publishing/흐름도 CSS를 연결하고 목적별 예외를 기록한다(비RAG 표현 담당).
- [x] 독립 관련 Vitest, 전체 TypeScript, 변경 ESLint, 실제 CSS의320/375/1280px·키보드·상태·대비를 검사한다.
- [x] 본래 화면 적용을 읽기 전용 확인하고 스타일 정본·적용 목록·문제 기록·WORKBOARD를 마감한다.

## 검증 명령

- `node node_modules/vitest/vitest.mjs run <관련 테스트 파일> --maxWorkers=2`
- `node node_modules/typescript/bin/tsc --noEmit --pretty false`
- `node node_modules/eslint/bin/eslint.js <변경 TS/TSX> --max-warnings 0`
- 합성 스타일 하네스: 기존 `frontend/tests/ui-style/` 패턴으로 실제 컴포넌트/CSS를 렌더링하며 API를 모두 차단한다.
- 브라우저 UI 조작은 사용 가능한 CUA 경로로 수행하고, 필요하면 하네스만 화면 제공 역할로 사용한다.

## 역할과 상태

요구·아키텍처·문서/통합은 메인, 화면 구현은 범위별 담당, 최종 검증·리뷰는 독립 담당이다.
백엔드/DB/AI/배포/권한 정책 역할은 해당 동작 변경이 없어 제외했다. 범위가 바뀌면 재분류한다.

## 완료 기록

적용·실제 검증·제한은 [작업 기록](../../worklogs/2026-10-26-design-system-adoption.md)을 따른다. ISSUE-00040을 본래 관리자 화면에서 저장·재조회했다.
