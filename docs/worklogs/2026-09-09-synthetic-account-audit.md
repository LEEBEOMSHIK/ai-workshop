# 기존 합성 마스터 계정 조사

- 상태: 읽기 전용 조사 완료. 삭제·비활성화·테스트 실행·서버 변경 없음.
- 대상: 로컬 `ai_workshop_local_clean`, schema0030. 사용자 승인 범위는 원인/연결 데이터 조사다.
- 메인은 DB 조사, 별도 역할 에이전트는 테스트 코드 생성/정리 경로를 독립 추적했다.
- DB 트랜잭션은 REPEATABLE READ READ ONLY, 문장 제한20초로 수행했다.
  비공개 본문·실계정 식별정보·비밀번호를 보고서로 저장하지 않았다.

## 확인된 원인과 한계

Supersession2·Embedding2·Alias Parity1 계정은 테스트의 이름, UUID 결합 이메일,
합성 password marker까지 일치한다. 모두 기존 활성 owner이며 비대상 사용자는1명이다.
0030 migration 이전에도 존재했고 권한 관리 UI가 새로 만든 계정이 아니다.

- `backend/tests/integration/labs/rag/ingestion/test_supersession_reconciliation.py:64`
- `backend/tests/integration/labs/rag/ingestion/test_production_embedding_indexing.py:240`
- `backend/tests/integration/labs/rag/indexing/test_alias_parity_recovery.py:49`

이 세 테스트는 애플리케이션 `get_settings()` DB에 합성 owner를 commit한다.
기존 격리 fixture는 `test_ingestion_task.py` 내부에만 있어 형제 파일을 보호하지 않는다.
Embedding/Alias는 Elasticsearch 정리 예외가 뒤의 DB 정리를 건너뛸 수 있으며,
Supersession은 seed 후 try/finally 진입 전 실패 경로가 있다.
각 잔존 계정의 당시 실행·중단 원인은 로그로 확정하지 못했다.
과거 한 묶음41행 복구는 전체 테스트 데이터 정리가 아니었다.

## 연결 범위

UUID 참조의 반복 탐색은 다음121행을 찾았다. 이는 삭제 승인 목록이 아닌 조사 집합이다.

| 범주 | 행 수 |
|---|---:|
| users / user_authorization_states | 5 / 5 |
| workspaces / workspace_memberships | 5 / 2 |
| documents / asset_versions | 8 / 11 |
| jobs | 16 |
| rag_document_projections / rag_index_builds | 14 / 8 |
| rag_ingestion_jobs / rag_ingestion_dispatches | 14 / 12 |
| 구조 요소 / 검색 청크 / 근거 단위 | 7 / 7 / 7 |

작업16개는 succeeded8/failed8이다. 조사 집합 밖의 직렬화 UUID 참조는0으로 관찰됐다.
이 검사는 현재 UUID/직렬화 참조 범위이며, 이름으로 연결된 ES alias 등까지 증명하지 않는다.

연결 파일 버전11개 중 실제 파일6개/145bytes는 DB 크기·SHA-256과 일치했고5개는 없었다.
Alias fixture는 파일 없이 메타데이터만 생성하므로 부재 전부를 파일 유실로 단정하지 않는다.
소스 literal과의 원본별 삼자 대조, 경로 중간 reparse 점검은 실제 정리 전 필요하다.

## 보존·차단 경계

- 비대상 실사용자1명과 그 문서·공간·설정은 보존한다.
- 참조된 프로파일5개 중 공통 색인/문서처리2개는 실제 구성에서도 사용되므로 반드시 보존한다.
  후속 모의검증에서 공통 색인을 BM25라고 단정한 초기 표기를 정정했다. 정확한 ID는
  `00000000-0000-0000-0000-000000000201`과 `00000000-0000-0000-0000-000000000207`이다.
- 비기본 synthetic 프로파일3개는 별도 정리 후보다. UUID 조사 집합 밖 참조는
  profile-model binding2개뿐이지만 프로파일 이름·JSON 참조·ES 이름 연결을 추가 확인해야 한다.
- 모델 레지스트리/가중치·사용 중 서비스·DB·Docker 볼륨·복구 백업은 삭제하지 않는다.
- 현재 정리는 파일 캐시 삭제가 아니라 승인된 단일 데이터 복구로 설계해야 한다.
  0030의 revision FK와 append-only 감사 정책을 우회하거나 일반 계정 삭제 API를 만들지 않는다.
- 조사 이후 활동으로 상태가 바뀔 수 있다. 기존 백업만 믿고 삭제하지 않고 실행 직전
  writer 중지·새 백업·정확한 PK/참조/해시 목록·나머지 데이터 보존 검증을 다시 수행해야 한다.

## 권장 다음 단계

1. 재발 방지: 세 테스트를 공통 격리 DB/파일/ES namespace로 전환하고 실사용 DB 연결을
   연결 전에 거절한다. seed 직후부터 예외 보호하고 자원별 cleanup 실패를 독립 보고한다.
2. 별도 복구 dry-run: 정확한5개 계정과 관련 합성 데이터만 명세하고 공통 프로파일/모델은 제외한다.
   ES 연결 증거와 원본 삼자 검증을 포함해 최종 삭제 목록을 승인받는다.
3. 승인 후 단일 복구 트랜잭션과 전후 비대상 데이터 검증을 수행한다. 이번에는 실행하지 않았다.

이 조사는 전체 integration 테스트의 안전성을 보증하지 않는다.
