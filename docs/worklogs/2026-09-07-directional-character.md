# 플레이어 방향별 표현 보완

## 승인 범위와 원인

사용자는 메인 캐릭터의 좌우·뒷모습이 부자연스럽다는 피드백 뒤, 네 방향별 몸체와 보행
표현 보완을 승인했다. 기존 정면 스타일·색상은 유지하고 이동 속도, 발 충돌, 카메라,
맵, NPC 대화 및 RAG 화면 기능은 바꾸지 않는다.

이전 `humanPixels`는 정면 몸통·다리를 먼저 그리고 방향에 따라 얼굴만 옮기거나 덮었다.
그 결과 옆면에서도 가슴과 두 다리가 정면으로 남고, 뒷면에도 앞쪽 장식이 보였다.
보행 역시 작은 상하 변위의 3개 프레임을 바로 반복하는 방식이었다.

## 검증 기준

- 좌우는 좁은 몸통·옆얼굴·앞뒤 팔다리 겹침이 구별된다.
- 뒤에는 정면 얼굴·셔츠·넥타이 대신 뒷머리·목덜미·등판이 보인다.
- 발 디딤과 지나가는 자세가 연결되며 정지 시 해당 방향을 유지한다.
- 모든 그림은 48×64 셀 안에 있고 그림자·발 기준 위치를 유지한다.
- 공용 React 사람형과 NPC 정지 프레임을 유지하며 새 의존성을 추가하지 않는다.
- 프론트 구현/테스트 담당과 메인의 실제 브라우저 검증 책임을 분리한다.

## 결과

- `human-art.ts`: 좌우는 좁은 옆몸·한쪽 눈·코·앞뒤 팔다리와 수평 보폭을 별도로 구성했다.
  뒤는 뒷머리·목덜미·등판을 그리며 얼굴·셔츠·배지·넥타이를 재사용하지 않는다.
  정면 중립 자세와 색상은 유지하고 앞뒤 보행의 팔다리 변위를 보완했다.
- `office-game/assets.ts`: 기존 방향별 3개 그림 셀을 접지→중간→반대 접지→중간의 4박자로
  반복한다. 텍스처는 기존 12셀, NPC 정지 셀 1과 idle/walk 키를 유지한다.
- 두 영역의 새 테스트는 합성된 최종 픽셀의 옆면 폭·뒷면·보폭·셀 경계와 실제 애니메이션
  등록 결과를 확인한다. 원본 파일의 문자열 존재 검사는 사용하지 않는다.
- 메인이 네 방향의 실제 이동/정지와 브라우저 오류 0을 확인했다. 수정 전후 방향별 프레임과
  걷기 연속 그림도 시각 검토했다. 실제 Edge 회귀 6개 통과(54.6초), production build/타입 통과.
- 구현 담당의 관련 단위/UI 13개 파일·87개 테스트 통과(58.05초), 타입 및 변경 파일 린트 통과.
  독립 코드 리뷰는 승인했으며 조치할 결함을 발견하지 않았다. 전체 백엔드/프론트 전체 suite는
  이번 좁은 시각 변경에서 재실행하지 않고 관련 영역과 실제 회귀·전체 build를 검증했다.

추가 검증 명령(`frontend/`):

```text
node node_modules/vitest/vitest.mjs run src/features/public-labs src/features/office-game --pool=threads --maxWorkers=1
node node_modules/typescript/bin/tsc --noEmit --pretty false
node node_modules/eslint/bin/eslint.js src/features/public-labs/human-art.ts src/features/public-labs/human-art.test.ts src/features/office-game/assets.ts src/features/office-game/assets.test.ts --max-warnings 0
```

실제 브라우저 명령(`frontend/`):

```text
node node_modules/@playwright/test/cli.js test --config playwright.office.config.ts
node node_modules/next/dist/bin/next build
```

화면 확인: 기존 로컬 `/`를 새로고침하고 WASD/방향키로 네 방향 이동 후 정지한다.
새 이미지 다운로드·패키지·백엔드 작업 없이 코드 기반 캐릭터 표현만 변경했다.
main에 미커밋 변경으로 유지한다. 임시 비교/검증 스크린샷은 해당 task 디렉터리에만 있으며
CACHE_POLICY의 정확 대상 승인 전에는 삭제하지 않는다.
