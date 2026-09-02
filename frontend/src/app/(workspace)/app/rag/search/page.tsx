import { SearchPage } from "../../../../../features/rag/search/SearchPage";
import type {
  SavedConfiguration,
  SearchOptions,
  WorkspaceOption,
} from "../../../../../features/rag/search/api";
import { serverApiRequest } from "../../../../../shared/api/server-client";
import {
  incomingCookieHeader,
  requireWorkspaceUser,
} from "../../../../../shared/auth/server-session";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../../../shared/ui/ServerRouteFailure";

export default async function RagSearchRoute() {
  const result = await captureServerRoute(async () => {
    await requireWorkspaceUser("/app/rag/search");
    const cookieHeader = await incomingCookieHeader();
    return Promise.all([
      serverApiRequest<WorkspaceOption[]>("/api/v1/workspaces", {}, cookieHeader),
      serverApiRequest<SavedConfiguration[]>("/api/v1/rag/configurations", {}, cookieHeader),
    ]);
  });
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  const [workspaces, configurations] = result.value;
  const initialOptions: SearchOptions = { workspaces, configurations };
  return <SearchPage initialOptions={initialOptions} />;
}
