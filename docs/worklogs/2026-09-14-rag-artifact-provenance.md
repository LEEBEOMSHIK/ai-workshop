# RAG 객체 산출물 추적 구현 기록

- 상태: 승인된 Task1–4 구현·전체 보완 독립 검토·최종 메인 검증 완료. 사용자 요청으로 main 커밋·푸시 인계, 실사용 배포 제외.
- 설계: [승인 상세안](../superpowers/specs/2026-09-14-rag-artifact-provenance-design.md)
- 계획: [4단계 구현](../superpowers/plans/2026-09-14-rag-artifact-provenance.md)
- 메인: 시스템/RAG 경계·테스트 설계·통합·문서. 백엔드/DB 구현과 독립 검토·프라이버시 검증은 분리한다.
- 기존 main의 SQL 출처·2C·UI 변경을 보존한다. 실사용 migration/backfill·저장소 표식·서버·파일 삭제·commit/push는 변경하지 않는다.

## 변경 전 검증

기존 backend 환경에서 Assets·DB 대상 안전·RAG 문서/청킹/ingestion 단위 **445 passed**(12.64초).
기존 Starlette/httpx 경고1건은 변경 전부터 재현되며 이번에 의존성을 교체하지 않는다.
DB 검증은 대상 확인을 포함하는 isolated_publishing_database의 정확한 UUID DB만 사용한다. 기존 ingestion integration의 자동 fixture와 실제 모델/ES를 무조건 실행하지 않는다.
상위 ingestion conftest의 autouse seed가 get_settings()로 DB를 여는 것을 사전 확인했다. 새 테스트 모듈에서 해당 fixture를 격리 의존성으로 재정의하도록 필수 조건을 추가했다.

## 실행 경계

Task1은 새 영속 모델·0041 migration·등록/작성 시도 repository를 구현했다. 메인 재검증에서
보강된 집중 테스트14건(26.22초)이 통과했지만, 독립 리뷰의 별도 동시 실행 재현에서
savepoint 롤백과 다른 작성자의 개입 시 revision 증가를 놓치는 문제가 확인됐다. 이 검토는
전용 UUID DB만 사용하고 정리했다. 두 번째 수정에서 증가를 시작한 transaction과 롤백 범위를
추적해 보완했으며 독립 재검토의 spec/quality가 모두 통과했다. 메인 fresh 집중 테스트는
**18 passed**(25.29초)다. 일반/중첩 savepoint 뒤 다른 작성자의 변경과 기존 성공 변경 보존을 검증했다.
신규 에이전트 생성 한도로 기존 에이전트를 수정 역할에 재배정하되 독립 리뷰 역할은 분리한다.

Task2의 정확한 임시 key·binding 검사·불변 게시·자기 임시 파일 정리를 구현했고 독립 검토가
통과했다. 메인 검증은 **86 passed, 1 skipped**(3.09초), 타입2파일·린트4파일 통과다.
skip은 Windows의 실제 symlink 생성 권한 부재이며, 경로 교체·파일 identity 보존·전용
자식 프로세스 종료 후 등록된 임시 파일 잔존은 테스트했다. 실사용 marker는 만들지 않았다.

Task3은 공식 신규 등록과 파싱·청킹·임베딩의 추적 게시/동일 transaction 최종화를 연결했다.
독립 리뷰에서 게시 직후 FAILED 전환 경합을 찾아 최신 잠금 상태 재확인으로 보완했고 재검토가
통과했다. 담당 최종 통합13건+단위73건=86건이 통과했다. 외부 encoder/index 포트만 합성 구현이며
DB·게시 어댑터·단계 저장은 실제 경로다. 기존 실사용 DB fixture 통합 모듈은 실행하지 않고
신규 격리 DB에서 legacy 재사용·목록 조회 보존을 검증했다. 전체 legacy 통합 통과를 주장하지 않는다.
메인의 보완 후 실제 연결 집중 재검증은 **13 passed**(38.77초)다.

새 추적 ingestion은 설정된 논리 store/binding과 이미 초기화된 루트 표식이 필요하다. 이 작업은 실사용 저장소를 초기화하지 않는다.
미추적 legacy 경로를 보존하지만 추적된 경로의 실패를 legacy로 조용히 우회하지 않는다.
open writer를 timeout으로 인계하거나 지우는 기능, 실제 purge/receipt/UI는 범위 밖이다.

## 최종 통합 검증 진행

