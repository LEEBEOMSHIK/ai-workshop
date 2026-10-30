# 원문 관계 선택·저장 관측·RAG 자율 재위임

## 범위와 결정

사용자는 관계를 보존하는 근거 선택과 저장 완료 관측 충돌 수정, 현재 RAG 안의 자율 재위임을 승인했다. [ADR-0050](../decisions/0050-rag-relations-and-autonomous-handoffs.md)에 설계와 수용 경계를 기록했다. 추가 검색/외부 모델/다른 Labs 호출은 없다. 기존 활성 direct 프로파일과 기본값을 유지하며 새 경로는 명시적인 v2 후보로만 선택한다.

## 구현 결과

- 표 선택은 명시한 한 상품과 원문 행 항목 전체 토큰을 연결한다. 해당 열·모든 항목·전체 설명/조건을 ID/본문/위치/순서 그대로 보존하고 불명확한 구조·비교·부정·다중 상품·다른 셀 참조를 제외한다. 합성 마감 사례33→28개, 기존 지급 사례28개 동일. 임계값과32개 한도는 유지한다.
- 턴 저장 트리거가 실행을 먼저 종료하는 경합을 실제 DB에서 재현했다. 같은 시작 시각의 기존 running persistence, 같은 소유자/삭제되지 않은 대화, 일치하는 부모 terminal 상태에서만 완료 메타데이터를 기록한다. 다른 늦은 본문/근거/이력/SDK 관측은 거부하고 기존 과거 기록은 자동 재작성하지 않는다.
- SDK의 근거·답변·검토 담당이 다른 두 역할 중 다음 담당을 고른다. 같은 역할로 돌아오면 새로운 span을 기록한다. 매 이동에 서버 소유 원래 입력을 다시 구성하고 최신 제한된 위임 작업만 데이터로 추가한다. 최종 답변은 답변 담당만 제출하고 기존 인용 검증을 거친다. 모델/출력/시간 예산과 현재 ACL·취소를 공유한다.
- 관리 화면은 공용 ChoiceGroup으로 관리자 위임/자율 재위임과 별도 예산을 제공한다. 등록은 draft/nondefault이며 평가 없이 기본값 전환은 거절한다.

## 실행한 검증

| 범위 | 결과 |
|---|---|
| highlighting·표 generation 연결 | 290 통과 |
| 기존 direct/manager 및 새 SDK handoff 전체 | 275 통과, 별도 독립22 포함 |
| 실행·대화 회귀 | 439 통과, 새 persistence28 포함 |
| 본래 DB persistence 트리거 rollback | 8 통과, 변경 전5 실패 재현 |
| 본래 DB v2 등록 서비스/JSON/재조회/승격 거부 rollback | 1 통과 |
| HTTP 생성 폼 | 54 통과, 신규14 실패 확인 후 수정 |
| 타입/린트 | backend 변경12소스 범위 Mypy, 전체 frontend TypeScript, 변경 Python/TSX Ruff/ESLint 통과 |

독립 검토는 구현과 분리해 SDK 권한·취소·예산·본문 비공개·관측 연결 및 persistence 경계를 확인했다. 내부 소켓 차단으로 멈춘 Windows asyncio 검사는 해당 실행 권한으로 재검증했다. 초기 임시폴더 접근 오류3건은 새로운 작업 전용 basetemp로 해결했다. 실패 기록을 성공 결과로 덮어쓰지 않았다.

## 본래 환경

유휴 DB, 정확한 API/launcher/포트·생성 시각·환경을 검증하고 기존 실행기로 재시작했다. API PID185568, launcher181448에서 health/ready 정상. 전후25표2569행의 PK별 해시 및 .env 동일. 기존 로그인 화면에서 새 선택·예산·키보드 이동을 확인했다. 별도 DB/계정·migration·설치·commit/push는 없다.

## 실제 검증 진행

사용자 새 승인: 기존 대화 마감 시각 후속 최대2회(문맥화+답변), 비기본 자율 재위임 후보의 동일 공개 첫 질문 최대4회, 합계 Gemma 최대6회·자동 재시도0. 실행 결과·소비 횟수·답변/인용·복귀·저장 관측을 아래에 기록한다. 승격은 포함하지 않는다.

