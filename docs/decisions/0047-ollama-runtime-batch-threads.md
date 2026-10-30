# ADR-0047: 프로파일별 Ollama 배치·스레드 선택

- 상태: 구현·배치/스레드 실측 완료. batch256과 명시6스레드 모두 첫 입력 처리 미개선으로 채택하지 않고 기존 기본값 유지 (2026-10-28)
- 관련: [ADR-0043](0043-ollama-native-timing.md), [ADR-0046](0046-rag-direct-answer-dispatch.md)

## 목적과 확인 사실

동일 모델·입력·근거를 유지하며 첫 입력 처리134.920초를 줄일 실행 설정을 비교한다. 사용자는 배치·스레드 확인부터 후속 수정을 요청했다. 사전 조사 당시 Ollama0.40.3 serve는 살아 있지만 runner와 적재 모델은 없고 저장 모델 parameters에도 num_batch/num_thread가 없었다. 직전 실행의 실제 값은 미관측이었다. 모델을 새로 로드해 확인하거나 과거 값을 기본값으로 채우지 않았다.

0.40.3의 API 기본 num_batch512는 최종 실행값이 아니다. scheduler가 생략한 배치를 자동 선택할 수 있다. 명시 num_batch는 runner의 논리 batch와 physical ubatch를 함께 바꾸고, num_thread는 입력 처리 전용이 아닌 기본 실행 스레드 수다. temperature0이라도 병렬·배치에 따른 수치 연산 차이로 출력이 달라질 수 있으므로 동일 품질을 코드 검증만으로 보장하지 않는다.

## 선택과 대안

전역 환경 또는 모델 저장 parameter 변경은 다른 요청과 재현 조건을 함께 바꾼다. provider에 임의 options 객체를 통과시키면 검증되지 않은 생성·자원 제어까지 허용한다. 두 방법 대신 **버전 생성 프로파일의 명시적·제한된 native runtime 설정**을 선택한다. 기존 기능을 요청 범위 안에서 확장하는 구현 판단이며 사용자에게 특정 수치가 최적이라고 승인받은 것으로 기록하지 않는다.

최초 비교 후보는 num_batch256 하나만 명시하고 num_thread는 생략한다. 작은 physical batch의 작업 메모리/캐시 압박 완화가 입력 처리에 유리한지 검증하는 가설이다. 더 느려질 수도 있으며256이 최적값이라는 근거는 아직 없다. 스레드 변경은 실제 자동 선택값 관측 뒤 별도로 비교한다.

## 계약

`orchestration.ollama_runtime`은 선택적 객체이며 생략 또는 null이면 기존 wire를 그대로 유지한다.

```json
{"version": 1, "num_batch": 256}
```

- `OllamaRuntimeOptions`는 strict/frozen/extra forbid이다. version은 strict integer1, num_batch는 선택적 strict integer1..2048, num_thread는 선택적 strict integer1..64다. 둘 중 하나 이상의 값이 있어야 한다. bool·문자열·float·0·음수·초과·알 수 없는 필드는 거부한다.
- 이 상한은 이번 애플리케이션의 보수적 허용 범위이며 Ollama의 최대 지원값이나 최적값이 아니다. 기본값을 주입하지 않는다. 범위 확장은 별도 변경이다.
- 객체가 있으면 local_http_api=ollama_chat이어야 한다. 기존 local·retry0·schema2·실제 dialect=ollama 경계도 유지한다. 호환 API나 다른 provider로 조용히 무시·변환하지 않는다.
- 중첩 frozen Mapping을 새 dict로 해석하고 원래 Profile.config·snapshot JSON은 변경하지 않는다. version은 wire에 보내지 않고 명시 숫자만 native options에 추가한다.
- SDK body의 임의 extra options는 계속 거절한다. 신뢰된 typed profile에서만 값을 전달한다. prompt/messages/format/think/모델/temperature/top_p/출력 한도·권한·인용·예산은 바꾸지 않는다.
- 기존 model span의 실제 native HTTP 입력 options에 요청값이 보관된다. 이는 **요청값**이다. 서버 실효값은 해당 실행의 runner command line/log 관측과 구분하며 없으면 미확인으로 기록한다. 새 DB schema·전체 로그 수집·비공개 추론 수집은 없다.
- 거절·timeout·취소·종료 추적·자동 재시도0과 실패 시 fallback 금지는 유지한다. manager/direct 두 경로에서 같은 프로파일 설정을 사용한다. 선행 문맥화는 기존 별도 생성 경로를 유지한다.

