# RAG 색인의 생성 전 출처 등록과 실물 목록

- 상태: 2026-09-20 사용자의 바로 구현 지시에 따라 구현·독립 검증 완료. 실사용 적용과 실제 삭제는 후속이다.
- 기준일: 2026-09-20
- 상위 계약: [휴지통·영구 삭제](2026-09-13-asset-trash-purge-design.md).
- 선행 완료: [SQL 출처](2026-09-14-rag-sql-provenance-design.md), [객체 산출물](2026-09-14-rag-artifact-provenance-design.md).
- 기존 동작 정본: [RAG 수명주기와 alias 복구](../../labs/rag/design.md).
- 후속 구현: 이 문서에서 후속으로 둔 별칭 원장·RAG 색인 쓰기 차단은 [별도 계약](2026-09-20-rag-alias-write-fence-design.md)에서 구현했다. 전체 삭제 활성화는 여전히 후속이다.

## 1. 목적과 이번 범위

문서의 모든 버전에 속한 RAG build와 실제 Elasticsearch 색인을 연결해, 생성 도중 실패한 색인도 향후 영구 삭제 목록에서 놓치지 않는다.
이번 구현은 생성 전 등록, create/bulk 시도 추적, build 변경의 revision 갱신, 읽기 전용 실물 목록이다.
성공은 이 참여자의 등록·대조 계약을 충족했다는 뜻이며 실제 영구 삭제나 전체 작성자 종료를 뜻하지 않는다.
별칭 변경 요청의 영속 실행 원장과 서버 측 종료 증명, 실제 삭제 실행기, 모든 참여자 조립은 후속 통합의 필수 조건이다.
원본 파일, 파서/OCR/뷰어 임시물, 일반 작업 메타데이터의 삭제 소유권은 별도 작업이다. 세 JSON 산출물을 다시 구현하지 않는다.
제품 UI·검색 순위·모델·프로파일 기본값·실사용 DB/ES·서버·백업은 이번 작업에서 변경하지 않는다.

## 2. 구현 전 확인한 동작과 선택

| 코드 경계 | 현재 확인한 동작 | 보완 이유 |
|---|---|---|
| `ingestion/stages.py`, `ProductionIndexingStage._ensure_build` | ES 호출 전에 build UUID와 ingestion 포인터를 commit | build ID 자체는 이미 추적 가능하나 물리 대상은 미확정 |
| 같은 파일의 `index` | create/bulk/count 후 `build.index_name`·count·dimension·prepared 저장 | ES 성공 후 DB 실패 시 정확한 이름과 쓰기 상태가 DB에 남지 않을 수 있음 |
| `indexing/elasticsearch.py`, `create` | 같은 이름이 존재하면 즉시 반환 | 이름만 같은 다른 색인의 소유권·mapping을 검증하지 않음 |
| `indexing/service.py`, `prepare_projection` | build별 이름, chunk ID 기반 upsert, projection count 확인 | 개수 일치만으로 전체 색인의 단독 소유권은 증명되지 않음 |
| `ingestion/stages.py`, 최종 activation | source/profile/build 잠금 중 alias 교체·확인 후 READY 저장 | ES와 DB는 단일 원자적 트랜잭션이 아님 |
| `indexing/recovery.py` | DB의 현재 READY 집합으로 공유 alias와 build 활성 플래그 수렴 | 비활성·실패·준비 중 build 전체 목록을 대신하지 못함 |

대안은 다음과 같다.

1. **권장: build별 등록과 실물 대조를 먼저 연결.** 기존 build를 유지하고 별도 추적 행을 더해 범위를 제한한다. 삭제 실행은 아직 제공하지 않는다.
2. 기존 build의 현재 이름·상태만 목록화. 변경량은 적지만 생성 중 실패, endpoint 교체, 같은 이름 재생성, 미확인 writer를 구분하지 못한다.
3. alias 실행 원장·writer 종료·실제 purge까지 한 번에 구현. 전체 삭제 목표에는 필요하지만 여러 참여자와 공유 alias의 동시성까지 함께 바뀌어 이번 단계보다 범위가 크다.

1번을 상세화한다. 기존 Platform 참여자 계약을 확장하지 않고 RAG 소유 구현으로 연결한다.
별도의 일반 색인 프레임워크나 새 외부 서비스는 만들지 않는다. 공개 API 변경이나 상위 삭제 정책 변경이 없어 별도 ADR 대신 이 상세안을 정본으로 둔다.

