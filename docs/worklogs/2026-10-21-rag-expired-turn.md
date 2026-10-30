# 실행 기한 만료와 다음 대화 요청의 경합 수정

2026-10-21. 사용자가 [이전 점검](2026-10-21-rag-terminal-flow.md#별도-발견--15분-실행-기한-만료의-경합)에서 발견한 경합 수정을 승인했다. 12B/GPU 성능 개선은 보류하고 기존 실행 환경·자료·품질 기준을 유지한다.

## 원인과 범위

`Conversation.recover`는 15분이 지난 running 요청을 interrupted로 바꿨다. 다음 요청 예약은 running, 종료 미확인 cancelled 또는 명시적 provider 종료 오류만 차단했으므로 기존 executor가 정리되기 전에 다른 request ID로 새 실행을 시작할 수 있었다. 합성 저장소·실제 서비스 코드에서 재현한 결함이며 실모델 중복 호출을 관측한 기록은 아니다.

대화 상태 계약·서버·화면의 중간 위험 수정으로 분류했다. 메인이 RAG/AI 런타임·백엔드·프론트엔드·테스트 설계·설계 문서를 맡고 독립 담당자가 트랜잭션·실행 수명주기와 기존 기록 보존을 검토했다. 별도 DB·migration·배포·모델 설정은 범위 밖이다. 기존 dirty 작업을 보존하는 같은 작업 공간에서 진행했다.

## 변경

구현 전에 [ADR-0009](../decisions/0009-model-deployments-and-data-policy.md#2026-10-21-대화-실행-기한-만료와-종료-확인)와 [RAG 설계](../labs/rag/design.md)에 다음 계약을 반영했다.

- [도메인 상태](../../backend/src/ai_workshop/labs/rag/conversations/domain.py): 이번에 running에서 interrupted로 만료되며 종료가 미확인인 요청에만 `conversation_termination_unconfirmed`를 기록한다. 같은 request ID는 멱등 재조회하고 새 ID는 차단한다. 과거 failed/interrupted 기록은 소급 변경하지 않는다.
- [서비스 종료 처리](../../backend/src/ai_workshop/labs/rag/conversations/service.py): 해당 executor를 join하고 종료를 확인한 finalizer만 행 잠금 안에서 새 표식을 일반 중단 코드로 바꾼다. HTTP 시도가 여전히 미확인이면 `provider_termination_unconfirmed`로 기록하고 차단을 유지한다. 만료 저장과 예약 거절 트랜잭션은 분리한 기존 구조를 유지한다.
- 만료 후 늦은 답변은 중단된 요청의 결과로 저장·반환하지 않고 관측 결과도 answered로 남기지 않는다. 기존 interrupted 상태를 completed로 승격하지 않는다.
- [화면 상태 판단](../../frontend/src/features/rag/conversation/turn-state.ts): 서버의 두 종료 미확인 표식을 모두 적용한다. 다음 질문·남은 재시도를 차단하고 상태 새로고침과 입력 보존을 유지한다. 안내는 모델 호출 전에도 정확하도록 ‘이전 요청의 실행 종료’로 바꿨다.

## 검증

[도메인 회귀](../../backend/tests/unit/labs/rag/conversations/test_domain.py), [새 수명주기 회귀](../../backend/tests/unit/labs/rag/conversations/test_expired_execution.py), [화면 회귀](../../frontend/src/features/rag/conversation/ConversationTermination.test.tsx)를 먼저 추가했다. 수정 전 백엔드19개 중7개가 실패했으며, detail/submit 만료와 로컬/HTTP 미확인 조합4개에서 새 실행을 잘못 허용했다. 늦은 답변은 별도 재실행에서 관측 결과 answered 불일치를 확인했다. UI9개 중4개는 새 표식의 전송·재시도 차단2건과 변경할 안내 문구2건에서 실패했다.

서비스 검사는 실제 ConversationService와 트랜잭션 commit/rollback을 모사하는 메모리 저장소를 사용한다. 합성 시각을16분 전으로 설정하고 이벤트로 실행 정리를 멈춰 경합을 재현한다. 실제15분 대기·모델·네트워크·업무 DB 없이 다음을 확인한다.

- 새 요청409, 같은 요청 재조회, 반복 만료와15분 정확한 경계, 과거 기록 허용 의미.
- submit이 먼저 만료시킨 뒤 revision409를 반환해도 만료 표식 보존.
- 실행 정리 전/중, 반복 취소 후에도 새 실행 차단과 정확한 executor 호출 수.
- 종료 확인 뒤 다음 질문 허용, HTTP 미확인 뒤 계속 차단, 저장·재조회 일치.
- executor 시작 전 만료와 finalizer 종료 확인, 늦은 답변의 저장·반환·관측 일치.

주요 검증 결과:

- 백엔드 핵심19개 통과. 관련 conversations/executions와 로컬 HTTP·취소·생성 결과 검사390개 통과. [결과](../../.local-data/project-agent-work/rag-expired-turn-20261021/backend-regression.xml).
- 프론트엔드 conversation/executions: 19파일157개 통과. [결과](../../.local-data/project-agent-work/rag-expired-turn-20261021/frontend-regression.json).
- 프론트엔드 전체 TypeScript `--noEmit --incremental false`, 변경3파일 ESLint 통과. 변경 Python4파일 Ruff 통과.
- 백엔드 전체 Mypy484파일 통과. 새 작업별 Mypy 캐시는 만들지 않았다.
- 독립 검증: 백엔드25개(기존/신규19개와 별도 경계6개), UI9개 통과. 실제 SQL 저장소의 잠금 메서드와 모의 트랜잭션으로409 rollback 이후 만료 저장 보존을 확인했다. 만료 후 취소·삭제, 권한 거절/예외, 관측 실패 경계도 확인했다. 제품 차단 결함은 발견하지 않았다. 실제 DB·네트워크·모델 검증은 아니다.

[독립 최종 리뷰](../../.local-data/project-agent-work/rag-expired-turn-20261021/independent/final-review.md)와 [검증 결과·소스 SHA](../../.local-data/project-agent-work/rag-expired-turn-20261021/independent/final-review.json)를 확인했다. 검토한 구현·테스트·설계11파일의 SHA가 같고 작업 기록만 최종 수치로 갱신했다. 작업 시작19파일 중 이번 공유 수정5파일을 제외한14파일은 SHA가 유지됐다. 최근 완료 목록5개, 문서의 로컬 링크 대상과 `git diff --check`도 확인했다. [마감 검사](../../.local-data/project-agent-work/rag-expired-turn-20261021/postcheck.json).

백엔드는 승인된 기존 Conda Python으로 실행했다. 초기 전체 검증 명령의 존재하지 않는 테스트 경로와 Mypy package 진입 오류는 실제 파일명·`mypy src`로 바로잡았다. 새 테스트의 관측 완료 플래그는 메모리 Recorder에 DB 조회기가 없으므로 저장 비교에서 제외하고, 상태·오류·종료 확인·답변과 별도 observer 결과를 검사한다.

독립 검사에서는 Windows 이벤트 루프의 로컬 self-pipe 소켓 생성이 차단되어 첫 실행12개가 setup에서 실패했다. 독립 테스트 전용 socket-free 루프를 명시한 뒤25개를 통과했으며 제품 실행 환경·정책은 변경하지 않았다. 메인의390개 검사는 기존 정규 루프로 통과한 별도 결과다.

## 한계와 보존

실행 소유 작업이 사라져 finalizer가 종료를 확인할 수 없는 새 만료 요청은 계속 차단된다. 새로고침이나 경과 시간만으로 자동 해제하지 않는다. 과거 취소/미종료 작업의 정식 복구 API는 이번 수정에 포함하지 않는다.

실제 로그인 브라우저→API→DB→모델 검증, 본래 서버 반영 후 종료 수용은 미실행이다. 모델·임베딩·업무 HTTP·DB 호출0, 설치·다운로드·서비스/worker 기동·도메인 활성화0이다. 운영 문제 이력 DB의 등록·연결은 미완료로 남기고 임의 문제 번호를 만들지 않는다. 기존 자료와 다른 미커밋 변경을 보존하며 커밋·푸시는 하지 않았다.

## 최근 완료 목록에서 이동한 기록

최종 입력/답변 진단·A/B/C 비교(2026-10-19): 실제12회 모두 완료, 정상 품질0/2씩·거절2/2씩. [당시 결과](2026-10-19-rag-v5-evaluation-preparation.md). 역사 기록이며 이번 수정에서 재실행한 결과가 아니다.
