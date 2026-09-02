export function safeReturnPath(candidate: string | null): string {
  if (
    !candidate?.startsWith("/") ||
    candidate.startsWith("//") ||
    candidate.includes("\\") ||
    /[\u0000-\u001f\u007f]/u.test(candidate)
  ) {
    return "/app/workspaces";
  }
  const localOrigin = "https://ai-workshop.local";
  if (new URL(candidate, localOrigin).origin !== localOrigin) {
    return "/app/workspaces";
  }
  return candidate;
}

export function unauthenticatedDestination(
  setupRequired: boolean,
  returnTo: string,
): string {
  const entry = setupRequired ? "/setup" : "/login";
  return `${entry}?next=${encodeURIComponent(safeReturnPath(returnTo))}`;
}

export function canAccessAdmin(user: { role: string }): boolean {
  return user.role === "owner";
}
