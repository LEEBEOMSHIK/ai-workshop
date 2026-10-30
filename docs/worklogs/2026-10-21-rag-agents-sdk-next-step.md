# RAG Agents SDK 다음 작업 확인

- 확인일: 2026-10-21
- 범위: 사용자 요청에 따른 후속 순서·기술 명칭·현재 의존성 확인과 기존 준비 계획 정정.
- 상태: 준비 범위 확인. SDK 버전 선정·호환성 표·ADR·설치·구현·활성화는 미완료.

[WORKBOARD의 작업 순서](../../WORKBOARD.md#다음-작업-순서)는 RAG 기능 마감 → Agents SDK → 벡터 저장소 비교 → 로컬 LLM 파인튜닝 비교 → Kubernetes다. 따라서 취소 요청·색인 소유권·첨부 복구 다음에 등록된 작업은 **OpenAI Agents SDK를 사용하는 서비스 RAG 실행 조율 계층 준비**다. 호환성 조사·설계는 복구와 병행 가능하며, 보류한 12B/GPU 품질 비교를 다시 실행해야만 준비를 시작할 수 있는 것은 아니다. 이 기록은 복구 세 항목의 완료를 판정하지 않는다.

## 구분과 근거

| 이름 | 이번 프로젝트에서의 위치 | 현재 판단 |
|---|---|---|
| OpenAI Agents SDK | 애플리케이션 내부의 모델 반복·도구·전문 역할 호출 조율 | 다음 도입 대상. 기존 권한·세션 DB·검색·인용 검증을 보존하고 어댑터 뒤에서 검토 |
| Codex SDK / App Server | 로컬 Codex 실행과 클라이언트 통합 | 기존 별도 Provider 조사. 격리 차단이나 개인 Codex 실행 조건은 이번 준비로 해제하지 않음 |
| 프로젝트 개발 에이전트 | Codex 협업 도구와 저장소 역할·독립 검증 규칙 | 현재 개발 작업 방식. 서비스 SDK 설치로 교체하는 대상이 아님 |

공식 OpenAI 문서는 Agents SDK를 애플리케이션에서 실행하며 서버가 도구·저장소·승인·런타임을 소유하는 계층으로 설명한다. 이는 기존 계획의 책임 경계와 일치한다. [Agents SDK 공식 안내](https://developers.openai.com/api/docs/guides/agents/sdk), [실행 계층 비교](https://developers.openai.com/api/docs/guides/agents).

Codex SDK 공식 문서는 로컬 Codex의 프로그래밍 제어와 App Server 기반 클라이언트 통합을 별도로 설명한다. 현재 안내에는 TypeScript와 Python SDK가 모두 있으므로 Codex SDK를 TypeScript 전용이라고 설명하지 않는다. 공식 `developers.openai.com/codex/sdk/`를 열었을 때 아래 공식 문서로 이동한 것을 확인했다. [Codex SDK 공식 안내](https://learn.chatgpt.com/docs/codex-sdk).

이 구분은 [RAG 설계 §10](../labs/rag/design.md#10-rag-에이전트-조직), [기존 Codex Provider 결정](../decisions/0010-development-codex-sdk-provider.md), [개발 에이전트 정본](../project-agents/README.md)에 따른다. SDK가 생성을 조율한다는 사실만으로 모델의 답변 품질이나 지연이 개선됐다고 판정하지 않는다.

## 실제 환경 확인

기존 실행 파일에서 `-I -B`와 표준 라이브러리 `sys`, `sysconfig`, `platform`, `importlib.metadata`만 사용해 아래 값을 읽었다. SDK·모델 모듈 import나 모델 요청은 하지 않았다.

| 항목 | 2026-10-21 확인값 |
|---|---|
| Python | `C:\projects\ai-workshop\backend\.conda\python.exe`, 3.13.16 |
| 실행 아키텍처 | `platform.machine() = AMD64`, `sysconfig.get_platform() = win-amd64` |
| 프로젝트 Python 범위 | `backend/pyproject.toml`: `>=3.13,<3.14` |
| 현재 설치 배포 메타데이터 | `openai-agents`, `openai`, `mcp` 없음; HTTPX 0.28.1, Pydantic 2.13.5 |
| 의존성 선언 | `backend/pyproject.toml`, `backend/uv.lock`에 Agents SDK 선언 없음 |
| 기존 모델 실행 포트 | `GenerationRuntimePort.health/contextualize/generate` |
| 기존 resolver | 로컬 OpenAI 호환·OpenAI Responses 어댑터 및 local Transformers 경로. SDK 조율 어댑터 확인되지 않음 |

배포 메타데이터 없음은 이 Python 환경에 대한 확인이며 다른 환경에 SDK가 없다는 뜻은 아니다. 현재 패키지와 Python 버전만으로 새 SDK의 의존성 해석·네이티브 호환성·로컬 모델 도구 호출 지원을 통과 처리하지 않는다. 호스트 OS의 아키텍처와 위 Python 실행 아키텍처도 별개다.

## 다음 준비 단계

1. 공식 릴리스의 버전 후보·Python 요구·종속성 범위를 확인해 기존 잠금과 비교한다. 패키지 설치 전에 의존성 변경과 복구 경계를 정한다.
2. 기존 Provider별 모델 어댑터·구조 출력·도구 호출·취소·usage 지원을 표로 정리한다. 현재 Gemma/Ollama가 SDK의 모든 기능을 지원한다고 가정하지 않는다.
3. 외부 호출 없는 fake model 검증 계약과 실행 예산·취소·늦은 응답·현재 권한 재검사·trace 비활성화 검증을 설계한다. 기존 DB를 세션 정본으로 유지한다.
4. 실행 계층 위치와 식별자 연결을 ADR·구현 계획으로 확정한 뒤 어댑터 구현으로 넘어간다. 별칭 종료 게이트와 품질 기준은 유지한다.

현재 공식 [모델·Provider 문서](https://developers.openai.com/api/docs/guides/agents/models)는 모델과 실행 기본값을 명시하도록 안내한다. 이번 확인에서는 구체적인 SDK 버전·Provider 호환성 판정·인증/trace 설정 검증을 마치지 않았으며, 위 준비 단계의 완료 표시를 바꾸지 않았다.

## 변경과 검증

[2026-10-04 준비 계획](../superpowers/plans/2026-10-04-rag-agents-sdk-adoption.md)의 당시 등록 이력과 설계 방향은 유지했다. 실행 기준을 현재 AMD64 Conda로 정정하고 구 `.venv` 명령을 로컬 실행서의 `$workshopPython` 절차로 연결했다. 준비 범위와 실제 구현·활성화의 차이를 명시하고 WORKBOARD 앵커를 현재 제목으로 맞췄다.

두 문서의 로컬 상대 링크·앵커 16개와 변경 공백 검사를 통과했다. `pyproject.toml`과 `uv.lock`을 표준 `tomllib`로 읽어 SDK 관련 의존성 부재도 확인했다. SDK 설치·dependency lock 수정·실제 SDK 실행은 하지 않았으므로 SDK 호환성 검증 결과는 없다. 운영 상태·DB·브라우저·계정·큐·모델 설정은 이 하위 작업에서 변경하지 않았다.
