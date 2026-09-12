# Founder 사장실과 RAG 연구소 탐색

## 승인 범위

사용자는 사장실에 본인 캐릭터가 연구 방향을 지시하는 장면, RAG 공간 안의 총괄을 통한
직접 연구소 진입, 캐릭터와 내부 연구 공간의 품질 개선을 승인했다. 기존 게임 입구와
공개 RAG 작업실을 발전시키며 실제 AI 명령 전송·인증·비공개 데이터 연결은 포함하지 않는다.

## 설계 기준

- Founder는 `LEE BEOMSHIK / Founder`로 표현하며 방문자 플레이어와 별개다.
- 사장실의 지시는 공개 연구 방향을 설명하는 연출이다. 실제 작업 이력·진행률이 아니다.
- 메인 RAG 공간의 총괄 클릭/근접 E → React 안내 → `/labs/rag` 입장.
- 기존 RAG 작업실의 여섯 담당자, 소개·현재 작업·입출력·인계 설명과 서비스 경로를 보존한다.
- Next/React UI와 메인 Phaser 공간의 책임 분리, Tiled 배치/충돌 데이터 경계를 유지한다.
- 캐릭터·타일·가구를 분리하여 표현한다. 통배경 이미지와 외부 자산 의존을 추가하지 않는다.
- 연구하지 않은 Lab의 빈 방·가짜 메뉴·AI 실행 상태는 만들지 않는다.

## 역할과 상태

메인이 요구·ADR·작업 보드와 실제 브라우저 통합 검증을 맡고, 프론트 구현/테스트와 독립 코드
리뷰를 분리한다. main의 기존 변경은 보존하며 자동 커밋·푸시·캐시 삭제를 하지 않는다.
구현 후 독립 리뷰와 실제 브라우저 검증을 진행한다. 최종 상태는 아래 결과를 기준으로 확인한다.

## 수용 검증

1. 메인에서 사장실과 RAG 공간이 구별되고 각 NPC가 자기 공간 안에 있다.
2. 이동 플레이어는 Founder와 별개이며, 벽/가구를 통과하지 않고 두 NPC에게 접근 가능하다.
3. Founder를 클릭하면 이름·연구 방향·복수의 역할별 지시가 보이며 실행 중으로 오인시키지 않는다.
4. RAG 총괄의 마우스 클릭과 근접 E로 같은 소개/연구소 입장 버튼을 연다.
5. 잘못된 NPC ID, loading/error 및 열린 대화에서 재선택은 허용하지 않는다.
6. 대화 중 이동 잠금, Escape/닫기 뒤 복귀, Tab 접근, resize 및 라우트 재진입을 유지한다.
7. `/labs/rag`에서 여섯 작업자를 각각 선택해 설명을 확인하며, 기존 로그인 서비스 링크를 유지한다.
8. 1440×900 및 960×640에서 그래픽·UI 겹침과 대화 배치를 확인한다.
9. 단위/UI·타입·린트·빌드·실제 Edge 시나리오 및 독립 리뷰 증거를 구분하여 남긴다.

## 검증 결과

### 구현 파일과 책임

- `frontend/src/features/office-game/npcs.ts`, `gameStore.ts`, `OfficeOverlay.tsx`:
  Founder 공개 지시 소개, RAG 총괄 등록, 클릭/근접 E의 안전한 선택 상태와 React 대화.
- 같은 영역의 `assets.ts`, `office-decor.ts`, `config.ts`, `entities/`, `scenes/OfficeScene.ts`:
  사람형 방향별 캐릭터, 분리 가구, 발 위치 충돌, 클릭 영역과 카메라/수명주기.
- `frontend/public/office/maps/office.json`, `tiles/office-placeholder.svg`:
  사장실·RAG 공간·로비 및 문/가구 충돌과 독립 타일. 통배경 이미지가 아니다.
- `frontend/src/features/public-labs/human-art.ts`, `PixelPerson.tsx`,
  `rag-station-art.ts`, `RagWorkbench.tsx`: 공용 사람형 미술 데이터와 역할별 작업대.
