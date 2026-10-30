# RAG 복구: 현재 서버 관측 경로 연결

2026-10-21 착수, 2026-10-22 이번 구현·오프라인 검증 마감. [이전 복구 작업](2026-10-21-rag-recovery-wsl-boundary.md)에 이어 승인된 v2 복구의 committed 현재 서버 관측 경로를 구현했다. 운영 복구와 다음 native 조립 단계는 아직 미완료다.

## 범위와 운영 상태

저장된 성공 기록만으로 현재 서버가 같은 서버이고 같은 권한으로 응답한다고 판단할 수 없다. 이번 변경은 새로 구성한 읽기 전용 의존성을 통해 저장 조건을 확인하고, 고정된 Docker·HTTPS 조회의 실제 응답을 검증한 뒤 그 관측 결과만 발급하는 경로다.

이번 작업은 코드와 외부 I/O를 대체한 합성 테스트 범위다. 운영 RAG 데이터·보안 설정·서버·worker를 변경하지 않았고, 실제 Docker/Elasticsearch 조회·제어와 모델 호출도 수행하지 않았다. 관리자 화면의 인증 상태 확인은 이 범위와 구분한다. 새 환경·계정·모델 설치, 재색인, 운영 전환, commit/push와 캐시 정리도 수행하지 않았다. 기존 미커밋 변경 44파일을 시작 시 SHA로 기록했다. 관리 문서로 이미 등록된 [과거 복구 보고서](2026-10-21-rag-recovery-followup.md)는 변경하지 않는다.

과거 취소 미종료1·열린 별칭1·queued 첨부1은 **직전 운영 관측의 미해결 상태**이며 이번에 DB를 다시 조회한 숫자가 아니다. 새 관측 성공은 과거 프로세스의 종료 시각·종료 대기·자식 정리 증거가 아니다. 부족한 역사 근거를 현재 시각이나 새 영수증으로 대체하지 않는다. 전체 복구와 Agents SDK 구현 착수는 아직 완료되지 않았다.

## 구현

- 고정 HTTPS 읽기: 명시한 프로젝트 CA, 호스트 검증과 실제 peer 인증서 확인 후 로컬 고정 주소에 요청한다. 신원3회와 역할별 인증·권한 확인6회만 허용한다. 요청·응답 크기와 5초 요청 기한을 제한하고, 중복 헤더·압축·비정상 상태·잘못된 chunk framing을 거부한다. 취소 시 실제 소유 소켓 정리를 기다린다.
- 순수 응답 검증: Docker5개 응답의 원래 이미지·볼륨·네트워크·컨테이너, HTTPS의 클러스터·노드·JVM·공개 보안 설정을 저장된 기대값과 비교한다. 저장된 유한 권한 정책은 기존 descriptor와 요청 행렬의 정규 바이트로 복원·대조한다. 순수 검증 결과 자체에는 실행 권한이 없다.
- 실제 저장 자료 연결: 기존 committed source의 SQL·권한 원장·`store.load`와 TLS reader의 보호된 묶음·6개 bind 파일 검증 결과에서 CA와 역할별 자격 정보를 얻는다. 내부 비교용 seal을 역으로 해석해 자격 정보로 사용하지 않는다.
- 소유한 관측: 새 `NativeFreshSecuredReadSource.open_committed()`가 기존 실제 assembly를 직접 구성한다. Docker5회와 HTTPS9회 전후에 저장 상태·floor·anchor·자격 정보·인증서·고정 설정을 다시 확인한다. 동일 실행의 verified→receipted 전환만 허용하고 역행·다른 실행·자료 변경은 거부한다.
- 결과와 종료: 모든 사후 검사가 끝난 뒤에만 복제할 수 없는 관측 객체를 발급한다. 공개 JSON에는 검증한 서버·공개 설정·TLS 해시·유한 권한 정책·key ID만 둔다. 원시 응답·키 값·개인 파일 경로는 포함하지 않는다. 실패는 해당 source를 폐기하며 자동 재시도하지 않는다. 종료는 발급 결과를 먼저 무효화하고 실제 조회와 DB 연결 정리를 기다린다.

주요 구현은 [fresh source](../../backend/src/ai_workshop/labs/rag/indexing/access_epoch_fresh_secured_read.py), [HTTPS transport](../../backend/src/ai_workshop/labs/rag/indexing/access_epoch_https_read.py), [실제 committed 자료 연결](../../backend/src/ai_workshop/labs/rag/indexing/access_epoch_committed_https.py)에 있다.

