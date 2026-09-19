# RAG 색인 출처·실물 목록 구현과 검증

- 작업일: 2026-09-20
- 산출물: [상세 설계](../superpowers/specs/2026-09-20-rag-index-provenance-design.md).
- 범위: build·Elasticsearch 생성 전 출처 등록, prepare 시도, 실물 목록과 후속 삭제의 연결 조건.
- 상태: 상세 설계 후 사용자가 바로 구현을 지시했다. 구현·통합·독립 최종 검증 완료.
- 구현 계획: [Task 1–4](../superpowers/plans/2026-09-20-rag-index-provenance.md).

## 의도와 역할

사용자가 다음 작업 진행을 지시한 대상은 작업 보드의 RAG index build·Elasticsearch 추적·정리 연결이다.
메인은 요구사항·시스템 아키텍처·RAG 책임자·색인 담당·문서 관리자 책임으로 상세안을 작성했다.
별도 DBA는 build FK·변경 경로·잠금·revision을 읽기 전용 조사하고 상세안을 검토했다.
독립 프라이버시 검증자는 공유 색인·alias, 불확실한 ES 요청 종료, 기존 미추적 자료와 비노출을 검토했다.
UI·모델·배포 변경은 없어 해당 역할은 제외했다. 구현 승인 후 메인이 서비스 연결·worker·통합을 맡고,
별도 DBA·ES·inventory 담당에게 겹치지 않는 파일 범위를 배정했다. 코드·프라이버시·최종 검증은
구현하지 않은 독립 담당이 수행했다. 테스트 서비스가 꺼져 있어 메인에 전용 테스트 인프라 역할을 추가 고지했다.

역할 selector는 기본 Python의 PyYAML 부재로 처음 실패했다. 패키지를 설치하지 않고 기존 backend 가상환경으로 실행해 필수 여섯 역할을 확인했다.
색인 전문 역할은 실제 build/alias 범위에 따라 추가했다. 독립 검증자는 문서나 제품 코드를 작성하지 않았다.

## 구현 전 코드에서 확인한 근거

| 위치 | 확인한 사실 |
|---|---|
| `backend/src/ai_workshop/labs/rag/ingestion/stages.py`, `_ensure_build`, `index` | build UUID를 먼저 commit하지만 concrete name은 ES prepare 뒤 저장 |
| `backend/src/ai_workshop/labs/rag/documents/models.py`, `RagIndexBuildRecord` | projection당 build 하나, 이름 UNIQUE, projection 삭제 CASCADE |
| `backend/src/ai_workshop/labs/rag/ingestion/models.py` | ingestion의 build 참조 SET NULL |
| `backend/src/ai_workshop/labs/rag/indexing/elasticsearch.py`, `create` | 같은 이름이 있으면 descriptor/소유권 검사 없이 반환 |
| `backend/src/ai_workshop/labs/rag/indexing/service.py`, `prepare_projection` | build별 이름, chunk ID upsert, projection count 검증 |
| `backend/src/ai_workshop/labs/rag/ingestion/stages.py`, activation | source/profile/build 잠금 중 alias 호출, 여러 build의 활성 플래그 갱신 |
| `backend/src/ai_workshop/labs/rag/indexing/recovery.py` | READY/current 집합 기반 alias 복구와 build 활성 플래그 일괄 갱신 |
| `backend/src/ai_workshop/labs/rag/retrieval/elasticsearch.py`, `describe_frozen_index` | concrete index UUID·metadata 검증, `_meta.rag` key 집합 정확 비교 |

실제 DB/ES에 고아 색인이나 손상 자료가 존재한다고 확인한 것은 아니다. 실패 가능성과 필요한 보완을 코드에서 조사했다.

## 독립 검토와 반영

