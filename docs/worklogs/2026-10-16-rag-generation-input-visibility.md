# 최종 생성 입력 확인 (2026-10-16)

## 목적과 범위

사용자가 답변 품질을 더 조정하기 전에 LLM에 전달되는 근거·지침을 확인할 수 있도록
기존 검색 근거·유사도 패널을 확장한다. 선택/표 알고리즘·모델·프롬프트 내용은 바꾸지 않는다.
설계 계약은 [ADR-0038](../decisions/0038-request-local-generation-input-inspection.md)이다.
기존 WORKBOARD의 RAG P0 마감과 학습 문서/예약은 유지한다.

초기 Git 상태 170항목과 기존 1964파일 SHA를
`.local-data/project-agent-work/rag-input-visibility-20261016/`에 보존했다.
별도 브랜치·worktree·계정·DB를 만들지 않았다. 저장소 `.agents/skills`에는 SKILL.md가 없었다.
프로젝트 역할 지침과 bounded brainstorming/verification 스킬을 참고했다.

## 구현

- 진단 요청만 요청 수명에 묶인 포착기를 활성화한다. local OpenAI-compatible 어댑터의
  최종 Ollama 지침·응답 스키마 적용 뒤 messages/허용 옵션을 포착한다.
- 사용자용 모델명·버전, prompt reference·profile version, 근거 예산·출력 토큰 한도,
  표시 JSON 크기·SHA를 제공한다. 원시 Provider 모델 ID·headers·주소·secret은 제외한다.
  따라서 SHA는 허용 필드 정규 JSON의 해시이며 전체 네트워크 패킷 증거가 아니다.
- HTTP 응답 수신/준비 상태를 구분한다. 실제 모델 내부의 입력 잘림·해석 여부는 unknown이다.
  진단 한도 131072자를 넘으면 원문 전체를 생략한다. 실제 요청 내용을 잘라내지 않는다.
- 기존 최종 검색 ACL 검증 뒤에만 응답하며, 대화 저장에서는 추가 입력 필드를 제외한다.
  즉시 응답의 완료·비가림 turn에만 결합하며 과거/새로고침/replay에는 복원하지 않는다.
- UI는 최종 user JSON의 질문·검색 질문·근거 원문·인용 ID를 읽고 기존 선택/제외 사유 표와
  대조하게 한다. 기존 후보의 ‘전달’ 표기를 ‘선택’으로 바로잡는다.
- 제공되지 않은 캡처를 선택 근거로 재구성하거나 실제 전송으로 주장하지 않는다.
  미지원 provider·생성 미실행·실패로 결과가 없는 경우에는 입력 확인이 불가능하다.

## 사용 위치와 한계

업데이트된 앱에서 RAG 대화 결과의 **검색 근거·유사도 → LLM 입력 확인**을 펼친다.
선택 근거 표와 인용 ID를 대조하고 **최종 지침과 메시지**, **전송 입력 JSON (허용 필드)**를
확인한다. 기본 대화 요청은 기존처럼 include_diagnostics=true다.

이번 작업은 코드와 오프라인 검증이다. 실행 중인 서버를 재시작하지 않았으므로 현재 서버에
반영됐다고 주장하지 않는다. 실제 생성/임베딩·브라우저 E2E·원래 DB/ES 수용은 미실행이다.
실제 모델 입력을 새로 얻기 위한 호출은 이 작업에서 하지 않았다. 과거 저장 입력은 합성
fixture의 무손실 직렬화 검사로만 재사용했다. 실제 모델의 답변 품질은 개선/검증하지 않았다.

## 검증 진행 기록

- 생성 포착 모듈 부재로 RED 수집 실패 확인 후 구현.
- 생성 포착·저장 합성 표본·v3/v4·기존 HTTP 그룹/출처/업체 교체 동기 회귀: 75통과.
- 대화 저장 제외/완료·비가림·동일 turn overlay 동기 검사: 2통과.
- 백엔드 변경 제품6파일 scoped strict Mypy 통과, 제품/테스트8파일 Ruff 통과.
- OpenAPI export와 TypeScript schema 생성 통과. 기존 Conda 활성화 명령을 사용했다.
- UI 초기14검사·targeted ESLint 통과. 최종 경합 회귀·통합 결과는 아래 마감 기록으로 보완한다.
- 서비스 async 검사2개는 기존 Windows 이벤트 루프 생성 정체로 중단했다. 통과로 집계하지 않는다.
- 첫 pnpm 호출은 corepack registry DNS 오류로 실패했고 설치는 없었다. 설치된 Node CLI로 진행했다.
  첫 API 타입 생성은 Conda 미활성 검사에서 거절됐으며 정식 활성화 후 통과했다.
  Vitest 기본 sandbox temp rename EPERM은 process-local TEMP/TMP를 허용된 Windows Temp로 지정해
  해결했다. 권한·정책 설정은 변경하지 않았다.

## 독립 검토

독립 리뷰가 첫 질문의 completed GET이 POST보다 먼저 반환될 때 요청 입력이 사라지는 경합을
발견했다. 기존 취소/복구 상태는 유지하고 동일한 완료 응답에만 transient 입력을 병합하는
국소 수정과 회귀를 완료했다. 일반 사용자에게 raw Provider model ID가 노출될 수 있는 초기
설계는 구현 중 제거했고 사용자 표시명과 허용 필드 스냅샷만 제공하도록 수정했다.

## 다음 후보

업데이트된 본래 환경에서 사용자가 새로 허용한 질문의 입력 확인 화면을 확인한 뒤, 필요한
일반 규칙·조건·예시가 입력에 남는지 검토한다. 이 확인 전 모델 변경·파인튜닝으로 넘어가지
않는다. 기존 실제 운영 RAG P0 미완료를 이 UI 검증으로 완료 처리하지 않는다.


