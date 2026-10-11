import { ragFlowPhases } from "./technical";
import { ragArchitectures } from "./architecture";
import type { FlowDefinition } from "../../flowcharts/types";
import { routes } from "../../../shared/routing/routes";

export const multiturnFlow: FlowDefinition = {
  id: "multiturn", categoryId: "rag", categoryLabel: "RAG", title: "멀티턴 문맥 관리",
  summary: "화면에 보이는 대화와 모델에 포함하는 문맥은 다릅니다. 현재 범위·권한·예산으로 문맥을 다시 구성합니다.",
  version: "3", reviewedAt: "2026-10-04", entryNodeId: "scope",
  architecture: ragArchitectures.multiturn,
  phases: ragFlowPhases.multiturn,
  nodes: [
    { id: "scope", label: "현재 범위·segment 확인", kind: "start", input: "현재 연결·공간·폴더·선택 문서", process: "연결 버전, 선택 모드·문서, 활성 원본 버전·READY 색인 build를 범위 identity로 확인합니다. 바뀌면 새 segment로 나눕니다.", output: "이번 질문의 segment", failures: ["과거 메시지가 화면에 남아 있어도 다른 segment를 모델 문맥에 포함하지 않습니다."] },
    { id: "same", label: "같은 segment의 과거 turn 선택", kind: "action", input: "앱 DB의 저장 대화", process: "현재 turn 이전의 같은 segment만 후보로 삼습니다. 브라우저가 제출한 임의 대화 이력을 그대로 신뢰하지 않습니다.", output: "범위가 일치하는 과거 turn", failures: [] },
    { id: "access", label: "현재 권한·의존 근거 재검사", kind: "decision", input: "후보 turn과 원문·선행 turn dependencies", process: "현재 문서 접근 권한과 선행 근거를 재검사합니다. 외부 처리에서는 현재 필요한 전송 승인과 공개·합성 동의 조건도 확인합니다.", output: "접근 가능한 후보", failures: ["권한 철회된 원문이나 가려진 선행 답변에 의존한 결과는 제외합니다."] },
    { id: "eligible", label: "검증된 완료 답변 선별", kind: "action", input: "접근 가능한 후보", process: "completed이면서 answered이고 텍스트·검증 토큰이 있는 turn만 선택합니다. 실패·취소·근거 부족·검증 불가 답변은 포함하지 않습니다.", output: "문맥으로 쓸 수 있는 질의·응답 쌍", failures: [] },
    { id: "budget", label: "최근 문맥·프로파일 예산 적용", kind: "decision", input: "최근 최대 10개 질의·응답 쌍 후보", process: "후보는 최대 20개 메시지입니다. 생성 프로파일의 메시지 수·토큰 예산으로 더 줄일 수 있으므로 항상 10개 쌍을 전송하지 않습니다.", output: "이번 요청에 포함할 문맥 또는 빈 문맥", failures: [] },
    { id: "context", label: "이번 질문 문맥화", kind: "action", input: "새 질문과 예산 안의 문맥", process: "이전 대화의 대상·조건을 반영한 검색 질문을 만듭니다. 앱이 DB에서 문맥을 재구성하며 모델 내부 세션을 resume하는 흐름이 아닙니다.", output: "문맥화한 검색 질문", failures: ["선택 모델 실패 시 다른 모델로 조용히 전환하지 않습니다."] },
    { id: "search", label: "현재 원문 재검색", kind: "action", input: "이번 검색 질문과 현재 허용 문서", process: "문맥 유무와 관계없이 이번 질문의 원문을 다시 검색합니다. 과거 답변은 질문 이해를 위한 문맥이며 새 답변의 원문 근거가 아닙니다.", output: "현재 질문의 선택 근거", failures: ["문서 범위가 달라지면 이전 범위 답변을 근거로 재사용하지 않습니다."] },
    { id: "answer", label: "답변·인용 검증", kind: "decision", input: "현재 근거와 허용된 문맥", process: "선택한 원문으로 답변을 생성하고 인용을 검증합니다. 결과와 어떤 과거 turn에 의존했는지를 저장합니다.", output: "검증된 답변 또는 별도 종료 상태", failures: [] },
    { id: "saved", label: "새 turn 저장", kind: "result", input: "검증·실행 종료 결과", process: "현재 turn과 의존 관계를 저장합니다. 이후 질문에서는 이 답변도 현재 권한·segment·검증 상태를 다시 확인한 뒤 후보가 됩니다.", output: "이어갈 수 있는 대화", failures: [] },
    { id: "failed", label: "근거 부족·실패·취소", kind: "result", input: "답변 불가 또는 실행 오류", process: "종료 이유와 가능한 진단을 기록합니다. answered가 아닌 결과는 다음 질문의 모델 문맥에서 제외합니다.", output: "문맥 재사용에서 제외되는 turn", failures: [] },
  ],
  edges: [
    { from: "scope", to: "same", condition: "현재 범위 확정·필요하면 새 segment" }, { from: "same", to: "access", condition: "저장된 후보 확인" },
    { from: "access", to: "eligible", condition: "허용된 후보만 유지" }, { from: "access", to: "budget", condition: "허용된 이전 대화 없음" },
    { from: "eligible", to: "budget", condition: "완료·answered·토큰 선별" }, { from: "budget", to: "context", condition: "예산 안의 이전 대화 있음" }, { from: "budget", to: "search", condition: "문맥 없음·문맥화 생략" },
    { from: "context", to: "search", condition: "검색 질문 준비" }, { from: "context", to: "failed", condition: "문맥화 실패" },
    { from: "search", to: "answer", condition: "현재 근거 준비" }, { from: "search", to: "failed", condition: "근거 부족·검색 실패" },
    { from: "answer", to: "saved", condition: "답변·인용 검증 통과" }, { from: "answer", to: "failed", condition: "모델·인용 실패·취소" },
  ],
  links: [{ label: "RAG 대화·검색 진단", href: routes.workshopRagSearch, audience: "workspace" }, { label: "실행 모니터링", href: routes.adminRagExecutions, audience: "owner" }],
  sources: [{ title: "이전 대화 선별", reference: "backend/src/ai_workshop/labs/rag/conversations/service.py" }, { title: "문서 범위·현재 권한", reference: "backend/src/ai_workshop/labs/rag/conversations/access.py" }, { title: "문맥 예산·검색 실행", reference: "backend/src/ai_workshop/labs/rag/search/pipeline.py" }],
};
