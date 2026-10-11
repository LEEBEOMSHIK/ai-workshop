# 84일 날짜별 커리큘럼

2026-10-12–2027-01-03, Asia/Seoul 매일 21시 전후. 계획일은 고정 기준이며 실제 학습일은 [진도](progress.md)에 따로 기록한다. 모든 항목은 아직 미시작이다. [일일 절차](README.md)와 [기록 템플릿](daily-template.md)을 함께 사용한다.

이론 칸은 그날 설명해야 할 핵심 개념이며 완성된 교재 본문은 아니다. 코드 연결은 읽을 구현 또는 비교 경계다. Transformer·MCP·새 SDK·벡터 DB·Ollama·학습·Kubernetes가 이 저장소에 모두 구현됐다는 뜻은 아니다. 새 기술의 공식 자료는 [읽기 자료](sources.md)에서 확인하고 실행 API/버전은 해당 학습일에 재확인한다.

실습은 모두 **읽기/손계산/종이 추적/문서 안 의사코드**로 완수할 수 있다. 실제 코드 작성·실행·설치·모델 호출·서비스 변경은 이번 승인에 포함되지 않으며, 필요하면 정확한 대상과 승인 여부를 일일 기록에 먼저 남긴다.

## 1주 — 프로젝트와 검색 기준선

### Day 01 | 2026-10-12 | 프로젝트 지도와 학습 기준선

- 목표: 개발 상태와 학습 상태를 분리한다.
- 원리: 구현 코드의 존재, 실행 상태, 기능 완료는 각각 다른 증거가 필요하다.
- 이론: 모듈형 모놀리스, 의존성 역전, 증거의 범위.
- 내부 구조·데이터 흐름: 화면 → API → 서비스 → 어댑터 → 저장소.
- 실제 코드 연결: [SYS](../../../docs/architecture/system-design.md) · [PIPE](../../../backend/src/ai_workshop/labs/rag/search/pipeline.py).
- 실습: 공개·비공개·관리자 경계와 미완료 5묶음을 종이에 표시한다.
- 검증 기준: 서비스 정상 응답이 RAG 전체 완료를 뜻하지 않는 이유 2개를 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 02 — 한 질문의 전체 경로. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 02 | 2026-10-13 | 한 질문의 전체 경로

- 목표: 검색과 생성의 책임을 구별한다.
- 원리: 검색은 근거 후보를 찾고 생성은 선택된 근거로 답변을 만들며 검증이 저장 가능 여부를 판정한다.
- 이론: request/turn/execution 식별성과 단계 관측.
- 내부 구조·데이터 흐름: 대화 접수 → 범위 확인 → 검색 → 근거 → 생성 → 검증 → 저장.
- 실제 코드 연결: [PIPE](../../../backend/src/ai_workshop/labs/rag/search/pipeline.py) · [CONV](../../../backend/src/ai_workshop/labs/rag/conversations/service.py) · [TRACE](../../../backend/src/ai_workshop/labs/rag/executions/observer.py).
- 실습: 합성 질문 하나를 함수 호출 화살표로 추적한다.
- 검증 기준: 각 단계의 입력·출력·실패 상태를 7칸 표로 작성한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 03 — 문서와 근거의 수명주기. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 03 | 2026-10-14 | 문서와 근거의 수명주기

- 목표: Asset READY와 Projection READY를 구분한다.
- 원리: 원본의 무결성 확인과 검색 가능한 파생본의 완성은 별도 상태 전이다.
- 이론: 불변 버전, active pointer, provenance.
- 내부 구조·데이터 흐름: 저장 → 무결성 확인 → Asset READY → 파싱/색인 → Projection READY.
- 실제 코드 연결: [ASSET](../../../backend/src/ai_workshop/platform/assets/models.py) · [INGEST](../../../backend/src/ai_workshop/labs/rag/ingestion/service.py).
- 실습: 늦게 도착한 v1과 먼저 활성화된 v2의 처리 순서를 그린다.
- 검증 기준: READY인데 검색 불가한 사례와 stale 작업 거절 이유를 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 04 — 청킹과 원문 위치. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 04 | 2026-10-15 | 청킹과 원문 위치

- 목표: 검색 단위와 원문 위치가 연결되는 원리를 익힌다.
- 원리: 청크를 작게 나눠도 원문 버전과 구조 위치를 잃으면 검증 가능한 근거가 되지 못한다.
- 이론: 구조 청킹, overlap, offset, 표 머리글 보존.
- 내부 구조·데이터 흐름: 구조 요소 → 청크 → 원문 span → viewer.
- 실제 코드 연결: [CHUNK](../../../backend/src/ai_workshop/labs/rag/chunking/service.py) · [HIGHLIGHT](../../../backend/src/ai_workshop/labs/rag/highlighting/service.py).
- 실습: 공개 합성 문단·표를 3청크로 나누고 offset을 표시한다.
- 검증 기준: 문장 일부만 인용해도 원문 위치가 복원되며 표 맥락 손실을 지적한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 05 — BM25 기준선. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 05 | 2026-10-16 | BM25 기준선

- 목표: 희소 검색의 점수 요인을 설명한다.
- 원리: 희귀어는 구분력이 크지만 반복 횟수의 이득은 포화되며 문서 길이가 점수에 영향을 준다.
- 이론: TF 포화, IDF, 문서 길이 정규화.
- 내부 구조·데이터 흐름: 질의 토큰 → 역색인 후보 → BM25 순위.
- 실제 코드 연결: [ES](../../../backend/src/ai_workshop/labs/rag/retrieval/elasticsearch.py) · [RETR](../../../backend/src/ai_workshop/labs/rag/retrieval/service.py).
- 실습: 합성 문서 3개에서 희귀어와 반복어의 영향 방향을 예측한다.
- 검증 기준: 같은 단어 횟수라도 길이에 따라 순위가 달라지는 이유를 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 06 — Dense와 RRF. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 06 | 2026-10-17 | Dense와 RRF

- 목표: 점수 대신 순위를 결합하는 이유를 이해한다.
- 원리: 서로 다른 점수 척도의 결과를 순위로 변환하면 순위 기여를 같은 방식으로 합칠 수 있다.
- 이론: 코사인 유사도, bi-encoder, RRF 합 1/(k+rank).
- 내부 구조·데이터 흐름: 질의 벡터 → dense 순위 + BM25 순위 → 융합.
- 실제 코드 연결: [RRF](../../../backend/src/ai_workshop/labs/rag/retrieval/rrf.py) · [RETR](../../../backend/src/ai_workshop/labs/rag/retrieval/service.py).
- 실습: A/B/C 두 순위표를 k=60으로 손계산하고 중복 ID를 확인한다.
- 검증 기준: 원점수를 직접 합치지 않는 이유와 동률 정렬 기준을 코드로 찾는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 07 — 1주 복습: 권한 있는 검색. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 07 | 2026-10-18 | 1주 복습: 권한 있는 검색

- 목표: 검색 범위와 결과 추적을 독립적으로 설명한다.
- 원리: 허용되지 않은 문서는 검색 후보를 구성하기 전에 제외해야 한다.
- 이론: pre-filter, 최소 권한, 불변 청크 식별성.
- 내부 구조·데이터 흐름: 사용자/공간 → 허용 scope → sparse/dense → 근거.
- 실제 코드 연결: [SCOPE](../../../backend/src/ai_workshop/labs/rag/retrieval/scope.py) · [RETR](../../../backend/src/ai_workshop/labs/rag/retrieval/service.py).
- 실습: 비허용 문서가 상위인 합성 반례와 1주 흐름도를 만든다.
- 검증 기준: 검색 후 숨김만으로 부족함을 설명하고 Day01–06 질문을 다시 답한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 08 — PostgreSQL과 데이터 모델. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

## 2주 — 데이터·트랜잭션·비동기 복구

### Day 08 | 2026-10-19 | PostgreSQL과 데이터 모델

- 목표: 관계형 정본과 검색 projection을 구별한다.
- 원리: 관계형 제약은 상태의 일관성을 보조하고 검색 인덱스는 정본에서 파생된 조회 구조로 관리한다.
- 이론: PK/FK, 제약, 정규화, 파생 데이터.
- 내부 구조·데이터 흐름: 문서 행 → 버전 행 → projection 행 → 검색 인덱스.
- 실제 코드 연결: [DB](../../../backend/src/ai_workshop/shared/db.py) · [ASSET](../../../backend/src/ai_workshop/platform/assets/models.py) · [INGEST](../../../backend/src/ai_workshop/labs/rag/ingestion/service.py).
- 실습: ORM에서 참조 관계를 읽고 최소 ER 그림을 작성한다.
- 검증 기준: DB 정본과 ES 재구성 대상, 보존할 원본을 각각 짚는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 09 — 트랜잭션과 원자성. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 09 | 2026-10-20 | 트랜잭션과 원자성

- 목표: 첫 질문 접수의 원자적 경계를 이해한다.
- 원리: 한 트랜잭션의 변경은 함께 확정되지만 다른 시스템의 부작용까지 자동으로 원자적이 되지는 않는다.
- 이론: ACID, commit/rollback, 외부 부작용.
- 내부 구조·데이터 흐름: 초안/세션/첫 turn 준비 → commit → 후속 실행.
- 실제 코드 연결: [CONV](../../../backend/src/ai_workshop/labs/rag/conversations/service.py) · [DB](../../../backend/src/ai_workshop/shared/db.py).
- 실습: commit 전후 실패 3지점을 종이 타임라인에 넣는다.
- 검증 기준: DB rollback이 이미 전송된 외부 요청까지 취소하지 않음을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 10 — MVCC와 동시성. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 10 | 2026-10-21 | MVCC와 동시성

