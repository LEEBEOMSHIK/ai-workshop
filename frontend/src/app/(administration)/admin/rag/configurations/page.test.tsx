import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ProfileSummary } from "../../../../../features/rag/models/api";
import { ConfigurationStudioPage } from "../../../../../features/rag/configurations/ConfigurationStudioPage";

import { serverApiRequest } from "../../../../../shared/api/server-client";
import { ApiError } from "../../../../../shared/api/client";
import { ServerRouteFailure } from "../../../../../shared/ui/ServerRouteFailure";
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
  beforeEach(() => vi.resetAllMocks());
  it("keeps processing lookup failure visible instead of handing an empty list to the studio", async () => {
    vi.mocked(incomingCookieHeader).mockResolvedValue("synthetic-session");
    vi.mocked(serverApiRequest).mockImplementation(async (path) => {
      if (path === "/api/v1/rag/profiles/document_processing") throw new ApiError("Synthetic failure", 503, "unavailable");
      return [];
    });
    const result = await RagConfigurationsRoute();
    expect(result.type).toBe(ServerRouteFailure);
    expect(result.props.failure).toEqual({ status: 503, code: "unavailable" });
  });
  it("does not read the cookie or load data when the owner guard rejects", async () => {
    const rejection = new Error("Synthetic owner rejection");
    vi.mocked(requireOwner).mockRejectedValue(rejection);
    await expect(RagConfigurationsRoute()).rejects.toBe(rejection);
    expect(incomingCookieHeader).not.toHaveBeenCalled();
    expect(serverApiRequest).not.toHaveBeenCalled();
  });
  it("passes returned document-processing profiles with the owner's synthetic session to the studio", async () => {
    const processing: ProfileSummary = {
      id: "synthetic-processing", kind: "document_processing", name: "Synthetic processing", version: 1,
      config: {}, bindings: [], deployment_version_id: null, legacy: false,
      readiness: { ready: true, reason_codes: [] }, evaluation_state: "pending", is_default: false,
    };
    vi.mocked(incomingCookieHeader).mockResolvedValue("synthetic-session");
    vi.mocked(serverApiRequest).mockImplementation(async (path) => path === "/api/v1/rag/profiles/document_processing" ? [processing] : []);
    const result = await RagConfigurationsRoute();
    expect(requireOwner).toHaveBeenCalledWith(routes.adminRagConfigurations);
    expect(vi.mocked(requireOwner).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(incomingCookieHeader).mock.invocationCallOrder[0]);
    expect(serverApiRequest).toHaveBeenCalledWith("/api/v1/rag/profiles/document_processing", {}, "synthetic-session");
    expect(result.type).toBe(ConfigurationStudioPage);
    expect(result.props.initialData.profiles).toEqual([processing]);
  });
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
