# 로그인 화면 AI Lab 보조 링크 정돈

- 요청: 로그인 화면의 얇게 늘어난 `로그인 없이 AI Lab 둘러보기` 스타일 수정.
- 문제 연결: ISSUE-00040 디자인 시스템 후속. 기존 전역 링크 정리는 본문용 장식을 적용했지만 인증 카드의 독립 링크 크기·정렬을 지정하지 못했다.
- 범위/역할: 낮은 위험의 React UI 스타일 변경. 메인이 프론트엔드 구현·문서·본래 화면 검증·통합, 별도 코드 리뷰어가 독립 검토/기존 회귀를 맡는다. 인증 정책·API·DB·AI 동작 변경이 없어 관련 구현 역할은 제외한다.

## 수정

`LoginPage.tsx`의 로그인 전/후 공개 AI Lab 링크에 동일 `secondaryLink` class를 지정했다. native anchor와 기존 `/labs` 주소·문구는 유지한다. CSS Module에서 raised 표면, 경계, 차분한 글자, 가운데 정렬, 공통 반경·패딩·44px 최소 높이를 적용했다. hover는 청록 경계/글자, 키보드는 기존 2px outline·3px offset을 사용한다. 로그인 제출 버튼의 강조 계층은 유지한다.

공통 링크 CSS를 넓히는 대신 기능 소유 스타일로 한정했다. 로그인 요청·상태·권한·RAG·모델·설정·저장 결과 변경은 없다. 기존 미커밋 변경을 보존하며 새 패키지 설치·서버 재시작·모델 호출은 하지 않았다.

## 검증

- 본래 Next 개발 서버 `/login`의 실제 렌더링에서 보조 링크 366×47px, 가운데 정렬·밑줄 없음·12px/16px 패딩·기존 `/labs`를 확인했다.
- 실제 Chrome viewport 320/375px: 링크 238×47 / 293×47px, document scroll/client 320/320·375/375로 가로 넘침 없음. viewport는 원복했다.
- 비밀번호 → Tab → 제출 → Tab → 보조 링크, 2px outline·3px offset 확인. Enter로 공개 `/labs`의 `AI 연구실`에 실제 도달했다. 실제 로그인 제출은 하지 않았다.
- 전체 TypeScript: frontend에서 `node node_modules/typescript/bin/tsc --noEmit --pretty false` 통과.
- 변경 TSX lint: `node node_modules/eslint/bin/eslint.js src/features/identity/LoginPage.tsx --max-warnings 0` 통과.
- `git diff --check` 변경 범위 통과.
- 첫 `pnpm --dir frontend ...`는 corepack registry 조회 DNS 실패로 실행되지 않았다. 설치 없이 기존 node_modules의 동일 검사 도구를 직접 실행했다.
- 역할 selector는 base Python PyYAML 부재로 첫 실행 실패, 기존 프로젝트 Python으로 재실행해 `react-ui → frontend-engineer`를 확인했다.
- 독립 기존 `LoginPage.test.tsx`·`Button.test.tsx` 2파일 6개 통과(14.09초). 로그인 실패/대기·기본/보호 경로 이동과 두 공개 링크 URL, 버튼 동작을 검증했다. 최초 Vitest는 시스템 Temp rename EPERM으로 0개 실행됐고, 작업 전용 Temp 지정 후 통과했다.
- 독립 before snapshot 대비 코드 리뷰에서 차단 지적 없음. 토큰의 색 조합 계산은 일반 글자8.26:1·hover9.21:1·경계/카드3.03:1·focus/카드12.11:1이다. 본래 화면의 기본 글자/배경은 해당 RGB와 일치한다.
- 추가 합성 Edge 하네스는 임시 virtual JSX 로더 오류로 중단했으며 성공에 집계하지 않는다. 실제 로그인 후 상태와 임의 긴 문구의 배치 수용은 미검증이고, 로그인 후 링크 URL/상태는 위 unit 회귀 범위다. 본래 화면 검증과 독립 소스 검토를 하네스 성공으로 대체 표현하지 않는다.

증거: `.local-data/project-agent-work/login-secondary-link-20261030/`의 수정 전 파일, `login-desktop.png`, `login-320.png`, `login-375.png`, 독립 검사 기록.

## 기록 경계

디자인 정본과 적용 현황을 갱신했다. 본래 관리자 문제 이력 URL은 로그인으로 이동해 ISSUE-00040의 DB 진행 이력은 **반영 대기**다. 스타일 수정과 공개 화면 검증을 진행했으며 기록만을 위해 인증을 우회하거나 계정을 만들지 않았다. 기존 이슈 상태·과거 기록은 변경하지 않았다.
