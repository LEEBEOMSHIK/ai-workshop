# 미종료 RAG 별칭 요청 정상 복구

- 문제: ISSUE-00013
- 상태: 구현·독립 검토·본래0061/SAVEPOINT 검증 반영. 실환경 호스트 지원 경계 미충족으로 ISSUE-00013은 open이며 요청은 아직 종료하지 않았다. 원래 서버는 복원했다(2026-10-01 03:57).
- 계약: [ADR-0032](../decisions/0032-rag-alias-recovery.md), [설계](../superpowers/specs/2026-09-30-rag-alias-recovery-design.md), [계획](../superpowers/plans/2026-09-30-rag-alias-recovery.md)

## 확인한 원인과 범위

원장의 예약은 외부 호출 전에 별도 transaction으로 commit된다. 현재 행만으로 전송 전 실패,
전송 후 timeout 또는 종료 commit 오류를 구분할 수 없다. 기존 별도 프로파일의 open 요청1건과
공유 alias admission 충돌이 반복 busy의 직접 원인이다. 정확한 최초 실패 단계는 미확인이다.
활성 E5 도메인·첫 질문 대화의 오류 또는 전체 검색 실패를 의미하지 않는다.

현재 alias target은 기존 요청의 빈 target과 같고 현재 ES는 단일 node다. task 관찰·현상 일치와
기존 client/server의 재시작은 과거 요청이 더 이상 쓰지 못한다는 증거가 아니다. 늦은 client가
새 ES incarnation에 전송했을 수 있어 client 종료 뒤 서버의 실제 종료·교체 순서를 확인해야 한다.

## 변경 전 보존과 역할

본래0060·계정1·공간3·원문7·Asset Version7·구성7, 활성 연결과 이전 첫 질문 미커밋 변경을
보존한다. 새 DB·환경·계정·모델·색인을 만들지 않는다. 아키텍처/DB·운영 조사와 독립
보안/통합 사전 검토를 마쳤고 Python/테스트 구현과 독립 코드 검토를 분리했다.

반영용 원래 DB 백업은 `.local-data/backups/alias-recovery-20260930T145612Z/original.dump`에 저장했다.
0060 guard와 고정 Docker context/daemon/Postgres container, SQL listener와 container의
PostgreSQL system identity 일치를 확인했다. custom archive13,888,405bytes, SHA256
`aa2fb0065e4a29580ce7ea40fd0fc846e976a4b93e4eee38886e9dc6ab4fb09d`,
pg_restore list907행 확인. 앞선 이름 기반 백업은 보존하되 반영용 근거로 사용하지 않는다.
백업 복원을 실행하지 않았으며 restore 성공을 입증한 것은 아니다.
임시 증거는 승인된 로컬 작업 폴더에 보존하고 비밀값·본문·command line은 기록하지 않는다.

## 구현과 검증 경계

원장 phase·cluster gate·atomic receipt와 exact 복구 서비스 구현은 독립 검토를 통과했다.
trusted local collector/CLI도 구현했으며, 최종 검토의 표시 오류 수정 후 writer drain·0061 migration·본래 rollback 검증을
수행했다. 종료 근거가 충족될 때만 legacy 요청을 `recovered_terminated`로 닫는다.
원래 요청의 성공 여부는 미확인으로 보존하고 현재 DB 기준 새 정상 parity의 성공을 별도로 확인한다.

trusted Windows/local/direct-loopback/single-node의 과거 endpoint 및 전체 client 통제 전제는
자동 process polling만으로 입증할 수 없다. 미확인 writer/topology/history가 있으면 차단을 유지한다.
구현 fake 테스트, rollback SQL 검증과 실제 runtime 증거를 구분하며 아직 제품 완료로 보고하지 않는다.

## 중간 검사 기록

Task1 전체 offline 단위는 실행서의 합성 키와 짧은 새 작업 임시 경로에서3,074passed·6skipped·
기존 warning1건으로 종료했다. 최초 실행의55실패는49건 시스템 Temp의 저장 실패와6건 합성 키
누락으로 분류됐다. 키/작업 경로를 반영한 다음 실행에서 기존55건은 해소됐고 긴 경로의
Windows MAX_PATH 때문에 업로드8건이 실패했다. 새 짧은 작업 경로에서 모두 통과했다.
실제 서버 secret이나 계정·객체 저장소를 바꾸지 않았고 이전 실패 임시 기록은 보존했다.

