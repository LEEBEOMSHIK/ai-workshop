# 12B CPU 입력 처리 개선

사용자 요청 “개선 진행해봐”에 따라 [직전 진단](2026-10-21-rag-12b-timeout-diagnosis.md)의 입력 처리 지연을 개선한다. 현재 PC의 물리·논리 코어10개를 읽기 전용으로 다시 확인했고, 첫 후보는 요청별 `num_thread=10`이다. 이전 평균4.98코어 사용을 이전 스레드 수5개의 확정 근거로 사용하지 않는다.

## 변경 범위와 성공 기준

- 동일12B digest, 질문·근거·system/user 메시지·JSON schema·출력512·temperature0·reasoning 없음·timeout360초를 유지한다. 검색·임베딩·색인·품질 기준은 바꾸지 않는다.
- 이전2회 소진을 유지하고 신규1회만 허용한다. 성공 또는 실패 뒤 자동 반복하지 않는다. 오류가 발생하면 같은 요청을 재전송하지 않는다.
- 먼저 실제 runner의 `-t 10`과 기존 context·batch·draft 조건을 확인한다. 입력 처리 완료와 답변 반환 시간을 측정하고360초 제한 및120초 목표를 각각 판정한다. 답변 내용·인용 수용 여부는 별도로 검토한다.
- 변경은 실험 요청에만 적용한다. 기존 모델 등록·serve 프로세스·전역 환경·DB·운영 기본값은 보존한다. 신규 설치나 모델 다운로드가 필요하지 않다.
- 메인이 AI 런타임 변경, 독립 검토자가 요청 동등성·예산·결과 해석 검증을 맡는다. UI·DB 구조 변경 역할은 제외했다. 기존 미커밋 코드와 사용자 참고 이미지는 보존한다.

## 실행 경로

Ollama0.40.3의 OpenAI 호환 요청은 CPU 스레드 옵션을 전달하지 않는다. 같은 로컬 서버의 정식 `/api/chat`로 변환하고 기존 정책·runtime resolver·HTTP 오류 처리 경로를 사용한다. 별도 DB나 계정·모델 alias를 만들지 않는다.

기존 `FromChatRequest` 동작과 대조해 messages·schema를 그대로 복사하고, `max_tokens`는 `num_predict`, `reasoning_effort=none`은 `think=false`로 옮긴다. `stream=false`를 유지하며 생략된 `top_p`의 기존 유효값1.0도 명시한다. 모델 기본값0.95로 달라지는 것을 방지한다. 추가되는 실행 옵션은 `num_thread=10`뿐이다. 요청의 의미 동등성을 검사하는 것이며 HTTP 요청 바이트가 같다는 뜻은 아니다.

