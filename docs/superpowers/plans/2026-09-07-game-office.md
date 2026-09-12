# 게임형 연구소 입구 MVP 구현 계획

> 사용자 상세 요구를 승인된 명세로 사용한다. main에서 기존 변경을 보존하며
> 역할별 구현 후 독립 검증한다. 자동 commit/push 또는 worktree는 만들지 않는다.

## 성공 기준

`/` 접속 → 타일형 로비 → WASD/방향키 이동 → 벽/가구 충돌 → 카메라 추적
→ LLM Lead 접근 → `[E]` 안내 → React 대화창 → 닫기 → 이동 복귀.
SSR, StrictMode 재마운트, resize, 포커스 이탈에서 게임/키 이벤트가 누적되지 않아야 한다.

## 역할과 범위

- 오케스트레이터: 요구/아키텍처/설계 문서, 의존성 설치와 통합, 작업 보드.
- 프론트 구현·테스트 설계: `frontend/src/features/office-game/`, 맵,
  메인 라우트, 별도 Tailwind stylesheet/PostCSS 구성. RED/GREEN 증거를 남긴다.
- 독립 코드 리뷰·통합 검증: 구현과 별도로 요구 충족, lifecycle, 접근성,
  충돌, 회귀 위험을 검토한다. 백엔드/DB/AI 전문 구현은 범위 밖이다.

## 작업 1: 연결 가능한 수직 슬라이스

1. 테스트: 상태 브리지, NPC 근접/룸 판정, 대각선 정규화, 맵 계약,
   비동기 lifecycle 취소/해제, React 대화 열기/닫기와 이동 잠금.
2. Phaser 4.2.1, Zustand 5.0.15, Tailwind/PostCSS 4.3.3을 frontend에만 설치.
3. Tiled 호환 작은 맵, placeholder texture/animation, Player/NPC,
   OfficeScene, client-only host, bridge와 React UI 구현.
4. 공개 root만 연결하고 기존 탐색/관리자 기능과 전역 스타일은 보존.

## 작업 2: 검증과 보완

1. `pnpm test --run src/features/office-game`.
2. `pnpm typecheck`, `pnpm lint`, `pnpm build` 및 관련 공개 탐색 테스트.
3. 실제 브라우저에서 이동/벽/대각선/카메라/E/닫기/포커스/resize/재진입 확인.
4. 독립 리뷰의 중요 결함을 수정하고 해당 테스트 재실행.

## 작업 3: 인계

구현 파일·실행 방법·검증 증거·미구현 경계를 작업 로그에 기록한다.
WORKBOARD 현재 작업을 갱신하고 최근 완료는 최대 5개만 유지한다.
생성 캐시는 CACHE_POLICY를 따르며 원본/모델/사용자 자료를 정리하지 않는다.
