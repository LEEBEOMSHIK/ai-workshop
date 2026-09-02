import { routes } from "../routing/routes";

export function safeReturnPath(candidate: string | null): string {
  if (
    !candidate?.startsWith("/") ||
    candidate.startsWith("//") ||
    candidate.includes("\\") ||
    /[\u0000-\u001f\u007f]/u.test(candidate)
  ) {
    return routes.workshopHome;
  }
  const localOrigin = "https://ai-workshop.local";
  if (new URL(candidate, localOrigin).origin !== localOrigin) {
    return routes.workshopHome;
  }
  return candidate;
}

export function unauthenticatedDestination(
  setupRequired: boolean,
  returnTo: string,
): string {
  const entry = setupRequired ? routes.setup : routes.login;
  return `${entry}?next=${encodeURIComponent(safeReturnPath(returnTo))}`;
}

export function canAccessAdmin(user: { role: string }): boolean {
  return user.role === "owner";
}
