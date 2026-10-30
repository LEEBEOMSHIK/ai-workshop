# RAG 복구 후속과 PowerShell 실행 파일 고정값 보수

2026-10-21 사용자 요청의 ① 과거 취소 복구 ② 별칭 잠금 복구 ③ 기존 첨부 색인 완료를 대상으로 본래 상태와 정상 실행 경로를 확인했다. SDK 후속 순서는 [별도 확인 기록](2026-10-21-rag-agents-sdk-next-step.md)에 정리했다. **복구 세 항목은 아직 완료되지 않았다.**

## 본래 상태

기존 설정의 `ai_workshop_local_clean` DB를 READ ONLY·repeatable read·10초 statement timeout으로 조회한 뒤 rollback했다. 질문·응답·문서 본문이나 인증값을 출력하지 않았다. schema는 `0066_generative_pending_cancel`이다.

| 대상 | 이번 확인값 | 판정 |
|---|---|---|
| 과거 취소 | turn `bc10a519-62b6-4adf-8dac-de1a58011139`, cancelled·execution_terminated=false, 대화 revision3 | 종료 근거와 복구 경로 필요 |
| 연결 관측 | execution `146c3bc3-5567-4316-ad70-85b089667430`, cancelled·complete=false, 연결 생성 감사0 | 감사0은 생성 미기동/종료 증거가 아님 |
| 별칭 | operation `f61a8fde-5a88-4690-be51-56e8f14ae696`, open·legacy_unknown | 기존 요청 유지 |
| 별칭 gate | frozen·revision1, 기존 request `09e0ee10-b5ac-4ace-a053-deafb20ec4ef`, receipt0 | 해제 조건 미충족 |
| 개인 첨부 | job `d642f913-287f-4f45-944f-aa6b9f2d710e`, queued·attempt0, dispatch pending·attempt0 | 아직 실행하지 않음 |
| 첨부 자산/색인 | active Asset version ready, projection `99afcb4b-46e4-436f-931c-35ba7e6e4b84` pending, 파싱·청크·임베딩·색인 개수 미기록 | 저장 완료와 RAG 준비 완료를 구분 |

전체 projection은 ready6/pending1/failed1이다. 현재 running turn/execution/job은0이지만 과거 요청의 실제 종료를 증명하지 않는다. API health/ready 정상도 별칭 복구나 색인 완료를 뜻하지 않는다.

## 1. 과거 취소 복구

현재 코드의 정상 종료 생산자는 살아 있는 동일 실행의 finalizer다. 실제 task join과 종료 확인 뒤 turn을 저장한다. 과거 cancelled/false에 대한 복구 API와 영속 종료 증거 소비 경로는 없다. 삭제 tombstone용 `record_termination`을 활성 대화에 재사용할 수 없다.

[당시 기록](2026-10-05-rag-browser-closure.md)도 정확한 과거 취소 타이밍과 종료를 입증하지 못했다고 명시한다. 생성이 시작됐는지도 미확정이므로 Codex 프로세스 종료만 확인하면 된다고 좁히지 않는다. 필요한 출발점은 해당 API/search task와 실제 생성된 자식의 정확한 수명 결합이다.

현재 슬롯·프로세스 부재, 시간 경과, 최근 Gemma 성공을 과거 종료 증거로 사용하지 않았다. [기존 복구 초안](../superpowers/specs/2026-10-11-rag-cancelled-turn-recovery-draft.md)의 증거 생산·영속화 계약을 먼저 구체화해야 하며, 소비 API만 추가해도 이 과거 건이 복구되지는 않는다. 원래 증거를 확보하지 못한 경우는 미확정으로 유지한다.

## 2. 별칭 사전 검사와 보수

v1 이력의 고정 세 파일 SHA는 기존 계약과 일치했다. 이는 v2 과거34요청/67의존성 source-map 문제와 별개다. v1 정상 사전 검사로 현재 지원 조건을 확인했다.

1. 일반 sandbox의 정상 preflight: `blocked/local_command_failed`. 정확한 첫 Docker context 읽기 명령은 exit1·access_denied=true였다.
2. 승인 검토를 거친 sandbox 밖의 동일 읽기 전용 preflight: `powershell_binary_unverified`. 코드가 고정한 PowerShell7.6.6 파일은 없고 설치 패키지는7.6.7이었다.
3. 이미 설치된7.6.7의 정확한 파일을 실측했다. Microsoft 서명 `Valid`, SHA-256 `b444dbe54328db2a42e7156d8394e4164900ebaace0f2544cbb05f437247dfe6`, 파일과 모든 상위 경로 reparse 없음이었다.
4. 현재 helper/controller 경로와 SHA 두 상수, 관련 기존 회귀, 정본 실행서만 갱신했다. 자동 버전 탐색·fallback·검증 예외는 추가하지 않았다. `access_epoch_original_apps.py`의 과거7.6.6 supervisor identity는 보존했다.
5. 수정 후 정상 v1 preflight는 PowerShell 검증을 지나 `wsl_infrastructure_unverified`로 거부됐다. `termination_proven=false`, `parity=not_run`, 동일 snapshot SHA를 유지했다. 이 코드는 여러 WSL/Docker 실행 관계 조건을 포함하므로 결과만으로 특정 바이너리 변경이나 장애를 단정하지 않는다.

