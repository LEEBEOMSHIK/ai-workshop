# RAG 에이전트 지침 한국어 정리

- 날짜: 2026-10-23
- 요청: 모니터링에 보이는 영어 에이전트 지침을 한국어로 변경한다.
- 상태: 한국어 지침 구현·독립 전달 경로 검증·본래 API 반영 완료. 실제 모델 품질 재평가와 구분한다.

## 확인한 범위와 성공 기준

실제 SDK 에이전트는 `rag_manager`, `answer_specialist` 두 개다. 관리자의 조정 지침과 도구 설명은 영어다. 답변 담당의 버전 프롬프트는 한국어이고 어댑터가 추가하는 위임·JSON 출력 규칙은 영어다. 기존 `rag-answer-v1`부터 `v5`까지의 원문 파일은 한국어이며 변경하지 않는다.

1. 관리자 지침, 답변 담당의 추가 지침, 도구 설명을 한국어로 전달한다. 위임 1회, 질문의 대상·제약 보존, 직접 답변·사실 창작 금지, 근거 불변과 비신뢰 입력 경계를 유지한다.
2. 로컬 HTTP의 공통 JSON 출력·한도 안내도 한국어로 맞춘다. 직접 HTTP와 SDK에 중복된 출력 안내는 공유한다. schema 2 계약과 정수·최소/정확한 항목 수, 거절 상태, 추가 키 금지는 동일하다. 검색 질의 보조 지침도 같은 로컬 어댑터에서 한국어로 유지한다.
3. `rag_manager`, `answer_specialist`, `write_grounded_answer`, JSON 필드·상태·UUID 등 연동 식별자는 번역하지 않는다. 모델·예산·검색·근거·프로파일·평가 기준을 바꾸지 않는다.
4. 실제 SDK Runner가 만든 합성 HTTP 요청과 trace의 지침이 일치하고 한국어로 전달되는지 확인한다. 직접 HTTP·schema 검증·예산/ACL/실패 회귀를 실행한다. 기존 DB 실행을 화면에서 번역하거나 새 내용으로 덮어쓰지 않는다.

## 역할과 순서

범위가 작은 동작 변경이며, 프롬프트 의미·품질 영향 위험은 중간이다. selector의 requirements-or-behavior, python-api-or-worker, ai-model-or-runtime, rag-behavior, feature-implementation 신호로 요구·Python·AI·RAG·테스트 설계·통합 검증 역할을 선택했다. 메인이 요구/의미 보존·구현·테스트 설계를 담당하고 `sdk_monitor_review`는 구현과 분리된 독립 검증을 맡는다. UI·DB·검색 구조·외부 전송 계약이 바뀌지 않아 해당 구현 역할은 제외한다.

먼저 기존 변경 150개 파일의 SHA와 이번 변경 전 파일을 비공개 작업 디렉터리에 보존했다. 전달 경로의 언어·trace 테스트에서 변경 전 실패를 확인한 뒤 번역하고, 관련 테스트·타입·린트·문서와 독립 의미 검토를 진행한다. 작업 디렉터리는 `.local-data/project-agent-work/agent-korean-instructions-20261023/`이다.

## 재현성과 검증 경계

기존 버전 프롬프트의 본문과 프로파일 저장값은 그대로다. 이번 변경은 어댑터가 추가하는 지침 언어의 변경이며, 새 실행의 실제 지침·HTTP 입력·SHA로 구분한다. 과거 영어 지침은 당시 실제 입력이므로 계속 영어 원문으로 남는다.

이전 실제 검증의 질문 1건×2회, 총 4회 호출은 이미 완료됐다. 이번 추가 생성·임베딩 호출은 0회로 제한한다. 번역 검증을 기존 정답 0/2·P95 실패의 개선 증거로 주장하거나 후보를 기본값/서비스로 승격하지 않는다.

## 구현과 검증 결과

