# OpenAI Agents SDK 호환성과 도입 실익

확인일: 2026-10-22. 범위는 현재 환경·공식 배포 요구사항·기존 코드의 읽기 전용 조사다. **첫 적용 후보는 Python Agents SDK + 로컬 Ollama/Gemma다. 구조상 연결 가능하나 의존성 조정과 SDK 어댑터 검증이 필요하다. 설치·실행 호환성 통과 판정은 아니다.**

[Gemma 첫 실제 LLM 연동·RAG 입력/출력 검증 완료](2026-10-22-rag-first-llm-milestone.md)는 유지한다. 이 보고서는 후속 SDK 준비 결과이며 과거 복구나 추가 품질 평가를 재개하지 않는다. SDK 적용으로 정확도·속도·비용이 개선됐다는 측정 결과도 없다.

## 확인한 환경과 패키지 조건

프로젝트 `backend/.conda/python.exe`에서 Python **3.13.16 / Windows AMD64**를 확인했다. SDK 검토 후보는 **openai-agents 0.24.0**(2026-10-15 배포)이다. 공식 요구사항은 Python >=3.10이고 SDK 본체는 OS 독립 wheel을 제공하므로 현재 Python/OS 조합을 배제하지 않는다. 선택 기능인 Unix 로컬 sandbox는 이번 RAG 적용 대상이 아니다. [배포 메타데이터](https://pypi.org/project/openai-agents/0.24.0/)

공식 버전의 기본 의존성 12개를 설치 메타데이터와 `backend/uv.lock`에 대조했다. 아래 값은 설치된 버전과 lock이 일치한다. **5개 충족, 2개 상향 필요, 5개 미설치**이며 SDK 본체도 미설치다. optional extras는 선택하지 않았다. [공식 요구사항 JSON](https://pypi.org/pypi/openai-agents/0.24.0/json), [같은 태그의 pyproject](https://github.com/openai/openai-agents-python/blob/v0.24.0/pyproject.toml)

| 패키지 | 현재 | SDK 요구 | 판정 |
|---|---|---|---|
| pydantic | 2.13.5 | >=2.12.2,<3 | 충족 |
| python-multipart | 0.0.32 | >=0.0.31 | 충족 |
| requests | 2.34.2 | >=2.0,<3 | 충족 |
| starlette | 1.6.0 | >=1.3.1 | 충족 |
| typing-extensions | 4.16.0 | >=4.12.2,<5 | 충족 |
| PyJWT | 2.13.0 | >=2.15.0 | 상향 필요 |
| urllib3 | 2.7.0 | >=2.8.0 | 상향 필요 |
| openai | 미설치 | >=3.0.0,<4 | 신규 의존성 |
| mcp | 미설치 | >=1.19.0,<3 | 신규 의존성 |
| griffelib | 미설치 | >=2,<3 | 신규 의존성 |
| httpx2 | 미설치 | >=2.12.0 | 신규 의존성 |
| websockets | 미설치 | >=15,<17 | 신규 의존성 |

현재 프로젝트의 `httpx 0.28.1`은 별도 패키지인 `httpx2` 요구를 충족한 것으로 계산하지 않았다. PyJWT 상향은 프로젝트 선언 `>=2.10,<3.0` 안에 있지만 인증 회귀 검증이 필요하다. 전체 전이 의존성 해석·wheel 설치·import 검증은 수행하지 않았으므로 새 패키지들의 공존 가능성과 최종 설치 용량은 미확정이다. OpenAI 클라이언트의 최종 고정 버전도 의존성 해석 후 결정한다. 낮은 버전으로 요구 조건을 우회하지 않는다.

## Ollama와 Gemma에서 확인한 것

로컬 `127.0.0.1:11434`의 `/api/version`, `/api/tags`, `/api/show` 메타데이터 조회가 성공했다. Ollama **0.40.3**, 모델 **gemma4:e2b-it-q4_K_M**, digest `b37049369adfe3d2b653af0ab301a062ca5cbe96ace6aa0d3f2559ee9b563fc2`다. capabilities는 `completion`, `vision`, `audio`, **`tools`**, `thinking`이다. `/api/show`의 POST는 모델 정보 조회이며 생성 요청이 아니다.

따라서 설치 모델은 도구 호출 가능성을 명시한다. **도구를 올바르게 고르고 인수를 만들며 결과를 받아 최종 답변까지 완성하는지는 이번에 실행하지 않았다.** 모델 최대 문맥 메타데이터도 실제 실행 문맥 설정이나 메모리 여유의 증거로 사용하지 않는다.

Ollama는 OpenAI 호환 Chat Completions와 도구·구조 출력 기능을 제공한다. SDK에는 `OpenAIChatCompletionsModel`이 있으므로 기존 로컬 endpoint와 모델을 명시하는 연결이 첫 후보다. Ollama의 Responses도 문서상 일부 지원하지만 서버 보관 대화 상태는 지원하지 않는다. 이미 사용한 Chat Completions 경로를 우선하는 것은 변경 범위를 줄이기 위한 판단이다. [Ollama 호환 API](https://docs.ollama.com/api/openai-compatibility), [구조 출력](https://docs.ollama.com/capabilities/structured-outputs), [SDK 모델 어댑터](https://github.com/openai/openai-agents-python/blob/v0.24.0/docs/models/index.md)

## 기존 코드와의 접점

[GenerationRuntimePort](../../backend/src/ai_workshop/labs/rag/generation/contracts.py)는 `health/contextualize/generate`와 최종 답변을 다룬다. [현재 로컬 HTTP 어댑터](../../backend/src/ai_workshop/labs/rag/generation/openai_compatible.py)는 Ollama schema 2에 JSON Schema와 프로파일의 thinking 설정을 전달하지만 엄격한 응답 검사에서 비어 있지 않은 `tool_calls`를 거부한다. 이는 현재 단발 생성 계약이며 SDK 도구 반복을 이미 구현했다는 뜻은 아니다.

| 기존 경로 | SDK 연결 판단 | 구조 출력·도구 실행 | 취소·usage에서 필요한 연결 |
|---|---|---|---|
| 로컬 Ollama/Gemma | 첫 후보. Chat Completions 어댑터 경로가 맞음 | 현재 구조 답변 사용 이력 있음. SDK 도구 왕복은 새 연결과 검증 필요 | 현재 실행 ID·종료 상태와 단계별 호출/토큰 합산 연결 |
| 그 밖의 로컬 OpenAI 호환 서버 | API 명칭만으로 호환 확정 불가 | 각 서버의 schema·tool_choice·tool 결과 재전달을 별도 판정 | 서버별 usage 누락·취소 동작 확인 |
| OpenAI Responses | SDK 기본 어댑터 존재. 이번 첫 적용 대상은 아님 | 프로젝트의 기존 Responses 어댑터는 schema 1 최종 답변 경로 | 기존 외부 전송 정책·store=false·timeout·재시도 조건 보존 필요 |
| Local Transformers | 현재 SDK 직접 연결 없음 | 커스텀 모델 어댑터와 기능 계약 필요. 단발 포트를 도구 반복 지원으로 간주하지 않음 | 프로세스 수명과 사용량 매핑 별도 필요 |
| 개발용 Codex exec | 별도 명령 실행 계약. SDK 모델/API 인증으로 재사용 가능하다고 판정하지 않음 | 현재 schema 2/3 답변 파싱과 SDK 도구 반복은 별개 | 현재 소유 작업 정리·종료 기록 보존 |

코드 근거: [resolver](../../backend/src/ai_workshop/labs/rag/generation/runtime_resolver.py), [Responses](../../backend/src/ai_workshop/labs/rag/generation/openai_responses.py), [Codex exec](../../backend/src/ai_workshop/labs/rag/generation/codex_runtime.py). 위 표는 코드·문서 분석 결과이며 각 경로의 SDK 실행 성공표가 아니다.

제안하는 위치는 **기존 RAG 애플리케이션 아래의 별도 실행 조율 어댑터**다. SDK를 기존 모델 종류에 하나 더 추가하는 방식으로 다루지 않는다. 단발 생성 포트는 유지하고, SDK에 필요한 메시지·도구 호출·결과 왕복을 별도 계약으로 연결한다. 권한·자료 범위·검색 순위·인용 검증·최종 저장은 기존 서비스가 맡는다. 세부 공개 계약과 ADR은 다음 준비 작업에서 확정한다.

## 무엇이 왜 좋은가

아래는 공식 SDK 기능을 현재 구조에 적용했을 때의 **예상 실익**이다. 구현 시간 절감이나 품질 향상을 측정한 값은 아니다. SDK는 모델 응답, 도구 실행, 역할 전환, 종료를 하나의 실행 반복으로 다룬다. [공식 실행 흐름](https://developers.openai.com/api/docs/guides/agents/running-agents)

| 선택 | 이 프로젝트에서 좋은 이유 | 한계 |
|---|---|---|
| Python SDK | 기존 FastAPI·Python 검색/권한 서비스를 같은 프로세스 경계에서 연결할 수 있음 | 패키지 호환성 확인과 어댑터는 필요 |
| 기존 Gemma/Ollama 유지 | 첫 RAG 실측 기준선을 그대로 비교할 수 있고 로컬 모델 경로를 유지함 | SDK가 Gemma의 추론 능력을 높여 주지는 않음 |
| SDK의 도구 실행 반복 | 검색 요청→도구 결과→최종 답변 전달을 공통 방식으로 다뤄 확장 시 직접 작성할 제어 코드를 줄일 여지가 있음 | 모델이 도구 호출을 안정적으로 수행해야 함 |
| 역할별 입력/결과와 실행 이벤트 | 근거 누락·입력 변환·도구 실패·답변 누락이 어느 단계에서 생겼는지 연결하기 쉬워짐 | 현재 기록 기능과 통합해야 하며 외부 trace를 그대로 쓰지 않음 |
| 하나의 조정 역할부터 시작 | 현재 단순 질의에 필요 없는 다중 모델 호출을 추가하지 않고 연결 계약부터 확인 가능 | 전문 역할 확장은 실제 필요와 측정 뒤에 판단 |
| 기존 단발 RAG 유지 | 단순 질의의 현재 기준선과 비교 경로를 보존함 | SDK의 장점은 추가 단계가 필요한 업무에서 더 커질 것으로 예상 |

예를 들어 향후 “두 문서의 규칙 차이를 비교”하는 요청에 필요한 검색·충돌 검토·답변 작성 단계를 연결하기 쉬워진다. 특정 업체나 질문별 정답을 코드에 넣는 방식은 필요하지 않다. 반면 도구 결과를 받아 다시 생성하면 LLM 호출과 지연이 늘 수 있으므로 기존 답변 시간·정확도가 자동 개선된다고 설명할 수 없다.

## 첫 적용에 필요한 설정

- SDK 모델과 Ollama endpoint를 기존 Deployment/Profile에서 명시적으로 전달한다. 기본 모델이나 외부 endpoint로의 자동 전환을 허용하지 않는다.
- 초기 **외부 tracing은 비활성화**한다. 기본 SDK tracing은 모델·도구 실행을 수집하고 OpenAI 전송 경로를 사용한다. `set_tracing_disabled(True)`를 첫 실행 전에 적용하고, 기존 내부 모니터링에는 단계·상태·호출 수·토큰·시간 같은 허용 메타데이터를 연결한다. 민감 데이터 수집 옵션만 끄는 것으로 외부 전송 전체를 막았다고 보지 않는다. [공식 관측 문서](https://developers.openai.com/api/docs/guides/agents/integrations-observability), [외부 모델과 tracing 설정](https://github.com/openai/openai-agents-python/blob/v0.24.0/docs/models/index.md#tracing-client-error-401)
- 하위 OpenAI client와 Runner 재시도를 모두 명시적으로 0으로 제한하는 초기안을 검증한다. 기존 프로파일의 출력/temperature/timeout을 전달하고, 전체 기한·모델 시도 수·도구 호출 수를 따로 제한한다. `max_turns` 하나로 모든 호출을 제한했다고 간주하지 않는다. [Runner 재시도·timeout](https://github.com/openai/openai-agents-python/blob/v0.24.0/docs/models/index.md#runner-managed-retries)
- SDK의 취소 반환과 Ollama의 실제 생성 종료는 구분한다. 기존 실행 수명주기를 보존하되 이번에 과거 복구를 재개하지 않는다.
- 기존 DB를 대화 이력의 정본으로 유지한다. 현재 권한으로 선별한 이력과 근거만 전달하며 도구 실행마다 기존 권한 검사를 거친다. SDK Session을 별도 정본 저장소로 자동 추가하지 않는다.
- JSON Schema는 구조 검사다. 정답성·근거 충족·인용 유효성은 기존 검증을 유지한다. 누락 usage를 0으로 바꾸거나 모델의 비공개 내부 추론을 기록하지 않는다.

## 다음 검증 계약과 의존성 보존

다음은 구현 전에 확정할 검증안이다. **SDK 미설치 상태이므로 아래 테스트 파일은 아직 없으며 실행하지 않았다.**

| 예정 검증 | 통과 조건 |
|---|---|
| Fake model 단발·도구 왕복·역할 도구 호출 | 외부 네트워크와 실제 모델 호출 없이 호출 순서, tool call ID, 결과 재전달, 최종 구조 출력 확인 |
| 입력·출력·권한 | 잘못된 도구/인수/구조 답변 거부, 도구별 권한 재검사, 인용 실패 시 정상 답변 저장 금지 |
| 모델 요청 매핑 | 명시한 모델/endpoint와 프로파일 파라미터 보존, 지원하지 않는 옵션은 조용히 무시하지 않고 실패 |
| 예산·실패·취소 | 재시도0, 단계별 시도 수 합산, 전체 기한/turn 제한, 늦은 응답 중복 저장 금지, 종료 미확인을 완료로 오인하지 않음 |
| 기록·외부 전송 | tracing 비활성 상태와 외부 요청0 확인, 본문/비밀/내부 추론 제외, 기존 실행 ID 연결, usage 누락 보존 |

예정 테스트 경로는 `backend/tests/unit/labs/rag/orchestration/test_agents_sdk_contract.py`다. 구현 시 생성한 뒤 승인된 Conda 활성화와 `backend` 작업 위치에서 `& $workshopPython -m pytest tests/unit/labs/rag/orchestration/test_agents_sdk_contract.py -q`로 실행한다. 실제 타입/함수·mock 경계는 [준비 작업 2](../superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md#준비-작업-2-실행-계약adr구현-작업-분할-확정)에서 설계에 맞춰 확정한다.

설치 전에는 현재 manifest/lock과 설치 목록을 보존하고, 후보 lock 변경을 먼저 검토한다. SDK·필수 의존성만 허용 목록으로 대조하며 Torch·임베딩·OCR 패키지의 불필요한 재설치를 막는다. PyJWT·urllib3 상향의 인증/HTTP 영향과 Windows wheel·전체 전이 의존성을 확인한 뒤 정확한 버전들을 고정한다. 설치 이후에는 import·의존성 검사·위 오프라인 계약 검증·영향받는 기존 회귀 테스트를 통과해야 한다. 이번에는 lock 해석·패키지 설치·환경 교체를 하지 않았다.

## 수행 증거와 독립 검토

- 읽기 전용 조사·문서 작업으로 분류했다. 메인이 환경/의존성 분석을 담당했고 독립 AI 검토와 데이터 전송 검토를 수행했다. UI·DB·배포 구현 역할은 변경 범위가 없어 제외했다.
- AI 검토는 단발 생성 포트와 도구 반복의 차이, provider별 범위, 취소·usage 연결 필요를 확인했다. 데이터 전송 검토는 기본 tracing, 명시적 모델 경로, 재시도, 이력/권한 경계를 확인했다. 최종 표와 결론도 이 검토 범위에 맞췄다.
- 로컬 증거: `.local-data/project-agent-work/rag-agents-compatibility-20261022/environment.json`, `dependency-comparison.json`. 민감 본문·키·모델 template은 수집하지 않았다.
- SDK 요구사항은 공식 PyPI JSON과 같은 Git 태그를 대조했다. 셸의 PyPI 직접 조회는 연결 오류로 실패하여 공식 웹 조회 결과를 사용했다. 이는 SDK 설치 실패나 호환 불가 판정이 아니다.
- 조사 중 생성/임베딩/설치/DB 변경/commit/push는 모두 0이다. 실제 SDK 실행 테스트와 성능 측정은 미실시다.
- `backend/pyproject.toml` SHA-256 `98c8aa5141eb4915189e753dc56116ea4d902ac4c3b51365ba34cb0584c547b1`, `backend/uv.lock` SHA-256 `16f9b5207df5568ba7526343823a80006843793a83b7522b9d8d88a38dd6c3f2`를 보존했다.
- 문서 3개·로컬 파일/앵커 링크 125개·공백 검사를 통과했다. 의존성 파일 2개·기존 설치 메타데이터 24개·과거 보고서 4개의 보존과 WORKBOARD 최근 완료 5개를 확인했다. 독립 최종 AI·데이터 전송 검토에서 중요한 오류를 발견하지 못했다. 이 문서 검사를 SDK 실행 테스트로 계산하지 않는다.

판정: **SDK 도입 준비를 진행할 기술적 근거는 있으며, 현재 환경에 즉시 추가해도 안전하다는 판정은 보류한다.** 다음 작업은 실행 계약·의존성 변경 범위를 확정하고, 기존 RAG를 보존한 최소 어댑터의 오프라인 검증을 준비하는 것이다.
