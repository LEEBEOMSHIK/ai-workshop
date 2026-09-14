# RAG SQL 산출물의 출처·내용 revision 연결

- 상태: 승인 범위 구현·통합 검증·독립 최종 검토 완료. 실사용 적용과 실제 삭제는 제외.
- 계획: [단계별 구현](../plans/2026-09-14-rag-sql-provenance.md)
- 상위 계약: [공통 출처·삭제 목록·증명](2026-09-14-asset-purge-provenance-design.md)
- 조사 근거: [저장 경로 및 독립 검토](../../worklogs/2026-09-14-rag-provenance-connection-survey.md)
- 목적: RAG 재처리로 DB 산출물이 바뀌면 기존 삭제 목록을 재사용할 수 없게 한다.

## 1. 범위와 모듈 소유자

`rag_document_projections`, `rag_structural_elements`, `rag_retrieval_chunks`, `rag_evidence_units`를 하나의 SQL 산출물 묶음으로 추적한다.
참여자는 `rag_document_sql`, 종류는 `projection_bundle`, 자원 ID는 projection UUID, 관계는 `derived_artifact`다.
이 이름은 프로토콜 식별자이며 환경 설정값이나 전체 RAG 완료 표시가 아니다.
RAG가 자신의 테이블과 자원 의미를 해석하고 Platform Assets는 일반 출처 계약만 제공한다. Platform에서 RAG를 import하지 않는다.

`rag_index_builds`, ingestion job/dispatch/handoff·외부 산출물 파일·OCR/뷰어 파일·Elasticsearch·평가·생성·Learning·Publishing은 이 참여자의 범위가 아니다.
전체 삭제 조립 계층은 이 참여자 하나를 전체 필수 참여자 집합으로 사용해서는 안 된다. 실제 전체 조립·삭제·receipt 발행은 이번에 구현하지 않는다.

## 2. 내용 revision

projection에 nullable positive BIGINT `content_revision`을 추가한다. NULL은 추적 전 기존 자료이며 1로 추정하지 않는다.
신규 projection은 revision 1과 정확한 source 관계를 같은 트랜잭션에서 만든다.
추적된 projection의 구조 요소 교체, 청크·근거 집합 교체, 실제 상태 전이마다 revision을 단조 증가시킨다.
상태도 묶음의 내용으로 취급하여 pending 이후 내용이 생기는 경우나 failed 전환에서 기존 목록을 무효화한다.
동일 상태 요청이나 단계 완료 중복 전달로 실제 쓰기가 생기지 않으면 revision은 유지한다.
한 트랜잭션에서 구조 저장과 상태 전이가 각각 발생하면 각각 증가한다. commit당 정확히 1로 합치지 않는다.
교체 요청이 실제 delete/reinsert를 수행하면 결과가 의미상 같아도 새로운 revision이다. 본문 해시로 동등성을 추정하지 않는다.

기존 NULL projection의 정상 ingestion은 유지하되 자동으로 추적 완료로 승격하지 않는다. 목록에서는 기존 자료 확인 필요로 반환한다.
출처를 확인하는 backfill은 별도 승인 작업이다. 새 코드가 배포됐다는 이유만으로 기존 자료 전체를 완료 처리하지 않는다.

## 3. 쓰기와 현재 관계 갱신

각 aggregate 쓰기 메서드는 projection 잠금으로 직렬화한다. 현재 DB revision을 읽고 원래 값에 대한 조건부 갱신으로 lost update를 막는다.
현재 ORM 캐시값만으로 revision을 정하지 않는다. 기존 ingestion의 잠금 순서를 뒤집는 추가 source 잠금은 넣지 않는다.
`populate_existing` 또는 명시적 refresh로 잠금 후 최신 값을 사용한다.
기존 `ensure`는 source를 먼저 잠그므로 재사용 projection에 대한 신규 잠금·legacy 자동 등록·revision 보정을 추가하지 않는다.
현재 worker의 ingestion→Job→projection→Asset Version→Document 순서와 미래 purge의 잠금 조정은 별도 활성화 검증 사항이다.
신규 source는 실제 Asset Version→Document→Workspace 조회와 공통 복합 FK로 확인한다.

추적된 묶음에는 현재 revision의 정확한 source 관계 하나만 유지한다. 이전 revision 관계는 새 관계와 같은 트랜잭션에서 교체한다.
기존의 범용 `register()` 멱등 계약은 유지하고, 현재 관계 교체는 별도의 제한된 repository 연산으로 구현한다.
교체 전 source·participant·kind·resource ID·기대 revision·관계 유형을 모두 확인한다. 누락·추가·다른 소유자·기대 revision 불일치는 충돌이며 임의 복구하지 않는다.
현재 관계 조건부 교체의 영향 행 수는 정확히 1이어야 한다. 이 전용 자원에 남은 다른 source 또는 revision 관계도 충돌로 확인한다.
공유 자원의 일반 출처 관계나 다른 참여자의 행을 삭제하는 범용 전체 삭제 연산은 만들지 않는다.
과거 목록·receipt는 자체 복사된 revision을 유지하므로 현재 관계 교체가 이전 검증을 새 revision으로 승격하지 않는다.