- 목표: 읽기 격리와 경합의 차이를 설명한다.
- 원리: 읽은 뒤 다른 실행이 상태를 바꿀 수 있으므로 쓸 때 최신 revision이나 잠금 조건을 확인한다.
- 이론: snapshot, isolation, lost update, revision.
- 내부 구조·데이터 흐름: 연결 A 읽기 → 연결 B 갱신 → A 조건부 쓰기.
- 실제 코드 연결: [CONV](../../../backend/src/ai_workshop/labs/rag/conversations/service.py) · [INGREP](../../../backend/src/ai_workshop/labs/rag/ingestion/repository.py).
- 실습: 두 연결의 stale revision 시나리오를 표로 추적한다.
- 검증 기준: READ ONLY fixture 성공과 실제 committed 경합 검증을 구분한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 11 — 잠금 순서와 멱등성. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 11 | 2026-10-22 | 잠금 순서와 멱등성

- 목표: 재시도에 안전한 상태 전이를 설명한다.
- 원리: 같은 잠금 순서가 교착 위험을 줄이고 멱등 키가 동일 명령의 중복 효과를 막는다.
- 이론: row lock, deadlock, idempotency key.
- 내부 구조·데이터 흐름: RAG Job → Platform Job → Projection → Asset Version → Document → profile/build.
- 실제 코드 연결: [LOCK](../../../backend/src/ai_workshop/labs/rag/ingestion/locking.py) · [INGREP](../../../backend/src/ai_workshop/labs/rag/ingestion/repository.py).
- 실습: 같은 명령이 두 번 전달되는 사례와 역순 잠금 반례를 그린다.
- 검증 기준: 잠금 순서 정본과 exact 버전 검사 지점을 찾아 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 12 — Redis와 Celery. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 12 | 2026-10-23 | Redis와 Celery

- 목표: 큐와 영속 작업 정본의 역할을 구별한다.
- 원리: 메시지가 다시 전달될 수 있으므로 worker는 중복 실행을 정상적인 입력 조건으로 다뤄야 한다.
- 이론: broker, acknowledgement, at-least-once, redelivery.
- 내부 구조·데이터 흐름: DB 작업 → dispatch → Redis → worker → DB 상태.
- 실제 코드 연결: [WORKER](../../../backend/src/ai_workshop/worker.py) · [JOBS](../../../backend/src/ai_workshop/platform/jobs/domain.py).
- 실습: worker가 ack 전에 멈춘 합성 사례의 재전달 결과를 예상한다.
- 검증 기준: Redis 메시지 유무만으로 작업 성공을 판단할 수 없는 이유를 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 13 — Outbox와 beat 복구. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 13 | 2026-10-24 | Outbox와 beat 복구

- 목표: DB와 broker 사이 유실을 어떻게 줄이는지 이해한다.
- 원리: DB에 남은 전달 의도를 다시 읽으면 commit과 broker 전송 사이의 손실을 복구할 수 있다.
- 이론: outbox, reconciliation, retry 분류.
- 내부 구조·데이터 흐름: commit → outbox claim → publish → worker / beat 재확인.
- 실제 코드 연결: [DISPATCH](../../../backend/src/ai_workshop/labs/rag/ingestion/dispatch.py) · [WORKER](../../../backend/src/ai_workshop/worker.py).
- 실습: publish 전 실패·ACK 유실·영구 오류를 세 갈래로 분류한다.
- 검증 기준: 재시도 가능 오류와 checksum 영구 실패를 구별한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 14 — 2주 복습: 별칭 차단 읽기. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 14 | 2026-10-25 | 2주 복습: 별칭 차단 읽기

- 목표: 안전 gate와 실제 종료 증거를 구별한다.
- 원리: 관측상 조용한 상태는 과거 쓰기 실행이 다시 살아날 수 없다는 증거와 다르다.
- 이론: fencing, receipt, 상태 관측과 종료 proof.
- 내부 구조·데이터 흐름: 미종료 요청 → frozen → 종료 증거 → receipt → parity.
- 실제 코드 연결: [FENCE](../../../backend/src/ai_workshop/labs/rag/indexing/write_fence.py) · [RECOVERY](../../../backend/src/ai_workshop/labs/rag/indexing/alias_recovery.py).
- 실습: 현재 ISSUE-00013 기록으로 충족/미충족 체크표만 작성한다.
- 검증 기준: health200·프로세스 부재·재시작이 종료 proof가 아닌 이유를 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 15 — ML과 DL의 기본 단위. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

## 3주 — ML·LLM·Transformer 원리

### Day 15 | 2026-10-26 | ML과 DL의 기본 단위

- 목표: 모델 학습과 추론을 구분한다.
- 원리: 학습은 오차를 줄이도록 파라미터를 갱신하고 추론은 주어진 파라미터로 출력을 계산한다.
- 이론: 특징, 파라미터, 손실, gradient, 신경망.
- 내부 구조·데이터 흐름: 데이터 → forward → loss → gradient → update.
- 실제 코드 연결: [EMBED](../../../backend/src/ai_workshop/labs/rag/embeddings/sentence_transformers.py) · [REGISTRY](../../../backend/src/ai_workshop/labs/rag/models/domain.py).
- 실습: 스칼라 선형 모델의 예측 오차와 한 번의 갱신을 손계산한다.
- 검증 기준: 학습과 추론에서 바뀌는 값·고정되는 값을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 16 — 토큰과 Embedding. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 16 | 2026-10-27 | 토큰과 Embedding

- 목표: 문자·토큰·벡터의 차이를 설명한다.
- 원리: 토큰 식별자를 수치 표현으로 바꾸지만 토큰 수와 벡터 차원은 다른 축이다.
- 이론: tokenization, vocabulary, lookup, contextual representation.
- 내부 구조·데이터 흐름: 문자열 → token IDs → embedding 행렬.
- 실제 코드 연결: [EMBED](../../../backend/src/ai_workshop/labs/rag/embeddings/sentence_transformers.py) · [CONTEXT](../../../backend/src/ai_workshop/labs/rag/highlighting/context.py).
- 실습: 같은 한국어 문장을 문자 수와 토큰 수가 다를 수 있는 사례로 분석한다.
- 검증 기준: embedding 차원과 token 길이를 혼동하지 않고 budget의 단위를 말한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 17 — Attention 손계산. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 17 | 2026-10-28 | Attention 손계산

- 목표: Q/K/V가 하는 일을 이해한다.
- 원리: query와 key의 적합도로 가중치를 정해 value를 섞으므로 입력 간 관계가 출력에 반영된다.
- 이론: scaled dot-product, softmax, attention mask.
- 내부 구조·데이터 흐름: X → Q/K/V → QKᵀ/√d → softmax → 가중 V.
- 실제 코드 연결: [EMBED](../../../backend/src/ai_workshop/labs/rag/embeddings/sentence_transformers.py) · [GENPORT](../../../backend/src/ai_workshop/labs/rag/generation/contracts.py).
- 실습: 작은 2×2 행렬로 점수와 가중합을 계산한다.
- 검증 기준: 행렬 크기를 맞추고 mask가 미래 토큰 접근을 막는 이유를 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 18 — Transformer 구조. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 18 | 2026-10-29 | Transformer 구조

- 목표: Attention과 FFN·잔차의 역할을 연결한다.
- 원리: attention의 정보 혼합과 FFN의 변환을 잔차 경로로 반복해 표현을 갱신한다.
- 이론: multi-head, positional information, residual, normalization.
- 내부 구조·데이터 흐름: embedding → attention → FFN → 반복 block → 출력.
- 실제 코드 연결: [EMBED](../../../backend/src/ai_workshop/labs/rag/embeddings/sentence_transformers.py) · [GENPORT](../../../backend/src/ai_workshop/labs/rag/generation/contracts.py).
- 실습: encoder와 decoder의 블록 그림을 비교한다.
- 검증 기준: 검색 encoder와 생성 decoder의 출력 목적 차이를 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 19 — LLM의 학습 목적. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 19 | 2026-10-30 | LLM의 학습 목적

- 목표: 다음 토큰 예측과 사실 정확성을 구별한다.
- 원리: 다음 토큰의 통계적 가능성을 높이는 목표만으로 답변의 사실성과 근거 지지를 보장하지 못한다.
- 이론: autoregressive factorization, cross-entropy, pretraining.
- 내부 구조·데이터 흐름: prefix → token distribution → loss 또는 다음 토큰.
- 실제 코드 연결: [GENPORT](../../../backend/src/ai_workshop/labs/rag/generation/contracts.py) · [CITATION](../../../backend/src/ai_workshop/labs/rag/generation/citation_validation.py).
- 실습: 확률 높은 문장이 근거 없는 답변인 합성 반례를 만든다.
- 검증 기준: 유창함과 사실 근거 검증이 별도라는 점을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 20 — 추론과 context budget. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 20 | 2026-10-31 | 추론과 context budget

- 목표: 지연·토큰·문맥 예산의 관계를 설명한다.
- 원리: 유한한 입력 예산에서 어떤 근거를 남기는지가 생성 품질에 영향을 주므로 누락을 관측해야 한다.
- 이론: prefill/decode, KV cache, truncation, sampling.
- 내부 구조·데이터 흐름: 근거 선택 → 입력 budget → prefill → decode → 출력.
- 실제 코드 연결: [CONTEXT](../../../backend/src/ai_workshop/labs/rag/highlighting/context.py) · [BUDGET](../../../backend/src/ai_workshop/labs/rag/models/budget_trace.py).
- 실습: 작은 근거 목록을 예산 안에 배치하고 누락 근거를 기록한다.
- 검증 기준: 문맥 확장이 정답 향상을 보장하지 않는 이유와 필요한 측정을 제시한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 21 — 3주 복습: 임베딩 평가. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 21 | 2026-11-01 | 3주 복습: 임베딩 평가

