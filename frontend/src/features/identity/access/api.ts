import { apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";

export type Capability = components["schemas"]["Capability"];
export type TechnologyCatalog = components["schemas"]["TechnologyCatalogResponse"];
export type UserAuthority = components["schemas"]["UserAuthorityResponse"];
export type UserAuthorityPage = components["schemas"]["UserAuthorityPageResponse"];
export type AuthorityAudit = components["schemas"]["AuthorityAuditResponse"];
export type AuthorityAuditPage = components["schemas"]["AuthorityAuditPageResponse"];
export type UserRole = components["schemas"]["UserRole"];

const accessBase = "/api/v1/admin/access";
const pageSize = 50;

function pagePath(path: string, cursor?: string | number | null): string {
  const query = new URLSearchParams({ limit: String(pageSize) });
  if (cursor !== undefined && cursor !== null) query.set("cursor", String(cursor));
  return `${path}?${query.toString()}`;
}

export function listTechnologyCatalog(signal?: AbortSignal): Promise<TechnologyCatalog[]> {
  return apiRequest<TechnologyCatalog[]>(`${accessBase}/technologies`, { signal });
}

export function listAuthorityUsers(
  cursor?: string | null,
  signal?: AbortSignal,
): Promise<UserAuthorityPage> {
  return apiRequest<UserAuthorityPage>(pagePath(`${accessBase}/users`, cursor), { signal });
}

export function getUserAuthority(userId: string, signal?: AbortSignal): Promise<UserAuthority> {
  return apiRequest<UserAuthority>(`${accessBase}/users/${encodeURIComponent(userId)}`, { signal });
}

export function listAuthorityAudit(
  userId: string,
  cursor?: number | null,
  signal?: AbortSignal,
): Promise<AuthorityAuditPage> {
  return apiRequest<AuthorityAuditPage>(
    pagePath(`${accessBase}/users/${encodeURIComponent(userId)}/audit`, cursor),
    { signal },
  );
}

export function updateTechnologyGrant(
  userId: string,
  technologyKey: string,
  expectedRevision: number,
  capabilities: Capability[],
): Promise<UserAuthority> {
  return apiRequest<UserAuthority>(
    `${accessBase}/users/${encodeURIComponent(userId)}/technologies/${encodeURIComponent(technologyKey)}`,
    {
      method: "PUT",
      json: { expected_revision: expectedRevision, capabilities },
    },
  );
}

export function updateUserStatus(
  userId: string,
  expectedRevision: number,
  isActive: boolean,
): Promise<UserAuthority> {
  return apiRequest<UserAuthority>(
    `${accessBase}/users/${encodeURIComponent(userId)}/status`,
    {
      method: "PATCH",
      json: { expected_revision: expectedRevision, is_active: isActive },
    },
  );
}

export function updateUserRole(
  userId: string,
  expectedRevision: number,
  role: UserRole,
): Promise<UserAuthority> {
  return apiRequest<UserAuthority>(
    `${accessBase}/users/${encodeURIComponent(userId)}/role`,
    {
      method: "PATCH",
      json: { expected_revision: expectedRevision, role },
    },
  );
}
