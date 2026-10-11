# ADR-0032: 증거 기반 RAG 별칭 요청 복구

- 상태: 사용자 다음 기능 진행 승인에 따른 구현 결정, 2026-09-30
- 문제: ISSUE-00013
- 계약: [상세 설계](../superpowers/specs/2026-09-30-rag-alias-recovery-design.md)

기존 fail-closed 별칭 예약은 전송 여부가 불확실하면 영구 차단될 수 있다. 현재 alias 일치·시간·task
없음을 종료로 취급하면 늦은 writer가 이후 alias를 다시 바꿀 수 있다. 강제 원장 삭제/해제는 채택하지 않는다.

cluster admission gate와 reserved/dispatching/legacy_unknown 단계, 불변 복구 receipt를 도입한다.
전송 전 CAS 종료는 not_dispatched, causal client/server drain은 recovered_terminated로 기록한다.
confirmed는 기존 invocation의 정상 확인 의미를 보존한다. closure와 receipt는 원자적이다.

첫 운영 진입은 활성 owner를 확인하는 내부 local CLI다. 신뢰하는 운영자가 통제하는 Windows의
직접 loopback·기존 single-node Docker ES만 지원하며, 미확인 sender/remote/proxy/multi-node는
실제 collector가 마련될 때까지 차단한다. 종료 증거 수집은 OS/Docker/ES 어댑터 책임이다.

2026-10-01 후속 결정: [사전검사 계약](../superpowers/specs/2026-10-01-rag-alias-preflight-design.md)에
따라 읽기 전용 `preflight`와 새 legacy/dispatching freeze 전 지원 검사를 추가한다. 같은 HOST
관찰에서만 잠근 실행 파일의 서명·해시를 공유하고 허용 범위는 유지한다. `ready`는 관찰 결과이며
종료 proof가 아니다. 실제 종료·receipt·release·새 parity는 별도 검증한다. 취소, endpoint 폐기와
ES 인증 전환은 이번 계약에 포함하지 않는다.

기존 요청의 target은 재전송하지 않는다. 정상 profile parity는 현재 DB truth로 새 operation을
만들며 회복 결과와 수렴 결과를 분리한다. 원문·색인·계정·활성 구성·큐는 보존하고 삭제/품질 기능은 확장하지 않는다.
