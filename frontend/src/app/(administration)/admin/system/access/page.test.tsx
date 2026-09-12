import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { requireOwner } from "../../../../../shared/auth/server-session";
import { routes } from "../../../../../shared/routing/routes";
import AccessManagementRoute from "./page";

vi.mock("../../../../../shared/auth/server-session", () => ({
  requireOwner: vi.fn(),
}));
vi.mock("../../../../../features/identity/access/AccessManagementPage", () => ({
  AccessManagementPage: ({ currentUser }: { currentUser: { display_name: string } }) => (
    <p>권한 관리자: {currentUser.display_name}</p>
  ),
}));

beforeEach(() => vi.clearAllMocks());

it("uses the existing owner guard and hands the authenticated server user to the client page", async () => {
  vi.mocked(requireOwner).mockResolvedValue({
    id: "00000000-0000-4000-8000-000000000001",
    display_name: "서버 마스터",
    email: "master@example.test",
    role: "owner",
  });

  render(await AccessManagementRoute());

  expect(requireOwner).toHaveBeenCalledWith(routes.adminSystemAccess);
  expect(screen.getByText("권한 관리자: 서버 마스터")).toBeVisible();
});
