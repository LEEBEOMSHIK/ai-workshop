# 생성형 평가 준비 모드 분리

- 날짜: 2026-10-19
- 상태: frontend 구현·최종 전체 mock 회귀·독립 리뷰·현재 5173 제공본 확인 완료. 로그인 브라우저 수용·실제 평가 제출은 미실행.
- 범위: 저장 자료 재사용/새 자료 작성 모드 분리, 모드별 입력·초안 보존, 활성 자료/규칙 제출, 지연 응답 무효화, 성공 문구 일치, 사례 유형 표시.
- 제외: DB·backend·모델 설정 변경, 실제 평가 제출·모델 호출, 설치, 인증 우회, 사용자 화면 캡처, commit/push.
- 원인: 새 작성 영역의 구성/지식 공간 변경이 상위 snapshot과 규칙을 초기화하나 자료 ID와 성공 문구를 남겼다. 진단 mock7개로 재현했으며 자동 effect·단순 재렌더링·접기/펼치기는 원인이 아니었다.
- 설계: 두 모드의 입력 상태를 별도 보존하며 명시 전환 시 활성 실행 자료만 바뀐다. 정상 답변/근거 부족 유형은 저장 데이터에서 표시하고 정답 문자열을 주입하지 않는다.
- 역할: 메인 요구/RAG/통합·기록, frontend 담당 구현·테스트, 별도 담당 독립 코드 리뷰·mock 통합검증. DB/backend/AI/보안 계약 변화가 없어 해당 전문 구현 역할은 제외.
- 기준 상태: 시작 시1,981개 기존 파일 SHA-256 및 대상 파일 원본 보존. 기존 미커밋·미추적 변경 유지.
- 구현: 기본 `저장 자료 재사용`과 `새 자료 작성`을 명시적으로 분리했다. 각 모드의 자료·규칙·문맥·K·반복·동의를 별도로 보존하고, 숨겨진 작성 영역을 유지해 초안과 자료 선택도 보존한다. 비교 후보·승격 기준은 공통이며 제출에는 활성 모드의 자료/규칙만 사용한다. 지연 성공·오류 및 전환 전 요청의 콜백을 무효화하고 사례별 저장 유형을 표시한다.
- 리뷰 보완: 미완료 저장 중 모드 왕복 후 입력 검증에 실패하면 busy 상태가 남아 입력이 잠기는 결함을 독립 테스트로 발견했다. 새 실행 전에 이전 busy/오류/성공 상태를 정리했고, 잠김과 과거 성공 문구 재등장을 정식 회귀로 추가했다.
- 수정 파일: frontend `src/features/rag/configurations/`의 `GenerativeEvaluationPanel.tsx`, `EvaluationAuthoringPanel.tsx`, `EvaluationSourceSelector.tsx`, `generative-api.ts`, 신규 `useEvaluationPreparation.ts`, 신규 `GenerativePreparationModes.test.tsx`, 기존 `GenerativeEvaluation.test.tsx`; 기록은 이 문서와 `WORKBOARD.md`만 변경했다.
- 문제 이력 DB: 이번 요청의 DB 수정 금지 및 정상 로그인 세션 부재로 갱신하지 않는다.

## 실행한 검증

- TDD: 신규 모드 시나리오 7개 RED → GREEN, 리뷰 경계 2개 RED → GREEN. 최종 관련 4파일 53개 통과(43.55초). 보완 전 configurations 15파일 141개 통과는 중간 결과이며 최종 전체 결과와 구분한다.
- 최종 전체 frontend: `node node_modules/vitest/vitest.mjs run src --pool=threads --maxWorkers=1 --reporter=dot` **151파일 1,064개 통과**, exit 0, 1,206.99초. 문서 브라우저 및 모델 관리 화면 테스트에서 React `act` 경고가 출력됐으나 실패는 없었다. 동일 실행을 끝까지 유지했으며 중복 실행하지 않았다.
- TypeScript: `node node_modules/typescript/bin/tsc --noEmit --pretty false --incremental false` exit 0. 변경 frontend 7파일 ESLint 및 diff-check exit 0.
- 독립 검증: 관련 4파일 53개 통과. 최종 보완 후 입력 잠금 복구, 모드별 동의 분리·재로드 초기화, 숨겨진 미리보기의 지연 오류 무효화 3개 통과(17.25초). 병행 실행 중 두 테스트의 5초 timeout은 assertion 실패가 아니며 동일 assertion을 30초 한도로 다시 실행해 통과했다. 미해결 코드 리뷰 차단 없음.
- Node 실행기 mock: `node --experimental-test-module-mocks --test tests/local-python-runtime.test.mjs tests/openapi-runtime-selection.test.mjs` 15개 통과. 실 subprocess·외부 모델 호출 없음.
- 현재 제공본: 5173의 `src_features_rag_16hsyay._.js` 및 `.map` HTTP 200, 생성 파일과 바이트 일치. 소스맵에 포함된 구성 화면 TS/TSX 19파일이 현재 소스와 일치하며 새 hook도 포함된다. `/admin/rag/configurations`는 정상 로그인 경로로 이동했고 인증을 시도하지 않았다. 이는 제공 자산 확인이며 사용자의 브라우저 메모리·로그인 E2E 검증이 아니다.
- 보존: 최초 1,981개 파일 해시 대조에서 허용한 기존 6파일 외 변경·삭제 없음, 신규 3파일만 확인했다. baseline·원본·진단 및 제공본 보고서는 Git 제외된 `.local-data/project-agent-work/evaluation-preparation-modes-20261019/`에 보존한다.
- 문서: WORKBOARD의 로컬 링크 87개 존재 확인. 사용자 기존 파일·학습 문서·예약·환경 설정은 변경하지 않았다.

## 사용 경로와 남은 검증

1. 기존 로그인 화면에서 구성 관리의 생성형 평가 → `새 생성형 평가 준비`를 연다.
2. `저장 자료 재사용`에서 기존 평가 자료 ID를 입력하고 `평가 자료 불러오기`를 누른다.
3. 사례별 `정상 답변`/`근거 부족` 표시와 문자열 규칙을 확인·입력한다. 기존 자료 재사용에는 새 작성 영역의 구성·지식 공간 선택이 필요하지 않다.
4. 비교 후보·생성형 승격 기준·K·반복을 확인한다. 실제 실행은 이번 검증에 포함하지 않았다.

로그인 후 실제 화면 조작, 실제 평가 제출·모델 품질, 문제 이력 DB 반영, commit/push는 미실행이다. 다음 후보는 기존 자료 재사용 화면의 본래 로그인 환경 수용 확인이며, 실제 재제출·모델 호출은 별도 승인 경계로 유지한다. 기존 RAG P0 및 후속 개발 순서는 바꾸지 않는다.
