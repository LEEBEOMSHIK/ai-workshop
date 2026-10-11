# RAG 모니터링 원문 접근·문제 이력 후속 검증

2026-10-04 사용자 재개 요청에 따라 기존 RAG 기능 마감 중 모니터링 접근 경계를 검증한다. 기존 main 작업 공간·본래 환경·마스터 계정·자료를 보존한다. 새 환경·계정·색인·모델 호출·배포 변경은 없다.

## 작업 범위와 역할

메인 Codex는 기존 브라우저 확인·관리자 DB 등록 준비·검증 결과 통합을 담당한다. 독립 보안 검증 담당은 기존 SQL 저장소와 ConversationAccess·ExecutionReadService를 사용하는 원문 revision/projection 비노출 시험만 작성·실행한다. 제품 코드 변경은 범위에 없으며 UI·인프라 구현 역할은 제외한다.

2026-10-04 직접 API health/readiness와 프론트 경유 health200을 재확인했다. 기존 관리자 탭에서 이력 URL 진입은 로그인으로 돌아갔고 이메일·비밀번호는 비어 있었다. 기존 마스터 재로그인을 요청했다. 로그인하지 않은 상태에서 직접 SQL로 문제 이력을 등록하거나 가짜 세션을 만들지 않는다.

## 화면 자동 검증

다음 명령을 실제로 실행했다.

```powershell
pnpm --dir frontend test run src/features/rag/executions/ExecutionMonitoring.test.tsx src/features/rag/configurations/EvaluationExecutionDiagnostics.test.tsx src/features/issue-history/IssueHistoryPage.test.tsx src/features/issue-history/api.test.ts
pnpm --dir frontend typecheck
```

4파일 **20통과**(29.54초, 종료 코드0), TypeScript 종료 코드0이다. 모니터링 표시·진단 열기·필터/전체 통계와 문제 이력의 버전 표시·멱등 저장·revision 충돌 처리의 자동 검증이며, 실제 로그인·모델·브라우저 E2E를 대신하지 않는다.

본래 API의 비로그인 접근도 확인했다. 문제 목록·관련 문서 목록·실행 상세 GET과 실행 검색 POST가 각각401을 반환해 관리자 인증 경계를 유지했다(4요청, 종료 코드0). 실행 상세에는 임의 합성 UUID를 사용했고 기존 실행 본문이나 사용자 질문을 읽지 않았다. 이 결과는 인증 없는 접근 거부이며 로그인 사용자의 원문별 접근 검사와 별개다.

## 관리자 DB 등록 준비

`.local-data/project-agent-work/rag-monitoring-source-access-20261004/issue-registration-proposal.json`에 원인이 다른 두 결함(관측 완료 판정 덮어쓰기, SQL 조회 조기 반환의 세션 정리 지연)과 기존 연결 준비 문제의 후속 이력 내용을 준비했다. 문제 번호·카테고리 UUID·문서 버전은 만들지 않았다. 현재 수정은 미커밋이므로 출처 커밋을 임의로 기록하지 않는다.

관리자 로그인 후 기존 문제 검색으로 중복을 확인하고, 정확한 기존 하위 카테고리에 등록하거나 동일 원인의 문제에 사건을 추가한다. 기존 문서 ID·버전 연결을 보존하고 최신 본문은 반환된 새 문서 버전에만 연결한다. 아직 DB 반영 완료가 아니다.

## 본래 SQL 검증 결과

본래 loader·기존 schema0061·COMMIT 거부·SAVEPOINT·outer rollback 경계를 사용한다. 합성 DB 메타데이터로 source의 준비 상태·수명주기·정확한 revision/projection 조합 불허 시 상세404와 목록·집계 비노출, 같은 서비스의 재조회 복구를 확인했다. 이전 답변의 근거 접근 불허가 후속 질문 의존성에도 전파되는지 확인했다. 독립 담당 실행은5통과(38.25초), 메인 Codex의 재실행은5통과(37.46초)이며 모두 종료 코드0이다.

