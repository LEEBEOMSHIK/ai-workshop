# RAG SQL 출처 연결 구현 기록

- 상태: 승인 범위 구현·메인 통합 및 개별/최종 전체 독립 검토 완료(지적 0건).
- 설계: [승인 상세안](../superpowers/specs/2026-09-14-rag-sql-provenance-design.md)
- 계획: [구현 계획](../superpowers/plans/2026-09-14-rag-sql-provenance.md)

## 역할과 경계

메인은 시스템/RAG 경계·테스트 설계·통합·문서, 별도 Python/DB 담당은 쓰기 연결과 목록 어댑터를 순차 구현한다.
독립 코드 검토 및 데이터 보존/통합 검증 책임은 구현과 분리한다.
UI·모델·Docker는 변경하지 않는다. main의 기존 UI 및 2C 변경을 보존한다.
실사용 migration·backfill·삭제·서버 재시작·commit/push는 하지 않는다.

## 변경 전 검증

- 기존 backend 환경: Assets 단위 및 DB 안전성 **372 passed**, 12.31초.
- 기존 Starlette/httpx 사용 중단 예고 경고1건. 이번 변경과 무관한 의존성 변경은 하지 않는다.
- 기존 document repository 테스트는 앱 DB 기본 주소를 사용하므로 직접 실행하지 않는다. 전용 UUID 합성 DB를 주입한 검증만 허용한다.
- 문서/청킹 단위20건 통과. 기존 document repository7건을 전용 UUID DB wrapper로 실행해 통과했고 해당 DB 정리를 확인했다.
- 기존 ingestion 단위53건 통과(4.84초).
- 첫 wrapper 실행은 부모 프로세스의 Windows Proactor event loop로 migration 접속 전에 실패했다. 기존 `configure_windows_selector_policy()`를 wrapper에 적용해 재검증했다. 제품 코드 변경은 없으며 실패 시에도 전용 DB 정리가 수행됐다.
- Task1 첫 RED: 신규 projection의 content_revision 부재로 기대한 실패1건을 확인한 뒤 경계 테스트와 구현을 진행했다.

## 검증 기준

| 경계 | 관찰할 결과 |
|---|---|
| 신규/legacy | 새 자료1·정확한 관계, 기존NULL 자동 승격 없음 |
| 쓰기/상태 | 변경마다 단조 증가, 무변경 중복 전달 유지 |
| 동시성/rollback | 잠금 후 최신값, lost update 없음, 내용·revision·관계 함께 rollback |
| 관계 충돌 | 누락/초과/다른 source/과거revision 자동 복구 없이 실패 |
| 목록 | 모든버전/상태, 일관된 읽기 snapshot, 소유자와 하위 관계 검증 |
| 데이터 최소화 | 본문·경로·해시가 목록/오류로 나가지 않음 |
| migration | 기존자료 보존, 양수제약, 안전downgrade |

이 참여자의 완료는 전체 RAG 또는 파일함 영구 삭제 완료가 아니다. 외부 산출물·색인·기타 모듈 연결과 writer 차단은 후속 작업이다.

## 구현 및 검증 결과

- nullable content_revision·0040 migration, 신규 등록과 현재 관계 교체, RAG 저장/상태/복구 경로를 구현했다.
- 구현자 집중12건 통과 후 메인12건 재실행 통과(22.37초), 기존 문서 저장소7건(2.67초)과 공통 출처/migration14건(36초)도 통과했다.
- 독립 리뷰에서 Important2건 확인: 캐시된 출처 관계 미갱신에 의한 정상 요청 거부, evidence 입력 검증 전 삭제 실행.
- 두 결함의 RED2건 실패를 재현하고, 관계 잠금 조회의 populate_existing와 삭제 전 입력 검증으로 수정했다.
- 보완 후 메인 관련 검사 **86 passed**(24.35초), 제품/migration 타입6파일·린트8파일 통과.
- 재개 후 메인 회귀: Assets·문서·청킹·ingestion·출처/휴지통 migration **446 passed**(73.99초), 기존 Starlette 경고1건.
- DB 대상 안전성26건(2.25초), 전용 UUID DB의 기존 문서 저장소7건(4.14초) 통과. 생성한 DB는 fixture 종료 시 제거됐고 제품/migration 타입6파일도 통과했다.
- Task2: 읽기 전용 목록 수집과 집중18건을 구현했다. 동시 commit 스냅샷, 모든 버전·상태, 출처/근거 소속 불일치, 안전 오류와 본문 비선택을 확인했다.
- 메인 최종 통합: `tests/unit/platform/assets`, `tests/unit/test_publishing_database_safety.py`, RAG documents/chunking/ingestion 단위, RAG provenance writes/migration/inventory 및 Platform provenance persistence/trash migration을 실행해 **490 passed**(74.96초). 기존 Starlette 경고1건 외 실패 없음.
- 최종 타입 검사 제품/migration7파일, Ruff 변경 Python10파일 통과. 검증·리뷰 패키지의 소스10파일이 동일함을 확인했다.

## 이전 중단과 재개

기존 구현자 재호출과 새 구현자 호출이 모두 `agent thread limit reached`로 거부됐다.
`subagent-driven-development` 역할 분리 절차를 계속 실행할 수 없어 메인이 이미 독립 검토된 두 결함만 TDD로 보완했다.
이 대체 처리의 비용은 독립 재검토가 여전히 필요하다는 점이다. 자기 검증을 독립 승인으로 바꾸지 않는다.
재개 시 검증 에이전트 호출에 성공했고 두 수정 모두 해결·새 지적 없음으로 독립 승인됐다.
Task2 읽기 목록 어댑터를 별도 구현자가 완료했고 독립 검토는 명세·품질 승인, 지적0건이다. 메인 통합과 최종 전체 리뷰도 통과했다.
임시 인계 자료는 `.local-data/project-agent-work/rag-sql-provenance/`의 task-1-fix1-report.md와 task-1-fix1.diff다.
승인된 SQL 출처·목록 범위는 완료했지만 전체 영구 삭제 기능 완료를 뜻하지 않는다. 실사용 DB·서버·사용자 자료·commit/push·임시 기록 삭제는 변경하지 않았다.

## 최종 인계

- Task1과 Task2 구현 책임·독립 검토를 분리했고 최종 전체 리뷰에서 Critical/Important/Minor 모두0건이다.
- 이전 호출 제한 때문에 메인이 두 결함을 보완한 예외 판단은 독립 재검토를 추가로 받아야 하는 비용이 있었으며, 이번 재개에서 해당 검토까지 통과했다.
- 다음은 이 SQL 묶음 밖의 색인·파일·작업 메타데이터 및 기타 모듈의 출처/정리 연결이다. writer 차단·전체 참여자 조립·실제 삭제 UI/API는 후속이다.
- 생성한 UUID 합성 테스트 DB는 fixture에서 정리했다. 회귀 테스트 소스는 제품 검증 자산으로 유지한다. 임시 인계 diff/보고서는 아직 미커밋 작업의 유일한 검토 근거이므로 보존하고, 정본/저장소 인계 후 정책에 맞춰 정리한다.
