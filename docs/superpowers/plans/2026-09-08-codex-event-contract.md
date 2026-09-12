# Codex exec 이벤트 수신 계약

정본: `../specs/2026-09-07-personal-codex-exec-rag-design.md` §6·7·9.
승인된 실행 연결의 다음 내부 단위다. main만 사용하고 기존 변경을 보존한다.

## Task 1: bounded JSONL 수신기

신규 파일 `backend/src/ai_workshop/labs/rag/generation/codex_events.py`와
`backend/tests/unit/labs/rag/generation/test_codex_events.py`만 구현한다.
프로세스/Provider/DB/UI 연결과 실제 호출은 이 단위에 포함하지 않는다.

입력 bytes chunk를 받는 순수 수신기로 total/line/event/token 한계를 typed limits로 받는다.
`thread.started` → `turn.started` → agent_message 완료 → `turn.completed`의 단일 turn을 허용한다.
agent_message의 started/updated가 오면 같은 id의 완료까지 순서를 확인한다. 직접 completed도 허용한다.
최종 메시지는 정확히 하나이고 필수 종료 이벤트 뒤 다른 이벤트는 거부한다.
빈/잘린/중복키/비정상 숫자/UTF-8 오류/알 수 없는 필드나 이벤트/도구/추론 항목은 안전 코드로 거절한다.
reasoning 본문을 저장하거나 오류에 넣지 않는다. 원시 이벤트를 상태에 보존하지 않는다.
`turn.failed`/`error`는 본문 없이 안정 오류로 처리한다. 실패는 sticky이고 기존 초안은 폐기한다.
사용량은 음수가 아닌 정수이며 bool·float를 거부한다. cached<=input, reasoning<=output을 검증한다.
출력 token 예산은 reasoning을 포함한 output_tokens로 적용한다.
필수 usage는 input_tokens/cached_input_tokens/output_tokens, reasoning_output_tokens는 있으면 검증한다.
수신 완료 후에도 호출자가 exit code와 프로세스 회수를 확인하기 전에는 서비스 응답으로 사용하지 않는다.
현재 공식 JSONL 예시는 실제 모델 식별 필드가 없다. requested model 입력을 받지 않으며
관측 모델은 None으로 명시하고 모델 준비 완료를 주장하지 않는다. 미확인 임의 필드를 발명하지 않는다.
본문은 repr에서 숨기고 오류에는 안정 코드만 둔다. 완성된 final text만 메모리로 반환한다.

TDD: chunk 분할/다중줄/CRLF, 정상 순서, 출력전후 잘못된 이벤트, 중복 최종 메시지,
도구/추론 차단, bytes/line/event/token 경계, UTF8·중복키·NaN·큰정수, 실패 후 초안 폐기,
usage 타입·관계·identity 미확인과 repr 비노출을 검증한다.

검증: 신규 pytest → generation 테스트 → mypy backend/src → 관련 Ruff → 독립 리뷰.

## Task 2: 실제 CLI 접합 근거 조사

메인이 설치된 CLI와 공식 문서에서 지원 설정·출력 형식을 확인한다. 개인 인증 파일은 읽지 않는다.
실제 호출 전 승인 설계의 전송 허가·CLI 설정·임시 경로·출력 수신·수명주기 조건을 모두 충족해야 한다.
모델 증거를 확보할 수 없으면 readiness 차단 이유를 남기고 요청 모델 복사로 대체하지 않는다.

## 완료 조건

Task 1 코드·회귀·독립 리뷰, Task 2 확인 사실과 미검증 목록을 worklog에 남긴다.
전체 RAG나 실제 CLI 연결의 완료를 뜻하지 않는다.

결과: Task 1 구현·독립 재검토 승인, 신규 42개·전체 unit/contract 1,114개·mypy 214개·Ruff 통과.
Task 2 실제 native CLI --version 0.153.4/exit 0/잔류 0 확인. 실제 추론·identity 검증은 미완료.
기록: `docs/worklogs/2026-09-08-codex-event-contract.md`.
