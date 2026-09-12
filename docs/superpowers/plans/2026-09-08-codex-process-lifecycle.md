# Codex 요청 프로세스 수명주기 구현 계획

**Goal:** 승인된 Codex exec 연결의 Windows 요청 소유 프로세스 실행·회수 기반을 구현한다.
**Architecture:** RAG generation 내부의 비노출 process adapter다. CLI 의미 해석·권한·DB/API와 분리한다.
**Tech Stack:** Python, Windows Job Object, ctypes, pytest. 새 패키지는 추가하지 않는다.
**Spec:** `docs/superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md` §6·§10.2.

## 경계

main에서만 작업하고 기존 변경을 보존한다. 자동 commit/push·정책 우회·인증 파일 조회·실제 모델 호출은 이 단위에 없다.
실제 CLI 활성화에는 별도로 argv/설정·권한·전송 허가·identity·schema 검증이 필요하다.
이번 프로세스 테스트에는 Python으로 만든 합성 자식만 사용한다.

## Task 1: Windows 요청 소유 실행기

파일: `backend/src/ai_workshop/labs/rag/generation/windows_process.py`,
필요한 ctypes 선언은 같은 디렉터리 `windows_process_native.py`로 분리한다.
테스트: `backend/tests/unit/labs/rag/generation/test_windows_process.py`.

입력은 executable/argv, cwd, 명시적 env, stdin bytes, timeout·출력 byte 한계, 취소 신호다.
출력은 exit code·bounded stdout/stderr·종료/회수 결과이며 본문은 repr와 오류에 노출하지 않는다.
오류는 안정 코드만 반환한다. 실행기는 서버 내부 코드만 호출하고 외부 API에 임의 명령 실행을 노출하지 않는다.

- [x] RED: 미구현 실행기 대상으로 합성 echo·nonzero·timeout·취소·큰 stdout/stderr·자식 잔류 테스트를 작성한다.
- [x] suspended 상태 생성 → kill-on-close Job 배정 → resume. 배정 실패 시 실행하지 않고 닫는다.
- [x] 직접 argv 실행, 명시적 환경, 제한된 pipe 소비, 정상/실패/취소/timeout의 모든 종료 경로를 구현한다.
- [x] 남은 Job 자식을 회수하고 실제 active process count 0 확인 전 성공을 반환하지 않는다.
- [x] 실 Windows에서 fake parent/child 회수와 byte 한계·취소를 검증한다. 전체 프로세스 이름 기반 kill은 금지한다.
- [x] pytest·Ruff·mypy와 독립 보안 리뷰를 수행한다.

결과: Windows 합성 13개·전체 unit/contract 1,072개·mypy 213개 파일·관련 Ruff 통과.
독립 재검토에서 스레드 시작 실패의 Job count 0과 handle close 3회를 확인했고 신규 중요 결함은 없다.
전체 Win32 실패 조합 또는 실제 CLI 준비 완료를 검증한 것은 아니다.

## Task 2: CLI 접합 준비 확인

메인이 설치된 0.153.4 help와 공식 설정 문서를 대조해 신뢰된 argv·환경·schema 경계를 확인한다.
실행기만 통과했다고 실제 CLI 준비 완료로 표시하지 않는다. 이후 전용 외부 임시 cwd, 개인 설정 미로딩,
공식 인증, 실행 직전 승인 snapshot, 이벤트 allowlist와 실제 모델 증거 검증을 접합한다.
모델 ID는 선택 설정에서 받으며 최초 사용자 선택은 `gpt-5.5`다.

## 검증 명령

```powershell
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/unit/labs/rag/generation/test_windows_process.py -q
backend/.venv/Scripts/python.exe -m mypy --config-file backend/pyproject.toml backend/src
backend/.venv/Scripts/python.exe -m ruff check backend/src/ai_workshop/labs/rag/generation backend/tests/unit/labs/rag/generation
```

기존 미완료 LPAC Canary Supervisor는 변경하지 않으며 새 구현의 검증 증거를 별도로 확보한다.
