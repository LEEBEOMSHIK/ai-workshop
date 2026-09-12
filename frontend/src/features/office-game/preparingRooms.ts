export const preparingRooms = [
  { id: "finetuning", name: "파인튜닝 연구소", purpose: "학습 데이터와 모델 조정 과정을 살펴보고, 파인튜닝 실험과 평가를 함께 연구할 공간입니다." },
  { id: "study", name: "AI 공부실", purpose: "책과 노트로 AI의 기초를 공부하고, 배운 내용과 질문을 함께 정리할 공간입니다." },
  { id: "ontology", name: "온톨로지 연구소", purpose: "개념과 개념 사이의 관계를 정리하고, 지식 구조와 연결을 연구할 공간입니다." },
] as const;
export type PreparingRoomId = typeof preparingRooms[number]["id"];
export const preparingStatus = "관리자 모집 중 · 기능 준비 중";