DBA 지적은 projection의 source/profile 및 Job workspace까지 복합 FK 명시, build 생성 전에 descriptor 확보,
activation의 전체 대상 build 정렬 잠금이었다. 상세안 §4·5·7에 반영했다.
프라이버시 지적은 SDK/helper의 숨은 retry, count만 같은 다른 chunk 집합, 비노출 테스트 구체화였다.
자동 mutation 재전송 금지, 정확한 chunk ID 집합 대조, 합성 민감값을 포함한 오류 정제 검증을 §5·6·8·12에 추가했다.
메인 검토에서 기존 frozen inspector와 새 metadata의 충돌을 발견해 `_meta.rag`를 유지하고 sibling 표식으로 분리했다.
이 결정은 소유권 추적이며 본문·벡터 전체의 byte equality나 관리자 조작 방지 보장이 아니다.
보완 부분의 DBA·프라이버시 재검토에서 현재 상세 설계 범위의 잔여 차단 사항이 없음을 확인했다. 실제 실행 검증을 대신하지 않는다.

## 후속 경계

상세안의 권장 범위는 prepare 추적과 inventory다. alias는 공유 자원이므로 별도의 영속 실행·서버 종료 확인과 전체 writer 차단이 후속 필수 게이트다.
frozen 평가의 직접 concrete index 참조 등 다른 소유자의 소비·복제도 별도 계약으로 해소해야 한다.
원본·파서/OCR/뷰어 임시물·작업 메타데이터, 실제 purge API/UI와 기존 자료 활성화는 여전히 남는다.
이 문서만으로 삭제 준비 완료나 사용자 영구 삭제 테스트 가능을 주장하지 않는다.

## 설계 단계 검증

문서 2개의 상대 링크 5개·중복 제목·미완성 표식·잘못된 문자·공백, 최근 완료 5개·AGENTS 200줄 이하 검사 통과.
첫 검사에서는 PowerShell의 Python stdin 전달 인코딩 때문에 한글 섹션 검색이 실패했다. 검사 문자열을 Unicode escape로 바꿔 재실행해 통과했고 원문 인코딩은 변경하지 않았다.
`git diff --check -- WORKBOARD.md` 통과. Git 변경 범위는 작업 보드와 새 상세안·기록 2개이며 기존 별도 변경은 보존했다.
설계 단계에서는 제품 코드 변경이 없어 애플리케이션 테스트·타입 검사·린트를 실행하지 않았다.
실사용 DB/ES 연결·migration/backfill·서버 재시작·삭제·패키지 설치·commit/push는 구현 단계에서도 수행하지 않았다.
시작 시 존재하던 프론트/UI·ADR-0023·이동 설계와 미추적 참고 자료는 이번 범위에서 보존한다.

## 구현 결과

- `0042_rag_index_resources`: build별 원장과 prepare 시도, 정확한 source/profile/job 복합 FK,
  삭제 RESTRICT, open 시도 고유성, 불변 필드 보호 및 기록이 남은 downgrade 거부.
- repository는 시도 예약·UUID 관측·종료·build 변경을 현재 출처 관계와 revision으로 원자적으로 연결한다.
  입력 fingerprint와 정렬한 chunk ID 집합 digest를 첫 시도에 고정한다.
- 추적 ES 어댑터는 cluster·concrete target·UUID·mapping·소유 레코드·정확한 chunk ID를 검사한다.
  `_meta.rag`는 유지하고 `_meta.rag_index_resource`를 추가해 frozen inspector와 호환한다.
- ingestion은 사전 등록 commit → 시도 commit → ES UUID commit → bulk → prepared/시도 종료 순서다.
  서버 종료가 확인된 부분 실패는 재시도 가능하며 timeout/취소/DB 최종화 실패는 open을 보존한다.
  busy 작업은 다른 worker가 실패 처리하지 않고, 불확실한 요청을 새 writer가 자동 인계하지 않는다.
- activation/parity는 추가·유지·제거하는 tracked build를 검증하고 실제 변경된 모든 revision을 갱신한다.
  READY 재호출도 실제 alias membership을 확인한다. legacy build는 자동 등록하지 않는다.
- inventory는 전체 상태·버전의 DB → ES → 새 DB 관찰을 대조하며 ID/revision/flags만 반환한다.
  실제 purge 실행기나 공유 alias writer의 영속 종료 증명은 추가하지 않았다.

