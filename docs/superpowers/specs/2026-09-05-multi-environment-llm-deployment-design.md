# 다중 환경 LLM Deployment와 데이터 전송 정책 설계

- 상태: 사용자 승인 완료
- 작성일: 2026-09-05
- 범위: RAG 생성 모델의 로컬·온프레미스·외부 API 실행과 사용자 고지
- 선행 설계: `2026-09-04-conversational-generative-rag-v2-design.md`

## 1. 배경

대화형 생성 RAG V2는 `GenerationRuntimePort`와 로컬 OpenAI-compatible adapter를
구현했지만, 현재 LLM Model Definition에 Provider·실행 모델·로컬 데이터 정책이 함께
들어 있어 실행 위치와 모델 자체를 독립적으로 관리할 수 없다.

개발 환경에서는 로컬 LLM 또는 현재 인증된 Codex를 사용할 수 있어야 한다. 운영에서는
OpenAI Responses API의 여러 모델을 등록하고 RAG 구성마다 선택할 수 있어야 한다. 외부
전송을 허용하지 않는 조직이나 지식 공간은 로컬 또는 온프레미스 Deployment만 사용한다.
외부 전송을 허용하는 경우에도 관리자가 명시적으로 승인하고 사용자가 처리 위치를 항상
인지해야 한다.

## 2. 목표와 비목표

### 목표

- 모델 정체성과 실제 실행 위치를 분리한다.
- 저장된 RAG 구성이 정확한 불변 Deployment Version을 선택한다.
- 현재 환경과 데이터 정책이 허용한 Deployment만 실행한다.
- 로컬 OpenAI-compatible, 개발 전용 Codex SDK, OpenAI Responses API를 실제 adapter로
  지원한다.
- 관리자는 외부 전송을 명시적으로 승인하고 사용자는 대화 중 처리 위치를 항상 확인한다.
- Provider별 응답을 기존 구조화 생성·인용 검증 계약으로 정규화한다.
- 새 Provider는 기존 RAG 업무 로직을 바꾸지 않고 adapter로 추가할 수 있다.

### 비목표

- 첫 구현에서 Anthropic, Gemini, Azure OpenAI 또는 Bedrock adapter를 구현하지 않는다.
- 사용자 개인 API Key와 BYOK를 지원하지 않는다.
- 여러 Provider를 자동으로 순회하는 fallback·load balancing·최저가 routing을 만들지 않는다.
- Provider의 대화 저장 기능을 애플리케이션 대화 기록의 정본으로 사용하지 않는다.
- 두 번째 AI Lab이 생기기 전에 미래 Lab용 빈 모듈이나 데이터 구조를 만들지 않는다.

## 3. 용어와 경계

```text
Model Definition
  └─ Model Deployment Version
       ├─ local_openai_compatible
       ├─ codex_sdk
       └─ openai_responses

Generation Profile
  └─ exact Model Deployment Version

Saved RAG Configuration Version
  ├─ Indexing Profile
  ├─ Retrieval Profile
  ├─ Generation Profile
  └─ approved Data Policy Version
```

- **Model Definition**은 모델명·버전·종류·기능을 표현한다.
- **Model Deployment**는 관리자가 알아볼 수 있는 논리적 배포 이름이다.
- **Model Deployment Version**은 Provider, 실행 위치, Provider 모델 ID, endpoint·secret
  reference, 환경 범위와 기능을 고정한 불변 실행 계약이다.
- **Provider Adapter**는 서로 다른 호출·인증·응답·오류를 공통 Generation Runtime 계약으로
  변환한다.
- **Data Policy**는 외부 전송 가능 여부와 승인 Provider를 결정한다.
- `운영 모델`은 별도 모델 종류가 아니다. 운영 여부는 Deployment Version의 환경 범위와
  실행 위치가 표현한다.

현재 구현은 RAG에서 먼저 사용한다. 공통 Provider port는 RAG 도메인에 의존하지 않게
설계하되 실제 두 번째 소비자가 생기기 전에는 별도 범용 플랫폼으로 추출하지 않는다.

## 4. 지원 Provider와 환경

### 로컬 OpenAI-compatible

