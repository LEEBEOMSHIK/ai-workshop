import { redirect } from "next/navigation";

import { LoginPage } from "../../../features/identity/LoginPage";
import type { SetupStatus } from "../../../features/identity/api";
import { serverApiRequest } from "../../../shared/api/server-client";
import { safeReturnPath } from "../../../shared/auth/access";

interface LoginRouteProps {
  searchParams: Promise<{ next?: string | string[] }>;
}

export default async function LoginRoute({ searchParams }: LoginRouteProps) {
  const status = await serverApiRequest<SetupStatus>("/api/v1/setup/status");
  const query = await searchParams;
  const nextPath = safeReturnPath(
    typeof query.next === "string" ? query.next : null,
  );
  if (status.setup_required) {
    redirect(`/setup?next=${encodeURIComponent(nextPath)}`);
  }
  return <LoginPage nextPath={nextPath} />;
}
