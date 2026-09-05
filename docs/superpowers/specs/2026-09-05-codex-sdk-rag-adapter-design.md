# 개발 전용 Codex SDK RAG Adapter 설계

- 상태: 사용자 승인 완료
- 작성일: 2026-09-05
- 범위: RAG 생성 런타임의 개발 전용 Python Codex SDK Provider
- 선행 설계:
  `2026-09-05-multi-environment-llm-deployment-design.md`

## 1. 배경

RAG 생성 런타임은 `local_openai_compatible`과 `openai_responses` Provider를
지원하고, 저장 구성은 불변 Generation Profile을 통해 정확한 Model Deployment
Version 하나를 선택한다. OpenAI Responses 첫 구현과 외부 전송 정책·승인·감사
계약은 완료됐다.

개발 환경에서는 별도 API key를 애플리케이션에 저장하지 않고 현재 개발 머신에
로그인된 Codex를 RAG 생성 모델로 선택해 비교할 필요가 있다. Codex SDK 프로세스와
pinned CLI runtime은 로컬에서 실행되지만 기본 Codex 모델 추론에는 질문, 제한된 이전
대화와 선별 근거가 OpenAI로 전송된다. 그러므로 이 Provider를 로컬 LLM으로 표시하면
안 되며 기존 외부 전송 정책을 그대로 통과해야 한다.

공식 Python SDK는 `AsyncCodex`, ephemeral thread, 정확한 모델 선택, JSON Schema
`output_schema`, 읽기 전용 sandbox와 승인 거부 모드를 제공한다. 배포 패키지는
pinned Codex CLI runtime을 포함하고 기존 Codex 인증을 재사용한다.

- <https://developers.openai.com/codex/sdk/>
- <https://github.com/openai/codex/blob/main/sdk/python/docs/api-reference.md>

## 2. 결정

`codex_sdk` Provider를 실제 adapter와 함께 추가한다. 각 `contextualize()`와
`generate()` 호출은 서로 상태를 공유하지 않는 새 ephemeral Codex thread에서
수행한다. 장기 thread, 공유 App Server session과 요청마다 직접 조립한 `codex exec`
명령은 사용하지 않는다.

이 Provider는 다음 계약을 동시에 만족해야 한다.

- `development_only=true`
- 허용 환경은 `development` 하나뿐이다.
- 모델 추론 위치와 데이터 전송 위치는 `external`이다.
- `external_transfer=true`이며 기존 Installation·Workspace 정책과 관리자 승인을
  적용한다.
- HTTP endpoint와 애플리케이션 소유 secret reference를 요구하지 않는다.
- 현재 OS 사용자에게 저장된 Codex 인증을 SDK가 직접 재사용한다.
- 실제 선택 모델은 Deployment Version의 `provider_model_id`와 정확히 일치한다.
- 다른 Provider나 모델로 자동 fallback하지 않는다.

## 3. 목표와 비목표

### 목표

- 현재 `GenerationRuntimePort` 뒤에 Codex SDK adapter를 추가한다.
- 질문 문맥화와 최종 생성 호출을 사용자·요청·단계 사이에서 격리한다.
- RAG가 고른 bounded history와 Evidence 이외의 로컬 정보를 제공하지 않는다.
- 기존 구조화 출력과 인용 hard gate를 그대로 사용한다.
- 인증, 모델, 격리 설정과 환경 제한을 readiness에서 fail closed로 검증한다.
- 관리자가 개발 전용 성격과 외부 전송 사실을 정확히 인지하고 모델을 선택하게 한다.
- 프론트엔드가 지원 Provider와 입력 요구사항을 중복 하드코딩하지 않게 한다.

### 비목표

- Claude, Gemini, Azure OpenAI, Bedrock 또는 가짜 Provider 선택지를 추가하지 않는다.
- Codex를 staging·production Provider로 사용하지 않는다.
- Codex browser/device/API-key 로그인을 애플리케이션 UI에서 구현하지 않는다.
- 인증 파일이나 token을 애플리케이션 DB, 환경 설정 또는 secret table로 복사하지 않는다.
- Codex thread를 애플리케이션 대화 기록의 정본으로 사용하지 않는다.
- Codex에 파일·shell·웹 검색·MCP·plugin·skill·하위 agent 도구를 제공하지 않는다.
- `--oss` 기반 Ollama·LM Studio 로컬 추론을 이 adapter에 포함하지 않는다.
- Provider routing, load balancing, 자동 failover 또는 비용 최적화 routing을 추가하지
  않는다.

## 4. 도메인과 저장 모델

### ProviderKind

