# Ollama native timing implementation plan

**Goal:** SDK 관리자/답변 담당의 실제 서버 준비·입력·출력 시간을 수집하는 선택적 경로를 구현한다.
**Architecture:** 프로파일 명시 선택 → readiness/runtime gate → 좁은 native codec → 기존 bounded transport/trace 저장. 기존 경로 기본값 유지.
**Tech stack:** Python, Pydantic, httpx2, OpenAI Agents SDK, 기존 PostgreSQL JSON.
**Spec:** [ADR-0043](../../decisions/0043-ollama-native-timing.md)

## 제약

실제 모델0회로 구현/독립 검증한다. 기존4회 예산·DB/프로파일·기본값·서비스를 임의 전환하지 않는다. 기존 수정 파일을 보존하며 commit/push와 캐시 제거는 하지 않는다. 기본 모델2회·도구1회·retry0·1MiB 응답 제한을 유지한다.

## 작업

- [x] AI 구현 담당: 새 orchestration/ollama_chat.py의 엄격한 요청/응답 codec과 독립된 합성 테스트. 기존 호환 변환과 temperature/top_p/num_predict/format/think·도구 검증 동등성 확인.
- [x] 메인 백엔드: policy 선택/readiness/실행 gate, 실제 wire trace, native timing 파싱/저장 계약을 실패 테스트 후 구현. 실제 프로파일은 그대로 보존.
- [x] 독립 검토자: 기본 경로 보존, frozen config, 잘못된 native binding, 토큰/호출 예산, 부분 body/크기/timeout/cancel/종료 확인, missing/invalid 지표와 저장 호환을 확인.
- [x] 메인: 관련 단위 테스트·범위 strict 타입·Ruff·API 타입·독립 검토 결과 통합. WORKBOARD/실제 수용 경계를 기록하고 재측정 가능한 구체적 변경을 제시.

구현·검증 결과와 별도로 남은 실제 활성화/재측정은 [작업 기록](../../worklogs/2026-10-26-ollama-native-timing.md)을 따른다.

## 검증 명령

기존 Conda 실행기로 backend 단위 orchestration·executions·generation readiness 범위 pytest를 실행한다. 네트워크/모델은 mock이며 Windows asyncio socketpair에 필요한 정상 실행 권한을 사용한다. 새 통합 검증이 필요하면 기존 DB의 명시 opt-in·COMMIT 거절·외부 rollback만 허용한다. frontend OpenAPI 생성/일치와 tsc를 실행한다.
