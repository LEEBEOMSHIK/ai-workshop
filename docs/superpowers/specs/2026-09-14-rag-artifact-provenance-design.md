# RAG 객체 산출물의 생성 전 출처 등록

- 상태: 승인 범위 구현·개별/전체 보완 독립 검증 완료. 실사용 적용·전체 삭제 활성화는 제외.
- 근거: [외부 산출물 조사](../../worklogs/2026-09-14-rag-external-artifact-survey.md).
- 상위: [휴지통·영구 삭제](2026-09-13-asset-trash-purge-design.md), [SQL 출처 연결](2026-09-14-rag-sql-provenance-design.md).

## 1. 범위와 선택

첫 범위는 RAG의 parsed/chunks/embeddings JSON과 이를 게시하기 위한 객체 저장소 임시 파일이다.
원본 업로드, 파서가 원본을 복사하는 임시 디렉터리, DOCX/PDF OCR 입력 이미지, 뷰어 임시물, ES/build, 작업 기록 삭제 실행, 공유 모델 캐시는 제외한다.
제외한 문서 전용 임시물도 전체 삭제 활성화 전 별도로 연결해야 한다. 이 참여자를 전체 RAG 완료로 표시하지 않는다.

일반 source 관계만 등록하면 작성 중인 시도·임시 경로·게시 무결성 상태를 표현할 수 없다.
따라서 공통 관계는 재사용하되 RAG 소유의 묶음·슬롯·작성 시도 행을 추가한다. 모든 기술용 범용 파일 작업 프레임워크는 만들지 않는다.
Platform은 기존 일반 출처 계약만 제공하고 RAG를 import하지 않는다. 파일 I/O는 객체 저장 어댑터 뒤에 둔다.

## 2. 식별자와 저장 모델

참여자는 `rag_ingestion_artifacts`, 종류는 `artifact_bundle`, 관계는 `derived_artifact`, contract_version은 1이다.
자원 ID는 별도 bundle UUID다. projection UUID와 혼용하지 않는다. 하나의 projection에는 하나의 bundle만 있다.

| RAG 소유 행 | 내용·제약 |
|---|---|
| `rag_artifact_bundles` | UUID, projection ID UNIQUE, 연결 ingestion job ID, 정확한 workspace/document/asset version, 양수 BIGINT revision, 생성/갱신 시각 |
| `rag_artifact_slots` | UUID, bundle ID, role(parsed/chunks/embeddings), 논리 store ID, store binding UUID, 정확한 key, state(reserved/verified), 게시 size/hash. UNIQUE(bundle, role), UNIQUE(store ID, key) |
| `rag_artifact_attempts` | UUID, slot ID, store ID, store binding UUID, 정확한 임시 key, 제안 size/hash, state(open/closed), 안전 결과 코드, 생성/종료 시각. UNIQUE(store ID, temporary key) 및 슬롯별 open 시도 최대1개를 DB 제약으로 보장 |

슬롯은 세 종류만 허용하고 reserved는 게시 size/hash가 NULL, verified는 둘 다 유효해야 한다. 파일이 존재한다는 이유만으로 verified로 바꾸지 않는다.
slot의 UNIQUE(id, store ID, binding UUID)와 attempt의 복합 FK로 동일 저장소 연결을 보장한다.
`uq_rag_artifact_attempts_open_slot`은 PostgreSQL의 `UNIQUE(slot_id) WHERE state='open'` 인덱스다. 애플리케이션 busy 검사만으로 대체하지 않는다.
closed는 종료 시각·허용된 결과 코드가 있고, open은 종료 시각이 없다.
bundle의 source 복합 FK와 ingestion job/projection/asset 일치는 필요한 복합 UNIQUE/FK로 확인한다. 기존 projection PK만 참조하고 서로 다른 asset을 연결할 수 있는 구조는 허용하지 않는다.
source/projection/job에서 관련 등록 정보로의 삭제는 RESTRICT다. 자식 슬롯/시도를 포함해 외부 자원 확인 전에 CASCADE로 추적 정보가 사라지지 않는다.
일반 Job·dispatch·handoff 전체를 이 묶음의 삭제 소유물로 편입하지 않는다. Job ID는 작성 주체 추적을 위한 참조다.