## 3. 소유 경계와 식별자

참여자는 `rag_index_resources`, kind는 `index_build`, relation은 `derived_artifact`, contract_version은 1로 한다.
자원 ID는 기존 build UUID를 사용한다. projection ID나 alias를 자원 ID로 사용하지 않는다.
공통 `ResourceIdentity`와 `SourceRelation`에는 기존 계약의 불투명 ID/revision만 전달한다.
물리 색인명·별칭·cluster/index 식별자·입력 fingerprint는 RAG 소유 원장에만 저장하며 일반 로그·최소 삭제 증명에 복제하지 않는다.

물리 색인은 현재 공식 생성 경로에서 build 하나에 대응하지만, 이름 패턴만으로 단독 소유라고 판정하지 않는다.
alias는 처리 프로파일·색인 프로파일에 속한 여러 문서의 공유 연결이다. 문서 삭제 소유물로 등록하거나 alias 전체를 삭제 대상으로 삼지 않는다.
원본은 Platform Assets, 색인과 이 원장은 RAG Indexing이 소유한다. 조립 계층에서 참여자를 연결하며 Platform이 RAG를 import하지 않는다.

## 4. 저장 모델과 제약

| RAG 소유 행 | 필드와 불변 조건 |
|---|---|
| `rag_index_resources` | PK build ID, projection·ingestion job·정확한 workspace/document/asset version·처리/색인 profile, 양수 BIGINT revision, 논리 search store ID, 기대 cluster UUID, 정확한 concrete name·alias, 이름 계약 버전, mapping version·dimension·similarity, nullable index UUID·입력 fingerprint, 생성/갱신 시각 |
| `rag_index_attempts` | 시도 UUID, build/resource ID, operation=`prepare`, open/closed, 안전 결과 코드, 생성/종료 시각 |

cluster UUID는 Elasticsearch가 제공하는 불투명 문자열로 취급하며 Python UUID 형식으로 강제 변환하지 않는다.
논리 store ID와 기대 cluster UUID는 typed settings에서 주입한다. endpoint URL이나 credential은 원장에 보관하지 않는다.
동일 물리 cluster를 여러 논리 store 이름으로 중복 등록하지 않는다. `UNIQUE(cluster_uuid, concrete_name)`으로 같은 대상의 이중 소유를 막는다.
등록한 cluster/name/alias/profile/source는 불변이며 설정이 바뀌었다고 행을 고치지 않는다.
index UUID는 최초 생성·소유권 확인 후 한 번만 NULL에서 값으로 바꿀 수 있다. 이후 다른 UUID는 같은 이름의 재생성 충돌이다.
입력 fingerprint는 첫 prepare 예약 시 확정한다. source/build/profile identity를 포함한 실제 전송할 전체 문서 집합을 명명된 canonical 규칙으로 결합한다.
동시에 정렬한 정확한 chunk ID 집합의 `chunk_ids_sha256`도 저장하며 두 fingerprint는 함께 NULL이거나 함께 유효해야 한다.
이후 목록에서는 현재 SQL chunk ID 집합의 digest와 이 불변값을 먼저 대조하고 ES의 정확한 집합을 확인한다. 원본 본문·벡터를 목록 조회에서 다시 읽을 필요가 없다.
본문을 원장에 복사하지 않는다. 재시도 입력이 다르면 같은 색인에 덮어쓰지 않고 충돌로 차단한다. 정상 재처리는 새 build 수명주기를 따른다.

build/projection/profile/ingestion/source 일치는 명명된 복합 UNIQUE/FK로 강제한다.
build의 `(id, projection_id, document_processing_profile_id, indexing_profile_id)`와 ingestion의 job/projection/source/profile 조합을 참조하고,
source는 기존 정확한 workspace/document/asset version 복합 식별성과 연결한다. 단순 build PK 하나만 참조해 다른 문서와 연결할 수 있게 하지 않는다.
projection의 `(id, asset_version_id, document_processing_profile_id, indexing_profile_id)` 복합 UNIQUE/FK도 추가해 실제 projection profile을 강제한다.
Platform Job의 기존 `(id, workspace_id, asset_version_id)` 복합 UNIQUE를 재사용해 job의 실제 공간·원본도 일치시킨다.
source·projection·build·ingestion에서 추적 행으로의 삭제는 RESTRICT다. attempt의 resource 참조도 RESTRICT다.
기존 CASCADE/SET NULL을 전부 바꾸기보다 추적 자식의 제약으로 외부 대상 확인 전에 원장이 사라지는 것을 막는다.
구현 migration에서 실제 PostgreSQL 삭제 그래프로 이 차단을 검증한다.

