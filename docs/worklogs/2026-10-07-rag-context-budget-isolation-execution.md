# RAG 문맥 예산 분리 구현·실행 검증 (2026-10-07)

상태: 비교·검증 helper 구현, 제한 평가 실행 및 독립 보존 확인 완료, **실제 답변 검증 불통과**. 이 보고서는 정상 문제 이력 API에 등록할 exact v1 원문이다. 활성32 구성은 유지하며 후보를 승격하지 않는다.

정본 연결: [승인 설계](../superpowers/specs/2026-10-07-rag-context-budget-isolation-design.md), [구현 계획](../superpowers/plans/2026-10-07-rag-context-budget-isolation.md), [문제 이력 규칙](../issues/README.md).

## 구현과 검증

본래 작업소에서 task-local 비교기, 읽기 전용 검색 조합, 정상 API 후보·스냅샷·제한 평가 조합, 독립 판정 기록·집계 helper를 구현했다. 제품 선택 알고리즘과 UI·파서·migration·모델 의존성은 변경하지 않았다.

- 같은 요청의 임베딩 cache와 전체 원문 EvidenceUnit을 공유해32/128단위 예산을 비교한다. 8그룹·12000자 제한과 모든 업무 설정은 고정한다. 원문을 자르거나 ID·표 관계를 새로 만들어 통과시키지 않는다.
- 6사례 전체의 첫 scope/state를 고정한다. 후보 POST 직전에는 독립 보존 감사의55테이블·동결10보고서·원본3PDF·환경·gate·활동 해시와 실제 Elasticsearch alias/index UUID를 다시 대조한다.
- 후보는 기존 cap-only128 generation을 재사용하는 새 pending 구성 하나다. 승인·연결 검증·평가 입력 동의를 각각 정상 API로 결속한다. 새 snapshot 사례 UUID·정확한 highlight·result digest를 확인한다.
- 자동 규칙 판정과 독립 원문 의미 판정을 분리하며 completed를 passed로 세지 않는다. interrupted는 종료 상태로 집계하고 workflow 반환 뒤 실제 상태를 조회한다.
- helper 회귀47개, 기존 budget trace/context generation 회귀11개, Ruff와 mypy9파일 검사 통과. 테스트는 합성 입력·fake port만 사용했고 외부 모델·DB 쓰기를 사용하지 않았다.

## 독립 코드 검토와 판단

독립 전체 코드 리뷰의 Important3건·Minor2건을 모두 한 번의 TDD 수정 패스에 반영했다. 자동 규칙 provenance, 사례 사이·후보 준비의 기준선 결속, 정확한 highlight·기존 UUID 전체 배제, interrupted 집계, workflow claim 이후 상태 조회에 대한7개 회귀가 수정 전 실패하고 수정 후 통과했다. 수정 중 문법 괄호 하나와 양성 규칙 테스트의 필수 근거 그룹 누락도 바로잡았다. 보류한 Minor 항목은 없다.

실제 보존·원문 의미·API 승인/readiness·provider 수·단계 시간/bytes/사용량은 정적 리뷰가 판단하지 않았으므로 실제 실행과 별도 독립 검증으로 확인한다. 강제 동시 claim·timeout 경합과 범위 밖 WIP 전체를 재현한 것으로 보고하지 않는다.

진행 판단은 다음과 같다. 별도 환경/worktree와 Git 변경 없이 본래 작업소를 사용하고, 새로 동결된 계획 보고서도 포함해 기존 보고서10개를 보호한다. 정적 검사는 실제 backend/src 타입을 사용한다. 검증은 승인 범위의 회귀에 집중하며 전체 저장소 회귀를 통과한 것으로 주장하지 않는다. 과거75회 평가의 terminal failed run은 불변 입력 template로만 사용하며 성공 결과나 판정을 복사하지 않는다. 기준선 결속 수정 때문에 실제 로컬 입력6개 비교를 다시 실행한다. 이 재실행은 provider 호출을 추가하지 않지만 로컬 임베딩 계산 시간이 든다.

## 실제 입력 비교와 원문 검토

첫 읽기 전용 비교에서 Q02는32예산0그룹→128예산2그룹·69단위·1395자, Q03은1그룹·19단위·691자→3그룹·90단위·2067자였다. 공개 합성 PDF의 대상·조건·예외 완결성과 필요한 원문 근거를 독립 확인했다. 모든6사례의 원문 무결성과 두 번째 선택의 추가 embedding delegate 호출0을 확인했다.