- 목표: 벡터가 유사한 것과 정답 근거인 것을 분리한다.
- 원리: 의미 유사도는 관련성 신호이며 특정 질문의 정답 근거인지 여부는 별도로 평가한다.
- 이론: contrastive learning, cosine, query/document 역할.
- 내부 구조·데이터 흐름: 질의/문서 encoder → 유사도 → 순위 → relevance 판단.
- 실제 코드 연결: [EMBED](../../../backend/src/ai_workshop/labs/rag/embeddings/sentence_transformers.py) · [RRF](../../../backend/src/ai_workshop/labs/rag/retrieval/rrf.py).
- 실습: 긍정/부정 합성 문서 쌍을 설계하고 2차원 코사인을 계산한다.
- 검증 기준: 모델·차원·청킹 변경 때 새 색인이 필요한 이유를 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 22 — 근거 제한 생성. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

## 4주 — 생성·인용·대화·RAG 평가

### Day 22 | 2026-11-02 | 근거 제한 생성

- 목표: 허용 근거만 답변에 쓰는 경계를 이해한다.
- 원리: 검색된 정보라도 현재 허용된 근거가 부족하면 답을 만들어내지 않고 부족 상태를 반환한다.
- 이론: grounding, abstention, context selection.
- 내부 구조·데이터 흐름: 검색 후보 → 허용 근거 → prompt → 생성 초안.
- 실제 코드 연결: [PIPE](../../../backend/src/ai_workshop/labs/rag/search/pipeline.py) · [GENPORT](../../../backend/src/ai_workshop/labs/rag/generation/contracts.py).
- 실습: 답이 없는 합성 질문에서 근거 부족 응답 조건을 적는다.
- 검증 기준: 검색 실패·생성 실패·근거 부족을 세 상태로 구별한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 23 — 구조 출력과 인용. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 23 | 2026-11-03 | 구조 출력과 인용

- 목표: 문법적 적합성과 의미적 지지를 구별한다.
- 원리: 형식이 올바른 출력도 원문과 연결되지 않거나 주장을 지지하지 않으면 검증에 실패한다.
- 이론: schema validation, citation binding, claim support.
- 내부 구조·데이터 흐름: 구조 출력 → schema → 근거 ID/span → 주장 검증.
- 실제 코드 연결: [STRUCT](../../../backend/src/ai_workshop/labs/rag/generation/structured_output_v3.py) · [CITATION](../../../backend/src/ai_workshop/labs/rag/generation/citation_validation.py).
- 실습: JSON 모양은 맞지만 근거가 틀린 예를 설계한다.
- 검증 기준: 구조 출력 통과만으로 정상 답변 저장이 불가능함을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 24 — 숫자·날짜와 계산 근거. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 24 | 2026-11-04 | 숫자·날짜와 계산 근거

- 목표: 표기 정규화와 새 계산을 구별한다.
- 원리: 표기만 같은 값으로 정규화하는 일과 새 값을 계산해 증명하는 일은 분리해야 한다.
- 이론: canonicalization, unit/sign, source-backed calculation.
- 내부 구조·데이터 흐름: 원문 값 → catalogue → 계산 proof → 검증 receipt.
- 실제 코드 연결: [NUMERIC](../../../backend/src/ai_workshop/labs/rag/generation/numeric_validation.py) · [EXACT](../../../backend/src/ai_workshop/labs/rag/generation/exact_values.py).
- 실습: 합성 10%→12%의 변화와 2%p를 구분하고 원문 위치를 붙인다.
- 검증 기준: 값·단위·부호가 바뀐 오류를 찾고 실제 품질과 산술 통과를 구분한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 25 — 대화·Memory·현재 권한. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 25 | 2026-11-05 | 대화·Memory·현재 권한

- 목표: 저장 이력과 매 요청 사용 가능한 이력을 구별한다.
- 원리: 저장 시 허용됐던 문서가 지금도 허용된다고 가정할 수 없으므로 이력을 다시 제한한다.
- 이론: session state, scope revision, memory invalidation.
- 내부 구조·데이터 흐름: 저장된 turn → 현재 권한 검사 → 허용 문맥 → 후속 질문.
- 실제 코드 연결: [CONV](../../../backend/src/ai_workshop/labs/rag/conversations/service.py) · [INTEGRITY](../../../backend/src/ai_workshop/labs/rag/generation/integrity.py).
- 실습: 문서 권한 철회 뒤 예전 답변을 다시 사용하는 반례를 작성한다.
- 검증 기준: 이력이 저장돼 있어도 모델 입력에서 제외할 이유를 찾는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 26 — 검색 평가. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 26 | 2026-11-06 | 검색 평가

- 목표: 순위 지표의 의미를 계산한다.
- 원리: 검색 지표는 같은 질문·정답 판단·top-k 조건에서 계산해야 비교 의미가 있다.
- 이론: Recall@K, MRR, nDCG, judgment set.
- 내부 구조·데이터 흐름: 질문/정답 집합 → 검색 순위 → 지표 → 기준선 비교.
- 실제 코드 연결: [METRICS](../../../backend/src/ai_workshop/labs/rag/evaluation/metrics.py) · [EVAL](../../../backend/src/ai_workshop/labs/rag/evaluation/service.py).
- 실습: 정답 2개가 있는 5개 순위에서 K=3 지표를 손계산한다.
- 검증 기준: 지표마다 분모와 top-k를 명시하고 BM25 기준선을 유지한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 27 — 생성 평가와 실패 측정. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 27 | 2026-11-07 | 생성 평가와 실패 측정

- 목표: 정답률과 실행 성공률을 따로 기록한다.
- 원리: 실패 시도까지 분모와 지연 기록에 포함해야 좋은 결과만 남는 선택 편향을 줄인다.
- 이론: faithfulness, answer correctness, abstention, latency.
- 내부 구조·데이터 흐름: 고정 snapshot → 같은 코어 실행 → 규칙/사람 판정 → 비교.
- 실제 코드 연결: [GENEVAL](../../../backend/src/ai_workshop/labs/rag/evaluation/generative.py) · [TRACE](../../../backend/src/ai_workshop/labs/rag/executions/observer.py).
- 실습: 성공·거절·timeout 6행의 합성 결과표를 분리 집계한다.
- 검증 기준: 실패 행을 버리면 지연/품질 비교가 왜곡됨을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 28 — 4주 복습: RAG 마감 판정. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 28 | 2026-11-08 | 4주 복습: RAG 마감 판정

- 목표: 기능 완료와 품질 개선의 경계를 설명한다.
- 원리: 품질 개선은 지속되지만 핵심 사용자 흐름과 안전한 실패 처리는 기능 완료의 별도 조건이다.
- 이론: 회귀, 독립 검증, 증거 수준, 승격 gate.
- 내부 구조·데이터 흐름: 실행 기록 → 기능 조건 → 품질 비교 → 명시 승인.
- 실제 코드 연결: [PIPE](../../../backend/src/ai_workshop/labs/rag/search/pipeline.py) · [RECOVERY](../../../backend/src/ai_workshop/labs/rag/indexing/alias_recovery.py).
- 실습: 현재 미완료 5묶음에 필요한 증거와 학습 가능 항목을 연결한다.
- 검증 기준: 자동 테스트·합성 실험·본래 환경 검증을 서로 대체하지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 29 — Tool Calling과 Function Calling. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

## 5주 — 도구·MCP·Agent Loop

### Day 29 | 2026-11-09 | Tool Calling과 Function Calling

- 목표: 모델의 도구 요청과 실제 실행 권한을 분리한다.
- 원리: 모델은 호출할 도구와 인자를 제안하고 애플리케이션이 검증·승인 후 실행한다.
- 이론: typed schema, validation, dispatch, tool result.
- 내부 구조·데이터 흐름: 모델 요청 → 입력 검증 → 허용 도구 실행 → 결과 → 모델.
- 실제 코드 연결: [GENPORT](../../../backend/src/ai_workshop/labs/rag/generation/contracts.py) · [SCOPE](../../../backend/src/ai_workshop/labs/rag/retrieval/scope.py).
- 실습: 검색 도구의 입력/출력 JSON과 거부 입력 2개를 종이에 쓴다.
- 검증 기준: 도구 요청 생성이 곧 실행 승인이 아님을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 30 — 안전한 도구 계약. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 30 | 2026-11-10 | 안전한 도구 계약

- 목표: 부작용과 중복 실행을 통제하는 경계를 정한다.
- 원리: 도구마다 권한·부작용·재시도 계약을 정해야 모델 반복이 위험한 중복 효과를 만들지 않는다.
- 이론: allowlist, deadline, idempotency, typed error.
- 내부 구조·데이터 흐름: 권한 확인 → 도구 → timeout/성공 → 감사 이벤트.
- 실제 코드 연결: [POLICY](../../../backend/src/ai_workshop/labs/rag/policies/domain.py) · [JOBS](../../../backend/src/ai_workshop/platform/jobs/domain.py).
- 실습: 읽기 도구와 쓰기 도구의 승인·재시도 표를 작성한다.
- 검증 기준: 임의 SQL/shell 대신 앱 도구만 노출해야 하는 이유를 말한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 31 — MCP 구조. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 31 | 2026-11-11 | MCP 구조