store ID는 typed 설정의 안정된 논리 저장소 식별자다. 물리 저장소에는 별도 초기화 절차로 binding UUID를 가진 루트 표식 `.ai-workshop-store.json`을 둔다.
설정의 기대 UUID, 표식의 UUID, 슬롯/시도의 UUID가 모두 같아야 쓰기와 대조를 진행한다. 표식 부재·불일치·잘못된 형식·reparse이면 차단하며 호출 중 표식을 자동 생성/수정하지 않는다.
같은 물리 저장소에 논리 별칭을 중복 등록하지 않는다. 저장소 설정은 승인된 단일 binding만 제공한다. 표식은 문서 자료가 아니므로 문서 삭제 대상이 아니다.
현재 경로를 새 빈 저장소로 바꿔 놓는 실수는 이 검사로 차단한다. 관리자에 의한 표식 복제·조작을 방지하는 인증 장치는 아니며 저장소 이동/복제는 별도 검증·접근권한 절차다.
기존 canonical key 규칙 `rag/parsed/{projection}.json`, `rag/chunks/{projection}.json`, `rag/embeddings/{projection}.json`을 유지하고 슬롯 생성 시 실제 key를 저장한다.
key 규칙 버전을 명명된 계약으로 고정한다. 기존 자료의 key를 현재 환경 설정만으로 추정해 등록하지 않는다.
본문·파일명·경로·해시는 공통 출처 relation, 목록 DTO, 일반 로그에 복제하지 않는다. size/hash는 RAG 소유 무결성 메타데이터에만 둔다.

## 3. revision과 원자성

신규 projection/job을 만드는 공식 ingestion 트랜잭션에서 bundle(revision 1), 세 reserved 슬롯, 현재 source relation 하나를 함께 만든다. 이 commit 전에는 외부 queue 전송이나 객체 쓰기를 허용하지 않는다. 기존 DB dispatch/outbox 행은 같은 트랜잭션에서 생성할 수 있다.
단독 projection 저장 API가 Job을 임의 생성하지 않는다. 실제 ingestion 등록 경계가 bundle을 생성하며, bundle 없는 projection은 목록에서 미추적 상태다.
신규 등록 시 generic register의 충돌 무시 결과만 믿지 않고 정확한 source와 유일한 현재 관계를 검증한다.
attempt 생성·종료, 슬롯의 실제 verified 전환을 포함하는 변경 트랜잭션은 bundle revision을 증가시키고 공통 현재 관계를 같은 트랜잭션에서 교체한다.
같은 결과의 멱등 재확인은 증가시키지 않는다. 파일 묶음은 한 명령 트랜잭션의 여러 변경을 합해 정확히1 증가시킨다. 기존 SQL 묶음의 증가 계약은 바꾸지 않는다.
슬롯의 검증된 canonical bytes는 불변이다. 다른 내용으로 덮어쓰거나 재처리를 위해 기존 revision을 되돌리지 않는다.
외부 파일 내용은 DB revision만으로 증명되지 않는다. 목록 수집과 실제 삭제 직전에 실물/작성자 상태를 별도로 대조해야 한다.

## 4. 작성·게시 순서

1. 공식 ingestion 경로에서 현재 source/job/projection과 등록된 슬롯을 확인한다.
2. 이미 verified인 슬롯은 실제 bytes 검증 후 재사용한다. 그 외에는 슬롯을 짧게 잠그고 open attempt가 없는지 확인한 뒤 새 attempt UUID·정확한 임시 key·제안 bytes size/hash를 저장하고 revision/관계를 갱신해 commit한다. 실패하면 파일 I/O를 시작하지 않는다.
3. 추적 전용 객체 저장 연산은 지정된 임시 key만 exclusive-create로 작성한다. 내부에서 또 다른 미등록 UUID 임시 파일을 생성하지 않는다.
4. 파일 내용을 완성·flush한 후 기존 put-if-absent 의미로 canonical key에 게시한다. 다른 파일을 덮어쓰지 않는다.
5. 실제 canonical bytes를 다시 읽고 size/hash 및 기존 파싱·청크·임베딩 도메인 검증을 수행한다. 생성 입력이 아니라 게시된 실제 bytes가 기준이다.
6. 자신의 쓰기를 끝내고 정확한 임시 key를 정리·부재 확인한다. 이 확인에 실패하면 attempt는 open으로 남긴다.
7. 현재 lifecycle/source와 정확한 attempt token을 재확인하고 슬롯 verified·attempt closed·기존 ingestion key/hash·관련 단계 완료를 같은 호출자 DB 트랜잭션으로 저장한다. 파싱/청킹의 SQL 묶음 변경과도 함께 commit/rollback한다.

