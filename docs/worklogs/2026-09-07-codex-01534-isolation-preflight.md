# Codex CLI 0.153.4 연결 사전 검증

- 날짜: 2026-09-07
- 요청: 로컬 개발용 Codex CLI 연결 및 관리자 UI 변경·관리
- 결과: 기존 ADR-0011의 스키마 선행 조건 미충족, 연결 구현 미진행
- 정본: [ADR-0011](../decisions/0011-development-codex-app-server-provider.md)

## 수행 범위

설치 버전을 `codex --version`으로 확인하고 다음 명령으로 해당 버전의 기본 비실험
프로토콜 스키마를 생성했다. 두 명령 모두 exit 0이다.

```powershell
codex app-server generate-json-schema --out .local-data/project-agent-work/codex-01534-preflight/schema
```

`--experimental`은 사용하지 않았다. 이 명령은 스키마 생성이며 live App Server 세션 시작,
인증 조회 또는 모델 호출이 아니다. 생성 명령의 성공이 격리 검증 성공을 의미하지 않는다.
질문·Evidence·대화 본문 전송, `thread/start`, `turn/start`, 로그인·로그아웃은 수행하지 않았다.
개인 Codex 설정·인증 파일을 읽거나 변경하지 않았다.

## 확인된 계약

| 확인 대상 | 제공 내용 | 부족한 증거 |
|---|---|---|
| ClientRequest의 99개 메서드 | thread·config·MCP·app·skill 등 | thread별 실제 built-in 도구 전체 목록 조회 없음 |
| ThreadStartResponse | approvalPolicy, approvalsReviewer, cwd, instructionSources, model, modelProvider, reasoningEffort, sandbox, serviceTier, thread | 실제 노출 도구 목록 없음 |
| ThreadReadResponse.thread | thread 상태·이력·모델 등 | 실행 전 전체 도구 목록 없음 |
| ThreadSettingsUpdatedNotification | threadId와 threadSettings | 설정 보고이며 도구 전체 목록이 아님 |
| MCP 상태 조회 | threadId 및 MCP 서버별 tools | built-in 도구 부재를 증명하지 못함 |
| ModelProviderCapabilitiesReadResponse | imageGeneration, namespaceTools, webSearch | provider capability 불리언이며 thread inventory가 아님 |

별도 `AttestationGenerateResponse`의 opaque client token도 실제 도구 목록 판정으로
간주하지 않았다. 설정 플래그와 실행 후 이벤트를 사전 증명으로 대체하지 않는다.
독립 보안 리뷰 담당이 생성 스키마와 승인 설계를 읽고 같은 BLOCK 판정을 내렸다.

## 재현 식별자

- CLI: `codex-cli 0.153.4`
- ClientRequest.json SHA-256: `25bc001b5dfe3b35785597b8f9ad9e5aaf7e437331fa9921f041c9e0e03fc9f3`
- v2/ThreadStartResponse.json SHA-256: `656f8fd0fe91f533126cbfdb9369cfab550927a229e48dd46460f6f015d2b186`
- 생성물: 프로젝트 전용 ignored 경로에 JSON 304개, 3,464,477 bytes.
- 이 생성물은 사용자 데이터가 아니며 캐시 정책상 정확 대상 삭제 승인 전에는 일괄 제거하지 않는다.

## 결론과 남은 선택

이는 Codex CLI가 일반적으로 연동 불가능하거나 모든 도구가 활성화됐다는 판정이 아니다.
**이 프로젝트가 요구한 실행 전 effective tool inventory 증명을 현재 확인한 계약으로
충족할 수 없다는 판정**이다. live 상태 검증은 선행 조건 실패로 시작하지 않았으므로,
0.151.0의 과거 live gate 결과와 혼합하지 않는다.

ADR-0011은 이 조건이 충족되기 전 Provider·DB·UI·본문 실행을 구현하지 않도록 한다.
따라서 연결 어댑터와 관리자 Codex 선택 항목을 추가하거나 기존 차단 코드를 제거하지 않았다.
원본 문서, 모델, 서비스 프로세스와 Docker도 변경하지 않았다.

Codex CLI를 유지하면서 현재 버전으로 진행하려면, 도구 목록 조회에 의존하는 설계를
대체할 격리 방식의 검토·승인이 먼저 필요하다. 전용 실행 환경의 OS 수준 파일·프로세스·
네트워크 접근 차단은 검토 후보이지, 이번에 검증되거나 승인된 해결책이 아니다.
단순 read-only·승인 never·빈 작업 디렉터리만으로 기존 보안 조건을 만족한다고 선언하지 않는다.

## 공식 문서 확인

