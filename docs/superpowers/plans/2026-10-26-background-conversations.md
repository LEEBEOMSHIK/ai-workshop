# Background Conversations Implementation Plan

> Use subagent-driven-development with separate implementation and independent review.

**Goal:** 질문을 보낸 사용자가 다른 작업을 하는 동안 서버가 답변을 계속 만들고, 재진입 시 결과를 확인한다.
**Architecture:** 기존 원자적 접수/실행 코어와 저장 API를 보존하며 앱 소유 실행과 화면 상태 조회를 분리한다.
**Tech Stack:** FastAPI/asyncio, PostgreSQL, React/TypeScript.
**Spec:** [ADR-0048](../../decisions/0048-background-conversations.md)

## Constraints and review focus

- 기존 변경265파일·환경·계정·자료를 보존하며 현재 checkout에서 누적 수정한다. 별도 환경/DB·설치·commit/push 없음.
- 모델 호출0, 자동 재시도0. 모델/입력/근거/인용/프로파일 기본값 불변.
- 요청 의존성 종료, 예약 후 실패, 취소와 완료 경합, 중복 접수, 권한 철회 및 늦은 화면 응답을 독립 검토한다.
- 메인: 요구·설계·프론트·문서/통합. reference_trace: 백엔드/RAG 구현·테스트 설계.
- lifetime_review: 독립 통합/권한 검증. embedding_audit: 독립 코드 리뷰.
- 스키마/모델/외부 전송/배포 변경이 없어 해당 specialist는 제외한다. 범위 확장 시 재분류한다.

## Tasks

- [x] Backend: 실패 테스트 후 `conversations/background.py`와 작업 의존성 조립을 추가한다.
  service 접수 callback, API Prefer/202, main lifecycle을 연결한다. 기존 동기 계약을 보존한다.
  offline start/submit replay, disconnect, context 종료 순서, 느린 동기 작업 중 API 응답,
  explicit cancel/shutdown과 안전한 오류 처리를 검증한다.
- [x] Frontend: `ConversationPage.tsx`, `pending-start.ts`, `sessions-api.ts`에 실패 회귀를 먼저 추가한다.
  화면 이탈 취소를 제거하고 현재 대화 자동 조회·입력 보존·명시 취소·늦은 응답 fence를 구현한다.
  이전 자동취소 기대만 새 계약에 맞추고 명시 취소와 draft 원자성 검증은 유지한다.
- [x] Independent: 기존 DB rollback과 부정 권한 검증, 관련 회귀, 타입·린트·API 계약을 확인한다.
  새 baseline의 기존25표2547행과 .env 보존을 확인한다.
- [x] Integration: 본래 API 반영과 화면 확인, 가능한 관리자 문제 DB 기록, WORKBOARD/작업 기록에
  구현 검증·실모델 미실행·서버 재시작 한계를 구분해 남긴다.
