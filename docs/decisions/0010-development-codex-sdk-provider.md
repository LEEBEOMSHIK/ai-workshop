# ADR-0010: 개발 전용 Codex SDK Provider를 격리 검증 전까지 차단한다

- 상태: 차단
- 결정일: 2026-09-06
- 후속 결정: `0011-development-codex-app-server-provider.md`

## 배경

개발 환경에서 현재 OS 사용자의 Codex 인증을 재사용하는 생성 Provider를 검토했다. SDK
프로세스와 bundled Codex runtime은 로컬에서 실행되지만 기본 모델 추론에는 질문, 제한된
이전 대화와 선별 Evidence가 OpenAI로 전송되므로 로컬 Provider로 취급할 수 없다.

공식 OpenAI 문서와 설치된 stable 패키지 `openai-codex==0.147.0`을 확인했다. 이 패키지는
Python `>=3.10`을 요구하고 `openai-codex-cli-bin==0.147.0`을 포함한다. bundled 실행 파일의
실제 버전 출력도 `codex-cli 0.147.0`이다.

## 확인된 공개 계약

- `AsyncCodex` context와 기존 Codex 계정 상태·모델 목록 조회
- `thread_start()`의 exact model, developer instructions, 전용 `cwd`, `ephemeral=True`,
  `Sandbox.read_only`, `ApprovalMode.deny_all`
- thread `run()`의 exact model, `cwd`, JSON Schema `output_schema`, sandbox와 approval override
- 진행 중 turn의 `interrupt()`와 client 종료
- `TurnResult`의 final response, duration과 token usage
- 별도 `CodexConfig.codex_bin`을 지정하지 않을 때 bundled pinned runtime 사용

`ApprovalMode.deny_all`은 설치된 SDK 소스에서 app-server의 `approvalPolicy=never`로
변환된다. 생성된 내부 thread-start 응답 타입에는 approval policy와 sandbox가 있지만 공개
high-level `thread_start()`는 그 응답 대신 thread handle만 반환한다. 공개 `thread.read()`의
thread 모델도 `cwd`, model과 ephemeral 상태는 제공하지만 approval policy, sandbox 또는
도구 inventory를 제공하지 않는다.

## 차단 근거와 결정

설치된 공개 Python API에는 호출에 실제 적용된 shell, web search, MCP, plugin, app,
connector, skill과 sub-agent 도구의 effective inventory를 반환하는 계약이 없다. 또한 이 모든
범주를 호출별로 비활성화하고 그 결과를 다시 읽는 typed 공개 API도 없다. `thread_start()`의
임의 `config` 객체, 빈 `cwd`, read-only sandbox와 approval 거부는 개별 설정 선언일 뿐,
사용자 전역 설정이 금지 도구를 다시 활성화하지 못했다는 증거가 아니다.

따라서 `codex_isolation_not_enforced` gate를 통과시킬 수 없다. `codex_sdk` Provider와 실제
gateway adapter, readiness, 모델 등록·실행 경로는 구현하거나 등록하지 않는다. contract
요구사항을 완화하지 않는다. Task 1 feasibility RED 증거는 SDD report에 보존하고 정상
suite에는 실패 테스트를 남기지 않는다. 후속 구현은 pinned stable SDK가 호출별 effective
tool inventory와 모든 금지 범주의 비활성 상태를 공개 API로 증명할 때만 재개한다.

이 차단은 Python high-level SDK 경로에 적용된다. 같은 안전 기준을 유지한 별도 Codex App
Server 경계는 ADR-0011에서 후속 설계하며, 이 문서의 실패 증거를 삭제하거나 성공으로
재해석하지 않는다.

## 재개 시 유지할 안전 계약

- 인증은 SDK의 기존 Codex 인증만 재사용하며 token, 계정 식별자와 인증 경로를
  애플리케이션에 저장하거나 기록하지 않는다.
- 각 문맥화·생성 호출은 새 client, 새 ephemeral thread와 새 빈 임시 디렉터리를 사용한다.
- shell, web, MCP, plugin, app, connector, skill과 sub-agent는 모두 비활성화되어야 한다.
- sampling은 Provider-managed로 표시하고 temperature 지원을 꾸미지 않는다.
- output token usage가 없거나 수락 한도를 넘으면 결과를 폐기한다.
- 외부 전송 정책과 exact 관리자 승인 전에 질문·대화·Evidence를 전달하지 않는다.
- 다른 Provider나 모델로 자동 fallback하지 않는다.

## 비채택 대안

- 빈 `cwd`와 read-only sandbox만으로 격리를 성공 처리: 읽기 범위와 도구 존재 여부는 다른
  계약이므로 채택하지 않는다.
- 문서화되지 않은 config key 또는 내부 JSON-RPC method 사용: 버전 안전성과 공개 호환성을
  증명하지 못하므로 채택하지 않는다.
- 응답에 도구 사용 흔적이 없으면 도구가 비활성이라고 간주: 미사용과 비활성은 다르므로
  채택하지 않는다.
- 애플리케이션이 인증정보를 복사하거나 별도 시스템 `codex` 실행 파일을 탐색: credential
  비저장과 pinned runtime 계약을 깨뜨리므로 채택하지 않는다.
