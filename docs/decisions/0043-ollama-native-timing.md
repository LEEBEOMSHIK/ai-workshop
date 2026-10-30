# ADR-0043: 명시적으로 선택하는 Ollama native 생성 계측

- 상태: 구현·독립 검증 및 명시 비기본 후보 실제4회 수용 완료, 일반 기본값 미승격 (2026-10-26)
- 관련: [ADR-0042](0042-rag-model-call-timing.md)

현재 호환 API에는 내부 시간이 없어 큰 생성 지연의 원인을 확정할 수 없다. 서버 로그 상관관계도 없고 호환 API 스트리밍은 준비/로드 시간을 주지 않으므로, 동일 Ollama의 비스트리밍 `/api/chat`을 선택하는 SDK transport 경로를 추가한다. 기본값 전환이나 자동 fallback은 하지 않는다.

## 선택과 의미

버전이 고정되는 OrchestrationPolicy에 `local_http_api`를 추가한다. 생략 시 `openai_chat_completions`, 명시 선택은 `ollama_chat`이다. native는 기존 local·외부 전송 없음·retry0·schema2 조건과 실제 endpoint dialect=ollama를 readiness 및 실행에서 검사한다. 기존 저장 프로파일·기본값·모델·후보 승격은 변경하지 않는다.

SDK의 manager→as_tool→specialist, 모델2회/도구1회와 출력 예산을 유지한다. 현재 사용 중인 텍스트 요청만 지원하고 알 수 없는 옵션은 거절한다. Ollama0.40.3의 호환 변환과 같은 의미로 model/messages/tools, temperature, max_tokens→num_predict, 기본 top_p=1.0, response_format.schema→format, reasoning_effort=none→think=false를 변환한다. tool_choice=required/parallel=false는 이 버전의 호환 API도 서버에서 지원하지 않는다. 현재 manager의 단일 승인 도구 설정만 허용하고 응답의 정확히1개 도구 이름·arguments 검증을 계속 애플리케이션이 소유한다. 서버 강제 선택을 지원한다고 표시하지 않는다.

native model·done·done_reason·message·도구 ID/arguments를 검사한 뒤 SDK 응답으로 변환한다. 실제 제공된 ID를 유지하고 누락 ID를 만들어서 정상화하지 않는다. 응답 크기 제한·닫기·timeout/취소·로컬 종료 확인과 실패 시 재시도0은 유지한다. trace의 http_request에는 SDK 변환 전 입력 대신 실제 native 요청의 허용 필드를 보관하고 API 종류를 timing에 남긴다.

## 서버 지표

기존 client timing과 별도의 선택적 `server_timing`에 출처 `ollama_chat` 및 total/load/prompt_eval/eval 시간을 ms로 보관한다. 입력/출력 토큰은 기존 span 토큰 필드에 매핑한다. 원본 ns는 bool/문자열/음수/과대 정수 없이 검증하고 한 번만 ms로 변환한다. server_timing_status는 available/missing/invalid와 기존 not_exposed_by_non_streaming_api를 구분한다. 부가 계측이 빠지거나 잘못돼도 유효한 답변 자체를 실패시키지 않는다. 과거 JSON은 None으로 읽는다.

`load_duration`은 handler 시작부터 scheduleRunner 이후까지여서 **서버 준비·로드(대기 포함)**다. 총시간과 구성값은 완전히 분리된 구간을 보장하지 않으므로 합계나 뺄셈으로 queue·network를 추정하지 않는다. 원문/비공개 추론/인증/임의 헤더를 추가 수집하지 않는다.

## 수용과 다음 수정

오프라인 요청 동등성·예산·실패/취소·저장/현재 권한 재조회 검증 후 사용자 추가 승인4회 범위에서 동일 질문·근거·온도·출력 예산의 첫 실행/반복을 측정했다. 첫 답변 담당의 총196.492초 중 입력 처리181.092초가 주된 비용이었고 같은 입력의 반복에서는0.292초였다. 실제4개 span 내부 지표와 입력·답변·근거·인용 보존을 확인했다. 일반 기본값·후보 승격과 속도 개선 완료는 아니다. 구현·실측·다음 입력 형식 후보는 [작업 기록](../worklogs/2026-10-26-ollama-native-timing.md)을 따른다. 이번 추가4회도 소진했으며 자동 연장하지 않는다.

공식 근거: [0.40.3 호환 입력 변환](https://github.com/ollama/ollama/blob/v0.40.3/openai/openai.go#L579), [서버 준비 시간 경계](https://github.com/ollama/ollama/blob/v0.40.3/server/routes.go#L2943), [native API](https://docs.ollama.com/api/chat).
