import { ModelLabPage } from "../../../../../features/rag/models/ModelLabPage";
import type {
  ModelDefinitionSummary,
  ProfileKind,
  ProfileSummary,
} from "../../../../../features/rag/models/api";
import { serverApiRequest } from "../../../../../shared/api/server-client";
import { incomingCookieHeader } from "../../../../../shared/auth/server-session";

const profileKinds: ProfileKind[] = ["indexing", "retrieval", "generation"];

export default async function RagModelsRoute() {
  const cookieHeader = await incomingCookieHeader();
  const [models, ...profileGroups] = await Promise.all([
    serverApiRequest<ModelDefinitionSummary[]>("/api/v1/rag/models", {}, cookieHeader),
    ...profileKinds.map((kind) =>
      serverApiRequest<ProfileSummary[]>(`/api/v1/rag/profiles/${kind}`, {}, cookieHeader),
    ),
  ]);
  return <ModelLabPage initialModels={models} initialProfiles={profileGroups.flat()} />;
}