첫 비교의 사례 사이 기준선 결속을 보강한 뒤 같은6사례의 재실행도 exit0으로 통과했다. 첫 비교와6개 counter가 모두 같고, 첫 기준선에 고정된 권한·DB 상태·별칭/색인 UUID가 비교 내내 유지됐다. 실제 선택 순서·점수·cache는 요청 내 검증에 의존하며 독립 재검색은 하지 않는다. Q15의 문맥 증가를 실제 답변 유보 성공으로 간주하지 않는다. 이 단계의 같은 cache를 이용한 시간은 정상32/128서비스의 속도 비교가 아니다.

| 사례 | 32단위: 그룹/단위/문자 | 128단위: 그룹/단위/문자 | 필요한 근거의 예산 복구 |
| --- | --- | --- | --- |
| Q01 대상 구분 | 0/0/0 | 0/0/0 | 없음 |
| Q02 표의 행·열 구분 | 0/0/0 | 2/69/1395 | 확인 |
| Q03 조건·예외 | 1/19/691 | 3/90/2067 | 확인 |
| Q04 날짜 | 0/0/0 | 0/0/0 | 없음 |
| Q13 다중 문서 | 0/0/0 | 1/38/664 | 전체 필요한 근거 미충족 |
| Q15 없는 속성 | 2/26/891 | 4/98/2112 | 음성 대조군이며 유보 별도 검증 |

Q01·Q04의 적격 근거 부재는 이 예산 변경으로 해결되지 않았다. Q13의 일부 문맥 증가는 필요한 모든 문서의 근거 충족을 뜻하지 않는다. 표의 table_cell은 계속 null이므로 표 row/column 복원 기능을 구현한 결과도 아니다.

## 정상 API 후보·제한 평가 결과

정상 owner API에서 다음 신규 결과를 만들었으며 기존 구성·평가·승인을 수정하거나 복사하지 않았다.

| 항목 | 실제 결과 |
| --- | --- |
| 후보 configuration version | `74d8bf31-10c8-4465-8c90-254354f7bf56`, pending·default=false |
| 재사용 generation | 기존 cap-only128, 새 generation profile0 |
| 새 snapshot | `cfe52e31-983a-5607-9340-7925e7a111e4`, 원래3PDF의6새사례 UUID·정확한 highlight/rules |
| 새 평가 run | `da146ef8-067f-4cb0-839a-98400ba42747`, terminal failed |
| 실행 제한 | 6사례×2회=12시도, history={}, attempt_number1, 재시도/승격/전역 worker 시작0 |
| 실행 결과 | completed4, runtime failed8, pending/interrupted0 |
| 독립 판정 | passed0, 계약 failed4, runtime failed8에는 수동 판정0 |
| 생성 상태 | answered0, insufficient_evidence4 |
| 고정 실패 코드 | `provider_request_failed`8, 별도 validation/timeout 코드0 |
| 관측된 전체 시도 시간 | 12개 관측 p50 약40.45초, p95 약50.67초 |
| 평가 observation 토큰 사용량 | 입력/출력 관측0건. 미관측을 실제 비용0으로 해석하지 않음 |

4개 completed는 Q01·Q04의 반복1/2다. 정상 웹 화면에서 실제 근거 부족 상태를 직접 읽었고, 불변 result bytes/digest에 결속된 empty-or-none answer·citations0과 양성 authoritative rule을 독립 확인했다. 지급 규칙 등의 합성 원문도 직접 시각 검토했다. 이 결과는 양성 질문에 근거 답변을 내지 못한 **계약 실패**이며 생성된 답변 문장을 의미 검토해 통과시킨 결과가 아니다. 이 신규4판정만 exact attempt/result digest에 정상 API로 기록했다. Q15는 runtime failure여서 올바른 음성 유보가 가능한지는 여전히 미검증이다.

처음 웹 실행 목록은0개였지만 정상 deep-link의 로드가 끝난 뒤 새 결과와6개 실행 목록을 확인했다. 이를 지속적인 UI 조회 실패로 기록하지 않는다. 이 검토는 기존 계정의 정상 읽기만 수행했고 새 질문·생성·설정 변경이나 token/cookie 주입을 사용하지 않았다.

연결 검증은 원래 백엔드의 정상 API에서 contextualize1+generate1이 성공해 exact 후보 ready=true를 얻었다. requested model은`gpt-5.5`이며 observed model은 미노출이어서 **actual unknown**이다. 두 검증의 provider event usage 합계는 input17004/output114 tokens다. 평가8개 생성 요청은 정책 허용 뒤`provider_request_failed`로 실패했고 provider 사용량을 받지 못했다. Codex stage 감사의 실패 분류는`codex_stage_failed`다. 전체 stage 호출 시도는10개로 상한14개 안이며, 검증2완료·평가8실패다. 이 숫자를 원격 모델의 요청 수락·정상 응답 수와 구분한다. 모든 호출의 종료·cleanup은 확인됐다.

