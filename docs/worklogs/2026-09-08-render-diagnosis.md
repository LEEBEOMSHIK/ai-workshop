# 돌아가기 버튼과 반복 렌더링 진단

## 반영

PublicStudyDetail의 목록 복귀 Link에 기존 readIndicator 버튼 스타일을 적용했다.
주소와 링크 의미를 보존했고 관련 테스트 7개 및 실제 Edge의 44px 버튼 표시·Enter 복귀를 확인했다.

## 관찰과 원인

메인, RAG 연구실, 기록 목록, 기록 상세를 각각 안정화 3초 후 7초 관찰했다.
아무 조작 없이 각 페이지의 RSC fetch가 6–7회 발생했다. 화면 텍스트는 유지됐다.
WebSocket에서 building/built/serverComponentChanges가 반복되고 개발 표시가 Rendering...이었다.

`frontend/.next/dev/logs/next-development.log`에는 약 1초 간격으로
`[Server HMR] Subscription error, resubscribing: TurbopackInternalError`와
`VersionedContents ... no longer exists`가 기록됐다.
설치된 Next의 `server/dev/hot-reloader-turbopack.js` 229–231에서 subscription 예외 시
전체 모듈 재평가 후 1000ms 뒤 재구독한다. 재평가 경로는 serverComponentChanges를 보내고
브라우저가 RSC를 다시 가져온다. 이 복구 반복이 전체 공개 화면의 렌더링 표시 원인이다.
오류를 최초 유발한 변경이나 디스크 캐시 손상까지 입증한 것은 아니다.

메인의 Phaser 프레임 루프는 정상 게임 동작이다. 별개로 위치가 같아도 100ms마다 새
playerPosition 객체를 store에 넣는 비효율은 있지만, canvas가 없는 상세 화면에서도
같은 HMR 루프가 재현되므로 이번 전체 페이지 반복 요청의 원인과 구분한다.

## 조치 경계

사용자 요청은 원인 확인이므로 렌더링 코드·Next 설정·실행 서버·캐시는 변경하지 않았다.
권장 후속은 프론트 개발 서버만 정상 재시작한 뒤 네 경로의 무입력 RSC·HMR 요청을 재검증하는 것.
재현되면 별도 승인된 빌드 인스턴스나 번들러 비교로 원인을 더 좁힌다. 캐시 무조건 삭제나
개발 표시 숨기기로 완료 처리하지 않는다. API·DB·공개 기록은 그대로다.

## 승인된 재시작과 결과

사용자가 프론트만 재시작하는 조치를 승인했다. 5173 listener와 부모 CLI 및 PostCSS
자식 프로세스를 정확히 확인한 뒤 해당 프론트만 종료하고 기존 combined 모드·5173으로
다시 실행했다. private API 18000과 공개 reader 18001, DB·캐시는 변경하지 않았다.

재시작 후 네 경로를 각각 안정화 3초·무조작 7초 관찰했다. 모든 경로의 추가 요청 0건,
브라우저 오류 0건, main DOM 변경 0건이었다. 별도 9초 HMR 관찰에서도
serverComponentChanges 반복이 없고 Rendering... 표시가 사라졌다. 현재 개발 서버 로그에서
이전 subscription 오류가 재발하지 않았다. 단기 복구 확인이며 장시간 재발 가능성이나
Turbopack 자체 결함의 영구 수정까지 입증한 것은 아니다.

실행 중 프론트 exec 세션은 92478이다. Next가 next-env.d.ts를 정상 dev/types 경로로
자동 갱신했다. 번들러 설정 변경·의존성 교체·캐시 삭제는 하지 않았다.
