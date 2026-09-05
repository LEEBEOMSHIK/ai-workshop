# RAG OpenAI Deployment 구현 검증

- 날짜: 2026-09-05
- 범위: 다중 환경 LLM Deployment, 데이터 전송 정책, OpenAI Responses adapter,
  관리자 설정과 사용자 실행 고지
- 설계: `docs/superpowers/specs/2026-09-05-multi-environment-llm-deployment-design.md`
- 구현 계획: `docs/superpowers/plans/2026-09-05-rag-llm-deployments-openai.md`

## 검증한 계약

- LLM Model Definition과 실행 위치·Provider·정확한 모델 ID를 가진 불변 Deployment
  Version을 분리했다.
- Generation Profile은 정확한 Deployment Version 하나에 연결되며, Deployment나 LLM만
  바꿔도 검색 색인을 다시 만들지 않는다.
- Installation 정책은 회사 기본이고 Workspace 정책은 같거나 더 강하게만 변경할 수 있다.
- 외부 Deployment 저장에는 exact 구성·Deployment·Installation policy·Workspace policy와
  disclosure version에 대한 관리자 승인이 필요하다.
- 검색 실행은 현재 정책을 다시 읽고 외부 전송이 금지되면 runtime 생성과 Provider 호출 전에
  중단한다. 정책 writer와의 행 잠금 경합에서도 정책 강화 commit 뒤의 요청은 차단된다.
- 허용된 경우 저장 구성의 exact Deployment만 한 번 해석하며, Provider 실패를 다른 모델이나
  추출 답변으로 조용히 우회하지 않는다.
- 공개 `GenerationExecutionResponse`는 Provider, 사용자용 모델명·버전, Deployment 표시명,
  실행 위치, 외부 전송 여부와 disclosure만 포함한다. endpoint/secret reference,
  Deployment 내부 ID와 Provider 원시 모델 ID는 포함하지 않는다.
- 감사 테이블은 ID·version·Provider·정책 판정·Evidence ID·토큰·지연·안전 오류 코드와
  correlation ID만 저장한다. 질문, 이전 대화, 문서 본문, 생성 초안, Provider body,
  endpoint와 secret 열은 없다.
- 일반 사용자 저장 구성 응답은 서버가 exact 구성→Profile→Deployment→Model 연결로 계산한
  7개 안전 실행 필드만 포함한다. 기술 Deployment 옵션은 owner-only이며 검색 화면은 기술
  Profile/Deployment 카탈로그를 조회하지 않는다.

## TDD와 집중 검증 결과

다음 백엔드 명령은 모두 저장소의 `backend/`에서 실행했다.

첫 OpenAPI 실행에서 의도한 실패를 확인했다.

```powershell
.\.venv\Scripts\pytest.exe tests\contract\test_openapi.py -q
2 failed, 4 passed
```

실패 원인은 새 Deployment·정책 API 8개가 전체 경로 계약에 누락된 것과,
`AnswerPolicyVersionResponse.mode`가 `extractive | generative`로 확장됐는데 이전 테스트가
`extractive` 상수만 기대한 것이었다. 경로와 mode enum을 현재 계약에 맞추고 공개 생성 실행의
정확 필드 집합을 추가한 뒤 다음 결과를 확인했다.

```powershell
$task11OpenapiGreen = Join-Path $env:TEMP "ai-workshop-task11-openapi-green"
.\.venv\Scripts\pytest.exe tests\contract\test_openapi.py -q --basetemp $task11OpenapiGreen
7 passed

$task11Contract = Join-Path $env:TEMP "ai-workshop-task11-contract"
.\.venv\Scripts\pytest.exe tests\contract -q --basetemp $task11Contract
12 passed
```

정책 흐름 검증은 루트 `.env`를 프로세스에만 로드하고 격리 PostgreSQL database와 mock
Generation runtime을 사용했다. 외부 네트워크 요청은 없다.

```powershell
$task11PolicyFlow = Join-Path $env:TEMP "ai-workshop-task11-policy-flow-env"
.\.venv\Scripts\python.exe -m dotenv -f ..\.env run -- .\.venv\Scripts\pytest.exe tests\integration\labs\rag\generation\test_openai_policy_flow.py -q --basetemp $task11PolicyFlow
1 passed
```

