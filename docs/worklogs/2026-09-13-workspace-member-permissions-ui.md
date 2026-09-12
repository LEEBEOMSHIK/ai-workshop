# 파일함 구성원 권한 UI

## 승인 범위

기존 파일함과 [권한 서버 계약](../superpowers/specs/2026-09-13-workspace-member-permissions-design.md)을 연결한다.
사용자는 누적 변경 커밋·푸시 이후 이 작업을 이어가도록 승인했다. 푸시는 원격 확인 문제로 차단되어 UI 작업을 먼저 계속한다.

- 전사 파일함 안에서 서버 capability의 manage_members가 참일 때만 구성원 관리 진입을 제공한다.
- 기존 구성원 목록을 페이지 단위로 조회하고 이름·소유자·활성 여부·읽기/쓰기/삭제 권한을 표시한다.
- 권한 편집은 명시 저장한다. 소유자는 수정하지 않고 비활성 계정은 편집하지 않는다.
- 저장에는 조회한 permission_revision을 사용한다.409는 자동 덮어쓰기 없이 새 조회를 요구한다.
- 읽기 철회 시 쓰기·삭제도 해제한다. 삭제 권한 저장과 실제 삭제/휴지통 기능 완료를 구분한다.
- 공간 변경·화면 종료 시 이전 요청/편집 결과를 폐기한다. 권한 실패 시 구성원 정보를 남기지 않는다.
- 대화 안의 문서 선택 화면에는 구성원 관리를 넣지 않는다. 파일 관리가 대화의 필수 단계가 되지 않는다.
- 신규 사용자 UUID 입력·사용자 검색/초대·소유권 이전·시스템 마스터 관리 메뉴 확장은 포함하지 않는다.

## 검증 진행

프론트 구현/테스트와 독립 보안·코드 검토를 분리한다. 실제 DB는0032 상태로 유지하며 새 API가 배포됐다고 표현하지 않는다.
독립 검토에서 패널 닫기 시 요청/편집 상태가 남는 문제를 확인했다. 닫을 때 controller 중단·상태 폐기,
재열기 시 capability·목록 재조회로 보완했다. 이미 서버에 반영된 저장을 abort가 취소한다는 뜻은 아니다.
다른 행 저장 중 충돌 목록 새로고침을 잠그고 controller 중복 검사로 중복 PUT도 차단한다.
페이지 추가 조회 오류는 기존 목록과 cursor를 유지하며 재시도 안내를 표시한다.
401/403/404 폐기 행렬, 권한 확인 중 status, 기존 파일함의 색상 토큰 적용까지 반영했다.

최종 lint에서 render 중 ref 갱신과 effect 동기 reset을 지적하여 workspace-keyed 내부 컴포넌트로 정리했다.
이후 재검토에서 재열기 capability 요청의 unmount 정리를 보완하고, 늦은 응답이 추가 구성원 조회를 시작하지 않는 회귀를 추가했다.
최종 독립 코드 재검토에는 남은 Critical/Important/Minor 지적이 없다.

main 최종 독립 재실행: `pnpm --dir frontend test --run src/features/workspaces/WorkspaceMemberPermissions.test.tsx`
→20통과(10.46초). 최종 통합·type·lint 결과는 아래 마감 기록을 따른다.

최종 구현 담당 결과: 패널20건과 `DocumentBrowser.test.tsx`·`DomainFileCabinet.test.tsx`·
`DocumentSelectionPanel.test.tsx`37건 통과(총57건). 전체 typecheck·변경 TS/TSX8파일 ESLint 통과.
main도 최종 패널20건과 typecheck를 재실행해 exit0을 확인했다. 전체 프론트 테스트 통과를 주장하지 않는다.
초기 RED 및 리뷰 보완 RED는 실패 원인을 확인한 뒤 구현했으며, 최종 결과와 섞어 계산하지 않는다.

## 변경 파일 역할

- `frontend/src/features/workspaces/api.ts`: 생성된 API 타입과 인증된 capability·구성원 조회·저장 요청.
- `WorkspaceMemberPermissions.tsx` 및 module CSS: 명시 저장 패널, 오류/충돌/권한·요청 수명주기.
- `DocumentBrowser.tsx`·`DocumentPage.tsx`: 독립 파일함 진입 연결. `DocumentLibrary.module.css`: 오류 색상 토큰.
- `DomainFileCabinet.tsx`: 독립 도메인 파일함에는 연결하고 embedded 대화 선택에서는 제외.
- 관련 테스트: 실제 컴포넌트에 합성 API 응답을 연결하여 노출·저장·경합 및 기존 파일 선택 계약 검증.

## 적용 경계

새 의존성·계정·자료 생성이나 실사용 DB migration, 서버 재시작은 하지 않았다.
브라우저 실사용/시각 검증은 포함하지 않는다. 사용자 권한을 UI에서 편집하려면0033 서버 적용이 먼저 필요하다.
다음 단계는 백업·복원 검증을 포함한 적용 절차 확인과 승인된 migration/API·worker 적용, 실제 화면 검증이다.

후속 사용자 승인으로 로컬 DB0033 적용·독립 데이터 보존 확인·API/worker/beat 재시작을 완료했다.
관련 UI54건·typecheck 재실행 통과. 로그인된 실제 화면 확인은 대기 중이다.
최신 적용 경계는 [로컬 적용 기록](2026-09-13-workspace-permissions-cutover.md)을 따른다.
