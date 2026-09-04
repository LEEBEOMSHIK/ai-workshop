# 대화형 생성 RAG V2 구현 기록

- 날짜: 2026-09-04
- 브랜치: `main`
- 상태: 애플리케이션 구현·자동 검증 완료, 실제 로컬 LLM 선택·설치·smoke 대기

## 구현 결과

- 추출식 기준선과 생성형 답변 정책을 분리하고, 생성형 저장 구성에는 정확한 Generation
  Profile과 LLM binding이 반드시 존재하도록 도메인·DB trigger·API 계약을 V2로 확장했다.
- `search_ready`, `answer_ready`, `service_ready`를 분리했다. 검색 화면은 세 상태가 모두
  준비된 구성만 질문을 제출할 수 있다.
- 로컬 loopback 주소만 허용하는 provider 독립 OpenAI-compatible adapter를 구현했다.
  등록한 `runtime_model`과 `/v1/models` 응답이 정확히 일치해야 준비 상태가 된다.
- 첫 질문은 원문으로 검색하고 후속질문은 bounded 이전 turn과 현재 질문을 독립 검색 질의로
  문맥화한다. 같은 제한된 history만 문맥화와 최종 답변 생성에 전달한다.
- 검증된 assistant turn에 actor·구성 버전·turn ID·본문 해시 기반 HMAC 토큰을 발급한다.
  위조됐거나 다른 사용자·구성의 assistant turn은 검색 전에 거절한다.
- Hybrid 검색과 근거 선별 뒤에만 구조화된 답변을 생성한다. 근거 부족이면 LLM을 호출하지
  않고, 허용되지 않은 인용·출처 위치·중요 수치나 날짜 검증이 실패하면 생성 초안을
  사용자에게 노출하지 않는다.
- 리랭커가 없는 상태는 정상으로 유지한다. 현재 V2에는 리랭커 실행 구현을 추가하지 않았고
  RRF 결과를 바로 근거 선별에 전달한다.
- 관리자 구성 화면에서 추출식/생성형 답변 방식과 버전이 고정된 Generation Profile·LLM을
  선택하고 준비 상태를 확인할 수 있다. 사용자 화면은 여러 질문·AI 답변·인용·원래 질문과
  실제 검색 질의를 한 대화로 보여준다.

## 검증 증거

- Backend 전체 단위 테스트: `464 passed`.
- RAG 검색 API 통합: `34 passed`.
- 구성 API·구성/생성 도메인: `51 passed`.
- 격리 PostgreSQL에서 0015 migration과 생성 구성 해석: `1 passed`.
- Frontend 전체: `41 files, 174 passed`.
- Python Ruff, mypy 145개 source, `uv lock --check` 통과.
- TypeScript, ESLint, OpenAPI 생성물 check, Next.js 16.3.4 production build 통과.
- 실제 저장소 프로젝트 에이전트 계약 `validate`와 `git diff --check` 통과.

## 선별 실패와 환경 메모

- 최초 전체 backend 실행 1건은 루트 개발 `.env`의 Elasticsearch 접두사가 기본값 테스트에
  주입돼 실패했다. backend 디렉터리에서 격리해 재실행했다.
- 긴 Windows `--basetemp`가 중첩 UUID 객체 경로와 합쳐져 Asset 단위 테스트 8건이 경로
  길이 오류로 실패했다. 짧은 `%TEMP%\\awv2u`로 같은 전체 단위 테스트가 통과했다.
- 프로젝트 에이전트 검증기 자체 테스트 중 5건은 Windows가 테스트용 확장자 없는 가짜
  `git`을 실행하지 못해 실패했다. 변경 대상은 아니며 실제 저장소 `validate`는 통과했다.
- FastAPI TestClient에서 기존 Starlette의 httpx2 전환 안내 경고가 남아 있다.

## 남은 실제 실행 게이트

- 실제 로컬 LLM 제품·모델은 아직 선택하거나 다운로드하지 않았다. PC 자원, 라이선스,
  한국어·금융 품질과 JSON 구조화 출력 지원을 비교한 뒤 사용자가 승인한 정확한 모델 버전을
  Registry와 Generation Profile에 등록해야 한다.
- 개발 DB를 migration 0015로 올리고 로컬 실행기를 연결한 뒤, 업로드된 비민감 합성 문서로
  첫 질문 → 대명사/생략형 후속질문 → 문맥화 질의 → 검증된 답변·인용을 실제 브라우저에서
  확인해야 한다.
