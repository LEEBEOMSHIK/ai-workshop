import { routes } from "../../shared/routing/routes";
export const rooms = { lobby: "중앙 로비", founder: "사장실", rag: "RAG 연구소", "preparing-hall": "준비 공간 연결 복도", finetuning: "파인튜닝 연구소", study: "AI 공부실", ontology: "온톨로지 연구소" } as const;
export interface OfficeNpc {
  id: "founder" | "rag-chief";
  name: string; room: keyof typeof rooms; role: string; eyebrow: string;
  asset: "founder" | "rag-chief";
  introduction: string; invitation: string;
  href?: string; linkLabel?: string;
  directions: readonly { recipient: string; subject: string; message: string }[];
}
export const npcCatalog: readonly OfficeNpc[] = [{
  id: "founder", name: "LEE BEOMSHIK", room: "founder", role: "Founder", asset: "founder",
  eyebrow: "FOUNDER / RESEARCH DIRECTION",
  introduction: "안녕하세요. AI Workshop을 만드는 LEE BEOMSHIK입니다. 이곳에서는 AI 기술을 직접 만들고, 근거를 확인하고, 배운 과정을 기록합니다.",
  invitation: "연구 조직에 전하는 방향을 소개할게요. 오른쪽 RAG 연구소에서는 각 담당자의 작업을 만나볼 수 있습니다.",
  directions: [
    { recipient: "RAG 총괄", subject: "답보다 먼저, 근거", message: "검색 결과가 정확한 원문으로 이어지는지 확인해 주세요. 근거의 정확성과 추적성을 연구의 중심에 둡니다." },
    { recipient: "문서 처리 담당", subject: "읽은 위치를 남기기", message: "OCR로 읽은 내용도 원본의 위치와 처리 과정을 추적할 수 있도록 살펴봐 주세요." },
    { recipient: "평가 담당", subject: "실패에서 다음 실험으로", message: "실패한 질문과 개선 결과를 함께 기록해 주세요. 비교할 수 있는 평가가 다음 연구 방향을 만듭니다." },
  ],
}, {
  id: "rag-chief", name: "RAG 총괄", room: "rag", role: "문서·검색·근거 품질 책임자", asset: "rag-chief",
  eyebrow: "RESEARCH LEAD / RAG",
  introduction: "반가워요. RAG 총괄입니다. 문서 처리부터 청킹, 색인, 검색, 근거 표시와 평가까지 여섯 담당자의 작업을 연결합니다.",
  invitation: "연구소 안에서 각 담당자가 맡은 일과 다음 단계로 넘기는 결과를 살펴보세요.",
  href: routes.ragLab, linkLabel: "RAG 연구소 들어가기", directions: [],
}];
