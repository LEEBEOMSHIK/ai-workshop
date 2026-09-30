# RAG 선택형 거절 지침 v5 구현·오프라인 검증 — 2026-09-30

## 최초 완료분의 공개 main 반영

사용자가 기존 변경까지 조사해 올리도록 승인한 범위를 두 일반 커밋으로 반영했다.

- [9b8e2c25b38972f4539b96a07528290bad3d2eac](https://github.com/LEEBEOMSHIK/ai-workshop/commit/9b8e2c25b38972f4539b96a07528290bad3d2eac): 정확한 Codex CLI 0.158.0 호환, 생성형 평가 재시도 JSON 계약, 관련 회귀·기록 6개 파일.
- [2ea1396a8dfb4f717650d2c6a64a52f9cba75947](https://github.com/LEEBEOMSHIK/ai-workshop/commit/2ea1396a8dfb4f717650d2c6a64a52f9cba75947): 비교·모니터링 UI, 요청 내 평가 run 조회 묶음, 인용 실패 진단·실패 단계 및 실패 이전 측정값 보존, 관련 회귀·기록 25개 파일.
- 기존 origin `https://github.com/LEEBEOMSHIK/ai-workshop.git`의 main에 일반 push가 성공했다. 직후 `ls-remote` main은 전체 SHA `2ea1396a8dfb4f717650d2c6a64a52f9cba75947`과 일치했고 추적 브랜치 차이는 0/0이었다.
- 총 31개 파일을 명시적으로 검토·선택했다. 미사용 참고 캡처 `references/images/img.png`는 포함하지 않고 그대로 보존했다. 비밀값·DB 자료·캐시·로컬 테스트 산출물은 추가하지 않았다. 신규 작업 기록의 로컬 사용자 경로는 비식별화했다.
- 직전 검증: 관련 백엔드 131 passed in 4.73s, 변경 Python Ruff·Mypy 6개, 전체 TypeScript·변경 TS/TSX ESLint 및 독립 코드·개인정보 검토 통과. 같은 제품 코드의 앞선 전체 단위 2977 passed / 6 skipped, 프론트 112 passed 기록은 [통합 기록](2026-09-30-rag-main-integration.md)에 있다.
- GitHub CLI의 HTTP401과 별개로 기존 Git 인증으로 push가 성공했다. 인증 설정은 변경하지 않았다. GitHub 기본 브랜치는 변경하지 않았다. force push·보호 해제·배포는 수행하지 않았다.

아래 v5는 최초 푸시 이후의 별도 구현분이다. 구현 완료 시점에는 미커밋이었으며, 후속 사용자 요청으로 기존 공개 origin/main에 일반 커밋·푸시하도록 승인됐다. 이 기록의 main 반영 검증 절은 커밋 직전에 작성한 사전 검증 결과이며 실제 commit SHA·원격 반영·CI 결과는 push 후 최종 보고로 확인한다.

## 문제와 이번 작업의 경계

[실제 평가 기록](2026-09-30-rag-evaluation-followup.md)에서 두 음성 시도는 안전하게 거절했지만 `answered`로 기록됐다. 기존 parser/runtime에는 이미 `insufficient_evidence` + 빈 `claims` 상태 계약이 있다. 거절 문장 자체를 답변 claim으로 만들지 않도록 명시하는 선택형 지침을 추가한다. 이 변경은 실제 모델 행동의 원인을 확정하거나 실제 품질 개선을 증명한 것이 아니다.

범위는 기존 Codex v4 문맥·인용 지침을 보존하는 새 v5 자산과 해당 자산의 등록·예산·검증 서명·실행 경로다. 문장 키워드로 상태를 덮어쓰는 휴리스틱, 새 의미 분류기, 출력 schema/status 변경, 기존 프로파일 변경은 없다. 기본 활성 구성의 승격과 ISSUE-00005 종결은 하지 않는다.

## 구현

- `generation/prompts/codex-answer-v5.txt`: 기존 v4 전체 지침을 유지한다. 원문이 있어도 질문의 실제 대상·속성·조건·예외를 확인할 수 있어야 답하며, 자료 없음·판단 불가·거절 설명을 `answered`의 사실 claim으로 만들거나 무관한 근거로 인용하지 않도록 명시한다. 답할 근거가 부족하면 `status=insufficient_evidence`, `claims=[]`를 요청한다. 실제 사실 답변을 불필요하게 거절하지 않도록 함께 명시한다.
- `generation/prompts.py`: `rag-codex-answer-v5`와 task version 5를 별도 등록한다. v3/v4 자산은 바이트 단위로 불변임을 직접·독립 확인했다.
- `generation/codex_prompt.py`, `generation/codex_execution.py`, `generation/codex_verification.py`: v5를 신뢰 선택 목록에 추가하고 v4처럼 명시적 evidence budget을 필수로 요구한다. 기존 grouped evidence payload, wire schema v1/response schema v2, control/context 프롬프트는 동일하다. 답변 prompt hash와 version은 v4와 구별되어 기존 연결 검증 서명을 재사용하지 않는다.
- `models/context_evidence.py`: v5 설정에 context budget을 허용하고 없거나 잘못된 예산은 거부한다. 모델·runner·권한·외부 전송 승인·동시 실행·정리 검증 경계는 기존 그대로다.
- `generation/codex_admin_api.py`: 서버 소유 프롬프트 목록의 세 번째 선택지로 v5를 노출한다. 첫 번째 v3 기본 선택은 유지하며 v5에는 기존 v4와 같은 version 1 / groups 8 / units 32 / characters 12000 예산을 제공한다.
- `tests/unit/labs/rag/generation/test_codex_abstention_prompt.py`: 신규 17개 회귀로 자산 버전, untrusted 본문의 지침 분리, 기존 payload/schema 보존, budget 경계, 검증 서명, runtime의 typed 거절·잘못된 상태/claim 거부, 거절 단어가 있는 실제 사실의 비오인, 관리자 조회의 무실행을 검증한다.
- `frontend/src/features/rag/models/CodexSetup.test.tsx`: 신규 2개 회귀로 초기 v3 선택 유지와 명시적 세 번째 v5 선택의 정확한 프로파일 등록·budget 전달을 검증한다. 프론트 제품 코드는 변경하지 않았다.

## 실제 검증 결과

| 검사 | 결과 |
| --- | --- |
| 구현 전 신규 backend 회귀 RED | 11 failed, 6 passed, 1 warning in 5.20s. 미등록 v5·미지원 경로가 원인 |
| 구현 후 신규 backend 회귀 | 17 passed, 1 warning in 8.09s |
| 전체 backend 단위 | 2994 passed, 6 skipped, 1 warning in 100.59s |
| 프론트 모델 설정·탭·구성 스튜디오 | 3 files, 47 passed in 56.29s. 새 UI 회귀 2개 포함 |
| Python lint | 변경 6개 소스와 신규 test에 Ruff 통과 |
| Python 타입 | Mypy: Success, no issues found in 6 source files |
| 프론트 정적 검사 | 전체 TypeScript 및 변경 CodexSetup.test.tsx ESLint 통과 |
| 독립 리뷰 | 차단/중요 결함 없음. 기존 v3/v4 바이트 불변, v5 opt-in·예산·서명·기존 schema 경계와 UI 회귀 확인 |
| 독립 회귀 | 7 files, 176 passed, 1 warning in 27.89s, exit 0 |

실행 명령은 backend `python -m pytest tests/unit -q --tb=short --basetemp <verification-workspace>/avu1`, 신규 회귀는 해당 파일 한정으로 실행했다. 프론트는 `vitest run`의 CodexSetup·ModelLabPage.tabs·ConfigurationStudioPage 세 파일과 `--maxWorkers=1`을 사용했다. synthetic secret, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`로 외부 LLM·네트워크 없이 테스트했다. 서버·DB·사용자 계정을 새로 만들지 않았다.

캐시 쓰기 제한으로 첫 Ruff 호출은 실행되지 않아 `--no-cache`로 재실행해 통과했다. pytest 임시 경로는 새롭고 짧은 검증 작업공간 경로를 사용했으며 기존 임시 디렉터리를 삭제하거나 권한을 바꾸지 않았다. 기존 TestClient deprecation 경고 1건과 skip 6건은 통과 수에 넣지 않았다. 로컬 전체 단위·화면 로그는 검증 작업공간에 보존하고 저장소에는 추가하지 않는다.

## main 반영 사전 재검증

- 사용자 변경 후 GitHub REST API로 기본 브랜치 `main`, 공개 저장소 `LEEBEOMSHIK/ai-workshop`, 원격 main SHA `2ea1396a8dfb4f717650d2c6a64a52f9cba75947`를 확인했다. 기본 브랜치·보호·공개 범위를 다시 변경하지 않는다.
- 로컬 main과 origin/main 추적 관계, 승인된 origin fetch/push URL, 기존 HEAD와 빈 staging을 확인했다. 기존 완료분을 다시 커밋하지 않는다.
- 이전 검증 이후 v5 제품 코드·회귀는 변경되지 않았다. 신규 프롬프트와 테스트도 최종 검토했다. WORKBOARD에 추가된 기본 브랜치 작업 기록과 별도 문서는 다른 작업이므로 로컬에 보존하고 이번 v5 커밋에 섞지 않는다. 참고 이미지도 보존·제외한다.
- 커밋 직전 전체 backend 단위: 2994 passed, 6 skipped, 1 warning in 100.48s. synthetic secret/offline flags, 새롭고 짧은 `<verification-workspace>/vc1` 임시 경로로 실행했다.
- 커밋 직전 관리자 설정 UI 회귀: 1 file, 18 passed in 6.77s. CodexSetup.test.tsx, 단일 worker로 실행했다.
- 변경 Python 6개 소스·신규 테스트 Ruff를 다시 확인했다. Mypy 6개·전체 TypeScript·변경 UI 테스트 ESLint와 독립 리뷰/176개 회귀는 위 동일 코드의 검증 결과다.
- 최종 선택된 11개 파일과 기존 v3/v4 바이트 불변, 로컬 사용자 경로·비밀값 비노출, 문서 링크·diff 검사를 확인하고 일반 push한다. force push·배포·새 모델 호출·새 인증은 수행하지 않는다. 실제 모델 품질과 본래 환경 적용을 완료로 처리하지 않는다.

## 미검증과 다음 작업

- 실제 v5 프로파일/저장 구성을 본래 DB에 등록하지 않았으며 API/worker 재시작·실제 브라우저·ISSUE-00005 문서 DB 연결은 수행하지 않았다. 기존 활성 구성과 실제 모델 설정은 유지했다.
- 새 v5를 선택한 불변 생성 프로파일·후보 저장 구성을 정상 관리자 흐름으로 만들고 새 prompt hash에 대해 기존 승인·연결 검증 절차를 통과해야 실제로 사용할 수 있다. 서버 옵션 노출이나 로컬 테스트 통과만으로 준비/승인 완료가 되지 않는다.
- 실제 거절 사례와 양성 사례를 함께 반복 평가해 상태 계약·불필요 거절·인용·지연을 비교해야 한다. 이번에는 외부 LLM 호출·추가 결제·새 인증을 실행하지 않았으므로 실제 품질 개선은 미확인이다.
- 필수 비교 결론 누락(Q09 주의 상태), 본래 환경에 앞선 진단/측정값 보존 적용, 과거 실패 backfill·근거 선택 완료 전 측정값 복원, 새 문서 일반화·지연이 남았다.
- 이 작업을 실행한 조수의 실제 LLM 모델 식별자는 제공된 런타임 메타데이터로 확정할 수 없어 확인 불가다. 프로젝트 RAG 모델과 저장 기본 설정을 실행 모델로 추정하지 않았다.