`ProviderKind.CODEX_SDK = "codex_sdk"`를 추가한다. 실제 adapter, readiness와 관리자
표시가 같은 변경에 포함되므로 구현 없는 enum 값은 존재하지 않는다.

### ModelDeploymentVersion

현재 모든 Provider에 필요한 `endpoint_ref`를 `str | None`으로 바꾼다. DB column도
nullable로 변경한다. Provider별 연결 요구사항은 단일 Provider contract registry에서
검증한다.

| Provider | endpoint | secret | location | environment |
| --- | --- | --- | --- | --- |
| `local_openai_compatible` | 필수 | 선택 | local/on-premise | 기존 계약 |
| `openai_responses` | 필수 | 필수 | external | 기존 계약 |
| `codex_sdk` | 금지 | 금지 | external | development 전용 |

Codex Deployment Version은 다음을 추가로 강제한다.

- `allowed_environments == (development,)`
- `development_only is true`
- `external_transfer is true`
- 외부 전송 데이터 범주와 처리 안내 reference가 존재한다.
- `provider_model_id`가 비어 있지 않다.
- generation에 필요한 `structured_output`, `contextualization`, `token_accounting`
  capability가 존재한다.

기존 불변 Deployment Version은 수정하지 않는다. migration은 column nullability와 새
Provider 저장 가능성만 확장하며 기존 row 값을 변환하지 않는다.

### Provider contract registry

Provider별 조건을 domain, resolver, API와 UI에 각각 중복하지 않는다. backend의 한
registry가 다음 안전 메타데이터를 제공한다.

- Provider kind와 사용자 표시 이름
- 실제 구현 여부
- endpoint·secret 필요 여부
- 허용 실행 위치
- 허용 환경과 development-only 여부
- 인증 방식
- 외부 전송 기본 성격
- 관리자에게 표시할 안전한 설명

도메인 검증과 runtime factory 등록은 이 정본을 사용한다. 관리자 API는 registry의
안전 필드만 반환하고 프론트는 이를 기준으로 입력 필드와 안내를 렌더링한다.

## 5. Runtime 구성

### 공통 resolver 변경

현재 factory의 `(deployment, endpoint, secret)` positional 계약을 Provider별 선택 값을
담는 `ResolvedProviderConnection`으로 바꾼다. `endpoint`와 `secret`은 선택 값이며
registry가 필요 여부를 검증한다.

Codex factory는 endpoint와 secret이 있으면 준비 불가로 판정한다. 로컬과 OpenAI
Responses factory의 기존 동작은 유지한다.

### SDK 경계

업무 adapter가 외부 패키지 세부 타입에 직접 결합하지 않도록 작은
`CodexSdkClientPort`를 둔다. 실제 구현만 `openai_codex`를 import하며 단위 테스트는
in-memory fake를 사용한다. port는 다음 최소 책임만 가진다.

- 안전한 계정 로그인 상태 조회
- 현재 계정에서 사용 가능한 모델 목록 조회
- 격리된 단일 structured turn 실행
- timeout·취소 시 turn 중단과 client 종료
- SDK 결과의 final response, token usage, duration과 안전 오류 반환

SDK dependency는 Python 프로젝트와 lockfile에 정확한 stable version으로 고정한다.
SDK가 포함한 pinned CLI runtime을 기본 사용하고 개발 머신의 별도 `codex` 실행 경로를
자동 탐색하거나 우선하지 않는다.

## 6. 호출 단계별 격리

`contextualize()`와 `generate()`는 각각 다음 순서로 실행한다.

1. OS 임시 위치에 비어 있는 전용 디렉터리를 생성한다.
2. `AsyncCodex` context를 시작한다.
3. 로그인 상태와 exact model 가용성을 확인한다.
4. 새 thread를 `ephemeral=True`로 시작한다.
5. thread와 turn 모두 `Sandbox.read_only`를 지정한다.
6. `ApprovalMode.deny_all`을 지정한다.
7. 전용 빈 디렉터리를 `cwd`로 지정한다.
8. 단계별 최소 developer instructions와 입력 문자열만 전달한다.
9. Deployment의 exact model ID를 thread와 turn 모두에 지정한다.
10. 현재 RAG JSON Schema를 `output_schema`로 전달한다.
11. timeout 안에 결과를 수집하고 final response와 usage를 정규화한다.
12. client를 먼저 닫고 임시 디렉터리를 정리한다.

한 단계가 실패하거나 재시도돼도 기존 thread를 resume하지 않는다. retry마다 새 client,
새 ephemeral thread와 새 임시 디렉터리를 사용한다. thread ID는 애플리케이션 DB나 일반
로그에 저장하지 않는다.

