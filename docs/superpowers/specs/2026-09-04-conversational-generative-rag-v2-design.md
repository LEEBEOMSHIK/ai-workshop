# 대화형 생성 RAG V2 설계

- 상태: 승인됨
- 기준일: 2026-09-04
- 범위: 로그인 사용자의 RAG 검색부터 근거 제한 LLM 답변과 인용 검증까지
- 관련 결정: `docs/decisions/0008-required-generation-optional-reranker.md`
- 관련 기준선: `docs/decisions/0003-hybrid-retrieval-baseline.md`

## 1. 배경과 목표

현재 구현은 문서 파싱·청킹·색인, BM25 또는 dense를 포함한 검색, RRF 결합, 근거 선별,
하이라이트와 원문 추적까지 제공한다. 사용자에게 표시하는 답변은 검색 근거의 추출 결과이며
LLM 생성 답변이 아니다.

AI Workshop이 제공하려는 RAG 서비스의 완료 기준은 검색 결과 목록이 아니라 다음 흐름이다.

```text
질문
→ 권한이 적용된 Hybrid 검색
→ 선택적 리랭킹
→ 근거 선별
→ 근거에 제한된 LLM 답변
→ 인용 검증
→ 답변 또는 명시적인 근거 부족 상태
```

리랭커는 품질 실험을 위한 선택 구성요소다. 리랭커가 없다는 이유로 검색이나 생성이
실패하면 안 된다. 반면 LLM과 인용 검증은 이 프로젝트가 완성된 대화형 RAG 서비스로
표시되기 위한 필수 구성요소다.

## 2. 채택 방식과 대안

### 채택: 고정 파이프라인과 명시적 선택 단계

현재 서비스 흐름을 `Retrieval → Optional Reranking → Evidence Selection → Generation →
Citation Validation`으로 확장한다. 각 단계는 작은 포트와 어댑터로 분리하되 임의의 단계
그래프를 사용자가 조립하는 플러그인 시스템은 만들지 않는다.

- 장점: 현재 구조를 유지하면서 선택 단계의 부재와 실패를 명확하게 구분할 수 있다.
- 장점: 실행 순서, 권한 적용 시점과 평가 재현성이 고정된다.
- 비용: 새로운 선택 단계를 추가할 때 공개 계약을 명시적으로 확장해야 한다.

### 대안 1: 모든 단계를 범용 DAG로 구성

자유도는 높지만 현재 필요한 리랭커 하나보다 훨씬 큰 오케스트레이션·검증·UI 복잡성을
만든다. 실제 반복 요구가 없어 채택하지 않는다.

### 대안 2: 생성과 리랭킹을 별도 마이크로서비스로 분리

독립 확장에는 유리하지만 현재 부하와 보안 경계가 이를 요구하지 않는다. 모델 런타임만
어댑터 뒤의 별도 로컬 프로세스로 둘 수 있고 애플리케이션은 모듈형 모놀리스를 유지한다.

## 3. 필수·선택 구성요소 계약

### 필수 구성요소

- 권한 범위가 먼저 적용되는 BM25와 bi-encoder dense retrieval
- RRF 융합
- 근거 선별과 충분성 정책
- 버전이 고정된 LLM 생성 프로파일과 사용 가능한 로컬 런타임
- 구조화된 생성 결과 검증과 인용 검증

대화형 생성 구성을 일반 사용자에게 제공하려면 모든 필수 구성요소가 준비되어야 한다.
필수 구성요소가 준비되지 않았는데 추출 답변으로 조용히 대체하지 않는다.

### 선택 구성요소

- 리랭커

리랭커 프로파일이 없으면 실행 상태를 `skipped_not_configured`로 기록하고 RRF 결과를 바로
근거 선별에 전달한다. 이 상태는 오류나 성능 저하 fallback이 아니라 저장 구성 자체의
정상 동작이다.

리랭커 프로파일이 있는데 모델 또는 런타임 실행이 실패하면 조용히 RRF 결과로 대체하지
않는다. 해당 실행은 `reranker_unavailable`로 실패시키고 구성 평가도 실패로 기록한다.
따라서 “처음부터 사용하지 않기로 한 상태”와 “사용하기로 했지만 실패한 상태”가 섞이지
않는다.

