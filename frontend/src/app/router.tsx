import {
  createBrowserRouter,
  type LoaderFunctionArgs,
  type RouteObject,
} from "react-router-dom";

import { listDocuments } from "../platform/assets/api";
import { loadModelLab } from "../labs/rag/models/api";
import { ModelLabRoute } from "../labs/rag/models/ModelLabPage";
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
    path: "/rag/models",
    element: <ModelLabRoute />,
    loader: loadModelLab,
  },
];

export const router = createBrowserRouter(routes);
