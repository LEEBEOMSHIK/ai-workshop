# 전체 화면 AI 연구소 월드 구현·검증 기록

- 날짜: 2026-09-04
- 범위: 공개 `/`, `/labs`, RAG 연구실 장면, 관리자 캐릭터 소개 말풍선
- 설계: `docs/superpowers/specs/2026-09-03-full-screen-ai-lab-world-design.md`
- 결정: `docs/decisions/0005-public-ai-lab-world.md`
- 구현 계획: `docs/superpowers/plans/2026-09-04-full-screen-ai-lab-world.md`

## 구현 결과

- `/`와 `/labs`가 같은 공개 catalog와 `LabWorldPage`를 사용해 동일한 AI 연구소 월드를
  직접 렌더링한다.
- 현재 공개된 RAG만 연구실로 표시하며 문서 수집 라인, 검색 코어, 근거 검증 모니터와 작업
  중인 RAG 총괄 캐릭터를 DOM·CSS로 표현한다.
- 캐릭터 소개는 body portal을 사용한다. 데스크톱·태블릿에서는 캐릭터를 향하는 연결형
  말풍선이고, 48rem 미만에서는 safe area를 반영한 하단 패널이다.
- 대화상자는 초기 닫기 초점, 양방향 Tab 순환, Escape, 배경 차단, body scroll lock과
  `preventScroll`을 사용한 trigger 초점 복원을 제공한다.
- 빈 catalog와 조회 실패는 하드코딩 RAG fallback 없이 공개 탐색을 포함한 명시적 상태를
  표시한다.

## 구현 중 발견하고 해결한 문제

| 문제 | 원인 | 해결·회귀 방지 |
| --- | --- | --- |
| 320×568에서 15px 가로 넘침 | 전역 `body { min-width: 320px; }`가 세로 스크롤바를 제외한 content viewport보다 넓었다. | 고정 최소 폭을 제거하고 전역 CSS 계약 테스트와 6개 viewport 수치 검사를 추가했다. |
| 844×390에서 말풍선 하단 여백이 12px | 짧은 화면 규칙이 최대 높이를 `100dvh - 2rem`으로 늘려 배치 계산의 20px 여백과 충돌했다. | `100dvh - 2.5rem`으로 정렬하고 CSS 계약과 실제 rect를 검증했다. |
| 말풍선 종료 시 trigger focus가 스크롤할 가능성 | 기본 `focus()`가 화면 밖 trigger를 보이게 하려고 문서 위치를 바꾼다. | 두 종료 경로 모두 `focus({ preventScroll: true })`를 사용하고 호출 옵션을 테스트한다. |
| 정확히 1024px·768px에서 한 단계 작은 layout 적용 | inclusive `max-width`가 설계의 `이상` 경계까지 축소 tier에 포함했다. | `width < 64rem`, `width < 48rem`으로 바꾸고 1024/768/767px 실제 경계를 검증했다. |
| 개발 중 말풍선 배치 효과가 정리된 것처럼 관찰됨 | 장시간 열린 Next.js dev 탭이 여러 Fast Refresh를 거쳐 오래된 effect 수명주기 상태를 유지했다. | 최신 소스로 완전 새로고침한 뒤 재현되지 않았고, 배치·scroll lock·focus를 다시 측정했다. 제품 fallback 수정은 하지 않았다. |

## 실제 브라우저 증거

- `1440×900`, `1024×768`, `768×1024`, `390×844`, `320×568`, `844×390`에서
  `scrollWidth <= clientWidth`를 확인했다. 모든 크기에서 세로 콘텐츠 흐름은 유지됐다.
- 1024px은 12열 넓은 방, 768px은 2열 방과 tail이 보이는 fixed 연결 말풍선,
  767px은 tail이 없는 하단 패널이다.
- 데스크톱·태블릿 말풍선은 모든 경계가 viewport 안에 있고 tail 좌표가 trigger 사각형을
  향했다. 844×390에서도 상하좌우 20px 안전 여백을 유지했다.
- 390×844와 320×568에서 dialog, 닫기 버튼과 `/labs/rag` CTA가 모두 viewport 안에 있고
  하단 padding과 내부 스크롤 제한이 적용됐다.
- 닫기 초기 초점, Tab·Shift+Tab 순환, 배경 `AI Labs` 링크 차단, Escape 종료와 trigger
  초점 복원, body overflow 복원, `/labs/rag` CTA 이동을 확인했다.
- 별도 headless Chrome을 DPR 2와 CSS viewport `720×450`으로 실행해 물리적
  `1440×900`의 200% 확대 대응 조건을 재현했다. 가로 넘침이 없고 dialog가 viewport 안에
  유지됐다.
- 같은 별도 세션에 `--force-prefers-reduced-motion=reduce`를 적용했다.
  `matchMedia`가 true이고 캐릭터, 상태등, 컨베이어, 검색 코어와 모니터의 computed
  `animation-name`이 모두 `none`이었다.

## 자동 검증

- frontend Vitest: 38개 파일, 142개 테스트 통과
- TypeScript: 통과
- ESLint: 경고 없이 통과
- Next.js production build: 정적·동적 route 11개 생성 통과
- 프로젝트 에이전트 계약 검증: 통과
- `git diff --check`: 오류 없음
- 전체 구현 독립 리뷰: exact breakpoint 수정 후 Critical·Important·Minor 없이 `Ready: Yes`

## 변경하지 않은 경계

- 공개 catalog 내용·schema, backend API, DB migration과 RAG 검색·모델 파이프라인은
  변경하지 않았다.
- 새 이미지, 게임 엔진, WebGL·Canvas 또는 런타임 dependency를 추가하지 않았다.
- 인증된 작업소와 관리자 화면의 기존 동작은 이번 UI 변경 범위 밖이다.
