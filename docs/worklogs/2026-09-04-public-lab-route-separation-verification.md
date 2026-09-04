# 공개 연구소 입구와 Lab 작업 현장 분리 검증

- 기준일: 2026-09-04
- 대상: 공개 `/`, `/labs`, 기술 관리자 대화상자와 공개 URL 문서
- 결정: `docs/decisions/0006-separate-public-entrance-and-labs.md`

## 구현 결과

- `/`는 `LabEntrancePage`에서 공개 catalog의 기술 관리자를 `roaming` 상태로 보여준다.
- 입구 관리자 대화상자는 `/labs`로 안내한다.
- `/labs`는 기존 `LabWorldPage`에서 연구실 장비와 `working` 관리자를 보여준다.
- 작업 현장 관리자 대화상자는 catalog의 `/labs/{slug}` 상세로 안내한다.
- `/`와 `/labs`는 각각 자기 canonical URL을 갖는다.
- 공개 catalog, RAG 상세, 백엔드 API와 DB 계약은 변경하지 않았다.

## TDD와 자동 검증

기존 코드에서 메인 입구 heading 부재와 `/labs` canonical 오류를 먼저 재현했다. 이후 최소
구현으로 관련 테스트를 통과시키고, 입구의 빈·오류 상태를 별도 RED-GREEN 단계로 추가했다.

- 관련 public-labs·route 테스트: `5 files, 18 passed`
- 전체 frontend Vitest: `39 files, 145 passed`
- TypeScript: `tsc --noEmit --pretty false` 통과
- ESLint: `eslint . --max-warnings 0` 통과
- Next.js `16.3.4` production build: `11/11` route 생성 통과
- `git diff --check`: 오류 없음

## 실제 브라우저 검증

별도 headless Chrome과 CDP device metrics로 `/`와 `/labs`를 다음 CSS viewport에서 확인했다.

- `1440×900`
- `1024×768`
- `768×1024`
- `390×844`
- `320×568`
- `844×390`
- 정확한 mobile 경계 `767×900`
- DPR 2의 `720×450` CSS viewport로 물리 `1440×900` 200% 대응 조건

모든 화면에서 실제 `innerWidth`, `scrollWidth <= clientWidth`, 경로별 heading과 장비 노출
경계, 캐릭터 대화상자의 CTA URL·문구, 닫기 버튼 초기 초점과 viewport containment를 확인했다.
동작 감소 환경에서는 media query가 일치하고 실행 중인 CSS 애니메이션이 0개였다.

직접 확인한 사용자 흐름은 다음과 같다.

1. `/`에서 연구실 장비 없이 입구 광장과 이동 중인 RAG 총괄을 본다.
2. 캐릭터 소개의 `AI Labs 살펴보기`로 `/labs`에 이동한다.
3. `/labs`에서 문서 수집 라인, 검색 코어, 근거 검증 모니터와 작업 중인 RAG 총괄을 본다.
4. 작업 현장 소개는 `RAG 연구실 들어가기`로 `/labs/rag`를 가리킨다.

## 검증 중 확인한 사항

CLI screenshot의 `--window-size=390,844`는 Windows 200% 배율과 Chrome 최소 창 폭 때문에
요청한 CSS viewport와 다른 이미지를 만들 수 있었다. 앱 CSS를 임의 수정하지 않고 CDP의
`Emulation.setDeviceMetricsOverride`로 CSS viewport와 DPR을 분리해 다시 검증했다.

## 독립 리뷰

첫 리뷰에서 작업보드의 과거 동일 화면 문구, 경로별 빈·오류 상태 문서, `/labs/rag` 기본
CTA 테스트와 새 입구의 viewport 검증 공백이 지적됐다. 모두 보완한 뒤 재리뷰에서
Critical·Important·Minor finding 없이 `Ready: Yes` 판정을 받았다.