작성 등록은 짧은 자체 트랜잭션으로 commit하지만, 게시 최종화 repository는 lifecycle이 전달한 session을 사용하며 commit하지 않는다. 파일 어댑터가 DB 최종화까지 독립 commit하는 구조는 금지한다.

동일 슬롯의 다른 open 시도가 있으면 안전한 busy 오류를 반환하고 별도 쓰기를 시작하지 않는다. canonical key는 기존 원자적 put-if-absent 의미를 유지하며 덮어쓰지 않는다.
게시된 bytes의 source·projection·profile/descriptor 일치를 검증해야 한다. 이미 완료된 단계의 중복 요청은 기존 검증 결과를 반환하며 신규 attempt를 만들지 않는다.
게시 전에 canonical 파일이 이미 있는데 이를 설명할 과거 추적 시도·검증 정보가 없다면 임의로 소유권을 인수하지 않고 충돌로 차단한다.
DB 갱신 실패가 이미 게시된 파일까지 rollback했다고 보고하지 않는다. 등록된 open attempt가 장애 후 대조의 근거로 남는다.

## 5. 잠금과 중단된 시도

기존 ingestion 잠금 순서를 유지하고 새로운 bundle→기존 source/job/projection 역방향 잠금을 만들지 않는다.
기존 잠금이 필요한 명령은 기존 순서로 취득한 뒤 bundle→slot→attempt→해당 현재 relation을 잠근다. 잠금 조회는 최신 ORM 상태를 다시 읽는다.
파일 I/O 중 DB 트랜잭션·행 잠금·advisory lock을 길게 유지하지 않는다. DB 연결 해제가 외부 writer 종료를 보장한다고 가정하지 않는다.
추적만 갱신하는 명령은 bundle 이하만 잠그고 이후 기존 잠금 체인으로 진입하지 않는다.
같은 트랜잭션에서 SQL 묶음과 파일 묶음을 모두 갱신할 때는 기존 projection 변경을 먼저, 파일 bundle 변경을 뒤에 수행한다.

타임아웃·lease 만료·DB 연결 끊김만으로 open attempt를 closed로 바꾸거나 임시 파일을 지우지 않는다.
정상적으로 쓰기 종료·임시 key 부재를 확인한 실패는 attempt를 closed와 안전 실패 코드로 남길 수 있다. 그 후 재시도는 새 UUID를 사용한다.
종료를 확인하지 못한 open 시도가 있으면 새 시도 생성·인계·임시 key 재사용을 막는다. canonical 파일의 존재/hash 일치만으로 작성자가 종료됐다고 판단하지 않는다.
살아 있는 작성자가 없다는 검증 없는 강제 종료 복구는 `writer_unconfirmed`로 남긴다. 실제 writer 정지/증명 및 삭제 실행기는 후속 통합 범위다.

## 6. 경로·임시 파일 안전

새 추적 전용 어댑터는 store ID와 등록된 canonical/temp key만 받는다. 사용자가 전한 절대 경로·glob·디렉터리 prefix를 삭제 입력으로 받지 않는다.
임시 key는 canonical과 같은 저장소·부모 아래 `.{canonical filename}.{attempt UUID hex}.tmp`로 예약한다. role/UUID 기반 canonical과 다른 이름 영역이며 해당 시도 외에는 재사용하지 않는다.
허용 루트, 정규화 key, Windows 경로 별칭·대소문자 충돌, symlink/reparse/junction과 루트 자체 접근을 거부한다.
경로 검사는 문자열 startswith가 아니라 실제 루트와 구성요소 기준이다. 검사 후 바뀐 경로를 따라가지 않도록 I/O 직전에도 검증한다.
임의의 로컬 관리자에 의한 파일 교체까지 보장하는 격리는 아니다. 운영 저장 루트는 앱 전용 권한이 필요하며 이 가정이 깨지면 삭제를 활성화하지 않는다.
generic ObjectStore.put/put_if_absent를 쓰는 원본 업로드 경로의 의미는 바꾸지 않는다. RAG 세 게시 경로만 새 추적 연산으로 연결한다.

## 7. 읽기 목록과 실물 대조

