# 대화 종료 미확인 상태의 화면·전송 계약 정합화

2026-10-21. 사용자가 현재 실행 환경을 유지하고 다음 기능 작업을 진행하도록 요청했다. 12B 성능 비교·GPU 환경 변경은 보류한다. 기존 E2B 품질 미통과와 12B 누적4/4회 소진·응답0 기록은 유지한다.

## 범위와 발견

취소·시간 초과·실패 이후 저장 상태, 재조회, 화면 표시와 다음 질문 수용을 점검했다. 기존 구현에 있는 작은 상태 불일치를 수정하는 중간 위험 작업이다. 메인은 RAG·AI 런타임·백엔드 계약 조사와 프론트엔드 구현·테스트 설계를 맡고, 별도 담당자는 독립 코드 리뷰·합성 경계 검증을 맡았다. DB 구조·배포·모델 설정·검색 품질 변경은 제외했다.

기존 [ADR-0009](../decisions/0009-model-deployments-and-data-policy.md#2026-10-12-로컬-http-schema2종료-상태-보완)는 HTTP timeout·전송 실패만으로 원격 실행 종료를 확인하지 않는다. 서버는 `failed`/`execution_terminated=false`/`provider_termination_unconfirmed` 조합을 저장할 수 있고, 이 경우 다음 질문을 `conversation_busy`로 차단한다.

변경 전 화면은 `running`과 종료 미확인 `cancelled`만 전송을 막았다. 종료 미확인 `failed`에는 일반 재시도 안내와 활성 전송 버튼을 보여주고 상태 새로고침을 제공하지 않았다. 따라서 서버가 허용하지 않는 다음 질문을 화면에서 시도할 수 있었다. 서버의 기존 차단은 유지되어 있었으며, 이번 발견을 실제 중복 모델 호출 증거로 해석하지 않는다.

## 수정

- [상태 판단](../../frontend/src/features/rag/conversation/turn-state.ts)을 별도 모듈로 두고 서버의 기존 조건에 맞췄다. `running` 또는 종료 미확인 상태의 `cancelled`/명시적 provider 종료 미확인 오류일 때 차단한다. 과거 `failed`/`interrupted`의 false 값을 일괄 차단하지 않는다.
- [대화 화면](../../frontend/src/features/rag/conversation/ConversationPage.tsx)의 새 질문 버튼, 제출 함수와 남아 있는 같은 질문 재시도 버튼에 같은 조건을 적용했다.
- 종료 미확인 `failed`/`interrupted`에는 종료 확인 전 전송할 수 없다는 안내와 상태 새로고침을 제공한다. 이미 입력한 다음 질문은 보존한다.
- 새로고침이 서버에서 종료 확인 상태를 반환한 경우에만 전송을 허용한다. UI가 종료 플래그를 고치거나 기존 요청을 재실행하지 않는다. 실제 과거 미종료 작업의 복구 API를 추가한 변경이 아니다.

## 검증

[신규 회귀](../../frontend/src/features/rag/conversation/ConversationTermination.test.tsx)는 합성 fetch 응답과 실제 React 화면·API 클라이언트를 사용한다. 변경 전7개 중3개가 실패했다: 종료 미확인 failed/interrupted의 전송 버튼 활성2건, 새로고침 뒤 남은 재시도 동작의 추가 POST1건이다. 기존 정상 종료·과거 실패/중단의 허용 의미4건은 통과했다. 재시도 버튼의 disabled 표시를 추가할 때도 변경 전1실패를 확인했다.

종료 미확인 상태를 반복 조회해도 입력이 보존되고 전송되지 않는지, 서버의 종료 확인 뒤 최신 revision·새 request ID로 다음 질문을 제출하는지 확인한다. 초기 검증 중 테스트가 임시 질문 DOM에서 저장 질문 DOM으로 바뀌는 순간을 잡는 경합은 `act`로 정리했고, 테스트 데이터의 status literal 타입 오류2건도 수정했다.

최종 검증 결과는 다음과 같다.

- `pnpm exec vitest run src/features/rag/conversation src/features/rag/executions`: 19파일155개 통과. [최종 결과](../../.local-data/project-agent-work/rag-terminal-flow-20261021/frontend-tests.json).
- `pnpm exec tsc --noEmit --pretty false --incremental false`: 통과.
- 변경된 프론트엔드3파일 `pnpm exec eslint ... --max-warnings 0`: 통과.
- 독립 검증: 최종 신규 UI7/7, 기존 백엔드 `test_domain.py`9/9 통과. 동기 백엔드 검사에서 plugin autoload를 끈 영향으로 `asyncio_mode` 설정 경고1개가 있었고 실패는0이다. [최종 검토](../../.local-data/project-agent-work/rag-terminal-flow-20261021/independent/final-review.md), [검증·소스 SHA](../../.local-data/project-agent-work/rag-terminal-flow-20261021/independent/final-review.json).

이번 검사는 실제 로그인 브라우저→API→DB→모델 E2E나 실모델 종료 수용을 대신하지 않는다. CSS·공개 API·서버 업무 규칙은 변경하지 않았다.

## 별도 발견 — 15분 실행 기한 만료의 경합

독립 검토에서 현재 실행 중인 turn의15분 lease가 만료되면 `recover`가 먼저 `interrupted`로 바꾸고, 기존 executor 정리가 끝나기 전에 새 request ID의 실행을 허용할 수 있는 경계를 재현했다. 합성 메모리 저장소의 시각만16분 전으로 바꾸고 실제 ConversationService를 사용했으며, 원래 작업의 join 전에 두 번째 mock executor가 시작됐다. [독립 계약 검토](../../.local-data/project-agent-work/rag-terminal-flow-20261021/independent/backend-contract-review.md), [합성 재현](../../.local-data/project-agent-work/rag-terminal-flow-20261021/independent/expired-running-probe.json).

이는 현행 실모델에서 관측한 사건이나 과거 interrupted 작업이 실제 실행 중이라는 증거가 아니다. 다음 백엔드 수정 후보로 남긴다. 과거 failed/interrupted의 계약을 일괄 변경하지 않고, 새로 만료 처리하는 활성 요청의 종료 확인과 다음 요청 예약 사이를 다뤄야 한다. 이번 프론트엔드 수정은 이 별도 경합을 해결하지 않는다.

## 보존과 남은 범위

모델·임베딩·업무 HTTP·DB 호출, 설치·다운로드, 서버/worker 기동, 프로필 승격·도메인 활성화는 수행하지 않았다. 기존 사용자 파일과 다른 미커밋 변경을 보존하며 커밋·푸시는 하지 않는다. 운영 문제 이력 DB의 신규 등록·연결은 미완료다. 이번 파일을 발견·수정·검증 근거로 보존하며 임의 문제 번호나 DB 반영 완료를 만들지 않는다.

실제 terminal 저장·권한 경합·브라우저 수용, 과거 종료 미확인 복구, 첨부/별칭 복구는 여전히 별도 기능 마감 항목이다. 모델 품질 개선 완료를 다음 학습의 무기한 선행 조건으로 삼지 않으며 Agents SDK 호환성 조사·설계는 이 기능 마감과 병행 가능한 준비 범위다.

## 최근 완료 목록에서 이동한 기록

평가 준비 모드·UI 기준(2026-10-19): 모드별 입력 보존, 공통 토큰/ChoiceGroup, 연결형 버튼과 관련156·독립13검사 통과. [모드](2026-10-19-rag-evaluation-preparation-modes.md), [스타일](2026-10-19-ui-style-foundation.md), [버튼](2026-10-19-preparation-segmented-control.md). 해당 구현·당시 검증의 역사 기록이며 이번에 재실행한 결과가 아니다.
