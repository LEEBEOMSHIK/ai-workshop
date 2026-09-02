import { headers } from "next/headers";
import { describe, expect, it, vi } from "vitest";

import { requireOwner } from "../../../shared/auth/server-session";
import AdminLayout from "./layout";

vi.mock("next/headers", () => ({ headers: vi.fn() }));
vi.mock("../../../shared/auth/server-session", () => ({
  requireOwner: vi.fn(),
}));

describe("AdminLayout", () => {
  it("preserves the requested admin URL for the authentication redirect", async () => {
    vi.mocked(headers).mockResolvedValue(
      new Headers({
        "x-ai-workshop-return-to": "/admin/rag/configurations?tab=evaluation",
      }) as Awaited<ReturnType<typeof headers>>,
    );
    vi.mocked(requireOwner).mockResolvedValue({
      id: "6806a6c1-04c4-4f2c-87d8-8cd1bf06e898",
      display_name: "Owner",
      email: "owner@example.com",
      role: "owner",
    });

    await AdminLayout({ children: <main>content</main> });

    expect(requireOwner).toHaveBeenCalledWith(
      "/admin/rag/configurations?tab=evaluation",
    );
  });
});
