# 합성 데이터 복구 모의검증

- 상태: DB·파일 후보 명세 및 후속 Elasticsearch 실제 참조 확인 완료. 정리 제안 가능, 삭제 미승인.
- 범위: 사용자 승인한 읽기 전용 모의검증. DELETE 후 ROLLBACK 실험도 하지 않았다.
- 대상 DB: loopback15432 `ai_workshop_local_clean`, `0030_technology_permissions`.
- 선행: [계정 조사](2026-09-09-synthetic-account-audit.md), [재발 방지](2026-09-09-rag-test-isolation.md).

## 제거 후보 — 아직 삭제 승인 아님

정확한5개 계정 ID와 테스트 이름·UUID 이메일·합성 password marker·활성 owner 조건을 대조했다.
민감 계정 필드 비교는 DB 내부에서만 수행했다. 초기 UUID 참조121행에 합성 프로파일3개와
모델 binding2개를 더해16테이블126행을 명세했다. 모델 정의 자체는 포함하지 않았다.

| 후보 | 수량 |
|---|---:|
| users / 권한 revision | 5 / 5 |
| 공간 / 멤버십 | 5 / 2 |
| 문서 / 파일 버전 | 8 / 11 |
| 작업 | 16 |
| projection / index build | 14 / 8 |
| ingestion job / dispatch | 14 / 12 |
| 구조 요소 / 청크 / 근거 단위 | 7 / 7 / 7 |
| 합성 프로파일 / 모델 binding | 3 / 2 |

정확한 PK(복합 PK 포함), 파일 경로·해시·검색 이름 명세는 Git 제외 로컬 산출물에 보존한다.

- `.local-data/project-agent-work/synthetic-recovery-dryrun/candidate-manifest.json`
- `.local-data/project-agent-work/synthetic-recovery-dryrun/file-verification.json`
- 같은 디렉터리의 `manifest.py`는 SELECT 전용 조사 도구이며 삭제/복구 실행 기능이 없다.

원본11경로 중6개/145bytes가 존재하고 소스 literal·DB·파일 해시가 일치한다.
부재5개 중 Alias3개는 원래 메타데이터 전용 fixture이며, Embedding2개는 DB 기록만 남았다.
파생21경로 중18개/94,141bytes가 존재하고 DB 해시와 일치하며3개는 부재다.
합계32경로 중24파일/94,286bytes(약92.1KiB)가 존재한다. 경로의 상위·대상 reparse point는 없다.
이는 논리적 파일 크기이며 DB/검색 색인 용량 또는 실제 디스크 회수량은 산정하지 않았다.

## 보존 대상

- 비대상 실사용자1명, 실제 문서·공간·구성·모델 정의·가중치 및 기존 승인/감사 기록.
- 공통 색인 프로파일 `00000000-0000-0000-0000-000000000201` 및 문서처리 프로파일
  `00000000-0000-0000-0000-000000000207`.
- DB·Docker 볼륨·백업·현재 서버 및 다른 프로젝트 자원. 캐시 정책으로 DB 자체를 삭제하지 않는다.

## 초기 조사 당시 차단 대상 및 공유 리소스

- `ai-workshop-elasticsearch-1`은 중지 상태이며9200에서 서비스가 확인되지 않았다.
  이번에는 시작하지 않았다. 실제 index 존재·alias target·문서 소유 범위는 미확인이다.
- DB build8개 중4개가 공통201 프로파일의 alias 이름을 사용한다. 이 alias는 사용자 문서도
  포함할 수 있으므로 삭제 후보로 취급하지 않는다. 나머지4개는 테스트 namespace지만 실제 존재 미확인이다.
- 명세의 `derived_alias`는 DB 이름 규칙에서 추론한 값이지 ES 조회 결과가 아니다.
  prefix 일괄삭제 또는 추론 alias 삭제는 금지한다.
- 로컬 DB는 조회 중에도 앱이 사용할 수 있다. 이 명세는 승인 시점/실행 직전 재검증을 대신하지 않는다.

