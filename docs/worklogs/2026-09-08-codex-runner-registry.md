# Codex 실행기 설정 registry

## 범위

승인된 개인 Codex exec 설계의 서버 소유 실행 설정을 구현한다.
계획: `docs/superpowers/plans/2026-09-08-codex-runner-registry.md`.
Python/AI 구현, 메인 합성 파일 검증, 독립 보안/privacy 검토로 책임을 분리한다.
main에서만 작업하고 사용자 `.env`·DB·문서·인증·서버·관리자 UI는 변경하지 않는다.

## 등록과 실행 준비의 구분

- 서버 설정의 명명된 runner 참조만 해석한다. HTTP endpoint나 임의 명령 문자열로 대신하지 않는다.
- 모델 ID는 기존 Deployment/Profile의 값이다. runner에 모델·임의 argv·credential 필드를 추가하지 않는다.
- 실행 파일 SHA-256, 기대 CLI 버전, 전용 작업 루트, 명시 환경변수와 예산을 typed 설정으로 관리한다.
- 조회는 파일과 경로를 읽기 전용으로 검사한다. 프로세스·모델·인증 조회나 임시 디렉터리 생성은 하지 않는다.
- 기대 버전은 운영자가 등록한 기대값이며 실제 버전 관측 증거가 아니다. 파일 검사만으로 ready를 올리지 않는다.
- 설정 fingerprint는 정확한 설정을 비교하기 위한 값이다. 호출 승인·동시 실행 제한·실제 실행 직전
  파일 재검사·CLI 설정 검증을 대신하지 않으며, 해당 배선은 후속 실행 경계에서 적용해야 한다.

## 공식 문서 대조

[OpenAI 설정 참조](https://learn.chatgpt.com/docs/config-file/config-reference)에서 추가 개발자 지침,
shell·multi-agent 설정과 프로젝트 지침 읽기 한도의 역할을 확인했다.
[비대화형 실행 문서](https://learn.chatgpt.com/docs/non-interactive-mode)에서 기본 사용자 설정 미로딩,
JSONL·출력 schema·ephemeral과 기존 CLI 인증 사용을 확인했다.
문서에 있는 옵션을 모두 사용하지 않는다. 프로젝트가 금지한 rules/관리 정책 우회는 추가하지 않으며,
이번 registry는 CLI 옵션을 조립·실행하거나 설치 버전의 적용 검증을 완료했다고 주장하지 않는다.

## 검증 기록

합성 파일·임시 경로만 사용한다. 실제 Codex 설치 파일이나 개인 인증 경로는 테스트 fixture로 사용하지 않는다.
- 구현 담당 TDD: 설정 미구현 6개 실패와 registry 모듈 부재를 확인한 뒤 구현했다.
  Windows 파일 정보 차이, canonical alias 중첩, 추가 필드명의 경로 노출을 재현·수정했다.
- 메인 재실행: 관련 pytest **126 passed, 4 skipped** (1.00s).
- 메인 전체 unit/contract: **1,390 passed, 4 skipped, 1 warning** (54.66s).
  warning은 기존 Starlette TestClient/httpx deprecation이다.
- `mypy src`: **220개 소스 파일 통과**. 변경 소스·테스트 4개 Ruff 및 변경 diff 공백 검사 통과.
- 독립 보안/privacy·계획/품질 리뷰: Critical/Important/Minor 확정 결함 없음, 제한된 단계 인계 승인.
- 실제 합성 파일로 해시·크기 제한·검사 중 성장/축소/동일 크기 변경·중첩·불변성을 확인했다.
  reparse 속성·canonical alias·OS 오류·handle identity는 모의 검사다. 실제 symlink 4건은 Windows
  생성 권한 부족으로 skip했으며 권한을 변경하지 않았다. 실제 junction/alias 성공 검증이라고 부르지 않는다.

Windows CPython 3.13에서 경로 `lstat`와 열린 handle `fstat`의 `.exe` mode·ctime 의미가 달랐다.
교차 비교에는 공통 identity/type/size/mtime/attribute를 쓰고, 각 API의 전체 metadata는 그 API의
전후 값끼리 비교한다. 정상 읽기로 바뀌는 atime은 제외한다. 이는 실행 시점의 모든 교체 경쟁 제거를 뜻하지 않는다.

추가 파일은 `generation/codex_runner_registry.py`와 대응 단위 테스트다. 기존 `config.py`에는
기본 빈 typed map·참조명 검증만 추가했고 `test_config.py`에는 환경 JSON 및 기존 HTTP 호환 검사를 추가했다.
새 의존성·migration·실제 설정 등록은 없다. 사용자 전체 RAG 테스트 요청은 아직 하지 않는다.

## 후속 연결 순서

1. registry의 검증 결과로 지원 CLI 설정·argv를 조립하고, 요청별 작업 경로의 생성·정리를 연결한다.
2. 호출 승인에 정확한 runner 설정 지문을 결합하고 실행 직전 재검사·동시 실행 제한을 적용한다.
3. 기존 생성 런타임과 관리자 연결 검사에 배선한 뒤, 승인된 합성 입력으로 실제 CLI 버전·모델 관측을 검증한다.
4. 자산운용 도메인·검색/생성 구성·권한을 맞추고 실제 화면에서 답변·인용·후속 질문·실패 안내를 확인한다.

이 단계가 끝나도 기본 runner 목록은 비어 있으며, 사용자의 `.env`나 관리자 모델 선택을 대신 변경하지 않는다.
파일 SHA-256이 일치한다는 것은 해당 조회 시점의 등록 파일 검사 결과다. 검사 이후 실행 전 교체 가능성을
완전히 제거했다거나, 선언된 CLI 버전·요청 모델을 실제로 관측했다는 의미가 아니다.