`uq_rag_index_attempts_open_resource`는 resource별 `state='open'` 최대 1개를 보장하는 partial UNIQUE다.
open은 종료 시각·결과 코드가 없고, closed는 종료 시각과 allowlist 결과 코드가 있어야 한다.
원장은 최초 build 생성과 같은 트랜잭션에서 revision 1 및 정확한 현재 relation 하나와 함께 등록한다.
build만 생성하고 원장 등록에 실패했는데 ingestion을 계속하는 경로는 허용하지 않는다.

## 5. 쓰기 전 예약과 외부 자원 확인

1. 기존 ingestion→Job→Projection→Asset Version→Document 잠금과 현재 source 검사를 유지한다. 현재 `_ensure_build` 뒤에 있는 descriptor 해석을 build 생성 트랜잭션 안에서 먼저 수행하거나, 검증한 descriptor를 전달받아 같은 트랜잭션에서 불변 profile과 재검증한다. 새 build에는 이름·별칭·cluster binding·descriptor와 출처를 저장해 commit한다. ES mutation은 이 commit보다 앞설 수 없다.
2. 입력 chunk/embedding 검증 뒤 짧은 트랜잭션에서 등록 내용·현재 source·build를 재확인한다. fingerprint를 확정하고 open attempt를 생성, revision/현재 relation을 교체해 commit한다.
3. ES 어댑터는 등록된 단일 concrete name만 받는다. wildcard, comma-separated 목록, alias를 쓰기 대상으로 허용하지 않는다. 호출 전에 실제 cluster UUID가 설정 및 원장과 같은지 확인한다.
4. 새 색인의 mapping metadata에는 기존 `_meta.rag`와 별개인 `_meta.rag_index_resource`에 추적 계약 버전, resource/build ID, source 식별성, 입력 fingerprint를 넣는다. 기존 frozen index inspector는 `_meta.rag`의 key 집합을 정확하게 검사하므로 그 하위에 새 key를 끼워 넣지 않는다. 이 소유권 표식은 최초 create 요청에 포함한다.
5. 이미 같은 이름이 있으면 등록된 표식·mapping·실제 index UUID를 먼저 대조한다. 표식 부재·다른 소유자·다른 descriptor·이미 저장된 UUID와 불일치면 bulk를 호출하지 않는다. 이름만 일치하는 legacy 색인을 인수하지 않는다.
6. 같은 cluster에서 정확한 concrete 대상이 한 개의 물리 색인으로 해석되는지 확인한다. alias/data stream/여러 target으로 해석되면 거절한다. 확인된 UUID는 가능한 최초 경계에서 원장에 저장하고 revision을 갱신한다.
7. 등록 시도의 동일 입력만 bulk에 전달하고 refresh 후 count·정확한 chunk ID 집합·단독 소유 메타데이터를 검증한다. 각 `_id`와 `chunk_id`도 같아야 한다. 단순 count나 표식의 fingerprint만으로 실제 입력 집합이 같다고 판단하지 않는다. bulk의 일부 실패는 전체 성공이 아니다. `_source` 본문이나 개별 실패 payload를 로그에 남기지 않는다.
8. ES 작업 종료와 결과를 확인한 뒤 호출자의 lifecycle 트랜잭션에서 prepared/count/dimension, attempt closed, revision/현재 relation을 함께 저장한다. 실패하면 전체 DB 변경을 rollback하고 open 등록을 유지한다.