새 `backend/tests/integration/labs/rag/executions/test_original_monitoring_source_access.py`는 기존 owner·읽기 가능한 workspace와 profile ID만 읽고 합성 Document1·AssetVersion2·Projection2·retention policy1·trash batch1·conversation1·turn2·execution2의12행을 외부 트랜잭션 안에서 만든다. 본문·파일·ES·모델은 사용하지 않고 기존 자료·권한·계정·실행 행을 수정하지 않는다.

5조건은 원본 버전 failed, projection failed, 문서 trashed, 버전/projection 조합 불일치2종류다. 합성 READY 기준에서는 부모·자식 실행2건과 시간 통계를 조회한다. 각 제한을 nested transaction에서 적용하면 부모 상세·legacy 조회404, 목록/오류 건수/시간 집계0을 확인한다. 자식은 자체 원문 참조가 없어 직접 ConversationAccess 검사에는 허용되지만, 부모 의존성 확인으로 상세·legacy·목록에서도 숨겨진다. 이 구분을 명시적으로 assert해 의존성 검사가 실제로 실행됨을 확인한다.

nested rollback 뒤 같은 service에서2건과 통계를 복원하고 outer rollback 뒤 합성12행 잔존0을 확인했다. 기존 기록과 합성 질문을 구분하는 무작위 접수 UUID를 검색 조건에 사용해 기존 대화 본문을 결과로 출력하지 않는다. SQL 오류의 원시 매개변수·로컬 계정 식별자를 출력하지 않도록 `--tb=no --assert=plain`을 적용했다.

재실행 명령(저장소 루트 PowerShell):

```powershell
@'
import os
import pytest
for key in list(os.environ):
    if key.upper().startswith('AI_WORKSHOP_'):
        del os.environ[key]
os.environ['AI_WORKSHOP_VERIFY_ORIGINAL_MONITORING_SOURCE_ACCESS']='1'
raise SystemExit(pytest.main(['-c','backend/pyproject.toml','backend/tests/integration/labs/rag/executions/test_original_monitoring_source_access.py','-q','--tb=no','--assert=plain','-p','no:cacheprovider']))
'@ | backend/.venv/Scripts/python.exe -
```

메인 Codex는 전체 테스트 파일을 별도로 읽고 합성 행만 제한되는 SQL·source triple 연결·자식 의존성 검사·리스트/통계·rollback 전후 assertion을 검토했다. 제품 코드 변경은 없다. 본래 source 자료상태와 정확한 참조 조합에 대한 검증이며 다른 사용자의 workspace 권한 회수 시험은 포함하지 않는다.

## 남은 게이트

관리자 DB 문제 등록·정확한 문서 버전 연결, 실제 모델 실패와 브라우저 신규 이력/새로고침, ISSUE-00013 종료 증빙·정상 parity, 실제 첨부·모바일·Git/실행 인계는 완료되지 않았다. 현재 workspace 권한과 원문 상태/정확한 조합 검증을 구분하고, workspace 권한 회수나 다른 사용자 공간 접근을 이번 시험으로 과장하지 않는다. 기존 RAG는 아직 품질 개선만 남은 단계가 아니다.

## 정적 검사와 인계

새 시험 파일의 Ruff와 Mypy가 통과했다. 최초 root cwd Mypy 실행은 editable 패키지를 py.typed 없는 라이브러리로 취급해 import-untyped16건을 반환했다. 검사 프로세스에만 MYPYPATH=backend/src와 backend/pyproject.toml을 지정해 재실행한 결과1파일 오류0이다. 제품 코드나 원래 실행 환경/.env는 변경하지 않았다. 전체 제품 회귀·외부 모델 오류를 이 결과로 주장하지 않는다.

최근 완료 항목은5개로 유지하며 상세 근거는 이 문서에 연결했다. 두 결함과 연결 복구 이력 초안은 아직 DB 등록 대기이며, 관리자 로그인 이후 실제 번호·문서 ID/버전을 반환받아 기록한다.
