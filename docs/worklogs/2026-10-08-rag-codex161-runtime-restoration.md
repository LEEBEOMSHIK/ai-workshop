# Codex0.161.0 신뢰 등록·본래 생성 준비 복구

2026-10-08 KST. 사용자가 [직전 변경안](2026-10-08-rag-attachment-mobile-verification.md)에 `진행해봐`로 명시 승인한 뒤 수행했다. 동일 runner의 버전·해시, 정확한 명령 계약, 기존 API만 반영하고 고정 합성 연결 검사1건으로 확인했다. 메인은 구현·운영·정상 API 실행, 독립 담당은 보안/개인정보·리뷰·자료 보존을 맡았다. 검색 품질·DB 구조·프론트·권한·새 모델 변경은 범위 밖이다.

## 수정과 회귀

등록0.160.0과 현재 공식0.161.0 파일의 SHA 불일치로 runner 사전 검사가 차단돼 있었다. 기존 exact argv 테스트에0.161.0을 먼저 추가하고 실제 `codex_command_contract_unsupported` RED1실패/경계2통과를 확인했다. 앞선 실행은 공용 임시 폴더 권한과 새 작업 부모 경로 미준비로 각각 fixture3오류였으며, 제품 실패 증거와 구분했다. 작업 경로를 준비해 RED를 확인한 뒤 허용 목록에 정확한0.161.0만 추가했다.

0.161.0-beta/0.161.1 거부·기존 strict-config/ignore-user-config/ephemeral/json/read-only sandbox·approval-never·web/tool/apps/hooks 제한과 고정 argv를 유지했다. 생성 모듈 단위 **1016통과/4skip**(47.17초), 변경 코드/테스트 Ruff와 코드1파일 Mypy가 통과했다. skip4는 Windows 합성 symlink 권한 사례이며 통과로 계산하지 않는다. 기존 Starlette/httpx deprecation 경고1은 패키지 변경 없이 기록했다. 독립 command/runner 회귀는 **239통과/4skip**(2.65초), 정적 보안 리뷰 차단/중요 지적0이다. 전체 저장소 통합 테스트 통과로 확대하지 않는다.

## 정확한 등록과 기존 API 반영

적용 직전에 같은 실행 파일의 Authenticode Valid/OpenAI OpCo, 실제 `codex-cli0.161.0`, 승인 SHA `a0f89acca07a511734cac7fddee26b2106fab68918717bc90df16104a0760a30`를 재확인했다. 실제 로컬 도움말에서 기존 exec 옵션도 확인했다.

`.env`의 같은 codex-personal runner에서 expected_cli_version/executable_sha256 두 필드만 갱신했다. 기존 바이트 동일성 확인 후 해당 한 줄의 두 값만 교체하고 다른 설정 의미·runner 경로/환경/제한·실제 hash/registry resolve를 확인했다. 파일 전후 SHA는 `3eda9a6d4397545125a8d552d958c011c64f00e469b67f618654f3e0414cb1b5` → `2f760a3163f370b6ec6075b0ef2e61ae2489ef4810a0140cb6c8f25c50f3b2aa`다. 독립 읽기에서도 기타 환경 값/typed settings SHA와 runner의 나머지 필드 보존을 확인했다. 다른 줄의 byte-for-byte 보존은 메인 적용 assert 증거이며 독립 담당은 원시 `.env`를 복사하지 않았다. 동시 편집이 없는 적용 구간에서 확인했으며 원자적 파일 CAS라고 주장하지 않는다.

본래 DB의 진행 대화/평가/시도/실행과 provider slot을 다시 읽어 모두0, API 자식 프로세스0을 확인했다. 기존 API88028/venv launcher108200의 정확한 명령·경로·시작 시각·18000 소유권을 확인해 그 두 프로세스만 종료했다. 원래 저장소 루트·`.env`·공식 Python과 같은 Selector loop factory로 API만 숨김 시작했다.

