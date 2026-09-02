import { ConfigurationStudioPage } from "../../../../../features/rag/configurations/ConfigurationStudioPage";
import type {
  ConfigurationStudioData,
  EvaluationRun,
  SavedConfiguration,
  Workspace,
} from "../../../../../features/rag/configurations/api";
import type {
  ModelDefinitionSummary,
  ProfileKind,
  ProfileSummary,
} from "../../../../../features/rag/models/api";
import { serverApiRequest } from "../../../../../shared/api/server-client";
import {
  incomingCookieHeader,
  requireOwner,
} from "../../../../../shared/auth/server-session";
import { routes } from "../../../../../shared/routing/routes";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../../../shared/ui/ServerRouteFailure";

const profileKinds: ProfileKind[] = ["indexing", "retrieval", "generation"];

export default async function RagConfigurationsRoute() {
  const result = await captureServerRoute(async () => {
    await requireOwner(routes.adminRagConfigurations);
    const cookieHeader = await incomingCookieHeader();
    return Promise.all([
      serverApiRequest<SavedConfiguration[]>("/api/v1/rag/configurations", {}, cookieHeader),
      serverApiRequest<ModelDefinitionSummary[]>("/api/v1/rag/models", {}, cookieHeader),
      serverApiRequest<Workspace[]>("/api/v1/workspaces", {}, cookieHeader),
      serverApiRequest<EvaluationRun[]>("/api/v1/rag/evaluation-runs?limit=20", {}, cookieHeader),
      ...profileKinds.map((kind) =>
        serverApiRequest<ProfileSummary[]>(`/api/v1/rag/profiles/${kind}`, {}, cookieHeader),
      ),
    ]);
  });
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  const [configurations, models, workspaces, runs, ...profileGroups] = result.value;
  const initialData: ConfigurationStudioData = {
    configurations,
    models,
    profiles: profileGroups.flat(),
    workspaces,
    runs,
  };
  return <ConfigurationStudioPage initialData={initialData} />;
}
