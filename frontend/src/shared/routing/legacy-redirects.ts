import { routes } from "./routes";

export interface LegacyRedirect {
  source: string;
  destination: string;
  permanent: true;
}

export const legacyRedirects: LegacyRedirect[] = [
  { source: "/app", destination: routes.workshopHome, permanent: true },
  { source: "/app/workspaces", destination: routes.workshopHome, permanent: true },
  {
    source: "/app/workspaces/:workspaceId/documents",
    destination: "/workshop/workspaces/:workspaceId/documents",
    permanent: true,
  },
  { source: "/app/rag/search", destination: routes.workshopRagSearch, permanent: true },
  {
    source: "/app/rag/configurations",
    destination: routes.adminRagConfigurations,
    permanent: true,
  },
  {
    source: "/app/rag/sources/:assetVersionId",
    destination: "/workshop/rag/sources/:assetVersionId",
    permanent: true,
  },
  { source: "/workspaces", destination: routes.workshopHome, permanent: true },
  {
    source: "/workspaces/:workspaceId/documents",
    destination: "/workshop/workspaces/:workspaceId/documents",
    permanent: true,
  },
  { source: "/rag/search", destination: routes.workshopRagSearch, permanent: true },
  {
    source: "/rag/configurations",
    destination: routes.adminRagConfigurations,
    permanent: true,
  },
  {
    source: "/rag/sources/:assetVersionId",
    destination: "/workshop/rag/sources/:assetVersionId",
    permanent: true,
  },
  { source: "/rag/models", destination: routes.adminRagModels, permanent: true },
];
