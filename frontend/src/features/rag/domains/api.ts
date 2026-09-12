import { apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";
import type { SavedConfiguration, Workspace } from "../configurations/api";

export type Domain = components["schemas"]["DomainResponse"];
export type AdminDomain = components["schemas"]["AdminDomainResponse"];
export type DomainCreate = components["schemas"]["DomainCreateRequest"];
export type DomainUpdate = components["schemas"]["DomainUpdateRequest"];
export type DomainConnection = components["schemas"]["DomainConnectionVersionResponse"];
export type DomainConnectionCreate = components["schemas"]["DomainConnectionCreateRequest"];

export interface AdminDomainView {
  id: string;
  slug: string;
  displayName: string;
  description: string;
  activeConnectionVersionId: string | null;
}

export interface DomainAdminData {
  domains: Domain[];
  configurations: SavedConfiguration[];
  workspaces: Workspace[];
  histories: Record<string, DomainConnection[]>;
}

export function adminListDomainView(domain: Domain): AdminDomainView {
  return {
    id: domain.id,
    slug: domain.slug,
    displayName: domain.display_name,
    description: domain.description,
    activeConnectionVersionId: domain.active ? domain.connection_version?.id ?? null : null,
  };
}

export function adminMutationDomainView(domain: AdminDomain): AdminDomainView {
  return {
    id: domain.id,
    slug: domain.slug,
    displayName: domain.display_name,
    description: domain.description,
    activeConnectionVersionId: domain.active_connection_version_id,
  };
}

export function listDomains(signal?: AbortSignal): Promise<Domain[]> {
  return apiRequest<Domain[]>("/api/v1/rag/domains", { signal });
}

export function getDomain(slug: string, signal?: AbortSignal): Promise<Domain> {
  return apiRequest<Domain>(`/api/v1/rag/domains/${encodeURIComponent(slug)}`, { signal });
}

export function listAdminDomains(signal?: AbortSignal): Promise<Domain[]> {
  return apiRequest<Domain[]>("/api/v1/admin/rag/domains", { signal });
}

export function createDomain(request: DomainCreate): Promise<AdminDomain> {
  return apiRequest<AdminDomain>("/api/v1/admin/rag/domains", { method: "POST", json: request });
}

export function updateDomain(domainId: string, request: DomainUpdate): Promise<AdminDomain> {
  return apiRequest<AdminDomain>(`/api/v1/admin/rag/domains/${encodeURIComponent(domainId)}`, {
    method: "PATCH",
    json: request,
  });
}

export function listDomainConnections(domainId: string): Promise<DomainConnection[]> {
  return apiRequest<DomainConnection[]>(
    `/api/v1/admin/rag/domains/${encodeURIComponent(domainId)}/connections`,
  );
}

export async function createDomainConnection(
  domainId: string,
  request: DomainConnectionCreate,
): Promise<DomainConnection[]> {
  await apiRequest(
    `/api/v1/admin/rag/domains/${encodeURIComponent(domainId)}/connections`,
    { method: "POST", json: request },
  );
  return listDomainConnections(domainId);
}

export function activateDomainConnection(
  domainId: string,
  connectionId: string,
): Promise<AdminDomain> {
  return apiRequest<AdminDomain>(
    `/api/v1/admin/rag/domains/${encodeURIComponent(domainId)}/connections/${encodeURIComponent(connectionId)}/activate`,
    { method: "POST" },
  );
}

export function deactivateDomain(domainId: string): Promise<AdminDomain> {
  return apiRequest<AdminDomain>(
    `/api/v1/admin/rag/domains/${encodeURIComponent(domainId)}/deactivate`,
    { method: "POST" },
  );
}