- 목표: 연결 프로토콜과 agent 정책을 구별한다.
- 원리: 표준화된 메시지 교환은 도구 연결을 돕지만 앱의 권한 정책을 대신 결정하지 않는다.
- 이론: host/client/server, JSON-RPC, capability negotiation.
- 내부 구조·데이터 흐름: host → client → server 도구 목록 → 호출 → 결과.
- 실제 코드 연결: [GENPORT](../../../backend/src/ai_workshop/labs/rag/generation/contracts.py) · [POLICY](../../../backend/src/ai_workshop/labs/rag/policies/domain.py).
- 실습: 합성 read-only 검색 서버의 메시지 왕복 그림을 그린다.
- 검증 기준: MCP 연결이 문서 권한이나 외부 전송 승인을 대체하지 않음을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 32 — MCP 경계와 신뢰. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 32 | 2026-11-12 | MCP 경계와 신뢰

- 목표: tool/resource/prompt와 비신뢰 데이터를 구분한다.
- 원리: 외부 도구나 문서의 내용은 데이터이며 더 높은 권한의 실행 지시로 승격시키지 않는다.
- 이론: protocol lifecycle, transport, authentication, injection.
- 내부 구조·데이터 흐름: 리소스/도구 결과 → 데이터 검증 → 정책 → 모델 입력.
- 실제 코드 연결: [POLICY](../../../backend/src/ai_workshop/labs/rag/policies/domain.py) · [CITATION](../../../backend/src/ai_workshop/labs/rag/generation/citation_validation.py).
- 실습: 문서 속 악성 지시를 명령으로 취급하지 않는 사례를 적는다.
- 검증 기준: 프로토콜 오류·업무 오류·권한 거절을 각각 분류한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 33 — Agent Loop. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 33 | 2026-11-13 | Agent Loop

- 목표: 반복 실행과 종료 조건을 설계한다.
- 원리: 모델과 도구의 반복은 명시적인 종료·예산·오류 조건이 있어야 제어할 수 있다.
- 이론: observe/decide/act, bounded loop, termination.
- 내부 구조·데이터 흐름: 상태 → 모델 → tool 또는 final → 상태 갱신 → 종료.
- 실제 코드 연결: [TRACE](../../../backend/src/ai_workshop/labs/rag/executions/observer.py) · [GENPORT](../../../backend/src/ai_workshop/labs/rag/generation/contracts.py).
- 실습: 최대 3회 호출의 합성 loop를 상태표로 추적한다.
- 검증 기준: 무한 재시도·예산 초과·도구 실패마다 종료 상태가 있다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 34 — State와 Memory. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 34 | 2026-11-14 | State와 Memory

- 목표: 진행 상태·대화 기억·근거 저장을 구별한다.
- 원리: 대화 기록과 현재 실행 상태는 수명이 다르며 재사용할 기억도 현재 권한에 맞아야 한다.
- 이론: ephemeral state, durable state, retrieval memory.
- 내부 구조·데이터 흐름: 현재 요청 상태 + 허용 이력 → 실행 → 검증된 저장.
- 실제 코드 연결: [CONV](../../../backend/src/ai_workshop/labs/rag/conversations/service.py) · [INTEGRITY](../../../backend/src/ai_workshop/labs/rag/generation/integrity.py).
- 실습: 무기한 기억에 권한 철회 문서가 남는 반례를 설계한다.
- 검증 기준: checkpoint와 DB 정본을 중복 소유할 때의 충돌을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 35 — 5주 복습: Orchestration. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 35 | 2026-11-15 | 5주 복습: Orchestration

- 목표: 결정적 파이프라인과 agent 선택의 경계를 정한다.
- 원리: 결정적인 계산은 코드로 유지하고 판단이 필요한 단계에만 제한된 모델 역할을 넣는다.
- 이론: workflow, branching, tools-as-agents, handoff.
- 내부 구조·데이터 흐름: 중앙 조정 → 필요한 역할 → 도구 결과 → 통합 검증.
- 실제 코드 연결: [PIPE](../../../backend/src/ai_workshop/labs/rag/search/pipeline.py) · [SDKPLAN](../../../docs/superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md).
- 실습: 간단 질문과 복잡 질문에서 역할 호출 수를 비교한다.
- 검증 기준: 파싱/BM25/RRF/권한 검사는 LLM에게 넘기지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 36 — OpenAI Agents SDK 읽기. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

## 6주 — Agents SDK와 LangChain/LangGraph

### Day 36 | 2026-11-16 | OpenAI Agents SDK 읽기

- 목표: SDK가 맡을 실행 계층을 프로젝트 경계에 배치한다.
- 원리: SDK는 반복과 도구 조정을 돕지만 앱의 문서 권한과 저장 정본 책임은 그대로 남는다.
- 이론: Agent/Runner 개념, 도구, 실행 결과.
- 내부 구조·데이터 흐름: 기존 API → 앱 권한 → SDK adapter → 앱 도구 → 저장.
- 실제 코드 연결: [SDKPLAN](../../../docs/superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md) · [GENPORT](../../../backend/src/ai_workshop/labs/rag/generation/contracts.py).
- 실습: 공식 개요와 도입 계획을 대조해 책임표를 만든다.
- 검증 기준: SDK 타입이 도메인 밖으로 새지 않는 어댑터 위치를 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 37 — SDK 세션·handoff·trace. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 37 | 2026-11-17 | SDK 세션·handoff·trace

- 목표: SDK 편의 기능과 앱의 영속 책임을 분리한다.
- 원리: 세션·handoff 편의 기능을 사용해도 현재 권한과 외부 trace 전송 경계는 따로 검증한다.
- 이론: session, handoff, guardrails, observability.
- 내부 구조·데이터 흐름: 허용 이력 → SDK 실행 → 안전 이벤트 → 기존 monitoring.
- 실제 코드 연결: [SDKPLAN](../../../docs/superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md) · [TRACE](../../../backend/src/ai_workshop/labs/rag/executions/observer.py).
- 실습: 세션 복제·외부 trace 유출의 반례와 차단 위치를 작성한다.
- 검증 기준: 기존 DB 정본·외부 trace 비활성 원칙을 유지한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 38 — SDK 호환성과 fake model. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 38 | 2026-11-18 | SDK 호환성과 fake model

- 목표: 설치 전에 검증할 계약을 구체화한다.
- 원리: 지원 기능과 인증을 확인하지 않은 provider를 같은 실행 계약으로 취급하지 않는다.
- 이론: provider capability, cancellation, structured output, usage.
- 내부 구조·데이터 흐름: fake 응답 → 반복 실행 → 실패/취소 → 결과 계약.
- 실제 코드 연결: [SDKPLAN](../../../docs/superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md) · [GENPORT](../../../backend/src/ai_workshop/labs/rag/generation/contracts.py).
- 실습: 정상·도구·잘못된 출력·취소 4개 fixture 명세를 쓴다.
- 검증 기준: Codex 로그인과 SDK API 인증이 별개임을 설명하고 미확인 항목을 남긴다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 39 — Claude Agent SDK 비교. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 39 | 2026-11-19 | Claude Agent SDK 비교

- 목표: 코딩 agent 실행과 서비스 RAG의 차이를 분석한다.
- 원리: 코딩용 실행 도구의 권한은 서비스 사용자의 문서 접근 권한보다 넓어지면 안 된다.
- 이론: 실행 도구, 권한 모드, session, hooks 개념.
- 내부 구조·데이터 흐름: 애플리케이션 → SDK loop → 허용 도구 → 실행 결과.
- 실제 코드 연결: [CODEX](../../../backend/src/ai_workshop/labs/rag/generation/codex_execution.py) · [GENPORT](../../../backend/src/ai_workshop/labs/rag/generation/contracts.py).
- 실습: 공식 문서에서 기능을 읽고 기존 provider와 책임 비교표를 만든다.
- 검증 기준: shell/file 도구가 있는 SDK를 그대로 서비스에 노출하지 않는 이유를 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 40 — LangChain 구성 요소. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 40 | 2026-11-20 | LangChain 구성 요소

- 목표: 모델·retriever·도구 조합을 기존 포트에 대응시킨다.
- 원리: 조합 도구를 바꾸더라도 검색·권한·인용 불변식을 어댑터 경계에서 유지해야 한다.
- 이론: Runnable/chain 개념, adapter, prompt composition.
- 내부 구조·데이터 흐름: 질문 → retriever → context → model → parser.
- 실제 코드 연결: [PIPE](../../../backend/src/ai_workshop/labs/rag/search/pipeline.py) · [RETR](../../../backend/src/ai_workshop/labs/rag/retrieval/service.py).
- 실습: 동일 RAG 경로를 자체 코드와 LangChain 개념 두 열로 표현한다.
- 검증 기준: 프레임워크 변경과 검색 알고리즘 변경을 분리한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 41 — LangGraph State Graph. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 41 | 2026-11-21 | LangGraph State Graph

- 목표: 분기·재개·상태 병합을 이해한다.
- 원리: 상태를 저장해 재개하더라도 이전 외부 부작용의 중복 방지는 별도 계약이 필요하다.
- 이론: node/edge, state reducer, checkpoint, interrupt.
- 내부 구조·데이터 흐름: state → node → conditional edge → checkpoint → resume.
- 실제 코드 연결: [CONV](../../../backend/src/ai_workshop/labs/rag/conversations/service.py) · [TRACE](../../../backend/src/ai_workshop/labs/rag/executions/observer.py).
- 실습: 두 노드가 같은 필드를 갱신하는 충돌을 종이로 재현한다.
- 검증 기준: checkpoint 재개가 외부 도구 중복 실행을 막아주지 않음을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 42 — 6주 복습: 실행 계층 비교. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 42 | 2026-11-22 | 6주 복습: 실행 계층 비교

