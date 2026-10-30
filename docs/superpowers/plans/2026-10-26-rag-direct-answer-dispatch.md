# RAG Direct Answer Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 동일 답변 담당 입력을 보존하며 명시적으로 선택한 경로의 불필요한 관리자 모델 호출을 제거한다.

**Architecture:** 기존 RAG orchestration 어댑터에서 모드를 선택하고 공통 specialist와 SDK Runner를 재사용한다. 모델/권한/검색/인용/저장 경계를 바꾸지 않는다.

**Tech Stack:** Python3.13, Pydantic, OpenAI Agents SDK0.24, httpx2, pytest.

**Spec:** [ADR-0046](../../decisions/0046-rag-direct-answer-dispatch.md).

## Global Constraints

- 기존252개 dirty 파일을 보존한다. 의존하는 누적 변경이 있는 현재 본래 checkout을 사용한다. commit/push·설치·캐시 삭제·별도 DB/계정 생성 없음.
- 제품·검증 실행은 기존 Conda 환경과 `.local-data/project-agent-work/first-response-packing-20261026` 산출물을 사용한다.
- 구현 중 추가 모델 호출 예산0. 이후 사용자 새 승인 최대2회·retry0으로 실제 검증을 완료했고2/2회 소진했다.
- 기존manager_delegation 기본 경로와 API/프로파일 raw snapshot을 보존한다. 직접 경로만 모델1회/도구0회다.

## Task 1: 명시적 계약과 SDK 경로 (backend 구현 담당)

- [x] `models/orchestration_policy.py`: strict Literal dispatch_mode, 기본manager_delegation, 잘못된값 거부 테스트를 먼저 실패 확인.
- [x] `orchestration/budget.py`: 직접1/기존2 및 선행 문맥화 예산의 경계 테스트를 먼저 실패 확인.
- [x] `orchestration/openai_agents.py`: 공통 specialist 입력 조립을 재사용하고 direct_answer에서 Runner.run(specialist), 실 hook 수집·최종출력/도구0 확인. 기존manager/as_tool 흐름과 입력 순서 보존.
- [x] `tests/unit/labs/rag/orchestration/test_direct_answer.py`: 실제 SDK mock으로 두 모드 specialist wire 일치, HTTP1/2와span2/5, 기본·오류·예산·취소 검증. 기존 test_agents_sdk/test_pipeline/test_ollama_native_transport도 실행.
- [x] 변경 Python strict Mypy·Ruff 통과. 공유 타입 문제는 좁게 수정하고 설계 외 변경은 root에 보고.

## Task 2: 독립 수용·기존 환경 (독립 검증 담당, 구현 파일 수정 금지)

- [x] 별도 `test_direct_answer_independent.py`에서 native v6 실제SDK 단일호출/두span·eN map·본문 보관·현재ACL 거부·malformed/timeout/cancel·선행 문맥화 예산을 검증.
- [x] 기존 DB에서 rollback만 하는 저장/조회 테스트에 직접trace 형태를 검사. 기존 config snapshot 보존 검증.
- [x] 관련 회귀 범위 실행 및 중복 없는 테스트 수 집계, 독립 코드 리뷰. UI는 기존 패널의 단일 최상위agent 표현 검증으로 충분한지 확인.

## Task 3: 통합·기록·실측 준비 (root)

- [x] ADR·RAG설계·runbook·WORKBOARD와 작업 결과를 갱신하고 본래 API에 반영/health/readiness 확인.
- [x] 기존 공개 질문과 v6 frozen 설정에서 dispatch_mode만 바꾸는 draft 후보·실측 실행기를 준비. 실제 생성 전 허용 모델 호출2/재시도0와 비교 자료를 검토 가능한 형태로 남김.
- [x] 기존파일·.env·DB 보존 및 실제호출0을 확인. 품질·속도 미확인과 기존품질 실패를 정확히 보고.

## Rulings

- 2026-10-26: 입력 사전화 이득은 최대61B로 작고 batch tuning 효과도 미확인. 관측된 정보 추가 없는 관리자 호출 제거를 별도 선택 모드로 구현한다. 기존 모델 위임 경로는 보존한다.
- 2026-10-26: 현재 작업에서 구현과 독립 검증을 분리하되 기존 에이전트의 조사 문맥을 재사용한다. 별도 커밋·작업 디렉터리 제거는 사용자 승인 범위 및 보존 정책상 수행하지 않는다.

## 완료 근거

2026-10-26: backend405/DBrollback1/frontend38, strictMypy11/Ruff/TypeScript/OpenAPI통과. 본래API54904·health/ready200 후 사용자 새 승인2/2회·retry0 실측완료. 실제 실행시각순 전체 첫210.948→193.908초·반복16.810→13.549초, 두답변/인용과28근거/입력동일. 첫 입력처리134.920초·정답0/2는 남아 비승격이다. 원본25표2508행/.env보존·허용신규15행, 본래2/2완료·실제2단계 확인. [결과](../../worklogs/2026-10-26-rag-direct-answer-dispatch.md).
