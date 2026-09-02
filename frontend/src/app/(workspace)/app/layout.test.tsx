import { headers } from "next/headers";
import { describe, expect, it, vi } from "vitest";

import { requireWorkspaceUser } from "../../../shared/auth/server-session";
import WorkspaceLayout from "./layout";

vi.mock("next/headers", () => ({ headers: vi.fn() }));
vi.mock("../../../shared/auth/server-session", () => ({
  requireWorkspaceUser: vi.fn(),
}));

describe("WorkspaceLayout", () => {
  it("preserves the requested protected URL for the authentication redirect", async () => {
    vi.mocked(headers).mockResolvedValue(
      new Headers({
        "x-ai-workshop-return-to": "/app/rag/search?query=alpha",
      }) as Awaited<ReturnType<typeof headers>>,
    );
    vi.mocked(requireWorkspaceUser).mockResolvedValue({
      id: "6806a6c1-04c4-4f2c-87d8-8cd1bf06e898",
      display_name: "Owner",
      email: "owner@example.com",
      role: "owner",
    });

    await WorkspaceLayout({ children: <main>content</main> });

    expect(requireWorkspaceUser).toHaveBeenCalledWith(
      "/app/rag/search?query=alpha",
    );
  });
});
