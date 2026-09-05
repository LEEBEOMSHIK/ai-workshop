# Codex App Server 기반 개발용 RAG 생성 Provider 설계

- 상태: 승인됨
- 승인일: 2026-09-06
- 대체 대상: `2026-09-05-codex-sdk-rag-adapter-design.md`의 구현 경로
- 관련 결정: `docs/decisions/0010-development-codex-sdk-provider.md`,
  `docs/decisions/0011-development-codex-app-server-provider.md`

## 1. 배경과 결정

공개 Python Codex SDK는 호출에 실제 적용된 shell, web, MCP, app, plugin, skill과
sub-agent inventory를 다시 읽어 증명하지 못해 차단됐다. 안전 기준은 완화하지 않는다.

후속 개발용 Provider는 Codex App Server를 고정 버전 자식 프로세스로 실행하고, 프로젝트
전용 `CODEX_HOME`, 관리형 요구사항과 App Server 상태 조회를 조합해 실행 전 격리를
증명한다. stdio JSON-RPC만 사용하며 실험적 WebSocket transport는 사용하지 않는다.

이 Provider의 내부 식별자는 `codex_app_server`, 관리자 표시명은
`Codex 로컬 실행 환경`이다. 프로세스는 로컬에서 실행되지만 기본 Codex 모델 추론에는 질문,
제한된 대화와 선별 Evidence가 OpenAI로 전송되므로 외부 Provider로 판정한다. 개발 환경에서만
등록·선택·실행할 수 있고 운영 OpenAI Responses 등 다른 Provider에는 이 프로세스를
의존시키지 않는다.

## 2. 목표와 비목표

### 목표

- owner가 전용 Codex 계정 로그인과 안전 상태를 관리자 UI에서 확인한다.
- 질문과 Evidence 전송 전에 effective 격리 상태를 fail-closed로 검증한다.
- 문맥화와 답변 생성을 각각 새 임시 thread와 빈 임시 작업 디렉터리에서 실행한다.
- 기존 구조화 출력, Evidence 인용 hard gate와 외부 전송 정책을 재사용한다.
- 폐기된 답변은 노출하지 않되 원인 분석에 필요한 안전 진단 정보를 남긴다.
- 합성 데이터에서만 명시적으로 상세 진단을 허용해 회귀 테스트를 재현한다.

### 비목표

- Codex를 staging 또는 production Provider로 사용하지 않는다.
- 일반 사용자에게 Codex 로그인·로그아웃·격리 설정 권한을 주지 않는다.
- 프로젝트 코드, 원본 문서 저장소, 사용자 홈을 Codex 작업 공간으로 제공하지 않는다.
- shell, web, MCP, app, plugin, skill, connector와 sub-agent 사용을 허용하지 않는다.
- Codex thread를 애플리케이션 대화 기록의 정본으로 사용하지 않는다.
- 금지 동작이나 생성 실패 때 다른 모델·Provider·추출 답변으로 자동 전환하지 않는다.
- 다른 Labs가 필요하다는 측정 전 Platform 공통 모듈로 추출하지 않는다.

## 3. 구성요소와 경계

### CodexRuntimeSupervisor

- 설정에 고정된 exact Codex CLI 실행 파일과 버전만 시작한다.
- 애플리케이션이 소유한 프로젝트 전용 `CODEX_HOME`을 자식 프로세스에 전달한다.
- 요청별 빈 임시 `cwd`를 만들고 정상·실패·취소 모두에서 정리한다.
- App Server와 stdio JSON-RPC로 통신하고 시작, timeout, interrupt, 종료를 책임진다.
- 예상하지 못한 종료와 금지 이벤트 뒤에는 프로세스를 폐기하고 새 preflight 전 재사용하지
  않는다.

### CodexIsolationAttestor

질문·대화·Evidence를 보내기 전에 다음 상태를 읽어 하나의 attestation을 만든다.

- CLI와 App Server exact 허용 버전
- 전용 `CODEX_HOME` 및 관리형 requirements revision
- shell, web, apps, plugins와 multi-agent 기능 비활성
- 등록되거나 활성인 MCP server 없음
- 활성 skill과 hook 없음
- 호출 가능한 app·connector 없음
- 승인 정책 `never`와 read-only sandbox
- 선택 모델 exact 가용성
- 대상 thread에 실제 노출되는 built-in tool inventory와 금지 도구 0개

필수 항목을 조회할 수 없거나 한 항목이라도 허용 상태가 아니면
`codex_isolation_not_enforced`로 종료한다. 선언된 설정만 믿지 않고 App Server가 제공하는
현재 상태를 읽어 검증한다. 설치 버전에서 특정 범주의 effective 상태를 증명할 수 없다면 해당
버전은 허용 목록에 넣지 않는다. `features.shell_tool=false` 같은 설정값은 보조 증거이며 실제
thread tool inventory를 대신하지 않는다.

