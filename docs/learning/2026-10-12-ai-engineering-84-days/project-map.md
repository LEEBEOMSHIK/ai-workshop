# 프로젝트 현황과 학습 연결 지도

분석일: 2026-10-11. **코드·문서의 정적 읽기** 결과다. 실행 서비스·DB·모델을 조회하거나 재검증하지 않았다. 기록에 나오는 상태와 수치는 해당 날짜의 관측이며 현재 런타임 상태를 보증하지 않는다.

## 구현·진행·차단 구분

| 영역 | 읽어서 확인한 구현/기록 | 남은 경계 | 연결 Day |
|---|---|---|---|
| 공통 구조 | Next.js/React → FastAPI 서비스 → 어댑터. Platform과 Labs 분리 | 모듈 존재와 본래 환경 기능 성공은 별도 | 01–03, 08–14 |
| RAG 검색 | HybridRetrievalService, scope, ES sparse/dense, rrf_fuse 및 단위 테스트 존재. RRF는 순위 역수 합과 동률 정렬 사용 | 현재 frozen 별칭의 새 쓰기/복구 완료를 뜻하지 않음 | 04–07, 25, 50–56 |
| 문서 처리 | ingestion/파서/OCR/청킹/임베딩 코드, Asset와 Projection 수명주기 | DOCX/OCR 코드와 설계가 있으나 모든 OS·본래 자료 지원을 이번에 검증하지 않음 | 03–04, 08–14 |
| 생성·인용·대화 | GenerationRuntimePort, pipeline, citation/numeric 검증, conversations 및 monitoring 코드 | 실제 모델 실패/timeout/cancel·committed 경합 등 기능 마감은 기록상 남음 | 15–28, 45–48 |
| 현재 RAG P0 | 최신 WORKBOARD 2026-10-09 checkpoint58: 보호 읽기·SQL/TLS 연결 회귀 기록 | 아래 5묶음과 별칭 3하위 패키지 미완료 | 14, 28, 47, 83 |
| 학습 앱 | Platform Learning domain의 NOTE/EXPERIMENT, revision·archive 계약 존재 | 이번 Markdown 진도는 DB 자동 동기화·화면 반영 아님 | 70, 84 |
| Agents SDK | 2026-10-04 도입 준비 계획, 앱 권한/세션 정본 유지 조건 | 설치·전환·provider 호환성·본래 환경 검증 미착수로 기록됨 | 29–49 |
| 벡터 저장소·Local LLM | 동일 데이터 비교와 파인튜닝 후속 계획 | pgvector/전용 DB·Ollama·학습 런타임의 설치·실험 완료를 추정하지 않음 | 50–70 |
| Kubernetes | 2026-10-08 계획과 기존 Dockerfile/Compose 설정 | 클러스터/배포 미착수. Windows native·DPAPI 호환성 별도 조사 | 71–81 |

근거: [전체 설계](../../architecture/system-design.md), [RAG 설계](../../labs/rag/design.md), [최신 WORKBOARD](../../../WORKBOARD.md), [native 제어 기록](../../worklogs/2026-10-08-rag-control-native.md), [기능 경계 검증](../../worklogs/2026-10-07-rag-functional-boundary-verification.md), [첨부 저장·색인 구분](../../worklogs/2026-10-08-rag-personal-attachment-verification.md).

최신 기록의 상위 5묶음은 ①별칭 복구·첨부 색인 ②첫 질문/권한·취소 경합 ③실모델 실패/timeout/cancel ④DLL 재발 방지 ⑤main/원격·실행 인계다. ①의 하위 3개는 native 제출·이력 / 과거 종료·보안 전환 / receipt·release·parity·색인이다. 5와 7을 같은 단위의 진척 수로 비교하지 않는다.

ISSUE-00013은 기록상 open/r33·frozen1·receipt0이며 개인 첨부 queued attempt0가 남아 있다. 과거 34개 요청의 67개 코드 의존성을 당시 승인 source map 없이 현재 코드로 입증할 수 없다는 차단과 전체 native observer/backend/factory 미완료를 그대로 보존한다. 70PASS/3fixtureERROR 후 대상 3PASS는 단일 전체 73PASS가 아니다. 이번에는 그 검사를 재실행하지 않았다.

## 기준 문서의 시점 차이

