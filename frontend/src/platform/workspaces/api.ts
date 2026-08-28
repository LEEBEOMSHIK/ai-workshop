export type WorkspaceKind = "company" | "team" | "personal" | "temporary";

export interface WorkspaceSummary {
  id: string;
  name: string;
  kind: WorkspaceKind;
  expires_at: string | null;
}

export async function listWorkspaces(): Promise<WorkspaceSummary[]> {
  const response = await fetch("/api/v1/workspaces", { credentials: "include" });
  if (!response.ok) throw new Error("지식 공간을 불러오지 못했습니다.");
  return (await response.json()) as WorkspaceSummary[];
}
