# ADR-0009: 모델 정체성과 실행 Deployment 및 데이터 정책을 분리한다

- 상태: 승인
- 결정일: 2026-09-05

## 배경

기존 LLM Model Definition은 평가할 모델의 정체성과 Provider, 실행 endpoint, 외부 전송
정책을 함께 표현한다. 이 구조에서는 같은 모델을 로컬과 외부에서 실행하거나 Provider를
교체할 때 모델 평가 정체성과 실행 계약을 독립적으로 버전 관리할 수 없다. 또한 여러
Workspace의 근거를 사용하는 요청에서 회사 기본 정책보다 넓은 외부 전송을 막는 명시적
도메인 경계가 필요하다.

## 결정

- Model Definition은 모델의 정체성과 평가 기준을 소유한다.
- Generation Profile은 정확한 불변 Model Deployment Version을 참조한다.
- Deployment Version은 Provider, 실행 위치, 허용 환경, exact Provider 모델 ID,
  endpoint·secret reference, 비어 있지 않은 명명된 capability 집합, 외부 전송 계약과
  실행 한계값을 고정한다.
- 첫 전달에서 등록 가능한 Provider kind는 `local_openai_compatible`과
  `openai_responses`뿐이다.
- 로컬 Provider는 `local` 또는 `on_premise`에서만 실행하고 외부 전송을 선언하지 않는다.
- OpenAI Responses는 `external`에서만 실행하며 endpoint·secret reference, 전송 데이터
  범주와 데이터 처리 안내 reference를 모두 요구한다. 실제 endpoint와 secret 값은 이
  도메인 객체에 저장하지 않는다.
- Installation Data Policy가 외부 전송의 상한이다. Workspace Data Policy는 이를
  상속하거나 거부하거나 승인 Provider의 부분집합으로만 강화할 수 있다.
- 여러 Workspace를 선택한 요청은 모든 Workspace 정책을 만족해야 한다. 정책 완화 시도는
  잘못된 정책으로 거부하고, 유효한 정책의 실행 거절은 구분된 안전 reason code로 반환한다.
- 환경 정규화, answer-ready capability 교집합, 관리자 승인, 영속성, API, UI와 실제
  Provider adapter는 후속 변경에서 이 계약을 소비한다.

## 결과

- Provider 변경은 새 Deployment/Profile/Configuration version을 만들며 검색 색인을
  재구축하지 않는다.
- 정책 강화는 과거 구성을 grandfathering하지 않고 후속 실행 판정에 즉시 반영된다.
- 지원하지 않는 Provider가 enum이나 선택지에 미리 노출되지 않는다.
- 현재 `Settings.environment`의 `local | test | production` 값과 Deployment의
  `development | staging | production` 값 사이 정규화는 후속 runtime resolver가 명시적으로
  소유하며, 이 도메인 계약은 두 문자열 집합을 묵시적으로 동일시하지 않는다.

## 비채택 대안과 제외

- Model Definition에 실행 위치와 인증정보를 유지: 모델 정체성과 운영 변경의 수명주기를
  결합하므로 채택하지 않는다.
- Workspace가 Installation보다 넓은 Provider를 승인: 회사 외부 전송 상한을 우회하므로
  거부한다.
- Provider 실패 시 다른 Deployment 자동 선택: 저장 구성의 재현성과 사용자 고지를
  깨뜨리므로 허용하지 않는다.
- Codex SDK와 타사 Provider adapter: OpenAI 첫 전달이 검증된 뒤 별도 변경으로 추가한다.
- 이번 결정은 API, DB schema·migration, secret resolver, readiness와 UI를 구현하지 않는다.

## 2026-10-12 로컬 HTTP schema2·종료 상태 보완

사용자가 기존 HTTP 어댑터의 근거 부족 응답·출력 검증·취소 상태와 모의 연결 테스트 변경을 승인했다.
`local_openai_compatible`은 schema2에서 명시적 `status`와 claims의 일관성, 정확한 필드·타입·
UUID·중복 키·잘린 출력·최종 assistant 응답을 검증한다. 기존 schema1 및 schema3 거부와
공통 인용 검증은 유지한다. 모델명·endpoint를 업무 코드에 고정하지 않는다.