이후 canonical profile/processing alias·target 검증의 누락을 발견해 실패 회귀를 먼저 추가하고
보완했다. 해당 수정까지 indexing 단위159건, src mypy377파일과 scoped Ruff를 통과했다.
독립 리뷰가 reserved phase에서 실제 종료 collector를 먼저 호출하는 문제를 발견해, 원장 phase를
검사한 뒤 외부 작업을 시작하도록 고쳤다. 실패 회귀 후 indexing 단위160건을 통과했고 독립
재검토에서 spec·quality 승인을 받았다. 위 전체 단위 결과만으로 이 후속 수정이 검증됐다고
주장하지 않는다. 최종 전체 단위는 collector 통합 뒤 실행한다. 단위 fake
proof·offline migration SQL 출력·harness collect-only는 실제0061/ES 종료를 입증하지 않는다.
로컬 collector·CLI의 독립 검토와 원래 환경 검증이 남아 있다.

로컬 collector/CLI 구현 후 indexing 단위238건, scoped Ruff8파일과 src mypy381파일을
통과했다. 독립 리뷰는 새 Windows 프로세스의 실제 CLI가 기본 Proactor 루프를 사용해
psycopg 연결 전에 거부되는 문제를 재현했다. 기존 pytest의 selector 사전 설정이 이를
가렸다. DB·네트워크 없는 fresh-process 회귀를 먼저 추가하고 공유 Selector 설정을 진입점에
적용했다. 해당 수정은 독립 재검토를 통과했고 indexing241건을 통과했다.

통합 전체 단위는3,161passed·6skipped·기존 Starlette warning1건(172.83초), 18개 파일 Ruff와
전체 src381파일 mypy를 통과했다. mypy의 최초 `--cache-dir=NUL`은 설치 버전의 대소문자
처리 때문에 내부 오류가 났고, 공식 문서와 설치 소스를 확인해 `--cache-dir=nul`로 재실행했다.
의존성이나 캐시를 변경·삭제하지 않았다.

최종 전체 독립 검토에서는 종료·해제된 요청의 freeze 재접수를 새 차단처럼 표시하는 오류를
재현했다. 과거 receipt와 현재 gate 권한을 구분하고 freeze 이후 확정 readback을 추가했다.
RED6실패→GREEN15통과, indexing247건·좁은 Ruff/mypy 통과와 메인의 CLI15건 직접 실행을
확인했다. 두 파일 수정의 독립 재검토는 승인됐다. 전체3,161건 검사는 이 후속 변경 이전의
결과이며 이후 변경은 위 좁은 검사로 검증했다.

본래 반영 첫 StopBeat는 커널 생성 시각(100ns)과 CIM 생성 시각(µs)의 정밀도 차이로 종료 전
거부됐다. 같은 µs에 속하는 값을 정확히 비교하는 운영 helper 보완·9개 경계 검사와 독립
승인 후 실행했다. child 종료 직후 launcher 자체 종료와 CIM 반영 사이의 일시적 조회 차이는
재확인으로 실제 부재를 확정했다. API·worker·beat6개 프로세스는 종료했고 프론트는 유지했다.

본래0061 migration을 실제 반영한 뒤 exact revision과 보호 정보7개 유지, 기존 요청의
`legacy_unknown/open`을 확인했다. 외부 COMMIT을 금지한 원본 SAVEPOINT3건은1.62초에
통과했다(anyio 사전 import 경고1건). 테스트 후 gate0·receipt0이며 기존 상태를 보존했다.
원문7개 파일도 DB의 크기·SHA256과 모두 일치한다. 이 검사는 실제 다중 연결 commit 경합이나
물리적 commit 응답 유실을 입증하지 않는다.

실제 CLI preview는 복구 전 환경 설정 단계에서 거부됐다. `.env`의 JSON 모델 등록 설정을
문자열 init 인자로 전달해 일반 Settings source의 구조화 값 처리를 건너뛴 것이 원인이다.
원래 서버의 Settings 로더는 같은 파일에서 정상이다. 환경 파일을 바꾸지 않고 고정된 원래
`.env`에 정본 로더를 사용하는 좁은 수정과 CLI26건 검사를 마쳤고 독립 승인했다. 수정된 CLI가
원본 snapshot을 조회하고 동일 durable request의 frozen revision1을 확정했다.