Task1–3과 기존 Assets·RAG 단위·SQL 출처 통합을 함께 실행해 **593 passed, 1 skipped**
(107.33초)를 확인했다. skip은 위 Windows symlink 권한 제약이며 기존 Starlette 경고1건이 있다.
Task4 메인 집중 재검증은 **8 passed**(9.79초), 현재 변경 Python 23파일 Ruff와 업무 코드
14파일 mypy가 통과했다. Task4 독립 리뷰와 전체 범위 최종 리뷰는 별도 완료 조건이다.

Task4 독립 리뷰의 등록 불완전 상태 표시·설정 문구를 수정하고 재검토를 통과했다.
필수 슬롯 누락 또는 등록된 시도 key 불일치는 목록 소진(exhausted)으로 표시하지 않는다.
설정 안내는 기존 공유 `AI_WORKSHOP_OBJECT_STORE_ROOT`와 논리 store ID/별도 binding UUID를
정확히 구별한다. 보완 후 메인 집중 검증은 **8 passed**(12.31초), 해당2파일 Ruff 통과다.
변경하지 않은 Task1–3 관련593건과 보완 후 Task4 8건을 합해 **601 passed, 1 skipped**다.
전체 애플리케이션·실제 모델·실사용 데이터 검증 결과가 아니라 이번 관련 범위의 분리 실행 합계다.
Task4 보완 후 메인의 `mypy --no-incremental` 1파일 재검증도 통과했다.

최종 교차경계 리뷰에서 중복 delivery의 busy 오류가 실제 worker를 통해 공유 job을 FAILED로
바꾸는 문제와, 원본 SQLAlchemy 예외가 retry/terminal traceback에 key/hash를 포함할 수 있는
경로를 발견했다. 실사용 누출 관찰이 아니라 코드 경로 확인이며 두 건을 한 수정 묶음으로 보완했다.
위601건은 이 최종 보완 전 검증 기록이며 수정 후 관련 재검증을 별도 기록한다.

최종 보완 후 메인 결합 실행은 **632 passed, 1 skipped**(153.72초), mypy14·Ruff24 통과다.
실제 Celery handler의 중복 delivery, SQL 예약·최종화·commit rollback과 안전한 재시도 예외를
보강했다. 독립 재검토에서 원래 두 지적은 해소됐으나, 업로드→RAG 호출자가 새 안전 오류의
일시적 장애 분류를 놓치는 회귀1건을 발견했다. worker와 해당 단위 테스트 두 파일만 추가 보완했다.
이 보완의 RED2건→worker/OCR29건 통과, 타입1·린트2 통과를 확인했고 독립 재검토의 새 지적은 없다.
중복 요청은 소유자의 작업을 실패시키지 않으며, 두 task 진입점 모두 안전한 오류의 재시도 분류와
원본 cause/context 비노출을 보존한다. 기록된 모든 구현 리뷰 지적이 해소됐다.

재현 명령은 `backend`에서 기존 `.venv`로 실행한다. 아래 첫 명령은593건, 둘째는8건에 대응한다.

```powershell
.venv/Scripts/python.exe -B -m pytest tests/unit/platform/assets tests/unit/test_publishing_database_safety.py tests/unit/labs/rag/ingestion tests/unit/labs/rag/documents tests/unit/labs/rag/chunking tests/unit/infrastructure/object_store/test_tracked.py tests/unit/test_config.py tests/integration/labs/rag/ingestion/test_artifact_repository.py tests/integration/labs/rag/ingestion/test_artifact_migration.py tests/integration/labs/rag/ingestion/test_artifact_lifecycle.py tests/integration/labs/rag/documents/test_provenance_writes.py tests/integration/labs/rag/documents/test_provenance_migration.py tests/integration/labs/rag/documents/test_purge_inventory.py -q --tb=short -p no:cacheprovider
.venv/Scripts/python.exe -B -m pytest tests/integration/labs/rag/ingestion/test_artifact_inventory.py -q --tb=short -p no:cacheprovider
```

## 구현된 연결

1. `artifact_contracts/models/repository`와 migration0041: 세 산출물 슬롯 및 작성 시도 등록,
   출처 관계와 revision, 중복·롤백·동시 실행 제약을 저장한다.
2. `object_store/tracked.py`와 설정: 정확한 저장소 표식·key·파일 identity를 검증하고 기존 파일을
   덮어쓰지 않는다. 자신이 만든 임시 파일만 종료·부재를 확인하며 정리한다.
