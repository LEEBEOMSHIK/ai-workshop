import { redirect } from "next/navigation";

import { LoginPage } from "../../../features/identity/LoginPage";
import type { SetupStatus } from "../../../features/identity/api";
import { serverApiRequest } from "../../../shared/api/server-client";
import { safeReturnPath } from "../../../shared/auth/access";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../shared/ui/ServerRouteFailure";

interface LoginRouteProps {
  searchParams: Promise<{ next?: string | string[] }>;
}

export default async function LoginRoute({ searchParams }: LoginRouteProps) {
  const result = await captureServerRoute(() =>
    serverApiRequest<SetupStatus>("/api/v1/setup/status"),
  );
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  const status = result.value;
  const query = await searchParams;
  const nextPath = safeReturnPath(
    typeof query.next === "string" ? query.next : null,
  );
  if (status.setup_required) {
    redirect(`/setup?next=${encodeURIComponent(nextPath)}`);
  }
  return <LoginPage nextPath={nextPath} />;
}