첫 종료 근거 수집은 ES의 nodes metric만 요청하면서 별도 master_node metric의 응답을
요구해 `cluster_node_changed`로 거부됐다. 실제 응답 키를 대조해 잘못된 요청을 확인했으며
ES 컨테이너는 기존 시작 시각·cluster/node/ephemeral을 유지했다. 이는 ES 교체가 아니다.
[공식 cluster state API](https://www.elastic.co/docs/api/doc/elasticsearch/v9/operation/operation-cluster-state)의
명시 metric을 사용하는 좁은 수정·회귀·독립 검토를 통과했다(native/CLI73건, 좁은 Ruff/mypy).
요청은 open/frozen으로 유지하며 실제 ES stop/start·요청 종료·새 정상 parity는 미실행이다.

다음 실제 수집은 Windows PowerShell5.1의 `Get-AuthenticodeSignature` module autoload 실패로
ES stop 전에 거부됐다. 해당 정책의 정확한 원인은 확정하지 않았다. 기존 설치된 공식 서명
PowerShell7.6.6 ARM64의 정확한 실행 파일·SHA256·호출 payload를 고정한 helper를 구현했다.
PATH fallback·설치·보안 정책 변경은 하지 않았다. RED12→관련85건 통과, 좁은 Ruff/mypy와
독립 검토 승인 후 실제 WSL_STATE 명령은 정상 반환했다.

## 실제 호스트 차단과 서버 복원

공식 helper의 HOST 명령은45초 제한을 초과했다. 읽기 전용 단계 측정에서 CIM466개 process
조회는863ms, TCP269개 조회는1,866ms였다. Node마다 서명·해시 조회는 약1.7–2.1초,
Docker backend는3.1–3.3초였다. Node21개가 두 실행 파일을 공유하며 Docker build까지 포함한
대상22개는 세 실행 파일이다. 반복 조회 비용은 확인했으나 timeout 제거만으로 복구가
가능하다고 결론내리지 않는다. 같은 호출 안의 안전한 중복 조회 제거는 후속 설계 대상이다.

실제 Node에는 유지한 frontend 두 process 외에 frontend PostCSS 빌드 child, IDE server,
Codex CUA/MCP/kernel/worker/CLI와 부모가 이미 종료된 server가 있었다. Docker build process도
존재했다. 현재 collector는 exact frontend pair·수집기/controller와 검증된 Docker backend/WSL
외의 Node 및 Docker process를 허용하지 않는다. 서명·브랜드·부모 또는 현재 TCP 부재만으로
과거/지연 writer가 아님을 입증할 수 없다. 따라서 일괄 예외나 관련 없는 앱 종료를 수행하지
않았다. 독립 경계 검토도 차단 유지와 기존 서버 복원이 타당하다고 판정했다.

같은 operation/request의 확정 readback은 `legacy_unknown/open`, 결과null,
`matching_frozen_claim/revision1`, receipt0, parity `not_run`이다. ES는 동일 컨테이너의
2026-09-29T01:02:21.718672132Z 실행을 유지했다. 어떤 ES stop/start·과거 target 재전송·강제
종료·gate 해제·새 정상 parity도 실행하지 않았다. 이 gate는 **클러스터 전체의 새 alias
예약·전송**을 차단한다. 활성 E5의 기존 색인을 삭제하거나 검색 결과를 변경하지 않았지만,
이번 작업에서 모델 답변을 새로 호출해 검증하지는 않았다.

2026-10-01 03:54 원래 `.env`로 API·worker·beat를 숨김 재시작했다. 03:57 확인한 실제
API84504/launcher84536, worker81816/61944, beat4276/22992, frontend22660/45592다.
frontend 생성 시각·listener는 유지했다. API18000·frontend5173 경유 health200,
worker ready·beat starting을 확인하고 프로세스 registry를 갱신했다. worker의
`reconcile_asset_handoffs`는 `RagAliasParityRunError`를 기록했다. 이는 별칭 정합성이 아직
복구되지 않았음을 보여주며 서버 기동 성공으로 숨기지 않는다. 재시작 후 보호 정보7개와
원문7개 크기·해시도 모두 유지됐다. 새 환경·DB·계정이나 파일 정리는 없었다.

## 남은 기능 작업

다음은 반복 수집 수정이 아니라 **실제 개발 호스트에서 가능한 종료 증거의 지원 경계와
freeze 전 사전 검사 재설계**다. 비쓰기 tool/IDE/build process를 식별할 충분한 근거 또는
기존 endpoint의 지연 writer를 차단하는 검증 가능한 대안을 정해야 한다. 현재 프로세스
이름에 예외를 붙이거나 관련 없는 앱을 종료하는 방식으로 대신하지 않는다. 설계·독립
보안/운영 검토 이후 같은 exact request에서 실제 proof·receipt·해제·새 정상 parity를
각각 확인한다. 그 전 ISSUE-00013은 open이며 복구 완료나 새 색인 정상화를 주장하지 않는다.
그 다음 기능 순서는 새 모델 실패 저장 E2E와 최신/누적 실행 이력 검증이며 품질 개선은
별도로 지속한다. 이번 변경은 이전 첫 질문 변경과 함께 미커밋 상태로 보존했다.
