# 실패 대화 통합 검증 준비와 Codex 런타임 등록 불일치

2026-10-04 기존 RAG 기능 마감의 후속이다. 실제 실패의 저장·재시도·대화 복원·모니터링 조회를 검증하려고 기존 환경과 계정·문서를 보존한 통합 테스트를 작성했다. 별도 DB·계정·환경을 만들지 않았다. [직전 수정 기록](2026-10-04-rag-execution-finalization.md).

## 시험 범위

`backend/tests/integration/labs/rag/executions/test_original_failure_conversation.py`는 명시적 opt-in에서만 실행한다. 본래 `.env` allowlist·schema0061·COMMIT 거부·SAVEPOINT·외부 롤백과 시험 UUID/요청 원장 잔존0 검사를 유지한다.

실제 ConversationService/DomainService/ConversationAccess/SQL recorder/종료 트리거/ExecutionReadService를 사용한다. generation_timeout, citation_validation_failed, 예기치 않은 예외를 시험 전용 executor 경계에서 주입한다. 실패·종료·관측 완료, 같은 요청 replay·변경 본문409·재조회, execution/turn/conversation 각1개, 실패 단계/세부 사유·이전 시간·선택 측정값 보존, 모니터링 반복 상세/실패 목록을 검사한다. 후보 원문 없이 workspace 권한만 확인하므로 원문 revision/projection 권한 검증을 대체하지 않는다. 실제 retrieval·모델·브라우저 E2E도 아니다.

## 현재 차단과 확인 결과

통합 opt-in은 **준비 게이트에서3실패**했다. 모두 시험 생성 전 본래 도메인의 `ready=False`, `search_ready=True`, `deployment_not_ready`를 확인했고 요청 원장의 rollback 후0건 검사는 통과했다. 권한 제한 여부를 분리하려고 동일 읽기 검사를 제한 밖에서도 실행했으며 같은 결과였다. 실패 주입·저장 경로는 아직 실행하지 못했다. 준비 검사를 fake/우회하지 않았다.

읽기 전용 Codex 상태는 `codex_verification_required`이며 기록은 존재하지만 현재 runner binding을 만들 수 없다. 더 좁힌 실제 원인은 **`codex_runner_hash_mismatch`**다.

- 원래 등록 버전은0.159.2다.
- 기존 실행 파일·요청 디렉터리는 존재하지만 실행 파일 SHA256은 등록값과 다르다.
- 실행 파일의 Authenticode는 Valid이며 서명자는 OpenAI OpCo, LLC다. 서명을 재확인한 뒤 기존 파일의 `--version`을 읽어 실제0.160.0을 확인했다.
- 제품 파일 변경 시각은2026-10-02 09:45:32 KST다. 변경 원인/업데이트 주체는 확인하지 않았으며 임의로 추정하지 않는다.
- 서명 확인 후 실제 `exec --help`에서 기존 strict-config/ignore-user-config/ephemeral/json/read-only sandbox/output-schema/stdin 옵션을 확인했다. 이것은 명령 옵션 관찰이며 실제 provider event·출력 검증은 아니다.
- 독립 검토가 현재 코드의 정확한 승인 버전 목록이0.159.2까지만임을 발견했다. 설정 두 값만 바꾸면 `codex_command_contract_unsupported`로 추가 차단된다.
- 제품 코드는 그대로 둔 후보 exact argv 회귀가 root/독립 모두 **1실패**로 이 미지원 상태를 재현했다. 의도적인 RED는 `.local-data/project-agent-work/rag-failure-conversation-20261004/`에 보존하며 기본 단위 경로에는 넣지 않았다.

`.env`의 같은 runner 버전·해시 두 필드를 갱신하려던 실행은 **자동 승인 검토가 거부**했다. 신뢰 등록을 영구 변경해 실행 허용 경계를 넓히는데 정확한 범위의 사용자 명시 승인이 없다는 이유다. 명령은 실행되기 전에 거부됐고 우회/간접 실행/재시도하지 않았다. `.env`, 제품 코드, 기존 API 프로세스와 DB 증빙은 유지했다.

## 준비된 변경안과 승인 후 순서

독립 보안·통합 검토를 반영한 구체적 제안은 `.local-data/project-agent-work/rag-failure-conversation-20261004/runner-binding-proposal.json`이다.

1. 제품 명령 계약에서 정확한0.160.0만 추가하고 기존 exact argv 테스트의 승인 목록에도 추가한다. 인접/beta 버전 거부와 기존 명령·tool 제한은 유지한다.
2. 공식 서명·실측 버전·해시를 재확인하고 `.env`의 **동일 runner의 expected_cli_version/executable_sha256 두 값만** 갱신한다. 경로·runner ref·환경·제한·모델·프로파일·권한을 보존한다.
3. running 대화/평가0을 다시 확인한 뒤 원래 API만 수정 코드/설정으로 반영한다. Docker/ES·gate·worker/beat는 바꾸지 않는다.
4. 과거 검증 proof는 수정하지 않고, 명시 동의를 받은 **새 합성 연결 검사**로 현재 binding의 증빙을 만든다. 고정된 합성 질문만 사용하며 문서나 사용자 이전 대화를 전송하지 않는다. 기존 Codex 계정 사용량은 발생할 수 있다.
5. 실제 ready·본래 SQL 실패 통합3건·독립 검증을 수행하고 기존 마스터 로그인에서 새 문제 등록/문서 버전 연결 및 실제 브라우저 실패 이력 확인을 이어간다.

