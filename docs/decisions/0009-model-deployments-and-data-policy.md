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
