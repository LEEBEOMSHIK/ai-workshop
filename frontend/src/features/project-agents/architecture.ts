import type { FlowArchitecture } from "../flowcharts/types";

export const projectAgentArchitecture = {
  summary: "역할 선정은 Python 규칙 계산이고, 실제 담당 호출·파일 배정·결과 통합은 메인 Codex의 도구 오케스트레이션입니다. 역할 계약은 저장소 문서에, 산출물은 배정한 파일에, 검증 증거는 인계와 작업 기록에 남습니다.",
  technologies: [
    { name: "Markdown·YAML frontmatter", purpose: "역할의 책임·권한·독립성 계약을 정의합니다.", implementation: "역할 문서의 frontmatter가 메타데이터 정본입니다. 활성화 규칙 문서는 작업 신호와 최소 필수 역할의 관계를 담습니다." },
    { name: "Python·PyYAML 계약 로더", purpose: "역할 문서와 규칙을 읽고 형식·참조를 검사합니다.", implementation: "scripts/project_agents/contracts.py가 YAML을 타입 있는 계약으로 읽습니다. 검증기는 중복 역할 ID·독립성 참조·필수 절·규칙 참조를 검사합니다." },
    { name: "결정적 Python 역할 selector", purpose: "입력한 작업 신호에 필요한 역할을 계산합니다.", implementation: "select_required_roles가 일치 규칙의 역할을 합쳐 중복을 없애고 정렬합니다. 알 수 없는 신호는 오류이며 LLM으로 역할 목록을 추측하지 않습니다." },
    { name: "Codex 하위 에이전트 도구", purpose: "메인 담당자가 구체적인 작업을 분리해 배정하고 결과를 받습니다.", implementation: "메인 Codex가 승인된 수정 파일·검증 범위·산출물·인계 대상을 정해 호출합니다. 역할 문서 자체가 실행 프로세스나 자동 배정 서비스를 띄우는 것은 아닙니다." },
    { name: "저장소 검증 명령·Git·WORKBOARD", purpose: "검토할 증거를 남기고 통합 결과를 추적합니다.", implementation: "담당자가 실제 검증 결과를 인계하면 독립 검토자가 확인합니다. 메인 Codex가 최종 통합·기록·staging·commit·push를 결정합니다." },
  ],
  steps: [
    { title: "요청·작업 신호 입력", technology: "메인 Codex·WORKBOARD", explanation: "사용자 요청과 설계·현재 작업을 읽고 성공 기준·위험·UI·권한 등 실제 변경 신호를 정합니다. 이 분류가 selector의 입력입니다." },
    { title: "필수 역할 계산", technology: "YAML 규칙 → Python selector", explanation: "계약 로더가 규칙을 읽고 selector가 정렬된 최소 역할 목록을 반환합니다. 메인 담당자가 필요한 전문 역할을 더하고 참여·제외 이유를 고지합니다." },
    { title: "경계가 다른 작업 배정", technology: "Codex 하위 에이전트 도구", explanation: "담당별 입력·수정 가능 파일·산출물·검증 명령·다음 인계 대상을 전달합니다. 구현과 해당 변경의 독립 검증·리뷰는 다른 책임으로 배정합니다." },
    { title: "산출물·증거 검토", technology: "담당 파일·검증 명령·독립 리뷰", explanation: "담당자가 파일 변경과 실행한 검사 결과·남은 위험을 반환합니다. 독립 검토가 결함을 찾으면 수정·재검증으로 돌아갑니다. 범위 확장은 역할 재선정으로 돌아갑니다." },
    { title: "통합·기록·인계", technology: "메인 Codex·Git·WORKBOARD", explanation: "메인 담당자가 검토 증거를 확인해 변경을 통합하고 기록을 갱신합니다. 완료와 차단 조건을 구분해 사용자에게 반환하며 반영·인계·정리 조건을 확인합니다." },
  ],
  example: {
    question: "가상 개발 요청 ‘검색 결과 화면에 근거 필터를 추가해 줘.’",
    explanation: "설명용 가상 예시입니다. 메인 담당자는 요구·React UI·기능 구현 신호로 필수 역할을 계산하고 실제 검색 동작이 바뀌는지 확인해 전문 역할을 더합니다. 구현자에게 화면 파일, 독립 검토자에게 검증 책임을 분리해 배정하고 결과·검사 증거를 받아 통합합니다. selector가 코드를 작성하거나 서비스 AI 에이전트를 배포하는 예시는 아닙니다.",
  },
  boundaries: [
    "개발 역할·서비스 LLM 에이전트·안내 NPC·Celery worker는 다른 개념입니다. 이 흐름은 저장소 개발과 검토 책임을 설명합니다.",
    "역할 선택 결과는 최소 기준선이며 실제 배정은 메인 오케스트레이터가 범위와 권한에 맞춰 결정합니다. 변경 범위가 확장되면 새 배정 전에 다시 계산합니다.",
    "하위 담당자는 배정 파일 경계를 넘거나 자신의 변경을 독립 승인하지 않습니다. 최종 통합과 저장소 반영 결정은 메인 Codex에 있습니다.",
  ],
  references: [
    { title: "활성화 규칙", reference: "docs/project-agents/governance/activation-rules.md" },
    { title: "계약 로더·검증", reference: "scripts/project_agents/contracts.py" },
    { title: "결정적 역할 selector", reference: "scripts/project_agents/selection.py" },
    { title: "계약 검증 명령", reference: "scripts/verify_project_agent_contracts.py" },
    { title: "역할 계약", reference: "docs/project-agents/governance/role-contract.md" },
    { title: "Codex 호출·인계", reference: "docs/guidelines/codex/project-agent-orchestration.md" },
  ],
} as const satisfies FlowArchitecture;
