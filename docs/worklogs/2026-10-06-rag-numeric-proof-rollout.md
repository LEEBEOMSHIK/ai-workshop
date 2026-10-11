# 원문 계산 근거 본래 반영·새 평가 검증

2026-10-06 사용자 승인에 따라 기존 DB에 정확한0061→0062→0063 경로를 적용하고 기존 API만 재시작했다. 새 불변 v6/schema3 후보를 등록하고 정상 API 합성 연결 검사를 통과했다. 새25문항×3 평가를 실제 실행해64정상/11근거 검증 거절로 종료했고, 정상64건의 독립 의미 검토는63통과/1실패다. 새 후보는 승격하지 않았다. 본래 브라우저는 미검증이다.

## 본래 반영과 보존

- 기존 DB의 private `pg_dump -Fc` 23,232,481bytes 및 `pg_restore --list` 목록 검사를 완료했다. 실제 복원 시험은 하지 않았다.0063의 downgrade는 허용되지 않으며 앱 복원 또는 forward fix가 필요하다.
- 기존117테이블의 기존 열·행 수·정렬 행 digest, `.env`, 별칭 gate 함수 OID를 적용 직후 비교해 일치했다. 독립 읽기 전용 검증은 보호 대상50테이블의 기존 행, 이전 평가155/75판정·첫75/68판정·실패7재시도 및 과거 exact DB v1을 확인했다.
- worker/beat는 기존 미실행 상태, Docker·프론트는 기존 상태다. 계정·문서·세션·기존 활성 연결을 유지했다. 별칭 frozen gate1·recovery receipt0·acceptance0을 임의 해제하지 않았다.
- 원래 루트와 `.env`에서 API만 반영했다. 직접 health/readiness·프론트 경유 health·정상 로그인200을 확인했다. health 성공을 생성 품질 또는 RAG 전체 완료로 해석하지 않는다.

## 실제 합성 연결에서 발견한 승인 재파생 오류

첫 합성 검사2건은 문맥화가 완료됐지만 생성 요청의 승인 재파생에서 `codex_authorization_source_unavailable`로 차단됐다. schema3 프롬프트 신원을 검증하려고 만든 빈 요청에 숫자 목록이 빠진 것이 원인이었다. 정상 실제 요청의 숫자 목록·사용자 권한·승인·원문 revision·정책 검사는 유지하고, 빈 승인 재파생 요청에만 현재 요청·구성·프로파일에 결속된 빈 목록을 제공했다.

- 실제 승인 재파생 경로의 generate/contextualize 회귀: RED1실패/1통과 → GREEN2통과. 관련128통과.
- 관련 backend1374통과/4skip, 기존 Starlette/httpx deprecation warning1. `mypy src/ai_workshop`410파일 통과. 변경2파일 Ruff/check·format 및 diff 검사 통과. `mypy -p ai_workshop`는 설치된 py.typed 패키지 탐색 경로로 실패했으며 저장소 source 경로 검사로 확인했다.
- 독립 보안 검토는 회귀2통과와 실제 요청의 숫자 목록·권한·정책 검사가 유지됨을 확인했다. 전체 구현 재검토를 반복하지 않았다.
- API 재반영 후 정상 API 합성 연결 `ready=true`. 이전 실패2건도 DB에서 보존했다. 요청 모델 `gpt-5.5`, 관측 모델은 `unknown`이다.
- 다른 원인의 ISSUE-00027을 정상 관리자 API로 별도 생성해 verified로 기록했다. 광범위한 품질 문제5/26을 이 오류 수정으로 닫지 않았다.

## 새 불변 후보와 동일 조건

| 항목 | 식별자·조건 |
| --- | --- |
| 후보 | 원문 계산 검증 v6 · 2026-10-06 |
| configuration version | `9c7c07e7-d128-4876-9411-aa7479eff3e1` |
| generation profile | `3682b7cd-bdc2-4ac1-b014-c8be4a62eb83`, v6/schema3 |
| 새 run | `e20b73e8-2db4-423a-8d79-dfbc1f34999e` |
| snapshot | `4eec7cab-067d-5b96-933b-37b3725d5ea6` |
| policy | `3cb3fc16-98d7-4cd6-8f6c-4646fbff3256` |
| 비교 조건 | 같은 합성3문서·고정25문항·3반복·원문 snapshot·QA/rules·정책·모델/deployment·색인·검색·대화 이력 |
| 변경 조건 | 별도 불변 v6/schema3와 `source-numeric-proof-v1` |

