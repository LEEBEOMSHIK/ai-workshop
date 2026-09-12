const topicLabels: Readonly<Record<string, string>> = {
  rag: "검색 증강 생성",
  retrieval: "검색",
  data: "데이터",
  ocr: "문자 인식",
  evidence: "근거",
  generation: "답변 생성",
  learning: "학습",
  evaluation: "평가",
  models: "모델",
  infrastructure: "인프라",
  security: "보안",
  interface: "인터페이스",
  configuration: "구성 관리",
  conversation: "대화",
};

export function publicTopicLabel(key: string): string {
  return Object.hasOwn(topicLabels, key) ? topicLabels[key] : key;
}
