# Owner RAG 실제 데이터 smoke 검증

- 검증일: 2026-09-04
- 대상: 로컬 `main`, 호스트 Next.js·FastAPI·Celery와 Docker 인프라
- 데이터: 실제 회사·고객·개인정보가 없는 합성 Markdown 1종

## 검증 결과

- owner 로그인 후 `/admin/rag/configurations`와 `/workshop/rag/search`가 실제 저장 데이터를 렌더했다.
- 전사 지식 공간에 합성 문서를 업로드했고 Platform Asset 검증이 `ready`가 되는 것을 확인했다.
- `BM25 기준선 v1 · 실험`은 평가 전 구성 사용 동의가 없을 때 검색 실행을 막았다.
- 정상 색인 뒤 질문 `환매 대응 최소 현금성 자산 비율은 얼마야?`에 대해 `순자산의 7%`가 포함된 정확한 근거 문장을 첫 결과로 반환했다.
- 원문 뷰어는 같은 불변 Asset Version의 구조 경로 `합성 자산운용 유동성 위험 관리 지침 › 환매 대응 기준`을 열고 질의 토큰 7개를 `keyword-highlight`로 표시했다.
- 검색 결과의 근거 일치 유형은 `정확·키워드 일치`였고 관련 문서가 없다는 빈 상태도 명시했다.

## 문제와 해결 과정

1. 최초 검색은 `409 configuration_not_ready`였고 선택한 indexing profile의 Build가 0개였다.
2. 첫 업로드의 Asset은 `ready`였지만 RAG Projection과 Job은 `chunk_tokenizer_unavailable`로 실패했다. Asset 준비 상태와 RAG Projection 준비 상태가 별개임을 확인했다.
3. 호스트 `.env`는 `AI_WORKSHOP_MODEL_CACHE_ROOT=.local-data/models`를 사용하지만 해당 경로와 Docker `ai-workshop_model-cache`가 모두 비어 있었다.
4. 등록 모델 정의의 `intfloat/multilingual-e5-base` revision `d128750597153bb5987e10b1c3493a34e5a4502a`만 호스트 캐시에 내려받았다. `local_files_only=True` 런타임에서 13 tokens와 정규화된 768차원 벡터 생성이 통과했다.
5. 실패 Projection은 terminal 상태라 DB 상태를 임의 변경하지 않았다. 정상 업로드 경로로 새 Asset을 만들었고 새 Projection의 Build가 `ready`, `active=true`, expected/indexed chunk `4/4`, dimension `768`이 되는 것을 확인했다.

## 확인된 후속 문제

- 현재 선택 가능한 유일한 `BM25 기준선`은 dense retrieval과 생성 모델이 꺼져 있다. 근거 검색은 성공하지만 사용자 요구의 LLM 자연어 답변과 의미 하이라이트를 검증할 수 없다.
- 검색 결과의 구성 메타데이터와 지식 공간 표시에 내부 UUID가 노출된다. 기본 사용자 화면에서는 이름·버전·상태만 보여야 한다.
- 문서 라이브러리의 `문서 올리기`는 동일 파일명을 기존 문서의 새 버전으로 보내지 않고 별도 문서 `버전 1`로 생성한다. 별도 version API는 존재하지만 현재 UI에서 사용할 수 없다.
- 문서와 READY 색인이 없을 때 제출 전 안내가 없고, 실행 뒤 포괄적인 구성 오류만 표시한다.
- Windows가 Hugging Face cache symlink를 지원하지 않아 전체 snapshot이 일반 파일로 저장됐고 측정 용량은 `5,322,815,222 bytes`다. 필요한 런타임 파일만 보존하는 안전한 캐시 초기화·정리 절차를 `CACHE_POLICY.md` 기준으로 별도 설계해야 한다.

## 판정

첫 기준선의 Asset 검증, 구조 청킹, E5 임베딩, Elasticsearch 색인, BM25 검색, 근거 추적과 정확 키워드 하이라이트 수직 슬라이스는 실제 로컬 데이터로 동작했다. Hybrid 검색, 의미 하이라이트와 LLM 답변은 아직 완료 판정하지 않는다.