이 시나리오는 current exact approval에서 contextualization 1회와 generation 1회, 근거 부족
시 generation 추가 호출 0회, 감사 저장 실패 시 사용자 본문 비노출, Workspace 정책을 `deny`로
강화하는 동시 요청에서 추가 runtime·Provider 호출 0회와 metadata-only 감사 snapshot을 함께
검증한다.

Migration `0016_rag_llm_deployments`는 fresh upgrade, 0015에서의 upgrade, legacy 참조 보존,
제약과 안전 downgrade를 격리 database에서 검증했다.

```powershell
$task11Migration = Join-Path $env:TEMP "ai-workshop-task11-migration"
.\.venv\Scripts\python.exe -m dotenv -f ..\.env run -- .\.venv\Scripts\pytest.exe tests\integration\test_migration_0016_rag_llm_deployments.py -q --basetemp $task11Migration
16 passed
```

변경 테스트 파일에 대한 Ruff도 통과했다.

```powershell
.\.venv\Scripts\ruff.exe check tests\contract\test_openapi.py tests\integration\labs\rag\generation\test_openai_policy_flow.py tests\integration\labs\rag\search\test_search_api.py
All checks passed
```

`git diff --check`는 exit code 0이었다. credential 검사는 일치 값 자체를 출력하지 않는
검사기로 실행했다. 구현 계획의 정확한 두 패턴 `sk-[A-Za-z0-9_-]+`와
`Bearer\s+[A-Za-z0-9_-]{12,}`를 Git 반영 후보에 적용하되, 사용자 참고 자산인
`references`, Git metadata와 명시적으로 staging에서 제외한 pytest 산출물은 검사 대상에서
제외했다.

정확 패턴은 `task-`, `desk-` 같은 일반 단어의 끝부분과 패턴 자체를 설명하는 문서까지 잡아
45개 일치·43개 후보 줄을 반환했다. 경계와 현실적인 길이를 추가한 2차 검사는 이 패턴을
설명하는 현재 worklog 한 줄과
`backend/tests/unit/labs/rag/generation/test_openai_responses.py:323`, `:791`의
`Bearer synthetic-secret` 합성 fixture 두 줄, 총 3개 줄을 반환했다. 후보는 모두 일반 문자열,
패턴 설명 또는 합성 테스트 값이었고 실제 credential은 없었다. 이 검사는 위 두 형태에 대한
staging 후보 검사이며 다른 credential 형식 전체를 검증했다는 의미는 아니다.

### Privacy review 수정 검증

RED에서 저장 구성 safe preview 스키마가 없고 일반 회원의 기술 Deployment 옵션 요청이
`200`이던 두 실패를 확인했다. 서버 exact join과 7개 필드 DTO, owner-only catalog, 검색 화면의
catalog fetch 제거 후 다음을 확인했다.

```text
backend focused unit/OpenAPI/deployment: 44 passed, 1 pre-existing warning
isolated PostgreSQL exact-preview API integration: 1 passed, 1 pre-existing warning
configuration API regression including that PostgreSQL case: 6 passed, 1 pre-existing warning
frontend Search/ConfigurationStudio/Comparison: 53 passed
backend mypy src: passed
scoped Ruff: passed
frontend typecheck: passed
```

검증 과정의 첫 환경 wrapper는 command quoting 실패로 로컬 DB 연결 설정을 도구 출력에 한 번
표시했다. 값은 source, docs, tests 또는 Git에 저장되지 않았고 외부 노출 증거는 없다. 공유 또는
재사용 credential이었다면 회전해야 하며, 폐기 가능한 local-only 값이면 별도 외부 노출 증거는
확인되지 않았다. 이후 DB 검증은 값을 출력하지 않는 dotenv runner만 사용했다.

### 저장 구성 생성 준비 상태 결함 수정

추가 통합 점검에서 `RagConfigurationService.readiness()`가 주입된 기술 readiness를 호출하지
않아 모든 생성형 구성이 `answer_ready=false`였던 결함을 재현했다. RED는 로컬 기술 준비 완료,
외부 current exact 승인, 정책 거절 사유 세 계약에서 `3 failed, 25 passed`였다.

검색 실행과 구성 준비 상태가 같은 exact 승인 비교 함수를 사용하도록 정책 도메인 계약을
공유했다. 로컬 준비 완료와 외부 current exact 승인에는 `answer_ready=true`, stale 승인에는
`deployment_not_ready`, Installation 거절에는 `provider_not_allowed`, Workspace 거절에는
`workspace_external_transfer_denied`를 반환한다. 기술 준비 확인과 정책·승인 조회만 수행하며
Provider runtime 생성 또는 호출은 없다.