별칭 ISSUE-00013 종료 증빙·gate 해제는 이 갱신의 범위가 아니다. 설치·다운로드·새 모델·활성 구성 승격도 하지 않는다. 실제 모델/브라우저 실패 검증 및 관리자 DB 등록은 여전히 미완료다.

## 사용자 승인 후 반영·검증

사용자가 위 최종 변경안에 `그래 진행해봐`로 승인했다. 승인 후 정상 승인 검토를 다시 거쳐 진행했으며 앞선 거부를 우회하지 않았다.

- 제품 명령의 정확한 허용 버전과 기본 exact argv 테스트에0.160.0만 추가했다. 기존 argv·기능 차단·인접/beta 버전 거부는 유지했다. 후보 RED→GREEN 포함 **283통과/4skip**(2.46초), Ruff 및 변경 소스1파일 Mypy 통과.
- 현재 실행 파일의 유효한 OpenAI 서명·실측 버전0.160.0·해시를 재확인하고 `.env`의 동일 runner에서 expected_cli_version/executable_sha256 두 값만 갱신했다. 쓰기 직전 원본 동일성, runner 나머지 필드와 나머지 환경 설정 동일성, 새 registry resolve를 확인했다. 과거 DB 증빙은 수정하지 않았다.
- running 대화·생성형 평가가 각각0건인 것을 재확인해 원래 API53672/Python launcher48244만 재시작했다. 새 API54856/Python launcher54852/숨김 launcher59256이다. 실제 API 시작은2026-10-04 23:05:11 KST이며 기존 프론트는 유지했다. 직접 health/readiness·프론트 경유 health가200이다. 로그는 `.local-data/dev-logs/original-rag-api-codex160-20261004.*.log`다.
- 승인된 **새 합성 연결 검사**가 실제로 통과했다. 현재 binding의 ready=true/safe_error_code=null이며 모델 식별 상태는unknown이다. 실행 시 지정 모델과 현재 계약의 합성 출력·usage·종료/정리 검증을 통과한 것이며 provider가 관측 모델명을 반환했다고 주장하지 않는다. 고정 합성 질문만 전송하고 문서·사용자 이전 대화는 보내지 않았다. 기존 계정/문서/원본 버전/연결 구성4개 테이블 건수 전후 동일을 확인했다.
- 준비 복구 후 본래 SQL 통합 **7통과**(40.86초): 실패 대화3종류와 관측 완료/종료 순서4사례. 실패 상태·종료·관측 완료·세부 사유·이전 시간/선택 측정값, 동일 요청 replay1회·본문 변경409·저장된 대화 복원·실제 monitoring service 상세/실패 목록을 확인했다. 각 시험 행과 요청 원장은 롤백 후0건이다. 준비 차단 시점의3실패와 복구 후7통과는 서로 다른 시점의 증거로 보존한다.

실패3종류는 **모델 경계의 시험 전용 오류 주입**이다. 본래 애플리케이션 서비스·DB·권한·모니터링 조회를 실행했지만 실제 외부 모델의 timeout/오류 재현이나 브라우저 화면에서의 신규 실패 검증을 대신하지 않는다. 관리자 브라우저는 아직 로그인 화면이며 새 결함의 DB 이력·문서 버전 연결과 실제 사용자 화면 검증이 남아 있다.

## 독립 검토·재검증

독립 검증 역할이 코드 변경 범위와 실제 등록 상태를 읽기 전용으로 검토하고 테스트를 별도로 실행했다. 단위 **386통과/4skip**(4.28초, 종료 코드0), 본래 SQL **7통과**(40.20초, 종료 코드0)다. skip4건은 OS 권한상 합성 심볼릭 링크 생성이 불가능한 사례이며 기능 통과로 계산하지 않는다. 시험 대화·turn·execution·접수 원장은 rollback 후 모두0건이다.

등록 runner1개, 버전0.160.0, 현재 실행 파일 해시 일치와 registry resolve를 비공개 값 출력 없이 확인했다. 승인 직전 상태 대비 정확한 버전 항목만 추가됐고 argv·인접/beta 거부·보안 조건이 유지됐음을 확인했다. 이전 관측 완료 판정과 조회 조기 종료의 세션 정리 수정도 재검토했다. 독립 검증에서 환경 쓰기·서버 변경·연결 검사 재실행은 하지 않았다.

현재 workspace 권한과 실패 저장·재전송·복원·모니터링 경로까지 검증했다. 실제 원문 revision/projection ACL 거부 사례·외부 모델 실패·브라우저 E2E·ES 별칭 종료/정상 parity는 범위 밖이며 후속 게이트로 유지한다. 관리자 로그인 이후 DB 문제 이력 등록과 관련 문서의 정확한 버전 연결을 이어간다.
