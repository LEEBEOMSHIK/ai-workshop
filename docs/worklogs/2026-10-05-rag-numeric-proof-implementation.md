# RAG 원문 계산 근거 구현과 본래 반영 경계

- 날짜: 2026-10-05
- 상태: 코드 구현·독립 리뷰 보완·오프라인 및 본래 rollback 검증 완료. 본래 서버 미반영.
- 문제: ISSUE-00026, 관련 ISSUE-00005. 전체 품질·별칭 종료는 미완료다.
- 기준: [승인 계획](../superpowers/plans/2026-10-05-rag-numeric-proof.md), [명세](../superpowers/specs/2026-10-05-rag-numeric-proof-design.md), [ADR-0036](../decisions/0036-rag-source-backed-calculation.md).
- 작업 공간: 사용자 승인된 기존 main, BASE f8e85656b1b633929c3489ed65166ecfb5e52b67. 관련 없는 WIP 보존, 미커밋.

## 구현한 동작

schema3/Codex wire2/v6 프롬프트에서 모델은 자기 인용한 서버 토큰과 연산·결과 위치를 지정한다.
서버는 요청 nonce·원문 revision/occurrence·프로파일·정책을 대조하고 독립 Decimal 문맥에서 재계산한다.
허용 연산은 명시된 두 비율의 퍼센트포인트 차이와 원/만원/억원 환산이다. 반올림·환율·날짜 추론·숫자의
헤더 상속·다른 모델 대체는 추가하지 않았다. 계산 통과는 상품·기간·관계의 의미 정답을 보증하지 않는다.

audit와 별도 immutable receipt를 같은 트랜잭션에 저장한다. 결과 JSON에서 실행 문맥을 역산하지 않고
대화 turn·평가 attempt·모니터링의 서버 execution으로 문맥을 먼저 조회한다. 직접 값·근거 부족 결과도
receipt를 보존하며 envelope 삭제·schema downgrade·다른 실행의 receipt 이식은 거절한다.
기존 schema1/2는 새 필드를 생략하고 기존 bytes/digest·서명 계약을 유지한다.0061의 legacy 조회는 새
numeric table을 조회하지 않으며 schema3 준비 검사는 저장 기능이 없으면 모델 호출 전에 차단한다.

검색은 audit commit 이후 현재 원문 권한을 다시 확인한다. 평가의 성공 저장은 새 transaction에서
실행·구성·동결 프로파일·receipt와 원문 권한을 검사한다. 대화의 최종 권한 확인도 정상 답변 저장보다
앞에 수행한다. 철회 시 본문/proof 없는 실패 결과로 기록한다. 복원 시 현재 권한·READY 원문을 확인하며
과거 평가를 읽는 데 현재 색인의 활성 여부를 새 조건으로 요구하지 않는다.

기존 주장 검토의 접힌 `계산 근거`에서 연산·결과·원문 위치를 볼 수 있다. Python/JS 모두 Unicode code
point 위치를 사용하며 현재 허용된 원문 identity에만 링크한다. 접근 불가 원문에는 링크를 만들지 않는다.

## 독립 리뷰와 보완

fresh-context reviewer가 전체 구현과 원본 trial helper를 검토했다. Critical0·Important4이며 모두 수정했다.
숫자 suffix를 읽던 문제는 schema3의 원문 operand·직접 지원·결과 occurrence에서 차단했고 legacy lexer는
유지했다. 저장 후 권한 철회는 검색 재확인 및 평가 저장 경계로 보완했다. 변조 시험에는 정상 복제 대조
행과 동일한 임시 판정을 넣고, 모든 DB 오류가 아닌 정확한 숫자 검증 오류만 기대한다. 과거 READY 입력은
재색인으로 비활성화돼도 현재 읽기 권한 아래 복원할 수 있다. 별도 조치할 Minor는 없었다.

reviewer는 실제 PostgreSQL 실행·rollback, 실모델 품질·브라우저·rollout, 기존 alias/access-epoch WIP의
판정을 유보했다. PostgreSQL 실행은 메인 구현자가 아래 original trial로 확인한다. retrieval-only 대화
우려는 현재 도메인 계약이 생성 프로파일을 필수로 요구함을 확인해 적용 대상이 아닌 것으로 판정했다.

## 검증과 보존

최종 관련 backend suite는 **1372통과/4skip**, 본래 single-file SQL trial은 **4통과**다.
프론트4파일77건·API 타입/TypeScript/ESLint가 통과했다. 전체 local source mypy410 파일과 계획 범위
Ruff check와 이번 소유56파일 format을 확인했고, 이후 변경된 핵심15파일의 format check도 통과했다.
초기 넓은 format check의 미수정 파일34건은 일괄 변경하지 않는다.

본래 SQL 시험은 기존0061 연결 안에서 실제0063 DDL·실제 승인 함수를 호출한다. positive control,
11변조·wrong actor 조회·근거 부족·legacy를 구분한다. COMMIT0, rollback 뒤 보호14테이블의 행 수/전체
행 해시와 gate OID/정의 해시를 비교하고 새 receipt table/helper가 없는 상태에서 기존 legacy 조회를
확인한다. 임시 SQL 판정은 실제 모델 답변이나 정상 의미 판정으로 취급하지 않는다.
4건 모두 통과했고 11변조의 정확한 거절과 positive control을 확인했다. rollback 이후 원본0061에서
실제 legacy 조회도 성공했다. 저장·canonical의 Python/PostgreSQL byte parity와 emoji/한글/줄바꿈을 확인했다.

