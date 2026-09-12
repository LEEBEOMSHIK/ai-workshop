import { render, screen } from "@testing-library/react";
import { beforeEach, vi } from "vitest";

import { serverApiRequest } from "../../../../../../shared/api/server-client";
import { incomingCookieHeader, requireWorkspaceUser } from "../../../../../../shared/auth/server-session";
import DocumentsRoute from "./page";

vi.mock("../../../../../../shared/api/server-client", () => ({ serverApiRequest: vi.fn() }));
vi.mock("../../../../../../shared/auth/server-session", () => ({ incomingCookieHeader: vi.fn(), requireWorkspaceUser: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("../../../../../../features/assets/DocumentPage", () => ({
  DocumentPage: (props: { initialDocument: { id: string } | null; initialVersionId: string | null; initialLibrary: { folder: { id: string } | null }; initialRoot: { folder: null } }) => <div data-testid="document-page" data-document={props.initialDocument?.id} data-version={props.initialVersionId} data-folder={props.initialLibrary.folder?.id} data-root={String(props.initialRoot.folder)} />,
}));

const workspace = { id: "workspace-1", name: "제품 자료", kind: "company", expires_at: null } as const;
const exactDocument = { active_version_id: "version-2", folder_id: "folder-deep", id: "document-deep", job_id: null, latest_version: 3, latest_version_id: "version-3", name: "deep.md", status: "processing", workspace_id: "workspace-1" } as const;
const root = { ancestors: [], documents: [], folder: null, folders: [], next_document_cursor: null, next_folder_cursor: null, workspace };
const deep = { ...root, folder: { id: "folder-deep", name: "깊은 폴더", parent_id: null }, ancestors: [] };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "member", role: "member", display_name: "Synthetic", email: "member@example.test" });
  vi.mocked(incomingCookieHeader).mockResolvedValue("synthetic-session");
  vi.mocked(serverApiRequest).mockImplementation(async (path) => {
    if (path === "/api/v1/workspaces") return [workspace] as never;
    if (path.endsWith("/library/documents/document-deep")) return exactDocument as never;
    if (path.endsWith("/library?folder_id=folder-deep")) return deep as never;
    if (path.endsWith("/library")) return root as never;
    throw new Error(`Unexpected path: ${path}`);
  });
});

it("restores an exact document and historical version independently of the loaded document page", async () => {
  render(await DocumentsRoute({ params: Promise.resolve({ workspaceId: "workspace-1" }), searchParams: Promise.resolve({ document: "document-deep", version: "version-old" }) }));

  expect(requireWorkspaceUser).toHaveBeenCalledWith("/workshop/workspaces/workspace-1/documents");
  expect(screen.getByTestId("document-page")).toHaveAttribute("data-document", "document-deep");
  expect(screen.getByTestId("document-page")).toHaveAttribute("data-version", "version-old");
  expect(screen.getByTestId("document-page")).toHaveAttribute("data-folder", "folder-deep");
  expect(screen.getByTestId("document-page")).toHaveAttribute("data-root", "null");
  expect(serverApiRequest).toHaveBeenCalledWith("/api/v1/workspaces/workspace-1/library/documents/document-deep", {}, "synthetic-session");
});

it("uses the server-validated folder and rejects a contradictory folder/document query", async () => {
  render(await DocumentsRoute({ params: Promise.resolve({ workspaceId: "workspace-1" }), searchParams: Promise.resolve({ folder: "other-folder", document: "document-deep" }) }));

  expect(screen.getByRole("alert")).toHaveAttribute("data-upstream-status", "404");
  expect(screen.queryByTestId("document-page")).not.toBeInTheDocument();
});