- 목표: SDK 선택을 근거 있는 비교로 만든다.
- 원리: 같은 입력과 기준으로 기능·실패·비용을 비교해야 프레임워크 선택의 이유를 설명할 수 있다.
- 이론: 기능 적합성, lock/version, 유지보수, 비용 지표.
- 내부 구조·데이터 흐름: 같은 합성 요청 → 자체/SDK/graph 설계 → 차이 기록.
- 실제 코드 연결: [SDKPLAN](../../../docs/superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md) · [PIPE](../../../backend/src/ai_workshop/labs/rag/search/pipeline.py).
- 실습: OpenAI·Claude·LangChain/LangGraph·현재 코드 비교표를 작성한다.
- 검증 기준: 설치나 활성화 없이 채택 유보 이유와 다음 검증을 제시한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 43 — 멀티에이전트 분업. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

## 7주 — Multi-Agent·Harness·Sandbox·평가

### Day 43 | 2026-11-23 | 멀티에이전트 분업

- 목표: 독립 역할이 필요한 경우만 구분한다.
- 원리: 역할을 나누면 검토 관점이 늘지만 통신과 통합 비용도 생기므로 필요할 때만 분업한다.
- 이론: specialization, communication overhead, independence.
- 내부 구조·데이터 흐름: 조정자 → 독립 읽기 역할 → 결과 → 최종 검증.
- 실제 코드 연결: [ROLES](../../../docs/project-agents/README.md) · [SDKPLAN](../../../docs/superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md).
- 실습: 검색 검토와 인용 검토를 분리한 입력/출력 계약을 쓴다.
- 검증 기준: 역할 수 증가가 정답·속도 향상을 보장하지 않음을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 44 — 병렬 실행과 공유 상태. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 44 | 2026-11-24 | 병렬 실행과 공유 상태

- 목표: 동시 실행 가능한 부분과 직렬 부분을 나눈다.
- 원리: 입력이 독립인 읽기는 병렬화할 수 있어도 같은 상태의 최종 갱신은 정합성을 보장해야 한다.
- 이론: DAG, critical path, race condition, bounded concurrency.
- 내부 구조·데이터 흐름: 독립 읽기 병렬 → barrier → 동일 turn 저장 직렬.
- 실제 코드 연결: [CONV](../../../backend/src/ai_workshop/labs/rag/conversations/service.py) · [TRACE](../../../backend/src/ai_workshop/labs/rag/executions/observer.py).
- 실습: 두 역할의 늦은 결과가 최신 revision을 덮는 반례를 만든다.
- 검증 기준: 의존 단계·공유 DB 쓰기를 무조건 병렬화하지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 45 — 취소·timeout·재시도. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 45 | 2026-11-25 | 취소·timeout·재시도

- 목표: 요청 취소와 실제 실행 종료를 구별한다.
- 원리: 취소 요청 접수와 실제 외부 실행 종료는 시점과 증거가 다르다.
- 이론: deadline propagation, cancellation, late completion.
- 내부 구조·데이터 흐름: 취소 요청 → 실행 중단 확인 → cleanup → terminal.
- 실제 코드 연결: [CODEX](../../../backend/src/ai_workshop/labs/rag/generation/codex_execution.py) · [TRACE](../../../backend/src/ai_workshop/labs/rag/executions/observer.py).
- 실습: 취소 뒤 늦은 provider 응답의 상태 전이를 적는다.
- 검증 기준: cancelled UI만으로 자식 실행 종료를 입증하지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 46 — Harness와 재현성. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 46 | 2026-11-26 | Harness와 재현성

- 목표: 에이전트 실행을 둘러싼 평가 조건을 정의한다.
- 원리: 평가 결과를 재현하려면 모델뿐 아니라 도구 응답·입력·예산·환경도 고정하거나 기록해야 한다.
- 이론: task fixture, tool stub, budget, artifact, replay.
- 내부 구조·데이터 흐름: 고정 입력 → harness → agent/tool → 결과/측정.
- 실제 코드 연결: [EVAL](../../../backend/src/ai_workshop/labs/rag/evaluation/service.py) · [TRACE](../../../backend/src/ai_workshop/labs/rag/executions/observer.py).
- 실습: 합성 도구 결과와 시간 예산을 포함한 실행 명세를 만든다.
- 검증 기준: 모델·도구·자료·프로파일·버전·실패를 함께 기록한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 47 — Sandbox와 권한 경계. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 47 | 2026-11-27 | Sandbox와 권한 경계

- 목표: 지침과 기술적 격리를 구별한다.
- 원리: 지침을 따르라는 요청과 OS가 자원 접근을 막는 기술적 격리는 다른 보장이다.
- 이론: process isolation, least privilege, capability, filesystem scope.
- 내부 구조·데이터 흐름: 요청 승인 → 제한 실행 → 도구 접근 → 감사/종료.
- 실제 코드 연결: [CODEX](../../../backend/src/ai_workshop/labs/rag/generation/codex_execution.py) · [FENCE](../../../backend/src/ai_workshop/labs/rag/indexing/write_fence.py).
- 실습: Windows native·DPAPI 경계와 container 경계 차이를 그린다.
- 검증 기준: 프롬프트로 금지하는 것과 OS에서 막는 것의 증거 차이를 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 48 — Agent Evaluation. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 48 | 2026-11-28 | Agent Evaluation

- 목표: 결과 품질과 실행 경로의 안전을 같이 평가한다.
- 원리: 정답을 얻었어도 비허용 도구나 자료를 사용했다면 안전한 성공으로 판정할 수 없다.
- 이론: task success, tool correctness, policy compliance, cost.
- 내부 구조·데이터 흐름: 합성 작업 → trace → 결과 판정 + 도구/권한 판정.
- 실제 코드 연결: [GENEVAL](../../../backend/src/ai_workshop/labs/rag/evaluation/generative.py) · [TRACE](../../../backend/src/ai_workshop/labs/rag/executions/observer.py).
- 실습: 잘못된 도구 호출로 우연히 정답인 사례를 실패로 판정한다.
- 검증 기준: 본문·비밀·비공개 내부 추론 대신 안전 메타데이터만 기록한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 49 — 7주 복습: 작은 agent 설계. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 49 | 2026-11-29 | 7주 복습: 작은 agent 설계

- 목표: 현재 RAG를 손상시키지 않는 설계안을 설명한다.
- 원리: 작은 읽기 전용 설계에서 실패·권한 경계를 설명한 뒤 실제 개발 게이트를 따로 확인한다.
- 이론: bounded orchestration, current authority, fail closed.
- 내부 구조·데이터 흐름: 질문 → 1개 읽기 도구 → 근거 답변 → 앱 검증.
- 실제 코드 연결: [SDKPLAN](../../../docs/superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md) · [PIPE](../../../backend/src/ai_workshop/labs/rag/search/pipeline.py).
- 실습: 5개 정상/실패 시나리오로 종이 실행을 하고 미해결 질문을 정리한다.
- 검증 기준: SDK 개발 착수와 학습 설계 완료가 다름을 명시한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 50 — 벡터 저장소 비교 설계. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

## 8주 — Vector DB·ANN·pgvector 비교

### Day 50 | 2026-11-30 | 벡터 저장소 비교 설계

- 목표: 엔진만 바꾸는 공정한 비교를 정의한다.
- 원리: 동일 벡터·청크·필터를 고정하고 저장 엔진만 바꿔야 검색 차이의 원인을 분리할 수 있다.
- 이론: controlled experiment, baseline, 동일 snapshot.
- 내부 구조·데이터 흐름: 동일 청크/벡터 → ES/후보/pgvector → 같은 RRF.
- 실제 코드 연결: [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md) · [ES](../../../backend/src/ai_workshop/labs/rag/retrieval/elasticsearch.py).
- 실습: 바꿀 변수와 고정할 변수를 2열 표로 작성한다.
- 검증 기준: Elasticsearch도 벡터 검색 엔진이며 JSON은 별도 산출물임을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 51 — Exact kNN과 거리. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 51 | 2026-12-01 | Exact kNN과 거리

- 목표: 정확 검색을 ANN의 비교 기준으로 삼는다.
- 원리: 정확 검색은 전체 후보의 거리를 비교하므로 근사 검색이 놓친 이웃의 기준이 된다.
- 이론: L2, inner product, cosine, normalization.
- 내부 구조·데이터 흐름: 벡터 전체 거리 → 정렬 → top-k.
- 실제 코드 연결: [RETR](../../../backend/src/ai_workshop/labs/rag/retrieval/service.py) · [EMBED](../../../backend/src/ai_workshop/labs/rag/embeddings/sentence_transformers.py).
- 실습: 2차원 벡터 4개로 L2와 cosine 순위를 손계산한다.
- 검증 기준: 정규화 여부에 따른 순위 차이와 엔진 점수 변환을 명시한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 52 — ANN과 HNSW. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 52 | 2026-12-02 | ANN과 HNSW

- 목표: 근사 검색의 recall/지연 절충을 이해한다.
- 원리: 탐색 후보를 줄여 속도를 얻는 대신 정확한 최근접 이웃을 놓칠 수 있다.
- 이론: graph search, ef/M 개념, index memory.
- 내부 구조·데이터 흐름: 진입 노드 → 이웃 탐색 → 후보 집합 → top-k.
- 실제 코드 연결: [ES](../../../backend/src/ai_workshop/labs/rag/retrieval/elasticsearch.py) · [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md).
- 실습: 작은 그래프에서 후보 수를 줄일 때 놓치는 정답을 표시한다.
- 검증 기준: ANN Recall@K와 relevance Recall@K의 분모가 다름을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 53 — IVF와 압축. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 53 | 2026-12-03 | IVF와 압축