관측 전체에는 240초의 협조적 기한을 둔다. Docker 대기5×10초와 HTTPS9×5초의 합계95초 외에 SQL·파일·인증서 검사가 필요하다. 기한이 지나면 새 작업을 중단하지만 이미 시작한 작업의 정리는 끝까지 기다린다. 따라서 240초를 보장된 반환 시간으로 표현하지 않는다. 이 복구용 제한은 RAG 답변 품질의 P95 120초 기준과 별개다.

## 재현한 결함과 수정

1. 기존 Docker 읽기 worker가 정리·보호된 출력 기록 실패의 고정 진단을 오류 포장 과정에서 버렸다. worker·일반 예외·취소의 각 경로에서 안전한 진단만 유지하도록 수정했다. 비공개 예외 문자열은 노출하지 않는다.
2. 첫 통합에서 CA 바이트를 바이트 미지원 일반 seal 함수에 전달해 정상 관측도 거부됐다. 실제 CA 해시와 나머지 타입이 유지되는 비교 값으로 분리했다.
3. Docker 조회 객체는 닫힌 자식 이력을 보존하므로 같은 객체를 두 번째 조회에 재사용할 수 없었다. 각 조회에 새 실제 객체를 만들고 이전 종료 이력은 유지한다.
4. 조회를 직접 수행하는 context 소유자와 외부 `close()`가 서로 task 전체의 종료를 기다리는 교착이 재현됐다. 실제 transport 정리가 끝난 관측 메서드의 완료 신호만 기다리도록 수정했다. 반복·동시 close는 하나의 소유한 정리 작업을 기다린다.
5. native 객체의 인스턴스 메서드 교체와 함수 기본 인자 변경이 기존 함수 고정 검사에서 누락됐다. 인스턴스 덮어쓰기와 함수 defaults/kwdefaults의 타입을 포함한 변경을 거부한다.
6. UUID 내부 정수의 타입·범위 변조를 일반 값 비교가 놓쳤다. 정확한 `int`와 128비트 범위를 검사한다. 정상 값의 비교 방식은 유지하며 영 UUID의 허용 여부는 각 업무 계약이 계속 판단한다.

## 검증

합성 fixture는 실제 제품 assembly·저장소·보호 파일·native process·HTTP parser를 사용하고 외부 SQL driver·Windows API·파일·socket/SSL I/O만 대체한다. guard·issuer·자료 getter를 가짜 성공으로 교체하지 않는다.

| 검증 범위 | 결과와 한계 |
| --- | --- |
| committed catalog/material·Docker·유한 권한 정책·HTTPS | 독립 302개 통과. 8/9/108/114/63개 구성 |
| HTTPS·server packets·material·기존 TLS/material/source association 7파일 | 독립 245개 통과. TLS `_fresh`의 실제 sample 연결 이후 회귀이며 시작 시 전체 SHA는 미기록 |
| Docker worker 오류·정리 진단 | 메인·독립 각 35개 통과 |
| 기존 committed source | 최종 UUID 보강 후 메인 20개 통과 |
| 신규 source 수용 | 당시 17개 통과, 26분3초. 초기 정상·새 nonce·상태 전진/역행·늦은 floor/credential/binary/TLS 변경·HTTP/Docker 실패·반복 취소. 이후 close/seal 보강을 포함한 최종 동일 SHA 결과로 표현하지 않음 |
| context 소유자와 외부 close 경합 | 완료 Future 보강 후 별도 1개 통과 |
| 메서드/defaults/UUID 변조 | 6개+2개 RED 뒤 메인 8개와 독립 8개 통과 |
| 최신 영향 범위 | 정상·중복 조회/취소·기한 만료/정리 실패·외부 close 각1개와 seal8개, 총12개 독립 통과. 377.28초, exit0, 실패/오류/skip0. 실행 전후18파일 SHA 동일 |
| 정적 검사 | 제품9파일 Mypy·Ruff·format, 테스트11파일 Ruff·format 통과. 후속 import 정렬 뒤27개 수집·빠른8개 통과 |

서로 겹치는 검증 묶음을 단순 합산하지 않는다. 최종 변경이 영향을 주는 경로와 새 테스트만 다시 검증하고, 변경 없는 전체 수용 시험을 반복하지 않는다. 302/245와 초기 계측의 과거 stdout 값은 `independent-prior-results.json`에 복구 기록으로 옮겼으며 원래 JUnit 결과인 것처럼 표시하지 않는다. 최종12개는 별도의 전후 SHA와 JUnit을 보존한다.

최종12개 후 제품 파일 변경은 없다. 테스트3파일의 import 순서·빈 줄만 정식 backend cwd의 Ruff 설정으로 고쳤다. 그 변경을 역으로 적용하면 검증 당시 SHA와 정확히 같아짐을 별도 검사했다. 최종 제품 source SHA는 `ff35706ce89cfa05464ed0dca3b613f1829141d28e3b31e7c314eb93d4c37b84`다. 루트 cwd에서 명시 config만 사용하면 기본 `src` 탐색 위치가 달라지는 것이 초기 lint 판정 불일치의 원인이었다.

