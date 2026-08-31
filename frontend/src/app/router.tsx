import {
  createBrowserRouter,
  type LoaderFunctionArgs,
  type RouteObject,
} from "react-router-dom";

import { listDocuments } from "../platform/assets/api";
import { loadConfigurationStudio } from "../labs/rag/configurations/api";
import { ConfigurationStudioRoute } from "../labs/rag/configurations/ConfigurationStudioPage";
import { loadModelLab } from "../labs/rag/models/api";
import { ModelLabRoute } from "../labs/rag/models/ModelLabPage";
import { SearchPage } from "../labs/rag/search/SearchPage";
import { SourceViewerRoute } from "../labs/rag/search/SourceViewer";
import { DocumentPage } from "../platform/assets/DocumentPage";
import { LoginPage } from "../platform/identity/LoginPage";
import { WorkspacePage } from "../platform/workspaces/WorkspacePage";
import { App } from "./App";

async function documentLoader({ params }: LoaderFunctionArgs) {
  if (!params.workspaceId) return [];
  return listDocuments(params.workspaceId);
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <App />,
  },
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    path: "/workspaces",
    element: <WorkspacePage />,
  },
  {
    path: "/workspaces/:workspaceId/documents",
    element: <DocumentPage />,
    loader: documentLoader,
  },
  {
    path: "/rag/configurations",
    element: <ConfigurationStudioRoute />,
    hydrateFallbackElement: <p role="status">RAG 구성 스튜디오를 불러오는 중…</p>,
    loader: loadConfigurationStudio,
  },
  {
    path: "/rag/models",
    element: <ModelLabRoute />,
    loader: loadModelLab,
  },
  {
    path: "/rag/search",
    element: <SearchPage />,
  },
  {
    path: "/rag/sources/:assetVersionId",
    element: <SourceViewerRoute />,
  },
];

export const router = createBrowserRouter(routes);
