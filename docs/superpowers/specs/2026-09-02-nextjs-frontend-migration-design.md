# Next.js 프론트엔드 전환 설계

- 상태: 사용자 검토 대기
- 작성일: 2026-09-02
- 대상: `frontend/`, FastAPI 관리자 권한 API 경계, 로컬 실행·검증 문서

## 1. 배경

현재 프론트엔드는 React 19, React Router와 Vite 기반 SPA다. 최초 관리자 설정과 지식
공간, RAG 검색·구성·모델 화면이 구현됐지만 공개 초기화, 일반 작업소와 관리자 운영 화면이
동일한 라우터 계층에 놓여 URL과 레이아웃의 책임이 명확하지 않다.

프론트엔드를 Next.js App Router로 전환해 URL, 레이아웃, 초기 데이터 로딩과 접근 안내를
구조적으로 분리한다. FastAPI는 사용자, 세션, 권한, AI·RAG와 데이터베이스 업무 규칙의
유일한 정본으로 유지한다.

## 2. 결정

- Next.js `16.3.4`와 App Router를 사용한다.
- React와 TypeScript를 유지한다.
- Vite와 React Router를 병행하지 않고 하나의 전환 작업에서 제거한다.
- Next.js는 화면 렌더링과 FastAPI rewrite만 담당한다.
- Next.js에 별도 사용자 저장소, 세션 토큰 발급 또는 AI 업무 로직을 만들지 않는다.
- 서버 렌더링을 기본으로 사용하고 사용자 상호작용이 필요한 최소 경계만 Client Component로
  둔다.
- 로컬 프론트 주소는 `http://127.0.0.1:5173`을 유지한다.
- 루트 `.env`의 `API_PORT`로 FastAPI rewrite 대상을 구성한다.
- FastAPI OpenAPI에서 생성한 TypeScript 타입을 프론트 계약의 정본으로 유지한다.

## 3. 목표와 제외 범위

### 목표

- 공개·초기화, 사용자 작업소와 관리자 화면을 URL 및 레이아웃으로 분리한다.
- 관리자 한 명도 일반 작업소와 관리자 화면을 같은 계정으로 이용하게 한다.
- 관리자 등록 직후 전사·개인 기본 공간을 `/app/workspaces`에서 표시한다.
- 기존 검색, 구성, 모델, 문서 화면의 기능과 API 계약을 보존한다.
- 기존 URL을 새 canonical URL로 이동시킨다.
- Server Component의 초기 데이터 로딩과 Client Component의 상호작용 책임을 분리한다.

### 제외 범위

- NextAuth 또는 별도 Next.js 세션 저장소
- FastAPI 업무 API를 Next Route Handler로 재구현하는 BFF
- 사용자 초대, 사용자 CRUD 또는 다중 관리자 UI
- 빈 `/admin/users` 또는 `/admin/workspaces` 화면
- 공개 전시실 구현
- Playwright와 브라우저 바이너리 설치
- DOCX 파서·뷰어 확장

## 4. URL과 레이아웃

```text
frontend/src/app/
├─ layout.tsx
├─ page.tsx                                  /
├─ (public)/
│  ├─ login/page.tsx                         /login
│  └─ setup/page.tsx                         /setup
├─ (workspace)/
│  └─ app/
│     ├─ layout.tsx                          /app/* 사용자 레이아웃
│     ├─ workspaces/page.tsx                 /app/workspaces
│     ├─ workspaces/[workspaceId]/documents/page.tsx
│     └─ rag/
│        ├─ search/page.tsx                  /app/rag/search
│        └─ configurations/page.tsx          /app/rag/configurations
└─ (administration)/
   └─ admin/
      ├─ layout.tsx                          /admin/* 관리자 레이아웃
      └─ rag/models/page.tsx                 /admin/rag/models
```

괄호로 감싼 route group은 코드 조직과 레이아웃 분리에만 사용하며 URL에는 나타나지 않는다.
`app`과 `admin` 폴더는 실제 URL segment다.

### 기존 URL 리다이렉트