기존 profile/configuration/결과·판정은 덮어쓰지 않았다. 새 후보는 pending/defaultfalse이고 기존 도메인 연결을 유지한다. 정상 API로 생성한 새75회는 기존 원래 환경의 실행 workflow에서 처리하며 worker/beat를 새로 띄우지 않는다. 재시도는 하지 않는다.

## 새75회 최종 결과

전체25×3의75개 쌍은 각각 한 번씩 실행됐다. 모든 attempt_number는1이며 재시도0, run은 `failed`, 진행 중 실행0이다. 원래 workflow는 정상 반환(exit0)했지만 평가 실패를 성공으로 보고하지 않는다.

| 관측 | 결과 |
| --- | --- |
| 생성·근거 검증 | 정상64 / citation_validation_failed11 |
| 답변 가능한 질문63회 | 답변52 / 검증 거절11 |
| 근거가 없는 음성 사례12회 | 정상 근거 부족 응답12 |
| 독립 의미 검토 | 정상 답변51 + 올바른 근거 부족12 = 통과63 / 의미 실패1 |
| 정상 결과 저장·복원 | 64개 canonical digest·실제 numeric receipt·현재 권한 검증 모두 통과 |
| 주장·계산 | claim83 / percentage_point_difference10개, 결과9건 |
| 통화 단위 환산 | 실제 convert_krw_unit proof0. 단위·rollback SQL 성공과 실제 모델 성공을 구분 |
| 모델 | 실제 요청 audit75개 모두gpt-5.5 / 관측 모델75개 모두unknown |

의미 실패1건은 H05 rep2다. signed subtraction 자체는 정확하지만 음수 차이에 ‘낮다’를 함께 사용해 비교 방향이 모순됐다. 해당 결과의 계산 proof2개가 산술 검증을 통과했다는 사실과 의미 실패를 함께 보존한다. 계산 검증은 상품·기간·관계·조건의 정답 검토를 대체하지 않는다.

### 거절11건의 기록된 원인

repetition은 원래 저장 값0/1/2다. 모든 실패에서 생성 단계는completed, 인용 검증 단계가failed다. 실패 answer·claim·numeric binding·receipt는0이며 최초 safe reason만 관측했다.

| 최초 safe reason | 사례·반복 | 건수 |
| --- | --- | --- |
| exact_value_not_supported | Q04:0,2 / Q08:0,1,2 / Q12:0 / H07:2 / H04:0 | 8 |
| calculation_result_span_invalid | H05:1 / H04:2 / Q07:0 | 3 |

정확한 실패 값·span과 전체 validator kind_count는 기록되지 않아unknown이다. 폐기 초안을 복원하거나 원인을 채워 넣지 않는다. Q08 표의 원문 적용 관계 미기록은 별도 알려진 경계지만 이번3개 실패의 정확한 원인으로 단정하지 않는다. Q12의 실패 반복은 정확한 값이 미확인이다. Q04의 정상 반복은 원문에 직접 적힌 날짜를 답했으며 날짜 계산을 추론하지 않았다.

실패의 generation audit에서는 허용된 정책·요청 모델을 확인했다. 별도 Codex stage의 동일 actor/config/실행 시간창에서는 generate completed와 termination/cleanup을 관측했지만, stage와 execution의 persisted correlation UUID가 정확히 일치하지 않아시간창 관측을 UUID 결합 증명으로 보고하지 않는다.

### 단계 시간과 실패 위치

기록된 duration을 정렬한 nearest-rank p50/p95다. 단계별 분위수를 합산해 전체 시간으로 취급하지 않는다. 단위가ms인 두 행을 구분한다.

| 단계 | 기록 건수 | p50 | p95 | 상태 |
| --- | ---: | ---: | ---: | --- |
| 접수 | 75 | 2.304초 | 2.619초 | 완료75 |
| 검색 | 75 | 6.730초 | 7.863초 | 완료75 |
| 근거 선택 | 75 | 23.555초 | 29.034초 | 완료75 |
| 생성 | 75 | 25.416초 | 46.951초 | 완료75 |
| 인용 검증 | 63 | 33.035ms | 59.308ms | 정상52 / 근거 부족 skip12 / 실패11 |
| 저장 | 75 | 162.316ms | 237.697ms | 완료75 |
| 멀티턴 문맥화 | 3 | 19.805초 | 20.777초 | 완료3 / skip72 |
| 전체 실행 | 75 | 60.727초 | 84.713초 | 정상64 / 실패11 |