- 목표: 분할 탐색·양자화가 오차를 만드는 위치를 찾는다.
- 원리: 분할과 압축은 저장·탐색 비용을 줄이지만 경계 후보 누락과 거리 오차를 만들 수 있다.
- 이론: coarse centroid, nprobe, quantization, PQ 개념.
- 내부 구조·데이터 흐름: 벡터 → cluster → probe → 거리 근사 → 순위.
- 실제 코드 연결: [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md) · [RETR](../../../backend/src/ai_workshop/labs/rag/retrieval/service.py).
- 실습: 합성 점 6개를 두 centroid에 배정하고 놓친 경계점을 찾는다.
- 검증 기준: 메모리 감소가 정확도·갱신 비용과 교환됨을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 54 — pgvector와 PostgreSQL. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 54 | 2026-12-04 | pgvector와 PostgreSQL

- 목표: 트랜잭션 정본과 벡터 검색 결합을 검토한다.
- 원리: 벡터를 PostgreSQL에서 조회할 수 있다는 사실만으로 BM25용 Elasticsearch 제거가 정당화되지는 않는다.
- 이론: vector column, exact/ANN, SQL filter, index plan.
- 내부 구조·데이터 흐름: 권한 범위 → SQL/vector 후보 → 순위 → RRF.
- 실제 코드 연결: [DB](../../../backend/src/ai_workshop/shared/db.py) · [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md).
- 실습: 가상 SQL을 문서에만 쓰고 사전 필터 요구를 점검한다.
- 검증 기준: extension·인덱스 설치 없이 후보 설계이며 ES 제거가 아님을 명시한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 55 — 전용 벡터 DB와 필터. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 55 | 2026-12-05 | 전용 벡터 DB와 필터

- 목표: 권한·갱신·운영 비용 기준으로 후보를 좁힌다.
- 원리: 후보 엔진도 현재 허용 문서·버전 범위 안에서 검색하고 결과의 원문 추적을 유지해야 한다.
- 이론: payload filter, consistency, tenancy, deletion.
- 내부 구조·데이터 흐름: 허용 문서/버전 → engine filter → ANN → provenance.
- 실제 코드 연결: [SCOPE](../../../backend/src/ai_workshop/labs/rag/retrieval/scope.py) · [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md).
- 실습: 공식 기능 확인이 필요한 후보 평가표를 만들고 미확인을 표시한다.
- 검증 기준: 검색 후 숨김으로 권한을 보장하지 않고 stale 버전 검증을 포함한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 56 — 8주 복습: 비교 판정표. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 56 | 2026-12-06 | 8주 복습: 비교 판정표

- 목표: 같은 데이터에서 품질과 비용을 비교하도록 설계한다.
- 원리: 품질·지연·저장 비용을 같은 조건에서 측정하고 미측정 항목은 추정과 분리한다.
- 이론: p50/p95, warm/cold, recall, storage, concurrency.
- 내부 구조·데이터 흐름: 고정 질의 → 각 엔진 → 지표/실패 → 채택 유보/결정.
- 실제 코드 연결: [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md) · [METRICS](../../../backend/src/ai_workshop/labs/rag/evaluation/metrics.py).
- 실습: 가상의 숫자는 예시로 표시하고 측정 빈칸을 남긴 결과표를 만든다.
- 검증 기준: SDK·별칭 gate 완료와 저장소 실험 완료를 서로 대체하지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 57 — Local LLM과 Ollama. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

## 9주 — Local LLM·ML/DL·학습 기초

### Day 57 | 2026-12-07 | Local LLM과 Ollama

- 목표: 모델 가중치·런타임·API 어댑터를 구별한다.
- 원리: 가중치 자체와 가중치를 실행하는 런타임, 앱이 호출하는 API는 교체 경계가 다르다.
- 이론: serving, quantization, context length, device constraints.
- 내부 구조·데이터 흐름: 모델 파일 → 로컬 런타임 → API → GenerationRuntimePort.
- 실제 코드 연결: [COMPAT](../../../backend/src/ai_workshop/labs/rag/generation/openai_compatible.py) · [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md).
- 실습: 현행 openai-compatible 어댑터와 로컬 후보 연결도를 그린다.
- 검증 기준: 로컬 실행도 다운로드·설치·자원 예산 확인이 필요함을 명시한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 58 — 장치·메모리 예산. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 58 | 2026-12-08 | 장치·메모리 예산

- 목표: 실행 가능성과 성능을 추정과 측정으로 나눈다.
- 원리: 실행 메모리는 가중치 외에도 문맥 cache와 활성값·런타임 공간을 포함한다.
- 이론: parameter bytes, KV cache, batch, CPU/GPU.
- 내부 구조·데이터 흐름: 가중치 + cache + activation → 메모리/시간.
- 실제 코드 연결: [REGISTRY](../../../backend/src/ai_workshop/labs/rag/models/domain.py) · [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md).
- 실습: 가상 파라미터 수×비트 수를 계산하고 추가 메모리를 적는다.
- 검증 기준: 양자화 가중치 크기만으로 총 메모리를 판정하지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 59 — 지도 학습과 데이터 분리. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 59 | 2026-12-09 | 지도 학습과 데이터 분리

- 목표: 데이터 누수를 막는 평가 분리를 설계한다.
- 원리: 서로 비슷한 문서나 질문이 학습과 시험에 함께 있으면 새로운 자료에 대한 성능을 과대평가할 수 있다.
- 이론: train/validation/test, group split, distribution shift.
- 내부 구조·데이터 흐름: 원본 → 권한/정제 → 문서별 split → 학습/평가.
- 실제 코드 연결: [EVAL](../../../backend/src/ai_workshop/labs/rag/evaluation/service.py) · [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md).
- 실습: 같은 문서의 유사 질문이 양쪽 split에 들어간 누수 사례를 찾는다.
- 검증 기준: 최종 test로 프롬프트·하이퍼파라미터를 반복 조정하지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 60 — Loss와 역전파. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 60 | 2026-12-10 | Loss와 역전파

- 목표: 학습의 한 단계가 바꾸는 값을 설명한다.
- 원리: 연쇄 미분으로 손실에 대한 각 파라미터의 영향을 계산하고 학습률로 갱신 크기를 조절한다.
- 이론: chain rule, gradient descent, learning rate.
- 내부 구조·데이터 흐름: prediction → loss → backward → optimizer step.
- 실제 코드 연결: [EMBED](../../../backend/src/ai_workshop/labs/rag/embeddings/sentence_transformers.py) · [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md).
- 실습: 단순 제곱 오차의 gradient를 손계산한다.
- 검증 기준: gradient 크기·방향과 학습률의 역할을 분리한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 61 — Overfitting과 일반화. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 61 | 2026-12-11 | Overfitting과 일반화

- 목표: 훈련 점수 향상과 실제 개선을 구별한다.
- 원리: 훈련 오차 감소가 검증 오차 감소와 함께 가지 않으면 학습 데이터에 과도하게 맞춘 것일 수 있다.
- 이론: bias/variance, regularization, early stopping.
- 내부 구조·데이터 흐름: epoch별 train/validation loss → 선택 → 고정 test.
- 실제 코드 연결: [EVAL](../../../backend/src/ai_workshop/labs/rag/evaluation/service.py) · [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md).
- 실습: 합성 학습 곡선을 그려 과적합 시작 지점을 표시한다.
- 검증 기준: validation 선택과 test 보고가 분리되고 실패 모델도 기록된다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 62 — PEFT·LoRA·QLoRA. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 62 | 2026-12-12 | PEFT·LoRA·QLoRA

- 목표: 전체 학습과 저랭크 적응의 차이를 이해한다.
- 원리: 기반 가중치를 고정하고 작은 저랭크 변경만 학습해 조정할 파라미터 수를 줄일 수 있다.
- 이론: frozen backbone, low-rank update, quantized base.
- 내부 구조·데이터 흐름: 고정 W + 작은 ΔW → forward/loss → adapter 갱신.
- 실제 코드 연결: [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md) · [REGISTRY](../../../backend/src/ai_workshop/labs/rag/models/domain.py).
- 실습: 행렬 크기로 full update와 저랭크 parameter 수를 비교한다.
- 검증 기준: 파인튜닝이 새 문서 지식의 정확한 검색을 대체하지 않음을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 63 — 9주 복습: 로컬 실험 계약. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 63 | 2026-12-13 | 9주 복습: 로컬 실험 계약

- 목표: 다운로드 전 확인할 데이터·모델·환경 조건을 정리한다.
- 원리: 장치와 라이선스·자료 권한이 준비되지 않은 모델 후보는 실행 가능한 모델로 단정하지 않는다.
- 이론: license, reproducibility, resource budget, approval.
- 내부 구조·데이터 흐름: 장치/라이선스 → 승인 데이터 → baseline → 후보 실험.
- 실제 코드 연결: [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md) · [COMPAT](../../../backend/src/ai_workshop/labs/rag/generation/openai_compatible.py).
- 실습: 모델 선정·설치·데이터 승인·원복 항목을 미실행으로 작성한다.
- 검증 기준: 선택 실패 시 다른 모델로 조용히 바꾸지 않는 원칙을 유지한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 64 — SFT 데이터 설계. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

## 10주 — Fine-tuning과 학습 전후 검증

