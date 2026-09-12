import type { ModelKind, ProfileKind } from "./api";

export const modelKinds = ["embedding", "reranker", "llm", "ocr_layout_detection", "ocr_text_detection", "ocr_text_recognition", "ocr_textline_orientation", "ocr_table_classification", "ocr_table_structure_wired", "ocr_table_structure", "ocr_table_cells_wired", "ocr_table_cells_wireless", "ocr_table_orientation"] as const satisfies readonly ModelKind[];

// User workflow order, shared by the server loader, client loader and registry UI.
export const profileKinds = ["document_processing", "indexing", "retrieval", "generation"] as const satisfies readonly ProfileKind[];
export const profileLabels: Record<ProfileKind, string> = {
  document_processing: "문서 처리 프로파일", indexing: "색인 프로파일",
  retrieval: "검색 프로파일", generation: "생성 프로파일",
};
