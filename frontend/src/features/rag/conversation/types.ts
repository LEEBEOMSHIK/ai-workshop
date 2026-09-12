import type { DomainSearchResult } from "./api";
import type { DocumentSummary } from "../../assets/api";

export type Selection = {
  documentIds: string[];
  documentNames: string[];
  documents: DocumentSummary[];
} | null;

export type ScopeMode = "workspace" | "folder" | "documents";

export interface ScopeSnapshot {
  workspaceIds: string[];
  workspaceNames: string[];
  folderIds: string[];
  folderNames: string[];
  documentIds: string[] | null;
  documentNames: string[];
  documents: DocumentSummary[];
}

export interface CompletedTurn {
  type: "answer";
  query: string;
  result: DomainSearchResult;
  scope: ScopeSnapshot;
}

export interface ScopeDivider {
  type: "scope-divider";
  key: number;
}

export type TranscriptItem = CompletedTurn | ScopeDivider;

export function scopeSummary(scope: ScopeSnapshot): string {
  if (scope.documentIds !== null) {
    return scope.documentNames.length > 0
      ? `선택 문서 ${scope.documentNames.join(", ")}`
      : "선택 문서 없음";
  }
  const workspaces = scope.workspaceNames.join(", ") || "선택 없음";
  const folders = scope.folderNames.length > 0 ? `폴더 ${scope.folderNames.join(", ")}` : "선택 공간 전체";
  return `${workspaces} · ${folders}`;
}


export function selectionFromDocuments(documents: DocumentSummary[]): NonNullable<Selection> {
  return {
    documentIds: documents.map((document) => document.id),
    documentNames: documents.map((document) => document.name),
    documents,
  };
}