실제 선택 trace도 두 반복에서 동일했다. Q02는2그룹/69단위/1395자, Q03은3/90/2067, Q13은1/38/664, Q15는4/98/2112이며8그룹·128단위·12000자를 지켰다. 저장된 evidence JSON 직렬화 크기는 각각58914/77252/32063/84011 bytes다. Q01·Q04는 selected0으로 빈 배열2 bytes였다. 이는 원문 위치·metadata를 포함한 evidence JSON이며 질문·provider instructions·SDK/CLI envelope를 포함한 전체 wire 크기는 미관측이다. 문자 수로 wire bytes를 추정하지 않았다.

| 실제 단계 | 관측 수 | nearest-rank p50 | p95 |
| --- | --- | --- | --- |
| 요청 준비 | 12 | 2.32초 | 2.58초 |
| 검색 | 12 | 6.51초 | 16.85초 |
| 근거 선택 | 12 | 20.86초 | 26.48초 |
| 생성 단계(전부 실패) | 8 | 14.75초 | 15.44초 |
| 결과 저장 | 12 | 0.06초 | 0.12초 |

질문 응답 지연에서 검색·근거 선택 시간이 크다는 관측은 가능하지만, 이 실행은 생성 실패를 포함하므로 정상 답변의 지연이나 과거32구성과의 동일 조건 비교로 해석하지 않는다. 이번 실패에서는 생성 후 인용 검증이 실행되지 않았다.

연결 검증은 원래 백엔드 프로세스에서, 평가 workflow는 승인 계획에 따라 원래 venv/root의 task-local 실행 프로세스에서 수행됐다. 같은 DB·계정·문서·profile을 사용했지만 도구 sandbox의 네트워크/프로세스 권한 차이는 실행 실패의 가설이다. raw stderr·실제 wire bytes가 감사에 남지 않아 현재 증거로 근본 원인을 확정할 수 없다. 다른 모델로 전환하거나 재시도해서 실패를 숨기지 않았다. 이 결과를 본래 서비스에서 답변 생성이 성공했다는 증거로 보고하지 않는다.

## 최종 보존과 남은 경계

실행 후 독립 READ ONLY에서55개 보호 테이블의 기존 모든 행 SHA multiset 포함·삭제/변경0, 동결10보고서 exact file/DBv1/current1, 활성32와 도메인·기존 구성/프로파일/승인/평가/판정, 원래9턴 대화, 원본3PDF,0063 gate정의·frozen1/receipt0, 환경 해시를 확인했다. 추가는 승인된 새 configuration/version/policy/external/workspace approval 각1, dataset1·case6, run1·attempt12·새 판정4와 정상 실행의 감사/인증 기록뿐이다. 새 generation/model/profile/source·대화 추가0이다. 새 run은 terminal failed·finished·claimnull/history0/attempt_number1이고 실행 중 작업은0이다. 독립4판정과 실제 DB의 digest/status/reason도 정확히 일치했다. 별도 fresh READ COMMITTED에서 현재owner·원본3문서 READY/active/currentACL과 활성32를 재확인했다.

기존 서버3 PID의 실행파일/starttime 유지도 확인했으나 parent/cwd/environment/port ownership 전체를 독립 증명한 것은 아니다. 원래 환경의 원본·계정을 보존했으며 별도 환경/DB/계정/문서·세션·서버/worker/beat 시작·삭제·Git staging/commit/push를 수행하지 않았다. 독립 검증은 DB/API/provider 쓰기와 추가 검색·embedding 없이 진행했다. 정상 웹의 읽기와 원문 시각 검토를 제외한 helper 산출물에는 원문·질문·답변·원문 ID 목록을 저장하지 않았다.

유효 대화·성공한 멀티턴, 별칭의 실제 종료 proof, DLL 재발 방지, 권한/첨부/모바일/실패·timeout, Git 인계 등 RAG 기능 마감은 여전히 별도 미완료다. 이번 제한 실험은 자동 승격·전체 RAG 완료 또는 품질 개선만 남았다는 판단의 근거가 아니다. SDK 도입→벡터 저장소 비교→로컬 LLM 학습의 후속 순서는 유지한다.