```text
backend configuration + generation policy gate: 39 passed
frontend SearchPage submit regression: 19 passed
backend Ruff: passed
backend mypy src: passed, 166 source files
frontend typecheck, ESLint, OpenAPI check: passed
```

독립 리뷰에서 실제 추출형 구성이 생성 모델 부재 사유로 잘못 막히는 문제도 확인했다.
`generation_profile_id=null`, `answer_policy.mode=extractive`이고 검색 색인이 준비된 구성은
생성 모델이 필요 없으므로 `answer_ready=true`, `service_ready=true`, `answer_reasons=[]`,
`generation_execution_preview=null`이다. RED `1 failed, 28 passed`를 확인한 뒤 생성형 분기를
변경하지 않고 추출형 readiness만 수정했으며, 위 backend 39건과 명시적 frontend 제출 회귀
19건이 통과했다.

## 최종 통합 게이트

모든 구현 및 독립 리뷰 수정 후 다음 결과를 새로 확인했다.

```text
backend unit: 636 passed, 1 dependency deprecation warning
backend contract + RAG integration + e2e: 175 passed, 6 skipped, 1 pytest import warning
migration 0016 isolated PostgreSQL: 16 passed, 1 pytest import warning
backend Ruff: passed
backend mypy src: passed, 166 source files
frontend Vitest: 43 files, 198 passed
frontend typecheck: passed
frontend ESLint: passed
frontend Next.js production build: 11 routes built
frontend OpenAPI generated contract check: passed
project-agent repository validation: passed
git diff --check: passed (Windows LF/CRLF notices only)
```

통합·migration 검증은 실행마다 임시 PostgreSQL database를 생성하고 `0016`까지 올린 뒤 해당
임시 database만 제거했다. 저장소의 기존 개발 DB 데이터와 보호된 pytest 경로는 변경하지
않았다. 단위 테스트는 구성 기본값을 검증하므로 루트 `.env`를 주입하지 않고 실행했다.

## 실제 OpenAI smoke 조건

실제 또는 과금 가능한 OpenAI API는 호출하지 않았다. 자동 검증은 mock transport와 합성
메타데이터만 사용했다. 실제 smoke는 owner가 다음을 모두 명시적으로 준비·승인한 경우에만
수행한다.

1. 승인된 secret source와 endpoint reference
2. 현재 환경에서 허용된 exact OpenAI Responses Deployment Version과 정상 health
3. 외부 전송을 허용한 Installation policy와 더 완화되지 않은 Workspace policy
4. exact Deployment에 연결된 Generation Profile과 현재 policy snapshot에 대한 저장 구성 승인
5. 비민감 합성 문서와 질문

브라우저에서는 제출 전 disclosure, bounded 후속질문, exact 실행 모델, 생성 답변의 문장별
인용, 원문 이동, 응답 execution snapshot을 확인한다. DB에서는 metadata-only audit만 확인하며
API key, 질문·문서·prompt와 Provider request/response를 출력하거나 캡처하지 않는다.

## 발견 사항과 후속 조치

- 공개 OpenAPI 전체 경로 집합이 새 관리자 기능을 따라가지 못한 문제를 수정했다.
- 추출형 전용이던 답변 정책 테스트가 생성형 mode 확장을 반영하지 못한 문제를 수정했다.
- 정책·runtime·감사 통합 시나리오를 generation 전용 테스트 경로로 분리해 최종 gate에서 직접
  선택할 수 있게 했다.
- 첫 OpenAPI RED 실행에 repository 내부 basetemp를 잘못 지정해
  `.pytest-task11-openapi-red/`에 생성 OpenAPI JSON 1개, 195,267 bytes가 남았다. 애플리케이션
  데이터가 아닌 삭제 후보지만 `CACHE_POLICY.md`에 따라 사용자 명시 승인 전에는 제거하지
  않는다. 이후 검증은 `%TEMP%` 절대 경로만 사용했다.
- `backend/.pytest-nextjs-final-contract/`, `.local-data`, `references/`와 Docker 데이터는
  조사하거나 변경하지 않았다.
- 다음 기능 작업은 개발 전용 Codex SDK adapter다. 기존 OpenAI Responses adapter와 동일한
  Deployment·정책·승인·감사 경계를 따르는 별도 설계와 TDD가 필요하다.
