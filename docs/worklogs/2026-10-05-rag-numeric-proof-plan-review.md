# 원문 기반 계산 근거 구현 계획 준비·검토

- 날짜: 2026-10-05
- 범위: 관리자 DB ISSUE-00026, 관련 ISSUE-00005
- 단계: 작성된 명세 사용자 승인, 구현 계획 준비·검토. 제품 구현·실모델 평가 미착수.
- 정본: [승인 명세](../superpowers/specs/2026-10-05-rag-numeric-proof-design.md), [ADR-0036](../decisions/0036-rag-source-backed-calculation.md), [구현 계획](../superpowers/plans/2026-10-05-rag-numeric-proof.md)
- 이전 불변 기록: [설계·원문 진단](2026-10-05-rag-numeric-proof-design-review.md), [첫75 평가](2026-10-05-rag-fresh75-evaluation.md), [실패7 진단](2026-10-05-rag-failed7-diagnostic.md)

사용자의 구현 진행 요청으로 작성된 명세 승인을 반영했다. 작성된 계획을 검토하고 실행 방법을
선택한 뒤 구현한다. 권고는 현재 세션에서 메인 Codex가 Task별로 구현하고 독립 검증·리뷰를
분리하는 방식이다. nonce·wire·검증·저장·digest의 공용 계약을 한 책임자가 통합한다.

## 범위와 역할

위험 등급은 높음이다. 응답 계약과 저장·복원·승인 경로를 함께 확장하므로 요구/설계·아키텍처·
RAG/AI·Python·DB·프론트엔드·테스트 설계 역할을 포함했다. 구현 책임과 독립 코드 리뷰·권한/
프라이버시·통합 검증 책임을 분리했다. 계획 입력은 두 담당에 겹치지 않게 배정하고 메인 Codex가
실제 파일·명령과 승인 명세를 대조했다. Docker·배포 구조 변경은 없어 인프라 역할은 제외했다.

| Task | 구현 대상 | 핵심 검증 |
| --- | --- | --- |
| 1 | 불변 숫자 정책과 원문 토큰 목록 | 요청 nonce·원문 occurrence·명시 단위·상한 |
| 2 | schema3·Codex wire2·프롬프트와 준비 검사 | 닫힌 구조·승인 payload·미지원 provider 거절 |
| 3 | Decimal 계산 검증과 검색 연결 | 정확 부호/단위·자기 인용·최종 권한 |
| 4 | 원자적 audit/receipt와 DB gate | 서버 실행 문맥·payload 해시·legacy 조회 보존 |
| 5 | 저장/API/관리자 주장 검토 | proof 왕복·digest·접힌 계산 설명·원문 접근 |
| 6 | 원본0061 rollback SQL trial과 관련 검사 | COMMIT 차단·전체 rollback·기존 자료/결과 보존 |
| 7 | 본래 반영·새 전체 평가·인계 | 명시 migration 경로·실제 브라우저·정상 승인 |

## 검토로 구체화한 경계

기존 Codex 요청의 UUID를 PreparedGeneration에 보존하고 provider와 validator가 같은 요청을
검증한다. validator의 기대 문맥은 실제 pipeline 입력에서 받으며 catalogue에서 역산하지 않는다.
Python code point와 JavaScript UTF-16 위치를 섞지 않고 UI는 code point 배열로 결과 위치를 읽는다.

복원 때는 대상 turn/attempt/monitoring record의 신뢰된 실행 ID로 audit·동결 프로파일·서버
receipt를 먼저 조회한다. 같은 사용자의 다른 정상 receipt와 payload를 통째로 가져와도 대상
실행 문맥과 맞지 않으면 거절한다. authoritative schema3에서 envelope가 없어졌다고 legacy로
내리지 않는다. 과거 schema1/2는 새 receipt 테이블을 조회하지 않아 현재0061 읽기를 보존한다.

audit와 receipt는 같은 transaction에서 저장하고 pipeline이 commit한 뒤 결과에 연결한다.
검증 실패/commit 전 취소는 receipt가 없다. commit 후 최종 권한 철회/취소는 이미 저장한
immutable 검증 기록을 보존하되 답변·proof를 정상 결과로 저장/반환하지 않는다.

