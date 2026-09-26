import { beforeEach, expect, it, vi } from "vitest";
import { SetupPage } from "../../../features/identity/SetupPage";
import { PublicNavigation } from "../../../features/navigation/PublicNavigation";
import { ApiError } from "../../../shared/api/client";
import { serverApiRequest } from "../../../shared/api/server-client";
import { ServerRouteFailure } from "../../../shared/ui/ServerRouteFailure";
import SetupRoute from "./page";

vi.mock("../../../shared/api/server-client", () => ({ serverApiRequest: vi.fn() }));
beforeEach(() => vi.clearAllMocks());

it("returns the setup component which owns its single public shell", async () => {
  vi.mocked(serverApiRequest).mockResolvedValue({ setup_required: true });
  expect((await SetupRoute()).type).toBe(SetupPage);
});

it("keeps public navigation on setup API failure", async () => {
  vi.mocked(serverApiRequest).mockRejectedValue(new ApiError("Unavailable", 503, "unavailable"));
  const result = await SetupRoute();
  expect(result.type).toBe(PublicNavigation);
  expect(result.props.children.type).toBe(ServerRouteFailure);
  expect(result.props.children.props.failure.status).toBe(503);
});