- `RagLabOverviewPage.tsx`, `RagWorkerCharacter.tsx`, `AgentCharacter.tsx`,
  `InteractiveAgentCharacter.tsx`, `PublicLabScene.module.css`:
  기존 여섯 담당자의 데이터·대화를 보존한 열린 연구실 표현. 기본 로봇 시각은 유지한다.
- 해당 단위/UI 테스트와 `frontend/tests/office/office.e2e.ts`: 상태 가드, 대화,
  이동/충돌, 직접 입장과 라우트 복귀 검증.
- ADR-0018, 프로젝트 비전/시스템 설계, 로컬 실행 안내와 WORKBOARD: 승인 범위와 확인 경로.

### 검증 진행

- 초기 단위 RED는 Founder/RAG 등록·선택·방 정보·안내 target 누락을 확인했다.
- 첫 Edge 4개 시나리오 통과. 독립 1440×900 및 960×640 입력 검증에서 Founder/RAG,
  여섯 담당자, reduced-motion, 브라우저 오류 0·변이 요청 0을 확인했다.
- 전체 프론트 첫 실행은 297개 중 296개 통과, 기존 카드 화살표 CSS 문자열 검사 1개 실패.
  새 열린 연구실의 반응형 배치 계약을 실제 Edge 1440/960/640px의 3/2/1열·순서·겹침·바닥선
  검증으로 옮겼다. `src/app/styles.test.ts`에 브라우저 검증 위치를 남겼다.
- 시각 검토에서 짧은 화면의 Founder 닫기 버튼이 상단 header에 가려지는 문제를 발견했다.
  회귀 테스트에서 dialog.top=24 < header.bottom=72를 먼저 재현했다. `.world` 기준 absolute
  backdrop와 영역 내 최대 높이로 수정 후 실제 close 클릭·포커스 복귀를 확인했다.
- 보완 Edge 2개와 관련 단위 8개 통과. 최종 변경의 Next production build와 TypeScript 통과.
- 최종 Edge 전체 6개 통과(54.4초), 전체 ESLint exit 0. 독립 scoped 재리뷰는 두 문제 모두
  ADDRESSED이며 수정으로 생긴 새 결함은 없다고 판정했다.
- 최종 통합 독립 리뷰 APPROVED: 추가 조치 또는 보류한 경미 결함 없음.
  최종 전체 프론트 단위/UI 63개 파일·296개 테스트 통과(300.87초).
  기존 ModelLabPage 테스트의 React act 경고는 남아 있으나 실패는 없다.

검증 명령은 `frontend/`에서 실행했다.

```text
node node_modules/vitest/vitest.mjs run --pool=threads --maxWorkers=2 --reporter=dot
node node_modules/@playwright/test/cli.js test --config playwright.office.config.ts
node node_modules/eslint/bin/eslint.js .
node node_modules/next/dist/bin/next build
```

### 실행 및 범위

기존 로컬 서버에서 `/`로 접속한다. WASD/방향키로 위쪽 사장실 또는 오른쪽 RAG 공간으로
이동하고 캐릭터 클릭 또는 근접 E로 소개를 연다. RAG 총괄의 입장 버튼은 `/labs/rag`로 연결된다.
새 라이브러리 설치나 backend/DB/인증 변경은 없다. 실제 AI 지시 전송·실행 상태 연결과
전체 타 연구실 확장은 이번 범위가 아니다. 원본 그래픽 자산으로 교체 가능한 코드 기반 픽셀 표현이다.

구현·검증·독립 리뷰를 완료했다. `main` 작업 폴더에 변경을 유지했으며 커밋/푸시는 하지 않았다.
이번 작업의 테스트는 공개 화면만 사용했고 DB 데이터/모델 실행을 만들지 않았다. 임시 스크린샷과
검증 기록은 단일 task 경로의 정리 후보이며 CACHE_POLICY의 정확 대상 승인 전에는 삭제하지 않는다.
이전 구현 인계: `2026-09-07-game-office-mvp.md`, `2026-09-07-office-visual-polish.md`.