실제 검증은 아래 결과로 종료했다. 마감 후속의 핵심 정답·인용·복귀·저장 완료는 확인했지만 불필요한 예시 반복과 기존 일반 지급 규칙 누락은 남는다. 자율 후보는 실패했고 후속 보강의 실제 모델 수용은 미완료다. ISSUE-00005/00035에 수정·검증·잔여와 진행 이력을 저장·재조회했다.

### 기존 direct 연결의 마감 시각 후속 검증

2026-10-27 11:43:22–11:47:04 KST에 기존 대화 `2fb524c6-d252-4732-8dd0-d9a84f02f202`의 같은 segment 1에서 sequence 3을 실행했다. 턴은 `ad8fa365-8105-4a53-81cd-4ce8138ca386`, 실행은 `6deb6a1d-b9a9-4b95-8a7d-0893987c94c5`다. 이번 승인 6회 중 문맥화 1회와 direct 답변 생성 1회, **2회를 사용했고 자동 재시도는 0회**다. 메인 검증자는 이후 자율 재위임 후보 프로파일 `5e188c12-c257-4b11-b55c-826650e1a9d2`의 draft 등록을 확인했으며, 이 기록 시점의 추론은 0/4회다. [별도 준비 기록](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/autonomous-candidate-prepared.json)은 등록 전 산출물이므로 그 파일 자체를 등록 완료 증거로 취급하지 않는다. 기존 direct 연결과 기본값은 유지했다.

읽기 전용 독립 확인 [실제 결과](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/review-live-direct-result.json)와 [종료 상태](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/review-live-direct-terminal-state.json)에서 다음을 확인했다. 확인 담당자의 모델 호출·DB 쓰기는 0이며 비공개 본문을 보고서에 복제하지 않았다.

- 앞선 answered 턴의 사용자·답변 메시지 2개가 채택됐고 문맥화 입력은 저장된 이력·현재 질문과 일치한다. 문맥화 결과 `AM-SYN-101 신청 접수 마감 시각`이 검색·SDK 입력에 그대로 전달됐다.
- 정답 PDF 2쪽이 검색 1위에서 `structured_table_selected`로 채택됐다. 원래 대상 열·행 항목·설명·조건 **28개/659자**가 ID·본문·위치·순서 그대로 전달됐고 32개 한도 위반은 없었다. 이전 33개 전체 제외와 달리 이번에는 답변 생성까지 진행했다.
- 실행과 턴은 `completed`, `execution_terminated=true`, 관측 `complete=true`이며 오류가 없다. 문맥화·인용 검증·저장을 포함한 8단계가 모두 완료됐다. SDK에는 실제 답변 담당 agent/model 2개 span만 있으며 관리자 위임을 수행한 것처럼 기록하지 않았다.
- 답변은 `answered`와 서명 검증을 통과했고 핵심 마감 시각 15:00과 원문 인용은 정확하다. [인용 집계 정정](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/review-live-direct-citation-correction.json)에서 **claim 1개·claim 인용 그룹 1개·서로 다른 근거 2개 → UI 원문 버튼 2개**가 일치함을 확인했다. 앞선 보고서의 `citations_count=1`은 원문 링크 개수가 아니라 claim별 인용 그룹 개수다. 마감 셀과 날짜 예시 근거가 함께 연결됐으며 저장 답변은 이전 확인 이후 바뀌지 않았다. 다만 질문이 요청하지 않은 이전 날짜 예시를 답변에 반복해 **답변 초점·간결성 수용은 실패**했다. 핵심 정답·출처 통과를 전체 답변 품질 통과로 확대하지 않는다.
- 현재 owner 권한에서 원문·의존 이력을 조회할 수 있고 다른 actor는 404로 거부됐다. 문맥 본문은 응답에 중복 저장되지 않았으며 비공개 추론 보관은 없다.

전체 실행은 222.309초, 문맥화 26.900초, 답변 생성 단계 149.168초였다. 답변 모델의 서버 입력 처리 138.252초·출력 9.955초·로드 0.043초는 HTTP 전체 148.457초의 내부 관측이며 서로 중복 합산하지 않는다. 이번 검증은 선택·완료 저장 경계의 실제 동작 확인이며 속도 개선이나 전체 질문 품질 통과를 뜻하지 않는다.