향후 다른 선택 단계를 추가할 때도 `not_configured → 정상 생략`, `configured_and_ready → 실행`,
`configured_but_failed → 명시적 실패`의 세 상태를 각각 정의한다. 이 원칙을 적용하되 실제
선택 단계가 늘어나기 전에는 범용 플러그인 프레임워크를 만들지 않는다.

## 4. 프로파일과 저장 구성

색인, 검색과 생성 책임을 계속 분리한다.

- Indexing Profile: parser policy, chunker, embedding 모델과 벡터 차원
- Retrieval Profile: BM25, dense, RRF와 선택적 reranker binding
- Generation Profile: LLM binding, prompt reference, context budget, 출력 한도, 샘플링 설정,
  응답 schema 버전과 timeout
- Answer Policy: 근거 충분성, 인용 필수 여부, 충돌과 검증 실패 처리
- Saved RAG Configuration Version: 위 불변 버전들의 조합과 허용 지식 공간

새 V2 Retrieval Profile에서 reranker binding과 설정이 모두 없으면 리랭커 미사용이다.
binding과 설정은 함께 존재해야 한다. 현재 V1의 `reranker.enabled=false` 메타데이터는 읽기
호환만 유지하고 V2 선택 상태의 정본으로 사용하지 않는다.

대화형 생성 구성은 Generation Profile과 생성 가능한 Answer Policy를 반드시 참조한다.
LLM 변경만으로 검색 색인을 재구축하지 않는다. 모델명, revision, provider, prompt, 주요
파라미터와 실행 환경은 registry와 profile에 기록하며 업무 코드에 직접 고정하지 않는다.

## 5. 준비 상태

API는 다음 상태를 구분한다.

- `search_ready`: 호환되는 활성 READY 색인이 있고 검색 모델을 실행할 수 있음
- `answer_ready`: generation profile, LLM binding, prompt, 런타임 health와 answer policy가
  모두 유효함
- `service_ready`: `search_ready && answer_ready`

설정하지 않은 리랭커는 어떤 준비 상태도 낮추지 않는다. 설정한 리랭커는 검색 계약의
일부가 되므로 해당 runtime이 준비되지 않으면 `search_ready=false`다.

관리자 화면은 검색·답변·전체 서비스 준비 상태와 원인을 각각 보여준다. 로그인 사용자
검색 화면은 `service_ready=false`인 구성을 선택할 수는 있어도 생성 RAG 요청을 제출할 수
없으며 필요한 관리자 조치를 설명한다.

## 6. 실행 흐름과 경계

1. 요청 사용자의 workspace·folder 권한을 확인하고 검색 전에 범위를 확정한다.
2. 저장 구성의 정확한 불변 버전과 세 준비 상태를 확인한다.
3. 현재 대화의 이전 user·검증 완료 assistant turn을 versioned context policy로 제한한다.
4. 첫 질문은 원문을 사용하고, 후속질문은 Query Contextualizer가 history와 현재 질문을
   독립적으로 검색 가능한 질의로 확정한다.
5. BM25와 dense 후보를 같은 권한 범위에서 조회하고 RRF로 결합한다.
6. reranker가 없으면 단계를 정상 생략하고, 있으면 허용된 후보만 전달한다.
7. 근거 선별기가 LLM에 전달할 Evidence Unit과 충분성 상태를 결정한다.
8. 근거가 부족하면 답변 생성 LLM을 호출하지 않고 `insufficient_evidence`를 반환한다.
9. 충분한 경우 Generation Runtime Port에 원 질문, 확정 검색 질의, 제한된 대화 history,
   허용된 Evidence Unit과
   generation profile을 전달한다.
10. 런타임은 자유 텍스트가 아니라 답변 문장과 evidence ID가 연결된 versioned schema를
   반환한다.
11. 인용 검증기가 모든 evidence ID의 권한·검색 포함 여부, 원문 위치, 인용 coverage와
   구조적 무결성을 확인한다.
12. 검증을 통과한 답변만 `answered`로 반환하고 현재 브라우저 대화에 추가한다.

