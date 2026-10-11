import type { FlowPhase } from "../flowcharts/types";

export const projectAgentPhases = [
  {
    id: "select", title: "작업 분류·역할 선정",
    summary: "개발 요청의 실제 범위에서 필요한 담당 역할을 정합니다.",
    nodeIds: ["request", "select"],
    technical: {
      components: [
        { name: "WORKBOARD·activation signals", role: "현재 작업과 요구·UI·권한·DB 등 변경 신호를 분류하는 기준입니다." },
        { name: "결정적 role selector", role: "활성화 규칙에서 최소 필수 역할을 중복 없이 정렬해 반환합니다." },
      ],
      mechanism: [
        "메인 오케스트레이터가 성공 기준·설계·위험을 읽고 실제 변경 신호를 정합니다. selector는 규칙에 해당하는 필수 역할의 합집합을 계산합니다.",
        "실제 범위가 필요한 전문 역할만 추가하고 참여·제외 이유를 고지합니다. 역할 메타데이터는 역할 문서의 YAML frontmatter를 정본으로 사용합니다.",
      ],
      checks: ["알 수 없는 활성화 신호는 오류로 처리하며 모든 역할을 일괄 호출하지 않습니다.", "이 절차는 저장소 개발 담당의 선정이며 서비스 LLM 에이전트·NPC·백그라운드 worker의 운영을 뜻하지 않습니다."],
      references: [
        { title: "역할 선택 알고리즘", reference: "scripts/project_agents/selection.py" },
        { title: "활성화 규칙", reference: "docs/project-agents/governance/activation-rules.md" },
        { title: "역할 정본 진입점", reference: "docs/project-agents/README.md" },
      ],
    },
  },
  {
    id: "assign", title: "수정 경계 배정·산출물 인계",
    summary: "각 담당자가 바꿀 파일과 전달할 검증 증거를 명확히 합니다.",
    nodeIds: ["assign", "work"],
    technical: {
      components: [
        { name: "역할 계약·독립성", role: "담당 범위·권한·금지 사항과 같은 변경의 구현·검증 책임 분리를 선언합니다." },
        { name: "작업 배정·인계 계약", role: "입력·수정 가능 파일·예상 산출물·검증 명령·다음 담당자를 지정합니다." },
      ],
      mechanism: [
        "하위 담당자에게 겹치지 않는 수정 범위를 배정하고 자신의 변경을 독립 승인하는 역할과 구현 역할을 분리합니다.",
        "담당자는 산출물·실행한 검증과 결과·남은 위험을 인계합니다. 범위·공용 계약·데이터 분류·운영 조건이 바뀌면 새 배정 전에 역할을 다시 계산합니다.",
      ],
      checks: ["역할 계약의 independent_from과 같은 변경 구현 금지 선언을 확인합니다.", "배정된 파일 경계를 넘거나 다른 담당자의 독립 검증 결과를 대신 승인하지 않습니다."],
      references: [
        { title: "역할 계약 스키마", reference: "docs/project-agents/governance/role-contract.md" },
        { title: "배정·재선정 규칙", reference: "docs/project-agents/governance/orchestration.md" },
        { title: "Codex 호출·인계 방식", reference: "docs/guidelines/codex/project-agent-orchestration.md" },
      ],
    },
  },
  {
    id: "review", title: "독립 검토·통합",
    summary: "다른 담당자가 명세와 회귀를 확인한 뒤 메인 Codex가 통합합니다.",
    nodeIds: ["review", "integrate"],
    technical: {
      components: [
        { name: "독립 검증자·코드 리뷰어", role: "구현과 분리된 책임으로 동작·권한·회귀·모듈 경계를 확인합니다." },
        { name: "메인 오케스트레이터", role: "결과 수락·충돌 해결·최종 통합과 staging·commit·push를 결정합니다." },
      ],
      mechanism: [
        "검토자는 산출물과 재현 가능한 검증 증거를 명세에 대조합니다. 중요한 결함은 구현 담당의 수정과 영향 범위 재검증으로 돌려보냅니다.",
        "메인 Codex가 독립 결과를 확인하고 통합합니다. 테스트 통과와 권한·설계 충족 여부를 실제 증거로 판단합니다.",
      ],
      checks: ["독립 검토자는 승인하는 같은 변경을 구현하지 않습니다.", "관련 없는 사용자·도구의 변경을 덮어쓰거나 현재 작업의 커밋에 섞지 않습니다."],
      references: [
        { title: "독립 코드 리뷰 계약", reference: "docs/project-agents/roles/quality/independent-code-reviewer.md" },
        { title: "통합 책임", reference: "docs/project-agents/governance/orchestration.md" },
        { title: "역할 계약 검증기", reference: "scripts/verify_project_agent_contracts.py" },
      ],
    },
  },
  {
    id: "result", title: "완료 기록·차단 인계",
    summary: "완료한 범위와 남은 조건을 기록해 다음 작업이 이어지게 합니다.",
    nodeIds: ["done", "blocked"],
    technical: {
      components: [
        { name: "WORKBOARD·정본 문서·문제 이력", role: "검증된 결과·다음 순서·발견한 결함과 남은 조건을 추적합니다." },
        { name: "worktree·임시 산출물 수명주기", role: "반영·인계·정리 조건을 충족한 정확한 작업 경계만 정리합니다." },
      ],
      mechanism: [
        "메인 Codex가 통합 결과와 실제 실행한 검증을 보고하고 WORKBOARD·필요한 설계·문제 이력을 갱신합니다.",
        "권한·설계·검증 조건이 미충족이면 차단 원인과 다음 조치를 기록합니다. main·원격 반영 이후에도 worktree 인계와 정리 조건을 확인합니다.",
      ],
      checks: ["별도 환경의 성공을 본래 환경 완료로 보고하거나 미완료 조건을 성공으로 숨기지 않습니다.", "정리 정책과 종료 증거를 확인하기 전에 환경·자료·캐시를 삭제하지 않습니다."],
      references: [
        { title: "작업 보드", reference: "WORKBOARD.md" },
        { title: "worktree 종료 조건", reference: "docs/guidelines/codex/worktree-lifecycle.md" },
        { title: "임시 작업 정리", reference: "docs/project-agents/governance/temporary-work-lifecycle.md" },
      ],
    },
  },
] as const satisfies readonly FlowPhase[];
