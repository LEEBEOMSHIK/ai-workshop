# Codex CLI 응답 수신과 실행 경로 점검

## 범위

승인된 개인용 exec 설계의 다음 단계다. 최초 요청 모델은 `gpt-5.5`이고 합성 전송/계정 사용량
동의는 확보했다. 이번 단위는 응답 수신 계약과 로컬 실행 경로 확인이며 실제 모델 추론은 아직 수행하지 않는다.
구현 정본: `docs/superpowers/plans/2026-09-08-codex-event-contract.md`.

## 설치 경로 확인

기본 `codex` 명령은 NVM 심볼릭 링크를 거친다. 기존 Windows runner는 경로 조상의 링크도
거부하므로 서버 registry에는 점검된 실제 패키지 실행 파일을 등록해야 한다. PATH 별칭을
업무 코드에 고정하지 않는다. 패키지 manifest의 layoutVersion 1, version 0.153.4,
target x86_64-pc-windows-msvc, entrypoint bin/codex.exe를 확인했다.

실제 파일을 기존 WindowsProcessRunner로 `--version`만 실행했다. 명시 환경은 SystemRoot,
stdin은 비었으며 결과는 codex-cli 0.153.4, exit 0, cleanup_verified True, 잔류 Job 프로세스 0이다.
인증 파일·개인 설정은 애플리케이션이 조회하지 않았고 모델 질문은 보내지 않았다.
이는 실행 파일 호환성 증거이며 안전한 모델 설정·호스트 격리·실제 답변의 증거가 아니다.

## 공식 계약 대조

[OpenAI 공식 비대화형 문서](https://learn.chatgpt.com/docs/non-interactive-mode)의 예시는
thread/turn/item 이벤트와 usage를 제공하지만 실제 응답 모델 ID 필드는 보여주지 않는다.
예시 부재만으로 설치 CLI가 해당 증거를 절대 제공하지 못한다고 단정하지 않는다.
수신기에는 임의 모델 필드를 발명하지 않으며 요청 모델 복사로 기존 identity 검증을 대체하지 않는다.

[공식 설정 참조](https://learn.chatgpt.com/docs/config-file/config-reference)에서 shell/hook/
multi-agent 비활성 설정과 reasoning 표시 설정을 확인했다. 문서 확인은 설치 버전의 실제 적용
검증과 별개다. 공개 문서에서 max_output_tokens 설정은 확인하지 못했으므로 추정 key를 넣지 않는다.
수신기 사용량 제한은 응답 수용 한계이며 서버 측 생성 비용의 사전 상한이라고 표현하지 않는다.

## 남은 연결 조건

- CLI 설정/임시 요청 경로/실행 직전 전송 허가와 스트리밍 수신기 접합.
- 실제 호출의 모델 identity·출력 schema 호환성·사용량 검증.
- Provider/관리자 실행 설정·자산운용 Hybrid/공간/도메인 연결 및 평가.

DB·문서·도메인 상태·서버 프로세스·인증 설정은 변경하지 않는다.

## 구현 중 검토와 개선

수신기는 단일 turn의 순서·최종 메시지·사용량과 총/행/이벤트/토큰 한계를 검사한다.
잘못된 입력에는 안정 오류만 반환하고 모델 ID는 미확인으로 남긴다. 초기 메인 검토에서
필수 필드 포함 관계 검사, 비정상 JSON 후 실패 상태 유지, 잘못된 event type과 null 사용량
처리를 보완했다. 독립 검토에서는 다음 경계를 추가로 재현했다.

- 예외 객체를 수신기에 저장하면 traceback이 원시 chunk/event를 붙잡는다. 오류 코드만
  상태에 남기고 호출별 새 예외를 발생시키는 방식으로 수정한다.
- CRLF가 CR/LF 사이에서 나뉘어 수신될 때 행 한계 결과가 달라졌다. 미완성 줄바꿈에 대한
  한 바이트 처리를 명시하고 chunk 분할과 무관하게 판정하도록 수정한다.

두 수정의 신규 회귀를 포함한 42개 테스트, mypy 214개 파일, 관련 Ruff가 통과했다.
독립 재검토에서 오류 코드만 보관하는 방식과 CRLF 경계의 수정이 확인됐고 새 확정 결함은 없다.
메인 최종 전체 unit/contract 1,114개가 통과했다. 기존 Starlette/httpx 사용 중단 경고 1개는 유지된다.
