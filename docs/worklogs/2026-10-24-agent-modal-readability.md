# 단계 모달의 핵심 정보 우선 표시

- 날짜: 2026-10-24
- 관련 문제: ISSUE-00035
- 사용자 피드백: 구성한 사람도 무엇을 설명하는지, 어떤 내용이 중요하고 부수 정보인지 구분하기 어렵다.
- 설계: [핵심 정보·상세 분리](../superpowers/specs/2026-10-24-agent-modal-readability-design.md)
- 계획: [역할·범위·검증](../superpowers/plans/2026-10-24-agent-modal-readability.md)

## 확인한 원인

이전 모달은 지침 전문·중복 질문·상태값·원시 근거 ID를 비슷한 시각적 비중으로 펼쳐 놓았다. 실제 manager 기본 모달의 보이는 텍스트는1,244자였으며 질문과 결과를 찾으려면 이 정보를 함께 읽어야 했다. 모델 호출에서는 system 지침과 도구 schema까지 요청 내용 앞에 나타났다.

모델의 반환이 항상 답변은 아니다. 기존 manager 모델은 도구 이름과 작업 인자를 반환한다. 단계 공통 evidence_refs는 권한 manifest이며 실제 전달 개수로 해석할 수 없다. available_evidence_count도 사용 가능한 후보 개수다. 표시 축약 과정에서 이 의미를 바꾸지 않는다.

## 적용한 구조

첫 화면은 실제 관계에서 확인한 역할 한 줄, `받은 요청`, `반환한 결과`를 우선한다. 질문과 답변 본문을 나란히 비교하고 작은 화면은 세로로 표시한다. 지침, 함께 전달된 자료, 원문·기술 기록은 목적별로 펼쳐 본다. 기본 미리보기는 최대3항목·각600자로 제한하고 일부 표시임과 전체 원문 경로를 안내한다.

원래 질문, 재작성 검색 질의, 위임 작업을 구분한다. 현재 요청은 루트 필드 또는 마지막 user 메시지에서 읽으며 과거 이력·근거 안의 질문을 현재 질문으로 승격하지 않는다. 도구 반환은 도구 요청/호출 도구/요청한 작업으로 표시한다. `insufficient_evidence`와 빈 claims,0·false·null·빈 문자열도 의미를 보존한다. 불완전한 claims/도구 인자에는 부분 표시 안내를 남긴다.

별도 지침 필드가 해당 없음이고 실제 HTTP messages에 system/developer 지침이 있으면 실제 HTTP 지침을 먼저 보여준다. 해당 없음 필드 자체는 기술 기록에 보존한다. 지침의 임의 요약·번역과 LLM 호출은 없다. 대화 이력에는 화자를 유지하고, 사용 가능 근거 수와 입력에 기록된 근거 수를 구분한다.

본문 표시 허용과 content_status를 확인한 다음 추출한다. 미보관·미수집·검증 실패 본문은 요약이나 접힌 상세 DOM에도 넣지 않는다. complete이지만 text가 null/누락인 경우와 JSON 문자열 `null`을 구분해 빈 카드 대신 안내한다. 정확한 전체 원문·SHA·토큰·출처 링크와 기존 모달 포커스 계약은 유지한다.

## 검증

최종 독립 검증은 실행+대화 진단13파일 **127개 통과**, 전체 TypeScript exit0, 변경 TS/TSX9파일 ESLint exit0이다. 독립 경계5개는 이127개에 포함된다. 부분 주장/알 수 없는 도구 인자 안내, 화자, 본문 접근 차단 전 미열람, 긴 입력 미리보기와 정확한 원문, 접근 회수 시 DOM 제거를 확인했다.

구현 담당 관련45개와 호출부45개도 위 최종 합계에 포함되므로 중복 합산하지 않는다. 호출부의 변경 전29실패/16통과는 접힌 기술 상세의 새 접근 경로에 대한 실패였고, 기존 데이터·비노출 assertions를 유지한 채 이관 후45개를 통과했다. 초기 타입 검사에서 기존 TypeScript lib가 지원하지 않는 findLast2곳을 발견해 역순 탐색으로 바꿨고 컴파일러 타깃 변경 없이 통과했다.

- `pnpm exec vitest run src/features/rag/executions src/features/rag/conversation/SearchDiagnostics.test.tsx --reporter=dot`:127개 통과.
- `pnpm exec tsc --noEmit --pretty false --incremental false`:exit0.
- 변경 TS/TSX9파일 `pnpm exec eslint ... --max-warnings 0`:exit0.

본래 로그인된5173의 기존 완료 실행을 읽기 전용으로 확인했다. 새 모델 실행 없이 manager, 도구 요청 모델, 위임, 답변 담당, 답변 모델5개 단계의 의미가 구분됨을 확인했다.

- 같은 manager 기본 화면의 보이는 텍스트1,244→317자. 긴 영어 지침·UUID·반복 질문을 펼쳐 보는 상세로 이동했다.
- CSS1280px에서는 질문/결과가 나란히 표시된다.320·375px에서는 세로 배치이며 내부 가로 넘침0.320px 모달 폭304·높이784px, 닫기44px·펼침 컨트롤 약50.4px다.
- Shift+Tab/Tab은 모달의 닫기와 마지막 펼침 사이를 순환한다. Escape로 닫은 뒤 원래 manager 노드로 포커스가 돌아온다.
- 모델의 실제 system 지침을 펼쳐 확인하고 해당 없음 카드가 먼저 나오지 않는 것을 확인했다. 전체 HTTP 요청 원문1,194자에서 system/user 역할과 required 도구 선택이 보존됨을 확인했다.
- CDP 클릭1회가 시간 초과를 반환했지만 실제 manager 모달은 이미 열려 있었다. 상태를 확인하고 중복 클릭하지 않았다. 제품 실패로 판정하지 않았다.
- 브라우저의 기존 배율을 보존했고 viewport override는 해제했다. 실제 터치 장치 검증은 수행하지 않았다.

증거는 Git 제외된 `.local-data/project-agent-work/modal-readability-20261024/`와 `.local-data/browser-verification/modal-readability-20261024/`에 보관한다. `before-agent.png`, `after-agent.png`, `after-model-tool-request.png`, `browser-results.json`은 실제 화면 비교 자료다.

## 보존 범위

시작 시 기존174개 변경 파일의 SHA를 `.local-data/project-agent-work/modal-readability-20261024/baseline-sha256.json`에 저장했다. 종료 독립 비교는167개 동일·허용7개 변경(모달3·기존 호출부 테스트3·WORKBOARD)·누락0이다. Mermaid 조작, 저장/API/모델/검색·권한 계약은 유지했다. 신규 생성·임베딩·설치·서비스 재시작·프로파일 변경·commit/push는0이다. 기존 RAG 품질 실패 및 멀티턴 후속 범위도 유지한다.

## 문제 이력 연결

인증된 기존 문제 관리 UI에서 ISSUE-00035의 증상·해결 내용·검증 결과에 이번 후속 작업을 누적하고 진행 이력 저장 완료를 확인했다. 이 문서를 `단계 모달 핵심 정보·상세 분리 검증 (2026-10-24)`으로 등록해 문서 `fd5ecbfb-19d5-42b2-9d56-1823296fb8e5` 버전1을 연결했다. UI의 연결 링크에서 정확한 문서·버전을 확인했다. 기존 기록과 후속 범위를 보존하며 전체 이슈 상태는 OPEN을 유지한다.
