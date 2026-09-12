import { render, screen } from "@testing-library/react";
import { beforeEach, vi } from "vitest";

import { serverApiRequest } from "../../../../../../../shared/api/server-client";
import { incomingCookieHeader, requireWorkspaceUser } from "../../../../../../../shared/auth/server-session";
import { ragDomainFilesPath } from "../../../../../../../shared/routing/routes";
import RagDomainFilesRoute from "./page";

vi.mock("../../../../../../../shared/api/server-client", () => ({ serverApiRequest: vi.fn() }));
vi.mock("../../../../../../../shared/auth/server-session", () => ({ incomingCookieHeader: vi.fn(), requireWorkspaceUser: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("../../../../../../../features/rag/domains/DomainFileCabinet", () => ({
  DomainFileCabinet: (props: { context: { display_name: string }; initialLibrary: { workspace: { id: string } }; initialDocument: { id: string } | null }) => <main data-testid="cabinet" data-workspace={props.initialLibrary.workspace.id} data-document={props.initialDocument?.id}>{props.context.display_name}</main>,
}));

const workspaceId = "11111111-1111-4111-8111-111111111111";
const documentId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const context = { domain_id: "domain-1", display_name: "자산운용", connection_version_id: "connection-1", selection_limit: 2, workspace_options: [{ id: workspaceId, name: "회사 규정", kind: "company", expires_at: null }] };
const document = { active_version_id: "version-1", folder_id: null, id: documentId, job_id: null, latest_version: 1, latest_version_id: "version-1", name: "운용 규정.md", status: "ready", workspace_id: workspaceId };
const root = { ancestors: [], documents: [document], folder: null, folders: [], next_document_cursor: null, next_folder_cursor: null, workspace: context.workspace_options[0] };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(incomingCookieHeader).mockResolvedValue("synthetic-session");
  vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "member", role: "member", display_name: "Synthetic", email: "member@example.test" });
  vi.mocked(serverApiRequest).mockImplementation(async (path) => {
    if (path.endsWith("/library")) return context as never;
    if (path.endsWith(`/workspaces/${workspaceId}/documents/${documentId}`)) return document as never;
    if (path.endsWith(`/workspaces/${workspaceId}`)) return root as never;
    throw new Error(`Unexpected path: ${path}`);
  });
});

it("loads the domain library context and exact authorized document without search readiness", async () => {
  render(await RagDomainFilesRoute({ params: Promise.resolve({ slug: "asset/manage" }), searchParams: Promise.resolve({ workspace: workspaceId, document: documentId }) }));

  expect(requireWorkspaceUser).toHaveBeenCalledWith(ragDomainFilesPath("asset/manage"));
  expect(serverApiRequest).toHaveBeenCalledWith("/api/v1/rag/domains/asset%2Fmanage/library", {}, "synthetic-session");
  expect(serverApiRequest).toHaveBeenCalledWith(`/api/v1/rag/domains/asset%2Fmanage/library/workspaces/${workspaceId}/documents/${documentId}`, {}, "synthetic-session");
  expect(screen.getByTestId("cabinet")).toHaveAttribute("data-document", documentId);
});

it("fails closed for a workspace outside the server-provided domain context", async () => {
  render(await RagDomainFilesRoute({ params: Promise.resolve({ slug: "asset-management" }), searchParams: Promise.resolve({ workspace: "22222222-2222-4222-8222-222222222222" }) }));

  expect(screen.getByRole("alert")).toBeVisible();
  expect(screen.queryByTestId("cabinet")).not.toBeInTheDocument();
  expect(vi.mocked(serverApiRequest).mock.calls.some(([path]) => path.includes("22222222-2222-4222-8222-222222222222"))).toBe(false);
});