## 검증 증거

- PostgreSQL default_transaction_read_only 및 REPEATABLE READ READ ONLY, statement20초/lock3초 제한.
  exact schema와 계정 조건을 확인했다. 실행 wrapper에서 libpq 우회 환경 변수가 없음을 확인했고
  도구 자체에도 같은 거절 조건을 추가했다. PGHOSTADDR 주입 시 연결 전 RuntimeError/exit1을 확인했다.
- 복합키·비UUID 타입을 포함한 실제 FK67개 검사에서 후보 밖의 연쇄 영향 행0.
- NULL-safe 외부 UUID 및 직렬화된 UUID/프로파일명/객체 키/검색 이름 참조 검사에서 후보 밖 행0.
  ES·별도 파일 저장소까지 참조가 없다는 의미는 아니다.
- 원본 이름 검증의 synthetic 번호는 테스트 소스 `enumerate(...,1)`에 맞춰1/2로 보정했다.
- 독립 검토가 후보 수·PK 중복·보호 대상·삭제 비승인 상태를 별도 확인했다.
- 초기 모의검증에서는 계정 삭제/비활성화, DB 쓰기, 서버 시작/중지, 원문/파생 파일 삭제, Docker 변경을 하지 않았다.

## 후속 Elasticsearch 실제 확인 — 2026-09-10

사용자 승인으로 기존 `ai-workshop-elasticsearch-1` 한 개만 시작했다. 컨테이너는 running/healthy이며,
단일 노드의 cluster yellow는 미할당 replica 11개 때문이고 미할당 primary는 0개였다.
새 컨테이너·이미지·볼륨 생성, 설정 변경, 계정/DB 쓰기, 색인/alias 변경 또는 삭제는 하지 않았다.

- 명세의 정확한 물리 색인 8개와 추론 alias 4개를 GET으로만 확인했다.
- 물리 색인 4개는 부재했다. 존재하는 후보 4개는 각각 검색 레코드 1개이며,
  mapping의 build/profile/projection과 후보 workspace/asset/projection/build/profile 필터가 모두 일치했다.
- 공통201 active alias는 후보 색인 4개와 비후보 색인 2개에 연결돼 있다.
  비후보 색인은 각각 검색 레코드 4개를 포함한다. 이는 업로드 원본 문서 수가 아니라 ES 검색 레코드 수다.
  공통 alias와 비후보 색인 2개는 보존한다. 나머지 private alias 3개는 부재했다.
- 부분 shard 실패를 거부하도록 조회 도구를 보완한 뒤 전체 조회를 재실행했다.
  실패 없이 완료됐으며 최초 결과와 객체 키 순서를 정규화한 비교 결과가 동일했다.
- 독립 검토도 후보/보존 경계를 확인했다. 최종 정리 제안은 DB126행·존재 파일24개·존재 물리 색인4개다.
  실제 삭제 실행기는 아직 구현하지 않았고 삭제 승인은 받지 않았다.

읽기 전용 조회 및 독립 검토 산출물은 동일한 로컬 작업 디렉터리에 보존한다.

- `inspect-elasticsearch.ps1`
- `elasticsearch-verification.json`
- `elasticsearch-final-verification.json` (shard 실패 거부 조건 적용 후 재실행 결과)
- `es-review.md`

기존 `candidate-manifest.json`은 ES 확인 전 스냅샷으로 유지한다. 그 안의 ES 미확인 표시는
위 후속 증거로 보완하며 `deletion_authorized:false`는 그대로 유효하다.

## 다음 단계

1. 확인된 DB126행·파일24개·물리색인4개의 정리 목록과 순서, 보존 검증·새 백업·writer 중단 범위를 승인받는다.
2. 실행 직전 소유권·외부 참조·파일 해시·alias 연결을 재검증하고 변경이 있으면 중단한다.
3. 실제 정리는 별도 승인 후 수행한다. 공통 alias·비후보 색인2개는 보존하며 본 명세만으로 삭제하지 않는다.
