export interface DocumentSummary {
  id: string;
  name: string;
  latest_version: number;
  status: "stored" | "processing" | "ready" | "failed";
}

export async function listDocuments(workspaceId: string): Promise<DocumentSummary[]> {
  const response = await fetch(`/api/v1/workspaces/${workspaceId}/documents`, {
    credentials: "include",
  });
  if (!response.ok) throw new Error("문서 목록을 불러오지 못했습니다.");
  return (await response.json()) as DocumentSummary[];
}

export async function uploadDocument(
  workspaceId: string,
  file: File,
): Promise<DocumentSummary> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(`/api/v1/workspaces/${workspaceId}/documents`, {
    method: "POST",
    credentials: "include",
    body,
  });
  if (!response.ok) throw new Error("문서를 올리지 못했습니다.");
  return (await response.json()) as DocumentSummary;
}