본문 저장, revision 변경, 현재 관계 교체 중 하나라도 실패하면 호출자 트랜잭션 전체를 rollback한다. repository는 commit하지 않는다.
새로운 등록 실패를 경고만 남기고 ingestion 성공으로 처리하지 않는다.
`ingestion/recovery.py`의 직접 FAILED 상태 변경도 공통 mutation 경로로 연결한다. `tasks.py`의 동일 상태 재대입은 추가 증가를 만들지 않는다.
이 단계의 보장은 정식 repository 쓰기 경계에 대한 것이다. 임의 SQL writer·이전 worker 전체 차단이나 DB 관리자 우회 방지까지 구현했다고 표현하지 않는다.
SQL trigger는 이번에 추가하지 않는다. 별도 SQL writer를 허용하려면 동등한 강제 갱신 계약이 실제 삭제 활성화 전에 필요하다.

## 4. 읽기 전용 목록 어댑터

입력은 정확한 workspace와 문서별 모든 Asset Version ID다. 파일명·원본 SHA-256로 다른 문서의 자원을 합치지 않는다.
권위 있는 projection→Asset Version→Document→Workspace 조인과 등록 대장을 양방향 비교한다.
현재 활성 버전 또는 READY 상태만 조회하지 않는다. pending·실패·부분 완료·과거 비활성 projection도 포함한다.
실제 하위 테이블은 본문을 읽지 않고 식별자·소속 관계·건수의 정합성을 검증한다.
등록만 있고 실제 자원이 없거나, 실제 자원이 있는데 등록이 없거나, revision·소유자가 다르면 완료가 아니다.

목록 서비스가 소유하는 PostgreSQL REPEATABLE READ READ ONLY 트랜잭션에서 조사한다. 임의의 기존 쓰기 트랜잭션에 그대로 결합하지 않는다.
전체 페이지를 같은 트랜잭션에서 읽고 여러 SELECT 사이에 다른 commit의 값을 섞지 않는다. 이 스냅샷의 결과는 이후 삭제 실행의 현재 상태 재검사를 대체하지 않는다.
어댑터 호출은 읽기 전용이며 출처 backfill·revision 갱신·자료 삭제·receipt 저장을 수행하지 않는다.
확실히 자원이 없는 유효한 source는 빈 목록이 가능하지만, source 자체 부재·다른 공간은 빈 성공으로 바꾸지 않는다.
미등록 기존 자료는 `legacy_resolved=false`, 미지원 종류/계약은 `supported=false`, 전체 조회 미완료는 `exhausted=false`로 표현한다.
SQL 실패는 안전한 오류로 전달하며 예외를 빈 목록으로 바꾸지 않는다.
반환은 기존 `ParticipantInventory` 계약의 불투명 ID·revision·완전성 값으로 제한한다. 본문·경로·이미지/원본 해시는 포함하지 않는다.

스냅샷 이후의 쓰기까지 막았다는 뜻은 아니다. 후속 실제 삭제 실행기는 writer 차단과 현재 revision 재검증을 별도로 수행해야 한다.

## 5. migration과 실행 경계

0039 다음 additive migration으로 nullable revision과 양수 제약을 추가한다. 기존 행의 revision은 NULL로 남긴다.
일반 등록 대장 스키마는 재사용한다. 기존 source FK·UNIQUE·RESTRICT를 약화하지 않는다.
추적된 revision 또는 해당 참여자 관계가 남으면 downgrade는 안전 코드로 거부한다. 비어 있는 추적 상태에서는 원래 데이터를 보존하며 되돌릴 수 있어야 한다.
실사용 DB 적용·기존 자료 backfill·서버/worker 재시작·외부 모델 호출·실제 삭제는 이번 작업에 포함하지 않는다.
새 패키지·가상환경·worktree를 만들지 않고 main의 기존 사용자 변경을 보존한다.

## 6. 수용 기준

- 신규 projection과 source 관계가 함께 commit/rollback된다.
- 구조 요소·청크·근거·상태 변경은 revision과 현재 관계를 함께 바꾼다.
- 중복 전달의 실제 무변경 경로는 revision을 올리지 않는다.
- 동시 교체에서 증가를 잃거나 이전 revision 관계가 현재 관계로 남지 않는다.
- 여러 원본 버전·여러 projection·모든 상태를 누락 없이 조사한다.
- 다른 공간/문서/버전, 미등록 기존 자료, 고아·초과 관계, 오래된 revision을 거부하거나 미완료로 표시한다.
- 목록 결과와 오류에는 비공개 본문·경로·원본 해시가 없다.
- additive migration의 이전 자료 보존과 안전 downgrade를 합성 격리 PostgreSQL에서 검증한다.
- 기존 파싱·청킹·상태 전이·ingestion 멱등 회귀 및 타입·린트, 독립 검토를 통과한다.
- 이 참여자의 성공을 전체 영구 삭제 완료로 해석하는 제품 경로가 없다.
