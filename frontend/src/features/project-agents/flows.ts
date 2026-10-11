import { projectAgentPhases } from "./technical";
import { projectAgentArchitecture } from "./architecture";
import type { FlowDefinition } from "../flowcharts/types";
import { routes } from "../../shared/routing/routes";

export const projectAgentFlows: readonly FlowDefinition[] = [{
  id: "development-agents", categoryId: "common", categoryLabel: "공통", title: "개발 에이전트 관리",
  summary: "개발 작업의 역할 선정·배정·독립 검토·완료 절차입니다. 서비스 AI 에이전트의 실행 관리 화면은 아닙니다.",
  version: "3", reviewedAt: "2026-10-04", entryNodeId: "request",
  architecture: projectAgentArchitecture,
  phases: projectAgentPhases,
  nodes: [
    { id: "request", label: "요청·현재 작업 확인", kind: "start", input: "사용자 요청과 WORKBOARD", process: "목적·성공 기준·기존 설계를 읽고 작업 등급과 위험을 분류합니다.", output: "분류된 작업 범위", failures: ["설계와 코드 충돌을 임의로 결정하지 않습니다."] },
    { id: "select", label: "필수 역할·전문 역할 선정", kind: "action", input: "요구·UI·권한 등 활성화 신호", process: "정본 activation rules에서 최소 필수 역할을 선택합니다. 실제 범위에 필요한 전문 역할만 추가하고 참여·제외 이유를 고지합니다.", output: "근거가 있는 역할 명단", failures: ["모든 작업에 모든 역할을 배정하거나 미래 기술 역할을 만들지 않습니다."] },
    { id: "assign", label: "경계가 분리된 작업 배정", kind: "action", input: "역할·수정 가능 파일·예상 산출물", process: "각 담당자에게 입력·수정 경계·검증·인계 대상을 정합니다. 구현자와 해당 변경의 독립 검증자를 분리합니다.", output: "중복되지 않는 책임과 작업", failures: [] },
    { id: "work", label: "구현·검증 증거 인계", kind: "decision", input: "배정된 작업과 승인 설계", process: "담당자가 산출물·실행한 검증 명령과 결과·남은 위험을 전달합니다. 범위나 권한·운영 조건이 확장되면 배정을 멈추고 역할 명단을 다시 계산합니다.", output: "검토할 산출물 또는 범위 재선정", failures: ["같은 변경의 독립 결과를 구현자가 대신 승인하지 않습니다."] },
    { id: "review", label: "독립 검토", kind: "decision", input: "산출물과 재현 가능한 검증 증거", process: "구현과 분리된 검토자가 명세·회귀·권한·모듈 경계를 확인합니다. 중요한 결함은 수정과 영향 검증으로 돌아갑니다.", output: "통합 가능 여부와 검토 결과", failures: [] },
    { id: "integrate", label: "메인 Codex 통합", kind: "action", input: "검토된 작업 결과", process: "메인 Codex가 증거를 확인하고 충돌을 해결해 통합합니다. staging·commit·push 결정도 메인 Codex만 하며 해당 작업의 승인·권한을 따릅니다.", output: "통합된 변경과 기록", failures: ["관련 없는 변경을 덮어쓰거나 커밋에 포함하지 않습니다."] },
    { id: "done", label: "기록·완료·인계", kind: "result", input: "검증된 통합 결과", process: "WORKBOARD와 정본 문서를 갱신하고 완료와 미완료를 구분해 보고합니다. 정리 정책과 완료 조건을 충족하기 전 환경·자료를 삭제하지 않습니다.", output: "추적 가능한 개발 결과", failures: [] },
    { id: "blocked", label: "차단·확인 필요", kind: "result", input: "권한·설계·검증의 미충족 조건", process: "차단 원인과 필요한 사용자 판단을 기록합니다. 미완료를 성공으로 보고하거나 별도 환경의 성공으로 본래 환경을 대체하지 않습니다.", output: "보존된 진단과 다음 조치", failures: [] },
  ],
  edges: [
    { from: "request", to: "select", condition: "작업 범위 확인" }, { from: "request", to: "blocked", condition: "필수 설계·권한 미확정" },
    { from: "select", to: "assign", condition: "참여·제외 이유 고지" }, { from: "assign", to: "work", condition: "경계·산출물 배정" },
    { from: "work", to: "select", condition: "범위 확장·역할 재선정" }, { from: "work", to: "review", condition: "산출물·검증 증거 준비" }, { from: "work", to: "blocked", condition: "실행·검증 차단" },
    { from: "review", to: "work", condition: "결함 수정·재검증" }, { from: "review", to: "integrate", condition: "중요 결함 해소·통합 가능" },
    { from: "integrate", to: "done", condition: "기록·최종 확인 완료" },
  ],
  links: [{ label: "학습 기록", href: routes.workshopLearning, audience: "workspace" }, { label: "문제 및 개선 이력", href: routes.adminSystemIssues, audience: "owner" }],
  sources: [{ title: "프로젝트 개발 에이전트 정본", reference: "docs/project-agents/README.md" }, { title: "역할 선정·배정·통합 책임", reference: "docs/project-agents/governance/orchestration.md" }],
}];
