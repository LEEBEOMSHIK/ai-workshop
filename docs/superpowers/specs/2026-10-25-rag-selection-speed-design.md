# 근거 선택 속도와 세부 시간 기록 설계

사용자는 [속도 조사](../../worklogs/2026-10-25-rag-latency-audit.md)에서 제시한 첫 단계인 근거 선택 계산 개선과 세부 시간 계측을 승인했다. 품질 개선 보류·기존 모델·프로파일·SDK 위임은 유지한다.

## 선택한 접근

1. **채택:** coverage 전용 정규화와 요청 내부 계산 재사용. 실제 위치가 필요한 하이라이트는 기존 원문 offset 알고리즘을 유지한다. 모델 변경 없이 검증 가능한 중복 계산부터 줄인다.
2. 임베딩 상주·요청 간 캐시는 기존 메모리 소유권과 권한/버전 설계가 필요하므로 후속으로 남긴다.
3. 고정 관리자 모델 호출 생략·모델 유지 시간 설정은 실행 구조와 배포 범위이므로 이번 변경에 포함하지 않는다.

## 선택 결과 보존

NFKC → casefold → 연속 공백 축약의 기존 최종 문자열을 동일하게 계산한다. 앞뒤 공백 유무와 query term 중복 제거, substring 매치의 기존 의미를 유지한다. 문자열당 한 번의 정규화로 coverage를 계산하며 원문 위치 배열을 만들지 않는다.

`KeywordMatcher(query)`는 질의어·정규화 결과·필요한 원문 offset을 요청 안에서 재사용한다. `EvidenceSelector.select`와 `select_context`에 선택적 `keywords` 인자를 추가하고 pipeline에서 같은 객체를 전달한다. 기존 호출자는 기본 생성 경로를 쓴다. 프로세스 전역 캐시나 응답 캐시는 만들지 않는다. 권한·점수 임계값·정렬·충돌·근거 예산·표 처리·인용 ID/위치·본문은 바꾸지 않는다.

## 세부 계측

[ADR-0041](../../decisions/0041-rag-operation-timings.md)의 선택적 stage `operations` 계약을 사용한다. 기존 실행의 값은 미수집이며 0으로 추정하지 않는다. 같은 요청의 observer 안에만 집계하고 관측기가 없으면 no-op이다. 병렬 작업은 실행별로 격리하고 단계 종료 뒤 늦게 끝난 관측은 저장 결과를 뒤집지 않는다.

`measure_operation(name, *, items=0, reused_items=0)`는 동기 context manager로 sync/await 블록 모두 감싼다. 횟수·실패 횟수·포함 경과시간·입력 항목 수·재사용 수만 모은다. 예외·취소는 그대로 전파한다. 본문·질문·ID·endpoint·예외 메시지를 받는 인터페이스는 없다. 새 DB 왕복 없이 기존 단계 저장에 함께 넣는다.

초기 이름은 `keyword.normalize`, `keyword.offsets`, `embedding.model_load`, `embedding.tokenize`, `embedding.query`, `embedding.documents`, `retrieval.authorize`, `retrieval.bm25`, `retrieval.dense`, `retrieval.sources`, `selection.extractive`, `selection.context`, `retrieval.describe`, `retrieval.pit_open`, `retrieval.pit_close`다. 중첩·병렬 시간을 포함한 누적값으로 전체 시간에 합산하지 않는다. 모델 런타임 내부 적재/입력/출력 평가 시간은 제공하지 않으며 이번에는 수집된 것처럼 표현하지 않는다.

## 검증과 제외 범위

Unicode 결합 문자·한글 자모·ligature·casefold 확장·공백·빈 질의·중복 질의어의 coverage 및 offset을 검증한다. 다중 요청 캐시 격리와 query→selection→context의 재사용, 선택 결과·충돌·구조화 근거 회귀를 확인한다. 시간의 절대 임계값으로 CI를 불안정하게 만들지 않고 함수 호출/결과 계약을 테스트한다.

계측은 fake clock의 누적·실패·취소·동시 실행 격리·이전 JSON 호환·잘못된 메타데이터 거절·DB 저장→읽기와 권한 계약을 확인한다. DB 검증은 본래 기존 환경의 외부 트랜잭션 rollback으로 한정하며 새 DB/계정은 만들지 않는다.

합성 입력의 변경 전후 성능 측정은 모델·네트워크 없이 진행하고 실제 RAG 단축과 구분한다. 관련 pytest·Mypy·Ruff와 OpenAPI 생성/TypeScript 검사를 수행한다. 본래 서비스 적용 여부는 별도로 확인한다. 새 생성/임베딩·설치·다운로드·재색인·설정 변경·commit/push는 하지 않는다.
