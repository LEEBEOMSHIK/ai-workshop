import { vi } from "vitest";

import { serverApiRequest } from "../../../../../shared/api/server-client";
import { incomingCookieHeader, requireOwner } from "../../../../../shared/auth/server-session";
import { routes } from "../../../../../shared/routing/routes";
import RagDomainsAdminRoute from "./page";

vi.mock("../../../../../features/rag/domains/DomainAdminPage", () => ({ DomainAdminPage: vi.fn(() => null) }));
vi.mock("../../../../../shared/api/server-client", () => ({ serverApiRequest: vi.fn() }));
vi.mock("../../../../../shared/auth/server-session", () => ({ incomingCookieHeader: vi.fn(), requireOwner: vi.fn() }));

describe("RagDomainsAdminRoute", () => {
  it("loads domains, readable immutable histories, configurations and workspaces for an owner", async () => {
    vi.mocked(requireOwner).mockResolvedValue({ id: "owner-1", display_name: "Owner", email: "owner@example.com", role: "owner" });
    vi.mocked(incomingCookieHeader).mockResolvedValue("ai_workshop_session=token");
    vi.mocked(serverApiRequest).mockImplementation(async (path) => path === "/api/v1/admin/rag/domains" ? [{ id: "domain-1" }] : []);

    await RagDomainsAdminRoute();

    expect(requireOwner).toHaveBeenCalledWith(routes.adminRagDomains);
    expect(serverApiRequest).toHaveBeenCalledWith("/api/v1/admin/rag/domains/domain-1/connections", {}, "ai_workshop_session=token");
    expect(serverApiRequest).toHaveBeenCalledWith("/api/v1/rag/configurations", {}, "ai_workshop_session=token");
    expect(serverApiRequest).toHaveBeenCalledWith("/api/v1/workspaces", {}, "ai_workshop_session=token");
  });
});
