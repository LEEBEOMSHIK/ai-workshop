import { redirect } from "next/navigation";

import { LoginPage } from "../../../features/identity/LoginPage";
import { safeReturnPath } from "../../../shared/auth/access";
import {
  incomingCookieHeader,
  resolveSession,
} from "../../../shared/auth/server-session";
import { routes } from "../../../shared/routing/routes";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../shared/ui/ServerRouteFailure";

interface LoginRouteProps {
  searchParams: Promise<{ next?: string | string[] }>;
}

export default async function LoginRoute({ searchParams }: LoginRouteProps) {
  const query = await searchParams;
  const nextPath = loginReturnPath(
    typeof query.next === "string" ? query.next : null,
  );
  const result = await captureServerRoute(async () =>
    resolveSession(await incomingCookieHeader(), nextPath),
  );
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  const decision = result.value;
  if (decision.kind === "authenticated") redirect(nextPath);
  if (decision.destination.startsWith(`${routes.setup}?`)) {
    redirect(decision.destination);
  }
  return <LoginPage nextPath={nextPath} />;
}

function loginReturnPath(candidate: string | null): string {
  const nextPath = safeReturnPath(candidate);
  try {
    const decoded = decodeURIComponent(nextPath);
    const pathname = new URL(
      safeReturnPath(decoded),
      "https://ai-workshop.local",
    ).pathname.replace(/\/+$/u, "");
    if (pathname === routes.login || pathname === routes.setup) {
      return routes.workshopHome;
    }
  } catch {
    return routes.workshopHome;
  }
  return nextPath;
}