create가 성공했으나 UUID 저장 전에 연결이 끊겨도 생성 전 원장과 create에 포함된 표식이 대조 근거로 남는다.
외부 ES 성공이 DB rollback으로 취소됐다고 보고하지 않는다. ES가 저장된 이름을 삭제·재생성하도록 자동 복구하지 않는다.
동일 ready/prepared 결과의 중복 호출은 소유권·UUID·descriptor·정확한 chunk ID 집합·예약 입력 일치 확인 뒤 재사용하며 불필요한 bulk나 새 attempt를 만들지 않는다.
이 검사는 ES에 저장된 본문·벡터 전체의 byte equality나 외부 관리자의 조작 부재를 증명하지 않는다. 입력 fingerprint와 소유권 표식은 접근권한 통제를 대신하는 인증 장치가 아니다.
앱 전용 쓰기 권한과 승인된 writer 경계가 전제이며 검사와 I/O 사이의 관리자 교체까지 방어한다고 주장하지 않는다. 이 전제가 깨지면 쓰기·삭제 준비를 차단한다.
같은 프로세스의 단순 재전달도 open attempt를 자동 승계하지 않는다. 살아 있는 다른 worker와 구분할 수 없으면 busy/미확인 상태를 반환한다.

## 6. 실패·재시도와 작성자 종료의 한계

create/bulk 호출 전 로컬 검증 실패처럼 외부 쓰기가 없거나, 모든 요청의 최종 응답으로 서버 측 실행 종료를 확인할 수 있는 실패만 closed로 기록할 수 있다.
추적 mutation용 client/transport 및 helper의 자동 timeout retry·숨은 bulk 재전송은 비활성화한다. 기존 일반 검색 client의 재시도 정책은 그대로 둔다.
후속 명시적 전송이 성공했어도 선행 timeout 요청이 끝났다는 뜻이 아니다. client 재생성·worker 재전달로 이 제약을 우회하지 않으며 관련 설정과 실제 전송 횟수를 테스트한다.
부분 bulk의 최종 실패 응답은 잔존 레코드가 있다는 의미일 수 있다. closed는 성공이나 색인 부재가 아니라 그 시도가 더 쓰지 않음을 뜻한다.
그 후 재시도는 새로운 attempt UUID를 사용하되 같은 입력과 동일 물리 identity만 재사용한다. 부분 쓰기를 숨기지 않는다.
timeout·취소·클라이언트 연결 종료·worker 프로세스 종료·DB 연결 상실은 ES 서버 요청 종료를 증명하지 않는다.
응답이 불명확하면 open과 `rag_index_writer_unconfirmed` 진단으로 남기고 자동 재시도 쓰기·인계·삭제를 차단한다.
정상 count·색인 존재·lease 만료만으로 open을 닫지 않는다. 운영자에 의한 상태 직접 수정도 공식 복구 절차가 아니다.
기존 worker는 이 오류를 무조건 일반 재시도 가능한 장애로 바꾸거나 타 worker가 소유한 ingestion을 실패시키지 않도록 별도 분류해야 한다.
안전한 busy/미확인 반환과 기존 작업 상태 보존은 구현 계획의 필수 테스트다.

이 단계는 prepare 요청만 시도 원장에 포함한다. alias activation/reconciliation은 여전히 외부 호출 후 DB rollback 또는 늦은 서버 실행이 가능하다.
따라서 prepare 시도가 모두 closed여도 전체 writer 정지 증명이나 purge receipt를 발행할 수 없다.
후속 삭제 통합은 alias의 공유 scope별 영속 예약·종료 확인과 모든 writer 차단을 구현하고 검증한 뒤에만 활성화한다.

## 7. revision·잠금·alias 호환

예약/attempt 시작·종료, index UUID 확정, fingerprint 확정, build count/dimension/status/실제 is_active 변경은 resource revision을 증가시킨다.
한 트랜잭션에서 여러 필드가 바뀌어도 resource당 한 번만 증가한다. 같은 값의 재확인은 증가하지 않는다.
현재 relation은 같은 트랜잭션에서 기대 revision에 대해 정확히 하나만 교체한다. 누락·중복·다른 source는 충돌로 중단한다.
SQL projection 묶음·JSON artifact 묶음 revision은 각각의 기존 의미를 유지한다.

기존 stage/source/profile/build 잠금 뒤 resource→attempt→현재 relation 순서를 추가한다.
여러 build/resource는 build UUID 오름차순으로 잠근다. resource를 잠근 뒤 기존 source/profile 잠금으로 역진입하지 않는다.
activation은 현재 build를 먼저 단독 잠근 뒤 다른 build를 덧붙이지 않는다. profile 잠금 후 현재 build와 활성 전환 대상 전체를 확정·정렬 잠근 뒤 resource 잠금으로 진행한다.
prepare ES I/O는 짧은 예약 트랜잭션 밖에서 수행한다. 기존 alias activation/parity는 source/profile/build 잠금 중 ES를 호출하는 현재 직렬화 계약을 유지한다.
따라서 모든 ES I/O가 DB 잠금 밖이라고 설명하지 않는다. 이번 단계에서 alias를 잠금 밖으로 옮기지 않는다.

