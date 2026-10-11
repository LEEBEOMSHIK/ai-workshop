# RAG Agents SDK 도입 준비 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OpenAI Agents SDK를 RAG 서비스 에이전트 실행 계층에 도입하기 위한 호환성, 책임 경계, 단계별 구현·검증 기준을 확정한다.

**Architecture:** 기존 FastAPI 애플리케이션이 권한·세션·검색 범위·실행 수명주기를 소유하고, SDK는 어댑터 뒤에서 모델 실행과 전문 역할 호출을 조율한다. 현재 검색·생성 파이프라인을 비교 기준으로 유지하고 검증된 후보만 명시적으로 활성화한다.

**Tech Stack:** 기존 Python 3.13, FastAPI, PostgreSQL/SQLAlchemy, HTTPX와 OpenAI Agents SDK Python. SDK 및 종속 OpenAI 클라이언트의 고정 버전은 첫 호환성 검증에서 결정한다.

**Spec:** [RAG 설계 — 에이전트 조직](../../labs/rag/design.md#10-rag-에이전트-조직), [시스템 에이전트 실행 원칙](../../architecture/system-design.md#7-에이전트-실행-원칙).

- 등록일: 2026-10-04
- 상태: 사용자 요청으로 다음 작업에 등록. 도입 준비·방향 정리 완료, 구현·설치·활성화 미착수.
- 결정 소유자: 사용자 요구를 기준으로 메인 Codex가 구현 범위와 통합을 관리한다.
- 이 문서는 도입 방향과 준비 작업의 인계 계획이다. SDK 세부 인터페이스·ADR·실행 가능한 구현 계획은 아래 준비 작업에서 확정한다.

## 도입 목적과 구분

반복적인 모델 실행·도구 호출·전문 역할 호출·오류 전달을 SDK 실행 계층으로 정리한다. 효율은 구현 중복 감소와 실제 호출 수·토큰·지연·정확도 측정으로 판단하며, SDK 설치만으로 개선됐다고 보고하지 않는다.

- 서비스 RAG 에이전트: 이번 도입 대상. 중앙 조정자가 필요한 전문 역할을 도구로 호출하는 구성을 우선 검토한다.
- 프로젝트 개발 에이전트: 기존 Codex 협업 도구와 `docs/project-agents` 역할·인계 규칙을 유지한다. 프로젝트 SDK 설치가 Codex 개발 도구를 교체하지 않는다.
- Agents SDK와 기존 Codex SDK Provider 조사는 별개다. 기존 Codex SDK/App Server 격리 차단이나 개인 Codex 실행 승인 조건을 이번 도입으로 해제하지 않는다.

## Global Constraints

- 기존 DB·계정·문서·세션·프로파일·활성 연결을 보존한다. 사용자 확인용 별도 환경·DB·계정을 만들지 않는다.
- Python 환경 기준은 `>=3.13,<3.14`이며 현재 Windows ARM64와 기존 의존성의 호환성을 확인한다.
- SDK 타입은 어댑터 내부에 둔다. Platform은 Labs/RAG 구현에 의존하지 않는다.
- 기존 DB가 대화 이력의 정본이다. 매 요청의 현재 권한·범위·revision·외부 전송 승인에 맞는 이력만 SDK에 전달한다. SDK의 별도 자동 세션 저장소를 정본으로 추가하지 않는다.
- 모델·endpoint·credential은 기존 Deployment와 Profile 계약을 따른다. Codex 로그인으로 Agents SDK의 API 인증을 대신할 수 있다고 가정하지 않는다.
- 파싱·청킹·BM25·dense·RRF·권한 검사·정확 인용 검증은 결정적인 서비스로 유지한다. 첫 검색 순위를 LLM에 맡기지 않는다.
- 에이전트에는 승인된 애플리케이션 도구만 제공한다. 직접 DB·ES·파일시스템·shell 접근 도구를 추가하지 않는다.
- 외부 모델에는 현재 승인된 자료만 전달한다. SDK trace도 외부 전송에 포함하며, 초기 외부 trace export는 비활성화하고 기존 내부 모니터링에 안전한 메타데이터를 연결한다.
- SDK 세션 메모리나 handoff는 현재 권한 확인·문서 revision·인용 검증을 대체하지 않는다.
- 선택한 모델 실패 시 다른 모델·기존 실행 경로로 조용히 전환하지 않는다. 취소 요청과 실제 실행 종료를 구분한다.
- ISSUE-00013의 frozen 상태는 보존한다. SDK 도입이 종료 proof·receipt·gate 해제·새 parity를 대신하지 않는다. 새 별칭 쓰기가 필요한 검증은 기존 종료 게이트 충족 후 진행한다.

## 책임과 기술 흐름

```text
기존 대화 API
  → 애플리케이션 권한·범위·현재 이력·전송 승인 확인
  → RAG 실행 조정 계층
  → Agents SDK 어댑터: 필요한 전문 역할 호출
  → 기존 권한 범위 검색·근거 검토·답변 도구
  → 애플리케이션의 인용·현재 권한·최종 저장 검증
  → 기존 세션 DB 및 실행 모니터링
```

제안한 초기 협업은 중앙 조정자 + 필요 시 질의 분석·근거 충돌 검토·답변 작성 역할이다. 간단한 질문에 모든 역할을 호출하지 않는다. 전문 에이전트를 도구로 호출하는 방식과 제어권을 넘기는 handoff를 구분하고, 첫 구현은 중앙 조정자가 결과를 통합하는 방식을 우선한다. 독립적인 읽기 작업만 병렬화하며 의존 작업·동일 세션 저장은 직렬화한다.

## Review Focus

- 이력 중 문서 권한 철회·범위 변경: 현재 허용되는 구간과 근거만 모델 입력에 포함.
- 연결 모델이 필요한 SDK 기능·파라미터를 미지원: 명시적 준비 불가 사유, 무단 모델 변경 없음.
- 취소·timeout 뒤 늦은 응답 또는 재시도: 기존 request ID/revision을 보존하고 중복 turn·잘못된 완료 저장 없음.
- 전문 역할 실패·근거 부족·잘못된 구조 출력: 어느 단계에서 실패했는지 기록하고 인용 검증을 통과하지 않은 답변은 정상 답변으로 저장하지 않음.
- trace·예외·도구 입출력: 비공개 본문·비밀·내부 추론을 로그나 외부 trace로 유출하지 않음.

## 준비 작업 1: 공식 SDK·현재 환경·모델 호환성 확인

**Files:** 읽기 대상 `backend/pyproject.toml`, `backend/uv.lock`, `generation/contracts.py`, `generation/runtime_resolver.py`, `generation/openai_responses.py`, `generation/openai_compatible.py`와 `generation/codex_runtime.py`(모두 기존 RAG 경로). 산출물 `docs/worklogs/2026-10-04-rag-agents-sdk-compatibility.md`는 실제 조사를 시작할 때 생성한다.

**Interfaces:** 입력은 현재 의존성·Deployment/Profile 공개 계약·공식 SDK 문서. 출력은 버전 후보, provider별 지원 기능, 안전한 trace 설정, 로컬 실행 가능 여부와 지원하지 못하는 기능을 명시한 호환성 표다.

- [ ] 공식 문서와 패키지 릴리스의 정확한 버전·Python/OS 요구·종속성을 확인하고 출처·확인일을 기록한다.
- [ ] 현재 Provider마다 SDK 모델 어댑터·구조 출력·도구 호출·취소·usage를 지원하는지 판정한다. 개인 Codex exec 경로의 지원을 추정하지 않는다.
- [ ] 외부 호출 없는 fake model로 실행 반복·전문 역할 도구 호출·구조 출력·실패·trace 비활성화를 확인할 검증 명령과 계약을 정한다. 본래 환경의 패키지 설치 전에 lock diff와 기존 의존성 보존 방법을 구체화한다.
- [ ] 호환성 표를 독립 AI·보안 검토에 인계하고 도입 가능한 첫 provider와 남은 제한을 확정한다. 확인되지 않은 기능은 미검증으로 남긴다.

## 준비 작업 2: 실행 계약·ADR·구현 작업 분할 확정

**Files:** 읽기 대상 `backend/src/ai_workshop/labs/rag/search/pipeline.py`, `conversations/service.py`, `generation/domain.py`, `generation/contracts.py`, `executions/observer.py`와 관련 단위 테스트. 문서 수정은 RAG·시스템 설계, 이 계획과 다음 사용 가능한 번호의 ADR이며, 번호는 작성 직전 확인한다.

**Interfaces:** 준비 작업 1의 호환성 표를 사용한다. SDK 타입을 노출하지 않는 실행 포트, 도구 입력·출력 계약, 예산·취소·오류·관찰 이벤트와 기존 request/turn/execution ID 연결표를 산출한다.

- [ ] 기존 `GenerationRuntimePort`의 `health/contextualize/generate`와 다중 역할 조정의 책임을 비교해 SDK 실행 계층의 위치를 확정한다. SDK는 orchestration 수단이므로 단순히 새로운 모델 Provider로 취급하지 않는다.
- [ ] 역할별 입력·결과·근거 참조·의존 단계와 권한 재검사 위치를 확정한다. 모델 반복·도구 호출·동시성·전체 시간·토큰 한도는 설정 또는 버전 있는 실행 프로파일로 관리한다.
- [ ] Review Focus 5개를 실패 테스트로 배정하고 테스트 파일·정확한 타입/함수·mock 경계·실행 명령을 구현 계획에 기록한다. 새 영속 프로파일·이벤트가 필요하면 그 작업에 migration과 호환성 검증을 포함한다.
- [ ] ADR에 채택 근거·대안·영향·제한을 기록하고 독립 설계 검토 후 아래 구현 단계로 인계한다. 실행 계획에는 최소 필수 역할을 다시 계산해 고지한다.

## 후속 구현 순서와 완료 기준

| 순서 | 작업 | 완료 기준 |
|---|---|---|
| 1 | SDK 의존성과 어댑터 | 버전 고정·기존 의존성 보존, fake model 실행 및 오류/취소/출력 계약·타입 검사 통과 |
| 2 | 기존 세션·권한·실행 수명주기 연결 | 첫 질문 생성·기존 대화 이어가기·문맥 구간·권한 철회·중복 요청·늦은 완료 회귀 통과 |
| 3 | 중앙 조정자와 전문 역할 협업 | 애플리케이션 도구만 호출, 간단한 질문의 불필요 역할 생략, 독립 작업만 병렬 실행, 예산 초과 명시 |
| 4 | 기존 실행 모니터링 연결 | 질문→역할→도구→답변의 식별자 연결, 호출/토큰/소요 시간/오류/인용 결과 저장, 실패 이전 측정값 보존 및 화면 조회 |
| 5 | 현재 파이프라인과 비교·본래 환경 검증 | 동일 승인 합성 질문·문서·프로파일로 결과와 비용/속도를 비교하고 기존 마스터 화면에서 세션·멀티턴·실패 흐름 확인 |
| 6 | 문서·흐름도·실행 인계 | 구현한 기술 구성·협업 흐름·제한을 갱신하고 적용·검증·미완료 범위를 구분. 검증 전 기본 활성 경로를 변경하지 않음 |

SDK 도입 완료와 효율 개선 입증은 별도 판정이다. 비교 항목은 정답·인용 검증률, 근거 부족/실행 실패, 모델·도구 호출 수, input/output token, 전체 및 단계별 지연(p50/p95)이다. 동일 실행 조건에서 승인된 모델 가격을 확인할 수 있을 때만 비용을 계산하고, 불가능하면 추정값과 측정값을 구분한다. 자동 평가와 실제 질문 둘 다 확인하며 기존 구성의 자동 승격은 하지 않는다.

## 검증·인계

- 문서 준비 완료 검증: 로컬 상대 링크·정본 연결·차이 공백 검사·WORKBOARD 최근 완료 최대5개 확인.
- 구현 검증 기본 명령(실행 위치 `backend`): `.venv/Scripts/python.exe -m pytest tests/unit/labs/rag/generation tests/unit/labs/rag/conversations tests/unit/labs/rag/executions -q`, `.venv/Scripts/python.exe -m ruff check src tests`, `.venv/Scripts/python.exe -m mypy src`.
- SDK 전용 테스트와 실제 DB·브라우저 검증은 준비 작업 2에서 정확한 명령·비파괴 조건을 확정한다. 전체 pytest에 실사용 `.env`를 혼입하지 않는다.
- 현재 문서 작업은 메인 Codex가 작성하고 설계·ADR 문서 관리자가 독립 검토한다. 구현 시 AI 런타임·Python·RAG·권한·외부 전송·테스트/독립 검증 역할을 실제 범위에 맞춰 배정한다. UI·DB·배포 역할은 해당 변경이 있을 때만 추가한다.
- 첫 재개 작업은 준비 작업 1이다. ISSUE-00013과 기존 RAG 기능 마감 게이트는 보존하며, 준비·오프라인 검증을 진행해도 frozen 상태의 해제나 기능 완료를 주장하지 않는다.

## 근거

사용자 추가 후속(2026-10-04): SDK 도입 이후 진행할 [벡터 저장소 비교·로컬 LLM 파인튜닝 계획](2026-10-04-rag-vector-store-and-local-llm-experiments.md)을 별도로 등록했다. 두 실험은 SDK 도입의 완료 조건에 합치지 않으며 현재 설치·학습·실험 실행은 미착수다.

문서 준비 검증(2026-10-04): 로컬 상대 파일 링크·WORKBOARD 최근 완료5개·역할 계약·공백 검사를 통과했다. 독립 설계·ADR 문서 검토에서 정본/승인 범위 충돌이나 차단 결함을 찾지 못했고, 연결된 앵커와 현재 Python·GenerationRuntimePort 계약의 일치를 확인했다. 이 결과는 문서 등록에 한정되며 SDK 호환성·설치·모델 실행의 검증 결과가 아니다.

- [OpenAI 공식 Agents SDK 안내](https://developers.openai.com/tracks/building-agents#foundations-of-the-agents-sdk): 실행 반복, 도구 호출, handoff, session, guardrail, tracing의 책임 설명. 공식 문서 확인일 2026-10-04.
- [개발 에이전트 정본](../../project-agents/README.md), [개발 규칙](../../guidelines/development-guidelines.md), [실행 모니터링 ADR](../../decisions/0029-rag-execution-monitoring.md), [대화 세션 ADR](../../decisions/0023-domain-cabinet-conversation.md).
- [현재 별칭 종료 경계](../../worklogs/2026-10-02-rag-control-boundary-assessment.md), [작업 순서](../../../WORKBOARD.md#다음-작업).
