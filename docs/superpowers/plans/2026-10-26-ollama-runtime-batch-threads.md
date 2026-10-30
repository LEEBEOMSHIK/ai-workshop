# Ollama Runtime Batch and Threads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 같은 입력·근거·모델을 보존하는 선택형 배치/스레드 요청을 구현하고 실제 비교 가능한 후보를 준비한다.

**Architecture:** 기존 versioned orchestration policy에서 strict runtime 설정을 읽고 native codec에 전달한다. 기존 실제 HTTP 입력 보관으로 요청값을 추적하며 DB/UI 공용 응답 계약은 추가하지 않는다.

**Tech Stack:** Python3.13/Pydantic/OpenAI Agents SDK/httpx2/pytest, 현재 본래 Conda.

**Spec:** [ADR-0047](../../decisions/0047-ollama-runtime-batch-threads.md).

## Global Constraints

- 기존259 dirty 파일/원본25표2523행/.env·기본값 보존. 현재 checkout의 누적 수정에 의존하므로 그대로 이어서 작업. 설치·commit/push·cache삭제·새DB/계정 없음.
- 실제모델 호출 예산0; 이전2/2 소진. 실제 속도·품질은 별도 새 승인 뒤 검증한다.
- 제품 수정은 policy/codec/transport3파일만. raw config·입력 본문·모델·검색·인용·출력 한도·재시도 경계 유지.
- 작업 산출물은 `.local-data/project-agent-work/prefill-runtime-20261026/`. 메인만 문서/WORKBOARD/이슈/본래 API 통합 책임.

## Review Focus

- frozen MappingProxy 중첩 설정이 정상 해석되며 원래 config/snapshot을 변경하지 않는다.
- bool/float/문자열/unknown·범위 초과·빈 runtime은 생성 전에 거부된다.
- native 아닌 API/dialect/provider는 설정을 조용히 무시하지 않는다.
- 설정 없는 경로는 기존 실제 요청 bytes가 그대로이며 설정 있는 경로도 지정 두 options 외 입력은 같다.
- 실패/취소에도 실제 요청값이 보관되고 다른 actor에는 본문이 노출되지 않는다. 요청값을 실효값이라고 표시하지 않는다.

## Task 1: typed policy와 실제 전송 (구현 담당)

- [x] `models/orchestration_policy.py`: `OllamaRuntimeOptions(version,num_batch?,num_thread?)`, `OrchestrationPolicy.ollama_runtime` 및 frozen mapping/native-only 검증. 계약 실패 테스트 먼저 RED 확인.
- [x] `orchestration/ollama_chat.py`: native_chat_request에 typed 선택 인자 추가, 허용 두값만options에 복사하고 기본bytes 유지.
- [x] `orchestration/model_transport.py`: 선택값 전달, 기존 실제wire수집/전송전ACL·예산·실패·취소 유지.
- [x] `tests/unit/labs/rag/orchestration/test_ollama_runtime.py`: strict policy, native-only, frozen config, 두dispatch 실제SDKwire·trace, 기본bytes동일·재시도0 검증.
- [x] 관련pytest와 제품3파일/필요타입의 strictMypy·Ruff 통과.

## Task 2: 독립 수용 (검증 담당, 제품 수정 금지)

- [x] 별도 runtime 독립 테스트로 실제SDK에 두옵션전달/입력·인용보존·불일치거부·오류/취소의요청값보관·재시도0 검증.
- [x] 본래 DB rollback 한정 저장→현재ACL재조회와 다른actor거부·legacy조회·원본보존 확인. 기존통합fixture를 재사용하고새DB는 만들지않음.
- [x] 관련회귀·설계대조코드리뷰. 불필요하게 전체저장소를 반복검사하지 않는다.

## Task 3: 통합·기록·실측 준비 (메인)

- [x] ADR/RAGdesign/runbook/WORKBOARD/ISSUE38 갱신 및 본래 API 반영·health/ready 확인.
- [x] baseline direct와 num_batch256만변경하는 비기본 후보JSON 및 4전송상한·retry0 실측계획 준비. 아직 DB등록/실제전송하지 않는다.
- [x] 원본파일/.env/DB보존, 독립결과·실효값미확인/기존품질실패·실제모델0을 확인하고 결과 보고.

## Rulings

- 기존 역할 담당의 조사 문맥을 재사용하고 구현과 독립검증을 분리한다. 사용자 요청으로 이미 정해진 동일 모델·입력·품질보존 목적과 배치/스레드 후속 범위 안의 가역적 구현을 진행한다.
- profile별 제한된 native options를 선택한다. 전역설정과 저장모델parameter는 다른요청까지바꾸므로 채택하지 않는다.
- 첫 후보는 batch256 하나이며 thread는 자동 유지한다. 최적값/속도개선은 미확정이다.


## 승인 후 실제 비교 마감

- [x] 사용자 새 최대4회·retry0 승인으로 baseline2+batch2562 완료, 실제전송과DB modelspan4 일치.
- [x] 동일 입력·답변·인용·28근거 및 원본2523행/.env·제품62파일 보존, 허용신규24행만 확인.
- [x] 실제1024→256에서 첫입력130.876→132.683초(+1.38%)로 미개선, 후보비기본 유지·호출예산소진 기록.
- [ ] 실제결과의 ISSUE38 DB갱신·완료화면 확인: Windows 현재URL을 확정할 수 없어 Computer Use가 중단됨. 준비된 issue38-live-update.json과 worklog를 다음 정상 UI세션에서 반영한다.
