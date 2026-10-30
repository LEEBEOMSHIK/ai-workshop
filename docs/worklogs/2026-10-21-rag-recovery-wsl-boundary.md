# RAG 복구 계속 진행: WSL 경로와 v2 인증 응답 검증

사용자가 과거 취소·별칭·기존 첨부의 복구를 먼저 진행하도록 요청해 [직전 결과](2026-10-21-rag-recovery-followup.md)를 이어 확인했다. **Docker 경로 인식 결함 수정과 v2 인증 응답 검증 분리는 완료했지만 세 운영 복구는 여전히 미완료다.** 이전 관리자 등록 문서 버전1은 수정하지 않았다.

## 실제 상태와 실행 범위

2026-10-21 21:57·22:15·22:32 KST의 본래 DB 읽기 전용 관찰에서 다음 상태가 유지됐다.

| 대상 | 상태 | 완료에 필요한 것 |
|---|---|---|
| 과거 취소 turn `bc10a519-62b6-4adf-8dac-de1a58011139` | cancelled, execution_terminated=false, 대화 revision3 | 정확한 실행·자식 종료 근거와 이를 소비하는 정식 복구 경로 |
| 별칭 operation `f61a8fde-5a88-4690-be51-56e8f14ae696` | open/legacy_unknown, gate frozen/revision1, receipt0 | 지원되는 통제 경로의 실제 종료 확인·receipt·release·새 parity |
| 기존 첨부 job `d642f913-287f-4f45-944f-aa6b9f2d710e` | queued/attempt0, dispatch pending/attempt0, projection pending | 별칭 복구 뒤 해당 작업만 처리하고 검색·원문 접근 확인 |

생성 감사는 세 관찰 모두496건이다. 업무23테이블의 행 수와 fingerprint가 모두 같고, 기존 변경35파일의 SHA도 보존했다. 기존 수정 파일 중 WORKBOARD와 로컬 실행서는 이번 결과를 추가했다. 추가 생성·임베딩, 일반 큐 worker 기동, 프로세스 종료, 서비스 재시작, 인증·보안 설정·DB 업무 상태 변경은 수행하지 않았다.

## Docker bootstrap 경로 인식 수정

기존 분류기는 `C:/Program Files/Docker/Docker/resources/` 아래의 두 ISO 경로를 예상했다. 실제 서명·해시 검증을 통과한 Docker WSL bootstrap은 다음 인자를 전달했다.

- `/c/Program Files/Docker/Docker/resources/docker-desktop.iso`
- `/c/Program Files/Docker/Docker/resources/wsl/docker-wsl-cli.iso`

읽기 전용 관찰로 두 인자의 정확한 대소문자와 System32 launcher→WSL runtime 인자 전체 일치를 확인했다. 호출 수·순서·다른 옵션은 기존 bootstrap 문법과 같았고 vpnkit 명령은 기존 검사에 통과했다.

`alias_recovery_local_wsl.py`의 `_launcher`만 보완했다. 기존 Windows 쌍을 보존하고 위 POSIX 두 문자열의 정확한 쌍을 별도 문법으로 지원한다. POSIX 경로에는 소문자 변환·역슬래시 변환·일반 경로 정규화를 적용하지 않는다. binary pin·서명·SCM·부모·distro·VM·수명 검사는 그대로다. 이는 두 표기가 물리적으로 같은 파일이라는 증명이나 임의 WSL 허용이 아니다.

단위 fixture는 합성 process/distro/VM 식별자를 사용했다. 실제 PID·사용자·질문·명령 원문은 fixture에 복사하지 않았다.

## 수정 뒤 실제 사전검사

같은 operation/actor의 정상 `preflight`를 실행했다. 결과는 여전히 `blocked/wsl_infrastructure_unverified`, `termination_proven=false`, `parity=not_run`이다. operation snapshot SHA도 기존 `4c381f1adf7c93ad08c043eb405f8dd7b546bca356dd6f7db827f3c6c8fe8c36`을 유지했다.

