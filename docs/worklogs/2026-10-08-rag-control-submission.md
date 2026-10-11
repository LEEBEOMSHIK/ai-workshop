# RAG 제어 제출 이력 기록과 남은 기능 작업

- 날짜: 2026-10-08
- 문제: ISSUE-00013, 실제 별칭 복구는 open 유지
- 범위: 승인된 [접근 전환 계획 Task4](../superpowers/plans/2026-10-01-rag-access-epoch.md)의 recording-only journal
- 계약: [ADR-0033](../decisions/0033-rag-access-epoch.md#2026-10-08-제출-이력-기록-경계)
- 본래 저장소·공식 Python 가상환경 유지, 새 DB·계정·애플리케이션 환경 없음

## 이번 구현

RAG에 `access_epoch_submission.py`를 추가하고 Windows 잠금에 읽기 전용 scope digest를
제공했다. 기존 Infrastructure의 DPAPI·owner ACL private-file 포트를 주입하며, 업무 action과
상태 전이는 Labs/RAG에 둔다. 실제 launcher나 command callback을 제공하지 않는다.

새 recording session이 발급한 nonce를 expected payload에 포함한다. 발급한 ticket 객체,
execution/generation, kind/순서, expected 내용과 실제 보유한 잠금 scope를 정확히 대조한다.
begin은 ticket을 validation/I/O 전에 한 번만 소비하고 intent를 보호 저장한 뒤 exact readback을
요구한다. 오래된 pending에 새 ticket을 붙일 수 없고 파일 부재를 never-submitted로 해석하지 않는다.

기록 단계는 intent → process_created → process_finished 또는 unknown이다.
PID·생성 시각·Job UUID가 다른 종료 결과, 역행·unknown 이후 전이, 새 session의 과거 기록
append, 복사한 record/ticket을 거부한다. 응답 유실 때 저장된 기록은 읽을 수 있지만 해당 호출의
append 권한을 되살리거나 같은 ticket으로 기록을 재시도하지 않는다. argv·output·비밀값은 저장하지 않는다.

process_finished와 exit 0은 local child 관찰 기록이다. daemon 작업 정산·과거 제어 종료·
DB reservation commit·실제 command submission의 증거가 아니다. 다음 native adapter는
정확한 DB 예약 및 실제 suspended child/Job 등록·resume·daemon 결과를 함께 연결해야 한다.

## 검증과 발견한 경계

모듈 부재의 collection error 1건을 확인한 뒤 초기 20개가 통과했다. 추가 테스트와 독립 리뷰에서
다음 경계를 재현하고 수정했다.

- unknown의 도달 불가능한 revision/child 조합: 3 RED → intent 이후 revision 2/child 없음,
  created 이후 revision 3/child 있음만 허용.
- nonce/digest만 맞지만 expected의 version/scope/target/순서/execution/kind가 잘못된 경우:
  6 RED → closed fields·canonical JSON·정확한 type/value 및 target digest 검증.
- generation의 str subclass를 값만 비교해 저장하던 경우: 1 RED → 저장 전 exact type 거부.
- protection 포트가 반환하면서 소유권을 바꾸는 경우: 1 RED → protect와 file write 사이 검사,
  저장 1회에서 0회로 변경. 실제 OS takeover 증거가 아닌 injected-port 경계 검증이다.

| 최종 확인 | 결과 |
| --- | --- |
| Infrastructure local + RAG indexing 단위 회귀 | 558 passed, 기존 경고 1, 34.46초, exit 0 |
| Ruff, 새 journal·잠금·test | 3파일 통과 |
| Mypy, journal·잠금 | 2 source 통과 |
| 독립 코드·보안 리뷰 | bounded recording 범위의 차단 finding 없음 |
| 독립 journal + mutex fake 회귀 | 68 passed, 0.44초, exit 0 |
| 프로젝트 역할 계약·문서/AST/동결 내용 검사 | 마감 때 실제 결과 확인, WORKBOARD에 기록 |

주 회귀는 backend cwd의 기존 `.venv/Scripts/python.exe -B` child에서만 AI_WORKSHOP 환경값을
제거하고 `pytest -c pyproject.toml tests/unit/infrastructure/local tests/unit/labs/rag/indexing
-q --tb=short <작업별 basetemp>`로 실행했다. 부모·서비스 환경은 변경하지 않았다.
경고는 기존 Starlette TestClient/httpx deprecation이며 의존성 변경은 없다.

독립 리뷰는 실제 journal 코드와 fake private/kernel 포트로 created/finished 저장 ACK 유실 및
created 저장 후 소유권 상실을 추가 확인했다. 읽기 상태는 보존되며 재호출 추가 write는 0이었다.
이번 작업은 실제 DPAPI 파일의 전원 상실·namespace commit 내구성·anti-rollback 시험이 아니다.
기존 fsync/replace/ACL 및 fake roundtrip을 완성된 native durable journal로 보고하지 않는다.

## 품질 개선을 제외한 남은 작업량

2026-10-08의 WORKBOARD, 승인 계획 Task1–6, 실제 source/test/CLI 및 최신 실행 기록을
독립 대조했다. **7개 기능 작업 묶음이 남아 있으며 이번 구현은 1번의 일부다.**
규모는 의존 범위에 대한 상대 분류이고 날짜·진척률·작업 횟수의 약속이 아니다.

| 남은 묶음 | 규모 | 완료 기준 |
| --- | --- | --- |
| 1. 실제 고정 명령 제출·실행 이력 | 큼 | DB 예약과 보호 journal 연결, 같은 owner thread의 suspended child/Job·resume·결과, 불명확한 제출 재발행 차단 |
| 2. 과거 제어 종료/차단과 보안 서버 전환 | 가장 큼·범위 미확정 | 무계측 과거 구간의 authoritative settlement 또는 검토된 fencing, TLS/인증·전체 route·원래 volume 보존·secured forward repair |
| 3. 별칭 복구·대기 첨부 색인 | 큼 | exact receipt/release, 현재 DB truth의 새 parity, 기존 queued 1의 정상 파싱·청킹·임베딩·색인 READY 및 권한 있는 원문 검색 |
| 4. 첫 질문·권한/취소 동시 실행 검증 | 중간 | 본래 첫 POST201에서 정확히 한 세션 생성, committed 다중 연결 경합·현재 권한/근거 승인 변경의 안전한 처리 |
| 5. 실제 모델 실패·timeout·취소 처리 | 중간~큼 | 실제 deadline/취소/자식 종료, 안전 실패·cleanup·측정값 저장과 대화/모니터링/비교 화면 복원, 과거 미확인 종료의 별도 처리 |
| 6. Windows DLL 재발 방지 | 중간·원인/정책 의존 | 승인된 보안 정책 안에서 같은 공식 Python의 import·검색·재시작 경로를 반복 검증하고 재발 원인을 해결 |
| 7. main/원격 및 실행 인계 | 중간·선행 작업 의존 | 현재 관련 WIP의 선별 커밋·통합·원격 반영, 본래 실행 검증과 worktree/산출물 인계 조건 충족 |

주 의존 순서는 1 → 2 → 3이다. 4–6은 별도의 보존·검증 범위를 준비해 함께 진행할 수 있고,
7은 통합 마감에 해당한다. 실제 첨부 저장/인증 모바일·기존 대화 후속/원문 인용/새로고침·
생성 준비는 이미 확인한 범위로 분리했다. 과거 로그인 대기 기록을 현재 미완료로 다시 계산하지 않았다.

가장 큰 일정 불확실성은 2번이다. 과거 complete history 원천이 없고 기존 IDE/Codex/frontend
보존 조건을 유지한다. 새 잠금·새 journal·PID/TCP 부재나 단순 PC/Docker 재시작 성공으로
그 공백을 채울 수 없다. 실제 종료/fencing의 운영·설계 범위를 정하기 전에는 전체 기간과
신뢰할 만한 완료 비율을 산정할 수 없다. “한두 번 더 작업하면 완료”로 약속하지 않는다.

답변 유보·일반화·정답률·지연·구성 승격 같은 지속적인 품질 개선과 SDK, 벡터 저장소 비교,
로컬 LLM 및 Kubernetes 후속은 위 7묶음에서 제외했다. 아직 **품질 개선만 남은 상태가 아니다**.

## 본래 환경과 이력

독립 담당은 기록 전 보호83테이블의 fresh compact count/digest 기준선과 기존20개 동결보고서
exact version을 확보했다. ISSUE-00013 open revision22, gate frozen1/receipt0·alias open1·epoch4테이블0,
개인 Asset READY·RAG queued1·active32/pending128·5대화23턴/선택4와 원본·환경·runner·서버를 보존했다.

기존 owner의 정상 관리 API로 이 문서 exact v1과 진행 사건·연결만 추가한다. 기존 status·remaining·
업무필드·사건·문서 버전은 덮어쓰지 않는다. 새 문서 ID/SHA와 등록 후 독립 보존 결과는
WORKBOARD에 별도로 기록한다. 동결 본문은 사후 갱신하지 않는다.

원래 DB/schema/gate/credentials·OS 잠금/제어·Docker·서버·provider/model·실제 색인·staging/commit/push
변경은 없다. 이번 추가는 recording source/test/문서와 정상 문제 이력이며 실제 native 제출은 없다.
다음은 DB 예약/이력의 확정 연결 및 suspended child/Job 실행 경계다. 과거 종료/fencing 설계와
실제 복구·release·parity·색인 검증의 미완료 상태를 유지한다.
