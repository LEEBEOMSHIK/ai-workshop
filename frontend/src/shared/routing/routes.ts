export const routes = {
  home: "/",
  labs: "/labs",
  ragLab: "/labs/rag",
  ragStudies: "/labs/rag/studies",
  login: "/login",
  setup: "/setup",
  workshopHome: "/workshop/workspaces",
  workshopRagSearch: "/workshop/rag/search",
  workshopLearning: "/workshop/learning",
  adminRagDomains: "/admin/rag/domains",
  adminRagConfigurations: "/admin/rag/configurations",
  adminRagModels: "/admin/rag/models",
  adminSystemRuntime: "/admin/system/runtime",
  adminSystemAccess: "/admin/system/access",
  adminSystemIssues: "/admin/system/issues",
  adminPublishing: "/admin/publishing",
} as const;

export function publicStudyPath(publicSlug: string): string {
  return `/studies/${encodeURIComponent(publicSlug)}`;
}

export function learningRecordPath(recordId: string): string {
  return `${routes.workshopLearning}/${encodeURIComponent(recordId)}`;
}

export interface DomainDocumentPair {
  workspaceId: string;
  documentId: string;
}

export interface DomainLibrarySelection {
  workspaceId?: string | null;
  folderId?: string | null;
  documentId?: string | null;
  versionId?: string | null;
}

export function ragDomainChatPath(slug: string, documents: DomainDocumentPair[] = []): string {
  const path = `/workshop/rag/domains/${encodeURIComponent(slug)}/chat`;
  if (documents.length === 0) return path;
  const query = new URLSearchParams();
  documents.forEach(({ workspaceId, documentId }) => query.append("selected", `${workspaceId}:${documentId}`));
  return `${path}?${query.toString()}`;
}

export function ragDomainFilesPath(slug: string, selection: DomainLibrarySelection = {}): string {
  const path = `/workshop/rag/domains/${encodeURIComponent(slug)}/files`;
  const query = new URLSearchParams();
  if (selection.workspaceId) query.set("workspace", selection.workspaceId);
  if (selection.folderId) query.set("folder", selection.folderId);
  if (selection.documentId) query.set("document", selection.documentId);
  if (selection.versionId) query.set("version", selection.versionId);
  const value = query.toString();
  return value ? `${path}?${value}` : path;
}

export function workspaceDocumentPath(workspaceId: string): string {
  return `/workshop/workspaces/${encodeURIComponent(workspaceId)}/documents`;
}

export function workspaceLibraryPath(workspaceId: string, selection: {
  folderId?: string | null;
  documentId?: string | null;
  versionId?: string | null;
}): string {
  const path = workspaceDocumentPath(workspaceId);
  const query = new URLSearchParams();
  if (selection.folderId) query.set("folder", selection.folderId);
  if (selection.documentId) query.set("document", selection.documentId);
  if (selection.versionId) query.set("version", selection.versionId);
  const value = query.toString();
  return value ? `${path}?${value}` : path;
}

export function ragSourcePath(assetVersionId: string): string {
  return `/workshop/rag/sources/${encodeURIComponent(assetVersionId)}`;
}

export function loginPath(nextPath: string): string {
  return `${routes.login}?next=${encodeURIComponent(nextPath)}`;
}
