# ADR-0053: Claude 직접 연결과 작업 중심의 고급 관리

- 상태: 사용자 요청에 따른 구현
- 결정일: 2026-10-31
- 관련: [ADR-0052](0052-admin-model-setup.md)

## 목적과 선택

사용자는 Claude도 등록할 수 있고 RAG 구성·모델 메뉴를 이해하기 쉽게 사용하기를 요청했다. 기존 불변 버전·권한·수용 게이트를 유지하면서 native Anthropic Messages 어댑터와 기존 화면의 점진적 정보 공개를 추가한다. 직접 Anthropic API는 이번 구현의 선택이며 Bedrock/Vertex 연결은 포함하지 않는다. OpenAI 호환으로 위장하는 방식은 공급자·사용량·고지 계약이 달라 제외한다. 새 마법사/라우터를 중복 신설하지 않고 기존 URL·저장 핸들러를 유지한다.

## 공급자 계약

- 공급자 `anthropic_messages`, endpoint dialect `anthropic`, 외부 위치와 secret reference를 요구한다. 초기 지원은 workspace 범위 키이며 organization 범위 키를 자동 변환하지 않는다. URL과 키는 서버 설정에서만 해석하며 브라우저에는 참조 이름만 반환한다. HTTP redirects·환경 proxy를 사용하지 않는다. typed endpoint가 다른 dialect이면 등록/실행 전에 거절한다.
- protocol version `2026-10-21`, native `/v1/messages`, top-level system과 messages, `output_config.format`의 JSON schema를 사용한다. 기존 schema1 prompt·response parser·근거/인용 검증을 유지한다. 지원하지 않는 설정을 자동 변환하지 않는다.
- `generation.sampling_mode` 누락은 기존 `explicit` 의미다. Claude는 `provider_default`와 `temperature=1.0`을 명시한 후보만 허용하고 wire에는 temperature/top_p/top_k를 보내지 않는다. 다른 공급자에 provider_default를 지정하면 거절한다. 기존 프로파일 데이터는 수정하지 않는다.
- 등록·readiness·runtime 모두 schema1/명시 sampling 호환성을 검사한다. Claude의 SDK orchestration·로컬 전용 옵션은 지원하지 않으며 명시적으로 거절한다.
- 성공은 정확한 모델·종료 상태·텍스트 JSON·필수 사용량·현재 인용 검증을 만족해야 한다. refusal/max_tokens/tool/알 수 없는 block은 정상 답변으로 저장하지 않는다. thinking/redacted_thinking은 답변·로그·예외 본문에 보존하지 않는다.
- 사용량은 공식 의미에 따라 cache 생성/읽기 포함 입력과 출력으로 매핑한다. 측정되지 않은 내부 시간·비용은 미확인으로 유지한다. 실제 추론 호출·계정 권한·품질 수용과 mock 통과를 구분한다.
- 외부 고지는 수신자 Anthropic과 별도 `anthropic-generation-v1` 버전을 사용한다. 기존 OpenAI 확인으로 Claude를 승인하지 않는다. 설치·공간 정책의 기존 approved_providers는 변경하지 않는다. 신규 DB 제약은 공급자 허용 범위만 확장하고 downgrade는 새 공급자 데이터가 있으면 거절한다.

## 화면 계약

- 통합 설정에 Claude 공급자와 공식 공개 모델 최신순 콤보박스를 추가한다. 빈 초기 선택·확인일·출시일·공식 출처·계정 접근 미확인·고급 직접 입력·지원 기능 명시 확인을 유지한다.
- RAG 구성·고급은 저장 구성 확인과 새 구성 만들기를 분리한다. 카드에는 이름·버전·모델·준비 상태를 먼저 표시하고 전체 파이프라인은 펼쳐 보게 한다. 작업/탭 이동에도 미저장 초안을 보존한다.
- RAG 모델·고급은 등록 현황/모델 연결/처리 설정/데이터 정책의 목적을 명확히 한다. 단순 검증 링크는 현황의 안내로 옮기고 등록 작업 하나에 집중하게 한다. 모델 정의·배포·프로파일·JSON/YAML 접근을 없애지 않는다.
- 탐색/선택은 등록·health·추론·승격을 실행하지 않는다. 현재 기본값·도메인 연결·기존 답변과 평가 기록을 변경하지 않는다. 44px 조작, 2px 포커스, desktop·375/320px를 검증한다.

## 공식 확인 근거

2026-10-31 기준 [모델](https://platform.claude.com/docs/en/models/overview), [변경 이력](https://platform.claude.com/docs/en/release-notes/overview), [Messages](https://platform.claude.com/docs/en/api/messages/create), [2026-10-21 migration](https://platform.claude.com/docs/en/api/migration-2026-10-21), [구조화 출력](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)을 확인한다. API 모델 목록의 생성 시각을 출시일로 간주하지 않는다. 공개 목록은 계정 사용 가능 모델이나 품질 추천 순위가 아니다.
