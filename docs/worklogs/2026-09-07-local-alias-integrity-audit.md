# 로컬 색인 정합성 오류: 합성 테스트 잔여 데이터 조사

## 결론

`alias_parity_invalid_build`는 사용자 원본 손상이 아니라 기존 통합 테스트 fixture 잔여 기록이다.
`test_production_embedding_indexing.py`의 `seed_two_jobs()`에 있는 두 합성 byte literal의
SHA-256이 DB와 실제 원본 파일의 SHA-256에 각각 일치한다. 본문은 이 기록에 복사하지 않는다.
fixture 계정·공간·프로파일 식별성도 일치하며 문제 프로파일은 비기본이고 저장 구성 참조가 0개다.

## 정확한 조사 범위

- fixture owner: `78f353d0-c2e6-4f78-be9e-d16f9139ee47`
- fixture workspace: `565cf8ab-ed10-4b05-8cad-ed4d65eaa08a`
- fixture indexing profile: `d465a812-f295-4217-832e-fb73b155d8a8`
- 잘못된 READY build: `23bbf88a-bf41-49b7-ade6-cae22b1f3b27`
- documents: `c498390d-bb58-4e26-af21-41d61ab3ce39`, `f966d3e9-580f-42f3-9a2a-147139f994c3`
- asset versions: `bd027ed1-ccd1-4ea3-9eda-fdc429f0dfd6`, `c37b37f3-d4d0-40f4-928b-7606ed4b319d`
- 해당 공간의 문서 2건·버전 2건, projection/build/job/dispatch 각 4건,
  구조 요소·청크·근거 각 4건, 멤버십 1건, fixture 프로파일·binding 각 1건.
- 네 처리 묶음 중 두 건은 공통 BM25 기준선 구독이 만든 것이다. 공통 프로파일 201,
  문서 처리 프로파일 207과 E5 모델 101은 테스트 전용이 아니므로 보존해야 한다.
- 합계 41행이다. public schema UUID 직접 참조 검사에서 이 묶음 밖 참조는 0개였다.
  fixture owner의 공간은 정확히 1개이며 saved configuration/subscription·evaluation·
  generation audit·deployment·정책·folder 외부 참조가 없다. 삭제 직전 다시 확인해야 한다.
- 원본 2개·파생 객체 참조 12개, 기존 ES 색인 3개는 이번 DB 레코드 정리 승인 범위에서
  제외한다. 공유 BM25 alias 자체는 삭제하지 않으며 DB 복구 후 정상 reconciler로 재조정한다.

## 발생 상태와 추정 경로

READY build는 사라진 `rag-task7` 테스트 네임스페이스의 ES 색인을 가리킨다.
현재 환경의 색인 접두사와 legacy207 namespace 규칙 모두 일치하지 않는다.
같은 fixture의 다른 원본은 prepared build와 `index_build_incomplete` 실패 작업을 가진다.
통합 테스트는 개발 환경 설정을 그대로 읽을 수 있고 ES를 먼저 삭제한 뒤 DB를 정리한다.
이 구조는 관찰 상태와 부합하지만 당시 정리 실패·중단의 정확한 원인은 확정하지 않는다.

기존 ensure는 같은 작업을 재사용하고 READY/FAILED는 terminal이므로 재실행만으로는
복구되지 않는다. 임의 READY 변경이나 잘못된 색인명에 맞춘 alias 연결은 하지 않는다.

## 복구 결과 (2026-09-07)

- 사용자가 DB 정합성 복구 작업의 진행을 승인했다. 캐시 삭제와 구분된 데이터 복구로 실행했다.
- 독립 리뷰 후 정확한 합성 계정 password_hash, 두 원본 SHA-256, 41행과 외부 UUID·문자열·JSON
  참조 0을 다시 검증했다. 비공개 본문은 출력하지 않았다.
- 전체 public 테이블 쓰기 잠금 안에서 workspace → fixture profile → fixture owner 순서로
  삭제했다. 삭제 전후 나머지 모든 행의 count·내용 해시가 동일함을 확인한 뒤 commit했다.
- 정상 `SqlAlchemyRagAliasParityReconciler.run_once()` 결과: claimed 7, reconciled 7,
  failed 0. READY 상태나 색인명을 수동 변경하지 않았다.
- 호스트 worker·beat를 재시작했고 Redis를 거친 reconcile 작업들의 정상 완료를 확인했다.
- 원본·파생 객체와 ES 물리 색인은 이 DB 삭제에서 제거하지 않았다. shared alias는 정상
  reconciler로 조정했다. 사용자 데이터·공통 모델·프로파일은 보존됐다.
- 복구용 합성 41행 백업과 실행 도구는 ignored 작업 경로에 잠시 보존하며 최종 검증 후 정리한다.
- 실제 큐 기반 혼합 PDF 업로드·OCR·검색 검증은 별도로 진행 중이다. 브라우저 직접 검증과
  외부 LLM 호출까지 완료된 것으로 해석하지 않는다.
- 독립 읽기 전용 검증에서 fixture 계정·공간·프로파일·문서 2개·버전 2개 부재와 공유
  프로파일 201·207 및 E5 모델 101 보존을 확인했다. 재시작 로그의 정합성 오류·ERROR·
  Traceback은 0건이고 예약 작업 전송→수신→성공을 확인했다.

## 재발 방지 경계

기존 `test_production_embedding_indexing.py`는 애플리케이션 DB 설정을 그대로 읽을 수 있고,
ES 정리 예외가 후속 DB 정리를 막을 수 있다. 격리 DB·객체 저장소·큐가 보장되기 전에는
사용자 로컬 데이터 설정을 물려 실행하지 않는다. 이번 실제 큐 검증은 고유 DB·ES 접두사·
객체 경로·Redis keyprefix/queue를 별도로 사용한다. 기존 통합 테스트 전체의 격리 강제는
아직 구현되지 않았으므로 후속 개발 검증 항목으로 남긴다.

## 승인 전 조사 이력

읽기 전용 조사만 수행했다. 사용자 원본·모델·DB·ES·파일을 삭제하거나 수정하지 않았다.
정리 요청 범위는 검증된 fixture의 DB 레코드 묶음이며, 실제 DB 자체나 볼륨 삭제가 아니다.
원본·파생 파일은 보존하고 공유 프로파일·모델·사용자 기록을 제외해야 한다.
정확한 의존 관계를 재검증하고 사용자 승인 후에만 처리한다. 전체 검증 완료 상태가 아니다.

하이라이트는 기존 실제 OCR/API 검증과 별개로 이번 조사에서 `SourceViewer.test.tsx`
6건을 재실행해 통과했다. 현재 브라우저 자동화 목록은 비어 있고 in-app browser도 사용할 수
없으므로 실제 브라우저 조작 검증은 수행하지 못했다.
