import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { serverApiRequest } from "../../../../../shared/api/server-client";
import { incomingCookieHeader, requireWorkspaceUser } from "../../../../../shared/auth/server-session";
import { routes } from "../../../../../shared/routing/routes";
import RagSearchRoute from "./page";

vi.mock("../../../../../shared/api/server-client", () => ({ serverApiRequest: vi.fn() }));
vi.mock("../../../../../shared/auth/server-session", () => ({ incomingCookieHeader: vi.fn(), requireWorkspaceUser: vi.fn() }));

describe("RagSearchRoute", () => {
  it("loads only the dynamic domain list and passes owner visibility", async () => {
    vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "owner-1", display_name: "Owner", email: "owner@example.com", role: "owner" });
    vi.mocked(incomingCookieHeader).mockResolvedValue("ai_workshop_session=token");
    vi.mocked(serverApiRequest).mockResolvedValue([]);

    render(await RagSearchRoute());

    expect(requireWorkspaceUser).toHaveBeenCalledWith(routes.workshopRagSearch);
    expect(serverApiRequest).toHaveBeenCalledTimes(1);
    expect(serverApiRequest).toHaveBeenCalledWith("/api/v1/rag/domains", {}, "ai_workshop_session=token");
    expect(screen.getByRole("link", { name: "도메인 관리" })).toBeVisible();
  });
});