최종 activation의 이전 build 비활성화와 parity의 일괄 `is_active` 갱신도, 추적된 각 build의 실제 변경에 대해 revision/관계를 함께 갱신해야 한다.
parity가 resource 잠금 후 다른 build를 추가로 잠그는 역순을 만들지 않는다. 필요한 build 집합 잠금을 먼저 완료한다.
외부 alias 결과가 바뀌었지만 DB rollback이면 revision이 바뀌지 않을 수 있으므로 DB revision만으로 ES 상태를 증명하지 않는다.
추적 build의 activation/recovery는 저장된 binding·name·alias·index UUID를 검증한다. 현재 prefix로 이름을 새로 계산해 기존 대상을 대체하지 않는다.
현재 설정에서 계산한 대상과 등록 대상이 다르면 명시적인 구성 불일치다. 다른 cluster나 새 prefix로 조용히 전환하지 않는다.
legacy build는 기존 처리 경로를 유지하되 추적 완료로 승격하지 않는다. 혼합 alias에서 legacy가 있다는 이유로 다른 문서의 target을 제거하지 않는다.
검색의 READY/current source gate와 기존 profile별 exact alias 수렴은 유지한다. 휴지통 lifecycle/generation gate의 전체 연결은 후속 삭제 통합에서 검증한다.

## 8. 읽기 전용 목록과 실물 대조

입력은 정확한 workspace와 문서별 전체 asset version 집합·generation이다. 현재 활성 버전만 조회하지 않는다.
첫 REPEATABLE READ READ ONLY 관찰에서 모든 상태의 projection/build/ingestion/resource/attempt/current relation을 양방향 대조한다.
building/prepared/ready/failed와 비활성 과거 build를 모두 포함한다. READY alias 복구용 조회를 inventory로 재사용하지 않는다.
DB에 build가 없는 projection은 아직 색인 전 단계일 수 있다. 전체 projection/작업 집합과 단계의 일관성을 확인하되 미래의 build 생성 부재까지 증명했다고 하지 않는다.
등록 없는 build, build 없는 원장, 잘못된 source/job/profile, 오래된 relation은 미해결이다.

DB 트랜잭션 밖에서 등록된 각 concrete name의 cluster/index identity, mapping 소유권, 전체 레코드 수와 source/profile/build가 다른 레코드의 존재를 대조한다.
prepared/ready 대상의 실제 `_id`·chunk ID 집합은 검증된 입력 산출물의 집합과 대조하며 같은 개수의 다른 chunk도 거절한다. 필요한 입력 자료가 없거나 조회를 끝내지 못하면 불완전이다.
존재하는 모든 레코드가 정확한 workspace/asset version/projection/build/profile/mapping 조합이어야 단독 소유 후보로 본다. 필드 누락도 불일치다.
상세 본문을 반환하지 않고 필터·count 또는 제한된 식별 메타데이터 조회로 확인한다. 부분 응답·샤드 실패·timeout을 count 0으로 해석하지 않는다.
해당 concrete index의 모든 alias membership을 확인한다. 등록된 alias 외의 연결은 알려진 공유 의존성으로 차단 보고하며 자동 제거하지 않는다.
공유 alias 전체 target 목록은 owner-side 검사에만 사용한다. 다른 문서의 이름/ID를 사용자 오류 메시지나 공통 DTO에 노출하지 않는다.
활성 여부와 alias membership이 DB의 의도된 상태와 다르면 안전한 불완전 결과로 반환한다. inventory 호출에서 parity나 metadata 보정을 수행하지 않는다.

마지막 새 DB 관찰에서 전체 source/generation/version, projection/build/ingestion 집합·상태, resource revision·관계·attempt가 동일한지 재확인한다.
이 관찰은 DB와 ES의 원자적 snapshot도, 외부 관리자 쓰기 차단도 아니다. 삭제 직전 새 inventory와 writer 차단 뒤 재검증이 별도로 필요하다.

