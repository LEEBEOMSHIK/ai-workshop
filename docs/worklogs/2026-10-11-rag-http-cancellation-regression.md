# RAG HTTP 어댑터 취소 회귀 보강

2026-10-11. RAG 안정화의 모델 failure/timeout/cancel 하위 검증 한 건이다.
제품 기능 수정이나 실제 모델 종료 검증을 완료했다는 의미가 아니다.

## 최신 확인과 선정

- README·설계·WORKBOARD·관련 계획/작업 기록과 실제 두 HTTP 어댑터 및 기존 테스트를 대조했다.
  `.agents/skills`는 이 체크아웃에 없었다. 추적된 하위 AGENTS는 없었다.
- 기록상 최근 완료는 source 연결 조회·보호 파일·TLS 수명주기 일부다. ISSUE-00013은
  최신 저장소 기록에서 open/r33이고 native 조립·역사 종료·보안 전환·별칭 복구·첨부 READY는
  미완료다. 이번에는 운영 DB를 조회하지 않았으므로 현재 DB 상태를 재확인한 값은 아니다.
- 작업 상태 도구에서 같은 저장소의 `다음 작업 확인`은 커밋 검증 도중 interrupted/notLoaded,
  학습 구조 작업은 idle이었다. 다른 대화의 커밋 요청을 이번 작업의 승인으로 사용하지 않았다.
- 시작 시 main에 461개 변경 파일이 있었다. 임시 디렉터리에 파일별 SHA와 Git 상태,
  WORKBOARD 원본을 보관하고 쓰기 전 대조했다. 기존 제품·테스트 파일은 수정하지 않았다.
- 기존 timeout/HTTP 오류 테스트는 있었지만 요청·재시도 대기에서 task 취소를 검증하는
  사례는 두 HTTP 테스트 파일에 없었다. 운영 상태 변경 없이 추가 가능한 이 범위를 선택했다.
- 낮은 위험의 테스트 전용 변경이다. 메인이 테스트 설계·AI 런타임 계약 확인·통합을 맡고
  별도 독립 코드 리뷰어가 검토·재실행했다. UI·DB·배포·권한·공개 계약 변경 역할은 제외했다.

## 구현

`backend/tests/unit/labs/rag/generation/test_http_cancellation.py`를 추가했다.
두 HTTP 어댑터 × generate/contextualize × 요청 중/timeout 재시도 대기/429 재시도 대기의
12사례에서 CancelledError 전파, task 취소 상태, 요청 1회와 finally 실행을 확인한다.
Event로 진입 지점을 맞추고 최대 대기 검사 후 정리하므로 실시간 sleep에 의존하지 않는다.
MockTransport와 기존 합성 fixture만 사용하며 외부 모델·소켓·DB를 호출하지 않는다.

## 실행한 검증

backend 디렉터리의 기존 `.venv/Scripts/python.exe`를 사용했다.

- `-B -m pytest tests/unit/labs/rag/generation/test_http_cancellation.py tests/unit/labs/rag/generation/test_openai_compatible.py tests/unit/labs/rag/generation/test_openai_responses.py -q --tb=short`: 최종 **83 passed**, 0.84초.
- 새 파일 `ruff check`, `ruff format --check`: 통과.
- `MYPYPATH=backend/src`, `mypy --strict --explicit-package-bases --follow-imports=silent` 새 파일: **1 source file 통과**.
- 독립 리뷰: 차단 지적 없음. 최종 새 파일 독립 재실행 **12 passed**, 0.63초.
- 메모리 내 결함 주입: 두 어댑터의 요청 예외 처리를 BaseException으로 바꾸면 요청 취소
  4사례가 provider_invalid_response로 실패했다. backoff 취소를 삼키면 8사례가
  `Provider did not propagate cancellation`로 실패했다(16.61초). 소스 파일 변경은 없었다.
  이후 깨끗한 프로세스의 최종 83통과를 확인했다.
- 최초 새 테스트는 없는 contextualization 인자를 전달해 6실패/6통과였고 인자를 수정했다.
  첫 backoff 변이는 테스트 namespace에 CancelledError가 없어 8실패했으므로 유효한
  결함 탐지 증거로 세지 않았다. namespace 보존과 bounded wait 보강 후 위 8실패를 확인했다.
- 최종 파일 보존 검사에서 별도 동시 변경을 감지했다:
  `evaluation/test_generative_failure_metrics.py` 수정,
  `evaluation/test_generative_workflow.py`와 `executions/test_citation_failure_diagnostics.py` 추가
  (모두 `backend/tests/unit/labs/rag/` 아래). 이번 작업은 이 파일들을 수정하지 않았고
  검사·완료 범위에서 제외한다. 초기 461파일 중 WORKBOARD와 위 동시 수정1개를 제외한
  459파일은 SHA가 동일했다. 최신5개·UTF-8·로컬 문서 링크 검사는 통과했다.

## 미실행과 남은 경계

실제 provider 실패/timeout/cancel·원격 실행 종료, Codex 자식 프로세스 종료, DB 저장·복원,
첫 질문/권한 committed 경합, 웹 E2E, 전체 저장소 테스트는 실행하지 않았다.
새 제품 결함을 확인한 작업은 아니며 ISSUE-00005/18의 실제 실행 완료 조건은 유지한다.
DB 변경 금지 범위이므로 관리자 문제 이력 등록·상태 변경은 미수행이다.

커밋·푸시·마이그레이션·DB/ES/Docker·서버·보안 설정·학습 진도·알림 예약을 변경하지 않았다.
기존 ISSUE-00013 역사 source map/종료 증거와 전체 native 연결의 미완료 기록을 유지하며
새 승인이나 receipt가 있다고 가정하지 않는다. 다음 독립 후보는 기존 Codex 실행 경로의
취소·deadline mock 회귀 보강이다. 실제 RAG 마감 후 Agents SDK → 벡터 저장소 비교 →
로컬 LLM 파인튜닝 → Kubernetes 순서를 유지한다.

## 최근 완료 목록에서 이동한 기존 기록

5. Kubernetes 학습·실습 후속 등록(2026-10-08): 현재 앱에 적용할 배포·통신·설정·복구·확장·영속 저장소 및 Compose 비교·학습 기록/흐름도 단계를 정리했다. 본래 자료/계정 보존과 OS 의존성·자원·실제 검증·원복/산출물 기준을 포함했다. 계획 등록이며 설치·실습·운영 전환은 미착수다. [계획](docs/superpowers/plans/2026-10-08-kubernetes-learning.md).