초기 시험의 임시 ORM 관계 로딩·실행 상태 제약·계산 fixture·terminal timestamp 만료를 수정했다.
실제 PostgreSQL 호출에서는 JSON containment 오른쪽 추출식의 괄호 누락을 발견해 수정했다.
실패마다 rollback 보존 검사를 수행했다. 실패 초안·원문/답변·provider body·비밀·원시 DB 예외를 로그,
receipt, 문제 이력에 저장하지 않았다. 진단은 단계·예외 종류·SQLSTATE·소스 줄 번호 등 안전한 메타데이터다.

이전 평가155/75 판정·수정 후 첫75/68 판정·후속7실패, 기존 프로파일/활성 연결·문서·계정·별칭을
수정하지 않았다. 이전 설계/계획 보고서의 정본·동결본·DB 정확한v1 연결도 새 보고서로 교체하지 않는다.
현재 과거 코드를 동결해 둔 검증 snapshot과 이번에 의도한 제품 코드 변경을 구분한다.

## 구체적인 반영 범위와 복구 제한

현재 본래 DB는0061이다.0063의 parent는 별도 WIP인0062다.0062는 access-epoch 관련4테이블과
nullable receipt 연결2열·제약·함수/trigger를 추가/변경한다. schema1 기존 receipt 계약을 유지하지만
DDL이 기존 receipt 테이블을 잠그므로 원본 활동0을 재확인해야 한다. 이 migration은 ES 재시작·보안
전환·별칭 해제를 실행하지 않는다.0063은 별도 numeric receipt table·불변 trigger·검증 helper 및 기존
승인 함수의 호출 추가이며 기존 gate OID를 보존한다.

실제 반영 경로는 기존 `.env`의 본래 DB에 **0061→0062_rag_access_epoch→0063_rag_numeric_proof**다.
읽기 사전검사에서 진행 execution0·평가 run0, epoch/numeric table 없음, frozen gate1·receipt0·acceptance0,
직접 API와 프론트 HTTP200을 확인했다. Windows listener inventory 명령은 값을 반환하지 않았으므로
PID 소유권을 확인했다고 보고하지 않으며 실제 재기동 직전에 exact process를 다시 확인한다.
적용 직전 private backup과 schema/기존 receipt·함수·진행 실행·프로세스 identity를 확보하고,
현재 Alembic의 단일 `begin_transaction` 안에서 정확한0063 target까지 적용한다. `upgrade head`나
stamp를 사용하지 않는다. migration 실패는 transaction rollback으로 대응하며 성공 후0063 downgrade는
차단된다. 이후 문제가 있으면 자료를 보존한 앱 복원 또는 검토한 forward fix를 사용한다.0062는 epoch/floor/
schema2 receipt가 하나라도 생기면 downgrade할 수 없으므로 삭제로 되돌리지 않는다.

승인 후 기존 API만 exact 프로세스·진행 실행0을 확인하고 재시작한다. worker/beat·Docker/IDE와 기존
ES/별칭 gate는 변경하지 않는다. 같은 모델·deployment·색인·고정 QA/rules/정책으로 새 불변 v6/schema3
후보를 정상 owner API에 등록하고 합성 연결 검사·새25×3 평가를 수행한다. 기존 후보를 덮어쓰거나
신뢰 등록/정책을 완화하지 않는다. 정상 owner 의미 검토와 accept를 통과하기 전 pending/defaultfalse다.

본래 새 답변·기존 세션/멀티턴·원문/계산 설명·1440/390px·권한 철회·새로고침의 브라우저 검증은
반영 후 수행한다. Q08 표 단위/헤더/행 provenance와 Q12 정확한 실패 원인은 남아 있다. SDK·벡터
저장소 비교·로컬 파인튜닝은 후속이며, 별칭 종료·첨부/모바일·Git 인계가 남아 품질 개선만 남은 단계가 아니다.

## 실행 중 판정과 비용

| 판정 | 근거 | 잘못됐을 때 비용 |
| --- | --- | --- |
| 기존 main 작업 공간 사용 | 사용자 승인된 무분리 작업 원칙 | 겹친 WIP를 파일별로 검토해야 함 |
| task-local ledger 위치 유지 | 프로젝트 임시 산출물 규칙·PowerShell | 수동 인계 기록 확인 필요 |
| unit와 reviewed single-file trial만 실행 | 기존 자료 보호·통합 fixture 범위 제한 | 무관한 통합 동작은 미검증 |
| unit에 합성 secret만 주입 | 실제 `.env` 로딩 없이 기존 필수 설정 충족 | 운영 credentials는 이 시험의 범위 밖 |
| mypy를 전체 local source 경로로 실행 | editable package discovery 제한 | 전체410 파일 검사 유지 필요 |
| 내부 evidence_ids를 catalogue/wrapper에 보존 | 근거 부족도 정확한 audit 선택 집합 필요 | producer/consumer 일치 검사 필요 |
| 설치된 Node CLI 직접 실행 | 기존 pnpm shim의 vitest 해석 실패 | 패키지 매니저 환경 차이는 미검증 |
| 최초 UI 행동 검증은 구현 후 실행 | 명령 실패를 RED로 오인하지 않음 | 해당 UI의 RED 증거는 없음 |
| 단일 whole-feature review를 original trial 전에 수행 | helper 독립 검토가 실행 선행 조건 | 이후 SQL 수정은 회귀로 검증 |
| inherited formatting은 일괄 변경하지 않음 | 무관한 변경 보존 | 넓은 format check는 기존34 파일 때문에 미통과 |
| final persistence의 DB 검증 오류를 안전한 실패로 변환 | 정상 답변 저장/원시 예외 노출 방지 | 장애 시 해당 답변을 거절함 |
| fixture는 현 owner·기존 원문과 rollback 행만 사용 | 새 환경/DB/계정 금지 | 실모델·의미 품질은 별도 평가 필요 |
