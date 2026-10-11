# RAG 실제 개인 첨부·모바일 검증과 생성 준비 재발

2026-10-08 KST. 기존 마스터 로그인·원래 Chrome·원래 DB와 기존 대화에서 검증했다. 별도 환경·계정·대화는 만들지 않았다. 메인은 UI 실행·수정을, 독립 담당은 권한·개인정보 경계와 기존 자료 보존 검토를 맡았다. 이 문서는 DB에 정확한 버전으로 등록한 뒤 동결한다.

## 실제 업로드와 보존

- 기존 공개 합성 `output/pdf/synthetic-monthly-report.pdf` 한 개(204671바이트)를 정상 파일 선택기로 기존 대화의 개인 공간에 첨부했다. 실제 물리 드래그앤드롭은 실행하지 않았다.
- 화면은 `저장됨 · 현재 답변에 사용 불가`와 생성 범위 밖 개인 파일 안내를 표시했다. 개인 공간 외부 전송 deny·기존 회사 생성 범위를 유지했고 질문 선택에 자동 추가하지 않았다.
- 독립 읽기에서 attachment attached/retained·intake cleaned·임시 파일 종료/제거·원본과 저장 파일 SHA/크기 일치를 확인했다. 파일 삭제나 첨부 제외는 하지 않았다.
- Platform Asset Version은 **stored**, 문서 active_version은 아직 NULL이다. verify_asset 작업은 running/dispatching_verification, attempt1이며 worker/beat는 꺼져 있다. RAG projection0이다. 저장 성공을 검증·파싱·색인 READY 또는 답변 가능으로 확대하지 않는다.
- 업로드 후 독립71테이블 비교에서 기존 행 변경/제거0, 새 document1/version1/attachment1/intake1/provenance3/job1/job_source1을 구분했다. original_upload_attempts/original_file_resources는 사전71테이블에 없어 새 관계·상태만 검증했으며 그 두 테이블의 전체 기존 행 보존까지 주장하지 않는다.
- 기존 대화5개/23턴, 선택 대화4턴·revision10, 구성·승인·모델 호출 기록은 그대로다. 업로드 원본3개·환경·프로세스 시작/경로·schema0063·활성32/pending128·별칭 frozen1/receipt0을 유지했다.

## 새로고침 첨부 복원 수정

저장한 파일이 새로고침 후 화면에서 사라지는 결함을 실제로 확인했다. 파일 자체는 저장돼 있었으나 대화 선택이 첨부 패널을 닫고 서버의 기존 첨부를 조회하지 않았다.

`ConversationPage.tsx`의 대화 복원 시 기존 권한 검사 GET으로 첨부를 조회해 제외되지 않은 첨부가 있을 때 기존 패널을 연다. 실패도 기존 안전한 오류 표시로 연결한다. mounted·요청 generation·선택 대화 ID를 함께 확인해 늦은 다른 대화 응답을 차단한다. 새 세션·업로드·문서 선택·외부 호출을 자동 생성하지 않는다.

RED2실패 후 최초 GREEN2통과를 확인했다. 최종 관련6파일 **103통과**, TypeScript 전체 타입 검사와 변경4파일 ESLint는 종료 코드0이다. 복원·늦은 이전 응답·제외 항목·서버 오류 원문 비노출을 검증했다. 초기 확대 회귀4실패99통과/오류1, 이후103통과/오류1은 기존 fetch fixture의 attachments GET 응답 형태 누락 때문이었다. 해당 fixture를 실제 빈 배열 계약으로 수정한 뒤 최종103통과/오류0을 확인했다. 전체 저장소 테스트 통과로 확대하지 않는다.

원래 Chrome에서 정상 새로고침 후 저장 카드와 기존4턴 복원을 확인했다. 프론트 개발 서버 반영으로 확인했으며 서버 재시작은 하지 않았다. 독립 정적 리뷰는 제품 복원 코드와 새4테스트의 권한·stale 응답·오류 경계에서 차단/중요 지적0이었다. UI 관찰은 메인 실행 증거다.

## 모바일 관찰