### CodexAccountGateway

owner 전용 로그인 시작, 로그인 상태, 로그아웃만 제공한다. 계정 이메일, account ID, token,
인증 파일과 `CODEX_HOME` 실제 경로는 API·DB·일반 로그에 반환하거나 복사하지 않는다.
프로젝트용 Codex 계정은 개발 머신에서 한 번 별도로 로그인하며 애플리케이션 사용자 계정과
구분한다.

### CodexAppServerGenerationRuntime

기존 `GenerationRuntimePort`를 구현한다. 입력은 현재 질문, 서버가 검증한 bounded history,
확정 검색 질의, 허용된 Evidence ID와 최소 본문 및 출력 schema뿐이다. 문맥화와 생성은 서로
다른 ephemeral thread로 실행하며 retry도 새 thread와 새 임시 `cwd`를 사용한다.

## 4. 요청 실행 흐름

```text
사용자·Workspace 권한
→ exact 저장 구성·Generation Deployment 해석
→ development 환경과 외부 전송 정책·승인 확인
→ Hybrid 검색·선택적 reranker·최소 Evidence 선택
→ Codex App Server preflight와 isolation attestation
→ 요청별 빈 cwd·새 ephemeral contextualize thread
→ 검색 질의 schema 검증
→ 별도 빈 cwd·새 ephemeral generate thread
→ 답변 schema·usage·Evidence citation 검증
→ 안전 감사·진단 기록
→ 검증된 답변만 반환
```

preflight 완료 전에는 질문, 대화 또는 Evidence 본문을 App Server에 보내지 않는다. 실행 중
command, 파일 접근, web search, MCP, app, plugin, skill, sub-agent, 권한 요청 또는 사용자
입력 요청 이벤트가 발생하면 turn을 interrupt하고 답변을 폐기하며 프로세스를 종료한다.

실행 중 탐지는 사전 격리를 대신하지 않는다. 금지 이벤트가 관측되면 이미 요청 또는 외부
동작이 시작됐을 가능성을 숨기지 않고 `possible_external_tool_execution`을 기록한다. 프로토콜이
실행 전 거절을 명확히 증명한 경우에만 false로 기록할 수 있다.

## 5. 구조화 출력과 폐기 기준

기존 문맥화·생성 JSON schema와 citation hard gate를 그대로 사용한다. 다음 중 하나면 초안을
사용자 응답, 대화 history 또는 정상 답변 저장소에 포함하지 않는다.

- JSON 파싱 또는 schema 검증 실패
- 허용 집합 밖 Evidence ID 인용
- 원문으로 추적할 수 없는 인용
- 출력 usage 부재 또는 프로파일 수락 한도 초과
- exact 모델 불일치 또는 모델 identity 검증 불가
- 금지 App Server 이벤트
- timeout, process failure 또는 불완전 cleanup으로 안전 완료를 증명하지 못함

Codex sampling은 Provider-managed로 표시한다. 지원하지 않는 temperature나 요청형 출력 제한을
지원하는 것처럼 표시하지 않는다.

## 6. 이중 진단 기록

`답변 폐기`는 사용자 노출과 정상 답변 저장을 금지한다는 뜻이며 진단 증거 삭제를 뜻하지
않는다.

### 항상 저장하는 안전 사건 기록

기존 실행·감사 기록에 연결된 진단 레코드는 다음 metadata만 저장한다.

- correlation/trace ID, 시각, duration과 실행 단계
- 안전 오류 코드, 위반 rule ID와 정확한 폐기 사유
- CLI/App Server/provider/model/deployment/profile version
- requirements·config revision 또는 비가역 hash와 attestation 항목별 판정
- 이벤트 method·item category·상태·순서와 안전한 도구 범주
- process exit code, timeout 단계, interrupt·quarantine 결과
- 질문·history·Evidence의 개수, 크기, token 수와 SHA-256
- JSON parse 결과, schema error path/code와 citation 검증 통계
- cleanup 성공 여부와 `possible_external_tool_execution`

질문·대화·Evidence·폐기 답변 본문, 명령·도구 인자와 출력, 전체 JSON-RPC payload, 내부 추론,
인증정보, 원본 exception과 로컬 경로는 저장하지 않는다. 관리자 사건 상세 화면은 trace ID로
이 안전 정보와 다음 점검 항목만 보여준다.

### owner가 명시적으로 켜는 상세 진단 모드

