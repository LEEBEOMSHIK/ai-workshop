import {
  createBrowserRouter,
  redirect,
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
import { ApiError } from "../shared/api/client";
import { getCurrentUser, getSetupStatus } from "../features/identity/api";
import { LoginPage } from "../features/identity/LoginPage";
import { SetupPage } from "../features/identity/SetupPage";
import { listWorkspaces } from "../platform/workspaces/api";
import { WorkspacePageRoute } from "../platform/workspaces/WorkspacePage";
import { HomePage } from "../features/home/HomePage";

async function documentLoader({ params }: LoaderFunctionArgs) {
  if (!params.workspaceId) return [];
  return listDocuments(params.workspaceId);
}

async function requireSession({ request }: LoaderFunctionArgs) {
  try {
    return await getCurrentUser();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      const url = new URL(request.url);
      const returnTo = `${url.pathname}${url.search}`;
      const { setup_required: setupRequired } = await getSetupStatus();
      const destination = setupRequired ? "/setup" : "/login";
      throw redirect(`${destination}?next=${encodeURIComponent(returnTo)}`);
    }
    throw error;
  }
}

async function setupLoader() {
  const { setup_required: setupRequired } = await getSetupStatus();
  if (!setupRequired) throw redirect("/login");
  return null;
}

async function loginLoader() {
  const { setup_required: setupRequired } = await getSetupStatus();
  if (setupRequired) throw redirect("/setup");
  return null;
}

async function protectedDocumentLoader(args: LoaderFunctionArgs) {
  await requireSession(args);
  return documentLoader(args);
}

async function protectedWorkspaceLoader(args: LoaderFunctionArgs) {
  await requireSession(args);
  return listWorkspaces();
}

async function protectedConfigurationLoader(args: LoaderFunctionArgs) {
  await requireSession(args);
  return loadConfigurationStudio();
}

async function protectedModelLoader(args: LoaderFunctionArgs) {
  await requireSession(args);
  return loadModelLab();
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <HomePage />,
  },
  {
    path: "/login",
    element: <LoginPage />,
    loader: loginLoader,
  },
  {
    path: "/setup",
    element: <SetupPage />,
    loader: setupLoader,
  },
  {
    path: "/workspaces",
    element: <WorkspacePageRoute />,
    loader: protectedWorkspaceLoader,
  },
  {
    path: "/workspaces/:workspaceId/documents",
    element: <DocumentPage />,
    loader: protectedDocumentLoader,
  },
  {
    path: "/rag/configurations",
    element: <ConfigurationStudioRoute />,
    hydrateFallbackElement: <p role="status">RAG 구성 스튜디오를 불러오는 중…</p>,
    loader: protectedConfigurationLoader,
  },
  {
    path: "/rag/models",
    element: <ModelLabRoute />,
    loader: protectedModelLoader,
  },
  {
    path: "/rag/search",
    element: <SearchPage />,
    loader: requireSession,
  },
  {
    path: "/rag/sources/:assetVersionId",
    element: <SourceViewerRoute />,
    loader: requireSession,
  },
];

export const router = createBrowserRouter(routes);