메인 검증자는 실행 중 파일함으로 이동한 뒤 대화 복귀·새로고침 후 답변 표시를 확인했고, 원문 뷰어에서 PDF 2쪽의 `영업일 15:00까지` 셀 하이라이트가 열리는 것을 확인했다. [파일함 이동](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/background-files.jpg), [후속 질문·답변 전체와 인용2](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/background-returned-followup.jpg), [복귀 AX 텍스트](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/background-returned-answer-ax.txt), [마감 시각 원문](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/deadline-source.jpg)을 보존한다. 원문 뷰어가 오른쪽 답변 일부를 가리는 캡처와 달리 마지막 후속 캡처는 뷰어를 닫고 sequence 3 질문·답변을 함께 표시했다. 답변·인용의 수용은 메인 화면 관찰과 위 저장 결과·인용 집계 정정을 함께 근거로 삼는다.

[자료 보존 비교](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/review-live-direct-preservation.json)는 25표의 기존 2,569행에서 삭제가 없고, 승인된 대상 대화 행 외 기존 행 변경이 없음을 확인했다. 새 턴·실행·성공 감사·감사 공간 정책 4행이 추가돼 2,573행이 됐으며 접수 ledger 6행과 `.env`는 동일하다. 대상 대화의 변경은 승인 범위지만, 이전 자료가 행 전체 해시이므로 변경 열별 전후 일치까지 검증했다고 주장하지 않는다. 남은 running 턴은 0이다. 기존 지급 규칙 누락 및 자율 후보의 실제 품질 수용은 계속 별도 잔여다.

증거 폴더: `.local-data/project-agent-work/rag-selection-redelegation-20261027/`.

### 비기본 자율 재위임 실제 결과

기존 로그인 관리자 화면에서 위 draft 프로파일과 구성 버전 `50ddfbea-1667-4d2d-812c-d60e03e32dee`를 등록하고 공개 질문 한 사례·두 반복을 접수했다. 실행 `d2b3f64b-67e4-4132-8898-07c6d94de098`은 원래 v6·모델·출력512·원문·검색·평가 정책을 유지한다. UI가 생성한 요청 ID로 한 번만 접수했으며 등록 전 준비 JSON의 예시 요청 ID를 재전송하지 않았다. 독립 읽기 전용 사전 검사 후 공식 exact-run 실행기에 전체 HTTP4회·재시도0·재실행 금지 제한을 적용했다. 일반 큐 worker/beat는 없었다.

두 반복 모두 근거 담당의 첫 모델 응답 뒤 `orchestration_invalid_delegation`으로 실패했다. **실제 위임0, 답변/검토 담당0, 최종 답변·인용0**으로 자율 경로와 답변 품질은 미수용이다. 정상 원문28개와 T+4 영업일 셀은 실제 입력에 있었으므로 근거 누락으로 판정하지 않는다. 실제 두 모델 입력3844/출력130토큰, 평가 duration209.998/23.523초이며 성공 답변의 성능과 비교하지 않는다. [독립 결과](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/review-autonomous-terminal.json)·[실패 화면](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/autonomous-failed.jpg)·[화면 텍스트](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/autonomous-failed-ax.txt).

승인6회 중 **후속2+자율2=총4회**, 자동 재시도0이다. 예정된 두 반복은 모두 종료했고 남은2회를 재시도에 쓰지 않았다. [송신 원장](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/autonomous-approved-execution.jsonl)은 실제 native 송신2회와 exact executor 종료를 기록한다. 후보는 draft/nondefault, 구성pending/nondefault, 활성 도메인0이며 기존 서비스 연결·기본값을 유지했다. [보존 비교](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/review-autonomous-preservation.json)에서 직전25표2573행 전체의 해시를 보존하고 승인된 후보·평가·감사15행만 추가돼2588행이다. 대화 세 턴·접수 원장·.env는 동일하다.

### 실제 실패 후 보강

[독립 원인 조사](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/autonomous-failure-diagnosis.json)는 네이티브 응답 변환 이후 SDK 위임 검증 전의 거절로 범위를 좁혔다. 실패 응답 본문은 보관되지 않아 무도구·복수 도구·이름·종료 형태 중 어느 조건인지 단정하지 않는다. 실제 지침에는 근거 담당의 최종 답변 금지와 공통 최종 JSON 요구가 동시에 있어 충돌이 확인됐다. 단순히 답변 지침 파일만 불러와도 v6 파일 자체에 JSON 요구가 있으므로, 근거/검토에는 전용 위임 지침을 사용하고 답변 담당만 기존 답변 지침 전체를 최종 제출 조건으로 유지하도록 수정했다. 원문·비신뢰 입력·조건/예외·내부 추론 미출력과 기존 인용 검증은 유지한다. 추가4개 회귀 실패를 확인한 후 전체 SDK279개가 통과했다. 수정 후 실제 모델 재검증은 하지 않았다.

