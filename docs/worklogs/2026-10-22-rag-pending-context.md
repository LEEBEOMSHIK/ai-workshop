# 복구 전환 전 실제 소스·context 검증

2026-10-22. [committed 현재 관측 작업](2026-10-21-rag-fresh-observation.md)에 이어, 전환 중 검증의 선행 조건을 실제 구성 객체로 확인했다. ISSUE-00013/00018 후속 기록이다. **운영 취소·별칭·첨부 복구와 전체 native 지원은 아직 완료하지 않았다.**

## 확인한 차이와 변경

과거 pending 검증 시제품의 O/B/F·27개 경로 시험은 테스트 경로·상수 대체와 수동 runtime 연결을 포함했다. 그 결과를 기존 환경의 실제 생성 경로 검증으로 옮겨 쓰지 않는다. 이번에는 고정 설정 로더, 실제 SQLAlchemy engine/session/repository, 원본·자료 범위·보안 부재 issuer와 `NativeControlContext`를 사용하고 SQL driver·HTTP·파일·Win32 같은 외부 I/O만 합성으로 대체했다. epoch와 제어 소유권은 만들지 않았다.

- namespace가 사용하는 `ProfileRecord.id IN (...) LIMIT ...`를 기존 합성 SQL transport가 지원하지 않았다. 실제 SQLAlchemy 연결에서 실패를 재현한 뒤 필요한 IN/정수 LIMIT만 지원했다. 필터→정렬→LIMIT 순서, 잘못된 값·외부 테이블·임의 SQL 거부를 검증했다. 제품 SQL을 테스트에 맞춰 바꾸지 않았다.
- `control_native._freeze`는 UUID 클래스 자체를 확인했지만 내부 정수의 정확한 타입과 범위를 확인하지 않았다. 같은 값의 int 하위 클래스, bool, 음수, 128비트 초과의 4개 실패를 재현하고 거부하도록 수정했다. 정상 UUID의 기존 비교 형식은 보존했다.
- 실제 준비 경로에서 필요한 공개 소프트웨어 원문 5개가 과거 기록에는 해시로만 남아 있었다. 기존 고정 Docker daemon/container/image와 실행 수명이 전후 같음을 확인하고, 고정 `javap` 명령 5개로 공개 클래스 정의만 다시 읽었다. 모든 바이트가 기존 `_PINS`와 일치했으며 정규화하지 않았다. 50,051바이트 압축 자료와 출처를 [테스트 fixture](../../backend/tests/fixtures/elasticsearch/README.md)에 보존해 외부 환경 없이 재검증할 수 있다.
- 별도 내부 `NativePendingVerification`을 도입했다. `assert_prepared()`는 이미 발행된 준비 소스의 동일성만 확인한다. 운영 지원을 뜻하는 `assert_supported()`와 고정 final 모듈은 추가하지 않았다. 새 객체가 자신의 registry를 소유하며 복사·registry 유실·source 교체를 거부한다. 생성 실패 때 등록을 철회하고 비공개 graph는 repr에 노출하지 않는다.
- 독립 리뷰에서 준비 이후 route의 context·context pin 또는 descriptor의 native process·원본 executor·reader가 바뀌어도 준비 검사를 통과하는 누락을 발견했다. 5개 실패를 먼저 재현한 뒤 실제 `commands.context`와 기존 descriptor issuer의 I/O 없는 `assert_issued()`로 확인하도록 수정했다. 후속 `verify()`에는 거부 검사가 있었으므로 이번 발견은 준비 상태 판단의 정확성 문제이며 운영 권한 우회가 확인된 것은 아니다.

새 실제 소스 fixture의 첫 준비 시험은 큰 stdout의 다음 조각이 stderr로 들어가 실패했다. 이는 합성 Win32의 공유 버퍼 문제였다. 새 fixture 안에서 실제 pipe handle별로 stdout/stderr를 나눠 수정했으며 제품 process 코드나 검증 상수는 변경하지 않았다.

## 검증

| 범위 | 확인한 결과 |
| --- | --- |
| 실제 SQL namespace query | RED 4·음성 통과14 → 수정 후18개 통과 |
| UUID 내부 정수 | 4개 RED 재현 → 수정 후4개 통과 |
| 관련 control·committed snapshot 포함 회귀 | 메인108개 통과, 14.58초 |
| 실제 원본→namespace→absence→context→공개 descriptor/JDK 준비 | 작성자2개 통과, 고정 상수·실제 issuer 유지 |
| 리뷰 수정 전 관련 control·snapshot·SQL·준비 전체 | 독립118개 통과, 18.07초; 검사 전후12파일 SHA 동일 |
| 준비 이후 중첩 연결 변경 | route2·descriptor3, 총5개 RED → 수정 후 관련 준비 시험 메인15개 통과, 9.30초 |
| 수정 후 pending·preepoch | 독립15개 통과, 8.06초; 검사 전후12파일 SHA 동일 |
| SQL 테스트 결과 변환의 타입 보정 후 | 해당 SQL18개 독립 통과; 제품 동작 변경 없음 |
| 최종 정적 검사 | 제품2파일 strict Mypy, 선택 테스트/helper6파일 scoped strict Mypy, 관련10파일 Ruff·format 및 마지막 변경1파일 재검사 통과 |

