import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { ApiError } from "../../../../../../../shared/api/client";
import { serverApiRequest } from "../../../../../../../shared/api/server-client";
import { incomingCookieHeader, requireWorkspaceUser } from "../../../../../../../shared/auth/server-session";
import { ragDomainChatPath } from "../../../../../../../shared/routing/routes";
import RagDomainChatRoute from "./page";

vi.mock("../../../../../../../features/rag/conversation/ConversationPage", () => ({ ConversationPage: ({ domain, initialSelection }: { domain: { display_name: string }; initialSelection?: { documentIds: string[]; documentNames: string[] } | null }) => <main data-testid="conversation" data-documents={initialSelection?.documentIds.join(",") ?? "unrestricted"} data-names={initialSelection?.documentNames.join(",") ?? ""}>{domain.display_name}</main> }));
vi.mock("../../../../../../../shared/api/server-client", () => ({ serverApiRequest: vi.fn() }));
vi.mock("../../../../../../../shared/auth/server-session", () => ({ incomingCookieHeader: vi.fn(), requireWorkspaceUser: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

describe("RagDomainChatRoute", () => {
  it("guards and loads the selected domain by encoded slug", async () => {
    vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "member-1", display_name: "Member", email: "member@example.com", role: "member" });
    vi.mocked(incomingCookieHeader).mockResolvedValue("ai_workshop_session=token");
    vi.mocked(serverApiRequest).mockResolvedValue({ display_name: "자산운용" });

    render(await RagDomainChatRoute({ params: Promise.resolve({ slug: "asset/manage" }), searchParams: Promise.resolve({}) }));

    expect(requireWorkspaceUser).toHaveBeenCalledWith(ragDomainChatPath("asset/manage"));
    expect(serverApiRequest).toHaveBeenCalledWith("/api/v1/rag/domains/asset%2Fmanage", {}, "ai_workshop_session=token");
    expect(screen.getByText("자산운용")).toBeVisible();
  });

  it("shows an explicit state for an unknown domain slug", async () => {
    vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "member-1", display_name: "Member", email: "member@example.com", role: "member" });
    vi.mocked(incomingCookieHeader).mockResolvedValue("ai_workshop_session=token");
    vi.mocked(serverApiRequest).mockRejectedValue(new ApiError("private detail", 404, "not_found"));

    render(await RagDomainChatRoute({ params: Promise.resolve({ slug: "unknown" }), searchParams: Promise.resolve({}) }));

    expect(screen.getByRole("heading", { name: "도메인을 찾을 수 없습니다" })).toBeVisible();
    expect(screen.queryByText("private detail")).not.toBeInTheDocument();
  });

  it("revalidates bounded UUID pairs and derives names only from authorized metadata", async () => {
    const workspaceId = "11111111-1111-4111-8111-111111111111";
    const documentId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "member-1", display_name: "Member", email: "member@example.com", role: "member" });
    vi.mocked(incomingCookieHeader).mockResolvedValue("ai_workshop_session=token");
    vi.mocked(serverApiRequest).mockImplementation(async (path) => {
      if (path === "/api/v1/rag/domains/asset-management") return { display_name: "자산운용", connection_version: { id: "connection-1", version: 1 } } as never;
      if (path.endsWith("/library")) return { connection_version_id: "connection-1", selection_limit: 3, workspace_options: [{ id: workspaceId, name: "회사 규정", kind: "company", expires_at: null }] } as never;
      if (path.endsWith(`/workspaces/${workspaceId}/documents/${documentId}`)) return { id: documentId, workspace_id: workspaceId, folder_id: "folder-1", name: "서버 문서명.md", active_version_id: "version-1", latest_version_id: "version-1", latest_version: 1, status: "ready", job_id: null } as never;
      throw new Error(`Unexpected path: ${path}`);
    });

    render(await RagDomainChatRoute({ params: Promise.resolve({ slug: "asset-management" }), searchParams: Promise.resolve({ selected: `${workspaceId}:${documentId}` }) }));

    expect(screen.getByTestId("conversation")).toHaveAttribute("data-documents", documentId);
    expect(screen.getByTestId("conversation")).toHaveAttribute("data-names", "서버 문서명.md");
    expect(serverApiRequest).toHaveBeenCalledWith(`/api/v1/rag/domains/asset-management/library/workspaces/${workspaceId}/documents/${documentId}`, {}, "ai_workshop_session=token");
  });

  it("fails closed for malformed selected pairs without widening to unrestricted chat", async () => {
    vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "member-1", display_name: "Member", email: "member@example.com", role: "member" });
    vi.mocked(incomingCookieHeader).mockResolvedValue("ai_workshop_session=token");
    vi.mocked(serverApiRequest).mockResolvedValue({ display_name: "자산운용" });

    render(await RagDomainChatRoute({ params: Promise.resolve({ slug: "asset-management" }), searchParams: Promise.resolve({ selected: "not-a-uuid:also-invalid" }) }));

    expect(screen.getByRole("alert")).toBeVisible();
    expect(screen.queryByTestId("conversation")).not.toBeInTheDocument();
  });

  it("fails closed when authorized metadata revalidation fails and never drops the requested restriction", async () => {
    const workspaceId = "11111111-1111-4111-8111-111111111111";
    const documentId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "member-1", display_name: "Member", email: "member@example.com", role: "member" });
    vi.mocked(incomingCookieHeader).mockResolvedValue("ai_workshop_session=token");
    vi.mocked(serverApiRequest).mockImplementation(async (path) => {
      if (path === "/api/v1/rag/domains/asset-management") return { display_name: "자산운용", connection_version: { id: "connection-1", version: 1 } } as never;
      if (path.endsWith("/library")) return { connection_version_id: "connection-1", selection_limit: 1, workspace_options: [{ id: workspaceId }] } as never;
      throw new ApiError("private metadata detail", 404, "library_document_not_found");
    });

    render(await RagDomainChatRoute({ params: Promise.resolve({ slug: "asset-management" }), searchParams: Promise.resolve({ selected: `${workspaceId}:${documentId}` }) }));

    expect(screen.getByRole("alert")).toHaveAttribute("data-error-code", "library_document_not_found");
    expect(screen.queryByTestId("conversation")).not.toBeInTheDocument();
    expect(screen.queryByText("private metadata detail")).not.toBeInTheDocument();
  });

  it("fails closed when the library context belongs to a different connection version", async () => {
    const workspaceId = "11111111-1111-4111-8111-111111111111";
    const documentId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "member-1", display_name: "Member", email: "member@example.com", role: "member" });
    vi.mocked(incomingCookieHeader).mockResolvedValue("ai_workshop_session=token");
    vi.mocked(serverApiRequest).mockImplementation(async (path) => {
      if (path === "/api/v1/rag/domains/asset-management") return { display_name: "자산운용", connection_version: { id: "connection-new", version: 3 } } as never;
      if (path.endsWith("/library")) return { connection_version_id: "connection-old", selection_limit: 1, workspace_options: [{ id: workspaceId }] } as never;
      throw new Error(`Selection metadata must not be requested from a stale connection: ${path}`);
    });

    render(await RagDomainChatRoute({ params: Promise.resolve({ slug: "asset-management" }), searchParams: Promise.resolve({ selected: `${workspaceId}:${documentId}` }) }));

    expect(screen.getByRole("alert")).toHaveAttribute("data-error-code", "invalid_document_selection");
    expect(screen.queryByTestId("conversation")).not.toBeInTheDocument();
  });
});
