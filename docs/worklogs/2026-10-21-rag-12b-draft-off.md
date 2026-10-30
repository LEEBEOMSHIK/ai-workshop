# 12B 보조 예측 비활성화 검증

사용자 후속 요청 “그래. 개선 진행해”로 [CPU10스레드 시도](2026-10-21-rag-12b-prefill-improvement.md)의 남은 병목을 검증한다. 보조 예측 모델(draft)의 입력 처리·메모리 비용을 줄일 수 있는지 확인하며 효과는 실측으로 판정한다.

## 변경과 실행 범위

직전 `/api/chat` 요청의 `options`에 정수 `draft_num_predict=0`만 추가한다. 모델 digest, 질문·근거·지침·schema, CPU10스레드, 출력512, temperature0, top_p1.0, think=false, stream=false, timeout360초는 유지한다. 직전 native 요청 전체와 wire SHA를 먼저 대조하며 검색·임베딩·재색인은 수행하지 않는다.

기존3회 소진을 보존하고 남은1회만 사용한다. 자동 재시도는0이며 성공·실패 후 추가 생성하지 않는다. 기존 메모리 부족 상태 시험 허용 범위와 commit 여유 검사를 유지한다. 서버 전역·모델 등록·DB·운영 기본값은 바꾸지 않는다. 원문 접근과 정책·기존 runtime resolver를 경유하고 사후 권한 확인 뒤 결과를 보존한다.

메인은 AI 런타임 변경, 독립 검토자는 입력 동등성·호출 수·실제 옵션·결과 해석을 맡는다. UI·DB 구조 변경 역할은 제외한다. 실험 파일은 별도 로컬 작업 폴더에 두고 기존 미커밋 코드·사용자 이미지는 보존한다.

## 근거와 검증 조건