- development 환경에서만 사용할 수 있다.
- 합성 fixture 또는 공개 데이터로 표시되고 검증된 입력만 허용한다.
- 실제 비공개·사내·개인 문서와 일반 사용자 요청은 hard gate에서 거부한다.
- 전체 protocol event와 폐기 응답은 Gitignored 로컬 진단 저장소에만 암호화 또는 OS 접근
  제한 상태로 짧게 보존한다.
- 일반 DB, 애플리케이션 로그, Git과 학습 데이터에는 기록하지 않는다.
- 활성 상태와 만료 시간을 관리자 UI에 계속 표시하고 정책 만료 시 자동 정리한다.
- 경로와 보존 시간은 환경 설정으로 관리하고 실제 제거는 `CACHE_POLICY.md` 절차를 따른다.

운영 사건을 장기 학습 자료로 자동 전환하지 않는다. 가치 있는 합성 실패 사례만 owner가
비식별화 검토 후 `Learning`의 구조화된 실험·실패 기록으로 수동 승격한다.

## 7. 오류 계약

- `codex_runtime_unavailable`
- `codex_auth_required`
- `codex_isolation_not_enforced`
- `codex_model_unavailable`
- `codex_tool_activity_detected`
- `codex_response_invalid`
- `codex_output_limit_unverified`
- `codex_timeout`
- `codex_process_failed`
- `codex_cleanup_failed`

사용자에게는 안전한 설명과 trace ID만 반환한다. 관리자에게도 본문, token, 계정, 경로와 원본
오류를 노출하지 않는다. 실패는 다른 Provider나 모델로 자동 fallback하지 않는다.

## 8. 관리자와 사용자 UI

owner 전용 관리 화면은 다음을 제공한다.

- Codex App Server 설치·버전·프로세스 상태
- 프로젝트 전용 Codex 로그인, 상태 확인과 로그아웃
- isolation attestation 항목별 성공·실패와 마지막 점검 시각
- 현재 계정에서 조회된 exact 모델 선택과 연결 확인
- 개발 전용·외부 전송·계정 사용량 고지
- trace ID 기반 안전 사건 목록과 문제 해결 안내
- 합성 데이터 전용 상세 진단 모드의 명시적 시작·종료·만료 상태

일반 로그인 사용자는 저장 구성에 선택된 Provider, 사용자용 모델명·버전, 외부 전송 여부와
검증된 답변 또는 안전 오류·trace ID만 본다. 공개 방문자에게 데이터 입력, 생성 실행이나
진단 기능을 제공하지 않는다.

## 9. 테스트 전략

### 네트워크 없는 단위 테스트

fake App Server가 각 preflight 상태, 금지 이벤트, malformed JSON, 잘못된 citation, usage
부재·초과, timeout과 process exit를 주입한다. 모든 실패에서 답변 미노출, 다른 Provider
미호출, 안전 진단 생성과 민감 필드 부재를 함께 검증한다.

### subprocess·protocol 통합 테스트

- 고정 버전·전용 `CODEX_HOME`·stdio 시작
- config/requirements mismatch와 MCP·skill·app 활성 상태 차단
- contextualize/generate의 별도 thread·cwd
- mid-stream 금지 이벤트 interrupt·process quarantine
- timeout·crash·cleanup 실패와 trace 연결
- 상세 진단 모드의 합성 입력 gate, 만료와 일반 저장소 유출 방지

### 실제 로컬 smoke

자동 CI에서는 실행하지 않는다. owner 승인과 별도 Codex 로그인 후 공개·합성 문서만 사용해
정상 구조화 답변·인용, prompt-injection fixture, 모델 불일치, 금지 동작 탐지와 사건 화면을
확인한다. 실제 비공개 문서는 격리 구현의 시험 재료로 사용하지 않는다.

## 10. 수용 기준

1. 전용 Codex 로그인·설정은 기존 사용자 Codex 환경과 분리된다.
2. effective 격리를 증명하지 못하면 본문 전송 전에 실패한다.
3. 문맥화와 생성은 별도 ephemeral thread와 빈 임시 `cwd`를 사용한다.
4. 금지 이벤트가 발생하면 답변을 폐기하고 프로세스를 재사용하지 않는다.
5. 폐기 원인은 민감 본문 없이 trace ID로 분석할 수 있다.
6. 상세 protocol과 폐기 본문은 합성 데이터 진단 모드에서만 임시 보존된다.
7. 검증되지 않은 답변은 사용자·history·정상 답변 저장소에 들어가지 않는다.
8. 다른 모델·Provider·추출 답변으로 조용히 전환하지 않는다.
9. 운영 Provider와 staging·production 실행은 Codex App Server에 의존하지 않는다.
10. 자동 테스트는 외부 네트워크, 실제 Codex 인증과 민감 문서 없이 실행된다.
