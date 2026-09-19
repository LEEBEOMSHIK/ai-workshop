# 공유 별칭 종료 확인과 문서 쓰기 차단

- 일자: 2026-09-20
- 사용자 승인: 별칭 종료 확인·문서 쓰기 차단 설명 후 “그래 진행해”.
- 계약: [설계](../superpowers/specs/2026-09-20-rag-alias-write-fence-design.md), [계획](../superpowers/plans/2026-09-20-rag-alias-write-fence.md).
- 실사용 migration·배포·물리 삭제·commit/push는 범위 밖이다.

## 역할과 작업 경계

높은 위험의 RAG/DB 동시성 변경으로 분류했다. 메인은 요구/시스템/RAG·색인·Python 연결·테스트 설계·문서를 맡았다.
별도 DBA가 원장·migration과 잠금 경계를 검토하고 Task1을 구현했으며 별도 담당이 fence core를 구현했다.
코드/프라이버시 및 통합 검증은 구현하지 않은 리뷰어에게 배정했다. UI·모델 변경은 없어 제외했다.
테스트용 임시 서비스 준비에 한해 메인이 인프라 역할을 수행했다. 기존 worktree 권한 실패의 checkout fallback을 유지했다.

역할 selector 첫 실행의 root 인수가 중복 경로를 만들어 실패했다. 저장소 root로 수정한 실행에서
필수 10개 역할을 확인했다. 추가 패키지는 설치하지 않았다. 기존 프론트·ADR·참고 자료 및 선행 색인 출처 변경을 보존했다.

## 구현과 확인한 경계

`rag_alias_operations`는 같은 cluster/alias의 open 요청을 하나로 제한한다. 기존 source/profile의 잠금을
기다리는 FK가 없으므로 별도 연결의 사전 commit이 자기 교착 없이 완료된다. 입력·identity는 불변이고 기록이
남은 downgrade는 거부한다. ES의 정확한 ack·target 확인 뒤만 닫는다. timeout/취소/종료 기록 실패는 열린
요청을 보존하고 후속 mutation을 막는다. 업무 DB rollback과 원장 종료 실패는 다른 경계로 검증한다.

`rag_index_write_fences`는 exact Document/workspace/generation을 RESTRICT FK로 묶는다. block은 Document
→정렬 Profile 순으로 잠그며 반대 순서의 Asset/Build 잠금을 추가하지 않는다. source gate는 require_active=False
경로에서도 lifecycle/fence를 확인한다. activation과 parity의 target은 비활성·차단 문서를 제외한다.
prepare/alias open과 legacy는 writer 종료 판정을 막는다. inventory는 lifecycle/fence/alias history를 두 번 읽어 대조한다.

독립 리뷰에서 truthy 값으로 승인 응답을 처리하던 문제를 발견했다. 문자열 `"false"`와 숫자1이 성공으로
변환되는 RED를 확인한 뒤 `is True`로 수정했다. READY shortcut의 미확인 alias 누락도 RED→GREEN으로 수정했다.
실제 activation 중 fence가 대기하고 완료 후 다음 READY가 차단되는 경합, 다른 문서 보존, 원장 commit 실패 후
동일한 실제 별칭이 관찰되어도 재전송하지 않는 흐름을 검증했다.

## 검증 환경과 결과

기존 이미지의 PostgreSQL17·Elasticsearch9.5.2를 전용 loopback 임의 포트·tmpfs·AutoRemove 컨테이너로 실행했다.
이 작업 라벨은 `ai-workshop.task=rag-alias-fence`다. 영속 volume/host mount 없이 UUID 전용 DB와 exact ES
테스트 index만 사용했다. 테스트는 기존 `.venv`와 작업별 `backend/.pytest-alias-*` basetemp에서 수행했다.

- 관련 indexing·ingestion·retrieval·config·worker 단위 290 passed.
- 신규/선행 색인 출처 통합 54 passed(전용 PG 및 실제 ES stage→READY→inventory 포함).
- mypy indexing·stages·locking 19 source files 및 관련 Ruff 통과.
- 독립 테스트 60회, 고유56건 통과. 최종 코드/프라이버시 리뷰 잔여 차단 없음.
- 마지막 DB 보완 후 기존 legacy parity4건과 원장10건을 함께 실행해 14 passed(26.17초)를 확인했다.
  중복을 제외한 이번 주 검증은 349건이다. 전체 backend/브라우저 E2E 통과를 뜻하지 않는다.

기존 parity 회귀의 첫 실행에서는 별도 원장 commit이 추가되어 기존 업무 commit 실패 주입 지점과 오류 기대값이
달라진 것을 확인했다. journal 종료 commit 이후 업무 commit에 실패를 주입하고, 미확인 전송은 일반 재시도 대신
writer_unconfirmed로 기대하도록 갱신했다. 많은 profile 순회의 추가 실패는 psycopg가 prepared generic plan을
사용할 때 바인딩 파라미터로 된 ON CONFLICT 조건에서 partial UNIQUE를 찾지 못하는 문제였다.
DBA가 실제 InvalidColumnReference를 확인하고 `index_where=text("state = 'open'")`로 수정했다.
prepare_threshold=0으로 강제한 15회 예약 회귀를 추가했고 원장10건·103-profile keyset 재검증을 통과했다.
마지막 독립 재검토에서도 원장10건·keyset1건이 통과했고 잔여 차단 사항이 없었다. 독립 실행은 중복을
포함해 총71회다. 독립 검증 명령의 합성 SECRET_KEY 누락으로 한 번 fixture 시작 전 오류가 있었으며
필수 설정을 보완한 재실행에서 통과했다.

## 마감

문서3개·상대 링크5개·공백·최근 완료5개·AGENTS 200줄 이하 검사와 관련 `git diff --check`를 통과했다.
임시 컨테이너의 exact ID·작업 라벨·AutoRemove·tmpfs·영속 mount 부재를 확인하고 이번 검증용 두 개만
종료했다. 기존 `tpmp-db-local`의 healthy 상태 및 기존 중지 서비스 보존을 재확인했다.
이미지·volume·기존 캐시·작업별 pytest 임시 폴더는 일괄 삭제하지 않았다. 구현 검증 단계에서는 Git staging/commit/push를 하지 않았다.

사용자의 후속 커밋·푸시 승인에 따라 선행 색인 출처와 이번 별칭/fence를 하나의 변경으로 main에 인계한다.
별도 UI·ADR-0023·이동 설계·참고 자료는 제외한다. 별도 worktree가 생성되지 않아 제거할 작업 공간은 없다.

## 후속 경계

RAG 색인/별칭 writer의 admission·종료 관찰 기반이다. 실제 purge API/UI, 원본·파서/OCR/뷰어 임시물·작업
메타데이터 및 전체 참여자 조립은 남아 있다. 구 프로세스·외부 관리자 요청의 종료를 DB 원장만으로 증명하지 않는다.
미확인 요청의 자동 해제나 fence 해제는 제공하지 않으며, 원장 최종 보존/정리도 전체 삭제 계약에서 연결한다.
실사용 적용 조건은 [로컬 실행 정본](../runbooks/local-development.md)에 갱신했다.
