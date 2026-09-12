# 자산운용 대화형 RAG 연결 재개

## 확인된 상태

도메인 자산운용은 등록되어 있으나 연결 0건·비활성이다. 저장 구성은 BM25 기준선 1건(pending),
생성 프로파일·LLM 실행 설정 버전은 0건이다. 공개 UI 완료와 실제 RAG 대화 완료를 구분한다.
CLI 0.153.4의 help에서 stdin, JSONL, ephemeral, ignore-user-config와 공식 인증 유지,
output-schema를 확인했다. 실제 모델 identity와 기존 v2 root oneOf schema의 호환성은 확인 전이다.

## 승인 설계와 실행 순서

정본은 `docs/superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md`와 ADR-0017이다.
기존 차단을 해제하거나 요청 모델을 관측 모델로 복사하지 않는다. 개인 owner·development·
공개/합성 입력·현재 전송 정책·실행 동의를 검사하고 실제 Windows 프로세스 회수 검증이 필요하다.

1. 입력/출력 계약 회귀와 v2 정상 근거 부족의 runtime/search 접합.
2. 버전된 CLI 실행 계약, 요청별 허가·수명주기와 가짜 CLI 검증.
3. 명시 승인된 합성 호출로 실제 identity·schema·사용량 검증.
4. 계약이 확인된 경우 Provider/DB·관리자 UI·Hybrid 구성·공간/도메인·평가 연결.
5. 실제 질문·근거/하이라이트·후속 질문·근거 부족/실패 확인 후 사용자에게 전체 테스트 요청.

현재 1단계 generation 기준선은 153개 통과했다. v2 parser는 근거 부족을 반환하지만
ProviderGenerationResult는 답변 필수라 검색 단계에 연결되지 않은 점을 보완한다.
기존 v1 호출을 유지하고 관측 모델 검증 후 정상 보류를 감사·반환하며 가짜 인용/서명 답변은 만들지 않는다.
이는 CLI 지원 증거와 무관하게 필요한 기존 승인 출력 계약의 접합이며 readiness 승격이 아니다.

실제 호출은 짧은 합성 질문·근거만 OpenAI에 전송하고 계정 사용량이 발생함을 고지했다.
사용자는 합성 입력 외부 전송·계정 사용량에 동의했고 첫 요청 모델로 `gpt-5.5`를 명시 선택했다.
이 선택은 모델을 소스에 고정하거나 관리자 등록·실행 검증이 완료됐다는 뜻이 아니다.
비공개 원문·인증 파일은 읽거나 전송하지 않았다.

공식 근거: [비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode),
[developer_instructions 설정](https://learn.chatgpt.com/docs/config-file/config-reference).

## 이번 구현과 검증

- `generation/execution.py`는 기존 두 인자 answered 생성자를 유지하면서 명시적인
  insufficient_evidence 결과를 표현하고 잘못된 상태/본문 조합을 거부한다.
- `search/service.py`는 기존 실행 provider/model/deployment 일치 검사 다음에 정상 보류를
  처리한다. 검색 결과는 유지하고 contextualize/answer 사용량을 감사에 합산한다.
  인용 검증·assistant 서명·자동 fallback을 수행하지 않는다.
- 합성 테스트 11개를 추가했다. RED에서 status 미지원과 CitationValidator(None) 경로를 확인했다.
  담당 generation/search 174개 통과, 메인 전체 unit/contract 1,059개 통과(기존 Starlette 경고 1개),
  mypy 211개 파일과 관련 Ruff 통과. 독립 검토자가 신규 11개를 별도 실행해 통과하고 결함 없음으로 판단했다.
- `search/service.py`의 기존 format 불일치는 baseline에서도 재현된다. 관련 없는 전체 포맷 변경은 하지 않았다.
- 실제 모델 호출·CLI 실행기·Provider 등록·migration·관리자 UI·도메인 활성화는 아직 수행하지 않았다.
  로컬 서버를 재시작하거나 비공개 자료·인증 파일을 읽지 않았다. 전체 RAG 테스트 준비 상태는 아니다.

합성 전송/계정 사용량 승인과 요청 모델 ID(`gpt-5.5`)는 확보했다.
Windows 요청별 자식 회수·실행 직전 권한/전송 검사도 먼저 검증해야 한다.
공식 Structured Outputs 문서는 루트 object와 지원 키워드 제약을 명시하므로 기존 v2 root oneOf를
그대로 CLI에 넣어 동작한다고 가정하지 않는다. 실제 모델 identity 확인을 요청 모델 복사로 대체하지 않는다.

## 요청별 프로세스 실행 기반

구현 계획: `docs/superpowers/plans/2026-09-08-codex-process-lifecycle.md`.
Windows Job Object에 suspended 프로세스를 먼저 배정하고 재개하며, stdin/stdout/stderr만
상속한다. 환경은 호출자가 명시하며 요청·응답 본문은 repr에서 제외한다. 이 기반은 임의 명령
실행 API로 공개하지 않으며 실제 CLI 권한·모델·출력 해석과 분리한다.

독립 검토에서 Thread.start 실패 후 시작되지 않은 writer.join이 정리를 중단하는 결함을
합성 자식으로 재현했다. 시작 상태 확인·예외 처리와 writer의 단일 fd 소유로 보완했다.
환경 snapshot과 UTF-16 명령/환경 길이 검증도 추가했다. 메인 재실행에서 Windows 합성 13개,
전체 backend unit/contract 1,072개(기존 Starlette 경고 1개), mypy 213개 파일과 관련 Ruff가 통과했다.
검증 범위는 프로세스 실행 기반이며 실제 모델 호출·관리자 등록·도메인 활성화가 아니다.
독립 재검토에서도 13개가 통과했다. 기존 Thread.start 실패 주입은 start_failed 정상 반환,
cleanup_verified=True, Job active count 0, handle close 3회로 수정됐으며 이 범위의 신규 중요 결함은 없다.
전체 Win32 API 실패 조합·실제 CLI 호출은 별도 검증 대상으로 남는다.

CLI 접합 준비 확인: 설치된 0.153.4 help의 `--strict-config`, `--model`, `--sandbox`,
`--ephemeral`, `--ignore-user-config`, `--output-schema`, `--json`을 확인했다.
공식 설정 문서는 shell tool, project instruction byte limit, developer instructions와
reasoning 표시 설정을 설명한다. 문서 존재는 실제 도구 비활성화나 모델 identity 증거가 아니므로
실제 CLI 검증은 별도로 남긴다. 현재 정책을 무시하는 옵션은 사용하지 않는다.
