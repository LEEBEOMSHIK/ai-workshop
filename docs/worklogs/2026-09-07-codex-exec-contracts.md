# 개인용 Codex RAG 입력·출력 계약 구현

- 기준일: 2026-09-07
- 상태: 메인 화면 MVP 우선 요청으로 인계 대기, 실제 CLI 연결 및 RAG 대화는 미검증
- 승인: 사용자가 상세 설계 확인 뒤 역할별 구현 진행을 승인했다.
- 정본: [상세 설계](../superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md),
  [실행 계획](../superpowers/plans/2026-09-07-codex-exec-contracts.md),
  [ADR-0017](../decisions/0017-personal-codex-exec-provider.md)

## 작업 경계

main에서 기존 변경을 보존한다. 신뢰된 버전 지침·입력 JSON 분리와 답변 v2 파서를 먼저 구현한다.
기존 Provider와 v1 계약은 유지하며 새 기능을 DB·관리자 화면·검색 기본값에 자동 연결하지 않는다.
모델 호출, 인증 조회·변경, 개발 DB migration, 서버·Docker 재시작은 하지 않았다.

## 기준선

`backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/unit/labs/rag/generation -q`

변경 전: 105 passed in 1.47s. HEAD `9082bb55d61665d4613c9ba9e91cb4d02cbfc9aa`.
기존 미커밋 OCR·Learning·도메인 작업과 분리해서 검사한다.

## 출력 v2 완료 및 독립 검토

신규 `structured_output_v2.py`와 회귀 테스트를 구현했다. 기존 v1 parser/schema는 변경하지 않았다.
근거가 부족하면 claims 없는 명시적 보류 상태를 반환하고, 정상 답변은 현재 근거 ID를 검증한다.
중복 JSON key·미허용 ID·NaN/Infinity·지수 오버플로·부적절한 필드는 안전한 검증 오류로 거절한다.

독립 리뷰의 중요 지적 2건(정적 schema 제약 누락, 지수 오버플로 오류 경계)을 RED로 재현해 수정했다.
재리뷰에서 두 건 모두 해결됐으며 새 중요 문제는 발견되지 않았다.
최종 담당 검증: focused 35 passed, generation 140 passed, scoped Ruff lint/format·mypy 통과.
이 수치는 출력 계약 단계 결과이며 이후 입력 조립 단계와 전체 검증은 별도로 기록한다.

## 내부 지침과 입력 조립 완료

`codex-control-v1.txt`는 승인된 통제 지침, `codex-answer-v2.txt`와
`codex-contextualize-v1.txt`는 각 작업의 출력·근거 경계를 담는다.
`codex_prompt.py`는 registry 자산으로만 개발자 지침을 조립하고 질문·이력·근거를 별도 canonical JSON으로 반환한다.
지침·schema 참조/버전/SHA-256은 함께 반환하지만 이를 실행 감사 DB에 저장하는 연결은 후속 단계다.
본문은 envelope repr에서 제외하며 프로파일 조합 불일치·지침 파일 읽기/해독 실패는 안전한 오류로 반환한다.

독립 리뷰 중요 지적 2건(전체 profile tuple, 파일 오류 비노출)을 RED로 재현해 수정했고 재리뷰 승인을 받았다.
최종 담당 검증: focused 12 passed, generation 152 passed, scoped Ruff·mypy 통과.

## 최종 코드 검증

```powershell
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/unit backend/tests/contract -q
backend/.venv/Scripts/python.exe -m mypy --config-file backend/pyproject.toml backend/src
backend/.venv/Scripts/python.exe -m ruff check backend/src/ai_workshop/labs/rag/generation backend/tests/unit/labs/rag/generation
```

수정 후 결과: **884 passed, 1 warning in 24.87s**, mypy **195 source files** 통과, Ruff 통과.
경고는 기존 FastAPI/Starlette TestClient의 httpx 사용 중단 예정 안내다. 의존성 교체는 이번 범위가 아니며
경고를 숨기거나 완전 무경고 결과로 표시하지 않는다. UI/API/DB 계약은 변경하지 않아 프론트 빌드·migration은 실행하지 않았다.
전체 단계의 최종 독립 리뷰는 별도 게이트다.
최종 리뷰에서 32자 비16진수 UUID가 기존 v1 예외 context에 남는 사례를 추가 발견했다.
새 v2 경계에서 정규화하고 담당 focused36/generation153·정적 검사를 통과했다.
이후 사용자 우선순위 변경으로 scoped 재리뷰와 수정 후 전체 회귀는 대기하며 884건 결과와 구분한다.

## CLI 계약 조사

RAG 담당이 공식 문서와 설치된 0.153.4의 공개 help/package 선언을 대조했다.
모델 요청 인자, JSONL 출력, 일반 JSON Schema 출력 지원은 문서화되어 있다.
하지만 실제 실행 모델 identity 필드와 v2 union schema의 지원 여부는 공개 계약만으로 확정되지 않았다.
이를 미지원으로 단정하거나 요청한 모델을 실제 관측 모델로 복사하지 않는다.

근거: [공식 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode),
[공식 CLI 명령](https://learn.chatgpt.com/docs/developer-commands?surface=cli).
문서 예시는 전체 이벤트 스키마가 아니므로 사용량·모델 증거는 설치 버전의 합성 실행에서 별도 확인한다.

## 순수 계약 연결 확인

오케스트레이터가 합성 fixture로 입력 조립 → v2 파싱 → 기존 CitationValidator 연결을 직접 실행했다.
contextualize 입력의 정확한 key, 생성 입력의 evidence ID/text, 정상 인용 연결,
근거에 없는 수치(합성 근거 7%에 대한 99% 주장)의 인용 실패, 명시적 근거 부족 분기를 모두 확인했다.
이는 모델 생성 없이 직접 만든 응답을 이용한 코드 경계 검증이다. 실제 CLI·DB·검색이나 일반적인 사실성 검증이 아니다.

## 다음 연결 단계

1. 순수 계약과 회귀 검증 완료 후 요청별 실행기·권한/전송 허가·Windows 자식 회수 계약을 구현한다.
2. 공개·합성 입력과 계정 사용량을 고지한 명시적 연결 검사로 지침/schema/모델 identity를 검증한다.
3. 증거가 확보되면 DBA가 runner 설정·Provider 제약을 migration하고 관리자 UI에서 등록·검증을 제공한다.
4. 자산운용의 Hybrid·생성 프로파일·공간/도메인 연결과 평가를 맞춰 실제 질문·인용·후속 질문을 검증한다.

내부 지침과 파서의 테스트 통과는 실제 모델 동작·프롬프트 주입 차단·RAG 전체 준비의 증거가 아니다.
단계별 실패와 미검증 경계를 다음 작업에 인계한다.