LLM은 검색 결과의 첫 순위를 직접 바꾸지 않는다. 문맥 기반 질의 확정은 generation
profile에 연결된 versioned context policy로 기록하며, 원래 질문과 실제 검색 질의를
사용자에게 보여준다. context policy는 history turn 수와 token budget을 profile에서 읽고
오래된 turn을 임의 문자 수로 잘라 넣지 않는다. 문맥 질의 확정이 실패하면 원 질문으로
조용히 대체하지 않고 `query_contextualization_unavailable`로 실패한다.

## 7. 응답과 실패 계약

기존 SearchResponse의 `status`, `answer`, `conflicts`, `related_sources`는 근거 선별과 원문
추적 계약이므로 의미를 바꾸지 않는다. V2는 다음 `generation` 객체를 additive하게 추가한다.

```text
generation.status = answered
                  | not_requested
                  | insufficient_evidence
                  | citation_validation_failed
generation.text = 검증된 생성 답변 또는 null
generation.citations = 문장과 Evidence Unit을 연결한 인용 목록
resolved_query = 문맥에서 확정되어 실제 검색에 사용한 질의
```

- `answered`: 검증된 답변 본문과 문장별 인용을 제공한다.
- `not_requested`: 추출식 V1 비교 실행이며 완성된 생성 RAG 상태로 표시하지 않는다.
- `insufficient_evidence`: 답변을 생성하지 않고 허용된 관련 근거만 제공한다.
- `citation_validation_failed`: 생성문을 사용자에게 노출하지 않고 검증 실패와 검색 근거를
  제공한다.

runtime timeout·연결 실패처럼 요청을 정상 판정할 수 없는 경우는 `llm_unavailable` 503으로
응답한다. 구성된 리랭커 실패는 `reranker_unavailable` 503으로 응답한다. 오류 응답이나
로그에 프롬프트, 비공개 질문·본문 또는 생성 초안을 포함하지 않는다.

## 8. 생성과 인용 검증

Generation Runtime Port는 provider SDK 객체를 도메인으로 노출하지 않는다. 입력은 다음
항목으로 제한한다.

- 현재 질문
- versioned context policy가 선택한 이전 user·검증 완료 assistant turn
- 문맥에서 확정한 실제 검색 질의
- 허용된 Evidence Unit ID, 본문, 문서 표시 정보와 원문 위치
- generation profile과 answer schema 버전
- correlation ID와 timeout

첫 인용 검증 기준은 결정적으로 검사할 수 있는 항목을 hard gate로 둔다.

- 존재하지 않거나 검색되지 않은 evidence ID 사용 금지
- 호출 사용자가 접근할 수 없는 evidence 사용 금지
- 답변의 주요 주장마다 최소 한 개 인용 요구
- 인용 원문 위치가 활성 Asset Version과 RAG Projection으로 추적 가능
- 수치·날짜 등 정확성이 중요한 인용은 근거 원문에서 확인 가능

의미적 지지 여부를 별도 모델이 판정하는 기능은 후속 후보이며 초기 hard gate를 대체하지
않는다. 운영 승격은 합성·승인 평가 세트의 answer correctness, faithfulness, citation
precision·coverage와 abstention 기준을 모두 통과해야 한다.

## 9. 로컬 모델 런타임과 데이터 경계

첫 구현은 provider 독립적인 `GenerationRuntimePort`와 로컬 OpenAI-compatible HTTP adapter를
사용한다. adapter는 로컬 endpoint만 허용하고 특정 provider SDK 객체를 도메인에 노출하지
않는다. 구체 모델명과 endpoint는 registry, versioned profile과 typed settings에서 선택한다.

- 비공개 원문과 질문은 로컬 또는 승인된 사내 런타임 밖으로 전송하지 않는다.
- 외부 provider adapter는 공개 또는 비식별 승인 데이터만 허용하며 기본 활성화하지 않는다.
- 프롬프트와 모델 출력 전문은 일반 애플리케이션 로그에 남기지 않는다.
- 실행 기록에는 모델·profile 버전, 입력 evidence ID, 상태, token 수, 소요 시간과 안전한
  오류 코드만 기록한다.
- 다른 모델 또는 provider로 조용히 전환하지 않는다.