## 검증·실측 경계

기존 wire bytes 동일, 실제 SDK mock→native 전송의 허용 옵션만 차이, 두 dispatch의 호출 수·본문/인용 복원, frozen profile/readiness와 잘못된 설정의 전송 전 거부, 저장→현재 ACL 조회·다른 actor 거부를 검증한다. 새 모델 호출 없이 strict 타입·린트·회귀를 완료하고 본래 API에 반영한다.

실측은 구현·검증 후 별도 호출 범위로 한다. 준비할 비교는 기존 direct 후보2회와 batch256 후보2회(최대4실제전송·retry0)다. 같은 공개 질문과 v6/worker16MiB 조건을 유지하고 실제 execution 시각순으로 첫/반복을 판정한다. 매 호출 시 runner의 batch/thread 값을 읽기 전용 관측한다. 기준 실효 배치가256이면 서로 다른 설정의 효과 증거로 보지 않는다. 임의 unload/warmup·추가 호출·자동 튜닝·운영 승격은 하지 않는다. 답변·인용·필수 조건의 추가 퇴행이 있으면 후보를 채택하지 않는다.

공식 근거: [0.40.3 옵션](https://github.com/ollama/ollama/blob/v0.40.3/api/types.go), [자동 배치 선택](https://github.com/ollama/ollama/blob/v0.40.3/server/sched.go), [runner 인자](https://github.com/ollama/ollama/blob/v0.40.3/llm/llama_server.go). 조사 원문과 source pin·수치 동일성 한계는 작업 산출물에 보관한다.

## 실제 비교 판정

새 승인4/4회·retry0에서 기준 첫 runner1024/1024와 후보256/256을 관측했다. 기준 반복 관측은 시간 초과, 스레드 실효값은 미확인이다. 첫 입력130.876→132.683초로1.38% 느려져 batch256을 입력 처리 개선안으로 채택하지 않는다. 입력·답변·인용·28근거는 같고 기존 정답0/2는 유지됐다. 전체195.312→166.047초 감소는 검색·로드 등 다른 차이를 포함해 배치 효과로 귀속하지 않는다. 선택 설정 계약은 유지하며 후보는 비기본이다. [실측과 한계](../worklogs/2026-10-26-ollama-runtime-batch-threads.md#실제-결과).

2026-10-28에는 같은 공개 입력을 native 단계에서 분리해 총4회(첫1회 계측 불완전·유효3회), retry0으로 자동값과 명시6스레드를 진단했다. 유효 기준 입력131.222초→6스레드 첫143.781초(+9.57%)로 개선되지 않아 채택하지 않는다. batch/ubatch/context1024/1024/16384와 후보 `-t6`, 유효3개 답변·인용 동일을 확인했다. 자동 내부 스레드는 미확인이고 반복1.260초는 캐시/runner 재사용 영향과 구분한다. 프로파일/기본값은 변경하지 않았다. [장치·CPU/메모리·실제 수치·한계](../worklogs/2026-10-28-gemma-runtime-prefill-diagnosis.md).

같은 날 후속 조사에서 장치의 Dot Product/i8mm 지원과 설치 CPU backend의 해당 컴파일 지원 부재를 확인했다. GPU 장치는 OS에서 열거되나 설치 runner에 필요한 backend가 없으며, 공식 portable 후보는 Windows 정책에 차단됐다. 추가 모델 호출·기본값 변경 없이 후보를 보류한다. 문맥 축소의 작은 조건부 KV 절감 추정도 새 공개 옵션이나 기본값 변경의 근거로 삼지 않는다. [빌드 근거·차단·다음 경계](../worklogs/2026-10-28-gemma-gpu-memory-improvement.md).

서명 후보 후속에서는 최신 Ollama 0.40.12도 DOTPROD/i8mm 지원이 없는 반면 LM Studio CPU 2.65.1은 유효 서명·해당 기능1을 확인했다. 별도 bundle의 `--version` 1회는 exit0으로 끝났지만 버전 문자열은 수집되지 않았고 모델 로드·입력 시간·답변 품질은 미검증이다. 기존 Gemma4 입력 renderer/BOS와 sampler를 보존하는 비기본 비교 준비로만 취급하며 Ollama DLL 혼합, 기존 서비스 교체나 기본값 승격으로 연결하지 않는다. [취득·실행·호환성 근거](../worklogs/2026-10-28-gemma-signed-runtime-candidate.md).