## 7. 도구와 로컬 데이터 격리

Codex 입력에는 문자열 형태의 다음 데이터만 포함한다.

- 현재 질문
- 서버가 검증한 bounded 이전 대화
- 문맥화 단계의 출력 검색 질의
- 검색·권한·근거 선별을 통과한 Evidence ID와 최소 텍스트
- 구조화 응답 규칙과 인용 가능한 Evidence ID 집합

다음 입력 타입과 경로는 사용하지 않는다.

- `LocalImageInput`, `SkillInput`, `MentionInput`
- 프로젝트 저장소 경로
- Asset 원본 저장 경로
- 파싱 산출물이나 모델 cache 경로
- 사용자 홈과 Codex 설정 경로

thread config는 pinned SDK/runtime이 지원하는 정식 설정만 사용해 shell, web search,
MCP, plugin, apps, connectors, skills와 multi-agent 기능을 비활성화한다. 사용자 전역
설정이 기능을 다시 활성화하지 못하는지 실제 SDK contract test로 확인한다.

`read_only`와 빈 `cwd`만으로 도구 비활성화를 대체하지 않는다. pinned SDK/runtime에서
금지 기능 중 하나라도 확실하게 제거되지 않거나 승인 거부가 강제되지 않으면 health와
readiness는 `codex_isolation_not_enforced`로 실패하고 질문을 전송하지 않는다.

## 8. 인증과 모델 탐색

SDK의 기존 Codex 인증 자동 재사용만 허용한다. 애플리케이션은 login method를 호출하지
않고 다음 안전 상태만 관리자에게 반환한다.

- SDK/runtime 사용 가능 여부
- 로그인 여부
- 모델 목록 조회 가능 여부
- 마지막 확인 시각
- 안전한 실패 코드

계정 이메일, account ID, 인증 저장 위치, token과 원본 SDK 오류는 반환하거나 기록하지
않는다.

관리자 모델 선택지는 SDK `models()` 결과에서 생성한다. 선택한 ID를 Deployment Version의
`provider_model_id`에 그대로 고정하며 health와 실제 turn에서 다시 exact match를 검사한다.
저장된 모델이 현재 계정에서 사라지면 readiness는 false가 되고 임의 모델로 대체하지 않는다.
health는 계정과 모델 metadata만 확인하며 질문, 대화와 Evidence를 보내는 생성 요청을
수행하지 않는다.

이 인증은 개발 머신 운영자의 Codex 계정이며 애플리케이션 사용자 계정과 다르다. 관리자
화면은 로컬에서 로그인한 사용자들의 요청이 이 개발 계정 사용량을 소비한다는 사실을
안내한다.

## 9. 정책과 실행 흐름

Codex SDK는 외부 Provider로 취급한다. 실행 전 기존 순서를 유지한다.

```text
사용자·Workspace 권한
→ exact Saved Configuration·Deployment 해석
→ development 환경 제한
→ Installation·모든 Workspace 외부 전송 정책
→ exact 관리자 승인 snapshot
→ Hybrid 검색과 선택적 reranker
→ 최소 Evidence 선택
→ 단계별 격리 Codex 호출
→ 구조화 출력 검증
→ 인용 hard gate
→ 안전 감사 기록과 응답
```

하나라도 외부 전송을 금지하면 SDK client를 생성하지 않는다. 근거 부족, 잘못된 assistant
turn 서명과 구성 readiness 실패도 동일하게 Provider 호출 전에 종료한다.

Codex 실패 시 `openai_responses`, `local_openai_compatible` 또는 다른 Codex 모델로
fallback하지 않는다.

## 10. 구조화 출력과 답변 검증

문맥화와 생성은 기존 Provider와 동일한 schema를 사용한다. SDK `run(...,
output_schema=...)`의 `final_response`를 기존 parser에 전달하고 다음을 검증한다.

- JSON Schema 일치
- 최대 답변 길이와 답변 정책
- citation ID가 허용 Evidence 집합의 부분집합인지
- 모든 인용이 원문 위치로 추적 가능한지
- 근거가 부족할 때 추측 답변을 반환하지 않는지
- SDK가 실행 모델 정체성을 반환하는 버전에서는 Deployment의 exact model과 일치하는지

검증 전 초안은 사용자 응답이나 대화 history에 포함하지 않는다. 검증 실패는 생성 실패로
기록하며 추출형 답변으로 조용히 바꾸지 않는다.