대화 실행별로 로컬 HTTP POST 시도와 완전한 HTTP 응답 수신을 추적한다. 요청 취소·timeout·
전송 실패는 서버 추론 종료 증거가 아니며, 앞선 미확인은 재시도 성공으로 지워지지 않는다.
미확인 실행은 기존 `execution_terminated=false`와 `provider_termination_unconfirmed` 오류로
기록하고 결과를 완료로 승격하지 않는다. 취소 상태는 유지하며 새 질문을 막는다. 기존 다른
provider 및 과거 failed/interrupted의 의미를 일괄 변경하지 않는다. 삭제된 대화도 종료를
확인하지 못했으면 termination 기록을 만들지 않으며 기존 첨부 보존 규칙을 유지한다.
이는 새 DB 열·migration·과거 취소 복구 API를 추가하지 않는다. HTTP 응답 수신은 해당 요청의
통신 완료이며 서버 프로세스 종료나 모델 unload 증거가 아니다. 실제 모델 종료 수용은 별도다.

Ollama 설치·실행·모델 다운로드·DB 등록·정책 변경·운영 활성화는 이 코드 승인에 포함하지 않는다.


### 같은 날 실제 HTTP 시험 후 reasoning 계약 보완

별도 승인된 합성 실호출3회는 모두 실패했다. 정상/근거 부족은 HTTP200·stop과 schema2
본문을 받았지만 `message.reasoning` 때문에 거부됐고, 문맥화는512토큰·length로 잘렸다.
Ollama [v0.40.3 OpenAI 변환 소스](https://github.com/ollama/ollama/blob/v0.40.3/openai/openai.go)는
`message.reasoning`을 content와 분리하고 `reasoning_effort="none"`을 think=false로 변환한다.
[Gemma thinking 문서](https://ai.google.dev/gemma/docs/capabilities/thinking)는 thinking/answer의
분리를 명시한다. [같은 버전 Gemma4 renderer](https://github.com/ollama/ollama/blob/v0.40.3/model/renderers/gemma4.go)의
생각 토큰 조건부 추가도 확인했다. 이 계약은 설치된 사용자 GGUF의 실효 동작까지 증명하지 않는다.

HTTP 어댑터의 명시적 `dialect="ollama"`와 schema2 조합에서만 문자열 reasoning 메타데이터를
버리고 content JSON만 검증한다. 기본 dialect는 기존 openai이며 모델명/포트 자동감지와
기본 factory 전환은 하지 않는다. content의 추가 필드·중복 키·인용 UUID·status/claims와
finish_reason=stop 검증은 유지한다. Ollama 문맥화 요청에만 reasoning_effort=none과 짧은
독립 검색 질의 지시를 넣으며 기존 출력 상한을 늘리거나 잘린 출력을 재시도하지 않는다.
정상 답변 생성은 thinking 설정을 바꾸지 않는다. 원문 reasoning은 저장·반환·로그하지 않는다.
DB·설정·서비스 변경과 추가 실호출은 이번 보완 승인에서 제외한다.

### 2026-10-14 프로파일별 answer reasoning opt-in

승인된 시험용 최소 계약으로 Generation Profile의 `generation.answer_reasoning_effort`를 선택적으로 추가한다. 키 생략은 기존 동작이며 명시 값은 문자열 `none`만 허용한다(null/기타 값 거부). 로컬 `local_openai_compatible`의 schema2 및 명시적 Ollama dialect에서 answer 요청의 `reasoning_effort="none"`으로 전달한다. 비지원 조합은 명시적으로 거부한다. rewrite의 기존 none, 출력 한도, 입력 직렬화, timeout/retry, 종료·스키마·인용 검증은 유지한다. 모델명/UUID 하드코딩이나 전역 기본값 변경은 없다. 기존 JSON config를 이용하므로 DB migration은 없으며 실제 프로파일/구성 버전 반영·재시작·실추론은 코드/mock 완료와 별개다.
