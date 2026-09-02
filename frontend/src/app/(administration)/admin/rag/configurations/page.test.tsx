import { describe, expect, it, vi } from "vitest";

import { serverApiRequest } from "../../../../../shared/api/server-client";
import {
  incomingCookieHeader,
  requireOwner,
} from "../../../../../shared/auth/server-session";
import { routes } from "../../../../../shared/routing/routes";
import RagConfigurationsRoute from "./page";

vi.mock("../../../../../features/rag/configurations/ConfigurationStudioPage", () => ({
  ConfigurationStudioPage: vi.fn(() => null),
}));
vi.mock("../../../../../shared/api/server-client", () => ({
  serverApiRequest: vi.fn(),
}));
vi.mock("../../../../../shared/auth/server-session", () => ({
  incomingCookieHeader: vi.fn(),
  requireOwner: vi.fn(),
}));

describe("RagConfigurationsRoute", () => {
  it("requires the owner and loads configuration data with the incoming session", async () => {
    vi.mocked(requireOwner).mockResolvedValue({
      id: "6806a6c1-04c4-4f2c-87d8-8cd1bf06e898",
      display_name: "Owner",
      email: "owner@example.com",
      role: "owner",
    });
    vi.mocked(incomingCookieHeader).mockResolvedValue(
      "ai_workshop_session=token",
    );
    vi.mocked(serverApiRequest).mockResolvedValue([]);

    await RagConfigurationsRoute();

    expect(requireOwner).toHaveBeenCalledWith(routes.adminRagConfigurations);
    expect(serverApiRequest).toHaveBeenCalledWith(
      "/api/v1/rag/configurations",
      {},
      "ai_workshop_session=token",
    );
  });
});