- 개발·운영 환경 모두에서 사용할 수 있다.
- endpoint는 Deployment Version의 참조 정보로 선택한다.
- `local`은 loopback, `on_premise`는 관리자가 승인한 사내 endpoint를 의미한다.
- 실제 모델 목록에서 등록한 Provider 모델 ID가 정확히 일치해야 준비 상태가 된다.

### Codex SDK

- `development_only=true`인 개발 전용 Deployment다.
- Python Codex SDK의 pinned local runtime을 사용하고, 매 요청마다 `codex exec` 프로세스를
  직접 조립하는 방식을 사용하지 않는다.
- 전용 빈 실행 디렉터리, read-only sandbox, 웹 검색·MCP·plugin 비활성, 비대화형 승인 정책을
  사용한다. 저장소나 사용자 문서 경로를 workspace로 제공하지 않는다.
- RAG가 전달한 bounded history와 선별 Evidence만 입력하며 결과는 동일한 구조화 출력과
  인용 hard gate를 통과해야 한다.
- staging·production에서는 구성·선택·실행을 모두 거부한다.

공식 Codex SDK는 로컬 Codex agent를 프로그래밍 방식으로 제어하며 Python SDK가 pinned
Codex CLI runtime을 포함한다고 설명한다. app-server WebSocket transport는 실험 단계이고
운영 workload를 지원하지 않으므로 이 설계의 운영 통신 경계로 사용하지 않는다.

- <https://learn.chatgpt.com/docs/codex-sdk>
- <https://learn.chatgpt.com/docs/app-server>

### OpenAI Responses API

- staging·production 및 정책이 허용된 development에서 사용할 수 있다.
- 여러 OpenAI 모델을 각각 별도 Deployment Version으로 등록할 수 있다.
- Responses API의 JSON Schema Structured Outputs를 사용한다.
- Provider conversation이나 `previous_response_id`를 대화 정본으로 사용하지 않고, 현재의
  서명 검증된 bounded history를 매 요청 명시적으로 전달한다.
- API 모델 ID와 응답의 실제 모델 정체성이 허용 계약과 맞지 않으면 결과를 폐기한다.

공식 Responses API는 모델 선택, 구조화 출력과 대화 연결을 지원한다.

- <https://developers.openai.com/api/reference/cli/resources/responses/methods/create>

## 5. 데이터 모델

### Model Definition

기존 모델 이름·버전·종류와 평가 정체성을 유지한다. LLM의 `provider`, `runtime_model`,
`data_policy`는 Model Definition의 필수 속성에서 제거하고 Deployment Version으로 옮긴다.

### Model Deployment Version

최소 필드는 다음과 같다.

- deployment identity ID, version ID와 양의 version
- 표시 이름과 설명
- model definition ID
- provider kind
- execution location: `local | on_premise | external`
- allowed environments: `development | staging | production`
- exact provider model ID
- endpoint reference
- organization secret reference 또는 `null`
- capability: structured output, contextualization, token accounting
- external transfer 여부
- 전송 데이터 범주와 Provider 데이터 처리 안내 reference
- timeout·retry policy와 health check 설정
- `development_only`
- 생성자와 생성 시각

같은 Deployment identity를 수정하지 않고 새 version을 만든다. 저장 RAG 구성은 version
ID를 참조하므로 기존 실행을 재현할 수 있다. endpoint와 secret의 실제 값은 DB에 저장하지
않는다.

### Generation Profile binding

새 Generation Profile은 LLM Model binding 대신 정확한 Deployment Version binding을
사용한다. 기존 불변 Generation Profile binding을 제자리에서 수정하지 않는다.
Prompt·context policy·출력 제한·인용 정책은 Generation Profile에 유지한다. Deployment
변경은 새 Generation Profile version을 만들지만 검색 색인을 재구축하지 않는다.

### Data Policy

현재 단일 조직 구조에서는 Installation Data Policy가 회사 기본 정책이다.

- outbound mode: `deny | approved_providers`
- 승인 Provider 종류
- 정책 버전, 변경자와 변경 시각

