# 관리자 모집 중인 준비 공간

## 승인과 경계

사용자가 기존 회사 맵에 파인튜닝 연구소, AI 공부실, 온톨로지 연구소를 추가하고
`관리자 모집 중`으로 표시하도록 승인했다. 각 공간에 들어가 둘러볼 수 있으며 담당자 대신
빈 작업대와 모집 안내판을 둔다. 안내판 클릭 또는 근접 E는 목적과 준비 상태를 설명한다.

새 서비스 링크, 실제 채용 신청, AI 실행, 별도 Lab backend/라우트, 인증 변경은 없다.
기존 비공개 Learning이나 파인튜닝 관련 코드를 이 공간에 자동 연결하지 않는다.
AGENTS의 미래 기능 빈 폴더 금지는 유지하며, 승인된 맵 준비 공간의 예외는 ADR-0018에 기록했다.

## 수용 기준

1. 세 공간은 기존 사장실·RAG와 연결되고 벽/가구를 통과하지 않고 들어갈 수 있다.
2. 학습 장비, 책/노트, 지식 관계도라는 서로 다른 시각 요소가 있다.
3. 안내판은 NPC가 아니며 목적·관리자 모집 중·기능 준비 중만 표시한다.
4. 클릭/E, 닫기/Escape, 대화 중 이동 정지와 포커스 복귀를 지원한다.
5. 기존 Founder/RAG 소개와 `/labs/rag` 직접 진입, 개선된 캐릭터·카메라를 유지한다.
6. 실제 브라우저와 단위/UI·타입·린트·빌드, 독립 코드 리뷰를 구분하여 검증한다.

## 역할과 결과

프론트 구현·테스트 담당, 메인의 요구/문서·독립 브라우저 검증, 독립 코드 리뷰로 분리했다.
구현 파일과 책임:

- `office-game/preparingRooms.ts`: 준비 공간 ID·이름·목적과 공통 상태. 서비스 링크 없음.
- `gameStore.ts`, `OfficeOverlay.tsx`: NPC와 구분된 안내판 선택/근접 상태, 기존 대화 껍데기와
  로딩/잘못된 ID/열린 대화 가드, 이동 잠금과 닫기/포커스 복귀.
- `map.ts`, `npcs.ts`, `scenes/OfficeScene.ts`, `office-decor.ts`: 새 공간 이름과 Notices layer,
  안내판 상호작용 및 독립 가구/관계도 그림. NPC 추가는 없음.
- `frontend/public/office/maps/office.json`: 1536×2176 맵. 기존 좌표를 유지하며 남쪽 연결부와
  복도, 세 방 및 문·가구 충돌 추가. 파인튜닝/공부실/온톨로지는 왼쪽부터 배치했다.
- `preparingRooms.test.tsx`, `frontend/tests/office/office.e2e.ts`: 준비 공간 계약과 실제 이동 회귀.

검증:

- 새 테스트 5개가 준비 공간/선택 동작 부재로 실패하는 RED를 먼저 확인했다.
- 초기 관계도 보드가 온톨로지 접근을 막는 것을 경로 테스트와 독립 브라우저에서 확인했다.
  보드를 방 뒤쪽 y1950으로 옮겨 중앙 접근을 확보했다. 기존 화면을 재로드해 검증했다.
- 관련 단위/UI 5개 파일·24개 테스트 통과(44.91초), TypeScript와 관련 ESLint 통과.
- 메인의 실제 3개 방 click/E, 안내 중 이동 잠금, no service link, pageerror 0·변이 요청 0 확인.
- 메인의 전체 Office Edge 7개 통과(1.8분), Next production build/TypeScript 통과.
- 960×640에서도 세 방 click/E·닫기·이동 복귀, 링크 없음·pageerror 0·변이 요청 0을 확인했다.
  화면과 대화 배치를 시각 검토했다.
- 독립 코드 리뷰 승인: 추가 결함 없음. 별도 3,069개 발 크기 경로 샘플, 객체 ID 유일성과
  가구 시각 영역/충돌 footprint 일치를 확인했다. 기존 NPC/Interaction layer는 보존됐다.
- AGENTS 123줄, 관련 문서 diffcheck 통과. 프론트 전체 unit/backend suite는 이번 범위에서
  재실행하지 않았으며 office 관련 검사와 실제 전체 Office E2E/Next build를 검증했다.

검증 명령(`frontend/`):

```text
node node_modules/vitest/vitest.mjs run src/features/office-game --pool=threads --maxWorkers=1
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js src/features/office-game tests/office/office.e2e.ts
node node_modules/@playwright/test/cli.js test --config playwright.office.config.ts
node node_modules/next/dist/bin/next build
```

확인 방법: `/`를 새로고침하고 로비 중앙에서 아래쪽 통로로 이동한다. 연결 복도에서
왼쪽은 파인튜닝, 가운데는 AI 공부실, 오른쪽은 온톨로지 연구소다. 각 모집 안내판을 클릭하거나
근처에서 E로 안내를 열고 닫기/Escape로 복귀한다. 개발 서버 외 새 런타임 설치는 없다.

main 작업 폴더에 변경을 유지했으며 커밋/푸시하지 않았다. 테스트는 공개 공간만 이용했으며
DB/모델 실행 데이터를 생성하지 않았다. 임시 비교본/스크린샷은 단일 task 경로의 정리 후보로
CACHE_POLICY의 정확 대상 승인 전에는 삭제하지 않는다.