변경하지 않은 전체 분류기의 실패 위치를 좁힌 결과, bootstrap·부모·distro·VM 검사를 지나 마지막 `allowed != set(by_pid)`에서 거부됐다. 미분류 프로세스는 **`com.docker.build.exe` 1개**였다. 부모·시각 관계는 Docker backend와 연결되지만 이것만으로 늦은 쓰기 불능이나 종료를 증명하지 않는다. 임의 예외나 종료 명령은 추가하지 않았다.

v1은 그 이후에도 등록되지 않은 Python/Node 등의 client 부재를 요구한다. 따라서 현재 IDE/Codex를 보존하면서 전체 v1 조건을 충족했다고 보고할 수 없다. 현재 Docker 실행 자체가 장애라는 판정도 아니다.

## 과거 취소의 새 역사 근거와 결손

기존 로컬 API 로그와 당시 실행 이력에서 다음 연결을 추가 확인했다.

1. 대상 request ID와 대화의 취소 POST 200이 당시 API 로그에 있다. 현재 DB의 turn/execution FK와 대조했다.
2. 당시 API와 부모 launcher의 PID·생성시각 기록이 있다.
3. 같은 API PID·포트·실행경로·인자를 검사하고 중지한 과거 명령의 exit0 기록을 찾았다. 바로 앞의 실패 시도는 exit1로 분리했다.
4. 당시 예외 스택은 `run_until_disconnect`가 소유 coroutine과 watcher를 join한 뒤 `CancelledError`를 올린 경로다. 다만 스택에 exact request/turn/execution 식별자는 없다.

중지 직전의 생성시각 재대조, 중지 후 실제 종료 대기, 전체 자식/Job accounting은 해당 기록에 없다. 당시 conversation의 unshielded cleanup 경합 때문에 소유 coroutine join을 하위 executor와 모든 자식의 종료로 확대할 수도 없다. Codex 생성이 실제 시작됐는지 역시 미확정이다.

따라서 **“과거 자료가 전혀 없다”는 설명은 부정확하지만, 현재 찾은 자료로 실행 종료 플래그를 바꿀 수는 없다.** 현재 PID 부재·시간 경과·최근 Gemma 실행·합성 테스트로 결손을 대체하지 않았다. 정식 종료 증거 생산/소비 계약은 [기존 취소 복구 초안](../superpowers/specs/2026-10-11-rag-cancelled-turn-recovery-draft.md) 범위에서 따로 완성해야 한다.

## v2 인증 응답 검증 분리

[승인된 access epoch 계획](../superpowers/plans/2026-10-01-rag-access-epoch.md)의 native 구현을 이어 `access_epoch_auth_packets.py`를 추가했다. 기존 `FinalAuthCommands`에서 고정 권한 질의와 응답 해석만 순수 함수로 분리했다. 실제 실행·관측·발급 권한을 만드는 구성요소는 아니다.

- reader/writer/collector의 유한 권한 질의, 명시적 `.security`와 외부 namespace 검사, `allow_restricted_indices=false`를 유지한다. 임의 role descriptor는 받지 않는다.
- 공개 key ID/name·API key 형식·enabled와 두 realm의 정확한 형태·비어 있지 않은 문자열·동등성을 검사한다. 기존 계약에 없던 realm literal은 추가하지 않았다.
- 중복 JSON 키, 비정상 UTF-8, 비유한 숫자, 누락·추가 필드와 boolean 강제변환을 거부한다. 기존 파서가 `1e400`/`-1e400`을 무한대로 받아들이던 재현2건도 수정했다.
- 순수 body 한도는262144바이트다. 기존 active 실행은 HTTP 상태4바이트를 포함한 전체 wire262144바이트 한도를 그대로 지킨다.
- 반환은 새 일반 질의/예상 데이터 또는 `None`뿐이다. 비공개 응답 metadata는 반환하지 않고 오류도 고정 코드다. 호출부의 issuer·guard·일회성 명령·발급 객체 집합·공개 manifest 구성을 유지했다.

새 helper를 통과했다고 과거 실행 종료나 현재 서버 관측이 증명되지는 않는다. 향후 committed observer는 실제 phase/material의 출처와 최신성을 별도로 확인해야 한다. native 최종 검증기·backend/factory·CLI 지원·schema는 이번에 활성화하지 않았다.