첫 V2의 이전 turn은 브라우저 현재 세션에서 유지하고 매 요청의 bounded history로 서버에
전달한다. 서버는 history를 새 대화 자산으로 영속 저장하지 않으며, 현재 요청 처리와 기존
감사 계약의 안전한 실행 메타데이터에만 사용한다. assistant history에는 인용 검증을 통과한
답변만 포함한다. 새로고침 이후에도 대화를 복원하는 서버 저장 기능은 보존·삭제 정책을
별도로 승인한 뒤 추가한다.

클라이언트가 전달한 history는 권한 증거로 신뢰하지 않는다. 서버는 매 turn마다 현재
workspace·folder 권한과 새로 검색한 Evidence Unit을 다시 검사하고, history에 포함된 과거
인용 ID만으로 문서에 접근하거나 답변 근거를 확장하지 않는다.

## 10. 관리자와 사용자 UI

관리자 모델 화면은 LLM 정의와 정확한 버전, runtime 종류와 상태를 관리한다. 구성 화면은
Generation Profile과 Answer Policy를 선택하고 리랭커는 `사용 안 함`을 정상 선택지로 둔다.
내부 UUID 대신 이름·버전과 상태를 기본 표시하고 상세 진단에서만 내부 식별자를 제공한다.

로그인 사용자 검색 화면은 대화형 답변, 문장별 인용, 관련 문서와 원문 이동을 제공한다.
추출 결과를 LLM 답변처럼 표시하지 않는다. 구성과 런타임이 준비되지 않았거나 근거가
부족한 상태를 각각 다른 문구로 안내한다.

공개 검색과 공개 릴리스 연결은 이 작업의 비목표다. 먼저 비공개 작업소에서 생성 RAG를
검증한 뒤 승인된 공개 릴리스 계약으로 확장한다.

## 11. 평가와 수용 기준

1. 리랭커가 없는 V2 구성이 Hybrid 검색과 LLM 답변을 정상 완료한다.
2. 리랭커가 설정된 구성만 리랭커를 호출하며 실패를 조용히 건너뛰지 않는다.
3. 생성 구성에 LLM 또는 prompt가 없으면 `answer_ready=false`이고 제출 전에 안내한다.
4. 충분한 근거가 없으면 LLM을 호출하지 않고 `insufficient_evidence`를 반환한다.
5. 허용되지 않은 evidence ID를 참조한 생성 답변은 사용자에게 노출되지 않는다.
6. 검증된 답변의 주요 주장은 접근 가능한 원문 위치로 추적된다.
7. LLM 변경만으로 기존 검색 색인이 재구축되지 않는다.
8. 모델·profile·prompt·검색 구성 버전으로 실행을 재현할 수 있다.
9. 비공개 질문·본문·프롬프트·생성 초안이 로그와 오류 응답에 남지 않는다.
10. BM25와 추출식 V1은 생성형 V2의 품질·회귀 비교 기준으로 유지된다.
11. 후속질문은 이전 turn으로부터 독립 검색 질의를 확정하고 원 질문과 확정 질의를 함께
    반환한다.
12. 다른 대화의 history가 섞이지 않고 매 turn의 문서 권한을 다시 검사한다.

## 12. 구현 순서

1. V2 저장 구성, context policy, 준비 상태와 응답 schema 계약
2. Generation Runtime Port, fake와 로컬 adapter
3. 문맥 기반 Query Contextualizer와 bounded history 검증
4. 구조화된 생성 및 결정적 인용 검증
5. 검색 application service와 생성 파이프라인 연결
6. 관리자 LLM·Generation Profile 선택과 준비 상태 UI
7. 로그인 사용자 대화형 history·답변·인용 UI
8. 단위·통합·권한·privacy·실제 로컬 runtime smoke와 평가 비교

## 13. 제외 범위

- 리랭커 구현 또는 기본 활성화
- 공개 방문자 검색과 공개 릴리스 활성화
- 외부 LLM provider의 비공개 문서 전송
- 모델 기반 인용 검증을 단독 hard gate로 사용하는 방식
- 자동 prompt 변경, 자동 모델 승격 또는 자동 파인튜닝
- 범용 사용자 구성 DAG와 마이크로서비스 분리
- 서버에 영속 저장되어 새로고침 뒤 복원되는 대화 기록