시간은 주로 근거 선택과 모델 생성에 사용됐다. 인용 검증 실패가 나타나기 전에 모델 생성 시간이 이미 발생한다. 일반 history 단계는75개 skipped이며 실제 문맥화3건의 성공을 제품의 기존 세션 이어가기·브라우저 멀티턴 성공으로 확대하지 않는다.

이전 수정 런타임 첫75회의68정상/7실패와 이번64정상/11실패는 각각의 동결 run으로 보존한다. 이번 의미 통과는63/75다. 같은 자료/QA/모델 요청 조건에서 강화한 schema3 계약과 실행 변동이 있으므로 전체 품질이 개선됐다는 결론을 내리지 않는다. 실패 재시도나 후보 프로파일 덮어쓰기로 수치를 바꾸지 않았다.

### 안전한 복원과 실제 승격 차단

실제64개 저장 결과의 canonical digest·receipt·현재 ACL 복원을 독립 읽기 전용으로 확인했다. 메모리에서 다른 actor, envelope 삭제, payload digest 변경, 다른 execution의 binding을 적용한 네 요청은 모두 numeric_validation_binding_invalid로 거절됐다. 실제 DB·권한을 변경하는 철회 시험 또는 Chrome 권한 철회 검증은 하지 않았다.

정상 owner API를 통해64개 completed 결과의 독립 판정63passed/1failed를 모두 등록했다. 이전57개 판정의 상태·reason·result/rule digest를 그대로 보존하고 마지막7개만 추가했다. 실제 accept API는409/generative_evaluation_not_qualified로 거절했다. 후보의 모든 반환 필드는 요청 전후 동일하고 pending/defaultfalse를 유지한다. 기존 활성 도메인 연결은 변경하지 않았다.

receipt는 신원·digest·참조만 저장하고 원문/답변 본문 컬럼이 없다. stage audit의 금지된 본문 key와 현재 API/평가 로그의 .env secret literal·SQL parameter dump·traceback·body-field dump 신호가 없음을 확인했다. 이는 정해진 탐지 검사의 결과이며 모든 가능한 정보 누출이 없다는 보증으로 확대하지 않는다.


원문/답변/실패 초안·provider payload·비밀·비공개 내부 추론은 이 보고서와 로그에 저장하지 않는다. 정상 판정 사유는 원문 근거와 관측 가능한 결과에 대한 짧은 설명만 저장한다.

## 브라우저와 남은 범위

기존 Chrome 관리자 화면은 로그인 화면으로 전환되어 사용자 로그인을 요청했지만 응답을 받지 못했다. 이후 같은 Chrome 탭 목록도 로그인 주소였고 브라우저 제어 연결이 중단됐다. 이 상태에서 실제 화면·새로고침·1440/390px·키보드 계산 펼침·원문 연결·세션/멀티턴을 완료했다고 주장하지 않는다. 통과·승격 조건을 충족하지 않은 후보를 도메인에 연결하지 않는다.

별칭의 실제 종료 증빙·새 정상 parity, 본래 세션/첨부/모바일 흐름과 Git 인계도 별도 미완료다. 아직 품질 개선만 남은 상태가 아니다. SDK·벡터 저장소 비교·로컬 LLM 학습은 기존 RAG 마감 뒤의 추가 작업이다.

## 근거 문서

- [구현과 기존 시험](2026-10-05-rag-numeric-proof-implementation.md)의 동결 v1.
- [승인된 명세](../superpowers/specs/2026-10-05-rag-numeric-proof-design.md), [실행 계획](../superpowers/plans/2026-10-05-rag-numeric-proof.md), [ADR-0036](../decisions/0036-rag-source-backed-calculation.md).
- [본래 로컬 실행과 복구 경계](../runbooks/local-development.md).
- 새 실제 운영 메타데이터: `.local-data/project-agent-work/rag-numeric-proof-rollout-20261006/`.
