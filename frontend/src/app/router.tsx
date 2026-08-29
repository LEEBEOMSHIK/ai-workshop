import {
  createBrowserRouter,
  type LoaderFunctionArgs,
  type RouteObject,
} from "react-router-dom";

import { listDocuments } from "../platform/assets/api";
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
];

export const router = createBrowserRouter(routes);