| 기존 URL | canonical URL |
|---|---|
| `/workspaces` | `/app/workspaces` |
| `/workspaces/:workspaceId/documents` | `/app/workspaces/:workspaceId/documents` |
| `/rag/search` | `/app/rag/search` |
| `/rag/configurations` | `/app/rag/configurations` |
| `/rag/models` | `/admin/rag/models` |

단순 경로 변경은 `next.config.ts`의 permanent redirect로 처리한다. 동적 workspace ID를
보존한다. 애플리케이션 내부 링크는 canonical URL만 생성한다.

## 5. 인증과 권한

FastAPI가 기존 `ai_workshop_session` HttpOnly 쿠키를 발급·검증한다. Next.js는 JWT를
복호화하거나 동일 비밀키를 보유하지 않는다.

- 공개 페이지: `/`, `/login`, `/setup`
- 사용자 페이지: `/app/*`
- 관리자 페이지: `/admin/*`

`/app/*` 서버 레이아웃은 요청 쿠키를 전달해 FastAPI `/api/v1/auth/me`를 호출한다.
미인증이면 setup 상태를 확인한 뒤 `/setup` 또는 `/login`으로 이동한다. `/admin/*` 서버
레이아웃은 동일한 사용자 조회 후 `owner` 역할을 요구한다.

Next.js 접근 검사는 렌더링 전 사용자 안내를 위한 방어선이다. 모든 데이터 조회·변경은
FastAPI가 다시 인증하고 권한을 검사한다. 관리자 성격 FastAPI endpoint에는 재사용 가능한
`require_owner` 의존성을 적용한다.

URL 분리와 API 권한을 실제로 검증할 수 있도록 사용자 역할 계약에 `member`를 추가한다. 최초
설정은 계속 `owner` 한 명만 만들며 이번 범위에서는 사용자 초대·생성 UI를 만들지 않는다.
`owner`와 `member`는 `/app/*`를 사용할 수 있고 `/admin/*`는 `owner`만 사용할 수 있다.
현재 역할 컬럼이 문자열을 저장하므로 별도 데이터 마이그레이션이 필요한지는 구현 전 Alembic
상태 검사로 확인한다. 역할 추가는 OpenAPI와 인증 테스트에 반영한다.

## 6. FastAPI API 경계

### 유지하는 사용자·공개 API

- `/api/v1/setup/*`: 최초 로컬 설치
- `/api/v1/auth/*`: 로그인, 현재 사용자, 로그아웃
- `/api/v1/workspaces*`: 호출 사용자에게 허용된 공간
- `/api/v1/rag/search`: 사용자 검색
- `/api/v1/rag/configurations*`: 사용자 저장 구성과 비교
- 문서, job, source viewer와 사용자 평가 실행 API

### 관리자 API

기술 모델 등록·버전 관리와 시스템 기본값 변경은 다음 관리자 명령 endpoint를 정본으로
사용한다.

- `POST /api/v1/admin/rag/models`
- `POST /api/v1/admin/rag/profiles/{kind}`
- `POST /api/v1/admin/rag/profiles/{kind}/yaml`
- `POST /api/v1/admin/rag/profiles/{profileId}/default`

기존 동일 기능의 `POST /api/v1/rag/*` endpoint는 프론트가 새 API로 전환되는 호환 기간 동안
같은 서비스 계층을 호출하고 `require_owner`를 적용하며 deprecated OpenAPI 설명을 제공한다.
상태 변경 POST를 외부 redirect로 처리하지 않는다.

읽기 전용 `GET /api/v1/rag/models`와 `GET /api/v1/rag/profiles/{kind}`는 사용자 RAG 구성
화면에서도 필요하므로 인증된 사용자 조회 endpoint로 유지한다. 프로파일 생성·기본값 승격
같은 관리 명령만 관리자 namespace와 `require_owner`를 사용한다. 저장 구성의 사용자별
기본값과 평가 실행 API는 이번 전환에서 관리자 API로 이동하지 않는다. 이로써 화면 URL과
API 권한을 일치시키되 같은 데이터 조회 로직을 복제하지 않는다.

