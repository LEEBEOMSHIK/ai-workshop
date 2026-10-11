# 공식 읽기 자료

아래 첫 표는 2026-10-11 웹에서 페이지 접근과 개요를 확인한 1차 출처다. 개요 확인은 SDK/제품의 현재 PC 지원·설치·실행 검증이 아니다. 미래 학습일에는 정확한 문서/패키지 버전·OS·의존성·인증/비용 조건을 다시 확인하고 일일 기록에 남긴다. 공식 예제에 설치/실행 명령이 있어도 이번 승인으로 실행하지 않는다.

| 연결 Day | 읽기 출처 | 읽을 관점 |
|---|---|---|
| 17–20 | [Attention Is All You Need](https://arxiv.org/abs/1706.03762) | attention, multi-head, positional information과 구조 |
| 15, 59–61 | [PyTorch 기초](https://docs.pytorch.org/tutorials/beginner/basics/intro.html) | tensor, autograd, optimization; 설치하지 않고 흐름 읽기 |
| 31–32 | [MCP architecture](https://modelcontextprotocol.io/docs/learn/architecture) | host/client/server와 프로토콜 책임 |
| 36–38 | [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) | 실행 반복·도구·handoff·sessions·tracing; 프로젝트 도입 계획과 비교 |
| 39 | [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) | agent 실행·도구·권한/세션 경계; 현재 RAG와 동일하다고 가정하지 않기 |
| 40 | [LangChain overview](https://docs.langchain.com/oss/python/langchain/overview) | 모델·도구 조합의 추상화와 현재 코드 대응 |
| 41 | [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview) | state·실행 graph·영속 실행의 책임 |
| 52–55 | [pgvector 공식 저장소](https://github.com/pgvector/pgvector) | exact/ANN, HNSW/IVFFlat, 거리/필터 조건 |
| 57–58 | [Ollama 공식 문서](https://docs.ollama.com/) | 로컬 모델 serving과 API; 장치 지원은 별도 확인 |
| 62–67 | [PEFT 공식 문서](https://huggingface.co/docs/peft/index) | 적은 파라미터를 조정하는 학습 기법과 adapter |
| 74–81 | [Kubernetes Basics](https://kubernetes.io/docs/tutorials/kubernetes-basics/) | deploy, expose, scale, update; 현재 Compose와 개념 비교 |

첫 MCP URL은 조회 당시 버전 문서로 이동했으며 학습 때 협상할 프로토콜 버전은 별도 확인한다. Claude 문서는 platform.claude.com에서 code.claude.com으로 이동한 목적지 링크를 사용했다. 최신이라는 이유로 저장소 lock이나 런타임을 자동 갱신하지 않는다.

## 저장소 안에서 우선 읽을 근거

- 1–2주: [RAG 설계](../../labs/rag/design.md), [개발 규칙](../../guidelines/development-guidelines.md), [실행 정본](../../runbooks/local-development.md). 이번에는 명령 실행 없이 계약과 상태만 읽는다.
- 4주: [검색 평가 구현](../../../backend/src/ai_workshop/labs/rag/evaluation/metrics.py), [생성 평가](../../../backend/src/ai_workshop/labs/rag/evaluation/generative.py), [인용 검증](../../../backend/src/ai_workshop/labs/rag/generation/citation_validation.py).
- 5–7주: [SDK 도입 계획](../../superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md), [프로젝트 개발 에이전트](../../project-agents/README.md). 개발 에이전트와 서비스 에이전트를 구분한다.
- 8–10주: [저장소/학습 비교 계획](../../superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md)의 고정 조건과 자료 승인 범위.
- 11–12주: [Kubernetes 계획](../../superpowers/plans/2026-10-08-kubernetes-learning.md), [산출물 보존 정책](../../../CACHE_POLICY.md).

DB·Redis·Celery·Linux·Docker 세부 API가 필요한 날은 기존 의존성/설정 버전을 먼저 확인하고 해당 프로젝트의 공식 문서를 읽는다. 링크를 많이 읽은 횟수보다 설명·과제·반례의 검증 결과를 기록한다.