루트 AGENTS/README의 초기 RAG 설명은 생성·DOCX/OCR을 후속으로 소개하지만 최신 RAG 설계·코드에는 관련 구현과 일부 검증 기록이 있다. README의 `/app/*`는 최신 구조 문서의 canonical `/workshop/*`와 다르며 호환 경로로 취급한다. 이번 학습 구조 작업에서는 기존 정본을 일괄 수정하지 않고 초기 범위·코드 존재·검증 기록·기능 완료를 나누어 인용한다. 충돌을 제품 구현 변경의 근거로 삼지 않는다.

개발 순서: [SDK 도입](../../superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md) → [벡터 저장소/로컬 LLM](../../superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md) → [Kubernetes](../../superpowers/plans/2026-10-08-kubernetes-learning.md), 모두 기존 RAG 마감 뒤의 추가 개발이다. 학습은 읽기·합성 사례로 선행할 수 있다.

## 코드 읽기 인덱스

아래는 curriculum의 약어를 실제 파일로 연결한 것이다. 미래 기술 학습에서 기존 포트에 연결했다는 것은 비교 기준이라는 뜻이며 실제 통합됐다는 뜻이 아니다. REGISTRY의 프로파일과 모델 버전 계약은 [RAG 모델 도메인](../../../backend/src/ai_workshop/labs/rag/models/domain.py)과 [배포 도메인](../../../backend/src/ai_workshop/labs/rag/deployments/domain.py)을 함께 읽는다.