canonical payload는 검증 이후 생성되는 audit/validation ID와 payload_digest 자체를 제외한다.
audit 전 검증형과 저장 후 복원형이 같은 bytes를 만들도록 identity 필드를 고정했다. 순수
serialization 모듈은 Search/evaluation을 import하지 않아 순환 의존을 피한다. 기존 대화 서명은
내용·사용자·구성·범위를 확인하며 계산 근거는 서버 결과/receipt로 별도 검증한다.

기존 audit ORM에 새 SELECT 컬럼을 추가하지 않는다. 새0063 migration은 미적용0062를 parent로
준비하되 묵시적 upgrade head나 stamp를 하지 않는다. 본래0061에서 단일 연결의 rollback
DDL trial은 실제 migration/API 반영·HTTP 경쟁·실모델 검증과 구분한다. 새 테이블/함수가 없는
상태의 schema3 준비 검사는 명시적으로 거절하고 기존 프로파일은 유지한다.

원본 trial의 실패도 원문을 노출하지 않도록 assert rewriting을 끄고 짧은 traceback을 사용한다.
SQL parameter/echo를 차단하고 DB/API 예외는 원 statement/parameters 없이 고정 오류 코드로
변환한다. 본문 repr·assert diff·로그/검증 receipt 저장을 금지한다.

## 확인과 미실행 범위

프로젝트 개발 에이전트 역할 계약 검사를 실행해 exit0을 확인했다. 실제 코드와 기존 테스트
경로·frontend 명령을 읽어 계획의 잘못된 test 경로와 모호한 정적 검사 명령을 바로잡았다.
명세의 연산·상한·자기 인용·provenance·호환성·개인정보·본래 검증 요구를 Task1–7에 연결했고,
메인 자체 검토와 독립 저장·권한 리뷰의 발견 사항을 계획에 반영했다.

독립 검토 발견5건은 보완 후 모두 해소됐으며 blocking0이다. 기존 경로29개 누락0과 package
명령 실재를 별도로 확인했다. 관련4문서·로컬 링크15개·미완성 표기·일본어 문자·공백·기본 비밀
패턴·최근 완료5개 검사는 exit0이다. 기본 비밀 검사에서 task-by-task 문구를 짧은 키 패턴으로
오인한 항목은 패턴을 실제 긴 키 형태로 한정해 수정한 뒤 재검사했다. tracked diff 공백 검사도
exit0이다. 이 결과는 문서/계획 검토이며 제품 검사 통과가 아니다.

정상 관리자 API로 이 보고서의 정확한 버전을 문제5/26에 추가 연결하며 기존 문서/
사건/관련 없는 필드를 보존한다. 문서 검사와 DB 등록의 실제 결과는 WORKBOARD와 task-local
검증 receipt에 기록한다. 이 보고서를 DB 등록한 뒤에는 본문을 소급 수정하지 않는다.

제품 코드/테스트·패키지·DB schema·모델/runner·프로파일/승격·서버·별칭·Git은 변경하지 않았다.
계획에 적힌 RED/GREEN, unit/통합/타입/린트 명령은 구현 단계에 실행할 명령이며 지금 통과한
제품 검사로 보고하지 않는다. 기존 활성 구성과 후보 pending/defaultfalse를 보존한다.

새 전체 평가의68완료/7실패와 실패7 재시도의7실패는 그대로다. Q08은 원문 단위 문맥이 있지만
현재 구조에 단위→헤더→셀 결속이 없고 Q12에는 완전한 직접 날짜가 있다. 실패 정확 표현은
미확정이며 계산 기능으로 둘 다 해결된다고 약속하지 않는다. 표 구조 보강과 날짜 상세 진단,
별칭 종료 proof·새 본래 답변/멀티턴·실제 첨부/모바일·Git 인계도 남아 품질 개선만 남은 상태가 아니다.

다음은 작성된 구현 계획의 사용자 검토와 실행 방법 선택이다. 이후 Task1부터 외부 모델 없는
단위 회귀로 구현하고 저장/권한 SQL 검증과 본래 반영·전체 평가를 순서대로 진행한다.