SDK가 응답 모델 ID를 제공하지 않는 버전에서는 제공되지 않은 값을 추측하거나 응답 모델
검증을 성공으로 꾸미지 않는다. 이 경우 모델 목록 사전 검증과 thread·turn 양쪽의 exact model
지정을 실행 계약으로 삼고, 감사에는 실제 Provider 응답값이 아니라 선택된 Deployment 계약을
기록한다.

## 11. 오류와 재시도

Codex 전용 안전 오류 코드는 다음과 같다.

- `codex_sdk_unavailable`
- `codex_not_authenticated`
- `codex_model_unavailable`
- `codex_isolation_not_enforced`
- `codex_timeout`
- `codex_overloaded`
- `codex_response_missing`
- `codex_invalid_structured_output`
- `codex_citation_validation_failed`

공통 API에서는 기존 `GenerationProviderError` 계약으로 변환한다. SDK가 명시적으로
transient/overload로 분류한 오류만 Deployment Version의 `max_retries`와 backoff 범위에서
재시도한다. 인증, 모델 불일치, 격리 실패, schema와 citation 오류는 재시도하지 않는다.

원본 exception 문자열, subprocess command, 인증 경로와 입력 본문은 사용자 오류나 일반
로그에 포함하지 않는다. timeout과 취소 시 진행 중 turn을 interrupt하고 client 종료 후
임시 디렉터리를 정리한다.

## 12. 관리자 API와 UI

owner 전용 Provider metadata API는 실제 등록된 backend Provider만 반환한다. 각 항목에는
표시 이름, 연결 필드 요구사항, 개발 전용 여부, 외부 전송 여부와 안전 설명을 포함한다.

Codex 모델 목록 조회는 owner 전용이며 development 환경에서만 동작한다. staging과
production에서는 목록 조회, Deployment 생성, 저장 구성 선택과 실행을 모두 거부한다.

관리자 Deployment 화면은 다음처럼 동작한다.

- `Codex SDK · 개발 전용`을 실제 구현된 선택지로 표시한다.
- endpoint와 API key 입력란을 표시하지 않는다.
- 안전한 로그인 상태와 SDK model 목록을 표시한다.
- exact model 하나를 선택해야 새 Deployment Version을 만들 수 있다.
- `SDK 프로세스는 로컬에서 실행되지만 질문·대화·근거는 OpenAI로 전송됩니다.`를
  항상 표시한다.
- 현재 로컬 Codex 로그인 계정의 사용량을 소비한다는 사실을 표시한다.
- 로그인, 모델, 격리 contract 또는 외부 정책이 준비되지 않으면 선택·활성화를 차단한다.

일반 사용자는 기존 검색 화면의 authoritative execution 안내로 Provider, 모델명·버전과
외부 전송 사실을 확인한다. 내부 endpoint, 인증 상태와 SDK 진단은 노출하지 않는다. 공개
방문자에게 새 데이터 입력이나 Codex 실행 권한을 추가하지 않는다.

## 13. 감사와 개인정보

기존 metadata-only 감사 계약을 유지한다.

기록 가능 항목:

- actor, 구성·Deployment·정책 version
- `codex_sdk`와 exact provider model ID
- 외부 전송 판정과 승인 snapshot
- Evidence ID
- input/output token usage와 duration
- 성공 상태 또는 안전 오류 코드
- correlation ID

기록 금지 항목:

- 현재 질문과 대화 전문
- Evidence 본문과 생성 초안
- Codex 내부 추론과 전체 thread item
- thread ID
- 계정 식별자와 인증 정보
- 원본 SDK 오류와 로컬 경로

## 14. 캐시와 임시 산출물

`openai-codex` dependency와 pinned CLI runtime은 Python dependency cache 정책을 따른다.
애플리케이션이 별도 모델 cache를 생성하거나 Git에 추가하지 않는다.

요청별 빈 실행 디렉터리는 OS 임시 위치에 만들고 정상·실패·취소 모두에서 제거한다.
정리 실패는 원래 생성 결과를 성공으로 바꾸지 않으며 안전한 운영 경고로 기록한다.
실제 cache 조사·제거는 `CACHE_POLICY.md`의 승인과 재검증 절차를 따른다.

## 15. 테스트 전략

### 도메인과 migration

- `codex_sdk` enum과 실제 adapter 등록의 동시 존재
- Codex의 development-only, external transfer, no endpoint/no secret 검증
- 다른 Provider의 기존 endpoint·secret 규칙 회귀
- endpoint column nullable migration과 기존 row 무변경
- downgrade 안전성

### Adapter 단위·계약

