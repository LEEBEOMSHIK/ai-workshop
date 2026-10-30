# 무결성·권한을 유지하는 백엔드 응답성 개선

- 날짜: 2026-10-31 KST
- 문제: [ISSUE-00048](http://127.0.0.1:5173/admin/system/issues?offset=0&issue=c7e47a74-fdfc-4cd1-90df-e1f54f239c90)
- 상태: 구현·독립 검증·본래 API 반영·실제 화면 동시 요청 비교 완료
- 정본: [ADR-0054](../decisions/0054-request-response-lifetimes.md), [계획](../superpowers/plans/2026-10-31-backend-response-improvements.md), [수정 전 진단](2026-10-31-backend-latency-diagnosis.md)

## 결과

전체 실행파일 검사와 현재 권한·정책·승인 검사를 유지하면서 동기 검사가 다른 요청을 막는 경로를 분리했다. HTTP DB 풀은 앱 수명주기에서 재사용하고 구성 조회는 일괄화했다. 모델·프롬프트·검색 근거·답변·인용 판정과 기본 연결을 바꾸지 않았다. 실제 모델 호출 및 추가 API 비용은 0이다.

### 본래 API에서 화면 갱신 중 다른 요청

기존 관리자 계정의 **모델 연결·RAG 설정 → 설정 목록 새로 확인**을 사용했다. 모델 등록·연결 검증·답변 실행·적용은 하지 않았다. 별도 클라이언트가250ms 간격으로 health를 최대100건/40초 읽었다. 각 구간은 갱신 전 idle과 갱신 중을 포함하며, 전체 운영 부하의 지연 분포가 아니다.

| 항목 | 수정 전 | 수정 후 |
| --- | ---: | ---: |
| 요청 수 / HTTP200 | 100 / 100 | 100 / 100 |
| 중앙값 | 5.72ms | 4.97ms |
| 최대 지연 | 1,226.26ms | 190.31ms |
| 500ms 초과 | 4건 | 0건 |

수정 전 네 차례 큰 지연은1,226/1,204/1,155/1,157ms였다. 수정 후 목록이 정상 표시되고 갱신 버튼이 다시 활성화됨을 확인했다. 기존 로컬/Codex 연결과 등록 옵션도 그대로 표시됐다. 이 결과는 다른 요청이 초 단위로 묶이는 현상의 개선 증거이며 모든 업무 화면의 성능이나 LLM 생성 시간 개선을 뜻하지 않는다.

관측 UTC: 수정 전16:29:50~16:30:20, 갱신 호출16:30:06.578; 수정 후16:32:45~16:33:11, 갱신 호출16:32:59.617. 도구가 클릭을 처리하는 시간은 실제 HTTP 요청 시작 시각과 같지 않다. 수정 후 서비스 probe는16:29:48, 독립 검증은16:29:36에 종료돼 위 갱신 구간과 겹치지 않았다. 앞선 `health-before.json`은 UI 갱신 클릭이 도구 지연으로 수행되지 않아 idle 참고값일 뿐 전후 표에서 제외했다.

### 같은 본래 DB·같은 결과의 서비스 비교

원래 활성 소유자와16개 구성에 대해 각2회 측정했다. 수정 전 소스는 로컬 증거 디렉터리에 보존하고 진단 프로세스에서만 import해 측정했다. 제품 파일을 교체하거나 다른 DB/계정을 만들지 않았다. 변경 전후 모델·프로파일·구성 목록·준비 상태 결과의 전체 정규화 SHA-256이 모두 동일했다.

| 항목 | 수정 전 1/2회 | 수정 후 1/2회 |
| --- | ---: | ---: |
| 구성 목록 | 2,485.69 / 487.11ms | 31.39 / 11.34ms |
| 구성 목록 SQL | 97 / 97회 | 3 / 3회 |
| 생성 준비 상태 | 9.374 / 9.216초 | 5.839 / 5.677초 |
| 준비 상태 SQL, 모든 엔진 | 243 / 243회 | 121 / 121회 |
| 진단 루프 최대 지연 | 2,588.33 / 2,293.57ms | 71.15 / 30.75ms |
| 325.46MiB 실행파일 전체 해시 | 각4회 | 각4회 |

목록+준비 상태 SQL은340→124회다. SQL 수는 반복 작업 감소를 나타내지만 측정 시점의 호스트 부하와 파일/DB 캐시가 동일하다고 가정하지 않는다. 특히 첫 목록 시간의 큰 차이 전체를 코드 효과로 설명하지 않는다. 진단 프로세스의20ms heartbeat와 본래 API HTTP 관측은 별도 경계다.

수정 후 해시 총 시간은4.912/4.808초다. 전체 검사 비용 자체는 남아 있으며 약5.7초의 준비 조회를 계속 개선할 여지는 있다. 해시 시간과 이를 포함하는 resolve 시간을 합산하지 않았다. 약1.27GiB/조회는 논리 읽기이며 물리 디스크 읽기량이 아니다.

### DB 연결 재사용·트랜잭션

같은 측정 구간의 새 연결+SELECT1+dispose5회는32.8~45.8ms, 재사용 연결은3.9~6.0ms였다. 별도 실제 `RequestDatabase`와 원래 PostgreSQL 통합 검사에서6개 순차 요청이 같은 backend connection을 재사용하고, 동시 두 세션은 다른 connection을 사용했다. 요청 실패 후 `SET LOCAL` 상태가 rollback되어 다음 요청에 남지 않았으며 lifespan 종료 뒤 pool이 폐기됐다. 첫 요청283.9ms, 다음5회25.6~66.9ms였으며 이 추가 검사는 부하·SQL 경계가 달라 앞의 SELECT1 시간과 합치지 않는다. 영속 쓰기와 임시 테이블 생성은 없다.

## 변경 경계

- `generation/codex_verification.py`와 전용 `codex_integrity_offload.py`: 상태 조회 및 명시 검증의 binding3곳을 await한다. 이벤트 루프별 실제 검사1개만 executor에 제출하며 취소된 대기자는 제출하지 않는다. 실행 중 반복 취소도 실제 future 종료 후 전달하고 슬롯을 반환한다. default executor 종료는 이벤트 루프가 소유한다. 검사 결과 캐시는 없다. 기존 registry의 경로·reparse·파일 정체성·전체 SHA-256 구현은 그대로다.
- `shared/db.py`, `main.py`: lifespan마다 별도 `RequestDatabase`를 소유하고 첫 DB 요청 때 engine/factory를 만든다. 요청마다 별도 세션·begin/commit/rollback/close를 수행한다. 현재 사용자 확인은 유지한다. background→model host→DB 순으로 종료하며 앞의 cleanup 실패에도 DB disposal을 실행한다. worker/독립 서비스의 명시 engine 소유권은 유지한다.
- `configurations/repository.py`, `service.py`, `generation/readiness.py`, `deployments/repository.py`: 현재 owner/system 필터와 최신 버전 정렬을 유지한 집합 조회, 요청 내 불변 profile/deployment/model 일괄 해석을 추가했다. 누락 관계·잘못된 policy는 기존처럼 거절한다. 현재 health·정책 잠금·구성별 승인·Codex proof/무결성 확인을 합쳐서 생략하거나 요청 밖에 캐시하지 않는다.

## 검증

| 범위 | 실제 결과 |
| --- | --- |
| 무결성 offload 신규 RED | 8실패/1통과, 예상 동기 경로 재현 |
| 무결성/기존 verification·registry·execution | 198통과, 기존 symlink OS 권한4skip |
| 구성 일괄 조회 신규 RED | 합성2/17개가13/103 SELECT로 상한 실패, 이후 집합 조회 통과 |
| 구성·배포·준비 상태 회귀 | 139통과, 신규9개 포함 |
| HTTP DB lifecycle 신규 RED | 5개 예상 실패: 재사용/종료 소유/격리 |
| DB·기존 인증·health·background 회귀 | 35통과 |
| 답변 프롬프트·인용·상대 영업일 + DB | 95통과 |
| 독립 보안·통합 검증 | 36통과, 독립 작성13개 포함 |
| 정적 검사 | 변경8소스 strict Mypy, 변경 source/test Ruff, diff 검사 통과 |
| 본래 API | health/ready200, OpenAPI 전체 해시 동일 |

범위가 겹치므로 숫자를 총 고유 테스트 수로 합산하지 않는다. 독립 검증은 구현 담당과 분리했고 반복 취소·대기 취소·fresh inspection·HTTP 취소 rollback·startup 실패·두 app 격리·같은 profile의 서로 다른 승인·중간 정책 변경·누락 관계·기존 상세와 전체 값 동등성을 확인했다. 단위 검증은 합성 자료이며 모델/네트워크를 사용하지 않았다. 전체 repository 테스트를 실행한 것은 아니다.

일부 제한 환경의 Python 실행은 출력 없이 정체해 해당 세션만 중단했다. 승인된 기존 Conda 환경으로 같은 offline 검사를 실행했고 임시 디렉터리 ACL 문제는 작업별 basetemp를 지정했다. 실패·정체 기록은 성공으로 집계하지 않았다. 초기 probe의 UUID map key 직렬화 오류는 진단 코드에서 수정해 완주한 파일만 비교에 사용했다.

## 본래 반영·보존

원래 API의 실행 경로·포트18000·PID256188을 확인하고 실행 중 RAG 작업0·화면 갱신 완료 뒤 같은 설정/명령으로 재기동했다(새 PID246760). frontend·worker·Ollama·기본 연결·migration·환경 파일은 변경하지 않았다. health/ready와 실제 관리자 조회를 확인했다.

문제 이력 쓰기 전에 기존124개 테이블162,099행의 전체 행 해시, `.env`, schema0068, 생성형 수용 gate가 모두 동일했다. 독립 검증에서 인증 서비스·원래 runner 검사·생성 domain 소스 해시도 보존됐다. 이후 ISSUE48의 수정·검증·남은 작업 및 날짜별 이력을 기존 관리자 화면에 저장·재조회했다.

문제 본문 저장 직후 진행 이력 추가1회는 이전 revision의409 충돌로 거절됐다. 서버가 오래된 버전 쓰기를 차단한 결과이며, 새로고침으로 최신 버전을 읽은 뒤 진행 이력을1회 저장하고 성공 표시·날짜별 내용을 확인했다. 이 충돌을 모델 재시도나 성능 검증 성공에 포함하지 않는다.

## 한계와 다음 순서

1. Windows nonpaged pool의 큰 점유는 그대로 남는다. 재기동 전 관측은12,650,618,880bytes(약11.8GiB), 가용1,810MiB·PageReads31/s였다. 이전 진단의 가용984~1,557MiB와 달라 호스트 조건이 동일하지 않다. 할당 드라이버·누수·각 원인 기여율은 미확인이다. 다른 프로세스 종료·캐시 삭제·드라이버 변경·재부팅은 하지 않았다.

   종료 직전 추가 표본은 nonpaged12,678,938,624bytes·가용963MiB·PageReads130/s였다. 짧은 표본으로 지속 누수나 원인 기여율을 확정하지 않는다. API 오류 로그0·본래 frontend 프로세스 유지·독립 검증한8소스의 후속 변경0도 확인했다.
2. 준비 조회의 전체 해시와 Codex 별도 서비스/정책 조회 비용은 남는다. 다음은 보안 계약을 유지하는 추가 조회 축소 및 프론트 중복 setup-options 요청의 실효 비용 검토다. 이번 범위에서 frontend 코드를 변경하지 않았다.
3. 새 실제 답변 품질 평가나 모델 생성 속도 비교는 하지 않았다. 모델·프롬프트·인용 판정과 저장 결과가 유지된다는 증거이며 기존 Gemma 의미 품질 문제를 해결했다고 주장하지 않는다.

## 증거

`.local-data/project-agent-work/backend-response-20261031/`: 보존 preimages, `probe.py`, `service-before/after.json`, `service-comparison.json`, `health-before/after-refresh.json`, `http-comparison.json`, `db_pool_probe.py`, `db-pool-integration.json`, `database-before/after.json`, `database-verification.json`, `runtime-smoke.json`, `integrity-report.txt`, `review-result.md`, `review-focused.txt`와 소스 보존 해시. 비밀값·계정·비공개 본문·SQL 매개변수는 증거에 출력하지 않았다.

역할: root가 경계 설계·DB lifespan 구현·본래 실측·문서 통합, backend 담당이 무결성 offload, DB/backend 담당이 조회 일괄화, 독립 담당이 보안·통합·코드 리뷰를 맡았다. UI/AI 모델 튜닝은 동작 변경 범위가 아니므로 제외했다. commit/push/worktree 생성·삭제는 하지 않았다.
