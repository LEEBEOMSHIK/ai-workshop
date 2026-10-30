# 여러 화면의 응답 지연 진단

> 후속: 아래는 수정 전 진단 기록이다. 이후 승인된 수정과 본래 전후 비교는 [응답성 개선 결과](2026-10-31-backend-response-improvements.md)를 따른다.

- 관측: 2026-10-31 KST
- 문제: [ISSUE-00048](http://127.0.0.1:5173/admin/system/issues?offset=0&issue=c7e47a74-fdfc-4cd1-90df-e1f54f239c90)
- 상태: 원인 진단 완료, 성능 수정 미착수

사용자는 특정 페이지가 아니라 여러 화면의 전반적인 지연을 보고했다. 기존 API·DB·로그인 계정을 사용해 상태 요청, 조회 서비스, DB 연결, Windows/Docker 자원을 조사했다. 제품 코드·환경·기본 연결·모델·정책·캐시를 변경하거나 서버/다른 앱을 재시작하지 않았다. 신규 모델 호출과 추가 API 비용은 0이다. 문제 기록 외 업무 데이터를 쓰지 않았다.

## 결론

구성 준비 상태 조회에 실행파일 전체 해시를 동기적으로 반복 계산하는 경로가 있다. 진단 프로세스의 이벤트 루프 정체와 본래 API의 동시 상태 요청 지연을 각각 확인했다. 요청마다 DB 연결 풀을 재생성하고 구성마다 조회를 반복하는 비용도 있다. 별도로 Windows nonpaged pool이 약11.7GiB를 차지하고 가용 메모리가 약1GiB까지 내려가 전체 응답 변동이 커질 조건을 관측했다. 특정 드라이버의 누수나 각 원인의 전체 기여율은 아직 확정하지 않았다.

모델을 호출하지 않고 재현했으므로 이 지연을 Gemma/Claude의 답변 생성 시간으로 설명할 수 없다. 최근 Claude 변경이 Windows 메모리 상태를 만들었다는 증거도 없다.

## 본래 API·화면 동시 관측

첫 상태 조회는 health94ms, ready220ms였다. 반복 health는4~22ms, ready58~93ms로 내려왔다. 인증 없는 `/auth/me`23ms는 인증 토큰 부재로 DB 조회 전에 반환하므로 유효 인증 요청의 성능 기준으로 사용하지 않는다. 로그인 페이지는 첫1.278초, 반복1.214/0.292/0.267초였다. frontend 개발 빌드·호스트 부담이 섞인 값이며 backend 순수 시간과 구분한다.

기존 관리자 화면의 **설정 목록 새로 확인**을 한 번 누르고 별도 프로세스에서40초/100건 상한으로 health를 읽었다. 실제100건 모두200이었다.

| 범위 | 관측 |
| --- | --- |
| 갱신 직전51건 | 중앙4.52ms, 최대137.50ms |
| 갱신 후 네 차례 큰 지연 | 1,379.31 / 1,294.36 / 1,198.34 / 1,278.91ms |
| 화면 | 갱신 중 표시 후 버튼 다시 활성, 선택/등록/모델 실행 없음 |

갱신 시작은 UTC `2026-10-30T16:06:19.152Z`, 큰 지연 요청 시작은16:06:24.972~30.620이다. 실제 API에서도 다른 단순 요청이 지연되는 현상을 확인한 것이며 이 수치를 아래 별도 프로세스의3.6초 지연과 동일한 측정으로 합치지 않는다. 모든 화면·각 요청의 P95/P99 수용 기준을 검증한 것은 아니다.

## 기존 DB·서비스 계측

현재 활성 소유자의 ID를 기존 DB에서 읽어 같은 서비스 권한 경로를 사용했다. 인증 토큰을 새로 만들거나 관리자 권한을 임의 생성하지 않았다. 모델/문서 본문·계정·비밀값은 출력하지 않고 시간·건수·테이블별 횟수만 기록했다.

주 세션은 `default_transaction_read_only=on`이었다. Codex 상태 조회 내부는 정상 `SELECT FOR SHARE` 정책 잠금을 유지하므로 별도 엔진을 read-only로 강제하지 않았다. 상세 계측은 프로세스 내 모든 SQLAlchemy Engine의 실행 SQL에 DML 거절 장치를 두고 기존 읽기 경로만 호출했다. 이는 진단 보조장치이며 일반 SQL 보안 sandbox라는 뜻은 아니다. 시작 시 DB 차단 세션0·실행 중 RAG 작업0이었다.

| 항목 | 첫 가벼운 측정 | 상세 계측, 다른 호스트 부하 |
| --- | --- | --- |
| 모델14개 | 34.56 / 4.94ms, SQL1회 | 571.18 / 36.51ms |
| 구성16개 목록 | 361.91 / 186.03ms, SQL97회 | 1,897.61 / 801.19ms, SQL97회 |
| 구성 준비 상태 | 9.297 / 5.850초 | 56.788 / 20.795초 |
| 준비 상태 전체 SQL | 주 엔진만162회 집계 | 모든 엔진243회 집계 |
| 새 연결 + SELECT1 + 종료,5회 | 39.8~56.8ms | 255.7~1,309.6ms |
| 연결 재사용 + SELECT1,5회 | 4.5~8.0ms | 7.9~295.7ms |

두 열은 같은 부하의 전후 비교가 아니다. 초기162→상세243은 관측 범위 확장이며 SQL 증가 회귀가 아니다. 드라이버에서 잰 SQL 경과시간에는 DB 실행 외 통신·스케줄링·대기도 포함된다. 이 소규모 진단으로 전체 화면 개선율을 계산하지 않는다.

### 동기 파일 검사

`SqlAlchemyGenerationReadiness.is_ready` → Codex `status` → `_binding` → `CodexRunnerRegistry.resolve/_inspect` → `_executable_digest`가 async 경로에서 동기 실행된다. 과거 Codex 구성이4개여서 같은 크기의 실행파일을 네 번 읽는다. 상태 조회는 새 Codex 모델 실행을 하지 않는다.

| 상세 계측 | 첫 측정 | 두 번째 측정 |
| --- | --- | --- |
| 파일 크기 / 해시 횟수 | 341,270,320bytes(325.46MiB) / 4회 | 동일 |
| 해시 경과시간 합 | 13.701초 | 11.812초 |
| 진단 프로세스 이벤트 루프 최대 관측 지연 | 3.616초 | 3.756초 |

한 번의 준비 상태 조회당 약1.27GiB의 논리 파일 읽기다. OS 캐시가 개입하므로 매번 그만큼 실제 디스크를 읽었다는 뜻은 아니다. resolve 시간은 해시 시간을 포함하므로 합산하지 않는다.20ms heartbeat가 관측한 최대 지연은 보장된 상한이 아니다.

코드 위치: [파일 무결성 검사](../../backend/src/ai_workshop/labs/rag/generation/codex_runner_registry.py), [상태 조회](../../backend/src/ai_workshop/labs/rag/generation/codex_verification.py), [readiness](../../backend/src/ai_workshop/labs/rag/generation/readiness.py).

### 공통 연결·반복 조회

[get_session](../../backend/src/ai_workshop/shared/db.py)은 HTTP 요청마다 engine 생성→세션 트랜잭션→dispose를 수행한다. 유효 인증 요청마다 현재 사용자 조회와 새 연결 비용이 발생한다. [구성 repository](../../backend/src/ai_workshop/labs/rag/configurations/repository.py)의 목록 조회는 구성마다 최신 버전·정책·구독·프로파일을 직렬 조회하고 [service](../../backend/src/ai_workshop/labs/rag/configurations/service.py)가 다시 준비 상태를 확인한다.

통합 설정은 초기10개 API와 하위 패널의 중복 setup-options1개를 요청한다. 고급 구성은8개 요청 완료를 기다린다. SSR 인증 선언은 중복되지만 Next의 동일 fetch 메모이제이션 가능성이 있어 선언 수를 실제 중복 요청 수로 확정하지 않는다.

## 호스트 관측과 남은 원인

물리 메모리는 약23.5GiB, 논리 프로세서10개다. 초기 가용 메모리 약1,557MiB, 압박 관측 시984MiB였다. nonpaged pool은12,544,389,120bytes(약11.68GiB), 후속12,536,193,024bytes로 여전히 컸다. 후속 가용1,166MiB·PageReads4,262/s를 관측했다. 짧은 표본만으로 지속 증가나 누수를 확정할 수 없다.

PageReads는 파일 기반 페이지를 포함한 hard-page-fault 읽기이며 모두 pagefile swap을 의미하지 않는다. API/node의 작은 resident memory와 큰 private bytes도 단독으로 누수 증거가 아니다. Docker 스냅샷에서 PostgreSQL128.2MiB·CPU0%, Redis9.5MiB·0.21%, Elasticsearch1.612GiB·3.10%였지만 순간값으로 전체 기간 부하를 설명하지 않는다. Windows nonpaged 메모리의 할당 주체는 미확인이다.

Microsoft는 추세 확인과 pool-tag별 할당 추적으로 커널 메모리 원인을 찾도록 안내한다. [메모리 누수 판단](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/determining-whether-a-leak-exists), [PoolMon](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/poolmon). 현재 PATH에는 WPR이 있고 PoolMon은 발견하지 못했으며 새 도구 설치·trace 수집·드라이버 변경·재부팅은 하지 않았다.

## 다음 수정의 우선순위

1. 무결성 검사를 유지하고 동기 검사를 이벤트 루프 밖에서 제한적으로 처리한다. 취소·종료·동시성 제한을 검증한다. 다른 요청의 응답성과 해당 목록의 총 소요 시간을 따로 비교한다. 과거 검사 성공을 무조건 캐시하거나 해시를 제거하지 않는다.
2. 앱 수명주기에 맞춰 DB 연결 풀을 재사용한다. 요청별 트랜잭션·현재 권한 재조회·worker/테스트의 엔진 소유와 종료를 보존한다.
3. 구성 조회를 묶고 작업 내 이미 읽은 불변 자료를 재사용한다. 현재 권한·정책 승인·준비 상태 확인을 생략하지 않는다. 중복 setup-options도 별도로 정리한다.
4. 호스트 nonpaged pool의 할당 주체와 추세를 읽기 전용으로 조사한다. 이것이 해결됐다고 가정하여 앱 수정 효과를 과장하지 않는다.

현재는 조사 요청에 대한 진단 완료이며 구현·성능 개선 완료가 아니다. 모델·프롬프트·근거·답변·인용·품질 기준은 바꾸지 않았다. 문제 상태는 진행 중으로 저장했다. 후속 수정 시 독립 보안/동작 검증과 본래 동시 요청 비교가 필요하다.

## 증거와 독립 검토

`.local-data/project-agent-work/backend-latency-20261031/`의 `probe.py`, `service-timing.json`, `service-detailed.json`, `health_watch.py`, `live-health-watch.json`, `live-health-summary.json`, `host-final.json`, `code-audit.md`, `measurement-review.md`에 보존한다. 별도 테스트/빌드를 성능 진단과 동시에 실행하지 않았다. SQL 본문·매개변수·키·문서 내용을 저장하지 않았다.

백엔드 담당이 조회·인증·프록시·파일 검사의 코드 근거를 독립 조사하고 root의 계측 해석을 읽기 전용으로 재검토했다. 초기 SQL 관측 범위 차이·호스트 부하 변화·논리/물리 읽기 구분을 반영했다. 본래 화면 동시 health 후속 결과는 root가 별도 수행했다. ISSUE-00048을 기존 관리자 화면에서 등록·재조회했다. 커밋/푸시·제품 수정·성능 수정용 테스트는 수행하지 않았다.