## 7. FastAPI 연결과 API 클라이언트

`next.config.ts`는 브라우저의 `/api/:path*`를 루트 `.env`에서 계산한 FastAPI 주소로
rewrite한다. API 주소 계산은 하나의 설정 모듈에서 검증하며 페이지나 컴포넌트에 포트를
하드코딩하지 않는다.

API 클라이언트는 다음 두 경계로 나눈다.

### 서버 API 클라이언트

- Server Component와 서버 레이아웃에서 사용한다.
- `next/headers`의 요청 쿠키를 FastAPI `Cookie` header로 전달한다.
- 사용자별 데이터는 `cache: "no-store"`로 요청한다.
- 401, 403, 404와 setup 상태를 구분한 typed 오류를 반환한다.

### 브라우저 API 클라이언트

- 검색, 업로드, 로그인, setup, 모델 등록 등 사용자 이벤트에서 사용한다.
- 상대 경로 `/api/v1/...`와 same-origin 쿠키를 사용한다.
- 기존 OpenAPI 타입과 오류 envelope를 유지한다.

서버와 브라우저 클라이언트는 오류 decoding과 schema type을 공유하지만 런타임 전용 import를
서로 침범하지 않는다.

## 8. Server Component와 Client Component

페이지, 레이아웃과 최초 목록 조회는 Server Component가 담당한다.

다음 경계는 Client Component로 유지한다.

- 로그인과 최초 관리자 setup 폼
- 검색 입력·범위 선택·검색 실행
- 파일 선택·업로드·job 상태 polling
- 구성 스튜디오의 탭, 폼과 비교 선택
- 모델·프로파일 등록 폼
- 원문 하이라이트의 사용자 상호작용

`"use client"`는 위 기능의 최상단 상호작용 컴포넌트에만 둔다. 순수 표시 컴포넌트와 타입,
포맷터, API 계약 파일에는 사용하지 않는다.

## 9. 코드 조직

라우팅 파일에는 페이지 조합과 route-level 데이터 로딩만 둔다. 기존 도메인별 컴포넌트는
`src/features/`로 이동한다.

```text
frontend/src/
├─ app/                       Next.js route와 layout
├─ features/
│  ├─ identity/
│  ├─ workspaces/
│  ├─ assets/
│  └─ rag/
│     ├─ search/
│     ├─ configurations/
│     └─ models/
└─ shared/
   ├─ api/
   │  ├─ browser-client.ts
   │  ├─ server-client.ts
   │  └─ schema.d.ts
   ├─ auth/
   └─ ui/
```

Next.js 특수 파일에 업무 규칙을 두지 않는다. FastAPI와 공유해야 할 규칙은 OpenAPI 계약으로
표현하고, 프론트 전용 접근 결정은 작은 순수 함수로 분리한다.

## 10. 전환 순서

1. 현재 테스트와 API 계약을 기준선으로 고정한다.
2. Next.js 설정, root layout, 스타일과 API rewrite를 만든다.
3. `/`, `/login`, `/setup`을 이전한다.
4. `/app/workspaces`와 문서 화면을 이전한다.
5. RAG 검색과 구성 화면을 이전한다.
6. 모델 화면을 `/admin/rag/models`로 이전하고 관리자 권한을 적용한다.
7. 기존 URL permanent redirect를 추가한다.
8. Vite 진입점·설정과 React Router 의존성을 제거한다.
9. 실행서, 저장소 구조와 작업 대시보드를 갱신한다.
10. 전체 테스트, 정적 검사, Next production build와 host runtime smoke를 수행한다.

전환 중 임시로 Vite와 Next 스크립트가 함께 존재할 수 있지만 완료 상태에는 Vite와 React
Router가 남지 않는다. 별도 worktree나 기능 브랜치를 만들지 않고 사용자 지침에 따라
`main`에서만 작업한다.

## 11. 오류 처리