| 관찰 결과 | 공통 목록 판정 |
|---|---|
| 모든 등록과 실물 대조 성공, prepare open 없음 | 이 참여자 범위의 exhausted=true. 전체 writer 종료/삭제 완료는 아님 |
| open prepare, 확인 불능, alias 불일치 | exhausted=false 또는 allowlist 안전 오류 |
| 미등록 build, 소유권/현재 관계 누락·충돌 | legacy_resolved=false 또는 안전 오류 |
| 미지원 계약·저장소 | supported=false |
| build 생성 후 아직 prepare 없음, 실물 없음 | 미생성 자원으로 정상 목록에 포함. 미래 쓰기 차단은 별도 |
| prepared/ready 또는 이미 관측한 UUID의 색인이 없음 | 무결성 오류. 조용히 없음=삭제 완료로 변환하지 않음 |
| 같은 이름 다른 UUID·cluster, 다른 소유 레코드 | identity/ownership 충돌. 수정·삭제 없이 차단 |

성공 반환에는 build ID/revision과 flags만 포함한다. wildcard로 cluster 전체를 검색해 고아 색인이 없다고 선언하지 않는다.
기존 미추적 자료·수동 복제·다른 cluster의 사본은 별도 legacy 조사 대상이다. 이 참여자의 완전성은 추적 활성화 절차와 등록된 관리 범위에 한정한다.

## 9. 안전 오류 계약

owner-side 오류는 명명된 allowlist로 분류한다. 예외 메시지·접속 URL·색인명·query·본문을 일반 로그로 전파하지 않는다.

| 안전 코드 | 의미·처리 |
|---|---|
| `rag_index_binding_mismatch` | 설정·원장·실제 cluster 불일치, 운영 조치 전 차단 |
| `rag_index_identity_conflict` | 대상 유형/표식/UUID/descriptor 불일치, 자동 인수 금지 |
| `rag_index_input_conflict` | 예약한 입력과 다름, 기존 색인 덮어쓰기 금지 |
| `rag_index_attempt_busy` | 다른 open prepare 소유, 새 writer 생성 금지 |
| `rag_index_writer_unconfirmed` | 서버 측 종료 미확인, 일반 재시도 쓰기 금지 |
| `rag_index_inventory_changed` | 관찰 중 DB 대상 변경, 읽기 재수집 가능 |
| `rag_index_inventory_incomplete` | legacy·공유 의존·관계 누락 등, 완료 판정 금지 |
| `rag_index_observation_failed` | DB/ES 대조 실패, 안전 분류에 따른 제한 재조회 |

실패를 다른 모델·저장소·색인으로 전환해 숨기지 않는다. 이 코드들은 owner-side 내부 오류 계약이며 새 공개 API를 추가하지 않는다.

## 10. 향후 제거 계약과 명시적 차단 조건

상위 purge가 현재 권한·generation을 확정하고 prepare·alias·복구·구 worker의 실행 및 ES 서버 처리 종료를 입증한 뒤에만 파괴적 단계로 진입한다.
공유 alias는 DB의 허용된 다른 문서 target을 보존해 갱신하고 재검증한다. 추가 alias·공유 의존성이 있으면 소유자의 별도 해소 전 차단한다.
문서 전용 identity·실제 레코드 집합·다른 참조 부재가 확인된 물리 색인만 전체 삭제 후보가 된다.
frozen 평가처럼 alias를 거치지 않고 concrete index를 직접 사용하는 독립 참조도 해당 소유자의 철회·소비 차단 계약으로 해소해야 한다. alias 분리만으로 모든 소비가 차단됐다고 판단하지 않는다.
공유/미확인 색인은 전체 삭제하지 않는다. 상위 계약의 정확한 불변 ID 조합에 의한 레코드 삭제는 별도 공유 색인 실행기와 수용 검증 전에는 미지원으로 차단한다.
삭제 후 정확한 자원의 부재와 재생성 없음, alias의 다른 문서 target 보존을 확인한 다음 attempt/resource/relation·build 등 SQL 참조를 순서대로 정리한다.
외부 대상 정리 전에 build/projection/source를 CASCADE로 지워 추적 근거를 잃지 않는다.
최종에는 상위 본문 없는 최소 증명만 남긴다. 원장·fingerprint·물리 이름을 영구 감사로 보존하지 않는다.
ES segment·snapshot/백업·외부 사본은 온라인 논리 삭제와 별도이며 이 단계가 물리 secure erase나 전체 사본 제거를 보장하지 않는다.

