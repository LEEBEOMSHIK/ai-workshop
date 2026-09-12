# Codex 호출별 실행 승인 검사

## 범위

사용자가 승인한 다음 단계인 호출 승인 검사와 거절 테스트를 구현한다.
정본: `docs/superpowers/plans/2026-09-08-codex-call-authorization.md`.
기존 HTTP 정책과 Codex 등록/runtime/readiness 차단은 변경하지 않는다.
실제 CLI·인증·계정 사용량·사용자 DB·문서·UI 변경은 없다.

## 승인 경계

한 번의 실행은 actor/request/operation/stage와 정확한 구성·모델·지침·정책·입력 revision에 결합한다.
실제 전송 bytes의 digest는 검사기가 계산한다. 클라이언트가 제출한 digest나 approved boolean을
검증된 서버 승인으로 간주하지 않는다. 질문·이력·메타데이터와 신뢰 지침을 모두 포함해야 한다.

승인 저장소 source는 서버 내부 port다. 최신 상태를 잠금 context 안에서 읽고,
승인 소비와 실행을 같은 context 안에서 수행한다. 소비 기록은 실행 실패/취소로 되돌아가지 않아야 한다.
특히 후속 DB adapter에서 실행 오류 시 일반 transaction rollback으로 소비가 취소되면 안 된다.
여러 프로세스의 원자적 단회 소비·현재 actor/권한/정책/승인 철회와의 직렬화는 실제 adapter의 필수 계약이다.
이번 in-memory test source 통과는 실제 DB 잠금/장애 복구 증명이 아니다.

## 구현 상태와 검증

- `generation/codex_authorization.py`: 불변 호출/승인 snapshot, 실제 bytes digest,
  현재 사용자·정책·공간·revision·동의·유효기간 검사와 단회 소비 후 실행 gate.
- `tests/unit/labs/rag/generation/test_codex_authorization.py`: 신규 행동 검사 56개.
  존재 확인용 초기 RED 테스트는 최종 행동 테스트로 교체했다.
- 후속 질문 contextualize는 검색 전에 실행되므로 빈 evidence를 허용하지만 payload 승인은 유지한다.
- 원시 오류를 `raise ... from None`만으로 가리지 않고 예외 handler 밖에서 안전 코드로 변환한다.
  오류의 `__cause__`/`__context__`에 원시 source/operation 오류가 남지 않는지 검사했다.
- 수정 후 메인 전체 unit/contract: 1,196 passed, 기존 Starlette/httpx 경고 1개, 44.05초.
  runbook에 따라 합성 테스트 secret만 해당 테스트 프로세스에 지정했다.
  신규 파일 Ruff 통과. 독립 재검토에서 설계 준수·코드 품질 승인.
  수정 후 mypy도 215개 소스 파일 통과. API/프론트 계약 변경은 없다.

독립 리뷰 보완 항목:

1. consume을 기다리는 동안 만료될 수 있으므로, 소비 완료 후 실제 callback 직전 유효기간 재검사.
2. source가 CodexAuthorizationError로 이미 감싼 오류도 원시 cause/context를 보존하지 않도록 재구성.

두 항목은 신규 실패 테스트 4개로 재현 후 수정했고, 56개 targeted 검사와 위 전체 회귀를 통과했다.
독립 재검토에서도 두 지적 해결 및 수정으로 생긴 새 차단 문제 없음을 확인했다.

## 남은 연결 조건

- 실제 서버 승인 기록과 잠금/소비 adapter를 구현하고 rollback·동시성·취소를 격리 DB에서 검증한다.
- 검색 contextualize/generate, 평가 worker, 명시 합성 연결 검사에 같은 최종 실행 경계를 배선한다.
- registry·실시간 이벤트 감시·정확한 모델 확인을 연결하기 전에는 Codex 준비 상태를 승격하지 않는다.
- 승인자는 현재 actor와 일치해야 한다. 운영/일반 사용자/비공개 자료를 허용하는 확장 작업이 아니다.