각 실행은 범위가 겹치므로 합산한 전체 테스트 수로 표현하지 않는다. 최초 독립 검사 wrapper 문법 오류는 pytest 실행 전 실패였고 수정 후118개를 실행했다. 첫 Mypy8 검사는 모듈 이름 중복으로 중단됐으며 `--explicit-package-bases`와 명시한 `MYPYPATH`로 실행 경로를 정리했다. 이어 실제 선택 테스트의 `dict(rows)` 타입 오류1건을 같은 의미의 명시적 키·값 변환으로 수정했다. 함께 드러난 import 대상 기존 테스트/fixture의836개 strict 진단은 이번 수정 범위의 오류와 구분한다. 제품2는 일반 import 검사까지 통과했고, 선택 테스트/helper6은 `--follow-imports=silent`로 대상 파일을 검사했다. **전체 import 테스트 그래프의 strict 통과를 주장하지 않는다.**

합성 fixture 준비에는 실제 repository의 preview/freeze가 합성 SQL 자료를 변경하는 단계가 있다. 전체 테스트를 DML 0으로 표현하지 않는다. 준비 완료 후 epoch·실행·소유권 획득과 추가 업무 변경이 없고, 소유한 engine/pool/연결 및 합성 native handle이 정리되는 것을 확인한다. **운영 DB 호출·모델/임베딩/worker 호출·서버 전환은 0이다.**

실제 공개 소프트웨어 조회는 성공한 Docker 읽기9개(전후 identity4＋javap5)다. 앞선 두 시도는 sandbox의 Docker 설정/명명 파이프 접근 거부로 본 조회 전에 실패했다. 같은 고정 읽기 스크립트의 권한 검토 승인 후 성공했으며 서버 중단이나 프로젝트 오류의 증거로 해석하지 않는다. 이 현재 소프트웨어 조회는 과거 프로세스 종료 증거가 아니다.

증거는 `.local-data/project-agent-work/rag-pending-context-20261022/`에 보존한다. 기존 미커밋44파일 중 의도적으로 갱신한 WORKBOARD 외43파일과 앞선 등록 보고서, committed 관측 보고서는 보존한다. 새 파일을 포함한 이번 변경은 커밋·푸시하지 않았다.

## 아직 남은 범위

내부 pending producer의 **새 실제 factory를 통한 VERIFY 발급/O→B→F/27경로 실행은 아직 검증하지 않았다**. 이번 준비 시험은 그 실행의 성공을 뜻하지 않는다. 실제 held owner·journal/store/key graph, pending 발급과 정확한 VERIFY settlement, all-settled 현재 관측, evidence→anchor→mark_verified→receipt→새 committed 관측까지 연결하고 검증해야 한다. 전체 native factory 지원은 그 이후에만 노출한다.

다음 구현 순서는 독립적으로 읽기 검토했다. 현재 정상 `ConcreteNativeCutoverControl.acquire()`는 소유권 생성 전에 완성 final 구현을 요구하고, `assembly.bind_context()`는 이미 소유한 같은 context만 받는다. 따라서 임시 final 껍데기나 테스트 전용 runtime 대입으로 연결하지 않는다. 먼저 내부 all-settled 관측과 concrete backend를 완성하고, 같은 pending issuer를 보유하는 final 구현·source-owned factory를 연결한 뒤 정상 acquire부터 수명주기를 검증한다. 합성 SQL transport의 event/key-event/phase/floor/receipt DML과 보호 파일·DPAPI·ACL·mutex/pipe 쓰기 경계도 실제 사용 문법·경로에 한정해 확장해야 한다. 이번 기록은 이 후속 구현의 완료 증거가 아니다.

본래 환경의 취소 종료 근거 정산·별칭 receipt/해제·첨부 처리와 검색/원문 확인은 여전히 별도 수용 단계다. 역사 근거를 현재 시각으로 대신하지 않고, READY 강제 변경이나 평가 기준 완화를 하지 않는다. 추가 LLM 평가와 12B/GPU 작업을 수행하지 않았으며 [Agents SDK 순서](2026-10-21-rag-agents-sdk-next-step.md)는 복구 뒤로 유지한다.

관리자 DB 문제/문서 이력 등록은 로그인 대기다. 이번에도 기존 관리자 탭이 `/login?next=...` 화면임을 확인하고 인계용으로 보존했다. 로컬 기록을 DB 반영으로 표현하지 않으며 보존용 `issues.json`도 수정하지 않았다.