## 11. 호환·migration·활성화

0041 다음의 additive migration `0042_rag_index_resources`로 원장과 필요한 복합 제약을 추가한다.
기존 build는 자동 등록하지 않는다. 이름 패턴, 현재 endpoint, `is_active`만으로 legacy source·소유권을 추정하지 않는다.
새 공식 build는 반드시 추적 행과 함께 생성한다. 기존 untracked build의 정상 ingestion/recovery 호환은 유지하되 삭제 목록에서는 legacy 미해결이다.
등록 행·시도·참여자 relation이 남아 있으면 downgrade를 안전하게 거부한다. downgrade에서 외부 색인이나 추적 기록을 자동 삭제하지 않는다.
실사용 적용 전 별도 절차로 기존 API/worker/beat·직접 writer를 중지·확인하고 cluster binding을 확인한 뒤 migration과 같은 버전의 writer를 함께 배포한다.
코드 병합만으로 이 절차를 수행했다고 간주하지 않는다. 추적되지 않은 과거 자료는 별도 dry-run 대조와 승인을 거쳐야 한다.
실사용 migration/backfill·서버 재시작·ES 설정 변경·삭제는 이번 작업에서 실행하지 않는다. migration은 전용 합성 DB에서 검증한다.

## 12. 구현 경계와 수용 검증

예상 변경 모듈은 RAG Indexing의 원장·repository·추적 어댑터·inventory, Ingestion의 prepare/activation 연결, Indexing alias recovery와 additive migration이다.
기존 generic ES port를 임의 경로의 삭제 port로 확대하지 않는다. 추적 대상용 typed 연산으로 binding·identity 검사를 강제한다.
Platform 공통 DTO와 SQL/JSON 참여자의 기존 소유권은 유지한다. API·worker 조립에서 기존 untracked/새 tracked 흐름을 명시적으로 구분한다.

필수 검증은 다음과 같다.

1. 등록/attempt commit 실패 시 ES mutation 0건, create 성공 뒤 DB 실패·부분 bulk·timeout 후에도 원장 보존.
2. cross-source/profile/job 복합 FK, 원본/projection/build 삭제 RESTRICT, open UNIQUE, revision/current relation rollback·동시 실행·멱등성.
3. 다른 cluster·같은 이름 다른 UUID·legacy 표식 부재·alias/data stream 입력·다른 소유 레코드·같은 개수의 다른 chunk 집합 거부. 무관 문서 보존. frozen inspector의 기존 descriptor 호환.
4. 실제 embedding artifact dimension과 예약 descriptor 일치, 입력 불일치 재시도 차단, 종료 미확인 재전달에서 추가 bulk 0건 및 기존 작업 상태 보존, 자동 timeout retry·helper 재전송 없음, prepared 재사용 검사.
5. activation과 parity가 바꾼 모든 추적 build revision 갱신, no-op 불변, 다른 문서 target 보존, DB rollback 후 읽기 대조 실패 노출.
6. 모든 상태·모든 버전·영 build·legacy·관계 역방향 조회, 관찰 중 집합/revision 변경, 부분 ES 응답·timeout·없는 색인 처리.
7. upgrade/거부형 downgrade, 기존 legacy ingestion/alias 회귀, 타입·린트·독립 DB/프라이버시/코드 검토.
8. 원시 ES/partial bulk 오류에 합성 본문·벡터·URL·credential·다른 문서 식별자를 넣어도 일반 로그·공통 DTO·오류에 노출되지 않음.

단위 검증은 fake ES와 합성 입력으로 외부 네트워크 없이 수행한다. 통합은 안전 검사된 UUID 전용 PostgreSQL DB와 전용 ES concrete 자원만 쓴다.
기존 통합 테스트를 실사용 `.env`로 일괄 실행하지 않는다. ES 통합의 자원 격리와 정확한 정리 범위가 검증되기 전 실행하지 않는다.
실행한 테스트·정적 검사·독립 검토와 환경 격리 근거는 [작업 기록](../../worklogs/2026-09-20-rag-index-provenance.md)에 남긴다.
