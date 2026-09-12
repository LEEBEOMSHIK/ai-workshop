import { ModelLabPage } from "../../../../../features/rag/models/ModelLabPage";
import type {
  ModelDefinitionSummary,
  ProfileSummary,
} from "../../../../../features/rag/models/api";
import { profileKinds } from "../../../../../features/rag/models/registryCatalog";
import { serverApiRequest } from "../../../../../shared/api/server-client";
import {
  incomingCookieHeader,
  requireOwner,
} from "../../../../../shared/auth/server-session";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../../../shared/ui/ServerRouteFailure";

export default async function RagModelsRoute() {
  const result = await captureServerRoute(async () => {
    await requireOwner("/admin/rag/models");
    const cookieHeader = await incomingCookieHeader();
    return Promise.all([
      serverApiRequest<ModelDefinitionSummary[]>("/api/v1/rag/models", {}, cookieHeader),
      ...profileKinds.map((kind) =>
        serverApiRequest<ProfileSummary[]>(`/api/v1/rag/profiles/${kind}`, {}, cookieHeader),
      ),
    ]);
  });
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  const [models, ...profileGroups] = result.value;
  return <ModelLabPage initialModels={models} initialProfiles={profileGroups.flat()} />;
}