- 관리자·답변 담당의 영어 자연어 지침과 위임 도구 설명을 한국어로 바꿨다. 직접 HTTP와 SDK는 한국어 JSON 안내를 공유하며, 기존 응답 schema와 parser·호출 예산은 그대로다.
- 실제 SDK Runner와 HTTP MockTransport를 사용하는 언어/trace 테스트 6개를 추가했다. 기존 출력 계약 테스트 4개와 함께 변경 전 7실패·3통과, 변경 후 10통과를 확인했다. v2/v4/v5와 openai/ollama 조합의 실제 system 메시지·도구 설명·보관 trace 및 질문/근거/위임 내용 보존을 확인한다.
- 독립 영향 검증 첫 실행은 367통과·11실패였다. 기존 contextualize/입력 진단 테스트가 영어 문구를 기대한 것이 원인이며, 대응 negative assertion과 JSON 예제 파싱·key/schema·budget 검증을 유지해 갱신했다. 최종 같은 범위 **378개 모두 통과**했다. 최초/최종 실행과 앞의 10개는 중복이므로 합산하지 않는다.
- 독립 검토에서 번역 전후 답변·질의 JSON schema, version과 상태별 claims 규칙이 동일했다. 정확히 1회 위임, 사용자 대상·제약·요청 설명, 권한 있는 근거 불변, 사용자/이력의 지침 변경 권한 금지, 원질문과 위임 제안의 구분, JSON/인용 제한의 의미를 대조했다.
- Mypy 변경 소스 2개와 Ruff 변경 소스·테스트 6개 통과. 기존 버전 프롬프트 13개 SHA 동일, 새 모델·임베딩 호출 0이다.

검증 명령은 본래 Conda 환경 활성화 후 실행했다.

```text
python -B -m pytest tests/unit/labs/rag/generation/test_openai_compatible.py tests/unit/labs/rag/orchestration tests/unit/labs/rag/generation/test_input_inspection.py tests/unit/labs/rag/generation/test_openai_compatible_diagnostics.py tests/unit/labs/rag/executions/test_agent_retention.py tests/unit/labs/rag/executions/test_agent_retention_independent.py -q --tb=short
```

위 명령의 작업 디렉터리는 `backend`이며 상세 실행 증거는 비공개 작업 디렉터리의 `review-result.json`에 있다.

## 본래 환경 반영

반영 단계에서는 docker-compose-or-deployment 신호로 인프라 역할을 추가해 메인이 담당했다. 새 환경이나 큐 워커를 만들지 않고 기존 API의 실행 경로·PID·시작 시각·포트와 활성 RAG 작업 0건을 검증했다. 제한된 셸의 프로세스 종료 권한 거부 뒤 동일한 정확 대상·사전검사를 포함한 권한 상승 재기동이 승인돼 실행됐다. 자동 승인 검토의 거절은 없었다.

API PID 119944를 같은 `backend/.conda/python.exe`, Selector 이벤트 루프, 127.0.0.1:18000으로 재기동했다. 새 PID는 127584이며 창은 숨겼다. health/ready HTTP 200과 `ok`/`ready`를 확인했다. read-only transaction으로 전후 **RAG 22테이블 2,419행의 SHA와 상태가 동일**함을 확인했다. 신규 평가·실행·감사·생성 호출 0, 저장 프로파일·연결과 과거 영어 지침은 보존됐다. 실행 증거는 `api-rollout.json`, `api-verification.json`과 전후 DB 해시 기록에 있다.

반영 이후 실제 Gemma 생성은 실행하지 않았다. 다음 새 실행부터 한국어 지침을 구성하고 저장하며, 기존 영어 실행을 다시 열어도 당시 원문이 유지되는 것이 정상이다.

## 문제 이력과 보존

로그인된 본래 관리 화면에서 ISSUE-00037(`3d88b2e3-bc86-4665-a094-6a9502fa5778`)을 등록하고 한국어 지침/전달 계약 검증 범위를 완료로 기록했다. 요약 문서 `15f5be1f-ac17-4d4d-9efd-fbc18d78d640` 버전1을 정확히 연결했다. 실제 Gemma 품질 재평가 미실시와 과거 영어 원문 유지 조건은 남은 작업에 명시했다. 검색 재조회에서 저장된 내용·상태·문서 연결을 확인했고 화면 증거는 `issue37-verified.png`에 보존했다.

기존 변경150파일은146개 SHA 동일·허용4개 변경·누락0이다. 추가로 기존에 깨끗했던 테스트3개와 이 작업 기록1개가 작업 범위에 포함됐다. 사용자 이미지와 다른 변경은 보존했으며 커밋·푸시·캐시 정리는 하지 않았다.
