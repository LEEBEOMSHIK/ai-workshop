# 게임형 AI 연구소 입구 MVP

## 범위와 상태

2026-09-07 사용자 상세 요구에 따라 기존 대시보드형 입구 대신 `/`에 게임형 공간을
구현했다. main에서 기존 작업 변경을 보존했으며 commit/push는 하지 않았다.
참고 이미지는 디자인 방향만 사용했고 복사하거나 배경으로 삽입하지 않았다.
이번 범위는 로비·LLM 연구실·플레이어·LLM Lead 한 명의 수직 슬라이스다.

## 구현 파일과 역할

프론트 기준 경로:
이름만 기재한 게임 파일은 `src/features/office-game/` 아래에 있다.

| 파일 | 역할 |
| --- | --- |
| `src/app/page.tsx`, `page.test.tsx` | 공개 root 진입 및 라우트 계약 |
| `src/features/office-game/GameClient.tsx` | 브라우저에서만 Phaser를 비동기 생성하는 React 호스트 |
| `PhaserGame.ts`, `lifecycle.ts`, `sceneCleanup.ts` | 게임·resize·늦은 import 취소·종료 자원 회수 |
| `scenes/OfficeScene.ts` | 단일 맵, 정적 충돌, 카메라, NPC 접근, 상태 갱신 |
| `entities/Player.ts`, `entities/NPC.ts`, `assets.ts` | 발 영역 충돌·Y 정렬·4방향 idle/walk 임시 sprite |
| `systems/OfficeInput.ts` | WASD/방향키/E, 포커스·탭 숨김·키 해제 |
| `gameStore.ts` | 세션별 Zustand vanilla 상태 브리지 |
| `map.ts`, `spatial.ts`, `npcs.ts`, `config.ts` | 공간 판정·Tiled 객체·NPC/방 정의·튜닝/자산 경로 |
| `OfficeOverlay.tsx`, `Office.module.css` | 현재 방, 조작 안내, 근접 버튼, React 대화 및 포커스 복원 |
| `public/office/maps/office.json` | Tiled 호환 24×20 orthogonal 맵, 9개 레이어 |
| `public/office/tiles/office-placeholder.svg` | 바닥·벽·식물·책상용 별도 임시 타일셋 |
| `src/app/office-tailwind.css`, `layout.tsx`, `postcss.config.mjs` | prefix 적용, preflight 제외한 Tailwind UI |
| `office.test.ts`, `GameClient.test.tsx`, `sceneCleanup.test.ts` | 공간·상태·입력·대화·수명주기 단위 테스트 |
| `tests/office/office.e2e.ts`, `playwright.office.config.ts` | 실제 브라우저 이동/충돌/대화/복구 회귀 |
| `package.json`, `pnpm-lock.yaml` | 최소 런타임 및 개발 의존성 고정 |

추가 의존성은 Phaser 4.2.1, Zustand 5.0.15이며 개발 전용으로 Tailwind CSS/
PostCSS plugin 4.3.3, Playwright Test 1.63.0을 사용한다. 모두 `frontend`에 설치했다.
Playwright는 기존 Edge 152를 사용했으며 브라우저 다운로드는 하지 않았다.

## 연결 경계

`HomeRoute → GameClient.useEffect → import(PhaserGame) → OfficeScene`으로 연결된다.
서버는 React UI만 렌더링하며 Phaser 모듈을 실행하지 않는다.
Scene은 세션 store에 위치·방·가까운 NPC를 전달하고 E 입력은 대화 상태를 변경한다.
React는 Zustand selector로 구독하며 대화 UI를 표시한다. Scene은 React를 참조하지 않는다.
현재 위치는 100ms 간격으로 반영하며 저장소·DB·계정에 저장하지 않는다.

대화창이 열리거나 canvas가 포커스를 잃으면 이동을 중지한다. 닫기/Escape는 canvas에
포커스를 돌려준다. 선택한 NPC의 공개 안내에서 기존 `/labs/rag`로 이동할 수 있다.
이 안내는 AI 답변이 아니며 실제 AI 실행과 인증은 이번 변경에 포함하지 않았다.

## 검증 및 발견한 이슈

- 공간/store/async lifecycle/Input/React 대화/Scene 종료: 신규 10개 통과.
- 독립 리뷰어 직접 실행: 신규 10개(11.36초), Edge E2E 3개(22.1초) 통과.
- 메인 Edge E2E: 3개(23.7초) 통과. 이동·벽/책상 충돌·E 대화·Escape/닫기·이동 잠금/
  복귀·포커스·960×640 resize·다른 경로 후 단일 canvas 복귀·맵 실패 안내 확인.
- 최종 root/공개/내비게이션 및 신규 범위 통합: 15개 파일 79개 통과(50.80초).
- TypeScript·ESLint 통과. 최종 소스의 Next 프로덕션 빌드 및 정적 root 생성 통과.
- 1440×900 브라우저에서 LLM 방과 대화창을 시각 확인했다.
- 초기 전체 회귀에서 구형 root 화면 계약 테스트가 발견돼 새 입구 계약으로 갱신했다.
  첫 전체 실행은 구현 중 cleanup RED와 이 구형 root 계약을 포함해 286 통과·2 실패였다.
  두 실패 모두 수정 후 각각 재검증했으며 이를 전체 288개 재실행 통과로 표시하지 않는다.

독립 리뷰에서 Phaser의 실제 Game.destroy 경로가 Scene shutdown이 아니라 destroy만
발생시키는 점을 발견했다. destroy 단독 이벤트의 미정리 실패를 먼저 재현하고 두 이벤트를
멱등 cleanup에 연결해 입력 리스너와 store 구독 누수를 수정했다. NPC body도 refresh 이후
발 크기를 적용하도록 정리했다. 수정 후 독립 재리뷰의 미해결 중요 결함은 없다.

## 실행과 다음 범위

설치·실행·테스트 정본은 [로컬 실행서](../runbooks/local-development.md)의 게임형 공개 입구 절이다.
이번 입구만 확인할 때 백엔드·Docker·로그인은 필요 없다.

다음은 사용자 이동감/크기 확인 후 타일셋·sprite sheet 품질을 올리고, 승인된 방/NPC를
데이터로 확장하는 작업이다. 전체 연구실, NPC 자동 이동, 모바일 최적화, 연구 진행 상태의
실제 runtime 연결은 미구현이다. 현재 그래픽은 최종 레퍼런스 수준의 완성 자산이 아니다.
Codex RAG 연결 작업은 별도 인계 상태 그대로 보존한다.
