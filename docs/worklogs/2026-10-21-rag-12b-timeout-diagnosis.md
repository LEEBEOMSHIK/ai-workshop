# 12B 시간 초과 단계 진단

사용자 요청: “원인은 뭔데? 다시 검증해봐”. [전일 비교 시도](2026-10-20-rag-readable-layout.md#12b-실제-시도와-시간-초과)는360초 시간 초과와 응답 부재만 확인했고 서버 처리 단계는 관측하지 못했다. 이번에는 같은 입력1회를 단계 관측과 함께 재검증했다.

## 확인한 원인

**현 CPU 실행 경로에서 입력 처리(prefill)가 끝나기 전에 클라이언트의360초 전체 제한에 도달했다.** 입력 토큰 처리량은 늘었지만 답변 생성은 시작되지 않았다. 답변 품질 실패를 재현한 것이 아니라 답변 생성 전 지연을 확인한 결과다.

| POST 기준 시점 | 관측 |
| --- | --- |
| 약32.8ms | 연결과 HTTP 요청 본문 전송 완료 |
| 약21.6초 | 추론 엔진 health `ok`, 작업 처리 중. 적재 완료 시각 자체가 아니라 최초 ready 관측 시각 |
| 약131.7초 | 입력 처리 완료1,024개, 다음 묶음까지 슬롯에2,048개, 생성0개 |
| 약251.3초 | 입력 처리 완료2,048개, 다음 묶음까지3,072개, 생성0개 |
| 약311.3초 | 입력 처리 완료3,072개, 다음 묶음까지4,096개, 생성0개 |
| 약356.6초 | 같은 작업이4,096개 묶음 처리 중, 생성0개 |
| 약360.040초 | `asyncio.wait_for(..., 360)` 제한으로 `TimeoutError`. HTTP 응답 헤더 수신 완료 이벤트도 없었음 |
| 약363.6초 | 입력 처리 완료3,072개·생성0개·처리 중 상태를 다시 관측 |

실제 POST는2026-10-21 10:10:55.773577 KST, 오류 기록은10:16:55.810141 KST다. 두 UTC 시각 차이는360.036564초이고 실행 시작 기준 단조 시계 측정은360.039726초다. 모니터는 POST보다 약70초 먼저 시작했으므로 모니터 자체 elapsed를 요청 지연으로 사용하지 않았다.

[재계산 결과](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/summary.json), [HTTP 단계 기록](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/http-trace.jsonl), [입력 진행량](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/slot-progress.jsonl), [CPU·메모리·엔진 상태](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/runtime-observations.jsonl)를 보존했다.

## 실행 환경과 해석 경계

- CPU는 Snapdragon X2 Plus, 논리 프로세서10개다. GPU는 Adreno X2-45지만 현 설치의 `llama-server.exe --list-devices`는 `Available devices: (none)`으로 종료 코드0을 반환했다. 실행 중 적재 정보의 `size_vram=0`, CPU 백엔드 모듈 로드도 확인했다. 다른 런타임에서 Adreno 사용이 불가능하다는 뜻은 아니다.
- Ollama0.40.3, 서버 PID29096, 추론 자식 PID53224를 확인했다. Ollama·llama-server·ggml-cpu·libllama의 PE는 모두ARM64다. 실행 중 서버의 `IsWow64Process2`는 process machine0/native machine0xaa64여서 x64 에뮬레이션 가설을 배제했다. 이는 기존 Ollama 상태 확인이며 프로젝트 Python 환경이나 아키텍처를 변경한 결과가 아니다.
- 기존 실행 옵션은 context16,384, parallel1, batch/ubatch1,024, draft-mtp3, load-mode none이며 명시적 threads 옵션은 없었다. 서버 설정을 바꾸지 않았다. 최초 모니터의 flags 정규식은 경로 일부까지 매칭했으므로 그 배열은 옵션 해석에 쓰지 않고 CIM으로 실제 명령줄을 별도 대조했다.
- ready 관측 이후 제한 직전까지 CPU 시간 증분은 평균약4.98코어 상당이다. 전체10코어 포화나 프로세스 정지를 주장하지 않는다. 제한 전 관측에서 working set 최대약8.89GiB, 시스템 물리 여유 최소약2.21GiB였다.
- RAM·페이징·CPU 스케줄링 및 target/draft 각각의 입력 처리 비용은 분리하지 못했다. 메모리만을 원인으로 단정하거나GPU 전환 시 몇 초로 줄어든다고 예측하지 않는다. `n_prompt_tokens_cache=0`은 관측한 프롬프트 KV 재사용 없음이며 OS 파일 캐시까지 없었다는 뜻은 아니다.
- 슬롯의 `n_prompt_tokens`는 당시 진행 중인 묶음까지의 값으로 관측됐다.12B의 전체 입력 토큰 수를 관측한 것은 아니다. 전일 E2B 입력5,526토큰을12B의 실측값으로 옮겨 적지 않는다.

[환경 관측](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/runtime-environment.json)을 남겼다. 아키텍처 판독은 [Microsoft API 계약](https://learn.microsoft.com/en-us/windows/win32/api/wow64apiset/nf-wow64apiset-iswow64process2)에, 읽기 전용 상태 관측은 [Ollama 실행 모델 API](https://docs.ollama.com/api/ps)와 [llama.cpp slots 모니터링 계약](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#get-slots-returns-the-current-slots-processing-state)에 대조했다. 설치 버전의 [Ollama runner 소스](https://github.com/ollama/ollama/blob/v0.40.3/llm/llama_server.go)도 확인했다.

## 재검증 범위와 보존

메인이 AI 런타임 진단을, 기존 독립 검토자가 요청·타이머·결과 해석 검증을 맡았다. UI·DB 구조·운영 배포 변경은 없어 해당 역할은 제외했다. 신규 설치·다운로드·재색인·새 검색·임베딩·일반 큐 실행·서버 재시작은 없었다.

사용자의 재검증 요청을 동일 실패 사례1회의 관측 재현으로 제한했다. 전일1회와 합산해 **누적2/기존 최대4회**, 남은2회는 실행하지 않았다. 자동 재시도0, 출력512, temperature0, reasoning 없음, timeout360초, 동일 E 지침·원문·schema를 유지했다. 같은13,311bytes 요청의 SHA256은 전일과 같은 `bb38622c176c395c6571b3686a66d3320818231a6a70680054f74c890bddfd18`이다. 과거 시작 표식이나 예약·manifest를 초기화하지 않고 새 [진단 범위](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/authorization.json)에서 기존 소진량까지 검사했다.

기존 application 정책·runtime resolver, 원문 접근과 프로필 동일성 검사를 그대로 사용했다. 모니터는 기존 서버의 자식 신원·포트만 확인한 뒤 GET `/health`, `/slots`와 CPU·메모리 수치만 읽는다. 헤더·프롬프트·비공개 추론을 HTTP trace에 저장하지 않았다. 입력·품질 기준을 낮추거나 질문별 답을 삽입하지 않았다.

전송 전 모니터 첫 관측·30초 이내 heartbeat·PID 생존을 확인했다. 원문 접근·DB6해시·고정111개 파일은 사후에도 동일했다. [실패 후 보존 확인](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/diagnostic-finalization.json)의 `outcome=error`, `quality=not_evaluable`을 판정에 사용한다. 진단 스크립트 exit0은 기록 마감 성공이며 생성 성공이 아니다. 실제 답변은 없고12B 정확성·인용·거절 품질 및 응답 P95는 여전히 판정할 수 없다. 도메인 READY·활성 연결·운영 프로필은 변경하지 않았다.

클라이언트 취소가 서버 작업을 즉시 멈춘다고 가정하지 않았다. POST397.25초까지 처리 중을 관측했고453.50초 시점에는 같은 엔진 슬롯이 `is_processing=false`, 생성0이었다. [취소 후 관측](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/cancellation-observation.json)으로 작업 비활성 상태를 확인했지만 정확한 종료 지연은 두 관측 사이여서 확정하지 않는다. 모델 적재 캐시와 작업 실행 상태도 구분한다.

## 검증과 남은 작업

기존 로그의 헤더·본문 구분 공백을 확인했다. 전일 `ExactTransport`는 본문 전체 수신 뒤에 상태를 저장했으므로 당시 파일만으로 헤더 미수신까지 확정할 수 없다. 이번에는 HTTP 단계 trace를 추가했고 헤더 수신 대기 중 제한에 도달한 것을 직접 확인했다. 소켓 없는 모의4종으로 무응답·부분본문·HTTPX ReadTimeout·완료 응답을 구분했고 숨은5초 기본 제한 문제를 배제했다. [독립 타임아웃 검증](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/independent/timeout-layer-probes.json)

메인7개 검사에서 단일 요청·재시작 차단·기존 소진량·설정 변경 거부·trace 내용 제외를 확인했고 Ruff F와 PowerShell 구문 검사를 통과했다. 독립 검토의 사후 권한 확인 전 응답 저장, 모니터 heartbeat, 관측값 제한 지적을 실행 전에 반영했다. [독립 실행기 검토](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/independent/runner-review/review.md), [실제 진행 해석](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/independent/progress-interpretation.md)

최종 독립 검토는 저장 파일·산술 대조148/148개를 통과했고 P1/P2 불일치는 없었다. 기존 작업 공간2,022개 파일의 존재를 확인했으며 이번 작업에서 변경한 기존 파일은 WORKBOARD와 전일 작업 기록뿐이다. 이 진단 기록은 새 파일이다. 로컬 문서 링크·코드 블록·UTF-8 및 `git diff --check`도 통과했다. 이 검증 과정의 추가 모델 호출은0회다. [독립 검토 결과](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/independent/final-review.md), [148개 검사 기록](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/independent/final-review.json), [작업 공간 보존 검사](../../.local-data/project-agent-work/rag-12b-timeout-diagnosis-20261021/document-preservation-check.json)

보조 slots 관측에서 `next_token`이 객체 하나를 담은 배열로 반환돼 처음1회 읽기 분석이 실패했다. 읽기 보조 도구만 형태를 처리하도록 보완했으며 실행 요청이나 고정 모니터는 바꾸지 않았다. 누락된 수치를0으로 채우지 않았다. 기존 서버의 콘솔 로그 파일은 확보하지 못했지만 이번에는 직접 엔진 수치로 처리 단계를 확인했다.

다음 검토 대상은 동일 입력을 감당할 추론 실행 경로와 입력 처리 성능이다. 잔여2회를 같은 조건으로 자동 반복하거나 시간 제한 연장·입력 축소·GPU 백엔드 설치를 이번 결과에 섞지 않는다. 기존 E2B의 일반 규칙 누락 문제와12B의 시간 초과는 별개로 남는다. 이 런타임 지연은 ISSUE-00005 관련 후속 자료로 보존하며 관리자 문제 이력 DB 반영은 미완료다. 기존 작업과 사용자 파일을 보존했고 커밋·푸시는 하지 않았다.