| 키 | 읽을 파일 |
|---|---|
| SYS | [docs/architecture/system-design.md](../../../docs/architecture/system-design.md) |
| PIPE | [backend/src/ai_workshop/labs/rag/search/pipeline.py](../../../backend/src/ai_workshop/labs/rag/search/pipeline.py) |
| CONV | [backend/src/ai_workshop/labs/rag/conversations/service.py](../../../backend/src/ai_workshop/labs/rag/conversations/service.py) |
| TRACE | [backend/src/ai_workshop/labs/rag/executions/observer.py](../../../backend/src/ai_workshop/labs/rag/executions/observer.py) |
| ASSET | [backend/src/ai_workshop/platform/assets/models.py](../../../backend/src/ai_workshop/platform/assets/models.py) |
| INGEST | [backend/src/ai_workshop/labs/rag/ingestion/service.py](../../../backend/src/ai_workshop/labs/rag/ingestion/service.py) |
| CHUNK | [backend/src/ai_workshop/labs/rag/chunking/service.py](../../../backend/src/ai_workshop/labs/rag/chunking/service.py) |
| HIGHLIGHT | [backend/src/ai_workshop/labs/rag/highlighting/service.py](../../../backend/src/ai_workshop/labs/rag/highlighting/service.py) |
| ES | [backend/src/ai_workshop/labs/rag/retrieval/elasticsearch.py](../../../backend/src/ai_workshop/labs/rag/retrieval/elasticsearch.py) |
| RETR | [backend/src/ai_workshop/labs/rag/retrieval/service.py](../../../backend/src/ai_workshop/labs/rag/retrieval/service.py) |
| RRF | [backend/src/ai_workshop/labs/rag/retrieval/rrf.py](../../../backend/src/ai_workshop/labs/rag/retrieval/rrf.py) |
| SCOPE | [backend/src/ai_workshop/labs/rag/retrieval/scope.py](../../../backend/src/ai_workshop/labs/rag/retrieval/scope.py) |
| DB | [backend/src/ai_workshop/shared/db.py](../../../backend/src/ai_workshop/shared/db.py) |
| INGREP | [backend/src/ai_workshop/labs/rag/ingestion/repository.py](../../../backend/src/ai_workshop/labs/rag/ingestion/repository.py) |
| LOCK | [backend/src/ai_workshop/labs/rag/ingestion/locking.py](../../../backend/src/ai_workshop/labs/rag/ingestion/locking.py) |
| WORKER | [backend/src/ai_workshop/worker.py](../../../backend/src/ai_workshop/worker.py) |
| JOBS | [backend/src/ai_workshop/platform/jobs/domain.py](../../../backend/src/ai_workshop/platform/jobs/domain.py) |
| DISPATCH | [backend/src/ai_workshop/labs/rag/ingestion/dispatch.py](../../../backend/src/ai_workshop/labs/rag/ingestion/dispatch.py) |
| FENCE | [backend/src/ai_workshop/labs/rag/indexing/write_fence.py](../../../backend/src/ai_workshop/labs/rag/indexing/write_fence.py) |
| RECOVERY | [backend/src/ai_workshop/labs/rag/indexing/alias_recovery.py](../../../backend/src/ai_workshop/labs/rag/indexing/alias_recovery.py) |
| EMBED | [backend/src/ai_workshop/labs/rag/embeddings/sentence_transformers.py](../../../backend/src/ai_workshop/labs/rag/embeddings/sentence_transformers.py) |
| REGISTRY | [backend/src/ai_workshop/labs/rag/models/domain.py](../../../backend/src/ai_workshop/labs/rag/models/domain.py) |
| CONTEXT | [backend/src/ai_workshop/labs/rag/highlighting/context.py](../../../backend/src/ai_workshop/labs/rag/highlighting/context.py) |
| GENPORT | [backend/src/ai_workshop/labs/rag/generation/contracts.py](../../../backend/src/ai_workshop/labs/rag/generation/contracts.py) |
| CITATION | [backend/src/ai_workshop/labs/rag/generation/citation_validation.py](../../../backend/src/ai_workshop/labs/rag/generation/citation_validation.py) |
| BUDGET | [backend/src/ai_workshop/labs/rag/models/budget_trace.py](../../../backend/src/ai_workshop/labs/rag/models/budget_trace.py) |
| STRUCT | [backend/src/ai_workshop/labs/rag/generation/structured_output_v3.py](../../../backend/src/ai_workshop/labs/rag/generation/structured_output_v3.py) |
| NUMERIC | [backend/src/ai_workshop/labs/rag/generation/numeric_validation.py](../../../backend/src/ai_workshop/labs/rag/generation/numeric_validation.py) |
| EXACT | [backend/src/ai_workshop/labs/rag/generation/exact_values.py](../../../backend/src/ai_workshop/labs/rag/generation/exact_values.py) |
| INTEGRITY | [backend/src/ai_workshop/labs/rag/generation/integrity.py](../../../backend/src/ai_workshop/labs/rag/generation/integrity.py) |
| METRICS | [backend/src/ai_workshop/labs/rag/evaluation/metrics.py](../../../backend/src/ai_workshop/labs/rag/evaluation/metrics.py) |
| EVAL | [backend/src/ai_workshop/labs/rag/evaluation/service.py](../../../backend/src/ai_workshop/labs/rag/evaluation/service.py) |
| GENEVAL | [backend/src/ai_workshop/labs/rag/evaluation/generative.py](../../../backend/src/ai_workshop/labs/rag/evaluation/generative.py) |
| POLICY | [backend/src/ai_workshop/labs/rag/policies/domain.py](../../../backend/src/ai_workshop/labs/rag/policies/domain.py) |
| SDKPLAN | [docs/superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md](../../../docs/superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md) |
| CODEX | [backend/src/ai_workshop/labs/rag/generation/codex_execution.py](../../../backend/src/ai_workshop/labs/rag/generation/codex_execution.py) |
| ROLES | [docs/project-agents/README.md](../../../docs/project-agents/README.md) |
| VECTORPLAN | [docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md) |
| COMPAT | [backend/src/ai_workshop/labs/rag/generation/openai_compatible.py](../../../backend/src/ai_workshop/labs/rag/generation/openai_compatible.py) |
| LEARN | [backend/src/ai_workshop/platform/learning/domain.py](../../../backend/src/ai_workshop/platform/learning/domain.py) |
| K8PLAN | [docs/superpowers/plans/2026-10-08-kubernetes-learning.md](../../../docs/superpowers/plans/2026-10-08-kubernetes-learning.md) |
| DOCKER | [backend/Dockerfile](../../../backend/Dockerfile) |
| COMPOSE | [infrastructure/compose/compose.yaml](../../../infrastructure/compose/compose.yaml) |
| CONFIG | [backend/src/ai_workshop/config.py](../../../backend/src/ai_workshop/config.py) |

## 대표 읽기 흐름

- 수신: conversations/service → search/pipeline → retrieval/service → sparse/dense adapters → RRF → highlighting/context → GenerationRuntimePort → citation/numeric 검증 → 세션·실행 저장.
- 처리: Platform Asset 검증 → READY/active source → ingestion job/handoff → outbox/Redis/Celery → 파싱/청킹/임베딩/색인 → provenance/alias → Projection READY.
- 평가: 고정 질문·자료 snapshot → 동일 검색/생성 코어 → 규칙 판정과 의미 판정 → 실패/지연 포함 비교 → 명시적 후보 승인.

코드 읽기를 시작할 때 실제 호출 순서와 실패 분기를 재확인한다. 현재 파일은 다른 RAG 작업이 수정 중이므로 줄 번호를 고정하지 않았다.