인증된 같은 대화를390×844 viewport로 확인했다. 입력 테두리·입력 내부 +/전송 버튼, 저장 카드, 대화 목록 접기와 `+ → 기존 문서 선택`을 확인했다. 파일 선택 모달의 닫기·선택 목록은 화면 안에 표시되고 닫으면 `문서 추가`로 포커스가 돌아왔다. 페이지 documentWidth375/viewportWidth390으로 관찰했으며 가로 넘침은 없었다. 임시 viewport는 원래 크기로 복구했다.

생성 준비 불가로 질문 입력/전송은 비활성이다. 실제 모바일 기기·소프트 키보드·질문 전송·물리 드래그앤드롭·전체 모바일 동선까지 통과한 것은 아니다. 세로 스크롤과 준비 안내가 차지하는 공간도 남아 있다.

## 생성 준비 재발 원인과 실행 전 변경안

정상 관리자 GET에서 search_ready=true, answer_ready/service_ready=false, deployment_not_ready를 확인했다. Codex 상태는 codex_verification_required이고 runner 조회의 더 좁은 사유는 **codex_runner_hash_mismatch**다. 과거 proof 날짜만 보고 만료로 해석하지 않는다.

기존 등록은0.160.0이지만 현재 파일은 공식 OpenAI OpCo Authenticode Valid의 **codex-cli0.161.0**이다. 변경 시각은2026-10-08 03:04:57 KST이며 업데이트 주체·경위는 미확인이다. 서명 확인 후 로컬 --version/--help만 실행했고 provider 호출0이다. SHA 등록값은 `fdda5fa3cf3fb3d000b876720742857676293e4315e4b045fae6f8bd7e866d1d`, 현재값은 `a0f89acca07a511734cac7fddee26b2106fab68918717bc90df16104a0760a30`다. 제품 허용 계약도 아직0.160.0까지다.

구체적인 복구안은 정확한0.161.0 명령 계약·회귀를 추가하고, 동일 runner의 expected_cli_version/executable_sha256 두 값만 재확인 후 갱신하는 것이다. 진행 대화/평가0을 확인해 원래 API만 재시작하고 과거 proof를 보존한 새 고정 합성 연결 검사1건으로 현재 binding을 검증한다. 이 검사1건은 contextualize+generate **provider 단계 최대2회**이며 기존 계정 사용량이 발생할 수 있다. 개인 첨부·사용자 대화·문서는 검사에 전송하지 않는다. 경로·runner ref·권한·제한·모델·활성 구성·worker/beat·Docker·별칭 gate는 유지한다.

현재 제품에 기존 exact argv 테스트를0.161.0으로 적용한 후보 검사는 codex_command_contract_unsupported 거부를 확인했다(제품 변경0/provider0). 로컬 도움말에는 strict-config/ignore-user-config/ephemeral/json/read-only/output-schema/stdin 옵션이 존재했다. 독립 보안 검토는 기존 제한·모델·승인·old proof를 보존하고 적용 직전 서명/해시 재결속과 인접 미검토 버전 거부 회귀를 수행하는 조건으로 변경안을 수용했다. 옵션 존재 관찰은 실제 모델 명령 성공을 대신하지 않는다.

아직 신뢰 등록·허용 버전·서버·proof는 변경하지 않았다. 정확한 새 실행 파일을 허용하는 승인 후 작업으로 구분한다. 이번 실행의 자동 승인 검토 거절은 없으며 과거0.160.0 승인과 새0.161.0 허용을 동일시하지 않는다.

## 남은 기능 마감

생성 준비 복구, 첨부 검증·색인 작업의 정상 종료, 실제 외부 모델 취소/실패/timeout·committed 권한/첫 질문 경합, 별칭 실제 종료 proof/새 parity·DLL 재발 방지와 Git 인계가 남았다. 아직 품질 개선만 남은 상태가 아니다. ISSUE-00002/00003/00005에 정확한 보고서 버전과 실제 실행/제한을 추가하며 기존 status/remaining·업무 필드·기존 사건·문서 링크를 덮어쓰지 않는다.

staging/commit/push0, 새 대화/turn/provider0이다. 제품 프론트1파일·새 테스트1파일·기존 fixture2파일·작업 문서는 수정했으며 Git 변경0으로 표현하지 않는다.
