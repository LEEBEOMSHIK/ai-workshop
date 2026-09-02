import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import type { SessionUser } from "../../platform/identity/session";
import type { SetupStatus } from "../../platform/identity/api";
import { ApiError } from "../api/client";
import { serverApiRequest } from "../api/server-client";
import { canAccessAdmin, unauthenticatedDestination } from "./access";

export type SessionApiRequest = (
  path: string,
  options?: Record<string, never>,
  cookieHeader?: string,
) => Promise<unknown>;

export type SessionDecision =
  | { kind: "authenticated"; user: SessionUser }
  | { kind: "redirect"; destination: string };

export async function resolveSession(
  cookieHeader: string,
  returnTo: string,
  request: SessionApiRequest = serverApiRequest,
): Promise<SessionDecision> {
  try {
    const user = (await request(
      "/api/v1/auth/me",
      {},
      cookieHeader,
    )) as SessionUser;
    return { kind: "authenticated", user };
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    const status = (await request(
      "/api/v1/setup/status",
      {},
      cookieHeader,
    )) as SetupStatus;
    return {
      kind: "redirect",
      destination: unauthenticatedDestination(status.setup_required, returnTo),
    };
  }
}

async function incomingCookieHeader(): Promise<string> {
  const store = await cookies();
  return store
    .getAll()
    .map(({ name, value }) => `${name}=${value}`)
    .join("; ");
}

export async function requireWorkspaceUser(returnTo: string): Promise<SessionUser> {
  const decision = await resolveSession(await incomingCookieHeader(), returnTo);
  if (decision.kind === "redirect") redirect(decision.destination);
  return decision.user;
}

export async function requireOwner(returnTo: string): Promise<SessionUser> {
  const user = await requireWorkspaceUser(returnTo);
  if (!canAccessAdmin(user)) redirect("/app/workspaces?error=owner_required");
  return user;
}