첫 migration은 Installation 정책을 `deny`로 생성한다. 관리자가 Provider와 전송 범위를
검토해 새 정책 version을 승인하기 전에는 외부 Deployment를 사용할 수 없다.

Workspace Data Policy는 Installation 정책을 상속하며 더 강화할 수만 있다.

- `inherit`
- `deny`
- Installation이 승인한 Provider의 부분집합

Workspace 정책이 회사 기본보다 외부 전송 범위를 넓히는 변경은 도메인과 DB에서 모두
거부한다. 정책이 강화되면 과거에 저장된 RAG 구성도 grandfathering하지 않고 즉시 실행
불가가 된다.

### 관리자 승인

외부 Deployment를 사용하는 Saved RAG Configuration Version에는 다음을 기록한다.

- 승인한 관리자
- 승인 시각
- 승인한 Installation·Workspace policy version
- Deployment Version
- disclosure 문구 version

정책이나 Deployment가 바뀌면 기존 승인을 재사용하지 않고 새 RAG 구성 version으로 다시
승인한다.

## 6. Secret 관리

- 초기 버전은 관리자 등록 조직 공용 인증정보만 지원한다.
- 환경변수 또는 운영 Secret Manager가 실제 값을 보관한다.
- DB에는 allowlist 형식의 `secret_ref`만 저장한다.
- 임의 환경변수명이나 secret 경로를 일반 사용자가 제출할 수 없다.
- API는 secret 값을 입력 이후 다시 반환하지 않는다.
- UI는 구성 여부, 마지막 검증 시각과 안전한 오류 코드만 보여준다.
- 질문, 문서 본문, prompt, 생성 초안과 secret은 일반 로그에 남기지 않는다.

## 7. 정책 판정과 실행 흐름

실제 실행 가능 여부는 다음 교집합으로 계산한다.

```text
Saved RAG Configuration이 선택한 Deployment Version
∩ 현재 애플리케이션 환경에서 허용된 Deployment
∩ Installation Data Policy
∩ 모든 선택 Workspace Data Policy
= 실행 가능한 단일 Deployment Version
```

하나의 질문이 여러 Workspace를 검색하면 가장 엄격한 정책을 적용한다. 하나라도 외부
전송을 금지하면 외부 Provider를 호출하지 않는다. 문서를 검색한 뒤 금지된 항목만 빼고
외부로 보내는 방식은 동일 질문의 정책 의미를 모호하게 하므로 첫 버전에서 허용하지 않는다.

실행 순서는 다음과 같다.

1. 사용자와 Workspace·folder 권한을 확인한다.
2. 저장된 RAG 구성과 정확한 Generation Profile·Deployment Version을 해석한다.
3. 현재 환경, capability와 Installation·Workspace policy를 판정한다.
4. 사용자에게 반환할 서버 authoritative disclosure를 확정한다.
5. Hybrid 검색과 선택적 reranking을 수행한다.
6. 답변에 필요한 최소 Evidence만 선택한다.
7. 선택된 단일 Provider Adapter를 호출한다.
8. Provider 응답을 공통 StructuredGeneration으로 변환한다.
9. 인용과 원문 위치를 검증한다.
10. 검증된 답변, 인용과 실제 실행 정보를 반환한다.

정책 판정은 Evidence 본문이 외부 adapter에 전달되기 전에 끝나야 한다. 설정한 Deployment가
실패해도 다른 Deployment로 자동 전환하지 않는다.

## 8. API와 응답 계약

관리자 API는 다음 책임을 분리한다.

- Model Definition 등록·조회
- Deployment identity와 새 immutable version 등록·조회
- secret reference 연결과 연결 상태 검사
- Installation·Workspace 정책 version 등록·조회
- Generation Profile과 Deployment Version binding
- 외부 Deployment RAG 구성 저장 시 명시적 승인

일반 사용자는 자신이 접근 가능한 RAG 구성의 안전한 실행 설명만 조회한다. 내부 endpoint,
secret reference와 기술 식별자는 기본 응답에 노출하지 않는다.

검색 응답의 `generation`에는 서버가 확정한 다음 정보를 추가한다.

```text
execution.provider
execution.model_name
execution.model_version
execution.deployment_name
execution.location
execution.external_transfer
execution.disclosure
```

