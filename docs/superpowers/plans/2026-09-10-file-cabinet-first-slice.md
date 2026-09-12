# 독립 파일함 첫 단계 구현 계획

**Goal:** RAG 대화와 분리된 파일함에서 회사·개인 공간 탐색과 기존 문서 관리 기능을 제공한다.

**Architecture:** 기존 `/workshop/workspaces` 및 하위 문서 경로를 유지한다. 허용된 공간 목록을 표시하는
WorkspacePage와 LibraryTree/DocumentBrowser/LibraryViewer를 재사용한다. 검색·권한 API는 변경하지 않는다.

**Tech Stack:** Next.js, React, TypeScript, 기존 CSS Modules 및 Vitest.

**Spec:** 사용자가 승인한 독립 파일함/대화 분리 흐름. 이번 완료 범위는 첫 파일함 UI 단계다.

## 제약

- main에서 작업하며 관련 없는 변경·실제 자료·계정·서비스 설정을 바꾸지 않는다.
- UI 수치는 서버가 반환한 허용 공간 목록에서만 계산한다.
- 공간 이름 검색을 전체 문서 본문 검색으로 표시하지 않는다.
- 문서 단위 대화 필터 API가 없으므로 가짜 ‘선택 문서로 대화’ 기능은 만들지 않는다.
- 문서/폴더 이동·삭제·권한 편집·대화 저장·대화 내 업로드는 이 UI 단계의 완료 항목이 아니다.

## Task 1: 독립 파일함 화면

Files: `frontend/src/features/workspaces/WorkspacePage.tsx`, `WorkspacePage.module.css`, `WorkspacePage.test.tsx`;
`frontend/src/features/assets/DocumentBrowser.tsx`, `DocumentLibrary.module.css`, `DocumentBrowser.test.tsx`.

- [x] 회사·개인·임시 공간 필터, 공간 이름 검색, 빈 결과, 공간 생성 권한, 실제 문서 경로 연결을 테스트한다.
- [x] 실패를 확인한 뒤 파일함 제목·탐색·목록을 구현하고 기존 생성/원문/버전 기능을 유지한다.
- [x] 문서 탐색 화면에 파일함 복귀 경로를 제공하고 목록·뷰어와 일관된 전체 폭을 적용한다.
- [x] 해당 Vitest 테스트와 타입·린트를 실행한다.

## Task 2: 메뉴와 대화 경계

Files: `frontend/src/features/navigation/areaMenus.ts`, navigation tests;
`frontend/src/features/rag/domains/DomainPickerPage.tsx`, 해당 test.

- [x] 파일함 링크가 기존 보호 경로를 유지하고 RAG 대화와 별도 active 메뉴임을 테스트한다.
- [x] 실패 후 ‘파일 관리’ 표시를 ‘파일함’으로 변경한다. 경로·권한 판단은 그대로 둔다.
- [x] 메뉴·도메인 테스트를 재실행한다.

## Task 3: 통합 검증과 인계

- [x] 구현과 독립된 검토자가 권한·빈 상태·현재 경로·기존 자료 동작을 검토한다.
- [x] 기존 로그인 세션에서 파일함·공간·문서 뷰어를 읽기 전용 확인한다. 업로드나 계정 변경은 하지 않는다.
- [x] WORKBOARD와 결과 기록을 갱신하고 후속 문서 선택/대화 API 작업을 별도로 표시한다.
- [x] 커밋·push는 별도 요청 없이는 수행하지 않는다.