독립 리뷰에서 발견한 5건을 수정했다: 정상 replica 미할당 refresh 응답, open 시도의 busy 우선순위,
종료가 확정된 실패의 재시도, 제거 대상 active build의 binding 검사, READY shortcut의 alias 확인.
확정 실패 종료 테스트는 RED에서 open 상태가 남는 것을 확인한 뒤 수정하여 GREEN으로 전환했다.
최종 독립 재검토에서 5건의 해소와 추가 차단 결함 없음을 확인했다.

## 구현 검증과 환경

기존 backend 가상환경만 사용했다. `.git/refs` 쓰기 제한으로 worktree 생성이 실패하여 스킬의
sandbox fallback에 따라 현재 checkout에서 작업했다. 별도 branch/worktree·staging은 없다.

전용 PostgreSQL17/Elasticsearch9.5.2 컨테이너를 기존 이미지로 시작했다. loopback 임의 포트,
tmpfs 데이터, `--rm`, `ai-workshop.task=rag-index-provenance` 라벨을 사용하며 host mount와
영속 volume은 없다. UUID 전용 DB 및 정확한 테스트 index만 생성·제거했다. 기존 `tpmp-db-local`과
AI Workshop 실사용 자료는 대상에 포함하지 않았다. 외부 모델 호출은 없다.

backend에서 `python -B -m pytest … -q --tb=short -p no:cacheprovider --basetemp=<작업별 경로>` 실행:

| 검증 | 결과 |
|---|---|
| unit indexing·ingestion·retrieval ES·config·worker 관련 묶음 | 278 passed |
| integration resource repository/migration/inventory·tracking service·activation·live ES | 33 passed |
| 기존 `test_alias_parity_recovery.py` | 4 passed |
| 독립 담당의 indexing/worker·신규 통합 전체 재검증 | 150 passed, 27.35초, exit 0 (위 검사와 중복) |
| mypy config·worker·indexing·stages | 15 source files, 오류 없음 |
| Ruff 같은 제품 코드·관련 테스트·migration/env | 통과 |

주 검증 합계는 중복 없는 315건이다. 실제 ES 검사에는 정상 replica 미할당 및 ProductionIndexingStage
→ ProductionReadinessVerifier → RagIndexInventory 경로가 포함된다. 실제 모델 추론·브라우저 E2E나
전체 backend 테스트 통과를 의미하지 않는다.

첫 legacy parity 실행은 필수 합성 SECRET_KEY 누락으로 fixture 시작 전에 실패했다. 합성 키를
프로세스 환경에 추가한 재실행에서 4건 통과했다. Windows 공용 pytest Temp 권한 문제는 프로젝트
내 작업별 basetemp로 우회했다. 중간 전체 unit 실행은 동시 수정 중 중단하여 완료 증거에서 제외했다.
작업별 pytest 디렉터리와 기존 캐시·이미지는 일괄 삭제하지 않는다.

설정 예시와 활성화 전제는 [로컬 실행 정본](../runbooks/local-development.md)에 추가했다.
새 build에는 `AI_WORKSHOP_RAG_INDEX_STORE_ID`와 실제 `AI_WORKSHOP_RAG_INDEX_CLUSTER_UUID`가
모두 필요하다. 실사용 migration·writer drain·동일 버전 배포·legacy 처리는 별도 적용 작업이다.

검증 종료 후 두 컨테이너의 정확한 ID·작업 라벨·tmpfs·영속 mount 부재·AutoRemove를 확인해
이번 작업의 임시 서비스만 종료했다. 자동 제거와 기존 `tpmp-db-local`의 healthy 상태, 기존 중지
서비스 보존을 재확인했다. 이미지·volume·기존 캐시를 삭제하지 않았다.

추가 format 검사에서는 기존 코드가 포함된 8파일의 형식 차이가 발견됐다. 해당 검사는 필수 Ruff
lint 통과와 구별하며 무관한 기존 형식을 일괄 변경하지 않았다. 신규 파일은 별도로 형식을 확인했다.