- [App Server](https://learn.chatgpt.com/docs/app-server): stdio JSON-RPC, 버전별 생성 스키마,
  stable/experimental 구분과 제공 메서드를 확인했다.
- [Agent approvals & security](https://learn.chatgpt.com/docs/agent-approvals-security):
  sandbox와 approval의 역할이 서로 다름을 확인했다. 해당 설명을 이 프로젝트의
  금지 도구 0개 증명으로 확대 해석하지 않았다.

## 후속 재검토: 개인용 CLI 실험과 기존 격리 계약 분리

이 절은 당시 검토 결과다. 이후 사용자가 제한 실행의 잔여 위험을 수용하고 내부 통제 지침을
요구한 결정과 현재 상세 설계는 [ADR-0017](../decisions/0017-personal-codex-exec-provider.md)을 따른다.
아래 측정 결과를 수정하거나 실제 연결 성공으로 재해석하지 않는다.

- 요청: Codex CLI 방향을 유지하며 과도한 조건과 필요한 보호를 재검토한다.
- 상태: 읽기 전용 재검토 완료 / 제한 실험 후보의 위험 수용·설계 변경 승인 대기.
- 이번 검증: `git branch --show-current`는 main, `codex --version`은 0.153.4,
  `codex exec --help`는 exit 0. 모델 호출·인증 조회·설정 변경은 하지 않았다.

### 확인한 사실

설치 CLI 도움말에는 stdin 입력, `--json`, `--output-schema`, `--ephemeral`,
`--sandbox read-only`, `--ignore-user-config`, `--strict-config`가 있다.
`--ignore-user-config` 설명은 기본 config.toml 미로딩이며 인증은 CODEX_HOME을 계속 사용한다고
명시한다. 모든 설정·관리 정책·skill·hook·plugin의 미로딩 또는 비활성을 뜻하지 않는다.
`--strict-config`도 알 수 없는 필드 검출이지 도구 비활성 보증이 아니다.

[공식 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode)은 `codex exec`의
스크립트 연결, 저장된 CLI 인증 사용, 구조화 출력과 JSONL 이벤트를 지원한다고 설명한다.
이는 별도 자체 C# 실행기나 코드 서명을 Codex 연결의 일반 필수 요건으로 만들지 않는다.
현재 차단은 CLI의 연결 기능 부재가 아니라 ADR-0010/0011의 사전 전체 도구 목록 증명 조건이며,
그 대안으로 만든 자체 LPAC 실행기의 차단·수명주기 결함은 별개의 미해결 문제다.

### 개인용 실험으로 조정 가능한 범위와 유지할 보호

| 항목 | 재검토 판단 |
|---|---|
| 호출 전 모든 내장 도구 목록이 비어 있다는 증명 | 일반 CLI 연동의 필수 요건은 아니다. 제외하려면 기존 보장 수준의 변경을 명시 승인받아야 한다. |
| 자체 LPAC 실행기·유료 서명 | 제한된 신뢰 실행 실험의 필수 조건으로 두지 않는 후보. 기존 실행기를 우회 실행하거나 차단을 해제하지 않는다. |
| 사용 범위 | 개발 환경의 owner만, owner가 검토한 공개·합성 입력으로 제한. 일반 사용자·공개 서비스·비공개 문서는 제외. |
| 연결 후보 | 초기에는 App Server 상시 세션보다 `codex exec` 요청별 실행을 비교 검토. 기존 RAG가 선별한 최소 근거와 제한된 이력만 전달. |
| 설정·도구 | 고정 버전, 전용 실행 설정·빈 cwd, 최소 환경변수. shell·web·MCP·apps·plugins·skills·hooks·sub-agent 경로를 설치 버전별 점검. 관리형 요구사항을 우회하지 않는다. |
| 결과 처리 | 구조화 출력과 기존 인용 검증, timeout·출력 예산·금지 이벤트 실패, 자동 모델 전환 금지 유지. |
| 인증·외부 전송 | CLI의 공식 인증 경로를 사용하며 토큰 복사·추출·DB 저장 금지. 질문·이력·근거의 OpenAI 전송과 계정 사용량을 별도 고지·승인. |
| 대화 이력 | 애플리케이션을 정본으로 유지. 매번 필요한 문맥을 제공하며 개인 개발 세션 resume와 섞지 않는다. |

[공식 보안 문서](https://learn.chatgpt.com/docs/agent-approvals-security) 및
[설정 참조](https://learn.chatgpt.com/docs/config-file/config-reference)와 비교한 결과:

- read-only는 읽기 차단이 아니며 approval never는 도구 제거가 아니다.
- 빈 cwd와 사용자 기본 설정 미로딩은 호스트 비밀 파일의 접근 불가를 보증하지 않는다.
- 명령 sandbox의 네트워크 제한은 모델·인증·web·MCP·connector 통신 전체를 막는 정책이 아니다.
- JSON Schema는 출력 형식 제약이지 인용 사실성·도구 미사용 보장이 아니다.
- 이벤트 탐지 후 종료는 사후 대응이다. 의도치 않은 도구 동작의 부작용을 되돌리지 못한다.
- ephemeral은 세션 rollout 비저장이며 모든 로컬 로그·외부 보존의 부재를 보증하지 않는다.

### 독립 보안 검토와 다음 결정

독립 검토는 개인 owner-only 실험 후보로 재설계 가능하다고 판단했다. 공개 입력의 prompt
injection도 호스트 데이터 유출 위험을 만들 수 있어 공개·합성 자료라는 이유만으로 안전하다고
보지 않는다. 이 후보는 기존 완전 격리 계약을 달성한 것이 아니라 신뢰하는 CLI와 공식 통제에
의존하는 제한 실험이며, 호스트 읽기·의도치 않은 도구 동작의 잔여 위험 수용이 필요하다.

권고: Codex CLI 선택은 유지하고 위 제한 실험 범위의 변경 승인을 먼저 받는다. 승인 후
설계·ADR을 일치시킨 뒤 오프라인 adapter 계약 테스트, 명시 승인된 합성 모델 호출,
후속 질문·인용·실패 진단 검증 순으로 진행한다. UI에서 준비 완료로 표시하는 것은 이후다.
실행 설정 및 인증 경로의 실제 호환성, 모델 identity·사용량 이벤트, Windows 자식 프로세스
정리와 품질은 아직 검증하지 않았다. 모델 연결 성공 또는 추가 비용 0원을 보장하지 않는다.
현재 재검토 승인만으로 ADR 차단, Provider 등록·활성화 또는 실제 본문 전송을 변경하지 않는다.
