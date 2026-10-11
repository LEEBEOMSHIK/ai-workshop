# RAG 예산 한 변수 비교 구현 계획의 준비와 독립 검토

- 기준일: 2026-10-07
- 관련 문제: ISSUE-00005
- 상태: 승인된 설계의 구현 계획 준비·검토 완료. 작성된 계획의 사용자 검토 대기이며 비교 helper 구현·본래 입력 비교·후보 생성·실모델 실행은 아직 시작하지 않았다.
- 산출물: [승인 설계](../superpowers/specs/2026-10-07-rag-context-budget-isolation-design.md), [4단계 구현 계획](../superpowers/plans/2026-10-07-rag-context-budget-isolation.md)

## 확정한 실행 범위

첫 단계는 생성 없이 기존 검색·근거 선택을 조합해 동일한 원문과 추출 결과에32/128 예산을 비교한다. 요청별 embedding cache를 공유하되 두 번째 delegate 추가 호출/항목0, 적격·순서·점수 동일과 원문 전체 보존을 검사한다. 현재 권한과 READY exact 원문 버전·alias/build는 fresh READ COMMITTED READ ONLY 세션으로 재확인한다. 긴 보존 snapshot을 현재 권한 확인에 사용하지 않는다.

총량 증가 자체는 필요한 근거 복구가 아니다. 기존 authoritative rule의 inner OR/outer AND 의미를 유지하고128의필요근거충족·32의unit-budget만으로누락·fullchunk보존·원문의대상/조건/예외검토를 모두 확인한 사례가 있어야 새 후보를 준비한다. 관련성 미달·충돌·없는 속성을 예산 문제로 바꾸지 않는다.

기존pure-v4/128 generation만 재확인·재사용하고 활성 answer policy 업무 값을 고정한 새 pending configuration을 정상 API로 만든다. 기존128 configuration은 semantic 임계값이 달라 직접 비교하지 않는다. 새 생성 승인·exact 연결 검증·평가 입력 동의는 각각 정상 계약에 결속하며 옛 approval/proof/판정을 복사하지 않는다.

제한된 사례는 SYN-Q01·Q02·Q03·Q04·Q13·Q15의6개다. 원래3합성 PDF와 로컬 정답표를 사용하며 query/정답은 이 문서나 helper 결과에 기록하지 않는다. 정상 authoring snapshot이 반환하는 새 case UUID에 query SHA·expected original IDs·rule digest를 메모리로 재결속한다. 사례당 최소2회라 평가12회이며, exact 후보 연결 검증의contextualization1+generation1을 포함한 실제provider최대14회로 고정했다. history는비어있고 재시도·다른 모델 대체·추가검증·새75회는 하지 않는다.

답변의 숫자가 허용되어도 다른 대상·기간·조건의 값을 차용하면 독립 의미 실패로 남긴다. 정상 서비스 E2E와 cache를 공유한 반사실 입력 비교의 시간은 구분한다. 성공해도 승격·기본 연결 변경·본래 대화/멀티턴 성공을 주장하지 않는다.

## 책임과 독립 검토

메인은 요구/RAG/시스템 경계·테스트 설계·문서를 정리했고 독립 담당은 서비스/API 계약·원문/권한/전송 승인·실행 상한과 보존 경계를 읽기 전용으로 검토했다. UI·파서·DB 스키마·provider·서버 변경은 제외했다. 기존 역할 selector는 요구/행동·공개 경계·RAG·privacy·설계 신호의 필수5역할을 반환했으며 테스트 설계 책임을 추가했다. 기존 메인 직접 구현·독립 검증 방식을 유지한다.

독립 초안 검토의 중요2개를 반영했다. 첫째, 실제 조회 전과 새configuration POST 전에 독립 사전 보존 기준선을 만들고 새 artifact의 한정 whitelist를 정했다. 둘째, 단순 선택량 증가를 필요근거 복구로 오인하지 않도록 authoritative groups와 원문 검토 조건 및 테스트를 추가했다. 수정판의 설계/서비스/API/호출/권한/동일 cache/새case/보존 계획 차단 의견은0이다. 마지막 정밀화로 정상 issue 사건·문서 연결 추가의 revision/updated_at 변경과 새 인증세션을 명시적 예외로 두되 기존 issue의status/업무fields/사건/문서 연결은 보존하도록 했다.

## 이번에 실행한 확인과 미실행 경계

기존 코드의 실제 함수·타입·schema를 읽어 계획 인터페이스를 대조했고 역할 계약 selector를 본래 가상환경에서 실행해 exit0을 확인했다. 4단계 계획과 관련 문서의 UTF-8·로컬 링크·공백·미완성 표기·최근 완료 최대5개 및 scoped diff 검사는 마감 단계에서 실행한다. 제품 코드 변경이 없으므로 기존 애플리케이션 테스트나 전체 타입/린트를 반복하지 않았다. 지난 설계 단계의18회귀는 과거 검증이며 이번에 새 비교 테스트를 통과한 것으로 보고하지 않는다.

이번 범위의 비교 helper/fixture·새configuration/profile/snapshot/run/judgment·provider 호출·대화/원본 변경·서버 재시작·Git staging/commit/push·삭제는0이다. 문서 갱신과 정상 문제 이력 추가만 수행한다. 이 보고서의 exact v1을 ISSUE-00005에 연결하고 기존 필드/사건/문서 버전을 보존하는 등록 결과는 task-local receipt에 별도로 남긴다. 과거9개 동결 보고서는 수정하지 않는다. 독립 담당의 코드/계획 검토와 메인의 정상 API 전후 보존 검사는 서로 다른 증거이며 이 작업에서55테이블의새독립사전baseline을 생성했다고 주장하지 않는다.

## 다음 인계

`writing-plans`의 Execution Handoff는 “ask them to review the plan and confirm it captures what they want; wait for that review before implementation”을 요구한다. 따라서 작성된 계획 검토 후 보존된 메인 직접 구현 방식으로 Task1부터 실행한다. 방법 선택을 다시 요청하지 않는다.

ISSUE-00005의근거부족, 본래 유효 답변/성공한멀티턴·권한철회·첨부/모바일·실모델실패/timeout·별칭종료·DLL재발방지·Git인계는 열린 조건이다. 품질 개선만 남은 상태가 아니며 SDK·벡터 저장소 비교·로컬 LLM 학습의 후속 순서는 바꾸지 않는다.
