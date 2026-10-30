# ADR-0042: RAG 모델 호출 시간과 미관측 내부 시간

- 상태: 사용자 요청에 따른 관측 기능 구현 결정 (2026-10-26)
- 관련: [ADR-0039](0039-rag-agents-sdk-monitoring.md), [ADR-0041](0041-rag-operation-timings.md)

## 결정

SDK 관리자와 답변 담당의 `AgentSpan`에 선택적 `model_timing`을 추가한다. 기존 비공개 execution stage JSON과 현재 권한을 확인하는 상세 API를 사용한다. DB migration·별도 저장소·권한 경로 변경은 없다. 과거 기록의 값은 `None`이며 복원하거나 0으로 채우지 않는다.

`ModelCallTiming`은 schema_version=1, response_mode=non_streaming과 다음 값만 허용한다.

| 필드 | 의미 |
|---|---|
| request_duration_ms | delegate HTTP 요청 시작부터 응답 읽기·닫기 종료 또는 전송 예외까지의 monotonic 경과 시간 |
| response_headers_ms | 같은 요청 시작부터 헤더 수신까지의 누적 경과 시간. 미수신은 None |
| response_body_ms | 같은 요청 시작부터 전체 본문 iterator 완료까지의 누적 경과 시간. HTTPX의 EOF 자동 close를 포함하며 부분 수신은 None |
| response_validation_ms | 성공 HTTP 응답의 JSON 파싱·usage 추출·모델/출력 계약 검사 시간. 검사 실패도 측정하며 미착수는 None |
| server_timing_status | 현재 호출 방식은 not_exposed_by_non_streaming_api. 내부 적재·입력·출력 시간 미제공을 뜻함 |

수치는 유한한 비음수만 허용하고 bool·문자열 변환·임의 필드를 거절한다. body는 headers가 있어야 하며 request >= body >= headers를 검사한다. validation은 body 완료 뒤에만 존재한다. model 종류 외의 span에는 이 필드를 넣지 못한다. 이 값은 본문·URL·인증 정보·임의 헤더·비공개 추론을 포함하지 않는다.

이 구간은 HTTP 요청을 기준으로 한다. 비스트리밍의 헤더 수신은 첫 토큰 시간(TTFT)이 아니다. request에는 모델 내부 작업·서버 대기·전송 등이 섞여 있다. headers/body는 누적값이므로 서로 더하지 않는다. validation은 별도 구간이다. 모델 span은 계측 저장 등을 포함할 수 있어 request와 같지 않으며, 부모 agent/위임 span도 중첩되므로 합산하지 않는다.

실패·취소 시 시간은 아직 running인 model span에 먼저 부착하고 기존 종료 경로가 상태와 함께 저장한다. 따라서 timeout의 내부 CancelledError를 사용자 취소로 잘못 확정하지 않는다. 계측을 위한 추가 HTTP 요청·생성·재시도는 하지 않는다. 기존 요청 본문·stream=false·모델·프로파일·종료 확인 규칙을 보존한다.

## 런타임 제공 범위

현재 Ollama 0.40.3의 비스트리밍 `/v1/chat/completions` 변환은 내부 timing을 응답에 실어 보내지 않는다. 스트리밍 usage 최종 chunk의 timings 확장은 입력/출력 시간만 제공하고 모델 적재 시간은 제공하지 않는다. native `/api/chat`의 load_duration/prompt_eval_duration/eval_duration/total_duration과 구분한다. 이 구현에서 호출 프로토콜을 바꾸거나 미제공 값을 추정하지 않는다.

내부 적재·입력·출력 시간을 실제로 수집하려면 명시적인 native API 어댑터 또는 서버 측 상관관계 계측 설계가 필요하다. 도구 호출·출력 schema·reasoning·사용량·취소/종료·동일 질문 품질의 호환성 검증 후 별도 결정한다. 현재 직접 생성/문맥화 어댑터는 이 SDK model span 계약의 적용 범위 밖이다.

공식 근거: [Ollama native chat](https://docs.ollama.com/api/chat), [호환 API](https://docs.ollama.com/api/openai-compatibility), [0.40.3 응답 변환](https://github.com/ollama/ollama/blob/v0.40.3/openai/openai.go#L301-L329), [스트리밍 변환](https://github.com/ollama/ollama/blob/v0.40.3/middleware/openai.go#L126-L160).