공식 버전 소스에서 [`num_thread`→`-t`](https://github.com/ollama/ollama/blob/v0.40.3/llm/llama_server.go#L386-L390), [OpenAI 요청 변환](https://github.com/ollama/ollama/blob/v0.40.3/openai/openai.go#L688-L764), [batch/draft 스레드 상속](https://github.com/ggml-org/llama.cpp/blob/b11351/common/arg.cpp#L821-L825)을 확인했다. 설치된 `llama-server --help`도 batch 처리 스레드는 별도 설정이 없으면 `--threads`를 따른다고 안내한다. `draft_num_predict`와 메모리·batch 설정은 이번 후보에서 바꾸지 않는다.

응답은 model·done·assistant role·content·종료 사유·비음수 정수 usage를 검사해 기존 schema2 파서·인용 검증기로 전달한다. 비공개 thinking은 저장하지 않는다. 원문 접근·DB6테이블 해시·고정111파일을 사후에도 확인한 뒤 결과를 저장한다.

## 사전 검증

요청 변환·설정 변경 거부·스레드 값 검증·응답 필드/비공개 thinking 제외·누적 예산·중복 HTTP 차단을 다룬13개 검사가 통과했다. Mypy1파일·Ruff F·PowerShell 구문 검사를 수행했다. 기존 정책과 자료 접근을 사용하는 읽기 전용 preflight도 통과했으며 이 단계의 생성 호출은0이다.

[독립 소스 검토](../../.local-data/project-agent-work/rag-12b-prefill-improvement-20261021/independent/source-review.md), [검증 기록](../../.local-data/project-agent-work/rag-12b-prefill-improvement-20261021/tests.xml), [실험 범위](../../.local-data/project-agent-work/rag-12b-prefill-improvement-20261021/authorization.json)를 보존한다.

독립 검토에서 native `length` 응답이 기존 strict parser에서 거부될 때 종료 사유가 오류 기록에서 누락되는 문제가 발견됐다. 파싱 전에 검증된 종료 사유·숫자 timing을 보존하도록 수정하고 실제 strict parser를 사용하는13번째 검사로 확인했다. 독립 재검증13/13과 잘못된 응답6개 거부를 통과한 코드로 실행했다. [실행 전 검토](../../.local-data/project-agent-work/rag-12b-prefill-improvement-20261021/independent/pre-execution-review.md), [보완 재검증](../../.local-data/project-agent-work/rag-12b-prefill-improvement-20261021/independent/p2-recheck/review.md)

## 실제 결과 — 스레드 조정만으로 미해결

2026-10-21 10:44:14.841 KST에 신규 요청1회를 전송했고10:50:14.872 KST에 `TimeoutError`가 발생했다. 단조 시계 측정은360.033491초, 예약 시각부터 요청 본문 전송 완료까지는약21.2ms였다. 답변0회·관측 생성 토큰0개·재시도0회다. 기존2회를 합쳐 **누적3/최대4회**, 남은1회는 실행하지 않았다.

기존 Ollama serve PID29096을 유지했다. 새 자식 PID72804의 실제 옵션은 `-t 10`, context16,384, parallel1, batch/ubatch1,024, draft-mtp3, load-mode none, flash-attn auto였다. CPU 스레드 설정이 반영됐으며 함께 확인한 나머지 옵션은 이전과 같다. GPU 적재는0이다.

| 항목 | 이전 진단 | CPU10스레드 후보 |
| --- | --- | --- |
| 입력3,072개 처리 상태를 처음 확인한 관측 | 요청 후약311.3초 | 요청 후약255.6~268.4초 구간의 관측 |
| 클라이언트 종료 | 약360.040초 시간 초과 | 약360.033초 시간 초과 |
| 실제 답변 | 없음 | 없음 |
| 관측 물리 메모리 여유 최솟값 | 약2.21GiB | 약1.04GiB |

**표의 관측 시각 차이를 속도 향상으로 확정하지 않는다.** 이전 관측은251.3초에2,048개,311.3초에3,072개여서 정확한 완료 시점은 그 사이였다. 이번 관측도 주기가 일정하지 않아 두 완료 시점의 가능한 구간이 겹친다. 반복 비교가 아니며 메모리 조건도 다르므로 개선율을 계산하지 않는다.

모니터의 `at`는 각 조회 묶음의 시작 시각이다. 실제 수집은 해당 `at`와 다음 묶음의 `at` 사이에 있으므로 이번 재계산은 이를 범위로 표현했다. 특히 첫 ready 묶음은약25.9~92.5초에 걸쳐 있어25.9초를 적재 완료 시각으로 사용할 수 없다. 제한 전에 완전히 수집된 마지막 묶음은약335.5~348.0초이며 입력3,072개 처리·생성0개였다. 입력4,096개 처리 상태는 약362.0~372.6초, 즉 제한 이후에 처음 확인됐다. 이를 제한 전 처리량으로 계산하지 않았다.

약384.6~390.1초 조회 구간에서 같은 슬롯의 `is_processing=false`와 생성0을 확인했다. 정확한 취소 처리 시각은 모른다. 모니터는 종료했으며 캐시된 엔진을 강제 종료하거나 전역 설정을 변경하지 않았다.

사후 원문 접근·정책 확인, DB6테이블 row/hash와 고정111파일 SHA 검사는 통과했다. [실행 마감](../../.local-data/project-agent-work/rag-12b-prefill-improvement-20261021/finalization.json), [단계별 관측](../../.local-data/project-agent-work/rag-12b-prefill-improvement-20261021/runtime-observations.jsonl), [재계산 결과](../../.local-data/project-agent-work/rag-12b-prefill-improvement-20261021/summary.json)를 보존한다. 실행 스크립트 exit0은 실패 기록 마감 성공이며 답변 생성 성공이 아니다.

독립 저장 파일·수치 대조155/155개가 통과했다. 메인도 고정111파일, 검토한 실행 파일 해시, 실제 native 입력 변환과 문서 링크를 재검증했다. Ruff F·문서 형식·`git diff --check`를 통과했으며 이 사후 검증의 추가 모델 호출은0이다. [독립 사후 검증](../../.local-data/project-agent-work/rag-12b-prefill-improvement-20261021/independent/actual-verification.json), [메인 사후 검증](../../.local-data/project-agent-work/rag-12b-prefill-improvement-20261021/postcheck.json)

## 판정과 후속 범위

CPU10스레드 후보는 실행 설정 반영까지 확인했지만360초 내 답변 반환과120초 목표를 충족하지 못했다. 실제 답변이 없어12B의 correctness·coverage·거절·인용 품질은 평가 불가다. E2B의 일반 지급 규칙 누락과 별개의 런타임 문제이며 도메인 READY·운영 프로필·연결 활성화로 이어지지 않는다.

다음 검토 후보는 보조 예측 모델(draft)의 입력 처리·메모리 비용이다. 공식 옵션 `draft_num_predict=0`은 해당 실행 경로를 끄는 수단이지만 이번에는 바꾸지 않았고 성능 효과도 미검증이다. 현재 환경에서 이 후보가120초를 충족한다고 보장할 수 없다. 잔여1회는 보존했다. 관리자 문제 이력 DB 반영은 미완료이고 이 기록을 ISSUE-00005 후속 근거로 연결한다. 커밋·푸시는 수행하지 않았다.