Ollama0.40.3의 [요청 옵션 처리](https://github.com/ollama/ollama/blob/v0.40.3/api/types.go#L988-L1021)는 명시한 숫자0을 보존하고 [runner 설정](https://github.com/ollama/ollama/blob/v0.40.3/llm/llama_server.go#L748-L763)은 `draft_num_predict<=0`일 때 speculative 인자를 생략한다. 이 후보는 본 모델의 답변 품질을 개선하는 지침 변경이 아니며, CPU에서 부가 계산 경로를 제거하는 실험이다.

실제 child에서 `-t 10` 및 context/batch 불변을 확인하고 speculative 실행 인자 부재와 슬롯의 명시적 `speculative=false`를 함께 검증한다. 필드 누락을 false로 간주하지 않는다. 입력 처리, 답변 반환,120초 목표와 품질 수용을 구분한다. 답변이 없으면 품질을 판정하지 않는다.

관측 주기 차이를 완료 시간으로 오인하지 않도록 이번 모니터는 조회 묶음의 시작·종료 시각을 모두 기록한다. 원시 답변의 비공개 thinking은 저장하지 않으며 응답 종료 사유·숫자 timing만 allowlist로 보존한다.

사전18개 검사와 Mypy1파일·Ruff F·PowerShell 구문 검사를 통과했다. 단일 옵션 변화·누적3→4회 제한·잘못된 draft 값·기존 strict parser와 실패 기록 회귀를 포함한다. 읽기 전용 preflight에서 원문·정책·모델·메모리·고정111파일을 확인했으며 이 단계의 생성은0이다. [실험 범위](../../.local-data/project-agent-work/rag-12b-draft-off-20261021/authorization.json), [사전 검사](../../.local-data/project-agent-work/rag-12b-draft-off-20261021/tests.xml), [독립 소스 검토](../../.local-data/project-agent-work/rag-12b-draft-off-20261021/independent/source-review.md)

독립 검토는 변경된 신규5개 검사5/5, 실제 저장 입력·직전 wire·예산·15개 의존 파일 확인21/21을 통과했다. 기존13개 검사를 불필요하게 반복하지 않았고 모델·HTTP·DB를 호출하지 않았다. [실행 전 독립 검토](../../.local-data/project-agent-work/rag-12b-draft-off-20261021/independent/pre-execution-review.md)

## 실제 결과 — 보조 예측 제거로도 미해결

2026-10-21 11:04:10.011 KST에 신규1회를 전송했고11:10:10.274 KST에 `TimeoutError`가 발생했다. 단조 시계 측정은360.264920초다. 본문 전송 완료는 HTTP 기록의 전송 시작 시각 기준약5.53ms, 예약 기준약7.65ms였다. 응답 헤더 수신 완료 이벤트가 없었고 답변0·관측 생성 토큰0·재시도0이었다.

실제 child PID26780은 CPU10스레드·context16,384·parallel1·batch/ubatch1,024를 유지했다. speculative 실행 인자는 없고 수집한 모든 슬롯의 `speculative`는 명시적 false였다. 모델 digest와 GPU 적재0을 확인했다. 기존 Ollama serve PID29096은 유지했다.

| 항목 | CPU10스레드 + draft | CPU10스레드 + draft 비활성화 |
| --- | --- | --- |
| 결과 | 약360.033초 시간 초과 | 약360.265초 시간 초과 |
| 관측 working set 최대 | 약8.91GiB | 약8.38GiB |
| 실제 답변 | 없음 | 없음 |

이번 관측에서는 working set 최대가 약0.54GiB 작았다. 동시 작업·메모리 조건이 통제된 반복 비교는 아니므로 차이 전체를 draft 제거의 인과 효과로 단정하거나 속도 개선율로 환산하지 않는다. 메모리 여유 최솟값은 제한 전에 약1.19GiB, private bytes 최대는약9.68GiB였다.

제한 전에 끝난 마지막 조회 묶음은 요청 후약328.9~357.4초이며 입력4,096개 처리·생성0을 확인했다. 당시 프롬프트 묶음 범위는4,506개였고 완료 응답의 전체 token usage를 받은 것은 아니다. 이전 관측과 정확한 입력 완료 시각을 맞춘 비교는 아니며 입력 처리 전체 완료·답변 생성 성공으로 확대하지 않는다.

약367.8~378.0초 구간의 조회에서 같은 슬롯이 `is_processing=false`, 생성0인 것을 확인했다. 정확한 취소 지연은 확정하지 않는다. 읽기 전용 모니터는 종료했다. [실행 오류](../../.local-data/project-agent-work/rag-12b-draft-off-20261021/04-normal-E-threads10-draftoff-error.json), [관측 기록](../../.local-data/project-agent-work/rag-12b-draft-off-20261021/runtime-observations.jsonl), [재계산 결과](../../.local-data/project-agent-work/rag-12b-draft-off-20261021/summary.json)

사후 원문 접근·정책 검증과 DB6테이블 row/hash·고정111파일 SHA 보존을 확인했다. [실행 마감](../../.local-data/project-agent-work/rag-12b-draft-off-20261021/finalization.json)의 exit0은 실패 기록 마감 성공이며 모델 응답 성공이 아니다.

독립 사후 검사32/32개가 통과했다. 신규1회와 누적4회 소진, 실제 요청의 단일 delta와 SHA, 검토15파일·고정111파일, 저장된 DB6해시, 옵션과 시간·메모리 관측을 대조했다. 메인도 입력·검토 파일·문서 링크를 확인하고 Ruff F·`git diff --check`를 통과했다. 이 사후 검증의 추가 생성은0이다. [독립 사후 검사](../../.local-data/project-agent-work/rag-12b-draft-off-20261021/independent/final-checks.json), [메인 사후 검사](../../.local-data/project-agent-work/rag-12b-draft-off-20261021/postcheck.json)

## 판정과 다음 경계

이번까지 **누적4/허용4회 소진, 응답0, 재시도0, 남은 호출0**이다. 실패 진단과 개선 시도로 정상 질문을 사용한 것이며 정상·근거 부족 두 사례×2회의 품질 비교를 완료한 것은 아니다. 추가 생성은 중단했다.

CPU 스레드 지정과 draft 제거 모두360초 내 답변 반환에 실패했다.120초 응답 목표도 충족하지 못했고12B의 correctness·coverage·거절·인용 품질은 평가 불가다. 현재 입력과 CPU 실행 방식으로 같은 실험을 반복하는 접근은 종료한다. 후속으로 실제 GPU 가속이 가능한 실행 환경 등 실행 방식 변경의 적합성을 검토해야 한다. GPU로 바꾸면 목표가 충족된다는 보장은 없으며 설치·다운로드·다른 서버 사용이나 추가 호출을 실행하지 않았다.

운영 기본값·도메인 READY·연결 활성화는 변경하지 않았다. 이전 E2B의 일반 지급 규칙 누락 문제는 별도 품질 과제로 남는다. 관리자 문제 이력 DB 반영은 미완료이며 이 문서를 ISSUE-00005 후속 근거로 보존한다. 커밋·푸시는 수행하지 않았다.