- FastAPI 연결 실패를 미인증 또는 빈 목록으로 바꾸지 않는다.
- 401은 login/setup 분기로, 403은 접근 거절 화면으로 구분한다.
- 관리자 권한 부족을 404 데이터 없음으로 표시하지 않는다.
- Server Component 초기 조회 실패는 route `error.tsx`에서 correlation ID와 재시도 안내를
  표시한다.
- 사용자별 API 응답을 Next server cache에 저장하지 않는다.
- API rewrite 대상 설정이 잘못되면 개발 서버 시작 또는 build 단계에서 명시적으로 실패한다.

## 12. 테스트와 검증

- Vitest와 Testing Library 기반 순수 컴포넌트 테스트를 유지한다.
- 접근 결정, legacy URL mapping과 API target 계산을 순수 함수로 검증한다.
- 서버 API 클라이언트의 쿠키 전달, `no-store`, 오류 decoding을 검증한다.
- setup 성공 후 `/app/workspaces`로 이동하고 기본 두 공간이 표시되는 계약을 검증한다.
- 미인증 `/app/*`, 소유자가 아닌 `/admin/*`, 완료된 `/setup`의 분기를 검증한다.
- FastAPI 관리자 endpoint의 owner 허용과 비관리자 거절을 API 테스트로 검증한다.
- 기존 RAG 검색·구성·모델 UI 동작 테스트를 새 route 경계에서 유지한다.
- FastAPI 전체 pytest, Ruff, mypy와 Alembic check를 실행한다.
- OpenAPI schema 생성과 `api:check`를 실행한다.
- 프론트 전체 테스트, TypeScript 검사, ESLint와 `next build`를 실행한다.
- host Next 개발 서버에서 공개 페이지, legacy redirect, FastAPI health rewrite와 인증된 workspace
  목록을 HTTP smoke로 검증한다.

Playwright와 브라우저 바이너리는 이번 전환에 추가하지 않는다. 실제 UI 상호작용은 기존
Testing Library 테스트와 사용 가능한 브라우저 수동 확인으로 보완한다.

## 13. 로컬 실행과 캐시

- PostgreSQL, Redis와 Elasticsearch만 Docker로 실행한다.
- FastAPI, Celery worker·beat와 Next.js는 호스트에서 실행한다.
- Next.js 생성물 `.next/`는 재생성 가능한 프론트 build cache로 분류하고 Git에서 제외한다.
- 의존성은 `frontend/node_modules`와 `frontend/pnpm-lock.yaml`로 한정한다.
- 루트 `node_modules`를 만들지 않는다.
- 캐시 정리는 `CACHE_POLICY.md`를 따르며 Next build cache를 자동 삭제하지 않는다.

## 14. 완료 조건

- `frontend`에서 Vite와 React Router 의존성·설정·진입점이 제거된다.
- 모든 기존 사용자 기능이 canonical Next.js URL에서 동작한다.
- 기존 URL이 정확한 canonical URL로 permanent redirect된다.
- `/app/*`와 `/admin/*`가 서로 다른 layout과 접근 정책을 사용한다.
- FastAPI만 세션, 권한과 AI·업무 규칙을 소유한다.
- 관리자 등록 후 전사·개인 공간이 `/app/workspaces`에 표시된다.
- 관리자 모델 화면은 `/admin/rag/models`에서 owner만 접근한다.
- OpenAPI 생성 타입과 프론트 API 호출이 일치한다.
- 전체 백엔드·프론트 검증과 host runtime smoke가 통과한다.
- `WORKBOARD.md`, 로컬 실행서와 저장소 구조 문서가 실제 코드와 일치한다.

## 15. 근거

- Next.js App Router는 파일 기반 page와 중첩 layout을 제공한다.
- route group은 URL에 나타나지 않으면서 화면 영역별 layout을 분리한다.
- external rewrite는 브라우저의 same-origin API 경로를 FastAPI로 전달할 수 있다.
- Next.js 인증 가이드는 화면의 사전 검사와 데이터 원천에 가까운 안전한 권한 검사를
  구분한다. 이 프로젝트에서는 FastAPI 검사를 안전한 최종 권한 경계로 유지한다.
