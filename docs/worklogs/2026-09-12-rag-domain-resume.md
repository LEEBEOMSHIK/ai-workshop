# RAG 도메인 준비 차단 작업 재개

## 실제 상태

2026-09-12, main의 기존 변경을 보존하고 현재 로컬 DB를 읽기 전용으로 확인했다.
대상은 local / 127.0.0.1:15432 / ai_workshop_local_clean이며 스키마는 0030이다.

- 자산운용 도메인 존재, 비활성, 연결 버전 0개.
- RAG-TEST v2는 생성 프로파일 연결 있음, 평가 pending. 평가 실행/데이터셋/정책 0개.
- 합성 참조 자료 문서의 기존 public 승인 1건은 취소 상태.
- 전사·개인 공간 외부 전송 deny 유지, 합성 공간만 기존 Codex 허용 상태.
- 프론트 5173 HTTP 200, 백엔드 18000 `/api/v1/health`는 status=ok.
- Chrome의 RAG 검색 탭은 로그인 화면. 현재 인증된 관리자 UI 검증은 미수행.

이는 도메인이 삭제된 문제가 아니라 평가·연결이 아직 완료되지 않은 상태다.

## Task3 검증과 수정

기존 승인 복구 계획의 사용자 요청 API를 독립 검토했다. 새 승인 요청 모델이
Alembic env.py에 등록되지 않아 새 프로세스의 metadata에서 요청/멱등 영수증
테이블이 빠졌다. 향후 autogenerate가 실제 테이블을 삭제 대상으로 오인할 수 있다.

env.py에 해당 모델을 등록했다. 기존 API 테스트 파일에 독립 subprocess에서
실제 Alembic offline 환경을 실행하는 회귀 검사를 추가했다. DB 접속이나 이관을
실행하지 않는다. 수정 전에는 테이블 누락 assertion 실패, 수정 후에는 통과했다.

이번 검증 결과:

- 관련 단위: 승인 요청 API·승인 lifecycle·도메인 45 passed.
- `tests/integration/test_evidence_approval_requests.py`: 15 passed.
  기존 전용 임시 PostgreSQL fixture 사용, 종료 시 생성한 DB 정리. 실사용 DB 수정 없음.
- 요청 관련 Python 소스 6파일 mypy 통과, 요청 소스 및 env.py/변경 테스트 ruff 통과.
- 독립 재검토에서 차단 지적 해소. 변경된 payload의 request ID 재사용 및 member POST
  성공 경로 추가 테스트는 비차단 후속으로 분류됐다. Task4 UI와 실제 적용은 완료가 아니다.

첫 독립 unit 실행은 합성 SECRET_KEY 누락으로 1 failed/43 passed였다.
실행서의 합성 테스트 키를 지정한 뒤 통과했다. 실제 인증 키는 테스트에 사용하지 않았다.
Starlette의 기존 TestClient/httpx deprecation 경고 1건은 남아 있다.

## 실제 적용 인계

코드 검증과 실제 적용은 기존 승인 복구 계획과 실행서에 따라 분리한다.
다음 적용의 구체적인 대상/순서는 다음과 같다.

1. 위 로컬 DB의 0030 상태와 해당 API/승인·모델 실행 writer를 다시 식별한다.
2. writer를 일시 중단하고 프로젝트 비공개 `.local-data/backups/` 아래 별도 시각 이름으로
   전체 DB 백업과 복구 검증을 확보한다. 백업은 Git에 넣지 않는다.
3. 검증된 현재 코드와 `0031_evidence_reapproval` → `0032_evidence_approval_requests`를
   함께 적용한다. 프론트/백엔드는 호스트 실행을 유지한다.
4. 기존 설정의 18000 API를 다시 시작하고 health, 승인 목록/세대/이력 조회를 확인한다.
5. 사용자 명시적 문서 재승인 이후 기존 합성 자료로 구성 평가를 실행하고, 통과한 구성과
   허용 공간을 자산운용 도메인에 연결·활성화한 뒤 실제 대화/근거를 검증한다.

