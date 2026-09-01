# Codex 프로젝트 개발 에이전트 호출과 인계

이 문서는 Codex의 역할 호출과 인계 방식만 정한다. 역할 정의, 선택 규칙과 오케스트레이션 권한의 정본은 [프로젝트 개발 에이전트 정본](../../project-agents/README.md), [활성화 규칙](../../project-agents/governance/activation-rules.md), [오케스트레이션](../../project-agents/governance/orchestration.md)을 따른다.

## 메인 Codex의 순서

1. `WORKBOARD.md`와 작업 범위 문서를 읽고 작업 등급과 위험을 분류한다.
2. 활성화 신호를 정하고 `scripts/verify_project_agent_contracts.py select --root PATH --signal SIGNAL`로 최소 필수 역할을 확인한다. 이 출력은 결정론적인 필수 역할 기준선이며, 알 수 없는 신호는 사용 오류로 즉시 보고한다.
3. 실제 범위에 필요한 역할만 더해 역할 파일을 읽고, 사용자에게 작업 등급·위험·참여 역할과 이유·의미 있는 제외 역할과 이유를 먼저 고지한다.
4. 구체적이고 경계가 겹치지 않는 수정 범위에 한해 하위 에이전트를 호출한다. 구현 담당과 독립 검증 또는 독립 코드 리뷰 담당은 같은 책임으로 배정하지 않는다.
5. 인계에는 입력, 수정 범위, 산출물, 실행한 검증 명령과 결과, 남은 위험을 포함한다. 메인 Codex는 그 증거를 확인하고 통합한다.
6. 범위, 공용 계약, 데이터 분류 또는 운영 조건이 확장되면 배정을 멈추고 신호와 역할 명단을 다시 계산해 사용자에게 알린다.
7. 임시 작업 기록은 `.local-data/project-agent-work/<task-id>/`에만 두고, 검증 게이트를 통과한 성공 기록만 정리한다. 실패 또는 차단 기록의 최소 진단 정보는 보존한다.
8. 메인 Codex만 최종 통합, `WORKBOARD.md` 마감, staging, commit과 push를 결정한다.

## 호출 경계

하위 에이전트는 자신의 승인된 파일·검증 범위를 넘는 통합, 다른 역할의 독립 결과 대체, `WORKBOARD.md` 최종화, staging, commit 또는 push를 수행하지 않는다. 역할 카탈로그와 세부 책임은 이 문서에 복제하지 않는다.
