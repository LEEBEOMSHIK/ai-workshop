import {
  createBrowserRouter,
  redirect,
  useLoaderData,
  useParams,
  useSearchParams,
  type LoaderFunctionArgs,
  type RouteObject,
} from "react-router-dom";

import { listDocuments } from "../features/assets/api";
import { loadConfigurationStudio, type ConfigurationStudioData } from "../features/rag/configurations/api";
import { ConfigurationStudioPage } from "../features/rag/configurations/ConfigurationStudioPage";
import { loadModelLab, type ModelLabData } from "../features/rag/models/api";
import { ModelLabPage } from "../features/rag/models/ModelLabPage";
import { SearchPage } from "../features/rag/search/SearchPage";
import { SourceViewer } from "../features/rag/search/SourceViewer";
import { DocumentPage } from "../features/assets/DocumentPage";
import { ApiError } from "../shared/api/client";
import { getCurrentUser, getSetupStatus } from "../features/identity/api";
import { LoginPage } from "../features/identity/LoginPage";
import { SetupPage } from "../features/identity/SetupPage";
import { listWorkspaces } from "../features/workspaces/api";
import { WorkspacePage } from "../features/workspaces/WorkspacePage";
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

function LegacyConfigurationRoute() {
  return <ConfigurationStudioPage initialData={useLoaderData() as ConfigurationStudioData} />;
}

function LegacyModelRoute() {
  const data = useLoaderData() as ModelLabData;
  return <ModelLabPage initialModels={data.models} initialProfiles={data.profiles} />;
}

function LegacySourceRoute() {
  const { assetVersionId = "" } = useParams();
  const [query] = useSearchParams();
  const projectionId = query.get("projectionId") ?? "";
  return <SourceViewer assetVersionId={assetVersionId} projectionId={projectionId} highlights={[]} />;
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
    element: <WorkspacePage />,
    loader: protectedWorkspaceLoader,
  },
  {
    path: "/workspaces/:workspaceId/documents",
    element: <DocumentPage workspaceId="" initialDocuments={[]} />,
    loader: protectedDocumentLoader,
  },
  {
    path: "/rag/configurations",
    element: <LegacyConfigurationRoute />,
    hydrateFallbackElement: <p role="status">RAG 구성 스튜디오를 불러오는 중…</p>,
    loader: protectedConfigurationLoader,
  },
  {
    path: "/rag/models",
    element: <LegacyModelRoute />,
    loader: protectedModelLoader,
  },
  {
    path: "/rag/search",
    element: <SearchPage />,
    loader: requireSession,
  },
  {
    path: "/rag/sources/:assetVersionId",
    element: <LegacySourceRoute />,
    loader: requireSession,
  },
];

export const router = createBrowserRouter(routes);
