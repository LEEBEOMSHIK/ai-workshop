# 파일함 root 표시와 이동 확인창 개선

- 범위: 사용자 승인한 최상위 표시·이동 확인창 가독성의 제한된 UI 변경.
- 작업 위치: main. API·DB·검색·권한 계약과 실제 문서 위치는 변경하지 않는다.

## 변경

- 파일 트리, 현재 위치 제목·저장 위치와 이동 확인창의 null 위치 표시를 `root`로 통일한다.
- 실제 이름이 `root`인 자식 폴더는 별개 ID와 계층으로 보존한다. 자동 병합·생성·이동은 없다.
- 이동 대상 종류/이름, 출발지와 목적지, 공간명과 폴더 경로를 구분한다.
- 목적지 탐색과 최종 취소/확인을 분리하고 긴 이름·좁은 화면은 줄바꿈으로 처리한다.
- 기존 명시 확인, 중복 제출 방지, 충돌·불확실 응답 복구, 대화 범위 무확대 계약을 유지한다.

## 검증 결과

- 구현 담당: 기존 assets 4파일을 새 수용 기준으로 먼저 실행해 예상 RED 27실패/50통과를 확인했다.
  구현 뒤 이동33건 및 트리/열람/관리44건 통과, 대상 TS/TSX 린트 통과를 보고했다.
- 독립 검토: 1440px·390px Edge와 격리 Next/메모리 API에서 긴 이름·경로·버튼의 가로 넘침 없음,
  같은 위치 확인 비활성, 명시 확인 전 POST 없음, null 목적지 1회 전송, 실제 root 자식 구분,
  Tab/Shift+Tab/Escape·초점 복귀를 확인했다. 25개 합성 요청, 실제 자료 변경 없음.
- 독립 브라우저 검사 프로세스를 종료하고 해당 포트의 LISTEN 부재를 확인했다.
  Next가 추가한 검증 인스턴스 타입 참조는 원래 실행 설정으로 되돌렸다.
- 검토에서 실제 root 상위 폴더와 최상위의 접근성 이름 중복 Minor를 발견했다.
  상위 폴더 버튼에 전체 경로 기반 접근성 이름을 추가하고, 명시적 root 자식 ID와 null 탐색을 구분하는
  테스트의 RED→GREEN 및 이동34건 통과를 확인했다. 독립 재검토에서 해당 지적 해소를 확인했다.
- 메인 TypeScript 검사와 전체 ESLint를 통과했다. 최초 타입 검사는 테스트 선택자에 잘못 추가한
  `exact` 옵션 때문에 실패했으며 해당 옵션만 제거한 뒤 재실행해 통과했다.
- 최초 관련12파일153건 통과 후, 접근성 보완을 포함한 최종 회귀12파일154건을 재실행해 통과했다(exit0,159.29초).
  구현 담당의 개별 실행에서 기존 React act 경고2건을 보고했으며, 메인 최종 실행은 실패 없이 종료했다.

메인 검증 명령(`frontend`에서 기존 의존성으로 실행):

```powershell
node node_modules/vitest/vitest.mjs run src/features/assets src/features/rag/domains/DomainFileCabinet.test.tsx src/features/rag/domains/DomainFileCabinet.movement.test.tsx src/features/rag/conversation/DocumentSelectionPanel.test.tsx src/features/rag/conversation/ConversationPage.test.tsx --pool=threads --maxWorkers=1
node node_modules/typescript/bin/tsc --noEmit --pretty false
node node_modules/eslint/bin/eslint.js . --max-warnings 0
```

브라우저 검증은 소스 컴포넌트를 실행하는 격리 합성 API 검사이며 실제 백엔드 E2E와 구분한다.
로컬 실제 API18000과 프론트5173의 `/api/v1/health`는 각각200으로 확인했다.

## 경계와 후속

- 삭제/휴지통 API·UI는 이번에 추가하지 않는다. 권한, 검색 제외, 복원 계약을 별도 설계한다.
- DB0034는 스키마 변경 코드이며 과거 DB를 버전마다 자동 복제하는 캐시가 아니다.
  이전 조사에서 확인된 백업·복원 DB는 삭제하지 않았다. 실제 적용 증거는
  [로컬 적용 기록](2026-09-13-movement-local-cutover.md)을 따른다.
- 기존 복구 중 뷰어 닫기의 비활성 opener 초점 Minor는 별도 후속이다.
- 새 패키지 설치, 실사용 업로드·이동·삭제, 모델 호출, migration, 서버 재시작, 커밋·푸시는 하지 않았다.
- 검증 스크립트/스크린샷은 `.local-data/project-agent-work/root-modal-review/`에만 둔다.
  실행 중 프론트 캐시·사용자 자료·references를 정리하지 않는다.

## 2026-09-20 커밋 인계

- 사용자가 남은 변경 중 커밋할 항목의 커밋·푸시를 승인했다. UI 구현·테스트·설계·ADR을 한 묶음으로 인계한다.
- 독립 재검증: 관련 12파일 154개 테스트 통과(exit 0, 155.16초), TypeScript `--noEmit` 및 전체 ESLint `--max-warnings 0` 통과.
- 독립 diff/설계 검토에서 차단 지적 없음. 이번에는 브라우저를 재실행하지 않았으며 위의 기존 합성 브라우저 검증 기록을 참고했다.
- ADR의 삭제 설계 승인 상태를 현재 작업 보드에 맞췄다. `references/images/img.png`는 용도가 확인되지 않은 사용자 참고 자료로 보존하고 제외한다.
