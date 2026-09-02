# 저장소 구조

- 상태: 승인됨
- 기준일: 2026-09-03

## 목표 구조

```text
ai-workshop/
├─ frontend/
│  ├─ src/
│  │  ├─ app/
│  │  │  ├─ page.tsx
│  │  │  ├─ (public)/
│  │  │  │  ├─ labs/
│  │  │  │  │  ├─ page.tsx
│  │  │  │  │  └─ rag/page.tsx
│  │  │  │  ├─ login/page.tsx
│  │  │  │  └─ setup/page.tsx
│  │  │  ├─ (workspace)/workshop/
│  │  │  │  ├─ workspaces/
│  │  │  │  └─ rag/
│  │  │  │     ├─ search/
│  │  │  │     └─ sources/
│  │  │  └─ (administration)/admin/
│  │  │     └─ rag/
│  │  │        ├─ configurations/
│  │  │        └─ models/
│  │  ├─ features/
│  │  │  ├─ identity/
│  │  │  ├─ workspaces/
│  │  │  ├─ assets/
│  │  │  ├─ navigation/
│  │  │  └─ rag/
│  │  │     ├─ search/
│  │  │     ├─ configurations/
│  │  │     └─ models/
│  │  └─ shared/
│  ├─ next.config.ts
│  └─ tests/
│
├─ backend/
│  ├─ src/
│  │  └─ ai_workshop/
│  │     ├─ platform/
│  │     │  ├─ identity/
│  │     │  ├─ workspaces/
│  │     │  ├─ assets/
│  │     │  ├─ agents/
│  │     │  ├─ learning/
│  │     │  ├─ publishing/
│  │     │  └─ evaluation/
│  │     ├─ labs/
│  │     │  └─ rag/
│  │     │     ├─ documents/
│  │     │     ├─ ingestion/
│  │     │     ├─ parsing/
│  │     │     ├─ chunking/
│  │     │     ├─ indexing/
│  │     │     ├─ retrieval/
│  │     │     ├─ highlighting/
│  │     │     ├─ generation/
│  │     │     ├─ models/
│  │     │     ├─ experiments/
│  │     │     ├─ agents/
│  │     │     └─ evaluation/
│  │     └─ shared/
│  └─ tests/
│     ├─ unit/
│     ├─ integration/
│     ├─ contract/
│     └─ end_to_end/
│
├─ model-profiles/
│  └─ rag/
│     ├─ indexing/
│     ├─ retrieval/
│     └─ generation/
│
├─ infrastructure/
│  ├─ compose/
│  ├─ containers/
│  ├─ elasticsearch/
│  └─ observability/
│
├─ docs/
│  ├─ vision/
│  ├─ architecture/
│  ├─ decisions/
│  ├─ guidelines/
│  └─ labs/
│     └─ rag/
│        ├─ design.md
│        ├─ studies/
│        ├─ experiments/
│        └─ designs/
│
├─ sample-data/
│  └─ public/
└─ tools/
```

## 생성 원칙

이 구조는 목표 상태를 나타낸다. 구현을 시작할 때 필요한 디렉터리만 생성하며, 미래 기술의 빈 `labs` 폴더를 미리 만들지 않는다.

작은 기능에 모든 계층을 기계적으로 만들지 않는다. 모듈이 복잡해질 때 `domain`, `application`, `adapters`, `api` 같은 내부 계층을 도입하되 의존 방향은 유지한다.

## 의존 방향

```text
frontend Next app -> features -> shared UI, 인증 경계와 API client

backend API/worker -> application -> domain <- adapters
labs/rag -> platform contracts
platform -X-> labs/rag
labs/* -X-> another labs/*
```

`platform`은 `labs/rag`의 타입이나 구현을 import하지 않는다. RAG가 공통 기능을 요구하면 플랫폼 계약을 사용하거나, 여러 연구 영역에서 실제로 반복된 뒤 공통 플랫폼으로 승격한다.

프론트엔드 canonical URL은 공개 `/`·`/labs/*`, 로그인 사용자 `/workshop/*`, owner 전용
`/admin/*`로 나뉜다. 이전 `/app/*`는 `next.config.ts`의 compatibility redirect 입력으로만
유지하며 새 화면이나 기능의 정본 경로로 사용하지 않는다.

## 저장소에 포함하는 것

- 소스 코드와 테스트
- 데이터베이스와 검색 색인 스키마
- 모델 및 검색 프로파일 정의
- 공개·합성 소형 테스트 데이터
- 설계, 결정 기록, 학습 요약과 실험 결과 요약
- 재현에 필요한 스크립트와 환경변수 예제

## 저장소에 포함하지 않는 것

- 실제 자산운용사 내부 문서
- 개인 또는 임시 업로드 문서
- 생성된 검색 색인과 임베딩
- 다운로드한 모델 가중치
- 페이지 이미지와 변환된 뷰어 자산
- 비밀값, 토큰, 사용자 정보
- 대용량 원시 실험 로그

대용량 또는 민감한 산출물은 로컬 볼륨이나 객체 저장소에 보관하고, Git에는 콘텐츠 해시와 재현 가능한 설정만 기록한다.