실제 내부 ID와 진단 정보는 관리자 기술 상세에서만 제공한다. 프론트는 provider 이름으로
처리 위치를 추측하지 않고 `execution`과 readiness 응답을 그대로 표시한다.

## 9. 관리자·사용자 UI

### 관리자 모델·Deployment 화면

- 로컬, 온프레미스, 외부 API, Codex 개발용 배지
- Provider, 모델명·버전과 사용 가능 환경
- 외부 전송 여부와 허용 데이터 정책
- 구조화 출력·문맥화 capability
- secret 구성 여부, 연결 상태와 마지막 검증 시각
- 내부 endpoint와 식별자는 접힌 기술 상세에만 표시

### RAG 구성 화면

- 선택지에 Deployment 이름·모델·버전·실행 위치를 함께 표시
- 현재 환경과 선택 Workspace 정책에 맞지 않는 항목은 비활성화하고 구체적인 이유를 표시
- 외부 API Deployment 저장 시 Provider, 전송되는 데이터 범위와 Workspace를 재확인
- 관리자 명시 체크 없이는 저장하지 않음
- 저장 카드에 승인 정책 version과 현재 readiness 표시

### 사용자 대화 화면

- 입력창 위에 현재 실행 위치 안내를 항상 표시
- 로컬 예시: `사내 로컬 모델에서 처리됩니다.`
- 외부 예시: `OpenAI 외부 API로 현재 질문, 제한된 이전 대화와 선별된 문서 근거가
  전송됩니다.`
- 모델명·버전·Provider 상세 보기 제공
- 각 응답에 실제 실행된 모델과 외부 전송 여부 표시
- 매 질문마다 반복 modal 동의를 받지 않고 관리자 승인과 사용자 상시 고지를 유지

## 10. 준비 상태와 오류 계약

`answer_ready=true`가 되려면 다음을 모두 만족해야 한다.

- Generation Profile과 정확한 Deployment Version 존재
- 현재 환경에서 Deployment 허용
- 필요한 capability 존재
- secret reference 해석 가능
- Provider health와 정확한 모델 확인 성공
- Installation·모든 Workspace policy 허용
- 외부 Deployment의 관리자 승인 유효

Provider별 오류는 다음 공통 안전 코드로 변환한다.

- `deployment_not_allowed_in_environment`
- `workspace_external_transfer_denied`
- `provider_not_allowed`
- `deployment_not_ready`
- `provider_authentication_failed`
- `provider_rate_limited`
- `provider_timeout`
- `provider_invalid_response`
- `structured_output_invalid`
- `citation_validation_failed`

재시도 가능한 timeout과 rate limit만 versioned retry policy 범위에서 제한적으로 재시도한다.
인증 실패, 정책 거절, 모델 불일치와 구조화 출력 실패는 재시도하지 않는다. Provider 원문
오류나 비공개 입력은 사용자 오류 응답과 일반 로그에 포함하지 않는다.

## 11. 감사와 비용 기록

본문 없이 다음 실행 메타데이터를 기록한다.

- actor와 RAG 구성 version
- Installation·Workspace policy version과 판정 결과
- Deployment·Provider·모델 version
- 실행 위치와 외부 전송 여부
- 전송된 Evidence ID
- 입력·출력 token 수
- 지연시간과 Provider가 제공한 사용량
- 비용 추정 기준 version과 추정액
- 성공·실패 코드와 correlation ID

비용은 사용자·RAG 구성·Deployment·기간별로 집계할 수 있어야 한다. Provider 청구액과
애플리케이션 추정액이 다를 수 있으므로 추정치로 명시한다.

## 12. 마이그레이션

현재 LLM Model Definition의 `provider=openai_compatible`, `runtime_model`,
`data_policy=local_only`를 모두 해석할 수 있으면 동일 모델을 참조하는 local Deployment
Version과 새 Generation Profile version을 생성한다. 기존 Generation Profile과 저장 구성
version의 binding은 수정하지 않는다.