### Day 64 | 2026-12-14 | SFT 데이터 설계

- 목표: 근거가 있는 교정 답변을 학습 예제로 만든다.
- 원리: 피드백은 검토·정제·근거 연결을 거쳐야 학습에 쓸 수 있는 감독 신호가 된다.
- 이론: instruction/input/output, evidence binding, deduplication.
- 내부 구조·데이터 흐름: 검토 피드백 → 교정 정답 → 근거 연결 → dataset version.
- 실제 코드 연결: [GENEVAL](../../../backend/src/ai_workshop/labs/rag/evaluation/generative.py) · [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md).
- 실습: 공개 합성 질문·근거·교정 답변 3건을 문서로 작성한다.
- 검증 기준: 좋아요/싫어요 원시 신호를 그대로 학습에 쓰지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 65 — 선호 학습과 DPO 개념. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 65 | 2026-12-15 | 선호 학습과 DPO 개념

- 목표: 선호 쌍과 정답 데이터의 차이를 설명한다.
- 원리: 선호는 정답 그 자체가 아니므로 비교 쌍의 기준과 편향을 검토해야 한다.
- 이론: chosen/rejected, preference objective, confounding.
- 내부 구조·데이터 흐름: 같은 prompt → 두 답변 → 검토 선호 → 학습 후보.
- 실제 코드 연결: [GENEVAL](../../../backend/src/ai_workshop/labs/rag/evaluation/generative.py) · [CITATION](../../../backend/src/ai_workshop/labs/rag/generation/citation_validation.py).
- 실습: 길이만 긴 답변을 선택한 편향 사례를 반례로 작성한다.
- 검증 기준: 근거 지지·정확도 기준으로 선호 이유를 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 66 — 학습 실행 계획과 checkpoint. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 66 | 2026-12-16 | 학습 실행 계획과 checkpoint

- 목표: 실험 재현과 중단/재개 조건을 정의한다.
- 원리: 재개 가능한 학습에는 모델 값 외에도 진행 상태와 실험 설정의 일관성이 필요하다.
- 이론: seed, batch, optimizer state, checkpoint, provenance.
- 내부 구조·데이터 흐름: 고정 dataset/config → 학습 → checkpoint → validation.
- 실제 코드 연결: [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md) · [REGISTRY](../../../backend/src/ai_workshop/labs/rag/models/domain.py).
- 실습: 실행하지 않는 실험 명세에 버전·예산·중단 조건을 채운다.
- 검증 기준: checkpoint 파일과 완성 모델·운영 배포를 구별한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 67 — 학습 전후 RAG 비교. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 67 | 2026-12-17 | 학습 전후 RAG 비교

- 목표: 모델 변경 효과를 검색 변경과 분리한다.
- 원리: 동일 근거와 평가 세트를 사용해야 모델 변경의 효과를 검색 변경과 구분할 수 있다.
- 이론: paired comparison, control variables, held-out evaluation.
- 내부 구조·데이터 흐름: 같은 검색 근거 → base/fine-tuned → 동일 평가.
- 실제 코드 연결: [PIPE](../../../backend/src/ai_workshop/labs/rag/search/pipeline.py) · [GENEVAL](../../../backend/src/ai_workshop/labs/rag/evaluation/generative.py).
- 실습: 동일 근거에서 두 가상 답변을 정답·인용·거절로 채점한다.
- 검증 기준: 청킹/검색/프롬프트까지 동시에 바꿔 효과를 혼동하지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 68 — 모델 등록·승격·원복. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 68 | 2026-12-18 | 모델 등록·승격·원복

- 목표: 후보 모델과 기본 모델을 구별한다.
- 원리: 학습이 끝난 모델도 회귀 평가와 명시 승격을 거치기 전에는 운영 기본값이 아니다.
- 이론: versioned profile, compatibility, promotion gate.
- 내부 구조·데이터 흐름: 학습 산출물 → Registry 후보 → 회귀 → 승인 → 연결.
- 실제 코드 연결: [REGISTRY](../../../backend/src/ai_workshop/labs/rag/models/domain.py) · [GENPORT](../../../backend/src/ai_workshop/labs/rag/generation/contracts.py).
- 실습: 실패 후보와 승인 후보의 상태 전이표를 만든다.
- 검증 기준: 생성 모델만 교체할 때 검색 색인 재생성이 필수가 아님을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 69 — 운영 비용과 실패 분석. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 69 | 2026-12-19 | 운영 비용과 실패 분석

- 목표: 지연·메모리·정답의 절충을 평가한다.
- 원리: 평균 지연만 보면 드문 긴 요청과 실패 비용이 가려지므로 분포와 실패 단계를 함께 본다.
- 이론: throughput, latency distribution, timeout, error budget.
- 내부 구조·데이터 흐름: 요청 → 대기 → 추론 → 검증 → 단계별 지표.
- 실제 코드 연결: [TRACE](../../../backend/src/ai_workshop/labs/rag/executions/observer.py) · [BUDGET](../../../backend/src/ai_workshop/labs/rag/models/budget_trace.py).
- 실습: 합성 지연 10개에서 평균과 p95의 차이를 계산한다.
- 검증 기준: 모델 실패·검색 누락·인용 거절을 별도로 기록한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 70 — 10주 복습: 파인튜닝 결론. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 70 | 2026-12-20 | 10주 복습: 파인튜닝 결론

- 목표: 실행하지 않은 실험을 수행한 것처럼 결론내리지 않는다.
- 원리: 설계의 타당성, 실제 실험 결과, 운영 반영은 서로 다른 완료 판정을 가진다.
- 이론: evidence-based comparison, reproducible report.
- 내부 구조·데이터 흐름: 설계/실제 측정 → 제한 → 채택/보류 → 다음 질문.
- 실제 코드 연결: [VECTORPLAN](../../../docs/superpowers/plans/2026-10-04-rag-vector-store-and-local-llm-experiments.md) · [LEARN](../../../backend/src/ai_workshop/platform/learning/domain.py).
- 실습: 학습 전후 비교 보고서 목차와 미측정 칸을 완성한다.
- 검증 기준: 학습 이해·실험 실행·운영 적용의 세 완료 상태를 구분한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 71 — Linux 실행 기초. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

## 11주 — Linux·Docker·Kubernetes 기본

### Day 71 | 2026-12-21 | Linux 실행 기초

- 목표: 프로세스·파일·권한·신호의 관계를 설명한다.
- 원리: 프로세스의 자원 접근은 OS 권한과 열린 자원에 영향을 받으며 신호 전송만으로 종료가 입증되지는 않는다.
- 이론: PID, UID/GID, file descriptor, signals, exit code.
- 내부 구조·데이터 흐름: 프로세스 시작 → 파일/네트워크 접근 → signal → 종료.
- 실제 코드 연결: [CODEX](../../../backend/src/ai_workshop/labs/rag/generation/codex_execution.py) · [K8PLAN](../../../docs/superpowers/plans/2026-10-08-kubernetes-learning.md).
- 실습: Linux 개념과 Windows 실행 경계의 대응표를 만든다.
- 검증 기준: Linux 학습이 현재 Windows/DPAPI 지원을 보장하지 않음을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 72 — Docker 이미지와 컨테이너. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 72 | 2026-12-22 | Docker 이미지와 컨테이너

- 목표: 빌드 산출물과 실행 상태를 구별한다.
- 원리: 이미지는 실행 입력이고 컨테이너는 실행 인스턴스이며 영속 자료는 별도 수명주기를 가진다.
- 이론: layers, image digest, writable layer, volume.
- 내부 구조·데이터 흐름: Dockerfile → image → container → 외부 volume.
- 실제 코드 연결: [DOCKER](../../../backend/Dockerfile) · [COMPOSE](../../../infrastructure/compose/compose.yaml).
- 실습: 기존 Dockerfile target과 compose 서비스를 읽어 그림으로 연결한다.
- 검증 기준: 컨테이너 삭제와 volume/자료 보존을 혼동하지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 73 — Compose 네트워크와 설정. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 73 | 2026-12-23 | Compose 네트워크와 설정

- 목표: 서비스 주소·설정·비밀 전달을 이해한다.
- 원리: 컨테이너 내부 서비스 주소와 호스트 공개 포트를 구분해야 올바른 통신 경로를 설명할 수 있다.
- 이론: service DNS, published port, env, healthcheck.
- 내부 구조·데이터 흐름: frontend → API → DB/ES; API dispatch → Redis → worker → DB/ES.
- 실제 코드 연결: [COMPOSE](../../../infrastructure/compose/compose.yaml) · [CONFIG](../../../backend/src/ai_workshop/config.py).
- 실습: compose 설정 파일만 읽어 통신 표와 설정 출처를 작성한다.
- 검증 기준: host 포트와 container 포트를 구분하고 .env 비밀을 기록하지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 74 — Kubernetes 제어 루프. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 74 | 2026-12-24 | Kubernetes 제어 루프

- 목표: 원하는 상태와 관측 상태의 차이를 이해한다.
- 원리: controller는 관측 상태가 선언한 목표와 다르면 반복적으로 맞추려 한다.
- 이론: control plane, scheduler, controller, reconciliation.
- 내부 구조·데이터 흐름: manifest → API server → controller → Pod → status.
- 실제 코드 연결: [K8PLAN](../../../docs/superpowers/plans/2026-10-08-kubernetes-learning.md) · [COMPOSE](../../../infrastructure/compose/compose.yaml).
- 실습: 현재 compose 서비스들을 개념 자원에 대응시킨다.
- 검증 기준: 클러스터·namespace가 현재 생성됐다고 표현하지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 75 — Pod·Deployment·Service. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 75 | 2026-12-25 | Pod·Deployment·Service