- `AsyncCodex`, exact model, `ephemeral=True`
- `Sandbox.read_only`와 `ApprovalMode.deny_all`
- 빈 외부 `cwd`
- shell·web·MCP·plugin·apps·skill·multi-agent 비활성 설정
- 구조화 출력 schema 전달과 final response parsing
- token usage와 duration 정규화
- context manager, interrupt와 임시 디렉터리 정리
- 재시도마다 새 thread와 새 작업 디렉터리 사용
- 다른 Provider fallback 미호출

SDK 버전과 config key의 실제 호환성은 pinned dependency를 대상으로 contract test를 둔다.
도구 비활성화를 증명하지 못하면 테스트와 readiness가 실패해야 한다.

### 정책·통합

- 외부 전송 금지 시 SDK client 생성 전 종료
- 여러 Workspace 중 하나가 금지하면 전체 호출 없음
- stale 또는 없는 관리자 승인 거부
- production에서 모델 조회·등록·선택·실행 거부
- exact Deployment와 exact model만 호출
- 구조화 출력·citation 실패 결과 폐기
- metadata-only 감사와 secret·본문 로그 부재

### 프론트엔드

- backend Provider metadata 기반 필드 렌더링
- Codex에서 endpoint·secret 입력 미표시
- development-only·외부 전송·계정 사용량 안내
- 미로그인·모델 없음·격리 실패 상태의 저장 차단
- 운영 환경 선택지와 실행 차단
- Claude 등 미구현 Provider 부재

### 실제 로컬 smoke

실제 Codex smoke는 자동 CI에서 실행하지 않는다. 현재 로그인된 개발 계정, 사용자 승인과
비민감 합성 질문·근거가 준비된 경우에만 명시적으로 실행한다.

- SDK가 기존 로그인을 재사용하는지
- 모델 목록과 exact 선택이 일치하는지
- 문맥화와 생성이 각각 새 ephemeral thread인지
- 최종 답변과 인용이 기존 RAG UI에 표시되는지
- 실패·timeout 뒤 임시 작업 디렉터리가 남지 않는지
- 감사 기록에 본문·계정·thread 정보가 없는지

## 16. 수용 기준

1. 개발 환경 owner가 실제 `Codex SDK · 개발 전용` Provider와 사용 가능한 모델을 확인할
   수 있다.
2. Codex Deployment에는 endpoint와 secret을 입력하거나 저장하지 않는다.
3. 현재 로그인된 Codex 인증을 재사용하되 인증 파일·token·계정 식별자를 복사하지 않는다.
4. SDK 프로세스의 로컬 실행과 OpenAI 외부 추론·전송을 UI가 구분해 설명한다.
5. 문맥화와 생성은 각각 새 ephemeral thread와 빈 read-only workspace에서 실행된다.
6. 모든 권한 상승 요청을 거부하고 금지 도구 비활성화를 확인하지 못하면 실행하지 않는다.
7. 외부 전송 정책과 exact 관리자 승인 전에는 Evidence가 SDK에 전달되지 않는다.
8. 정확한 Deployment Version과 모델만 실행하며 다른 Provider나 모델로 fallback하지 않는다.
9. Codex 결과는 기존 JSON Schema와 citation hard gate를 통과해야만 표시된다.
10. staging·production에서는 등록·모델 조회·선택·실행이 모두 거부된다.
11. 일반 자동 테스트는 외부 네트워크·개인 인증 없이 실행된다.
12. 감사와 로그에 질문·근거 본문·내부 추론·인증값·로컬 경로가 남지 않는다.
13. Claude 등 미래 Provider의 enum, UI 선택지와 fake adapter는 생성하지 않는다.

## 17. 구현 영향과 순서

구현은 별도 TDD 계획 승인 뒤 진행한다. 예상 순서는 다음과 같다.

1. ADR과 RAG 정본 설계 갱신
2. Provider contract registry와 domain RED 테스트
3. endpoint nullable migration과 repository/schema RED 테스트
4. `CodexSdkClientPort`와 실제 SDK wrapper RED/구현
5. `CodexSdkGenerationRuntime`의 health·contextualize·generate RED/구현
6. resolver와 정책·감사 통합 RED/구현
7. owner Provider metadata·Codex models API RED/구현
8. 관리자 Deployment·정책·구성 UI RED/구현
9. OpenAPI 생성, backend/frontend 전체 회귀와 privacy 검사
10. 사용자 승인을 받은 비민감 실제 로컬 smoke와 작업 기록

주요 예상 변경 영역은 `backend/src/ai_workshop/labs/rag/deployments/`,
`backend/src/ai_workshop/labs/rag/generation/`, 관련 migration·API·tests,
`frontend/src/features/rag/models/`, 데이터 정책·구성 UI와 생성 OpenAPI 타입이다.