입력은 정확한 workspace 및 문서별 전체 version/generation이다. 유효하지 않은 source는 빈 성공으로 바꾸지 않는다.
먼저 한 REPEATABLE READ READ ONLY 트랜잭션에서 모든 상태의 projection·bundle·세 슬롯·모든 attempt·현재 공통 관계와 ingestion 참조를 양방향 확인한다.
실제 저장소는 별도 단계에서 정확한 canonical/temp key를 조사한다. 내용은 필요한 무결성 검사에만 읽고 반환하거나 로그에 출력하지 않는다.
마지막 DB 읽기에서 source generation/전체 버전, bundle revision/현재 관계, 대상 집합이 같은지 재확인한다. 달라졌으면 안전한 변경 오류로 재수집한다.
SQL과 파일의 원자적 snapshot이라고 표현하지 않는다. 정상 결과 역시 수집 구간의 관찰 결과이며 미래 writer 차단을 대체하지 않는다.

- 세 슬롯 및 attempt가 완전히 등록되고 조회를 마친 경우에만 이 참여자 목록의 exhausted를 인정한다.
- open attempt나 실물 확인 불능은 exhausted=false다. timeout을 빈 파일 성공으로 바꾸지 않는다.
- reserved 슬롯의 파일 부재는 아직 미생성일 수 있지만, 실물이 있으면 무결성과 과거 시도 연결 확인 전 완료로 판단하지 않는다.
- verified 파일의 부재·size/hash 불일치, 등록 누락·다른 source·과거 relation·ingestion 참조 불일치는 legacy_resolved=false 또는 안전한 오류다.
- closed attempt의 임시 파일 잔존은 불완전 상태이며 숨기거나 자동 삭제하지 않는다.
- 미지원 종류/저장소/계약은 supported=false다. DB/파일 오류에는 안전 코드만 제공한다.
- 정상 반환은 ParticipantInventory의 bundle ID/revision·완전성 flags뿐이다. detailed owner-side 관찰값은 공통 DTO나 최소 증명에 저장하지 않는다.

## 8. 기존 자료와 배포

기존 projection/job/file에 bundle이 없으면 미추적 상태다. 신규 코드 실행이나 파일명 패턴 일치만으로 자동 backfill하지 않는다.
기존 미추적 ingestion의 정상 처리 계약은 유지하되 이 참여자의 삭제 준비 완료로 인정하지 않는다. 새로 만드는 projection에는 반드시 추적이 붙는다.
업그레이드 전에 API/worker 버전 혼재를 제거해야 신규 자료의 완전한 추적을 주장할 수 있다. 이전 worker·직접 SQL/파일 쓰기까지 강제 차단한 것으로 설명하지 않는다.
0040 다음 additive migration으로 새 테이블과 필요한 정확한 소유권 제약을 추가한다. 기존 자료와 key는 이동하지 않는다.
새 추적 행이 남아 있으면 downgrade는 안전 코드로 거부한다. 실제 migration·backfill·worker 재시작은 별도 대상 확인 후 수행한다.

## 9. 제거·보존 경계

추적 행은 영구 보관 기록이 아니다. 향후 writer 중단→외부 실물 정리→잔존 검증→원장/relation 해소→source/작업 정리 순서로 제거한다.
최종에는 상위 계약의 본문 없는 최소 삭제 증명만 남긴다. 경로/hash/시도별 상세 정보를 영구 증명에 복제하지 않는다.
이번 구현은 실제 purge·receipt 발행·휴지통 UI·전체 참여자 조립을 활성화하지 않는다. 일반적인 자기 시도의 임시 파일 정리와 사용자가 요청한 문서 영구 삭제를 구별한다.

## 10. 수용 기준

- 예약/attempt 등록 commit 전 파일 쓰기0건, 등록 실패 시 파일0건.
- 파일 게시 후 DB 실패·강제 프로세스 종료 후에도 정확한 소유권/시도·임시 key를 조회할 수 있음.
- 동시·중복 게시 시 canonical bytes 비덮어쓰기, 게시된 결과 검증과 revision/현재 관계 일치.
- 종료가 확인된 실패 후 재시도는 별도 시도, 과거 open이 남으면 차단, 생존 확인 없이 완료 처리하지 않음.
- 기존 자료 자동 backfill 없음, 모든 source/버전/상태 및 양방향 정합성 검사.
- 실제 파일·DB 변경이 교차하면 변경 감지/불완전 반환, 본문/경로/hash의 공통 DTO·로그 비노출.
- 잘못된 key·다른 소유자·같은 key 충돌·reparse/루트 밖 경로 거부, 무관 문서·공유 모델 보존.
- 기존 파싱/청킹/임베딩·멱등 lifecycle 회귀, 격리 DB migration·타입·린트·독립 검토.
- 테스트는 기존 backend 환경, 검증된 UUID 합성 DB와 전용 임시 루트만 사용하고 실사용 파일·모델·서버는 변경하지 않음.
