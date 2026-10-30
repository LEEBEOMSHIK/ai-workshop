# Claude·관리 화면 Implementation Plan

> 작업별 구현과 독립 검증 책임을 분리한다. 기존 공유 checkout을 사용하며 commit/push는 하지 않는다.

**Goal:** Claude 신규 후보를 등록·검증할 수 있게 하고 두 고급 관리 화면을 작업 중심으로 정리한다.

**Architecture:** native Anthropic adapter와 기존 runtime factory/정책·수용 경계를 재사용한다. 화면의 URL과 저장 handler를 보존하며 선택한 작업만 우선 표시한다.

**Tech Stack:** FastAPI/SQLAlchemy/httpx, Next.js/React, pytest/Vitest.

**Spec:** [ADR-0053](../../decisions/0053-claude-and-admin-workflows.md)

## 공통 제약과 검토 초점

- 기존 키·환경·모델·활성 연결·정책 승인·검색 인덱스를 변경하지 않는다. 새 유료 생성 0회.
- 기존 OpenAI sampling 이슈47은 별도이며 native Claude에 그 계약을 복제하지 않는다.
- 공급자 전환 후 이전 ID/동의·기능 확인 재사용, 다른 dialect, 잘린 JSON, 정책 고지 mismatch, 작업 이동의 초안 손실을 검증한다.
- 외부 출력 예외와 thinking에서 비밀·본문을 노출하지 않는다. 완료 주장은 실제 검증 범위를 분리한다.

## 작업

- [x] backend 담당: domain/config/setup options/preset/registry/readiness와 native adapter, migration0068. provider_default+1.0 및 schema1, 별도 disclosure를 등록부터 실행까지 검증. native mock 성공/오류/취소/사용량/기존 OpenAI·local 회귀와 타입·린트.
- [x] frontend 담당: ModelAdminWorkspace/Tabs/ModelLabPage/ConfigurationStudioPage/Builder/SavedConfigurationList 및 소유 CSS·tests. 작업 선택/접기/초안 보존/기존 payload·deep link 검증. 공급자 계약은 root와 경계 분리.
- [x] root: Claude catalog·통합 설정·공급자 표시/정책/고지·고급 생성 폼 호환성·생성 OpenAPI 타입 통합, 관련 회귀·전체 TS·변경 lint.
- [x] 독립 담당: 공급자 보안/프라이버시·고지·호환성·회귀 검토 및 독립 테스트. 구현 소유 없음.
- [x] root: 기존 DB 보존 검사 후 migration·기존 API 반영, health/ready와 로그인된 desktop/mobile viewport 실제 화면·탐색·초안 보존 확인. 실기기 모바일 검증과 구분하며 운영 정책/등록/추론 자동 실행 없음.
- [x] root: 디자인 정본·실행서·worklog·문제 DB 이력·WORKBOARD 마감. 키/실제 Claude 평가가 없으면 그 경계를 명시한다.

결과: [수정·검증·운영 한계](../../worklogs/2026-10-31-claude-admin-workflows.md). Claude 키/서버 참조·실제 답변 평가·활성화는 별도이며 이번 호출0·추가 API비용0이다.
