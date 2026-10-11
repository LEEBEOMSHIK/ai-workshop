# RAG 권한·실패 저장 기능 경계 검증

2026-10-07. 본래 개발 환경의 기능 마감 후속이며 ISSUE-00005의 진행 근거다.

기존 답변에 대한 현재 SQL 권한 재검사와 실패 저장·재요청·복원·모니터링 계약을
검증했다. 실제 파일 첨부·인증된 모바일 화면과 실제 모델의 시간 초과는 미검증이다.
**아직 품질 개선만 남은 상태가 아니다.**

## 범위와 변경

- 메인 Codex가 테스트 구현과 통합을, 독립 담당자가 권한·개인정보 경계 검토와 원래
  자료 보존 검증을 맡았다. 모델·검색·청킹·승인 정책·DB 구조·서버는 변경하지 않았다.
- 기존 original failure integration을 실행했을 때 본래 DB0063과 테스트의 exact0061
  검사 불일치로 실패했다. 테스트를 현재 지원 스키마0063만 허용하도록 수정했다.
  migration·downgrade·임의 스키마 허용은 하지 않았다.
- SQL 예외의 파라미터 노출을 막고, 항상 예외를 발생시키는 시험 executor의 반환 타입을
  `Never`로 바로잡았다. 기존 잘못된 type-ignore로 발생한 mypy 오류2개는 해소됐다.
- `test_original_conversation_access.py`에 기존 실제 answered turn과 원문 identity를
  사용하는 두 권한 검증을 추가했다. 새 계정·환경·대화·모델 요청은 만들지 않았다.

## 실제로 확인한 계약

| 검사 | 확인 결과 | 증거의 한계 |
| --- | --- | --- |
| 회사 공간 읽기 권한 제거 | 기존 owner membership의 owner 예외와 읽기·쓰기·삭제 허용을 함께 제거하면 내부·외부 근거 접근 모두 거절 | 동일 트랜잭션 안의 SQL authority 검사이며 정상 revoke API·동시 세션·브라우저 경합 검증은 아님 |
| exact 근거의 외부 전송 승인 철회 | 내부 열람은 유지하고 외부 대화 이력 사용은 거절 | 기존 승인을 영구 철회하지 않았으며 provider 호출은 없음 |
| timeout·인용 검증 실패·예상하지 못한 오류 | 실패 저장, 동일 요청 재실행 방지, 재조회 복원, 안전 오류 코드와 모니터링 단계 기록 일치 | 시험 executor의 고장 주입이며 실제 provider deadline·취소·자식 프로세스 종료 증거는 아님 |

통합 검사는 본래 `.env`·DB0063·기존 계정과 연결을 사용했다. 모든 서비스 세션은
동일 connection의 savepoint에 연결하고 connection COMMIT을 금지했다. `finally`의
outer rollback 후 권한 테이블 해시와 새 SQL positive control을 다시 확인했다.
실패 시험의 합성 대화·turn·execution·요청 ledger는 롤백 후 남지 않았다.

## 실행 결과

- 변경 전 original timeout 사례: schema guard 불일치로 `1 failed` 재현.
- 최종 original access2 + failure3 통합: `5 passed`, 83.78초.
  명시적 opt-in 두 환경 변수로 `backend/tests/integration/labs/rag/executions/`의
  해당 두 파일만 실행했다. pytest의 `-p no:cacheprovider --tb=short`를 사용했다.
- 관련 백엔드 단위: access·final authority·attachment storage scope·first question의
  네 파일에서 `33 passed`, 9.83초. 외부 모델과 네트워크는 사용하지 않았다.
- 관련 프론트 단위: ConversationAttachments·ConversationPage·FirstQuestion·
  DocumentSelectionPanel의 네 파일에서 `92 passed`, 88.52초.
  frontend 디렉터리에서 login shell을 끄고 설치된 Vitest를 직접 실행했다. 최초 pnpm 호출은
  Vitest를 찾지 못해 테스트가 실행되지 않았고, 정상 호출과 구분했다. 최초 명령 해석
  실패의 정확한 원인은 확인하지 않았으며 패키지 재설치·환경 교체는 하지 않았다.
- 수정 테스트 두 파일의 Ruff와 mypy 모두 통과했다. 전체 저장소 테스트 통과를 주장하지 않는다.
- 독립 코드 검토 차단0. 테스트 실행 결과는 메인, 자료 보존 결과는 독립 담당자의 증거다.

## 독립 보존 확인

보고서 등록 전 fresh 기준선과 비교한 기존55 + 추가16, 총71개 테이블의 원래 행
SHA와 개수는 동일했다. 회사 membership·근거 승인 상태, 기존 대화5개·23턴,
동결 보고서12개 exact 파일/DB 본문, 모든 문제 행, 이전 평가·판정, 활성32와 pending128,
원래 환경·원본 합성 PDF3개, schema0063·별칭 frozen gate1/receipt0을 보존했다.
진행 중 실행은0이었다. 기존 프로세스3개의 실행 경로와 시작 시간은 같았으며
parent·cwd·env·전체 runtime 동일성까지 입증한 것은 아니다.

독립 읽기와 테스트 결과에는 원문·질문·답변·계정 식별자·비밀값을 저장하지 않았다.
임시 검증 자료와 정확한 문서 등록 영수증은
`.local-data/project-agent-work/rag-functional-boundary-verification-20261007/`에서 관리한다.

## 남은 기능과 다음 순서

문제 DB의 기존 remaining을 직접 대조했다. 날짜별 검증 범위를 추가하며 기존 상태나
남은 조건을 자동 완료로 바꾸지 않는다.

1. ISSUE-00002/03: 정상 기존 계정으로 실제 파일 첨부·저장 상태와 인증된 모바일 화면 확인.
   현재 Chrome은 로그인 화면이므로 미수행이다. 자동 UI 테스트를 실제 업로드나
   물리적인 드래그앤드롭 검증으로 대체하지 않는다. 개인 저장과 외부 답변 사용 권한은 구분한다.
2. ISSUE-00001: 실제 첫 질문 POST201과 다중 연결의 committed 경합·브라우저 ACL/취소 경합.
   기존 세션의 후속 POST200이나 이번 rollback 검증으로 완료 처리하지 않는다.
3. ISSUE-00005/18: 실제 모델 실행 중 취소·실패·시간 초과의 안전 사유·종료·측정·화면 일치,
   과거 미종료 turn의 종료 증거와 정식 복구. 현재 실행0은 과거 종료 증거가 아니다.
4. ISSUE-00013: 정확한 이전 별칭 작업의 실제 종료 proof·receipt·release·현재 DB 기준 fresh parity.
   동일 ES cluster의 새 별칭 예약·전송 차단은 유지한다.
5. ISSUE-00029: 승인된 보안 정책 안에서 DLL 차단의 영구 재발 방지와 원래 환경 재검증.
6. 필요한 기능 수정의 main·원격 반영과 실행 인계. 이번 작업에서는 staging·commit·push를 하지 않았다.

불필요한 유보·원문 일반화·정답률·지연 개선은 계속될 품질 작업이다. 기능 경계 마감 전에
SDK 도입·벡터 저장소 비교·로컬 LLM 학습을 앞당기거나 기존 후보를 승격하지 않는다.