## 최종 검증과 인계

- 최종 backend 관련 동기 회귀 **81통과 / 서비스 async2제외** (3.97초).
  입력 캡처/저장/권한 핵심14개가 포함된다. 실제 `_view`를 즉시 완료 mock으로 실행해
  이전 turn 권한 철회에 따른 후속 turn 가림과 입력 복구 차단을 검증했다.
- 최종 frontend 기존 대화/세션 포함6 suite **68통과** (45.02초), 메인 재검사 변경 UI4 suite **22통과** (13.39초): 입력 표시, 기존 진단 패널, 안전 병합,
  실제 ConversationPage의 GET 선행/화면 이탈 경합. 전체 TypeScript 검사 exit0.
- 변경 backend 제품6파일 scoped strict Mypy 통과, 제품/테스트8파일 Ruff 통과.
  프론트 변경7파일 ESLint 통과. OpenAPI 재생성 통과.
- 독립 리뷰: backend14통과/async2제외, UI26통과 및 실제 Page 경합2통과.
  발견한 GET/POST 입력 유실과 observation_complete의 비영속 차이로 인한 병합 거절을
  수정·재검증했다. 미해결 차단 결함 없음. async/본래 환경 수용 미검증은 유지한다.
- 최초1964파일 중 이번 변경10파일 외 **1954파일 SHA 동일**, 삭제0.
  Page의 추가 import/병합 코드만 제외하면 변경 전 SHA와 일치함을 UI 담당이 확인했다.
  최종 변경 명세와 보존 해시는 작업 전용 `final-preservation.json`에 기록한다.
- 실제 생성/임베딩/유료 호출0, 서버 재시작0, DB/ES 데이터 변경0, 설치0, commit/push0.
  mock HTTP 경계에서 포착 값과 실제 어댑터 요청 messages/schema가 일치함을 증명했으며,
  새 실제 전송·모델 내부 입력·정답 품질은 증명하지 않는다.

### 변경 파일

- Backend 제품: `generation/input_inspection.py`, `generation/openai_compatible.py`,
  `search/diagnostics.py`, `search/pipeline.py`, `search/schemas.py`, `conversations/service.py`
  (모두 `backend/src/ai_workshop/labs/rag/` 아래).
- Backend 테스트: `backend/tests/unit/labs/rag/generation/test_input_inspection.py`,
  `backend/tests/unit/labs/rag/conversations/test_input_inspection.py`.
- Frontend: `GenerationInputInspection.tsx`, `GenerationInputInspection.test.tsx`,
  `SearchDiagnostics.tsx`, `ConversationPage.tsx`, `merge-generation-input.ts`,
  `merge-generation-input.test.ts`, `ConversationInputRecovery.test.tsx`
  (모두 `frontend/src/features/rag/conversation/` 아래), `frontend/src/shared/api/schema.d.ts`.
- 문서: `WORKBOARD.md`, `docs/labs/rag/design.md`, ADR-0038, 이 기록.

### 알려진 한계

local OpenAI-compatible 생성 경로만 포착한다. 다른 provider·기존 기록·생성 미실행은
명시적 확인 불가 상태다. 실패로 검색 결과 자체가 반환되지 않으면 준비 입력도 UI에
전달되지 않는다. 새로고침·세션 재조회·재생 후에는 요청 전용 원문 캡처가 없다.
선행 GET과 POST의 실제 내용이 다르면 캡처 병합을 거절한다. 이는 권한/내용 변경을
무시하면서 오래된 본문을 재노출하지 않기 위한 제한이다.

## 실환경 사전 점검 (2026-10-16)

사용자가 백엔드 재기동과 기존 합성 질문의 로컬 생성 1회·재시도0을 승인한 후,
2026-10-16 18:02 UTC에 다음 선행 조건을 확인했다. 로그인 또는 추가 권한이 필요하면
멈추라는 실행 범위를 적용했다.

- 기본 도구 환경의 CIM/로컬 소켓 접근은 거부됐다. 허용된 도구 권한 심사 후 읽기 전용
  조회에서 18000 listener의 PID27812와 `backend/.conda/python.exe` 직접 Uvicorn 실행,
  기존 Selector loop 옵션을 확인했다. `/api/v1/health`는 `status: ok`였다.
- 설치된 Playwright와 Edge의 임시 로그인 없는 context로
  `/workshop/rag/domains/asset-management/chat`에 접근하자 `/login?next=...`로 이동했다.
  실제 화면에는 빈 이메일·비밀번호 로그인 폼이 나타났다. 이 결과는 검증 브라우저에
  로그인 세션이 없다는 증거이며 사용자의 다른 브라우저 로그인 상태를 판단하지 않는다.
- 로그인 중단 조건에 따라 재기동0·임베딩0·생성0을 유지했다. 새 실제 모델 입력·답변·
  입력 검사 패널은 확보하지 못했다. 과거 결과나 mock 화면을 새 실행 결과로 대체하지 않았다.
- 로그인 제출·자격/쿠키 추출·보호 설정 변경·DB/ES/Docker 조작·모델 변경·설치·commit/push0.
  실제 로그인 화면만 Windows Temp의 `ai-workshop-input-inspection-preflight.png`에 보존했다.
- 독립 검토에서도 인증된 세션 선행, 첫 질문의 빈 history, 활성 deployment의
  `max_retries=0` 확인이 필요함을 확인했다. 재개 시 승인된 브라우저 로그인 연결이 필요하며,
  현재 배포 설정과 단일 호출 한도 확인 전 생성 요청을 보내지 않는다.

이번 점검은 기능 E2E 통과나 답변 품질 검증이 아니다. 기존 제품 코드와 우선순위를 유지하며
WORKBOARD와 이 기록만 갱신했다.