- 원본 레코드와 기존 구성 version은 즉시 삭제하지 않는다.
- 기존 model-bound Generation Profile을 사용하는 구성은 legacy read-only로 유지하고 새
  Deployment-bound 구성으로 명시적으로 저장하기 전까지 `deployment_not_ready`로 표시한다.
- 안전하게 변환할 수 없는 모델 레코드도 준비 불가로 남기고 관리자 조치를 요구한다.
- migration은 secret 값을 만들거나 추측하지 않는다.
- migration 전후 configuration·profile·model·deployment 참조 개수와 해석 결과를 검증한다.
- downgrade는 새 Deployment를 참조하는 구성이 존재하면 데이터 손실 없이 거부한다.

## 13. 테스트 전략

### 도메인·단위

- Deployment 불변 버전과 환경/capability 검증
- Installation 정책과 Workspace 강화 정책의 교집합
- Workspace가 회사 정책을 완화하려는 변경 거절
- secret literal과 허용되지 않은 reference 거절
- Provider 오류의 공통 오류 변환

### Adapter 계약

- 로컬 OpenAI-compatible 모델 identity와 구조화 출력
- Codex SDK 전용 빈 workspace·read-only·development-only 계약
- OpenAI Responses API 모델 identity, JSON Schema와 usage 변환
- timeout, rate limit, 인증 실패, 잘못된 응답과 secret 위생

### 통합·권한

- 외부 전송 금지 요청이 adapter 호출 전에 중단됨
- 여러 Workspace 중 하나가 금지하면 외부 호출 없음
- 여러 OpenAI Deployment 중 저장 구성의 정확한 하나만 호출
- 관리자 승인 없는 외부 RAG 구성 저장 거절
- 정책 강화 뒤 기존 구성 readiness가 즉시 false
- 후속질문의 bounded history와 assistant 서명 검증 유지
- 근거 부족 시 모든 Provider 미호출

### 프론트엔드·실행

- 관리자 선택지의 실행 위치·정책·비활성 사유
- 외부 전송 승인 확인과 사용자 상시 안내
- 서버 disclosure와 실제 응답 모델 표시
- 로컬 fake server 및 OpenAI API 모의 응답 통합 검증
- 실제 외부 API smoke는 비민감 합성 문서만 사용

## 14. 수용 기준

1. 로컬 환경에서 로컬 OpenAI-compatible 또는 Codex SDK Deployment를 RAG 구성에 선택할
   수 있다.
2. 운영 환경에서 여러 OpenAI 모델 Deployment를 등록하고 정확한 version을 선택할 수 있다.
3. Codex Deployment는 production에서 저장·실행할 수 없다.
4. 외부 전송 금지 Workspace의 Evidence는 외부 adapter에 도달하지 않는다.
5. 여러 Workspace 중 하나라도 금지하면 전체 외부 생성 요청을 거절한다.
6. 관리자가 외부 전송을 승인하지 않은 RAG 구성은 저장되지 않는다.
7. 사용자는 질문 전과 응답 후에 실행 위치, Provider와 외부 전송 여부를 확인할 수 있다.
8. API Key와 secret reference가 일반 사용자 응답·로그에 노출되지 않는다.
9. Provider 실패를 다른 모델로 자동 전환하지 않는다.
10. 모든 Provider 결과가 동일한 인용 검증을 통과한 뒤에만 표시된다.
11. 모델 또는 Deployment 변경만으로 검색 색인을 재구축하지 않는다.
12. 실행 메타데이터로 모델·Deployment·정책·prompt·구성 version을 재현할 수 있다.

## 15. 구현 순서

1. ADR과 Deployment·Data Policy 도메인 계약
2. DB migration과 기존 로컬 LLM 명시적 이전
3. Deployment Registry·정책·secret reference 관리자 API
4. 환경·Workspace 정책 판정과 readiness
5. adapter resolver와 기존 로컬 OpenAI-compatible adapter 이전
6. OpenAI Responses API adapter와 usage 수집
7. Codex SDK 개발 전용 adapter
8. RAG 구성의 Deployment 선택·관리자 승인 UI
9. 사용자 상시 disclosure와 응답 실행 정보 UI
10. 회귀·통합·privacy·실제 비민감 smoke와 운영 문서