적용 중 잠시 API 이용이 중단된다. 기존 승인/취소 이력과 원본을 보존하며 이전 대기 호출
binding은 무효화된다. 데이터가 있는 상태의 downgrade는 차단되므로 장애 시 검증된
백업 복구 또는 순방향 수정을 사용한다. 문서 승인을 자동 복구하지 않는다.

이번에는 실제 이관·백업 생성·서버 재시작·문서 승인·모델 호출·commit/push를 하지 않았다.

## 후속 사용자 승인에 따른 실제 적용 완료

사용자가 위 백업·복원 검증·이관·재시작을 승인해 같은 날 수행했다.
기존 18000 API PID20332/launcher39808을 실행 경로와 활성 연결 부재로 식별 후 중단했다.
다른 Python writer는 없었고, 백업/실제 적용 직전 대상 DB의 다른 client 연결0을 확인했다.

- 백업: `.local-data/backups/reapproval-20260912/database.dump`, 413,124bytes.
  바이너리 pg_dump, SHA-256 별도 기록, Git 제외. Docker PostgreSQL 컨테이너와15432 매핑 확인.
- 전용 새 DB `ai_workshop_reapproval_restore_20260912`에 실제 pg_restore 완료.
  원본65테이블 전체 건수/행 지문 및 sequence 상태 일치. 복원본에서0031→0032 예행 통과.
- 동일 백업 이후 원본 변경 없음 재확인 후 실사용 DB에0031→0032 적용.
  기존63테이블·sequence 그대로, 승인 상태/이력 변환 불일치0. 구형 미취소 호출2건만 무효화.
  기존 취소 승인1건은 revoked/generation2 유지, 과거 취소 주체NULL 유지.
  호출 binding·기존 취소 시각 보존, 신규 요청/영수증0건, 불변 트리거의 테이블·활성 상태 확인.
- 기존 root.env 로더와 Selector uvicorn 설정으로 호스트 API 재시작.
  launcher5172/서버10724, 로그 `.local-data/dev-logs/reapproval-20260912-api.*.log`.
  최초 health는 시작 직후 연결 전이었고, startup 완료 후18000 및5173 프록시 모두status=ok.
  실행 OpenAPI에 요청 관련3경로 반영, 비인증 관리자 요청 조회401 확인.
- 독립 검증 담당이 새 읽기 전용 트랜잭션으로 실사용/복원본 보존 결과와 백업 해시를 재확인했다.
  이후 이번 작업이 만든 복원DB만 연결0·정확한 대상 재검사 후 제거, 백업은 보존했다.

백업 폴더의 before/backup/restore-verified/rehearsal/applied/recovery-cleanup.json에
상세 지문과 검증 결과를 보관한다. 원문·인증정보는 출력하지 않았다.
브라우저는 로그인 화면이라 인증된 관리자 승인 목록/이력 UI 확인은 아직 미수행이다.
문서 승인을 자동 복구하지 않았으며 평가·도메인 활성화·모델 호출·commit/push도 하지 않았다.

### 사용자 로그인 후 확인

마스터 모델 관리 화면 진입과 데이터 사용 범위·승인 탭의 존재를 실제 브라우저에서 확인했다.
이후 브라우저 제어 세션 초기화/재연결이 `orchestrator_helper_launch_failed` 및
`codex-windows-sandbox-setup.exe ... program not found`로 연속 실패했다.
이는 앱 로그인 오류가 아닌 도구 실행 오류다. 승인 탭 클릭/문서 목록 UI 확인은 미완료다.
DB 읽기 전용 재조회에서 취소 세대2와 승인/취소 이력2건, API health ok를 확인했다.
문서 재승인/모델 호출은 수행하지 않았다. 현재 UI의 `데이터 사용 범위·승인` →
`RAG 합성 참조 자료` → `문서 revision 불러오기`로 사용자 확인을 이어갈 수 있다.
