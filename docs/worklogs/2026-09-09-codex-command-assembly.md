# Codex CLI 요청 조립

## 범위

기존 실행기 registry·CodexCallIntent·정확한 CodexExecutionPayload를 하나의 불변 실행 요청 계획으로
결합한다. Python/AI 구현과 독립 보안/privacy 검토를 분리하고 main의 다른 변경은 보존한다.
계획: `docs/superpowers/plans/2026-09-09-codex-command-assembly.md`.

이 단계의 산출물은 프로세스 실행 허가가 아니다. schema 파일 생성·요청 디렉터리 정리,
영속 승인에 runner 지문 결합·동시 실행 제한·실행 직전 파일 재검사와 런타임 연결은 후속 범위다.
관리자 설정, 사용자 DB, 모델 선택과 readiness는 변경하지 않는다.

## 확인한 CLI 계약

2026-09-09 설치 실행 파일의 `--version`은 `codex-cli 0.153.4`, `exec --help`는 exit 0이었다.
이 두 읽기 전용 명령 외에 CLI 세션·모델·인증 조회는 실행하지 않았다. 개인 인증/설정 파일을
읽거나 복사하지 않았고, 서버 환경과 사용자 `.env`도 변경하지 않았다.

[공식 비대화형 실행 문서](https://learn.chatgpt.com/docs/non-interactive-mode)와
[설정 참조](https://learn.chatgpt.com/docs/config-file/config-reference)를 조회했다.
stdin·JSONL·출력 schema·ephemeral·사용자 기본 config 미로딩 옵션 및 추가 developer 지침,
shell·multi-agent·apps·hooks·web 설정의 의미를 대조했다.

지원 옵션 조립과 실제 유효 설정 검증은 다르다. 이 계약은 MCP·skills·plugins 및 관리 계층을
포함한 전체 도구 미노출 증명이 아니다. 검증되지 않은 blanket switch를 추정해서 추가하지 않는다.
관리 정책/rules와 sandbox를 우회하는 옵션은 사용하지 않는다. 실제 연결 전에 해당 버전의
유효 설정과 출력·모델 관측을 검증해야 하며, 충돌·증거 부족이면 readiness 차단을 유지한다.

## 데이터와 실행 경계

- 모델 ID는 기존 호출 intent에서 받는다. 특정 모델을 기본값으로 코드에 고정하지 않는다.
- 질문·이력·근거는 승인 대상 stdin 원본 bytes 그대로 유지하며 argv나 schema 파일에 넣지 않는다.
- 신뢰된 내부 지침/schema hash가 intent와 다르면 명령을 조립하지 않는다.
- TOML 문자열 인코딩은 shell quoting과 구분하고 Unicode·개행·따옴표·역슬래시를 검사한다.
- Windows 명령 길이 한계를 넘으면 지침을 자르거나 제거하지 않고 명시 실패한다.
- 요청 경로의 구문 검사만 수행한다. 경로의 실제 소유권·reparse 여부는 후속 파일 수명주기에서 검사한다.
- runner 설정 지문과 payload 지문은 후속 승인 비교 입력이지 그 자체로 승인 증거가 아니다.

## 검증 기록

- TDD: 조립기 모듈 부재 RED → 82개 GREEN. 예약 이름 수정은 12개 실패를 먼저 재현한 뒤 GREEN.
- 메인 최종 관련 검사: **218 passed, 4 skipped** (2.13s).
- 메인 최종 전체 unit/contract: **1,492 passed, 4 skipped, 1 warning** (68.26s).
- 전체 `mypy src`: **221개 소스 파일 통과**. 변경 소스/테스트 4개 Ruff 통과.
- 4개 skip은 기존 Windows 실제 symlink 생성 권한 제한이다. 경고는 기존 Starlette/httpx deprecation이다.
- 독립 보안/privacy·계획/품질 리뷰 및 수정 재검토: 예약 이름·권한 문구 두 지적 해결, 남은 결함 없음.
- 기존 프롬프트 생성기의 실제 합성 envelope 연결, TOML round trip, exact byte/hash,
  명령 길이, immutable 환경, 경로 및 오류 노출을 검사했다. 모델 호출·파일 수명주기 E2E는 아니다.

추가 파일: `generation/codex_command.py`, 대응 `test_codex_command.py`.
기존 registry와 그 단위 테스트는 동일 예약 이름 검사 보정만 변경했다. 의존성 추가 없음.
main의 미커밋 변경으로 유지하며 staging/commit/push/worktree 생성·삭제는 하지 않았다.
전체 RAG 사용자 테스트 가능 선언은 하지 않는다.

### 독립 리뷰에서 발견한 경로 검사 누락

초기 전체 검사 1,472개와 정적 검사는 통과했지만, 독립 검토가 `COM¹`, `LPT².txt`, `CON .txt`를
일반 경로처럼 수용하는 반례를 재현했다. 예약 이름 정규식이 ASCII 숫자만 다루고 확장자 앞 공백을
놓친 것이 원인이다. 실제 파일·장치 접근은 수행하지 않았으며 순수 문자열과 builder 호출로 확인했다.
동일 검사를 사용하는 기존 registry도 함께 수정하는 것으로 범위를 명시하고 사용자에게 고지했다.
Python 3.13의 Windows 예약 경로 판정을 사용하고 경로 이탈·UNC·device namespace 거절은 유지한다.
이 사례는 기존 테스트 수가 많아도 OS 경계의 누락을 독립 반례 검토로 찾아야 한다는 기록이다.
