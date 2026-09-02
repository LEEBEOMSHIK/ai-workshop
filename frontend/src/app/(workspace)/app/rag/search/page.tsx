import { SearchPage } from "../../../../../features/rag/search/SearchPage";
import type {
  SavedConfiguration,
  SearchOptions,
  WorkspaceOption,
} from "../../../../../features/rag/search/api";
import { serverApiRequest } from "../../../../../shared/api/server-client";
import { incomingCookieHeader } from "../../../../../shared/auth/server-session";

export default async function RagSearchRoute() {
  const cookieHeader = await incomingCookieHeader();
  const [workspaces, configurations] = await Promise.all([
    serverApiRequest<WorkspaceOption[]>("/api/v1/workspaces", {}, cookieHeader),
    serverApiRequest<SavedConfiguration[]>("/api/v1/rag/configurations", {}, cookieHeader),
  ]);
  const initialOptions: SearchOptions = { workspaces, configurations };
  return <SearchPage initialOptions={initialOptions} />;
}
