# 과거 취소 요청의 종료 상태 재검증

2026-10-21. 사용자의 재시험 요청으로 기존 취소 요청의 저장 상태와 실제 로그인 화면을 다시 확인했다. **현재 종료·차단 회귀는 통과했지만, 과거 취소 요청 1건의 종료 미확인 상태는 그대로다. 문제없음 또는 복구 완료로 판정하지 않는다.**

## 본래 환경 결과

16:25~16:27 KST에 기존 환경을 조회했다. [DB 이전](../../.local-data/project-agent-work/rag-cancel-recheck-20261021/database-before.json)·[이후](../../.local-data/project-agent-work/rag-cancel-recheck-20261021/database-after.json)와 [대조](../../.local-data/project-agent-work/rag-cancel-recheck-20261021/comparison.json)를 남겼다. 연결·트랜잭션을 읽기 전용으로 제한하고 SELECT 후 rollback했다. 기본 상태와 대화별 집계는 별도 트랜잭션의 관측이며 전체 DB의 원자적 스냅샷은 아니다.

| 확인 | 실제 결과 |
|---|---|
| 대상 대화 | 기존 `fea91839-4107-469d-9aef-7543b1f78d68`, 요청 1건·revision 3 |
| 요청 상태 | `cancelled` / `execution_terminated=false` / `conversation_cancelled` |
| 실제 화면 | ‘취소를 요청했습니다. 실행 종료 확인 중입니다.’ 유지 |
| 상태 새로고침 | 정상 UI에서 1회, 이후 상태·revision·안내 동일 |
| 현재 서비스 | API health `ok`, ready `ready`, Ollama 적재 모델 0 |
| 실행·대기 집계 | 저장된 running 0, 기존 queued job 1 유지 |
| 데이터 보존 | RAG 8테이블 행수·집계 지문, 대화 revision·상태 동일 |

[UI 관측](../../.local-data/project-agent-work/rag-cancel-recheck-20261021/ui-observation.json)과 [실제 화면](../../.local-data/project-agent-work/rag-cancel-recheck-20261021/cancelled-after-refresh.jpg)을 저장했다. 도메인 준비 미완료와 기존 Codex CLI 실행 지원 종료도 함께 표시됐다. 따라서 비활성 버튼만으로 종료 상태 단독의 차단을 분리 입증하지 않는다. 입력 보존과 신규 실제 생성·취소·종료 후 다음 질문 수용은 미검증이다. 현재 running/적재 모델이 없다는 사실을 과거 개별 실행의 종료 증거로 사용하지 않는다.

## 코드와 회귀 결과

현재 [대화 상태](../../backend/src/ai_workshop/labs/rag/conversations/domain.py)의 recover는 기한이 지난 running만 처리한다. 과거 cancelled·종료 미확인 건은 조회나 시간 경과로 바뀌지 않는다. 같은 request ID는 저장 결과를 반환하고 새 요청은 `conversation_busy`로 차단한다. [서비스](../../backend/src/ai_workshop/labs/rag/conversations/service.py)의 실행 소유 finalizer가 실제 정리를 기다려 종료 표식을 저장하는 경로와, 과거 고립된 요청을 복구하는 경로는 다르다. 이번에 후자를 추가하거나 상태를 강제로 바꾸지 않았다.

- 화면 2파일 **47개 통과**: `ConversationPage.test.tsx` 38개, `ConversationTermination.test.tsx` 9개. [실행 결과](../../.local-data/project-agent-work/rag-cancel-recheck-20261021/frontend-tests.json).
- 독립 서버 회귀 4파일 **53개 통과**: terminal cleanup cancellation, expired execution, conversation domain, HTTP cancellation.
- 독립 합성 과거 취소 사례 **1개 통과**: 반복 조회·재취소·동일 요청 재조회 뒤에도 상태 보존, 새 요청 차단, executor/preflight 호출 0 확인. 실제 대상 ID·본문을 테스트에 사용하지 않았다.
- [독립 보고서](../../.local-data/project-agent-work/rag-cancel-recheck-20261021/independent/final-review.md)는 실제 DB 전후·화면·메인의 47개 결과를 별도로 대조했다. 독립 재실행 수는 54개이며 화면 47개를 여기에 중복 합산하지 않는다.

프론트엔드는 기존 Vitest, 백엔드는 본래 `backend/.conda/python.exe`를 사용했다. 테스트의 저장소·executor·HTTP는 합성 메모리/MockTransport이며, 실제 모델이나 업무 DB를 사용한 생성·취소 시험이 아니다. 제품 코드는 변경하지 않았다. 기존 미커밋 자료와 품질 기준·연결·모델 설정을 보존했다. 추가 생성·임베딩·업무 재전송·큐 처리·DB 직접 변경·서버 재시작·설치·커밋·푸시 0이다.

## 판정과 기록

새 회귀 실패를 발견하지 않았고, 종료 근거 없이 다음 실행을 허용하지 않는 현재 계약은 통과했다. **과거 요청의 정식 복구 기능 미완료는 재확인됐다.** 실제 해당 실행의 종료 또는 미기동 근거와 정상 복구 절차가 필요하다. 새로고침·재취소·서버 재시작만으로 해제됐다고 보고하지 않는다. 모델 답변 품질 문제 및 별칭·첨부 복구는 이번 검증 대상과 별개다.

정상 관리자 UI에서 기존 [ISSUE-00018](http://127.0.0.1:5173/admin/system/issues?issue=1f096dc4-c484-466c-93e3-150b7424a9ce)에 재시험 이력을 추가했다. ‘구현됨·검증 남음’과 기존 이력·문서를 보존한다. 정확한 문서 등록 버전과 본문 대조는 [등록 영수증](../../.local-data/project-agent-work/rag-cancel-recheck-20261021/issue-record.json)에 기록한다.

## 최근 완료 목록에서 이동한 기록

인용 값 검사·배열 후보 구현(2026-10-19): 관련 1,665통과/4skip·독립234통과. 서버 반영은 별도이며 실제 D 비교는 당시 결과를 따른다. [기존 구현 기록](2026-10-19-rag-relation-improvement.md). 이번에 재실행한 결과가 아니다.
