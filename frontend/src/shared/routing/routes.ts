export const routes = {
  home: "/",
  labs: "/labs",
  ragLab: "/labs/rag",
  login: "/login",
  setup: "/setup",
  workshopHome: "/workshop/workspaces",
  workshopRagSearch: "/workshop/rag/search",
  adminRagConfigurations: "/admin/rag/configurations",
  adminRagModels: "/admin/rag/models",
} as const;

export function workspaceDocumentPath(workspaceId: string): string {
  return `/workshop/workspaces/${encodeURIComponent(workspaceId)}/documents`;
}

export function ragSourcePath(assetVersionId: string): string {
  return `/workshop/rag/sources/${encodeURIComponent(assetVersionId)}`;
}

export function loginPath(nextPath: string): string {
  return `${routes.login}?next=${encodeURIComponent(nextPath)}`;
}
