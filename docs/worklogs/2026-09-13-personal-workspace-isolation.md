# 개인 파일함 소유자 격리 보완

## 범위와 원인

통합 파일함 쓰기 확장 전 선행 보안 작업이다. RAG 검색은 개인 공간 생성자를 검사했지만,
Platform 일부 경로는 멤버십과 만료만 검사했다. 잘못 부여된 타인 멤버십이 있으면 원문·목록·쓰기·작업 상태에
접근할 가능성을 격리 합성 DB에서 재현했다. 실제 사용자 자료 유출이 확인됐다는 의미는 아니다.

## 변경

- `platform/workspaces/repository.py`: 기존 membership·active 조건에 더하는 공통 개인 소유자 SQL 조건.
  개인 공간 존재 검사는 생성자 기준이며, 본인 membership 누락을 새 공간 생성으로 복구하지 않는다.
- `platform/assets/{repository,library_repository,originals}.py`: 목록, 정확한 문서/버전, 원문·미리보기,
  다운로드, 폴더 생성·업로드의 기존 권한 검사에 적용한다. 원문 최종 재검사도 동일하다.
- `platform/jobs/repository.py`: 사용자 처리 상태/오류 metadata 조회에도 적용한다. 신뢰된 worker 경로는 유지한다.
- 글로벌 관리자와 잘못된 OWNER membership도 타인의 개인 공간을 우회하지 못한다.
- 회사/team/temporary의 기존 membership·만료 계약은 유지한다. 승인 요청은 기존 개인 소유자 검사가 있어
  production 변경 없이 member/owner × personal/expired/membership 회귀를 강화했다.

## 검증

구현 책임자와 독립 보안/코드 리뷰 책임자를 분리했다. 사양·품질 최종 리뷰 통과, Critical/Important 없음.
신규 격리 회귀는 수정 전 3건 실패에서 수정 후 통과했다. main 재실행 결과:

```powershell
backend/.venv/Scripts/python.exe -B -m pytest -c backend/pyproject.toml backend/tests/integration/platform/assets/test_personal_workspace_isolation.py backend/tests/integration/platform/assets/test_asset_library.py backend/tests/integration/platform/assets/test_asset_originals.py backend/tests/integration/test_evidence_approval_requests.py --basetemp=C:/projects/ai-workshop/.local-data/test-results/personal-isolation-main/run-2 -q --tb=short
```

27건 통과(69.28초). 기존 UUID 격리 DB fixture의 생성·migration·정확한 이름 검증·종료 삭제를 재사용했다.
실사용 DB에 테스트 계정이나 문서를 넣지 않았다.

```powershell
backend/.venv/Scripts/python.exe -B -m pytest -c backend/pyproject.toml backend/tests/unit/platform/workspaces backend/tests/unit/platform/assets backend/tests/unit/platform/jobs backend/tests/unit/labs/rag/retrieval/test_scope.py backend/tests/unit/labs/rag/domains/test_library.py --basetemp='\\?\C:\projects\ai-workshop\.local-data\test-results\personal-isolation-main\unit-2' -q --tb=short
```

86건 통과(4.17초), 기존 Starlette/httpx 경고 1건. 첫 main 실행은 긴 임시 경로의 Windows MAX_PATH로
8건 실패했고 extended path를 사용한 재실행으로 통과했다. 테스트용 경로 수정이며 제품의 파일명/저장 계약 변경은 아니다.
대상 Ruff는 backend 작업 디렉터리에서 통과했다. 루트 실행은 first-party import 분류가 달라 실패하여
작업 디렉터리를 바로잡았으며 불필요한 import 변경은 하지 않았다.
구현 책임자의 전체 production strict mypy는 265개 파일 통과했다.

## 로컬 반영과 보존

기존 실행기 신원을 확인한 뒤 API18000만 재시작했다. 직접 및 frontend5173 proxy health200,
비로그인 workspace 조회401을 확인했다. 프론트·worker·DB·Docker는 재시작하지 않았다.
실사용 workspaces, workspace_memberships, documents, asset_versions, rag_evidence_approval_states,
rag_evidence_approval_events 6개 테이블의 건수·행 지문을 시작 시점과 최종 테스트/재시작 후 대조해 동일함을 확인했다.
새 의존성·환경·migration·모델 호출·사용자 승인 변경·commit/push는 없다.

## 남은 경계

- 다음은 전사 읽기/쓰기/삭제 권한과 동시 변경 충돌 계약, 이후 통합 관리 UI다.
- 폴더 탐색/미리보기는 대화의 필수 선행 단계가 아니다. 공간·폴더·개별 파일 범위 선택을 유지한다.
- 이번 PDF 검사는 권한 선차단이며 실제 PDF/OCR 처리 성공을 새로 검증한 것은 아니다.
- 실제 로그인 브라우저·LLM 답변·평가·도메인 활성 연결은 별도 검증이 남았다.
- 테스트 소스와 합성 공개 PDF는 보존 대상이다. 실행 임시물은 CACHE_POLICY의 별도 조사·승인 경계를 따른다.