기존 변경44파일 중 의도한 `WORKBOARD.md` 외43파일의 SHA와 등록된 과거 보고서 SHA를 보존했다. 새 문서·보드의 로컬 링크/anchor와 최근 완료5개 제한도 검사했다. 수정 코드·새 검증 결과는 커밋하지 않았다.

역할은 메인이 구현·통합, 별도 평가 역할이 테스트 설계, 별도 검증 역할이 실행·계측, 보안/인프라 리뷰 역할이 독립 검토를 담당했다. 테스트 작성자의 실행을 최종 독립 검증으로 세지 않는다.

실행 증거는 `.local-data/project-agent-work/rag-fresh-observation-20261021/`에 보존한다. 프로파일링 시간은 운영 응답 속도 측정값으로 사용하지 않는다.

독립 정상 경로를 처음 재실행할 때는 테스트용 임시 경로가 `.pending` 파일까지 262자가 되어 Windows 경로 제한에서 실패했다. 실제 제품 guard를 고치지 않고 더 짧은 전용 basetemp로 같은 경로가 통과함을 확인했다. 해당 실패 기록을 보존한다.

독립 관측 1회의 비용 계측(초기 fixture 준비 제외)은 다음과 같다. 당시 import 시점의 파일 SHA는 별도 기록하지 않았다. 프로세스 시작 후 디스크에서 확인한 SHA를 실제 import 버전이라고 단정하지 않으며, 최신 코드 검증은 별도 전후 SHA가 있는 실행으로 구분한다.

| 합성 I/O 계측 항목 | 관측값 |
| --- | ---: |
| SQLAlchemy가 합성 DBAPI에 전달한 SELECT | 1,464 |
| READ ONLY snapshot / rollback | 122 / 245 |
| 보호 파일 open / 합성 DPAPI / ACL 경계 | 630 / 1,186 / 11,998 |
| Docker / HTTPS 고정 조회 | 5 / 9 |
| 닫힌 합성 native handle / 남은 handle | 40 / 0 |
| 삭제한 process attribute list | 5 |
| 소유 context 종료 후 열린 DB 연결 / retained buffer | 0 / 0 |
| DML / commit | 0 / 0 |

모든 합성 HTTPS peer/file이 닫혔다. 계측된 관측 함수 시간은 164.427초이며 CPU에서 실제 검증 코드를 수행한 합성 시험 시간이다. 운영 PostgreSQL 쿼리 수, 실제 Windows 자원 정리 횟수 또는 사용자 RAG 응답 시간 측정으로 해석하지 않는다. 현재 구현은 인접 검사를 합치거나 SQL/파일 검사 성공을 재사용하지 않는다. 실제 도입 시 이 검사 비용을 측정해야 한다.

## 남은 복구 경계

이번 source는 **이미 committed된 verified/receipted 상태의 현재 관측**만 구현한다. 아직 전환 중인 all-settled 상태의 실제 context·pending verifier 연결, 완전한 native 검증 backend/factory, 역사 근거 정산과 본래 환경 수용은 남아 있다. 부분 모듈을 만들어 지원 검사를 통과시키지 않았으며 native 전환 차단을 해제하지 않았다.

실제 receipt 저장·별칭 해제·정합성 복구·첨부 처리·검색/원문 확인은 그 선행 조건을 만족한 정상 경로에서 별도로 검증해야 한다. 현재 상태를 강제로 READY로 바꾸거나 품질 기준을 낮추지 않는다. 12B/GPU 보류와 [Agents SDK 후속 순서](2026-10-21-rag-agents-sdk-next-step.md)를 유지한다.

다음 구현은 실제 all-settled context와 pending 검증 결과를 연결하고, 이번 committed 관측을 소비하는 완전한 native backend/factory를 조립하는 것이다. 그 전체 경로의 오프라인 검증과 역사 근거 정산 전에는 전환을 실행하지 않는다. 구현 연결·운영 전환·세 복구 완료를 각각 구분해 보고한다.

ISSUE-00013/00018의 관리자 DB 이력 반영은 미완료다. 2026-10-22 기존 Chrome의 본래 관리자 URL에 접속했으나 로그인 화면으로 돌아오는 것을 확인하고 사용자에게 로그인 필요를 알렸다. 코드 검증은 계속 진행한다. 현 문서 작성만으로 DB 반영을 주장하지 않으며 보존용 `issues.json`은 수정하지 않는다.