- 새 API29536/venv launcher33656/hidden launcher73132, 시작2026-10-08 09:46:23 KST.
- 기존 frontend7824/5173 보존. worker/beat 시작0, Docker·ES·DB·별칭 gate 변경0.
- 직접 `/api/v1/health`·`/api/v1/ready`, 프론트 경유 health가200.
- 새 runner 사전 검사0.161.0 통과. 연결 검사 전에는 기존 proof를 보존해 codex_verification_required/ready=false였으며 강제로 ready로 바꾸지 않았다.
- 로그는 `.local-data/dev-logs/original-rag-api-codex161-20261008-094622.stdout.log`와 동일 prefix의 stderr다. 비밀값·원문은 보고서에 기록하지 않았다.

## 정상 합성 검사와 기존 화면

기존 소유자 인증으로 정상 관리자 `codex-verify` API를 **1회** 호출했다. 고정 합성 입력만 사용하며 사용자 문서·이전 대화·개인 첨부 전송0이다. 검사1operation의 provider 단계 상한은2, 자동 재시도0이다. 실행 시작 표식을 먼저 저장해 같은 도구의 중복 실행을 거부했다.

응답200·ready=true·safe_error_code=null, 검사 시각2026-10-08 00:48:05.208219 UTC(09:48 KST)다. 후속 읽기에서 search_ready/answer_ready/service_ready 모두true, reason_codes=[]와 runner0.161.0 사전 검사 통과를 확인했다. 관측 모델 식별은 **unknown**이며 요청 모델과 같다고 추정하지 않는다. 이전 proof와 과거 실패 판정은 수정하지 않는다.

검사 두 단계는 기존 실행 코어의 issue_request/consume를 각각 거친다. 허용하는 신규 원장은 call approval2·consumption2·stage audit2·verification attempt1뿐이며, 새 원문 승인이나 기존 승인 변경을 허용하지 않는다. 독립 counter 읽기에서 이7행만 추가되고 기존71+추가4테이블의 기존 행 SHA 누락0을 확인했으며 같은 요청·구성·runner binding의 연결 검증은 후속 감사로 분리한다.

원래 Chrome의 기존 로그인 대화를 정상 새로고침해 준비 불가 안내가 사라지고 질문 입력이 활성인 것을 확인했다. 기존4턴·저장된 개인 첨부 카드도 복원됐다. 전송 버튼은 빈 질문·미선택 분류/동의 조건으로 비활성인 정상 상태다. 실제 질문을 추가하거나 선택·동의를 자동 설정하지 않았다. 새 대화/turn0이며 새로운 답변 품질·멀티턴 통과를 주장하지 않는다.

## 자료 보존과 남은 범위

적용 전 독립 기준선은 기존71테이블과 proof/slot/original-upload/resource 추가4테이블, 동결14보고서, 기존5대화23턴·선택4턴, fresh 문제2/3r4·5r65 업무 필드, 기존 원본3PDF와 저장 개인 PDF의 실제 바이트, 환경·active32/pending128·0063·frozen gate1/receipt0을 확보했다. 기준선과 적용/검사 receipt는 `.local-data/project-agent-work/rag-codex161-rollout-20261008/`에 있으며 계정·비밀값·원문 본문은 저장하지 않았다. 새 proof·stage audit와 이 보고서/이력의 정확한 append·기존 행 보존 최종 확인은 독립 후속 감사로 구분한다.

개인 첨부는 여전히stored·active_version NULL·verify_asset running/dispatching_verification·projection0이며 worker/beat는 꺼져 있다. 생성 연결 복구가 개인 파일의 검증·색인 READY를 뜻하지 않는다. 기존 개인 공간 외부deny·회사 생성 범위를 유지한다.

실제 첨부 검증/색인 마감, 외부 모델 취소/실패/timeout·committed 권한/첫 질문 경합, 별칭 종료 proof/새parity·DLL 재발 방지와 Git 인계가 남는다. **아직 품질 개선만 남은 상태가 아니다.** ISSUE-00005에 새 보고서 정확한 버전과 진행 사건을 연결하고 기존 status/remaining·업무 필드·사건·과거 문서 연결을 보존한다. 이 보고서는 DB 등록 후 동결하며 최종 독립 감사 메타데이터는 Workboard에서 이어 기록한다.

staging/commit/push0이다. 제품 코드1파일·테스트1파일·설정 두 필드·운영 프로세스·문서의 실제 변경을 Git 변경0 또는 실행 변경0으로 표현하지 않는다.