후속 최소 진단은 고정 WSL_STATE/HOST 읽기를 메모리에서만 받아 변경하지 않은 `classify_infrastructure`를 한 번 실행했다. 최초 거부는 `classify_infrastructure:277 → _launcher:183`으로, 관찰된 WSL 실행 인자가 기존 두 Docker launcher 패턴과 일치하지 않았다. 그 앞의 WSL service 경로·SHA·서명·발급자 검사는 일치했다. 원시 명령·환경값·프로세스 전체를 저장하지 않았으며, 이 결과로 다른 WSL 작업을 종료하거나 새 실행 인자를 임의 허용하지 않는다. 다른 후속 검사는 아직 통과하지 않았다.

새 pin의 채택 전 서명·전체 경로 검증과 실행 시 검증 범위는 다르다. 현재 런타임은 exact path·파일 존재·leaf symlink·SHA를 확인한다. 매 실행마다 전체 서명/ancestor 검사를 한다고 보고하지 않는다.

v2는 이미 구현된 READ ONLY·보호 읽기·source/TLS 부품을 반복 구현할 대상이 아니다. 실제 final observer/backend/factory 연결과 과거 제어 정산·보안 전환이 남아 있다. `access_epoch_verification_native.NativeFinalVerification` 운영 모듈도 아직 없다. 운영 승인을 추가로 받기만 하면 바로 복구할 수 있는 상태가 아니다.

## 3. 기존 첨부 한 건

기존 job/projection/Asset의 정확한 연결과 대기 상태를 확인했다. 별칭 gate가 클러스터 전체를 차단하므로 이 첨부의 profile이 열린 operation의 profile과 다르더라도 바로 실행하지 않는다.

정상 순서는 동일 claim의 종료 receipt readback → exact release → 해당 profile의 `SqlAlchemyRagAliasParityReconciler.run_once(profile_id=...)` → 이미 저장된 job 한 건의 `create_rag_ingestion_workflow(settings).run(exact_job)`이다. 실행 전 현재 자산·소유권·dispatch·projection·gate 조건을 재검사한다. 일반 Celery worker는 다른 작업과 재시도까지 실행할 수 있으므로 사용하지 않는다.

`access_epoch_ingestion_cli`는 v2의 등록된 writer child 전용이다. 현재 legacy/epoch0 환경에 임의 capability를 만들어 실행할 수 없다. 색인 완료 뒤에도 parsing/chunk/embedding/index count·projection READY·job succeeded·alias 검증과 실제 권한 검색/원문 접근을 확인해야 한다. 현재는 이 실행 및 검색·원문 검증 모두 미완료다.

## 검증과 보존

- 새 pin 기대값을 적용한 기존 회귀4개가 수정 전 실패했고, 제품의 두 상수 보수 뒤 관련 native/collector/CLI/access-epoch **276개가 한 번의 실행에서 통과**했다(17.32초).
- 최초 sandbox 검증은263통과/13개 PowerShell 실행 권한 실패였다. sandbox 밖 첫 재검증도263통과/13개 공용 pytest 임시 폴더 접근 오류였다. 보안 설정을 바꾸지 않고 프로젝트의 새 테스트 임시 경로로 분리한 마지막 실행에서276개를 확인했다.
- Ruff·format 두 파일, Mypy 제품1파일 통과. 최초 Mypy의 `NUL` cache 경로 실행은 내부 오류였고, 별도 작업 cache 경로로 재검증했다. 전체 저장소 테스트 통과를 주장하지 않는다.
- 독립 리뷰는 pin 보수가 기존 보안 계약을 유지하고 역사 identity를 변경하지 않았음을 확인했다. SDK 두 문서도 별도 독립 검토에서 차단 사항이 없었다.
- 사전·사후 DB23테이블의 행 수와 내용 지문이 일치했다. 생성 감사496건, 취소 미종료1건·별칭 open1/frozen1/receipt0·첨부 queued1을 그대로 보존했다. 착수 때 존재한 변경 파일31개 중 WORKBOARD의 의도한 갱신을 제외한30개 SHA도 모두 일치했다.
- 검증 자료는 `.local-data/project-agent-work/rag-recovery-followup-20261021/`에 보존한다. 사전 검사는 읽기 전용이며 실제 recover·release·parity·ingestion, 서버 재시작, 모델 생성·임베딩, DB 직접 수정, 설치·다운로드·commit·push는 하지 않았다.

## 다음 실제 작업

취소 건은 정확한 과거 종료/미기동 근거 또는 그 부재를 처리할 복구 설계가 필요하다. 별칭 건은 현재 거부된 WSL 실행의 소유·용도를 확인하고 기존 v1 지원 경계로 충족 가능한지 판단해야 한다. 지원 범위를 늘리는 경우 별도 종료/보안 전환 설계를 먼저 구체화한다. 종료 증거 없이 gate를 해제하는 방식은 사용하지 않는다. 첨부 실행은 이 조건 뒤에 이어진다.

후속 등록 작업은 **OpenAI Agents SDK의 호환성 표·실행 계약·ADR 준비**다. Codex SDK/App Server Provider 조사나 개발 Codex 에이전트 교체와 별개이며, 준비는 위 복구와 병행 가능하다. 12B/GPU 품질 비교 보류와 기존 품질 기준을 유지한다.