3. `artifact_service.py` 및 공식 ingestion·API/worker 조립: 파일 쓰기 전 등록을 commit하고,
   게시 결과와 단계 상태를 같은 lifecycle transaction에서 확정한다.
4. `artifact_inventory.py`: 두 읽기 전용 DB 관찰 사이에서 등록된 실제 파일을 대조하고,
   누락·손상·미확인 writer·관찰 중 변경을 빈 성공으로 바꾸지 않는다.

## 최종 검증

최종 동결 코드의 메인 재실행: **634 passed, 1 skipped, 기존 경고1건**(136.62초).
타입은 전체 관련14파일 통과 후 마지막 수정 worker1파일을 다시 통과했고, 최종 Ruff24파일 통과다.
Windows 실제 symlink 생성 권한만 skip이며, 경로 교체·프로세스 종료와 새 중복/오류/재시도 사례는 검증했다.
개별·전체·보완 독립 리뷰 지적은 모두 해소됐다. 작업 대시보드 최근 완료는5개로 유지했다.

최종 재현 명령(`backend`, 기존 환경, 안전한 격리 DB 대상 검사 포함):

```powershell
.venv/Scripts/python.exe -B -m pytest tests/unit/platform/assets tests/unit/test_publishing_database_safety.py tests/unit/labs/rag/ingestion tests/unit/labs/rag/documents tests/unit/labs/rag/chunking tests/unit/infrastructure/object_store/test_tracked.py tests/unit/test_config.py tests/integration/labs/rag/ingestion/test_artifact_repository.py tests/integration/labs/rag/ingestion/test_artifact_migration.py tests/integration/labs/rag/ingestion/test_artifact_lifecycle.py tests/integration/labs/rag/ingestion/test_artifact_inventory.py tests/integration/labs/rag/documents/test_provenance_writes.py tests/integration/labs/rag/documents/test_provenance_migration.py tests/integration/labs/rag/documents/test_purge_inventory.py tests/unit/test_worker.py tests/unit/test_worker_ocr_errors.py -q --tb=short -p no:cacheprovider
```

## 커밋 인계 검증(2026-09-14)

사용자 커밋·푸시 요청에 따라 미커밋 의존 공통 출처·SQL 추적 기반을 함께 포함한다.
기존 최종 명령에 공통 출처/목록/증명 영속 및 휴지통 migration 통합4모듈을 추가해
**674 passed, 1 skipped, 기존 경고1건**(117.50초)을 확인했다. 대상 Python51파일 Ruff와
staged whitespace·정확한64파일 범위·비밀키 패턴 검사도 통과했다.
프론트/UI 관련 별도 변경·참고 이미지·캐시·임시 기록은 제외하며 실사용 배포는 하지 않는다.

## 다음 경계

RAG index build/Elasticsearch, 원본 파일, 파서·OCR·뷰어의 문서 전용 임시물, 작업 메타데이터는
이 참여자에 포함하지 않았다. 각 소유자의 추적·정리 계약을 연결한 뒤 전체 참여자 수집,
writer 차단, 잔존 재검증과 실제 삭제 API/UI를 통합해야 사용자 영구 삭제 테스트가 가능하다.
기존 미추적 자료의 별도 검증·활성화 절차가 필요하므로 이번 코드만으로 삭제를 활성화하지 않는다.

## 작업 방식의 예외와 검증 한계

- Task1 두 번째 수정은 신규/기존 담당 호출 한도로 사용 가능한 이전 역할 에이전트에 재배정했다.
- 같은 도구 한도로 남은 구현도 사용 가능한 기존 에이전트에 순차 재배정했다. 이전 문맥 혼입으로
  재작업이 생길 위험이 있어 파일 범위를 제한하고 구현과 독립 리뷰 역할은 계속 분리했다.
- 실제 앱 DB나 외부 런타임을 여는 기존 통합 모듈 대신 전용 UUID DB의 legacy 재사용 사례와
  오프라인 단위 검증을 사용했다. 실행하지 않은 기존 통합 시나리오의 통과를 보장하지 않는다.
- 새로 발견한 worker 호출자 회귀를 남기지 않기 위해 스킬의 최종 수정1회 제한을 넘는 두 파일
  한정 보완을 허용했다. 추가 검토·테스트 시간과 오류 분류 영향 범위 증가가 비용이며,
  새 기능·실사용 변경 없이 독립 재검토를 유지한다.