두 평가 실행에서도 persistence가 running으로 남는 경합이 재현됐다. 대화 전용 예외로는 평가 시도 terminal 트리거를 처리하지 못해, 같은 실행·시도·평가 소유자·terminal 상태를 확인하는 메타데이터 전용 경계로 보강했다. 실패로 생략된 이력/인용 단계나 전체 complete를 강제로 완료시키지 않는다. 과거 실제 실패 기록은 재작성하지 않았다. 최종 검증과 본래 반영 결과는 아래 마감 기록을 따른다.

설정 화면은 본래 관리자 선택/방향키 동작과 실제 컴포넌트의 합성320/375px 화면을 확인했다. [320px](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/handoff-form-320.jpg)·[375px](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/handoff-form-375.jpg)에서 선택지와 설명의 잘림을 보지 못했고,375px Left/Right로 관리자/자율 선택과3/2 예산 복원을 확인했다. 실기기·정확한44px 계측·모든 상태 수용으로 확대하지 않는다. 작업 소유 미리보기 서버 PID118540의 명령/경로를 확인하고 해당 서버만 종료했다.

## 최종 보강 검증과 반영

- 평가 persistence 단위 RED6 실패→56 통과, 기존 DB 실제 complete_attempt/terminal 트리거 RED4 실패→대화8+평가7 **15 통과·1 제외**. 다른 기존 계정이 없어 평가 owner 부정 DB 사례만 제외했고 새 계정을 만들지 않았다. 단위 SQL의 정확한 owner 조건은 확인했다. COMMIT 차단·외부 rollback 뒤 관련11표 해시 동일·합성 행 잔여0이다.
- 구현 담당의 실행·대화·평가 단위 고유862개 통과. 최초861통과/1실패는 backend 기준 상대 migration 파일을 repo root에서 찾은 명령 위치 오류로, 해당1개만 backend cwd에서 재실행해 통과했다.
- [독립 최종 검토](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/final-independent-followup-review.md): SDK285 + 실행/평가687 = 서로 다른 경로 **972개 통과**, 제품2개 strict Mypy와 관련 Python16개 Ruff0.16.5 통과. 이 숫자는 앞선 검증과 중복되므로 모두 합산하지 않는다. 독립 검증의 임시폴더22오류/상대경로1실패는 새 작업 전용 basetemp·backend cwd로 해결했고 최초 결과도 보존했다. 원래 답변 serializer·v2/v6 지침·참조 포장 파일의 SHA와 direct/manager 마지막 HTTP 입력 바이트 동일성을 확인했다.
- 12:18 KST 유휴 상태·정확한 기존 API185568/실행기181448·생성시각·포트·환경·모델 실행 종료를 확인하고 기존 실행기로 최종 보강을 반영했다. 새 API182980/실행기190612의 health/ready200을 확인했다. [최종 런타임](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/trace-runtime-after-check-final.json), [재시작 전후25표2588행/.env 동일](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/final-rollout-preservation.json). 기존 실행·실패 관측·프로파일은 소급 변경하지 않았다.
- [파일 보존](../../.local-data/project-agent-work/rag-selection-redelegation-20261027/final-preservation-independent.json): 기존2266개 중2252동일·이번범위14변경·누락0·읽기실패0/.env동일. 새 handoff/회귀/설계/기록 파일을 추가했으며 관계없는 기존 변경을 정리하지 않았다. 최종 문서 마감은 이 스냅샷 이후 별도다. staging·commit/push·설치·DB/계정 생성은 없다.

다음은 자율 재위임 응답의 거절 사유를 본문·내부 추론 없이 구분하는 관측 보강과 수정본의 실제 위임·최종 답변/인용 검증이다. 이번 실행의 잔여 호출을 자동 재시도에 사용하지 않는다. 기존 direct의 답변/인용 계약과 활성 연결, 별도로 보류한 목록/스레드 성능 실험을 유지한다.
