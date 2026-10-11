import { ragFlowPhases } from "./technical";
import { ragArchitectures } from "./architecture";
import type { FlowDefinition } from "../../flowcharts/types";
import { routes } from "../../../shared/routing/routes";

export const sessionsFlow: FlowDefinition = {
  id: "sessions", categoryId: "rag", categoryLabel: "RAG", title: "대화 세션 관리",
  summary: "대화 메뉴를 열 때는 세션을 만들지 않습니다. 첫 질문 접수와 기존 대화 복원을 구분합니다.",
  version: "3", reviewedAt: "2026-10-04", entryNodeId: "open",
  architecture: ragArchitectures.sessions,
  phases: ragFlowPhases.sessions,
  nodes: [
    { id: "open", label: "새 대화 또는 기존 세션 선택", kind: "start", input: "사용자의 대화 화면 진입", process: "새 대화는 질문 전 상태로 열고, 기존 세션을 선택하면 저장된 대화 조회로 이동합니다. 메뉴 클릭만으로 DB 세션을 만들지 않습니다.", output: "미접수 새 대화 또는 조회할 기존 대화", failures: [] },
    { id: "draft", label: "질문 전 첨부 초안", kind: "action", input: "선택한 문서 또는 PC 첨부", process: "선택 문서는 검색 범위를 정합니다. 질문 전 PC 첨부는 owner·domain이 있는 별도 초안으로 관리하며 빈 대화를 선행 생성하지 않습니다.", output: "질문과 결합할 첨부 초안", failures: ["첨부 저장됨과 현재 답변에 사용 가능은 다른 상태입니다."] },
    { id: "preflight", label: "첫 질문 사전검사", kind: "decision", input: "질문·현재 범위·초안·요청 ID", process: "질문과 연결·권한·필요한 승인을 검증합니다. 동일 요청 ID와 digest의 재전송은 멱등하게 처리합니다.", output: "접수 가능 여부", failures: ["접수 전 거절은 새 세션을 만들지 않습니다."] },
    { id: "title", label: "질문 의도 기반 제목 산출", kind: "action", input: "첫 질문", process: "결정적 로컬 규칙으로 첫 질문의 대상·의도·조건을 보존한 제목을 산출합니다. 별도 LLM 호출은 없고 기존 수동 제목은 후속 질문이 덮어쓰지 않습니다.", output: "한 번 산출한 세션 제목", failures: ["불명확한 긴 질문은 fallback으로 구분합니다."] },
    { id: "accept", label: "세션·첫 질문·첨부 원자 저장", kind: "action", input: "제목·첫 turn·첨부 초안", process: "세션, 제목, 첫 turn, 접수 멱등 기록과 첨부 결합을 같은 트랜잭션으로 저장합니다. 중간 실패로 빈 대화가 남는 접수 경로를 사용하지 않습니다.", output: "첫 질문이 있는 저장 세션", failures: ["접수 이후 모델 오류가 나면 실패 turn을 가진 세션은 유지됩니다."] },
    { id: "restore", label: "현재 권한 확인·대화 복원", kind: "action", input: "기존 세션과 현재 사용자 권한", process: "소유자·도메인·삭제 여부와 현재 근거 접근 권한을 서버에서 확인합니다. 허용된 대화와 문서 범위만 복원하며 비허용 질문·답변·제목·실행 참조는 가립니다.", output: "복원된 대화와 선택 범위", failures: ["삭제된 세션이나 다른 소유자의 세션은 열 수 없습니다."] },
    { id: "followup", label: "후속 질문·revision 확인", kind: "decision", input: "기존 대화 revision과 새 질문", process: "현재 revision과 같은 요청의 재전송 여부를 확인합니다. 한 세션의 동시 실행을 제한하며 취소 뒤 실제 실행이 종료되지 않은 동안 새 실행을 막습니다.", output: "후속 turn 접수 또는 충돌", failures: ["오래된 revision·동시 요청 충돌을 숨기지 않습니다."] },
    { id: "execute", label: "질문 실행·상태 저장", kind: "decision", input: "접수한 첫 turn 또는 후속 turn", process: "공통 검색·생성 코어를 실행하고 완료·실패·취소 상태를 저장합니다. 취소 이후 늦은 결과가 취소 상태를 덮어쓰지 않습니다.", output: "종료 상태와 실행 종료 기록", failures: ["취소·lease 만료의 interrupted 상태는 실제 실행 종료 증거와 다릅니다."] },
    { id: "saved", label: "대화 저장·다시 이어가기", kind: "result", input: "종료된 turn이 있는 세션", process: "목록에서 다시 열어 대화를 이어갑니다. 수동 제목과 과거 결과를 보존하되 다시 조회할 때 현재 권한을 재검사합니다.", output: "복원 가능한 대화 세션", failures: [] },
    { id: "rejected", label: "미접수·충돌 안내", kind: "result", input: "사전검사 거절 또는 후속 충돌", process: "첫 질문 미접수는 새 세션을 만들지 않고 입력·초안을 유지합니다. 기존 대화의 충돌은 대화를 보존하고 새 상태를 확인하도록 안내합니다.", output: "조치 가능한 거절 상태", failures: [] },
    { id: "ended", label: "실패·취소·삭제 보존 경계", kind: "result", input: "실행 실패·취소 또는 삭제 요청", process: "실패 turn을 보존하며 재실행 조건을 확인합니다. 삭제는 다시 실행하지 못하도록 차단하고 원본 정리는 실제 writer 종료·참조 확인과 분리합니다.", output: "안전하게 제한된 종료 상태", failures: [] },
  ],
  edges: [
    { from: "open", to: "draft", condition: "새 대화·아직 첫 질문 없음" }, { from: "open", to: "restore", condition: "기존 세션 선택" },
    { from: "draft", to: "preflight", condition: "유효한 첫 질문 전송" }, { from: "preflight", to: "title", condition: "사전검사 통과" }, { from: "preflight", to: "rejected", condition: "접수 전 거절" },
    { from: "title", to: "accept", condition: "제목 준비" }, { from: "accept", to: "execute", condition: "원자 접수 완료" }, { from: "accept", to: "rejected", condition: "접수 트랜잭션 실패" },
    { from: "restore", to: "followup", condition: "허용된 기존 대화·후속 질문" }, { from: "restore", to: "ended", condition: "삭제 요청·접근 불가" },
    { from: "followup", to: "execute", condition: "revision·실행 제한 검사 통과" }, { from: "followup", to: "rejected", condition: "오래된 revision·동시 실행" },
    { from: "execute", to: "saved", condition: "완료·결과 저장" }, { from: "execute", to: "ended", condition: "실패·취소·중단" },
  ],
  links: [{ label: "RAG 대화", href: routes.workshopRagSearch, audience: "workspace" }, { label: "실행 모니터링", href: routes.adminRagExecutions, audience: "owner" }],
  sources: [{ title: "첫 질문·첨부 초안 계약", reference: "docs/decisions/0031-first-question-conversation-and-drafts.md" }, { title: "세션 서비스", reference: "backend/src/ai_workshop/labs/rag/conversations/service.py" }],
};