## 검증

- 테스트 작성 중 문자열 구문·예외 진단 assertion 오류를 수정했다. 제품 변경 전 정상 RED는 새 POSIX 양성1 FAIL/나머지31 PASS였고, 변경 후32 PASS다.
- 관련5파일을 한 번에 실행: **308 PASS, 17.09초**, skip/failure0. 단위·합성 native 검증이며 운영 복구 통과가 아니다.
- 독립 실행: WSL 분류32 PASS, 0.12초. 독립 코드·보안 리뷰 차단0.
- 변경 Python1파일 mypy 통과, 제품/테스트2파일 Ruff·format 통과. 전체 저장소 검사로 확대하지 않는다.
- 인증 분리 RED: 신규 모듈 부재3건과 기존 overflow 허용2건. 최초 실행의 대용량 pytest parameter ID 때문에 발생한 fixture 설정 오류2건은 짧은 ID로 수정했다. 최종 직접 관련145 PASS, 호출부를 포함한6파일 **241 PASS, 3.62초**, 독립145 PASS, 0.89초다.
- 인증 독립 리뷰의 제품 차단 결함0. wire 한도 테스트가 HTTP 상태까지 바꾸던 검증 결함1건은 정상 상태를 유지하고 body만1바이트 늘리도록 고쳤다. 최종241개 실행에 포함했다.
- 인증 제품2파일 mypy, 제품/테스트4파일 Ruff·format 통과. HEAD의 변경 전 구현과 현재 구현에 같은 합성 입력을 주어 세 역할의 질의와 공개 manifest가 **바이트 단위로 동일**함을 확인했다.
- 기존 읽기 전용 관찰기를 재사용해 before/after/final23테이블과 기존 변경35파일의 보존을 확인했다. 기존 보고서 SHA도 그대로다.

로컬 최소 진단은 `.local-data/project-agent-work/rag-recovery-boundary-20261021/`에 보존한다. 원시 명령·프로세스 목록·환경·세션 본문은 보고서에 넣지 않았다. 신규 설치·다운로드·재색인·DB 직접 수정·커밋·푸시는 하지 않았다.

## 기록 반영과 다음 실제 작업

로컬 상세 기록과 WORKBOARD를 갱신했다. 관리자 이력을 갱신하려던 기존 Chrome 탭이 로그인 화면으로 전환되어 재로그인을 요청했다. **이번 결과의 관리자 DB 등록은 아직 미완료**이며 이전 등록 문서·연결·문제 상태를 변경하지 않았다. 같은 복구 증상의 후속은 ISSUE-00013/00018에 이어 기록하고, 새로 재현한 비유한 숫자 파서 결함은 별도 원인으로 기록해야 한다.

기존 v1의 허용 프로세스를 늘려 통과시키지 않는다. IDE/Codex를 보존하는 [access epoch 계획](../superpowers/plans/2026-10-01-rag-access-epoch.md)의 다음 구현은 새 관측 source의 고정 Docker5회·HTTPS9회 읽기와 전후 SQL/material 검증, 취소/정리·시간 예산, 실제 native 최종 검증·backend/factory 조립이다. 부분 verifier로 지원 검사를 열지 않는다. 운영 보안 전환은 이 오프라인 구현과 구분해 구체적인 검토 자료가 완성된 후 진행 범위를 확인한다.

과거34요청/67의존성 조사와 이번 WSL 경로 수정은 서로 다른 증거 범위다. 역사 자료의 원본 보호 디렉터리는 OS 권한 거부로 추가 열람하지 못했으며 우회하지 않았다. 미분류 자료를 영구 유실로 단정하지 않는다. 이 사실이 미완성 v2 구성요소의 오프라인 구현 착수를 막는 것은 아니다.

첨부1건은 정확한 receipt readback→release→현재 DB 기준 parity가 검증된 뒤 정상 workflow로 처리한다. SDK 구현으로 넘어간 상태는 아니다. SDK 호환성·설계 준비 가능 범위는 [기존 확인 기록](2026-10-21-rag-agents-sdk-next-step.md)을 유지한다.
