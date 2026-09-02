export function safeReturnPath(candidate: string | null): string {
  if (!candidate?.startsWith("/") || candidate.startsWith("//")) {
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
