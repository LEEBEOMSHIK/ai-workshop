import { ragFlowPhases } from "./technical";
import { ragArchitectures } from "./architecture";
import type { FlowDefinition } from "../../flowcharts/types";
import { routes } from "../../../shared/routing/routes";

export const answerFlow: FlowDefinition = {
  id: "answer", categoryId: "rag", categoryLabel: "RAG", title: "검색·답변 생성",
  summary: "질문 문맥을 준비하고 허용된 원문을 다시 검색해, 근거와 인용을 검증한 답변을 만듭니다.",
  version: "3", reviewedAt: "2026-10-04", entryNodeId: "request",
  architecture: ragArchitectures.answer,
  phases: ragFlowPhases.answer,
  nodes: [
    { id: "request", label: "질문·연결·권한 확인", kind: "start", input: "질문, 선택 문서와 현재 연결", process: "접수 조건·연결 버전·문서 접근 권한·필요한 외부 전송 승인을 확인합니다.", output: "실행 가능한 질문과 문서 범위", failures: ["준비되지 않은 연결이나 허용되지 않은 자료는 실행 전에 거절합니다."] },
    { id: "history", label: "이전 대화 준비", kind: "decision", input: "앱 DB의 대화와 현재 범위", process: "현재 범위와 권한으로 유효한 과거 답변을 선별하고 생성 프로파일의 문맥 예산을 적용합니다.", output: "선별된 문맥 또는 빈 문맥", failures: ["화면의 모든 메시지를 그대로 모델에 보내지 않습니다."] },
    { id: "context", label: "질문 문맥화", kind: "action", input: "이번 질문과 선택된 이전 대화", process: "앞선 대화의 대상·의도를 반영해 검색할 질문을 구성합니다. 이전 대화가 없으면 이 단계를 생략합니다.", output: "문맥을 반영한 검색 질문", failures: ["구성한 모델의 실패 시 다른 모델로 조용히 전환하지 않습니다."] },
    { id: "retrieve", label: "권한 선필터·하이브리드 검색", kind: "action", input: "검색 질문과 활성 문서·색인", process: "검색 전에 권한·지식 공간 필터를 적용합니다. BM25와 bi-encoder dense 결과를 RRF로 병합합니다. BM25 단독 구성은 비교 기준으로 유지합니다.", output: "원문 위치를 추적할 수 있는 검색 후보", failures: ["검색한 뒤 비허용 결과를 숨기는 방식으로 권한을 대신하지 않습니다."] },
    { id: "rerank", label: "리랭킹 미적용 경계", kind: "action", input: "검색 후보와 검색 프로파일", process: "현재 검색 기준선은 리랭커를 실행하지 않고 RRF 후보를 근거 선택에 전달합니다. 리랭커는 후보를 다시 평가하는 선택 기술이지만 현재 구성 계약은 활성 binding을 허용하지 않습니다.", output: "재정렬 없이 전달하는 RRF 후보", failures: ["미설정은 오류가 아닙니다. 지원하지 않는 리랭커 구성을 정상 실행으로 표시하지 않습니다."] },
    { id: "selection", label: "답변 근거 선택", kind: "decision", input: "후보 청크, 유사도와 생성 예산", process: "현재 질문을 뒷받침하는 근거를 선택합니다. 검색 점수와 선택·제외 이유는 검색 진단에서 확인합니다.", output: "선택 근거 또는 근거 부족", failures: ["유사도 수치만으로 정답이나 인용 정확성을 보장하지 않습니다."] },
    { id: "generation", label: "근거 제한 답변 생성", kind: "action", input: "이번 질문·문맥·선택한 원문 근거", process: "구성한 모델이 허용된 근거로 답변을 만듭니다. 정상 모델 응답도 근거 내용이 부족하다고 판단하면 인용 검증을 생략하고 근거 부족으로 종료합니다. 과거 답변은 질문 이해를 돕는 문맥이며 이번 원문 근거를 대체하지 않습니다.", output: "인용 검증 전 답변 또는 모델이 판단한 근거 부족", failures: ["모델 오류·제한 시간 초과·취소를 구분해 기록합니다."] },
    { id: "citation", label: "인용 검증", kind: "decision", input: "생성 답변과 허용된 원문 근거", process: "각 주장에 인용이 있는지, 허용된 근거 ID와 projection·chunk 추적 정보가 있는지, 정규식으로 추출한 날짜·수치가 인용 근거에 포함되는지 검사합니다. 모든 문장의 의미적 참됨을 검증하는 기능은 아닙니다. 검증 실패한 초안을 정상 답변으로 노출하지 않습니다.", output: "현 검증 범위를 통과한 답변 또는 인용 실패", failures: [] },
    { id: "persist", label: "결과·실행 상태 저장", kind: "action", input: "검증된 답변 또는 진단 가능한 종료 상태", process: "대화 결과와 가능한 실행 관측 값을 저장합니다. 저장 자체 실패 등 모든 예외가 같은 경로를 반드시 완주하는 것은 아닙니다.", output: "저장된 상태와 실행 기록", failures: ["취소 이후 늦은 완료가 취소 상태를 덮어쓰지 않습니다."] },
    { id: "answered", label: "답변·근거 표시", kind: "result", input: "정상 답변과 인용", process: "답변과 근거·원문 링크를 표시합니다. 검색 진단에서 유사도·선택 이유를, 실행 모니터링에서 단계별 상태·시간을 확인합니다.", output: "사용자가 검증 가능한 답변", failures: [] },
    { id: "insufficient", label: "근거 부족", kind: "result", input: "선택 가능한 근거 없음 또는 모델 응답의 근거 내용 부족", process: "검색·근거 선택 단계와 모델 생성 이후의 근거 부족을 별도 종료 이유로 기록합니다. 모델이 근거 내용 부족을 반환한 경우 인용 검증은 생략합니다. 근거를 만들거나 이전 답변을 원문처럼 인용하지 않습니다.", output: "근거 부족 상태와 가능한 진단", failures: [] },
    { id: "failed", label: "거절·실패·취소", kind: "result", input: "사전검사 거절, 실행 오류 또는 취소", process: "안전한 오류 코드와 가능한 실패 관측을 남깁니다. 접수 전 거절은 대화 생성 후 실패와 다르며, 취소 상태와 실제 실행 종료도 구분합니다.", output: "실패 상태와 재시도·조치 안내", failures: [] },
  ],
  edges: [
    { from: "request", to: "history", condition: "실행 허용" }, { from: "request", to: "failed", condition: "권한·준비 사전검사 거절" },
    { from: "history", to: "context", condition: "포함할 이전 대화 있음" }, { from: "history", to: "retrieve", condition: "이전 대화 없음·문맥화 생략" },
    { from: "context", to: "retrieve", condition: "검색 질문 준비" }, { from: "context", to: "failed", condition: "문맥화 실패" },
    { from: "retrieve", to: "rerank", condition: "검색 후보 준비" }, { from: "retrieve", to: "failed", condition: "검색 실패" },
    { from: "rerank", to: "selection", condition: "현재 기준선에서 리랭킹 생략" },
    { from: "selection", to: "generation", condition: "사용할 근거 있음" }, { from: "selection", to: "insufficient", condition: "근거 부족·진단 저장" },
    { from: "generation", to: "citation", condition: "답변 생성 완료" }, { from: "generation", to: "failed", condition: "모델 실패·취소·종료 기록" },
    { from: "generation", to: "insufficient", condition: "모델 응답의 근거 부족" },
    { from: "citation", to: "persist", condition: "인용 검증 통과" }, { from: "citation", to: "failed", condition: "인용 실패·진단 저장" },
    { from: "persist", to: "answered", condition: "저장·최종 권한 확인 완료" }, { from: "persist", to: "failed", condition: "저장·최종 권한 확인 실패" },
  ],
  links: [{ label: "RAG 대화·검색 진단", href: routes.workshopRagSearch, audience: "workspace" }, { label: "실행 모니터링", href: routes.adminRagExecutions, audience: "owner" }],
  sources: [{ title: "RAG 검색·생성 설계", reference: "docs/labs/rag/design.md" }, { title: "검색 실행 코어", reference: "backend/src/ai_workshop/labs/rag/search/pipeline.py" }],
};