- 목표: 배포·재생성·라우팅의 책임을 구별한다.
- 원리: Deployment가 복제본을 유지하고 Service가 선택된 Pod로 통신을 연결한다.
- 이론: replica, label selector, Service, rollout.
- 내부 구조·데이터 흐름: Deployment → ReplicaSet → Pod ← Service selector.
- 실제 코드 연결: [K8PLAN](../../../docs/superpowers/plans/2026-10-08-kubernetes-learning.md) · [WORKER](../../../backend/src/ai_workshop/worker.py).
- 실습: 가상 manifest를 문서에서만 작성하고 selector 불일치를 찾는다.
- 검증 기준: Celery worker를 Kubernetes Job과 동일시하지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 76 — ConfigMap·Secret·권한. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 76 | 2026-12-26 | ConfigMap·Secret·권한

- 목표: 설정 주입과 권한 격리의 범위를 이해한다.
- 원리: 클러스터 권한·네트워크 경계·앱 사용자 권한은 서로 다른 계층에서 검사한다.
- 이론: RBAC, service account, secret handling, network policy.
- 내부 구조·데이터 흐름: 설정/비밀 → Pod 권한 → 앱의 사용자 권한.
- 실제 코드 연결: [K8PLAN](../../../docs/superpowers/plans/2026-10-08-kubernetes-learning.md) · [POLICY](../../../backend/src/ai_workshop/labs/rag/policies/domain.py).
- 실습: 가상 API/worker 권한표에서 과도한 권한을 제거한다.
- 검증 기준: Secret base64는 암호화가 아니며 namespace가 앱 ACL을 대체하지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 77 — 11주 복습: readiness와 복구. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 77 | 2026-12-27 | 11주 복습: readiness와 복구

- 목표: 살아 있음·준비됨·기능 검증을 구별한다.
- 원리: 준비되지 않은 인스턴스의 라우팅 제외와 비정상 프로세스 재시작은 목적이 다르다.
- 이론: liveness/readiness/startup, graceful shutdown.
- 내부 구조·데이터 흐름: probe → 라우팅 포함/제외 → 종료 유예 → 작업 처리.
- 실제 코드 연결: [K8PLAN](../../../docs/superpowers/plans/2026-10-08-kubernetes-learning.md) · [WORKER](../../../backend/src/ai_workshop/worker.py).
- 실습: 긴 작업 중 Pod 종료와 ack 타이밍을 종이로 추적한다.
- 검증 기준: 재시작이 과거 별칭 요청 종료 proof를 대신하지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 78 — Kubernetes 저장소. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

## 12주 — Kubernetes 운영 개념과 최종 통합

### Day 78 | 2026-12-28 | Kubernetes 저장소

- 목표: 상태 저장 데이터의 수명주기를 이해한다.
- 원리: Pod와 저장소의 수명이 다르므로 재생성 뒤 자료가 남는 조건과 삭제 정책을 확인해야 한다.
- 이론: PV/PVC, storage class, reclaim policy, backup.
- 내부 구조·데이터 흐름: Pod → PVC → PV → 실제 저장 장치.
- 실제 코드 연결: [K8PLAN](../../../docs/superpowers/plans/2026-10-08-kubernetes-learning.md) · [ASSET](../../../backend/src/ai_workshop/platform/assets/models.py).
- 실습: DB·원본·모델 캐시를 지속성 요구별로 분류한다.
- 검증 기준: PVC 삭제·백업 존재·실제 복원 성공을 서로 구분한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 79 — 확장과 rolling update. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 79 | 2026-12-29 | 확장과 rolling update

- 목표: replica 증가가 만드는 경합을 예측한다.
- 원리: 복제본 증가는 공유 저장소·큐의 경합과 중복 실행 가능성을 함께 늘릴 수 있다.
- 이론: horizontal scaling, rollout/rollback, singleton scheduler.
- 내부 구조·데이터 흐름: 부하 → replicas → 공유 큐/DB → 상태 전이.
- 실제 코드 연결: [K8PLAN](../../../docs/superpowers/plans/2026-10-08-kubernetes-learning.md) · [WORKER](../../../backend/src/ai_workshop/worker.py).
- 실습: API/worker/beat 각각 2개일 때 문제 여부를 표로 예측한다.
- 검증 기준: beat 중복과 worker 멱등성이 다른 문제임을 설명한다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 80 — 관찰과 장애 대응. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 80 | 2026-12-30 | 관찰과 장애 대응

- 목표: 서비스 간 실패 경로를 지표로 연결한다.
- 원리: 상관관계 ID로 요청의 단계들을 연결하면 비공개 본문 없이도 실패 위치를 추적할 수 있다.
- 이론: logs/metrics/traces, correlation ID, saturation.
- 내부 구조·데이터 흐름: 요청 ID → 단계 span → 저장소/모델 오류 → 안전 진단.
- 실제 코드 연결: [TRACE](../../../backend/src/ai_workshop/labs/rag/executions/observer.py) · [K8PLAN](../../../docs/superpowers/plans/2026-10-08-kubernetes-learning.md).
- 실습: 합성 timeout의 최초 실패 단계와 남길 메타데이터를 찾는다.
- 검증 기준: 원문·비밀·내부 추론 없이 실패를 추적할 수 있다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 81 — Compose와 Kubernetes 비교. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 81 | 2026-12-31 | Compose와 Kubernetes 비교

- 목표: 도입 효과와 운영 복잡성을 함께 판단한다.
- 원리: 더 많은 배포 기능이 항상 현재 규모의 운영 비용 감소로 이어지는 것은 아니다.
- 이론: availability, operability, resource cost, OS support.
- 내부 구조·데이터 흐름: 같은 사용자 흐름 → Compose/K8s 설계 → 제한 비교.
- 실제 코드 연결: [COMPOSE](../../../infrastructure/compose/compose.yaml) · [K8PLAN](../../../docs/superpowers/plans/2026-10-08-kubernetes-learning.md).
- 실습: 배포·복구·자원·Windows 지원·원복을 비교한다.
- 검증 기준: 학습용 설계 성공을 운영 전환 승인으로 쓰지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 82 — 최종 통합: 업로드부터 답변. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 82 | 2027-01-01 | 최종 통합: 업로드부터 답변

- 목표: 전체 데이터 흐름을 도움 없이 설명한다.
- 원리: 각 단계의 정본·권한·버전을 이어 설명할 수 있어야 업로드부터 답변까지의 무결성을 이해한 것이다.
- 이론: state lifecycle, retrieval/generation split, evidence.
- 내부 구조·데이터 흐름: 업로드 → 검증 → 큐 → 파싱/색인 → 검색 → 생성/인용 → 저장.
- 실제 코드 연결: [INGEST](../../../backend/src/ai_workshop/labs/rag/ingestion/service.py) · [PIPE](../../../backend/src/ai_workshop/labs/rag/search/pipeline.py) · [CONV](../../../backend/src/ai_workshop/labs/rag/conversations/service.py).
- 실습: 공개 합성 사례로 모든 단계의 입력·정본·실패를 백지에 그린다.
- 검증 기준: 권한·버전·멱등성·인용 검사 위치가 빠지지 않는다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 83 — 최종 통합: 실패와 평가. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 83 | 2027-01-02 | 최종 통합: 실패와 평가

- 목표: 서로 다른 실패의 증거와 복구 조건을 설명한다.
- 원리: 정상 흐름만 검증하면 실패 뒤 상태와 권한 경계의 결함을 놓칠 수 있다.
- 이론: fault model, evaluation coverage, independent evidence.
- 내부 구조·데이터 흐름: 권한 철회/중복 전달/timeout/나쁜 인용 → 각 gate → 기록.
- 실제 코드 연결: [GENEVAL](../../../backend/src/ai_workshop/labs/rag/evaluation/generative.py) · [FENCE](../../../backend/src/ai_workshop/labs/rag/indexing/write_fence.py) · [TRACE](../../../backend/src/ai_workshop/labs/rag/executions/observer.py).
- 실습: 4개 실패 시나리오에 기대 결과와 검증 방법을 적는다.
- 검증 기준: 실행 없는 분석은 분석으로 표시하고 미해결 핵심 질문을 남긴다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: Day 84 — Day84 종합 판정과 다음 주기. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.

### Day 84 | 2027-01-03 | Day84 종합 판정과 다음 주기

- 목표: 일정 종료와 숙련도 완료를 독립 판정한다.
- 원리: 학습 기간이 끝나도 독립 설명과 적용 증거가 없는 개념은 완료로 승격하지 않는다.
- 이론: teach-back, transfer, spaced review, evidence ledger.
- 내부 구조·데이터 흐름: 전체 기록 → 재설명/전이 과제 → 숙련도 판정 → 보충 계획.
- 실제 코드 연결: [LEARN](../../../backend/src/ai_workshop/platform/learning/domain.py) · [PIPE](../../../backend/src/ai_workshop/labs/rag/search/pipeline.py) · [SDKPLAN](../../../docs/superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md).
- 실습: 프로젝트 전체를 10분 설명하고 가장 약한 3개 개념의 재학습 일정을 제안한다.
- 검증 기준: 84일 경과로 자동 완료하지 않고 증거가 있는 Day만 확인 완료로 둔다. 본인 설명과 결과 근거를 남긴다.
- 다음 학습: 미해결 질문 상위 3개를 먼저 보충하고 다음 학습 주기는 별도 합의한다. 이해가 부족하면 이 날짜의 선수 개념 보충을 우선한다.
